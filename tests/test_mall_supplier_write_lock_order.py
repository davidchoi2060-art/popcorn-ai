"""Selected-AST no-DB regression; never import HTTP app or the fetch module."""
import ast
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import hashlib
import importlib.util
from pathlib import Path
import re
from types import SimpleNamespace
import unittest

from fastapi import HTTPException
from sqlalchemy import bindparam, text
from api.mall_supplier_write_guard import (
    lock_mall_write_scope, SupplierScopeChanged, _CONTACT_LOCK_SQL, _SUPPLIER_SCOPE_SQL,
)
from api.pricing_write_guard_core import ProductScopeChanged, _LOCK_PRODUCTS_SQL

ROOT = Path(__file__).resolve().parents[1]
BASELINE = {'api/admin_mall_supplier.py': {'function': '185f5a885b6524e72f98610f798fb281f04b3ce24e75218189c48bf8f654e6c0', 'rest': 'c39ec70d713c00a1fc9413d0b518a678c1ef3ea2202c32d0c86d39e51bc8c592'}, 'tools/mall_supplier_fetch.py': {'function': 'e68eb716c1c754caa532a763f702ecd34dfe1376b050f0a008ad187ea0e8d0b8', 'rest': '1ad713dba16a6cf6db7561ccc0ceb6fbfe447afb2c30d28b9f5435285b60154a'}}
PROTECTED = {'api/mall_supplier_parse.py': '22125a6156e6f4ba6f81abf4455d4bd90d498acf65929979d37e9efdc33d8a69',
             'api/pricing_write_guard_core.py': 'be068f1bf63421fd71e569a9b9b38fbedb13aa0c002a5973622de5f8e06c3e24'}
NOW = datetime(2030, 1, 2, 3, 4, 5)

class NativeFailure(RuntimeError): pass
class FixedDateTime:
    @staticmethod
    def now(): return NOW

class Result:
    def __init__(self, value): self.value = value
    def scalars(self): return self
    def mappings(self): return self
    def all(self): return self.value
    def scalar(self): return self.value
    def first(self): return self.value[0] if self.value else None

class Database:
    def __init__(self):
        self.products = {101, 102}
        self.suppliers = {11, 12, 13}
        self.psp, self.contacts, self.logs = {}, {sid: {'contact_phone': 'old'} for sid in self.suppliers}, []
        self.html, self.events, self.connections, self.transactions = {}, [], [], []
        self.after_product = None
        self.fail = None
        self.overrides = {}
    def connect(self): return Session(self, False)
    def begin(self): return Session(self, True)

class Session:
    def __init__(self, db, write): self.db, self.write = db, write
    def __enter__(self):
        self.conn = Connection(self.db, self.write)
        self.db.connections.append(self.conn)
        if self.write:
            self.before = deepcopy((self.db.psp, self.db.contacts, self.db.logs))
            self.db.events.append(('begin', self.conn))
        return self.conn
    def __exit__(self, typ, value, trace):
        if self.write:
            if typ: self.db.psp, self.db.contacts, self.db.logs = self.before
            self.db.transactions.append((self.conn, value))
            self.db.events.append(('rollback' if typ else 'commit', self.conn))
        self.conn.closed = True
        return False

