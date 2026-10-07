"""Pure inspection/restoration plans, separate from cash cancellation.

All observations, principals, policies and inspection results are injected by
trusted SERVER adapters. Hashes/receipts validate shape and reference binding;
they cannot authenticate evidence, prove a complete SQL snapshot or a COMMIT.
The adapter must lock the whole product set ascending before order/return/child
locks, recheck revision/quantity caps, apply a unique physical effect in its
caller transaction and observe it after commit. No DB/provider/auth I/O here.
Prepared/unknown restoration allocations are counted and cannot be bypassed.
The caller must resolve physical UUIDs to stored results before new planning;
this core cannot discover omitted inspection-operation records by itself.
No refund period, fee, responsibility or resale judgement is invented. Native
integer quantities only; Decimal/float/string coercion belongs outside this core.
Only public is an HTTP allowlist; it remains pending, never a factual result.
"""
from copy import deepcopy

from . import commerce_contract as c
from . import commerce_payment_core as payment
from . import commerce_fulfillment_core as shipping

VERSION = 'commerce_physical_return_plan_v1'
ACTIONS = ('inspect', 'restore')
_ORDER_FIELDS = ('order_no', 'owner', 'basis_id', 'revision', 'order_state', 'checkout_state',
                 'payment_state', 'allocation_state', 'refund_state', 'total', 'approved_amount',
                 'refunded_amount', 'lines')
_REQUEST_FIELDS = ('operation_id', 'actor_id', 'order_no', 'return_id', 'action',
                   'expected_order_basis', 'expected_order_revision', 'expected_return_revision',
                   'expected_policy_basis', 'expected_history_basis', 'evidence_basis', 'lines', 'request_basis')
_IDENTITY_FIELDS = ('contract', 'operation_id', 'actor_id', 'order_no', 'return_id', 'action',
                    'owner_scope', 'request_basis')
_RESULT_FIELDS = ('plan_basis', 'action', 'order_revision', 'return_revision', 'evidence_basis', 'lines')


def _quantities(value):
    if type(value) is not list or not value:
        c.fail('return_lines_required')
    result, seen = [], set()
    for row in value:
        c.object_fields(row, ('return_line_id', 'qty'))
        line_id = c.integer(row['return_line_id'], 1)
        qty = c.integer(row['qty'], 1, c.MAX_QUANTITY)
        if line_id in seen:
            c.fail('duplicate_return_line')
        seen.add(line_id); result.append(dict(return_line_id=line_id, qty=qty))
    return sorted(result, key=lambda row: row['return_line_id'])


def _request(value):
    c.object_fields(value, _REQUEST_FIELDS)
    result = deepcopy(value); result['operation_id'] = c.uuid_text(value['operation_id'])
    for key in ('actor_id', 'return_id', 'expected_order_revision', 'expected_return_revision'):
        c.integer(value[key], 1)
    c.text(value['order_no']); c.enum(value['action'], ACTIONS)
    for key in ('expected_order_basis', 'expected_policy_basis', 'expected_history_basis', 'evidence_basis'):
        c.basis_text(value[key])
    result['lines'] = _quantities(value['lines'])
    if c.basis_text(value['request_basis']) != c.fingerprint({k:v for k,v in result.items() if k!='request_basis'}):
        c.fail('return_request_basis_mismatch')
    return result


def _authorize(value, request, now):
    c.object_fields(value, ('auth_source', 'authenticated', 'allowed', 'actor', 'permission',
                            'order_no', 'return_id', 'action', 'checked_at'))
    c.object_fields(value['actor'], ('operator_id', 'role', 'status'))
    actor = value['actor']
    if (value['auth_source'] != 'api.auth.current_operator' or value['authenticated'] is not True
            or value['allowed'] is not True or value['permission'] != 'commerce.return.' + request['action']
            or actor['role'] not in ('operator', 'owner') or actor['status'] != '활성'
            or c.integer(actor['operator_id'], 1) != request['actor_id']
            or value['order_no'] != request['order_no'] or value['action'] != request['action']
            or c.integer(value['return_id'], 1) != request['return_id'] or c.integer(value['checked_at']) != now):
        c.fail('return_authorization_required')


