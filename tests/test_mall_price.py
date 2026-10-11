# -*- coding: utf-8 -*-
"""쇼핑몰 가격 반영(api/mall_price.py) — 파일 읽기 · 비교 · 적용 · 되돌리기.

파일 읽기는 DB 없이 돈다. 적용·되돌리기는 **루프백 주소의 Postgres** 가 DATABASE_URL 로
주어졌을 때만(CI 의 임시 Postgres · 개발 PC 의 로컬 DB) 이 테스트 전용 스키마를 만들어
돌리고 끝나면 지운다. Cloud SQL 같은 원격 주소면 건너뛴다 — 검사가 정본을 쓰지 않는다.
"""
import io
import json
import os
import unittest
import uuid

from api import mall_price as MP


def _csv(rows, enc="utf-8-sig"):
    return "\n".join(",".join(str(c) for c in r) for r in rows).encode(enc)


class ReadFileTests(unittest.TestCase):
    HEAD = ["자체상품코드", "상품명", "카테고리1", "일반회원", "시중가"]

    def test_csv_utf8_reads_code_and_general_member_price(self):
        raw = _csv([self.HEAD, [98149, "골드 NO.04", "프리미엄 피씨", "\"1,624,400\"", 1830000],
                    [121509, "B", "x", 1780600, 0]])
        out = MP.read_price_file(raw)
        self.assertEqual(out["prices"], {98149: 1624400, 121509: 1780600})
        self.assertEqual(out["columns"]["price"], "일반회원")
        self.assertEqual(out["format"], "csv")

    def test_csv_cp949_is_accepted(self):
        out = MP.read_price_file(_csv([self.HEAD, [1, "가", "나", 1000, 0]], enc="cp949"))
        self.assertEqual(out["prices"], {1: 1000})

    def test_zero_or_blank_price_rows_are_counted_not_used(self):
        out = MP.read_price_file(_csv([self.HEAD, [1, "a", "x", 0, 0], [2, "b", "x", "", 0],
                                       [3, "c", "x", 500, 0]]))
        self.assertEqual(out["prices"], {3: 500})
        self.assertEqual(out["bad_rows"], 2)

    def test_header_below_title_rows_and_html_table(self):
        html = ("<html><body><table><tr><td>상품 목록</td></tr>"
                "<tr><th>상품번호</th><th>품명</th><th>판매가</th></tr>"
                "<tr><td>98149</td><td>골드</td><td>1,624,400</td></tr></table></body></html>")
        out = MP.read_price_file(html.encode("cp949"))
        self.assertEqual(out["prices"], {98149: 1624400})
        self.assertEqual(out["format"], "html")

    def test_xlsx(self):
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(self.HEAD)
        ws.append([98149, "골드", "x", 1624400, 1830000])
        buf = io.BytesIO()
        wb.save(buf)
        self.assertEqual(MP.read_price_file(buf.getvalue())["prices"], {98149: 1624400})

    def test_missing_columns_are_refused_with_plain_message(self):
        with self.assertRaises(MP.PriceFileError) as e:
            MP.read_price_file(_csv([["이름", "가격"], ["a", 1]]))
        self.assertIn("상품코드 열", str(e.exception))
        with self.assertRaises(MP.PriceFileError):
            MP.read_price_file(_csv([["자체상품코드", "상품명"], [1, "a"]]))
        with self.assertRaises(MP.PriceFileError):
            MP.read_price_file(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 100)


def _local_url():
    url = os.environ.get("DATABASE_URL") or ""
    if not url:
        return None
    from sqlalchemy.engine import make_url
    try:
        u = make_url(url)
    except Exception:                                               # noqa: BLE001
        return None
    return u if u.host in ("127.0.0.1", "localhost", "::1") else None


