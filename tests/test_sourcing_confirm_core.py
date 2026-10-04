"""No-connection sourcing extraction checks, not PostgreSQL writer fixtures."""

import ast
import copy
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

from fastapi import HTTPException
from sqlalchemy.exc import OperationalError


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "api" / "sourcing_confirm_core.py"
ADAPTER = ROOT / "api" / "admin_sourcing.py"
SPEC = importlib.util.spec_from_file_location("api.sourcing_core_test", MODULE)
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)


class FakeResult:
    def __init__(self, value):
        self.value = value

    def mappings(self):
        return self

    def first(self):
        return self.value

    def one(self):
        return self.value

    def all(self):
        return self.value

    def scalar(self):
        return self.value

    def scalar_one(self):
        return self.value

    def scalars(self):
        return self


class FakeConnection:
    """Only execute exists: using begin/commit/rollback/connect is a test failure."""

    def __init__(self, fixture):
        self.fixture = fixture
        self.calls = []
        self.fail_index = None
        self.failure = RuntimeError("injected SQL failure")

    def execute(self, statement, params):
        index = len(self.calls)
        sql = str(statement)
        self.calls.append((sql, copy.deepcopy(params)))
        self.fixture.trace.append(("sql", index))
        if index == self.fail_index:
            raise self.failure
        return FakeResult(copy.deepcopy(self.fixture.values[index]))


class Fixture:
    def __init__(self, *, quote=None, missing_quote=False, psp=(148000, "불가"),
                 ready=True, siblings=None, batch_status="진행", before=None, after=None,
                 reprice_result=None):
        self.trace = []
        self.quote = dict(quote_id=77, product_code=101, supplier_id=11, price=142000,
                          status="회신", batch_id=201, sku="P-101")
        self.quote.update(quote or {})
        if missing_quote:
            self.quote = None
        self.psp = psp
        self.before = before or {"purchase_price": 148000, "sale_price": 160000}
        self.after = after or {"purchase_price": 142000, "sale_price": 155000}
        self.siblings = siblings if siblings is not None else [
            {"quote_id": 78, "status": "요청"}, {"quote_id": 79, "status": "회신"}]
        self.batch_status = batch_status
        self.ready = ready
        self.rp = reprice_result or {
            "purchase_changed": True, "sale_changed": True, "sale_locked": False}
        related = [dict(self.quote, **row) for row in self.siblings] if self.quote is not None else []
        if self.quote is not None:
            related.append(self.quote)
        related.sort(key=lambda row: row["quote_id"])
        scope = [{k: row[k] for k in ("quote_id", "product_code", "batch_id")} for row in related]
        self.values = [self.quote, scope, [101], self.batch_status, related, scope, "P-101",
                       self.psp, self.before, None, self.after, None, None, None]
        self.conn = FakeConnection(self)
        self.log_calls = []
        self.callback_failure = None
        self.failure = RuntimeError("injected callback failure")

    def check_callback(self, name):
        self.trace.append((name,))
        if self.callback_failure == name:
            raise self.failure

    def settings(self, conn):
        assert conn is self.conn
        self.check_callback("settings")
        return .02585, .1

    def reprice(self, conn, pc, fee, margin, reason, ref_id):
        assert conn is self.conn
        assert (pc, fee, margin, reason, ref_id) == (101, .02585, .1, "sourcing", 77)
        self.check_callback("reprice")
        return copy.deepcopy(self.rp)

    def confirmed_at_ready(self):
        self.check_callback("ready")
        return self.ready

    def log(self, conn, action, target_id, detail, *, kind):
        assert conn is self.conn
        self.check_callback("log")
        self.log_calls.append((action, target_id, copy.deepcopy(detail), kind))
        return 901

    def run(self, quote_id=77):
        return core.confirm_quote_tx(self.conn, quote_id, settings=self.settings,
                                     reprice=self.reprice, log=self.log,
                                     confirmed_at_ready=self.confirmed_at_ready)


class FakeTransaction:
    def __init__(self, fixture, *, exit_error=None):
        self.fixture = fixture
        self.exit_error = exit_error

    def __enter__(self):
        self.fixture.trace.append(("enter",))
        return self.fixture.conn

    def __exit__(self, exc_type, exc, traceback):
        self.fixture.trace.append(("exit", exc))
        if self.exit_error is not None:
            raise self.exit_error
        return False


