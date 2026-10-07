"""Caller-owned physical return storage. No HTTP/engine/provider/business defaults.

Observation, inspection, policy and authorization callbacks are trusted SERVER
dependencies, synchronous/no-network and cannot change the caller transaction.
All writes remain pending until a separate transaction reads the stored result.
"""
from copy import deepcopy
from uuid import uuid4

from . import commerce_contract as c
from . import commerce_writer as money
from . import commerce_physical_return_core as core
from . import commerce_physical_return_read as read

INTAKE_VERSION = 'commerce_physical_return_intake_v1'
INTAKE = ('create_case', 'record_collection', 'record_receipt')
ACTIONS = INTAKE + core.ACTIONS
COMMAND = ('operation_id', 'order_no', 'action', 'return_id', 'expected_order_basis',
           'expected_order_revision', 'expected_return_revision', 'expected_history_token', 'expected_policy_basis', 'lines')
RESULT = ('action', 'return_id', 'order_revision', 'return_revision', 'lines', 'evidence_basis', 'core_result')
RECEIPT = ('operation_id', 'request_basis', 'result_basis', 'storage_basis', 'core_result_basis', 'commit_id', 'write_txid')
OBSERVATION = ('source', 'state', 'action', 'order_no', 'actor_id', 'occurred_at', 'reference', 'targets_basis', 'basis')


def _command(value):
    c.object_fields(value, COMMAND); result = deepcopy(value)
    result['operation_id'] = c.uuid_text(value['operation_id']); read.shipping_read.order_no(value['order_no'])
    c.enum(value['action'], ACTIONS); c.integer(value['expected_order_revision'], 1)
    for key in ('expected_order_basis', 'expected_history_token'): c.basis_text(value[key])
    if value['action'] == 'create_case':
        if value['return_id'] is not None or value['expected_return_revision'] is not None: c.fail('unexpected_return_field')
        if type(value['lines']) is not list or not value['lines']: c.fail('return_lines_required')
        seen = set()
        for line in value['lines']:
            c.object_fields(line, ('shipment_id', 'line_id', 'qty'))
            c.integer(line['shipment_id'], 1); c.text(line['line_id']); c.integer(line['qty'], 1, c.MAX_QUANTITY)
            key = (line['shipment_id'], line['line_id'])
            if key in seen: c.fail('duplicate_return_line')
            seen.add(key)
        result['lines'] = sorted(result['lines'], key=lambda line: (line['shipment_id'], line['line_id']))
    else:
        c.integer(value['return_id'], 1); c.integer(value['expected_return_revision'], 1)
        result['lines'] = core._quantities(value['lines'])
    if value['action'] in INTAKE:
        if value['expected_policy_basis'] is not None: c.fail('unexpected_return_field')
    else:
        c.basis_text(value['expected_policy_basis'])
    return result


def _storage_basis(wire, request):
    return c.fingerprint(dict(wire_intent=wire, request=request))


