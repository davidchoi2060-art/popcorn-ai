"""Caller-transaction SQL adapter; no engine, transaction creation or network.

Inputs come from trusted owner/source/provider adapters, NEVER browser claims.
The caller must roll back its ENTIRE transaction on every exception. We force
PostgreSQL into an aborted transaction on failure, even if a caller catches it.
Writes return pending-commit identifiers only. Factual receipts require a new
transaction: PostgreSQL MVCC visibility plus a different stored write_txid.
No helper verifies an authentication provider, merchant or business stock source.
"""
from copy import deepcopy
from functools import wraps
import json
from uuid import uuid4

from sqlalchemy import text

from . import commerce_contract as c
from . import commerce_payment_core as core
from .pricing_write_guard_core import lock_products


def _sql(conn, tag, sql, **params):
    return conn.execute(text('/*commerce:' + tag + '*/ ' + sql), params)


def _transaction(conn):
    if (not conn.in_transaction() or conn.in_nested_transaction() or
            conn.get_execution_options().get('isolation_level') == 'AUTOCOMMIT'):
        c.fail('caller_transaction_required')


def _atomic(function):
    @wraps(function)
    def run(conn, *args, **kwargs):
        _transaction(conn)
        try:
            txid = _txid(conn)
            if _txid(conn) != txid:
                c.fail('caller_transaction_required')
            result = function(conn, *args, **kwargs)
            if _txid(conn) != txid:
                c.fail('caller_transaction_changed')
            return result
        except Exception as exc:
            # No rollback/savepoint or retry here. This statement makes the
            # caller's PostgreSQL TX uncommittable, preserving earlier writes.
            try:
                _sql(conn, 'abort', 'SELECT 1/0 AS commerce_transaction_abort')
            except Exception:
                pass
            if isinstance(exc, c.CommerceError):
                raise
            raise c.CommerceError('commerce_writer_failed') from None
    return run


def _json(value):
    c.fingerprint(value)
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _txid(conn):
    return c.integer(_sql(conn, 'txid', 'SELECT txid_current()').scalar_one(), 1)


def _policy_lock(conn):
    _sql(conn, 'policy_lock', 'SELECT pg_catalog.pg_advisory_xact_lock(1347375171,1)')
    return c.integer(_sql(conn, 'policy_revision',
                         'SELECT revision FROM pricing_basis_policy_revision WHERE singleton=1').scalar_one(), 1)


def _codes(snapshot):
    if type(snapshot) is not dict or type(snapshot.get('lines')) is not list or not snapshot['lines']:
        c.fail('lines_required')
    return sorted({c.integer(line['product_code'], 1) for line in snapshot['lines']})


def _products(conn, codes):
    lock_products(conn, codes)
    rows = _sql(conn, 'products', '''SELECT product_code,stock_qty,status,pricing_basis_revision,
      commerce_stock_revision FROM products WHERE product_code=ANY(:codes) ORDER BY product_code''',
                codes=codes).mappings().all()
    if [r['product_code'] for r in rows] != codes:
        c.fail('product_scope_changed')
    return [dict(r) for r in rows]


def _claims(conn, codes, now):
    return [dict(r) for r in _sql(conn, 'claims', '''SELECT reservation_id,order_id,product_code,qty,status,
      EXTRACT(EPOCH FROM expires_at AT TIME ZONE 'UTC')::bigint AS expires_epoch
      FROM stock_reservations WHERE commerce_order_id IS NOT NULL AND product_code=ANY(:codes)
      AND (status='protected' OR (status='held' AND expires_at>to_timestamp(:now) AT TIME ZONE 'UTC'))
      ORDER BY product_code,reservation_id''', codes=codes, now=c.integer(now)).mappings().all()]


def _stock_basis(products, claims):
    return c.fingerprint(dict(products=products, claims=claims))


@_atomic
def stock_basis(conn, codes, *, now):
    """Technical equality basis under policy/products locks, not sale authority."""
    _policy_lock(conn)
    products = _products(conn, sorted(set(codes)))
    claims = _claims(conn, sorted(set(codes)), now)
    return _stock_basis(products, claims)


def _context(conn, context_id, owner, now):
    context_id = c.uuid_text(context_id)
    owner = c.owner_identity(owner)
    row = _sql(conn, 'context', '''SELECT context_id,owner_scope,owner_identity,expires_at,revoked_at
      FROM commerce_owner_contexts WHERE context_id=CAST(:id AS uuid)''', id=context_id).mappings().first()
    if row is None or row['revoked_at'] is not None or c.integer(row['expires_at']) <= c.integer(now):
        c.fail('owner_unconfirmed')
    c.require_owner(row['owner_identity'], owner)
    if row['owner_scope'] != c.fingerprint(owner):
        c.fail('owner_scope_mismatch')
    return dict(row)


def _binding(value):
    if value is None:
        return None
    c.object_fields(value, ('adapter_id', 'provider', 'environment', 'merchant_id', 'provider_order_id'))
    for field in ('adapter_id', 'provider', 'merchant_id', 'provider_order_id'):
        c.text(value[field])
    c.enum(value['environment'], ('test', 'live'))
    return deepcopy(value)


def _order(conn, order_no, lock=False):
    row = _sql(conn, 'order_lock' if lock else 'order', '''SELECT o.order_id,o.order_no,o.status AS order_state,
      o.total_amount,d.context_id,d.owner_scope,d.owner_identity,d.request_id,d.request_basis,d.snapshot,
      d.policy_snapshot,d.provider_binding,d.states,d.revision,d.expires_at,d.write_txid
      FROM orders o JOIN commerce_order_details d USING(order_id) WHERE o.order_no=:no'''
      + (' FOR UPDATE OF o,d' if lock else ''), no=c.text(order_no)).mappings().first()
    if row is None:
        c.fail('order_not_found')
    return dict(row)


