"""Explicit router factory only; importing this module cannot register routes.

Default origin/policy producers are unconnected. Install the supplied no-store
function OUTSIDE auth when separately integrating. No real grant/physical issuer.
"""
from copy import deepcopy
import json
import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from . import commerce_contract as c
from . import commerce_owner as owner
from . import commerce_owner_contexts as owner_http
from . import commerce_fulfillment_core as core
from . import commerce_fulfillment_writer as writer
from . import commerce_fulfillment_read as reader
from . import commerce_writer as money

HEADERS = {'Cache-Control': 'no-store'}
MAX_REQUEST_BYTES = 16384
_PATH = re.compile(r'/api/(?:admin/)?commerce/orders/[^/]+/fulfillment(?:/operations/[^/]+)?/?\Z')
_COMMON = ('operation_id', 'action', 'expected_order_basis', 'expected_order_revision',
           'expected_policy_basis', 'shipment_id', 'expected_shipment_revision', 'lines')


def get_engine():
    from .db import engine
    return engine


def get_auth():
    from . import auth
    return auth


def get_origin():
    # Explicit server origin producer must be connected by its owner; no Host/env fallback.
    return None


def get_policies(conn, *, order_no, action, now):
    # Synchronous SERVER resolver only, no caller transaction ownership.
    return None


def _error(status, code):
    return JSONResponse({'detail': {'code': code}}, status_code=status, headers=HEADERS)


async def fulfillment_no_store(request, call_next):
    target = bool(_PATH.fullmatch(request.url.path))
    try:
        response = await call_next(request)
    except Exception:
        if not target:
            raise
        return _error(503, 'fulfillment_unavailable')
    if target:
        response.headers['Cache-Control'] = 'no-store'
    return response


def _clock(conn):
    return c.integer(conn.execute(text('/*fulfillment_http:clock*/ '
        'SELECT floor(extract(epoch FROM clock_timestamp()))::bigint')).scalar_one())


def _principal(write=False):
    actor = get_auth().current_operator()
    if actor is None:
        reader.fail(401, 'admin_authentication_required')
    if (type(actor) is not dict or type(actor.get('operator_id')) is not int
            or not 0 < actor['operator_id'] <= c.MAX_INTEGER
            or actor.get('status') != '활성'
            or actor.get('role') not in (('operator', 'owner') if write else ('viewer', 'operator', 'owner'))):
        reader.fail(403, 'fulfillment_permission_required')
    return {key: actor[key] for key in ('operator_id', 'role', 'status')}


def _session(conn, credential, principal, now):
    if type(credential) is not str or not credential or len(credential) > 256:
        reader.fail(401, 'admin_authentication_required')
    idle = c.integer(get_auth().IDLE_MINUTES, 1)
    rows = conn.execute(text('''/*fulfillment_http:session*/ SELECT s.operator_id,o.role,o.status,
        (s.revoked_at IS NOT NULL) AS revoked,(s.expires_at<=to_timestamp(:now)) AS expired,
        (s.last_seen_at<=to_timestamp(:now)-:idle*interval '1 minute') AS idle
        FROM admin_sessions s JOIN admin_operators o USING(operator_id)
        WHERE s.session_id=:sid'''), dict(sid=credential, now=now, idle=idle)).mappings().all()
    if not rows:
        reader.fail(401, 'admin_authentication_required')
    if len(rows) != 1:
        reader.fail(503, 'fulfillment_authorization_unready')
    row = dict(rows[0])
    c.object_fields(row, ('operator_id', 'role', 'status', 'revoked', 'expired', 'idle'))
    c.integer(row['operator_id'], 1)
    if any(type(row[key]) is not bool for key in ('revoked', 'expired', 'idle')):
        reader.fail(503, 'fulfillment_authorization_unready')
    if any(row[key] for key in ('revoked', 'expired', 'idle')):
        reader.fail(401, 'admin_authentication_required')
    if {key: row[key] for key in ('operator_id', 'role', 'status')} != principal:
        reader.fail(403, 'fulfillment_authorization_changed')


