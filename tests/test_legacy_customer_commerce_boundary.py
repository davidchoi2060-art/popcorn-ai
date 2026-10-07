"""R3: actual customer functions + shared helper, caller-connection mocks only.

No production module imports, DB connection, PostgreSQL transaction, or HTTP proof.
"""
import ast
import builtins
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import BaseModel


ROOT = Path(__file__).resolve().parents[1]
ORDERS = ROOT / "api/my_orders.py"
PAYMENTS = ROOT / "api/my_payments.py"
ADMIN = ROOT / "api/admin_orders.py"
BASELINE_AST = {
    "my_orders.py": "60117cef57679c5b895e85489ceba7c3f3510f4bf0bc8bae4480f209cb666e4c",
    "my_payments.py": "49a2d9715b143412026de06c9400fc17916e61addf725482d6db8ecbf4e67412",
}


def tree(path):
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


class WithoutBoundary(ast.NodeTransformer):
    """Remove only this patch for a whole-module legacy AST comparison."""
    def visit_ImportFrom(self, node):
        if node.module == "admin_orders":
            node.names = [n for n in node.names if n.name != "_commerce_order_ids"]
            if not node.names:
                return None
        return node

    def visit_Assign(self, node):
        if any(isinstance(t, ast.Name) and t.id == "commerce_ids" for t in node.targets):
            return None
        if isinstance(node.value, ast.ListComp) and any(
                isinstance(n, ast.Name) and n.id == "commerce_ids"
                for n in ast.walk(node.value)):
            return None
        return self.generic_visit(node)

    def visit_If(self, node):
        if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "_commerce_order_ids" for n in ast.walk(node.test)):
            return None
        return self.generic_visit(node)

    def visit_Constant(self, node):
        if isinstance(node.value, str) and node.value.startswith("SELECT o.order_id, o.order_no,"):
            node.value = node.value.replace("SELECT o.order_id, o.order_no,", "SELECT o.order_no,", 1)
        return node


class Result:
    def __init__(self, rows=(), scalar=None):
        self.rows, self.value = list(rows), scalar

    def mappings(self): return self
    def all(self): return self.rows
    def first(self): return self.rows[0] if self.rows else None
    def scalar(self): return self.value
    def __iter__(self): return iter(self.rows)


def order(oid, member=7, status="결제완료", hour=10):
    # Identical legacy-looking channel/modes/number shape for both memberships.
    return dict(order_id=oid, order_no=f"ORD-{oid}", member_id=member, status=status,
                channel="own", total_amount=100, ops_snapshot={"refund": "own"},
                created_at=datetime(2026, 10, 5, hour))


def payment(oid, pid, status="승인", hour=10):
    return dict(order_id=oid, payment_id=pid, pay_mode="own", method="카드",
                amount=100, status=status, pg_ref="private-ref",
                paid_at=datetime(2026, 10, 5, hour) if hour is not None else None)


