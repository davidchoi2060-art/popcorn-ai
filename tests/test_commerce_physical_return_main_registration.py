"""Isolated CODE/MOCK registration with approved exact3 source overlay.

Original checkout remains unmodified; no full api.main startup.
Selected registration AST + real HTTP/auth AST with bounded imports/SQL doubles.
No full api.main/auth/db startup, PG/network or production environment.
"""
import ast
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from tests import test_commerce_support_main_registration as support
from tests import test_commerce_fulfillment_http as shipping
from tests import test_commerce_physical_return_http as returns
from api import commerce_orders, commerce_owner_contexts

ROOT=Path(__file__).resolve().parents[1]
BASE=Path('D:/WORK/PopcornAI/outputs/opening-operator-backend-20261007/return-main-registration-design')
PIN='77bf6b93bfc64c30db381a0571f28e2b7e06aa91f58dcc775283cbff901ee263'
MEMBER_PIN='4dfba638b8e8a1e86bbee6bbaa3fd046e272727039019113619f47aaab2d91b5'
AUTH_PIN='37bf680d6203376c62d086f7d180e7294627648931f530cea0e90502fa45e5d4'
NODES=(
 'from .commerce_physical_return_http import create_router as create_physical_return_router, physical_return_no_store',
 'app.middleware("http")(physical_return_no_store)',
 'app.include_router(create_physical_return_router())',
)
ORDER=['physical_return_no_store','fulfillment_no_store','commerce_support_no_store',
       'admin_commerce_no_store','auth_middleware','member_middleware']
auth,member,h=support.auth,support.member,returns.h
def dump(node):return ast.dump(node,include_attributes=False)


