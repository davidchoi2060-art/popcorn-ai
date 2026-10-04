"""Selected mapping routes; mock serialization is not actual PG evidence."""
import ast
from copy import deepcopy
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from sqlalchemy import text
from api.pricing_write_guard_core import lock_products, ProductScopeChanged, _LOCK_PRODUCTS_SQL


def routes():
    source = Path(__file__).resolve().parents[1] / 'api/admin_reviews.py'
    nodes = []
    for node in ast.parse(source.read_text(encoding='utf-8')).body:
        if isinstance(node, ast.FunctionDef) and node.name in ('sourcing_link', 'sourcing_unlink'):
            node.decorator_list = []; nodes.append(node)
    env = dict(text=text, HTTPException=HTTPException, LinkBody=object,
               lock_products=lock_products, ProductScopeChanged=ProductScopeChanged,
               current_operator_id=lambda: 21)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), env)
    return env


class Result:
    def __init__(self, rows): self.rows = deepcopy(rows)
    def mappings(self): return self
    def scalars(self): return self
    def all(self): return deepcopy(self.rows)
    def first(self): return deepcopy(self.rows[0]) if self.rows else None
    def scalar(self): return self.first()


class Database:
    def __init__(self):
        self.prod = {'product_code': 101, 'sku': 'P101'}
        self.row = {'row_id': 5011, 'file_id': 501, 'model_name': 'model'}
        self.file = {'file_id': 501, 'supplier_id': 11}
        self.mapping = None
        self.logs = {}; self.calls = []; self.after_lock = None; self.fail = None
        self.commits = self.rollbacks = 0
        self.log_guard = threading.Lock(); self.pause = False
        self.first_locked = threading.Event(); self.second_entered = threading.Event(); self.release = threading.Event()
    def begin(self): return Transaction(self)
    def log(self, conn, action, target, detail):
        conn.wrote = True
        number = max(self.logs, default=0) + 1
        self.logs[number] = {'action': action, 'detail': deepcopy(detail)}
        if self.fail: raise self.fail
        return number
    def seed_link(self):
        self.mapping = {'map_id': 601, 'product_code': 101, 'match_method': 'manual', 'supplier_id': 11, 'model_key': 'model'}
        self.logs[1] = {'action': 'sourcing_link', 'detail': {'map_id': 601, 'row_id': 5011, 'supplier_id': 11, 'model_key': 'model', 'product_code': 101, 'sku': 'P101', 'method': 'manual'}}


class Transaction:
    def __init__(self, db): self.db = db
    def __enter__(self): self.conn = Connection(self.db); return self.conn
    def __exit__(self, typ, value, trace):
        if typ:
            self.db.rollbacks += 1
            if self.conn.wrote: self.db.mapping, self.db.logs = deepcopy(self.conn.snapshot)
        else: self.db.commits += 1
        if self.conn.log_held: self.db.log_guard.release()
        return False


