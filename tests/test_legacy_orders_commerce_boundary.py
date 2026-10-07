"""Actual legacy function calls with a caller-connection simulation; no DB/PG proof."""
import ast
import builtins
from copy import deepcopy
import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException


SOURCE = Path(__file__).resolve().parents[1] / 'api/admin_orders.py'
BASELINE_AST_SHA = '93dbb9688b31bd2e5c66163064888229046a0a81a31142899c5ff8efc1de29da'


class Result:
    def __init__(self, rows=(), scalar=None):
        self.rows, self.value = list(rows), scalar
    def mappings(self): return self
    def all(self): return self.rows
    def first(self): return self.rows[0] if self.rows else None
    def one(self):
        if len(self.rows) != 1: raise RuntimeError('fixture cardinality')
        return self.rows[0]
    def scalar(self): return self.value
    def __iter__(self): return iter(self.rows)


def row(oid, status='결제완료'):
    # Deliberately identical number/channel/mode for both memberships.
    return dict(order_id=oid, order_no=f'ORD-{oid}', status=status,
                channel='own', total_amount=100, ops_snapshot=dict.fromkeys(
                    ('pay', 'ship', 'settle', 'refund'), 'own'),
                shipping_snap={}, created_at='2026-10-05', cust='fixture')


class Connection:
    def __init__(self, schema=True, commerce=(), orders=()):
        self.schema = schema
        self.commerce = {oid: {'financial': 'paid'} for oid in commerce}
        self.orders = {o['order_id']: deepcopy(o) for o in orders}
        self.trace, self.writes, self.logs = [], [], []
        self.fail, self.membership_calls, self.fail_membership_at = None, 0, None
        self.refunds = set()
        self.log = dict(action='order_advance', detail=dict(order_id=2,
            action='ship', **{'from': '조립중', 'to': '배송중'},
            before=dict(shipment_id=42, shipment_updated=True)))
    def execute(self, sql, params=None):
        params = params or {}
        self.trace.append((sql, deepcopy(params)))
        if 'to_regclass' in sql:
            if self.fail == 'catalog': raise RuntimeError('catalog failure')
            return Result(scalar='commerce_order_details' if self.schema else None)
        if 'FROM public.commerce_order_details' in sql:
            self.membership_calls += 1
            if self.fail == 'membership' or self.membership_calls == self.fail_membership_at:
                raise RuntimeError('membership failure')
            return Result([(i,) for i in params['ids'] if i in self.commerce])
        if sql.startswith(('UPDATE ', 'INSERT ', 'DELETE ')):
            self.writes.append((sql, deepcopy(params)))
            if sql.startswith('UPDATE orders'): self.orders[params['o']]['status'] = params['s']
            if 'INSERT INTO shipments' in sql: return Result(scalar=42)
            if 'UPDATE shipments' in sql: return Result([dict(shipment_id=42, carrier='fixture', tracking_no='42')])
            return Result()
        if 'FROM orders' in sql:
            if 'order_no = ANY' in sql:
                return Result([o for _, o in sorted(self.orders.items()) if o['order_no'] in params['n']])
            if 'order_no=:n' in sql:
                return Result([o for o in self.orders.values() if o['order_no'] == params['n']])
            if 'order_id=:o' in sql: return Result([self.orders[params['o']]])
            return Result(list(self.orders.values()))
        if 'FROM admin_operator_activity_logs' in sql: return Result([self.log])
        if 'FROM refunds' in sql:
            if sql.startswith('SELECT 1'): return Result([(1,)] if params['o'] in self.refunds else [])
            return Result([(i,) for i in self.refunds] if sql.startswith('SELECT DISTINCT order_id') else [])
        if any(f'FROM {name}' in sql for name in ('order_items', 'payments', 'shipments', 'stock_reservations')):
            return Result()
        raise AssertionError(f'unexpected SQL: {sql}')


class Transaction:
    def __init__(self, conn): self.conn = conn
    def __enter__(self):
        self.before = deepcopy((self.conn.orders, self.conn.writes, self.conn.logs))
        return self.conn
    def __exit__(self, kind, value, tb):
        if kind:
            self.conn.orders, self.conn.writes, self.conn.logs = self.before
            self.conn.rollbacks += 1


class Engine:
    def __init__(self, conn): self.conn = conn; conn.rollbacks = 0
    def begin(self): return Transaction(self.conn)
    def connect(self): return Transaction(self.conn)


