"""Admin return snapshots in caller transactions; no engine, auth or policy IO.

SQL/native MVCC and commit behavior require separate PostgreSQL verification.
Only synchronous trusted SERVER callbacks may authorize these functions.
"""
from copy import deepcopy
from uuid import UUID

from sqlalchemy import text

from . import commerce_contract as c
from . import commerce_writer as money
from . import commerce_fulfillment_read as shipping_read
from . import commerce_physical_return_core as core

VERSION = 'commerce_physical_return_storage_v1'
CASE = ('return_id', 'order_id', 'revision', 'write_txid')
LINE = ('return_line_id', 'order_id', 'return_id', 'shipment_id', 'line_id', 'sale_movement_id',
        'product_code', 'claimed_qty', 'collected_qty', 'received_qty', 'inspected_qty',
        'resellable_qty', 'collection_evidence', 'receipt_evidence', 'inspection_evidence')
OP = ('operation_id', 'order_id', 'return_id', 'contract', 'action', 'actor_id', 'owner_scope',
      'wire_intent', 'request_basis', 'request', 'identity', 'state', 'revision', 'result', 'receipt', 'write_txid')
EFFECT = ('effect_key', 'physical_operation_id', 'order_id', 'return_id', 'return_line_id',
          'sale_movement_id', 'product_code', 'qty', 'inspection_basis', 'policy_basis', 'state',
          'movement_id', 'receipt', 'write_txid')
MOVEMENT = ('movement_id', 'product_code', 'movement_type', 'qty_delta', 'ref_kind', 'ref_id',
            'commerce_operation_id', 'commerce_effect_key', 'physical_return_operation_id', 'physical_return_effect_key')


def _sql(conn, tag, statement, **params):
    return conn.execute(text('/*physical_return:' + tag + '*/ ' + statement), params)


def _json_object(alias, fields):
    # All aliases/identifiers are source constants. UUIDs serialize canonically in JSONB.
    return 'jsonb_build_object(' + ','.join("'" + name + "'," + alias + '.' + name for name in fields) + ')'


def _aggregate(table, alias, fields, sort, predicate):
    return ("(SELECT COALESCE(jsonb_agg(" + _json_object(alias, fields) + ' ORDER BY ' + sort
            + "),'[]'::jsonb) FROM " + table + ' ' + alias + ' WHERE ' + predicate + ')')


