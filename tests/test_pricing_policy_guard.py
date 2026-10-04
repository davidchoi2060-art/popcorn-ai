"""Selected actual policy/reprice AST and fixed SQL; offline, no PG proof.

Original-body hashes are from the accepted source BEFORE these seven guard
insertions. Only those calls and routing/local import metadata are removed for
the paired original comparison. No operational DB/auth/router is imported.
Every queued SQL/parameter pair is checked and consumed; caller contexts are
mocks, not COMMIT receipts or actual lock/concurrency evidence.
"""
import ast
from copy import deepcopy
import hashlib
import importlib.abc
import json
from pathlib import Path
import sys
import unittest
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from api.admin_activity_log_core import log_action
from api.pricing import formula_text, resolve_margins, sale_from_purchase
from api.pricing_policy_guard_core import (
    lock_pricing_policy_shared, lock_pricing_policy_exclusive,
)
from api.pricing_write_guard_core import lock_products, ProductScopeChanged, _LOCK_PRODUCTS_SQL
from api.taxonomy import DISPLAY_LABELS, PART_LABELS, expand_display
from api.reprice_preview_expected import canonical_basis, make_expected, InvalidPreviewBasis, canonical_basis_v2, make_expected_v2
from api.reprice_basis_snapshot import read_basis, InvalidRepriceBasisSnapshot
from tests.test_reprice_write_lock_order import (
    u4_baseline, u4_module_baseline, receipt_core, prepare_test_operation,
    adapt_apply_model, TEST_CONTEXT, operation_request_fields,
)

ROOT = Path(__file__).resolve().parents[1]
KEY = {'namespace': 1347375171, 'key': 1}
SHARED = 'SELECT pg_catalog.pg_advisory_xact_lock_shared(:namespace,:key)'
EXCLUSIVE = 'SELECT pg_catalog.pg_advisory_xact_lock(:namespace,:key)'
OWNED = {
    'api/admin_engine_rules.py': {'save_pricing': '25c6878e718ef953c8119f16738623f1e8b964c19900025e1dd4a6519dd05231'},
    'api/admin_categories.py': {
        'create': 'b0d05471607d4a41bf5397bc95bbffff50ac5f31e1fcd9b3755d628706bf90a9',
        'patch': 'e7c0cdc1765a30dffcfe02f642014ea6b38f55e3000cfbd701a434378384ea98',
        'remove': '121e81e502adec0e3750f0fdb0f07ec4ba6fc0ef68debbf9a05a131555367e81',
        'set_margin': 'a464c61410cd74cfa0b7241986212fab056ce37d238a7d803d643ee7f4702c26',
    },
    'api/admin_reprice.py': {
        'preview': 'fe97871de485e2bda5ac0d6814dca3693799778677581eb79f8c8a447f9540a6',
        'apply': '23a550215e1a967bbf71b86e546f2751c4cbb63537768d2cc5c6e8da9d0a2d06',
    },
}
REST_AST = {
    'api/admin_engine_rules.py': '69f9f5287102f65fa640d75f471988d5a3a460d010291a7c9ca9cea25763f8f6',
    'api/admin_categories.py': '811e1ad0f91ef1dccbdfd1ae81893f5e551a87f2227c834f34d29362fe58c31f',
    'api/admin_reprice.py': 'a81767ef0346ed7bee92b631f09d0f8e06dcde360f8eeca838291bdf0aa1de8e',
}


class DenyOperationalImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in ('api.db', 'api.auth', 'api.main',
                        *(p.removesuffix('.py').replace('/', '.') for p in OWNED)):
            raise AssertionError('operational module import forbidden: ' + fullname)


_offline_active = 0


def deny_external_io(event, args):
    if _offline_active and (event.startswith('socket.') or event in ('subprocess.Popen', 'os.system')):
        raise AssertionError('offline tests forbid network/process execution')


sys.addaudithook(deny_external_io)


class OfflineTestCase(unittest.TestCase):
    def setUp(self):
        global _offline_active
        _offline_active += 1
        finder = DenyOperationalImports()
        sys.meta_path.insert(0, finder)
        self.addCleanup(self._stop_offline, finder)

    @staticmethod
    def _stop_offline(finder):
        global _offline_active
        sys.meta_path.remove(finder)
        _offline_active -= 1


def digest(node):
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


def original_body(path, node):
    out = u4_baseline(node) if path == 'api/admin_reprice.py' else deepcopy(node)
    tx = next(n for n in out.body if isinstance(n, ast.With))
    mode = 'shared' if path == 'api/admin_reprice.py' else 'exclusive'
    expected = ast.parse('lock_pricing_policy_' + mode + '(conn)').body[0]
    if ast.dump(tx.body[0]) != ast.dump(expected):
        raise AssertionError('guard must be the exact first caller-TX SQL call')
    del tx.body[0]
    if digest(out) != OWNED[path][node.name]:
        raise AssertionError('business body changed beyond one guard insertion')
    return out


