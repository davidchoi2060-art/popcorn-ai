"""Bounded page/committed-proof simulations; NOT PostgreSQL/MVCC evidence."""
from copy import deepcopy
import re
import unittest
from uuid import UUID, uuid5
from unittest.mock import patch

from api import commerce_contract as c
from api import commerce_writer as w
from tests import test_commerce_writer as f
from tests.test_commerce_contract import owner, policy, sale, draft
from tests.test_commerce_payment_core import spec, evidence, verifier


class PageConnection(f.Connection):
    """Capture one statement's data and simulate only this bounded SQL contract."""
    def __init__(self):
        super().__init__()
        self.on_page = None
        self.row_change = None
        self.nested = False
        self.autocommit = False
        self.on_txid = None
    def in_nested_transaction(self): return self.nested
    def get_execution_options(self): return {'isolation_level':'AUTOCOMMIT'} if self.autocommit else {}
    def execute(self, statement, params):
        sql = str(statement)
        match = re.search(r'/\*commerce:(\w+)\*/', sql)
        tag = match[1] if match else 'product_lock'
        if tag == 'txid' and self.on_txid: self.on_txid()
        if tag != 'admin_order_page': return super().execute(statement, params)
        self.trace.append((tag, sql, deepcopy(params)))
        if self.aborted or self.fail_tag == tag: raise RuntimeError('private page SQL failure')
        observed = deepcopy(self.data)
        if self.on_page: self.on_page()
        parents = sorted((o for o in observed['orders'].values()
            if o['order_id'] in observed['details']
            and (params['upper_id'] is None or o['order_id'] <= params['upper_id'])
            and (params['after_id'] is None or o['order_id'] < params['after_id'])),
            key=lambda o:o['order_id'], reverse=True)[:params['page_size']]
        rows = []
        for order in parents:
            row = order | observed['details'][order['order_id']]
            payments = [p for p in observed['payments'] if p['order_id'] == order['order_id']]
            money = dict(approved=sum(p['amount'] for p in payments if p['amount'] > 0),
                         refunded=-sum(p['amount'] for p in payments if p['amount'] < 0))
            proofs = []
            for payment in payments:
                record = observed['operations'].get(payment['operation_id'])
                if (payment['amount'] >= 0 and record is not None and record['order_id'] == order['order_id']
                    and record['operation']['spec']['kind'] == 'approve' and record['operation']['state'] == 'confirmed'):
                    proofs.append(dict(approval_payment_id=payment['payment_id'],approval_amount=payment['amount'],
                        approval_operation=record['operation'],approval_verification=record['verification'],
                        approval_write_txid=record['write_txid']))
            empty = dict.fromkeys(('approval_payment_id','approval_amount','approval_operation',
                                   'approval_verification','approval_write_txid'))
            rows.extend(row | money | proof for proof in (proofs or [empty]))
        if self.row_change: self.row_change(rows)
        return f.Result(rows)


def seed(count=5, paid_ids=(1, 3)):
    """Use the original actual writer/core simulated flow for committed facts."""
    conn = PageConnection(); conn.data['products'][101]['stock_qty'] = 10000
    conn.saved = deepcopy(conn.data)
    for index in range(1, count + 1):
        name = 'order-' + str(index)
        body = draft(); body['request_id'] = str(uuid5(UUID(f.CONTEXT), name))
        w.create_draft(conn, body, context_id=f.CONTEXT, owner=owner(), order_no=name,
                       sale_basis=sale(), policy=policy(), now=100, revalidate=f.reader)
        conn.commit_simulation()
        if index in paid_ids:
            basis = w.read_committed_order(conn, name, context_id=f.CONTEXT, owner=owner(), now=105)['basis_id']
            intent = spec(order_no=name, operation_id=str(uuid5(UUID(f.CONTEXT), 'op-' + name)),
                          request_id=body['request_id'], order_basis=basis)
            w.prepare(conn, intent, context_id=f.CONTEXT, owner=owner(), expected_basis=basis,
                      policy=policy(), now=105, revalidate=f.reader)
            conn.commit_simulation()
            w.dispatch(conn, intent['operation_id'], expected_revision=1, now=110, lease_expires_at=130)
            conn.commit_simulation()
            operation = w.read_committed_operation(conn, intent['operation_id'], now=120)
            event = evidence(operation)
            w.finalize(conn, intent['operation_id'], event, verifier(operation, event), expected_revision=2, now=120)
            conn.commit_simulation()
    conn.trace.clear()
    return conn


