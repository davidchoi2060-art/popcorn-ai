"""Page/auth contract, importing the no-network fixture before application code."""
import unittest
from unittest.mock import patch

from tests.test_admin_members import Fixture, auth, members
from api import admin_ui_members as ui
from fastapi import FastAPI
from fastapi.testclient import TestClient


class MemberPageContract(unittest.TestCase):
    def setUp(self):
        self.fixture=Fixture()
        self.dbpatch=patch.object(members,'engine',self.fixture);self.dbpatch.start()
        self.session=patch.object(auth,'resolve_session',side_effect=lambda sid:None if not sid else {'operator_id':7,'role':sid,'name':'fixture'})
        self.session.start()
        app=FastAPI();app.include_router(ui.router);app.include_router(members.router)
        app.middleware('http')(auth.auth_middleware)
        self.app=app;self.client=TestClient(app)
    def tearDown(self):self.client.close();self.session.stop();self.dbpatch.stop();self.fixture.db.close()
    def test_new_shell_page_protected_and_no_preview_controls(self):
        denied=self.client.get('/admin2/members')
        self.assertEqual(denied.status_code,401);self.assertIn('/admin2/login',denied.text)
        allowed=self.client.get('/admin2/members?admin=new',headers={'cookie':f'{auth.COOKIE}=viewer'})
        self.assertEqual(allowed.status_code,200)
        self.assertIn('data-admin-mode="new"',allowed.text)
        self.assertIn('/shared/admin2/members.js',allowed.text)
        self.assertIn('id="filterToggle"',allowed.text)
        self.assertIn('aria-controls="filterFields"',allowed.text)
        self.assertIn('id="rows" class="mm-member-list"',allowed.text)
        self.assertIn('저장 분류만으로 실제 고객 여부를 판단할 수 없습니다.',allowed.text)
        self.assertIn('no-store',allowed.headers['cache-control'])
        for unwanted in ['검토 시안','example.invalid','id="role"','id="scenario"','가상 회원']:
            self.assertNotIn(unwanted,allowed.text)
        self.assertEqual(self.fixture.calls,[])
    def test_fixed_search_precedes_detail_no_duplicate_routes(self):
        paths=[(m,r.path) for router in (ui.router,members.router) for r in router.routes if hasattr(r,'methods') for m in r.methods]
        self.assertEqual(len(paths),len(set(paths)))
        self.assertLess(paths.index(('GET','/api/admin/members/search')),paths.index(('GET','/api/admin/members/{member_id}')))
    def test_mutation_log_failure_rollback_through_auth(self):
        with patch.object(members,'_log',side_effect=RuntimeError('fixture')):
            with self.assertRaises(RuntimeError):
                self.client.post('/api/admin/members/1/map-request',headers={'cookie':f'{auth.COOKIE}=operator'})
        self.assertIsNone(members.member_detail(1)['member']['requested_at'])


if __name__=='__main__':unittest.main()
