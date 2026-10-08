"""판매가 마진 통일 — 네 경로가 같은 상품에 같은 판매가를 내는지 고정한다 (2026-10-08).

전에는 대량 재산정(`admin_reprice`)만 분류 마진(자기 노드 -> 조상 -> 전역)을 쓰고
단가표 반영·가격 검토·소싱 확정은 전역 마진만 써서, 분류 예외가 걸린 상품은
매입가가 바뀔 때마다 판매가가 오갔다.

네 경로:
  ① 대량 재산정      admin_reprice._margin_map + _classify
  ② 단가표 반영      admin_price_import._reprice (-> pricing_reprice_core)
  ③ 가격 검토        admin_price_review.price_review 제안가 · decide(approve) 는 _reprice
  ④ 소싱 확정        admin_sourcing 이 core 에 reprice=_reprice 를 넘긴다

운영 모듈(api.db 등)을 import 하지 않는다 — 함수 AST 만 떼어 가짜 연결로 돌린다.
PostgreSQL 동작 증명이 아니라 계산 규칙이 한 곳으로 모였다는 증명이다.
"""
import ast
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from api.pricing import resolve_margins, sale_from_purchase  # noqa: E402
from api.pricing_reprice_core import reprice, product_margin, margin_map  # noqa: E402

FEE, GLOBAL = 0.02585, 0.05
# 트리: 1 부품(10%) ─ 2 GPU(8%) ─ 3 RTX(예외 없음 -> 2 상속)
#                  └ 4 케이스(예외 없음 -> 1 상속)
#       5 주변기기(예외 없음 -> 전역)
CATEGORIES = [(1, None), (2, 1), (3, 2), (4, 1), (5, None)]
POLICIES = [(1, 0.10), (2, 0.08)]
# 상품: (category_id, 매입가) — 999 는 트리에 없는 분류(삭제된 노드), None 은 미분류
PRODUCTS = {
    101: (2, 412_300),     # 자기 노드 8%
    102: (3, 1_287_450),   # 조상 GPU 8%
    103: (4, 89_990),      # 조상 부품 10%
    104: (5, 33_210),      # 전역 5%
    105: (None, 57_000),   # 미분류 -> 전역
    106: (999, 128_400),   # 고아 분류 -> 전역
}
EXPECTED_MARGIN = {101: 0.08, 102: 0.08, 103: 0.10, 104: 0.05, 105: 0.05, 106: 0.05}


def extract(rel, names, env):
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    nodes = []
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name in names:
            n.decorator_list = []
            nodes.append(n)
    assert sorted(n.name for n in nodes) == sorted(names), (rel, names)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), rel, "exec"), env)
    return env


class Result:
    def __init__(self, rows): self.rows = deepcopy(rows)
    def mappings(self): return self
    def all(self): return deepcopy(self.rows)
    def one(self): return deepcopy(self.rows[0])
    def first(self): return deepcopy(self.rows[0]) if self.rows else None
    def scalar(self): return self.rows[0] if self.rows else None
    def __iter__(self): return iter(deepcopy(self.rows))


class FakeConn:
    """가격 계산에 필요한 읽기만 답하고 쓰기는 상품 표에 반영한다."""

    def __init__(self, sale=None, locked=None):
        self.products = {pc: {"category_id": c, "purchase_price": None, "sale_price": sale,
                              "locked_fields": locked or []} for pc, (c, _p) in PRODUCTS.items()}
        # 공급처 한 곳 '가능' — 재판정 결과 매입가 = 그 값
        self.psp = {pc: [(p, "가능", 7)] for pc, (_c, p) in PRODUCTS.items()}
        self.calls = []

    def execute(self, stmt, params=None):
        q = str(stmt); params = params or {}; self.calls.append(q)
        if q == "SELECT category_id, parent_id FROM categories":
            return Result(CATEGORIES)
        if q == "SELECT category_id, margin_rate FROM category_margin_policies":
            return Result(POLICIES)
        if q == "SELECT category_id FROM products WHERE product_code=:pc":
            return Result([self.products[params["pc"]]["category_id"]])
        if q.startswith("SELECT purchase_price, sale_price, locked_fields FROM products"):
            p = self.products[params["pc"]]
            return Result([{k: p[k] for k in ("purchase_price", "sale_price", "locked_fields")}])
        if q.startswith("SELECT cost_price, supply_state, supplier_id"):
            return Result(self.psp[params["pc"]])
        if q.startswith("UPDATE products SET purchase_price"):
            self.products[params["pc"]]["purchase_price"] = params["v"]; return Result([])
        if q.startswith("UPDATE products SET sale_price"):
            self.products[params["pc"]]["sale_price"] = params["v"]; return Result([])
        if q.startswith("INSERT INTO product_price_history"):
            return Result([])
        raise AssertionError("unexpected SQL " + q)


def expected_sale(pc):
    return sale_from_purchase(PRODUCTS[pc][1], FEE, EXPECTED_MARGIN[pc])


