"""Admin GET factory only. No POST, policy/observation producer or main registration.

The caller owns a read-only transaction and rolls it back before closing. Install
physical_return_no_store outside auth when this factory is separately registered.
Current and immutable-result DTOs preserve the frozen storage reader's version.
"""
from copy import deepcopy
import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from . import commerce_contract as c
from . import commerce_writer as money
from . import commerce_physical_return_read as reader

VERSION = reader.VERSION
HEADERS = {'Cache-Control': 'no-store'}
_PATH = re.compile(r'/api/admin/commerce/orders/[^/]+/physical-returns(?:/operations/[^/]+)?/?\Z')
ACTIONS = ('create_case', 'record_collection', 'record_receipt') + reader.core.ACTIONS
CURRENT = ('version', 'state', 'order_no', 'checked_at', 'order_revision', 'expected_order_basis',
           'expected_history_token', 'cases', 'actions')
RESULT = ('version', 'state', 'pending_commit', 'pending', 'order_no', 'operation_id', 'action',
          'return_id', 'order_revision', 'return_revision', 'lines')
LINE = ('return_line_id', 'shipment_id', 'line_id', 'claimed_qty', 'collected_qty', 'received_qty',
        'inspected_qty', 'resellable_qty', 'restoration_consumed_qty', 'restoration_remaining_qty', 'restoration_unresolved')
HISTORY = ('operation_id', 'action', 'actor_id', 'return_revision', 'order_revision', 'lines',
           'occurred_at', 'reference', 'evidence')


class HTTPError(c.CommerceError):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


def _fail(status, code):
    raise HTTPError(status, code)


def get_engine():
    from .db import engine
    return engine


def get_auth():
    from . import auth
    return auth


def _error(status, code):
    return JSONResponse({'detail': {'code': code}}, status_code=status, headers=HEADERS)


async def physical_return_no_store(request, call_next):
    target = bool(_PATH.fullmatch(request.url.path))
    try:
        response = await call_next(request)
    except Exception:
        if not target: raise
        return _error(503, 'physical_return_unavailable')
    if target: response.headers['Cache-Control'] = 'no-store'
    return response


def _clock(conn):
    return c.integer(conn.execute(text('/*physical_return_http:clock*/ '
        'SELECT floor(extract(epoch FROM clock_timestamp()))::bigint')).scalar_one())


def _principal(action='read'):
    actor = get_auth().current_operator()
    if actor is None: _fail(401, 'admin_authentication_required')
    if (type(actor) is not dict or type(actor.get('operator_id')) is not int
            or not 0 < actor['operator_id'] <= c.MAX_INTEGER or actor.get('status') != '활성'
            or actor.get('role') not in (('viewer', 'operator', 'owner') if action == 'read' else ('operator', 'owner'))):
        _fail(403, 'physical_return_permission_required')
    return {key: actor[key] for key in ('operator_id', 'role', 'status')}


def _session(conn, credential, principal, now):
    if type(credential) is not str or not credential or len(credential) > 256:
        _fail(401, 'admin_authentication_required')
    idle = c.integer(get_auth().IDLE_MINUTES, 1)
    rows = conn.execute(text('''/*physical_return_http:session*/ SELECT s.operator_id,o.role,o.status,
        (s.revoked_at IS NOT NULL) AS revoked,(s.expires_at<=to_timestamp(:now)) AS expired,
        (s.last_seen_at<=to_timestamp(:now)-:idle*interval '1 minute') AS idle
        FROM admin_sessions s JOIN admin_operators o USING(operator_id) WHERE s.session_id=:sid'''),
        dict(sid=credential, now=now, idle=idle)).mappings().all()
    if not rows: _fail(401, 'admin_authentication_required')
    if len(rows) != 1: _fail(503, 'physical_return_authorization_unready')
    row = dict(rows[0]); c.object_fields(row, ('operator_id', 'role', 'status', 'revoked', 'expired', 'idle'))
    c.integer(row['operator_id'], 1)
    if any(type(row[key]) is not bool for key in ('revoked', 'expired', 'idle')):
        _fail(503, 'physical_return_authorization_unready')
    if any(row[key] for key in ('revoked', 'expired', 'idle')): _fail(401, 'admin_authentication_required')
    if {key: row[key] for key in ('operator_id', 'role', 'status')} != principal:
        _fail(403, 'physical_return_authorization_changed')


