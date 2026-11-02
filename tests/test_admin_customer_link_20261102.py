"""관리자 상품 → 고객(/mvp4) 상세 주소 판정 (2026-11-02 · Codex 「MVP4 고객 화면과 관리자 연결」 1번).

DB 없이 판정 함수와 화면 계약을 고정한다. 입력은 고객 화면 함수(customer_supercomputer.load ·
customer_pc_catalog.catalog)가 돌려주는 값 모양 그대로다.
"""
import re
import unittest
from pathlib import Path

from api import admin_customer_link as L

ROOT = Path(__file__).resolve().parents[1]
TPL = (ROOT / "templates/admin/products.html.j2").read_text(encoding="utf-8")
JS = TPL[TPL.index("{% raw %}") + len("{% raw %}"):TPL.index("{% endraw %}")]
BASE = dict(part_type="CPU", status="판매중", supercomputer_item=None, in_supercomputer_category=False,
            fit_row=None, pc_item=None)


def j(code=101, **kw):
    a = dict(BASE); a.update(kw)
    return L.judge(code, **a)


class JudgeTests(unittest.TestCase):
    def test_public_pc_links_to_mvp4_product(self):
        r = j(130001, part_type="PC_COMPLETE", fit_row={"excluded": False}, pc_item={"product_code": 130001, "price": 1290000})
        self.assertEqual((r["kind"], r["url"], r["state"], r["reason"]), ("pc", "/mvp4/?screen=product&id=130001", "on_sale", None))

    def test_pc_without_price_links_with_price_check_note(self):
        r = j(130002, part_type="PC_COMPLETE", fit_row={"excluded": False}, pc_item={"product_code": 130002, "price": None})
        self.assertEqual(r["url"], "/mvp4/?screen=product&id=130002")
        self.assertEqual(r["reason"], L.NOTE_PRICE_CHECK)

    def test_pc_not_in_customer_catalog_has_reason_no_url(self):
        self.assertEqual(j(1, part_type="PC_COMPLETE", fit_row={"excluded": True})["reason"], L.REASON_PC_EXCLUDED)
        r = j(1, part_type="PC_COMPLETE", status="품절", fit_row={"excluded": False})
        self.assertIsNone(r["url"]); self.assertIn("「품절」", r["reason"])
        r = j(1, part_type="PC_COMPLETE")
        self.assertIsNone(r["url"]); self.assertEqual(r["reason"], L.REASON_PC_NOT_FIT)

    def test_supercomputer_links_even_when_stopped(self):
        r = j(129615, supercomputer_item={"sale_state": "on_sale"}, in_supercomputer_category=True)
        self.assertEqual((r["kind"], r["url"], r["reason"]), ("supercomputer", "/mvp4/supercomputer.html?id=129615", None))
        self.assertEqual(j(129615, supercomputer_item={"sale_state": "stopped"}, in_supercomputer_category=True)["reason"], L.NOTE_STOPPED)
        self.assertEqual(j(129615, supercomputer_item={"sale_state": "check"}, in_supercomputer_category=True)["reason"], L.NOTE_PRICE_CHECK)

    def test_hidden_supercomputer_has_reason(self):
        r = j(129614, in_supercomputer_category=True)
        self.assertEqual((r["url"], r["state"], r["reason"]), (None, "hidden", L.REASON_SC_HIDDEN))

    def test_part_has_no_customer_detail(self):
        r = j(114634, part_type="CPU")
        self.assertEqual((r["kind"], r["url"], r["reason"]), ("part", None, L.REASON_PART))

    def test_supercomputer_wins_over_pc_rows(self):
        r = j(5, part_type="PC_COMPLETE", supercomputer_item={"sale_state": "on_sale"}, in_supercomputer_category=True,
              fit_row={"excluded": False}, pc_item={"price": 1})
        self.assertEqual(r["kind"], "supercomputer")


class SafeUrlTests(unittest.TestCase):
    def test_only_same_env_mvp4_detail_paths(self):
        ok = ("/mvp4/?screen=product&id=1", "/mvp4/supercomputer.html?id=129615")
        bad = ("https://popcornai.co.kr/mvp4/?screen=product&id=1", "//evil.example/mvp4/?screen=product&id=1",
               "javascript:alert(1)", "/mvp4/?screen=product&id=0", "/mvp4/?screen=product&id=1&x=2",
               "/mvp5/?screen=product&id=1", "https://www.popcornpc.co.kr/goods/1", None, 1)
        for u in ok:
            self.assertEqual(L.safe_url(u), u)
        for u in bad:
            self.assertIsNone(L.safe_url(u), u)

    def test_client_regex_matches_server_regex(self):
        m = re.search(r"var CUST_SAFE = /(.+?)/;", JS)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1).replace(chr(92) + "/", "/"), L._SAFE.pattern)