class MarginUnificationTests(unittest.TestCase):
    def test_fixture_actually_distinguishes_category_from_global(self):
        # 분류 마진과 전역 마진이 같은 판매가를 내면 이 테스트는 아무것도 증명하지 못한다
        for pc in (101, 102, 103):
            self.assertNotEqual(expected_sale(pc), sale_from_purchase(PRODUCTS[pc][1], FEE, GLOBAL), pc)

    def test_product_margin_matches_resolve_margins_rule(self):
        conn = FakeConn()
        self.assertEqual({pc: product_margin(conn, pc, GLOBAL) for pc in PRODUCTS}, EXPECTED_MARGIN)
        self.assertEqual(margin_map(conn, GLOBAL),
                         {c: m for c, (m, _s) in resolve_margins(CATEGORIES, dict(POLICIES), GLOBAL).items()})

    def path_bulk_reprice(self):
        env = extract("api/admin_reprice.py", ["_margin_map", "_classify"],
                      {"text": text, "resolve_margins": resolve_margins,
                       "sale_from_purchase": sale_from_purchase, "PART_LABELS": {}, "OUTLIER_X": 2.0})
        conn = FakeConn()
        rows = [{"product_code": pc, "product_name": str(pc), "part_type": "GPU",
                 "purchase_price": p, "sale_price": None, "status": "판매중", "stock_qty": 1,
                 "locked_fields": [], "category_id": c} for pc, (c, p) in PRODUCTS.items()]
        out = env["_classify"](rows, FEE, GLOBAL, env["_margin_map"](conn, GLOBAL))
        return {i["product_code"]: i["proposed"] for i in out["up"]}

    def path_reprice_adapter(self):
        """단가표 반영·되돌리기·가격 검토 승인·소싱 확정이 모두 지나는 어댑터."""
        env = extract("api/admin_price_import.py", ["_reprice"],
                      {"_reprice_core": reprice, "product_margin": product_margin,
                       "current_operator_id": lambda: 1})
        conn = FakeConn()
        for pc in PRODUCTS:
            env["_reprice"](conn, pc, FEE, GLOBAL, "price_import", 1)
        return {pc: conn.products[pc]["sale_price"] for pc in PRODUCTS}

    def path_price_review_proposal(self):
        rows = [{"product_code": pc, "sku": f"P-{pc}", "product_name": str(pc), "part_type": "GPU",
                 "purchase_price": p, "sale_price": None, "category_id": c,
                 "supplier": "x", "cost_price": p} for pc, (c, p) in PRODUCTS.items()]
        conn = FakeConn()

        class Engine:
            def connect(self_inner):
                class Ctx:
                    def __enter__(s): return conn
                    def __exit__(s, *a): return False
                return Ctx()

        env = extract("api/admin_price_review.py", ["price_review"],
                      {"engine": Engine(), "_settings": lambda c: (FEE, GLOBAL), "_rows": lambda c: rows,
                       "margin_map": margin_map, "sale_from_purchase": sale_from_purchase,
                       "PART_TYPE_LABELS": {}, "NOTE": ""})
        out = env["price_review"]()
        self.assertEqual({i["product_code"]: i["margin_rate"] for i in out["items"]}, EXPECTED_MARGIN)
        return {i["product_code"]: i["proposed"] for i in out["items"]}

    def test_four_paths_give_the_same_sale_price(self):
        want = {pc: expected_sale(pc) for pc in PRODUCTS}
        self.assertEqual(self.path_bulk_reprice(), want, "① 대량 재산정")
        self.assertEqual(self.path_reprice_adapter(), want, "② 단가표 반영 · ③ 승인 · ④ 소싱 (공용 어댑터)")
        self.assertEqual(self.path_price_review_proposal(), want, "③ 가격 검토 제안가")

    def test_approve_and_sourcing_route_through_the_same_adapter(self):
        """③ 승인과 ④ 소싱이 다른 계산으로 새지 않는지 — 공용 어댑터를 부르는지 본다."""
        review = ast.parse((ROOT / "api/admin_price_review.py").read_text(encoding="utf-8"))
        decide = next(n for n in review.body if isinstance(n, ast.FunctionDef) and n.name == "decide")
        calls = {n.func.id for n in ast.walk(decide) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("_reprice", calls)
        self.assertNotIn("sale_from_purchase", calls)
        imports = {(n.module, a.name) for n in review.body if isinstance(n, ast.ImportFrom) for a in n.names}
        self.assertIn(("admin_price_import", "_reprice"), imports)

        sourcing = ast.parse((ROOT / "api/admin_sourcing.py").read_text(encoding="utf-8"))
        tx = next(n for n in sourcing.body if isinstance(n, ast.FunctionDef) and n.name == "_confirm_quote_tx")
        kw = {k.arg: k.value.id for n in ast.walk(tx) if isinstance(n, ast.Call)
              for k in n.keywords if isinstance(k.value, ast.Name)}
        self.assertEqual(kw.get("reprice"), "_reprice")
        imports = {(n.module, a.name) for n in sourcing.body if isinstance(n, ast.ImportFrom) for a in n.names}
        self.assertIn(("admin_price_import", "_reprice"), imports)

    def test_locked_sale_price_is_still_left_alone(self):
        env = extract("api/admin_price_import.py", ["_reprice"],
                      {"_reprice_core": reprice, "product_margin": product_margin,
                       "current_operator_id": lambda: 1})
        conn = FakeConn(sale=777_000, locked=["sale_price"])
        out = env["_reprice"](conn, 101, FEE, GLOBAL, "price_import", 1)
        self.assertTrue(out["sale_locked"])
        self.assertEqual(conn.products[101]["sale_price"], 777_000)


if __name__ == "__main__":
    unittest.main()