def aware(dt):
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class Connection:
    def __init__(self, orders=(), commerce=(), schema=True, payments=(), handoffs=()):
        self.orders = {o["order_id"]: deepcopy(o) for o in orders}
        self.commerce = {oid: "paid" for oid in commerce}
        self.schema = schema
        self.payments, self.handoffs = deepcopy(list(payments)), deepcopy(list(handoffs))
        self.items, self.ships, self.refunds, self.stock, self.logs = [], [], [], [], []
        self.handoff_counts, self.member_users = {}, {7: "promoted-user"}
        self.trace, self.writes, self.contexts = [], [], []
        self.rollbacks = self.commit_simulations = 0
        self.failure_at, self.failure = None, RuntimeError("fixture query failure")

    def state(self):
        return deepcopy((self.orders, self.payments, self.handoffs, self.items,
                         self.ships, self.refunds, self.stock, self.logs))

    def execute(self, sql, params=None):
        params = params or {}
        self.trace.append((sql, deepcopy(params)))
        if sql == "SELECT pg_catalog.to_regclass('public.commerce_order_details')":
            if self.failure_at == "catalog":
                raise self.failure
            return Result(scalar="public.commerce_order_details" if self.schema else None)
        if "FROM public.commerce_order_details" in sql:
            if self.failure_at == "membership":
                raise self.failure
            return Result([(i,) for i in params["ids"] if i in self.commerce])
        if sql.startswith(("INSERT ", "UPDATE ", "DELETE ")):
            self.writes.append((sql, deepcopy(params)))
            if sql.startswith("INSERT INTO refunds"):
                rid = 41
                self.refunds.append(dict(order_id=params["o"], refund_id=rid,
                    refund_mode=params["m"], reason_type=params["r"],
                    amount=params["a"], status="접수"))
                return Result(scalar=rid)
            raise AssertionError("unexpected mutation: " + sql)
        if "FROM payments p JOIN orders o" in sql:
            rows = [dict(p, order_no=self.orders[p["order_id"]]["order_no"])
                    for p in self.payments
                    if self.orders[p["order_id"]]["member_id"] == params["m"]]
            rows.sort(key=lambda r: (r["paid_at"] is not None,
                aware(r["paid_at"]) if r["paid_at"] else datetime.min.replace(tzinfo=timezone.utc),
                r["payment_id"]), reverse=True)
            return Result(rows)
        if "FROM orders" in sql:
            if "order_no=:n" in sql:
                return Result([o for o in self.orders.values() if o["order_no"] == params["n"]])
            rows = [o for o in self.orders.values() if o["member_id"] == params["m"]]
            return Result(sorted(rows, key=lambda o: (aware(o["created_at"]), o["order_id"]), reverse=True))
        if "FROM order_items" in sql:
            return Result([r for r in self.items if r["order_id"] in params["ids"]])
        if "FROM payments" in sql:
            latest = {}
            for p in sorted(self.payments, key=lambda r: r["payment_id"], reverse=True):
                if p["order_id"] in params["ids"]:
                    latest.setdefault(p["order_id"], p)
            return Result(latest.values())
        if "FROM shipments" in sql:
            return Result([r for r in self.ships if r["order_id"] in params["ids"]])
        if "FROM refunds" in sql:
            if sql.startswith("SELECT 1"):
                return Result([(1,)] if any(r["order_id"] == params["o"] and
                    r["status"] in params["st"] for r in self.refunds) else [])
            return Result([r for r in self.refunds if r["order_id"] in params["ids"]])
        if "FROM handoffs" in sql:
            rows = [h for h in self.handoffs if h["member_id"] == params["m"] or
                    (h["user_id"] is not None and h["user_id"] == self.member_users.get(params["m"]))]
            return Result(sorted(rows, key=lambda h: (aware(h["created_at"]), h["handoff_id"]), reverse=True))
        if "FROM handoff_items" in sql:
            return Result([(i, self.handoff_counts[i]) for i in params["ids"] if i in self.handoff_counts])
        raise AssertionError("unexpected SQL: " + sql)


class CallerContext:
    def __init__(self, conn, kind):
        self.conn, self.kind = conn, kind

    def __enter__(self):
        self.before = self.conn.state()
        self.conn.contexts.append(self.kind)
        return self.conn

    def __exit__(self, kind, value, tb):
        if kind:
            (self.conn.orders, self.conn.payments, self.conn.handoffs, self.conn.items,
             self.conn.ships, self.conn.refunds, self.conn.stock, self.conn.logs) = self.before
            self.conn.rollbacks += 1
        elif self.kind == "begin":
            self.conn.commit_simulations += 1
        return False


class Engine:
    def __init__(self, conn): self.conn = conn
    def connect(self): return CallerContext(self.conn, "connect")
    def begin(self): return CallerContext(self.conn, "begin")