ADAPTER_RULES={'tests/test_admin_commerce_main_registration.py': {'_build_main': [('    '
                                                                     "source=ast.parse(path.read_text(encoding='utf-8'))",
                                                                     '    from '
                                                                     'tests.test_commerce_physical_return_main_registration '
                                                                     'import historical_main\n'
                                                                     '    '
                                                                     "source=ast.parse(historical_main(path.read_bytes()).decode('utf-8')) "
                                                                     'if path == MAIN else '
                                                                     "ast.parse(path.read_text(encoding='utf-8'))")],
                                                    'test_exact_two_nodes_remove_to_original_whole_main_ast': [('        '
                                                                                                                "current=ast.parse(MAIN.read_text(encoding='utf-8')); "
                                                                                                                "original=ast.parse(BASE.read_text(encoding='utf-8'))",
                                                                                                                '        '
                                                                                                                'from '
                                                                                                                'tests.test_commerce_physical_return_main_registration '
                                                                                                                'import '
                                                                                                                'historical_main\n'
                                                                                                                '        '
                                                                                                                "current=ast.parse(historical_main(MAIN.read_bytes()).decode('utf-8')); "
                                                                                                                "original=ast.parse(BASE.read_text(encoding='utf-8'))")]},
 'tests/test_commerce_support_main_registration.py': {'build_main': [('    tree = '
                                                                      "ast.parse(path.read_text(encoding='utf-8'))",
                                                                      '    from '
                                                                      'tests.test_commerce_physical_return_main_registration '
                                                                      'import historical_main\n'
                                                                      '    tree = '
                                                                      "ast.parse(historical_main(path.read_bytes()).decode('utf-8')) "
                                                                      'if path == MAIN else '
                                                                      "ast.parse(path.read_text(encoding='utf-8'))")],
                                                      'test_exact_main_import_and_registration_strip_to_frozen_whole_ast_and_bytes': [('        '
                                                                                                                                       'raw '
                                                                                                                                       '= '
                                                                                                                                       'MAIN.read_bytes(); '
                                                                                                                                       'tree '
                                                                                                                                       '= '
                                                                                                                                       "ast.parse(raw.decode('utf-8'))",
                                                                                                                                       '        '
                                                                                                                                       'from '
                                                                                                                                       'tests.test_commerce_physical_return_main_registration '
                                                                                                                                       'import '
                                                                                                                                       'historical_main\n'
                                                                                                                                       '        '
                                                                                                                                       'raw '
                                                                                                                                       '= '
                                                                                                                                       'historical_main(MAIN.read_bytes()); '
                                                                                                                                       'tree '
                                                                                                                                       '= '
                                                                                                                                       "ast.parse(raw.decode('utf-8'))")],
                                                      'test_legacy_test_adapter_changes_only_approved_two_functions': [('        '
                                                                                                                        'current '
                                                                                                                        '= '
                                                                                                                        'LEGACY_TEST.read_bytes(); '
                                                                                                                        'old_tree '
                                                                                                                        '= '
                                                                                                                        "ast.parse(before.decode('utf-8')); "
                                                                                                                        'tree '
                                                                                                                        '= '
                                                                                                                        "ast.parse(current.decode('utf-8'))",
                                                                                                                        '        '
                                                                                                                        'from '
                                                                                                                        'tests.test_commerce_physical_return_main_registration '
                                                                                                                        'import '
                                                                                                                        'historical_test\n'
                                                                                                                        '        '
                                                                                                                        'current '
                                                                                                                        '= '
                                                                                                                        'historical_test(LEGACY_TEST.read_bytes(), '
                                                                                                                        "'tests/test_admin_commerce_main_registration.py'); "
                                                                                                                        'old_tree '
                                                                                                                        '= '
                                                                                                                        "ast.parse(before.decode('utf-8')); "
                                                                                                                        'tree '
                                                                                                                        '= '
                                                                                                                        "ast.parse(current.decode('utf-8'))")]},
 'tests/test_commerce_fulfillment_main_registration.py': {'build_main': [('    tree = '
                                                                          "ast.parse(path.read_text(encoding='utf-8'))",
                                                                          '    from '
                                                                          'tests.test_commerce_physical_return_main_registration '
                                                                          'import historical_main\n'
                                                                          '    tree = '
                                                                          "ast.parse(historical_main(path.read_bytes()).decode('utf-8')) "
                                                                          "if path == ROOT/'api/main.py' else "
                                                                          "ast.parse(path.read_text(encoding='utf-8'))")],
                                                          'test_exact_three_main_nodes_preserve_original_whole_ast_and_bytes': [('        '
                                                                                                                                 'before '
                                                                                                                                 '= '
                                                                                                                                 "self.before('api/main.py'); "
                                                                                                                                 'raw '
                                                                                                                                 '= '
                                                                                                                                 "(ROOT/'api/main.py').read_bytes()",
                                                                                                                                 '        '
                                                                                                                                 'from '
                                                                                                                                 'tests.test_commerce_physical_return_main_registration '
                                                                                                                                 'import '
                                                                                                                                 'historical_main\n'
                                                                                                                                 '        '
                                                                                                                                 'before '
                                                                                                                                 '= '
                                                                                                                                 "self.before('api/main.py'); "
                                                                                                                                 'raw '
                                                                                                                                 '= '
                                                                                                                                 "historical_main((ROOT/'api/main.py').read_bytes())")],
                                                          'test_existing_test_adapters_change_only_allocated_functions': [('            '
                                                                                                                           'before '
                                                                                                                           '= '
                                                                                                                           'self.before(rel); '
                                                                                                                           'current '
                                                                                                                           '= '
                                                                                                                           '(ROOT/rel).read_bytes()',
                                                                                                                           '            '
                                                                                                                           'from '
                                                                                                                           'tests.test_commerce_physical_return_main_registration '
                                                                                                                           'import '
                                                                                                                           'historical_test\n'
                                                                                                                           '            '
                                                                                                                           'before '
                                                                                                                           '= '
                                                                                                                           'self.before(rel); '
                                                                                                                           'current '
                                                                                                                           '= '
                                                                                                                           'historical_test((ROOT/rel).read_bytes(), '
                                                                                                                           'rel)')]},
 'tests/test_admin_commerce_order_list.py': {'_historical_main_source': [("    tree=ast.parse(raw.decode('utf-8'))",
                                                                          '    from '
                                                                          'tests.test_commerce_physical_return_main_registration '
                                                                          'import historical_main\n'
                                                                          '    raw=historical_main(raw)\n'
                                                                          "    tree=ast.parse(raw.decode('utf-8'))")],
                                             '_historical_registration_source': [('    '
                                                                                  "name='tests/test_admin_commerce_main_registration.py'",
                                                                                  '    from '
                                                                                  'tests.test_commerce_physical_return_main_registration '
                                                                                  'import historical_test\n'
                                                                                  '    '
                                                                                  "name='tests/test_admin_commerce_main_registration.py'\n"
                                                                                  '    '
                                                                                  'raw=historical_test(raw,name)')]}}
