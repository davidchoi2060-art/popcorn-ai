import unittest
from starlette.requests import Request
from api.admin_ui_common import render
from api.admin_nav import new_admin_nav


def request(path='/admin2/new', query='', cookie=''):
    return Request(dict(type='http',method='GET',path=path,raw_path=path.encode(),
                        query_string=query.encode(),headers=[(b'cookie',cookie.encode())],
                        scheme='https',server=('admin.example',443),root_path=''))


class NewNavigationTests(unittest.TestCase):
    def page(self, req, **kwargs):
        return render(req,'admin/new_home.html.j2',**kwargs)

    def test_default_is_legacy_with_entry(self):
        r=self.page(request('/admin2/'))
        self.assertIn('신 관리자',r.body.decode())
        self.assertNotIn('class="a2-new-secondary"',r.body.decode())

    def test_entry_and_followup_share_new_profile(self):
        r=self.page(request(query='admin=new'))
        self.assertIn('admin_ui_mode=new',r.headers['set-cookie'])
        for path in ('/admin2/pc-configurations','/admin2/pc-media','/admin2/pc-video','/admin2/pc-builder'):
            html=self.page(request(path,cookie='admin_ui_mode=new')).body.decode()
            self.assertIn('class="a2-new-secondary"',html)
            self.assertNotIn('class="a2-lnb-grp"',html)
            self.assertIn('신규 조립PC 생성',html)

    def test_explicit_exit_overrides_cookie_and_page_local_navigation(self):
        r=self.page(request('/admin2/',query='admin=legacy',cookie='admin_ui_mode=new'),workspace_nav=[dict(label='stale',href='/stale',icon='box')])
        self.assertIn('admin_ui_mode=legacy',r.headers['set-cookie'])
        self.assertNotIn('/stale',r.body.decode())
        self.assertIn('class="a2-lnb-grp"',r.body.decode())

    def test_invalid_query_cannot_select_arbitrary_profile(self):
        self.assertNotIn('class="a2-new-secondary"',self.page(request(query='admin=unknown')).body.decode())

    def test_product_subscreens_highlight_product_menu(self):
        for path in ('/admin2/pc-media','/admin2/pc-video','/admin2/configuration-consultation'):
            active=[i['label'] for i in new_admin_nav(path) if i['active']]
            self.assertEqual(['조립PC 제품군'],active)

    def test_member_page_uses_new_menu_and_preserves_profile(self):
        html=self.page(request('/admin2/members',cookie='admin_ui_mode=new')).body.decode()
        self.assertIn('class="a2-new-secondary"',html)
        self.assertIn('/admin2/members',html)
        self.assertEqual(['회원 관리'],[i['label'] for i in new_admin_nav('/admin2/members') if i['active']])


if __name__=='__main__':unittest.main()
