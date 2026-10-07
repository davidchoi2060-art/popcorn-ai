"""Unregistered support router. Register no-store OUTSIDE auth in integration.

Importing this module does not register middleware or start the full app.
"""
import json
import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from .auth import current_operator
from . import commerce_contract as c
from . import commerce_owner as owner
from . import commerce_owner_contexts as owner_http
from . import commerce_support_core as s
from . import commerce_support_writer as writer

router = APIRouter(tags=['commerce-support'])
HEADERS = {'Cache-Control': 'no-store'}
MAX_REQUEST_BYTES = 16384
_PATH = re.compile(r'/api/(?:admin/)?commerce/orders/[^/]+/support/?\Z')


async def commerce_support_no_store(request, call_next):
    response = await call_next(request)
    if _PATH.fullmatch(request.url.path):
        response.headers['Cache-Control'] = 'no-store'
    return response


def get_engine():
    from .db import engine
    return engine


def get_policy():
    return owner_http.get_policy()


def _error(status, code):
    return JSONResponse({'detail': {'code': code}}, status_code=status, headers=HEADERS)


def _clock(conn):
    return s.integer(conn.execute(text('/*commerce_support:clock*/ '
        'SELECT floor(extract(epoch FROM clock_timestamp()))::bigint')).scalar_one())


def _customer_authorize(conn, credential, expected):
    def authorize(*, order_no, action, now):
        owner.ensure_ready(conn)
        context = owner.lookup_context(conn, credential, expected_binding_id=expected, now=now)
        if context is None:
            raise owner.OwnerError(401, 'owner_context_lost')
        return dict(source='commerce_owner.lookup_context', audience='customer',
                    context=context, permission='commerce.support.' + action,
                    order_no=order_no, checked_at=now, allowed=True)
    return authorize


def _admin_authorize(initial):
    def authorize(*, order_no, action, now):
        principal = s.principal(current_operator(), write=action != 'read')
        if principal != initial:
            s.fail(403, 'support_authorization_changed')
        return dict(source='api.auth.current_operator', audience='admin', principal=principal,
                    permission='commerce.support.' + action, order_no=order_no,
                    checked_at=now, allowed=True)
    return authorize


def _authorize(conn, audience, credential, expected, principal):
    return (_customer_authorize(conn, credential, expected) if audience == 'customer'
            else _admin_authorize(principal))


def _read(engine, no, *, audience, credential, expected, principal, options,
          expected_command=None):
    with engine.connect() as conn:
        try:
            conn.execute(text('/*commerce_support:readonly*/ SET TRANSACTION READ ONLY'))
            now = _clock(conn)
            authorize = _authorize(conn, audience, credential, expected, principal)
            payload = writer.read(conn, no, audience=audience, now=now, authorize=authorize,
                                  expected_command=expected_command, **options)
            # Recheck current authorization/context after the final database clock.
            checked_at = _clock(conn)
            authorize(order_no=no, action='read', now=checked_at)
            payload['checked_at'] = checked_at
        finally:
            conn.rollback()
    # Return only after rollback and connection close both succeeded.
    return payload


def _write(engine, no, *, audience, credential, expected, principal, command):
    with engine.begin() as conn:
        now = _clock(conn)
        authorize = _authorize(conn, audience, credential, expected, principal)
        pending = writer.apply(conn, no, command, audience=audience, now=now, authorize=authorize)
        authorize(order_no=no, action=command['action'], now=_clock(conn))
    # Never confirm using the transaction which performed the INSERT/UPDATE.
    try:
        return _read(engine, no, audience=audience, credential=credential, expected=expected,
                     principal=principal, expected_command=command,
                     options=dict(operation_id=pending['operation_id'], request_hash=pending['request_hash']))
    except (owner.OwnerError, s.SupportError) as error:
        # Auth loss remains auth loss; absent proof after commit is unknown.
        if error.status in (401, 403) or error.code == 'owner_context_changed':
            raise
        s.fail(503, 'support_record_unconfirmed')


