"""Pure manual-shipment plans from trusted, complete server observations.

Only record_tracking, handoff and deliver are covered. No database, auth,
provider, transaction, stock mutation or physical-return implementation exists
here. Supplied receipts/hashes are structural references, never authentication
or proof of a real commit. The adapter must lock/recheck the complete scope,
apply the plan atomically and read the result after commit. Plans are INTERNAL;
only their public allowlist is suitable for a response, and remains pending.
All quantities/amounts use the existing native-integer contract, without Decimal,
float or string coercion. Business responsibility/carriers/refund eligibility
must be explicitly supplied by a confirmed server policy; there are no defaults.
"""
from copy import deepcopy

from . import commerce_contract as c
from . import commerce_payment_core as payment

VERSION = 'commerce_manual_fulfillment_v1'
ACTIONS = ('record_tracking', 'handoff', 'deliver')
SHIPMENT_STATES = ('준비', '배송중', '완료')
_ORDER_FIELDS = ('order_no', 'owner', 'basis_id', 'revision', 'order_state',
                 'checkout_state', 'payment_state', 'allocation_state', 'refund_state',
                 'total', 'approved_amount', 'refunded_amount', 'lines')
_REQUEST_FIELDS = ('operation_id', 'order_no', 'actor_id', 'action',
                   'expected_order_basis', 'expected_order_revision',
                   'expected_policy_basis', 'shipment_id', 'expected_shipment_revision',
                   'lines', 'carrier', 'tracking_no', 'evidence', 'request_basis')
_IDENTITY_FIELDS = ('contract', 'operation_id', 'order_no', 'actor_id', 'shipment_id',
                    'action', 'owner_scope', 'request_basis')
_RESULT_FIELDS = ('plan_basis', 'order_revision', 'shipment_revision',
                  'order_state', 'shipment_state', 'evidence_basis')


def _lines(values, *, sale=False, empty=False):
    if type(values) is not list or (not values and not empty):
        c.fail('shipment_lines_required')
    result, seen, movement_ids = [], set(), set()
    fields = ('line_id', 'product_code', 'qty') + (() if sale else ('sale_movement_id',))
    for line in values:
        c.object_fields(line, fields)
        item = dict(line_id=c.text(line['line_id']), product_code=c.integer(line['product_code'], 1),
                    qty=c.integer(line['qty'], 1, c.MAX_QUANTITY))
        if item['line_id'] in seen:
            c.fail('duplicate_shipment_line')
        seen.add(item['line_id'])
        if not sale:
            item['sale_movement_id'] = c.integer(line['sale_movement_id'], 1)
            if item['sale_movement_id'] in movement_ids:
                c.fail('duplicate_sale_movement')
            movement_ids.add(item['sale_movement_id'])
        result.append(item)
    return sorted(result, key=lambda line: line['line_id'])


def _cargo(order_no, shipment_id, lines, carrier, tracking_no):
    return c.fingerprint(dict(order_no=order_no, shipment_id=shipment_id, lines=lines,
                              carrier=carrier, tracking_no=tracking_no))


def _evidence(value, *, kind, order_no, shipment_id, cargo, now, actor_id=None):
    fields = ('source', 'kind', 'order_no', 'shipment_id', 'actor_id', 'occurred_at',
              'reference', 'content_basis', 'basis')
    c.object_fields(value, fields)
    if value['source'] != 'operator_record' or value['kind'] != kind:
        c.fail('manual_evidence_required')
    if (c.text(value['order_no']) != order_no or c.integer(value['shipment_id'], 1) != shipment_id
            or c.basis_text(value['content_basis']) != cargo):
        c.fail('shipment_evidence_scope_mismatch')
    actor = c.integer(value['actor_id'], 1)
    if actor_id is not None and actor != actor_id:
        c.fail('shipment_evidence_actor_mismatch')
    c.text(value['reference'])
    occurred = c.integer(value['occurred_at'])
    if occurred > now:
        c.fail('shipment_evidence_time_mismatch')
    raw = {key: value[key] for key in fields if key != 'basis'}
    if c.basis_text(value['basis']) != c.fingerprint(raw):
        c.fail('shipment_evidence_basis_mismatch')
    return deepcopy(value)