def _admin_authorize(conn, credential, principal):
    def authorize(*, order_no, action, now):
        current = _principal(write=action != 'read')
        if current != principal:
            reader.fail(403, 'fulfillment_authorization_changed')
        _session(conn, credential, principal, now)
        permission = ('commerce.order.read' if action == 'read' else
                      writer.PERMISSIONS[action] if action in writer.PREPARATION else 'commerce.fulfillment.write')
        return dict(auth_source='api.auth.current_operator', authenticated=True, allowed=True,
                    actor=current, permission=permission, order_no=order_no, action=action, checked_at=now)
    return _capture_auth(authorize)


def _customer_authorize(conn, credential, expected):
    initial = None
    def authorize(*, order_no, action, now):
        nonlocal initial
        if action != 'read':
            reader.fail(403, 'fulfillment_permission_required')
        owner.ensure_ready(conn)
        context = owner.lookup_context(conn, credential, expected_binding_id=expected, now=now)
        if context is None:
            reader.fail(401, 'owner_context_lost')
        identity = (context.context_id, context.owner_scope, context.owner_identity)
        if initial is not None and identity != initial:
            reader.fail(409, 'owner_context_changed')
        initial = deepcopy(identity)
        return context
    return _capture_auth(authorize)


def _capture_auth(callback):
    # The frozen writer aborts then redacts non-domain exceptions. Preserve the
    # auth denial for the HTTP caller after its transaction has unwound.
    def authorize(**kwargs):
        try:
            return callback(**kwargs)
        except (reader.HTTPError, owner.OwnerError) as error:
            authorize.failure = error
            raise
    authorize.failure = None
    return authorize


def command(value):
    c.object_fields(value, _COMMON, ('expected_order_state', 'event_kind', 'quantities',
        'outcome', 'prerequisites', 'observation', 'carrier', 'tracking_no'))
    action = c.enum(value['action'], reader.ACTIONS)
    extra = (('expected_order_state',) if action in writer.PREPARATION else ())
    if action == 'record_preparation_event':
        extra += ('event_kind', 'quantities', 'outcome', 'observation')
    elif action == 'confirm_dispatch_ready':
        extra += ('prerequisites', 'observation')
    elif action in core.ACTIONS:
        extra += ('carrier', 'tracking_no', 'observation')
    c.object_fields(value, _COMMON + extra)
    result = deepcopy(value)
    result['operation_id'] = c.uuid_text(value['operation_id'])
    c.integer(value['expected_order_revision'], 1)
    for key in ('expected_order_basis', 'expected_policy_basis'):
        c.basis_text(value[key])
    if action == 'prepare_shipment':
        if value['shipment_id'] is not None or value['expected_shipment_revision'] is not None:
            c.fail('unexpected_preparation_field')
    else:
        c.integer(value['shipment_id'], 1); c.integer(value['expected_shipment_revision'], 1)
    if action in writer.PREPARATION:
        c.enum(value['expected_order_state'], c.ORDER_STATES)
    if type(value['lines']) is not list or not value['lines'] or len(value['lines']) > 100:
        c.fail('shipment_lines_required')
    seen = set()
    for line in value['lines']:
        c.object_fields(line, ('line_id', 'qty')); c.text(line['line_id'])
        c.integer(line['qty'], 1, c.MAX_QUANTITY)
        if line['line_id'] in seen:
            c.fail('duplicate_shipment_line')
        seen.add(line['line_id'])
    result['lines'] = sorted(result['lines'], key=lambda line: line['line_id'])
    if action == 'record_preparation_event':
        c.enum(value['event_kind'], writer.EVENTS)
        c.enum(value['outcome'], ('accepted', 'rejected') if value['event_kind'] == 'inspection_recorded' else ('recorded',))
        if type(value['quantities']) is not list or len(value['quantities']) != len(seen):
            c.fail('preparation_line_scope_mismatch')
        metrics = set()
        for metric in value['quantities']:
            c.object_fields(metric, ('line_id', 'observed_qty')); c.text(metric['line_id'])
            c.integer(metric['observed_qty'], 1, c.MAX_QUANTITY)
            if metric['line_id'] in metrics:
                c.fail('duplicate_preparation_line')
            metrics.add(metric['line_id'])
        if metrics != seen:
            c.fail('preparation_line_scope_mismatch')
        result['quantities'] = sorted(result['quantities'], key=lambda item: item['line_id'])
    if action == 'confirm_dispatch_ready':
        result['prerequisites'] = writer._refs(value['prerequisites'])
    if action in core.ACTIONS:
        c.text(value['carrier']); c.text(value['tracking_no'])
    if action != 'prepare_shipment':
        c.object_fields(value['observation'], ('occurred_at', 'reference'))
        c.integer(value['observation']['occurred_at']); c.text(value['observation']['reference'])
    return result


