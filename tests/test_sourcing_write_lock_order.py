"""No-DB product-first scope races and sourcing route regressions."""
import ast
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest

from fastapi import HTTPException
from sqlalchemy import text

from api.pricing_write_guard_core import lock_products, ProductScopeChanged
import test_sourcing_confirm_core as confirm_fixture


ADAPTER = Path(__file__).resolve().parents[1] / 'api' / 'admin_sourcing.py'


def routes(engine, log):
    tree = ast.parse(ADAPTER.read_text(encoding='utf-8'))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in ('request_quotes', 'record_reply')]
    for node in functions:
        node.decorator_list = []
    namespace = dict(engine=engine, text=text, lock_products=lock_products,
                     ProductScopeChanged=ProductScopeChanged, HTTPException=HTTPException,
                     RequestBody=SimpleNamespace, ReplyBody=SimpleNamespace,
                     _log=log, iso=lambda value: value.isoformat())
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(ADAPTER), 'exec'), namespace)
    return namespace


class RouteConnection:
    def __init__(self, values):
        self.values = values
        self.calls = []

    def execute(self, statement, params):
        self.calls.append((str(statement), deepcopy(params)))
        return confirm_fixture.FakeResult(deepcopy(self.values[len(self.calls)-1]))


class Engine:
    def __init__(self, connection):
        self.connection = connection
        self.exits = []

    def begin(self):
        owner = self
        class Transaction:
            def __enter__(self): return owner.connection
            def __exit__(self, typ, error, traceback): owner.exits.append(error); return False
        return Transaction()


