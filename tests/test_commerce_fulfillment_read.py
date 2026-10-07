"""Actual read/proof functions over existing shipment SQL-result fixtures, not PG."""
from copy import deepcopy
from decimal import Decimal
import re
import json
import unittest
from unittest.mock import patch

from api import commerce_contract as c
from api import commerce_owner as owner
from api import commerce_fulfillment_read as read
from api import commerce_fulfillment_writer as writer
from tests.test_commerce_fulfillment_writer import Connection as StoredConnection
from tests.test_commerce_fulfillment_writer import Result, prep_request, shipping_request, policy, authorize
from tests import test_commerce_fulfillment_core as fixture

NO = 'fixture-order'
TOKEN = 'A' * 43


class Connection(StoredConnection):
    def __init__(self):
        super().__init__()
        row = self.order(NO)
        self.owner_context = dict(context_id=row['context_id'], owner_scope=row['owner_scope'],
            owner_identity=row['owner_identity'], credential_hash=owner.credential_digest(TOKEN),
            created_at=0, expires_at=10000, revoked_at=None)
        self.snapshot_hook = None
        self.scope_hidden = False

    def execute(self, statement, params=None):
        sql = str(statement); params = params or {}
        found = re.search(r'/\*fulfillment_read:(\w+)\*/', sql)
        if not found:
            return super().execute(statement, params)
        tag = found[1]; self.trace.append((tag, sql, deepcopy(params)))
        if self.fail_tag == tag:
            raise RuntimeError(fixture.PRIVATE)
        row = self.order(params['no']) if params['no'] in self.data['orders'] else None
        if self.scope_hidden or (row is not None and 'context' in params and
                (row['context_id'] != params['context'] or row['owner_scope'] != params['scope']
                 or row['owner_identity'] != json.loads(params['identity']))):
            row = None
        if row is None:
            return Result([])
        scoped = {key: deepcopy(row[key]) for key in ('order_id', 'order_no', 'context_id', 'owner_scope', 'owner_identity')}
        if tag == 'scope':
            return Result([scoped])
        if tag == 'snapshot':
            value = dict(scoped, **{key: deepcopy(row[key]) for key in ('order_state', 'snapshot', 'revision', 'write_txid')},
                read_txid=self.txid, parents=[deepcopy(p) for _, p in sorted(self.data['ships'].items())],
                cargo=sorted(deepcopy(self.data['cargo']), key=lambda l: (l['shipment_id'], l['line_id'])),
                operations=[deepcopy(op) for _, op in sorted(self.data['physical_ops'].items())])
            if self.snapshot_hook:
                self.snapshot_hook(value)
            return Result([value])
        raise AssertionError('unexpected read tag ' + tag)


def admin_authorize(*, order_no, action, now):
    return dict(auth_source='api.auth.current_operator', authenticated=True, allowed=True,
                actor=dict(operator_id=7, role='viewer', status='활성'),
                permission='commerce.order.read', order_no=order_no, action=action, checked_at=now)


def customer_authorize(conn):
    def callback(**kwargs):
        row = conn.owner_context
        return owner.OwnerContext(row['context_id'], row['owner_scope'], deepcopy(row['owner_identity']), row['expires_at'])
    return callback


def committed(conn, req, preparation_policy=None):
    if req.get('contract') == writer.VERSION:
        pending = writer.execute_preparation(conn, req, policy=policy() if preparation_policy is None else preparation_policy,
                                             authorize=authorize(req), now=conn.clock)
    else:
        pending = writer.execute_fulfillment(conn, req, fulfillment_policy=fixture.inputs()['policy'],
            preparation_policy=policy() if preparation_policy is None else preparation_policy,
            authorize=authorize(req), now=conn.clock)
    conn.commit_simulation()
    return pending['result']['shipment_id']


def prepare(conn, lines=None):
    request = prep_request(conn, lines=lines)
    return committed(conn, request), request