class FakeEngine:
    def __init__(self, fixture, **options):
        self.transaction = FakeTransaction(fixture, **options)

    def begin(self):
        self.transaction.fixture.trace.append(("begin",))
        return self.transaction


def adapter_namespace(fixture, **engine_options):
    """Execute only current route/adapter function AST, never import the app."""
    tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))
    functions = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in ("_confirm_quote_tx", "confirm_quote"):
            node.decorator_list = []
            functions.append(node)
    namespace = dict(engine=FakeEngine(fixture, **engine_options),
                     _confirm_quote_core=core.confirm_quote_tx, _settings=fixture.settings,
                     _reprice=fixture.reprice, _log=fixture.log,
                     _confirmed_at_ready=fixture.confirmed_at_ready,
                     HTTPException=HTTPException, OperationalError=OperationalError)
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(ADAPTER), "exec"), namespace)
    return namespace


class SourcingCoreTests(unittest.TestCase):
    def test_response_and_all_undo_log_materials(self):
        fixture = Fixture()
        output = fixture.run()
        self.assertEqual(output, {
            "ok": True, "sku": "P-101", "price": 142000,
            "purchase_changed": True, "sale_changed": True, "sale_locked": False,
            "purchase_before": 148000, "purchase_after": 142000,
            "sale_before": 160000, "sale_after": 155000, "undo_id": 901})
        self.assertEqual(fixture.log_calls, [("sourcing_confirm", "P-101", {
            "quote_id": 77, "product_code": 101, "supplier_id": 11, "price": 142000,
            "before": {"quote_status": "회신", "batch_status": "진행", "cost_price": 148000,
                       "supply_state": "불가", "purchase_price": 148000, "sale_price": 160000},
            "cancelled_siblings": [{"quote_id": 78, "status": "요청"},
                                   {"quote_id": 79, "status": "회신"}],
            "reprice": fixture.rp}, "sourcing")])

    def test_sql_and_dependency_order_and_original_parameters(self):
        fixture = Fixture()
        fixture.run()
        self.assertEqual(fixture.trace, [
            ("sql", 0), ("sql", 1), ("sql", 2), ("sql", 3), ("sql", 4), ("sql", 5),
            ("sql", 6), ("settings",), ("sql", 7), ("sql", 8), ("sql", 9),
            ("reprice",), ("sql", 10), ("ready",), ("sql", 11), ("sql", 12),
            ("sql", 13), ("log",)])
        sql = [call[0] for call in fixture.conn.calls]
        self.assertNotIn("FOR UPDATE", sql[0])
        self.assertIn("ORDER BY product_code FOR UPDATE", sql[2])
        self.assertIn("sourcing_batches WHERE batch_id=:b FOR UPDATE", sql[3])
        self.assertIn("ORDER BY quote_id FOR UPDATE", sql[4])
        self.assertEqual(sql[1], sql[5])
        self.assertIn("cost_price, supply_state FROM product_supplier_prices", sql[7])
        self.assertIn("purchase_price, sale_price FROM products", sql[8])
        self.assertIn("ON CONFLICT (product_code, supplier_id)", sql[9])
        self.assertIn("cost_price=:c, supply_state='가능', updated_at=now()", sql[9])
        self.assertEqual(sql[8], sql[10])
        self.assertIn("confirmed_at=now()", sql[11])
        self.assertIn("status='취소'", sql[12])
        self.assertIn("status='완료'", sql[13])
        self.assertEqual([call[1] for call in fixture.conn.calls], [
            {"i": 77}, {"i": 77, "b": 201}, {"codes": [101]}, {"b": 201},
            {"ids": [77, 78, 79]}, {"i": 77, "b": 201}, {"pc": 101},
            {"pc": 101, "s": 11}, {"pc": 101}, {"pc": 101, "s": 11, "c": 142000}, {"pc": 101},
            {"i": 77}, {"b": 201, "i": 77}, {"b": 201}])
        self.assertFalse(any("stock_qty" in statement or "stock_movements" in statement for statement in sql))

    def test_confirmed_at_absent_branch_keeps_the_same_call_point(self):
        fixture = Fixture(ready=False)
        fixture.run()
        self.assertNotIn("confirmed_at", fixture.conn.calls[11][0])
        self.assertEqual(fixture.trace[12:15], [("sql", 10), ("ready",), ("sql", 11)])
        self.assertEqual(fixture.trace.count(("ready",)), 1)

    def test_missing_psp_is_logged_as_null_before(self):
        fixture = Fixture(psp=None)
        fixture.run()
        before = fixture.log_calls[0][2]["before"]
        self.assertIsNone(before["cost_price"])
        self.assertIsNone(before["supply_state"])

    def test_empty_siblings_and_actual_batch_state_are_preserved(self):
        fixture = Fixture(siblings=[], batch_status="기타상태")
        fixture.run()
        detail = fixture.log_calls[0][2]
        self.assertEqual(detail["cancelled_siblings"], [])
        self.assertEqual(detail["before"]["batch_status"], "기타상태")

    def test_nullable_actual_prices_and_sale_lock_result(self):
        fixture = Fixture(before={"purchase_price": None, "sale_price": None},
                          after={"purchase_price": 142000, "sale_price": None},
                          reprice_result={"purchase_changed": True, "sale_changed": False,
                                          "sale_locked": True})
        result = fixture.run()
        self.assertIsNone(result["purchase_before"])
        self.assertIsNone(result["sale_before"])
        self.assertIsNone(result["sale_after"])
        self.assertFalse(result["sale_changed"])
        self.assertTrue(result["sale_locked"])

    def test_no_new_business_price_guard_is_added(self):
        for price in (0, -1):
            fixture = Fixture(quote={"price": price})
            self.assertEqual(fixture.run()["price"], price)

    def test_missing_quote_is_404_before_callbacks(self):
        fixture = Fixture(missing_quote=True)
        with self.assertRaises(HTTPException) as caught:
            fixture.run()
        self.assertEqual((caught.exception.status_code, caught.exception.detail), (404, "견적이 없습니다"))
        self.assertEqual(fixture.trace, [("sql", 0)])

    def test_not_replied_or_missing_price_is_409_without_writes(self):
        for changes in ({"status": "요청"}, {"status": "확정"}, {"status": "취소"}, {"price": None}):
            fixture = Fixture(quote=changes)
            with self.assertRaises(HTTPException) as caught:
                fixture.run()
            self.assertEqual((caught.exception.status_code, caught.exception.detail),
                             (409, "회신이 기록된 견적만 확정할 수 있습니다"))
            self.assertEqual(fixture.trace, [("sql", 0)])

    def test_each_callback_failure_propagates_without_later_steps(self):
        prefixes = {"settings": 7, "reprice": 10, "ready": 11, "log": 14}
        for callback, sql_count in prefixes.items():
            fixture = Fixture()
            fixture.callback_failure = callback
            with self.assertRaises(RuntimeError) as caught:
                fixture.run()
            self.assertIs(caught.exception, fixture.failure)
            self.assertEqual(len(fixture.conn.calls), sql_count)
            self.assertEqual(fixture.trace[-1], (callback,))

    def test_each_sql_failure_propagates_unchanged(self):
        for index in range(14):
            fixture = Fixture()
            fixture.conn.fail_index = index
            with self.assertRaises(RuntimeError) as caught:
                fixture.run()
            self.assertIs(caught.exception, fixture.conn.failure)
            self.assertEqual(len(fixture.conn.calls), index + 1)
            self.assertEqual(fixture.log_calls, [])

    def test_log_result_and_callback_object_are_not_replaced(self):
        fixture = Fixture()
        result = fixture.run()
        self.assertEqual(result["undo_id"], 901)
        self.assertEqual(fixture.log_calls[0][2]["reprice"], fixture.rp)