def _locked_order(conn, order_no):
    before = _order(conn, order_no)
    codes = _codes(before['snapshot'])
    _policy_lock(conn)
    products = _products(conn, codes)
    row = _order(conn, order_no, True)
    if row['order_id'] != before['order_id'] or row['snapshot'] != before['snapshot'] or _codes(row['snapshot']) != codes:
        c.fail('product_scope_changed')
    return row, products


def _owner(conn, row, context_id, owner, now):
    context = _context(conn, context_id, owner, now)
    if str(row['context_id']) != c.uuid_text(context_id) or row['owner_scope'] != context['owner_scope']:
        c.fail('owner_mismatch')
    c.require_owner(row['owner_identity'], owner)


def _balance(conn, row):
    values = _sql(conn, 'balance', '''SELECT
      COALESCE(sum(CASE WHEN p.status='승인' THEN p.amount ELSE 0 END),0)::bigint AS approved,
      COALESCE(-sum(CASE WHEN p.status='환불' THEN p.amount ELSE 0 END),0)::bigint AS refunded
      FROM payments p WHERE order_id=:oid AND commerce_operation_id IS NOT NULL''',
                  oid=row['order_id']).mappings().one()
    approved, refunded = c.integer(values['approved']), c.integer(values['refunded'])
    if refunded > approved or approved > row['total_amount']:
        c.fail('invalid_payment_balance')
    return approved, refunded


def _basis(row, approved, refunded):
    return c.fingerprint(dict(order_no=row['order_no'], revision=row['revision'], order_state=row['order_state'],
                              states=row['states'], snapshot_basis=row['snapshot']['basis_id'],
                              policy_basis=row['policy_snapshot']['policy_basis'],
                              provider_binding=row['provider_binding'], approved=approved, refunded=refunded))


def _expect(row, expected_basis, approved, refunded):
    if c.basis_text(expected_basis) != _basis(row, approved, refunded):
        c.fail('order_basis_changed')


def _update_order(conn, row, states):
    result = _sql(conn, 'update_order', '''UPDATE commerce_order_details SET states=CAST(:states AS jsonb),
      revision=revision+1,write_txid=txid_current() WHERE order_id=:oid AND revision=:revision''',
                  oid=row['order_id'], revision=row['revision'], states=_json(states))
    if result.rowcount != 1:
        c.fail('order_revision_conflict')


def _operation(conn, operation_id, lock=False):
    row = _sql(conn, 'operation_lock' if lock else 'operation', '''SELECT operation,verification,write_txid,order_id
      FROM commerce_payment_operations WHERE operation_id=CAST(:id AS uuid)'''
      + (' FOR UPDATE' if lock else ''), id=c.uuid_text(operation_id)).mappings().first()
    if row is None:
        c.fail('operation_not_found')
    return dict(row)


def _update_operation(conn, previous, changed, verification=None):
    result = _sql(conn, 'update_operation', '''UPDATE commerce_payment_operations SET
      operation=CAST(:operation AS jsonb),verification=COALESCE(CAST(:verification AS jsonb),verification),
      state=:state,revision=:next_revision,provider_ref=:ref,write_txid=txid_current()
      WHERE operation_id=CAST(:id AS uuid) AND revision=:revision''',
      operation=_json(changed), state=changed['state'], next_revision=changed['revision'],
      ref=(changed['provider_result'] or {}).get('provider_ref'), id=previous['spec']['operation_id'],
      revision=previous['revision'], verification=_json(verification) if verification is not None else None)
    if result.rowcount != 1:
        c.fail('operation_revision_conflict')


def _pending(row, operation=None, *, action='pending_commit'):
    return dict(action=action, pending_commit=True, order_no=row['order_no'],
                operation_id=operation['spec']['operation_id'] if operation else None)