def intent(request):
    """All editable HTTP fields, deterministically derived from the saved request."""
    value = {key: deepcopy(request[key]) for key in _COMMON}
    value['lines'] = [{key: line[key] for key in ('line_id', 'qty')} for line in request['lines']]
    action = request['action']
    if action in writer.PREPARATION:
        value['expected_order_state'] = request['expected_order_state']
    if action == 'record_preparation_event':
        value.update({key: deepcopy(request[key]) for key in ('event_kind', 'quantities', 'outcome')})
    if action == 'confirm_dispatch_ready':
        value['prerequisites'] = deepcopy(request['prerequisites'])
    if action in core.ACTIONS:
        value.update({key: request[key] for key in ('carrier', 'tracking_no')})
    if action != 'prepare_shipment':
        value['observation'] = {key: request['evidence'][key] for key in ('occurred_at', 'reference')}
    return command(value)


def _new_request(conn, no, cmd, principal, now):
    policies = get_policies(conn, order_no=no, action=cmd['action'], now=now)
    if policies is None:
        reader.fail(503, 'fulfillment_source_unconnected')
    c.object_fields(policies, ('preparation', 'fulfillment'))
    preparation = cmd['action'] in writer.PREPARATION
    if preparation or cmd['action'] == 'handoff':
        writer._policy(policies['preparation'], dict(cmd, order_no=no), compare=preparation)
    if not preparation and type(policies['fulfillment']) is not dict:
        reader.fail(503, 'fulfillment_source_unconnected')
    row = money._order(conn, no)
    movements = conn.execute(text('''/*fulfillment_http:sources*/ SELECT m.movement_id,m.product_code,
        m.qty_delta,m.commerce_operation_id::text AS operation_id,m.commerce_effect_key AS effect_key
        FROM stock_movements m JOIN commerce_payment_operations x ON x.operation_id=m.commerce_operation_id
        WHERE m.ref_kind='order' AND m.ref_id=:oid AND m.movement_type='own_sale'
          AND x.order_id=:oid AND x.kind='approve' AND x.state='confirmed'
        ORDER BY m.movement_id'''), dict(oid=row['order_id'])).mappings().all()
    originals = {line['line_id']: line for line in row['snapshot']['lines']}
    lines = []
    for line in cmd['lines']:
        original = originals.get(line['line_id'])
        candidates = [m for m in movements if original is not None and
            m['effect_key'] == str(m['operation_id']) + ':allocate:' + line['line_id'] and
            m['product_code'] == original['product_code'] and -m['qty_delta'] == original['qty']]
        if len(candidates) != 1:
            reader.fail(409, 'original_sale_unconfirmed')
        movement = candidates[0]
        c.integer(movement['movement_id'], 1); c.integer(movement['product_code'], 1)
        c.integer(movement['qty_delta'], -c.MAX_QUANTITY, -1); c.uuid_text(str(movement['operation_id']))
        lines.append(dict(line, product_code=movement['product_code'], sale_movement_id=movement['movement_id']))
    req = {key: deepcopy(cmd[key]) for key in _COMMON}
    req.update(order_no=no, actor_id=principal['operator_id'], lines=core._lines(lines))
    if preparation:
        req.update(contract=writer.VERSION, expected_order_state=cmd['expected_order_state'],
                   event_kind=cmd.get('event_kind'), quantities=cmd.get('quantities'),
                   outcome=cmd.get('outcome'), prerequisites=cmd.get('prerequisites', []), evidence=None)
    else:
        req.update(carrier=cmd['carrier'], tracking_no=cmd['tracking_no'])
    if cmd['action'] != 'prepare_shipment':
        if cmd['observation']['occurred_at'] > now:
            reader.fail(422, 'fulfillment_observation_in_future')
        proof = dict(source='operator_record', kind=cmd.get('event_kind', 'dispatch_ready') if preparation else cmd['action'],
                     order_no=no, shipment_id=cmd['shipment_id'], actor_id=principal['operator_id'],
                     **deepcopy(cmd['observation']))
        if preparation:
            proof.update(contract=writer.EVIDENCE_VERSION, state='confirmed', rules_basis=policies['preparation']['rule_basis'],
                content_basis=c.fingerprint(dict(lines=req['lines'], event_kind=req['event_kind'],
                    quantities=req['quantities'], outcome=req['outcome'], prerequisites=req['prerequisites'],
                    policy_basis=req['expected_policy_basis'], rule_basis=policies['preparation']['rule_basis'])))
        else:
            proof['content_basis'] = core._cargo(no, req['shipment_id'], req['lines'], req['carrier'], req['tracking_no'])
        proof['basis'] = c.fingerprint(proof); req['evidence'] = proof
    req['request_basis'] = c.fingerprint(req)
    return writer._normalize(req, now, preparation), policies