class LocalImports(ast.NodeTransformer):
    def visit_ImportFrom(self, node):
        # Actual actor lookup and actual log AST supplied below, no app import.
        return None


def selected(path, names, env, original=False):
    nodes, found = [], set()
    for node in ast.parse((ROOT / path).read_text(encoding='utf-8')).body:
        ids = {node.name} if isinstance(node, (ast.FunctionDef, ast.ClassDef)) else (
            {n.id for n in node.targets if isinstance(n, ast.Name)} if isinstance(node, ast.Assign) else set())
        if ids & names:
            out = original_body(path, node) if original and isinstance(node, ast.FunctionDef) and node.name in OWNED.get(path, {}) else deepcopy(node)
            if isinstance(out, ast.FunctionDef):
                out.decorator_list = []
                out = LocalImports().visit(out)
            nodes.append(out)
            found |= ids & names
    if found != names:
        raise AssertionError('missing actual AST: ' + str(names - found))
    exec(compile(ast.fix_missing_locations(ast.Module(nodes, [])), path, 'exec'), env)


class Result:
    def __init__(self, value=None): self.value = deepcopy(value)
    def mappings(self): return self
    def scalars(self): return self
    def first(self): return deepcopy(self.value)
    def scalar(self): return deepcopy(self.value)
    def scalar_one(self): return deepcopy(self.value)
    def one(self): return deepcopy(self.value)
    def all(self): return deepcopy(self.value)
    def __iter__(self): return iter(deepcopy(self.value))


class Connection:
    def __init__(self, steps):
        self.steps, self.calls = list(steps), []
        self.operation_calls, self.operation_identity, self.receipt_row = [], None, None
        self.basis_projections,self.basis_env={},None
    def execute(self, statement, params=None):
        q = ' '.join(str(statement).split())
        identity = self.operation_identity
        if q == receipt_core.OPERATION_LOCK_SQL and params.get('namespace') == receipt_core.OPERATION_NAMESPACE:
            if params != receipt_core.operation_lock_params(identity):raise AssertionError('operation lock params')
            self.operation_calls.append((q,deepcopy(params)));return Result(None)
        if q == receipt_core.LOOKUP_SQL:
            if params != {k:identity[k] for k in ('environment','operation_id')}:raise AssertionError('lookup params')
            self.operation_calls.append((q,deepcopy(params)));return Result(self.receipt_row)
        if q == receipt_core.INSERT_SQL:
            row = deepcopy(params);row['result'] = json.loads(row['result']);row['response_body'] = json.loads(row['response_body'])
            receipt_core.operation_record(row,expected=identity)
            if self.receipt_row is not None:raise AssertionError('unexpected duplicate receipt insert')
            self.receipt_row = row;self.operation_calls.append((q,deepcopy(params)));return Result(None)
        if q.startswith('WITH scoped_products AS'):
            if len(self.steps)<4:raise AssertionError('four original native basis input steps required')
            read_steps=self.steps[:4];del self.steps[:4]
            projection=Connection(read_steps)
            env=self.basis_env
            fee,margin=env['_settings'](projection)
            env['_margin_map'](projection,margin)
            scope=('live' if 'p.stock_qty > 0' in q else 'selling' if "p.status = '판매중'" in q else 'all')
            rows=env['_rows'](projection,scope);projection.complete()
            self.basis_projections[len(self.calls)]=projection.calls
            self.calls.append((q,deepcopy(params)))
            payload={'products':[dict(r,pricing_basis_revision=r['product_code']) for r in rows],
                     'settings':{'card_fee_rate':fee,'margin_rate':margin},
                     'nodes':[list(r) for r in read_steps[1][2]],
                     'margins':[list(r) for r in read_steps[2][2]],
                     'policy_tokens':[{'singleton':1,'revision':11}]}
            return Result(json.dumps(payload))
        if not self.steps:
            raise AssertionError('unplanned SQL: ' + q)
        prefix, wanted, result = self.steps.pop(0)
        if not q.startswith(prefix) or params != wanted:
            raise AssertionError('SQL/params mismatch: ' + repr((q, params, prefix, wanted)))
        self.calls.append((q, deepcopy(params)))
        if isinstance(result, BaseException): raise result
        return Result(result)
    def complete(self):
        if self.steps: raise AssertionError('unconsumed actual SQL steps: ' + str(self.steps))


