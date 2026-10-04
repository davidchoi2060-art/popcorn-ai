"""Selected actual apply/undo with caller transaction mocks; no live DB evidence."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest

from fastapi import HTTPException
from tests.test_reprice_write_lock_order import (
    Database, routes, product, expected_snapshot, _LOCK_PRODUCTS_SQL,
)


class UndoFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        self.env = routes()
        self.env.update(engine=self.db, current_operator=self.db.operator,
                        current_operator_id=self.db.actor, _log=self.db.log)

    def apply(self):
        expected = expected_snapshot(self.db, self.env, 'all')
        body = self.env['ApplyBody'](scope='all', expect_changed=4,
                                     expected=expected, note='freshness')
        return self.env['apply'](body)

    def undo(self, log_id=100):
        return self.env['undo'](SimpleNamespace(log_id=log_id))

    def seed(self, locks=None):
        self.db.products = {101:product(101,13000,locked_fields=deepcopy(locks))}
        self.db.logs = [{'log_id':100,'action':'판매가 재산정','detail':{
            'scope':'all','before':[{'pc':101,'sale':None,'after_sale':13000,
                                    'after_locked_fields':deepcopy(locks)}]}}]

    def reject_no_new_writes(self, log_id=100, status=409):
        before = self.db.state(); start = len(self.db.calls)
        with self.assertRaises(HTTPException) as caught:self.undo(log_id)
        self.assertEqual(caught.exception.status_code,status)
        self.assertEqual(self.db.state(),before)
        self.assertFalse(any(q.startswith(('UPDATE ','INSERT ','DELETE '))
                             for q,p in self.db.calls[start:]))
        return caught.exception, self.db.calls[start:]

    def test_actual_apply_logs_exact_written_sale_and_raw_null_or_list_locks(self):
        for locks in (None, [], ['maker','status']):
            self.setUp()
            self.db.products[102]['locked_fields']=deepcopy(locks)
            before = deepcopy(self.db.products)
            result = self.apply()
            entries = self.db.logs[-1]['detail']['before']
            self.assertEqual(result['changed'],4)
            self.assertEqual([e['pc'] for e in entries],[102,103,101,104])
            for e in entries:
                self.assertEqual(set(e),{'pc','sale','after_sale','after_locked_fields'})
                self.assertEqual(e['sale'],before[e['pc']]['sale_price'])
                self.assertEqual(e['after_sale'],self.db.products[e['pc']]['sale_price'])
                self.assertEqual(e['after_locked_fields'],before[e['pc']]['locked_fields'])
            self.assertEqual(entries[0]['after_locked_fields'],locks)
            self.assertEqual(self.db.actor_calls,2)

    def test_actual_apply_then_undo_restores_original_order_prices_histories_actor_and_locks(self):
        original = deepcopy(self.db.products); result = self.apply()
        entries = deepcopy(self.db.logs[-1]['detail']['before'])
        start=len(self.db.calls); hstart=len(self.db.histories)
        restored=self.undo(result['log_id'])
        self.assertEqual(restored,{'verdict':'4건의 판매가를 이전 값으로 되돌렸습니다','restored':4})
        self.assertEqual(self.db.products,original)
        self.assertEqual([h['pc'] for h in self.db.histories[hstart:]],[e['pc'] for e in entries])
        self.assertEqual([(h['old'],h['new'],h['op']) for h in self.db.histories[hstart:]],
                         [(e['after_sale'],e['sale'],21) for e in entries])
        calls=self.db.calls[start:]
        self.assertIn('FOR UPDATE',calls[0][0])
        guard=next(i for i,(q,p) in enumerate(calls) if q==_LOCK_PRODUCTS_SQL)
        self.assertEqual(calls[guard][1],{'codes':[101,102,103,104]})
        preflight=[i for i,(q,p) in enumerate(calls) if q.startswith('SELECT sale_price, locked_fields')]
        firstwrite=next(i for i,(q,p) in enumerate(calls) if q.startswith('UPDATE '))
        self.assertEqual(len(preflight),4);self.assertLess(guard,min(preflight));self.assertLess(max(preflight),firstwrite)
        self.assertEqual((self.db.commits,self.db.rollbacks,self.db.actor_calls),(2,0,4))

    def test_post_apply_sale_or_unrelated_lock_changes_rejected_without_overwrite(self):
        for change in ({'sale_price':17000},{'locked_fields':['maker']}):
            self.setUp();result=self.apply();self.db.products[102].update(change)
            error,calls=self.reject_no_new_writes(result['log_id'])
            self.assertIn('다른 변경',error.detail)
            self.assertEqual(self.db.products[102].get(next(iter(change))),next(iter(change.values())))

    def test_last_product_drift_checks_whole_scope_before_any_restore(self):
        result=self.apply();entries=self.db.logs[-1]['detail']['before']
        self.db.products[entries[-1]['pc']]['sale_price']=17000
        error,calls=self.reject_no_new_writes(result['log_id'])
        self.assertEqual([p['pc'] for q,p in calls if q.startswith('SELECT sale_price, locked_fields')],
                         [e['pc'] for e in entries])
        self.assertEqual(self.db.products[entries[0]['pc']]['sale_price'],entries[0]['after_sale'])

    def test_drift_while_waiting_for_product_guard_preserves_external_change(self):
        self.seed([])
        self.db.after_lock=lambda d:d.products[101].update(sale_price=17000)
        start=len(self.db.calls)
        with self.assertRaises(HTTPException) as caught:self.undo()
        self.assertEqual(caught.exception.status_code,409)
        self.assertEqual(self.db.products[101]['sale_price'],17000)
        self.assertFalse(any(q.startswith(('UPDATE ','INSERT ')) for q,p in self.db.calls[start:]))

    def test_null_sale_restore_null_and_empty_locks_are_distinct_and_preserved(self):
        for locks in (None,[]):
            self.setUp();self.seed(locks);self.undo()
            self.assertIsNone(self.db.products[101]['sale_price'])
            self.assertEqual(self.db.products[101]['locked_fields'],locks)
            self.assertEqual(self.db.histories,[{'pc':101,'old':13000,'new':None,'op':21,'reason':'margin_policy_undo'}])
        for logged,current in ((None,[]),([],None)):
            self.setUp();self.seed(logged);self.db.products[101]['locked_fields']=current
            self.reject_no_new_writes()

    def test_lock_array_order_change_is_not_normalized_away(self):
        self.seed(['maker','status']);self.db.products[101]['locked_fields'].reverse()
        self.reject_no_new_writes()

    def test_legacy_missing_after_or_malformed_evidence_fail_closed(self):
        for field in ('pc','sale','after_sale','after_locked_fields'):
            self.setUp();self.seed([]);self.db.logs[0]['detail']['before'][0].pop(field)
            self.reject_no_new_writes()
        for field,value in (('pc',True),('pc',0),('sale',False),('after_sale','13000'),
                            ('after_locked_fields',False),('after_locked_fields',[1])):
            self.setUp();self.seed([]);self.db.logs[0]['detail']['before'][0][field]=value
            self.reject_no_new_writes()
        for detail in ('invalid json','[]',{'before':'bad'},{'before':[None]}):
            self.setUp();self.seed([]);self.db.logs[0]['detail']=detail
            self.reject_no_new_writes()

    def test_explicit_null_after_sale_and_json_log_are_valid(self):
        self.seed([]);self.db.products[101]['sale_price']=None
        entry=self.db.logs[0]['detail']['before'][0];entry.update(sale=13000,after_sale=None)
        self.db.logs[0]['detail']=json.dumps(self.db.logs[0]['detail'])
        self.undo();self.assertEqual(self.db.products[101]['sale_price'],13000)
        self.assertEqual(self.db.histories[0]['old'],None)

    def test_second_undo_duplicate_before_product_guard_and_no_extra_history(self):
        self.seed([]);self.undo();error,calls=self.reject_no_new_writes()
        self.assertEqual(error.detail,'이미 되돌린 기록입니다')
        self.assertFalse(any(q==_LOCK_PRODUCTS_SQL for q,p in calls))
        self.assertEqual(len(self.db.histories),1)

    def test_preflight_restore_history_and_log_exceptions_propagate_caller_rollback(self):
        for prefix in ('SELECT sale_price, locked_fields','SELECT sale_price FROM',
                       'UPDATE products','INSERT INTO product_price_history','LOG '):
            self.setUp();self.seed([]);before=self.db.state();error=RuntimeError('offline failure')
            self.db.fail=lambda q,p,prefix=prefix:error if q.startswith(prefix) else None
            with self.assertRaises(RuntimeError) as caught:self.undo()
            self.assertIs(caught.exception,error);self.assertEqual(self.db.state(),before)
            self.assertEqual((self.db.commits,self.db.rollbacks),(0,1))


if __name__ == '__main__':unittest.main()