def _authorize(conn, credential, principal):
    def authorize(*, order_no, action, return_id, now):
        try:
            if _principal(action) != principal: _fail(403, 'physical_return_authorization_changed')
            _session(conn, credential, principal, now)
            return dict(auth_source='api.auth.current_operator', authenticated=True, allowed=True, actor=deepcopy(principal),
                permission='commerce.return.' + action, order_no=order_no, return_id=return_id, action=action, checked_at=now)
        except HTTPError as error:
            # Frozen _atomic aborts/redacts non-domain failures. Keep exact denial.
            authorize.failure = error
            raise
    authorize.failure = None
    return authorize


def _array(value):
    if type(value) is not list: c.fail('physical_return_invalid_projection')
    return value


def _quantities(value):
    return reader.core._quantities(value)


def _nullable_evidence_time(value, reference, now):
    if value is None:
        if reference is not None: c.fail('physical_return_invalid_projection')
    else:
        if c.integer(value) > now: c.fail('physical_return_invalid_projection')
        c.text(reference)


def _current(value, no, now):
    c.object_fields(value, CURRENT)
    if value['version'] != VERSION or value['state'] != 'confirmed' or value['order_no'] != no or value['checked_at'] != now:
        c.fail('physical_return_invalid_projection')
    c.integer(value['checked_at']); c.integer(value['order_revision'], 1)
    c.basis_text(value['expected_order_basis']); c.basis_text(value['expected_history_token'])
    c.object_fields(value['actions'], reader.core.ACTIONS)
    for cap in value['actions'].values():
        c.object_fields(cap, ('allowed', 'reason'))
        if cap['allowed'] is not False or cap['reason'] != 'source_unconnected': c.fail('physical_return_invalid_projection')
    cases_seen = set(); lines_seen = set(); operations_seen = set()
    for case in _array(value['cases']):
        c.object_fields(case, ('return_id', 'revision', 'lines', 'history'))
        rid = c.integer(case['return_id'], 1); revision = c.integer(case['revision'], 1)
        if rid in cases_seen: c.fail('physical_return_invalid_projection')
        cases_seen.add(rid); own_lines = set()
        if not _array(case['lines']): c.fail('physical_return_invalid_projection')
        for line in case['lines']:
            c.object_fields(line, LINE); lid = c.integer(line['return_line_id'], 1)
            c.integer(line['shipment_id'], 1); c.text(line['line_id'])
            if lid in lines_seen: c.fail('physical_return_invalid_projection')
            lines_seen.add(lid); own_lines.add(lid)
            for key in ('claimed_qty', 'collected_qty', 'received_qty', 'inspected_qty', 'resellable_qty',
                        'restoration_consumed_qty', 'restoration_remaining_qty'):
                c.integer(line[key], 1 if key == 'claimed_qty' else 0, c.MAX_QUANTITY)
            if (not line['resellable_qty'] <= line['inspected_qty'] <= line['received_qty'] <= line['collected_qty'] <= line['claimed_qty']
                    or line['restoration_consumed_qty'] + line['restoration_remaining_qty'] != line['resellable_qty']
                    or type(line['restoration_unresolved']) is not bool): c.fail('physical_return_invalid_projection')
        revisions = []
        for entry in _array(case['history']):
            c.object_fields(entry, HISTORY); opid = c.uuid_text(entry['operation_id'])
            if opid in operations_seen: c.fail('physical_return_invalid_projection')
            operations_seen.add(opid); c.enum(entry['action'], ACTIONS); c.integer(entry['actor_id'], 1)
            revisions.append(c.integer(entry['return_revision'], 1)); c.integer(entry['order_revision'], 1)
            if entry['order_revision'] > value['order_revision']: c.fail('physical_return_invalid_projection')
            quantities = _quantities(entry['lines'])
            if quantities != entry['lines'] or any(line['return_line_id'] not in own_lines for line in quantities):
                c.fail('physical_return_invalid_projection')
            _nullable_evidence_time(entry['occurred_at'], entry['reference'], now)
            seen = set()
            for proof in _array(entry['evidence']):
                c.object_fields(proof, ('return_line_id', 'kind', 'actor_id', 'occurred_at', 'reference'))
                lid = c.integer(proof['return_line_id'], 1); c.enum(proof['kind'], ('collect', 'receive', 'inspect'))
                c.integer(proof['actor_id'], 1)
                if lid in seen or lid not in {line['return_line_id'] for line in quantities}: c.fail('physical_return_invalid_projection')
                seen.add(lid)
                if c.integer(proof['occurred_at']) > now: c.fail('physical_return_invalid_projection')
                c.text(proof['reference'])
        if revisions != list(range(1, revision + 1)): c.fail('physical_return_invalid_projection')
    return deepcopy(value)