BEFORE_PINS={'tests/test_admin_commerce_main_registration.py': '7612c1f953d7712593878de06d52bef604b56ffbea9762b7be8442981f361527', 'tests/test_commerce_support_main_registration.py': '2d800596160a63c3e00077ae7d5a520e12ed587a8afdeb814878d6150b14f40e', 'tests/test_commerce_fulfillment_main_registration.py': '442eec418d353207feac1cc2472cbac1728ca023a9694da5204bfb686fb628ac', 'tests/test_admin_commerce_order_list.py': 'c259e5fe2ee8751b0da4f8c6a0a7a24e945eacf04d711e68c9fee1721521fba8'}

CODE_BASE=Path('D:/WORK/PopcornAI/outputs/opening-operator-backend-20261007/return-main-isolated-code/before')


def historical_main(raw):
    """Positive exact approved source checks before inverse; no re-pinning."""
    tree=ast.parse(raw.decode('utf-8'))
    existing=(
        'from .commerce_support_http import commerce_support_no_store',
        'app.middleware("http")(commerce_support_no_store)',
        'from .commerce_fulfillment_http import create_router as create_fulfillment_router, fulfillment_no_store',
        'app.middleware("http")(fulfillment_no_store)',
        'app.include_router(create_fulfillment_router())',
    )
    for statement in existing+NODES:
        matches=[n for n in tree.body if dump(n)==dump(ast.parse(statement).body[0])]
        if len(matches)!=1:raise AssertionError('approved main node count/shape')
    if [support.middleware_name(n) for n in tree.body if support.middleware_name(n)]!=ORDER[::-1]:
        raise AssertionError('approved middleware order')
    validate_three(raw)
    removed={i for statement in NODES for n in tree.body if dump(n)==dump(ast.parse(statement).body[0])
             for i in range(n.lineno-1,n.end_lineno)}
    normalized=b''.join(line for i,line in enumerate(raw.splitlines(keepends=True)) if i not in removed)
    if hashlib.sha256(normalized).hexdigest()!=PIN:raise AssertionError('approved main inverse bytes')
    return normalized


def historical_test(raw,name):
    """Reconstruct approved narrow amendments from pinned originals, then invert."""
    if name not in ADAPTER_RULES:raise AssertionError('unapproved registration file')
    before=(CODE_BASE/name).read_bytes()
    if hashlib.sha256(before).hexdigest()!=BEFORE_PINS[name]:raise AssertionError('approved registration before pin')
    old_tree=ast.parse(before.decode('utf-8'));tree=ast.parse(raw.decode('utf-8'))
    old_lines=before.splitlines(keepends=True);lines=raw.splitlines(keepends=True);changes=[]
    for function,replacements in ADAPTER_RULES[name].items():
        originals=[n for n in ast.walk(old_tree) if isinstance(n,ast.FunctionDef) and n.name==function]
        matches=[n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==function]
        if len(originals)!=1 or len(matches)!=1:raise AssertionError('approved registration function count')
        original,node=originals[0],matches[0]
        code=b''.join(old_lines[original.lineno-1:original.end_lineno]).decode('utf-8').replace('\r\n','\n')
        for old,new in replacements:
            if code.count(old)!=1:raise AssertionError('approved registration amendment count')
            code=code.replace(old,new,1)
        expected=ast.parse(code if original.col_offset==0 else __import__('textwrap').dedent(code)).body[0]
        if dump(node)!=dump(expected):raise AssertionError('approved registration function shape')
        changes.append((node.lineno-1,node.end_lineno,original))
    for start,end,original in sorted(changes,reverse=True):
        lines[start:end]=old_lines[original.lineno-1:original.end_lineno]
    normalized=b''.join(lines)
    if normalized!=before:raise AssertionError('approved registration whole before bytes')
    return normalized