async def _bounded_body(request):
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_REQUEST_BYTES:
            s.fail(422, 'support_request_too_large')
        chunks.append(chunk)
    return b''.join(chunks)


def _query(request, audience, *, post=False):
    pairs = list(request.query_params.multi_items())
    if len({key for key, _ in pairs}) != len(pairs):
        s.fail(422, 'invalid_support_query')
    query = dict(pairs)
    expected = None
    if audience == 'customer':
        if 'expected_binding_id' not in query:
            s.fail(422, 'invalid_support_query')
        expected = owner.expected_binding(query.pop('expected_binding_id'))
        if expected is None:
            s.fail(422, 'invalid_support_query')
    allowed = set() if post else {'case_id', 'operation_id', 'request_hash', 'limit', 'cursor'}
    if not set(query) <= allowed:
        s.fail(422, 'invalid_support_query')
    if post:
        return expected, {}
    if 'case_id' in query and 'operation_id' in query:
        s.fail(422, 'invalid_support_mode')
    if 'operation_id' in query:
        if set(query) != {'operation_id', 'request_hash'}:
            s.fail(422, 'invalid_support_mode')
        c.basis_text(query['request_hash'])
        return expected, dict(operation_id=s.uuid(query['operation_id']), request_hash=query['request_hash'])
    if 'request_hash' in query:
        s.fail(422, 'invalid_support_mode')
    limit = query.get('limit', '20')
    if not re.fullmatch(r'[1-9][0-9]?', limit) or not 1 <= int(limit) <= 50:
        s.fail(422, 'invalid_support_limit')
    return expected, dict(case_id=s.uuid(query['case_id']) if 'case_id' in query else None,
                          limit=int(limit), cursor=query.get('cursor'))


async def _handle(request, no, audience, *, post):
    try:
        principal = s.principal(current_operator(), write=post) if audience == 'admin' else None
        policy = get_policy()
        owner_http._secure_request(request, policy)
        if post:
            owner_http._same_origin(request, policy)
        no = s.order_no(no)
        expected, options = _query(request, audience, post=post)
        credential = request.cookies.get(owner.COOKIE) if audience == 'customer' else None
        raw = await _bounded_body(request)
        if post:
            try:
                value = json.loads(raw, object_pairs_hook=owner_http._unique_object)
            except (ValueError, TypeError, UnicodeError):
                s.fail(422, 'invalid_support_json')
            command = s.command(value, audience)
            try:
                payload = await run_in_threadpool(_write, get_engine(), no, audience=audience,
                    credential=credential, expected=expected, principal=principal, command=command)
            except (owner.OwnerError, s.SupportError) as error:
                if error.status in (401, 403):
                    raise
                # Domain failures before commit retain 4xx; infrastructure is unknown.
                if error.status >= 500:
                    s.fail(503, 'support_record_unconfirmed')
                raise
        else:
            if raw:
                s.fail(422, 'invalid_support_query')
            payload = await run_in_threadpool(_read, get_engine(), no, audience=audience,
                credential=credential, expected=expected, principal=principal, options=options)
        return JSONResponse(payload, headers=HEADERS)
    except (owner.OwnerError, s.SupportError) as error:
        return _error(error.status, error.code)
    except c.CommerceError:
        return _error(422, 'invalid_support_request')
    except Exception:
        return _error(503, 'support_record_unconfirmed' if post else 'support_unavailable')


@router.get('/api/commerce/orders/{order_no}/support')
async def customer_read(order_no: str, request: Request):
    return await _handle(request, order_no, 'customer', post=False)


@router.post('/api/commerce/orders/{order_no}/support')
async def customer_write(order_no: str, request: Request):
    return await _handle(request, order_no, 'customer', post=True)


@router.get('/api/admin/commerce/orders/{order_no}/support')
async def admin_read(order_no: str, request: Request):
    return await _handle(request, order_no, 'admin', post=False)


@router.post('/api/admin/commerce/orders/{order_no}/support')
async def admin_write(order_no: str, request: Request):
    return await _handle(request, order_no, 'admin', post=True)
