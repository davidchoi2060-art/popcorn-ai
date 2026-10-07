"""Internal caller-TX shipment adapter. No engine, HTTP, PG or stock restoration.

Authorization/policies/manual observations come from trusted synchronous SERVER
adapters. Matching dictionaries/hashes cannot authenticate them. Writes are
pending until a fresh caller transaction observes stored write_txid/results.
Preparation quantities are cumulative order-line observations, never deltas.
Only public is an allowlist. SQL grammar/concurrency require native verification.
"""
from copy import deepcopy
from uuid import uuid4

from . import commerce_contract as c
from . import commerce_fulfillment_core as core
from . import commerce_writer as money

VERSION = 'commerce_fulfillment_preparation_v1'
POLICY_VERSION = 'commerce_preparation_policy_v1'
EVIDENCE_VERSION = 'commerce_preparation_evidence_v1'
PREPARATION = ('prepare_shipment', 'record_preparation_event', 'confirm_dispatch_ready')
EVENTS = ('assembly_started', 'assembly_completed', 'inspection_recorded')
PERMISSIONS = dict(prepare_shipment='commerce.fulfillment.prepare',
    record_preparation_event='commerce.fulfillment.preparation.record',
    confirm_dispatch_ready='commerce.fulfillment.dispatch_ready')
_REQUEST = ('contract', 'operation_id', 'actor_id', 'order_no', 'action', 'expected_order_basis',
    'expected_order_revision', 'expected_order_state', 'expected_policy_basis', 'shipment_id', 'expected_shipment_revision',
    'lines', 'event_kind', 'quantities', 'outcome', 'prerequisites', 'evidence', 'request_basis')
_OP = ('operation_id', 'order_id', 'shipment_id', 'contract', 'action', 'actor_id', 'owner_scope',
       'request_basis', 'request', 'identity', 'state', 'revision', 'result', 'receipt', 'write_txid')
_RESULT = ('action', 'shipment_id', 'order_revision', 'shipment_revision', 'order_state',
           'shipment_state', 'ready', 'evidence_basis', 'readiness_basis', 'core_result')


def _sql(conn, tag, sql, **params):
    return money._sql(conn, 'physical_' + tag, sql, **params)


def _refs(values):
    if type(values) is not list: c.fail('preparation_references_required')
    result=[]; seen=set()
    for row in values:
        c.object_fields(row, ('operation_id', 'evidence_basis'))
        operation_id=c.uuid_text(row['operation_id']); c.basis_text(row['evidence_basis'])
        if operation_id in seen: c.fail('duplicate_preparation_reference')
        seen.add(operation_id); result.append(dict(operation_id=operation_id,evidence_basis=row['evidence_basis']))
    return sorted(result,key=lambda row:row['operation_id'])


def _normalize(value, now, preparation):
    if not preparation: return core._request(value,now)
    c.object_fields(value,_REQUEST)
    result=deepcopy(value)
    if result['contract']!=VERSION: c.fail('preparation_contract_mismatch')
    result['operation_id']=c.uuid_text(value['operation_id']); c.integer(value['actor_id'],1)
    c.text(value['order_no']); c.enum(value['action'],PREPARATION)
    c.enum(value['expected_order_state'],c.ORDER_STATES)
    c.integer(value['expected_order_revision'],1)
    for key in ('expected_order_basis','expected_policy_basis'): c.basis_text(value[key])
    result['lines']=core._lines(value['lines']); result['prerequisites']=_refs(value['prerequisites'])
    if value['action']=='prepare_shipment':
        if any(value[key] is not None for key in ('shipment_id','expected_shipment_revision','event_kind','quantities','outcome','evidence')) or result['prerequisites']:
            c.fail('unexpected_preparation_field')
    else:
        c.integer(value['shipment_id'],1); c.integer(value['expected_shipment_revision'],1)
        if value['action']=='record_preparation_event':
            c.enum(value['event_kind'],EVENTS)
            c.enum(value['outcome'],('accepted','rejected') if value['event_kind']=='inspection_recorded' else ('recorded',))
            if result['prerequisites'] or type(value['quantities']) is not list: c.fail('unexpected_preparation_field')
            metrics=[]; seen=set()
            for row in value['quantities']:
                c.object_fields(row,('line_id','observed_qty'))
                line=c.text(row['line_id']); qty=c.integer(row['observed_qty'],1,c.MAX_QUANTITY)
                if line in seen: c.fail('duplicate_preparation_line')
                seen.add(line); metrics.append(dict(line_id=line,observed_qty=qty))
            result['quantities']=sorted(metrics,key=lambda row:row['line_id'])
            if seen!={row['line_id'] for row in result['lines']}: c.fail('preparation_line_scope_mismatch')
        elif any(value[key] is not None for key in ('event_kind','quantities','outcome')):
            c.fail('unexpected_preparation_field')
        c.object_fields(value['evidence'],('contract','source','state','kind','order_no','shipment_id','actor_id',
            'occurred_at','reference','rules_basis','content_basis','basis'))
        if c.integer(value['evidence']['occurred_at'])>now: c.fail('preparation_evidence_time_mismatch')
    if c.basis_text(value['request_basis'])!=c.fingerprint({key:item for key,item in result.items() if key!='request_basis'}):
        c.fail('physical_request_basis_mismatch')
    return result


