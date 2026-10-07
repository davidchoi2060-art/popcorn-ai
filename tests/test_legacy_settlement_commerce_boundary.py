"""Actual source-function tests with caller-connection mocks; no PostgreSQL/PG proof."""
import ast
import builtins
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'api/admin_payments.py'
BASELINE_AST_SHA = '96ef1a2222292a0061eb943ee0ff69005f8c352cfccea95c0556c9cfb5d1a4fc'
DAY = date(2026, 10, 4)


class Result:
    def __init__(self, rows=(), scalar=None): self.rows, self.value = list(rows), scalar
    def mappings(self): return self
    def all(self): return self.rows
    def first(self): return self.rows[0] if self.rows else None
    def scalar(self): return self.value
    def scalar_one(self): return self.value
    def __iter__(self): return iter(self.rows)


def pay(pid, oid, amount=10000, status='승인', day=DAY, mode='own'):
    return dict(payment_id=pid, order_id=oid, order_no=f'ORD-{oid}', pay_mode=mode,
                amount=amount, status=status, method='카드', pg_ref=f'fixture-{pid}',
                paid_at=datetime(day.year, day.month, day.day, 23, 30, tzinfo=timezone.utc))


def batch(bid, day=DAY, gross=8500, fee=220):
    return dict(batch_id=bid, settle_date=day, gross=gross, fee=fee, net=gross-fee,
                status='마감', closed_at=datetime(2026, 10, 5, tzinfo=timezone.utc))


class Connection:
    def __init__(self, schema=True, commerce=(), payments=(), batches=(), settlements=()):
        self.schema, self.commerce = schema, set(commerce)
        self.payments = {p['payment_id']: deepcopy(p) for p in payments}
        self.batches = {b['batch_id']: deepcopy(b) for b in batches}
        self.settlements = [deepcopy(s) for s in settlements]
        self.rate, self.trace, self.writes, self.logs = Decimal('0.02585'), [], [], []
        self.fail, self.duplicate = None, False
        self.log = dict(action='settlement_close', detail=dict(batch_id=9, settle_date=DAY.isoformat(),
                        gross=8500, fee=220, net=8280, payment_ids=[1, 2]))
    def execute(self, sql, params=None):
        params = params or {}; self.trace.append((sql, deepcopy(params)))
        if 'to_regclass' in sql:
            if self.fail == 'catalog': raise RuntimeError('catalog failure')
            return Result(scalar='commerce_order_details' if self.schema else None)
        if 'FROM public.commerce_order_details' in sql:
            if self.fail == 'membership': raise RuntimeError('membership failure')
            return Result([(oid,) for oid in params['ids'] if oid in self.commerce])
        if 'SELECT s.batch_id, p.order_id' in sql:
            if self.fail == 'batch_membership': raise RuntimeError('batch_membership failure')
            return Result([dict(batch_id=s['batch_id'], order_id=self.payments[s['payment_id']]['order_id'])
                           for s in self.settlements if s['batch_id'] in params['ids']])
        if 'FROM pricing_settings' in sql: return Result(scalar=self.rate)
        if sql == 'SELECT CURRENT_DATE': return Result(scalar=date(2026, 10, 5))
        if sql.startswith('SELECT 1 FROM admin_operator_activity_logs'):
            return Result([(1,)] if self.duplicate else [])
        if 'FROM admin_operator_activity_logs' in sql: return Result([self.log])
        if sql.startswith('SELECT ') and 'FROM settlement_batches' in sql:
            if 'FOR UPDATE' in sql: return Result([self.batches[params['b']]] if params['b'] in self.batches else [])
            return Result(sorted(self.batches.values(), key=lambda b: b['settle_date'], reverse=True))
        if 'FROM payments p' in sql:
            pays = list(self.payments.values())
            if 'JOIN orders' in sql:
                return Result(sorted(pays, key=lambda p: (p['paid_at'], p['payment_id']), reverse=True))
            targets = [p for p in pays if p['pay_mode'] == 'own' and p['status'] in ('승인', '환불')]
            if 'FOR UPDATE' in sql:
                return Result(sorted([p for p in targets if p['paid_at'].date().isoformat() == params['d']], key=lambda p: p['payment_id']))
            settled = {s['payment_id'] for s in self.settlements}
            return Result([p | dict(d=p['paid_at'].date(), settled=p['payment_id'] in settled) for p in targets])
        if sql.startswith(('INSERT ', 'DELETE ')):
            if self.fail == 'settlement_insert' and sql.startswith('INSERT INTO settlements '):
                raise RuntimeError('settlement_insert failure')
            self.writes.append((sql, deepcopy(params)))
            if sql.startswith('INSERT INTO settlement_batches'):
                if any(b['settle_date'].isoformat() == params['d'] for b in self.batches.values()): return Result()
                bid = max(self.batches, default=0) + 1
                self.batches[bid] = batch(bid, date.fromisoformat(params['d']), params['g'], params['f'])
                return Result([self.batches[bid]])
            if sql.startswith('INSERT INTO settlements '):
                self.settlements.append(dict(payment_id=params['p'], batch_id=params['b'],
                                            fee_amount=params['f'], net_amount=params['n'], settle_mode=params['m']))
            elif sql.startswith('DELETE FROM settlements '):
                self.settlements = [s for s in self.settlements if s['batch_id'] != params['b']]
            elif sql.startswith('DELETE FROM settlement_batches '): del self.batches[params['b']]
            return Result()
        raise AssertionError('unexpected SQL: ' + sql)


