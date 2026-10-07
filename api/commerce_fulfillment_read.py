"""Caller-owned read snapshots and immutable request recovery, no engine or auth IO.

This is a stored-data projection, not a policy, grant or physical-fact issuer.
SQL snapshot/JSON/native transaction behavior still needs PostgreSQL verification.
"""
from copy import deepcopy
import json
import re

from sqlalchemy import text

from . import commerce_contract as c
from . import commerce_owner as owner
from . import commerce_fulfillment_core as core
from . import commerce_fulfillment_writer as writer
from . import commerce_writer as money

VERSION = 'commerce_fulfillment_http_v1'
ORDER_NO = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,19}\Z')
PARENT = ('shipment_id', 'order_id', 'revision', 'state', 'line_basis', 'carrier',
          'tracking_no', 'tracking_evidence', 'handoff_evidence', 'delivery_evidence',
          'readiness', 'readiness_operation_id', 'write_txid')
LINE = ('order_id', 'shipment_id', 'line_id', 'product_code', 'qty', 'sale_movement_id')
ACTIONS = writer.PREPARATION + core.ACTIONS


class HTTPError(c.CommerceError):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


def fail(status, code):
    raise HTTPError(status, code)


def order_no(value):
    if type(value) is not str or not ORDER_NO.fullmatch(value):
        fail(422, 'invalid_fulfillment_order')
    return value


def _sql(conn, tag, statement, **params):
    return conn.execute(text('/*fulfillment_read:' + tag + '*/ ' + statement), params)


def _authorize(authorize, no, now, audience):
    if audience not in ('admin', 'customer') or not callable(authorize):
        fail(503, 'fulfillment_authorization_unready')
    grant = authorize(order_no=no, action='read', now=now)
    if audience == 'customer':
        if not isinstance(grant, owner.OwnerContext):
            fail(401, 'owner_context_lost')
        c.uuid_text(grant.context_id)
        identity = c.owner_identity(grant.owner_identity)
        if (identity['kind'] != 'guest' or grant.owner_scope != c.fingerprint(identity)
                or c.integer(grant.expires_at) <= now):
            fail(401, 'owner_context_lost')
    else:
        c.object_fields(grant, ('auth_source', 'authenticated', 'allowed', 'actor',
                               'permission', 'order_no', 'action', 'checked_at'))
        c.object_fields(grant['actor'], ('operator_id', 'role', 'status'))
        c.integer(grant['actor']['operator_id'], 1)
        c.integer(grant['checked_at'])
        if (grant['auth_source'] != 'api.auth.current_operator'
                or grant['authenticated'] is not True or grant['allowed'] is not True
                or grant['permission'] != 'commerce.order.read' or grant['action'] != 'read'
                or grant['order_no'] != no or grant['checked_at'] != now
                or grant['actor']['role'] not in ('viewer', 'operator', 'owner')
                or grant['actor']['status'] != '활성'):
            fail(403, 'fulfillment_permission_required')
    return deepcopy(grant)


def _predicate(context):
    if context is None:
        return '', {}
    return (''' AND d.context_id=CAST(:context AS uuid) AND d.owner_scope=:scope
        AND d.owner_identity=CAST(:identity AS jsonb)''',
        dict(context=context.context_id, scope=context.owner_scope,
             identity=json.dumps(context.owner_identity, sort_keys=True, separators=(',', ':'))))


def scope(conn, no, context=None):
    """Owner restriction before shipment/operation/payment reads; caller authorizes."""
    predicate, params = _predicate(context)
    rows = _sql(conn, 'scope', '''SELECT o.order_id,o.order_no,d.context_id::text,
        d.owner_scope,d.owner_identity FROM orders o JOIN commerce_order_details d USING(order_id)
        WHERE o.order_no=:no''' + predicate, no=order_no(no), **params).mappings().all()
    if not rows:
        fail(404, 'order_not_found')
    if len(rows) != 1:
        fail(503, 'fulfillment_scope_unavailable')
    row = dict(rows[0])
    c.object_fields(row, ('order_id', 'order_no', 'context_id', 'owner_scope', 'owner_identity'))
    c.integer(row['order_id'], 1); c.uuid_text(row['context_id'])
    if row['order_no'] != no or c.fingerprint(c.owner_identity(row['owner_identity'])) != row['owner_scope']:
        fail(503, 'fulfillment_scope_unavailable')
    if context is not None and (row['context_id'] != context.context_id
            or row['owner_scope'] != context.owner_scope or row['owner_identity'] != context.owner_identity):
        fail(404, 'order_not_found')
    return row