class Connection:
    def __init__(self, db):
        self.db = db; self.wrote = False; self.log_held = False
        self.snapshot = deepcopy((db.mapping, db.logs))
    def execute(self, statement, params=None):
        q = str(statement); params = params or {}; d = self.db
        d.calls.append((threading.current_thread().name, q, deepcopy(params)))
        if q == _LOCK_PRODUCTS_SQL:
            if d.after_lock:
                fn = d.after_lock; d.after_lock = None; fn(d)
            self.snapshot = deepcopy((d.mapping, d.logs))
            return Result([d.prod['product_code']] if d.prod and d.prod['product_code'] in params['codes'] else [])
        if q.startswith('SELECT r.row_id'):
            return Result([{**d.row, 'supplier_id': d.file['supplier_id']}] if d.row and d.file else [])
        if q.startswith('SELECT product_code, sku'):
            return Result([d.prod] if d.prod and d.prod['sku'] == params['s'] else [])
        if q.startswith('SELECT file_id, supplier_id'):
            return Result([d.file] if d.file and d.file['file_id'] == params['f'] else [])
        if q.startswith('SELECT row_id, file_id, model_name'):
            return Result([d.row] if d.row and d.row['row_id'] == params['i'] else [])
        if q.startswith('SELECT action, detail'):
            if 'FOR UPDATE' not in q: raise AssertionError('original log must serialize unlink')
            if d.pause and threading.current_thread().name == 'unlink-second': d.second_entered.set()
            if not d.log_guard.acquire(timeout=3): raise AssertionError('mock log timeout')
            self.log_held = True; self.snapshot = deepcopy((d.mapping, d.logs))
            if d.pause and threading.current_thread().name == 'unlink-first':
                d.first_locked.set()
                if not d.release.wait(3): raise AssertionError('mock barrier timeout')
            return Result([d.logs[params['i']]] if params['i'] in d.logs else [])
        if q.startswith('SELECT 1 FROM admin_operator_activity_logs'):
            return Result([(1,)] if any(x['action'] == 'sourcing_unlink' and x['detail']['ref_log_id'] == params['i'] for x in d.logs.values()) else [])
        if q.startswith('SELECT product_code, match_method'):
            return Result([tuple(d.mapping[k] for k in ('product_code', 'match_method', 'supplier_id', 'model_key'))] if d.mapping and d.mapping['map_id'] == params['m'] else [])
        if q.startswith('INSERT INTO supplier_product_map'):
            if d.mapping: return Result([])
            self.wrote = True
            d.mapping = {'map_id': 601, 'product_code': params['pc'], 'match_method': params['m'], 'supplier_id': params['s'], 'model_key': params['k']}
            return Result([601])
        if q.startswith('DELETE FROM supplier_product_map'):
            self.wrote = True; d.mapping = None; return Result([])
        raise AssertionError('unexpected SQL ' + q)


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(); self.env = routes(); self.env.update(engine=self.db, _log=self.db.log)
    def link(self, via='manual'):
        return self.env['sourcing_link'](SimpleNamespace(row_id=5011, sku=' P101 ', via=via))
    def unlink(self, log_id=1): return self.env['sourcing_unlink'](log_id)
    def writes(self): return [q for _, q, _ in self.db.calls if q.startswith(('INSERT ', 'UPDATE ', 'DELETE '))]
    def assert_http(self, fn, code, detail=None):
        with self.assertRaises(HTTPException) as caught: fn()
        self.assertEqual(caught.exception.status_code, code)
        if detail: self.assertEqual(caught.exception.detail, detail)
        self.assertEqual(self.writes(), [])
    def test_link_product_then_file_then_row_then_insert_no_price_write(self):
        out = self.link(); calls = self.db.calls
        guard = next(i for i, (_, q, _) in enumerate(calls) if q == _LOCK_PRODUCTS_SQL)
        file = next(i for i, (_, q, _) in enumerate(calls) if 'supplier_price_files WHERE' in q)
        row = next(i for i, (_, q, _) in enumerate(calls) if q.startswith('SELECT row_id'))
        insert = next(i for i, (_, q, _) in enumerate(calls) if q.startswith('INSERT '))
        self.assertLess(guard, file); self.assertLess(file, row); self.assertLess(row, insert)
        self.assertEqual(calls[guard][2], {'codes': [101]})
        self.assertEqual(out, {'ok': True, 'undo_id': 1, 'sku': 'P101'})
        self.assertEqual(self.db.logs[1]['detail'], {'map_id': 601, 'row_id': 5011, 'supplier_id': 11, 'model_key': 'model', 'product_code': 101, 'sku': 'P101', 'method': 'manual'})
        self.assertEqual(len(self.writes()), 1); self.assertIn('supplier_product_map', self.writes()[0])
    def test_method_policy_candidate_and_unknown_via(self):
        for via, method in [('candidate', 'similarity'), ('other', 'manual')]:
            self.setUp(); self.link(via); self.assertEqual(self.db.mapping['match_method'], method)
    def test_initial_missing_row_or_product_404_without_lock(self):
        for attr in ('row', 'prod'):
            self.setUp(); setattr(self.db, attr, None); self.assert_http(self.link, 404)
            self.assertFalse(any(q == _LOCK_PRODUCTS_SQL for _, q, _ in self.db.calls))
    def test_link_file_row_supplier_model_and_product_scope_drift_no_late_lock(self):
        changes = [lambda d: setattr(d, 'file', None), lambda d: d.file.update(supplier_id=12), lambda d: d.file.update(file_id=502), lambda d: setattr(d, 'row', None), lambda d: d.row.update(model_name='other'), lambda d: d.row.update(file_id=502), lambda d: d.prod.update(sku='P102'), lambda d: d.prod.update(product_code=102), lambda d: setattr(d, 'prod', None)]
        for change in changes:
            self.setUp(); self.db.after_lock = change; self.assert_http(self.link, 409)
            self.assertEqual([p['codes'] for _, q, p in self.db.calls if q == _LOCK_PRODUCTS_SQL], [[101]])
            self.assertEqual(self.db.logs, {})
    def test_existing_key_and_new_conflict_keep_on_conflict_409(self):
        self.db.seed_link()
        with self.assertRaises(HTTPException) as caught: self.link()
        self.assertEqual(caught.exception.detail, '이미 연결된 모델입니다')
        self.assertEqual(len(self.db.logs), 1)
        self.assertIn('ON CONFLICT (supplier_id, model_key) DO NOTHING', self.writes()[0])
        self.setUp(); self.db.after_lock = lambda d: d.seed_link()
        with self.assertRaises(HTTPException) as caught: self.link()
        self.assertEqual(caught.exception.status_code, 409); self.assertEqual(len(self.db.logs), 1)
    def test_unlink_original_log_then_product_then_map_and_unchanged_return(self):
        self.db.seed_link(); self.assertEqual(self.unlink(), {'ok': True})
        qs = [q for _, q, _ in self.db.calls]
        self.assertIn('FOR UPDATE', qs[0]); guard = qs.index(_LOCK_PRODUCTS_SQL)
        child = next(i for i, q in enumerate(qs) if q.startswith('SELECT product_code, match_method'))
        self.assertLess(0, guard); self.assertLess(guard, child)
        self.assertIsNone(self.db.mapping); self.assertEqual(self.db.logs[2], {'action': 'sourcing_unlink', 'detail': {'ref_log_id': 1, 'model_key': 'model'}})
    def test_unlink_initial_invalid_log_or_duplicate_before_product(self):
        self.assert_http(self.unlink, 404)
        self.setUp(); self.db.seed_link(); self.db.logs[1]['action'] = 'other'; self.assert_http(self.unlink, 404)
        self.setUp(); self.db.seed_link(); self.db.logs[2] = {'action': 'sourcing_unlink', 'detail': {'ref_log_id': 1}}
        self.assert_http(self.unlink, 409, '이미 되돌린 연결입니다')
        self.assertFalse(any(q == _LOCK_PRODUCTS_SQL for _, q, _ in self.db.calls))
    def test_unlink_product_and_map_identity_drift_no_delete_or_log(self):
        for change in [lambda d: setattr(d, 'prod', None), lambda d: setattr(d, 'mapping', None)] + [lambda d, k=k, v=v: d.mapping.update({k: v}) for k, v in [('product_code', 102), ('match_method', 'similarity'), ('supplier_id', 12), ('model_key', 'other')]]:
            self.setUp(); self.db.seed_link(); self.db.after_lock = change
            self.assert_http(self.unlink, 409); self.assertEqual(len(self.db.logs), 1)
    def test_same_unlink_mock_serializes_original_log_and_one_duplicate_409(self):
        self.db.seed_link(); self.db.pause = True; results = {}; errors = []
        def work(name):
            try: results[name] = self.unlink()
            except HTTPException as exc: results[name] = (exc.status_code, exc.detail)
            except BaseException as exc: errors.append(exc)
        first = threading.Thread(target=work, args=('first',), name='unlink-first')
        second = threading.Thread(target=work, args=('second',), name='unlink-second')
        first.start()
        try:
            self.assertTrue(self.db.first_locked.wait(3)); second.start()
            self.assertTrue(self.db.second_entered.wait(3)); self.assertNotIn('second', results)
        finally:
            self.db.release.set(); first.join(3)
            if second.ident is not None: second.join(3)
        self.assertFalse(first.is_alive()); self.assertFalse(second.is_alive()); self.assertEqual(errors, [])
        self.assertEqual(results, {'first': {'ok': True}, 'second': (409, '이미 되돌린 연결입니다')})
        self.assertEqual(sum(q.startswith('DELETE ') for _, q, _ in self.db.calls), 1)
        self.assertEqual(len(self.db.logs), 2); self.assertEqual(self.db.commits, 1); self.assertEqual(self.db.rollbacks, 1)
    def test_log_failure_same_exception_caller_transaction_rolls_back(self):
        for operation in ('link', 'unlink'):
            self.setUp()
            if operation == 'unlink': self.db.seed_link()
            old = deepcopy((self.db.mapping, self.db.logs)); error = RuntimeError('synthetic log failure'); self.db.fail = error
            with self.assertRaises(RuntimeError) as caught: getattr(self, operation)()
            self.assertIs(caught.exception, error); self.assertEqual((self.db.mapping, self.db.logs), old)
            self.assertEqual(self.db.commits, 0); self.assertEqual(self.db.rollbacks, 1)
    def test_child_lock_SQL_error_propagates_same_without_write_or_retry(self):
        original = Connection.execute
        error = RuntimeError('synthetic child-lock failure')
        def execute(conn, statement, params=None):
            q = str(statement)
            if q.startswith(('SELECT file_id, supplier_id', 'SELECT product_code, match_method')): raise error
            return original(conn, statement, params)
        for operation in ('link', 'unlink'):
            self.setUp()
            if operation == 'unlink': self.db.seed_link()
            old = deepcopy((self.db.mapping, self.db.logs))
            with patch.object(Connection, 'execute', execute), self.assertRaises(RuntimeError) as caught:
                getattr(self, operation)()
            self.assertIs(caught.exception, error); self.assertEqual(self.writes(), [])
            self.assertEqual((self.db.mapping, self.db.logs), old)
            self.assertEqual(self.db.commits, 0); self.assertEqual(self.db.rollbacks, 1)


if __name__ == '__main__': unittest.main()