class Transaction:
    def __init__(self, conn): self.conn = conn
    def __enter__(self):
        self.before = deepcopy((self.conn.batches, self.conn.settlements, self.conn.writes, self.conn.logs))
        return self.conn
    def __exit__(self, kind, value, tb):
        if kind:
            self.conn.batches, self.conn.settlements, self.conn.writes, self.conn.logs = self.before
            self.conn.rollbacks += 1


class Engine:
    def __init__(self, conn): self.conn = conn; conn.rollbacks = 0
    def begin(self): return Transaction(self.conn)
    def connect(self): return Transaction(self.conn)


def functions(conn):
    tree = ast.parse(SOURCE.read_text(encoding='utf-8-sig'))
    tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    orders = ast.parse((ROOT / 'api/admin_orders.py').read_text(encoding='utf-8-sig'))
    tree.body += [n for n in orders.body if isinstance(n, ast.FunctionDef) and n.name == '_commerce_order_ids']
    for node in tree.body: node.decorator_list = []
    env = dict(Decimal=Decimal, HTTPException=HTTPException, text=lambda sql: sql,
        engine=Engine(conn), TARGET="p.pay_mode='own' AND p.status IN ('승인','환불')",
        current_operator_id=lambda: 1, iso=lambda v: v.isoformat() if hasattr(v, 'isoformat') else v,
        kst_day_range=lambda lo, hi: (None, None), range_sql=lambda *args: '')
    def log(c, action, target, detail, **kwargs):
        c.logs.append((action, target, deepcopy(detail), kwargs)); return len(c.logs)
    env['_log'] = log
    real_import = builtins.__import__
    def blocked_import(name, *args, **kwargs):
        if name == 'api' or name.startswith('api.'): raise AssertionError('production import blocked: ' + name)
        return real_import(name, *args, **kwargs)
    with patch('builtins.__import__', side_effect=blocked_import):
        exec(compile(tree, str(SOURCE), 'exec'), env)
    return SimpleNamespace(**env)