class SourcingScopeTests(unittest.TestCase):
    def assert_no_writes_or_callbacks(self, fixture):
        self.assertFalse(any(sql.startswith(('INSERT', 'UPDATE', 'DELETE')) for sql, _ in fixture.conn.calls))
        self.assertFalse(any(item[0] in ('settings', 'reprice', 'ready', 'log') for item in fixture.trace))

    def test_all_sibling_products_including_terminal_rows_are_locked_ascending_once(self):
        fixture = confirm_fixture.Fixture()
        fixture.values[1] = [
            {'quote_id': 77, 'product_code': 101, 'batch_id': 201},
            {'quote_id': 78, 'product_code': 7, 'batch_id': 201},
            {'quote_id': 79, 'product_code': 303, 'batch_id': 201},
            {'quote_id': 80, 'product_code': 7, 'batch_id': 201}]
        fixture.values[2] = [7, 101, 303]
        fixture.values[4][1]['product_code'] = 7
        fixture.values[4][2]['product_code'] = 303
        fixture.values[4].append({**fixture.quote, 'quote_id': 80, 'product_code': 7, 'status': '취소'})
        fixture.values[5] = deepcopy(fixture.values[1])
        fixture.run()
        self.assertEqual(fixture.conn.calls[2][1], {'codes': [7, 101, 303]})
        self.assertEqual(fixture.conn.calls[4][1], {'ids': [77, 78, 79, 80]})
        locks = [(i, sql) for i, (sql, _) in enumerate(fixture.conn.calls) if 'FOR UPDATE' in sql]
        self.assertEqual([i for i, _ in locks], [2, 3, 4])
        self.assertFalse(any('JOIN' in sql for _, sql in locks))
        self.assertEqual(fixture.log_calls[0][2]['cancelled_siblings'],
                         [{'quote_id': 78, 'status': '요청'}, {'quote_id': 79, 'status': '회신'}])

    def test_new_deleted_or_relinked_candidate_after_product_locks_aborts_without_late_lock(self):
        mutations = []
        for index in (4, 5):
            for mode in ('new', 'deleted', 'product', 'batch'):
                fixture = confirm_fixture.Fixture()
                fixture.values[index] = deepcopy(fixture.values[index])
                rows = fixture.values[index]
                if mode == 'new': rows.append({**rows[0], 'quote_id': 81, 'product_code': 999})
                elif mode == 'deleted': rows.pop()
                elif mode == 'product': rows[1]['product_code'] = 999
                else: rows[1]['batch_id'] = 202
                mutations.append(fixture)
        for fixture in mutations:
            with self.assertRaises(HTTPException) as error: fixture.run()
            self.assertEqual(error.exception.status_code, 409)
            self.assert_no_writes_or_callbacks(fixture)
            self.assertEqual(sum('ORDER BY product_code FOR UPDATE' in sql for sql, _ in fixture.conn.calls), 1)

    def test_target_disappears_or_changes_product_batch_before_and_after_discovery(self):
        for index in (1, 4, 5):
            for key in ('product_code', 'batch_id'):
                fixture = confirm_fixture.Fixture()
                fixture.values[index] = deepcopy(fixture.values[index])
                fixture.values[index][0][key] = 999
                with self.assertRaises(HTTPException) as error: fixture.run()
                self.assertEqual(error.exception.status_code, 409)
                self.assert_no_writes_or_callbacks(fixture)
        fixture = confirm_fixture.Fixture(); fixture.values[4] = []
        with self.assertRaises(HTTPException) as error: fixture.run()
        self.assertEqual(error.exception.status_code, 409); self.assert_no_writes_or_callbacks(fixture)

    def test_initial_target_missing_is_404_and_revalidation_state_failure_is_409(self):
        fixture = confirm_fixture.Fixture(missing_quote=True)
        with self.assertRaises(HTTPException) as error: fixture.run()
        self.assertEqual(error.exception.status_code, 404)
        for change in ({'status': '확정'}, {'price': None}):
            fixture = confirm_fixture.Fixture()
            fixture.values[4] = deepcopy(fixture.values[4]); fixture.values[4][0].update(change)
            with self.assertRaises(HTTPException) as error: fixture.run()
            self.assertEqual(error.exception.status_code, 409); self.assert_no_writes_or_callbacks(fixture)

    def test_product_scope_helper_mismatch_is_409_before_batch_or_quote_locks(self):
        for values in ([], [True], [102], [101, 101]):
            fixture = confirm_fixture.Fixture(); fixture.values[2] = values
            with self.assertRaises(HTTPException) as error: fixture.run()
            self.assertEqual(error.exception.status_code, 409)
            self.assertEqual(len(fixture.conn.calls), 3); self.assert_no_writes_or_callbacks(fixture)

    def test_locked_quote_price_and_locked_product_sku_supply_current_effects(self):
        fixture = confirm_fixture.Fixture(after={'purchase_price': 200000, 'sale_price': 212000})
        fixture.values[4] = deepcopy(fixture.values[4])
        fixture.values[4][0]['price'] = 200000
        fixture.values[6] = 'P-current'
        result = fixture.run()
        self.assertEqual((result['sku'], result['price']), ('P-current', 200000))
        self.assertEqual(fixture.conn.calls[9][1]['c'], 200000)
        self.assertEqual(fixture.log_calls[0][1], 'P-current')

    def test_nullable_batch_retains_null_before_and_no_cancellation_scope(self):
        fixture = confirm_fixture.Fixture(quote={'batch_id': None}, siblings=[], batch_status=None)
        fixture.run()
        self.assertEqual(fixture.conn.calls[3][1], {'b': None})
        self.assertEqual(fixture.conn.calls[4][1], {'ids': [77]})
        self.assertEqual(fixture.log_calls[0][2]['before']['batch_status'], None)
        self.assertEqual(fixture.log_calls[0][2]['cancelled_siblings'], [])
        self.assertEqual(fixture.conn.calls[12][1], {'b': None, 'i': 77})