SCHEMA_SQL = """
CREATE TABLE products (product_code BIGINT PRIMARY KEY, product_name TEXT, part_type TEXT NOT NULL,
  sale_price BIGINT, locked_fields JSONB NOT NULL DEFAULT '[]', updated_at TIMESTAMP);
CREATE TABLE product_price_history (history_id BIGSERIAL PRIMARY KEY, product_code BIGINT,
  field VARCHAR(20), old_price BIGINT, new_price BIGINT, reason VARCHAR(30), ref_id BIGINT,
  changed_by BIGINT, changed_at TIMESTAMP DEFAULT now());
CREATE TABLE admin_operator_activity_logs (log_id BIGSERIAL PRIMARY KEY, operator_id BIGINT,
  action TEXT, target_kind TEXT, target_id TEXT, detail JSONB);
"""


@unittest.skipUnless(_local_url(), "루프백 Postgres 가 없어 DB 검사를 건너뜁니다")
class ApplyUndoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sqlalchemy import create_engine, text
        cls.text = staticmethod(text)
        cls.schema = "mall_price_t_" + uuid.uuid4().hex[:12]
        cls.engine = create_engine(_local_url())
        mig = os.path.join(os.path.dirname(__file__), "..", "db", "migrations", "versions",
                           "0145_mall_price_checks.py")
        src = io.open(mig, encoding="utf-8").read()
        # 마이그레이션의 CREATE 문을 그대로 쓴다(사본을 두지 않는다)
        cls.ddl = [s for s in _upgrade_sql(src)]
        with cls.engine.begin() as c:
            c.execute(text('CREATE SCHEMA "%s"' % cls.schema))
            c.execute(text('SET search_path TO "%s"' % cls.schema))
            for stmt in SCHEMA_SQL.split(";"):
                if stmt.strip():
                    c.execute(text(stmt))
            for stmt in cls.ddl:
                c.execute(text(stmt))

    @classmethod
    def tearDownClass(cls):
        with cls.engine.begin() as c:
            c.execute(cls.text('DROP SCHEMA "%s" CASCADE' % cls.schema))
        cls.engine.dispose()

    def conn(self):
        cm = self.engine.begin()
        c = cm.__enter__()
        c.execute(self.text('SET LOCAL search_path TO "%s"' % self.schema))
        self.addCleanup(cm.__exit__, None, None, None)
        return c

    def seed(self, c, rows):
        c.execute(self.text("TRUNCATE products, product_price_history, mall_price_checks,"
                            " mall_price_runs, admin_operator_activity_logs CASCADE"))
        for pc, pt, price, locked in rows:
            c.execute(self.text(
                "INSERT INTO products (product_code, product_name, part_type, sale_price, locked_fields)"
                " VALUES (:pc, :n, :pt, :p, CAST(:l AS JSONB))"),
                {"pc": pc, "n": "상품%d" % pc, "pt": pt, "p": price, "l": json.dumps(locked)})

    def test_plan_scope_lock_same_and_not_found(self):
        c = self.conn()
        self.seed(c, [(1, "PC_COMPLETE", 1000, []), (2, "PC_COMPLETE", 2000, ["sale_price"]),
                      (3, "PC_COMPLETE", 3000, []), (4, "GPU", 400, [])])
        plan = MP.build_plan(c, {1: 1100, 2: 2500, 3: 3000, 4: 500, 9: 1})
        self.assertEqual([x["product_code"] for x in plan["changes"]], [1])
        self.assertEqual([x["product_code"] for x in plan["locked"]], [2])
        self.assertEqual((plan["same"], plan["out_of_scope"], plan["not_found"]), (1, 1, [9]))
        self.assertEqual((plan["up"], plan["down"]), (1, 0))
        with_parts = MP.build_plan(c, {1: 1100, 4: 500}, include_parts=True)
        self.assertEqual(sorted(x["product_code"] for x in with_parts["changes"]), [1, 4])

    def test_apply_writes_history_checks_and_undo_restores(self):
        c = self.conn()
        self.seed(c, [(98149, "PC_COMPLETE", 1585100, []), (121509, "PC_COMPLETE", 1779200, []),
                      (2, "PC_COMPLETE", 2000, ["sale_price"])])
        plan = MP.build_plan(c, {98149: 1624400, 121509: 1700000, 2: 2500})
        run = MP.start_run(c, "file", source="file", operator_id=7, file_name="a.csv")
        res = MP.apply_changes(c, plan["changes"] + plan["locked"], moment="file",
                               operator_id=7, run_id=run)
        self.assertEqual((res["changed"], res["locked"], res["up"], res["down"]), (2, 1, 1, 1))
        MP.finish_run(c, run, ok=True, apply_log_id=res["log_id"], counts={"changed": 2})
        prices = dict(c.execute(self.text("SELECT product_code, sale_price FROM products")).all())
        self.assertEqual(prices, {98149: 1624400, 121509: 1700000, 2: 2000})
        hist = c.execute(self.text(
            "SELECT product_code, old_price, new_price, reason, ref_id FROM product_price_history"
            " ORDER BY product_code")).all()
        self.assertEqual([tuple(h[:4]) for h in hist],
                         [(98149, 1585100, 1624400, "mall_price_file"),
                          (121509, 1779200, 1700000, "mall_price_file")])
        self.assertTrue(all(h[4] == res["log_id"] for h in hist))
        outcomes = dict(c.execute(self.text(
            "SELECT product_code, outcome FROM mall_price_checks WHERE run_id=:r"), {"r": run}).all())
        self.assertEqual(outcomes, {98149: "changed", 121509: "changed", 2: "locked"})

        # 그 사이 다른 경로가 121509 를 바꿨다 -> 되돌리기는 그 상품을 덮지 않는다
        c.execute(self.text("UPDATE products SET sale_price=1750000 WHERE product_code=121509"))
        out = MP.undo_run(c, run, operator_id=7)
        self.assertEqual((out["restored"], out["skipped"]), (1, 1))
        prices = dict(c.execute(self.text("SELECT product_code, sale_price FROM products")).all())
        self.assertEqual(prices[98149], 1585100)
        self.assertEqual(prices[121509], 1750000)
        undo = c.execute(self.text(
            "SELECT reason FROM product_price_history WHERE reason LIKE '%_undo'")).scalars().all()
        self.assertEqual(undo, ["mall_price_file_undo"])
        with self.assertRaises(MP.UndoRefused):
            MP.undo_run(c, run, operator_id=7)

    def test_undo_skips_a_round_trip_by_another_path(self):
        # 코덱스 검수 #99: 다른 경로가 바꿨다가 같은 값으로 돌아오면 값만 봐서는 모른다
        c = self.conn()
        self.seed(c, [(1, "PC_COMPLETE", 1000, []), (2, "PC_COMPLETE", 2000, [])])
        plan = MP.build_plan(c, {1: 1100, 2: 2200})
        run = MP.start_run(c, "file", source="file", operator_id=7, file_name="a.csv")
        res = MP.apply_changes(c, plan["changes"], moment="file", operator_id=7, run_id=run)
        MP.finish_run(c, run, ok=True, apply_log_id=res["log_id"], counts={"changed": 2})
        # 장바구니 재확인이 1 을 1150 으로 바꿨다가, 다음 재확인이 다시 1100 으로 돌렸다
        later = MP.apply_changes(c, [{"product_code": 1, "old": 1100, "new": 1150, "diff": 50}],
                                 moment="cart", operator_id=None)
        self.assertEqual(later["changed"], 1)
        MP.apply_changes(c, [{"product_code": 1, "old": 1150, "new": 1100, "diff": -50}],
                         moment="cart", operator_id=None)
        out = MP.undo_run(c, run, operator_id=7)
        self.assertEqual((out["restored"], out["skipped"], out["skipped_codes"]), (1, 1, [1]))
        prices = dict(c.execute(self.text("SELECT product_code, sale_price FROM products")).all())
        self.assertEqual(prices, {1: 1100, 2: 2000})

    def test_stale_and_hold_big(self):
        c = self.conn()
        self.seed(c, [(1, "PC_COMPLETE", 1000, []), (2, "PC_COMPLETE", 1000, [])])
        plan = MP.build_plan(c, {1: 1050, 2: 5000})
        c.execute(self.text("UPDATE products SET sale_price=1010 WHERE product_code=1"))
        res = MP.apply_changes(c, plan["changes"], moment="auto", operator_id=1, hold_big=True)
        self.assertEqual((res["changed"], res["stale"], res["held"]), (0, 1, 1))
        self.assertIsNone(res["log_id"])
        self.assertEqual(c.execute(self.text(
            "SELECT count(*) FROM product_price_history")).scalar(), 0)

    def test_token_changes_when_current_price_changes(self):
        c = self.conn()
        self.seed(c, [(1, "PC_COMPLETE", 1000, [])])
        t1 = MP.build_plan(c, {1: 1100})["token"]
        c.execute(self.text("UPDATE products SET sale_price=1050 WHERE product_code=1"))
        self.assertNotEqual(t1, MP.build_plan(c, {1: 1100})["token"])