@_atomic
def create_draft(conn, body, *, context_id, owner, order_no, sale_basis, policy, now, revalidate):
    """revalidate(conn, source, now) returns canonical sale/policy/provider binding.

    It MUST be a trusted, no-network source reader using this connection. A
    missing reader fails closed; stock tokens alone never confirm sale authority.
    """
    c.object_fields(body, ('request_id', 'source', 'expected_basis', 'shipping'))
    c.object_fields(body['shipping'], ('name', 'phone', 'address'), ('contact_email',))
    shipping = {k: c.text(v) for k, v in body['shipping'].items()}
    payload = dict(source=c.source_reference(body['source']), expected_basis=c.basis_text(body['expected_basis']), shipping=shipping)
    identity = c.request_identity(body['request_id'], payload, owner)
    _policy_lock(conn)
    previous = _sql(conn, 'draft_replay', '''SELECT o.order_no,d.snapshot FROM commerce_order_details d
      JOIN orders o USING(order_id) WHERE d.owner_scope=:scope AND d.request_id=CAST(:rid AS uuid)''',
      scope=c.fingerprint(identity['owner']), rid=identity['request_id']).mappings().first()
    codes = _codes(previous['snapshot'] if previous else sale_basis)
    products = _products(conn, codes)
    context = _context(conn, context_id, owner, now)
    if previous:
        row = _order(conn, previous['order_no'], True)
        _owner(conn, row, context_id, owner, now)
        if row['request_basis'] != identity['request_basis']:
            c.fail('request_conflict')
        return _pending(row, action='replay_pending_or_committed_read')
    if not callable(revalidate):
        c.fail('sale_reader_required')
    fresh = revalidate(conn, payload['source'], c.integer(now))
    c.object_fields(fresh, ('sale_basis', 'policy', 'provider_binding'))
    if c.confirmed_policy(fresh['policy']) != c.confirmed_policy(policy):
        c.fail('policy_basis_changed')
    result = c.draft_contract(body, owner=owner, sale_basis=fresh['sale_basis'], policy=fresh['policy'], now=now)
    snapshot = result['snapshot']
    if _codes(snapshot) != codes or snapshot['stock_basis'] != _stock_basis(products, _claims(conn, codes, now)):
        c.fail('stock_basis_changed')
    need = {}
    for line in snapshot['lines']:
        need[line['product_code']] = need.get(line['product_code'], 0) + line['qty']
    claimed = {}
    for claim in _claims(conn, codes, now):
        claimed[claim['product_code']] = claimed.get(claim['product_code'], 0) + claim['qty']
    for product in products:
        if product['status'] != '판매중' or c.integer(product['stock_qty']) - claimed.get(product['product_code'], 0) < need[product['product_code']]:
            c.fail('stock_insufficient')
    if len(c.text(order_no)) > 20:
        c.fail('invalid_order_no')
    binding = _binding(fresh['provider_binding'])
    principal = identity['owner']
    oid = _sql(conn, 'insert_order', '''INSERT INTO orders(order_no,member_id,channel,status,total_amount,
      ops_snapshot,shipping_snap,user_id,data_origin) VALUES(:no,:member,'own','접수',:total,
      CAST(:ops AS jsonb),CAST(:shipping AS jsonb),:user,'real') RETURNING order_id''',
      no=order_no, member=principal.get('member_id'), user=principal.get('user_id'), total=snapshot['total'],
      ops=_json(dict(commerce_version=c.VERSION)), shipping=_json(shipping)).scalar_one()
    states = {k: result[k] for k in ('checkout_state', 'payment_state', 'allocation_state', 'refund_state')}
    _sql(conn, 'insert_detail', '''INSERT INTO commerce_order_details(order_id,context_id,owner_scope,owner_identity,
      request_id,request_basis,snapshot,policy_snapshot,provider_binding,states,revision,expires_at,write_txid)
      VALUES(:oid,CAST(:context AS uuid),:scope,CAST(:owner AS jsonb),CAST(:rid AS uuid),:basis,
      CAST(:snapshot AS jsonb),CAST(:policy AS jsonb),CAST(:binding AS jsonb),CAST(:states AS jsonb),1,:expires,txid_current())''',
      oid=oid, context=c.uuid_text(context_id), scope=context['owner_scope'], owner=_json(principal),
      rid=identity['request_id'], basis=identity['request_basis'], snapshot=_json(snapshot),
      policy=_json(c.confirmed_policy(policy)), binding=_json(binding) if binding is not None else None,
      states=_json(states), expires=snapshot['expires_at'])
    physical_ids = {line['line_id'] for line in snapshot['lines']}
    if any('charge:' + charge['code'] in physical_ids for charge in snapshot['charges']):
        c.fail('charge_line_collision')
    for line in snapshot['lines']:
        _sql(conn, 'insert_item', '''INSERT INTO order_items(order_id,product_code,item_kind,name_snap,price_snap,spec_snap,qty)
          VALUES(:oid,:code,'core_part',:name,:amount,CAST(:spec AS jsonb),:qty)''',
          oid=oid, code=line['product_code'], name=line['name'], amount=line['unit_amount'], qty=line['qty'],
          spec=_json(dict(line_id=line['line_id'], source=snapshot['source'])))
    for charge in snapshot['charges']:
        _sql(conn, 'insert_item', '''INSERT INTO order_items(order_id,item_kind,name_snap,price_snap,spec_snap,qty)
          VALUES(:oid,'commerce_charge',:name,:amount,CAST(:spec AS jsonb),1)''',
          oid=oid, name=charge['code'], amount=charge['amount'], spec=_json(dict(line_id='charge:' + charge['code'])))
    for code, qty in sorted(need.items()):
        _sql(conn, 'insert_reservation', '''INSERT INTO stock_reservations(order_id,commerce_order_id,product_code,qty,status,expires_at)
          VALUES(:oid,:oid,:code,:qty,'held',to_timestamp(:expires) AT TIME ZONE 'UTC')''',
          oid=oid, code=code, qty=qty, expires=snapshot['expires_at'])
    _sql(conn, 'order_event', "INSERT INTO order_events(order_id,from_state,to_state,actor) VALUES(:oid,NULL,'접수','commerce')", oid=oid)
    return _pending(dict(order_no=order_no))