class ScreenContractTests(unittest.TestCase):
    def test_link_opens_new_tab_without_opener(self):
        seg = JS[JS.index("function loadCustomerLink"):JS.index("function loadDrawerPhoto")]
        self.assertIn('a.target="_blank"', seg)
        self.assertIn('a.rel="noopener noreferrer"', seg)
        self.assertIn("CUST_SAFE.test(j.url)", seg)
        self.assertIn("DRAWER.code !== code", seg)        # 늦은 응답이 다른 상품 창을 덮지 않는다
        self.assertNotIn("innerHTML", seg)                 # 서버 문구는 textContent 로만
        self.assertIn("다시 확인", seg)

    def test_loaded_with_basic_tab(self):
        self.assertIn("loadDrawerPhoto(DRAWER.code); loadCustomerLink(DRAWER.code);", JS)

    def test_route_registered_under_admin_gate(self):
        paths = [r.path for r in L.router.routes]
        self.assertIn("/api/admin/products/{product_code}/customer-link", paths)
        from api.auth import required_role
        self.assertEqual(required_role("GET", "/api/admin/products/1/customer-link"), "viewer")


class _Conn:
    """in_supercomputer_category 가 부르는 scalar() 한 번만 흉내 낸다(DB 없음)."""
    def __init__(self, inside): self.inside = inside
    def execute(self, *_a, **_k): return self
    def scalar(self): return self.inside


class PartGateScopeTests(unittest.TestCase):
    """완제품 PC·AI 슈퍼컴퓨터에 부품 견적 후보 기준을 대지 않는다(2026-11-02 Codex 검수 113835 · 129774)."""

    def test_pc_and_supercomputer_are_not_part_gated(self):
        self.assertFalse(L.part_gate_applies(_Conn(False), 113835, "PC_COMPLETE"))
        self.assertFalse(L.part_gate_applies(_Conn(True), 129774, "ETC"))

    def test_parts_and_misclassified_etc_keep_part_gate(self):
        self.assertTrue(L.part_gate_applies(_Conn(False), 114634, "CPU"))
        self.assertTrue(L.part_gate_applies(_Conn(False), 1, "ETC"))   # ETC 로 잘못 들어간 부품 — 분류 오류 단서 유지

    def test_detail_api_carries_scope(self):
        src = (ROOT / "api/admin_products.py").read_text(encoding="utf-8")
        seg = src[src.index("def get_product(product_code: int):"):]
        self.assertIn("gate_applies = part_gate_applies(conn, product_code, r[\"part_type\"])", seg)
        self.assertIn('"gate_applies": gate_applies', seg)
        self.assertIn('"gate_scope_note": None if gate_applies else GATE_NOT_PART_NOTE', seg)

    def test_drawer_uses_list_status_when_not_part_gated(self):
        i = JS.index("if(d.gate_applies === false){")
        self.assertLess(i, JS.index('badge.textContent="추천 제외"'))      # 「추천 제외」보다 먼저 가른다
        self.assertIn("ST[d.status_key]", JS[i:i + 300])                  # 목록 배지와 같은 표(ST)
        self.assertIn("'<div class=\"pp-gate pp-gate-na\">", JS)
        self.assertIn("esc(d.gate_scope_note", JS)


class SingleProductPcJudgeTests(unittest.TestCase):
    """PC 판정은 전체 목록을 다시 만들지 않고 같은 판정(추천 풀 ∩ listed)을 상품 하나에 적용한다."""

    def test_link_uses_single_item_path_not_full_catalog(self):
        src = (ROOT / "api/admin_customer_link.py").read_text(encoding="utf-8")
        body = src[src.index("def customer_link("):]
        self.assertIn("customer_pc_catalog.listed_item(product_code)", body)
        self.assertNotIn("catalog()", body)

    def test_catalog_and_single_item_share_predicate(self):
        src = (ROOT / "api/customer_pc_catalog.py").read_text(encoding="utf-8")
        self.assertIn("if listed(p)]", src[src.index("def _build"):])
        self.assertIn("not listed(p)", src[src.index("def listed_item"):src.index("def _build")])
        self.assertIn("load(codes=[code])", src)

    def test_load_scope_filter_only_narrows_rows(self):
        from unittest import mock
        from api import admin_product_fit as F
        seen = []

        class C:
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def execute(s, sql, params=None):
                seen.append((str(sql), params)); return s
            def all(s): return []
            def __iter__(s): return iter([])
        with mock.patch.object(F, "engine", mock.Mock(connect=lambda: C())):
            F.load(); full = list(seen); seen.clear()
            F.load(codes=[113835])
        self.assertNotIn("ANY(:codes)", " ".join(q for q, _ in full))
        scoped = [q for q, p in seen if p and p.get("codes") == [113835]]
        self.assertEqual(len(scoped), 2)          # 상품 행 + 용도 평가 행
        self.assertTrue(all("ANY(:codes)" in q for q in scoped))


if __name__ == "__main__":
    unittest.main()