class SourcingAdapterTests(unittest.TestCase):
    def test_adapter_uses_real_core_inside_existing_begin_boundary(self):
        fixture = Fixture()
        namespace = adapter_namespace(fixture)
        result = namespace["_confirm_quote_tx"](77)
        self.assertEqual(result["undo_id"], 901)
        self.assertEqual(fixture.trace[:3], [("begin",), ("enter",), ("sql", 0)])
        self.assertEqual(fixture.trace[-2:], [("log",), ("exit", None)])

    def test_adapter_does_not_preflight_ready_outside_transaction(self):
        fixture = Fixture(ready=False)
        namespace = adapter_namespace(fixture)
        namespace["_confirm_quote_tx"](77)
        self.assertEqual(fixture.trace.index(("ready",)), fixture.trace.index(("sql", 10)) + 1)
        self.assertLess(fixture.trace.index(("ready",)), len(fixture.trace) - 1)

    def test_adapter_exception_exits_context_and_propagates_same_error(self):
        fixture = Fixture()
        fixture.callback_failure = "reprice"
        with self.assertRaises(RuntimeError) as caught:
            adapter_namespace(fixture)["_confirm_quote_tx"](77)
        self.assertIs(caught.exception, fixture.failure)
        self.assertEqual(fixture.trace[-1], ("exit", fixture.failure))

    def test_begin_exit_failure_still_reaches_caller(self):
        fixture = Fixture()
        failure = RuntimeError("fake boundary failure")
        with self.assertRaises(RuntimeError) as caught:
            adapter_namespace(fixture, exit_error=failure)["_confirm_quote_tx"](77)
        self.assertIs(caught.exception, failure)

    def test_route_keeps_40p01_to_409_after_transaction_exit(self):
        fixture = Fixture()
        driver_error = RuntimeError("fake SQLSTATE")
        driver_error.pgcode = "40P01"
        failure = OperationalError("fake statement", {}, driver_error)
        fixture.conn.fail_index, fixture.conn.failure = 3, failure
        with self.assertRaises(HTTPException) as caught:
            adapter_namespace(fixture)["confirm_quote"](77)
        self.assertEqual((caught.exception.status_code, caught.exception.detail),
                         (409, "다른 확정 요청과 동시에 처리되어 충돌했습니다. 다시 시도하세요"))
        self.assertEqual(fixture.trace[-1], ("exit", failure))

    def test_route_rethrows_non_40p01_operational_error(self):
        for state in ("08006", "40001", None):
            fixture = Fixture()
            driver_error = RuntimeError("fake SQLSTATE")
            driver_error.pgcode = state
            failure = OperationalError("fake statement", {}, driver_error)
            fixture.conn.fail_index, fixture.conn.failure = 0, failure
            with self.assertRaises(OperationalError) as caught:
                adapter_namespace(fixture)["confirm_quote"](77)
            self.assertIs(caught.exception, failure)

    def test_current_import_and_adapter_dependency_wiring(self):
        tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))
        imports = [n for n in tree.body if isinstance(n, ast.ImportFrom)
                   and n.module == "sourcing_confirm_core"]
        self.assertEqual(len(imports), 1)
        self.assertEqual((imports[0].level, imports[0].names[0].name, imports[0].names[0].asname),
                         (1, "confirm_quote_tx", "_confirm_quote_core"))
        adapter = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_confirm_quote_tx")
        calls = [n for n in ast.walk(adapter) if isinstance(n, ast.Call)]
        direct = next(n for n in calls if isinstance(n.func, ast.Name) and n.func.id == "_confirm_quote_core")
        self.assertEqual({k.arg: k.value.id for k in direct.keywords}, {
            "settings": "_settings", "reprice": "_reprice", "log": "_log",
            "confirmed_at_ready": "_confirmed_at_ready"})