def _authorize(callback, request, now, preparation):
    if not callable(callback): c.fail('physical_authorization_unready')
    grant=callback(order_no=request['order_no'],action=request['action'],now=now)
    c.object_fields(grant,('auth_source','authenticated','allowed','actor','permission','order_no','action','checked_at'))
    c.object_fields(grant['actor'],('operator_id','role','status'))
    actor=grant['actor']
    permission=PERMISSIONS[request['action']] if preparation else 'commerce.fulfillment.write'
    if (grant['auth_source']!='api.auth.current_operator' or grant['authenticated'] is not True
            or grant['allowed'] is not True or grant['permission']!=permission
            or grant['order_no']!=request['order_no'] or grant['action']!=request['action']
            or c.integer(grant['checked_at'])!=now or c.integer(actor['operator_id'],1)!=request['actor_id']
            or actor['role'] not in ('operator','owner') or actor['status']!='활성'):
        c.fail('physical_authorization_required')
    return deepcopy(grant)


def _identity(req, row, preparation):
    c.integer(row['order_id'],1)
    owner=c.owner_identity(row['owner_identity']); scope=c.fingerprint(owner)
    if scope!=row['owner_scope']: c.fail('owner_scope_mismatch')
    return dict(contract=VERSION if preparation else core.VERSION,operation_id=req['operation_id'],
        actor_id=req['actor_id'],order_no=req['order_no'],owner_scope=scope,action=req['action'],request_basis=req['request_basis'])


def _operation(conn, operation_id):
    row=_sql(conn,'operation','''SELECT operation_id::text,order_id,shipment_id,contract,action,actor_id,owner_scope,
      request_basis,request,identity,state,revision,result,receipt,write_txid
      FROM commerce_physical_operations WHERE operation_id=CAST(:id AS uuid)''',id=operation_id).mappings().first()
    return dict(row) if row is not None else None


def _stored(record, req, identity, row, read_txid):
    c.object_fields(record,_OP)
    c.integer(record['order_id'],1); c.integer(record['shipment_id'],1); c.integer(record['actor_id'],1)
    c.integer(record['revision'],1); c.integer(record['write_txid'],1)
    c.enum(record['state'],('prepared','processing','unknown','applied'))
    if (record['order_id']!=row['order_id'] or c.uuid_text(record['operation_id'])!=req['operation_id']
            or record['identity']!=identity or record['request']!=req or record['owner_scope']!=identity['owner_scope']
            or record['actor_id']!=req['actor_id'] or record['contract']!=identity['contract']
            or record['action']!=req['action'] or record['request_basis']!=req['request_basis']):
        c.fail('physical_operation_conflict')
    if record['state']!='applied': c.fail('physical_operation_unresolved')
    receipt=record['receipt']; c.object_fields(receipt,('operation_id','request_basis','result_basis','commit_id','write_txid'))
    c.uuid_text(receipt['commit_id'])
    result=record['result']; c.object_fields(result,_RESULT)
    for key in ('shipment_id','order_revision','shipment_revision'): c.integer(result[key],1)
    c.enum(result['order_state'],c.ORDER_STATES); c.enum(result['shipment_state'],core.SHIPMENT_STATES)
    c.basis_text(result['evidence_basis'])
    if type(result['ready']) is not bool: c.fail('physical_result_mismatch')
    if result['readiness_basis'] is not None: c.basis_text(result['readiness_basis'])
    expected_revision=1 if req['action']=='prepare_shipment' else req['expected_shipment_revision']+1
    if (result['action']!=req['action'] or result['shipment_id']!=record['shipment_id']
            or (req['shipment_id'] is not None and result['shipment_id']!=req['shipment_id'])
            or result['order_revision']!=req['expected_order_revision']+1 or result['shipment_revision']!=expected_revision):
        c.fail('physical_result_mismatch')
    if req['action'] in core.ACTIONS:
        previous=dict(identity=dict(contract=core.VERSION,operation_id=req['operation_id'],order_no=req['order_no'],
            actor_id=req['actor_id'],shipment_id=req['shipment_id'],action=req['action'],
            owner_scope=identity['owner_scope'],request_basis=req['request_basis']),result=result['core_result'])
        previous['receipt']=dict(operation_id=req['operation_id'],request_basis=req['request_basis'],
            result_basis=c.fingerprint(previous),commit_id=record['receipt']['commit_id'],
            write_txid=record['write_txid'],read_txid=read_txid)
        core._replay(previous,previous['identity'],req)
        if (result['order_state']!=result['core_result']['order_state'] or result['shipment_state']!=result['core_result']['shipment_state']
                or result['evidence_basis']!=req['evidence']['basis']): c.fail('physical_result_mismatch')
    else:
        if result['core_result'] is not None or result['shipment_state']!='준비': c.fail('physical_result_mismatch')
        prior_state=req['expected_order_state']
        next_state=('조립중' if req['action']=='record_preparation_event' and req['event_kind']=='assembly_started' and prior_state=='결제완료'
                    else '출고' if req['action']=='confirm_dispatch_ready' and prior_state in ('결제완료','조립중') else prior_state)
        if result['order_state']!=next_state: c.fail('physical_result_mismatch')
        if req['action']=='prepare_shipment':
            if result['ready'] or result['readiness_basis'] is not None or result['evidence_basis']!=c.fingerprint(req['lines']):
                c.fail('physical_result_mismatch')
        else:
            _evidence(req,dict(rule_basis=req['evidence']['rules_basis'],policy_basis=req['expected_policy_basis']))
            if result['evidence_basis']!=req['evidence']['basis']: c.fail('physical_result_mismatch')
        if req['action']=='record_preparation_event' and (result['ready'] or result['readiness_basis'] is not None): c.fail('physical_result_mismatch')
        if req['action']=='confirm_dispatch_ready' and (not result['ready'] or result['readiness_basis'] is None):
            c.fail('physical_result_mismatch')
        if req['action']=='confirm_dispatch_ready':
            ready=dict(operation_id=req['operation_id'],line_basis=c.fingerprint(req['lines']),policy_basis=req['expected_policy_basis'],
                rule_basis=req['evidence']['rules_basis'],prerequisites=req['prerequisites'],confirmed_at=req['evidence']['occurred_at'])
            if result['readiness_basis']!=c.fingerprint(ready): c.fail('physical_result_mismatch')
    if (c.uuid_text(receipt['operation_id'])!=req['operation_id'] or receipt['request_basis']!=req['request_basis']
            or c.integer(receipt['write_txid'],1)!=record['write_txid']
            or c.basis_text(receipt['result_basis'])!=c.fingerprint(dict(identity=identity,result=result))):
        c.fail('physical_result_mismatch')
    return deepcopy(result)