@_atomic
def prepare(conn, spec, *, context_id, owner, expected_basis, policy, now, revalidate=None):
    spec = core._spec(spec)
    row, products = _locked_order(conn, spec['order_no'])
    _owner(conn, row, context_id, owner, now)
    c.require_owner(spec['owner'], row['owner_identity'])
    prior = _sql(conn, 'request_operation', '''SELECT operation FROM commerce_payment_operations
      WHERE order_id=:oid AND kind=:kind AND request_id=CAST(:rid AS uuid) FOR UPDATE''',
      oid=row['order_id'], kind=spec['kind'], rid=spec['request_id']).mappings().first()
    if prior:
        if core._operation(prior['operation'])['request_basis'] != c.fingerprint(spec):
            c.fail('request_conflict')
        return _pending(row, prior['operation'], action='replay_pending_or_committed_read')
    approved, refunded = _balance(conn, row)
    _expect(row, expected_basis, approved, refunded)
    if spec['order_basis'] != expected_basis:
        c.fail('order_basis_changed')
    actual_policy = c.confirmed_policy(policy)
    if spec['kind'] == 'approve' and (actual_policy['policy_id'] != row['policy_snapshot']['policy_id'] or
            actual_policy['policy_basis'] != row['policy_snapshot']['policy_basis']):
        c.fail('policy_basis_changed')
    if spec['capabilities'] != actual_policy['capabilities']:
        c.fail('policy_basis_changed')
    if (spec['order_total'], spec['approved_amount'], spec['refunded_amount']) != (row['total_amount'], approved, refunded):
        c.fail('payment_balance_changed')
    binding = _binding(row['provider_binding'])
    if binding is None or any(spec[k] != binding[k] for k in binding):
        c.fail('provider_unconfirmed')
    lines = [{k: line[k] for k in ('line_id', 'product_code', 'qty')} for line in row['snapshot']['lines']]
    if spec['allocation_lines'] != lines or spec['reservation_expires_at'] != row['expires_at']:
        c.fail('allocation_basis_changed')
    active = _sql(conn, 'active_operation', '''SELECT operation FROM commerce_payment_operations
      WHERE order_id=:oid AND state IN ('prepared','processing','unknown') FOR UPDATE''', oid=row['order_id']).mappings().first()
    if active:
        c.fail('active_operation_conflict')
    if spec['kind'] == 'approve':
        if row['states'] != dict(checkout_state='draft', payment_state='unpaid', allocation_state='held', refund_state='none'):
            c.fail('state_blocked')
        if not callable(revalidate):
            c.fail('sale_reader_required')
        fresh = revalidate(conn, row['snapshot']['source'], c.integer(now))
        c.object_fields(fresh, ('sale_basis', 'policy', 'provider_binding'))
        basis = fresh['sale_basis']
        checked = c.validate_sale_basis(basis, expected_basis=basis['basis_id'], policy=fresh['policy'], now=now)
        if checked['stock_basis'] != _stock_basis(products, _claims(conn, _codes(row['snapshot']), now)):
            c.fail('stock_basis_changed')
        for key in ('source', 'lines', 'charges', 'total', 'price_basis', 'terms_basis', 'policy_id', 'policy_basis'):
            if key == 'lines':
                if [{k: v for k, v in line.items() if k != 'stock_available'} for line in checked[key]] != [
                        {k: v for k, v in line.items() if k != 'stock_available'} for line in row['snapshot'][key]]:
                    c.fail('sale_basis_changed')
            elif checked[key] != row['snapshot'][key]:
                c.fail('sale_basis_changed')
        if _binding(fresh['provider_binding']) != binding or c.confirmed_policy(fresh['policy']) != actual_policy:
            c.fail('provider_unconfirmed')
        if _allocation(conn, row, products, now) != 'held':
            c.fail('stock_basis_changed')
    else:
        original = core._operation(_operation(conn, spec['original_operation_id'], True)['operation'])
        if (original['spec']['order_no'] != row['order_no'] or original['spec']['kind'] != 'approve'
                or original['state'] != 'confirmed' or original['provider_result']['provider_ref'] != spec['original_provider_ref']):
            c.fail('original_operation_mismatch')
    operation = core.prepare_operation(spec, now=now)['operation']
    receipt = dict(commerce_version=c.VERSION, operation_id=spec['operation_id'], request_basis=operation['request_basis'],
                   prepared_revision=1, commit_id=str(uuid4()))
    operation = core.attach_prepared_commit(operation, receipt)
    _sql(conn, 'insert_operation', '''INSERT INTO commerce_payment_operations(operation_id,order_id,kind,request_id,
      request_basis,provider,provider_environment,merchant_id,original_operation_id,state,revision,operation,write_txid)
      VALUES(CAST(:id AS uuid),:oid,:kind,CAST(:rid AS uuid),:basis,:provider,:environment,:merchant,
      CAST(:original AS uuid),'prepared',1,CAST(:operation AS jsonb),txid_current())''',
      id=spec['operation_id'], oid=row['order_id'], kind=spec['kind'], rid=spec['request_id'],
      basis=operation['request_basis'], provider=spec['provider'], environment=spec['environment'],
      merchant=spec['merchant_id'], original=spec['original_operation_id'], operation=_json(operation))
    states = dict(row['states'])
    if spec['kind'] == 'approve':
        states['payment_state'] = 'prepared'
    _update_order(conn, row, states)
    return _pending(row, operation)


def _locked_operation(conn, operation_id):
    discovered = _operation(conn, operation_id)
    initial = core._operation(discovered['operation'])
    row, products = _locked_order(conn, initial['spec']['order_no'])
    record = _operation(conn, operation_id, True)
    operation = core._operation(record['operation'])
    if record['order_id'] != row['order_id'] or operation['spec'] != initial['spec']:
        c.fail('operation_scope_mismatch')
    return row, products, record, operation


def _committed(conn, *records):
    current = _txid(conn)
    if any(c.integer(record['write_txid'], 1) == current for record in records):
        c.fail('commit_not_visible')


@_atomic
def dispatch(conn, operation_id, *, expected_revision, now, lease_expires_at):
    row, products, record, operation = _locked_operation(conn, operation_id)
    _committed(conn, row, record)
    if operation['revision'] != c.integer(expected_revision, 1):
        c.fail('operation_revision_conflict')
    plan = core.plan_dispatch(operation, now=now, lease_expires_at=lease_expires_at)
    if plan['action'] != 'dispatch_after_commit':
        return dict(action=plan['action'], pending_commit=False, operation_id=operation_id)
    if operation['spec']['kind'] == 'approve' and _allocation(conn, row, products, now) != 'held':
        c.fail('stock_basis_changed')
    _update_operation(conn, operation, plan['next_operation'])
    states = dict(row['states'])
    if operation['spec']['kind'] == 'approve':
        _reservations(conn, row, 'protected')
        states.update(checkout_state='processing', payment_state='processing', allocation_state='protected')
    else:
        states['refund_state'] = 'processing'
    _update_order(conn, row, states)
    return dict(_pending(row, plan['next_operation'], action='read_dispatch_after_commit'),
                dispatch_basis=c.fingerprint(plan['next_operation']))


@_atomic
def read_committed_operation(conn, operation_id, *, now):
    """Internal adapter read; HTTP callers MUST authorize separately."""
    record = _operation(conn, operation_id)
    _committed(conn, record)
    operation = core._operation(record['operation'])
    if operation['state'] in ('confirmed','declined'):
        core.validate_provider_evidence(operation, operation['provider_result'], record['verification'], now=now)
    return operation


