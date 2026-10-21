"""AI로 PC 찾기 코발트 연결 (2026-10-21 대표 승인 1번 · 최신 수정본).

① 구매 버튼 문구는 정확히 「팝콘PC몰에서 바로 구매」. ② 상세의 부품/사양 목록 바로 다음에 「상품 설명」 자리(자리만 -- 기존 설명은 그 안에,
없으면 숨김 · 자리표시 문구 없음). ③ 헤더·메뉴는 그대로 -- 코발트 색은 body[data-finder] 본문에만.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1] / "mockups/mvp4"
JS = ROOT / "assets/js"
LABEL = "팝콘PC몰에서 바로 구매"


def src(name):
    return (JS / name).read_text(encoding="utf-8")


class BuyLabel(unittest.TestCase):
    def test_every_buy_button_uses_the_new_label(self):
        for name in ("chat-answer.js", "design-conversation.js", "configuration-concept.js", "live-catalog.js", "live-checkout.js",
                     "mall-buy-guide.js", "supercomputer-detail.js", "ai-task-pc.js"):
            s = src(name)
            self.assertIn("'" + LABEL + "'", s, name)
            for old in ("'팝콘PC몰에서 구매하기'", "'팝콘PC몰 구매'", "P.mallBuyLink(p, 'pa-mall-buy', '팝콘PC몰에서 구매')"):
                self.assertNotIn(old, s, name)


class DescriptionSlot(unittest.TestCase):
    def test_pc_detail_slot_follows_parts_and_keeps_existing_text(self):
        s = src("live-cards.js")
        fn = s[s.index("  function intro(p) {"):s.index("  function checks(p) {")]
        self.assertIn("data-product-description", fn)
        self.assertIn("상품 설명", fn)
        self.assertIn("(body ? '' : ' hidden')", fn)   # 설명이 없으면 자리만 두고 숨긴다
        for t in ("d.intro", "d.scene", "d.benefits", "ABOUT THIS PC"):
            self.assertIn(t, fn)   # 운영에 있던 소개는 그대로 이 안에
        self.assertIn("var extra = intro(p) + checks(p) + more(p);", s)   # 부품 구성 바로 다음

    def test_ai_device_slot_follows_specs(self):
        s = src("supercomputer-detail.js")
        self.assertIn("var body = connections(p);", s)
        i = s.index("<h2>사양을 한눈에.</h2>")
        self.assertLess(i, s.index("description(p) +", i))

    def test_no_placeholder_copy_in_production(self):
        for name in ("live-cards.js", "supercomputer-detail.js", "configuration-concept.js"):
            for t in ("상품 설명이 들어갈 자리", "이곳에 표시합니다"):
                self.assertNotIn(t, src(name))


class CobaltScope(unittest.TestCase):
    def test_marker_only_on_finder_screens(self):
        self.assertIn("['chat', 'compare', 'saved', 'product'].indexOf(screen) >= 0) document.body.dataset.finder = screen; else delete document.body.dataset.finder;",
                      src("design-boot.js"))

    def test_css_never_reaches_header_or_footer(self):
        css = re.sub(r"/\*.*?\*/", "", (ROOT / "assets/css/finder-cobalt.css").read_text(encoding="utf-8"), flags=re.S)
        css = re.sub(r"@media[^{]*\{", "", css)
        for rule in re.findall(r"([^{}]+)\{[^{}]*\}", css):
            for sel in re.split(r",(?![^()]*\))", rule):
                sel = sel.strip()
                if not sel:
                    continue
                self.assertTrue(sel.startswith("body[data-finder"), sel)
                self.assertNotRegex(sel, r"site-header|header-|site-footer|nav")

    def test_linked_last_in_index(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('assets/css/finder-cobalt.css?v=', html)


class FeaturePanel(unittest.TestCase):
    def test_buy_select_compare_are_separate_existing_actions(self):
        s = src("design-conversation.js")
        fn = s[s.index("    function featured() {"):s.index("    function markup() {\n      var cards")]
        self.assertIn("buyButton(p, !!issue, 'btn btn-primary dc-feature-buy')", fn)
        self.assertIn('data-dc-select="', fn)
        self.assertIn("data-dc-unselect", fn)
        self.assertIn('data-pa-add="', fn)
        self.assertIn('data-pa-kind="pc"', fn)
        self.assertIn("부품 가격 변동으로 최종 금액이 달라질 수 있어요.", fn)
        for banned in ("send(", "model.draft", "model.log", "fetch("):
            self.assertNotIn(banned, fn)
        self.assertIn("' + featured() + '", s)


if __name__ == "__main__":
    unittest.main()