def _public(identity, result, pending):
    return dict(operation_id=identity['operation_id'],order_no=identity['order_no'],action=identity['action'],
        shipment_id=result['shipment_id'],order_state=result['order_state'],shipment_state=result['shipment_state'],
        ready=result['ready'],pending=pending)


def _response(identity, result, pending, action):
    return dict(action=action,pending_commit=pending,result=deepcopy(result),
                public=_public(identity,result,pending))


def _policy(value, req, *, compare=True):
    c.object_fields(value,('contract','policy_id','policy_basis','state','order_no','allowed_commands',
        'assembly_required','required_events','rule_basis','allowed_refund_states'))
    c.text(value['policy_id']); c.basis_text(value['rule_basis']); c.basis_text(value['policy_basis'])
    if (value['contract']!=POLICY_VERSION or value['state']!='confirmed' or value['order_no']!=req['order_no']
            or (compare and value['policy_basis']!=req['expected_policy_basis']) or type(value['assembly_required']) is not bool):
        c.fail('preparation_policy_unconfirmed')
    for key,choices in (('allowed_commands',PREPARATION),('required_events',('assembly_completed','inspection_recorded')),
                        ('allowed_refund_states',('none','requested','partial'))):
        values=value[key]
        if type(values) is not list or any(type(item) is not str for item in values) or len(values)!=len(set(values)):
            c.fail('preparation_policy_unconfirmed')
        for item in values: c.enum(item,choices)
    if (req['action'] in PREPARATION and req['action'] not in value['allowed_commands']) or (
            value['assembly_required'] and 'assembly_completed' not in value['required_events']):
        c.fail('preparation_policy_blocked')
    return deepcopy(value)


def _evidence(req, policy):
    proof=req['evidence']
    c.object_fields(proof,('contract','source','state','kind','order_no','shipment_id','actor_id',
        'occurred_at','reference','rules_basis','content_basis','basis'))
    kind=req['event_kind'] if req['action']=='record_preparation_event' else 'dispatch_ready'
    if (proof['contract']!=EVIDENCE_VERSION or proof['source']!='operator_record' or proof['state']!='confirmed'
            or proof['kind']!=kind or proof['order_no']!=req['order_no'] or c.integer(proof['shipment_id'],1)!=req['shipment_id']
            or c.integer(proof['actor_id'],1)!=req['actor_id'] or proof['rules_basis']!=policy['rule_basis']):
        c.fail('preparation_evidence_mismatch')
    c.text(proof['reference']); c.integer(proof['occurred_at']); c.basis_text(proof['rules_basis'])
    content=dict(lines=req['lines'],event_kind=req['event_kind'],quantities=req['quantities'],outcome=req['outcome'],
        prerequisites=req['prerequisites'],policy_basis=policy['policy_basis'],rule_basis=policy['rule_basis'])
    if (c.basis_text(proof['content_basis'])!=c.fingerprint(content) or c.basis_text(proof['basis'])!=
            c.fingerprint({key:value for key,value in proof.items() if key!='basis'})):
        c.fail('preparation_evidence_mismatch')
    return proof