def _replay(existing, identity, request):
    c.object_fields(existing, ('identity', 'result', 'receipt'))
    previous = existing['identity']; c.object_fields(previous, _IDENTITY_FIELDS)
    c.integer(previous['actor_id'], 1); c.integer(previous['return_id'], 1)
    c.text(previous['order_no']); c.enum(previous['action'], ACTIONS)
    c.basis_text(previous['owner_scope']); c.basis_text(previous['request_basis'])
    if dict(previous, operation_id=c.uuid_text(previous['operation_id'])) != identity:
        c.fail('return_operation_conflict')
    result = existing['result']; c.object_fields(result, _RESULT_FIELDS)
    c.basis_text(result['plan_basis']); c.basis_text(result['evidence_basis'])
    c.integer(result['order_revision'], 1); c.integer(result['return_revision'], 1)
    if (result['action'] != request['action'] or result['evidence_basis'] != request['evidence_basis']
            or result['order_revision'] != request['expected_order_revision'] + 1
            or result['return_revision'] != request['expected_return_revision'] + 1
            or _quantities(result['lines']) != request['lines']):
        c.fail('return_result_reference_mismatch')
    receipt = existing['receipt']
    c.object_fields(receipt, ('operation_id', 'request_basis', 'result_basis', 'commit_id', 'write_txid', 'read_txid'))
    c.uuid_text(receipt['commit_id'])
    if (c.uuid_text(receipt['operation_id']) != identity['operation_id']
            or c.basis_text(receipt['request_basis']) != identity['request_basis']
            or c.basis_text(receipt['result_basis']) != c.fingerprint(dict(identity=identity, result=result))
            or c.integer(receipt['write_txid'], 1) == c.integer(receipt['read_txid'], 1)):
        c.fail('return_result_reference_mismatch')
    return dict(contract=VERSION, action='read_existing_result', identity=deepcopy(identity), result=deepcopy(result),
                pending=True, pending_commit=False, effects=[], stock_effects=[], financial_effects=[],
                reservation_effects=[], public=_public(identity))


def _public(identity):
    return dict(operation_id=identity['operation_id'], return_id=identity['return_id'],
                action=identity['action'], pending=True)


def _origin(order, approval, movements, now):
    for key, choices in (('order_state', c.ORDER_STATES), ('checkout_state', c.CHECKOUT_STATES),
                         ('payment_state', c.PAYMENT_STATES), ('allocation_state', c.ALLOCATION_STATES),
                         ('refund_state', c.REFUND_STATES)):
        c.enum(order[key], choices)
    if (order['checkout_state'] != 'paid' or order['payment_state'] != 'confirmed'
            or order['allocation_state'] != 'allocated'):
        c.fail('original_sale_unconfirmed')
    for key in ('total', 'approved_amount', 'refunded_amount'):
        c.integer(order[key])
    if (order['approved_amount'] != order['total'] or order['refunded_amount'] > order['approved_amount']
            or (order['refund_state']=='none' and order['refunded_amount']!=0)
            or (order['refund_state']=='partial' and not 0<order['refunded_amount']<order['approved_amount'])
            or (order['refund_state']=='refunded' and order['refunded_amount']!=order['approved_amount'])):
        c.fail('invalid_payment_balance')
    c.object_fields(approval, ('operation', 'verification', 'payment_id', 'write_txid', 'read_txid'))
    operation = payment._operation(approval['operation']); spec = operation['spec']
    if (spec['kind']!='approve' or operation['state']!='confirmed' or spec['order_no']!=order['order_no']
            or spec['amount']!=order['total'] or c.integer(approval['payment_id'],1)!=operation['final_commit']['payment_id']
            or c.integer(approval['write_txid'],1)==c.integer(approval['read_txid'],1)):
        c.fail('original_sale_unconfirmed')
    c.require_owner(spec['owner'], order['owner'])
    payment.validate_provider_evidence(operation, operation['provider_result'], approval['verification'], now=now)
    lines = shipping._lines(order['lines'], sale=True)
    if shipping._lines(spec['allocation_lines'], sale=True) != lines:
        c.fail('original_sale_scope_changed')
    if type(movements) is not list or len(movements)!=len(lines):
        c.fail('original_sale_scope_changed')
    sources, ids = {}, set()
    for row in movements:
        c.object_fields(row, ('movement_id', 'order_no', 'operation_id', 'line_id', 'product_code',
                              'movement_type', 'qty_delta', 'effect_key'))
        movement_id=c.integer(row['movement_id'],1); line_id=c.text(row['line_id'])
        c.integer(row['product_code'],1); c.integer(row['qty_delta'],-c.MAX_QUANTITY,-1)
        effect=spec['operation_id']+':allocate:'+line_id
        if (row['order_no']!=order['order_no'] or c.uuid_text(row['operation_id'])!=spec['operation_id']
                or row['movement_type']!='own_sale' or row['effect_key']!=effect
                or effect not in operation['final_commit']['effect_keys'] or movement_id in ids or line_id in sources):
            c.fail('original_sale_scope_changed')
        ids.add(movement_id); sources[line_id]=deepcopy(row)
    for line in lines:
        source=sources.get(line['line_id'])
        if source is None or (source['product_code'],-source['qty_delta'])!=(line['product_code'],line['qty']):
            c.fail('original_sale_scope_changed')
    return lines, sources, spec['operation_id']