class ReaderTests(unittest.TestCase):
    """공개 페이지 읽기 — 네트워크 없이 응답 원문만 바꿔 끼운다."""

    def _with_body(self, body: bytes):
        from unittest.mock import patch

        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return patch("urllib.request.urlopen", lambda req, timeout=0: R(body))

    def test_pc_page_reads_sale_price(self):
        from api import mall_price_reader as RD
        from tools.mall_builtpc_fetch import _FIXTURE
        with self._with_body(_FIXTURE.encode("cp949")):
            r = RD.read_price(98149, "PC_COMPLETE", timeout=1)
        self.assertEqual((r["ok"], r["price"]), (True, 1591800))
        self.assertIn("system_detail.html?pd_no=98149", r["url"])

    def test_pc_page_without_price_is_failure_not_guess(self):
        from api import mall_price_reader as RD
        with self._with_body("<html>없음</html>".encode("cp949")):
            r = RD.read_price(98149, "PC_COMPLETE", timeout=1)
        self.assertEqual((r["ok"], r["price"]), (False, None))

    def test_part_page_uses_hidden_price(self):
        from api import mall_price_reader as RD
        html = ('<input type="hidden" name="pd_no" value="111">'
                '<input type="hidden" name="price" value="410000">').encode()
        with self._with_body(html):
            r = RD.read_price(111, "GPU", timeout=1)
        self.assertEqual((r["ok"], r["price"]), (True, 410000))

    def test_part_read_passes_its_own_timeout_without_touching_the_global(self):
        # 코덱스 검수 #99: 전역 mall.TIMEOUT 을 잠깐 바꾸면 동시에 도는 다른 요청의 제한도 바뀐다
        from api import mall, mall_price_reader as RD
        seen = []
        html = ('<input type="hidden" name="pd_no" value="111">'
                '<input type="hidden" name="price" value="410000">').encode()

        class Body(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake(req, timeout=0):
            seen.append((timeout, mall.TIMEOUT))
            return Body(html)
        before = mall.TIMEOUT
        from unittest.mock import patch
        with patch("urllib.request.urlopen", fake):
            RD.read_price(111, "GPU", timeout=2.5)
        self.assertEqual(seen, [(2.5, before)])
        self.assertEqual(mall.TIMEOUT, before)


def _upgrade_sql(src: str):
    """마이그레이션 upgrade() 안의 op.execute 문자열을 꺼낸다(실행하지 않고 AST 로 읽는다)."""
    import ast
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade")
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "execute":
            out.append(ast.literal_eval(node.args[0]))
    return out


if __name__ == "__main__":
    unittest.main()
