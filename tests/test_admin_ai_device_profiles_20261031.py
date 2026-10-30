"""AI 슈퍼컴퓨터 표시 정보 화면(ADM-PRD-060 · 가칭, 2026-10-31 관리자단 개선 PR-2) — DB 없이 확인하는 것.

API(GET/PUT)는 2026-10-20(0166)부터 있었고 화면이 없었다. 이 테스트는 ① 화면·메뉴·머리말이 이어졌는지 ② PUT 이
보내지 않은 사진·상세를 지우지 않게 바뀌었는지(2026-10-31 전에는 빈 값으로 덮었다) ③ 권한·검증이 그대로인지
④ 화면이 서버 값만 쓰고 고객 화면 경로 계약을 지키는지 본다. 실제 저장은 개발 서버에서 확인한다(PR 본문).
"""
import pathlib
import unittest

from fastapi import HTTPException

from api import admin_ai_device_profiles as AD
from api import admin_nav, admin_page_intro, admin_ui_ai_device_profiles as UI
from api import auth
from api import customer_supercomputer as SC

ROOT = pathlib.Path(__file__).resolve().parents[1]
PATH = '/admin2/ai-device-profiles'


class Wiring(unittest.TestCase):
    def test_menu_intro_and_page_route(self):
        hrefs = [i[1] for g in admin_nav.NAV for i in g[2]]
        self.assertIn(PATH, hrefs)
        groups = [g[0] for g in admin_nav.NAV if PATH in [i[1] for i in g[2]]]
        self.assertEqual(groups, ['상품관리'])
        self.assertIn(PATH, admin_page_intro.INTRO)
        # 신 관리자(NEW) 작업 메뉴의 경로 묶음은 tests/test_admin_commerce_orders_page.py 가 AST 해시로 고정한다 —
        # 이 화면은 거기 넣지 않았다(활성 표시 없음). 넣으려면 그 기준 해시 갱신 절차를 함께 밟는다.
        self.assertEqual([g['label'] for g in admin_nav.new_admin_nav(PATH) if g['active']], [])
        self.assertEqual([r.path for r in UI.router.routes], [PATH])

    def test_api_routes(self):
        paths = sorted((tuple(sorted(r.methods)), r.path) for r in AD.router.routes)
        self.assertIn((('GET',), '/api/admin/ai-device-profiles'), paths)
        self.assertIn((('GET',), '/api/admin/ai-device-profiles/{code}'), paths)
        self.assertIn((('PUT',), '/api/admin/ai-device-profiles/{code}'), paths)


class PutKeepsWhatIsNotSent(unittest.TestCase):
    def test_images_and_detail_default_to_keep(self):
        v = AD.clean(AD.ProfileBody(maker=' Dell '))
        self.assertIsNone(v['images']); self.assertIsNone(v['detail'])
        self.assertEqual(v['maker'], 'Dell')
        self.assertEqual(AD.clean(AD.ProfileBody(images=[]))['images'], '[]')      # 빈 목록 = 비운다
        self.assertEqual(AD.clean(AD.ProfileBody(detail={}))['detail'], '{}')

    def test_sql_keeps_null_images_and_detail(self):
        src = (ROOT / 'api/admin_ai_device_profiles.py').read_text(encoding='utf-8')
        self.assertIn("images = COALESCE(CAST(:images AS JSONB), ai_device_profiles.images)", src)
        self.assertIn("detail = COALESCE(CAST(:detail AS JSONB), ai_device_profiles.detail)", src)
        self.assertIn("COALESCE(CAST(:images AS JSONB), '[]'::jsonb)", src)       # 새 행은 표 기본값과 같은 빈 값
        self.assertIn("COALESCE(CAST(:detail AS JSONB), '{}'::jsonb)", src)
        self.assertNotIn("images = EXCLUDED.images", src)                          # 예전 덮어쓰기 경로가 남지 않았다

    def test_image_rule_and_limits_unchanged(self):
        with self.assertRaises(HTTPException) as cm:
            AD.clean(AD.ProfileBody(images=[AD.Image(src='https://example.com/x.png')]))
        self.assertEqual(cm.exception.status_code, 422)
        AD.clean(AD.ProfileBody(images=[AD.Image(src='assets/images/supercomputer/a.png'),
                                        AD.Image(src='/api/product-images/129615/detail')]))
        with self.assertRaises(Exception):
            AD.ProfileBody(model_group='Not Valid')
        with self.assertRaises(Exception):
            AD.ProfileBody(featured_rank=0)
        with self.assertRaises(Exception):
            AD.ProfileBody(unknown_field='x')


