"""Actual source functions and frozen guards, caller mocks only; no native SQL proof."""
import ast
import builtins
from copy import deepcopy
from datetime import datetime
import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'api/admin_refunds.py'
BASELINE_AST_SHA = '23210951c1de20b074929a74f90cbbc8856889a64d4397afdc5245ee73d289dc'


class Result:
    def __init__(self, rows=(), scalar=None): self.rows, self.value = list(rows), scalar
    def mappings(self): return self
    def all(self): return self.rows
    def first(self): return self.rows[0] if self.rows else None
    def one(self):
        if len(self.rows) != 1: raise RuntimeError('expected one fixture row')
        return self.rows[0]
    def scalar(self): return self.value
    def __iter__(self): return iter(self.rows)


def refund(rid=1, oid=10, status='접수', day=1, mode='own', order_no='CO-looking-legacy'):
    return dict(refund_id=rid, order_id=oid, status=status, refund_mode=mode,
                reason_type='fixture', amount=12000, created_at=datetime(2026, 10, day),
                order_no=order_no, order_status='결제완료', cust='fixture')


class Connection:
    def __init__(self, rows=None, schema=True, commerce=()):
        self.rows = {r['refund_id']: deepcopy(r) for r in (rows if rows is not None else [refund()])}
        self.schema, self.commerce = schema, set(commerce)
        self.trace, self.writes, self.logs, self.fail, self.rollbacks = [], [], [], None, 0
        self.payment, self.stock, self.order_status = None, 3, '결제완료'
        self.items = [(900, 2)]
        self.other_active = False
        self.log = dict(action='refund_advance', detail=dict(refund_id=1, action='review',
                        **{'from': '접수', 'to': '검토', 'order_id': 999}))
    def execute(self, sql, params=None):
        params = params or {}; self.trace.append((sql, deepcopy(params)))
        if 'to_regclass' in sql:
            if self.fail == 'catalog': raise RuntimeError('catalog failure')
            return Result(scalar='commerce_order_details' if self.schema else None)
        if 'FROM public.commerce_order_details' in sql:
            if self.fail == 'membership': raise RuntimeError('membership failure')
            return Result([(oid,) for oid in params['ids'] if oid in self.commerce])
        if 'FROM admin_operator_activity_logs' in sql:
            return Result([deepcopy(self.log)] if self.log else [])
        if sql.startswith('SELECT 1 FROM refunds'): return Result([(1,)] if self.other_active else [])
        if 'FROM refunds r JOIN orders' in sql: return Result(deepcopy(list(self.rows.values())))
        if 'FROM refunds' in sql:
            return Result([deepcopy(self.rows[params['i']])] if params['i'] in self.rows else [])
        if 'FROM orders WHERE' in sql:
            return Result([dict(order_id=params['o'], order_no='fixture', status=self.order_status)])
        if 'FROM payments' in sql: return Result([deepcopy(self.payment)] if self.payment else [])
        if 'FROM order_items' in sql: return Result(self.items)
        if sql.startswith(('INSERT ', 'UPDATE ')):
            if self.fail == 'write': raise RuntimeError('write failure')
            self.writes.append((sql, deepcopy(params)))
            if sql.startswith('UPDATE refunds'): self.rows[params['i']]['status'] = params['s']
            if sql.startswith('UPDATE products'): self.stock += params['q']
            if sql.startswith('UPDATE orders'): self.order_status = '취소'
            return Result()
        raise AssertionError('unexpected SQL: ' + sql)


class Transaction:
    def __init__(self, conn): self.conn = conn
    def __enter__(self):
        self.before = deepcopy((self.conn.rows, self.conn.stock, self.conn.order_status,
                                self.conn.writes, self.conn.logs))
        return self.conn
    def __exit__(self, kind, value, tb):
        if kind:
            (self.conn.rows, self.conn.stock, self.conn.order_status,
             self.conn.writes, self.conn.logs) = self.before
            self.conn.rollbacks += 1