class Context:
    def __init__(self, engine, writing): self.engine, self.writing = engine, writing
    def __enter__(self):
        self.engine.events.append('begin' if self.writing else 'connect')
        return self.engine.conn
    def __exit__(self, typ, value, trace):
        self.engine.events.append('rollback_mock' if typ and self.writing else
            'commit_mock' if self.writing else 'readonly_close_mock')
        return False


class Engine:
    def __init__(self, conn): self.conn, self.events, self.actor_events = conn, [], []
    def execution_options(self, **options):
        if options != {'isolation_level':'READ COMMITTED'}:raise AssertionError('exact isolation required')
        return self
    def begin(self): return Context(self, True)
    def connect(self): return Context(self, False)


def runtime(path, conn, role='owner', original=False):
    engine = Engine(conn)
    def operator():
        engine.actor_events.append('role_lookup')
        return {'role': role, 'operator_id': 21}
    def actor():
        engine.actor_events.append('log_actor_lookup')
        return 21
    def prepare(body, operator):
        identity = prepare_test_operation(body, operator);conn.operation_identity = identity;return identity
    env = dict(text=text, json=json, HTTPException=HTTPException, BaseModel=BaseModel,
        ConfigDict=ConfigDict, Field=Field, Literal=Literal,
        canonical_basis=canonical_basis, make_expected=make_expected, InvalidPreviewBasis=InvalidPreviewBasis,
        canonical_basis_v2=canonical_basis_v2, make_expected_v2=make_expected_v2,
        read_basis=read_basis, InvalidRepriceBasisSnapshot=InvalidRepriceBasisSnapshot,
        engine=engine, current_operator=operator, current_operator_id=actor,
        _log_core=log_action, lock_pricing_policy_shared=lock_pricing_policy_shared,
        lock_pricing_policy_exclusive=lock_pricing_policy_exclusive,
        lock_products=lock_products, ProductScopeChanged=ProductScopeChanged,
        formula_text=formula_text, resolve_margins=resolve_margins,
        sale_from_purchase=sale_from_purchase, DISPLAY_LABELS=DISPLAY_LABELS,
        PART_LABELS=PART_LABELS, expand_display=expand_display,
        MAX_SAFE_INTEGER=receipt_core.MAX_SAFE_INTEGER, UUID_PATTERN=receipt_core.UUID_PATTERN,
        prepare_reprice_operation=prepare, lock_operation=receipt_core.lock_operation,
        lookup_operation=receipt_core.lookup_operation, operation_record=receipt_core.operation_record,
        store_operation=receipt_core.store_operation, ReceiptUnavailable=receipt_core.ReceiptUnavailable,
        OperationConflict=receipt_core.OperationConflict, PrewriteRejected=receipt_core.PrewriteRejected)
    selected('api/admin_orders.py', {'_log'}, env)
    if path == 'api/admin_engine_rules.py':
        names = {'save_pricing', 'PricingBody'}
    elif path == 'api/admin_categories.py':
        names = {'MAX_NAME', '_operator', '_clean_name', '_clean_types', '_rows', '_descendants',
            '_subtree_products', 'CreateBody', 'PatchBody', 'MarginBody', 'create', 'patch', 'remove', 'set_margin'}
    else:
        selected('api/admin_price_import.py', {'_settings'}, env)
        names = {'MAX_APPLY', 'OUTLIER_X', 'SCOPES', '_owner', '_rows', '_margin_map', '_classify',
            '_summary', '_selected_reprice_rows', 'PreviewExpected', 'RepriceOperationContext', 'ApplyBody', 'preview', 'apply',
            '_preview_plan', '_require_expected'}
        if not original:names |= {'_read_revision_basis','_preview_plan_v2'}
    selected(path, names, env, original)
    if path == 'api/admin_reprice.py':
        adapt_apply_model(env);conn.basis_env=env
    return env


def policy(mode='exclusive', result=None):
    return (EXCLUSIVE if mode == 'exclusive' else SHARED, deepcopy(KEY), result)


def log_step(action, target, detail, kind, result=91):
    return ('INSERT INTO admin_operator_activity_logs',
            {'op': 21, 'a': action, 'k': kind, 't': target, 'd': json.dumps(detail)}, result)


def cat(cid=8, parent=7, name='child'):
    return dict(category_id=cid, parent_id=parent, name=name, sort_order=0, is_visible=True,
                allowed_part_types=None, created_at=None, updated_at=None, n=0, n_sub=3, n_stock=0)


def reprice_reads(locked=(), sale=11000):
    row = dict(product_code=101, product_name='policy product', part_type='GPU', purchase_price=12000,
        sale_price=sale, status='판매중', stock_qty=7, locked_fields=list(locked), category_id=8)
    return [
        ('SELECT card_fee_rate, margin_rate FROM pricing_settings', None, (.02, .03)),
        ('SELECT category_id, parent_id FROM categories', None, [(7, None), (8, 7)]),
        ('SELECT category_id, margin_rate FROM category_margin_policies', None, [(7, .05)]),
        ('SELECT p.product_code', None, [row]),
    ]