def _check_record(record, row):
    c.object_fields(record, read.OP); wire = _command(record['wire_intent'])
    c.integer(record['revision'], 1); c.integer(record['write_txid'], 1); c.integer(record['actor_id'], 1)
    c.integer(record['return_id'], 1); c.enum(record['state'], ('prepared', 'processing', 'unknown', 'applied'))
    contract = INTAKE_VERSION if wire['action'] in INTAKE else core.VERSION
    expected = dict(contract=contract, operation_id=wire['operation_id'], actor_id=record['actor_id'],
        order_no=wire['order_no'], return_id=record['return_id'], action=wire['action'],
        owner_scope=row['owner_scope'], request_basis=record['request_basis'])
    if (wire != record['wire_intent'] or record['order_id'] != row['order_id'] or wire['order_no'] != row['order_no']
            or record['operation_id'] != wire['operation_id'] or record['contract'] != contract
            or record['action'] != wire['action'] or record['owner_scope'] != c.fingerprint(c.owner_identity(row['owner_identity']))
            or record['identity'] != expected or (wire['return_id'] is not None and wire['return_id'] != record['return_id'])):
        c.fail('return_operation_scope_mismatch')
    c.basis_text(record['request_basis'])
    request = record['request']
    if wire['action'] in INTAKE:
        c.object_fields(request, ('actor_id', 'command', 'source_lines', 'observation', 'proofs', 'request_basis'))
        if request['command'] != wire or request['actor_id'] != record['actor_id']:
            c.fail('return_operation_conflict')
        basis = c.fingerprint({key: value for key, value in request.items() if key != 'request_basis'})
        if request['request_basis'] != basis or basis != record['request_basis']: c.fail('return_request_basis_mismatch')
        sources = request['source_lines']
        if type(sources) is not list or len(sources) != len(wire['lines']): c.fail('return_operation_conflict')
        for line in sources:
            fields = ('shipment_id', 'line_id', 'qty', 'sale_movement_id', 'product_code', 'return_id', 'return_line_id')
            if wire['action'] != 'create_case': fields = tuple(key for key in read.LINE if key != 'order_id') + ('qty',)
            c.object_fields(line, fields)
            for key in ('shipment_id', 'sale_movement_id', 'product_code', 'return_id', 'return_line_id'):
                c.integer(line[key], 1)
            c.integer(line['qty'], 1, c.MAX_QUANTITY); c.text(line['line_id'])
            if line['return_id'] != record['return_id']: c.fail('return_operation_conflict')
        keys = ('shipment_id', 'line_id', 'qty') if wire['action'] == 'create_case' else ('return_line_id', 'qty')
        if [{key: line[key] for key in keys} for line in sources] != wire['lines']: c.fail('return_operation_conflict')
        _check_observation(request['observation'], wire, record['actor_id'], request['source_lines'], c.MAX_INTEGER)
    else:
        c.object_fields(request, ('core_request', 'proofs', 'observation'))
        internal = core._request(request['core_request'])
        if (internal['actor_id'] != record['actor_id'] or internal['return_id'] != record['return_id']
                or internal['order_no'] != wire['order_no'] or internal['action'] != wire['action']
                or internal['request_basis'] != record['request_basis'] or internal['lines'] != wire['lines']
                or any(internal[key] != wire[key] for key in ('expected_order_basis', 'expected_order_revision',
                    'expected_return_revision', 'expected_policy_basis'))):
            c.fail('return_operation_conflict')
    if type(request['proofs']) is not dict: c.fail('return_evidence_history_mismatch')
    expected_proofs = set() if wire['action'] == 'create_case' else {str(line['return_line_id']) for line in wire['lines']}
    if set(request['proofs']) != expected_proofs: c.fail('return_evidence_history_mismatch')
    if wire['action'] in ('record_collection', 'record_receipt'):
        kind = 'collect' if wire['action'] == 'record_collection' else 'receive'
        for line in request['source_lines']:
            proof = request['proofs'][str(line['return_line_id'])]
            core._evidence(proof, kind=kind, order_no=wire['order_no'], return_id=record['return_id'],
                           line=line, quantities=dict(qty=line['qty']), now=c.MAX_INTEGER, actor_id=record['actor_id'])
            if (proof['occurred_at'], proof['reference']) != (request['observation']['occurred_at'], request['observation']['reference']):
                c.fail('return_evidence_history_mismatch')
    if record['state'] != 'applied' and (record['result'] is not None or record['receipt'] is not None):
        c.fail('return_result_unconfirmed')
    return wire