def _request(value, now):
    c.object_fields(value, _REQUEST_FIELDS)
    result = deepcopy(value)
    result['operation_id'] = c.uuid_text(value['operation_id'])
    for key in ('actor_id', 'expected_order_revision', 'shipment_id', 'expected_shipment_revision'):
        c.integer(value[key], 1)
    c.text(value['order_no'])
    c.enum(value['action'], ACTIONS)
    for key in ('expected_order_basis', 'expected_policy_basis'):
        c.basis_text(value[key])
    result['lines'] = _lines(value['lines'])
    c.text(value['carrier']); c.text(value['tracking_no'])
    cargo = _cargo(result['order_no'], result['shipment_id'], result['lines'],
                   result['carrier'], result['tracking_no'])
    result['evidence'] = _evidence(value['evidence'], kind=value['action'],
        order_no=result['order_no'], shipment_id=result['shipment_id'], cargo=cargo,
        now=now, actor_id=result['actor_id'])
    raw = {key: result[key] for key in _REQUEST_FIELDS if key != 'request_basis'}
    if c.basis_text(value['request_basis']) != c.fingerprint(raw):
        c.fail('fulfillment_request_basis_mismatch')
    return result


def _authorize(value, request, now):
    c.object_fields(value, ('auth_source', 'authenticated', 'allowed', 'actor',
                            'permission', 'order_no', 'action', 'checked_at'))
    c.object_fields(value['actor'], ('operator_id', 'role', 'status'))
    actor = value['actor']
    if (value['auth_source'] != 'api.auth.current_operator' or value['authenticated'] is not True
            or value['allowed'] is not True or value['permission'] != 'commerce.fulfillment.write'
            or actor['role'] not in ('operator', 'owner') or actor['status'] != '활성'
            or c.integer(actor['operator_id'], 1) != request['actor_id']
            or value['order_no'] != request['order_no'] or value['action'] != request['action']
            or c.integer(value['checked_at']) != now):
        c.fail('fulfillment_authorization_required')


def _replay(existing, identity, request):
    c.object_fields(existing, ('identity', 'result', 'receipt'))
    previous = existing['identity']
    c.object_fields(previous, _IDENTITY_FIELDS)
    c.integer(previous['actor_id'], 1); c.integer(previous['shipment_id'], 1)
    c.text(previous['order_no']); c.enum(previous['action'], ACTIONS)
    c.basis_text(previous['owner_scope']); c.basis_text(previous['request_basis'])
    normalized = dict(previous, operation_id=c.uuid_text(previous['operation_id']))
    if normalized != identity:
        c.fail('fulfillment_operation_conflict')
    result, receipt = existing['result'], existing['receipt']
    c.object_fields(result, _RESULT_FIELDS)
    for key in ('plan_basis', 'evidence_basis'):
        c.basis_text(result[key])
    for key in ('order_revision', 'shipment_revision'):
        c.integer(result[key], 1)
    c.enum(result['order_state'], c.ORDER_STATES)
    c.enum(result['shipment_state'], SHIPMENT_STATES)
    expected_state = {'record_tracking': '준비', 'handoff': '배송중', 'deliver': '완료'}[request['action']]
    allowed_order_states = {'record_tracking': ('결제완료', '조립중', '출고', '배송중'),
                            'handoff': ('배송중',), 'deliver': ('배송중', '완료')}[request['action']]
    if (result['evidence_basis'] != request['evidence']['basis']
            or result['order_revision'] != request['expected_order_revision'] + 1
            or result['shipment_revision'] != request['expected_shipment_revision'] + 1
            or result['shipment_state'] != expected_state or result['order_state'] not in allowed_order_states):
        c.fail('fulfillment_result_reference_mismatch')
    c.object_fields(receipt, ('operation_id', 'request_basis', 'result_basis', 'commit_id',
                              'write_txid', 'read_txid'))
    c.uuid_text(receipt['commit_id'])
    if (c.uuid_text(receipt['operation_id']) != identity['operation_id']
            or c.basis_text(receipt['request_basis']) != identity['request_basis']
            or c.basis_text(receipt['result_basis']) != c.fingerprint(dict(identity=identity, result=result))
            or c.integer(receipt['write_txid'], 1) == c.integer(receipt['read_txid'], 1)):
        c.fail('fulfillment_result_reference_mismatch')
    # No current business calculation or effects. The trusted adapter must
    # resolve this stored reference; this pure function cannot prove a commit.
    return dict(contract=VERSION, action='read_existing_result', identity=deepcopy(identity),
                result=deepcopy(result), pending=True, pending_commit=False, effects=[],
                stock_effects=[], reservation_effects=[],
                public=dict(operation_id=identity['operation_id'], shipment_id=identity['shipment_id'],
                            action=identity['action'], pending=True))