def functions(conn):
    """Compile the actual source functions, blocking production imports before execution."""
    module = ast.parse(SOURCE.read_text(encoding='utf-8-sig'))
    module.body = [n for n in module.body if isinstance(n, ast.FunctionDef)]
    for node in module.body:
        node.decorator_list = []  # Route registration is outside this function-call test.
    env = dict(HTTPException=HTTPException, text=lambda sql: sql, engine=Engine(conn),
        AdvanceBody=SimpleNamespace, BulkAdvanceBody=SimpleNamespace,
        TRANSITIONS={'assemble': ('결제완료', '조립중'), 'ship': ('조립중', '배송중'),
                     'done': ('배송중', '완료')},
        ACTIVE_REFUND=('접수', '검토', '수거·처리'), MAX_BULK_ORDER=200,
        STEP={'결제완료': 1, '조립중': 2, '배송중': 3, '완료': 4},
        LABELS={}, RF_BASE=1023, MODE_KO={'own': '자체', 'mall': '쇼핑몰'},
        current_operator_id=1, iso=lambda value: value,
        kst_day_range=lambda lo, hi: (None, None), range_sql=lambda *args: '')
    def log(c, action, target, detail, **kwargs):
        c.logs.append((action, target, deepcopy(detail))); return len(c.logs)
    env['_log_core'] = log
    real_import = builtins.__import__
    def no_production_import(name, *args, **kwargs):
        if name == 'api' or name.startswith('api.'):
            raise AssertionError('production import blocked: ' + name)
        return real_import(name, *args, **kwargs)
    with patch('builtins.__import__', side_effect=no_production_import):
        exec(compile(module, str(SOURCE), 'exec'), env)
    return SimpleNamespace(**env)