def _policy(value, order, request, financial_operations, approval_id):
    c.object_fields(value, ('policy_id','policy_basis','state','order_no','inspection_rule_basis',
                            'allowed_actions','allowed_refund_states','allowed_active_cancel_states'))
    c.text(value['policy_id']); c.basis_text(value['inspection_rule_basis'])
    if value['state']!='confirmed' or value['order_no']!=order['order_no']:
        c.fail('return_policy_unconfirmed')
    if c.basis_text(value['policy_basis'])!=request['expected_policy_basis']:
        c.fail('return_policy_changed')
    for key, choices in (('allowed_actions',ACTIONS),('allowed_refund_states',c.REFUND_STATES),
                         ('allowed_active_cancel_states',('prepared','processing','unknown'))):
        values=value[key]
        if type(values) is not list or any(type(item) is not str for item in values) or len(values)!=len(set(values)):
            c.fail('return_policy_unconfirmed')
        for item in values: c.enum(item,choices)
    if request['action'] not in value['allowed_actions'] or order['refund_state'] not in value['allowed_refund_states']:
        c.fail('return_policy_blocked')
    if type(financial_operations) is not list: c.fail('financial_observation_required')
    ids=set(); original_seen=False
    for row in financial_operations:
        c.object_fields(row,('operation_id','order_no','kind','state'))
        operation_id=c.uuid_text(row['operation_id']); c.enum(row['kind'],('approve','cancel'))
        c.enum(row['state'],payment.OPERATION_STATES)
        if row['order_no']!=order['order_no'] or operation_id in ids: c.fail('financial_scope_mismatch')
        ids.add(operation_id)
        if operation_id==request['operation_id']: c.fail('physical_operation_must_be_independent')
        if operation_id==approval_id:
            original_seen=row['kind']=='approve' and row['state']=='confirmed'
        if row['state'] in ('prepared','processing','unknown') and (
                row['kind']!='cancel' or row['state'] not in value['allowed_active_cancel_states']):
            c.fail('financial_state_policy_unconfirmed')
    if not original_seen: c.fail('financial_scope_mismatch')


def _ids(values, *, uuid=False):
    if type(values) is not list: c.fail('whole_return_history_required')
    normalized=[c.uuid_text(value) if uuid else c.integer(value,1) for value in values]
    if len(normalized)!=len(set(normalized)): c.fail('whole_return_history_required')
    return sorted(normalized)