class SourcingRouteTests(unittest.TestCase):
    def request(self, values, supplier_ids=None):
        conn = RouteConnection(values); engine = Engine(conn); logged = []
        ns = routes(engine, lambda *args, **kwargs: logged.append((args, kwargs)) or 91)
        body = SimpleNamespace(product_code=101, supplier_ids=[11] if supplier_ids is None else supplier_ids)
        return conn, engine, logged, ns, body

    def test_request_checks_duplicate_after_product_lock_and_preserves_response_and_duplicate_suppliers(self):
        conn, engine, logged, ns, body = self.request(
            [101, [101], {'sku': 'P-101', 'product_name': '상품'}, None, 201, '공급처', 77, '공급처', 78], [11, 11])
        result = ns['request_quotes'](body)
        self.assertEqual(result, {'ok': True, 'batch_id': 201,
                                 'quotes': [{'quote_id': 77, 'supplier': '공급처'}, {'quote_id': 78, 'supplier': '공급처'}], 'undo_id': 91})
        self.assertIn('ORDER BY product_code FOR UPDATE', conn.calls[1][0])
        self.assertIn('SELECT sku, product_name', conn.calls[2][0])
        self.assertIn("status IN ('요청','회신')", conn.calls[3][0])
        self.assertEqual([params['s'] for sql, params in conn.calls if sql.startswith('INSERT INTO product_sourcing_quotes')], [11, 11])
        self.assertEqual(logged[0][0][1:3], ('sourcing_request', 'P-101'))
        self.assertEqual(engine.exits, [None])

    def test_request_empty_suppliers_and_first_missing_product_preserve_400_404(self):
        conn, engine, logged, ns, body = self.request([], [])
        with self.assertRaises(HTTPException) as error: ns['request_quotes'](body)
        self.assertEqual(error.exception.status_code, 400); self.assertEqual(engine.exits, [])
        conn, engine, logged, ns, body = self.request([None])
        with self.assertRaises(HTTPException) as error: ns['request_quotes'](body)
        self.assertEqual(error.exception.status_code, 404); self.assertEqual(len(conn.calls), 1)

    def test_request_deleted_scope_and_existing_active_request_are_no_write_409(self):
        for values in ([101, []], [101, [101], None], [101, [101], {'sku': 'P-101'}, (1,)]):
            conn, engine, logged, ns, body = self.request(values)
            with self.assertRaises(HTTPException) as error: ns['request_quotes'](body)
            self.assertEqual(error.exception.status_code, 409)
            self.assertFalse(any(sql.startswith('INSERT') for sql, _ in conn.calls)); self.assertEqual(logged, [])
            self.assertIs(engine.exits[0], error.exception)

    def test_request_missing_supplier_keeps_existing_404_inside_caller_transaction(self):
        conn, engine, logged, ns, body = self.request(
            [101, [101], {'sku': 'P-101', 'product_name': '상품'}, None, 201, None])
        with self.assertRaises(HTTPException) as error: ns['request_quotes'](body)
        self.assertEqual((error.exception.status_code, error.exception.detail), (404, '공급처가 없습니다: 11'))
        self.assertIs(engine.exits[0], error.exception)
        self.assertEqual(logged, [])
        self.assertEqual(sum(sql.startswith('INSERT INTO sourcing_batches') for sql, _ in conn.calls), 1)
        self.assertFalse(any(sql.startswith('INSERT INTO product_sourcing_quotes') for sql, _ in conn.calls))

    def reply(self, discovered=None, locked=None, product_rows=None):
        initial = {'quote_id': 77, 'product_code': 101, 'batch_id': 201} if discovered is None else discovered
        q = {'quote_id': 77, 'product_code': 101, 'batch_id': 201, 'status': '회신', 'price': 100,
             'memo': 'old', 'replied_at': datetime(2026, 1, 2)} if locked is None else locked
        conn = RouteConnection([initial, [101] if product_rows is None else product_rows, q, None])
        engine = Engine(conn); logged = []
        ns = routes(engine, lambda *args, **kwargs: logged.append((args, kwargs)))
        return conn, engine, logged, ns

    def test_reply_locks_product_before_quote_and_preserves_original_before_detail(self):
        conn, engine, logged, ns = self.reply()
        result = ns['record_reply'](77, SimpleNamespace(price=200, memo=None))
        self.assertEqual(result, {'ok': True, 'price': 200})
        self.assertNotIn('FOR UPDATE', conn.calls[0][0])
        self.assertIn('ORDER BY product_code FOR UPDATE', conn.calls[1][0])
        self.assertIn('WHERE quote_id=:i FOR UPDATE', conn.calls[2][0])
        self.assertEqual(logged[0][0][3]['before'], {'price': 100, 'status': '회신', 'memo': 'old', 'replied_at': '2026-01-02T00:00:00'})
        self.assertEqual(conn.calls[3][1], {'p': 200, 'm': None, 'i': 77})

    def test_reply_connection_change_or_deleted_quote_scope_is_no_write_409(self):
        for change in ({'product_code': 999}, {'batch_id': 202}, {'status': '취소'}):
            conn, engine, logged, ns = self.reply(); conn.values[2].update(change)
            with self.assertRaises(HTTPException) as error: ns['record_reply'](77, SimpleNamespace(price=200, memo=None))
            self.assertEqual(error.exception.status_code, 409); self.assertEqual(len(conn.calls), 3); self.assertEqual(logged, [])
        for index, value in ((1, []), (2, None)):
            conn, engine, logged, ns = self.reply(); conn.values[index] = value
            with self.assertRaises(HTTPException) as error: ns['record_reply'](77, SimpleNamespace(price=200, memo=None))
            self.assertEqual(error.exception.status_code, 409); self.assertEqual(logged, [])

    def test_reply_missing_initial_quote_and_invalid_price_preserve_404_400(self):
        conn, engine, logged, ns = self.reply(); conn.values[0] = None
        with self.assertRaises(HTTPException) as error: ns['record_reply'](77, SimpleNamespace(price=200, memo=None))
        self.assertEqual(error.exception.status_code, 404); self.assertEqual(len(conn.calls), 1)
        conn, engine, logged, ns = self.reply()
        with self.assertRaises(HTTPException) as error: ns['record_reply'](77, SimpleNamespace(price=0, memo=None))
        self.assertEqual(error.exception.status_code, 400); self.assertEqual(conn.calls, [])

    def test_reply_nullable_batch_and_first_reply_nulls_preserved(self):
        conn, engine, logged, ns = self.reply()
        conn.values[0]['batch_id'] = None
        conn.values[2].update(batch_id=None, status='요청', price=None, memo=None, replied_at=None)
        ns['record_reply'](77, SimpleNamespace(price=200, memo='new'))
        self.assertEqual(logged[0][0][3]['before'], {'price': None, 'status': '요청', 'memo': None, 'replied_at': None})