def _result(value, no, operation_id, original, record, actor_id):
    c.object_fields(value, RESULT)
    c.object_fields(record, reader.OP)
    if (record['state'] != 'applied' or record['operation_id'] != operation_id
            or record['wire_intent'] != original or record['actor_id'] != actor_id):
        c.fail('return_result_unconfirmed')
    if (value['version'] != VERSION or value['state'] != 'confirmed' or value['order_no'] != no
            or value['operation_id'] != operation_id or value['action'] != original['action']
            or value['pending'] is not False or value['pending_commit'] is not False
            or (original['return_id'] is not None and value['return_id'] != original['return_id'])):
        c.fail('return_result_unconfirmed')
    c.uuid_text(value['operation_id']); c.enum(value['action'], ACTIONS); c.integer(value['return_id'], 1)
    c.integer(value['order_revision'], 1); c.integer(value['return_revision'], 1)
    if _quantities(value['lines']) != value['lines']: c.fail('return_result_unconfirmed')
    # create_case's wire return_id is null. Bind its assigned ID and all public
    # outcome fields to the stored original, never to current case quantities.
    if (value['return_id'] != record['return_id'] or type(record['result']) is not dict
            or any(value[key] != record['result'].get(key) for key in
                   ('action', 'return_id', 'order_revision', 'return_revision', 'lines'))):
        c.fail('return_result_unconfirmed')
    return deepcopy(value)


def _read(engine, no, credential, principal, operation_id=None):
    with engine.connect() as conn:
        authorize = None
        try:
            conn.execute(text('/*physical_return_http:readonly*/ SET TRANSACTION READ ONLY'))
            money._transaction(conn); txid = money._txid(conn); now = _clock(conn)
            authorize = _authorize(conn, credential, principal)
            authorize(order_no=no, action='read', return_id=None, now=now)
            if operation_id is None:
                payload = _current(reader.read_current(conn, no, authorize=authorize, now=now), no, now)
                action, rid = 'read', None
            else:
                # Scope/integrity before result authorization; no current-history replan.
                original = reader.load_request(conn, no, operation_id, authorize=authorize, now=now)
                record = reader._operation(conn, operation_id)
                payload = _result(reader.read_result(conn, no, operation_id, authorize=authorize, now=now),
                                  no, operation_id, original, record, principal['operator_id'])
                action, rid = original['action'], original['return_id']
            authorize(order_no=no, action=action, return_id=rid, now=_clock(conn))
            if money._txid(conn) != txid: c.fail('caller_transaction_changed')
        except Exception:
            if authorize is not None and authorize.failure is not None: raise authorize.failure
            raise
        finally:
            conn.rollback()
    # Close failure must not return a successful payload.
    return payload


async def _handle(request, no, operation_id=None):
    try:
        principal = _principal()
        if request.url.scheme != 'https': _fail(503, 'physical_return_secure_configuration_unready')
        if request.query_params.multi_items(): _fail(422, 'invalid_physical_return_query')
        if type(no) is not str or not reader.shipping_read.ORDER_NO.fullmatch(no): _fail(422, 'invalid_physical_return_order')
        if operation_id is not None:
            try: operation_id = c.uuid_text(operation_id)
            except c.CommerceError: _fail(422, 'invalid_physical_return_operation')
        async for chunk in request.stream():
            if chunk: _fail(422, 'physical_return_get_body_forbidden')
        if await request.is_disconnected(): _fail(503, 'physical_return_read_interrupted')
        payload = await run_in_threadpool(_read, get_engine(), no, request.cookies.get(get_auth().COOKIE), principal, operation_id)
        if _principal() != principal: _fail(403, 'physical_return_authorization_changed')
        if await request.is_disconnected(): _fail(503, 'physical_return_read_interrupted')
        return JSONResponse(payload, headers=HEADERS)
    except HTTPError as error:
        return _error(error.status, error.code)
    except c.CommerceError as error:
        if error.code in ('return_authorization_required', 'return_authorization_changed'):
            return _error(403, 'physical_return_permission_required')
        if error.code in ('order_not_found', 'return_operation_not_found'):
            return _error(404, 'physical_return_not_found')
        return _error(503, 'physical_return_result_unconfirmed' if operation_id else 'physical_return_unavailable')
    except Exception:
        return _error(503, 'physical_return_result_unconfirmed' if operation_id else 'physical_return_unavailable')


def create_router():
    router = APIRouter(tags=['commerce-physical-returns'])

    @router.get('/api/admin/commerce/orders/{order_no}/physical-returns')
    async def admin_current(order_no: str, request: Request):
        return await _handle(request, order_no)

    @router.get('/api/admin/commerce/orders/{order_no}/physical-returns/operations/{operation_id}')
    async def admin_result(order_no: str, operation_id: str, request: Request):
        return await _handle(request, order_no, operation_id)

    return router