def _origin(conn, row, now):
    bundle=money._read_order_bundle(conn,row['order_no'])
    if any(bundle[key]!=row[key] for key in ('order_id','snapshot','states','revision','owner_scope','order_state')):
        c.fail('physical_order_snapshot_changed')
    proof=dict(operation=bundle['approval_operation'],verification=bundle['approval_verification'],
        payment_id=bundle['approval_payment_id'],write_txid=bundle['approval_write_txid'],read_txid=money._txid(conn))
    if any(value is None for value in proof.values()): c.fail('original_sale_unconfirmed')
    money._committed(conn,dict(write_txid=proof['write_txid']))
    order=dict(order_no=row['order_no'],owner=deepcopy(row['owner_identity']),basis_id=money._basis(row,bundle['approved'],bundle['refunded']),
        revision=row['revision'],order_state=row['order_state'],total=row['total_amount'],approved_amount=bundle['approved'],
        refunded_amount=bundle['refunded'],lines=[{key:line[key] for key in ('line_id','product_code','qty')} for line in row['snapshot']['lines']],
        **row['states'])
    financial=[dict(item) for item in _sql(conn,'financial_history','''SELECT x.operation_id::text,o.order_no,x.kind,x.state
      FROM commerce_payment_operations x JOIN orders o USING(order_id) WHERE x.order_id=:oid
      ORDER BY x.operation_id FOR UPDATE OF x''',oid=row['order_id']).mappings().all()]
    if not financial: c.fail('financial_observation_required')
    source_id=proof['operation']['spec']['operation_id']
    keys={source_id+':allocate:'+line['line_id']:line['line_id'] for line in order['lines']}
    raw=_sql(conn,'sale_movements','''SELECT movement_id,product_code,movement_type,qty_delta,
      commerce_operation_id::text AS operation_id,commerce_effect_key AS effect_key
      FROM stock_movements WHERE ref_kind='order' AND ref_id=:oid AND commerce_operation_id IS NOT NULL
      ORDER BY movement_id FOR UPDATE''',oid=row['order_id']).mappings().all()
    movements=[]
    for item in raw:
        item=dict(item)
        if item.get('effect_key') not in keys: c.fail('sale_movement_scope_mismatch')
        movements.append(dict(item,order_no=row['order_no'],line_id=keys[item['effect_key']]))
    sale,sources=core._paid(order,proof,financial,movements,now)
    if _sql(conn,'legacy_refunds','SELECT refund_id,status FROM refunds WHERE order_id=:oid ORDER BY refund_id FOR UPDATE',
            oid=row['order_id']).mappings().all(): c.fail('legacy_refund_boundary')
    return order,proof,financial,movements,sale,sources


