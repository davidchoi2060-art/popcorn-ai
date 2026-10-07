"""Execute only approved main registration/discovery AST, never api.main.

Reuse the accepted auth AST + DB-double + actual router/reader fixtures. This
does not start production, scan/import all API modules, or prove native auth.
"""
import ast
from contextvars import ContextVar
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock

from tests import test_admin_commerce_orders as isolated

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / 'api/main.py'
BASE = Path('D:/WORK/PopcornAI/outputs/opening-commerce-backend-20261005/CODEMOCK-운영등록-원main.py')
EXPECTED = 'b2cba5e7d89e871fa3c44208145d6a324afabe644d9cce713a4dda1e93cf0d45'
MEMBER_TREE = ast.parse((ROOT / 'api/customer_auth.py').read_text(encoding='utf-8'))
member = types.ModuleType('api.customer_auth')
member.__dict__.update(ContextVar=ContextVar,Request=isolated.Request,
                       run_in_threadpool=isolated.run_in_threadpool,resolve_session=Mock(return_value=None))
member_nodes=[]
for node in MEMBER_TREE.body:
    if isinstance(node,ast.AsyncFunctionDef) and node.name=='member_middleware':
        member_nodes.append(deepcopy(node))
    elif isinstance(node,(ast.Assign,ast.AnnAssign)):
        targets=node.targets if isinstance(node,ast.Assign) else [node.target]
        if any(isinstance(n,ast.Name) and n.id in {'COOKIE','_current','OPEN_PREFIXES','GUARDED_PREFIX'} for n in targets):
            member_nodes.append(deepcopy(node))
exec(compile(ast.Module(body=member_nodes,type_ignores=[]),'selected-member-auth','exec'),member.__dict__)


def _middleware_name(node):
    if (isinstance(node,ast.Expr) and isinstance(node.value,ast.Call)
            and isinstance(node.value.func,ast.Call) and isinstance(node.value.func.func,ast.Attribute)
            and isinstance(node.value.func.func.value,ast.Name) and node.value.func.func.value.id=='app'
            and node.value.func.func.attr=='middleware'):
        return node.value.args[0].id
    return None


def _build_main(path=MAIN, fail_import=False):
    """Original discovery function/assignment/include loop with bounded inventory."""
    from tests.test_commerce_physical_return_main_registration import historical_main
    source=ast.parse(historical_main(path.read_bytes()).decode('utf-8')) if path == MAIN else ast.parse(path.read_text(encoding='utf-8'))
    selected=[]
    for node in source.body:
        if isinstance(node,ast.ImportFrom) and node.level==1 and node.module in ('auth','customer_auth','admin_commerce_orders'):
            selected.append(deepcopy(node))
        elif isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in ('app','_DISCOVERED_ROUTERS') for t in node.targets):
            selected.append(deepcopy(node))
        elif _middleware_name(node) and _middleware_name(node) not in ('commerce_support_no_store', 'fulfillment_no_store'):
            # This legacy component fixture excludes the independently tested
            # support/fulfillment registration, preserving its original three layers.
            selected.append(deepcopy(node))
        elif isinstance(node,ast.FunctionDef) and node.name=='_discover_routers': selected.append(deepcopy(node))
        elif isinstance(node,ast.For) and isinstance(node.iter,ast.Name) and node.iter.id=='_DISCOVERED_ROUTERS': selected.append(deepcopy(node))
    imports=[]; inventories=[]
    def modules(locations):
        inventories.append(locations)
        return [types.SimpleNamespace(name=name) for name in ('safe_helper','main','admin_commerce_orders','_private')]
    def load(name):
        imports.append(name)
        if name=='api.admin_commerce_orders': return isolated.routes
        if name=='api.safe_helper':
            if fail_import: raise RuntimeError('discovery import must propagate')
            return types.SimpleNamespace()
        raise AssertionError('unbounded production module import')
    namespace=dict(__name__='api._main_registration_test',__package__='api',__file__=str(MAIN),
                   FastAPI=isolated.FastAPI,APIRouter=isolated.routes.APIRouter,Path=Path,
                   pkgutil=types.SimpleNamespace(iter_modules=modules),
                   importlib=types.SimpleNamespace(import_module=load))
    overrides={'api.auth':isolated.auth,'api.customer_auth':member,'api.db':isolated.fake_db,'api.main':isolated.fake_main}
    previous={name:sys.modules.get(name) for name in overrides}
    sys.modules.update(overrides)
    try: exec(compile(ast.Module(body=selected,type_ignores=[]),'selected-main-registration','exec'),namespace)
    finally:
        for name,old in previous.items():
            if old is None: sys.modules.pop(name,None)
            else: sys.modules[name]=old
    return namespace,imports,inventories,selected


class MainRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=isolated.AdminDetailTests()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.fixture.client.close()
        self.namespace,self.imports,self.inventories,self.selected=_build_main()
        self.app=self.namespace['app']
        self.fixture.client=isolated.TestClient(self.app,base_url='https://example.invalid',follow_redirects=False)
        self.addCleanup(self.fixture.client.close)
        member.resolve_session.reset_mock()

    def test_exact_two_nodes_remove_to_original_whole_main_ast(self):
        self.assertEqual(hashlib.sha256(BASE.read_bytes()).hexdigest(),EXPECTED)
        from tests.test_commerce_physical_return_main_registration import historical_main
        current=ast.parse(historical_main(MAIN.read_bytes()).decode('utf-8')); original=ast.parse(BASE.read_text(encoding='utf-8'))
        fulfillment_nodes = []
        for statement in (
                'from .commerce_fulfillment_http import create_router as create_fulfillment_router, fulfillment_no_store',
                'app.middleware("http")(fulfillment_no_store)',
                'app.include_router(create_fulfillment_router())'):
            expected = ast.dump(ast.parse(statement).body[0], include_attributes=False)
            matches = [n for n in current.body if ast.dump(n, include_attributes=False) == expected]
            self.assertEqual(1, len(matches), statement)
            fulfillment_nodes.extend(matches)
        current.body = [n for n in current.body if n not in fulfillment_nodes]
        support_imports=[n for n in current.body if isinstance(n,ast.ImportFrom)
                         and n.level==1 and n.module=='commerce_support_http']
        support_regs=[n for n in current.body if _middleware_name(n)=='commerce_support_no_store']
        self.assertEqual(len(support_imports),1); self.assertEqual(len(support_regs),1)
        self.assertEqual([(n.name,n.asname) for n in support_imports[0].names],
                         [('commerce_support_no_store',None)])
        self.assertEqual(ast.dump(support_regs[0],include_attributes=False),ast.dump(
            ast.parse('app.middleware("http")(commerce_support_no_store)').body[0],include_attributes=False))
        # Remove exactly the new two-node component; every original whole-main
        # and middleware-order assertion below remains in force.
        current.body=[n for n in current.body if not (isinstance(n,ast.ImportFrom)
                      and n.level==1 and n.module=='commerce_support_http')
                      and _middleware_name(n)!='commerce_support_no_store']
        imports=[n for n in current.body if isinstance(n,ast.ImportFrom) and n.level==1 and n.module=='admin_commerce_orders']
        registrations=[n for n in current.body if _middleware_name(n)=='admin_commerce_no_store']
        self.assertEqual(len(imports),1); self.assertEqual(len(registrations),1)
        self.assertEqual([(n.name,n.asname) for n in imports[0].names],[('admin_commerce_no_store',None)])
        normalized=deepcopy(current)
        normalized.body=[n for n in normalized.body if not (isinstance(n,ast.ImportFrom) and n.level==1 and n.module=='admin_commerce_orders')
                         and _middleware_name(n)!='admin_commerce_no_store']
        self.assertEqual(ast.dump(normalized,include_attributes=False),ast.dump(original,include_attributes=False))
        positions=[(i,_middleware_name(n)) for i,n in enumerate(current.body) if _middleware_name(n)]
        self.assertEqual([name for _,name in positions],['member_middleware','auth_middleware','admin_commerce_no_store'])
        self.assertEqual(positions[-1][0],positions[-2][0]+1)

    def test_original_discovery_auto_includes_real_router_once_with_outer_auth_order(self):
        self.assertEqual(self.imports,['api.admin_commerce_orders','api.safe_helper'])
        self.assertEqual(self.inventories,[[str(ROOT/'api')]])
        self.assertEqual(self.namespace['_DISCOVERED_ROUTERS'],[('admin_commerce_orders',isolated.routes.router)])
        expected=['/api/admin/commerce/orders/{order_no}','/api/admin/commerce/orders']
        self.assertEqual([(r.path,r.methods) for r in isolated.routes.router.routes],
                         [(path,{'GET'}) for path in expected])
        self.assertEqual(set(self.app.openapi()['paths']),set(expected))
        for path in expected:
            self.assertEqual(set(self.app.openapi()['paths'][path]),{'get'})
            actual=path.replace('{order_no}',isolated.ORDER)
            self.assertEqual(self.fixture.client.post(actual,headers={'Cookie':isolated.auth.COOKIE+'=session-21'}).status_code,405)
        self.fixture.engine_loader.assert_not_called(); self.fixture.no_finance()
        self.assertEqual([m.kwargs['dispatch'].__name__ for m in self.app.user_middleware],
                         ['admin_commerce_no_store','auth_middleware','member_middleware'])
        self.assertTrue(all(not (isinstance(n,ast.ImportFrom) and n.module=='db') for n in self.selected))

    def test_real_auth_actor_bound_get_success_has_no_store_without_identity_output(self):
        data=self.fixture.response(self.fixture.get('session-22'))
        self.assertEqual(self.fixture.auth_engine.last_seen,['session-22'])
        self.assertEqual(data['item']['order_no'],isolated.ORDER)
        self.assertEqual(data['item']['basis_state'],'unconfirmed')
        self.assertTrue(all(not x['allowed'] for x in data['item']['actions'].values()))
        self.assertEqual(self.fixture.bridge.trace.count('order_bundle'),1)
        self.assertEqual(self.fixture.stored.data,self.fixture.before)
        member.resolve_session.assert_not_called()

    def test_original_auth_401403_bypass_route_but_outer_no_store_applies(self):
        self.fixture.response(self.fixture.get(None),401)
        self.fixture.auth_engine.seed('session-21',21,role='customer')
        self.fixture.response(self.fixture.get(),403)
        self.fixture.engine_loader.assert_not_called(); self.fixture.no_finance()
        member.resolve_session.assert_not_called()

    def test_422404503_all_have_no_store_under_actual_registration_ast(self):
        self.fixture.response(self.fixture.get(params={'actor':1}),422)
        self.fixture.response(self.fixture.get(path='/api/admin/commerce/orders/missing'),404)
        self.fixture.stored.fail_tag='order_bundle'
        self.fixture.response(self.fixture.get(),503)
        self.assertEqual(self.fixture.engine.trace[-1],'close')
        self.assertEqual(self.fixture.bridge.trace[-1],'rollback')

    def test_other_paths_keep_original_response_header_and_auth_error(self):
        baseline,*_=_build_main(BASE)
        async def other(): return isolated.routes.JSONResponse({'original':'unchanged'},headers={'Cache-Control':'private, max-age=7','X-Original':'yes'})
        for app in (baseline['app'],self.app): app.add_api_route('/api/admin/unrelated',other,methods=['GET'])
        client=isolated.TestClient(baseline['app'],base_url='https://example.invalid',follow_redirects=False)
        self.addCleanup(client.close)
        for headers,status in (({'Cookie':isolated.auth.COOKIE+'=session-21'},200),({},401)):
            original=client.get('/api/admin/unrelated',headers=headers)
            changed=self.fixture.client.get('/api/admin/unrelated',headers=headers)
            self.assertEqual((changed.status_code,changed.json(),changed.headers.get('cache-control'),changed.headers.get('x-original')),
                             (status,original.json(),original.headers.get('cache-control'),original.headers.get('x-original')))
        self.fixture.no_finance()

    def test_other_path_exceptions_are_not_converted_to_503(self):
        baseline,*_=_build_main(BASE)
        async def failure(): raise RuntimeError('original other-path exception')
        for app in (baseline['app'],self.app): app.add_api_route('/public/error',failure,methods=['GET'])
        client=isolated.TestClient(baseline['app'],base_url='https://example.invalid')
        self.addCleanup(client.close)
        for target in (client,self.fixture.client):
            with self.assertRaisesRegex(RuntimeError,'original other-path exception'): target.get('/public/error')
        self.fixture.no_finance()

    def test_original_discovery_import_error_still_propagates(self):
        with self.assertRaisesRegex(RuntimeError,'discovery import must propagate'): _build_main(fail_import=True)


if __name__=='__main__': unittest.main()
