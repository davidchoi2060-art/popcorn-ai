"""/mvp4 회사정보 · 정책 화면 (2026-10-21 대표 확정 디자인 05·06).

회사정보는 확정값만, 대표번호는 표기만(tel: 없음), 정책 v3 검토용 초안 본문은 공개 화면에 싣지 않는다.
"""
import pathlib
import unittest

M = pathlib.Path(__file__).resolve().parents[1] / "mockups" / "mvp4"
JS = (M / "assets/js/info-pages.js").read_text(encoding="utf-8")


class InfoPages(unittest.TestCase):
    def test_pages_load_the_info_script(self):
        for name in ("company", "terms", "privacy", "purchase-support"):
            html = (M / f"{name}.html").read_text(encoding="utf-8")
            self.assertIn(f'data-page="{name}"', html)
            self.assertIn("assets/js/info-pages.js", html)
            self.assertIn("assets/css/info-pages.css", html)

    def test_company_values_are_the_confirmed_ones(self):
        # 2026-10-22: 값은 core.js 의 PAI.COMPANY 한 곳으로 옮겼다(하단 사업자 표기와 회사정보 화면이 같이 쓴다).
        core = (M / "assets/js/core.js").read_text(encoding="utf-8")
        for v in ("주식회사 팝콘컴퓨터", "이미숙", "794-81-00671", "서울특별시 용산구 원효로 188, 5층",
                  "02)1644-0249", "070-8610-0100", "0303-3442-0249"):
            self.assertIn(v, core)
        self.assertIn("var COMPANY = P.COMPANY;", JS)
        self.assertNotIn("tel:", JS)


    def test_draft_policy_text_is_not_shipped(self):
        shipped = "".join(p.read_text(encoding="utf-8", errors="ignore")
                          for p in M.rglob("*") if p.suffix in (".js", ".html", ".json"))
        for draft in ("제2조 서비스와 용어", "[시행일 확정]", "게시 전 편집 안내", "검토용 초안 v3"):
            self.assertNotIn(draft, shipped)

    def test_footer_links_the_four_pages(self):
        core = (M / "assets/js/core.js").read_text(encoding="utf-8")
        for href in ("company.html", "terms.html", "privacy.html", "purchase-support.html"):
            self.assertIn(f'href="{href}"', core)


if __name__ == "__main__":
    unittest.main()
