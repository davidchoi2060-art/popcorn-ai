"""관리자 좌측 메뉴는 하나다(2026-11-18 사장님 지시 「하나로 만들어서 확정」).

예전에는 `?admin=new`(또는 쿠키)가 신 관리자 메뉴로 바꿔 그렸다. 지금은 모드와 무관하게 단일 메뉴
(`admin_nav.simple_nav`)를 그린다. 모드 쿠키는 화면 본문 변형(판매가·매입 견적·재고 입고)에만 남는다.
"""
import unittest
from starlette.requests import Request
from api.admin_ui_common import render
from api.admin_nav import simple_nav


def request(path='/admin2/new', query='', cookie=''):
    return Request(dict(type='http',method='GET',path=path,raw_path=path.encode(),
                        query_string=query.encode(),headers=[(b'cookie',cookie.encode())],
                        scheme='https',server=('admin.example',443),root_path=''))


def lnb(html):
    return html[html.index('id="lnb"'):html.index('id="lnbToggle"')]


class SingleNavigationTests(unittest.TestCase):
    def page(self, req, **kwargs):
        return render(req,'admin/new_home.html.j2',**kwargs)

    def test_default_draws_single_menu_without_new_entry(self):
        html=self.page(request('/admin2/')).body.decode()
        self.assertIn('data-admin-shell="simple"',html)
        self.assertIn('class="a2-lnb-grp"',html)
        self.assertNotIn('/admin2/?admin=new',html)
        self.assertNotIn('신 관리자 →',html)

    def test_new_query_and_cookie_draw_the_same_menu(self):
        r=self.page(request(query='admin=new'))
        self.assertIn('admin_ui_mode=new',r.headers['set-cookie'])   # 화면 변형 쿠키는 그대로 남는다
        base=lnb(self.page(request()).body.decode())
        self.assertEqual(lnb(r.body.decode()),base)
        for path in ('/admin2/pc-configurations','/admin2/pc-media','/admin2/pc-video','/admin2/pc-builder'):
            html=self.page(request(path,cookie='admin_ui_mode=new')).body.decode()
            self.assertIn('data-admin-shell="simple"',html)
            self.assertIn('class="a2-lnb-grp"',html)
            self.assertIn('신규 조립PC 생성',html)
            self.assertEqual(lnb(html),lnb(self.page(request(path)).body.decode()))

    def test_explicit_legacy_query_keeps_same_menu(self):
        r=self.page(request('/admin2/',query='admin=legacy',cookie='admin_ui_mode=new'))
        self.assertIn('admin_ui_mode=legacy',r.headers['set-cookie'])
        self.assertIn('class="a2-lnb-grp"',r.body.decode())
        self.assertEqual(lnb(r.body.decode()),lnb(self.page(request('/admin2/')).body.decode()))

    def test_invalid_query_draws_same_menu(self):
        self.assertEqual(lnb(self.page(request(query='admin=unknown')).body.decode()),
                         lnb(self.page(request()).body.decode()))

    def test_product_subscreens_highlight_product_group(self):
        for path in ('/admin2/pc-media','/admin2/pc-video','/admin2/pc-batch','/admin2/configuration-consultation'):
            self.assertEqual(['상품'],[g['title'] for g in simple_nav(path) if g['active']])

    def test_member_page_highlights_member_group(self):
        html=self.page(request('/admin2/members',cookie='admin_ui_mode=new')).body.decode()
        self.assertIn('href="/admin2/members"',lnb(html))
        self.assertEqual(lnb(html).count('aria-current="page"'),1)
        self.assertEqual(['회원'],[g['title'] for g in simple_nav('/admin2/members') if g['active']])


if __name__=='__main__':unittest.main()


class StudioLinkTests(unittest.TestCase):
    """관리자 헤더의 「견적 스튜디오」 링크 — 두 모드 모두, 새 탭으로 연다(2026-10-14)."""

    def test_header_links_studio_in_both_modes(self):
        STUDIO_URL = 'https://popcornpc-studio-741686685802.asia-northeast3.run.app/'
        for cookie in ('admin_ui_mode=legacy', 'admin_ui_mode=new'):
            html = render(request('/admin2/', cookie=cookie), 'admin/new_home.html.j2').body.decode()
            self.assertIn(f'class="a2-hub a2-studio" href="{STUDIO_URL}" target="_blank" rel="noopener"', html)
            self.assertIn('>견적 스튜디오</a>', html)


def test_screen_forced_variant_does_not_persist_mode_cookie():
    """2026-11-18 메뉴 통합 뒤: 회원·주문 운영 등 화면이 admin_mode='new' 로 그려도 쿠키는 바뀌지 않는다.
    쿠키는 운영자가 주소(?admin=)로 직접 고른 경우에만 바뀐다."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "api" / "admin_ui_common.py").read_text(encoding="utf-8")
    assert "if choice and choice != request.cookies.get('admin_ui_mode', 'legacy'):" in src
    assert "if choice or mode != request.cookies.get('admin_ui_mode', 'legacy'):" not in src