def _history(history, order_no, approval, financial_operations, shipments, returns, restorations):
    c.object_fields(history,('state','order_no','read_txid','financial_operation_ids','shipment_ids',
                             'return_ids','restoration_effect_keys','basis_id'))
    if history['state']!='complete' or history['order_no']!=order_no or c.integer(history['read_txid'],1)!=approval['read_txid']:
        c.fail('whole_return_history_required')
    for rows in (financial_operations,shipments,returns,restorations):
        if type(rows) is not list: c.fail('whole_return_history_required')
        if any(type(row) is not dict for row in rows): c.fail('whole_return_history_required')
    if (_ids(history['financial_operation_ids'],uuid=True)!=_ids([row.get('operation_id') for row in financial_operations],uuid=True)
            or _ids(history['shipment_ids'])!=_ids([row.get('shipment_id') for row in shipments])
            or _ids(history['return_ids'])!=_ids([row.get('return_id') for row in returns])):
        c.fail('whole_return_history_required')
    expected=history['restoration_effect_keys']
    if type(expected) is not list: c.fail('whole_return_history_required')
    for key in expected: c.text(key)
    actual=[c.text(row.get('effect_key')) for row in restorations]
    if len(set(expected))!=len(expected) or len(set(actual))!=len(actual) or sorted(expected)!=sorted(actual):
        c.fail('whole_return_history_required')
    basis=c.fingerprint(dict(order_no=order_no,read_txid=history['read_txid'],financial_operations=financial_operations,
                             shipments=shipments,returns=returns,restorations=restorations))
    if c.basis_text(history['basis_id'])!=basis: c.fail('return_history_changed')


def _evidence(value, *, kind, order_no, return_id, line, quantities, now, rule_basis=None, actor_id=None):
    fields=('source','state','kind','order_no','return_id','return_line_id','shipment_id','sale_movement_id',
            'actor_id','occurred_at','reference','content_basis','rules_basis','basis')
    c.object_fields(value,fields)
    if value['state']!='confirmed' or value['source']!=('server_inspection' if kind=='inspect' else 'operator_record') or value['kind']!=kind:
        c.fail('physical_evidence_unconfirmed')
    if (value['order_no']!=order_no or c.integer(value['return_id'],1)!=return_id
            or c.integer(value['return_line_id'],1)!=line['return_line_id']
            or c.integer(value['shipment_id'],1)!=line['shipment_id']
            or c.integer(value['sale_movement_id'],1)!=line['sale_movement_id']):
        c.fail('physical_evidence_scope_mismatch')
    actor=c.integer(value['actor_id'],1); c.text(value['reference'])
    if actor_id is not None and actor!=actor_id: c.fail('physical_evidence_actor_mismatch')
    if c.integer(value['occurred_at'])>now: c.fail('physical_evidence_time_mismatch')
    if kind=='inspect':
        c.basis_text(value['rules_basis'])
        if rule_basis is not None and value['rules_basis']!=rule_basis: c.fail('inspection_policy_changed')
    elif value['rules_basis'] is not None: c.fail('physical_evidence_scope_mismatch')
    if c.basis_text(value['content_basis'])!=c.fingerprint(quantities): c.fail('physical_evidence_quantity_mismatch')
    if c.basis_text(value['basis'])!=c.fingerprint({key:value[key] for key in fields if key!='basis'}):
        c.fail('physical_evidence_basis_mismatch')
    return deepcopy(value)