def _snapshot(conn, no):
    """One SELECT for financial, shipment and all return histories; no LIMIT/fallback."""
    columns = [
        _aggregate('commerce_shipments', 's', shipping_read.PARENT, 's.shipment_id', 's.order_id=d.order_id') + ' AS parents',
        _aggregate('commerce_shipment_lines', 'l', shipping_read.LINE, 'l.shipment_id,l.line_id', 'l.order_id=d.order_id') + ' AS cargo',
        _aggregate('commerce_physical_operations', 'x', shipping_read.writer._OP, 'x.operation_id', 'x.order_id=d.order_id') + ' AS operations',
        _aggregate('commerce_return_cases', 'r', CASE, 'r.return_id', 'r.order_id=d.order_id') + ' AS cases',
        _aggregate('commerce_return_lines', 'rl', LINE, 'rl.return_id,rl.return_line_id', 'rl.order_id=d.order_id') + ' AS return_lines',
        _aggregate('commerce_return_operations', 'rx', OP, 'rx.operation_id', 'rx.order_id=d.order_id') + ' AS return_operations',
        _aggregate('commerce_return_restoration_effects', 'e', EFFECT, 'e.effect_key', 'e.order_id=d.order_id') + ' AS effects',
        _aggregate('stock_movements', 'm', MOVEMENT, 'm.movement_id', "m.ref_kind='order' AND m.ref_id=d.order_id") + ' AS movements',
        "(SELECT COALESCE(jsonb_agg(jsonb_build_object('operation_id',f.operation_id,'order_no',o.order_no,"
        "'kind',f.kind,'state',f.state) ORDER BY f.operation_id),'[]'::jsonb) FROM commerce_payment_operations f"
        ' WHERE f.order_id=d.order_id) AS financial_operations']
    rows = _sql(conn, 'snapshot', '''SELECT o.order_id,o.order_no,o.status AS order_state,o.total_amount,
        d.context_id::text,d.owner_scope,d.owner_identity,d.request_id,d.request_basis,d.snapshot,
        d.policy_snapshot,d.provider_binding,d.states,d.revision,d.expires_at,d.write_txid,
        txid_current() AS read_txid,ledger.approved,ledger.refunded,
        proof.payment_id AS approval_payment_id,proof.operation AS approval_operation,
        proof.verification AS approval_verification,proof.write_txid AS approval_write_txid,'''
        + ','.join(columns) + ''' FROM orders o JOIN commerce_order_details d USING(order_id)
        CROSS JOIN LATERAL (SELECT
          COALESCE(sum(CASE WHEN p.status='승인' THEN p.amount ELSE 0 END),0)::bigint AS approved,
          COALESCE(-sum(CASE WHEN p.status='환불' THEN p.amount ELSE 0 END),0)::bigint AS refunded
          FROM payments p WHERE p.order_id=o.order_id AND p.commerce_operation_id IS NOT NULL) ledger
        LEFT JOIN LATERAL (SELECT p.payment_id,x.operation,x.verification,x.write_txid
          FROM payments p JOIN commerce_payment_operations x ON x.operation_id=p.commerce_operation_id
          WHERE p.order_id=o.order_id AND x.order_id=o.order_id AND p.status='승인'
            AND x.kind='approve' AND x.state='confirmed') proof ON TRUE WHERE o.order_no=:no''',
        no=shipping_read.order_no(no)).mappings().all()
    if len(rows) != 1:
        c.fail('order_not_found' if not rows else 'committed_approval_cardinality')
    return dict(rows[0])


def _history_token(row):
    """Stable public concurrency token: persisted contents only, never read TX IDs."""
    def persisted(value):
        if isinstance(value, dict):
            return {key: persisted(item) for key, item in value.items() if key != 'read_txid'}
        if isinstance(value, list):
            return [persisted(item) for item in value]
        return value
    names = ('order_no', 'owner_scope', 'order_state', 'revision', 'snapshot', 'states', 'approved', 'refunded',
             'approval_operation', 'approval_verification', 'parents', 'cargo', 'operations',
             'cases', 'return_lines', 'return_operations', 'effects', 'movements', 'financial_operations')
    return c.fingerprint(persisted({key: row[key] for key in names}))


def _authorize(callback, no, action, return_id, now, actor_id=None):
    if not callable(callback):
        c.fail('return_authorization_unconnected')
    grant = callback(order_no=no, action=action, return_id=return_id, now=now)
    c.object_fields(grant, ('auth_source', 'authenticated', 'allowed', 'actor', 'permission',
                           'order_no', 'return_id', 'action', 'checked_at'))
    c.object_fields(grant['actor'], ('operator_id', 'role', 'status'))
    actor = grant['actor']; c.integer(actor['operator_id'], 1)
    if (grant['auth_source'] != 'api.auth.current_operator' or grant['authenticated'] is not True
            or grant['allowed'] is not True or grant['permission'] != 'commerce.return.' + action
            or actor['role'] not in (('viewer', 'operator', 'owner') if action == 'read' else ('operator', 'owner'))
            or actor['status'] != '활성' or grant['order_no'] != no or grant['return_id'] != return_id
            or grant['action'] != action or c.integer(grant['checked_at']) != now
            or (actor_id is not None and actor['operator_id'] != actor_id)):
        c.fail('return_authorization_required')
    return deepcopy(grant)


