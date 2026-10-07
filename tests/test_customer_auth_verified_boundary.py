"""Closed customer dev issuer; actual handlers, isolated ASGI/caller mocks only.

The accepted owner harness blocks production api.db import, .env and network.
This does not implement or prove a real member identity issuer.
"""
import ast
import asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

# The network/import guard and fake api.db are installed before auth is loaded.
from tests import test_commerce_owner_contexts as isolated
from tests.test_commerce_owner import BINDING, TOKEN, policy, row

auth = isolated.auth
FastAPI, Request, Response, TestClient = (
    isolated.FastAPI, isolated.Request, isolated.Response, isolated.TestClient)
ORIGIN = isolated.ORIGIN
UNAVAILABLE = 'auth_unavailable'
NOTE = ('회원 본인 확인 기능을 준비 중입니다. 현재 로그인·가입을 이용할 수 없습니다.'
        ' 상담·추천은 로그인 없이 이용할 수 있습니다.')


class NoDatabase:
    def __init__(self): self.calls = []
    def begin(self):
        self.calls.append('begin')
        raise AssertionError('auth attempted a database transaction')
    def connect(self):
        self.calls.append('connect')
        raise AssertionError('auth attempted a database connection')


def request(path='/api/auth/login', method='POST', cookie=None):
    headers = [] if cookie is None else [(b'cookie', (auth.COOKIE+'='+cookie).encode())]
    return Request({'type':'http', 'method':method, 'path':path, 'headers':headers,
                    'scheme':'https', 'server':('shop.example',443),
                    'client':('127.0.0.1',4321), 'query_string':b''})


class VerifiedBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.database = NoDatabase()
        db = patch.object(auth, 'engine', self.database)
        db.start(); self.addCleanup(db.stop)
        self.issuer = Mock(side_effect=AssertionError('member session issuance attempted'))
        issuer = patch.object(auth, '_new_session', self.issuer)
        issuer.start(); self.addCleanup(issuer.stop)
        self.app = FastAPI()
        self.app.include_router(auth.router)
        self.app.middleware('http')(auth.member_middleware)
        self.member_handler = Mock(side_effect=AssertionError('unverified member route reached'))

        @self.app.get('/api/my/probe')
        def probe():
            self.member_handler()
            return auth.require_member()

        self.client = TestClient(self.app, base_url=ORIGIN)
        self.addCleanup(self.client.close)

    def assert_closed_effects(self, response=None):
        self.assertEqual(self.database.calls, [])
        self.issuer.assert_not_called()
        if response is not None:
            self.assertNotIn('set-cookie', response.headers)

    def test_invalid_email_still_returns_original_400_before_unavailable(self):
        for email in ('', '   ', 'invalid', 'a.example.invalid'):
            with self.subTest(email=email):
                response = self.client.post('/api/auth/login', json={'email':email,'provider':'google'})
                self.assertEqual(response.status_code,400)
                self.assertEqual(response.json(),{'detail':'이메일 형식이 올바르지 않습니다'})
                self.assert_closed_effects(response)

    def test_every_known_unknown_and_claimed_verified_provider_is_unavailable(self):
        for provider in [*auth.VIA, '', 'password', 'verified', 'unknown-provider']:
            with self.subTest(provider=provider):
                response = self.client.post('/api/auth/login', json={
                    'email':'existing@example.invalid','nickname':'fixture','provider':provider,
                    'verified':True,'auth_subject':'claimed-client-subject','member_id':11})
                self.assertEqual(response.status_code,503)
                self.assertEqual(response.json()['detail']['error'],UNAVAILABLE)
                self.assertIn('준비 중',response.json()['detail']['detail'])
                self.assertNotIn('existing@example.invalid',response.text)
                self.assertNotIn('claimed-client-subject',response.text)
                self.assert_closed_effects(response)

    def test_default_dev_existing_cookie_cannot_login_or_register(self):
        for email in ('existing@example.invalid','new@example.invalid'):
            response = self.client.post('/api/auth/login', json={'email':email},
                headers={'Cookie':auth.COOKIE+'=previous-dev-session'})
            self.assertEqual(response.status_code,503)
            self.assertEqual(response.json()['detail']['error'],UNAVAILABLE)
            self.assert_closed_effects(response)

    def test_localhost_and_configuration_markers_never_open_issuer(self):
        for secure in ('0','1','true'):
            with self.subTest(secure=secure), patch.dict(auth.os.environ, {
                'COOKIE_SECURE':secure, 'UI_CHECK_DEV_LOGIN':'1',
                'CUSTOMER_AUTH_VERIFIED':'1', 'ALLOW_DEV_LOGIN':'1'}, clear=True):
                response = Response()
                response.set_cookie = Mock(side_effect=AssertionError('auth cookie issuance attempted'))
                with self.assertRaises(isolated.auth.HTTPException) as caught:
                    auth.login(auth.LoginBody(email='member@example.invalid',provider='google'),
                               request(),response)
                self.assertEqual(caught.exception.status_code,503)
                self.assertEqual(caught.exception.detail['error'],UNAVAILABLE)
                response.set_cookie.assert_not_called()
                self.assert_closed_effects()

    def test_login_blocks_before_cookie_policy_or_session_random_generation(self):
        with patch.object(auth,'cookie_secure',side_effect=AssertionError('cookie policy consulted')):
            response = self.client.post('/api/auth/login',json={'email':'member@example.invalid'})
        self.assertEqual(response.status_code,503)
        self.assert_closed_effects(response)

    def test_all_previous_session_markers_resolve_none_without_database(self):
        for sid in ('',None,'previous-valid-dev-session','a'*64,'claimed-verified-session'):
            with self.subTest(sid=sid):
                self.assertIsNone(auth.resolve_session(sid))
        self.assert_closed_effects()

    def test_me_with_previous_cookie_is_unauthenticated_truthful_and_readonly(self):
        response = self.client.get('/api/auth/me',headers={'Cookie':auth.COOKIE+'=previous-dev-session'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json(),{'authenticated':False,'member':None,'note':NOTE})
        self.assertNotIn('입력 이메일을 신원으로 신뢰',response.text)
        self.assert_closed_effects(response)

    def test_me_without_cookie_is_identical_and_never_issues(self):
        response = self.client.get('/api/auth/me')
        self.assertEqual(response.json(),{'authenticated':False,'member':None,'note':NOTE})
        self.assert_closed_effects(response)

    def test_previous_dev_cookie_member_route_is_401_without_handler_or_lookup(self):
        response = self.client.get('/api/my/probe?email=existing@example.invalid',
            headers={'Cookie':auth.COOKIE+'=previous-valid-dev-session'})
        self.assertEqual(response.status_code,401)
        self.assertEqual(response.json(),{'detail':'로그인이 필요합니다'})
        self.member_handler.assert_not_called()
        self.assert_closed_effects(response)

    def test_require_member_remains_401_with_no_principal(self):
        token = auth._current.set(None)
        try:
            with self.assertRaises(isolated.auth.HTTPException) as caught:
                auth.require_member()
            self.assertEqual(caught.exception.status_code,401)
        finally:
            auth._current.reset(token)
        self.assert_closed_effects()

    def test_contextvar_restores_after_member_rejection_success_and_downstream_error(self):
        async def check(path, fail=False):
            before = {'member_id':99,'via':'dev'}
            token = auth._current.set(before)
            handler = Mock()
            async def next_handler(req):
                handler()
                self.assertIsNone(auth.current_member())
                if fail:
                    raise RuntimeError('fixture downstream error')
                return Response()
            try:
                if fail:
                    with self.assertRaisesRegex(RuntimeError,'fixture downstream error'):
                        await auth.member_middleware(request(path,'GET','previous-dev-session'),next_handler)
                else:
                    response = await auth.member_middleware(request(path,'GET','previous-dev-session'),next_handler)
                    self.assertEqual(response.status_code,401 if path.startswith('/api/my/') else 200)
                if path.startswith('/api/my/'):
                    handler.assert_not_called()
                else:
                    handler.assert_called_once()
                self.assertEqual(auth.current_member(),before)
            finally:
                auth._current.reset(token)
        asyncio.run(check('/api/my/orders'))
        asyncio.run(check('/api/orders'))
        asyncio.run(check('/api/orders',True))
        asyncio.run(check('/api/commerce/orders/fixture-order',True))
        self.assert_closed_effects()

    def test_secure_guest_context_remains_independent_with_previous_member_cookie(self):
        engine = isolated.Engine()
        engine.data['contexts'][row()['credential_hash']] = row()
        engine.data['users'] = [11]
        before = deepcopy(engine.data)
        self.app.include_router(isolated.routes.router)
        with patch.object(isolated.routes,'get_policy',return_value=policy()), \
                patch.object(isolated.routes,'get_engine',return_value=engine):
            response = self.client.get(isolated.ENDPOINT,params={'expected_binding_id':BINDING},
                headers={'Cookie':auth.COOKIE+'=previous-dev-session; '+isolated.o.COOKIE+'='+TOKEN})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['context'],{'state':'confirmed','binding_id':BINDING})
        self.assertEqual(engine.data,before)
        self.assertEqual(engine.commits,0)
        self.assert_closed_effects(response)

    def test_previous_member_cookie_alone_never_supplies_guest_ownership(self):
        engine = isolated.Engine()
        self.app.include_router(isolated.routes.router)
        with patch.object(isolated.routes,'get_policy',return_value=policy()), \
                patch.object(isolated.routes,'get_engine',return_value=engine):
            response = self.client.get(isolated.ENDPOINT,
                headers={'Cookie':auth.COOKIE+'=previous-dev-session; pc_vid=tracking-only'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['context'],{'state':'unconfirmed','binding_id':None})
        self.assertNotIn('lookup',[tag for tag,_ in engine.trace])
        self.assert_closed_effects(response)

    def test_guest_post_can_issue_only_independent_guest_cookie_in_simulation(self):
        engine = isolated.Engine()
        self.app.include_router(isolated.routes.router)
        with patch.object(isolated.routes,'get_policy',return_value=policy()), \
                patch.object(isolated.routes,'get_engine',return_value=engine):
            response = self.client.post(isolated.ENDPOINT,json={'expected_binding_id':None},
                headers={**isolated.GOOD_HEADERS,'Cookie':auth.COOKIE+'=previous-dev-session'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['context']['state'],'confirmed')
        self.assertEqual(engine.commits,1)
        self.assertTrue(response.headers['set-cookie'].startswith(isolated.o.COOKIE+'='))
        self.assertNotIn(auth.COOKIE,response.headers['set-cookie'])
        self.assert_closed_effects()  # Guest issuance is a separate mocked transaction.

    def test_logout_without_cookie_still_deletes_member_cookie_without_database(self):
        response = self.client.post('/api/auth/logout')
        self.assertEqual(response.json(),{'ok':True})
        self.assertIn(auth.COOKIE+'=',response.headers['set-cookie'])
        self.assertIn('Max-Age=0',response.headers['set-cookie'])
        self.assert_closed_effects()

    def test_logout_preserves_revocation_before_cookie_deletion(self):
        trace = []
        class RevocationConnection:
            def __enter__(self): trace.append('begin'); return self
            def __exit__(self,*args): trace.append('exit')
            def execute(self,statement,params): trace.append((str(statement),params))
        engine = SimpleNamespace(begin=lambda:RevocationConnection())
        with patch.object(auth,'engine',engine):
            response = self.client.post('/api/auth/logout',headers={'Cookie':auth.COOKIE+'=previous-dev-session'})
        self.assertEqual(response.json(),{'ok':True})
        self.assertEqual(trace,['begin',(
            'UPDATE member_sessions SET revoked_at=now() WHERE session_id=:s AND revoked_at IS NULL',
            {'s':'previous-dev-session'}),'exit'])
        self.assertIn('Max-Age=0',response.headers['set-cookie'])
        self.issuer.assert_not_called()

    def test_two_gates_are_unconditional_and_login_keeps_email_validation_priority(self):
        module = ast.parse(Path(auth.__file__).read_text(encoding='utf-8'))
        login = next(n for n in module.body if isinstance(n,ast.FunctionDef) and n.name=='login')
        resolver = next(n for n in module.body if isinstance(n,ast.FunctionDef) and n.name=='resolve_session')
        self.assertIsInstance(login.body[2],ast.If)
        self.assertEqual(login.body[2].body[0].exc.args[0].value,400)
        self.assertIsInstance(login.body[3],ast.Raise)
        self.assertEqual(login.body[3].exc.args[0].value,503)
        self.assertEqual(ast.dump(resolver.body[1]),ast.dump(ast.parse('return None').body[0]))
        self.assertFalse(any(isinstance(n,(ast.If,ast.Try)) for n in login.body[:2]))


if __name__ == '__main__':
    unittest.main()