class Permissions(unittest.TestCase):
    def test_login_and_role_gates_before_db(self):
        token = auth._current.set(None)
        try:
            with self.assertRaises(HTTPException) as cm:
                AD._me()
            self.assertEqual(cm.exception.status_code, 401)
            auth._current.set({'role': 'viewer', 'operator_id': 1, 'name': 'v'})
            self.assertEqual(AD._me()['role'], 'viewer')
            with self.assertRaises(HTTPException) as cm:
                AD._me(write=True)
            self.assertEqual(cm.exception.status_code, 403)
            self.assertFalse(AD._can_write({'role': 'viewer'}))
            self.assertTrue(AD._can_write({'role': 'operator'}))
        finally:
            auth._current.reset(token)


class HonestLabels(unittest.TestCase):
    def test_missing_uses_customer_visible_values(self):
        item = {'maker': 'Dell', 'accelerator': 'NVIDIA GB10', 'memory': '128GB', 'storage': None, 'os': None, 'images': []}
        self.assertEqual(AD._missing(item), ['storage', 'os', 'images'])
        self.assertEqual(set(AD.CUSTOMER_REQUIRED) | {'images'}, set(AD._missing({})))

    def test_derive_active_mirrors_customer_rule(self):
        # 고객 화면은 표시 이름이 비어 있을 때만 상품명 기준 값으로 채운다 — 화면 안내가 이 조건을 말한다.
        src = (ROOT / 'api/customer_supercomputer.py').read_text(encoding='utf-8')
        self.assertIn("derive(r['product_name'], r.get('p_maker')) if r['display_name'] is None else {}", src)
        self.assertEqual(SC.derive('ASUS Ascent GX10 (GB10/128GB/M.2 2TB)', 'ASUS')['storage'], '2TB')
        self.assertEqual(set(AD.FIELDS), set(AD.FIELD_LABELS))


class Screen(unittest.TestCase):
    def test_template_uses_server_values_only(self):
        tpl = (ROOT / 'templates/admin/ai_device_profiles.html.j2').read_text(encoding='utf-8')
        for needle in ('d.fields', 'd.field_labels', 'd.derived', 'd.saved', 'd.customer', 'derive_active', 'd.save_note',
                       'd.image_rule', 'd.truncated', 'can_write', 'colspan="8"'):
            self.assertIn(needle, tpl)
        body = tpl.split('{% block content %}')[1]          # 머리 주석(규칙 설명)은 빼고 실제 마크업·JS 만 본다
        self.assertNotIn('innerHTML', body)
        self.assertNotIn('http://', body)
        self.assertNotIn('https://', body)
        self.assertEqual(tpl.count('<th scope="col">'), 8)

    def test_customer_page_link_matches_mvp4(self):
        tpl = (ROOT / 'templates/admin/ai_device_profiles.html.j2').read_text(encoding='utf-8')
        self.assertIn("/mvp4/supercomputer.html?id=", tpl)
        js = (ROOT / 'mockups/mvp4/assets/js/live-checkout.js').read_text(encoding='utf-8')
        self.assertIn("supercomputer.html?id=", js)


if __name__ == '__main__':
    unittest.main()
