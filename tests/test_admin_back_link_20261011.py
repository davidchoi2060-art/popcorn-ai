"""카드로 들어온 화면의 「돌아가기」 줄 (2026-10-11 사장님 신고).

「사용·성능 자료」 위쪽 카드를 누르면 다른 화면으로 가는데 돌아올 길이 없었다.
셸이 `admin_page_intro.BACK_LINKS` 로 돌아가기 링크를 그리는지, 그 원천이 실제 카드·
신 관리자 메뉴 묶음과 맞는지 확인한다. DB·서버 없이 템플릿만 그린다.
"""
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader

from api import admin_nav, admin_page_intro as API

ROOT = Path(__file__).resolve().parents[1]
HUB = '/admin2/usage-floors'


def shell(path, new):
    env = Environment(loader=FileSystemLoader(str(ROOT / 'templates')), autoescape=True)
    t = env.from_string('{% extends "admin/_admin2_shell.html.j2" %}{% block content %}<main></main>{% endblock %}')
    return t.render(new_admin=new, workspace_nav=admin_nav.new_admin_nav(path) if new else None,
                    nav=[] if new else admin_nav.nav_for_screens(path), screen_id='X', domain='x',
                    crumb_group='g', crumb_now='n', page_intro=None, back_link=API.back_for(path),
                    request=SimpleNamespace(url=SimpleNamespace(path=path)))


class BackLinkTests(unittest.TestCase):
    def test_every_hub_card_target_links_back_to_hub(self):
        src = (ROOT / 'templates/admin/usage_floors.html.j2').read_text(encoding='utf-8')
        nav = re.search(r'<nav class="uf-hub-links".*?</nav>', src, re.S).group(0)
        cards = [h for h in re.findall(r'href="([^"]+)"', nav) if h != HUB]
        self.assertTrue(cards)
        for href in cards:
            with self.subTest(href=href):
                self.assertEqual(API.back_for(href)['href'], HUB)

    def test_back_sources_belong_to_same_new_admin_menu_group(self):
        for path in API.BACK_LINKS[HUB]['from']:
            with self.subTest(path=path):
                active = [i['href'] for i in admin_nav.new_admin_nav(path) if i['active']]
                self.assertEqual(active, [HUB])

    def test_hub_and_unrelated_pages_get_no_back_link(self):
        for path in (HUB, HUB + '/', '/admin2/products', '/admin2/', '/admin2/game-copy-review-x'):
            with self.subTest(path=path):
                self.assertIsNone(API.back_for(path))

    def test_shell_renders_plain_back_link_in_both_modes(self):
        for new in (True, False):
            for path in ('/admin2/game-copy-review', '/admin2/product-fit/'):
                with self.subTest(new=new, path=path):
                    html = shell(path, new)
                    self.assertEqual(html.count('id="a2BackLink"'), 1)
                    self.assertIn(f'href="{HUB}" id="a2BackLink"', html)
                    self.assertIn('사용·성능 자료로 돌아가기', html)
            self.assertNotIn('a2BackLink', shell(HUB, new))

    def test_shell_script_only_uses_history_when_previous_page_is_target(self):
        js = (ROOT / 'mockups/shared/admin2/admin2-shell.js').read_text(encoding='utf-8')
        block = js[js.index('function initBackLink'):]
        block = block[:block.index('})();')]
        self.assertIn('document.referrer', block)
        self.assertIn('ref.origin !== location.origin', block)
        self.assertLess(block.index('return;', block.index('ref.pathname')), block.index('history.back()'))


if __name__ == '__main__':
    unittest.main()