def reprice_expected(env, scope='live', locked=(), sale=11000):
    """Use literal queued native inputs and actual current canonical/classify helper."""
    steps = reprice_reads(locked, sale)
    fee, margin = steps[0][2]
    mmap = {cid: m for cid, (m, _) in resolve_margins(steps[1][2], dict(steps[2][2]), margin).items()}
    if '_preview_plan_v2' not in env:return env['_preview_plan'](steps[3][2], scope, fee, margin, mmap)[1]
    snapshot={'product_revisions':{r['product_code']:r['product_code'] for r in steps[3][2]},'policy_revision':11}
    return env['_preview_plan_v2'](steps[3][2],scope,fee,margin,mmap,snapshot)[1]


def reprice_body(env, *, sale=11000, **fields):
    scope = fields['scope'] if fields['scope'] in env['SCOPES'] else 'live'
    return env['ApplyBody'](**fields, expected=reprice_expected(env, scope, sale=sale))


class GuardTests(OfflineTestCase):
    def test_fixed_two_int_key_both_exact_statements_one_execute_none_return(self):
        self.assertEqual(KEY['namespace'], int.from_bytes(b'POPC', 'big'))
        for fn, q in ((lock_pricing_policy_shared, SHARED), (lock_pricing_policy_exclusive, EXCLUSIVE)):
            conn = Connection([(q, KEY, None)])
            self.assertIsNone(fn(conn))
            self.assertEqual(conn.calls, [(q, KEY)])
            conn.complete()

    def test_helper_does_not_leak_mutable_parameter_key(self):
        class MutatingConnection:
            def execute(self, statement, params):
                self.observed = deepcopy(params)
                params['namespace'], params['key'] = 0, 99
        for fn in (lock_pricing_policy_shared, lock_pricing_policy_exclusive) * 2:
            conn = MutatingConnection(); fn(conn)
            self.assertEqual(conn.observed, KEY)

    def test_helper_propagates_identical_exception_no_tx_or_retry(self):
        error = RuntimeError('native policy lock failure')
        for fn, q in ((lock_pricing_policy_shared, SHARED), (lock_pricing_policy_exclusive, EXCLUSIVE)):
            conn = Connection([(q, KEY, error)])
            with self.assertRaises(RuntimeError) as got: fn(conn)
            self.assertIs(got.exception, error)
            self.assertEqual(len(conn.calls), 1)
            conn.complete()

    def test_seven_body_baselines_and_all_nonowned_ast_unchanged(self):
        for path, names in OWNED.items():
            tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
            for node in tree.body:
                if isinstance(node, ast.FunctionDef) and node.name in names:
                    original_body(path, node)
            if path == 'api/admin_reprice.py':
                tree = u4_module_baseline(tree)
            rest = [n for n in tree.body if not (
                isinstance(n, ast.FunctionDef) and n.name in names) and not (
                isinstance(n, ast.ImportFrom) and n.module == 'pricing_policy_guard_core')]
            self.assertEqual(digest(ast.Module(rest, [])), REST_AST[path], path)

    def test_helper_imports_only_text_no_session_try_unlock_upgrade_or_engine(self):
        tree = ast.parse((ROOT / 'api/pricing_policy_guard_core.py').read_text(encoding='utf-8'))
        imports = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual([ast.unparse(n) for n in imports], ['from sqlalchemy import text'])
        self.assertFalse(any(isinstance(n, (ast.With, ast.Try, ast.AsyncFunctionDef)) for n in ast.walk(tree)))
        for n in tree.body:
            if isinstance(n, ast.FunctionDef):
                self.assertEqual(len(n.args.args), 1)
                self.assertEqual(n.args.args[0].arg, 'conn')
                self.assertEqual(len([x for x in ast.walk(n) if isinstance(x, ast.Call) and
                    isinstance(x.func, ast.Attribute) and x.func.attr == 'execute']), 1)

    def test_every_caller_lock_failure_rolls_back_or_closes_original_context(self):
        calls = [('api/admin_engine_rules.py', 'save_pricing', 'PricingBody', {'card_fee_rate': .02, 'margin_rate': .03}),
            ('api/admin_categories.py', 'create', 'CreateBody', {'name': 'new'}),
            ('api/admin_categories.py', 'patch', 'PatchBody', {'name': 'new'}),
            ('api/admin_categories.py', 'remove', None, {}),
            ('api/admin_categories.py', 'set_margin', 'MarginBody', {'margin_rate': .05}),
            ('api/admin_reprice.py', 'apply', 'ApplyBody', {'scope': 'live', 'expect_changed': 1}),
            ('api/admin_reprice.py', 'preview', None, {})]
        for path, name, body_name, values in calls:
            with self.subTest(name=name):
                error = RuntimeError('policy SQL failure')
                mode = 'shared' if path == 'api/admin_reprice.py' else 'exclusive'
                conn = Connection([policy(mode, error)]); env = runtime(path, conn)
                args = [8] if name in ('patch', 'remove', 'set_margin') else []
                if body_name:
                    args.append(reprice_body(env, **values) if path == 'api/admin_reprice.py' else env[body_name](**values))
                with self.assertRaises(RuntimeError) as got: env[name](*args)
                self.assertIs(got.exception, error)
                self.assertEqual(env['engine'].events, ['connect', 'readonly_close_mock'] if name == 'preview' else ['begin', 'rollback_mock'])
                conn.complete()

    def test_original_role_gates_precede_any_tx_for_all_writers_and_apply(self):
        for path, name, body_name, values in [
            ('api/admin_engine_rules.py', 'save_pricing', 'PricingBody', {'card_fee_rate': .02, 'margin_rate': .03}),
            ('api/admin_categories.py', 'create', 'CreateBody', {'name': 'new'}),
            ('api/admin_categories.py', 'patch', 'PatchBody', {'name': 'new'}),
            ('api/admin_categories.py', 'remove', None, {}),
            ('api/admin_categories.py', 'set_margin', 'MarginBody', {'margin_rate': .05}),
            ('api/admin_reprice.py', 'apply', 'ApplyBody', {'scope': 'live', 'expect_changed': 1})]:
            conn = Connection([]); env = runtime(path, conn, role='viewer')
            args = [8] if name in ('patch', 'remove', 'set_margin') else []
            if body_name:
                args.append(reprice_body(env, **values) if path == 'api/admin_reprice.py' else env[body_name](**values))
            with self.assertRaises(HTTPException) as got: env[name](*args)
            self.assertEqual(got.exception.status_code, 403)
            self.assertEqual(env['engine'].events, [])
            self.assertEqual(env['engine'].actor_events, ['role_lookup'])
            conn.complete()


