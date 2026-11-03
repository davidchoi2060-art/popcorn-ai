"""ADMIN-BRAND-B1 — 상품 브랜드(products.brand VARCHAR(100), NULL 허용) 수정·조회 연결 (2026-11-03).

무엇을 증명하나 (DB 없이 — 가짜 연결로 SQL 과 인자만 본다, 실제 상품에 쓰지 않는다):
  ① 99·100자(한글 포함)는 저장되고 101자는 «자르지 않고» 400 — 조회조차 하지 않는다.
  ② 앞뒤 공백을 걷고, 빈 칸·공백만·null 은 NULL(지움). null 이 문자열 "None" 으로 저장되지 않는다.
  ③ 문자열이 아닌 값(숫자·참거짓·목록·객체)은 400.
  ④ 잘못된 brand 가 다른 필드와 섞인 PATCH 는 전체 거부 — 값·감사·잠금 변화 0.
  ⑤ 저장은 감사(before/changes)와 잠금(locked_fields)을 남기고, 같은 값이면 쓰지 않는다.
  ⑥ 되돌리기는 브랜드 값과 잠금을 함께 되돌린다.
  ⑦ 상세 조회가 brand 를 낸다 · 쓰기는 운영자 이상 · 적재는 brand 를 쓰지 않는다 · 확인 창은 기존 저장 경로를 쓴다.
"""
import json
import os
import re
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://ci:ci@127.0.0.1:1/ci")

from fastapi import HTTPException  # noqa: E402

from api import admin_orders, admin_products as P  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None


class Conn:
    """patch_product · undo_product_edit 가 보내는 SQL 만 흉내 낸다(격리 — 실제 DB 없음)."""

    def __init__(self, product, log=None):
        self.product = dict(product)
        self.log = log
        self.sql = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, stmt, params=None):
        q = str(stmt)
        self.sql.append((q, dict(params or {})))
        if "FROM admin_operator_activity_logs WHERE log_id" in q:
            return Rows([self.log] if self.log else [])
        if "action='product_edit_undo'" in q:
            return Rows([])
        if q.startswith("SELECT") and "FROM products WHERE product_code=:pc" in q:
            return Rows([dict(self.product)])
        if q.startswith("UPDATE products SET"):
            for k, v in params.items():
                if k == "lf":
                    self.product["locked_fields"] = json.loads(v)
                elif k in P.EDITABLE:
                    self.product[P.EDITABLE[k][0]] = v
            return Rows([])
        if "v_recommendation_candidates" in q:
            return Rows([])
        raise AssertionError("예상하지 못한 SQL: " + q)

    def updates(self):
        return [(q, p) for q, p in self.sql if q.startswith("UPDATE")]


PRODUCT = dict(product_code=130001, sku="S-130001", product_name="합성 상품", maker="갑", supplier=None,
               purchase_price=None, sale_price=900000, stock_qty=1, status="판매중", model_name=None,
               danawa_code=None, market_price=None, is_visible=True, brand=None, locked_fields=[])


def run_patch(changes, product=PRODUCT):
    conn = Conn(product)
    logged = []
    with mock.patch.object(P, "engine", mock.Mock(begin=lambda: conn)), \
         mock.patch.object(admin_orders, "_log", side_effect=lambda c, a, t, d, kind=None: logged.append((a, d)) or 77), \
         mock.patch.object(P, "current_operator_id", return_value=1):
        out = P.patch_product(130001, P.PatchBody(changes=changes))
    return out, conn, logged


def rejected(test, changes):
    conn = Conn(PRODUCT)
    with mock.patch.object(P, "engine", mock.Mock(begin=lambda: conn)):
        with test.assertRaises(HTTPException) as e:
            P.patch_product(130001, P.PatchBody(changes=changes))
    test.assertEqual(e.exception.status_code, 400)
    test.assertEqual(conn.sql, [], "조회·쓰기 전에 멈춘다")
    return e.exception.detail


class BrandInputTests(unittest.TestCase):
    def test_99_and_100_chars_including_korean_are_saved(self):
        for v in ("가" * 99, "가" * 100, "Ab가" * 33 + "x"):
            with self.subTest(n=len(v)):
                out, conn, _ = run_patch({"brand": v})
                self.assertEqual(out["changed"], 1)
                self.assertEqual(conn.product["brand"], v)

    def test_101_chars_rejected_not_truncated(self):
        for v in ("가" * 101, "a" * 101, " " + "가" * 101 + " "):
            with self.subTest(n=len(v)):
                detail = rejected(self, {"brand": v})
                self.assertIn("100자", detail)
                self.assertIn("101자", detail)

    def test_trim_and_blank_to_null(self):
        out, conn, _ = run_patch({"brand": "  삼성전자  "})
        self.assertEqual(conn.product["brand"], "삼성전자")
        for blank in ("", "   ", None):
            with self.subTest(blank=blank):
                out, conn, logged = run_patch({"brand": blank}, dict(PRODUCT, brand="기존"))
                self.assertEqual(out["changed"], 1)
                self.assertIsNone(conn.product["brand"])
                self.assertIsNone(logged[0][1]["changes"]["brand"]["to"])

    def test_null_never_becomes_text_none(self):
        self.assertIsNone(P.EDITABLE["brand"][1](None))
        _, conn, _ = run_patch({"brand": None}, dict(PRODUCT, brand="기존"))
        self.assertNotEqual(conn.product["brand"], "None")

    def test_non_string_rejected(self):
        for bad in (5, 0, True, False, 1.5, [], {}, ["a"]):
            with self.subTest(value=bad):
                rejected(self, {"brand": bad})

    def test_mixed_patch_with_bad_brand_is_rejected_whole(self):
        rejected(self, {"maker": "을", "sale_price": 1000, "brand": "x" * 101})
        rejected(self, {"is_visible": False, "brand": 7})