def _returns(values, order_no, observed_shipments, now):
    cases, lines, claimed={}, {}, {}
    for case in values:
        c.object_fields(case,('return_id','order_no','revision','lines'))
        return_id=c.integer(case['return_id'],1); c.integer(case['revision'],1)
        if case['order_no']!=order_no or return_id in cases: c.fail('return_scope_mismatch')
        if type(case['lines']) is not list or not case['lines']: c.fail('return_lines_required')
        seen=set()
        for row in case['lines']:
            c.object_fields(row,('return_line_id','shipment_id','line_id','sale_movement_id','product_code',
                                 'claimed_qty','collected_qty','received_qty','inspected_qty','resellable_qty',
                                 'collection_evidence','receipt_evidence','inspection_evidence'))
            line_id=c.integer(row['return_line_id'],1); shipment_id=c.integer(row['shipment_id'],1)
            movement_id=c.integer(row['sale_movement_id'],1); c.integer(row['product_code'],1); c.text(row['line_id'])
            if line_id in lines or (shipment_id,row['line_id']) in seen: c.fail('duplicate_return_line')
            seen.add((shipment_id,row['line_id']))
            ship=observed_shipments.get(shipment_id)
            source=next((item for item in ship['lines'] if item['line_id']==row['line_id']),None) if ship else None
            if source is None or (source['sale_movement_id'],source['product_code'])!=(movement_id,row['product_code']):
                c.fail('return_shipment_scope_mismatch')
            for key in ('claimed_qty','collected_qty','received_qty','inspected_qty','resellable_qty'):
                c.integer(row[key],1 if key=='claimed_qty' else 0,c.MAX_QUANTITY)
            if not row['resellable_qty']<=row['inspected_qty']<=row['received_qty']<=row['collected_qty']<=row['claimed_qty']:
                c.fail('return_quantity_inconsistent')
            claim_key=(shipment_id,row['line_id']); claimed[claim_key]=claimed.get(claim_key,0)+row['claimed_qty']
            if claimed[claim_key]>source['qty']: c.fail('return_quantity_exceeded')
            previous=ship['handoff_evidence']['occurred_at'] if ship['handoff_evidence'] is not None else None
            for kind,qty,key in (('collect',row['collected_qty'],'collection_evidence'),
                                 ('receive',row['received_qty'],'receipt_evidence'),
                                 ('inspect',row['inspected_qty'],'inspection_evidence')):
                if qty==0:
                    if row[key] is not None: c.fail('physical_evidence_quantity_mismatch')
                    continue
                if previous is None: c.fail('actual_handoff_required')
                metrics=dict(inspected_qty=qty,resellable_qty=row['resellable_qty']) if kind=='inspect' else dict(qty=qty)
                proof=_evidence(row[key],kind=kind,order_no=order_no,return_id=return_id,line=row,quantities=metrics,now=now)
                if proof['occurred_at']<previous: c.fail('physical_evidence_time_mismatch')
                previous=proof['occurred_at']
            lines[line_id]=dict(deepcopy(row),return_id=return_id)
        cases[return_id]=deepcopy(case)
    return cases,lines


def _restorations(values, lines, order_no, financial_ids, original_movement_ids, history):
    by_line, by_sale, unresolved={}, {}, set()
    movement_ids=set(); operation_scopes={}
    for row in values:
        c.object_fields(row,('physical_operation_id','actor_id','order_no','return_id','return_line_id',
                             'sale_movement_id','product_code','qty','inspection_basis','policy_basis','state',
                             'effect_key','movement_id','receipt'))
        operation_id=c.uuid_text(row['physical_operation_id']); c.integer(row['actor_id'],1)
        line_id=c.integer(row['return_line_id'],1); line=lines.get(line_id)
        qty=c.integer(row['qty'],1,c.MAX_QUANTITY); c.basis_text(row['policy_basis']); c.basis_text(row['inspection_basis'])
        c.enum(row['state'],('prepared','processing','unknown','applied'))
        if (line is None or row['order_no']!=order_no or c.integer(row['return_id'],1)!=line['return_id']
                or c.integer(row['sale_movement_id'],1)!=line['sale_movement_id']
                or c.integer(row['product_code'],1)!=line['product_code'] or operation_id in financial_ids
                or row['effect_key']!=operation_id+':return:'+str(line_id) or line['inspection_evidence'] is None):
            c.fail('restoration_scope_mismatch')
        if row['inspection_basis']!=line['inspection_evidence']['basis']: c.fail('restoration_inspection_changed')
        scope=(row['actor_id'],row['return_id'],row['policy_basis'])
        if operation_id in operation_scopes and operation_scopes[operation_id]!=scope:
            c.fail('restoration_operation_scope_mismatch')
        operation_scopes[operation_id]=scope
        if row['state']=='applied':
            movement_id=c.integer(row['movement_id'],1)
            if movement_id in movement_ids or movement_id in original_movement_ids:
                c.fail('duplicate_restoration_movement')
            movement_ids.add(movement_id)
            receipt=row['receipt']
            c.object_fields(receipt,('operation_id','effect_key','movement_id','content_basis','commit_id','write_txid','read_txid'))
            c.uuid_text(receipt['commit_id'])
            content={key:row[key] for key in ('physical_operation_id','actor_id','order_no','return_id',
                     'return_line_id','sale_movement_id','product_code','qty','inspection_basis','policy_basis','effect_key')}
            if (c.uuid_text(receipt['operation_id'])!=operation_id or receipt['effect_key']!=row['effect_key']
                    or c.integer(receipt['movement_id'],1)!=movement_id or c.basis_text(receipt['content_basis'])!=c.fingerprint(content)
                    or c.integer(receipt['read_txid'],1)!=history['read_txid']
                    or c.integer(receipt['write_txid'],1)==receipt['read_txid']):
                c.fail('restoration_receipt_mismatch')
        else:
            if row['movement_id'] is not None or row['receipt'] is not None: c.fail('restoration_receipt_mismatch')
            unresolved.add(line['sale_movement_id'])
        by_line[line_id]=by_line.get(line_id,0)+qty
        by_sale[line['sale_movement_id']]=by_sale.get(line['sale_movement_id'],0)+qty
        if by_line[line_id]>line['resellable_qty']: c.fail('restoration_quantity_exceeded')
    return by_line,by_sale,unresolved