def ready(conn, sid):
    for event in ('assembly_started', 'assembly_completed', 'inspection_recorded'):
        lines = [line for line in conn.data['cargo'] if line['shipment_id'] == sid]
        request = prep_request(conn, 'record_preparation_event', sid=sid, event=event,
            quantities=[dict(line_id=line['line_id'], observed_qty=line['qty']) for line in lines],
            outcome='accepted' if event == 'inspection_recorded' else 'recorded')
        committed(conn, request)
    refs = [dict(operation_id=op['operation_id'], evidence_basis=op['request']['evidence']['basis'])
            for op in conn.data['physical_ops'].values() if op['action'] == 'record_preparation_event'
            and op['request']['event_kind'] in ('assembly_completed', 'inspection_recorded')]
    request = prep_request(conn, 'confirm_dispatch_ready', sid=sid, refs=refs)
    committed(conn, request)
    return request


class FulfillmentReadTests(unittest.TestCase):
    def setUp(self):
        self.conn = Connection()

    def current(self, audience='customer'):
        return read.read_current(self.conn, NO, audience=audience, now=self.conn.clock,
            authorize=customer_authorize(self.conn) if audience == 'customer' else admin_authorize)

    def test_empty_is_real_complete_snapshot_not_missing_schema_fallback(self):
        payload = self.current()
        self.assertEqual(payload['shipments'], [])
        self.assertEqual([tag for tag, _, _ in self.conn.trace].count('snapshot'), 1)
        self.conn.fail_tag = 'snapshot'
        with self.assertRaises(c.CommerceError):
            self.current()

    def test_customer_scope_precedes_whole_snapshot_and_no_financial_or_write_locks(self):
        sid, _ = prepare(self.conn); self.conn.trace.clear()
        payload = self.current()
        self.assertEqual(payload['shipments'][0]['shipment_id'], sid)
        tags = [tag for tag, _, _ in self.conn.trace]
        self.assertLess(tags.index('scope'), tags.index('snapshot'))
        sql = next(sql for tag, sql, _ in self.conn.trace if tag == 'snapshot')
        self.assertIn('jsonb_agg', sql)
        for table in ('commerce_shipments', 'commerce_shipment_lines', 'commerce_physical_operations'):
            self.assertIn(table, sql)
        self.assertNotIn('FOR UPDATE', sql); self.assertNotIn('LIMIT', sql)
        self.assertNotRegex(sql, r'\bpayments\b|\bcommerce_payment_operations\b|\bprovider_binding\b')
        self.assertIn('d.context_id=CAST(:context AS uuid)', sql)

    def test_foreign_or_absent_same404_before_any_shipment_or_operation_query(self):
        for no, foreign in ((NO, True), ('absent-order', False)):
            self.conn = Connection(); self.conn.scope_hidden = foreign
            with self.assertRaises(read.HTTPError) as error:
                read.read_current(self.conn, no, audience='customer', now=100, authorize=customer_authorize(self.conn))
            self.assertEqual((error.exception.status, error.exception.code), (404, 'order_not_found'))
            self.assertFalse(any(tag == 'snapshot' for tag, _, _ in self.conn.trace))

    def test_prepared_invoice_handoff_delivery_times_have_separate_meanings(self):
        sid, _ = prepare(self.conn)
        self.assertEqual(self.current()['shipments'][0]['handed_off_at'], None)
        ready(self.conn, sid)
        for action in ('record_tracking', 'handoff', 'deliver'):
            req = shipping_request(self.conn, sid, action); committed(self.conn, req)
            ship = self.current()['shipments'][0]
            self.assertEqual(ship['shipment_state'], {'record_tracking':'준비', 'handoff':'배송중', 'deliver':'완료'}[action])
            self.assertEqual(ship[{'record_tracking':'tracking_recorded_at','handoff':'handed_off_at','deliver':'delivered_at'}[action]], req['evidence']['occurred_at'])
            if action == 'record_tracking':
                self.assertIsNone(ship['handed_off_at']); self.assertIsNone(ship['delivered_at'])

    def test_current_is_distinct_from_earlier_operation_result_and_no_replan(self):
        sid, original = prepare(self.conn); ready(self.conn, sid)
        committed(self.conn, shipping_request(self.conn, sid)); committed(self.conn, shipping_request(self.conn, sid, 'handoff'))
        with patch.object(writer, '_origin', side_effect=AssertionError('no replan')), patch.object(writer, '_observations', side_effect=AssertionError('no locks')):
            payload = self.current('admin')
        self.assertEqual(payload['order_state'], '배송중')
        self.assertEqual(self.conn.data['physical_ops'][original['operation_id']]['result']['order_state'], '결제완료')
        self.assertIsNone(payload['expected_order_basis'])
        self.assertTrue(all(item['allowed'] is False for item in payload['actions'].values()))

    def test_customer_allowlist_excludes_finance_actor_evidence_and_is_detached(self):
        sid, _ = prepare(self.conn); ready(self.conn, sid)
        payload = self.current()
        self.assertEqual(set(payload), {'version','state','order_no','order_state','checked_at','shipments','context'})
        self.assertEqual(set(payload['shipments'][0]), {'shipment_id','shipment_state','lines','carrier','tracking_no','tracking_recorded_at','handed_off_at','delivered_at'})
        encoded = str(payload)
        for private in (fixture.PRIVATE, 'actor_id', 'owner_identity', 'total_amount', 'request_basis', 'readiness', 'operation_id', 'approved', 'product_code', 'sale_movement_id'):
            self.assertNotIn(private, encoded)
        payload['shipments'][0]['lines'][0]['qty'] = 999
        self.assertEqual(self.current()['shipments'][0]['lines'][0]['qty'], 3)

    def test_all_prepared_partial_quantities_count_and_overallocation_fails(self):
        prepare(self.conn, fixture.cargo_lines(a=1,b=1)); prepare(self.conn, fixture.cargo_lines(a=2,b=1))
        self.assertEqual(len(self.current()['shipments']), 2)
        self.conn.snapshot_hook = lambda row: row['cargo'].append(dict(row['cargo'][0]))
        with self.assertRaises(c.CommerceError): self.current()

    def test_unknown_operation_and_unconnected_contract_never_disappear(self):
        for key, value in (('state','unknown'), ('contract','future-return-contract')):
            self.conn = Connection(); _, req = prepare(self.conn)
            self.conn.data['physical_ops'][req['operation_id']][key] = value
            with self.assertRaises(c.CommerceError): self.current()

    def test_missing_operation_gap_and_dangling_cargo_parent_fail(self):
        for mutation in (lambda conn: conn.data['physical_ops'].clear(),
                         lambda conn: conn.data['cargo'][0].update(shipment_id=999),
                         lambda conn: conn.data['ships'][10].update(revision=999999999)):
            self.conn = Connection(); prepare(self.conn); mutation(self.conn)
            with self.assertRaises(c.CommerceError): self.current()

    def test_native_integer_boolean_decimal_null_and_actual_snapshot_txid_checked(self):
        for field, value in (('revision',True), ('write_txid',None), ('read_txid',Decimal(2)), ('read_txid',999)):
            self.conn = Connection(); prepare(self.conn)
            self.conn.snapshot_hook = lambda row, key=field, val=value: row.update({key:val})
            with self.assertRaises(c.CommerceError): self.current()

    def test_resealed_result_and_ready_and_latest_parent_proof_tampering_fail(self):
        for mutate in (lambda conn, req: conn.data['physical_ops'][req['operation_id']]['result'].update(shipment_revision=99),
                            lambda conn, req: conn.data['ships'][10].update(readiness_operation_id=None),
                            lambda conn, req: conn.data['ships'][10].update(write_txid=123)):
            self.conn = Connection(); sid, _ = prepare(self.conn); req = ready(self.conn, sid)
            mutate(self.conn, req)
            op = self.conn.data['physical_ops'][req['operation_id']]
            op['receipt']['result_basis'] = c.fingerprint(dict(identity=op['identity'],result=op['result']))
            with self.assertRaises(c.CommerceError): self.current()

    def test_public_delivery_requires_stored_chronological_physical_evidence(self):
        sid, _ = prepare(self.conn); ready(self.conn, sid)
        for action in ('record_tracking','handoff','deliver'): committed(self.conn, shipping_request(self.conn,sid,action))
        self.conn.data['ships'][sid]['delivery_evidence']['occurred_at'] = 1
        with self.assertRaises(c.CommerceError): self.current()

    def test_load_request_foreign_uuid_is404_and_returns_copy_not_raw_result(self):
        _, req = prepare(self.conn)
        copied = read.load_request(self.conn, NO, req['operation_id'], authorize=admin_authorize, now=self.conn.clock)
        self.assertEqual(copied, req); copied['actor_id'] = 99
        self.assertEqual(self.conn.data['physical_ops'][req['operation_id']]['request']['actor_id'], 7)
        self.conn.data['physical_ops'][req['operation_id']]['order_id'] = 88
        with self.assertRaises(read.HTTPError) as error:
            read.load_request(self.conn, NO, req['operation_id'], authorize=admin_authorize, now=self.conn.clock)
        self.assertEqual(error.exception.status, 404)

    def test_admin_grant_cannot_be_client_boolean_or_fallback_actor(self):
        for grant in (None, True,
                dict(admin_authorize(order_no=NO,action='read',now=100), checked_at=Decimal(100)),
                dict(admin_authorize(order_no=NO,action='read',now=100), actor=dict(operator_id=True,role='owner',status='활성'))):
            self.conn = Connection()
            with self.assertRaises(c.CommerceError):
                read.read_current(self.conn, NO, audience='admin', authorize=lambda **_:grant, now=100)

    def test_admin_history_keeps_all_stages_original_ids_and_observed_times(self):
        sid, original = prepare(self.conn)
        ready_request = ready(self.conn, sid)
        requests = [shipping_request(self.conn, sid)]
        committed(self.conn, requests[0])
        for action in ('handoff', 'deliver'):
            requests.append(shipping_request(self.conn, sid, action))
            committed(self.conn, requests[-1])
        self.conn.snapshot_hook = lambda row: row['operations'].reverse()
        payload = self.current('admin')
        history = payload['shipments'][0]['history']
        self.assertEqual([row['action'] for row in history], [
            'prepare_shipment', 'record_preparation_event', 'record_preparation_event',
            'record_preparation_event', 'confirm_dispatch_ready', 'record_tracking', 'handoff', 'deliver'])
        self.assertEqual([row['shipment_revision'] for row in history], list(range(1, 9)))
        self.assertEqual([row['order_revision'] for row in history],
                         list(range(original['expected_order_revision'] + 1, original['expected_order_revision'] + 9)))
        self.assertEqual(history[0]['operation_id'], original['operation_id'])
        self.assertEqual(history[4]['operation_id'], ready_request['operation_id'])
        self.assertEqual([row['event_kind'] for row in history[1:4]], list(writer.EVENTS))
        self.assertEqual([row['outcome'] for row in history[1:4]], ['recorded', 'recorded', 'accepted'])
        for row in history[1:4]:
            self.assertEqual(row['quantities'], [dict(line_id='a', observed_qty=3), dict(line_id='b', observed_qty=2)])
        for row, req in zip(history[-3:], requests):
            self.assertEqual(row['operation_id'], req['operation_id'])
            self.assertEqual(row['occurred_at'], req['evidence']['occurred_at'])
            self.assertEqual(row['reference'], req['evidence']['reference'])
            self.assertIsNone(row['event_kind']); self.assertIsNone(row['outcome']); self.assertIsNone(row['quantities'])
        self.assertEqual([row['ready'] for row in history], [False] * 4 + [True] * 4)
        self.assertIsNone(payload['expected_order_basis'])
        self.assertEqual(payload['actions'], {action: dict(allowed=False, reason='source_unconnected') for action in read.ACTIONS})

    def test_admin_history_uses_stored_actor_and_null_when_no_observation_exists(self):
        request = prep_request(self.conn, actor_id=8)
        committed(self.conn, request)
        payload = self.current('admin')
        entry = payload['shipments'][0]['history'][0]
        self.assertEqual(entry['actor_id'], 8)
        self.assertNotEqual(entry['actor_id'], admin_authorize(order_no=NO, action='read', now=self.conn.clock)['actor']['operator_id'])
        for field in ('event_kind', 'quantities', 'outcome', 'occurred_at', 'reference'):
            self.assertIsNone(entry[field])
        self.assertIsNotNone(payload['checked_at'])
        self.assertFalse(entry['ready'])

    def test_admin_history_preserves_latest_rejected_inspection_and_invalidated_ready(self):
        sid, _ = prepare(self.conn); ready(self.conn, sid)
        rejection = prep_request(self.conn, 'record_preparation_event', sid=sid, event='inspection_recorded',
            quantities=[dict(line_id='a', observed_qty=3), dict(line_id='b', observed_qty=2)], outcome='rejected')
        committed(self.conn, rejection)
        ship = self.current('admin')['shipments'][0]
        inspections = [row for row in ship['history'] if row['event_kind'] == 'inspection_recorded']
        self.assertEqual([row['outcome'] for row in inspections], ['accepted', 'rejected'])
        self.assertEqual(inspections[-1]['operation_id'], rejection['operation_id'])
        self.assertFalse(ship['ready']); self.assertFalse(ship['history'][-1]['ready'])
        self.assertTrue(ship['history'][-2]['ready'])

    def test_admin_history_is_scoped_per_shipment_and_customer_stays_private(self):
        one, req_one = prepare(self.conn, fixture.cargo_lines(a=1, b=1))
        two, req_two = prepare(self.conn, fixture.cargo_lines(a=2, b=1))
        payload = self.current('admin')
        self.assertEqual([(ship['shipment_id'], [row['operation_id'] for row in ship['history']])
                          for ship in payload['shipments']], [(one, [req_one['operation_id']]), (two, [req_two['operation_id']])])
        self.assertEqual([ship['history'][0]['shipment_revision'] for ship in payload['shipments']], [1, 1])
        customer = self.current()
        for ship in customer['shipments']:
            self.assertNotIn('history', ship)
        for forbidden in ('actor_id', 'operation_id', 'reference', 'quantities', 'outcome'):
            self.assertNotIn(forbidden, str(customer))

    def test_admin_history_allowlist_and_nested_values_are_detached_from_storage(self):
        sid, _ = prepare(self.conn); ready(self.conn, sid)
        payload = self.current('admin')
        history = payload['shipments'][0]['history']
        fields = {'operation_id', 'action', 'shipment_revision', 'order_revision', 'actor_id', 'event_kind',
                  'quantities', 'outcome', 'occurred_at', 'reference', 'ready'}
        for row in history:
            self.assertEqual(set(row), fields)
        def keys(value):
            if isinstance(value, dict):
                return set(value).union(*(keys(item) for item in value.values()))
            if isinstance(value, list):
                return set().union(*(keys(item) for item in value))
            return set()
        for forbidden in ('request_basis', 'owner_identity', 'owner_scope', 'provider_binding', 'verification',
                          'receipt', 'evidence_basis', 'rules_basis', 'content_basis', 'product_code', 'sale_movement_id'):
            self.assertNotIn(forbidden, keys(payload))
        before = deepcopy(self.conn.data)
        history[1]['quantities'][0]['observed_qty'] = 999
        history[1]['actor_id'] = 99; history[1]['reference'] = 'changed display reference'
        history.reverse(); payload['shipments'].clear()
        self.assertEqual(self.conn.data, before)
        fresh = self.current('admin')['shipments'][0]['history']
        self.assertEqual(fresh[1]['quantities'][0]['observed_qty'], 3)
        self.assertEqual(fresh[1]['actor_id'], 7)


if __name__ == '__main__':
    unittest.main()