class BrandLedgerTests(unittest.TestCase):
    def test_save_logs_before_changes_and_locks(self):
        out, conn, logged = run_patch({"brand": "ASUS"})
        self.assertEqual(out["undo_id"], 77)
        self.assertEqual(len(conn.updates()), 1)
        self.assertIn("brand = :brand", conn.updates()[0][0])
        self.assertEqual(conn.product["locked_fields"], ["brand"])
        self.assertEqual(logged, [("product_edit", {
            "product_code": 130001, "sku": "S-130001",
            "changes": {"brand": {"from": None, "to": "ASUS"}},
            "before": {"locked_fields": []}, "locked": True})])

    def test_same_value_writes_nothing(self):
        out, conn, logged = run_patch({"brand": " ASUS "}, dict(PRODUCT, brand="ASUS"))
        self.assertEqual(out["changed"], 0)
        self.assertEqual((conn.updates(), logged), ([], []))

    def test_maker_is_not_touched(self):
        _, conn, logged = run_patch({"brand": "ROG"})
        self.assertEqual(conn.product["maker"], "갑")
        self.assertEqual(list(logged[0][1]["changes"]), ["brand"])

    def test_undo_restores_value_and_lock(self):
        log = {"action": "product_edit", "detail": {
            "product_code": 130001, "sku": "S-130001",
            "changes": {"brand": {"from": "옛 브랜드", "to": "새 브랜드"}},
            "before": {"locked_fields": []}, "locked": True}}
        conn = Conn(dict(PRODUCT, brand="새 브랜드", locked_fields=["brand"]), log)
        logged = []
        with mock.patch.object(P, "engine", mock.Mock(begin=lambda: conn)), \
             mock.patch.object(P, "_lock_restore_products", return_value=None), \
             mock.patch.object(admin_orders, "_log", side_effect=lambda c, a, t, d, kind=None: logged.append((a, d)) or 78), \
             mock.patch.object(P, "current_operator_id", return_value=1):
            out = P.undo_product_edit(77)
        self.assertEqual(out, {"ok": True, "restored": 1})
        self.assertEqual(conn.product["brand"], "옛 브랜드")
        self.assertEqual(conn.product["locked_fields"], [])
        self.assertEqual((logged[0][0], logged[0][1]["ref_log_id"]), ("product_edit_undo", 77))


class ContractTests(unittest.TestCase):
    SRC = (ROOT / "api" / "admin_products.py").read_text(encoding="utf-8")

    def test_detail_reads_and_returns_brand(self):
        body = self.SRC.split("def get_product", 1)[1].split("class PatchBody", 1)[0]
        self.assertIn("p.brand", body)
        self.assertIn('"brand": r["brand"]', body)

    def test_patch_reads_current_brand_under_lock(self):
        body = self.SRC.split("def patch_product", 1)[1]
        self.assertRegex(body, r"is_visible, brand, locked_fields\"\s*\n\s*\" FROM products WHERE product_code=:pc FOR UPDATE")

    def test_permissions_unchanged(self):
        from api.auth import required_role
        self.assertEqual(required_role("PATCH", "/api/admin/products/130001"), "operator")
        self.assertEqual(required_role("GET", "/api/admin/products/130001"), "viewer")

    def test_catalog_ingest_never_writes_brand(self):
        ingest = (ROOT / "api" / "catalog_ingest.py").read_text(encoding="utf-8")
        # 적재가 brand 를 쓰기 시작하면 locked_fields ? 'brand' 가드가 필요하다 — 이 검사가 그 날을 알린다
        self.assertIsNone(re.search(r"\bbrand\b", ingest))

    def test_register_path_unchanged(self):
        reg = self.SRC.split("class RegisterBody", 1)[1].split("def ", 1)[0]
        self.assertNotIn("brand", reg, "등록(B-2)은 이번 범위 밖")


class DrawerTests(unittest.TestCase):
    TPL = (ROOT / "templates" / "admin" / "products.html.j2").read_text(encoding="utf-8")

    def test_brand_row_in_basic_fields_after_maker(self):
        self.assertIn('["maker","제조사","text","maker"],', self.TPL)
        self.assertIn('["brand","브랜드","text","brand"]', self.TPL)
        self.assertLess(self.TPL.index('["maker","제조사"'), self.TPL.index('["brand","브랜드"'))

    def test_uses_existing_save_path_only(self):
        # 기존 상품 수정 PATCH 로 함께 저장된다 — 새 쓰기 요청을 만들지 않는다(PR431 때와 같은 8건)
        self.assertEqual(len(re.findall(r'method *: *"(?:POST|PATCH|PUT|DELETE)"', self.TPL)), 8)
        collect = self.TPL.split("function collectBasicChanges", 1)[1].split("function onDrSaveClick", 1)[0]
        self.assertIn("else { out[k]=v; }", collect, "brand 는 입력값 문자열 그대로 보낸다(빈 칸 = 지움)")


if __name__ == "__main__":
    unittest.main()
