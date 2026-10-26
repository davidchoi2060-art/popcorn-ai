"""ADM-H1-20261027 — 상품 관리 → 선택 상품 가격 검토 → 목록 복귀의 서버 계약.

계약 원문: outputs/office-admin-h1-20261027/claude/contract.json
  C-1  GET /api/admin/price-review/target/{product_code} — 읽기 전용 단건 대상 판정
  E-1  GET /admin2/price-review?code=&ret= — code·ret 정제 후 템플릿에 넘김

DB 없이 돈다: 엔진을 가짜로 바꿔 «어떤 SQL 을 보냈는지»와 «받은 행을 어떻게 옮겼는지»를 본다.
판정 술어 자체는 PENDING 문자열을 그대로 쓰는지로 확인한다(같은 정의를 두 벌 두지 않는다).
"""
import datetime as dt
import os
import unittest
from unittest import mock

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://ci:ci@127.0.0.1:5432/ci")

from fastapi import FastAPI, HTTPException                      # noqa: E402
from fastapi.testclient import TestClient                       # noqa: E402

from api import admin_price_review as PR                        # noqa: E402
from api import admin_ui_price_review as UI                     # noqa: E402
from api import auth                                            # noqa: E402

KST = dt.timezone(dt.timedelta(hours=9))


class _Conn:
    def __init__(self, row, log):
        self.row, self.log = row, log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, stmt, params=None):
        self.log.append((str(stmt), dict(params or {})))
        row = self.row

        class _R:
            def mappings(self_inner):
                return self_inner

            def first(self_inner):
                return row
        return _R()


class _Engine:
    def __init__(self, row):
        self.row, self.log = row, []

    def connect(self):
        return _Conn(self.row, self.log)

    def begin(self):                                             # 쓰기 트랜잭션 — 이 경로에서 열리면 안 된다
        raise AssertionError("price-review target 은 쓰기 트랜잭션을 열지 않는다")


def _row(**over):
    base = {"product_code": 123456, "sku": "P-123456", "product_name": "예시 상품", "sale_price": None,
            "status": "판매중", "in_queue": True, "has_price": False, "review_required": False,
            "price_locked": False, "reason": "in_queue",
            "checked_at": dt.datetime(2026, 10, 27, 9, 0, tzinfo=KST)}
    base.update(over)
    return base


class TargetEndpointTests(unittest.TestCase):
    def call(self, row, code=123456):
        eng = _Engine(row)
        with mock.patch.object(PR, "engine", eng):
            out = PR.price_review_target(code)
        return out, eng

    def test_in_queue(self):
        out, _ = self.call(_row())
        self.assertTrue(out["in_queue"])
        self.assertEqual(out["reason"], "in_queue")
        self.assertEqual(out["reason_label"], "가격 검토 대기 대상")
        self.assertEqual(out["product_code"], 123456)
        self.assertTrue(out["found"])
        self.assertEqual(out["flags"], {"has_price": False, "review_required": False, "price_locked": False})
        self.assertEqual(out["checked_at"], "2026-10-27T09:00:00+09:00")

    def test_each_non_target_reason_and_flags_pass_through(self):
        cases = [
            ("has_price", {"has_price": True, "price_locked": True, "sale_price": 120000}),
            ("review_pending", {"review_required": True}),
            ("price_locked", {"price_locked": True}),
        ]
        for reason, over in cases:
            with self.subTest(reason=reason):
                out, _ = self.call(_row(in_queue=False, reason=reason, **over))
                self.assertFalse(out["in_queue"])
                self.assertEqual(out["reason"], reason)
                self.assertEqual(out["reason_label"], PR.TARGET_REASON_LABELS[reason])
                for k in ("has_price", "review_required", "price_locked"):
                    self.assertEqual(out["flags"][k], bool(over.get(k, False)))

    def test_unexpected_reason_is_unknown_not_guessed(self):
        out, _ = self.call(_row(in_queue=False, reason="something_else"))
        self.assertEqual(out["reason"], "unknown")
        self.assertEqual(out["reason_label"], "대상 여부 판정 불가")

    def test_not_found_is_404_with_detail(self):
        with self.assertRaises(HTTPException) as cm:
            self.call(None, code=999999999)
        self.assertEqual(cm.exception.status_code, 404)
        self.assertEqual(cm.exception.detail, "상품이 없습니다")

    def test_sql_reuses_pending_and_is_select_only(self):
        _, eng = self.call(_row())
        self.assertEqual(len(eng.log), 1, "SELECT 한 번")
        sql, params = eng.log[0]
        self.assertEqual(params, {"pc": 123456})
        self.assertEqual(sql.count(PR.PENDING), 2, "in_queue 와 CASE 첫 갈래 모두 PENDING 원문")
        up = sql.upper()
        self.assertTrue(up.lstrip().startswith("SELECT"))
        for bad in ("INSERT", "UPDATE", "DELETE", "FOR UPDATE", "LOCK ", "PRICE_HISTORY"):
            self.assertNotIn(bad, up)
        self.assertIn("WHERE p.product_code = :pc", sql)

    def test_reason_order_matches_empty_breakdown_split(self):
        """단건 사유가 empty-breakdown 갈래(검수 대기 → 잠금)와 같은 순서로 나뉜다."""
        sql = str(PR._TARGET)
        order = [sql.index(x) for x in ("THEN 'in_queue'", "THEN 'has_price'", "THEN 'review_pending'",
                                         "THEN 'price_locked'", "ELSE 'unknown'")]
        self.assertEqual(order, sorted(order))

    def test_route_is_get_only(self):
        hits = [r for r in PR.router.routes if getattr(r, "path", "") == "/api/admin/price-review/target/{product_code}"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].methods, {"GET"})