class Connection:
    def __init__(self, db, write): self.db, self.write, self.calls, self.closed = db, write, [], False
    def execute(self, statement, params=None):
        q = str(statement); p = {} if params is None else deepcopy(params)
        self.calls.append((q, p)); self.db.events.append(('sql', self, q, p))
        if self.db.fail:
            error = self.db.fail(q, p, self)
            if error is not None: raise error
        if q in self.db.overrides: return Result(deepcopy(self.db.overrides[q]))
        if q == _LOCK_PRODUCTS_SQL:
            rows = [pc for pc in p['codes'] if pc in self.db.products]
            if self.db.after_product: self.db.after_product(self.db, p['codes'])
            return Result(rows)
        if q == 'SELECT product_code FROM products WHERE product_code=:pc':
            return Result(p['pc'] if p['pc'] in self.db.products else None)
        if q in (_CONTACT_LOCK_SQL, _SUPPLIER_SCOPE_SQL):
            return Result([sid for sid in p['ids'] if sid in self.db.suppliers])
        if q.startswith('SELECT product_code FROM products WHERE product_code IN'):
            return Result([pc for pc in p['codes'] if pc in self.db.products])
        if q.startswith('SELECT product_code, supplier_id, cost_price'):
            return Result([{'product_code': pc, 'supplier_id': sid, **deepcopy(row)}
                           for (pc, sid), row in self.db.psp.items() if pc in p['codes']])
        if q.startswith('SELECT 1 FROM product_supplier_prices'):
            return Result([(1,)] if (p['pc'], p['s']) in self.db.psp else [])
        if q.startswith('SELECT contact_phone FROM suppliers'):
            return Result(self.db.contacts.get(p['s'], {}).get('contact_phone'))
        if q.strip().startswith('INSERT INTO product_supplier_prices'):
            if not self.write: raise AssertionError('write through read connection')
            self.db.psp[(p['pc'], p['s'])] = {'cost_price': p['cost'], 'supply_state': p['state'],
                'mall_rank': p['rank'], 'rebate_pct': p['rpct'], 'rebate_price': p['rprice'],
                'order_price': p['oprice'], 'mall_state_raw': p['sraw'], 'fetched_at': p['fa']}
            return Result([])
        if q.strip().startswith('UPDATE suppliers SET'):
            if not self.write: raise AssertionError('write through read connection')
            contact = self.db.contacts[p['s']]
            for key, arg in [('contact_name', 'cn'), ('contact_phone', 'cp'), ('order_phone', 'op'), ('contact_raw', 'cr')]:
                if p[arg] is not None: contact[key] = p[arg]
            contact['contact_fetched_at'] = p['fa']
            return Result([])
        raise AssertionError('unexpected selected SQL: ' + q)


def digest(node): return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


def selected(rel, names, env, legacy=False):
    tree = ast.parse((ROOT / rel).read_text(encoding='utf-8-sig'))
    nodes = [deepcopy(n) for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    if legacy:
        class RemoveGuard(ast.NodeTransformer):
            def visit_Expr(self, node):
                if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == 'lock_mall_write_scope':
                    return None
                return self.generic_visit(node)
        function = next(n for n in nodes if n.name in ('ingest', '_plan_and_maybe_apply'))
        RemoveGuard().visit(function)
        self_hash = BASELINE[rel]['function']
        if digest(function) != self_hash: raise AssertionError('baseline function AST drift')
    for node in nodes: node.decorator_list = []
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROOT / rel), 'exec'), env)
    return env


def parser_sql():
    tree = ast.parse((ROOT / 'api/mall_supplier_parse.py').read_text(encoding='utf-8-sig'))
    nodes = [deepcopy(n) for n in tree.body if (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in ('PSP_UPSERT', 'SUPPLIER_CONTACT_UPDATE') for t in n.targets)) or (isinstance(n, ast.FunctionDef) and n.name == 'cheapest_summary')]
    env = {'text': text}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'selected_mall_sql', 'exec'), env)
    return env


def row(sid, contact=True, cost=10000, idx=1):
    return {'state': '가능', 'o_price': cost, 'idx': idx, 'rebate_pct': 1.25,
            'rebate_price': 125, 'order_price': None, 'state_raw': '판매중',
            'phone': 'new' if contact else None, 'order_phone': None,
            'contact_blob': 'supplier' + str(sid) + ('|담당자' if contact else '')}


def stats():
    return {'psp_insert': 0, 'psp_update': 0, 'contact_filled': 0,
            'contact_would_fill': 0, 'contact_conflict': []}


def http(db, legacy=False):
    parser = parser_sql()
    def parse(html): db.events.append(('parse', html)); return deepcopy(db.html[html])
    def resolve(blob, suppliers):
        db.events.append(('resolve', blob))
        if blob == '재고있음': return None, None, blob, 'excluded_stock_status'
        match = re.fullmatch(r'supplier(\d+)(?:\|(.+))?', blob)
        if not match: return None, None, blob, 'unmatched'
        sid = int(match[1]); return sid, 'Supplier' + str(sid), match[2], 'matched'
    def log(conn, action, target, detail, kind='order'):
        db.events.append(('log', conn)); db.logs.append((action, target, deepcopy(detail), kind)); return len(db.logs)
    env = {'_IngestBody': object, '_require_owner': lambda: None, 'engine': db,
           'datetime': FixedDateTime, 'HTTPException': HTTPException, 'text': text,
           'bindparam': bindparam, 'MAX_ITEMS': 200, 'MAX_ROWS_HTML_CHARS': 300000,
           'MAX_TOTAL_ROWS_HTML_CHARS': 8000000, '_COMPARE_COLS': ('cost_price', 'supply_state', 'mall_rank', 'rebate_price', 'order_price', 'mall_state_raw'),
           'parse_rows': parse, 'load_suppliers': lambda conn: [{'supplier_id': sid} for sid in db.suppliers],
           'resolve_supplier': resolve, '_log': log, 'lock_mall_write_scope': lock_mall_write_scope,
           **parser}
    return selected('api/admin_mall_supplier.py', {'ingest', '_classify', '_known_product_codes', '_existing_psp_rows'}, env, legacy)


