"""상품 관리 재고상태 필터 「재고 있음」·「10개 이하」 (2026-11-03 ADMIN-REMAINING-BATCH1 묶음1A).

정의는 승인 디자인(docs/design/incoming/dc-product-unified-admin.html) 그대로다 —
재고 있음 = stock_qty > 0 · 10개 이하 = stock_qty <= 10(0·음수 포함). 「재고 없음」은 이 축이
아니라 기존 status=oos 버킷(상태 탭)을 쓴다.

DB 검사는 루프백 Postgres 안의 «격리 스키마»에 목록 쿼리가 읽는 칸만 만들어 실제 SQL
(_QUERY·_COUNT·_KPI)을 돌린다 — 실제 상품 DB 에는 닿지 않는다. CI(POPCORN_CI=1)에서는
연결이 안 되면 건너뛰지 않고 실패한다.
"""
import os
import re
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://ci:ci@127.0.0.1:1/ci")

from api import admin_products as AP                              # noqa: E402
from api import admin_ui_price_review as PRUI                     # noqa: E402
from api import auth                                              # noqa: E402

TEMPLATE = (ROOT / "templates/admin/products.html.j2").read_text(encoding="utf-8")


def _db_url():
    url = os.environ.get("DATABASE_URL") or ""
    from sqlalchemy.engine import make_url
    try:
        u = make_url(url)
    except Exception:                                               # noqa: BLE001
        return None
    if u.host not in ("127.0.0.1", "localhost", "::1"):
        return None                     # 루프백이 아니면(실제 DB) 절대 쓰지 않는다
    from sqlalchemy import create_engine, text
    try:
        with create_engine(u).connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:                                               # noqa: BLE001
        if os.environ.get("POPCORN_CI") == "1":
            raise
        return None
    return u


# 경계 표본 — (상품코드, 재고). 9006 은 «미확인»(NULL) — 실제 칸은 NOT NULL 이지만 격리
# 스키마에서는 NULL 을 넣어 0 으로 바뀌지 않는지 본다.
STOCK = {9001: -1, 9002: 0, 9003: 1, 9004: 10, 9005: 11, 9006: None}
IN_STOCK = {9003, 9004, 9005}
LOW = {9001, 9002, 9003, 9004}

SCHEMA_SQL = (
    "CREATE TABLE categories (category_id BIGINT PRIMARY KEY, parent_id BIGINT)",
    "CREATE TABLE products (product_code BIGINT PRIMARY KEY, sku TEXT, product_name TEXT NOT NULL,"
    " maker TEXT, part_type TEXT NOT NULL, status TEXT NOT NULL, review_required_yn BOOLEAN NOT NULL,"
    " sale_price BIGINT, stock_qty INTEGER, data_origin TEXT NOT NULL, is_visible BOOLEAN NOT NULL,"
    " category_id BIGINT)",
    "CREATE TABLE product_specs (product_code BIGINT PRIMARY KEY)",
    "CREATE TABLE product_supplier_prices (product_code BIGINT, supplier_id BIGINT)",
)