class AuthGateTests(unittest.TestCase):
    """기존 미들웨어 그대로 — 새 경로가 조회 등급으로 열리고, 무세션·권한 부족은 JSON 401/403."""

    def app(self, engine_row):
        app = FastAPI()
        app.middleware("http")(auth.auth_middleware)
        app.include_router(PR.router)
        self._eng = _Engine(engine_row)
        return app

    def test_required_role(self):
        self.assertEqual(auth.required_role("GET", "/api/admin/price-review/target/1"), "viewer")
        self.assertEqual(auth.required_role("POST", "/api/admin/price-review/1/decide"), "operator")

    def test_no_session_401_json(self):
        app = self.app(_row())
        with mock.patch.object(auth, "resolve_session", lambda sid: None), mock.patch.object(PR, "engine", self._eng):
            r = TestClient(app).get("/api/admin/price-review/target/123456")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json(), {"detail": "로그인이 필요하다"})
        self.assertEqual(self._eng.log, [], "인증 전에는 DB 를 보지 않는다")

    def test_insufficient_role_403_json(self):
        app = self.app(_row())
        with mock.patch.object(auth, "resolve_session", lambda sid: {"role": "none", "operator_id": 1}), \
                mock.patch.object(PR, "engine", self._eng):
            r = TestClient(app).get("/api/admin/price-review/target/123456")
        self.assertEqual(r.status_code, 403)
        self.assertIn("권한이 부족합니다", r.json()["detail"])
        self.assertEqual(self._eng.log, [])

    def test_viewer_gets_200_and_404_and_422(self):
        app = self.app(_row())
        sess = {"role": "viewer", "operator_id": 1, "email": "v@example.com", "name": "v"}
        with mock.patch.object(auth, "resolve_session", lambda sid: sess), mock.patch.object(PR, "engine", self._eng):
            c = TestClient(app)
            ok = c.get("/api/admin/price-review/target/123456")
            self._eng.row = None
            nf = c.get("/api/admin/price-review/target/999999999")
            bad = c.get("/api/admin/price-review/target/abc")
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(ok.json()["in_queue"])
        self.assertEqual(nf.status_code, 404)
        self.assertEqual(nf.json(), {"detail": "상품이 없습니다"})
        self.assertEqual(bad.status_code, 422)


class TargetCodeParseTests(unittest.TestCase):
    def test_cases(self):
        good = {"123": 123, " 123 ": 123, "9": 9, str(2 ** 63 - 1): 2 ** 63 - 1}
        for raw, want in good.items():
            with self.subTest(raw=raw):
                self.assertEqual(UI.parse_target_code(raw), (want, False))
        for raw in (None, "", "   "):
            with self.subTest(raw=raw):
                self.assertEqual(UI.parse_target_code(raw), (None, False))
        for raw in ("0", "-1", "01", "1e3", "12a", "1.5", "<script>", str(2 ** 63), "1" * 20, "１２３"):
            with self.subTest(raw=raw):
                self.assertEqual(UI.parse_target_code(raw), (None, True))