def grant(*, scope, now):
    return dict(auth_source='api.auth.current_operator',authenticated=True,
                actor=dict(operator_id=21,role='owner',status='활성'),permission='commerce.order.list',
                allowed=True,scope=scope,checked_at=now)


class AdminListWriterTests(unittest.TestCase):
    def setUp(self): self.conn = seed(); self.before = deepcopy(self.conn.data)
    def read(self, **kwargs):
        return w.read_committed_admin_orders(self.conn,now=150,authorize=grant,**kwargs)
    def tags(self): return [tag for tag,_,_ in self.conn.trace]

    def test_pages_are_parent_bounded_descending_complete_and_no_detail_business_n_plus_one(self):
        first = self.read(limit=2)
        self.assertEqual([x['row']['order_no'] for x in first['records']],['order-5','order-4'])
        self.assertEqual((first['upper_id'],first['after_id']),(5,4))
        second = self.read(limit=2,upper_id=5,after_id=4)
        third = self.read(limit=2,upper_id=5,after_id=2)
        all_items = first['records'] + second['records'] + third['records']
        self.assertEqual([x['row']['order_no'] for x in all_items],['order-5','order-4','order-3','order-2','order-1'])
        self.assertIsNone(third['after_id'])
        self.assertTrue(all(len(x['row']['lines']) == 2 for x in all_items))
        self.assertEqual([x['approved'] for x in all_items],[0,0,2100,0,2100])
        self.assertEqual(self.tags().count('admin_order_page'),3)
        self.assertTrue(set(self.tags()) <= {'admin_order_page','txid'})
        self.assertEqual(self.conn.data,self.before)

    def test_sql_cuts_parent_before_ledger_proof_and_keeps_native_types_and_duplicates(self):
        self.read(limit=2)
        _, sql, params = next(x for x in self.conn.trace if x[0]=='admin_order_page')
        self.assertEqual(params,dict(upper_id=None,after_id=None,page_size=3))
        self.assertLess(sql.index('LIMIT :page_size'),sql.index('CROSS JOIN LATERAL'))
        self.assertEqual(sql.count('LIMIT'),1)
        self.assertIn('CAST(:upper_id AS bigint)',sql); self.assertIn('CAST(:after_id AS bigint)',sql)
        self.assertIn('p.commerce_operation_id IS NOT NULL',sql)
        self.assertIn("x.kind='approve' AND x.state='confirmed'",sql)
        for forbidden in ('FOR UPDATE','products','order_items','::text','DISTINCT','OFFSET'):
            self.assertNotIn(forbidden,sql)

    def test_empty_page_and_exact_limit_have_no_cursor(self):
        self.assertIsNone(self.read(limit=5)['after_id'])
        self.assertEqual(self.read(limit=2,upper_id=5,after_id=1)['records'],[])
        self.conn.data['orders'].clear()
        page = self.read()
        self.assertEqual(page,dict(records=[],upper_id=None,after_id=None))

    def test_insert_above_first_upper_is_excluded_and_ids_over_2pow53_are_exact(self):
        page = self.read(limit=2)
        new = deepcopy(self.conn.data['orders']['order-5']); new.update(order_id=9007199254740993,order_no='new-high')
        self.conn.data['orders']['new-high'] = new
        self.conn.data['details'][new['order_id']] = deepcopy(self.conn.data['details'][5])
        self.assertEqual([r['row']['order_no'] for r in self.read(limit=5,upper_id=page['upper_id'],after_id=page['after_id'])['records']],
                         ['order-3','order-2','order-1'])
        self.assertEqual(self.read(limit=1)['upper_id'],9007199254740993)

    def test_statement_capture_survives_interleave_but_next_page_has_its_own_state(self):
        def mutate(): self.conn.data['details'][4]['states']['allocation_state']='blocked'
        self.conn.on_page = mutate
        first = self.read(limit=2)
        self.assertEqual(first['records'][1]['row']['allocation_state'],'held')
        self.conn.on_page = None
        second = self.read(limit=2,upper_id=5,after_id=5)
        self.assertEqual(second['records'][0]['row']['allocation_state'],'blocked')

    def test_duplicate_approval_for_sentinel_or_visible_row_fails_entire_page(self):
        for limit in (2, 5):
            self.conn=seed()
            self.conn.data['payments'].append(deepcopy(self.conn.data['payments'][1]))
            with self.assertRaises(c.CommerceError): self.read(limit=limit)
            self.assertTrue(self.conn.aborted)

    def test_null_native_money_overflow_owner_scope_and_uncommitted_row_fail_closed(self):
        for mode in ('null','float','overflow','owner','uncommitted'):
            with self.subTest(mode=mode):
                self.conn = seed()
                if mode == 'owner': self.conn.data['details'][5]['owner_scope']='0'*64
                elif mode == 'uncommitted': self.conn.data['details'][5]['write_txid']=self.conn.txid
                else:
                    def bad(rows,mode=mode): rows[0]['approved']={'null':None,'float':0.0,'overflow':2**63}[mode]
                    self.conn.row_change=bad
                with self.assertRaises(c.CommerceError): self.read(limit=2)
                self.assertTrue(self.conn.aborted)

    def test_original_operation_evidence_receipt_and_owner_validation_remain_required(self):
        for mode in ('missing','attestation','receipt','owner'):
            with self.subTest(mode=mode):
                self.conn=seed(); operation=next(x for x in self.conn.data['operations'].values() if x['order_id']==3)
                if mode=='missing': operation['verification']=None
                elif mode=='attestation': operation['verification']['evidence_basis']='0'*64
                elif mode=='receipt': operation['operation']['final_commit']['payment_id']=999
                else: self.conn.data['details'][3]['owner_identity']=owner()|{'owner_hash':'f'*64}; self.conn.data['details'][3]['owner_scope']=c.fingerprint(self.conn.data['details'][3]['owner_identity'])
                with self.assertRaises(c.CommerceError): self.read(limit=3)

    def test_wrong_ordering_duplicate_identity_and_out_of_cursor_scope_fail(self):
        for mutation in (lambda rows:rows.reverse(),lambda rows:rows.append(deepcopy(rows[0])),
                         lambda rows:rows[0].update(order_id=5)):
            self.conn=seed(); self.conn.row_change=mutation
            with self.assertRaises(c.CommerceError): self.read(limit=2,upper_id=5,after_id=4)

    def test_authorization_is_collection_scoped_and_precedes_business_select(self):
        changes=[dict(permission='commerce.order.read'),dict(scope='order-1'),dict(allowed=1),
                 dict(authenticated='true'),dict(checked_at=149),dict(actor=dict(operator_id=True,role='owner',status='활성')),
                 dict(actor=dict(operator_id=21,role='customer',status='활성'))]
        for change in changes:
            with self.subTest(change=change):
                self.conn=seed()
                def denied(**kwargs): return grant(**kwargs)|change
                with self.assertRaises(c.CommerceError): w.read_committed_admin_orders(self.conn,now=150,authorize=denied)
                self.assertNotIn('admin_order_page',self.tags())
        self.conn=seed()
        with self.assertRaises(c.CommerceError): w.read_committed_admin_orders(self.conn,now=150,authorize={'allowed':True})
        self.assertNotIn('admin_order_page',self.tags())

    def test_limits_cursors_nested_and_autocommit_are_native_strict(self):
        for kwargs in ({'limit':True},{'limit':'2'},{'limit':0},{'limit':51},{'upper_id':5},
                       {'upper_id':4,'after_id':5},{'upper_id':5.0,'after_id':2},{'upper_id':2**63,'after_id':2}):
            self.conn=seed()
            with self.assertRaises(c.CommerceError): self.read(**kwargs)
            self.assertNotIn('admin_order_page',self.tags())
        for kind in ('nested','autocommit'):
            self.conn=seed(); setattr(self.conn,kind,True)
            with self.assertRaises(c.CommerceError): self.read()
            self.assertFalse(self.conn.trace)

    def test_txid_change_and_page_sql_failure_abort_caller_transaction(self):
        self.conn.on_page=lambda:setattr(self.conn,'txid',self.conn.txid+1)
        with self.assertRaises(c.CommerceError): self.read()
        self.assertTrue(self.conn.aborted)
        self.conn=seed(); self.conn.fail_tag='admin_order_page'
        with self.assertRaises(c.CommerceError): self.read()
        self.assertTrue(self.conn.aborted)

    def test_snapshot_lines_are_detached_without_product_lookup(self):
        original=w._committed_order_result
        with patch.object(w,'_committed_order_result',wraps=original) as proof:
            result=self.read(limit=2)
        self.assertEqual(proof.call_count,3)  # sentinel is checked too
        result['records'][0]['row']['lines'][0]['name']='changed'
        self.assertEqual(self.conn.data,self.before)


if __name__=='__main__': unittest.main()