def validate_three(raw):
    before=(BASE/'main.before.py.txt').read_bytes()
    if hashlib.sha256(before).hexdigest()!=PIN:raise AssertionError('baseline pin')
    tree=ast.parse(raw.decode('utf-8')); added=[]
    for text in NODES:
        matches=[n for n in tree.body if dump(n)==dump(ast.parse(text).body[0])]
        if len(matches)!=1:raise AssertionError('exact node count/shape')
        added.extend(matches)
    middleware=[support.middleware_name(n) for n in tree.body if support.middleware_name(n)]
    if middleware!=ORDER[::-1]:raise AssertionError('middleware order')
    fulfill=next(n for n in tree.body if dump(n)==dump(ast.parse('app.include_router(create_fulfillment_router())').body[0]))
    if added[2].lineno!=fulfill.end_lineno+1:raise AssertionError('factory placement')
    mounts=[n.lineno for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
            and isinstance(n.func.value,ast.Name) and n.func.value.id=='app' and n.func.attr=='mount']
    if not mounts or added[2].lineno>=min(mounts):raise AssertionError('factory behind mount')
    indices={i for n in added for i in range(n.lineno-1,n.end_lineno)}
    stripped=b''.join(line for i,line in enumerate(raw.splitlines(keepends=True)) if i not in indices)
    if stripped!=before:raise AssertionError('outside3 bytes changed')
    tree.body=[n for n in tree.body if n not in added]
    if dump(tree)!=dump(ast.parse(before.decode('utf-8'))):raise AssertionError('outside3 AST changed')


def build_main(*,fail_import=False):
    """Future mock execution only; caller must validate actual source first."""
    raw=(ROOT/'api/main.py').read_bytes();validate_three(raw)
    tree=ast.parse(raw.decode('utf-8')); selected=[]
    allowed=('auth','customer_auth','admin_commerce_orders','commerce_support_http',
             'commerce_fulfillment_http','commerce_physical_return_http')
    includes={dump(ast.parse(text).body[0]) for text in (NODES[2],'app.include_router(create_fulfillment_router())')}
    for node in tree.body:
        if isinstance(node,ast.ImportFrom) and node.level==1 and node.module in allowed:selected.append(deepcopy(node))
        elif isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in ('app','_DISCOVERED_ROUTERS') for t in node.targets):selected.append(deepcopy(node))
        elif support.middleware_name(node) or dump(node) in includes:selected.append(deepcopy(node))
        elif isinstance(node,ast.FunctionDef) and node.name=='_discover_routers':selected.append(deepcopy(node))
        elif isinstance(node,ast.For) and isinstance(node.iter,ast.Name) and node.iter.id=='_DISCOVERED_ROUTERS':selected.append(deepcopy(node))
    actual=dict(admin_commerce_orders=support.isolated.routes,commerce_support_http=support.routes,
        commerce_orders=commerce_orders,commerce_owner_contexts=commerce_owner_contexts,
        commerce_fulfillment_http=shipping.h,commerce_physical_return_http=h)
    helpers={'safe_helper','commerce_physical_return_read','commerce_physical_return_writer'}
    loads=[]
    def modules(locations):
        if locations!=[str(ROOT/'api')]:raise AssertionError('inventory escaped')
        return [types.SimpleNamespace(name=n) for n in list(actual)+list(helpers)+['main','_private']]
    def load(name):
        loads.append(name)
        if name=='api.safe_helper' and fail_import:raise RuntimeError('bounded discovery failure')
        if name.startswith('api.') and name[4:] in actual:return actual[name[4:]]
        if name.startswith('api.') and name[4:] in helpers:return types.SimpleNamespace()
        raise AssertionError('unbounded import')
    ns=dict(__name__='api._return_registration_test',__package__='api',__file__=str(ROOT/'api/main.py'),
        Path=Path,FastAPI=FastAPI,APIRouter=APIRouter,
        importlib=types.SimpleNamespace(import_module=load),pkgutil=types.SimpleNamespace(iter_modules=modules))
    overrides={'api.'+key:value for key,value in actual.items()}
    overrides.update({'api.auth':auth,'api.customer_auth':member,'api.db':support.isolated.fake_db,'api.main':support.isolated.fake_main})
    with patch.dict(sys.modules,overrides):
        exec(compile(ast.Module(body=selected,type_ignores=[]),'selected-return-registration','exec'),ns)
    return ns,loads


class PhysicalReturnMainRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.auth=auth;self.auth_engine=support.isolated.AuthEngine()
        for token,actor,role in (('session-7',7,'operator'),('session-8',8,'owner'),('session-viewer',9,'viewer')):
            self.auth_engine.seed(token,actor,role)
        auth.engine=self.auth_engine;auth._device_trust_ready=None;member.resolve_session.reset_mock()
        self.engine=returns.Engine(self.auth_engine)
        p=patch.object(h,'create_router',wraps=h.create_router);self.factory=p.start();self.addCleanup(p.stop)
        self.ns,self.loads=build_main();self.app=self.ns['app']
        self.client=TestClient(self.app,base_url='https://example.invalid',follow_redirects=False);self.addCleanup(self.client.close)
        for name,value in (('get_engine',self.engine),('get_auth',auth)):
            p=patch.object(h,name,return_value=value);mock=p.start();self.addCleanup(p.stop)
            if name=='get_engine':self.engine_loader=mock
    def get(self,path=returns.PATH,token='session-7'):
        return self.client.get(path,headers={'Cookie':auth.COOKIE+'='+token})
    check=returns.ReturnHTTPTests.check
    seed=returns.ReturnHTTPTests.seed

    def test_exact3_preserves_whole_current_source_and_no_auth_member_changes(self):
        validate_three((ROOT/'api/main.py').read_bytes())
        for name,pin in (('api/auth.py',AUTH_PIN),('api/customer_auth.py',MEMBER_PIN)):
            self.assertEqual(pin,hashlib.sha256((ROOT/name).read_bytes()).hexdigest())
        for name in ADAPTER_RULES:
            self.assertEqual((CODE_BASE/name).read_bytes(),historical_test((ROOT/name).read_bytes(),name))
    def test_positive_inverse_rejects_duplicate_reordered_and_extra_post_nodes(self):
        raw=(ROOT/'api/main.py').read_bytes();nl=b'\r\n' if b'\r\n' in raw else b'\n'
        added=NODES[1].encode()+nl;auth_line=b'app.middleware("http")(auth_middleware)'+nl
        for changed in (raw+NODES[2].encode()+nl,
                raw.replace(added,b'').replace(auth_line,added+auth_line),
                raw+b'app.post("/api/admin/commerce/orders/{order_no}/physical-returns")(unexpected)'+nl):
            with self.assertRaises(AssertionError):validate_three(changed)
        # Every allocated adapter amendment is shape checked, not blanket removed.
        for name,functions in ADAPTER_RULES.items():
            actual=(ROOT/name).read_bytes()
            newline='\r\n' if b'\r\n' in actual else '\n'
            for function,replacements in functions.items():
                with self.subTest(file=name,function=function):
                    old,new=replacements[0]
                    self.assertEqual(1,actual.count(new.replace('\n',newline).encode('utf-8')))
                    mutated=actual.replace(new.replace('\n',newline).encode('utf-8'),
                        (new+'\n'+(' ' * (len(new.splitlines()[0])-len(new.splitlines()[0].lstrip())))+'raise AssertionError("unapproved adapter")').replace('\n',newline).encode('utf-8'),1)
                    with self.assertRaisesRegex(AssertionError,'approved registration function shape'):
                        historical_test(mutated,name)
    def test_factory_once_discovery_omits_return_and_exact_admin_get2(self):
        self.factory.assert_called_once_with();self.assertFalse(hasattr(h,'router'))
        self.assertEqual(1,self.loads.count('api.commerce_physical_return_http'))
        self.assertNotIn('commerce_physical_return_http',[n for n,_ in self.ns['_DISCOVERED_ROUTERS']])
        branches=[r.original_router for r in self.app.routes if isinstance(getattr(r,'original_router',None),APIRouter)]
        target=[(r.path,m) for r in branches[-1].routes if isinstance(r,APIRoute) for m in r.methods]
        self.assertEqual([(returns.PATH.replace(returns.NO,'{order_no}'),'GET'),
            (returns.PATH.replace(returns.NO,'{order_no}')+'/operations/{operation_id}','GET')],target)
        all_pairs=[(r.path,m) for branch in branches for r in branch.routes if isinstance(r,APIRoute) for m in r.methods]
        self.assertEqual(len(all_pairs),len(set(all_pairs)));self.engine_loader.assert_not_called()
    def test_factory_not_reached_on_discovery_failure(self):
        self.factory.reset_mock()
        with self.assertRaisesRegex(RuntimeError,'bounded discovery failure'):build_main(fail_import=True)
        self.factory.assert_not_called();self.engine_loader.assert_not_called()
    def test_middleware_runtime_order_and_early_auth_no_store(self):
        self.assertEqual(ORDER,[m.kwargs['dispatch'].__name__ for m in self.app.user_middleware])
        events=[]
        for item in self.app.user_middleware:
            original=item.kwargs['dispatch']
            def wrap(fn):
                async def dispatch(request,call_next):
                    events.append(fn.__name__);return await fn(request,call_next)
                return dispatch
            item.kwargs['dispatch']=wrap(original)
        for path in (returns.PATH,returns.PATH+'/operations/00000000-0000-0000-0000-000000000001'):
            events.clear()
            self.check(self.client.get(path),401)
            self.assertEqual(ORDER[:-1],events)
        member.resolve_session.assert_not_called();self.engine_loader.assert_not_called()
        events.clear();self.check(self.get(token='session-viewer'));self.assertEqual(ORDER,events)
    def test_viewer_current_disabled_and_auth_context_reset(self):
        value=self.check(self.get(token='session-viewer'))
        self.assertEqual({'inspect':{'allowed':False,'reason':'source_unconnected'},
                          'restore':{'allowed':False,'reason':'source_unconnected'}},value['actions'])
        self.assertIsNone(auth.current_operator());self.assertIsNone(member.current_member());member.resolve_session.assert_not_called()
    def test_original_actor_exact_result_and_foreign_actor_viewer_denied(self):
        rid,commands=self.seed();path=returns.PATH+'/operations/'+commands[0]['operation_id']
        self.assertEqual(rid,self.check(self.get(path))['return_id'])
        self.check(self.get(path,token='session-8'),403);self.check(self.get(path,token='session-viewer'),403)
        member.resolve_session.assert_not_called()
    def test_post_other_methods_not_registered_under_both_admin_paths(self):
        for path in (returns.PATH,returns.PATH+'/operations/00000000-0000-0000-0000-000000000001'):
            for method in ('POST','PUT','PATCH','DELETE','HEAD','OPTIONS'):
                response=self.client.request(method,path,headers={'Cookie':auth.COOKIE+'=session-7'})
                self.assertEqual(405,response.status_code);self.assertEqual('no-store',response.headers.get('cache-control'))
        self.engine_loader.assert_not_called();member.resolve_session.assert_not_called()
    def test_customer_has_no_return_route_or_member_exception(self):
        path=returns.PATH.replace('/api/admin/','/api/')
        for suffix in ('','/operations/00000000-0000-0000-0000-000000000001'):
            for method in ('GET','POST'):
                member.resolve_session.reset_mock();response=self.client.request(method,path+suffix)
                self.assertEqual(404,response.status_code);member.resolve_session.assert_called_once()
        self.engine_loader.assert_not_called()
    def test_auth_exception_redacted_by_outer_return_no_store(self):
        with patch.object(auth,'resolve_session',side_effect=RuntimeError(returns.fixture.PRIVATE)):
            self.check(self.get(),503)
        self.engine_loader.assert_not_called();member.resolve_session.assert_not_called()
    def test_queries_uuid_errors_unknown_and_read_failure_not_success(self):
        self.check(self.get(returns.PATH+'?x=1&x=2'),422)
        self.check(self.get(returns.PATH+'/operations/bad'),422)
        _,commands=self.seed('create_case');record=self.engine.data['return_ops'][commands[0]['operation_id']]
        original=deepcopy(record)
        record.update(state='unknown',result=None,receipt=None)
        self.check(self.get(returns.PATH+'/operations/'+commands[0]['operation_id']),503)
        record.clear();record.update(original)
        self.engine.fail='close';self.check(self.get(),503)
    def test_single_trailing_redirect_no_store_without_business_connection(self):
        for path in (returns.PATH,returns.PATH+'/operations/00000000-0000-0000-0000-000000000001'):
            response=self.get(path+'/');self.assertEqual(307,response.status_code)
            self.assertEqual('no-store',response.headers.get('cache-control'))
        self.engine_loader.assert_not_called()
    def test_unrelated_headers_and_exceptions_are_preserved(self):
        async def echo():return JSONResponse({'original':True},headers={'Cache-Control':'private, max-age=7'})
        async def fail():raise RuntimeError('unrelated preserved')
        self.app.add_api_route('/public/return-unrelated',echo,methods=['GET'])
        self.app.add_api_route('/public/return-unrelated-error',fail,methods=['GET'])
        self.assertEqual('private, max-age=7',self.client.get('/public/return-unrelated').headers.get('cache-control'))
        with self.assertRaisesRegex(RuntimeError,'unrelated preserved'):self.client.get('/public/return-unrelated-error')


if __name__=='__main__':unittest.main()