class WriterTests(OfflineTestCase):
    def test_global_save_empty_policy_append_log_actor_count_and_original_response(self):
        path = 'api/admin_engine_rules.py'
        detail = {'from': {'card_fee_rate': None, 'margin_rate': None},
                  'to': {'card_fee_rate': .02, 'margin_rate': .03}}
        steps = [('SELECT card_fee_rate, margin_rate FROM pricing_settings', None, None),
            ('INSERT INTO pricing_settings', {'f': .02, 'm': .03, 'by': 21}, None),
            log_step('pricing_settings', '전역', detail, 'price'),
            ('SELECT count(*) FROM products WHERE purchase_price IS NOT NULL', None, 3)]
        results = []
        for original in (True, False):
            conn = Connection(([] if original else [policy()]) + steps)
            env = runtime(path, conn, original=original)
            results.append(env['save_pricing'](env['PricingBody'](card_fee_rate=.02, margin_rate=.03)))
            self.assertEqual(env['engine'].events, ['begin', 'commit_mock'])
            self.assertEqual(env['engine'].actor_events, ['role_lookup', 'log_actor_lookup'])
            self.assertFalse(any(q.startswith('UPDATE products') for q, p in conn.calls))
            conn.complete()
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1]['affected_candidates'], 3)
        self.assertEqual(results[1]['undo_id'], 91)

    def test_global_six_decimal_same_value_error_remains_after_exclusive_guard(self):
        conn = Connection([policy(), ('SELECT card_fee_rate, margin_rate FROM pricing_settings', None,
                                     {'card_fee_rate': .02, 'margin_rate': .03})])
        env = runtime('api/admin_engine_rules.py', conn)
        with self.assertRaises(HTTPException) as got:
            env['save_pricing'](env['PricingBody'](card_fee_rate=.020000000000000004, margin_rate=.030000000000000002))
        self.assertEqual((got.exception.status_code, got.exception.detail), (400, '현재 값과 같습니다 — 바뀐 것이 없습니다'))
        self.assertEqual(env['engine'].events, ['begin', 'rollback_mock'])
        conn.complete()

    def test_invalid_global_rate_and_category_margin_before_tx_unchanged(self):
        for rate in (-.01, 1, float('nan')):
            conn = Connection([]); env = runtime('api/admin_engine_rules.py', conn)
            with self.assertRaises(HTTPException) as got:
                env['save_pricing'](env['PricingBody'](card_fee_rate=rate, margin_rate=.03))
            self.assertEqual(got.exception.status_code, 400); self.assertEqual(env['engine'].events, [])
            conn = Connection([]); env = runtime('api/admin_categories.py', conn)
            with self.assertRaises(HTTPException) as got:
                env['set_margin'](8, env['MarginBody'](margin_rate=rate))
            self.assertEqual(got.exception.status_code, 400); self.assertEqual(env['engine'].events, [])

    def test_create_operator_allowed_cleans_types_and_preserves_log_return(self):
        types = ['COOLER_CPU_AIO', 'COOLER_CPU_AIR']
        conn = Connection([policy(),
            ('SELECT 1 FROM categories WHERE category_id=:i', {'i': 7}, (1,)),
            ('SELECT 1 FROM categories WHERE name=:n', {'n': 'new', 'p': 7}, None),
            ('INSERT INTO categories', {'p': 7, 'n': 'new', 's': 0, 't': json.dumps(types)}, 701),
            log_step('카테고리 추가', '701', {'name': 'new', 'parent_id': 7}, 'category')])
        env = runtime('api/admin_categories.py', conn, role='operator')
        self.assertEqual(env['create'](env['CreateBody'](name=' new ', parent_id=7, allowed_part_types=['COOLER'])),
                         {'category_id': 701, 'verdict': "'new' 카테고리를 추가했습니다"})
        self.assertEqual(env['engine'].events, ['begin', 'commit_mock']); conn.complete()

    def test_create_missing_parent_and_duplicate_original_404_409(self):
        for exists, dup, expected in ((None, None, 404), ((1,), (1,), 409)):
            steps = [policy(), ('SELECT 1 FROM categories WHERE category_id=:i', {'i': 7}, exists)]
            if exists: steps += [('SELECT 1 FROM categories WHERE name=:n', {'n': 'new', 'p': 7}, dup)]
            conn = Connection(steps); env = runtime('api/admin_categories.py', conn)
            with self.assertRaises(HTTPException) as got: env['create'](env['CreateBody'](name='new', parent_id=7))
            self.assertEqual(got.exception.status_code, expected); conn.complete()

    def test_patch_cycle_self_or_descendant_rejected_from_current_tree(self):
        for parent in (7, 8):
            conn = Connection([policy(), ('SELECT c.category_id', None, [cat(7, None, 'root'), cat()])])
            env = runtime('api/admin_categories.py', conn)
            with self.assertRaises(HTTPException) as got: env['patch'](7, env['PatchBody'](parent_id=parent))
            self.assertEqual((got.exception.status_code, got.exception.detail),
                (400, '자기 자신이나 하위 카테고리 밑으로는 옮길 수 없습니다'))
            conn.complete()

    def test_patch_parent_move_exact_before_log_return_without_price_updates(self):
        conn = Connection([policy(), ('SELECT c.category_id', None, [cat(), cat(7, None, 'root'), cat(9, None, 'other')]),
            ('SELECT 1 FROM categories WHERE name=:n', {'n': 'child', 'p': 9, 'i': 8}, None),
            ('UPDATE categories SET parent_id=:p, updated_at=now()', {'i': 8, 'p': 9}, None),
            log_step('카테고리 수정', '8', {'from': {'parent_id': 7}, 'to': {'parent_id': 9}}, 'category')])
        env = runtime('api/admin_categories.py', conn)
        self.assertEqual(env['patch'](8, env['PatchBody'](parent_id=9)),
                         {'verdict': "'child' 카테고리를 수정했습니다", 'changed': ['parent_id']})
        conn.complete()

    def test_patch_no_changes_remains400(self):
        conn = Connection([policy(), ('SELECT c.category_id', None, [cat()])])
        env = runtime('api/admin_categories.py', conn)
        with self.assertRaises(HTTPException) as got: env['patch'](8, env['PatchBody']())
        self.assertEqual((got.exception.status_code, got.exception.detail), (400, '바뀐 내용이 없습니다'))
        conn.complete()

    def test_remove_child_and_product_restrictions_preserve409(self):
        for kids, products, message in ((1, None, '하위 카테고리 1개를 먼저 옮기거나 지우세요'),
                                       (0, 3, '상품 3건이 이 카테고리에 있습니다 — 먼저 옮기세요')):
            steps = [policy(), ('SELECT name FROM categories', {'i': 8}, {'name': 'child'}),
                     ('SELECT count(*) FROM categories WHERE parent_id=:i', {'i': 8}, kids)]
            if not kids: steps += [('SELECT count(*) FROM products WHERE category_id=:i', {'i': 8}, products)]
            conn = Connection(steps); env = runtime('api/admin_categories.py', conn)
            with self.assertRaises(HTTPException) as got: env['remove'](8)
            self.assertEqual((got.exception.status_code, got.exception.detail), (409, message)); conn.complete()

    def test_remove_success_preserves_delete_and_original_log(self):
        conn = Connection([policy(), ('SELECT name FROM categories', {'i': 8}, {'name': 'child'}),
            ('SELECT count(*) FROM categories WHERE parent_id=:i', {'i': 8}, 0),
            ('SELECT count(*) FROM products WHERE category_id=:i', {'i': 8}, 0),
            ('DELETE FROM categories WHERE category_id=:i', {'i': 8}, None),
            log_step('카테고리 삭제', '8', {'name': 'child'}, 'category')])
        env = runtime('api/admin_categories.py', conn)
        self.assertEqual(env['remove'](8), {'verdict': "'child' 카테고리를 지웠습니다"}); conn.complete()

    def test_margin_upsert_empty_or_same_rate_keeps_original_policy_not_noop(self):
        for before in (None, .05):
            conn = Connection([policy(), ('SELECT name FROM categories', {'i': 8}, {'name': 'child'}),
                ('SELECT margin_rate FROM category_margin_policies', {'i': 8}, before),
                ('INSERT INTO category_margin_policies', {'i': 8, 'm': .05}, None),
                ('SELECT count(*) FROM products WHERE category_id IN', {'i': 8}, 3),
                log_step('카테고리 마진', '8', {'name': 'child', 'from': before, 'to': .05, 'products': 3}, 'price')])
            env = runtime('api/admin_categories.py', conn, role='operator')
            result = env['set_margin'](8, env['MarginBody'](margin_rate=.05))
            self.assertEqual(result['verdict'], "'child' 마진을 5.0%로 정했습니다")
            self.assertEqual(result['products'], 3)
            self.assertIn('판매가는 지금 바뀌지 않습니다', result['note']); conn.complete()

    def test_margin_delete_direct_override_preserves_ancestor_fallback_return(self):
        conn = Connection([policy(), ('SELECT name FROM categories', {'i': 8}, {'name': 'child'}),
            ('SELECT margin_rate FROM category_margin_policies', {'i': 8}, .05),
            ('DELETE FROM category_margin_policies WHERE category_id=:i', {'i': 8}, None),
            ('SELECT count(*) FROM products WHERE category_id IN', {'i': 8}, 3),
            log_step('카테고리 마진', '8', {'name': 'child', 'from': .05, 'to': None, 'products': 3}, 'price')])
        env = runtime('api/admin_categories.py', conn)
        result = env['set_margin'](8, env['MarginBody']())
        self.assertEqual(result['verdict'], "'child' 마진을 지웠습니다 — 상위 분류를 따릅니다")
        self.assertEqual(resolve_margins([(7, None), (8, 7)], {7: .03}, .02)[8], (.03, 7)); conn.complete()

    def test_margin_delete_missing_override_remains400(self):
        conn = Connection([policy(), ('SELECT name FROM categories', {'i': 8}, {'name': 'child'}),
                           ('SELECT margin_rate FROM category_margin_policies', {'i': 8}, None)])
        env = runtime('api/admin_categories.py', conn)
        with self.assertRaises(HTTPException) as got: env['set_margin'](8, env['MarginBody']())
        self.assertEqual((got.exception.status_code, got.exception.detail), (400, '이 분류에 직접 걸린 마진이 없습니다')); conn.complete()

    def test_original_log_failure_propagates_after_business_sql_caller_rollback(self):
        error = RuntimeError('native activity log failure')
        conn = Connection([policy(), ('SELECT name FROM categories', {'i': 8}, {'name': 'child'}),
            ('SELECT margin_rate FROM category_margin_policies', {'i': 8}, None),
            ('INSERT INTO category_margin_policies', {'i': 8, 'm': .05}, None),
            ('SELECT count(*) FROM products WHERE category_id IN', {'i': 8}, 3),
            log_step('카테고리 마진', '8', {'name': 'child', 'from': None, 'to': .05, 'products': 3}, 'price', error)])
        env = runtime('api/admin_categories.py', conn)
        with self.assertRaises(RuntimeError) as got: env['set_margin'](8, env['MarginBody'](margin_rate=.05))
        self.assertIs(got.exception, error); self.assertEqual(env['engine'].events, ['begin', 'rollback_mock']); conn.complete()


