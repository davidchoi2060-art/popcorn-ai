"""Authenticated administrative stored detail; no commerce writes or actions.

Register admin_commerce_no_store OUTSIDE the existing auth middleware so its
early 401/403 responses also receive the header. Router registration is external.
"""
import re
import base64
import json
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from .auth import current_operator
from . import commerce_contract as c
from . import commerce_writer as writer

router = APIRouter(prefix='/api/admin/commerce', tags=['admin-commerce'])
_PREFIX = '/api/admin/commerce/orders/'
_ORDER_NO = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,19}\Z')
_HEADERS = {'Cache-Control': 'no-store'}


class _AdminError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


def get_engine():
    from .db import engine
    return engine


def _principal():
    # Only the existing server ContextVar supplies this principal. Do not use
    # current_operator_id(): its historical missing-session fallback is 1.
    actor = current_operator()
    if actor is None:
        raise _AdminError(401, 'admin_authentication_required')
    if (type(actor) is not dict or type(actor.get('operator_id')) is not int
            or not 0 < actor['operator_id'] <= c.MAX_INTEGER
            or actor.get('role') not in ('viewer', 'operator', 'owner')
            or actor.get('status') != '활성'):
        raise _AdminError(403, 'admin_permission_required')
    return {key: actor[key] for key in ('operator_id', 'role', 'status')}


def _authorization(principal):
    """Create a server-owned callback; no request/grant data enters it."""
    def authorize(*, order_no, now):
        try:
            current = _principal()
        except _AdminError:
            c.fail('admin_authorization_required')
        if current != principal:
            c.fail('admin_authorization_required')
        return dict(auth_source='api.auth.current_operator', authenticated=True,
                    actor=current, permission='commerce.order.read', allowed=True,
                    order_no=order_no, checked_at=now)
    return authorize


def _clock(conn):
    value = conn.execute(text('''/*admin_commerce:clock*/
        SELECT floor(extract(epoch FROM clock_timestamp()))::bigint''')).scalar_one()
    return c.integer(value)


def _provider(binding):
    environment = 'unknown'
    if binding is not None:
        c.object_fields(binding, ('adapter_id', 'provider', 'environment', 'merchant_id', 'provider_order_id'))
        for key in ('adapter_id', 'provider', 'merchant_id', 'provider_order_id'):
            c.text(binding[key])
        environment = c.enum(binding['environment'], ('test', 'live'))
    # The reader verifies stored money proof but does not return a provider
    # observation timestamp. The GET clock cannot supply that missing fact.
    return dict(provider_environment=environment, verification_state='unknown', provider_checked_at=None)


def _stored_detail(engine, order_no, principal):
    authorize = _authorization(principal)
    with engine.connect() as conn:
        try:
            # SQLAlchemy autobegins one caller transaction; no successful read
            # commits it. PostgreSQL enforces business-read-only operation.
            conn.execute(text('/*admin_commerce:readonly*/ SET TRANSACTION READ ONLY'))
            now = _clock(conn)
            stored = writer.read_committed_admin_order(conn, order_no, now=now, authorize=authorize)
            checked_at = _clock(conn)
            permissions = {key: dict(allowed=False, reason='route_unavailable', expected_basis=None)
                           for key in c.ADMIN_ACTIONS}
            record = dict(row=stored['row'], basis=dict(state='unconfirmed', basis_id=None),
                          permissions=permissions,
                          balances=dict(approved=stored['approved'], refunded=stored['refunded']),
                          provider=_provider(stored['provider_binding']))
            # Public UUID is only this request's correlation scope, never a
            # customer owner context, persistent grant, session or credential.
            context = dict(state='confirmed', binding_id=str(uuid4()))
            return c.order_envelope([record], audience='admin', context=context,
                                    checked_at=checked_at, detail=True)
        finally:
            conn.rollback()


def _error(status, code):
    return JSONResponse({'detail': {'code': code}}, status_code=status, headers=_HEADERS)


@router.get('/orders/{order_no}')
async def read_order_detail(order_no: str, request: Request):
    try:
        principal = _principal()
        if (type(order_no) is not str or not _ORDER_NO.fullmatch(order_no)
                or request.query_params or await request.body()):
            raise _AdminError(422, 'invalid_order_request')
        payload = await run_in_threadpool(_stored_detail, get_engine(), order_no, principal)
        return JSONResponse(payload, headers=_HEADERS)
    except _AdminError as error:
        return _error(error.status, error.code)
    except c.CommerceError as error:
        if error.code == 'order_not_found':
            return _error(404, 'order_not_found')
        if error.code == 'admin_authorization_required':
            return _error(403, 'admin_permission_required')
        return _error(503, 'order_detail_unavailable')
    except Exception:
        # Infrastructure/proof/schema/rollback/close exceptions may contain
        # SQL, parameters and identities. Never serialize their messages.
        return _error(503, 'order_detail_unavailable')