class IndependentImportTests(unittest.TestCase):
    def test_import_does_not_load_operational_modules_or_create_connections(self):
        program = """
import builtins, importlib, socket, sys, sqlalchemy
def deny(*args, **kwargs):
    raise AssertionError('connection creation forbidden')
socket.socket.connect = deny
socket.socket.connect_ex = deny
socket.create_connection = deny
sqlalchemy.create_engine = deny
sqlalchemy.engine.create_engine = deny
original = builtins.__import__
blocked = {'api.db', 'api.main', 'api.auth', 'api.admin_sourcing',
           'api.admin_price_import', 'api.admin_orders', 'api.admin_products'}
def checked(name, globals=None, locals=None, fromlist=(), level=0):
    resolved = importlib.util.resolve_name('.'*level + name, globals['__package__']) if level else name
    if resolved in blocked or resolved.split('.')[0] in {'psycopg', 'psycopg2', 'asyncpg'}:
        raise AssertionError('operational import forbidden')
    return original(name, globals, locals, fromlist, level)
builtins.__import__ = checked
sys.path.insert(0, sys.argv[1])
module = importlib.import_module('api.sourcing_confirm_core')
assert not blocked.intersection(sys.modules)
assert callable(module.confirm_quote_tx)
print('independent import; no operational modules or connection creation')
"""
        result = subprocess.run([sys.executable, "-I", "-B", "-c", program, str(ROOT)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no operational modules or connection creation", result.stdout)


if __name__ == "__main__":
    unittest.main()