class ReturnHrefTests(unittest.TestCase):
    ALLOWED = {k for k, _n, _check in UI._RET_RULES}

    def href(self, ret):
        return UI.products_return_href(ret)

    def assertSafe(self, out):
        self.assertTrue(out == "/admin2/products" or out.startswith("/admin2/products?"), out)
        for ch in '"\'<> \\':
            self.assertNotIn(ch, out)
        if "?" in out:
            from urllib.parse import parse_qsl
            keys = [k for k, _ in parse_qsl(out.split("?", 1)[1])]
            self.assertTrue(set(keys) <= self.ALLOWED, keys)
            self.assertEqual(len(keys), len(set(keys)))

    def test_empty_is_list(self):
        for ret in (None, "", "&&", "=x"):
            self.assertEqual(self.href(ret), "/admin2/products")

    def test_full_state_round_trip_in_fixed_order(self):
        ret = ("sel=123456&dir=desc&sort=price&size=50&page=2&include_desc=1&category_id=12"
               "&sale_status=%ED%8C%90%EB%A7%A4%EC%A4%91%2C%ED%92%88%EC%A0%88&visible=on"
               "&maker=ASUS&part_type=GPU&tab=price&q=RTX%204060")
        out = self.href(ret)
        self.assertSafe(out)
        from urllib.parse import parse_qsl
        got = parse_qsl(out.split("?", 1)[1])
        self.assertEqual([k for k, _ in got], ["q", "tab", "part_type", "maker", "visible", "sale_status",
                                               "category_id", "include_desc", "page", "size", "sort", "dir", "sel"])
        self.assertEqual(dict(got)["q"], "RTX 4060")
        self.assertEqual(dict(got)["sale_status"], "판매중,품절")

    def test_external_and_scheme_attempts_never_leave_products(self):
        for ret in ("https://evil.example/x", "//evil.example", "javascript:alert(1)",
                    "q=x&next=https://evil.example", "\\\\evil.example", "%2F%2Fevil.example",
                    "q=%22%3E%3Cscript%3Ealert(1)%3C%2Fscript%3E"):
            with self.subTest(ret=ret):
                out = self.href(ret)
                self.assertSafe(out)
                self.assertNotIn("evil", out.replace("q=", ""))     # 허용 키 q 의 값으로 들어간 경우만 인코딩된 채 남는다

    def test_q_script_is_kept_only_encoded(self):
        out = self.href("q=%22%3E%3Cscript%3E")
        self.assertSafe(out)
        self.assertIn("q=%22%3E%3Cscript%3E", out)

    def test_invalid_values_dropped(self):
        out = self.href("tab=hack&size=999&sort=__proto__&page=0&dir=up&visible=yes"
                        "&category_id=abc&part_type=GPU%3B--&sel=0&maker=")
        self.assertEqual(out, "/admin2/products")

    def test_include_desc_needs_category(self):
        self.assertEqual(self.href("include_desc=1&page=3"), "/admin2/products?page=3")
        self.assertEqual(self.href("category_id=7&include_desc=1"), "/admin2/products?category_id=7&include_desc=1")

    def test_sale_status_filters_unknown_and_dedupes(self):
        from urllib.parse import quote
        out = self.href("sale_status=" + quote("판매중,없는값,판매중,삭제대기"))
        self.assertTrue(out.endswith("sale_status=" + quote("판매중,삭제대기")), out)

    def test_limits(self):
        self.assertEqual(self.href("q=" + "a" * 201), "/admin2/products")
        self.assertEqual(self.href("q=" + "a" * 200), "/admin2/products?q=" + "a" * 200)
        self.assertEqual(self.href("&".join("k%d=v" % i for i in range(61))), "/admin2/products")

    # ── ADM-H1-SRV-001: 유효한 한글 상태가 총 길이 상한에 걸려 통째로 사라지던 결함 ──
    def test_srv001_pm_repro_korean_q200_maker100_keeps_page_and_sel(self):
        ret = "q=" + "%EA%B0%80" * 200 + "&maker=" + "%EB%82%98" * 100 + "&page=2&sel=123456"
        self.assertEqual(len(ret), 2727, "PM 재현값 그대로")
        out = self.href(ret)
        self.assertSafe(out)
        from urllib.parse import parse_qsl
        got = dict(parse_qsl(out.split("?", 1)[1]))
        self.assertEqual(got, {"q": "가" * 200, "maker": "나" * 100, "page": "2", "sel": "123456"})

    def test_srv001_longest_valid_state_fits_and_round_trips(self):
        """모든 키를 허용 최대 길이로 채우고 문자열은 UTF-8 4바이트 문자로 — 가장 긴 유효 상태."""
        from urllib.parse import parse_qsl, quote, urlencode
        four = "\U00020000"
        state = [("q", four * 200), ("tab", "review"), ("part_type", "A" * 40), ("maker", four * 100),
                 ("visible", "off"), ("sale_status", ",".join(UI.STATUS_OK)), ("category_id", "9" * 10),
                 ("include_desc", "1"), ("page", "9" * 6), ("size", "500"), ("sort", "status"), ("dir", "desc"),
                 ("sel", str(2 ** 63 - 1))]
        for quote_via in (quote, None):                      # %20 방식 · + 방식(브라우저 URLSearchParams) 둘 다
            ret = urlencode(state, quote_via=quote_via) if quote_via else urlencode(state)
            with self.subTest(encoding="quote" if quote_via else "quote_plus", length=len(ret)):
                self.assertLessEqual(len(ret), UI._RET_MAX_LEN)
                out = self.href(ret)
                self.assertSafe(out)
                self.assertEqual(parse_qsl(out.split("?", 1)[1]), state)

    def test_srv001_cap_still_defends_size(self):
        ok = "page=2&" + "x" * (UI._RET_MAX_LEN - len("page=2&"))
        self.assertEqual(len(ok), UI._RET_MAX_LEN)
        self.assertEqual(self.href(ok), "/admin2/products?page=2", "상한 이하면 읽고 허용 키만 남긴다")
        self.assertEqual(self.href(ok + "x"), "/admin2/products", "상한을 1자라도 넘으면 읽지 않는다")
        self.assertLess(UI._RET_MAX_LEN, 8192, "요청 줄 버퍼(nginx 기본 8k) 안에서 의미 있는 상한")

    def test_declared_max_chars_match_each_rule_boundary(self):
        """총 길이 상한의 근거(키별 최대 글자 수)가 실제 검사 경계와 같다 — 어긋나면 상한이 유효 값을 자른다."""
        rules = {k: (n, check) for k, n, check in UI._RET_RULES}
        longest = {"q": "a" * 200, "tab": "review", "part_type": "A" * 40, "maker": "a" * 100, "visible": "off",
                   "sale_status": ",".join(UI.STATUS_OK), "category_id": "9" * 10, "include_desc": "1",
                   "page": "9" * 6, "size": "500", "sort": "status", "dir": "desc", "sel": str(2 ** 63 - 1)}
        too_long = {"q": "a" * 201, "part_type": "A" * 41, "maker": "a" * 101, "category_id": "9" * 11,
                    "page": "9" * 7, "sel": "1" * 20}
        self.assertEqual(set(longest), set(rules))
        for k, v in longest.items():
            with self.subTest(key=k):
                n, check = rules[k]
                self.assertEqual(len(v), n)
                self.assertIsNotNone(check(v))
        for k, v in too_long.items():
            with self.subTest(key=k, over=True):
                self.assertIsNone(rules[k][1](v))

    def test_duplicate_keys_keep_first(self):
        self.assertEqual(self.href("page=2&page=9"), "/admin2/products?page=2")