def _object(alias, fields):
    # All identifiers are fixed source constants, never request data.
    return 'jsonb_build_object(' + ','.join("'" + key + "'," + alias + '.' + key for key in fields) + ')'


def _snapshot(conn, no, context):
    predicate, params = _predicate(context)
    rows = _sql(conn, 'snapshot', '''SELECT o.order_id,o.order_no,o.status AS order_state,
        d.context_id::text,d.owner_scope,d.owner_identity,d.snapshot,d.revision,d.write_txid,
        txid_current() AS read_txid,parents.value AS parents,cargo.value AS cargo,
        operations.value AS operations FROM orders o JOIN commerce_order_details d USING(order_id)
        CROSS JOIN LATERAL (SELECT COALESCE(jsonb_agg(''' + _object('s', PARENT) + '''
            ORDER BY s.shipment_id),'[]'::jsonb) AS value
            FROM commerce_shipments s WHERE s.order_id=d.order_id) parents
        CROSS JOIN LATERAL (SELECT COALESCE(jsonb_agg(''' + _object('l', LINE) + '''
            ORDER BY l.shipment_id,l.line_id),'[]'::jsonb) AS value
            FROM commerce_shipment_lines l WHERE l.order_id=d.order_id) cargo
        CROSS JOIN LATERAL (SELECT COALESCE(jsonb_agg(''' + _object('x', writer._OP) + '''
            ORDER BY x.operation_id),'[]'::jsonb) AS value
            FROM commerce_physical_operations x WHERE x.order_id=d.order_id) operations
        WHERE o.order_no=:no''' + predicate, no=no, **params).mappings().all()
    if not rows:
        fail(404, 'order_not_found')
    if len(rows) != 1:
        fail(503, 'fulfillment_snapshot_unavailable')
    return dict(rows[0])


