"""/mvp4 메인 롤링 배너 양옆 배경 확장 (2026-10-20 대표 승인).

「기존 헤더랑 띠메뉴, 배너 이미지와 문구, 롤링 동작은 그대로 두고 양옆 배경만 확장」 -- 장식 층 하나만 더하고,
색은 슬라이드 key 에 붙여 기존 show() 의 활성 슬라이드를 따른다(독립 타이머 없음).
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
JS = (ROOT / "mockups/mvp4/assets/js/home-carousel.js").read_text(encoding="utf-8")
CSS = (ROOT / "mockups/mvp4/assets/css/home-carousel.css").read_text(encoding="utf-8")

APPROVED = {"showcase": ("#FEFBF4", "#EEE3D6"), "gaming": ("#E1F1FD", "#A9C6E8"), "ai": ("#ECE5FD", "#E7E4F7"),
            "people": ("#FEF7DF", "#F3F4EF"), "collection": ("#FCF7EC", "#F3E6FA"), "supercomputer": ("#FBF8F6", "#E4EDF8")}


class EdgeBackground(unittest.TestCase):
    def test_approved_colors_are_bound_to_slide_keys_in_order(self):
        keys = re.findall(r"\{key:'(\w+)', edge:\['(#\w{6})','(#\w{6})'\]", JS)
        self.assertEqual([k for k, _, _ in keys], list(APPROVED))
        for k, a, b in keys:
            self.assertEqual((a, b), APPROVED[k], k)

    def test_follows_existing_active_slide_without_own_timer(self):
        self.assertEqual(JS.count("setInterval"), 0)
        self.assertEqual(JS.count("window.setTimeout(function(){show(index+1,false);},interval)"), 1)
        self.assertIn("tones.forEach(function(tone,i){tone.toggleAttribute('data-active',i===index);});", JS)
        self.assertIn("var interval=3000, transitionMs=600", JS)

    def test_decorative_layer_does_not_block_or_overflow(self):
        self.assertIn('<div class="hc-edge" aria-hidden="true">', JS)
        self.assertIn("document.documentElement.clientWidth", JS)
        self.assertNotIn("100vw", CSS)
        self.assertIn("pointer-events:none", CSS.split(".hc-edge{", 1)[1].split("}", 1)[0])
        self.assertIn("@media(max-width:800px){.hc-edge{display:none}}", CSS)
        self.assertIn("@media(prefers-reduced-motion:reduce){.hc-edge-tone{transition:none}}", CSS)

    def test_banner_frame_rules_unchanged(self):
        self.assertIn(".hc-stage{height:470px;position:relative;border-radius:16px;overflow:hidden;background:#fff9e9;touch-action:pan-y}", CSS)
        self.assertIn(".hc-image{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:center;user-select:none}", CSS)


if __name__ == "__main__":
    unittest.main()
