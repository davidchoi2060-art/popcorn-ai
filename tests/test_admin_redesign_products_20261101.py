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
        self.assertNotIn("/mvp4/", JS)
        self.assertIn("고객 화면 보기 · 주소 정보 없음", JS)

    def test_no_server_string_into_innerhtml_without_escape(self):
        seg = JS[JS.index("function renderApplied"):JS.index("function unsetFilter")]
        self.assertIn("esc(x.label)", seg)

    @unittest.skipUnless(shutil.which("node"), "node 없음")
    def test_script_parses(self):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(JS)
        r = subprocess.run(["node", "--check", f.name], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