def _paid(order, approval, active_operations, movements, now):
    if (order['checkout_state'] != 'paid' or order['payment_state'] != 'confirmed'
            or order['allocation_state'] != 'allocated'):
        c.fail('fulfillment_payment_unconfirmed')
    for key in ('total', 'approved_amount', 'refunded_amount'):
        c.integer(order[key])
    if order['approved_amount'] != order['total'] or order['refunded_amount'] > order['approved_amount']:
        c.fail('invalid_payment_balance')
    if ((order['refund_state'] == 'none' and order['refunded_amount'] != 0)
            or (order['refund_state'] == 'partial' and not 0 < order['refunded_amount'] < order['approved_amount'])
            or (order['refund_state'] == 'refunded' and order['refunded_amount'] != order['approved_amount'])):
        c.fail('invalid_payment_balance')
    c.object_fields(approval, ('operation', 'verification', 'payment_id', 'write_txid', 'read_txid'))
    operation = payment._operation(approval['operation'])
    spec = operation['spec']
    if (spec['kind'] != 'approve' or operation['state'] != 'confirmed'
            or spec['order_no'] != order['order_no'] or spec['amount'] != order['total']
            or c.integer(approval['payment_id'], 1) != operation['final_commit']['payment_id']
            or c.integer(approval['write_txid'], 1) == c.integer(approval['read_txid'], 1)):
        c.fail('fulfillment_approval_mismatch')
    c.require_owner(spec['owner'], order['owner'])
    payment.validate_provider_evidence(operation, operation['provider_result'], approval['verification'], now=now)
    lines = _lines(order['lines'], sale=True)
    if _lines(spec['allocation_lines'], sale=True) != lines:
        c.fail('fulfillment_allocation_scope_mismatch')
    if type(active_operations) is not list:
        c.fail('financial_observation_required')
    seen = set()
    for item in active_operations:
        c.object_fields(item, ('operation_id', 'order_no', 'kind', 'state'))
        operation_id = c.uuid_text(item['operation_id'])
        c.enum(item['kind'], ('approve', 'cancel'))
        c.enum(item['state'], payment.OPERATION_STATES)
        if item['order_no'] != order['order_no'] or operation_id in seen:
            c.fail('financial_operation_scope_mismatch')
        seen.add(operation_id)
        if item['state'] in ('prepared', 'processing', 'unknown'):
            c.fail('financial_operation_unresolved')
    if type(movements) is not list or len(movements) != len(lines):
        c.fail('sale_movement_scope_mismatch')
    by_line, ids = {}, set()
    for item in movements:
        c.object_fields(item, ('movement_id', 'order_no', 'operation_id', 'line_id',
                               'product_code', 'movement_type', 'qty_delta', 'effect_key'))
        movement_id = c.integer(item['movement_id'], 1)
        line_id = c.text(item['line_id'])
        c.integer(item['product_code'], 1)
        c.integer(item['qty_delta'], -c.MAX_QUANTITY, -1)
        effect = spec['operation_id'] + ':allocate:' + line_id
        if (item['order_no'] != order['order_no'] or c.uuid_text(item['operation_id']) != spec['operation_id']
                or item['movement_type'] != 'own_sale' or item['effect_key'] != effect
                or effect not in operation['final_commit']['effect_keys']
                or movement_id in ids or line_id in by_line):
            c.fail('sale_movement_scope_mismatch')
        ids.add(movement_id); by_line[line_id] = deepcopy(item)
    for line in lines:
        source = by_line.get(line['line_id'])
        if source is None or (source['product_code'], -source['qty_delta']) != (line['product_code'], line['qty']):
            c.fail('sale_movement_scope_mismatch')
    return lines, by_line


def _policy(value, order, request):
    c.object_fields(value, ('policy_id', 'policy_basis', 'state', 'order_no', 'responsibility',
                            'allowed_actions', 'allowed_refund_states', 'carriers'))
    c.text(value['policy_id'])
    if value['state'] != 'confirmed' or value['order_no'] != order['order_no']:
        c.fail('fulfillment_policy_unconfirmed')
    if c.basis_text(value['policy_basis']) != request['expected_policy_basis']:
        c.fail('fulfillment_policy_changed')
    c.enum(value['responsibility'], ('own', 'mall'))
    for key, choices in (('allowed_actions', ACTIONS),
                         ('allowed_refund_states', ('none', 'requested', 'partial'))):
        values = value[key]
        if type(values) is not list or not values or any(type(item) is not str for item in values):
            c.fail('fulfillment_policy_unconfirmed')
        if len(set(values)) != len(values):
            c.fail('fulfillment_policy_unconfirmed')
        for item in values:
            c.enum(item, choices)
    carriers = value['carriers']
    if type(carriers) is not list or not carriers:
        c.fail('fulfillment_policy_unconfirmed')
    for carrier in carriers:
        c.text(carrier)
    if len(set(carriers)) != len(carriers):
        c.fail('fulfillment_policy_unconfirmed')
    if (request['action'] not in value['allowed_actions'] or request['carrier'] not in carriers
            or order['refund_state'] not in value['allowed_refund_states']):
        c.fail('fulfillment_policy_blocked')


