"""No-connection log extraction checks; no real PG/actor/receipt guarantee."""

import ast
import copy
import importlib.util
import inspect
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "api" / "admin_activity_log_core.py"
ADAPTER = ROOT / "api" / "admin_orders.py"
SPEC = importlib.util.spec_from_file_location("activity_log_core_test", MODULE)
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)
SQL = (
    "INSERT INTO admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)"
    " VALUES (:op, :a, :k, :t, CAST(:d AS JSONB)) RETURNING log_id"
)


class FakeResult:
    def __init__(self, conn):
        self.conn = conn

    def scalar(self):
        self.conn.trace.append("scalar")
        if self.conn.scalar_error is not None:
            raise self.conn.scalar_error
        return self.conn.scalar_value


class FakeConnection:
    """No begin/connect/commit/rollback API exists."""

    def __init__(self, trace=None, value=901):
        self.trace = trace if trace is not None else []
        self.calls = []
        self.scalar_value = value
        self.execute_error = self.scalar_error = None

    def execute(self, statement, params):
        self.trace.append("execute")
        self.calls.append((str(statement), params))
        if self.execute_error is not None:
            raise self.execute_error
        return FakeResult(self)


class Actor:
    def __init__(self, trace, value=11, failure=None):
        self.trace, self.value, self.failure = trace, value, failure
        self.calls = 0

    def __call__(self):
        self.trace.append("actor")
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return self.value


def adapter_function(actor):
    """Compile just the checked-in wrapper, not the operational module."""
    tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_log")
    namespace = {"_log_core": core.log_action, "current_operator_id": actor}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(ADAPTER), "exec"), namespace)
    return namespace["_log"]


class ActivityLogCoreTests(unittest.TestCase):
    def test_default_kind_sql_parameters_and_return(self):
        conn = FakeConnection()
        actor = Actor(conn.trace)
        detail = {"order_id": 301, "before": {"status": "접수"}}
        result = core.log_action(conn, "order_advance", "O-301", detail, operator_id=actor)
        self.assertEqual(result, 901)
        self.assertEqual(conn.calls, [(SQL, {"op": 11, "a": "order_advance", "k": "order",
                                            "t": "O-301", "d": json.dumps(detail)})])
        self.assertEqual(actor.calls, 1)
        self.assertEqual(conn.trace, ["actor", "execute", "scalar"])

    def test_sourcing_and_explicit_kinds_are_forwarded_without_policy(self):
        for kind in ("sourcing", "stock", "price_file", "", None):
            conn = FakeConnection()
            actor = Actor(conn.trace)
            result = core.log_action(conn, "sourcing_confirm", "P-101", {"quote_id": 77},
                                     kind, operator_id=actor)
            self.assertEqual(result, 901)
            self.assertEqual(conn.calls[0][1]["k"], kind)
            self.assertEqual(conn.calls[0][1]["a"], "sourcing_confirm")

    def test_json_defaults_unicode_spacing_order_and_nonfinite(self):
        conn = FakeConnection()
        detail = {"z": "한글", "a": [None, True, 1.25], "nonfinite": float("nan")}
        core.log_action(conn, "fixture", "101", detail, operator_id=Actor(conn.trace))
        serialized = conn.calls[0][1]["d"]
        self.assertEqual(serialized, json.dumps(detail))
        self.assertIn('"z": "\\ud55c\\uae00"', serialized)
        self.assertTrue(serialized.startswith('{"z":'))
        self.assertIn("NaN", serialized)  # Legacy dumps, not PG JSONB validity.

    def test_actor_then_json_then_execute_then_scalar(self):
        conn = FakeConnection()
        actor = Actor(conn.trace)
        real_dumps = json.dumps

        def spy(detail, *args, **kwargs):
            conn.trace.append("json")
            self.assertEqual(args, ())
            self.assertEqual(kwargs, {})
            return real_dumps(detail)

        with patch.object(core.json, "dumps", side_effect=spy):
            core.log_action(conn, "fixture", "101", {"nullable": None}, operator_id=actor)
        self.assertEqual(conn.trace, ["actor", "json", "execute", "scalar"])
        self.assertEqual(actor.calls, 1)

    def test_actor_error_precedes_json_error_and_execute(self):
        conn = FakeConnection()
        failure = RuntimeError("actor fixture failure")
        actor = Actor(conn.trace, failure=failure)
        with patch.object(core.json, "dumps", side_effect=TypeError("JSON fixture failure")) as dumps:
            with self.assertRaises(RuntimeError) as caught:
                core.log_action(conn, "fixture", "101", {"bad": object()}, operator_id=actor)
        self.assertIs(caught.exception, failure)
        dumps.assert_not_called()
        self.assertEqual(actor.calls, 1)
        self.assertEqual(conn.calls, [])
        self.assertEqual(conn.trace, ["actor"])

    def test_json_error_after_actor_is_unchanged_and_no_sql_runs(self):
        conn = FakeConnection()
        actor = Actor(conn.trace)
        failure = ValueError("JSON fixture failure")
        with patch.object(core.json, "dumps", side_effect=failure) as dumps:
            with self.assertRaises(ValueError) as caught:
                core.log_action(conn, "fixture", "101", {}, operator_id=actor)
        self.assertIs(caught.exception, failure)
        dumps.assert_called_once_with({})
        self.assertEqual(actor.calls, 1)
        self.assertEqual(conn.calls, [])

    def test_real_default_json_type_error_is_not_repaired(self):
        conn = FakeConnection()
        actor = Actor(conn.trace)
        with self.assertRaises(TypeError):
            core.log_action(conn, "fixture", "101", {"bad": object()}, operator_id=actor)
        self.assertEqual(actor.calls, 1)
        self.assertEqual(conn.calls, [])

    def test_execute_error_is_unchanged_without_scalar(self):
        conn = FakeConnection()
        actor = Actor(conn.trace)
        conn.execute_error = RuntimeError("execute fixture failure")
        with self.assertRaises(RuntimeError) as caught:
            core.log_action(conn, "fixture", "101", {}, operator_id=actor)
        self.assertIs(caught.exception, conn.execute_error)
        self.assertEqual(conn.trace, ["actor", "execute"])

    def test_scalar_error_is_unchanged(self):
        conn = FakeConnection()
        actor = Actor(conn.trace)
        conn.scalar_error = RuntimeError("scalar fixture failure")
        with self.assertRaises(RuntimeError) as caught:
            core.log_action(conn, "fixture", "101", {}, operator_id=actor)
        self.assertIs(caught.exception, conn.scalar_error)
        self.assertEqual(conn.trace, ["actor", "execute", "scalar"])

    def test_scalar_null_and_values_are_not_coerced(self):
        for value in (None, 0, 77, object()):
            conn = FakeConnection(value=value)
            self.assertIs(core.log_action(conn, "fixture", "101", {}, operator_id=Actor(conn.trace)), value)

    def test_actor_value_is_forwarded_and_not_authentication(self):
        for value in (None, 0, 11):
            conn = FakeConnection()
            actor = Actor(conn.trace, value=value)
            core.log_action(conn, "fixture", "101", {}, operator_id=actor)
            self.assertIs(conn.calls[0][1]["op"], value)
            self.assertEqual(actor.calls, 1)

    def test_nested_detail_and_input_order_are_unchanged(self):
        detail = {"product_code": 101, "before": {"price": None, "status": "회신"},
                  "siblings": [{"quote_id": 78, "status": "요청"}]}
        original = copy.deepcopy(detail)
        conn = FakeConnection()
        core.log_action(conn, "sourcing_confirm", "P-101", detail, "sourcing",
                         operator_id=Actor(conn.trace))
        self.assertEqual(detail, original)
        self.assertEqual(list(detail), list(original))
        self.assertEqual(json.loads(conn.calls[0][1]["d"]), original)

    def test_repeated_invocations_do_not_add_idempotency(self):
        conn = FakeConnection()
        actor = Actor(conn.trace)
        for _ in range(2):
            core.log_action(conn, "fixture", "101", {}, operator_id=actor)
        self.assertEqual(len(conn.calls), 2)
        self.assertEqual(actor.calls, 2)
        self.assertEqual(conn.calls[0], conn.calls[1])