def functions(conn):
    tree = ast.parse(SOURCE.read_text(encoding='utf-8-sig'))
    tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef) or
                 isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and
                 t.id in ('STATE_IDX', 'TRANSITIONS', 'CANCELABLE') for t in n.targets)]
    guard_source = ROOT / 'api/admin_orders.py'
    guard_tree = ast.parse(guard_source.read_text(encoding='utf-8-sig'))
    tree.body += [n for n in guard_tree.body if isinstance(n, ast.FunctionDef) and n.name in
                  ('_commerce_order_ids', '_guard_legacy_order', 'refund_label') or
                  isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and
                  t.id in ('ACTIVE_REFUND', 'RF_BASE') for t in n.targets)]
    for n in tree.body:
        if isinstance(n, ast.FunctionDef): n.decorator_list = []
    def log(c, action, target, detail, **kwargs):
        c.logs.append((action, target, deepcopy(detail), kwargs)); return 81
    env = dict(HTTPException=HTTPException, AdvanceBody=SimpleNamespace,
               text=lambda sql: sql, _log=log,
               iso=lambda value: value.isoformat(),
               engine=SimpleNamespace(connect=lambda: Transaction(conn), begin=lambda: Transaction(conn)))
    real_import = builtins.__import__
    def blocked(name, *args, **kwargs):
        if name == 'main' or name == 'api' or name.startswith('api.'):
            raise AssertionError('production import blocked: ' + name)
        return real_import(name, *args, **kwargs)
    with patch('builtins.__import__', side_effect=blocked):
        exec(compile(tree, str(SOURCE), 'exec'), env)
    return SimpleNamespace(**env)