@_atomic
def read_dispatch(conn, operation_id, *, dispatch_basis, now):
    """Only the fresh dispatch caller uses this; recovered processing queries.

    Identity is stable, but this does not prove an external request was sent
    once. The chosen provider adapter MUST support its official replay/query
    contract. After loss mark_unresolved; never use this as a recovery retry.
    """
    operation = read_committed_operation(conn, operation_id, now=now)
    if (operation['state'] != 'processing' or operation['lease_expires_at'] <= c.integer(now)
            or c.fingerprint(operation) != c.basis_text(dispatch_basis)):
        c.fail('dispatch_not_available')
    spec = operation['spec']
    return dict(operation_id=spec['operation_id'], idempotency_key=spec['operation_id'],
                **{k: spec[k] for k in core._EXPECTED_FIELDS})


def _reservations(conn, row, target):
    _sql(conn, 'reservations', '''UPDATE stock_reservations SET status=:target WHERE commerce_order_id=:oid
      AND status IN ('held','protected')''', oid=row['order_id'], target=target)


def _allocation(conn, row, products, now):
    claims = _claims(conn, [p['product_code'] for p in products], now)
    own, all_claims, need = {}, {}, {}
    for line in row['snapshot']['lines']:
        need[line['product_code']] = need.get(line['product_code'], 0) + line['qty']
    for claim in claims:
        code = claim['product_code']
        all_claims[code] = all_claims.get(code, 0) + claim['qty']
        if claim['order_id'] == row['order_id']:
            own[code] = own.get(code, 0) + claim['qty']
    if (own != need or any(p['status'] != '판매중' or p['stock_qty'] is None or
                          p['stock_qty'] < all_claims.get(p['product_code'], 0) for p in products)):
        return 'blocked'
    return row['states']['allocation_state'] if row['states']['allocation_state'] in ('held', 'protected') else 'blocked'


@_atomic
def mark_unresolved(conn, operation_id, *, expected_revision, reason, now):
    row, _, record, operation = _locked_operation(conn, operation_id)
    _committed(conn, row, record)
    if operation['revision'] != c.integer(expected_revision, 1):
        c.fail('operation_revision_conflict')
    plan = core.plan_unresolved(operation, reason=reason, now=now)
    changed = plan['next_operation']
    if changed != operation:
        _update_operation(conn, operation, changed)
        states = dict(row['states'])
        if operation['spec']['kind'] == 'approve':
            _reservations(conn, row, 'protected')
            states.update(checkout_state='unknown', payment_state='unknown', allocation_state='protected')
        else:
            states['refund_state'] = 'unknown'
        _update_order(conn, row, states)
        return _pending(row, changed, action='query_after_commit')
    return dict(action=plan['action'], pending_commit=False, operation_id=operation_id)