def _load(conn, no, now):
    from . import commerce_physical_return_writer as writer
    row = _snapshot(conn, no); txid = money._txid(conn)
    if c.integer(row['read_txid'], 1) != txid:
        c.fail('caller_transaction_changed')
    money._committed(conn, row)
    for name in ('cases', 'return_lines', 'return_operations', 'effects', 'movements', 'financial_operations'):
        if type(row[name]) is not list:
            c.fail('whole_return_history_required')
    scoped = {key: row[key] for key in ('order_id', 'order_no', 'context_id', 'owner_scope', 'owner_identity')}
    shipment_row = {key: row[key] for key in ('order_id', 'order_no', 'order_state', 'context_id', 'owner_scope',
        'owner_identity', 'snapshot', 'revision', 'write_txid', 'read_txid', 'parents', 'cargo', 'operations')}
    shipping_read._validate(shipment_row, scoped, now)
    if row['owner_scope'] != c.fingerprint(c.owner_identity(row['owner_identity'])):
        c.fail('return_scope_mismatch')
    order = dict(order_no=no, owner=deepcopy(row['owner_identity']), basis_id=money._basis(row, row['approved'], row['refunded']),
        revision=row['revision'], order_state=row['order_state'], total=row['total_amount'],
        approved_amount=row['approved'], refunded_amount=row['refunded'],
        lines=[{key: line[key] for key in ('line_id', 'product_code', 'qty')} for line in row['snapshot']['lines']], **row['states'])
    approval = dict(operation=row['approval_operation'], verification=row['approval_verification'],
        payment_id=row['approval_payment_id'], write_txid=row['approval_write_txid'], read_txid=txid)
    if any(value is None for value in approval.values()):
        c.fail('original_sale_unconfirmed')
    original_id = approval['operation']['spec']['operation_id']
    financial_ids = set()
    for financial in row['financial_operations']:
        c.object_fields(financial, ('operation_id', 'order_no', 'kind', 'state'))
        fid = c.uuid_text(financial['operation_id'])
        c.enum(financial['kind'], ('approve', 'cancel')); c.enum(financial['state'], core.payment.OPERATION_STATES)
        if financial['order_no'] != no or fid in financial_ids: c.fail('financial_scope_mismatch')
        if fid == original_id and (financial['kind'], financial['state']) != ('approve', 'confirmed'):
            c.fail('financial_scope_mismatch')
        financial_ids.add(fid)
    if original_id not in financial_ids: c.fail('financial_scope_mismatch')
    mapping = {original_id + ':allocate:' + line['line_id']: line['line_id'] for line in order['lines']}
    originals = []
    moves = {}
    for movement in row['movements']:
        c.object_fields(movement, MOVEMENT); mid = c.integer(movement['movement_id'], 1)
        if ((movement['commerce_operation_id'] is None) != (movement['commerce_effect_key'] is None)
                or (movement['physical_return_operation_id'] is None) != (movement['physical_return_effect_key'] is None)):
            c.fail('restoration_movement_mismatch')
        if mid in moves: c.fail('duplicate_restoration_movement')
        moves[mid] = movement
        if movement['commerce_operation_id'] is not None:
            if movement['physical_return_operation_id'] is not None or movement['physical_return_effect_key'] is not None:
                c.fail('original_sale_scope_changed')
            if movement['commerce_operation_id'] != original_id:
                continue
            if movement['commerce_effect_key'] not in mapping: c.fail('original_sale_scope_changed')
            originals.append(dict(movement_id=mid, order_no=no, operation_id=movement['commerce_operation_id'],
                line_id=mapping[movement['commerce_effect_key']], product_code=movement['product_code'],
                movement_type=movement['movement_type'], qty_delta=movement['qty_delta'], effect_key=movement['commerce_effect_key']))
    _, sources, _ = core._origin(order, approval, originals, now)
    shipments = [dict(shipment_id=p['shipment_id'], order_no=no, revision=p['revision'], state=p['state'],
        lines=[{key: l[key] for key in ('line_id', 'product_code', 'qty', 'sale_movement_id')}
               for l in row['cargo'] if l['shipment_id'] == p['shipment_id']],
        **{key: p[key] for key in ('carrier', 'tracking_no', 'tracking_evidence', 'handoff_evidence', 'delivery_evidence')})
        for p in row['parents']]
    cases = []; all_line_ids = set()
    for parent in row['cases']:
        c.object_fields(parent, CASE); c.integer(parent['revision'], 1); money._committed(conn, parent)
        if parent['order_id'] != row['order_id']: c.fail('return_scope_mismatch')
        children = []
        for line in row['return_lines']:
            c.object_fields(line, LINE)
            if line['return_id'] == parent['return_id']:
                if line['order_id'] != row['order_id']: c.fail('return_scope_mismatch')
                all_line_ids.add(line['return_line_id'])
                children.append({key: line[key] for key in LINE if key not in ('order_id', 'return_id')})
        cases.append(dict(return_id=parent['return_id'], order_no=no, revision=parent['revision'], lines=children))
    if len(all_line_ids) != len(row['return_lines']): c.fail('whole_return_history_required')
    observed = core.shipping._shipments(shipments, no, sources, now) if shipments else {}
    _, lines = core._returns(cases, no, observed, now)
    operations = {}; revisions = {case['return_id']: {} for case in cases}
    for op in row['return_operations']:
        c.object_fields(op, OP); oid = c.uuid_text(op['operation_id'])
        if oid in operations or oid in financial_ids or oid in {s['operation_id'] for s in row['operations']} or op['return_id'] not in revisions:
            c.fail('return_operation_scope_mismatch')
        writer._check_record(op, row)
        money._committed(conn, op)
        if op['state'] == 'applied':
            result = writer._stored(op, row, txid)
            rev = result['return_revision']
            if rev in revisions[op['return_id']]: c.fail('return_history_incomplete')
            revisions[op['return_id']][rev] = op
        operations[oid] = op
    for case in cases:
        history = revisions[case['return_id']]
        if sorted(history) != list(range(1, case['revision'] + 1)):
            c.fail('return_history_incomplete')
        if history[1]['action'] != 'create_case': c.fail('return_history_incomplete')
        created = history[1]['request']['source_lines']
        current_lines = {line['return_line_id']: line for line in case['lines']}
        if {line['return_line_id'] for line in created} != set(current_lines): c.fail('return_history_incomplete')
        for source in created:
            current_line = current_lines[source['return_line_id']]
            if (any(source[key] != current_line[key] for key in ('shipment_id', 'line_id', 'sale_movement_id', 'product_code'))
                    or source['qty'] != current_line['claimed_qty']): c.fail('return_history_incomplete')
        for line in case['lines']:
            for action, field in (('record_collection', 'collection_evidence'), ('record_receipt', 'receipt_evidence'), ('inspect', 'inspection_evidence')):
                relevant = [op for _, op in sorted(history.items()) if op['action'] == action
                    and any(item['return_line_id'] == line['return_line_id'] for item in op['result']['lines'])]
                proof = relevant[-1]['request']['proofs'].get(str(line['return_line_id'])) if relevant else None
                if line[field] != proof: c.fail('return_evidence_history_mismatch')
    restorations = []; effects_seen = set(); effect_moves = set()
    for effect in row['effects']:
        c.object_fields(effect, EFFECT)
        if effect['order_id'] != row['order_id'] or effect['effect_key'] in effects_seen: c.fail('restoration_scope_mismatch')
        effects_seen.add(effect['effect_key']); op = operations.get(c.uuid_text(effect['physical_operation_id']))
        if op is None or op['action'] != 'restore' or effect['state'] != op['state'] or effect['return_id'] != op['return_id']:
            c.fail('restoration_scope_mismatch')
        internal = op['request']['core_request']
        requested = next((line for line in internal['lines'] if line['return_line_id'] == effect['return_line_id']), None)
        if (requested is None or effect['qty'] != requested['qty']
                or effect['policy_basis'] != internal['expected_policy_basis']
                or effect['inspection_basis'] != op['request']['proofs'][str(effect['return_line_id'])]['basis']):
            c.fail('restoration_scope_mismatch')
        item = {key: deepcopy(effect[key]) for key in EFFECT if key not in ('order_id', 'write_txid')}
        item.update(order_no=no, actor_id=op['actor_id'])
        if effect['state'] == 'applied':
            money._committed(conn, effect)
            movement = moves.get(effect['movement_id'])
            if (movement is None or effect['movement_id'] in effect_moves
                    or (movement['physical_return_operation_id'], movement['physical_return_effect_key']) != (op['operation_id'], effect['effect_key'])
                    or movement['commerce_operation_id'] is not None or movement['commerce_effect_key'] is not None
                    or (movement['product_code'], movement['qty_delta'], movement['movement_type'], movement['ref_kind'], movement['ref_id'])
                       != (effect['product_code'], effect['qty'], 'return', 'order', row['order_id'])):
                c.fail('restoration_movement_mismatch')
            effect_moves.add(effect['movement_id'])
            c.object_fields(item['receipt'], ('operation_id', 'effect_key', 'movement_id', 'content_basis', 'commit_id', 'write_txid'))
            if item['receipt']['write_txid'] != effect['write_txid']: c.fail('restoration_receipt_mismatch')
            item['receipt']['read_txid'] = txid
        restorations.append(item)
    physical_moves = {mid for mid, move in moves.items() if move['physical_return_operation_id'] is not None}
    if physical_moves != effect_moves: c.fail('whole_return_history_required')
    for op in operations.values():
        if op['action'] == 'restore':
            expected = {op['operation_id'] + ':return:' + str(item['return_line_id']) for item in op['request']['core_request']['lines']}
            actual = {e['effect_key'] for e in row['effects'] if e['physical_operation_id'] == op['operation_id']}
            if expected != actual: c.fail('whole_return_history_required')
    history = dict(state='complete', order_no=no, read_txid=txid,
        financial_operation_ids=[f['operation_id'] for f in row['financial_operations']],
        shipment_ids=[s['shipment_id'] for s in shipments], return_ids=[r['return_id'] for r in cases],
        restoration_effect_keys=[e['effect_key'] for e in restorations])
    history['basis_id'] = c.fingerprint(dict(order_no=no, read_txid=txid,
        financial_operations=row['financial_operations'], shipments=shipments, returns=cases, restorations=restorations))
    core._history(history, no, approval, row['financial_operations'], shipments, cases, restorations)
    allocated, by_sale, unresolved = core._restorations(restorations, lines, no,
        {f['operation_id'] for f in row['financial_operations']}, {s['movement_id'] for s in sources.values()}, history)
    if any(by_sale.get(source['movement_id'], 0) > -source['qty_delta'] for source in sources.values()):
        c.fail('restoration_quantity_exceeded')
    return dict(row=row, order=order, approval=approval, financial_operations=row['financial_operations'], movements=originals,
        shipments=shipments, returns=cases, restorations=restorations, history=history, sources=sources,
        lines=lines, operations=operations, allocated=allocated, unresolved=unresolved, token=_history_token(row))