def _validate(row, scoped, now):
    c.object_fields(row, ('order_id', 'order_no', 'order_state', 'context_id', 'owner_scope',
                         'owner_identity', 'snapshot', 'revision', 'write_txid', 'read_txid',
                         'parents', 'cargo', 'operations'))
    if any(row[key] != scoped[key] for key in scoped):
        fail(503, 'fulfillment_scope_changed')
    c.enum(row['order_state'], c.ORDER_STATES); c.integer(row['revision'], 1)
    read_txid = c.integer(row['read_txid'], 1)
    if c.integer(row['write_txid'], 1) == read_txid:
        c.fail('commit_not_visible')
    if type(row['snapshot']) is not dict or type(row['snapshot'].get('lines')) is not list:
        c.fail('shipment_content_changed')
    sale = core._lines([{key: line[key] for key in ('line_id', 'product_code', 'qty')}
                        for line in row['snapshot']['lines']], sale=True)
    original = {line['line_id']: line for line in sale}
    for key in ('parents', 'cargo', 'operations'):
        if type(row[key]) is not list:
            c.fail('whole_shipment_observation_required')
    parents, sources, used, cargo = {}, {}, {key: 0 for key in original}, {}
    for parent in row['parents']:
        c.object_fields(parent, PARENT)
        sid = c.integer(parent['shipment_id'], 1)
        c.integer(parent['order_id'], 1); c.integer(parent['revision'], 1)
        c.integer(parent['write_txid'], 1); c.enum(parent['state'], core.SHIPMENT_STATES)
        if sid in parents or parent['order_id'] != row['order_id'] or parent['write_txid'] == read_txid:
            c.fail('shipment_scope_mismatch')
        parents[sid] = parent; cargo[sid] = []
    for line in row['cargo']:
        c.object_fields(line, LINE)
        sid = c.integer(line['shipment_id'], 1); c.integer(line['order_id'], 1)
        movement = c.integer(line['sale_movement_id'], 1)
        source = original.get(c.text(line['line_id']))
        if sid not in parents or line['order_id'] != row['order_id'] or source is None:
            c.fail('shipment_line_history_incomplete')
        c.integer(line['product_code'], 1); qty = c.integer(line['qty'], 1, c.MAX_QUANTITY)
        if line['product_code'] != source['product_code']:
            c.fail('shipment_allocation_scope_mismatch')
        existing = sources.get(line['line_id'])
        if existing is not None and existing['movement_id'] != movement:
            c.fail('shipment_allocation_scope_mismatch')
        sources[line['line_id']] = dict(movement_id=movement, product_code=line['product_code'])
        used[line['line_id']] += qty
        cargo[sid].append({key: line[key] for key in ('line_id', 'product_code', 'qty', 'sale_movement_id')})
    if len({source['movement_id'] for source in sources.values()}) != len(sources):
        c.fail('shipment_allocation_scope_mismatch')
    if any(used[key] > original[key]['qty'] for key in used):
        c.fail('shipment_quantity_exceeded')
    ships, operations, histories = [], {}, {sid: {} for sid in parents}
    for sid, parent in parents.items():
        lines = core._lines(cargo[sid])
        cargo[sid] = lines
        if c.basis_text(parent['line_basis']) != c.fingerprint(lines):
            c.fail('shipment_content_changed')
        ships.append(dict(shipment_id=sid, order_no=row['order_no'], revision=parent['revision'],
                          state=parent['state'], lines=lines, **{key: parent[key] for key in
                          ('carrier', 'tracking_no', 'tracking_evidence', 'handoff_evidence', 'delivery_evidence')}))
    if ships:
        core._shipments(ships, row['order_no'], sources, now)
    for op in row['operations']:
        c.object_fields(op, writer._OP)
        oid = c.uuid_text(op['operation_id'])
        if oid in operations or op['shipment_id'] not in parents or op['state'] != 'applied':
            c.fail('physical_operation_unresolved')
        preparation = op['contract'] == writer.VERSION
        if not preparation and op['contract'] != core.VERSION:
            c.fail('physical_contract_unconnected')
        req = writer._normalize(op['request'], now, preparation)
        identity = writer._identity(req, row, preparation)
        if c.integer(op['write_txid'], 1) == read_txid:
            c.fail('commit_not_visible')
        result = writer._stored(op, req, identity, row, read_txid)
        revision = result['shipment_revision']
        history = histories[op['shipment_id']]
        if (revision in history or req['lines'] != cargo[op['shipment_id']]
                or result['order_revision'] > row['revision']):
            c.fail('shipment_operation_history_incomplete')
        history[revision] = op; operations[oid] = op
    for sid, parent in parents.items():
        history = histories[sid]
        if len(history) != parent['revision'] or sorted(history) != list(range(1, len(history) + 1)):
            c.fail('shipment_operation_history_incomplete')
        latest = history[parent['revision']]
        if (history[1]['action'] != 'prepare_shipment' or latest['result']['shipment_state'] != parent['state']
                or latest['write_txid'] != parent['write_txid']
                or latest['result']['ready'] != (parent['readiness'] is not None)):
            c.fail('shipment_operation_history_incomplete')
        ready = parent['readiness']; ready_id = parent['readiness_operation_id']
        if (ready is None) != (ready_id is None):
            c.fail('readiness_reference_mismatch')
        if ready is not None:
            c.object_fields(ready, ('operation_id', 'line_basis', 'policy_basis', 'rule_basis',
                                    'prerequisites', 'confirmed_at', 'basis'))
            reference = operations.get(c.uuid_text(ready_id))
            if (reference is None or reference['action'] != 'confirm_dispatch_ready'
                    or reference['shipment_id'] != sid or ready['operation_id'] != ready_id
                    or ready['line_basis'] != parent['line_basis']
                    or ready['basis'] != reference['result']['readiness_basis']
                    or ready['basis'] != latest['result']['readiness_basis']
                    or c.fingerprint({key: value for key, value in ready.items() if key != 'basis'}) != ready['basis']):
                c.fail('readiness_reference_mismatch')
        elif latest['result']['readiness_basis'] is not None:
            c.fail('readiness_reference_mismatch')
        for action, field in (('record_tracking', 'tracking_evidence'), ('handoff', 'handoff_evidence'), ('deliver', 'delivery_evidence')):
            candidates = [op for _, op in sorted(history.items()) if op['action'] == action]
            evidence = candidates[-1]['request']['evidence'] if candidates else None
            if parent[field] != evidence:
                c.fail('shipment_operation_history_incomplete')
            if action == 'record_tracking' and candidates:
                if any(parent[key] != candidates[-1]['request'][key] for key in ('carrier', 'tracking_no')):
                    c.fail('shipment_operation_history_incomplete')
    return parents, cargo, operations