class SettlementBoundaryTests(unittest.TestCase):
    def assert_no_write(self, conn): self.assertEqual((conn.writes, conn.logs), ([], []))
    def mixed(self, schema=True):
        return Connection(schema=schema, commerce=[20], payments=[pay(4, 20, -9000, '환불'),
            pay(2, 10, -1500, '환불'), pay(3, 20, 50000), pay(1, 10)])
    def test_mixed_day_close_only_legacy_positive_and_refund_with_exact_decimal_fees(self):
        conn = self.mixed(); result = functions(conn).close_settlement(DAY.isoformat())
        self.assertEqual({k: result['batch'][k] for k in ('gross', 'fee', 'net', 'n')},
                         dict(gross=8500, fee=220, net=8280, n=2))
        self.assertEqual([s['payment_id'] for s in conn.settlements], [1, 2])
        self.assertEqual([s['fee_amount'] for s in conn.settlements], [259, -39])
        self.assertEqual(conn.logs[0][2]['payment_ids'], [1, 2])
        lock = next(i for i, (s, _) in enumerate(conn.trace) if 'FOR UPDATE' in s)
        member = next(i for i, (s, _) in enumerate(conn.trace) if 'to_regclass' in s)
        self.assertLess(lock, member)
        self.assertIn('ORDER BY p.payment_id FOR UPDATE', conn.trace[lock][0])
    def test_all_new_close_existing_empty_400_before_first_write(self):
        conn = Connection(commerce=[20], payments=[pay(1, 20), pay(2, 20, -1500, '환불')])
        with self.assertRaises(HTTPException) as error: functions(conn).close_settlement(DAY.isoformat())
        self.assertEqual(error.exception.status_code, 400); self.assert_no_write(conn)
    def test_absent_schema_close_keeps_all_existing_legacy_targets(self):
        conn = self.mixed(schema=False); result = functions(conn).close_settlement(DAY.isoformat())
        self.assertEqual(result['batch']['n'], 4)
        self.assertEqual(conn.logs[0][2]['payment_ids'], [1, 2, 3, 4])
        self.assertFalse(any('FROM public.commerce_order_details' in s for s, _ in conn.trace))
    def test_list_filters_new_rows_and_keeps_public_allowlist_utc_day_and_order(self):
        conn = self.mixed(); result = functions(conn).list_payments()
        self.assertEqual([p['amount'] for p in result['payments']], [-1500, 10000])
        self.assertEqual(set(result['payments'][0]), {'order_no', 'mode', 'method', 'pg_ref', 'amount', 'status', 'at'})
        self.assertEqual(result['settles'][0], dict(date=DAY.isoformat(), state='대기', gross=8500,
                        fee=220, net=8280, n=2, refund_n=1, closed_at=None, late=None))
        self.assertEqual(set(result), {'fee_rate', 'today', 'payments', 'settles'})
        self.assertIn('date(p.paid_at) AS d', next(s for s, _ in conn.trace if 'LEFT JOIN settlements' in s))
        self.assertEqual(result['today'], '2026-10-05'); self.assert_no_write(conn)
    def test_mixed_existing_batch_is_hidden_without_inventing_pending_split(self):
        conn = self.mixed(); conn.batches[9] = batch(9)
        conn.settlements = [dict(batch_id=9, payment_id=1), dict(batch_id=9, payment_id=3)]
        result = functions(conn).list_payments()
        self.assertEqual(result['settles'], [])
        self.assertEqual(len(result['payments']), 2); self.assert_no_write(conn)
    def test_membership_reads_real_batch_even_non_target_new_payment_not_log(self):
        conn = Connection(commerce=[20], payments=[pay(1, 10), pay(2, 10, -1500, '환불'),
            pay(8, 20, 0, '취소', mode='mall')], batches=[batch(9)],
            settlements=[dict(batch_id=9, payment_id=8)])
        with self.assertRaises(HTTPException) as error: functions(conn).undo_settlement(5)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(error.exception.detail['error'], 'commerce_settlement_requires_new_workflow')
        self.assertEqual(conn.log['detail']['payment_ids'], [1, 2])
        self.assert_no_write(conn)
        self.assertIn('FROM settlements s JOIN payments', next(s for s, _ in conn.trace if 'SELECT s.batch_id' in s))
    def test_legacy_batch_saved_fee_and_late_calculation_are_preserved(self):
        conn = self.mixed(); conn.batches[9] = batch(9, gross=10000, fee=300)
        conn.settlements = [dict(batch_id=9, payment_id=1)]
        result = functions(conn).list_payments()['settles'][0]
        self.assertEqual((result['gross'], result['fee'], result['net'], result['n']), (10000, 300, 9700, 1))
        self.assertEqual(result['late'], dict(n=1, gross=-1500))
    def test_list_multiple_days_sorted_and_only_whole_commerce_batch_excluded(self):
        conn = Connection(commerce=[20], payments=[pay(1, 10), pay(2, 20),
            pay(3, 10, day=date(2026, 10, 3)), pay(4, 10, day=date(2026, 10, 5))],
            batches=[batch(9), batch(10, date(2026, 10, 3), 10000, 259)],
            settlements=[dict(batch_id=9, payment_id=2), dict(batch_id=10, payment_id=3)])
        result = functions(conn).list_payments()['settles']
        self.assertEqual([s['date'] for s in result], ['2026-10-05', '2026-10-03'])
    def test_absent_schema_list_and_undo_preserve_legacy_batch(self):
        conn = self.mixed(schema=False); conn.batches[9] = batch(9)
        conn.settlements = [dict(batch_id=9, payment_id=i) for i in (1, 2, 3, 4)]
        api = functions(conn)
        self.assertEqual(len(api.list_payments()['payments']), 4)
        self.assertEqual(len(api.list_payments()['settles']), 1)
        self.assertTrue(api.undo_settlement(5)['ok'])
        self.assertEqual([s.split()[0] for s, _ in conn.writes], ['DELETE', 'DELETE'])
    def test_legacy_undo_even_forged_log_new_ids_uses_actual_settlements(self):
        conn = self.mixed(); conn.batches[9] = batch(9)
        conn.settlements = [dict(batch_id=9, payment_id=1), dict(batch_id=9, payment_id=2)]
        conn.log['detail']['payment_ids'] = [3, 4]
        self.assertTrue(functions(conn).undo_settlement(5)['ok'])
        self.assertEqual(conn.batches, {}); self.assertEqual(conn.settlements, [])
    def test_duplicate_and_modified_batch_guards_precede_membership(self):
        for duplicate in (True, False):
            conn = self.mixed(); conn.batches[9] = batch(9); conn.duplicate = duplicate
            if not duplicate: conn.batches[9]['net'] += 1
            with self.assertRaises(HTTPException): functions(conn).undo_settlement(5)
            self.assertFalse(any('SELECT s.batch_id' in s for s, _ in conn.trace)); self.assert_no_write(conn)
    def test_already_closed_preserves_409_and_rolls_back_attempt(self):
        conn = self.mixed(); conn.batches[9] = batch(9)
        with self.assertRaises(HTTPException) as error: functions(conn).close_settlement(DAY.isoformat())
        self.assertEqual(error.exception.detail['error'], 'already_closed')
        self.assert_no_write(conn); self.assertEqual(conn.rollbacks, 1)
    def test_query_errors_propagate_and_undo_has_no_deletes(self):
        for route in ('list', 'close', 'undo'):
            for failure in ('catalog', 'membership', 'batch_membership'):
                if route == 'close' and failure == 'batch_membership': continue
                with self.subTest(route=route, failure=failure):
                    conn = self.mixed(); conn.batches[9] = batch(9)
                    conn.settlements = [dict(batch_id=9, payment_id=1)]; conn.fail = failure
                    api = functions(conn)
                    with self.assertRaisesRegex(RuntimeError, 'failure'):
                        if route == 'list': api.list_payments()
                        elif route == 'close': api.close_settlement(DAY.isoformat())
                        else: api.undo_settlement(5)
                    self.assert_no_write(conn); self.assertEqual(conn.rollbacks, 1)
    def test_later_settlement_write_failure_rolls_back_batch_simulation(self):
        conn = self.mixed(); conn.fail = 'settlement_insert'
        with self.assertRaisesRegex(RuntimeError, 'settlement_insert failure'):
            functions(conn).close_settlement(DAY.isoformat())
        self.assertEqual((conn.batches, conn.settlements), ({}, [])); self.assert_no_write(conn)
        self.assertTrue(any(s.startswith('INSERT INTO settlement_batches') for s, _ in conn.trace))
    def test_decimal_halfup_sign_and_schema_presence_is_not_cached(self):
        conn = self.mixed(schema=False); api = functions(conn)
        self.assertEqual(api._fee_won(100, Decimal('0.025')), 3)
        self.assertEqual(api._fee_won(-100, Decimal('0.025')), -3)
        self.assertEqual(len(api.list_payments()['payments']), 4)
        conn.schema = True; self.assertEqual(len(api.list_payments()['payments']), 2)
    def test_non_boundary_ast_preserves_original_legacy_rules(self):
        tree = ast.parse(SOURCE.read_text(encoding='utf-8-sig'))
        class RemoveBoundary(ast.NodeTransformer):
            def visit_ImportFrom(self, node):
                if node.module == 'admin_orders': node.names = [a for a in node.names if a.name != '_commerce_order_ids']
                return node
            def visit_FunctionDef(self, node):
                if node.name == '_commerce_batch_ids': return None
                return self.generic_visit(node)
            def visit_Assign(self, node):
                if any(isinstance(t, ast.Name) and t.id in ('commerce_ids', 'commerce_batch_ids') for t in node.targets): return None
                if isinstance(node.value, ast.ListComp) and any(isinstance(n, ast.Name) and n.id == 'commerce_ids' for n in ast.walk(node.value)): return None
                return self.generic_visit(node)
            def visit_If(self, node):
                if any(isinstance(n, ast.Name) and n.id in ('commerce_batch_ids', '_commerce_batch_ids') for n in ast.walk(node.test)): return None
                return self.generic_visit(node)
            def visit_Constant(self, node):
                if isinstance(node.value, str):
                    node.value = node.value.replace('SELECT p.payment_id, p.order_id, ', 'SELECT p.payment_id, ')
                return node
        cleaned = RemoveBoundary().visit(tree)
        self.assertEqual(hashlib.sha256(ast.dump(cleaned, include_attributes=False).encode()).hexdigest(), BASELINE_AST_SHA)


if __name__ == '__main__': unittest.main()