def _result_payload(request, stored, checked_at):
    if stored['pending_commit'] or stored['public']['pending']:
        reader.fail(503, 'physical_result_unconfirmed')
    result = stored['result']
    return dict(version=reader.VERSION, state='confirmed', checked_at=checked_at,
                operation_id=request['operation_id'], request_basis=request['request_basis'],
                order_no=request['order_no'], action=request['action'],
                **{key: result[key] for key in ('shipment_id', 'order_revision', 'shipment_revision',
                                               'order_state', 'shipment_state', 'ready')})


def _read(engine, no, *, audience, credential, expected=None, principal=None, operation_id=None, original=None):
    with engine.connect() as conn:
        try:
            conn.execute(text('/*fulfillment_http:readonly*/ SET TRANSACTION READ ONLY'))
            money._transaction(conn); txid = money._txid(conn)
            now = _clock(conn)
            authorize = (_customer_authorize(conn, credential, expected) if audience == 'customer'
                         else _admin_authorize(conn, credential, principal))
            if operation_id is None:
                payload = reader.read_current(conn, no, audience=audience, authorize=authorize, now=now)
                final_action = 'read'
            else:
                request = reader.load_request(conn, no, operation_id, authorize=authorize, now=now)
                if original is not None and request != original:
                    reader.fail(409, 'physical_operation_conflict')
                stored = writer.read_result(conn, request, authorize=authorize, now=now,
                                            preparation=request.get('contract') == writer.VERSION)
                payload = _result_payload(request, stored, now); final_action = request['action']
            checked_at = _clock(conn)
            final_grant = authorize(order_no=no, action=final_action, now=checked_at)
            if audience == 'customer':
                reader.scope(conn, no, final_grant)
            if money._txid(conn) != txid:
                c.fail('caller_transaction_changed')
            payload['checked_at'] = checked_at
        except Exception:
            if 'authorize' in locals() and authorize.failure is not None:
                raise authorize.failure
            raise
        finally:
            conn.rollback()
    return payload


def _write(engine, no, cmd, credential, principal):
    try:
        with engine.begin() as conn:
            money._transaction(conn); txid = money._txid(conn)
            now = _clock(conn); authorize = _admin_authorize(conn, credential, principal)
            authorize(order_no=no, action=cmd['action'], now=now)
            request = reader.load_request(conn, no, cmd['operation_id'], authorize=authorize, now=now, missing_ok=True)
            if request is not None:
                if intent(request) != cmd:
                    reader.fail(409, 'physical_operation_conflict')
                writer.read_result(conn, request, authorize=authorize, now=now,
                                   preparation=request.get('contract') == writer.VERSION)
            else:
                request, policies = _new_request(conn, no, cmd, principal, now)
                if money._txid(conn) != txid:
                    c.fail('caller_transaction_changed')
                if cmd['action'] in writer.PREPARATION:
                    writer.execute_preparation(conn, request, policy=policies['preparation'], authorize=authorize, now=now)
                else:
                    writer.execute_fulfillment(conn, request, fulfillment_policy=policies['fulfillment'],
                        preparation_policy=policies['preparation'], authorize=authorize, now=now)
            authorize(order_no=no, action=cmd['action'], now=_clock(conn))
            if money._txid(conn) != txid:
                c.fail('caller_transaction_changed')
    except Exception:
        if 'authorize' in locals() and authorize.failure is not None:
            raise authorize.failure
        raise
    # Only after caller COMMIT and connection close succeeded. No automatic retry.
    return _read(engine, no, audience='admin', credential=credential, principal=principal,
                 operation_id=cmd['operation_id'], original=request)