def _stored(record, row, read_txid):
    wire = _check_record(record, row)
    if record['state'] != 'applied' or c.integer(record['write_txid'], 1) == c.integer(read_txid, 1):
        c.fail('return_result_unconfirmed')
    result = record['result']; receipt = record['receipt']
    c.object_fields(result, RESULT); c.object_fields(receipt, RECEIPT); c.uuid_text(receipt['commit_id'])
    expected_revision = 1 if wire['action'] == 'create_case' else wire['expected_return_revision'] + 1
    if (result['action'] != wire['action'] or result['return_id'] != record['return_id']
            or c.integer(result['order_revision'], 1) != wire['expected_order_revision'] + 1
            or c.integer(result['return_revision'], 1) != expected_revision
            or receipt['operation_id'] != record['operation_id'] or receipt['request_basis'] != record['request_basis']
            or receipt['write_txid'] != record['write_txid']
            or receipt['storage_basis'] != _storage_basis(wire, record['request'])
            or receipt['result_basis'] != c.fingerprint(dict(identity=record['identity'], result=result))):
        c.fail('return_result_reference_mismatch')
    c.basis_text(result['evidence_basis']); normalized_lines = core._quantities(result['lines'])
    if normalized_lines != result['lines']: c.fail('return_result_reference_mismatch')
    if wire['action'] in INTAKE:
        if result['core_result'] is not None or receipt['core_result_basis'] is not None: c.fail('return_result_reference_mismatch')
        sources = record['request']['source_lines']
        if normalized_lines != sorted([dict(return_line_id=line['return_line_id'], qty=line['qty']) for line in sources],
                                      key=lambda line: line['return_line_id']): c.fail('return_result_reference_mismatch')
        if result['evidence_basis'] != record['request']['observation']['basis']: c.fail('return_evidence_history_mismatch')
    else:
        internal = record['request']['core_request']; core_result = result['core_result']
        if (result['lines'] != internal['lines'] or result['evidence_basis'] != internal['evidence_basis']
                or receipt['core_result_basis'] != c.fingerprint(dict(identity=record['identity'], result=core_result))):
            c.fail('return_result_reference_mismatch')
        proof_refs = [dict(return_line_id=line['return_line_id'],
                           inspection_basis=record['request']['proofs'][str(line['return_line_id'])]['basis']) for line in internal['lines']]
        if c.fingerprint(proof_refs) != internal['evidence_basis']: c.fail('return_evidence_history_mismatch')
        core._replay(dict(identity=record['identity'], result=core_result,
            receipt=dict(operation_id=record['operation_id'], request_basis=record['request_basis'],
                result_basis=receipt['core_result_basis'], commit_id=receipt['commit_id'],
                write_txid=record['write_txid'], read_txid=read_txid)), record['identity'], internal)
    return deepcopy(result)


def _targets(lines, action):
    fields = ('shipment_id', 'line_id', 'sale_movement_id', 'product_code', 'qty')
    if action != 'create_case': fields += ('return_line_id', 'return_id')
    return [{key: line[key] for key in fields} for line in lines]


def _check_observation(observation, cmd, actor_id, lines, now):
    c.object_fields(observation, OBSERVATION)
    if (observation['source'] != 'operator_record' or observation['state'] != 'confirmed'
            or observation['action'] != cmd['action'] or observation['order_no'] != cmd['order_no']
            or c.integer(observation['actor_id'], 1) != actor_id or c.integer(observation['occurred_at']) > now
            or observation['targets_basis'] != c.fingerprint(_targets(lines, cmd['action']))
            or observation['basis'] != c.fingerprint({key: value for key, value in observation.items() if key != 'basis'})):
        c.fail('return_observation_unconfirmed')
    c.text(observation['reference'])
    return deepcopy(observation)


def _same_tx(conn, txid):
    if money._txid(conn) != txid: c.fail('caller_transaction_changed')


def _lock_children(conn, oid):
    # The existing whole-products/order locks are acquired before these.
    for tag, table, order in (
            ('lock_returns', 'commerce_return_cases', 'return_id'),
            ('lock_lines', 'commerce_return_lines', 'return_id,return_line_id'),
            ('lock_operations', 'commerce_return_operations', 'operation_id'),
            ('lock_effects', 'commerce_return_restoration_effects', 'effect_key'),
            ('lock_financial', 'commerce_payment_operations', 'operation_id'),
            ('lock_shipments', 'commerce_shipments', 'shipment_id'),
            ('lock_cargo', 'commerce_shipment_lines', 'shipment_id,line_id')):
        read._sql(conn, tag, 'SELECT * FROM ' + table + ' WHERE order_id=:oid ORDER BY ' + order + ' FOR UPDATE',
                  oid=oid).mappings().all()


def _existing(conn, cmd, grant, row, authorize, now):
    previous = read._operation(conn, cmd['operation_id'])
    if previous is None: return None
    if previous['wire_intent'] != cmd or previous['actor_id'] != grant['actor']['operator_id']:
        c.fail('return_operation_conflict')
    money._committed(conn, row, previous)
    result = _stored(previous, row, money._txid(conn))
    if read._authorize(authorize, cmd['order_no'], cmd['action'], cmd['return_id'], now, previous['actor_id']) != grant:
        c.fail('return_authorization_changed')
    return dict(action='read_existing_result', pending_commit=False, pending=False, result=result,
                operation_id=previous['operation_id'])


