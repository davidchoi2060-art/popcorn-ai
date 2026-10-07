"""Selected real main/auth/member + actual fulfillment factory, SQL doubles only.

No full api.main/auth/db imports, TCP, production environment or native PG.
Existing shipping39 business tests are fixtures here, not rerun test cases.
"""
import ast
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

# This installs the original isolated auth AST and external-IO audit guard first.
from tests import test_commerce_support_main_registration as support
from tests import test_commerce_fulfillment_http as shipping
from api import commerce_orders, commerce_owner_contexts

ROOT = Path(__file__).resolve().parents[1]
BASE = Path('D:/WORK/PopcornAI/outputs/admin-sourcing-inbound-20261003/U2-E-정책잠금/배송-main-정확5-CODE-변경전-20261005')
HASHES = {
    'api/main.py': '49ed9dd9f1a45f0687e85a6e18631d508a450cb64309e16cdb6670f2d1a72920',
    'api/customer_auth.py': 'db3542405b0a8f2ecf682d3df8b8968adc8e9b67e26091d83e74310e9a20d4c5',
    'tests/test_admin_commerce_main_registration.py': '50e609e2b3f6f685dedf87e18d000cf90cac309ca010b38e720470eaf19049d7',
    'tests/test_commerce_support_main_registration.py': 'fa6854fd2a973dcc8db36c0ad9885e2ba33d4df20b9c3542cce3ee859c9a5384',
}
MAIN_NODES = (
    'from .commerce_fulfillment_http import create_router as create_fulfillment_router, fulfillment_no_store',
    'app.middleware("http")(fulfillment_no_store)',
    'app.include_router(create_fulfillment_router())',
)
MEMBER_EXCEPTION = ast.parse('''not (request.method == "GET" and len(path.split("/")) in (6, 7)
    and path.split("/")[:4] == ["", "api", "commerce", "orders"]
    and path.split("/")[4] != ""
    and path.split("/")[5] == "fulfillment"
    and (len(path.split("/")) == 6 or path.split("/")[6] == ""))''').body[0].value
auth, member, h = support.auth, support.member, shipping.h


def dump(node):
    return ast.dump(node, include_attributes=False)


def build_main(path=ROOT/'api/main.py', *, fail_import=False):
    """Execute original discovery/registration statements with bounded imports."""
    from tests.test_commerce_physical_return_main_registration import historical_main
    tree = ast.parse(historical_main(path.read_bytes()).decode('utf-8')) if path == ROOT/'api/main.py' else ast.parse(path.read_text(encoding='utf-8'))
    selected = []
    include = dump(ast.parse(MAIN_NODES[2]).body[0])
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module in (
                'auth', 'customer_auth', 'admin_commerce_orders',
                'commerce_support_http', 'commerce_fulfillment_http'):
            selected.append(deepcopy(node))
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and
                t.id in ('app', '_DISCOVERED_ROUTERS') for t in node.targets):
            selected.append(deepcopy(node))
        elif support.middleware_name(node) or dump(node) == include:
            selected.append(deepcopy(node))
        elif isinstance(node, ast.FunctionDef) and node.name == '_discover_routers':
            selected.append(deepcopy(node))
        elif isinstance(node, ast.For) and isinstance(node.iter, ast.Name) and node.iter.id == '_DISCOVERED_ROUTERS':
            selected.append(deepcopy(node))
    actual = dict(admin_commerce_orders=support.isolated.routes,
                  commerce_orders=commerce_orders, commerce_owner_contexts=commerce_owner_contexts,
                  commerce_support_http=support.routes, commerce_fulfillment_http=h)
    helpers = {'safe_helper', 'commerce_fulfillment_read', 'commerce_fulfillment_writer', 'commerce_support_core'}
    imports, inventories = [], []
    def modules(locations):
        inventories.append(locations)
        return [types.SimpleNamespace(name=n) for n in list(actual)+sorted(helpers)+['main', '_private']]
    def load(name):
        imports.append(name)
        if name == 'api.safe_helper' and fail_import:
            raise RuntimeError('bounded discovery failure must propagate')
        if name.startswith('api.') and name[4:] in actual:
            return actual[name[4:]]
        if name.startswith('api.') and name[4:] in helpers:
            return types.SimpleNamespace()
        raise AssertionError('unbounded production import')
    namespace = dict(__name__='api._fulfillment_registration_test', __package__='api', __file__=str(ROOT/'api/main.py'),
                     Path=Path, FastAPI=FastAPI, APIRouter=APIRouter,
                     importlib=types.SimpleNamespace(import_module=load),
                     pkgutil=types.SimpleNamespace(iter_modules=modules))
    overrides = {'api.auth':auth, 'api.customer_auth':member,
                 'api.admin_commerce_orders':support.isolated.routes,
                 'api.commerce_support_http':support.routes, 'api.commerce_fulfillment_http':h,
                 'api.db':support.isolated.fake_db, 'api.main':support.isolated.fake_main}
    previous = {k:sys.modules.get(k) for k in overrides}
    sys.modules.update(overrides)
    try:
        exec(compile(ast.Module(body=selected, type_ignores=[]), 'selected-real-fulfillment-main', 'exec'), namespace)
    finally:
        for key, old in previous.items():
            if old is None: sys.modules.pop(key, None)
            else: sys.modules[key] = old
    return namespace, imports, inventories, selected


class FulfillmentMainRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.auth_engine = support.isolated.AuthEngine()
        for token, actor, role in [('session-7',7,'operator'), ('session-viewer',9,'viewer')]:
            self.auth_engine.seed(token, actor, role)
        auth.engine = self.auth_engine; auth._device_trust_ready = None
        self.engine = shipping.Engine(self.auth_engine)
        member.resolve_session.reset_mock()
        self.factory = patch.object(h, 'create_router', wraps=h.create_router)
        self.factory_mock = self.factory.start(); self.addCleanup(self.factory.stop)
        self.namespace, self.imports, self.inventories, self.selected = build_main()
        self.app = self.namespace['app']
        self.client = TestClient(self.app, base_url=shipping.POLICY.origin, follow_redirects=False)
        self.addCleanup(self.client.close)
        for obj, key, value in [(h,'get_engine',self.engine), (h,'get_auth',auth),
                               (h.owner_http,'get_policy',shipping.POLICY)]:
            p = patch.object(obj,key,return_value=value); mock = p.start(); self.addCleanup(p.stop)
            if key == 'get_engine': self.engine_loader = mock

    def headers(self, token='session-7', *, customer=False):
        return {'Cookie': (shipping.owner.COOKIE+'='+shipping.TOKEN if customer else auth.COOKIE+'='+token),
                'Origin':shipping.POLICY.origin, 'Content-Type':'application/json'}

    def request(self, method='GET', path=shipping.ADMIN, *, customer=False, token='session-7', **kwargs):
        params = kwargs.pop('params', {'expected_binding_id':self.engine.owner_context['context_id']} if customer else {})
        return self.client.request(method,path,params=params,headers=kwargs.pop('headers',self.headers(token,customer=customer)),**kwargs)

    def check(self, response, status):
        self.assertEqual(status,response.status_code,response.text)
        self.assertEqual('no-store',response.headers.get('cache-control'))
        for private in (shipping.fixture.PRIVATE, shipping.TOKEN, 'session-7', 'provider_binding', 'owner_identity'):
            self.assertNotIn(private,response.text)
        return response.json() if response.content else None

    def before(self, rel):
        data = (BASE/rel).read_bytes()
        self.assertEqual(HASHES[rel],hashlib.sha256(data).hexdigest())
        return data

    def test_exact_three_main_nodes_preserve_original_whole_ast_and_bytes(self):
        from tests.test_commerce_physical_return_main_registration import historical_main
        before = self.before('api/main.py'); raw = historical_main((ROOT/'api/main.py').read_bytes())
        tree = ast.parse(raw.decode('utf-8')); nodes = []
        for statement in MAIN_NODES:
            matches = [n for n in tree.body if dump(n) == dump(ast.parse(statement).body[0])]
            self.assertEqual(1,len(matches),statement); nodes.extend(matches)
        support_reg = next(n for n in tree.body if support.middleware_name(n)=='commerce_support_no_store')
        discovery = next(n for n in tree.body if isinstance(n,ast.For) and isinstance(n.iter,ast.Name) and n.iter.id=='_DISCOVERED_ROUTERS')
        self.assertEqual(support_reg.end_lineno+1,nodes[1].lineno)
        self.assertEqual(discovery.end_lineno+1,nodes[2].lineno)
        mounts = [n.lineno for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
                  and isinstance(n.func.value,ast.Name) and n.func.value.id=='app' and n.func.attr=='mount']
        self.assertLess(nodes[2].lineno,min(mounts))
        removed = {i for n in nodes for i in range(n.lineno-1,n.end_lineno)}
        stripped = b''.join(line for i,line in enumerate(raw.splitlines(keepends=True)) if i not in removed)
        tree.body = [n for n in tree.body if n not in nodes]
        self.assertEqual(before,stripped); self.assertEqual(dump(ast.parse(before.decode('utf-8'))),dump(tree))

    def test_exact_get_member_exception_preserves_whole_source_and_closed_issuer(self):
        before = self.before('api/customer_auth.py'); raw = (ROOT/'api/customer_auth.py').read_bytes()
        tree = ast.parse(raw.decode('utf-8'))
        fn = next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='member_middleware')
        cond = next(n for n in ast.walk(fn) if isinstance(n,ast.If) and isinstance(n.test,ast.BoolOp)
                    and any(isinstance(v,ast.Compare) for v in n.test.values))
        self.assertEqual(5,len(cond.test.values)); added = cond.test.values[3]
        self.assertEqual(dump(MEMBER_EXCEPTION),dump(added)); cond.test.values.pop(3)
        removed = set(range(added.lineno-1,added.end_lineno)); self.assertEqual(5,len(removed))
        self.assertEqual(before,b''.join(line for i,line in enumerate(raw.splitlines(keepends=True)) if i not in removed))
        self.assertEqual(dump(ast.parse(before.decode('utf-8'))),dump(tree))
        self.assertIsNone(member.resolve_session._mock_wraps('unverified-member'))

    def test_existing_test_adapters_change_only_allocated_functions(self):
        allowed = {
            'tests/test_admin_commerce_main_registration.py': {'_build_main','test_exact_two_nodes_remove_to_original_whole_main_ast'},
            'tests/test_commerce_support_main_registration.py': {'build_main',
                'test_exact_main_import_and_registration_strip_to_frozen_whole_ast_and_bytes',
                'test_exact_member_exception_strip_to_frozen_whole_ast_and_bytes'},
        }
        for rel,names in allowed.items():
            from tests.test_commerce_physical_return_main_registration import historical_test
            before = self.before(rel); current = historical_test((ROOT/rel).read_bytes(), rel)
            old_tree, tree = ast.parse(before.decode('utf-8')), ast.parse(current.decode('utf-8'))
            originals = {n.name:n for n in ast.walk(old_tree) if isinstance(n,ast.FunctionDef) and n.name in names}
            changes = []
            for node in ast.walk(tree):
                if isinstance(node,ast.FunctionDef) and node.name in names:
                    changes.append((node.lineno-1,node.end_lineno,originals[node.name]))
                    node.body = deepcopy(originals[node.name].body)
            self.assertEqual(len(names),len(changes)); self.assertEqual(dump(old_tree),dump(tree))
            lines, original_lines = current.splitlines(keepends=True), before.splitlines(keepends=True)
            for start,end,node in sorted(changes,reverse=True):
                lines[start:end] = original_lines[node.lineno-1:node.end_lineno]
            self.assertEqual(before,b''.join(lines))

    def test_discovery_and_actual_factory_four_routes_are_included_exactly_once(self):
        self.factory_mock.assert_called_once_with(); self.assertFalse(hasattr(h,'router'))
        self.assertEqual([[str(ROOT/'api')]],self.inventories)
        self.assertEqual(sorted(self.imports),self.imports)
        self.assertEqual(1,self.imports.count('api.commerce_fulfillment_http'))
        self.assertEqual(['admin_commerce_orders','commerce_orders','commerce_owner_contexts','commerce_support_http'],
                         [name for name,_ in self.namespace['_DISCOVERED_ROUTERS']])
        branches = [r.original_router for r in self.app.routes if isinstance(getattr(r,'original_router',None),APIRouter)]
        self.assertEqual(5,len(branches)); self.assertEqual([r for _,r in self.namespace['_DISCOVERED_ROUTERS']],branches[:-1])
        shipping_pairs = [(r.path,m) for r in branches[-1].routes if isinstance(r,APIRoute) for m in r.methods]
        self.assertCountEqual([
            ('/api/admin/commerce/orders/{order_no}/fulfillment','GET'),
            ('/api/admin/commerce/orders/{order_no}/fulfillment','POST'),
            ('/api/admin/commerce/orders/{order_no}/fulfillment/operations/{operation_id}','GET'),
            ('/api/commerce/orders/{order_no}/fulfillment','GET')],shipping_pairs)
        pairs = [(r.path,m) for branch in branches for r in branch.routes if isinstance(r,APIRoute) for m in r.methods]
        self.assertEqual(13,len(pairs)); self.assertEqual(len(pairs),len(set(pairs)))
        effective = [(path,m.upper()) for path,item in self.app.openapi()['paths'].items()
                     for m in item if m in ('get','post','put','patch','delete','head','options')]
        self.assertCountEqual(pairs,effective); self.engine_loader.assert_not_called()
        self.assertFalse(any(isinstance(n,ast.ImportFrom) and n.module=='db' for n in self.selected))

    def test_discovery_import_failure_propagates_before_factory_registration(self):
        with self.assertRaisesRegex(RuntimeError,'bounded discovery failure'): build_main(fail_import=True)
        self.factory_mock.assert_called_once_with(); self.engine_loader.assert_not_called()

    def trace_middleware(self):
        events = []
        for item in self.app.user_middleware:
            original = item.kwargs['dispatch']
            def wrap(fn):
                async def dispatch(request,call_next):
                    events.append((fn.__name__,threading.get_ident()))
                    return await fn(request,call_next)
                return dispatch
            item.kwargs['dispatch'] = wrap(original)
        return events

    def test_actual_runtime_order_contextvar_threadpool_and_reset(self):
        expected = ['fulfillment_no_store','commerce_support_no_store','admin_commerce_no_store','auth_middleware','member_middleware']
        self.assertEqual(expected,[m.kwargs['dispatch'].__name__ for m in self.app.user_middleware])
        events = self.trace_middleware(); observed = []; actual = h._session
        def session(*args):
            observed.append((auth.current_operator()['operator_id'],threading.get_ident()))
            return actual(*args)
        with patch.object(h,'_session',side_effect=session), patch.object(auth,'resolve_session',wraps=auth.resolve_session) as resolve:
            self.check(self.request(),200)
        resolve.assert_called_once(); self.assertEqual(expected,[name for name,_ in events])
        self.assertTrue(observed); self.assertTrue(all(actor==7 and thread!=events[0][1] for actor,thread in observed))
        self.assertIsNone(auth.current_operator()); self.assertIsNone(member.current_member())

    def test_early_auth_stops_inner_member_and_route_with_outer_no_store(self):
        events = self.trace_middleware()
        self.check(self.request('POST',headers={'Content-Type':'application/json'},content='{}'),401)
        self.assertEqual(['fulfillment_no_store','commerce_support_no_store','admin_commerce_no_store','auth_middleware'],[n for n,_ in events])
        member.resolve_session.assert_not_called(); self.engine_loader.assert_not_called()

    def test_exact_customer_get_and_single_trailing_slash_skip_member_resolver(self):
        self.check(self.request(path=shipping.CUSTOMER,customer=True),200)
        member.resolve_session.assert_not_called(); self.engine_loader.reset_mock()
        response = self.request(path=shipping.CUSTOMER+'/',customer=True)
        self.assertEqual(307,response.status_code); self.assertEqual('no-store',response.headers.get('cache-control'))
        member.resolve_session.assert_not_called(); self.engine_loader.assert_not_called()

    def test_customer_post_other_methods_and_neighbors_are_not_exempt(self):
        for method in ('POST','PUT','DELETE','HEAD','OPTIONS'):
            member.resolve_session.reset_mock()
            self.check(self.request(method,path=shipping.CUSTOMER,customer=True),405)
            member.resolve_session.assert_called_once()
        for path,status in ((shipping.CUSTOMER+'//',307), (shipping.CUSTOMER+'/extra',404),
                            (shipping.CUSTOMER+'s',404), ('/api/commerce/orders//fulfillment',404),
                            (shipping.CUSTOMER+'/operations/'+str(UUID(int=900)),404)):
            member.resolve_session.reset_mock()
            response = self.request(path=path,customer=True)
            self.assertEqual(status,response.status_code,response.text); member.resolve_session.assert_called_once()
            if status == 307:
                self.assertEqual(shipping.CUSTOMER,response.headers['location'].split('?',1)[0].removeprefix(shipping.POLICY.origin))
        self.engine_loader.assert_not_called()

    def test_original_owner_order_support_exceptions_and_my_gate_remain(self):
        app = FastAPI(); app.middleware('http')(member.member_middleware)
        async def echo(request:Request): return JSONResponse({'member':member.current_member()})
        app.add_api_route('/{path:path}',echo,methods=['GET','POST'])
        cases = [('POST','/api/commerce/owner-context',False,200),
                 ('GET','/api/commerce/orders/'+shipping.NO,False,200),
                 ('POST','/api/commerce/orders/'+shipping.NO,True,200),
                 ('POST','/api/commerce/orders/'+shipping.NO+'/support',False,200),
                 ('POST','/api/commerce/orders/'+shipping.NO+'/support/',False,200),
                 ('GET','/api/my/profile',True,401)]
        with TestClient(app,base_url=shipping.POLICY.origin) as client:
            for method,path,called,status in cases:
                member.resolve_session.reset_mock(); response = client.request(method,path)
                self.assertEqual(status,response.status_code,response.text)
                self.assertEqual(int(called),member.resolve_session.call_count)
                self.assertIsNone(member.current_member())
        self.engine_loader.assert_not_called()

    def test_error_statuses_are_no_store_under_actual_whole_selected_stack(self):
        self.check(self.request(headers={}),401)
        self.check(self.request('POST',token='session-viewer',content='{}'),403)
        self.check(self.request(path=shipping.ADMIN.replace(shipping.NO,'missing-order')),404)
        self.check(self.request('POST',path=shipping.ADMIN+'/operations/'+str(UUID(int=900)),content='{}'),405)
        self.check(self.request(params={'unexpected':'1'}),422)
        with TestClient(self.app,base_url='http://example.invalid') as plain:
            self.check(plain.get(shipping.ADMIN,headers=self.headers()),503)

    def test_missing_origin_blocks_before_body_business_engine_and_policy(self):
        self.assertIsNone(h.get_origin()); self.assertIsNone(h.get_policies(None,order_no=shipping.NO,action='prepare_shipment',now=100))
        with patch.object(h,'_body',new=AsyncMock()) as body, patch.object(h,'get_policies',wraps=h.get_policies) as policies:
            data = self.check(self.request('POST',content='malformed-private-fixture'),503)
        self.assertEqual('fulfillment_origin_unconnected',data['detail']['code'])
        body.assert_not_awaited(); policies.assert_not_called(); self.engine_loader.assert_not_called()
        self.assertEqual([],self.engine.connections)
        self.assertTrue(self.auth_engine.trace); self.assertEqual(['session-7'],self.auth_engine.last_seen)

    def test_missing_policy_rolls_back_caller_transaction_without_business_effects(self):
        command = shipping.FulfillmentHTTPTests.make(self); before = deepcopy(self.engine.data)
        with patch.object(h,'get_origin',return_value=shipping.POLICY.origin), patch.object(h,'get_policies',wraps=h.get_policies) as policies, \
                patch.object(shipping.writer,'execute_preparation',wraps=shipping.writer.execute_preparation) as preparation, \
                patch.object(shipping.writer,'execute_fulfillment',wraps=shipping.writer.execute_fulfillment) as fulfillment:
            data = self.check(self.request('POST',json=command),503)
        self.assertEqual('fulfillment_source_unconnected',data['detail']['code'])
        policies.assert_called_once(); preparation.assert_not_called(); fulfillment.assert_not_called()
        self.engine_loader.assert_called_once(); self.assertEqual(before,self.engine.data)
        self.assertEqual(['begin','rollback_write','close_write'],[name for name,_ in self.engine.lifecycle])
        self.assertEqual(1,len(self.engine.connections)); conn = self.engine.connections[0]
        self.assertIs(policies.call_args.args[0],conn)
        self.assertIn('session',[tag for tag,_,_ in conn.trace]); self.assertIn('scope',[tag for tag,_,_ in conn.trace])
        self.assertIsNone(h.get_origin()); self.assertIsNone(h.get_policies(None,order_no=shipping.NO,action='prepare_shipment',now=100))

    def test_outer_layer_redacts_pre_route_auth_exception_for_post(self):
        with patch.object(auth,'resolve_session',side_effect=RuntimeError(shipping.fixture.PRIVATE)):
            data = self.check(self.request('POST',content='{}'),503)
        self.assertEqual('fulfillment_unavailable',data['detail']['code'])
        self.engine_loader.assert_not_called(); member.resolve_session.assert_not_called()

    def test_customer_operation_and_wrong_method_404_405_still_have_outer_no_store(self):
        path = shipping.CUSTOMER+'/operations/'+str(UUID(int=900))
        self.check(self.request(path=path,customer=True),404)
        self.check(self.request('POST',path=path,customer=True,content='{}'),404)
        self.check(self.request('PUT',content='{}'),405)
        self.engine_loader.assert_not_called()

    def test_registered_get_keeps_disabled_actions_and_customer_public_allowlist(self):
        current = self.check(self.request(),200)
        self.assertIsNone(current['expected_order_basis']); self.assertTrue(current['actions'])
        self.assertTrue(all(v=={'allowed':False,'reason':'source_unconnected'} for v in current['actions'].values()))
        public = self.check(self.request(path=shipping.CUSTOMER,customer=True),200)
        self.assertEqual({'version','state','order_no','order_state','checked_at','context','shipments'},set(public))
        self.assertEqual('commerce_fulfillment_http_v1',public['version']); self.assertEqual('confirmed',public['state'])
        self.assertEqual([],public['shipments']); self.assertNotIn('actions',public)
        member.resolve_session.assert_not_called()

    def test_unrelated_headers_auth_and_exceptions_match_prechange_main(self):
        baseline,*_ = build_main(BASE/'api/main.py')
        async def echo(): return JSONResponse({'original':'yes'},headers={'Cache-Control':'private, max-age=7','X-Original':'yes'})
        async def failure(): raise RuntimeError('original unrelated exception')
        for app in (baseline['app'],self.app):
            app.add_api_route('/api/admin/unrelated',echo,methods=['GET'])
            app.add_api_route('/public/unrelated-error',failure,methods=['GET'])
        with TestClient(baseline['app'],base_url=shipping.POLICY.origin) as client:
            for headers in ({},self.headers()):
                before = client.get('/api/admin/unrelated',headers=headers)
                after = self.client.get('/api/admin/unrelated',headers=headers)
                self.assertEqual((before.status_code,before.content,before.headers.get('cache-control'),before.headers.get('x-original')),
                                 (after.status_code,after.content,after.headers.get('cache-control'),after.headers.get('x-original')))
            for target in (client,self.client):
                with self.assertRaisesRegex(RuntimeError,'original unrelated exception'): target.get('/public/unrelated-error')
        self.engine_loader.assert_not_called()