def compile_definitions(source, env, names, baseline=False):
    module = tree(source)
    if baseline:
        module = WithoutBoundary().visit(module)
    module.body = [n for n in module.body
                   if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    if {n.name for n in module.body} != set(names):
        raise AssertionError("missing actual definition")
    for node in module.body:
        node.decorator_list = []  # Route registration is outside this function-call test.
    exec(compile(module, str(source), "exec"), env)


def functions(conn, member=7, locked=False, auth_error=None, baseline=False):
    def require_member():
        if auth_error:
            raise auth_error
        return {"member_id": member}

    env = dict(HTTPException=HTTPException, BaseModel=BaseModel, text=lambda sql: sql,
               engine=Engine(conn), timezone=timezone, require_member=require_member,
               write_locked=lambda: locked, WRITE_LOCK_REASON="fixture write lock",
               MALL_CART_URL="https://example.invalid/shop/order_basket_list.html",
               LABELS={"CPU": "CPU", "COOLER": "CPU쿨러"})
    for source, names in ((ADMIN, {"RF_BASE", "STEP"}), (ORDERS, {"REASONS", "ACTIVE_REFUND"})):
        for node in tree(source).body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name in names:
                    env[name] = ast.literal_eval(node.value)
    compile_definitions(ROOT / "api/timeutil.py", env, {"iso"})
    compile_definitions(ADMIN, env, {"_commerce_order_ids", "_item_label", "refund_label"})
    compile_definitions(ORDERS, env, {"my_orders", "RefundBody", "create_refund"}, baseline)
    compile_definitions(PAYMENTS, env, {"list_payments"}, baseline)
    return SimpleNamespace(**env)


class CustomerBoundaryTests(unittest.TestCase):
    def setUp(self):
        original_import = builtins.__import__

        def no_production_import(name, *args, **kwargs):
            if name == "api" or name.startswith("api.") or name == "main":
                raise AssertionError("production import blocked: " + name)
            return original_import(name, *args, **kwargs)

        self.import_guard = patch("builtins.__import__", side_effect=no_production_import)
        self.import_guard.start()
        self.addCleanup(self.import_guard.stop)

    def assert_no_write(self, conn, before):
        self.assertEqual(conn.writes, [])
        self.assertEqual(conn.state(), before)
        self.assertEqual(conn.commit_simulations, 0)

    def call_refund(self, conn, **kwargs):
        api = functions(conn, **kwargs)
        return api.create_refund(api.RefundBody(order_no="ORD-2", reason_type="단순 변심"))

    def test_my_orders_same_member_mixed_excludes_before_derived_queries(self):
        conn = Connection(orders=[order(1), order(2), order(3, member=8)], commerce=[2, 3])
        conn.items = [dict(order_id=1, item_kind="core_part", name_snap="fixture",
                           price_snap=50, qty=2, spec_snap={"part_type": "CPU"})]
        before = conn.state()
        result = functions(conn).my_orders()
        self.assertEqual([r["no"] for r in result["items"]], ["ORD-1"])
        self.assertEqual(result["items"][0]["items"], [["CPU", "fixture", 100]])
        self.assertEqual(conn.trace[0][1], {"m": 7})
        self.assertEqual(conn.trace[2][1], {"ids": [2, 1]})
        derived = [(sql, p) for sql, p in conn.trace if "ids" in p and "commerce_order_details" not in sql]
        self.assertEqual(len(derived), 4)
        self.assertTrue(all(p["ids"] == [1] for _, p in derived))
        self.assert_no_write(conn, before)

    def test_commerce_only_orders_skip_all_legacy_derivation(self):
        conn = Connection(orders=[order(2)], commerce=[2])
        self.assertEqual(functions(conn).my_orders(), {"items": []})
        self.assertFalse(any("FROM " + table in s for s, _ in conn.trace
                             for table in ("order_items", "payments", "shipments", "refunds")))
        self.assertTrue(any("FROM handoffs" in s for s, _ in conn.trace))

    def test_empty_orders_preserve_handoffs_without_schema_query(self):
        conn = Connection()
        self.assertEqual(functions(conn).my_orders(), {"items": []})
        self.assertFalse(any("to_regclass" in s for s, _ in conn.trace))

    def test_other_member_orders_and_payments_never_become_membership_candidates(self):
        conn = Connection(orders=[order(2, member=8)], commerce=[2], payments=[payment(2, 1)])
        api = functions(conn)
        self.assertEqual(api.my_orders(), {"items": []})
        self.assertEqual(api.list_payments(), {"items": []})
        self.assertTrue(all(p == {"m": 7} for _, p in conn.trace))
        self.assertFalse(any("commerce_order_details" in s for s, _ in conn.trace))

    def test_order_and_handoff_merge_timezone_ties_and_member_scope_are_unchanged(self):
        def h(hid, hour, member=7, user=None):
            return dict(handoff_id=hid, handoff_no=f"H-{hid}", member_id=member,
                        user_id=user, total=55, status="인계", created_at=datetime(2026, 10, 5, hour, tzinfo=timezone.utc))
        conn = Connection(orders=[order(1, hour=10), order(4, hour=10), order(2, hour=13)],
                          commerce=[2], handoffs=[h(8, 12), h(9, 11, member=None, user="promoted-user"),
                                                h(10, 10), h(11, 15, member=8)])
        conn.handoff_counts = {8: 2, 9: 3, 10: 1, 11: 5}
        result = functions(conn).my_orders()["items"]
        self.assertEqual([r["no"] for r in result], ["H-8", "H-9", "ORD-4", "ORD-1", "H-10"])
        baseline_conn = deepcopy(conn)
        baseline = functions(baseline_conn, baseline=True).my_orders()["items"]
        self.assertEqual(result, [r for r in baseline if r["no"] != "ORD-2"])
        self.assertEqual(conn.trace[-1][1], {"ids": [8, 9, 10]})
        self.assertIn("item_kind='core_part'", conn.trace[-1][0])

    def test_orders_schema_absent_or_unrelated_membership_equals_legacy_response(self):
        for schema, commerce in ((False, [1, 2]), (True, [99])):
            with self.subTest(schema=schema):
                conn = Connection(orders=[order(1), order(2)], commerce=commerce, schema=schema,
                                  payments=[payment(1, 3)])
                baseline = functions(deepcopy(conn), baseline=True).my_orders()
                self.assertEqual(functions(conn).my_orders(), baseline)
                if not schema:
                    self.assertFalse(any("FROM public.commerce_order_details" in s for s, _ in conn.trace))

    def test_order_refund_shipping_and_latest_payment_output_remains_legacy(self):
        conn = Connection(orders=[order(1), order(2)], commerce=[2],
                          payments=[payment(1, 1), payment(1, 2, status="환불")])
        conn.ships = [dict(order_id=1, carrier="fixture", tracking_no="tracking")]
        conn.refunds = [dict(order_id=1, refund_id=5, reason_type="기타", status="검토", refund_mode="own")]
        expected = functions(deepcopy(conn), baseline=True).my_orders()["items"]
        result = functions(conn).my_orders()["items"]
        self.assertEqual(result, [r for r in expected if r["no"] == "ORD-1"])
        self.assertEqual(result[0]["pay"]["state"], "환불")
        self.assertEqual(result[0]["refund"]["no"], "RF-1028")

    def test_payments_mixed_preserves_every_legacy_event_and_null_last_tie_order(self):
        conn = Connection(orders=[order(1), order(2), order(3, member=8)], commerce=[2, 3], payments=[
            payment(1, 1, "승인", 9), payment(2, 99, "승인", 15), payment(1, 2, "취소", 10),
            payment(1, 3, "환불", 10), payment(1, 4, "대기", None), payment(3, 100, "환불", 16)])
        before = conn.state()
        result = functions(conn).list_payments()["items"]
        self.assertEqual([r["status"] for r in result], ["환불", "취소", "승인", "대기"])
        self.assertTrue(all(r["order_no"] == "ORD-1" for r in result))
        self.assertEqual(conn.trace[0][1], {"m": 7})
        self.assertEqual(conn.trace[2][1], {"ids": [2, 1, 1, 1, 1]})
        self.assert_no_write(conn, before)

    def test_payments_private_projection_never_leaks_public_ids_or_pg_ref(self):
        conn = Connection(orders=[order(1)], payments=[payment(1, 11)])
        rows = functions(conn).list_payments()["items"]
        self.assertEqual(set(rows[0]), {"order_no", "mode", "method", "amount", "status", "at"})
        self.assertFalse(any(k in rows[0] for k in ("order_id", "payment_id", "pg_ref")))
        self.assertTrue(conn.trace[0][0].startswith("SELECT o.order_id, o.order_no,"))
        projection = conn.trace[0][0].split(" FROM ")[0]
        self.assertNotIn("payment_id", projection)
        self.assertNotIn("pg_ref", projection)

    def test_payments_schema_absent_or_unrelated_membership_equals_all_legacy_rows(self):
        for schema, commerce in ((False, [1]), (True, [99])):
            with self.subTest(schema=schema):
                conn = Connection(orders=[order(1)], commerce=commerce, schema=schema,
                                  payments=[payment(1, 1), payment(1, 2, "환불")])
                self.assertEqual(functions(conn).list_payments(), functions(deepcopy(conn), baseline=True).list_payments())
                if not schema:
                    self.assertFalse(any("FROM public.commerce_order_details" in s for s, _ in conn.trace))

    def test_empty_or_commerce_only_payments_return_empty_without_fabricated_rows(self):
        for rows in ([], [payment(2, 1)]):
            with self.subTest(rows=bool(rows)):
                conn = Connection(orders=[order(2)], commerce=[2], payments=rows)
                self.assertEqual(functions(conn).list_payments(), {"items": []})
                self.assertFalse(any("handoff" in s for s, _ in conn.trace))
                if not rows:
                    self.assertFalse(any("to_regclass" in s for s, _ in conn.trace))

    def test_read_membership_does_not_depend_on_order_or_financial_status(self):
        for financial in ("paid", "payment_unknown", "declined", "refunded", "refund_processing", "cancel_unknown"):
            conn = Connection(orders=[order(2, status="취소")], commerce=[2], payments=[payment(2, 1)])
            conn.commerce[2] = financial
            api = functions(conn)
            self.assertEqual(api.my_orders(), {"items": []})
            self.assertEqual(api.list_payments(), {"items": []})

    def test_auth_failure_precedes_any_connection_or_membership_lookup(self):
        for name in ("my_orders", "list_payments", "create_refund"):
            with self.subTest(name=name):
                conn = Connection(orders=[order(2)], commerce=[2])
                failure = HTTPException(401, "fixture member required")
                api = functions(conn, auth_error=failure)
                with self.assertRaises(HTTPException) as caught:
                    if name == "create_refund":
                        api.create_refund(api.RefundBody(order_no="ORD-2", reason_type="단순 변심"))
                    else:
                        getattr(api, name)()
                self.assertIs(caught.exception, failure)
                self.assertEqual((conn.contexts, conn.trace), ([], []))

    def test_refund_write_lock_precedes_reason_order_lock_and_membership(self):
        conn = Connection(orders=[order(2)], commerce=[2])
        api = functions(conn, locked=True)
        with self.assertRaises(HTTPException) as caught:
            api.create_refund(api.RefundBody(order_no="ORD-2", reason_type="invalid"))
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail["error"], "write_locked")
        self.assertEqual((conn.contexts, conn.trace, conn.writes), ([], [], []))

    def test_refund_invalid_reason_precedes_connection(self):
        conn = Connection(orders=[order(2)], commerce=[2])
        api = functions(conn)
        with self.assertRaises(HTTPException) as caught:
            api.create_refund(api.RefundBody(order_no="ORD-2", reason_type="invalid"))
        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual((conn.contexts, conn.trace), ([], []))

    def test_refund_missing_order_retains_404_before_schema_lookup(self):
        conn = Connection(commerce=[2])
        with self.assertRaises(HTTPException) as caught:
            self.call_refund(conn)
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(len(conn.trace), 1)
        self.assertIn("FOR UPDATE OF o", conn.trace[0][0])
        self.assertEqual(conn.rollbacks, 1)

    def test_refund_other_member_retains_403_before_schema_lookup(self):
        for schema, commerce in ((False, []), (True, [2])):
            with self.subTest(schema=schema):
                conn = Connection(orders=[order(2, member=8)], commerce=commerce, schema=schema)
                before = conn.state()
                with self.assertRaises(HTTPException) as caught:
                    self.call_refund(conn)
                self.assertEqual(caught.exception.status_code, 403)
                self.assertEqual(caught.exception.detail, "본인 주문만 접수할 수 있습니다")
                self.assertEqual(len(conn.trace), 1)
                self.assert_no_write(conn, before)

    def test_commerce_refund_all_financial_and_legacy_statuses_reject_before_first_mutation(self):
        states = ("paid", "payment_pending", "payment_processing", "payment_unknown", "declined",
                  "refunded", "refund_processing", "refund_unknown", "cancel_processing", "cancel_unknown")
        for financial in states:
            for status in ("접수", "결제완료", "조립중", "배송중", "완료", "취소"):
                with self.subTest(financial=financial, status=status):
                    conn = Connection(orders=[order(2, status=status)], commerce=[2])
                    conn.commerce[2] = financial
                    conn.refunds = [dict(order_id=2, status="접수")]
                    conn.stock, conn.logs = ["protected fixture"], ["existing fixture log"]
                    before = conn.state()
                    with self.assertRaises(HTTPException) as caught:
                        self.call_refund(conn)
                    self.assertEqual(caught.exception.status_code, 409)
                    self.assertEqual(caught.exception.detail["error"], "commerce_order_requires_new_workflow")
                    self.assertIn("신규 주문", caught.exception.detail["detail"])
                    self.assertEqual(len(conn.trace), 3)
                    self.assertIn("FOR UPDATE OF o", conn.trace[0][0])
                    self.assertEqual(conn.trace[2][1], {"ids": [2]})
                    self.assertEqual(conn.rollbacks, 1)
                    self.assert_no_write(conn, before)

    def test_legacy_refund_schema_absent_or_unrelated_membership_preserves_single_insert(self):
        for schema, commerce in ((False, [2]), (True, [99])):
            for status in ("결제완료", "조립중", "배송중", "완료"):
                with self.subTest(schema=schema, status=status):
                    conn = Connection(orders=[order(2, status=status)], commerce=commerce, schema=schema)
                    baseline = deepcopy(conn)
                    self.assertEqual(self.call_refund(conn), self.call_refund(baseline, baseline=True))
                    self.assertEqual(conn.state(), baseline.state())
                    self.assertEqual(len(conn.writes), 1)
                    self.assertTrue(conn.writes[0][0].startswith("INSERT INTO refunds"))
                    self.assertEqual(conn.orders[2]["status"], status)
                    self.assertEqual(conn.commit_simulations, 1)
                    if not schema:
                        self.assertFalse(any("FROM public.commerce_order_details" in s for s, _ in conn.trace))

    def test_legacy_invalid_status_refund_is_unchanged(self):
        for status in ("접수", "취소"):
            conn = Connection(orders=[order(2, status=status)])
            with self.assertRaises(HTTPException) as caught:
                self.call_refund(conn)
            self.assertEqual((caught.exception.status_code, caught.exception.detail["error"]), (409, "invalid_state"))
            self.assertEqual(conn.writes, [])

    def test_legacy_active_refund_guard_remains_unchanged(self):
        for status in ("접수", "검토", "수거·처리"):
            conn = Connection(orders=[order(2)])
            conn.refunds = [dict(order_id=2, status=status)]
            with self.assertRaises(HTTPException) as caught:
                self.call_refund(conn)
            self.assertEqual((caught.exception.status_code, caught.exception.detail["error"]), (409, "refund_active"))
            self.assertEqual(conn.writes, [])

    def test_repeated_legacy_refund_creates_one_row_then_original_active_guard_rejects(self):
        conn = Connection(orders=[order(2)])
        self.assertEqual(self.call_refund(conn)["status"], "접수")
        after_first = conn.state()
        with self.assertRaises(HTTPException) as caught:
            self.call_refund(conn)
        self.assertEqual((caught.exception.status_code, caught.exception.detail["error"]), (409, "refund_active"))
        self.assertEqual((len(conn.refunds), len(conn.writes), conn.commit_simulations), (1, 1, 1))
        self.assertEqual(conn.state(), after_first)
        self.assertEqual(conn.rollbacks, 1)

    def test_non_active_legacy_refund_still_allows_reception_and_snapshot_mode(self):
        conn = Connection(orders=[order(2)])
        conn.orders[2]["ops_snapshot"] = None
        conn.refunds = [dict(order_id=2, status="완료")]
        self.assertEqual(self.call_refund(conn), {"refund_no": "RF-1064", "status": "접수", "mode": "mall"})
        self.assertEqual(conn.writes[0][1], {"o": 2, "m": "mall", "r": "단순 변심", "a": 100})

    def test_catalog_and_membership_errors_propagate_with_caller_rollback_no_fallback(self):
        for name in ("my_orders", "list_payments", "create_refund"):
            for failure_at in ("catalog", "membership"):
                with self.subTest(name=name, failure_at=failure_at):
                    conn = Connection(orders=[order(2)], payments=[payment(2, 1)])
                    conn.failure_at = failure_at
                    before = conn.state()
                    api = functions(conn)
                    with self.assertRaises(RuntimeError) as caught:
                        if name == "create_refund":
                            api.create_refund(api.RefundBody(order_no="ORD-2", reason_type="단순 변심"))
                        else:
                            getattr(api, name)()
                    self.assertIs(caught.exception, conn.failure)
                    self.assertEqual(conn.rollbacks, 1)
                    self.assertEqual(conn.contexts, ["begin" if name == "create_refund" else "connect"])
                    self.assert_no_write(conn, before)

    def test_schema_absence_is_checked_again_no_cache(self):
        conn = Connection(orders=[order(2)], commerce=[2], schema=False, payments=[payment(2, 1)])
        api = functions(conn)
        self.assertEqual(len(api.my_orders()["items"]), 1)
        self.assertEqual(len(api.list_payments()["items"]), 1)
        conn.schema = True
        self.assertEqual(api.my_orders(), {"items": []})
        self.assertEqual(api.list_payments(), {"items": []})
        self.assertEqual(sum("to_regclass" in s for s, _ in conn.trace), 4)

    def test_actual_shared_helper_uses_only_caller_connection_readonly_fk_ids(self):
        conn = Connection(orders=[order(2)], commerce=[2])
        api = functions(conn)
        self.assertEqual(api._commerce_order_ids.__code__.co_filename, str(ADMIN))
        self.assertEqual(api._commerce_order_ids(conn, [2, 9]), {2})
        self.assertEqual(conn.trace, [
            ("SELECT pg_catalog.to_regclass('public.commerce_order_details')", {}),
            ("SELECT order_id FROM public.commerce_order_details WHERE order_id = ANY(:ids)", {"ids": [2, 9]}),
        ])
        self.assertEqual((conn.contexts, conn.writes), ([], []))

    def test_production_api_db_main_imports_blocked_before_execution(self):
        for name in ("api", "api.db", "api.main", "main"):
            with self.assertRaisesRegex(AssertionError, "production import blocked"):
                exec("__import__(name)", {"name": name})

    def test_whole_legacy_ast_preserved_except_exact_boundary_and_private_projection(self):
        for source in (ORDERS, PAYMENTS):
            with self.subTest(source=source.name):
                cleaned = WithoutBoundary().visit(tree(source))
                sha = hashlib.sha256(ast.dump(cleaned, include_attributes=False).encode()).hexdigest()
                self.assertEqual(sha, BASELINE_AST[source.name])

    def test_helper_import_is_shared_and_no_local_schema_or_fallback_added(self):
        for source in (ORDERS, PAYMENTS):
            module = tree(source)
            imports = [n for n in module.body if isinstance(n, ast.ImportFrom)
                       and n.module == "admin_orders" and any(a.name == "_commerce_order_ids" for a in n.names)]
            self.assertEqual(len(imports), 1)
            self.assertFalse(any(isinstance(n, ast.FunctionDef) and n.name == "_commerce_order_ids" for n in module.body))
            owned = [n for n in module.body if isinstance(n, ast.FunctionDef)
                     and n.name in ("my_orders", "create_refund", "list_payments")]
            self.assertFalse(any(isinstance(n, ast.Try) for f in owned for n in ast.walk(f)))
            self.assertNotIn("to_regclass", source.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