async def admin_commerce_no_store(request: Request, call_next):
    """Narrow outer response header, including original auth gate denials."""
    collection = request.url.path == _PREFIX.rstrip('/')
    target = request.method == 'GET' and (collection or request.url.path.startswith(_PREFIX))
    try:
        response = await call_next(request)
    except Exception:
        if target:
            return _error(503, 'order_list_unavailable' if collection else 'order_detail_unavailable')
        raise
    if target:
        response.headers['Cache-Control'] = 'no-store'
    return response


_LIST_SCOPE = 'commerce.orders:id-desc'
_DECIMAL_ID = re.compile(r'[1-9][0-9]{0,18}\Z')


def _cursor_encode(upper_id, after_id):
    value = dict(v=1, scope=_LIST_SCOPE, upper_id=str(c.integer(upper_id, 1)),
                 after_id=str(c.integer(after_id, 1)))
    raw = json.dumps(value, sort_keys=True, separators=(',', ':')).encode('ascii')
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def _cursor_decode(value):
    # Canonical, bounded transport state; never a credential or SQL fragment.
    if (type(value) is not str or not 0 < len(value) <= 256
            or not re.fullmatch(r'[A-Za-z0-9_-]+', value)):
        raise _AdminError(422, 'invalid_order_request')
    try:
        raw = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
        cursor = json.loads(raw)
        c.object_fields(cursor, ('v', 'scope', 'upper_id', 'after_id'))
        if type(cursor['v']) is not int or cursor['v'] != 1 or cursor['scope'] != _LIST_SCOPE:
            raise ValueError('cursor scope')
        for key in ('upper_id', 'after_id'):
            if type(cursor[key]) is not str or not _DECIMAL_ID.fullmatch(cursor[key]):
                raise ValueError('cursor identifier')
        upper, after = c.integer(int(cursor['upper_id']), 1), c.integer(int(cursor['after_id']), 1)
        if after > upper or _cursor_encode(upper, after) != value:
            raise ValueError('cursor noncanonical')
        return upper, after
    except Exception:
        raise _AdminError(422, 'invalid_order_request') from None


def _list_authorization(principal):
    def authorize(*, scope, now):
        try:
            current = _principal()
        except _AdminError:
            c.fail('admin_authorization_required')
        if current != principal or scope != 'commerce.orders':
            c.fail('admin_authorization_required')
        return dict(auth_source='api.auth.current_operator', authenticated=True,
                    actor=current, permission='commerce.order.list', allowed=True,
                    scope=scope, checked_at=now)
    return authorize


def _stored_list(engine, principal, limit, upper_id, after_id):
    with engine.connect() as conn:
        try:
            conn.execute(text('/*admin_commerce:readonly*/ SET TRANSACTION READ ONLY'))
            now = _clock(conn)
            page = writer.read_committed_admin_orders(conn, now=now, limit=limit,
                upper_id=upper_id, after_id=after_id, authorize=_list_authorization(principal))
            checked_at = _clock(conn)
            records = [dict(row=stored['row'], basis=dict(state='unconfirmed', basis_id=None),
                permissions={key: dict(allowed=False, reason='route_unavailable', expected_basis=None)
                             for key in c.ADMIN_ACTIONS},
                balances=dict(approved=stored['approved'], refunded=stored['refunded']),
                provider=_provider(stored['provider_binding'])) for stored in page['records']]
            cursor = (_cursor_encode(page['upper_id'], page['after_id'])
                      if page['after_id'] is not None else None)
            context = dict(state='confirmed', binding_id=str(uuid4()))
            return c.order_envelope(records, audience='admin', context=context,
                                    checked_at=checked_at, next_cursor=cursor)
        finally:
            conn.rollback()


@router.get('/orders')
async def read_order_list(request: Request):
    try:
        principal = _principal()
        query = request.query_params
        pairs = list(query.multi_items())
        if (any(key not in ('limit', 'cursor') for key, _ in pairs)
                or len({key for key, _ in pairs}) != len(pairs) or await request.body()):
            raise _AdminError(422, 'invalid_order_request')
        value = query.get('limit', '20')
        if not re.fullmatch(r'[1-9][0-9]?', value) or not 1 <= int(value) <= 50:
            raise _AdminError(422, 'invalid_order_request')
        upper, after = _cursor_decode(query['cursor']) if 'cursor' in query else (None, None)
        payload = await run_in_threadpool(_stored_list, get_engine(), principal, int(value), upper, after)
        return JSONResponse(payload, headers=_HEADERS)
    except _AdminError as error:
        return _error(error.status, error.code)
    except c.CommerceError as error:
        if error.code == 'admin_authorization_required':
            return _error(403, 'admin_permission_required')
        return _error(503, 'order_list_unavailable')
    except Exception:
        return _error(503, 'order_list_unavailable')