class PageContextTests(unittest.TestCase):
    def render_ctx(self, **query):
        seen = {}

        def fake_render(request, template, **kw):
            seen.update(kw, template=template)
            return "ok"
        with mock.patch.object(UI, "render", fake_render):
            UI.price_review_page(object(), **query)
        return seen

    def test_without_query_is_unchanged_screen(self):
        ctx = self.render_ctx(code=None, ret=None)
        self.assertEqual(ctx["template"], "admin/price_review.html.j2")
        self.assertIsNone(ctx["pr_target_code"])
        self.assertFalse(ctx["pr_target_invalid"])
        self.assertEqual(ctx["pr_return_href"], "/admin2/products")
        self.assertEqual(ctx["screen_id"], "ADM-PRC-010")

    def test_valid_code_and_return(self):
        ctx = self.render_ctx(code="123456", ret="q=RTX&page=2&sel=123456")
        self.assertEqual(ctx["pr_target_code"], 123456)
        self.assertFalse(ctx["pr_target_invalid"])
        self.assertEqual(ctx["pr_return_href"], "/admin2/products?q=RTX&page=2&sel=123456")

    def test_invalid_code_is_flag_only_raw_not_echoed(self):
        raw = '"><img src=x onerror=alert(1)>'
        ctx = self.render_ctx(code=raw, ret="https://evil.example")
        self.assertIsNone(ctx["pr_target_code"])
        self.assertTrue(ctx["pr_target_invalid"])
        self.assertEqual(ctx["pr_return_href"], "/admin2/products")
        self.assertNotIn(raw, repr(ctx))


if __name__ == "__main__":
    unittest.main()