class ActivityLogAdapterTests(unittest.TestCase):
    def test_current_adapter_calls_real_core_with_default_contract(self):
        conn = FakeConnection()
        actor = Actor(conn.trace)
        function = adapter_function(actor)
        signature = inspect.signature(function)
        self.assertEqual(list(signature.parameters), ["conn", "action", "target_id", "detail", "kind"])
        self.assertEqual(signature.parameters["kind"].default, "order")
        self.assertEqual(function(conn, "fixture", "101", {}), 901)
        self.assertEqual(conn.calls[0][1]["k"], "order")
        self.assertEqual(actor.calls, 1)

    def test_current_adapter_forwards_sourcing_kind_and_scalar_null(self):
        conn = FakeConnection(value=None)
        actor = Actor(conn.trace)
        output = adapter_function(actor)(conn, "sourcing_confirm", "P-101", {"quote_id": 77}, kind="sourcing")
        self.assertIsNone(output)
        self.assertEqual(conn.calls[0][1]["k"], "sourcing")
        self.assertEqual(conn.trace, ["actor", "execute", "scalar"])

    def test_adapter_preserves_actor_before_json_error(self):
        conn = FakeConnection()
        actor = Actor(conn.trace)
        with self.assertRaises(TypeError):
            adapter_function(actor)(conn, "fixture", "101", {"bad": object()})
        self.assertEqual(conn.trace, ["actor"])
        self.assertEqual(actor.calls, 1)
        self.assertEqual(conn.calls, [])

    def test_checked_in_import_and_callable_wiring(self):
        tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))
        imports = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == "admin_activity_log_core"]
        self.assertEqual(len(imports), 1)
        self.assertEqual((imports[0].level, imports[0].names[0].name, imports[0].names[0].asname),
                         (1, "log_action", "_log_core"))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_log")
        call = function.body[0].value
        self.assertEqual(call.func.id, "_log_core")
        self.assertEqual([value.id for value in call.args], ["conn", "action", "target_id", "detail"])
        self.assertEqual({keyword.arg: keyword.value.id for keyword in call.keywords},
                         {"kind": "kind", "operator_id": "current_operator_id"})


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
blocked = {'api.db', 'api.main', 'api.auth', 'api.admin_orders', 'api.admin_sourcing',
           'api.admin_price_import', 'api.admin_products'}
def checked(name, globals=None, locals=None, fromlist=(), level=0):
    resolved = importlib.util.resolve_name('.'*level + name, globals['__package__']) if level else name
    if resolved in blocked or resolved.split('.')[0] in {'psycopg', 'psycopg2', 'asyncpg'}:
        raise AssertionError('operational import forbidden')
    return original(name, globals, locals, fromlist, level)
builtins.__import__ = checked
sys.path.insert(0, sys.argv[1])
module = importlib.import_module('api.admin_activity_log_core')
assert not blocked.intersection(sys.modules)
assert callable(module.log_action)
print('independent import; no operational modules or connection creation')
"""
        output = subprocess.run([sys.executable, "-I", "-B", "-c", program, str(ROOT)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(output.returncode, 0, output.stderr)
        self.assertIn("no operational modules or connection creation", output.stdout)


if __name__ == "__main__":
    unittest.main()