def _observations(conn, row, sources, sale, now):
    parents=[dict(item) for item in _sql(conn,'shipments','''SELECT shipment_id,order_id,revision,state,line_basis,
      carrier,tracking_no,tracking_evidence,handoff_evidence,delivery_evidence,readiness,readiness_operation_id::text,write_txid
      FROM commerce_shipments WHERE order_id=:oid ORDER BY shipment_id FOR UPDATE''',oid=row['order_id']).mappings().all()]
    cargo=[dict(item) for item in _sql(conn,'shipment_lines','''SELECT order_id,shipment_id,line_id,product_code,qty,sale_movement_id
      FROM commerce_shipment_lines WHERE order_id=:oid ORDER BY shipment_id,line_id FOR UPDATE''',oid=row['order_id']).mappings().all()]
    operations=[dict(item) for item in _sql(conn,'operations','''SELECT operation_id::text,order_id,shipment_id,contract,action,actor_id,
      owner_scope,request_basis,request,identity,state,revision,result,receipt,write_txid
      FROM commerce_physical_operations WHERE order_id=:oid ORDER BY operation_id FOR UPDATE''',oid=row['order_id']).mappings().all()]
    parent_by_id={}; ships=[]; seen=set(); used={line['line_id']:0 for line in sale}
    for item in parents:
        c.object_fields(item,('shipment_id','order_id','revision','state','line_basis','carrier','tracking_no','tracking_evidence',
            'handoff_evidence','delivery_evidence','readiness','readiness_operation_id','write_txid'))
        ship_id=c.integer(item['shipment_id'],1); c.integer(item['order_id'],1); c.integer(item['revision'],1); c.integer(item['write_txid'],1)
        if item['order_id']!=row['order_id'] or ship_id in parent_by_id: c.fail('shipment_scope_mismatch')
        parent_by_id[ship_id]=item
        lines=[]
        for line in cargo:
            c.object_fields(line,('order_id','shipment_id','line_id','product_code','qty','sale_movement_id'))
            c.integer(line['order_id'],1); c.integer(line['shipment_id'],1)
            if line['shipment_id']==ship_id:
                if line['order_id']!=row['order_id']: c.fail('shipment_scope_mismatch')
                lines.append({key:line[key] for key in ('line_id','product_code','qty','sale_movement_id')})
        lines=core._lines(lines)
        if c.basis_text(item['line_basis'])!=c.fingerprint(lines): c.fail('shipment_content_changed')
        ship=dict(shipment_id=ship_id,order_no=row['order_no'],revision=item['revision'],state=item['state'],lines=lines,
                  **{key:item[key] for key in ('carrier','tracking_no','tracking_evidence','handoff_evidence','delivery_evidence')})
        ships.append(ship)
        for line in lines:
            if line['line_id'] not in used: c.fail('shipment_allocation_scope_mismatch')
            used[line['line_id']]+=line['qty']; seen.add((ship_id,line['line_id']))
    if len(seen)!=len(cargo): c.fail('shipment_line_history_incomplete')
    if ships: core._shipments(ships,row['order_no'],sources,now)
    if any(used[line['line_id']]>line['qty'] for line in sale): c.fail('shipment_quantity_exceeded')
    operation_ids=set(); read_txid=money._txid(conn)
    for op in operations:
        c.object_fields(op,_OP); op_id=c.uuid_text(op['operation_id'])
        if op_id in operation_ids or c.integer(op['order_id'],1)!=row['order_id'] or op['shipment_id'] not in parent_by_id:
            c.fail('physical_operation_scope_mismatch')
        operation_ids.add(op_id)
        # Unknown/new contract versions also fail closed; future return tables
        # must not be represented as an empty shipment/operation history.
        if op['state']!='applied': c.fail('physical_operation_unresolved')
        preparation=op['contract']==VERSION
        if not preparation and op['contract']!=core.VERSION: c.fail('physical_contract_unconnected')
        previous=_normalize(op['request'],now,preparation)
        identity=_identity(previous,row,preparation)
        money._committed(conn,op); _stored(op,previous,identity,row,read_txid)
    by_operation={op['operation_id']:op for op in operations}
    for item in parents:
        ready=item['readiness']; ready_id=item['readiness_operation_id']
        if (ready is None)!=(ready_id is None): c.fail('readiness_reference_mismatch')
        if ready is not None:
            c.object_fields(ready,('operation_id','line_basis','policy_basis','rule_basis','prerequisites','confirmed_at','basis'))
            c.integer(ready['confirmed_at']); c.uuid_text(ready['operation_id'])
            for key in ('line_basis','policy_basis','rule_basis','basis'): c.basis_text(ready[key])
            if _refs(ready['prerequisites'])!=ready['prerequisites']: c.fail('readiness_reference_mismatch')
            referenced=by_operation.get(c.uuid_text(ready_id))
            if (referenced is None or referenced['action']!='confirm_dispatch_ready' or referenced['shipment_id']!=item['shipment_id']
                    or referenced['result']['readiness_basis']!=ready['basis'] or ready['operation_id']!=ready_id
                    or ready['line_basis']!=item['line_basis']): c.fail('readiness_reference_mismatch')
            if c.basis_text(ready['basis'])!=c.fingerprint({key:value for key,value in ready.items() if key!='basis'}):
                c.fail('readiness_reference_mismatch')
    return parent_by_id,ships,operations,used


def _latest(operations, policy, line_ids):
    latest={}
    for op in operations:
        req=op['request']
        if op['action']!='record_preparation_event': continue
        proof=req['evidence']
        # Keep the latest observed event even if its policy is stale/rejected.
        # Falling back to an older accepted event would hide a later failure.
        for metric in req['quantities']:
            if metric['line_id'] not in line_ids: continue
            key=(req['event_kind'],metric['line_id']); stamp=(proof['occurred_at'],op['operation_id'])
            if key in latest and latest[key]['stamp'][0]==stamp[0]: c.fail('ambiguous_preparation_history')
            if key not in latest or latest[key]['stamp']<stamp:
                latest[key]=dict(stamp=stamp,qty=metric['observed_qty'],operation=op)
    return latest