def _operation(conn, operation_id):
    rows = _sql(conn, 'operation', 'SELECT ' + ','.join(OP) + ' FROM commerce_return_operations WHERE operation_id=CAST(:id AS uuid)',
                id=c.uuid_text(operation_id)).mappings().all()
    if len(rows) > 1: c.fail('return_operation_scope_mismatch')
    if not rows: return None
    record = dict(rows[0])
    # Native UUID columns may be decoded by DBAPI as UUID; JSON UUIDs are text.
    if type(record['operation_id']) is UUID:
        record['operation_id'] = str(record['operation_id'])
    return record


@money._atomic
def read_current(conn, no, *, authorize, now):
    no = shipping_read.order_no(no); now = c.integer(now)
    grant = _authorize(authorize, no, 'read', None, now)
    bundle = _load(conn, no, now); cases = []
    for case in bundle['returns']:
        public_lines = []
        for line in case['lines']:
            item = {key: line[key] for key in ('return_line_id', 'shipment_id', 'line_id', 'claimed_qty',
                'collected_qty', 'received_qty', 'inspected_qty', 'resellable_qty')}
            item.update(restoration_consumed_qty=bundle['allocated'].get(line['return_line_id'], 0),
                        restoration_remaining_qty=line['resellable_qty']-bundle['allocated'].get(line['return_line_id'], 0),
                        restoration_unresolved=line['sale_movement_id'] in bundle['unresolved'])
            public_lines.append(item)
        history = []
        for op in sorted((op for op in bundle['operations'].values() if op['return_id'] == case['return_id'] and op['state'] == 'applied'),
                         key=lambda op: op['result']['return_revision']):
            observation = op['request'].get('observation')
            evidence = [dict(return_line_id=int(lid), **{key: proof[key] for key in
                ('kind', 'actor_id', 'occurred_at', 'reference')}) for lid, proof in sorted(op['request']['proofs'].items(), key=lambda item: int(item[0]))]
            history.append(dict(operation_id=op['operation_id'], action=op['action'], actor_id=op['actor_id'],
                return_revision=op['result']['return_revision'], order_revision=op['result']['order_revision'],
                lines=op['result']['lines'], occurred_at=observation['occurred_at'] if observation else None,
                reference=observation['reference'] if observation else None, evidence=evidence))
        cases.append(dict(return_id=case['return_id'], revision=case['revision'], lines=public_lines, history=history))
    if _authorize(authorize, no, 'read', None, now) != grant: c.fail('return_authorization_changed')
    return deepcopy(dict(version=VERSION, state='confirmed', order_no=no, checked_at=now,
        order_revision=bundle['order']['revision'], expected_order_basis=bundle['order']['basis_id'],
        expected_history_token=bundle['token'], cases=cases,
        actions={action: dict(allowed=False, reason='source_unconnected') for action in core.ACTIONS}))