def _persist(conn, cmd, actor_id, row, return_id, request, result):
    txid = money._txid(conn); contract = INTAKE_VERSION if cmd['action'] in INTAKE else core.VERSION
    identity = dict(contract=contract, operation_id=cmd['operation_id'], actor_id=actor_id,
        order_no=cmd['order_no'], return_id=return_id, action=cmd['action'], owner_scope=row['owner_scope'], request_basis=request['request_basis']
        if cmd['action'] in INTAKE else request['core_request']['request_basis'])
    receipt = dict(operation_id=cmd['operation_id'], request_basis=identity['request_basis'],
        result_basis=c.fingerprint(dict(identity=identity, result=result)), storage_basis=_storage_basis(cmd, request),
        core_result_basis=c.fingerprint(dict(identity=identity, result=result['core_result'])) if result['core_result'] else None,
        commit_id=str(uuid4()), write_txid=txid)
    read._sql(conn, 'insert_operation', '''INSERT INTO commerce_return_operations(operation_id,order_id,return_id,
        contract,action,actor_id,owner_scope,wire_intent,request_basis,request,identity,state,revision,result,receipt,write_txid)
        VALUES(CAST(:id AS uuid),:oid,:rid,:contract,:action,:actor,:scope,CAST(:wire AS jsonb),:basis,
        CAST(:request AS jsonb),CAST(:identity AS jsonb),'applied',1,CAST(:result AS jsonb),CAST(:receipt AS jsonb),txid_current())''',
        id=cmd['operation_id'], oid=row['order_id'], rid=return_id, contract=contract, action=cmd['action'], actor=actor_id,
        scope=row['owner_scope'], wire=money._json(cmd), basis=identity['request_basis'], request=money._json(request),
        identity=money._json(identity), result=money._json(result), receipt=money._json(receipt))
    money._update_order(conn, row, deepcopy(row['states']))
    return deepcopy(dict(action='read_return_result_after_commit', pending_commit=True, pending=True,
                         operation_id=cmd['operation_id'], result=result))