def _readiness(ship_id, lines, parents, ships, operations, policy):
    latest=_latest(operations,policy,{line['line_id'] for line in lines}); refs={}; used={line['line_id']:0 for line in lines}
    for ship in ships:
        if ship['shipment_id']==ship_id or parents[ship['shipment_id']]['readiness'] is not None or ship['state']!='준비':
            for line in ship['lines']:
                if line['line_id'] in used: used[line['line_id']]+=line['qty']
    for kind in policy['required_events']:
        for line in lines:
            observation=latest.get((kind,line['line_id']))
            if observation is None: c.fail('dispatch_evidence_unready')
            op=observation['operation']; req=op['request']
            if (req['expected_policy_basis']!=policy['policy_basis'] or req['evidence']['rules_basis']!=policy['rule_basis']
                    or req['outcome'] not in ('recorded','accepted') or observation['qty']<used[line['line_id']]):
                c.fail('dispatch_evidence_unready')
            if policy['assembly_required']:
                start=latest.get(('assembly_started',line['line_id'])); complete=latest.get(('assembly_completed',line['line_id']))
                if (start is None or complete is None or start['stamp'][0]>complete['stamp'][0]
                        or start['qty']<complete['qty'] or start['operation']['request']['expected_policy_basis']!=policy['policy_basis']
                        or start['operation']['request']['evidence']['rules_basis']!=policy['rule_basis']
                        or (kind=='inspection_recorded' and observation['stamp'][0]<complete['stamp'][0])):
                    c.fail('dispatch_evidence_unready')
            refs[op['operation_id']]=dict(operation_id=op['operation_id'],evidence_basis=req['evidence']['basis'])
    return sorted(refs.values(),key=lambda ref:ref['operation_id'])


def _event(req, policy, operations, sources):
    proof=_evidence(req,policy); latest=_latest(operations,policy,{line['line_id'] for line in req['lines']})
    for metric in req['quantities']:
        line=metric['line_id']; qty=metric['observed_qty']; kind=req['event_kind']
        if qty>-sources[line]['qty_delta']: c.fail('preparation_quantity_exceeded')
        prior=latest.get((kind,line))
        if prior is not None and (proof['occurred_at']<=prior['stamp'][0] or qty<prior['qty']):
            c.fail('preparation_observation_regressed')
        prerequisite='assembly_started' if kind=='assembly_completed' else ('assembly_completed' if kind=='inspection_recorded' and policy['assembly_required'] else None)
        if prerequisite is not None:
            earlier=latest.get((prerequisite,line))
            if (earlier is None or earlier['qty']<qty or earlier['stamp'][0]>proof['occurred_at']
                    or earlier['operation']['request']['expected_policy_basis']!=policy['policy_basis']
                    or earlier['operation']['request']['evidence']['rules_basis']!=policy['rule_basis']):
                c.fail('preparation_prerequisite_unready')
    return proof


def _persist(conn, req, identity, row, ship, result, *, created=False):
    txid=money._txid(conn)
    receipt=dict(operation_id=req['operation_id'],request_basis=req['request_basis'],
        result_basis=c.fingerprint(dict(identity=identity,result=result)),commit_id=str(uuid4()),write_txid=txid)
    _sql(conn,'insert_operation','''INSERT INTO commerce_physical_operations(operation_id,order_id,shipment_id,contract,
      action,actor_id,owner_scope,request_basis,request,identity,state,revision,result,receipt,write_txid)
      VALUES(CAST(:id AS uuid),:oid,:sid,:contract,:action,:actor,:scope,:basis,CAST(:request AS jsonb),
      CAST(:identity AS jsonb),'applied',1,CAST(:result AS jsonb),CAST(:receipt AS jsonb),txid_current())''',
      id=req['operation_id'],oid=row['order_id'],sid=ship['shipment_id'],contract=identity['contract'],action=req['action'],
      actor=req['actor_id'],scope=identity['owner_scope'],basis=req['request_basis'],request=money._json(req),
      identity=money._json(identity),result=money._json(result),receipt=money._json(receipt))
    if not created:
        changed=_sql(conn,'update_shipment','''UPDATE commerce_shipments SET revision=revision+1,state=:state,
          carrier=:carrier,tracking_no=:tracking,tracking_evidence=CAST(:tracking_evidence AS jsonb),
          handoff_evidence=CAST(:handoff_evidence AS jsonb),delivery_evidence=CAST(:delivery_evidence AS jsonb),
          readiness=CAST(:readiness AS jsonb),readiness_operation_id=CAST(:ready_id AS uuid),write_txid=txid_current()
          WHERE order_id=:oid AND shipment_id=:sid AND revision=:revision''',oid=row['order_id'],sid=ship['shipment_id'],
          revision=ship['revision'],state=ship['state'],carrier=ship['carrier'],tracking=ship['tracking_no'],
          tracking_evidence=money._json(ship['tracking_evidence']) if ship['tracking_evidence'] is not None else None,
          handoff_evidence=money._json(ship['handoff_evidence']) if ship['handoff_evidence'] is not None else None,
          delivery_evidence=money._json(ship['delivery_evidence']) if ship['delivery_evidence'] is not None else None,
          readiness=money._json(ship['readiness']) if ship['readiness'] is not None else None,
          ready_id=ship['readiness_operation_id'])
        if changed.rowcount!=1: c.fail('shipment_revision_conflict')
    money._update_order(conn,row,deepcopy(row['states']))
    changed=_sql(conn,'order_status','''UPDATE orders SET status=:next WHERE order_id=:oid AND status=:previous''',
        oid=row['order_id'],previous=row['order_state'],next=result['order_state'])
    if changed.rowcount!=1: c.fail('physical_order_state_conflict')
    _sql(conn,'order_event','''INSERT INTO order_events(order_id,from_state,to_state,actor)
      VALUES(:oid,:previous,:next,:actor)''',oid=row['order_id'],previous=row['order_state'],next=result['order_state'],
      actor='physical:'+str(req['actor_id']))
    return _response(identity,result,True,'read_physical_result_after_commit')


