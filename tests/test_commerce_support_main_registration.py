"""Exact integration AST/bytes + selected real auth/member/routers only.

No api.main/db execution, full module imports, real sessions or PostgreSQL.
Concurrent actor tests use separate SQL doubles; they prove ContextVar flow,
NOT database concurrency/locking or native financial/customer functionality.
"""
import ast
import asyncio
from contextvars import ContextVar
from copy import deepcopy
import difflib
import hashlib
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import Mock, patch
from uuid import UUID

import httpx
from fastapi import APIRouter, FastAPI, Request
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.concurrency import run_in_threadpool

from tests import test_admin_commerce_orders as isolated
from tests import test_commerce_support_http as support_fixture
from tests.test_commerce_support_writer import command, NO, CONTEXT, TOKEN
from api import commerce_orders, commerce_owner_contexts

ROOT = Path(__file__).resolve().parents[1]
BASE = Path('D:/WORK/PopcornAI/outputs/opening-commerce-backend-20261005/support-main-code4/변경전동결')
MAIN = ROOT / 'api/main.py'
MEMBER = ROOT / 'api/customer_auth.py'
LEGACY_TEST = ROOT / 'tests/test_admin_commerce_main_registration.py'
BASE_HASHES = {
    'api/main.py': '2e22fdd6fe540dbee66e84e1a5938a3cfae825aad622080db63871573dcd1e27',
    'api/customer_auth.py': 'e43b364eb773d9ef1beae3103328eaa4df2dff2651f694aadca4bfdf159b6e50',
    'tests/test_admin_commerce_main_registration.py': '502f1fb4eb8d2ca9110711415edb1746288c3f82f0435fb8b4146762da2c7a12',
}
EXPECTED_EXCEPTION = ast.parse('''not (len(path.split("/")) in (6, 7)
    and path.split("/")[:4] == ["", "api", "commerce", "orders"]
    and path.split("/")[4] != ""
    and path.split("/")[5] == "support"
    and (len(path.split("/")) == 6 or path.split("/")[6] == ""))''').body[0].value
routes = support_fixture.routes
auth = isolated.auth

# Select exactly the original functions and constants. Even resolve_session's
# current fail-closed return is real source; no imported customer-auth module.
member = types.ModuleType('api.customer_auth')
member.__dict__.update(ContextVar=ContextVar, Request=Request, run_in_threadpool=run_in_threadpool,
                       engine=isolated.BlockedEngine())
member_tree = ast.parse(MEMBER.read_text(encoding='utf-8'))
selected_member = []
for node in member_tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in (
            'member_middleware', 'resolve_session', 'current_member'):
        selected_member.append(deepcopy(node))
    elif isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(n, ast.Name) and n.id in ('COOKIE', '_current', 'OPEN_PREFIXES', 'GUARDED_PREFIX') for n in targets):
            selected_member.append(deepcopy(node))
exec(compile(ast.Module(body=selected_member, type_ignores=[]), 'selected-real-member', 'exec'), member.__dict__)
member.resolve_session = Mock(wraps=member.resolve_session)


def middleware_name(node):
    if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Call)
            and isinstance(node.value.func.func, ast.Attribute)
            and isinstance(node.value.func.func.value, ast.Name)
            and node.value.func.func.value.id == 'app' and node.value.func.func.attr == 'middleware'):
        return node.value.args[0].id