def _new_plan(request, order, approval, financial_operations, movements, shipments, returns,
              restorations, history, inspection, policy, identity, now):
    if c.basis_text(order['basis_id'])!=request['expected_order_basis'] or c.integer(order['revision'],1)!=request['expected_order_revision']:
        c.fail('return_order_changed')
    sale_lines,sources,approval_id=_origin(order,approval,movements,now)
    _policy(policy,order,request,financial_operations,approval_id)
    _history(history,order['order_no'],approval,financial_operations,shipments,returns,restorations)
    if history['basis_id']!=request['expected_history_basis']: c.fail('return_history_changed')
    observed=shipping._shipments(shipments,order['order_no'],sources,now)
    used={line['line_id']:0 for line in sale_lines}
    for ship in observed.values():
        for line in ship['lines']: used[line['line_id']]+=line['qty']
    if any(used[line['line_id']]>line['qty'] for line in sale_lines): c.fail('shipment_quantity_exceeded')
    cases,lines=_returns(returns,order['order_no'],observed,now)
    target=cases.get(request['return_id'])
    if target is None or target['revision']!=request['expected_return_revision']: c.fail('return_revision_changed')
    allocated,by_sale,unresolved=_restorations(restorations,lines,order['order_no'],
        {c.uuid_text(row['operation_id']) for row in financial_operations},
        {source['movement_id'] for source in sources.values()},history)
    if any(c.uuid_text(row['physical_operation_id'])==request['operation_id'] for row in restorations):
        c.fail('physical_existing_result_required')
    for source in sources.values():
        if by_sale.get(source['movement_id'],0)>-source['qty_delta']: c.fail('restoration_quantity_exceeded')
    selected=[]
    for requested in request['lines']:
        line=lines.get(requested['return_line_id'])
        if line is None or line['return_id']!=request['return_id']: c.fail('return_line_scope_mismatch')
        selected.append((requested,line))
    effects,stock_effects=[],[]
    if request['action']=='inspect':
        if type(inspection) is not list or len(inspection)!=len(selected): c.fail('inspection_result_required')
        results={}
        for item in inspection:
            c.object_fields(item,('return_line_id','inspected_qty','resellable_qty','evidence'))
            line_id=c.integer(item['return_line_id'],1)
            if line_id in results: c.fail('duplicate_return_line')
            results[line_id]=item
        proof_refs=[]
        for requested,line in selected:
            item=results.get(line['return_line_id'])
            if item is None: c.fail('inspection_result_required')
            qty=c.integer(item['inspected_qty'],1,c.MAX_QUANTITY); resale=c.integer(item['resellable_qty'],0,c.MAX_QUANTITY)
            if qty!=requested['qty'] or not line['inspected_qty']<=qty<=line['received_qty'] or resale>qty or resale<allocated.get(line['return_line_id'],0):
                c.fail('inspection_quantity_exceeded')
            proof=_evidence(item['evidence'],kind='inspect',order_no=order['order_no'],return_id=target['return_id'],
                line=line,quantities=dict(inspected_qty=qty,resellable_qty=resale),now=now,
                rule_basis=policy['inspection_rule_basis'],actor_id=request['actor_id'])
            previous=line['inspection_evidence'] or line['receipt_evidence']
            if previous is None or proof['occurred_at']<previous['occurred_at']: c.fail('physical_evidence_time_mismatch')
            if any(row['return_line_id']==line['return_line_id'] for row in restorations):
                c.fail('inspection_has_restoration_history')
            proof_refs.append(dict(return_line_id=line['return_line_id'],inspection_basis=proof['basis']))
            effects.append(dict(kind='record_inspection',return_line_id=line['return_line_id'],
                                inspected_qty=qty,resellable_qty=resale,evidence_basis=proof['basis']))
    else:
        if inspection is not None: c.fail('unexpected_inspection_result')
        proof_refs=[]; proposed_by_sale={}
        for requested,line in selected:
            proof=line['inspection_evidence']
            if proof is None or proof['rules_basis']!=policy['inspection_rule_basis']: c.fail('inspection_result_required')
            if line['sale_movement_id'] in unresolved: c.fail('physical_restoration_unresolved')
            remaining=line['resellable_qty']-allocated.get(line['return_line_id'],0)
            original=-sources[line['line_id']]['qty_delta']-by_sale.get(line['sale_movement_id'],0)
            if requested['qty']>min(remaining,original): c.fail('restoration_quantity_exceeded')
            proposed_by_sale[line['sale_movement_id']]=proposed_by_sale.get(line['sale_movement_id'],0)+requested['qty']
            if proposed_by_sale[line['sale_movement_id']]>original: c.fail('restoration_quantity_exceeded')
            proof_refs.append(dict(return_line_id=line['return_line_id'],inspection_basis=proof['basis']))
            effect=dict(kind='restore_return_stock',physical_operation_id=request['operation_id'],
                return_id=target['return_id'],return_line_id=line['return_line_id'],sale_movement_id=line['sale_movement_id'],
                product_code=line['product_code'],qty_delta=requested['qty'],inspection_basis=proof['basis'],
                effect_key=request['operation_id']+':return:'+str(line['return_line_id']))
            stock_effects.append(effect)
    if c.fingerprint(proof_refs)!=request['evidence_basis']: c.fail('inspection_evidence_changed')
    c.integer(order['revision']+1,1); c.integer(target['revision']+1,1)
    result=dict(action=request['action'],order_revision=order['revision']+1,return_revision=target['revision']+1,
                evidence_basis=request['evidence_basis'],lines=deepcopy(request['lines']))
    plan=dict(contract=VERSION,action='apply_in_caller_transaction',identity=identity,result=result,pending=True,pending_commit=True,
        effects=effects,stock_effects=stock_effects,financial_effects=[],reservation_effects=[],
        required_product_codes=sorted({line['product_code'] for line in sale_lines}),history_basis=history['basis_id'],
        requirements=['whole_history_snapshot_recheck','whole_products_asc_before_order','order_then_return_then_child_locks',
                      'order_revision_cas','return_revision_cas','existing_physical_operation_read','physical_operation_unique','restoration_effect_unique',
                      'all_return_quantity_caps_recheck','atomic_caller_transaction','read_after_commit'],public=_public(identity))
    result['plan_basis']=c.fingerprint(plan)
    return plan


def plan_physical_return(request, *, order, approval, financial_operations, movements, shipments,
                         returns, restorations, history, inspection, policy, authorization, now, existing=None):
    """Plan only. Exact replay rechecks actor/scope/reference, not current business.

    A complete supplied manifest detects missing observed rows relative to that
    manifest; only the adapter can prove the manifest represents the actual DB.
    Inspection never restores stock. Restoration never refunds money or changes
    original allocation/reservations. This module does not enable return_stock.
    """
    now=c.integer(now); request=_request(request); _authorize(authorization,request,now)
    c.object_fields(order,_ORDER_FIELDS)
    if c.text(order['order_no'])!=request['order_no']: c.fail('return_order_scope_mismatch')
    owner=c.owner_identity(order['owner'])
    identity=dict(contract=VERSION,operation_id=request['operation_id'],actor_id=request['actor_id'],order_no=request['order_no'],
                  return_id=request['return_id'],action=request['action'],owner_scope=c.fingerprint(owner),request_basis=request['request_basis'])
    if existing is not None: return _replay(existing,identity,request)
    return _new_plan(request,order,approval,financial_operations,movements,shipments,returns,restorations,
                     history,inspection,policy,identity,now)