class RepriceTests(OfflineTestCase):
    def test_preview_shared_first_readonly_context_and_exact_original_response(self):
        results = []
        for original in (True, False):
            conn = Connection(([] if original else [policy('shared')]) + reprice_reads())
            env = runtime('api/admin_reprice.py', conn, role='viewer', original=original)
            results.append(env['preview']('live'))
            self.assertEqual(env['engine'].events, ['connect', 'readonly_close_mock'])
            self.assertEqual(env['engine'].actor_events, [])
            self.assertFalse(any('FOR UPDATE' in q for q, p in conn.calls)); conn.complete()
        self.assertEqual(results[1].pop('expected'), reprice_expected(env))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1]['margins_used'], [{'margin_rate': .05, 'count': 1}])
        self.assertEqual(results[1]['examples']['up'][0]['proposed'], 13000)

    def test_apply_shared_before_products_exact_original_sql_and_response(self):
        detail = {'scope': 'live', 'scope_label': '판매중 · 재고 있음', 'card_fee_rate': .02,
            'margin_rate': .03, 'margins_used': {'0.05': 1}, 'changed': 1, 'up': 1, 'down': 0,
            'note': 'same note', 'before': [{'pc': 101, 'sale': 11000}]}
        steps = reprice_reads() + [(_LOCK_PRODUCTS_SQL, {'codes': [101]}, [101])] + reprice_reads() + [
            ('UPDATE products SET sale_price=:v, updated_at=now()', {'v': 13000, 'pc': 101}, None),
            ('INSERT INTO product_price_history', {'pc': 101, 'o': 11000, 'n': 13000, 'op': 21}, None),
            log_step('판매가 재산정', 'live', detail, 'price')]
        results, calls = [], []
        for original in (True, False):
            exact_steps = deepcopy(steps)
            if not original:
                after_detail = deepcopy(detail)
                after_detail['before'][0].update(after_sale=13000, after_locked_fields=[])
                exact_steps[-1] = log_step('판매가 재산정', 'live', after_detail, 'price')
            conn = Connection(([] if original else [policy('shared')]) + exact_steps)
            env = runtime('api/admin_reprice.py', conn, original=original)
            results.append(env['apply'](reprice_body(env, scope='live', expect_changed=1, note=' same note ')))
            self.assertEqual(env['engine'].events, ['begin', 'commit_mock'])
            projected_calls=[]
            for index,call in enumerate(conn.calls):projected_calls.extend(conn.basis_projections.get(index,[call]))
            calls.append(projected_calls); conn.complete()
        self.assertEqual(results[0], {k:results[1][k] for k in results[0]})
        self.assertEqual(set(results[1]),set(results[0])|{'operation_receipt'})
        projected = deepcopy(calls[1][1:])
        logged = json.loads(projected[-1][1]['d'])
        self.assertEqual(logged['before'], [{'pc':101,'sale':11000,'after_sale':13000,'after_locked_fields':[]}])
        del logged['before'][0]['after_sale']; del logged['before'][0]['after_locked_fields']
        projected[-1][1]['d'] = json.dumps(logged)
        self.assertEqual(calls[0], projected)
        self.assertEqual(calls[1][0], (SHARED, KEY))
        product_index = next(i for i, (q, p) in enumerate(calls[1]) if q == _LOCK_PRODUCTS_SQL)
        self.assertGreater(product_index, 0)

    def test_apply_preserves_product_raw_basis_drift409_and_no_writes(self):
        conn = Connection([policy('shared')] + reprice_reads() + [(_LOCK_PRODUCTS_SQL, {'codes': [101]}, [101])] + reprice_reads(('market_price',)))
        env = runtime('api/admin_reprice.py', conn)
        with self.assertRaises(HTTPException) as got: env['apply'](reprice_body(env, scope='live', expect_changed=1))
        self.assertEqual((got.exception.status_code, got.exception.detail),
            (409, '재산정 대상 또는 계산 근거가 변경되었습니다 — 미리보기를 다시 확인하세요'))
        self.assertEqual(env['engine'].events, ['begin', 'commit_mock'])
        self.assertEqual(conn.receipt_row['state'],'rejected')
        self.assertTrue(all(q.startswith(('SELECT ','WITH scoped_products AS')) for q, p in conn.calls)); conn.complete()

    def test_apply_original_no_targets400_before_product_lock(self):
        conn = Connection([policy('shared')] + reprice_reads(sale=13000))
        env = runtime('api/admin_reprice.py', conn)
        with self.assertRaises(HTTPException) as got: env['apply'](reprice_body(env, scope='live', expect_changed=0, sale=13000))
        self.assertEqual(got.exception.status_code, 400); conn.complete()

    def test_invalid_reprice_scopes_preserve_no_tx_or_lock(self):
        for name in ('preview', 'apply'):
            conn = Connection([]); env = runtime('api/admin_reprice.py', conn)
            with self.assertRaises(HTTPException) as got:
                env[name]('other') if name == 'preview' else env[name](reprice_body(env, scope='other', expect_changed=1))
            self.assertEqual((got.exception.status_code, got.exception.detail), (400, '알 수 없는 범위입니다'))
            self.assertEqual(env['engine'].events, []); conn.complete()


if __name__ == '__main__':
    unittest.main()