@unittest.skipUnless(_db_url(), "루프백 Postgres 가 없어 DB 검사를 건너뜁니다(CI 에서는 실패)")
class StockFilterOnPostgres(unittest.TestCase):
    def setUp(self):
        from sqlalchemy import create_engine, text
        self.text = text
        self.url = _db_url()
        self.schema = "stock_filter_t_" + uuid.uuid4().hex[:12]
        with create_engine(self.url).begin() as c:
            c.execute(text('CREATE SCHEMA "%s"' % self.schema))
        self.engine = create_engine(self.url, connect_args={"options": "-csearch_path=%s" % self.schema})
        with self.engine.begin() as c:
            for stmt in SCHEMA_SQL:
                c.execute(text(stmt))
            for code, qty in STOCK.items():
                c.execute(text(
                    "INSERT INTO products VALUES (:c, :s, :n, :m, 'CPU', '판매중', false, 1000, :q, 'demo', :v, NULL)"),
                    {"c": code, "s": "S-%d" % code, "n": "격리 상품 %d" % code,
                     "m": "갑" if code % 2 else "을", "q": qty, "v": code != 9004})
        self.patches = [mock.patch.object(AP, "engine", self.engine),
                        mock.patch.object(AP, "required_fields", lambda part_type: [])]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.engine.dispose()
        from sqlalchemy import create_engine
        with create_engine(self.url).begin() as c:
            c.execute(self.text('DROP SCHEMA "%s" CASCADE' % self.schema))

    def codes(self, **kw):
        out = AP.list_products(size=500, **kw)
        got = {it["product_code"] for it in out["items"]}
        self.assertEqual(out["total"], len(got), "총건수 = 목록 행 수(한 페이지에 다 들어올 때)")
        return got, out

    def test_boundaries_match_design_definition(self):
        got, _ = self.codes(stock="in")
        self.assertEqual(got, IN_STOCK, "재고 있음: 1·10·11 만, -1·0·NULL 제외")
        got, _ = self.codes(stock="low")
        self.assertEqual(got, LOW, "10개 이하: -1·0·1·10, 11·NULL 제외")

    def test_unknown_stock_is_not_turned_into_zero(self):
        for v in ("in", "low"):
            with self.subTest(stock=v):
                got, _ = self.codes(stock=v)
                self.assertNotIn(9006, got)
        got, _ = self.codes()
        self.assertIn(9006, got, "필터가 없으면 미확인 행도 그대로 보인다")

    def test_blank_or_unknown_value_is_no_filter(self):
        everything, _ = self.codes()
        self.assertEqual(everything, set(STOCK))
        for v in ("", "  ", "x", "oos", "IN "):
            with self.subTest(stock=v):
                got, _ = self.codes(stock=v)
                self.assertEqual(got, set(STOCK) if v.strip().lower() not in ("in", "low") else IN_STOCK)

    def test_tab_counts_use_same_condition(self):
        _, out = self.codes(stock="low")
        self.assertEqual(out["kpis"]["total"], len(LOW), "상태 탭 건수(KPI)도 같은 조건으로 센다")
        # 재고 0 은 oos 버킷 — 10개 이하 안에서 oos 탭 건수와 실제 oos 목록이 같아야 한다
        oos, _ = self.codes(stock="low", status="oos")
        self.assertEqual(out["kpis"]["oos"], len(oos))
        self.assertEqual(oos, {9002})

    def test_combines_with_other_conditions(self):
        got, _ = self.codes(stock="in", maker="갑")
        self.assertEqual(got, {9003, 9005})
        got, _ = self.codes(stock="low", visible="off")
        self.assertEqual(got, {9004})
        got, _ = self.codes(stock="in", q="9005")
        self.assertEqual(got, {9005})
        got, _ = self.codes(stock="in", status="oos")
        self.assertEqual(got, set(), "재고 있음 + 재고 없음 탭은 겹치는 상품이 없다")

    def test_pages_split_the_same_filtered_set(self):
        seen, total = [], None
        for page in (1, 2, 3):
            out = AP.list_products(stock="low", size=2, page=page)
            total = out["total"]
            seen += [it["product_code"] for it in out["items"]]
        self.assertEqual(total, len(LOW))
        self.assertEqual(sorted(seen), sorted(LOW), "페이지를 넘겨도 빠지거나 겹치는 행이 없다")


class ContractTests(unittest.TestCase):
    def test_read_permission_unchanged(self):
        self.assertEqual(auth.required_role("GET", "/api/admin/products"), "viewer")

    def test_filter_lives_in_shared_where(self):
        self.assertIn(":stock = 'in' AND p.stock_qty > 0", AP._WHERE)
        self.assertIn(":stock = 'low' AND p.stock_qty <= 10", AP._WHERE)
        for q in (AP._QUERY, AP._COUNT, AP._KPI):
            self.assertIn(":stock", str(q), "목록·총건수·탭 건수가 같은 조건을 쓴다")

    def test_price_review_return_keeps_stock_state(self):
        href = PRUI.products_return_href("tab=review&stock=low&page=2")
        self.assertEqual(href, "/admin2/products?tab=review&stock=low&page=2")
        self.assertEqual(PRUI.products_return_href("stock=evil"), "/admin2/products")


class ScreenTests(unittest.TestCase):
    def test_options_are_selectable(self):
        sel = re.search(r'<select id="fstock".*?</select>', TEMPLATE, re.S).group(0)
        self.assertIn('<option value="in">재고 있음</option>', sel)
        self.assertIn('<option value="low">10개 이하</option>', sel)
        self.assertNotIn("disabled", sel)
        self.assertNotIn("미연결", sel)

    def test_state_is_sent_restored_and_cleared(self):
        self.assertIn('url += "&stock=" + encodeURIComponent(stockSel)', TEMPLATE)        # 서버로 보낸다
        self.assertIn('if(stockSel) sp.set("stock", stockSel);', TEMPLATE)                  # 주소에 남긴다
        self.assertIn('var st = sp.get("stock")', TEMPLATE)                                 # 주소에서 되살린다
        self.assertIn('stockSel = (cur !== "oos" && (st === "in" || st === "low")) ? st : "";', TEMPLATE)
        self.assertIn('visible=""; saleStatusSel={}; stockSel="";', TEMPLATE)               # 초기화
        self.assertIn('else if(k==="stock"){ stockSel=""; syncStockSelect(); }', TEMPLATE)  # 칩 해제
        self.assertIn('if(cur==="oos") stockSel="";', TEMPLATE)                            # 탭 재고 없음과 동시 금지
        self.assertIn('sel.value = (cur==="oos") ? "oos" : stockSel;', TEMPLATE)


if __name__ == "__main__":
    unittest.main()