@money._atomic
def load_request(conn, no, operation_id, *, authorize, now, missing_ok=False):
    from . import commerce_physical_return_writer as writer
    no = shipping_read.order_no(no); now = c.integer(now)
    grant = _authorize(authorize, no, 'read', None, now)
    row = money._order(conn, no); record = _operation(conn, operation_id)
    if record is None:
        if missing_ok is True:
            if _authorize(authorize, no, 'read', None, now) != grant: c.fail('return_authorization_changed')
            return None
        c.fail('return_operation_not_found')
    if record['order_id'] != row['order_id'] or record['owner_scope'] != row['owner_scope']:
        c.fail('return_operation_conflict' if missing_ok else 'return_operation_not_found')
    money._committed(conn, row, record); writer._check_record(record, row)
    if _authorize(authorize, no, 'read', None, now) != grant: c.fail('return_authorization_changed')
    return deepcopy(record['wire_intent'])


@money._atomic
def read_result(conn, no, operation_id, *, authorize, now):
    from . import commerce_physical_return_writer as writer
    no = shipping_read.order_no(no); now = c.integer(now); row = money._order(conn, no)
    record = _operation(conn, operation_id)
    if record is None: c.fail('return_operation_not_found')
    grant = _authorize(authorize, no, record['action'], record['wire_intent']['return_id'], now, record['actor_id'])
    money._committed(conn, row, record)
    result = writer._stored(record, row, money._txid(conn))
    if _authorize(authorize, no, record['action'], record['wire_intent']['return_id'], now, record['actor_id']) != grant:
        c.fail('return_authorization_changed')
    return deepcopy(dict(version=VERSION, state='confirmed', pending_commit=False, pending=False,
        order_no=no, operation_id=record['operation_id'], action=record['action'], return_id=record['return_id'],
        order_revision=result['order_revision'], return_revision=result['return_revision'], lines=result['lines']))
