"""Selected route AST only; native-shaped mocks do not prove PG concurrency."""
import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from sqlalchemy import text
from api.pricing_write_guard_core import lock_products, ProductScopeChanged, _LOCK_PRODUCTS_SQL


def routes():
    source = Path(__file__).resolve().parents[1] / 'api/admin_products.py'
    nodes = []
    for node in ast.parse(source.read_text(encoding='utf-8')).body:
        if isinstance(node, ast.FunctionDef) and node.name in ('upsert_supplier_price', 'delete_supplier_price'):
            node.decorator_list = []
            node.body = [n for n in node.body if not isinstance(n, ast.ImportFrom)]
            nodes.append(node)
    env = dict(text=text, HTTPException=HTTPException, SupplierPriceBody=object,
               SUPPLY_STATES=('가능', '품절'), lock_products=lock_products,
               ProductScopeChanged=ProductScopeChanged)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), env)
    return env


class Result:
    def __init__(self, rows): self.rows = deepcopy(rows)
    def mappings(self): return self
    def scalars(self): return self
    def all(self): return deepcopy(self.rows)
    def first(self): return deepcopy(self.rows[0]) if self.rows else None
    def scalar(self): return self.first()
    def scalar_one(self):
        if len(self.rows) != 1: raise AssertionError('one expected')
        return self.first()


class Database:
    def __init__(self):
        self.product = True
        self.supplier = '공급처'
        self.psp = {'psp_id': 301, 'cost_price': 12000, 'state': '품절'}
        self.logs = []
        self.calls = []
        self.after_lock = None
        self.fail = None
        self.commits = self.rollbacks = 0
    def begin(self): return Transaction(self)
    def log(self, conn, action, target, detail, **kwargs):
        conn.wrote = True
        self.logs.append((action, target, deepcopy(detail), kwargs))
        if self.fail: raise self.fail
        return len(self.logs)


class Transaction:
    def __init__(self, db): self.db = db
    def __enter__(self):
        self.conn = Connection(self.db)
        return self.conn
    def __exit__(self, typ, value, trace):
        if typ:
            self.db.rollbacks += 1
            if self.conn.wrote:
                self.db.psp, self.db.logs = deepcopy(self.conn.snapshot)
        else: self.db.commits += 1
        return False


class Connection:
    def __init__(self, db):
        self.db = db
        self.wrote = False
        self.snapshot = deepcopy((db.psp, db.logs))
    def execute(self, statement, params=None):
        q = str(statement); params = params or {}; d = self.db
        d.calls.append((q, deepcopy(params)))
        if q == _LOCK_PRODUCTS_SQL:
            if d.after_lock:
                fn = d.after_lock; d.after_lock = None; fn(d)
            self.snapshot = deepcopy((d.psp, d.logs))
            return Result(params['codes'] if d.product else [])
        if q.startswith('SELECT 1 FROM products'): return Result([(1,)] if d.product else [])
        if q.startswith('SELECT name FROM suppliers'): return Result([d.supplier] if d.supplier is not None else [])
        if q.startswith('SELECT psp_id, cost_price'):
            return Result([{'psp_id': d.psp['psp_id'], 'cost_price': d.psp['cost_price']}] if d.psp else [])
        if q.startswith('SELECT sp.psp_id'):
            return Result([{'psp_id': d.psp['psp_id'], 'cost_price': d.psp['cost_price'], 'name': d.supplier}] if d.psp and d.supplier is not None else [])
        if q.startswith('SELECT count(*)'): return Result([int(d.psp is not None)])
        if q.startswith('INSERT INTO product_supplier_prices'):
            self.wrote = True
            d.psp = {'psp_id': d.psp['psp_id'] if d.psp else 302, 'cost_price': params['c'], 'state': params['st']}
            return Result([])
        if q.startswith('DELETE FROM product_supplier_prices'):
            self.wrote = True; d.psp = None; return Result([])
        raise AssertionError('unexpected SQL ' + q)


class SupplierPriceTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(); self.env = routes()
        self.env.update(engine=self.db, _log=self.db.log)
    def upsert(self, cost=14000, state=None):
        return self.env['upsert_supplier_price'](101, SimpleNamespace(supplier_id=11, cost_price=cost, state=state))
    def delete(self): return self.env['delete_supplier_price'](101, 11)
    def writes(self): return [q for q, _ in self.db.calls if q.startswith(('INSERT ', 'UPDATE ', 'DELETE '))]
    def assert_http(self, fn, code):
        with self.assertRaises(HTTPException) as caught: fn()
        self.assertEqual(caught.exception.status_code, code)
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.db.logs, [])
    def test_upsert_guard_before_PSP_read_lock_write_and_no_reprice(self):
        result = self.upsert(); calls = self.db.calls
        guard = next(i for i, (q, _) in enumerate(calls) if q == _LOCK_PRODUCTS_SQL)
        psp = next(i for i, (q, _) in enumerate(calls) if 'product_supplier_prices' in q)
        self.assertLess(guard, psp); self.assertIn('FOR UPDATE', calls[psp][0])
        self.assertEqual(calls[guard][1], {'codes': [101]})
        self.assertEqual(result, {'ok': True, 'supplier': '공급처', 'count': 1, 'undo_id': 1, 'note': '공급처 매입가를 14,000원으로 수정했습니다.'})
        self.assertEqual(self.writes(), [next(q for q, _ in calls if q.startswith('INSERT '))])
    def test_absent_PSP_insert_participates_in_guard(self):
        self.db.psp = None; out = self.upsert()
        self.assertTrue(self.db.logs[0][2]['new']); self.assertIsNone(self.db.logs[0][2]['from'])
        self.assertIn('등록했습니다', out['note']); self.assertEqual(self.db.psp['state'], '가능')
        self.assertEqual(sum(q == _LOCK_PRODUCTS_SQL for q, _ in self.db.calls), 1)
    def test_lock_after_read_uses_actual_before_and_supplier_name(self):
        def change(d): d.psp['cost_price'] = 10000; d.supplier = '새 이름'
        self.db.after_lock = change; out = self.upsert()
        self.assertEqual(self.db.logs[0][2]['from'], 10000); self.assertEqual(out['supplier'], '새 이름')
    def test_validation_and_initial_missing_semantics(self):
        for cost, state in ((None, None), (-1, None), (1, '불가')):
            self.setUp(); self.assert_http(lambda: self.upsert(cost, state), 400)
            self.assertEqual(self.db.calls, [])
        self.setUp(); self.db.product = False; self.assert_http(self.upsert, 404)
        self.setUp(); self.db.supplier = None; self.assert_http(self.upsert, 400)
    def test_product_or_supplier_disappears_no_write_409(self):
        for attr, value in (('product', False), ('supplier', None)):
            self.setUp(); self.db.after_lock = lambda d: setattr(d, attr, value)
            self.assert_http(self.upsert, 409)
    def test_zero_price_and_explicit_state_existing_policy(self):
        self.upsert(0, '품절'); self.assertEqual(self.db.psp['cost_price'], 0)
        self.assertEqual(self.db.psp['state'], '품절')
    def test_delete_guard_then_PSP_lock_and_actual_log_before(self):
        self.db.after_lock = lambda d: d.psp.update(cost_price=10000)
        out = self.delete(); calls = self.db.calls
        guard = next(i for i, (q, _) in enumerate(calls) if q == _LOCK_PRODUCTS_SQL)
        child = next(i for i, (q, _) in enumerate(calls) if 'FOR UPDATE OF sp' in q)
        delete = next(i for i, (q, _) in enumerate(calls) if q.startswith('DELETE '))
        self.assertLess(guard, child); self.assertLess(child, delete)
        self.assertEqual(self.db.logs[0][2]['cost_price'], 10000)
        self.assertEqual(out, {'ok': True, 'note': '공급처 매입가를 삭제했습니다.'})
    def test_missing_PSP_delete_guard_and_initial_404(self):
        self.db.psp = None; self.assert_http(self.delete, 404)
        self.assertTrue(any(q == _LOCK_PRODUCTS_SQL for q, _ in self.db.calls))
        self.setUp(); self.db.psp = None; self.db.product = False; self.assert_http(self.delete, 404)
    def test_missing_PSP_inserted_while_guard_waits_still_initial_404(self):
        self.db.psp = None
        self.db.after_lock = lambda d: setattr(d, 'psp', {'psp_id': 302, 'cost_price': 9999})
        self.assert_http(self.delete, 404); self.assertEqual(self.db.psp['cost_price'], 9999)
    def test_delete_disappearance_replacement_or_product_loss_409_no_write(self):
        for change in (lambda d: setattr(d, 'psp', None), lambda d: d.psp.update(psp_id=999), lambda d: setattr(d, 'product', False)):
            self.setUp(); self.db.after_lock = change; self.assert_http(self.delete, 409)
    def test_log_failure_propagates_same_exception_and_caller_rolls_back(self):
        for operation in ('upsert', 'delete'):
            self.setUp(); before = deepcopy(self.db.psp); error = RuntimeError('synthetic log failure'); self.db.fail = error
            with self.assertRaises(RuntimeError) as caught: getattr(self, operation)()
            self.assertIs(caught.exception, error); self.assertEqual(self.db.psp, before)
            self.assertEqual(self.db.logs, []); self.assertEqual(self.db.commits, 0); self.assertEqual(self.db.rollbacks, 1)
    def test_guard_SQL_exception_propagates_without_write_or_retry(self):
        original = Connection.execute
        error = RuntimeError('synthetic guard SQL failure')
        def execute(conn, statement, params=None):
            if str(statement) == _LOCK_PRODUCTS_SQL: raise error
            return original(conn, statement, params)
        for operation in ('upsert', 'delete'):
            self.setUp()
            with patch.object(Connection, 'execute', execute), self.assertRaises(RuntimeError) as caught:
                getattr(self, operation)()
            self.assertIs(caught.exception, error); self.assertEqual(self.writes(), [])
            self.assertEqual(self.db.logs, []); self.assertEqual(self.db.commits, 0); self.assertEqual(self.db.rollbacks, 1)


if __name__ == '__main__': unittest.main()