@_atomic
def finalize(conn, operation_id, evidence, verification, *, expected_revision, now, event_key=None):
    row, products, record, operation = _locked_operation(conn, operation_id)
    _committed(conn, row, record)
    if operation['revision'] != c.integer(expected_revision, 1):
        c.fail('operation_revision_conflict')
    approved, refunded = _balance(conn, row)
    spec = operation['spec']
    if operation['state'] not in ('confirmed', 'declined'):
        if (spec['approved_amount'], spec['refunded_amount']) != (approved, refunded):
            c.fail('payment_balance_changed')
    allocation = _allocation(conn, row, products, now) if spec['kind'] == 'approve' and operation['state'] not in ('confirmed', 'declined') else row['states']['allocation_state']
    plan = core.plan_provider_result(operation, evidence, verification, now=now, allocation_state=allocation)
    if event_key is not None:
        previous = _sql(conn, 'event_lookup', '''SELECT operation_id,evidence_basis FROM commerce_payment_events
          WHERE provider=:provider AND provider_environment=:environment AND merchant_id=:merchant AND event_key=:key''',
          provider=spec['provider'], environment=spec['environment'], merchant=spec['merchant_id'], key=c.text(event_key)).mappings().first()
        if previous and (str(previous['operation_id']) != operation_id or previous['evidence_basis'] != c.fingerprint(evidence)):
            c.fail('provider_event_conflict')
        if not previous:
            _sql(conn, 'insert_event', '''INSERT INTO commerce_payment_events(operation_id,provider,provider_environment,
              merchant_id,event_key,evidence_basis,verification,observed_at) VALUES(CAST(:id AS uuid),:provider,
              :environment,:merchant,:key,:basis,CAST(:verification AS jsonb),:observed)''',
              id=operation_id, provider=spec['provider'], environment=spec['environment'], merchant=spec['merchant_id'],
              key=event_key, basis=c.fingerprint(evidence), verification=_json(verification), observed=evidence['observed_at'])
    if plan['action'] == 'read_result':
        return _pending(row, operation, action='read_result_after_commit') if event_key is not None else dict(action='read_result', pending_commit=False, operation_id=operation_id)
    if plan['action'] == 'query_required':
        changed = plan['next_operation']
        if changed != operation:
            _update_operation(conn, operation, changed, verification=verification)
            states = dict(row['states'])
            if spec['kind'] == 'approve':
                _reservations(conn, row, 'protected')
                states.update(checkout_state='unknown', payment_state='unknown', allocation_state='protected')
            else:
                states['refund_state'] = 'unknown'
            _update_order(conn, row, states)
        return _pending(row, changed, action='query_after_commit')
    payment_id = None
    for effect in plan['effects']:
        if effect['kind'] in ('payment_approval', 'payment_cancel'):
            provider_ref = evidence['provider_ref']
            payment_id = _sql(conn, 'insert_payment', '''INSERT INTO payments(order_id,pay_mode,pg_ref,amount,status,
              paid_at,commerce_operation_id,commerce_effect_key) VALUES(:oid,'own',:ref,:amount,:status,
              to_timestamp(:observed) AT TIME ZONE 'UTC',CAST(:id AS uuid),:key) RETURNING payment_id''',
              oid=row['order_id'], ref=provider_ref if len(provider_ref) <= 100 else None, amount=effect['amount'],
              status='승인' if spec['kind'] == 'approve' else '환불', observed=evidence['observed_at'],
              id=operation_id, key=effect['dedup_key']).scalar_one()
    allocations = [e for e in plan['effects'] if e['kind'] == 'allocate']
    if allocations:
        # Consume our protected claim BEFORE decrement. The DB product guard
        # then checks the remaining other buyers' claims under the same lock.
        _reservations(conn, row, 'converted')
        deltas = {}
        for effect in allocations:
            _sql(conn, 'insert_movement', '''INSERT INTO stock_movements(product_code,movement_type,qty_delta,ref_kind,
              ref_id,commerce_operation_id,commerce_effect_key) VALUES(:code,'own_sale',:delta,'order',:oid,CAST(:id AS uuid),:key)''',
              code=effect['product_code'], delta=effect['qty_delta'], oid=row['order_id'], id=operation_id, key=effect['dedup_key'])
            deltas[effect['product_code']] = deltas.get(effect['product_code'], 0) + effect['qty_delta']
        for code, delta in sorted(deltas.items()):
            result = _sql(conn, 'decrement_stock', '''UPDATE products SET stock_qty=stock_qty+:delta,updated_at=now()
              WHERE product_code=:code AND stock_qty>=:qty''', code=code, delta=delta, qty=-delta)
            if result.rowcount != 1:
                c.fail('stock_basis_changed')
    if any(e['kind'] == 'release_reservation' for e in plan['effects']):
        _reservations(conn, row, 'released')
    states = dict(row['states'])
    for key, value in plan['proposed_states'].items():
        if value != 'unchanged':
            states[key] = value
    if spec['kind'] == 'approve' and operation['state'] not in ('confirmed', 'declined') and evidence['status'] == 'declined':
        states['checkout_state'] = 'draft'
    if spec['kind'] == 'cancel' and evidence['status'] == 'declined':
        states['refund_state'] = 'partial' if refunded else 'none'
    receipt = dict(commerce_version=c.VERSION, operation_id=operation_id, request_basis=operation['request_basis'],
                   plan_basis=plan['plan_basis'], commit_id=str(uuid4()), payment_id=payment_id,
                   effect_keys=[e['dedup_key'] for e in plan['effects']])
    changed = core.apply_finalization_receipt(operation, plan, receipt)
    _update_operation(conn, operation, changed, verification=verification)
    _update_order(conn, row, states)
    if spec['kind'] == 'approve' and states['payment_state'] == 'confirmed' and states['allocation_state'] == 'allocated':
        _sql(conn, 'paid_order', "UPDATE orders SET status='결제완료' WHERE order_id=:oid", oid=row['order_id'])
        _sql(conn, 'paid_event', "INSERT INTO order_events(order_id,from_state,to_state,actor) VALUES(:oid,:previous,'결제완료','commerce')",
             oid=row['order_id'], previous=row['order_state'])
    return _pending(row, changed, action='read_final_result_after_commit')


@_atomic
def expire(conn, order_no, *, expected_basis, now):
    row, _ = _locked_order(conn, order_no)
    _committed(conn, row)
    approved, refunded = _balance(conn, row)
    _expect(row, expected_basis, approved, refunded)
    active = _sql(conn, 'active_operation', '''SELECT operation FROM commerce_payment_operations
      WHERE order_id=:oid AND state IN ('prepared','processing','unknown') FOR UPDATE''', oid=row['order_id']).mappings().first()
    operation = active['operation'] if active else None
    plan = core.plan_expiry(order_no=order_no, checkout_state=row['states']['checkout_state'],
      allocation_state=row['states']['allocation_state'], expires_at=row['expires_at'], now=now, active=operation)
    if plan['action'] != 'expire_draft_after_commit':
        return dict(action=plan['action'], pending_commit=False, reservation_action=plan['reservation_action'])
    if operation is not None and 'next_operation' in plan:
        _update_operation(conn, operation, plan['next_operation'])
    _reservations(conn, row, 'released')
    states = dict(row['states'], checkout_state='expired', allocation_state='released', payment_state='unpaid')
    _update_order(conn, row, states)
    return _pending(row, action='read_expiry_after_commit')


def _read_order_bundle(conn, order_no):
    """One READ COMMITTED statement snapshot, without acquiring write locks.

    The approval join deliberately has no LIMIT/aggregation: duplicate approval
    proofs produce duplicate result rows and are rejected, never silently chosen.
    Nullable proof columns and bigint aggregates keep native driver types.
    """
    rows = _sql(conn, 'order_bundle', '''SELECT o.order_id,o.order_no,o.status AS order_state,
      o.total_amount,d.context_id,d.owner_scope,d.owner_identity,d.request_id,d.request_basis,d.snapshot,
      d.policy_snapshot,d.provider_binding,d.states,d.revision,d.expires_at,d.write_txid,
      ledger.approved,ledger.refunded,
      proof.payment_id AS approval_payment_id,proof.amount AS approval_amount,
      proof.operation AS approval_operation,proof.verification AS approval_verification,
      proof.write_txid AS approval_write_txid
      FROM orders o JOIN commerce_order_details d USING(order_id)
      CROSS JOIN LATERAL (
        SELECT COALESCE(sum(CASE WHEN p.status='승인' THEN p.amount ELSE 0 END),0)::bigint AS approved,
               COALESCE(-sum(CASE WHEN p.status='환불' THEN p.amount ELSE 0 END),0)::bigint AS refunded
        FROM payments p WHERE p.order_id=o.order_id AND p.commerce_operation_id IS NOT NULL
      ) ledger
      LEFT JOIN LATERAL (
        SELECT p.payment_id,p.amount,x.operation,x.verification,x.write_txid
        FROM payments p JOIN commerce_payment_operations x ON x.operation_id=p.commerce_operation_id
        WHERE p.order_id=o.order_id AND x.order_id=o.order_id
          AND p.status='승인' AND x.kind='approve' AND x.state='confirmed'
      ) proof ON TRUE WHERE o.order_no=:no''', no=c.text(order_no)).mappings().all()
    if not rows:
        c.fail('order_not_found')
    if len(rows) != 1:
        c.fail('committed_approval_cardinality')
    row = dict(rows[0])
    approved, refunded = c.integer(row['approved']), c.integer(row['refunded'])
    if refunded > approved or approved > c.integer(row['total_amount']):
        c.fail('invalid_payment_balance')
    return row


