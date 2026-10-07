"""Thin commerce owner GET/POST; inactive without explicit secure configuration."""
import json
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from . import commerce_contract as c
from . import commerce_owner as owner

router = APIRouter(prefix='/api/commerce', tags=['commerce'])
_HEADERS = {'Cache-Control': 'no-store'}


def get_policy():
    # No legacy COOKIE_SECURE fallback and no implicit enable/expiry policy.
    return owner.OwnerPolicy.from_mapping({key: os.environ.get(key) for key in (
        'COMMERCE_OWNER_ENABLED', 'COMMERCE_OWNER_SECURE',
        'COMMERCE_OWNER_TTL_SECONDS', 'COMMERCE_OWNER_ORIGIN')})


def get_engine():
    from .db import engine
    return engine


def _error(error):
    return JSONResponse({'detail': {'code': error.code}}, status_code=error.status,
                        headers=_HEADERS)


def _secure_request(request, policy):
    if not isinstance(policy, owner.OwnerPolicy) or request.url.scheme != 'https':
        raise owner.OwnerError(503, 'owner_configuration_unready')


def _same_origin(request, policy):
    origins = request.headers.getlist('origin')
    sites = request.headers.getlist('sec-fetch-site')
    if (origins != [policy.origin] or (sites and sites != ['same-origin'])):
        raise owner.OwnerError(403, 'same_origin_required')
    if request.headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'application/json':
        raise owner.OwnerError(415, 'json_required')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


async def _post_binding(request):
    try:
        raw = await request.body()
        if len(raw) > 4096:
            raise ValueError()
        body = json.loads(raw, object_pairs_hook=_unique_object)
        if type(body) is not dict or set(body) != {'expected_binding_id'}:
            raise ValueError()
    except (ValueError, TypeError, UnicodeError):
        raise owner.OwnerError(422, 'invalid_owner_request') from None
    return owner.expected_binding(body['expected_binding_id'])


def _get_binding(request):
    values = request.query_params.getlist('expected_binding_id')
    if len(values) > 1:
        raise owner.OwnerError(422, 'invalid_expected_binding')
    return owner.expected_binding(values[0]) if values else None


def _read(engine, credential, expected):
    with engine.connect() as conn:
        try:
            owner.ensure_ready(conn)
            checked_at = owner.database_now(conn)
            context = owner.lookup_context(conn, credential, expected_binding_id=expected,
                                           now=checked_at)
            return context, checked_at
        finally:
            conn.rollback()


def _response(context, checked_at):
    public = context.public() if context else dict(state='unconfirmed', binding_id=None)
    # This endpoint confirms ownership only; it does not list or confirm orders.
    payload = c.order_envelope([], audience='customer', context=public, checked_at=checked_at)
    return JSONResponse(payload, headers=_HEADERS)


@router.get('/owner-context')
def read_owner_context(request: Request):
    try:
        policy = get_policy()
        _secure_request(request, policy)
        expected = _get_binding(request)
        context, checked_at = _read(get_engine(), request.cookies.get(owner.COOKIE), expected)
        return _response(context, checked_at)
    except owner.OwnerError as error:
        return _error(error)
    except Exception:
        # SQL/commit/adapter errors can contain parameters. Never expose them or
        # convert infrastructure failure into a successful unconfirmed result.
        return _error(owner.OwnerError(503, 'owner_context_unavailable'))


def _prepare(engine, credential, expected, policy):
    issued = None
    with engine.begin() as conn:
        owner.ensure_ready(conn)
        now = owner.database_now(conn)
        context = owner.lookup_context(conn, credential, expected_binding_id=expected, now=now)
        if context is None:
            context, issued = owner.create_guest(conn, policy, now=now)
        binding = context.context_id
    # __exit__ has committed successfully. Verify committed state on a new
    # read connection before exposing confirmation or issuing the cookie.
    context, checked_at = _read(engine, issued if issued is not None else credential, binding)
    if context is None:
        raise owner.OwnerError(503, 'owner_context_unavailable')
    response = _response(context, checked_at)
    if issued is not None:
        response.set_cookie(owner.COOKIE, issued, max_age=context.expires_at-checked_at,
                            httponly=True, secure=True, samesite='lax', path='/')
    return response


@router.post('/owner-context')
async def prepare_owner_context(request: Request):
    try:
        policy = get_policy()
        _secure_request(request, policy)
        _same_origin(request, policy)
        expected = await _post_binding(request)
        return await run_in_threadpool(_prepare, get_engine(), request.cookies.get(owner.COOKIE),
                                       expected, policy)
    except owner.OwnerError as error:
        return _error(error)
    except Exception:
        return _error(owner.OwnerError(503, 'owner_context_unavailable'))
