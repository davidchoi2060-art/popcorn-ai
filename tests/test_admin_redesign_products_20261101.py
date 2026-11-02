"""관리자 재설계 PR-B — 상품 관리(검색 → 목록 → 오른쪽 확인 패널) 화면 계약 (2026-11-01).

근거: Codex 확정안 §4(공유 폴더 `outputs/admin-redesign-20261101/확정안_구현명세.md`).
브라우저 없이 템플릿·스크립트 문자열로 계약을 고정한다. 동작은 로컬 미리보기에서 따로 확인했다.
"""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TPL = (ROOT / "templates/admin/products.html.j2").read_text(encoding="utf-8")
JS = TPL[TPL.index("{% raw %}") + len("{% raw %}"):TPL.index("{% endraw %}")]
BODY = TPL[TPL.index("{% block content %}"):TPL.index("{% block foot_extra %}")]
MARKUP = re.sub(r"\{#.*?#\}", "", BODY, flags=re.S)   # Jinja 주석(경위 기록)은 뺀 실제 마크업


class ProductsRedesignTests(unittest.TestCase):
    def test_order_head_search_applied_tabs_list(self):
        order = [BODY.index(s) for s in ('class="pp-head"', 'class="pp-quick"', 'id="ppApplied"',
                                         'id="tabs"', 'id="ppDetail"', 'id="thead"', 'id="drawer"')]
        self.assertEqual(order, sorted(order))
        self.assertIn('href="/admin2/product-new"', BODY)

    def test_detail_conditions_start_folded_with_apply_and_cancel(self):
        self.assertRegex(BODY, r'<div class="pp-searchbox" id="ppDetail" data-keep="1" hidden>')
        for i in ("btnApply", "btnCancel", "btnDetail"):
            self.assertIn(f'id="{i}"', BODY)
        self.assertIn('aria-controls="ppDetail"', BODY)

    def test_decorative_search_target_selector_removed(self):
        self.assertNotIn('id="qType"', MARKUP)
        self.assertNotIn("화면 표시용", MARKUP)

    def test_search_runs_only_on_enter_or_button(self):
        self.assertNotIn("typing = setTimeout", JS)
        self.assertNotIn("typingM = setTimeout", JS)
        self.assertIn('e.key==="Enter"', JS)

    def test_detail_controls_mark_dirty_instead_of_loading(self):
        for handler in ('getElementById("fvisible").addEventListener', 'getElementById("fstock").addEventListener',
                        'getElementById("fmfr").addEventListener'):
            seg = JS[JS.index(handler):JS.index("});", JS.index(handler))]
            self.assertIn("markDirty()", seg)
            self.assertNotIn("load()", seg)
        seg = JS[JS.index("function applyCategorySelection"):JS.index("function renderSaleStatusChecks")]
        self.assertIn("markDirty()", seg)

    def test_cancel_restores_last_applied_state_and_keeps_selection(self):
        seg = JS[JS.index('getElementById("btnCancel")'):]
        seg = seg[:seg.index("});")]
        self.assertIn("readStateFromUrl()", seg)
        self.assertIn("SEL = keepSel", seg)

    def test_list_load_drops_late_responses(self):
        self.assertIn("var my = ++LOAD_SEQ;", JS)
        self.assertGreaterEqual(JS.count("my!==LOAD_SEQ"), 3)

    def test_columns_and_unknown_price(self):
        head = BODY[BODY.index('id="thead"'):BODY.index('<div id="rows">')]
        labels = re.findall(r">([^<>]+?)(?: ↕)?</span>", head)
        self.assertEqual([l.strip() for l in labels if l.strip()], ["상품", "판매가", "판매 상태", "확인할 항목"])
        self.assertIn("가격 미확인", JS)
        self.assertNotIn("확인 필요", JS)   # 새 판매 상태를 만들지 않는다

    def test_row_view_does_not_touch_selection(self):
        self.assertIn('closest(".pp-chk")) return;', JS)
        seg = JS[JS.index("function readStateFromUrl"):JS.index("function fromApi")]
        self.assertNotIn("SEL[INITIAL_SEL_CODE] = true", seg)

    def test_panel_mode_and_focus_return(self):
        for name in ("function syncPanelMode", "function restoreRowFocus", "function markOpenRow"):
            self.assertIn(name, JS)
        self.assertIn('matchMedia("(min-width:1280px)")', JS)
        self.assertIn("restoreRowFocus(was)", JS)

    def test_photo_states_are_distinguished_by_status(self):
        seg = JS[JS.index("function loadDrawerPhoto"):]
        self.assertIn("r.status === 404", seg)
        self.assertIn("등록된 사진 없음", seg)
        self.assertIn("사진을 불러오지 못했습니다", seg)
        self.assertIn("다시 불러오기", seg)

    def test_customer_link_is_not_composed(self):
        # 화면은 고객 주소를 만들지 않는다 — 서버 판정(customer-link)만 쓴다(2026-11-02 연결).
        self.assertNotIn("/mvp4/", JS)
        self.assertIn('"/customer-link"', JS)

    def test_no_server_string_into_innerhtml_without_escape(self):
        seg = JS[JS.index("function renderApplied"):JS.index("function unsetFilter")]
        self.assertIn("esc(x.label)", seg)

    @unittest.skipUnless(shutil.which("node"), "node 없음")
    def test_script_parses(self):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(JS)
        r = subprocess.run(["node", "--check", f.name], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


class EnvLabelConfigTests(unittest.TestCase):
    def test_server_setting_wins_over_host(self):
        import os
        from unittest import mock
        from starlette.requests import Request
        from api.admin_ui_common import env_label

        def req(host):
            return Request(dict(type="http", method="GET", path="/admin2/", raw_path=b"/admin2/", query_string=b"",
                                headers=[(b"host", host.encode())], scheme="https", server=(host, 443), root_path=""))
        with mock.patch.dict(os.environ, {"POPCORN_ENV": "prod"}):
            self.assertEqual(env_label(req("dev.popcornai.co.kr")), "운영 환경")
        with mock.patch.dict(os.environ, {"POPCORN_ENV": "unknown-x"}):
            self.assertEqual(env_label(req("dev.popcornai.co.kr")), "")
        with mock.patch.dict(os.environ, {"POPCORN_ENV": ""}):
            self.assertEqual(env_label(req("dev.popcornai.co.kr")), "개발 환경")


class NarrowDrawerFitTests(unittest.TestCase):
    """좁은 화면 서랍은 스크롤바 폭만큼 왼쪽으로 밀리지 않는다(2026-11-02 Codex D-01)."""
    CSS = (ROOT / "mockups/shared/admin2/management-dialogs.css").read_text(encoding="utf-8")

    def test_drawer_width_not_from_100vw(self):
        for m in re.finditer(r"([^{}]*\.(?:pp|cr)-drawer[^{}]*)\{([^}]*)\}", self.CSS):
            self.assertNotRegex(m.group(2), r"(?<!max-)width:\s*calc\(100vw", m.group(1))
            self.assertNotIn("max-width:calc(100vw", m.group(2), m.group(1))

    def test_overlay_drawer_locks_background_scroll(self):
        self.assertIn('classList.toggle("pp-scroll-lock", open && !panel)', JS)
        self.assertIn("html.pp-scroll-lock", TPL)

    def test_shared_css_cache_version_bumped_everywhere(self):
        for name in ("compat_rules", "products", "spec_field_defs", "spec_standard"):
            t = (ROOT / f"templates/admin/{name}.html.j2").read_text(encoding="utf-8")
            self.assertIn("management-dialogs.css?v=20261102", t, name)


class ProductWritePermissionTests(unittest.TestCase):
    """상품 화면이 부르는 쓰기 요청은 서버 게이트에서 «운영자 이상», 읽기는 «조회 이상»이다.
    재설계는 이 판정·API 를 바꾸지 않았다 — 화면 문구 「조회: 모든 등급 · 쓰기: 운영자 이상」과
    서버 판정이 같은지 DB 없이 고정한다(2026-11-02 Codex 마무리 검수 §5-3)."""

    WRITES = (("POST", "/api/admin/products/bulk-status"), ("POST", "/api/admin/products/bulk-status/undo"),
              ("PATCH", "/api/admin/products/123"), ("PATCH", "/api/admin/products/123/specs"),
              ("POST", "/api/admin/products/123/part-type"), ("POST", "/api/admin/products/123/suppliers"),
              ("DELETE", "/api/admin/products/123/suppliers/7"))

    def test_every_write_call_in_screen_is_listed(self):
        self.assertEqual(len(re.findall(r'method *: *"(?:POST|PATCH|PUT|DELETE)"', JS)), 8)  # part-type 미리보기·확정 2곳 포함

    def test_writes_need_operator_reads_need_viewer(self):
        from api.auth import required_role
        for m, path in self.WRITES:
            self.assertEqual(required_role(m, path), "operator", (m, path))
        for path in ("/api/admin/products", "/api/admin/products/123", "/api/admin/product-meta"):
            self.assertEqual(required_role("GET", path), "viewer", path)
        self.assertIn("조회: 모든 등급 · 쓰기: 운영자 이상", TPL)


if __name__ == "__main__":
    unittest.main()