@money._atomic
def read_current(conn, no, *, audience, authorize, now):
    no, now = order_no(no), c.integer(now)
    grant = _authorize(authorize, no, now, audience)
    context = grant if audience == 'customer' else None
    scoped = scope(conn, no, context)
    row = _snapshot(conn, no, context)
    if row.get('read_txid') != money._txid(conn):
        c.fail('caller_transaction_changed')
    parents, cargo, operations = _validate(row, scoped, now)
    if _authorize(authorize, no, now, audience) != grant:
        fail(403 if audience == 'admin' else 409, 'fulfillment_authorization_changed')
    shipments = []
    for sid, parent in sorted(parents.items()):
        item = dict(shipment_id=sid, shipment_state=parent['state'],
                    lines=[dict(line_id=line['line_id'], qty=line['qty']) for line in cargo[sid]],
                    carrier=parent['carrier'], tracking_no=parent['tracking_no'])
        for name, field in (('tracking_recorded_at', 'tracking_evidence'), ('handed_off_at', 'handoff_evidence'), ('delivered_at', 'delivery_evidence')):
            item[name] = parent[field]['occurred_at'] if parent[field] is not None else None
        if audience == 'admin':
            item.update(revision=parent['revision'], ready=parent['readiness'] is not None)
            item['history'] = []
            for op in sorted((op for op in operations.values() if op['shipment_id'] == sid),
                             key=lambda op: op['result']['shipment_revision']):
                request, result = op['request'], op['result']
                evidence = request.get('evidence')
                item['history'].append(dict(
                    operation_id=op['operation_id'], action=op['action'],
                    shipment_revision=result['shipment_revision'], order_revision=result['order_revision'],
                    actor_id=op['actor_id'], event_kind=request.get('event_kind'),
                    quantities=request.get('quantities'), outcome=request.get('outcome'),
                    occurred_at=evidence['occurred_at'] if evidence is not None else None,
                    reference=evidence['reference'] if evidence is not None else None, ready=result['ready']))
        shipments.append(item)
    payload = dict(version=VERSION, state='confirmed', order_no=no,
                   order_state=row['order_state'], checked_at=now, shipments=shipments)
    if audience == 'customer':
        payload['context'] = context.public()
    else:
        # A persisted row/hash is not actionable policy. Business producers remain unconnected.
        payload.update(order_revision=row['revision'], expected_order_basis=None,
                       actions={action: dict(allowed=False, reason='source_unconnected') for action in ACTIONS})
    return deepcopy(payload)


def load_request(conn, no, operation_id, *, authorize, now, missing_ok=False):
    """Admin-scoped lookup only; caller then validates full immutable result with writer."""
    no = order_no(no); operation_id = c.uuid_text(operation_id)
    _authorize(authorize, no, now, 'admin')
    scoped = scope(conn, no)
    record = writer._operation(conn, operation_id)
    if record is None:
        if missing_ok is True:
            return None
        fail(404, 'physical_operation_not_found')
    if record['order_id'] != scoped['order_id'] or record['owner_scope'] != scoped['owner_scope']:
        fail(409 if missing_ok is True else 404,
             'physical_operation_conflict' if missing_ok is True else 'physical_operation_not_found')
    request = deepcopy(record['request'])
    if type(request) is not dict or request.get('order_no') != no:
        fail(503, 'physical_result_unconfirmed')
    return request