def build_main(path=MAIN, *, fail_import=False):
    """Real main statements; only bounded inventory, import and SQL doubles."""
    from tests.test_commerce_physical_return_main_registration import historical_main
    tree = ast.parse(historical_main(path.read_bytes()).decode('utf-8')) if path == MAIN else ast.parse(path.read_text(encoding='utf-8'))
    selected = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module in (
                'auth', 'customer_auth', 'admin_commerce_orders', 'commerce_support_http'):
            selected.append(deepcopy(node))
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in ('app', '_DISCOVERED_ROUTERS') for t in node.targets):
            selected.append(deepcopy(node))
        elif middleware_name(node) and middleware_name(node) != 'fulfillment_no_store':
            selected.append(deepcopy(node))
        elif isinstance(node, ast.FunctionDef) and node.name == '_discover_routers':
            selected.append(deepcopy(node))
        elif isinstance(node, ast.For) and isinstance(node.iter, ast.Name) and node.iter.id == '_DISCOVERED_ROUTERS':
            selected.append(deepcopy(node))
    imports, inventories = [], []
    actual = dict(admin_commerce_orders=isolated.routes, commerce_orders=commerce_orders,
                  commerce_owner_contexts=commerce_owner_contexts, commerce_support_http=routes)
    helper = types.SimpleNamespace()
    def modules(locations):
        inventories.append(locations)
        return [types.SimpleNamespace(name=n) for n in (
            'safe_helper', 'commerce_support_writer', 'main', 'commerce_support_http',
            'commerce_support_core', 'commerce_owner_contexts', 'commerce_orders',
            'admin_commerce_orders', '_private')]
    def load(name):
        imports.append(name)
        if name in ('api.safe_helper', 'api.commerce_support_core', 'api.commerce_support_writer'):
            if fail_import and name == 'api.safe_helper':
                raise RuntimeError('bounded discovery failure must propagate')
            return helper
        if name.startswith('api.') and name[4:] in actual:
            return actual[name[4:]]
        raise AssertionError('unbounded module import')
    namespace = dict(__name__='api._support_registration_test', __package__='api', __file__=str(MAIN),
                     Path=Path, FastAPI=FastAPI, APIRouter=APIRouter,
                     importlib=types.SimpleNamespace(import_module=load),
                     pkgutil=types.SimpleNamespace(iter_modules=modules))
    overrides = {'api.auth':auth, 'api.customer_auth':member, 'api.admin_commerce_orders':isolated.routes,
                 'api.commerce_support_http':routes, 'api.db':isolated.fake_db, 'api.main':isolated.fake_main}
    previous = {key:sys.modules.get(key) for key in overrides}
    sys.modules.update(overrides)
    try:
        exec(compile(ast.Module(body=selected, type_ignores=[]), 'selected-real-main', 'exec'), namespace)
    finally:
        for key, old in previous.items():
            if old is None: sys.modules.pop(key, None)
            else: sys.modules[key] = old
    return namespace, imports, inventories, selected


class SupportMainRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = support_fixture.Engine()
        self.auth_engine = isolated.AuthEngine()
        for token, actor, role in [('session-21',21,'operator'),('session-22',22,'operator'),('session-viewer',23,'viewer')]:
            self.auth_engine.seed(token,actor,role,password_verified=role!='viewer')
        auth.engine = self.auth_engine; auth._device_trust_ready = None
        member.resolve_session.reset_mock()
        self.namespace, self.imports, self.inventories, self.selected = build_main()
        self.app = self.namespace['app']
        self.client = TestClient(self.app, base_url=support_fixture.POLICY.origin, follow_redirects=False)
        self.addCleanup(self.client.close)
        self.engine_patch = patch.object(routes, 'get_engine', return_value=self.engine)
        self.engine_loader = self.engine_patch.start(); self.addCleanup(self.engine_patch.stop)
        for obj, key, value in [(routes,'get_policy',support_fixture.POLICY),
                               (commerce_owner_contexts,'get_policy',support_fixture.POLICY),
                               (commerce_owner_contexts,'get_engine',self.engine)]:
            p = patch.object(obj,key,return_value=value); p.start(); self.addCleanup(p.stop)
    def headers(self, audience='customer', token=None):
        cookie = (commerce_owner_contexts.owner.COOKIE + '=' + TOKEN if audience == 'customer'
                  else auth.COOKIE + '=' + (token or 'session-21'))
        return {'Cookie':cookie, 'Origin':support_fixture.POLICY.origin, 'Content-Type':'application/json'}
    def request(self, method='GET', audience='customer', *, path=None, token=None, payload=None, query=None, headers=None):
        path = path or (support_fixture.CUSTOMER if audience=='customer' else support_fixture.ADMIN)
        params = {'expected_binding_id':CONTEXT} if audience=='customer' else {}
        params.update(query or {})
        return self.client.request(method,path,params=params,headers=headers or self.headers(audience,token),
                                   **({'json':payload} if payload is not None else {}))
    def assert_no_store(self, response, status):
        self.assertEqual(status,response.status_code,response.text)
        self.assertEqual('no-store',response.headers.get('cache-control'))
        self.assertNotIn('private-fixture',response.text)
    def test_exact_main_import_and_registration_strip_to_frozen_whole_ast_and_bytes(self):
        before = (BASE/'api/main.py').read_bytes()
        self.assertEqual(BASE_HASHES['api/main.py'],hashlib.sha256(before).hexdigest())
        from tests.test_commerce_physical_return_main_registration import historical_main
        raw = historical_main(MAIN.read_bytes()); tree = ast.parse(raw.decode('utf-8'))
        fulfillment_nodes = []
        for statement in (
                'from .commerce_fulfillment_http import create_router as create_fulfillment_router, fulfillment_no_store',
                'app.middleware("http")(fulfillment_no_store)',
                'app.include_router(create_fulfillment_router())'):
            expected = ast.dump(ast.parse(statement).body[0], include_attributes=False)
            matches = [n for n in tree.body if ast.dump(n, include_attributes=False) == expected]
            self.assertEqual(1, len(matches), statement)
            fulfillment_nodes.extend(matches)
        removed_fulfillment = {i for n in fulfillment_nodes for i in range(n.lineno-1,n.end_lineno)}
        raw = b''.join(line for i,line in enumerate(raw.splitlines(keepends=True)) if i not in removed_fulfillment)
        tree = ast.parse(raw.decode('utf-8'))
        imports = [n for n in tree.body if isinstance(n,ast.ImportFrom) and n.level==1 and n.module=='commerce_support_http']
        regs = [n for n in tree.body if middleware_name(n)=='commerce_support_no_store']
        self.assertEqual((1,1),(len(imports),len(regs)))
        self.assertEqual(ast.dump(imports[0],include_attributes=False),ast.dump(
            ast.parse('from .commerce_support_http import commerce_support_no_store').body[0],include_attributes=False))
        self.assertEqual(ast.dump(regs[0],include_attributes=False),ast.dump(
            ast.parse('app.middleware("http")(commerce_support_no_store)').body[0],include_attributes=False))
        normalized = deepcopy(tree); normalized.body = [n for n in normalized.body if not (
            isinstance(n,ast.ImportFrom) and n.level==1 and n.module=='commerce_support_http')
            and middleware_name(n)!='commerce_support_no_store']
        self.assertEqual(ast.dump(ast.parse(before.decode('utf-8')),include_attributes=False),
                         ast.dump(normalized,include_attributes=False))
        removed = {i for n in imports+regs for i in range(n.lineno-1,n.end_lineno)}
        self.assertEqual(before,b''.join(line for i,line in enumerate(raw.splitlines(keepends=True)) if i not in removed))
        order = [(i,middleware_name(n)) for i,n in enumerate(tree.body) if middleware_name(n)]
        self.assertEqual(['member_middleware','auth_middleware','admin_commerce_no_store','commerce_support_no_store'],[n for _,n in order])
        self.assertEqual(order[-2][0]+1,order[-1][0])
    def test_exact_member_exception_strip_to_frozen_whole_ast_and_bytes(self):
        before = (BASE/'api/customer_auth.py').read_bytes(); current = MEMBER.read_bytes()
        self.assertEqual(BASE_HASHES['api/customer_auth.py'],hashlib.sha256(before).hexdigest())
        tree = ast.parse(current.decode('utf-8')); original = ast.parse(before.decode('utf-8'))
        fn = next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='member_middleware')
        condition = next(n for n in ast.walk(fn) if isinstance(n,ast.If) and isinstance(n.test,ast.BoolOp) and
                         any(isinstance(v,ast.Compare) for v in n.test.values))
        self.assertEqual(5,len(condition.test.values))
        fulfillment = condition.test.values[3]
        expected = ast.parse('''not (request.method == "GET" and len(path.split("/")) in (6, 7)
            and path.split("/")[:4] == ["", "api", "commerce", "orders"]
            and path.split("/")[4] != ""
            and path.split("/")[5] == "fulfillment"
            and (len(path.split("/")) == 6 or path.split("/")[6] == ""))''').body[0].value
        self.assertEqual(ast.dump(expected,include_attributes=False),ast.dump(fulfillment,include_attributes=False))
        removed_fulfillment = set(range(fulfillment.lineno-1,fulfillment.end_lineno))
        self.assertEqual(5,len(removed_fulfillment))
        current = b''.join(line for i,line in enumerate(current.splitlines(keepends=True)) if i not in removed_fulfillment)
        condition.test.values.pop(3)
        self.assertEqual(4,len(condition.test.values))
        self.assertEqual(ast.dump(EXPECTED_EXCEPTION,include_attributes=False),ast.dump(condition.test.values[2],include_attributes=False))
        condition.test.values.pop(2)
        self.assertEqual(ast.dump(original,include_attributes=False),ast.dump(tree,include_attributes=False))
        old_lines,new_lines = before.splitlines(keepends=True),current.splitlines(keepends=True)
        changes = [x for x in difflib.SequenceMatcher(a=old_lines,b=new_lines).get_opcodes() if x[0]!='equal']
        self.assertEqual(1,len(changes)); tag,a,b,x,y = changes[0]
        self.assertEqual(('insert',0,5),(tag,b-a,y-x))
        self.assertEqual(before,b''.join(new_lines[:x]+new_lines[y:]))
    def test_legacy_test_adapter_changes_only_approved_two_functions(self):
        before = (BASE/'tests/test_admin_commerce_main_registration.py').read_bytes()
        self.assertEqual(BASE_HASHES['tests/test_admin_commerce_main_registration.py'],hashlib.sha256(before).hexdigest())
        from tests.test_commerce_physical_return_main_registration import historical_test
        current = historical_test(LEGACY_TEST.read_bytes(), 'tests/test_admin_commerce_main_registration.py'); old_tree = ast.parse(before.decode('utf-8')); tree = ast.parse(current.decode('utf-8'))
        names = {'_build_main','test_exact_two_nodes_remove_to_original_whole_main_ast'}
        originals = {n.name:n for n in ast.walk(old_tree) if isinstance(n,ast.FunctionDef) and n.name in names}
        replacements = []
        for n in ast.walk(tree):
            if isinstance(n,ast.FunctionDef) and n.name in names:
                replacements.append((n.lineno-1,n.end_lineno,originals[n.name]))
                n.body = deepcopy(originals[n.name].body)
        self.assertEqual(2,len(replacements))
        self.assertEqual(ast.dump(old_tree,include_attributes=False),ast.dump(tree,include_attributes=False))
        lines = current.splitlines(keepends=True); old_lines = before.splitlines(keepends=True)
        for start,end,node in sorted(replacements,reverse=True):
            lines[start:end] = old_lines[node.lineno-1:node.end_lineno]
        self.assertEqual(before,b''.join(lines))
    def test_original_discovery_real_four_routers_once_and_no_explicit_duplicate_include(self):
        self.assertEqual([[str(ROOT/'api')]],self.inventories)
        self.assertEqual(sorted(self.imports),self.imports)
        self.assertEqual(['admin_commerce_orders','commerce_orders','commerce_owner_contexts','commerce_support_http'],
                         [name for name,_ in self.namespace['_DISCOVERED_ROUTERS']])
        # Installed FastAPI keeps each include as a branch, not flat APIRoutes.
        # Verify each original router exactly once AND the effective OpenAPI paths.
        included = [r for r in self.app.routes if isinstance(getattr(r,'original_router',None),APIRouter)]
        self.assertEqual([router for _,router in self.namespace['_DISCOVERED_ROUTERS']],
                         [r.original_router for r in included])
        self.assertEqual(4,len(included))
        pairs = [(r.path,method) for branch in included for r in branch.original_router.routes
                 if isinstance(r,APIRoute) for method in r.methods]
        expected = [(r.path,method) for module in (isolated.routes,commerce_orders,commerce_owner_contexts,routes)
                    for r in module.router.routes for method in r.methods]
        self.assertEqual(9,len(pairs));self.assertEqual(len(pairs),len(set(pairs)))
        self.assertCountEqual(expected,pairs)
        effective = [(path,method.upper()) for path,item in self.app.openapi()['paths'].items()
                     for method in item if method in ('get','post','put','patch','delete','head','options')]
        self.assertCountEqual(expected,effective)
        self.assertNotIn('api.main',self.imports);self.assertFalse(any('_private' in n for n in self.imports))
        self.assertFalse(any(isinstance(n,ast.ImportFrom) and n.module=='db' for n in self.selected))
        self.engine_loader.assert_not_called()
    def test_real_stack_request_order_is_support_admin_auth_member(self):
        self.assertEqual(['commerce_support_no_store','admin_commerce_no_store','auth_middleware','member_middleware'],
                         [m.kwargs['dispatch'].__name__ for m in self.app.user_middleware])
        self.assertIs(routes.current_operator,auth.current_operator)
        self.assertIsNone(auth.current_operator());self.assertIsNone(member.current_member())
        self.assert_no_store(self.request(),200)
        member.resolve_session.assert_not_called()
        self.assertIsNone(auth.current_operator());self.assertIsNone(member.current_member())
    def test_bounded_discovery_import_failure_propagates_without_full_main_or_db(self):
        with self.assertRaisesRegex(RuntimeError,'bounded discovery failure'):build_main(fail_import=True)
        self.assertNotIn('api.main',sys.modules);self.engine_loader.assert_not_called()
    def test_admin_early_401_and_viewer_403_bypass_support_business_with_outer_header(self):
        for method in ('GET','POST','PUT','HEAD','OPTIONS'):
            with self.subTest(method=method):
                self.assert_no_store(self.client.request(method,support_fixture.ADMIN),401)
        for method in ('POST','PUT'):
            with self.subTest(method=method):
                self.assert_no_store(self.request(method,'admin',token='session-viewer',payload=command('record_external_contact')),403)
        member.resolve_session.assert_not_called();self.engine_loader.assert_not_called()
        self.assertEqual([],self.engine.connections)
    def test_customer_get_post_use_actual_owner_cookie_binding_and_skip_legacy_resolver(self):
        response = self.request('POST',payload=command());self.assert_no_store(response,200)
        self.assertEqual('customer',response.json()['current_case']['origin'])
        response = self.request();self.assert_no_store(response,200)
        self.assertEqual(1,len(response.json()['cases']))
        member.resolve_session.assert_not_called()
        self.assertTrue(any(domain=='commerce_owner' and tag=='lookup' for conn in self.engine.connections for domain,tag,_,_ in conn.trace))
        missing = self.client.get(support_fixture.CUSTOMER,params={'expected_binding_id':CONTEXT})
        self.assert_no_store(missing,401);self.assertEqual('owner_context_lost',missing.json()['detail']['code'])
    def test_admin_get_post_actual_actor_readonly_and_current_context_reset(self):
        response = self.request('POST','admin',token='session-22',payload=command('record_external_contact'))
        self.assert_no_store(response,200)
        self.assertEqual(22,next(iter(self.engine.data['events'].values()))['actor']['operator_id'])
        self.assert_no_store(self.request(audience='admin',token='session-viewer'),200)
        self.assertEqual(['session-22','session-viewer'],self.auth_engine.last_seen)
        member.resolve_session.assert_not_called();self.assertIsNone(auth.current_operator())
    def test_unsupported_methods_405_both_audiences_skip_legacy_and_business_sql(self):
        for audience in ('customer','admin'):
            for method in ('PUT','HEAD','OPTIONS'):
                with self.subTest(audience=audience,method=method):
                    self.assert_no_store(self.request(method,audience),405)
        member.resolve_session.assert_not_called();self.engine_loader.assert_not_called()
        self.assertEqual([],self.engine.connections)
    def test_single_trailing_redirect_307_all_methods_keeps_no_store_and_no_business(self):
        for audience,path in [('customer',support_fixture.CUSTOMER),('admin',support_fixture.ADMIN)]:
            for method in ('GET','POST','PUT','HEAD','OPTIONS'):
                with self.subTest(audience=audience,method=method):
                    response = self.request(method,audience,path=path+'/',payload=command() if method=='POST' else None)
                    self.assert_no_store(response,307)
                    self.assertEqual(path,httpx.URL(response.headers['location']).path)
        member.resolve_session.assert_not_called();self.engine_loader.assert_not_called()
    def test_exact_customer_exclusion_does_not_expand_to_other_paths_or_my(self):
        for path in ('/api/commerce/orders/x/support-extra','/api/commerce/orders/x/support/extra',
                     '/api/commerce/orders/x/support//','/api/commerce/orders//support','/api/commerce/orders/x'):
            with self.subTest(path=path):
                member.resolve_session.reset_mock()
                self.client.put(path)
                member.resolve_session.assert_called_once()
        member.resolve_session.reset_mock()
        response = self.client.get('/api/my/support-probe');self.assertEqual(401,response.status_code)
        member.resolve_session.assert_called_once();self.engine_loader.assert_not_called()
        self.assertEqual([],self.engine.connections)
    def test_existing_owner_and_order_get_exceptions_and_legacy_post_stay_original(self):
        response = self.client.get('/api/commerce/owner-context');self.assertEqual(200,response.status_code,response.text)
        member.resolve_session.assert_not_called()
        response = self.client.get('/api/commerce/orders/'+NO,params={'expected_binding_id':CONTEXT})
        self.assertEqual(401,response.status_code,response.text);member.resolve_session.assert_not_called()
        response = self.client.post('/api/commerce/orders/'+NO)
        self.assertEqual(405,response.status_code);member.resolve_session.assert_called_once()
        for path in ('/api/admin/commerce/orders','/api/admin/commerce/orders/'+NO):
            response = self.client.get(path);self.assert_no_store(response,401)
    def test_json_origin_duplicate_body_and_query_errors_no_store_under_whole_stack(self):
        for audience,path in [('customer',support_fixture.CUSTOMER),('admin',support_fixture.ADMIN)]:
            params = {'expected_binding_id':CONTEXT} if audience=='customer' else {}
            headers = self.headers(audience)
            for raw,status in [('{',422),('x'*(routes.MAX_REQUEST_BYTES+1),422)]:
                with self.subTest(audience=audience,status=status):
                    response = self.client.post(path,params=params,headers=headers,content=raw)
                    self.assert_no_store(response,status)
            response = self.client.post(path,params=params,headers=headers|{'Origin':'https://evil.invalid'},json={})
            self.assert_no_store(response,403)
            response = self.client.post(path,params=params,headers=headers|{'Content-Type':'text/plain'},content='{}')
            self.assert_no_store(response,415)
            response = self.client.get(path,params=params|{'role':'owner'},headers=headers)
            self.assert_no_store(response,422)
        member.resolve_session.assert_not_called();self.engine_loader.assert_not_called()
    def test_missing_configuration_or_plain_http_fails_closed_with_outer_no_store(self):
        from api import commerce_owner as owner
        with patch.object(routes,'get_policy',side_effect=owner.OwnerError(503,'owner_configuration_unready')):
            for audience in ('customer','admin'):
                self.assert_no_store(self.request(audience=audience),503)
        with TestClient(self.app,base_url='http://example.invalid') as plain:
            response = plain.get(support_fixture.CUSTOMER,params={'expected_binding_id':CONTEXT},headers=self.headers())
            self.assert_no_store(response,503)
        member.resolve_session.assert_not_called();self.engine_loader.assert_not_called()
    def test_unrelated_paths_keep_original_header_auth_and_exceptions(self):
        baseline,*_ = build_main(BASE/'api/main.py')
        async def other():return JSONResponse({'original':'yes'},headers={'Cache-Control':'private, max-age=7','X-Original':'yes'})
        async def failure():raise RuntimeError('original unrelated exception')
        for app in (baseline['app'],self.app):
            app.add_api_route('/api/admin/unrelated',other,methods=['GET'])
            app.add_api_route('/public/unrelated-error',failure,methods=['GET'])
        with TestClient(baseline['app'],base_url=support_fixture.POLICY.origin) as client:
            for headers in ({},self.headers('admin')):
                original = client.get('/api/admin/unrelated',headers=headers)
                current = self.client.get('/api/admin/unrelated',headers=headers)
                self.assertEqual((original.status_code,original.content,original.headers.get('cache-control'),original.headers.get('x-original')),
                                 (current.status_code,current.content,current.headers.get('cache-control'),current.headers.get('x-original')))
            for target in (client,self.client):
                with self.assertRaisesRegex(RuntimeError,'original unrelated exception'):target.get('/public/unrelated-error')
        self.engine_loader.assert_not_called()
    def test_concurrent_real_contextvars_survive_threadpool_actor_split_and_reverse_responses(self):
        engines = {21:support_fixture.Engine(),22:support_fixture.Engine()}
        barrier, done22 = threading.Barrier(2), threading.Event()
        observed, completion = [], []
        actual = auth.current_operator
        def getter():
            actor = actual()
            observed.append((actor['operator_id'] if actor else None,threading.get_ident()))
            return actor
        def choose_engine():
            return engines[actual()['operator_id']]
        for actor,engine in engines.items():
            def interleave(tag,actor=actor,engine=engine):
                conn = engine.connections[-1]
                if tag=='scope' and not conn.readonly:barrier.wait(timeout=5)
                if actor==21 and tag=='clock' and conn.readonly:
                    if not done22.wait(timeout=5):raise AssertionError('reverse response synchronization failed')
            engine.after_tag = interleave
        async def run():
            loop_thread = threading.get_ident()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url=support_fixture.POLICY.origin) as client:
                async def post(actor):
                    response = await client.post(support_fixture.ADMIN,headers=self.headers('admin','session-'+str(actor)),
                                                 json=command('record_external_contact',op=actor))
                    completion.append(actor)
                    if actor==22:done22.set()
                    return actor,response
                results = await asyncio.gather(post(21),post(22))
            return loop_thread,results
        with patch.object(routes,'current_operator',side_effect=getter),patch.object(routes,'get_engine',side_effect=choose_engine):
            loop_thread,results = asyncio.run(run())
        self.assertEqual([22,21],completion)
        for actor,response in results:
            self.assert_no_store(response,200)
            events = list(engines[actor].data['events'].values())
            self.assertEqual(1,len(events));self.assertEqual(actor,events[0]['actor']['operator_id'])
            self.assertTrue(any(a==actor and thread!=loop_thread for a,thread in observed))
        member.resolve_session.assert_not_called();self.assertIsNone(auth.current_operator())


if __name__ == '__main__':
    unittest.main()