class BoundaryTests(unittest.TestCase):
    def assert_no_write(self, conn):
        self.assertEqual((conn.writes, conn.logs), ([], []))
    def test_absent_schema_legacy_transitions_still_work(self):
        for schema in (False, True):
            for action, status in [('assemble', '결제완료'), ('ship', '조립중'), ('done', '배송중')]:
                with self.subTest(schema=schema, action=action):
                    conn = Connection(schema=schema, orders=[row(2, status)])
                    result = functions(conn).advance('ORD-2', SimpleNamespace(action=action))
                    self.assertTrue(result['ok'])
                    self.assertTrue(conn.writes)
                    if not schema:
                        self.assertFalse(any('FROM public.commerce_order_details' in s for s, _ in conn.trace))
    def test_commerce_all_financial_states_and_actions_are_rejected_before_writes(self):
        for financial in ('paid', 'payment_unknown', 'refund_processing'):
            for action, status in [('assemble', '결제완료'), ('ship', '조립중'), ('done', '배송중')]:
                with self.subTest(financial=financial, action=action):
                    conn = Connection(commerce=[2], orders=[row(2, status)])
                    conn.commerce[2]['financial'] = financial
                    with self.assertRaises(HTTPException) as error:
                        functions(conn).advance('ORD-2', SimpleNamespace(action=action))
                    self.assertEqual(error.exception.status_code, 409)
                    self.assertEqual(error.exception.detail['error'], 'commerce_order_requires_new_workflow')
                    self.assert_no_write(conn)
                    self.assertIn('FOR UPDATE', conn.trace[0][0])
                    self.assertEqual(conn.trace[2][1], {'ids': [2]})
    def test_membership_beats_legacy_status_and_refund_inference(self):
        conn = Connection(commerce=[2], orders=[row(2, '접수')]); conn.refunds.add(2)
        with self.assertRaises(HTTPException) as error:
            functions(conn).advance('ORD-2', SimpleNamespace(action='ship'))
        self.assertEqual(error.exception.detail['error'], 'commerce_order_requires_new_workflow')
        self.assert_no_write(conn)
    def test_list_excludes_new_rows_before_legacy_derivation(self):
        conn = Connection(commerce=[2], orders=[row(1), dict(order_id=2)])
        result = functions(conn).list_orders()
        self.assertEqual([o['order_id'] for o in result['items']], [1])
        self.assert_no_write(conn)
    def test_absent_schema_list_is_unchanged(self):
        conn = Connection(schema=False, orders=[row(1), row(2)])
        self.assertEqual(len(functions(conn).list_orders()['items']), 2)
        self.assert_no_write(conn)
    def test_mixed_bulk_partial_success_order_and_explicit_skip(self):
        conn = Connection(commerce=[2], orders=[row(3, '배송중'), row(2), row(1)])
        result = functions(conn).bulk_advance(SimpleNamespace(order_nos=['ORD-3', 'missing', 'ORD-2', 'ORD-1', 'ORD-1'], action='assemble'))
        self.assertEqual((result['advanced'], result['skipped_total'], result['dropped']), (1, 3, 0))
        self.assertEqual([s['no'] for s in result['skipped']], ['missing', 'ORD-2', 'ORD-3'])
        self.assertIn('신규 주문 업무 화면', result['skipped'][1]['why'])
        self.assertEqual(conn.orders[1]['status'], '조립중')
        self.assertEqual(conn.orders[2]['status'], '결제완료')
        self.assertEqual(len(conn.logs), 1)
        self.assertIn('ORDER BY order_id FOR UPDATE', conn.trace[0][0])
    def test_bulk_cap_remains_200(self):
        conn = Connection(schema=False)
        result = functions(conn).bulk_advance(SimpleNamespace(order_nos=[f'ORD-{i}' for i in range(205)], action='assemble'))
        self.assertEqual((result['dropped'], result['skipped_total'], len(result['skipped'])), (5, 200, 20))
        self.assertEqual(len(conn.trace[0][1]['n']), 200)
        self.assert_no_write(conn)
    def test_undo_uses_locked_log_order_id_and_rejects_commerce_for_every_action(self):
        for action in ('assemble', 'ship', 'done'):
            with self.subTest(action=action):
                conn = Connection(commerce=[2], orders=[row(2, '접수')])
                conn.log['detail']['action'] = action
                with self.assertRaises(HTTPException) as error: functions(conn).undo(88)
                self.assertEqual(error.exception.detail['error'], 'commerce_order_requires_new_workflow')
                self.assertEqual(conn.trace[1][1], {'o': 2})
                self.assertIn('FOR UPDATE', conn.trace[1][0]); self.assert_no_write(conn)
    def test_absent_schema_undo_preserves_existing_writes(self):
        conn = Connection(schema=False, orders=[row(2, '배송중')])
        result = functions(conn).undo(88)
        self.assertEqual(result['status'], '조립중')
        self.assertTrue(conn.writes[0][0].startswith('DELETE FROM shipments'))
        self.assertEqual(conn.logs[0][0], 'order_advance_undo')
    def test_query_errors_propagate_and_transaction_rolls_back(self):
        for failure in ('catalog', 'membership'):
            for route in ('advance', 'bulk', 'undo', 'list'):
                with self.subTest(failure=failure, route=route):
                    conn = Connection(orders=[row(2, '배송중')]); conn.fail = failure
                    api = functions(conn)
                    with self.assertRaisesRegex(RuntimeError, 'failure'):
                        if route == 'advance': api.advance('ORD-2', SimpleNamespace(action='done'))
                        elif route == 'bulk': api.bulk_advance(SimpleNamespace(order_nos=['ORD-2'], action='done'))
                        elif route == 'undo': api.undo(88)
                        else: api.list_orders()
                    self.assert_no_write(conn); self.assertEqual(conn.rollbacks, 1)
    def test_later_bulk_query_failure_rolls_back_earlier_legacy_writes(self):
        conn = Connection(orders=[row(1), row(2)]); conn.fail_membership_at = 3
        with self.assertRaisesRegex(RuntimeError, 'membership failure'):
            functions(conn).bulk_advance(SimpleNamespace(order_nos=['ORD-1', 'ORD-2'], action='assemble'))
        self.assert_no_write(conn)
        self.assertEqual(conn.orders[1]['status'], '결제완료')
        self.assertEqual(conn.rollbacks, 1)
        self.assertTrue(any(s.startswith('UPDATE orders') for s, _ in conn.trace))
    def test_no_global_schema_cache(self):
        conn = Connection(schema=False, commerce=[2], orders=[row(2)])
        api = functions(conn); self.assertEqual(api._commerce_order_ids(conn, [2]), set())
        conn.schema = True; self.assertEqual(api._commerce_order_ids(conn, [2]), {2})
    def test_non_guard_ast_exactly_matches_baseline(self):
        tree = ast.parse(SOURCE.read_text(encoding='utf-8-sig'))
        class RemoveBoundary(ast.NodeTransformer):
            def visit_FunctionDef(self, node):
                if node.name in ('_commerce_order_ids', '_guard_legacy_order'): return None
                return self.generic_visit(node)
            def visit_Expr(self, node):
                if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == '_guard_legacy_order': return None
                return self.generic_visit(node)
            def visit_Assign(self, node):
                if any(isinstance(t, ast.Name) and t.id == 'commerce_ids' for t in node.targets): return None
                if isinstance(node.value, ast.ListComp) and any(isinstance(n, ast.Name) and n.id == 'commerce_ids' for n in ast.walk(node.value)): return None
                return self.generic_visit(node)
            def visit_If(self, node):
                if any(isinstance(n, ast.Name) and n.id == 'commerce_ids' for n in ast.walk(node.test)): return None
                return self.generic_visit(node)
        cleaned = RemoveBoundary().visit(tree)
        self.assertEqual(hashlib.sha256(ast.dump(cleaned, include_attributes=False).encode()).hexdigest(), BASELINE_AST_SHA)


if __name__ == '__main__': unittest.main()