@_atomic
def read_committed_order(conn, order_no, *, context_id, owner, now):
    """Authorized, single-snapshot stored detail. Public envelope is separate."""
    row = _read_order_bundle(conn, order_no)
    _committed(conn, row)
    _owner(conn, row, context_id, owner, now)
    return _committed_order_result(conn, row, now=now)


def _require_admin_read(authorize, order_no, now):
    """Reference grant from a trusted SERVER callback, never a request DTO.

    The route adapter must obtain api.auth.current_operator() only after the
    existing resolve_session/middleware gate, and check the GET read permission.
    This module cannot authenticate a session or establish callback provenance.
    A client role, positive actor ID, dict or truthy object is not that adapter.
    The callback must be synchronous/no-network and cannot own a transaction.
    """
    if not callable(authorize):
        c.fail('admin_authorization_unready')
    order_no, now = c.text(order_no), c.integer(now)
    grant = authorize(order_no=order_no, now=now)
    c.object_fields(grant, ('auth_source', 'authenticated', 'actor', 'permission',
                            'allowed', 'order_no', 'checked_at'))
    if (grant['auth_source'] != 'api.auth.current_operator'
            or grant['authenticated'] is not True or grant['allowed'] is not True
            or grant['permission'] != 'commerce.order.read'
            or c.text(grant['order_no']) != order_no
            or c.integer(grant['checked_at']) != now):
        c.fail('admin_authorization_required')
    actor = grant['actor']
    c.object_fields(actor, ('operator_id', 'role', 'status'))
    c.integer(actor['operator_id'], 1)
    c.enum(actor['role'], ('viewer', 'operator', 'owner'))
    if actor['status'] != '활성':
        c.fail('admin_authorization_required')


@_atomic
def read_committed_admin_order(conn, order_no, *, now, authorize=None):
    """Internal authenticated-admin read; route authentication is external.

    authorize is a server-owned adapter callback, NOT a browser-provided grant.
    Authorization precedes every order/payment SELECT. Customer credentials,
    context expiry and cookies have no role in an authorized operator read.
    The result remains private and requires the administrative allowlist.
    """
    _require_admin_read(authorize, order_no, now)
    row = _read_order_bundle(conn, order_no)
    _committed(conn, row)
    if row['owner_scope'] != c.fingerprint(c.owner_identity(row['owner_identity'])):
        c.fail('owner_scope_mismatch')
    return _committed_order_result(conn, row, now=now)


def _committed_order_result(conn, row, *, now):
    """Shared stored proof/projection; audience authorization runs beforehand."""
    order_no = row['order_no']
    approved, refunded = row['approved'], row['refunded']
    snapshot = row['snapshot']
    lines = deepcopy(snapshot['lines']) + [dict(line_id='charge:' + x['code'], name=x['code'], qty=1,
      unit_amount=x['amount']) for x in snapshot['charges']]
    capabilities = dict(row['policy_snapshot']['capabilities'])
    if row['provider_binding'] is None:
        capabilities.update(approve=False, cancel=False, partial_cancel=False)
    detail = dict(order_no=order_no, owner_binding_id=str(row['context_id']),
      order_state=row['order_state'], total=row['total_amount'], currency='KRW',
      expires_at=row['expires_at'], lines=lines, reason_codes=[], capabilities=capabilities, **row['states'])
    if detail['allocation_state'] == 'blocked':
        detail['reason_codes'].append('allocation_blocked')
    if detail['payment_state'] == 'confirmed':
        proof = dict(payment_id=row['approval_payment_id'], amount=row['approval_amount'],
          operation=row['approval_operation'], verification=row['approval_verification'],
          write_txid=row['approval_write_txid'])
        if any(value is None for value in proof.values()):
            c.fail('committed_payment_mismatch')
        _committed(conn, proof)
        operation = core._operation(proof['operation'])
        core.validate_provider_evidence(operation, operation['provider_result'], proof['verification'], now=now)
        c.require_owner(operation['spec']['owner'], row['owner_identity'])
        receipt = operation['final_commit']
        if (receipt['payment_id'] != c.integer(proof['payment_id'], 1)
                or c.integer(proof['amount']) != snapshot['total'] or approved != snapshot['total']
                or operation['spec']['order_no'] != row['order_no'] or operation['spec']['kind'] != 'approve'
                or operation['state'] != 'confirmed'):
            c.fail('committed_payment_mismatch')
        detail['committed_payment'] = dict(operation_id=operation['spec']['operation_id'],
          request_basis=operation['request_basis'], commit_id=receipt['commit_id'], payment_id=proof['payment_id'],
          order_no=order_no, amount=proof['amount'], currency='KRW', status='approved')
    elif (approved != 0 or refunded != 0 or any(row[key] is not None for key in
            ('approval_payment_id','approval_amount','approval_operation','approval_verification','approval_write_txid'))):
        c.fail('committed_payment_mismatch')
    # Return trusted INTERNAL row for projection. Caller must never JSON-serialize
    # it directly: committed_payment is not part of the public allowlist.
    c.order_detail(detail)
    return dict(row=detail, basis_id=_basis(row, approved, refunded), approved=approved, refunded=refunded,
                provider_binding=deepcopy(row['provider_binding']))