def _shipments(values, order_no, sources, now):
    if type(values) is not list or not values:
        c.fail('whole_shipment_observation_required')
    result = {}
    for row in values:
        c.object_fields(row, ('shipment_id', 'order_no', 'revision', 'state', 'lines', 'carrier',
                             'tracking_no', 'tracking_evidence', 'handoff_evidence', 'delivery_evidence'))
        shipment_id = c.integer(row['shipment_id'], 1)
        c.integer(row['revision'], 1)
        c.enum(row['state'], SHIPMENT_STATES)
        if row['order_no'] != order_no or shipment_id in result:
            c.fail('shipment_scope_mismatch')
        item = deepcopy(row); item['lines'] = _lines(row['lines'], empty=row['state'] == '준비')
        for line in item['lines']:
            source = sources.get(line['line_id'])
            if source is None or (source['movement_id'], source['product_code']) != (
                    line['sale_movement_id'], line['product_code']):
                c.fail('shipment_allocation_scope_mismatch')
        has_tracking = any(item[key] is not None for key in ('carrier', 'tracking_no', 'tracking_evidence'))
        if item['state'] == '준비' and not has_tracking:
            if any(item[key] is not None for key in ('handoff_evidence', 'delivery_evidence')):
                c.fail('shipment_state_inconsistent')
        else:
            if not item['lines']:
                c.fail('shipment_lines_required')
            c.text(item['carrier']); c.text(item['tracking_no'])
            cargo = _cargo(order_no, shipment_id, item['lines'], item['carrier'], item['tracking_no'])
            tracking = _evidence(item['tracking_evidence'], kind='record_tracking', order_no=order_no,
                                 shipment_id=shipment_id, cargo=cargo, now=now)
            if item['state'] in ('배송중', '완료'):
                handoff = _evidence(item['handoff_evidence'], kind='handoff', order_no=order_no,
                                    shipment_id=shipment_id, cargo=cargo, now=now)
                if handoff['occurred_at'] < tracking['occurred_at']:
                    c.fail('shipment_evidence_time_mismatch')
            elif item['handoff_evidence'] is not None:
                c.fail('shipment_state_inconsistent')
            if item['state'] == '완료':
                delivery = _evidence(item['delivery_evidence'], kind='deliver', order_no=order_no,
                                     shipment_id=shipment_id, cargo=cargo, now=now)
                if delivery['occurred_at'] < handoff['occurred_at']:
                    c.fail('shipment_evidence_time_mismatch')
            elif item['delivery_evidence'] is not None:
                c.fail('shipment_state_inconsistent')
        result[shipment_id] = item
    return result


