"""Actual v2 routes/canonical plus frozen same-statement reader, SQL mocks only."""
import ast
from copy import deepcopy
from decimal import Decimal
import hashlib
from pathlib import Path
import unittest

from fastapi import HTTPException
from api.reprice_preview_expected import canonical_basis,make_expected,canonical_basis_v2,make_expected_v2,InvalidPreviewBasis
from tests.test_reprice_write_lock_order import (
    ROOT,Database,routes,product,expected_snapshot,revision_module_baseline,digest,
    POLICY_SHARED_SQL,receipt_core,_LOCK_PRODUCTS_SQL,
)


class RevisionExpectedTests(unittest.TestCase):
    def setUp(self):
        self.db=Database();self.env=routes()
        self.env.update(engine=self.db,current_operator=self.db.operator,current_operator_id=self.db.actor,_log=self.db.log)

    def preview(self):return self.env['preview']('all')
    def body(self,preview=None):
        preview=self.preview() if preview is None else preview
        return self.env['ApplyBody'](scope='all',expect_changed=preview['changed'],expected=preview['expected'],note=' preserve ')
    def business(self,start=0):
        return [(q,p) for q,p in self.db.calls[start:] if q.startswith(('UPDATE ','INSERT ','DELETE ')) and q!=receipt_core.INSERT_SQL]
    def reject(self,body):
        before=self.db.state();start=len(self.db.calls)
        with self.assertRaises(HTTPException) as caught:self.env['apply'](body)
        self.assertEqual(caught.exception.status_code,409)
        self.assertEqual(self.business(start),[]);self.assertEqual(self.db.state(),before)
        record=self.db.receipts[(body.operation_context.environment,body.operation_id)]
        self.assertEqual(record['state'],'rejected')
        return self.db.calls[start:]
    def token(self,rows=None,revisions=None,policy=1,cap=1,v2=True):
        rows=[product(1,9000),product(2,13000)] if rows is None else rows
        args=dict(scope='all',rows=rows,fee=.02,margin=.03,mmap={},max_apply=cap)
        if v2:
            if revisions is None:revisions={r['product_code']:r['product_code'] for r in rows}
            basis=canonical_basis_v2(**args,product_revisions=revisions,policy_revision=policy)
            return make_expected_v2(basis,self.env['_classify'](rows,.02,.03,{}),scope='all',max_apply=cap)
        return make_expected(canonical_basis(**args),self.env['_classify'](rows,.02,.03,{}),scope='all',max_apply=cap)

    def test_exact_v2_overlay_preserves_full_accepted_u6_and_legacy_pure_module(self):
        tree=ast.parse((ROOT/'api/admin_reprice.py').read_text(encoding='utf-8'));overlay=[]
        self.assertEqual(digest(revision_module_baseline(tree,overlay)),
                         'fa16d7a5ad5cb066c9a54fb85ac0a6aa00ce59eb5918e3386530ee1ff18123ab')
        self.assertEqual(digest(ast.Module(overlay,[])),
                         'fa0e49f1ace8dd3473577a78175d70a6de4551d1a0b60c6d413a79e9824155e1')
        pure=ast.parse((ROOT/'api/reprice_preview_expected.py').read_text(encoding='utf-8'))
        pure.body=[n for n in pure.body if not (isinstance(n,ast.FunctionDef) and n.name in ('canonical_basis_v2','make_expected_v2'))
                   and not (isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='EXPECTED_VERSION_V2' for t in n.targets))]
        self.assertEqual(digest(pure),'85346abfb15a6a49163ee4ddf322506d8cdca159cab236e6122c2b33094eff4f')

    def test_frozen_revision_migration_reader_tests_remain_exact(self):
        for path,wanted in {
            'db/migrations/versions/0125_pricing_basis_revisions.py':'adbb55eba217f53c2736f98026013607c9d483fd6b0fb419207ab9deefef8bb2',
            'api/reprice_basis_snapshot.py':'d752d3c189aeb5204f1c798a92d75adf2d5502a43268db1b798ba7e958edde6f',
            'tests/test_reprice_basis_revision.py':'5606cb165c88a63eb11fa79fbc827610ed9d95d42c2056dd580e82196e3e24f2'}.items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),wanted)

    def test_v2_closed_exact_code_tokens_and_native_signed_bigint_reject_missing_extra_wrong_types(self):
        invalid=({}, {1:1},{1:1,2:2,3:3},{1:True,2:2},{1:1.0,2:2},{1:'1',2:2},
                 {1:0,2:2},{1:-1,2:2},{1:9223372036854775808,2:2},{True:1,2:2},[],None)
        for revisions in invalid:
            with self.subTest(revisions=revisions):
                with self.assertRaises(InvalidPreviewBasis):
                    canonical_basis_v2(scope='all',rows=[product(1,9000),product(2,13000)],fee=.02,margin=.03,
                                       mmap={},max_apply=1,product_revisions=revisions,policy_revision=1)
        for policy in (None,True,0,-1,1.0,'1',Decimal(1),9223372036854775808):
            with self.subTest(policy=policy):
                with self.assertRaises(InvalidPreviewBasis):self.token(policy=policy)
        for rows in ([product(1,9000),product(1,13000)],[product(0,9000)]):
            with self.assertRaises(InvalidPreviewBasis):self.token(rows=rows)

    def test_empty_scope_has_exact_empty_tokens_and_positive_policy_evidence(self):
        self.assertEqual(self.token(rows=[],revisions={})['version'],'reprice_basis_v2')
        with self.assertRaises(InvalidPreviewBasis):self.token(rows=[],revisions={1:1})
        with self.assertRaises(InvalidPreviewBasis):make_expected_v2([],{},scope='all',max_apply=1)

    def test_bigint_tokens_stay_exact_scope_and_plan_order_are_not_lost(self):
        token=9007199254740993
        self.assertNotEqual(self.token(revisions={1:token,2:2}),self.token(revisions={1:token+1,2:2}))
        self.assertNotEqual(self.token(policy=token),self.token(policy=token+1))
        self.assertEqual(self.token(revisions={2:2,1:1}),self.token())
        self.assertNotEqual(self.token(rows=[product(2,13000),product(1,9000)]),self.token())
        self.assertNotEqual(self.token(cap=2),self.token(cap=1))
        self.assertNotEqual(self.token()['fingerprint'],self.token(v2=False)['fingerprint'])

    def test_preview_uses_one_snapshot_after_policy_and_preserves_display_summary(self):
        old=self.env['_summary'](self.env['_classify']([deepcopy(r) for r in self.db.products.values() if r['purchase_price']],
                                                    self.db.fee,self.db.margin,{}),'all',self.db.fee,self.db.margin)
        result=self.preview()
        self.assertEqual({k:v for k,v in result.items() if k!='expected'},old)
        self.assertEqual(result['expected']['version'],'reprice_basis_v2')
        self.assertEqual(self.db.calls[0][0],POLICY_SHARED_SQL)
        self.assertEqual(len(self.db.calls),2)
        self.assertTrue(self.db.calls[1][0].lstrip().startswith('WITH scoped_products AS'))
        self.assertEqual((self.db.begins,self.db.commits), (0,0))

    def test_product_value_A_B_A_with_changed_native_token_rejects_before_product_lock(self):
        old=self.preview();body=self.body(old)
        self.db.products[102]['purchase_price']=14000
        self.db.products[102]['purchase_price']=10000
        self.db.product_revisions[102]+=2  # committed DB revision evidence, mocked
        self.assertEqual(self.preview()['changed'],old['changed'])
        calls=self.reject(body)
        self.assertFalse(any(q==_LOCK_PRODUCTS_SQL for q,p in calls))
        self.assertEqual((self.db.commits,self.db.rollbacks),(1,0))

    def test_policy_ancestor_global_same_value_cycle_revision_rejects_unchanged_values(self):
        for basis in ('global','ancestor','margin-delete-reinsert'):
            with self.subTest(basis=basis):
                self.setUp();old=self.preview();body=self.body(old)
                self.db.policy_revision+=2  # source trigger semantics tested in frozen revision suite
                new=self.preview()
                self.assertEqual({k:v for k,v in old.items() if k!='expected'},{k:v for k,v in new.items() if k!='expected'})
                self.assertNotEqual(old['expected'],new['expected'])
                self.assertFalse(any(q==_LOCK_PRODUCTS_SQL for q,p in self.reject(body)))

    def test_same_product_code_recreated_with_new_generation_rejects(self):
        body=self.body();row=deepcopy(self.db.products[102]);del self.db.products[102]
        self.db.products[102]=row;self.db.product_revisions[102]+=10
        self.reject(body)

    def test_cap_excluded_unchanged_and_locked_row_revision_tokens_are_all_bound(self):
        for code in (104,105,106):
            with self.subTest(code=code):
                self.setUp();self.env['MAX_APPLY']=3;body=self.body()
                self.db.product_revisions[code]+=1
                calls=self.reject(body)
                self.assertFalse(any(q==_LOCK_PRODUCTS_SQL for q,p in calls))

    def test_postlock_product_or_policy_only_token_drift_rejects_before_first_business_write(self):
        for change in (lambda d:d.product_revisions.__setitem__(102,d.product_revisions[102]+1),
                       lambda d:d.product_revisions.__setitem__(105,d.product_revisions[105]+1),
                       lambda d:setattr(d,'policy_revision',d.policy_revision+1)):
            self.setUp();body=self.body();self.db.after_lock=change
            calls=self.reject(body)
            self.assertEqual([p['codes'] for q,p in calls if q==_LOCK_PRODUCTS_SQL],[[101,102,103,104]])
            self.assertEqual(sum(q.lstrip().startswith('WITH scoped_products AS') for q,p in calls),2)
            self.assertEqual((self.db.commits,self.db.rollbacks),(1,0))

    def test_noop_and_rolled_back_generation_evidence_leaves_expected_unchanged(self):
        old=self.preview();saved=deepcopy((self.db.products,self.db.product_revisions,self.db.policy_revision))
        self.db.products[102]['sale_price']=self.db.products[102]['sale_price']
        self.assertEqual(self.preview()['expected'],old['expected'])
        self.db.products[102]['sale_price']=18000;self.db.product_revisions[102]+=1;self.db.policy_revision+=1
        self.db.products,self.db.product_revisions,self.db.policy_revision=deepcopy(saved)
        self.assertEqual(self.preview()['expected'],old['expected'])
        self.assertEqual(self.env['apply'](self.body(old))['changed'],4)

    def test_missing_or_invalid_current_tokens_fail_closed_receipt_only_on_apply(self):
        for mutate in (lambda d:d.product_revisions.pop(102),lambda d:d.product_revisions.__setitem__(102,True),
                       lambda d:setattr(d,'policy_revision',None),lambda d:setattr(d,'policy_revision',0)):
            self.setUp();body=self.body();mutate(self.db)
            self.reject(body)
        self.setUp();self.db.policy_revision=None
        with self.assertRaises(HTTPException) as caught:self.preview()
        self.assertEqual(caught.exception.status_code,409)
        self.assertEqual(self.db.receipts,{})

    def test_native_sql_error_including_value_and_http_types_is_never_terminal_rejected(self):
        for postlock in (False,True):
            for error in (RuntimeError('driver'),ValueError('driver'),TypeError('driver'),HTTPException(409,'driver')):
                self.setUp();body=self.body()
                self.db.fail=lambda q,p,e=error: e if q.lstrip().startswith('WITH scoped_products AS') and (
                    not postlock or any(query==_LOCK_PRODUCTS_SQL for query,params in self.db.calls)) else None
                with self.assertRaises(type(error)) as caught:self.env['apply'](body)
                self.assertIs(caught.exception,error);self.assertEqual(self.db.receipts,{})
                self.assertEqual(self.business(),[]);self.assertEqual((self.db.commits,self.db.rollbacks),(0,1))

    def test_replay_v2_receipt_skips_basis_even_if_tokens_or_values_are_now_invalid(self):
        body=self.body();first=self.env['apply'](body)
        self.db.policy_revision=None;self.db.products[102]['purchase_price']=True
        start=len(self.db.calls);state=self.db.state()
        self.assertEqual(self.env['apply'](body),first)
        self.assertEqual([q for q,p in self.db.calls[start:]],
                         [POLICY_SHARED_SQL,receipt_core.OPERATION_LOCK_SQL,receipt_core.LOOKUP_SQL])
        self.assertEqual(self.db.state(),state);self.assertEqual(self.business(start),[])

    def test_success_has_two_snapshot_reads_original_history_afterfacts_actor_and_receipt(self):
        body=self.body();start=len(self.db.calls);answer=self.env['apply'](body)
        calls=self.db.calls[start:]
        self.assertEqual(sum(q.lstrip().startswith('WITH scoped_products AS') for q,p in calls),2)
        self.assertEqual(calls[-1][0],receipt_core.INSERT_SQL)
        self.assertEqual(answer['changed'],4)
        self.assertEqual([h['op'] for h in self.db.histories],[21]*4)
        self.assertEqual([h['old'] for h in self.db.histories],[9000,10000,18000,15000])
        self.assertEqual([r['after_sale'] for r in self.db.logs[-1]['detail']['before']],[11000]*4)
        self.assertEqual(self.db.logs[-1]['detail']['note'],'preserve')
        self.assertEqual((self.db.commits,self.db.rollbacks),(1,0))


if __name__=='__main__':unittest.main()