def _require_admin_list_read(authorize, now):
    """Explicit collection scope from a trusted server adapter, never an order ID."""
    if not callable(authorize):
        c.fail('admin_authorization_unready')
    now = c.integer(now)
    grant = authorize(scope='commerce.orders', now=now)
    c.object_fields(grant, ('auth_source', 'authenticated', 'actor', 'permission',
                            'allowed', 'scope', 'checked_at'))
    if (grant['auth_source'] != 'api.auth.current_operator'
            or grant['authenticated'] is not True or grant['allowed'] is not True
            or grant['permission'] != 'commerce.order.list'
            or grant['scope'] != 'commerce.orders' or c.integer(grant['checked_at']) != now):
        c.fail('admin_authorization_required')
    actor = grant['actor']
    c.object_fields(actor, ('operator_id', 'role', 'status'))
    c.integer(actor['operator_id'], 1)
    c.enum(actor['role'], ('viewer', 'operator', 'owner'))
    if actor['status'] != '활성':
        c.fail('admin_authorization_required')


def _read_admin_order_page(conn, limit, upper_id, after_id):
    """Cut parent IDs before joins; one business statement per bounded page.

    Raw approval rows deliberately remain unaggregated so duplicates fail closed.
    All lines come from the stored snapshot, not current products or item joins.
    Each statement has its own MVCC snapshot; the upper ID is not a snapshot token.
    """
    return _sql(conn, 'admin_order_page', '''WITH page AS (
        SELECT o.order_id FROM orders o JOIN commerce_order_details d USING(order_id)
        WHERE (CAST(:upper_id AS bigint) IS NULL OR o.order_id<=CAST(:upper_id AS bigint))
          AND (CAST(:after_id AS bigint) IS NULL OR o.order_id<CAST(:after_id AS bigint))
        ORDER BY o.order_id DESC LIMIT :page_size
      ) SELECT o.order_id,o.order_no,o.status AS order_state,
      o.total_amount,d.context_id,d.owner_scope,d.owner_identity,d.request_id,d.request_basis,d.snapshot,
      d.policy_snapshot,d.provider_binding,d.states,d.revision,d.expires_at,d.write_txid,
      ledger.approved,ledger.refunded,
      proof.payment_id AS approval_payment_id,proof.amount AS approval_amount,
      proof.operation AS approval_operation,proof.verification AS approval_verification,
      proof.write_txid AS approval_write_txid
      FROM page JOIN orders o USING(order_id) JOIN commerce_order_details d USING(order_id)
      CROSS JOIN LATERAL (
        SELECT COALESCE(sum(CASE WHEN p.status='승인' THEN p.amount ELSE 0 END),0)::bigint AS approved,
               COALESCE(-sum(CASE WHEN p.status='환불' THEN p.amount ELSE 0 END),0)::bigint AS refunded
        FROM payments p WHERE p.order_id=o.order_id AND p.commerce_operation_id IS NOT NULL
      ) ledger
      LEFT JOIN LATERAL (
        SELECT p.payment_id,p.amount,x.operation,x.verification,x.write_txid
        FROM payments p JOIN commerce_payment_operations x ON x.operation_id=p.commerce_operation_id
        WHERE p.order_id=o.order_id AND x.order_id=o.order_id
          AND p.status='승인' AND x.kind='approve' AND x.state='confirmed'
      ) proof ON TRUE ORDER BY o.order_id DESC''',
                upper_id=upper_id, after_id=after_id, page_size=limit + 1).mappings().all()


@_atomic
def read_committed_admin_orders(conn, *, now, limit=20, upper_id=None, after_id=None, authorize=None):
    """Private, bounded collection projection with original committed-proof checks.

    TXID checks remain bounded per order; this is not a claim of one total SQL.
    The caller owns the read-only transaction and public envelope/redaction.
    """
    _require_admin_list_read(authorize, now)
    limit = c.integer(limit, 1, 50)
    if (upper_id is None) != (after_id is None):
        c.fail('invalid_order_cursor')
    if upper_id is not None:
        upper_id, after_id = c.integer(upper_id, 1), c.integer(after_id, 1)
        if after_id > upper_id:
            c.fail('invalid_order_cursor')
    rows = _read_admin_order_page(conn, limit, upper_id, after_id)
    if len(rows) > limit + 1:
        c.fail('committed_approval_cardinality')
    records, previous, names = [], None, set()
    for raw in rows:
        row = dict(raw)
        identifier = c.integer(row['order_id'], 1)
        if previous is not None and identifier >= previous:
            c.fail('committed_approval_cardinality')
        if ((upper_id is not None and identifier > upper_id)
                or (after_id is not None and identifier >= after_id)
                or row['order_no'] in names):
            c.fail('invalid_order_page')
        previous = identifier
        names.add(row['order_no'])
        approved, refunded = c.integer(row['approved']), c.integer(row['refunded'])
        if refunded > approved or approved > c.integer(row['total_amount']):
            c.fail('invalid_payment_balance')
        _committed(conn, row)
        if row['owner_scope'] != c.fingerprint(c.owner_identity(row['owner_identity'])):
            c.fail('owner_scope_mismatch')
        records.append(_committed_order_result(conn, row, now=now))
    more = len(records) > limit
    return dict(records=records[:limit], upper_id=upper_id if upper_id is not None else
                (c.integer(rows[0]['order_id'], 1) if rows else None),
                after_id=c.integer(rows[limit-1]['order_id'], 1) if more else None)