def cli(db, legacy=False):
    parser = parser_sql()
    env = {'text': text, '_PSP_UPSERT': parser['PSP_UPSERT'], '_SUPPLIER_CONTACT_UPDATE': parser['SUPPLIER_CONTACT_UPDATE'],
           'lock_mall_write_scope': lock_mall_write_scope}
    return selected('tools/mall_supplier_fetch.py', {'_plan_and_maybe_apply'}, env, legacy)['_plan_and_maybe_apply']


def body(items, dryrun=False):
    return SimpleNamespace(dryrun=dryrun, items=[SimpleNamespace(product_code=pc, rows_html=html) for pc, html in items])


def writes(conn): return [(q, p) for q, p in conn.calls if q.strip().startswith(('INSERT ', 'UPDATE ', 'DELETE '))]

class MallWriteGuardTests(unittest.TestCase):
    def test_guard_product_then_current_identity_then_sorted_contact_targets_then_all_supplier_scope(self):
        db = Database()
        with db.begin() as conn:
            self.assertEqual(lock_mall_write_scope(conn, 101, [12, 11, 13, 12], [12, 11, 12]), (11, 12, 13))
        self.assertEqual([q for q, _p in conn.calls], [_LOCK_PRODUCTS_SQL,
                         'SELECT product_code FROM products WHERE product_code=:pc', _CONTACT_LOCK_SQL, _SUPPLIER_SCOPE_SQL])
        self.assertEqual(conn.calls[0][1], {'codes': [101]})
        self.assertEqual(conn.calls[2][1], {'ids': [11, 12]})
        self.assertEqual(conn.calls[3][1], {'ids': [11, 12, 13]})
        self.assertEqual(writes(conn), [])
        self.assertIn('ORDER BY supplier_id FOR NO KEY UPDATE', _CONTACT_LOCK_SQL)
        self.assertNotIn('FOR UPDATE', _CONTACT_LOCK_SQL)

    def test_no_contact_target_has_no_extra_supplier_protection_lock(self):
        db = Database()
        with db.begin() as conn: lock_mall_write_scope(conn, 101, [11], [])
        self.assertNotIn(_CONTACT_LOCK_SQL, [q for q, _p in conn.calls])
        self.assertEqual([q for q, _p in conn.calls].count(_LOCK_PRODUCTS_SQL), 1)

    def test_missing_current_product_and_wrong_native_identity_fail_before_supplier_or_business_write(self):
        for current in (None, 102, True, '101'):
            db = Database(); db.overrides['SELECT product_code FROM products WHERE product_code=:pc'] = current
            with db.begin() as conn:
                with self.assertRaises(ProductScopeChanged): lock_mall_write_scope(conn, 101, [11], [11])
            self.assertEqual(writes(conn), [])
            self.assertEqual(len(conn.calls), 2)
        db = Database(); db.products.remove(101)
        with db.begin() as conn:
            with self.assertRaises(ProductScopeChanged): lock_mall_write_scope(conn, 101, [11], [11])
        self.assertEqual(len(conn.calls), 1)

    def test_supplier_missing_drift_native_type_or_scope_expansion_is_no_write_no_late_product_lock(self):
        for query, observed in [(_CONTACT_LOCK_SQL, []), (_CONTACT_LOCK_SQL, [12]),
                                (_CONTACT_LOCK_SQL, [True]), (_CONTACT_LOCK_SQL, [11, 11]),
                                (_CONTACT_LOCK_SQL, (11,)), (_SUPPLIER_SCOPE_SQL, []),
                                (_SUPPLIER_SCOPE_SQL, [11, 12])]:
            db = Database(); db.overrides[query] = observed
            with db.begin() as conn:
                with self.assertRaises(SupplierScopeChanged): lock_mall_write_scope(conn, 101, [11], [11])
            self.assertEqual(writes(conn), [])
            self.assertEqual([q for q, _p in conn.calls].count(_LOCK_PRODUCTS_SQL), 1)
        for supplier_ids, contacts in [([11], [12]), ([True], []), ([11], ['11'])]:
            db = Database()
            with db.begin() as conn:
                with self.assertRaises(SupplierScopeChanged): lock_mall_write_scope(conn, 101, supplier_ids, contacts)
            self.assertEqual(len(conn.calls), 2)

    def test_guard_raw_database_errors_propagate_unchanged(self):
        queries = [_LOCK_PRODUCTS_SQL, 'SELECT product_code FROM products WHERE product_code=:pc', _CONTACT_LOCK_SQL, _SUPPLIER_SCOPE_SQL]
        for target in queries:
            db = Database(); error = NativeFailure('private database diagnostic')
            db.fail = lambda q, p, c: error if q == target else None
            with self.assertRaises(NativeFailure) as caught:
                with db.begin() as conn: lock_mall_write_scope(conn, 101, [11], [11])
            self.assertIs(caught.exception, error)
            self.assertEqual(writes(conn), [])

    def test_http_reverse_contact_inputs_lock_ascending_but_write_in_original_row_order(self):
        for order in [(12, 11), (11, 12)]:
            db = Database(); db.html['a'] = [row(sid, idx=index) for index, sid in enumerate(order)] + [row(13, False)]
            result = http(db)['ingest'](body([(101, 'a')]))
            self.assertEqual(result['new_rows'], 3)
            self.assertEqual(len(db.transactions), 1)
            conn = db.transactions[0][0]
            self.assertEqual(conn.calls[0][0], _LOCK_PRODUCTS_SQL)
            contact = next(p for q, p in conn.calls if q == _CONTACT_LOCK_SQL)
            self.assertEqual(contact, {'ids': [11, 12]})
            expected_order = [('psp', order[0]), ('contact', order[0]), ('psp', order[1]), ('contact', order[1]), ('psp', 13)]
            self.assertEqual([('psp' if q.strip().startswith('INSERT ') else 'contact', p['s']) for q, p in writes(conn)], expected_order)
            self.assertTrue(all(p['fa'] == NOW for _q, p in writes(conn)))
            begin = next(i for i, e in enumerate(db.events) if e[0] == 'begin')
            self.assertLess(max(i for i, e in enumerate(db.events) if e[0] in ('parse', 'resolve')), begin)
            self.assertEqual(db.logs[0], ('mall_supplier_ingest', '101', {'rows_parsed': 3, 'new': 3, 'updated': 0, 'unchanged': 0}, 'supplier'))

    def test_http_existing_new_and_unchanged_psp_all_pass_guard_preserve_legacy_result(self):
        for legacy in (False, True):
            db = Database(); db.html['a'] = [row(11), row(12, False), row(13, False)]
            db.psp[(101, 11)] = {'cost_price': 9000, 'supply_state': '가능'}
            db.psp[(101, 12)] = {'cost_price': 10000, 'supply_state': '가능', 'mall_rank': 1,
                'rebate_pct': Decimal('1.250'), 'rebate_price': 125, 'order_price': None, 'mall_state_raw': '판매중'}
            result = http(db, legacy)['ingest'](body([(101, 'a')]))
            if not legacy: actual, state = result, deepcopy((db.psp, db.contacts, db.logs))
            else:
                self.assertEqual(actual, result)
                self.assertEqual(state, (db.psp, db.contacts, db.logs))
        self.assertEqual((actual['new_rows'], actual['updated_rows'], actual['unchanged_rows']), (1, 1, 1))

    def test_http_dryrun_and_empty_plan_keep_original_reads_statistics_no_guard_no_write(self):
        for dryrun, html_rows in [(True, [row(11), row(12)]), (False, [])]:
            outputs = []
            for legacy in (False, True):
                db = Database(); db.html['a'] = html_rows
                outputs.append(http(db, legacy)['ingest'](body([(101, 'a')], dryrun)))
                self.assertEqual(db.transactions, [])
                self.assertEqual(db.psp, {})
                self.assertEqual(db.logs, [])
                self.assertFalse(any(q == _LOCK_PRODUCTS_SQL for c in db.connections for q, p in c.calls))
            self.assertEqual(*outputs)

    def test_http_known_snapshot_is_revalidated_and_next_product_can_succeed(self):
        db = Database(); db.html = {'a': [row(11)], 'b': [row(12)]}
        db.after_product = lambda d, codes: d.products.discard(101) if codes == [101] else None
        result = http(db)['ingest'](body([(101, 'a'), (102, 'b')]))
        self.assertEqual(result['new_rows'], 1)
        self.assertEqual(result['errors'], [{'product_code': 101, 'error': 'ProductScopeChanged -- 처리하지 못했습니다'}])
        self.assertNotIn((101, 11), db.psp)
        self.assertIn((102, 12), db.psp)
        self.assertEqual([e is None for _c, e in db.transactions], [False, True])

    def test_http_missing_supplier_preflight_before_psp_and_no_contact_sid_still_checked(self):
        for contact in (False, True):
            db = Database(); db.html['a'] = [row(11, contact)]
            db.after_product = lambda d, codes: d.suppliers.discard(11)
            result = http(db)['ingest'](body([(101, 'a')]))
            self.assertEqual(result['new_rows'], 0)
            self.assertIn('SupplierScopeChanged', result['errors'][0]['error'])
            self.assertEqual(writes(db.transactions[0][0]), [])
            self.assertEqual(db.logs, [])

    def test_http_raw_psp_or_contact_failure_rolls_back_one_product_and_reports_only_type(self):
        for operation in ('INSERT INTO', 'UPDATE suppliers'):
            db = Database(); db.html = {'a': [row(11), row(12)], 'b': [row(13)]}
            error = NativeFailure('sensitive native SQL diagnostic')
            db.fail = lambda q, p, c: error if q.strip().startswith(operation) and p.get('s') == 12 else None
            result = http(db)['ingest'](body([(101, 'a'), (102, 'b')]))
            self.assertEqual(result['new_rows'], 1)
            self.assertEqual(result['errors'], [{'product_code': 101, 'error': 'NativeFailure -- 처리하지 못했습니다'}])
            self.assertNotIn((101, 11), db.psp)
            self.assertEqual(db.contacts[11], {'contact_phone': 'old'})
            self.assertIn((102, 13), db.psp)
            self.assertEqual(len(db.logs), 1)
            self.assertNotIn('sensitive', repr(result))

    def test_http_initial_absence_limits_and_unusable_unmatched_policy_unchanged(self):
        for legacy in (False, True):
            db = Database(); bad = row(11); bad['state'] = None
            unmatched = row(11); unmatched['contact_blob'] = 'unknown'
            excluded = row(11); excluded['contact_blob'] = '재고있음'
            db.html['a'] = [bad, unmatched, excluded]
            result = http(db, legacy)['ingest'](body([(999, 'missing'), (101, 'a')]))
            if not legacy: wanted = result
            else: self.assertEqual(wanted, result)
            self.assertEqual(db.transactions, [])
            with self.assertRaises(HTTPException) as caught:
                http(db, legacy)['ingest'](body([(101, 'x' * 300001)]))
            self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual((wanted['unusable_rows'], wanted['excluded_non_supplier'], wanted['unmatched_suppliers']), (1, 1, ['unknown']))

    def test_cli_each_psp_has_separate_transaction_and_preserved_stats_and_write_order(self):
        db = Database(); count = stats(); invoke = cli(db)
        for sid in (12, 11): invoke(db, True, 101, sid, 'Supplier' + str(sid), '담당자', row(sid), NOW, count)
        self.assertEqual(len(db.transactions), 2)
        self.assertEqual(count, {'psp_insert': 2, 'psp_update': 0, 'contact_filled': 2,
            'contact_would_fill': 0, 'contact_conflict': [(12, 'Supplier12', 'old', 'new'), (11, 'Supplier11', 'old', 'new')]})
        for (conn, error), sid in zip(db.transactions, (12, 11)):
            self.assertIsNone(error)
            self.assertEqual(conn.calls[0], (_LOCK_PRODUCTS_SQL, {'codes': [101]}))
            self.assertEqual(next(p for q, p in conn.calls if q == _CONTACT_LOCK_SQL), {'ids': [sid]})
            self.assertEqual([p['s'] for q, p in writes(conn)], [sid, sid])
            self.assertTrue(writes(conn)[0][0].strip().startswith('INSERT INTO'))
            self.assertTrue(writes(conn)[1][0].strip().startswith('UPDATE suppliers'))
        self.assertEqual(db.logs, [])

    def test_cli_dryrun_reads_and_insert_update_contact_conflict_stats_match_legacy(self):
        for existed in (False, True):
            counts, calls = [], []
            for legacy in (False, True):
                db = Database(); count = stats()
                if existed: db.psp[(101, 11)] = {}
                returned = cli(db, legacy)(db, False, 101, 11, 'Supplier11', '담당자', row(11), NOW, count)
                self.assertIsNone(returned)
                self.assertEqual(db.transactions, [])
                self.assertEqual(db.contacts[11], {'contact_phone': 'old'})
                counts.append(count); calls.append([c.calls for c in db.connections])
            self.assertEqual(*counts); self.assertEqual(*calls)
            self.assertEqual(counts[0]['psp_update' if existed else 'psp_insert'], 1)
            self.assertEqual(counts[0]['contact_would_fill'], 1)

    def test_cli_existing_psp_and_no_contact_apply_match_legacy_statistics_and_state(self):
        for contact in (False, True):
            outputs = []
            for legacy in (False, True):
                db = Database(); db.psp[(101, 11)] = {}; count = stats(); data = row(11, contact)
                cli(db, legacy)(db, True, 101, 11, 'Supplier11', '담당자' if contact else None, data, NOW, count)
                outputs.append((count, db.psp, db.contacts))
                if not legacy:
                    actual_queries = [q for q, p in db.transactions[0][0].calls]
                    self.assertEqual(_CONTACT_LOCK_SQL in actual_queries, contact)
            self.assertEqual(*outputs)

    def test_cli_scope_failure_and_native_errors_propagate_without_psp_contact_writes(self):
        for supplier_missing in (False, True):
            db = Database(); count = stats()
            if supplier_missing: db.after_product = lambda d, codes: d.suppliers.discard(11)
            else: db.products.discard(101)
            with self.assertRaises(SupplierScopeChanged if supplier_missing else ProductScopeChanged):
                cli(db)(db, True, 101, 11, 'Supplier11', '담당자', row(11), NOW, count)
            self.assertEqual(writes(db.transactions[0][0]), [])
            self.assertEqual(count['psp_insert'], 1)  # original accounting remains before write TX
        db = Database(); error = NativeFailure('private diagnostic')
        db.fail = lambda q, p, c: error if q == _CONTACT_LOCK_SQL else None
        with self.assertRaises(NativeFailure) as caught:
            cli(db)(db, True, 101, 11, 'Supplier11', '담당자', row(11), NOW, stats())
        self.assertIs(caught.exception, error)
        self.assertEqual(writes(db.transactions[0][0]), [])

    def test_unowned_top_level_ast_and_original_function_body_are_identical_except_guard(self):
        for rel, function in [('api/admin_mall_supplier.py', 'ingest'), ('tools/mall_supplier_fetch.py', '_plan_and_maybe_apply')]:
            tree = ast.parse((ROOT / rel).read_text(encoding='utf-8-sig'))
            rest = [n for n in tree.body if not (isinstance(n, ast.FunctionDef) and n.name == function)
                    and not (isinstance(n, ast.ImportFrom) and n.module in ('mall_supplier_write_guard', 'api.mall_supplier_write_guard'))]
            self.assertEqual(digest(ast.Module(body=rest, type_ignores=[])), BASELINE[rel]['rest'])
            if function == 'ingest': http(Database(), True)
            else: cli(Database(), True)
        for rel, wanted in PROTECTED.items(): self.assertEqual(hashlib.sha256((ROOT / rel).read_bytes()).hexdigest(), wanted)

    def test_selected_ast_does_not_execute_cli_or_app_imports_network_environment_or_cookie_code(self):
        db = Database(); env = http(db); invoke = cli(db)
        for forbidden in ('os', 'urllib', 'load_dotenv', 'ensure_utf8_console', 'fetch', 'main', '_cookie_header', 'current_operator', 'api.db'):
            self.assertNotIn(forbidden, env)
            self.assertNotIn(forbidden, invoke.__globals__)
        self.assertEqual(db.events, [])
        self.assertEqual(db.connections, [])

if __name__ == '__main__': unittest.main(verbosity=2)