def _apply(conn, value, *, policy, fulfillment_policy, authorize, now, preparation):
    now=c.integer(now); req=_normalize(value,now,preparation)
    grant=_authorize(authorize,req,now,preparation)
    previous=_operation(conn,req['operation_id']); discovered=money._order(conn,req['order_no'])
    identity=_identity(req,discovered,preparation)
    if previous is not None:
        money._committed(conn,previous)
        result=_stored(previous,req,identity,discovered,money._txid(conn))
        if _authorize(authorize,req,now,preparation)!=grant: c.fail('physical_authorization_changed')
        return _response(identity,result,False,'read_existing_result')
    row,_products=money._locked_order(conn,req['order_no'])
    if row['order_id']!=discovered['order_id'] or _identity(req,row,preparation)!=identity:
        c.fail('physical_order_scope_changed')
    # Same-order locks serialize all adapters; PK/DB guards retain identities.
    if _sql(conn,'financial_uuid','SELECT operation_id::text FROM commerce_payment_operations WHERE operation_id=CAST(:id AS uuid)',
            id=req['operation_id']).mappings().first() is not None: c.fail('physical_operation_must_be_independent')
    order,approval,financial,movements,sale,sources=_origin(conn,row,now)
    if order['basis_id']!=req['expected_order_basis'] or c.integer(row['revision'],1)!=req['expected_order_revision']:
        c.fail('physical_order_changed')
    if preparation and row['order_state']!=req['expected_order_state']: c.fail('physical_order_changed')
    parents,ships,operations,used=_observations(conn,row,sources,sale,now)
    if req['action']!='prepare_shipment':
        ship=deepcopy(parents.get(req['shipment_id']))
        if ship is None or ship['revision']!=req['expected_shipment_revision']: c.fail('physical_shipment_changed')
        actual=next(item for item in ships if item['shipment_id']==req['shipment_id'])
        if actual['lines']!=req['lines']: c.fail('shipment_content_changed')
    for line in req['lines']:
        source=sources.get(line['line_id'])
        if source is None or (source['movement_id'],source['product_code'])!=(line['sale_movement_id'],line['product_code']):
            c.fail('shipment_allocation_scope_mismatch')
    created=False; core_result=None; readiness_basis=None
    if preparation:
        confirmed=_policy(policy,req)
        if order['refund_state'] not in confirmed['allowed_refund_states']: c.fail('preparation_refund_policy_blocked')
        if order['order_state'] not in ('결제완료','조립중','출고','배송중'): c.fail('preparation_state_blocked')
        state=order['order_state']; ready=False
        if req['action']=='prepare_shipment':
            for line in req['lines']:
                if used[line['line_id']]+line['qty']>-sources[line['line_id']]['qty_delta']: c.fail('shipment_quantity_exceeded')
            line_basis=c.fingerprint(req['lines'])
            sid=c.integer(_sql(conn,'insert_shipment','''INSERT INTO commerce_shipments(order_id,revision,state,line_basis,write_txid)
              VALUES(:oid,1,'준비',:basis,txid_current()) RETURNING shipment_id''',oid=row['order_id'],basis=line_basis).scalar_one(),1)
            ship=dict(shipment_id=sid,order_id=row['order_id'],revision=1,state='준비',line_basis=line_basis,
                carrier=None,tracking_no=None,tracking_evidence=None,handoff_evidence=None,delivery_evidence=None,
                readiness=None,readiness_operation_id=None,write_txid=money._txid(conn))
            for line in req['lines']:
                _sql(conn,'insert_line','''INSERT INTO commerce_shipment_lines(order_id,shipment_id,line_id,product_code,qty,sale_movement_id)
                  VALUES(:oid,:sid,:line,:code,:qty,:movement)''',oid=row['order_id'],sid=sid,line=line['line_id'],
                  code=line['product_code'],qty=line['qty'],movement=line['sale_movement_id'])
            created=True; evidence_basis=line_basis
        else:
            if ship['state']!='준비': c.fail('preparation_state_blocked')
            if req['action']=='record_preparation_event':
                proof=_event(req,confirmed,operations,sources)
                ship.update(readiness=None,readiness_operation_id=None)
                if req['event_kind']=='assembly_started' and state=='결제완료': state='조립중'
            else:
                if state=='결제완료' and confirmed['assembly_required']: c.fail('assembly_policy_unready')
                refs=_readiness(ship['shipment_id'],req['lines'],parents,ships,operations,confirmed)
                if refs!=req['prerequisites']: c.fail('dispatch_references_changed')
                proof=_evidence(req,confirmed)
                if any(proof['occurred_at']<op['request']['evidence']['occurred_at'] for op in operations
                       if op['operation_id'] in {ref['operation_id'] for ref in refs}): c.fail('preparation_evidence_time_mismatch')
                readiness=dict(operation_id=req['operation_id'],line_basis=ship['line_basis'],policy_basis=confirmed['policy_basis'],
                    rule_basis=confirmed['rule_basis'],prerequisites=refs,confirmed_at=proof['occurred_at'])
                readiness['basis']=c.fingerprint(readiness); readiness_basis=readiness['basis']
                ship.update(readiness=readiness,readiness_operation_id=req['operation_id']); ready=True
                if state in ('결제완료','조립중'): state='출고'
            evidence_basis=proof['basis']
    else:
        if req['action']=='handoff':
            confirmed=_policy(policy,req,compare=False); readiness=ship['readiness']
            if readiness is None or readiness['policy_basis']!=confirmed['policy_basis'] or readiness['rule_basis']!=confirmed['rule_basis']:
                c.fail('dispatch_readiness_unready')
            refs=_readiness(ship['shipment_id'],req['lines'],parents,ships,operations,confirmed)
            if refs!=readiness['prerequisites'] or req['evidence']['occurred_at']<readiness['confirmed_at']:
                c.fail('dispatch_readiness_changed')
        plan=core.plan_fulfillment(req,order=order,approval=approval,active_operations=financial,movements=movements,
            shipments=ships,policy=fulfillment_policy,authorization=grant,now=now)
        core_result=deepcopy(plan['result']); state=core_result['order_state']; evidence_basis=core_result['evidence_basis']
        ship['state']=core_result['shipment_state']
        key={'record_tracking':'tracking_evidence','handoff':'handoff_evidence','deliver':'delivery_evidence'}[req['action']]
        ship[key]=deepcopy(req['evidence'])
        if req['action']=='record_tracking': ship.update(carrier=req['carrier'],tracking_no=req['tracking_no'])
        ready=ship['readiness'] is not None
        if ready: readiness_basis=ship['readiness']['basis']
    if _authorize(authorize,req,now,preparation)!=grant: c.fail('physical_authorization_changed')
    next_order=c.integer(row['revision']+1,1); next_ship=c.integer(ship['revision'] if created else ship['revision']+1,1)
    result=dict(action=req['action'],shipment_id=ship['shipment_id'],order_revision=next_order,shipment_revision=next_ship,
        order_state=state,shipment_state=ship['state'],ready=ready,evidence_basis=evidence_basis,
        readiness_basis=readiness_basis,core_result=core_result)
    return _persist(conn,req,identity,row,ship,result,created=created)


@money._atomic
def execute_preparation(conn, request, *, policy, authorize, now):
    """Three narrow preparation commands. No checklist/responsibility defaults."""
    return _apply(conn,request,policy=policy,fulfillment_policy=None,authorize=authorize,now=now,preparation=True)


@money._atomic
def execute_fulfillment(conn, request, *, fulfillment_policy, authorize, now, preparation_policy=None):
    """Persist the frozen core's tracking/handoff/delivery; never deduct again."""
    return _apply(conn,request,policy=preparation_policy,fulfillment_policy=fulfillment_policy,
                  authorize=authorize,now=now,preparation=False)


@money._atomic
def read_result(conn, request, *, authorize, now, preparation=True):
    """Fresh caller TX, current action permission and immutable stored result only."""
    if type(preparation) is not bool: c.fail('invalid_read_contract')
    now=c.integer(now); req=_normalize(request,now,preparation); _authorize(authorize,req,now,preparation)
    record=_operation(conn,req['operation_id'])
    if record is None: c.fail('physical_operation_not_found')
    row=money._order(conn,req['order_no']); identity=_identity(req,row,preparation)
    money._committed(conn,record); result=_stored(record,req,identity,row,money._txid(conn))
    return _response(identity,result,False,'stored_physical_result')