def _execute(conn, command, *, authorize, now, observe=None, policy=None, inspect=None):
    cmd = _command(command); now = c.integer(now); txid = money._txid(conn)
    grant = read._authorize(authorize, cmd['order_no'], cmd['action'], cmd['return_id'], now)
    actor_id = grant['actor']['operator_id']; row = money._order(conn, cmd['order_no'])
    previous = _existing(conn, cmd, grant, row, authorize, now)
    if previous is not None: return previous
    read._sql(conn, 'uuid_lock', 'SELECT pg_advisory_xact_lock(hashtext(:id),2)', id=cmd['operation_id'])
    row, _products = money._locked_order(conn, cmd['order_no']); _lock_children(conn, row['order_id'])
    previous = _existing(conn, cmd, grant, row, authorize, now)
    if previous is not None: return previous
    collision = read._sql(conn, 'foreign_uuid', '''SELECT operation_id FROM commerce_payment_operations
        WHERE operation_id=CAST(:id AS uuid) UNION ALL SELECT operation_id FROM commerce_physical_operations
        WHERE operation_id=CAST(:id AS uuid)''', id=cmd['operation_id']).mappings().all()
    if collision: c.fail('physical_operation_must_be_independent')
    bundle = read._load(conn, cmd['order_no'], now)
    if any(bundle['row'][key] != row[key] for key in ('order_id', 'revision', 'snapshot', 'states', 'owner_scope')):
        c.fail('return_order_changed')
    if (bundle['order']['basis_id'] != cmd['expected_order_basis'] or row['revision'] != cmd['expected_order_revision']
            or bundle['token'] != cmd['expected_history_token']): c.fail('return_history_changed')
    case = next((case for case in bundle['returns'] if case['return_id'] == cmd['return_id']), None)
    if cmd['action'] != 'create_case' and (case is None or case['revision'] != cmd['expected_return_revision']):
        c.fail('return_revision_changed')
    if any(op['state'] != 'applied' and op['return_id'] == cmd['return_id'] for op in bundle['operations'].values()):
        c.fail('return_operation_unresolved')
    sources = []; proofs = {}; observation = None; plan = None
    if cmd['action'] == 'create_case':
        for requested in cmd['lines']:
            ship = next((ship for ship in bundle['shipments'] if ship['shipment_id'] == requested['shipment_id']), None)
            line = next((line for line in ship['lines'] if line['line_id'] == requested['line_id']), None) if ship else None
            if line is None: c.fail('return_shipment_scope_mismatch')
            consumed = sum(line['claimed_qty'] for line in bundle['lines'].values()
                           if (line['shipment_id'], line['line_id']) == (requested['shipment_id'], requested['line_id']))
            if requested['qty'] > line['qty'] - consumed: c.fail('return_quantity_exceeded')
            sources.append(dict(requested, sale_movement_id=line['sale_movement_id'], product_code=line['product_code']))
    else:
        for requested in cmd['lines']:
            line = bundle['lines'].get(requested['return_line_id'])
            if line is None or line['return_id'] != cmd['return_id']: c.fail('return_line_scope_mismatch')
            sources.append(dict(line, qty=requested['qty']))
    if cmd['action'] in INTAKE:
        if not callable(observe): c.fail('return_observation_unconnected')
        observation = _check_observation(observe(conn, order_no=cmd['order_no'], action=cmd['action'],
            actor_id=actor_id, targets=deepcopy(_targets(sources, cmd['action'])), now=now), cmd, actor_id, sources, now)
        _same_tx(conn, txid)
        if cmd['action'] != 'create_case':
            kind, field, qtyfield, capfield = (('collect', 'collection_evidence', 'collected_qty', 'claimed_qty')
                if cmd['action'] == 'record_collection' else ('receive', 'receipt_evidence', 'received_qty', 'collected_qty'))
            proposed = deepcopy(bundle['returns'])
            for source in sources:
                if not source[qtyfield] < source['qty'] <= source[capfield]: c.fail('return_quantity_inconsistent')
                # Changing upstream counts after downstream evidence would invalidate its scope.
                downstream = 'received_qty' if kind == 'collect' else 'inspected_qty'
                if source[downstream] != 0: c.fail('return_downstream_evidence_exists')
                previous_proof = source[field]
                if previous_proof is not None and observation['occurred_at'] <= previous_proof['occurred_at']:
                    c.fail('physical_evidence_time_mismatch')
                proof = dict(source='operator_record', state='confirmed', kind=kind, order_no=cmd['order_no'],
                    return_id=cmd['return_id'], return_line_id=source['return_line_id'], shipment_id=source['shipment_id'],
                    sale_movement_id=source['sale_movement_id'], actor_id=actor_id,
                    occurred_at=observation['occurred_at'], reference=observation['reference'],
                    content_basis=c.fingerprint(dict(qty=source['qty'])), rules_basis=None)
                proof['basis'] = c.fingerprint(proof); proofs[str(source['return_line_id'])] = proof
                target = next(line for case_item in proposed for line in case_item['lines'] if line['return_line_id'] == source['return_line_id'])
                target.update({qtyfield: source['qty'], field: proof})
            core._returns(proposed, cmd['order_no'], core.shipping._shipments(bundle['shipments'], cmd['order_no'], bundle['sources'], now), now)
    else:
        if not callable(policy): c.fail('return_policy_unconnected')
        confirmed = policy(conn, order_no=cmd['order_no'], action=cmd['action'], now=now)
        if confirmed is None: c.fail('return_policy_unconnected')
        internal = dict(operation_id=cmd['operation_id'], actor_id=actor_id, order_no=cmd['order_no'], return_id=cmd['return_id'],
            action=cmd['action'], expected_order_basis=cmd['expected_order_basis'], expected_order_revision=cmd['expected_order_revision'],
            expected_return_revision=cmd['expected_return_revision'], expected_policy_basis=cmd['expected_policy_basis'],
            expected_history_basis=bundle['history']['basis_id'], evidence_basis='0'*64, lines=cmd['lines'])
        core._policy(confirmed, bundle['order'], internal, bundle['financial_operations'], bundle['approval']['operation']['spec']['operation_id'])
        _same_tx(conn, txid); inspection = None
        if cmd['action'] == 'inspect':
            if not callable(inspect): c.fail('return_inspection_unconnected')
            inspection = inspect(conn, order_no=cmd['order_no'], return_id=cmd['return_id'], actor_id=actor_id,
                                 lines=deepcopy(sources), policy=deepcopy(confirmed), now=now)
            if type(inspection) is not list: c.fail('inspection_result_required')
            for item in inspection:
                if str(item['return_line_id']) in proofs: c.fail('duplicate_return_line')
                proofs[str(item['return_line_id'])] = deepcopy(item['evidence'])
        else:
            proofs = {str(source['return_line_id']): deepcopy(source['inspection_evidence']) for source in sources}
        _same_tx(conn, txid)
        if any(proofs.get(str(line['return_line_id'])) is None for line in cmd['lines']): c.fail('inspection_result_required')
        internal['evidence_basis'] = c.fingerprint([dict(return_line_id=line['return_line_id'],
            inspection_basis=proofs[str(line['return_line_id'])]['basis']) for line in cmd['lines']])
        internal['request_basis'] = c.fingerprint(internal)
        plan = core.plan_physical_return(internal, **{key: bundle[key] for key in ('order', 'approval', 'financial_operations',
            'movements', 'shipments', 'returns', 'restorations', 'history')}, inspection=inspection, policy=confirmed,
            authorization=grant, now=now)
        request = dict(core_request=internal, proofs=proofs, observation=None)
    if read._authorize(authorize, cmd['order_no'], cmd['action'], cmd['return_id'], now, actor_id) != grant:
        c.fail('return_authorization_changed')
    _same_tx(conn, txid)
    return_id = cmd['return_id']; next_revision = 1 if return_id is None else case['revision'] + 1
    if cmd['action'] == 'create_case':
        return_id = c.integer(read._sql(conn, 'insert_case', '''INSERT INTO commerce_return_cases(order_id,revision,write_txid)
            VALUES(:oid,1,txid_current()) RETURNING return_id''', oid=row['order_id']).scalar_one(), 1)
        for source in sources:
            source['return_id'] = return_id
            source['return_line_id'] = c.integer(read._sql(conn, 'insert_line', '''INSERT INTO commerce_return_lines(order_id,
                return_id,shipment_id,line_id,sale_movement_id,product_code,claimed_qty)
                VALUES(:oid,:rid,:sid,:line,:movement,:code,:qty) RETURNING return_line_id''', oid=row['order_id'], rid=return_id,
                sid=source['shipment_id'], line=source['line_id'], movement=source['sale_movement_id'], code=source['product_code'], qty=source['qty']).scalar_one(), 1)
    elif cmd['action'] in INTAKE or cmd['action'] == 'inspect':
        for source in sources:
            lid = source['return_line_id']; proof = proofs[str(lid)]
            if cmd['action'] in INTAKE:
                field, qtyfield = ('collection_evidence', 'collected_qty') if cmd['action'] == 'record_collection' else ('receipt_evidence', 'received_qty')
                changed = read._sql(conn, 'update_observation', 'UPDATE commerce_return_lines SET ' + qtyfield + '=:qty,' + field
                    + '=CAST(:proof AS jsonb) WHERE order_id=:oid AND return_id=:rid AND return_line_id=:lid AND ' + qtyfield + '=:previous',
                    qty=source['qty'], proof=money._json(proof), oid=row['order_id'], rid=return_id, lid=lid, previous=source[qtyfield])
            else:
                effect = next(effect for effect in plan['effects'] if effect['return_line_id'] == lid)
                changed = read._sql(conn, 'update_inspection', '''UPDATE commerce_return_lines SET inspected_qty=:qty,
                    resellable_qty=:resale,inspection_evidence=CAST(:proof AS jsonb)
                    WHERE order_id=:oid AND return_id=:rid AND return_line_id=:lid AND inspected_qty=:previous''',
                    qty=effect['inspected_qty'], resale=effect['resellable_qty'], proof=money._json(proof),
                    oid=row['order_id'], rid=return_id, lid=lid, previous=source['inspected_qty'])
            if changed.rowcount != 1: c.fail('return_line_revision_conflict')
    else:
        deltas = {}
        for effect in plan['stock_effects']:
            movement_id = c.integer(read._sql(conn, 'insert_movement', '''INSERT INTO stock_movements(product_code,movement_type,
                qty_delta,ref_kind,ref_id,physical_return_operation_id,physical_return_effect_key)
                VALUES(:code,'return',:qty,'order',:oid,CAST(:id AS uuid),:key) RETURNING movement_id''',
                code=effect['product_code'], qty=effect['qty_delta'], oid=row['order_id'], id=cmd['operation_id'], key=effect['effect_key']).scalar_one(), 1)
            content = dict(physical_operation_id=cmd['operation_id'], actor_id=actor_id, order_no=cmd['order_no'], return_id=return_id,
                return_line_id=effect['return_line_id'], sale_movement_id=effect['sale_movement_id'], product_code=effect['product_code'],
                qty=effect['qty_delta'], inspection_basis=effect['inspection_basis'], policy_basis=cmd['expected_policy_basis'], effect_key=effect['effect_key'])
            receipt = dict(operation_id=cmd['operation_id'], effect_key=effect['effect_key'], movement_id=movement_id,
                content_basis=c.fingerprint(content), commit_id=str(uuid4()), write_txid=txid)
            read._sql(conn, 'insert_effect', '''INSERT INTO commerce_return_restoration_effects(effect_key,physical_operation_id,
                order_id,return_id,return_line_id,sale_movement_id,product_code,qty,inspection_basis,policy_basis,state,movement_id,receipt,write_txid)
                VALUES(:key,CAST(:id AS uuid),:oid,:rid,:lid,:sale,:code,:qty,:inspection,:policy,'applied',:movement,CAST(:receipt AS jsonb),txid_current())''',
                key=effect['effect_key'], id=cmd['operation_id'], oid=row['order_id'], rid=return_id, lid=effect['return_line_id'],
                sale=effect['sale_movement_id'], code=effect['product_code'], qty=effect['qty_delta'], inspection=effect['inspection_basis'],
                policy=cmd['expected_policy_basis'], movement=movement_id, receipt=money._json(receipt))
            deltas[effect['product_code']] = deltas.get(effect['product_code'], 0) + effect['qty_delta']
        for code, qty in sorted(deltas.items()):
            changed = read._sql(conn, 'restore_stock', '''UPDATE products SET stock_qty=stock_qty+:qty,updated_at=now()
                WHERE product_code=:code AND stock_qty IS NOT NULL AND stock_qty<=2147483647-:qty''', code=code, qty=qty)
            if changed.rowcount != 1: c.fail('return_stock_changed')
    if cmd['action'] != 'create_case':
        changed = read._sql(conn, 'update_case', '''UPDATE commerce_return_cases SET revision=revision+1,write_txid=txid_current()
            WHERE order_id=:oid AND return_id=:rid AND revision=:revision''', oid=row['order_id'], rid=return_id, revision=case['revision'])
        if changed.rowcount != 1: c.fail('return_revision_conflict')
    if cmd['action'] in INTAKE:
        request = dict(actor_id=actor_id, command=cmd, source_lines=sources, observation=observation, proofs=proofs)
        request['request_basis'] = c.fingerprint(request)
    result = dict(action=cmd['action'], return_id=return_id, order_revision=row['revision'] + 1, return_revision=next_revision,
        lines=sorted([dict(return_line_id=source['return_line_id'], qty=source['qty']) for source in sources], key=lambda line: line['return_line_id']),
        evidence_basis=observation['basis'] if observation else plan['result']['evidence_basis'], core_result=plan['result'] if plan else None)
    pending = _persist(conn, cmd, actor_id, row, return_id, request, result)
    if read._authorize(authorize, cmd['order_no'], cmd['action'], cmd['return_id'], now, actor_id) != grant:
        c.fail('return_authorization_changed')
    return pending


@money._atomic
def create_case(conn, command, *, authorize, observe, now):
    if command.get('action') != 'create_case': c.fail('unexpected_return_action')
    return _execute(conn, command, authorize=authorize, observe=observe, now=now)


@money._atomic
def record_collection(conn, command, *, authorize, observe, now):
    if command.get('action') != 'record_collection': c.fail('unexpected_return_action')
    return _execute(conn, command, authorize=authorize, observe=observe, now=now)


@money._atomic
def record_receipt(conn, command, *, authorize, observe, now):
    if command.get('action') != 'record_receipt': c.fail('unexpected_return_action')
    return _execute(conn, command, authorize=authorize, observe=observe, now=now)


@money._atomic
def execute_return(conn, command, *, authorize, policy, now, inspect=None):
    if command.get('action') not in core.ACTIONS: c.fail('unexpected_return_action')
    return _execute(conn, command, authorize=authorize, policy=policy, inspect=inspect, now=now)