class RefundBoundaryTests(unittest.TestCase):
    def no_write(self, c): self.assertEqual((c.writes, c.logs), ([], []))
    def assert_block(self, c, call):
        with self.assertRaises(HTTPException) as caught: call(functions(c))
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(caught.exception.detail['error'], 'commerce_order_requires_new_workflow')
        self.no_write(c)
        self.assertEqual(c.rollbacks, 1)
        membership = next(p for s, p in c.trace if 'FROM public.commerce_order_details' in s)
        self.assertEqual(membership, {'ids': [10]})
    def test_list_mixed_fk_only_public_shape_and_active_latest_sort(self):
        c = Connection(rows=[refund(1, 10, '완료', 5), refund(2, 20, day=6, order_no='ORD-normal'),
                             refund(3, 10, '검토', 2), refund(4, 30, '접수', 4)], commerce=[20])
        result = functions(c).list_refunds()
        self.assertEqual([r['refund_id'] for r in result['items']], [4, 3, 1])
        self.assertEqual(result['items'][1]['no'], 'RF-1026')
        self.assertEqual(set(result['items'][0]), {'refund_id', 'no', 'order', 'cust', 'kind',
            'reason', 'mode', 'state', 'status', 'amount', 'at', 'note', 'order_status'})
        self.assertTrue(any('r.order_id' in s for s, _ in c.trace))
        self.no_write(c)
    def test_list_all_commerce_empty_and_empty_input_skips_schema_lookup(self):
        c = Connection(commerce=[10]); self.assertEqual(functions(c).list_refunds(), {'items': []})
        self.no_write(c)
        c = Connection(rows=[]); self.assertEqual(functions(c).list_refunds(), {'items': []})
        self.assertFalse(any('to_regclass' in s for s, _ in c.trace))
    def test_list_schema_absent_preserves_all_rows(self):
        c = Connection(schema=False, commerce=[10])
        self.assertEqual([r['refund_id'] for r in functions(c).list_refunds()['items']], [1])
        self.assertFalse(any('FROM public.commerce_order_details' in s for s, _ in c.trace))
        self.no_write(c)
    def test_every_advance_action_commerce_409_before_any_mutation(self):
        for action, status in (('review', '접수'), ('approve', '검토'),
                               ('complete', '수거·처리'), ('reject', '접수'), ('reject', '검토')):
            with self.subTest(action=action, status=status):
                c = Connection(rows=[refund(status=status)], commerce=[10])
                self.assert_block(c, lambda f: f.advance(1, SimpleNamespace(action=action)))
                self.assertEqual((c.stock, c.rows[1]['status']), (3, status))
                self.assertFalse(any('FROM orders WHERE' in s or 'FROM payments' in s or
                                     'FROM order_items' in s for s, _ in c.trace))
    def test_complete_with_or_without_approved_payment_cannot_restore_stock(self):
        for payment in (None, dict(pay_mode='own', method='카드', pg_ref='fixture')):
            with self.subTest(payment=payment):
                c = Connection(rows=[refund(status='수거·처리')], commerce=[10]); c.payment = payment
                self.assert_block(c, lambda f: f.advance(1, SimpleNamespace(action='complete')))
                self.assertEqual((c.stock, c.order_status), (3, '결제완료'))
                self.assertFalse(any('payments' in s or 'order_items' in s for s, _ in c.trace))
    def test_undo_review_approve_reject_block_from_actual_refund_fk(self):
        for action, before, after in (('review', '접수', '검토'),
                                      ('approve', '검토', '수거·처리'), ('reject', '접수', '반려')):
            with self.subTest(action=action):
                c = Connection(rows=[refund(status=after)], commerce=[10])
                c.log['detail'].update(action=action, **{'from': before, 'to': after, 'order_id': 999})
                self.assert_block(c, lambda f: f.undo(81))
                self.assertEqual(c.rows[1]['status'], after)
    def test_legacy_advance_actions_keep_response_and_log(self):
        for schema in (True, False):
            for action, before, after, state in (('review', '접수', '검토', 1),
                                                ('approve', '검토', '수거·처리', 2),
                                                ('reject', '검토', '반려', -1)):
                with self.subTest(schema=schema, action=action):
                    c = Connection(rows=[refund(status=before)], schema=schema,
                                   commerce=[10] if not schema else [])
                    result = functions(c).advance(1, SimpleNamespace(action=action))
                    self.assertEqual(result, dict(status=after, state=state, undo_id=81,
                                                  returned=0, refund_row=None))
                    self.assertEqual(c.rows[1]['status'], after)
                    self.assertEqual(c.logs, [('refund_advance', 'RF-1024',
                        dict(refund_id=1, action=action, **{'from': before, 'to': after}), {'kind': 'refund'})])
                    self.assertEqual(len(c.writes), 1)
    def test_legacy_complete_payment_rail_stock_cancel_and_irreversible_response(self):
        for schema in (True, False):
            for mode in ('own', 'mall', None):
                with self.subTest(schema=schema, mode=mode):
                    c = Connection(rows=[refund(status='수거·처리', mode='mall')], schema=schema)
                    c.payment = dict(pay_mode=mode, method='카드', pg_ref='fixture') if mode else None
                    result = functions(c).advance(1, SimpleNamespace(action='complete'))
                    expected = dict(method='카드', pg_ref='fixture-R' if mode == 'own' else None,
                                    amount=-12000) if mode else None
                    self.assertEqual(result, dict(status='완료', state=3, undo_id=None,
                                                  returned=1, refund_row=expected))
                    self.assertEqual((c.stock, c.order_status, c.rows[1]['status']), (5, '취소', '완료'))
                    payments = [p for s, p in c.writes if s.startswith('INSERT INTO payments')]
                    self.assertEqual(payments, [dict(o=10, m=mode, me='카드', ref=expected['pg_ref'], a=-12000)] if mode else [])
                    self.assertEqual(c.logs[0][0], 'refund_advance')
    def test_legacy_complete_finished_order_keeps_status_and_no_cancel_event(self):
        c = Connection(rows=[refund(status='수거·처리')]); c.order_status = '완료'
        functions(c).advance(1, SimpleNamespace(action='complete'))
        self.assertEqual(c.order_status, '완료')
        self.assertFalse(any('UPDATE orders' in s or 'order_events' in s for s, _ in c.writes))
    def test_legacy_undo_preserves_response_log_and_uses_row_not_log_order(self):
        for schema in (True, False):
            for action, before, after in (('review', '접수', '검토'),
                                          ('approve', '검토', '수거·처리'), ('reject', '검토', '반려')):
                with self.subTest(schema=schema, action=action):
                    c = Connection(rows=[refund(status=after)], schema=schema, commerce=[999])
                    c.log['detail'].update(action=action, **{'from': before, 'to': after})
                    self.assertEqual(functions(c).undo(81), dict(status=before,
                                     state={'접수': 0, '검토': 1}[before]))
                    self.assertEqual(c.logs, [('refund_advance_undo', '81',
                        dict(ref_log_id=81, refund_id=1), {'kind': 'refund'})])
                    self.assertEqual(len(c.writes), 1)
    def test_original_advance_validation_404_and_invalid_transition_precedence(self):
        for rows, action, status, detail in (([], 'unknown', 400, '알 수 없는 액션: unknown'),
                                           ([], 'review', 404, '환불 건이 없습니다'),
                                           ([refund(status='완료')], 'review', 409, 'invalid_transition')):
            with self.subTest(action=action, rows=rows):
                c = Connection(rows=rows, commerce=[10]); c.fail = 'catalog'
                with self.assertRaises(HTTPException) as caught:
                    functions(c).advance(1, SimpleNamespace(action=action))
                self.assertEqual(caught.exception.status_code, status)
                self.assertEqual(caught.exception.detail.get('error') if isinstance(caught.exception.detail, dict)
                                 else caught.exception.detail, detail)
                self.no_write(c); self.assertFalse(any('to_regclass' in s for s, _ in c.trace))
    def test_original_undo_missing_wrong_log_complete_changed_active_precedence(self):
        for case, status in (('missing', 404), ('wrong', 404), ('complete', 409),
                             ('changed', 409), ('active', 409)):
            with self.subTest(case=case):
                c = Connection(rows=[refund(status='검토')], commerce=[10]); c.fail = 'catalog'
                if case == 'missing': c.log = None
                elif case == 'wrong': c.log['action'] = 'other'
                elif case == 'complete': c.log['detail']['action'] = 'complete'
                elif case == 'changed': c.rows[1]['status'] = '완료'
                else:
                    c.rows[1]['status'] = '반려'; c.other_active = True
                    c.log['detail'].update(action='reject', to='반려')
                with self.assertRaises(HTTPException) as caught: functions(c).undo(81)
                self.assertEqual(caught.exception.status_code, status)
                if case == 'active': self.assertEqual(caught.exception.detail['error'], 'refund_active')
                self.no_write(c); self.assertFalse(any('to_regclass' in s for s, _ in c.trace))
    def test_catalog_membership_errors_propagate_on_list_advance_and_undo(self):
        for failure in ('catalog', 'membership'):
            for route in ('list', 'advance', 'undo'):
                with self.subTest(failure=failure, route=route):
                    c = Connection(rows=[refund(status='검토' if route == 'undo' else '접수')])
                    c.fail = failure; f = functions(c)
                    with self.assertRaisesRegex(RuntimeError, failure + ' failure'):
                        if route == 'list': f.list_refunds()
                        elif route == 'advance': f.advance(1, SimpleNamespace(action='review'))
                        else: f.undo(81)
                    self.no_write(c)
    def test_mock_transaction_rolls_back_legacy_complete_if_first_write_fails(self):
        c = Connection(rows=[refund(status='수거·처리')]); c.fail = 'write'
        with self.assertRaisesRegex(RuntimeError, 'write failure'):
            functions(c).advance(1, SimpleNamespace(action='complete'))
        self.assertEqual((c.stock, c.rows[1]['status'], c.rollbacks), (3, '수거·처리', 1))
        self.no_write(c)
    def test_only_boundary_additions_original_ast_preserved(self):
        tree = ast.parse(SOURCE.read_text(encoding='utf-8-sig'))
        imp = next(n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == 'admin_orders')
        self.assertEqual([n.name for n in imp.names[-2:]], ['_commerce_order_ids', '_guard_legacy_order'])
        imp.names = imp.names[:-2]
        functions_by_name = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        tx = next(n for n in functions_by_name['list_refunds'].body if isinstance(n, ast.With))
        self.assertEqual([n.targets[0].id for n in tx.body[1:]], ['commerce_ids', 'rows'])
        self.assertIn('_commerce_order_ids', ast.dump(tx.body[1]))
        self.assertIn('commerce_ids', ast.dump(tx.body[2]))
        tx.body = tx.body[:1]
        sql = next(n for n in ast.walk(tx) if isinstance(n, ast.Constant) and
                   isinstance(n.value, str) and n.value.startswith('SELECT r.refund_id'))
        self.assertEqual(sql.value.count('r.order_id, '), 1)
        sql.value = sql.value.replace('r.order_id, ', '', 1)
        for name in ('advance', 'undo'):
            tx = next(n for n in functions_by_name[name].body if isinstance(n, ast.With))
            guards = [n for n in tx.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                      and isinstance(n.value.func, ast.Name) and n.value.func.id == '_guard_legacy_order']
            self.assertEqual(len(guards), 1)
            self.assertEqual(ast.unparse(guards[0]), "_guard_legacy_order(conn, r['order_id'])")
            tx.body.remove(guards[0])
        digest = hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()
        self.assertEqual(digest, BASELINE_AST_SHA)


if __name__ == '__main__': unittest.main()