async def _body(request):
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_REQUEST_BYTES:
            reader.fail(422, 'fulfillment_request_too_large')
        chunks.append(chunk)
    return b''.join(chunks)


def _query(request, audience):
    pairs = list(request.query_params.multi_items())
    if len({key for key, _ in pairs}) != len(pairs):
        reader.fail(422, 'invalid_fulfillment_query')
    if audience == 'customer':
        if len(pairs) != 1 or pairs[0][0] != 'expected_binding_id':
            reader.fail(422, 'invalid_fulfillment_query')
        expected = owner.expected_binding(pairs[0][1])
        if expected is None:
            reader.fail(422, 'invalid_fulfillment_query')
        return expected
    if pairs:
        reader.fail(422, 'invalid_fulfillment_query')
    return None


def _post_origin(request):
    origin = get_origin()
    if type(origin) is not str or not re.fullmatch(r'https://[A-Za-z0-9.-]+(?::[1-9][0-9]{0,4})?', origin):
        reader.fail(503, 'fulfillment_origin_unconnected')
    if request.headers.getlist('origin') != [origin] or request.headers.getlist('sec-fetch-site') not in ([], ['same-origin']):
        reader.fail(403, 'same_origin_required')
    if request.headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'application/json':
        reader.fail(415, 'json_required')


async def _handle(request, no, audience, *, post=False, operation_id=None):
    try:
        principal = _principal(write=post) if audience == 'admin' else None
        if request.url.scheme != 'https':
            reader.fail(503, 'fulfillment_secure_configuration_unready')
        if audience == 'customer':
            owner_http._secure_request(request, owner_http.get_policy())
        if post:
            _post_origin(request)
        no = reader.order_no(no); expected = _query(request, audience)
        if operation_id is not None:
            operation_id = c.uuid_text(operation_id)
        raw = await _body(request)
        credential = request.cookies.get(owner.COOKIE if audience == 'customer' else get_auth().COOKIE)
        if post:
            try:
                cmd = command(json.loads(raw, object_pairs_hook=owner_http._unique_object))
            except (ValueError, TypeError, UnicodeError, c.CommerceError):
                reader.fail(422, 'invalid_fulfillment_command')
            payload = await run_in_threadpool(_write, get_engine(), no, cmd, credential, principal)
        else:
            if raw:
                reader.fail(422, 'invalid_fulfillment_query')
            payload = await run_in_threadpool(_read, get_engine(), no, audience=audience,
                credential=credential, expected=expected, principal=principal, operation_id=operation_id)
        return JSONResponse(payload, headers=HEADERS)
    except (reader.HTTPError, owner.OwnerError) as error:
        return _error(error.status, error.code)
    except c.CommerceError as error:
        if error.code in ('physical_authorization_required', 'physical_authorization_changed', 'fulfillment_authorization_required'):
            return _error(403, 'fulfillment_permission_required')
        if error.code in ('physical_operation_conflict', 'physical_order_changed', 'physical_shipment_changed',
                          'preparation_policy_unconfirmed', 'fulfillment_policy_changed', 'shipment_quantity_exceeded'):
            return _error(409, error.code)
        return _error(503, 'physical_result_unconfirmed' if post or operation_id else 'fulfillment_unavailable')
    except Exception:
        return _error(503, 'physical_result_unconfirmed' if post or operation_id else 'fulfillment_unavailable')


def create_router():
    router = APIRouter(tags=['commerce-fulfillment'])

    @router.get('/api/admin/commerce/orders/{order_no}/fulfillment')
    async def admin_current(order_no: str, request: Request):
        return await _handle(request, order_no, 'admin')

    @router.post('/api/admin/commerce/orders/{order_no}/fulfillment')
    async def admin_write(order_no: str, request: Request):
        return await _handle(request, order_no, 'admin', post=True)

    @router.get('/api/admin/commerce/orders/{order_no}/fulfillment/operations/{operation_id}')
    async def admin_result(order_no: str, operation_id: str, request: Request):
        return await _handle(request, order_no, 'admin', operation_id=operation_id)

    @router.get('/api/commerce/orders/{order_no}/fulfillment')
    async def customer_current(order_no: str, request: Request):
        return await _handle(request, order_no, 'customer')

    return router