class ConcurrentRequestBoundaryTests(unittest.TestCase):
    def test_two_mock_requests_serialize_duplicate_check_after_product_lock(self):
        mutex = threading.Lock(); discovery = threading.Barrier(2)
        state = {'active': False, 'created': 0}; calls = []; logs = []; results = []
        class Connection:
            held = False
            def execute(self, statement, params):
                sql = str(statement); calls.append((threading.get_ident(), sql))
                if sql.startswith('SELECT product_code FROM products WHERE product_code=:pc'):
                    discovery.wait(timeout=3); value = 101
                elif 'ORDER BY product_code FOR UPDATE' in sql:
                    if not mutex.acquire(timeout=3): raise AssertionError('product_lock_timeout')
                    self.held = True; value = [101]
                elif sql.startswith('SELECT sku, product_name'): value = {'sku': 'P-101', 'product_name': '상품'}
                elif sql.startswith('SELECT 1 FROM product_sourcing_quotes'):
                    if not self.held: raise AssertionError('duplicate_read_before_lock')
                    value = (1,) if state['active'] else None
                elif sql.startswith('INSERT INTO sourcing_batches'): value = 201
                elif sql.startswith('SELECT name FROM suppliers'): value = '공급처'
                elif sql.startswith('INSERT INTO product_sourcing_quotes'):
                    state['active'] = True; state['created'] += 1; value = 77
                else: raise AssertionError('unexpected SQL')
                return confirm_fixture.FakeResult(value)
        class ConcurrentEngine:
            def begin(self):
                conn = Connection()
                class Transaction:
                    def __enter__(self): return conn
                    def __exit__(self, typ, error, traceback):
                        if conn.held: mutex.release()
                        return False
                return Transaction()
        ns = routes(ConcurrentEngine(), lambda *a, **k: logs.append(a) or 91)
        def invoke():
            try: results.append(ns['request_quotes'](SimpleNamespace(product_code=101, supplier_ids=[11])))
            except BaseException as error: results.append(error)
        workers = [threading.Thread(target=invoke) for _ in range(2)]
        for worker in workers: worker.start()
        for worker in workers: worker.join(5); self.assertFalse(worker.is_alive())
        self.assertEqual(state['created'], 1); self.assertEqual(len(logs), 1)
        self.assertEqual(sum(type(result) is dict for result in results), 1)
        errors = [result for result in results if isinstance(result, HTTPException)]
        self.assertEqual([error.status_code for error in errors], [409])


if __name__ == '__main__': unittest.main()