def _new_plan(request, order, approval, active_operations, movements, shipments, policy, identity, now):
    for key, choices in (('order_state', c.ORDER_STATES), ('checkout_state', c.CHECKOUT_STATES),
                         ('payment_state', c.PAYMENT_STATES), ('allocation_state', c.ALLOCATION_STATES),
                         ('refund_state', c.REFUND_STATES)):
        c.enum(order[key], choices)
    if (c.basis_text(order['basis_id']) != request['expected_order_basis']
            or c.integer(order['revision'], 1) != request['expected_order_revision']):
        c.fail('fulfillment_order_changed')
    lines, sources = _paid(order, approval, active_operations, movements, now)
    _policy(policy, order, request)
    if order['refund_state'] in ('processing', 'unknown', 'refunded'):
        c.fail('fulfillment_refund_unresolved')
    observed = _shipments(shipments, order['order_no'], sources, now)
    target = observed.get(request['shipment_id'])
    if target is None or target['revision'] != request['expected_shipment_revision']:
        c.fail('fulfillment_shipment_changed')
    for line in request['lines']:
        source = sources.get(line['line_id'])
        if source is None or (source['movement_id'], source['product_code']) != (
                line['sale_movement_id'], line['product_code']):
            c.fail('shipment_allocation_scope_mismatch')
    action = request['action']
    expected = {'record_tracking': '준비', 'handoff': '준비', 'deliver': '배송중'}[action]
    if target['state'] != expected:
        c.fail('fulfillment_transition_blocked')
    if action == 'record_tracking' and target['tracking_evidence'] is not None:
        c.fail('fulfillment_transition_blocked')
    if action == 'handoff' and target['tracking_evidence'] is None:
        c.fail('shipment_tracking_required')
    if action != 'record_tracking' and (request['lines'] != target['lines'] or
            (request['carrier'], request['tracking_no']) != (target['carrier'], target['tracking_no'])):
        c.fail('shipment_content_changed')
    if action == 'record_tracking' and target['lines'] and request['lines'] != target['lines']:
        c.fail('shipment_content_changed')
    used = {line['line_id']: 0 for line in lines}
    for shipment_id, row in observed.items():
        for line in request['lines'] if shipment_id == target['shipment_id'] else row['lines']:
            used[line['line_id']] += line['qty']
    if any(used[line['line_id']] > line['qty'] for line in lines):
        c.fail('shipment_quantity_exceeded')
    previous_evidence = target['tracking_evidence'] if action == 'handoff' else target['handoff_evidence']
    if action != 'record_tracking' and request['evidence']['occurred_at'] < previous_evidence['occurred_at']:
        c.fail('shipment_evidence_time_mismatch')
    if order['order_state'] not in ('결제완료', '조립중', '출고', '배송중'):
        c.fail('fulfillment_transition_blocked')
    if action in ('handoff', 'deliver') and order['order_state'] not in ('출고', '배송중'):
        c.fail('fulfillment_transition_blocked')
    if action == 'deliver' and order['order_state'] != '배송중':
        c.fail('fulfillment_transition_blocked')
    # A stored invoice remains preparation; only actual handoff advances it.
    next_state = {'record_tracking': '준비', 'handoff': '배송중', 'deliver': '완료'}[action]
    order_state = order['order_state']
    if action == 'handoff':
        order_state = '배송중'
    if action == 'deliver' and all(used[line['line_id']] == line['qty'] for line in lines) and all(
            row['state'] == '완료' for shipment_id, row in observed.items() if shipment_id != target['shipment_id']):
        order_state = '완료'
    c.integer(order['revision'] + 1, 1); c.integer(target['revision'] + 1, 1)
    result = dict(order_revision=order['revision'] + 1, shipment_revision=target['revision'] + 1,
                  order_state=order_state, shipment_state=next_state, evidence_basis=request['evidence']['basis'])
    effect = dict(kind=action, shipment_id=target['shipment_id'], content_basis=request['evidence']['content_basis'],
                  evidence_basis=result['evidence_basis'], evidence_source='operator_record')
    plan = dict(contract=VERSION, action='apply_in_caller_transaction', identity=identity,
                pending=True, pending_commit=True, result=result, effects=[effect], stock_effects=[],
                reservation_effects=[], required_product_codes=sorted({line['product_code'] for line in lines}),
                input_basis=c.fingerprint(dict(order=order, approval=approval, active_operations=active_operations,
                    movements=movements, shipments=shipments, policy=policy)),
                requirements=['whole_products_asc_before_order', 'order_revision_cas', 'shipment_revision_cas',
                              'physical_operation_unique', 'whole_shipment_quantity_recheck',
                              'atomic_caller_transaction', 'read_after_commit'],
                public=dict(operation_id=identity['operation_id'], shipment_id=identity['shipment_id'],
                            action=action, pending=True))
    result['plan_basis'] = c.fingerprint(plan)
    return plan


def plan_fulfillment(request, *, order, approval, active_operations, movements,
                     shipments, policy, authorization, now, existing=None):
    """Validate server-injected observations; return a pending, redacted plan.

    The caller must supply ALL shipment allocations, including prepared rows.
    Matching values cannot detect an omitted row or establish native auth/CAS.
    Exact replay checks current authorization and stored scope/reference only;
    it deliberately skips current price, quantity, policy and payment planning.
    """
    now = c.integer(now)
    request = _request(request, now)
    _authorize(authorization, request, now)
    c.object_fields(order, _ORDER_FIELDS)
    if c.text(order['order_no']) != request['order_no']:
        c.fail('fulfillment_order_scope_mismatch')
    owner = c.owner_identity(order['owner'])
    identity = dict(contract=VERSION, operation_id=request['operation_id'], order_no=request['order_no'],
                    actor_id=request['actor_id'], shipment_id=request['shipment_id'], action=request['action'],
                    owner_scope=c.fingerprint(owner), request_basis=request['request_basis'])
    if existing is not None:
        return _replay(existing, identity, request)
    return _new_plan(request, order, approval, active_operations, movements, shipments, policy, identity, now)
