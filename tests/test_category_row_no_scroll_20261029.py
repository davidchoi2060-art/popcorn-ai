"""전체 카테고리 줄은 옆으로 넘기지 않는다 (2026-10-29 사장님 「전체 카테고리가 좌우 스크롤 안되게 할 수 없나?」).

개발 서버 실측: 1231px 이상에서 카테고리 칸이 93~156px 모자라 일부가 가려진 채 옆으로 넘겨야 했고,
375px 휴대폰에서는 595px 중 225px만 보였다. 넓은 화면은 메뉴 아래 한 줄(901px 이상 공통), 좁은 화면은 줄 바꿈,
휴대폰은 노란 「전체 카테고리」 버튼 대신 오른쪽 위 ≡(같은 창)를 쓴다.
"""
import pathlib
import unittest

MVP4 = pathlib.Path(__file__).resolve().parents[1] / 'mockups/mvp4'


class CategoryRowNoScroll(unittest.TestCase):
    def setUp(self):
        self.css = (MVP4 / 'assets/css/header-ui.css').read_text(encoding='utf-8')
        self.js = (MVP4 / 'assets/js/header-ui.js').read_text(encoding='utf-8')

    def test_tabs_wrap_instead_of_scrolling_and_win_over_the_old_rule(self):
        wrap = '.nh-header .nh-purpose-tabs{flex-wrap:wrap;overflow:visible}'
        self.assertIn(wrap, self.css)
        self.assertGreater(self.css.index(wrap), self.css.index('.nh-header .nh-purpose-tabs{display:flex'))

    def test_wide_screens_put_categories_on_their_own_row(self):
        self.assertIn('@media(min-width:901px){.nh-header .nh-service-nav{flex-wrap:wrap', self.css)
        self.assertNotIn('@media(min-width:901px) and (max-width:1230px){.nh-header .nh-service-nav', self.css)

    def test_phones_hide_the_duplicate_button_but_keep_the_menu(self):
        self.assertIn('@media(max-width:600px){.nh-header .nh-purpose-group .nh-category-compact{display:none}', self.css)
        # 휴대폰 오른쪽 위 ≡ 버튼이 같은 전체 카테고리 창(site-menu)을 연다.
        self.assertIn("menuButton('nh-mobile-menu', '전체 메뉴')", self.js)
        self.assertIn('data-open-dialog="site-menu"', self.js)


if __name__ == '__main__':
    unittest.main()
