"""Actual selected auth ContextVar/threadpool + list ASGI; no real DB/main IO."""
import ast
import asyncio
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_admin_commerce_orders as isolated
from tests import test_admin_commerce_order_list_writer as page_fixtures
from tests import test_admin_commerce_main_registration as registration

routes, auth, c = isolated.routes, isolated.auth, isolated.c
PATH = '/api/admin/commerce/orders'
BASE = Path('D:/WORK/PopcornAI/outputs/opening-commerce-backend-20261005/CODEMOCK-운영목록-변경전동결')
ROOT = Path(__file__).resolve().parents[1]

OVERLAY_BASE = Path('D:/WORK/PopcornAI/outputs')
SHIPPING_BEFORE = OVERLAY_BASE/'admin-sourcing-inbound-20261003/U2-E-정책잠금/배송-main-정확5-CODE-변경전-20261005'
SUPPORT_BEFORE = OVERLAY_BASE/'opening-commerce-backend-20261005/support-main-code4/변경전동결'
MAIN_SHIPPING_NODES = (
    'from .commerce_fulfillment_http import create_router as create_fulfillment_router, fulfillment_no_store',
    'app.middleware("http")(fulfillment_no_store)',
    'app.include_router(create_fulfillment_router())')
MAIN_SUPPORT_NODES = (
    'from .commerce_support_http import commerce_support_no_store',
    'app.middleware("http")(commerce_support_no_store)')


def _historical_main_source(case,raw):
    """Positive node/count/order checks, then exact two-stage raw inverse."""
    from tests.test_commerce_physical_return_main_registration import historical_main
    raw=historical_main(raw)
    tree=ast.parse(raw.decode('utf-8'))
    groups=[]
    for statements in (MAIN_SHIPPING_NODES,MAIN_SUPPORT_NODES):
        group=[]
        for statement in statements:
            wanted=ast.dump(ast.parse(statement).body[0],include_attributes=False)
            matches=[n for n in tree.body if ast.dump(n,include_attributes=False)==wanted]
            case.assertEqual(len(matches),1,'approved main node count/shape: '+statement)
            group.append(matches[0])
        groups.append(group)
    positions=[(i,registration._middleware_name(n)) for i,n in enumerate(tree.body) if registration._middleware_name(n)]
    case.assertEqual([name for _,name in positions],
                     ['member_middleware','auth_middleware','admin_commerce_no_store','commerce_support_no_store','fulfillment_no_store'],
                     'approved middleware order')
    case.assertEqual([i for i,_ in positions[-3:]],list(range(positions[-3][0],positions[-3][0]+3)))
    case.assertEqual(tree.body.index(groups[0][0]),tree.body.index(groups[1][0])+1)
    discovery=[n for n in tree.body if isinstance(n,ast.For) and isinstance(n.iter,ast.Name) and n.iter.id=='_DISCOVERED_ROUTERS']
    case.assertEqual(len(discovery),1)
    include=groups[0][2]
    case.assertEqual(tree.body.index(include),tree.body.index(discovery[0])+1,'approved factory order')
    case.assertEqual(include.lineno,discovery[0].end_lineno+1)
    mounts=[n.lineno for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
            and isinstance(n.func.value,ast.Name) and n.func.value.id=='app' and n.func.attr=='mount']
    case.assertTrue(mounts); case.assertLess(include.lineno,min(mounts))
    lines=raw.splitlines(keepends=True); removed=set()
    for nodes,path,pin in ((groups[0],SHIPPING_BEFORE/'api/main.py','49ed9dd9f1a45f0687e85a6e18631d508a450cb64309e16cdb6670f2d1a72920'),
                           (groups[1],SUPPORT_BEFORE/'api/main.py','2e22fdd6fe540dbee66e84e1a5938a3cfae825aad622080db63871573dcd1e27')):
        for node in nodes: removed.update(range(node.lineno-1,node.end_lineno))
        historical=path.read_bytes()
        case.assertEqual(hashlib.sha256(historical).hexdigest(),pin)
        normalized=b''.join(line for i,line in enumerate(lines) if i not in removed)
        case.assertEqual(normalized,historical,'whole approved-before main raw')
    case.assertEqual(normalized,(BASE/'api/main.py').read_bytes())
    return normalized


def _historical_registration_source(case,raw):
    """Validate exact accepted function ASTs before restoring dirty-before bytes."""
    from tests.test_commerce_physical_return_main_registration import historical_test
    name='tests/test_admin_commerce_main_registration.py'
    raw=historical_test(raw,name)
    shipping=(SHIPPING_BEFORE/name).read_bytes(); support=(SUPPORT_BEFORE/name).read_bytes()
    case.assertEqual(hashlib.sha256(shipping).hexdigest(),'50e609e2b3f6f685dedf87e18d000cf90cac309ca010b38e720470eaf19049d7')
    case.assertEqual(hashlib.sha256(support).hexdigest(),'502f1fb4eb8d2ca9110711415edb1746288c3f82f0435fb8b4146762da2c7a12')
    names=('_build_main','test_exact_two_nodes_remove_to_original_whole_main_ast')
    def functions(source):
        tree=ast.parse(source.decode('utf-8')); result={}
        for function in names:
            matches=[n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==function]
            case.assertEqual(len(matches),1,'approved registration function count: '+function)
            result[function]=matches[0]
        case.assertIs(tree.body[tree.body.index(result['_build_main'])],result['_build_main'])
        classes=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='MainRegistrationTests']
        case.assertEqual(len(classes),1)
        case.assertIs(classes[0].body[1],result[names[1]],'approved registration function order')
        return result
    # Reconstruct the approved shipping amendment from its pinned support source,
    # not from a new current-file digest or a blanket function-name exception.
    expected=functions(shipping)
    old_condition=ast.parse('_middleware_name(node) and _middleware_name(node) != "commerce_support_no_store"',mode='eval').body
    matches=[n for n in ast.walk(expected['_build_main']) if isinstance(n,ast.If)
             and ast.dump(n.test,include_attributes=False)==ast.dump(old_condition,include_attributes=False)]
    case.assertEqual(len(matches),1)
    matches[0].test=ast.parse('_middleware_name(node) and _middleware_name(node) not in ("commerce_support_no_store", "fulfillment_no_store")',mode='eval').body
    amendment=ast.parse('''fulfillment_nodes = []
for statement in (
        'from .commerce_fulfillment_http import create_router as create_fulfillment_router, fulfillment_no_store',
        'app.middleware("http")(fulfillment_no_store)',
        'app.include_router(create_fulfillment_router())'):
    expected = ast.dump(ast.parse(statement).body[0], include_attributes=False)
    matches = [n for n in current.body if ast.dump(n, include_attributes=False) == expected]
    self.assertEqual(1, len(matches), statement)
    fulfillment_nodes.extend(matches)
current.body = [n for n in current.body if n not in fulfillment_nodes]''').body
    case.assertIsInstance(expected[names[1]].body[2],ast.Assign)
    case.assertEqual([t.id for t in expected[names[1]].body[2].targets],['original'])
    expected[names[1]].body[3:3]=amendment
    for before,approved in ((shipping,expected),(support,functions(shipping))):
        actual=functions(raw); old=functions(before)
        for function in names:
            case.assertEqual(ast.dump(actual[function],include_attributes=False),
                             ast.dump(approved[function],include_attributes=False),'approved registration function shape: '+function)
        lines=raw.splitlines(keepends=True); old_lines=before.splitlines(keepends=True)
        for function in sorted(names,key=lambda key:actual[key].lineno,reverse=True):
            node,original=actual[function],old[function]
            lines[node.lineno-1:node.end_lineno]=[b''.join(old_lines[original.lineno-1:original.end_lineno])]
        raw=b''.join(lines)
        case.assertEqual(raw,before,'whole approved-before registration raw')
    return raw


def _historical_compiler_sources(case,migration_raw,test_raw):
    """Verify the accepted compiler amendment, then invert only its three hunks."""
    from sqlalchemy import text
    from sqlalchemy.engine.default import DefaultDialect
    from sqlalchemy.exc import InvalidRequestError
    accepted=OVERLAY_BASE/'opening-commerce-backend-20261005/migration-payment-literal-code2-20261006'
    manifest=json.loads((accepted/'manifest.json').read_text(encoding='utf-8'))
    paths=('db/migrations/versions/0126_opening_commerce.py','tests/test_commerce_migration.py')
    case.assertEqual([entry['path'] for entry in manifest],list(paths))
    old={}; final={}
    for entry in manifest:
        name=entry['path']; old[name]=(accepted/'before'/name).read_bytes(); final[name]=(accepted/'final2'/name).read_bytes()
        case.assertEqual(hashlib.sha256(old[name]).hexdigest(),entry['before_sha256'])
        case.assertEqual(hashlib.sha256(final[name]).hexdigest(),entry['final_sha256'])
    case.assertEqual(hashlib.sha256(old[paths[0]]).hexdigest(),'d8553151ecf42ef68a73f02ba60f33da52548f76b0c4469e51d2d796abc29e76')
    case.assertEqual(hashlib.sha256(old[paths[1]]).hexdigest(),'7d81f734f33802f47b8f679c4911f36fc8e46c09f5a4b2e0521bc34eefafd985')
    case.assertEqual(migration_raw.count(b"'\\:payment'"),1,'approved literal count')
    case.assertEqual(migration_raw,final[paths[0]],'approved literal source shape')
    restored_migration=migration_raw.replace(b"'\\:payment'",b"':payment'",1)
    case.assertEqual(restored_migration,old[paths[0]])
    def upgrade_sql(raw):
        matches=[n for n in ast.parse(raw.decode('utf-8')).body if isinstance(n,ast.Assign)
                 and any(isinstance(t,ast.Name) and t.id=='UPGRADE_SQL' for t in n.targets)]
        case.assertEqual(len(matches),1)
        return ast.literal_eval(matches[0].value)
    compiled=text(upgrade_sql(migration_raw)).compile(dialect=DefaultDialect())
    case.assertEqual(compiled.params,{})
    case.assertEqual(compiled.construct_params(),{})
    case.assertEqual(str(compiled),upgrade_sql(old[paths[0]]),'emitted business SQL identical')
    trees=[ast.parse(raw.decode('utf-8')) for raw in (old[paths[1]],test_raw,final[paths[1]])]
    def unique(tree,name):
        matches=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==name]
        case.assertEqual(len(matches),1,'approved compiler class count: '+name)
        return matches[0]
    original_tests,current_tests=unique(trees[0],'MigrationTests'),unique(trees[1],'MigrationTests')
    case.assertEqual(sum(isinstance(n,ast.FunctionDef) and n.name.startswith('test_') for n in original_tests.body),7)
    case.assertEqual(ast.dump(current_tests,include_attributes=False),ast.dump(original_tests,include_attributes=False),
                     'original seven methods AST identical')
    capture=unique(trees[1],'Capture'); boundary=unique(trees[1],'CompilerBoundaryTests')
    for name,node in (('Capture',capture),('CompilerBoundaryTests',boundary)):
        case.assertEqual(ast.dump(node,include_attributes=False),ast.dump(unique(trees[2],name),include_attributes=False),
                         'approved compiler shape: '+name)
    case.assertEqual(sum(isinstance(n,ast.FunctionDef) and n.name.startswith('test_') for n in boundary.body),5)
    case.assertEqual(test_raw,final[paths[1]],'whole accepted compiler test source')
    # Execute only Scalar/Capture from the validated AST, never migration/DB imports.
    env=dict(text=text,DefaultDialect=DefaultDialect)
    exec(compile(ast.Module(body=[unique(trees[1],'Scalar'),capture],type_ignores=[]),'accepted-compiler-capture','exec'),env)
    recorder=env['Capture'](); recorder.execute(upgrade_sql(migration_raw))
    case.assertEqual(recorder.sql[0][0],upgrade_sql(old[paths[0]]))
    with case.assertRaisesRegex(InvalidRequestError,"bind parameter 'payment'"):
        recorder.execute("SELECT ':payment'")
    recorder.execute(text('SELECT :schema, :table'),{'schema':'public','table':'products'})
    with case.assertRaisesRegex(InvalidRequestError,"bind parameter 'table'"):
        recorder.execute(text('SELECT :schema, :table'),{'schema':'public'})
    imports=b'''import io

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.exc import InvalidRequestError
'''
    current_capture=b'''        clause=text(statement) if isinstance(statement,str) else statement
        compiled=clause.compile(dialect=DefaultDialect())
        compiled.construct_params(params)
        self.sql.append((str(compiled),params))
'''
    case.assertEqual(test_raw.count(imports),1)
    case.assertEqual(test_raw.count(current_capture),1)
    lines=test_raw.splitlines(keepends=True)
    boundary_bytes=b''.join(lines[boundary.lineno-1:boundary.end_lineno])+b'\n\n'
    case.assertEqual(test_raw.count(boundary_bytes),1)
    restored_test=test_raw.replace(imports,b'',1).replace(current_capture,b'        self.sql.append((str(statement),params))\n',1).replace(boundary_bytes,b'',1)
    case.assertEqual(test_raw.count(b'\r'),0)
    case.assertEqual(old[paths[1]].count(b'\r'),0)
    case.assertEqual(restored_test,old[paths[1]],'whole historical compiler test raw')
    return {paths[0]:restored_migration,paths[1]:restored_test}


class AdminListTests(unittest.TestCase):
    def setUp(self):
        self.fixture=isolated.AdminDetailTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.conn=page_fixtures.seed()
        self.fixture.stored=self.conn; self.fixture.bridge.stored=self.conn
        self.fixture.before=deepcopy(self.conn.data)
    def get(self, token='session-21', **kwargs): return self.fixture.get(token,path=PATH,**kwargs)
    def response(self, result, status=200):
        value=self.fixture.response(result,status)
        for private in ('fixture recipient','fixture phone','fixture address','fixture@example.invalid',
                        'owner_scope','owner_identity','provider_binding','committed_payment','final_commit','operation_id'):
            self.assertNotIn(private,result.text)
        return value
    def no_page(self):
        self.assertFalse(any(tag=='admin_order_page' for tag,_,_ in self.conn.trace))
    def reset(self):
        self.conn=page_fixtures.seed(); self.fixture.stored=self.conn; self.fixture.bridge.stored=self.conn
        self.fixture.before=deepcopy(self.conn.data)
        self.fixture.bridge.clock_reads=0; self.fixture.bridge.fail=None; self.fixture.bridge.now=150
        self.fixture.engine.fail=None

    def test_list_uses_real_auth_context_threadpool_readonly_envelope_and_redaction(self):
        captured=[]; original=routes.writer.read_committed_admin_orders
        def read(conn,**kwargs):
            captured.append(kwargs['authorize'](scope='commerce.orders',now=kwargs['now']))
            self.assertIs(routes.current_operator,auth.current_operator)
            return original(conn,**kwargs)
        with patch.object(routes.writer,'read_committed_admin_orders',side_effect=read):
            payload=self.response(self.get(params={'limit':'2'}))
        self.assertEqual(captured[0]['actor'],dict(operator_id=21,role='owner',status='활성'))
        self.assertEqual(captured[0]['scope'],'commerce.orders'); self.assertNotIn('order_no',captured[0])
        self.assertEqual(set(payload),{'commerce_version','checked_at','context','items','next_cursor'})
        self.assertEqual([r['order_no'] for r in payload['items']],['order-5','order-4'])
        self.assertEqual(routes._cursor_decode(payload['next_cursor']),(5,4))
        self.assertEqual(self.fixture.auth_engine.last_seen,['session-21'])
        self.assertEqual(self.fixture.bridge.trace[0],'readonly')
        self.assertEqual(self.fixture.bridge.trace.count('clock'),2)
        self.assertEqual(self.fixture.bridge.trace.count('admin_order_page'),1)
        self.assertTrue(set(self.fixture.bridge.trace) <= {'readonly','clock','txid','admin_order_page','rollback'})
        self.assertEqual(self.conn.data,self.fixture.before)
        for item in payload['items']:
            self.assertEqual(item['basis_state'],'unconfirmed'); self.assertIsNone(item['basis_id'])
            self.assertEqual(item['verification_state'],'unknown'); self.assertIsNone(item['provider_checked_at'])
            self.assertTrue(all(action==dict(allowed=False,reason='route_unavailable',expected_basis=None)
                                for action in item['actions'].values()))

    def test_next_pages_empty_end_complete_order_grouping_and_string_money(self):
        first=self.response(self.get(params={'limit':'2'}))
        second=self.response(self.get(params={'limit':'2','cursor':first['next_cursor']}))
        third=self.response(self.get(params={'limit':'2','cursor':second['next_cursor']}))
        items=first['items']+second['items']+third['items']
        self.assertEqual([r['order_no'] for r in items],['order-5','order-4','order-3','order-2','order-1'])
        self.assertEqual([r['approved_amount'] for r in items],['0','0','2100','0','2100'])
        self.assertTrue(all([l['line_id'] for l in r['lines']]==['item-1','charge:fixture-fee'] for r in items))
        self.assertTrue(all(r['total']=='2100' and r['lines'][0]['unit_amount']=='1000' for r in items))
        self.assertIsNone(third['next_cursor'])
        last=routes._cursor_encode(5,1)
        empty=self.response(self.get(params={'cursor':last}))
        self.assertEqual(empty['items'],[]); self.assertIsNone(empty['next_cursor'])

    def test_default20_max50_and_first_empty_page(self):
        self.conn=page_fixtures.seed(25); self.fixture.stored=self.conn; self.fixture.bridge.stored=self.conn
        self.fixture.before=deepcopy(self.conn.data)
        self.assertEqual(len(self.response(self.get())['items']),20)
        full=self.response(self.get(params={'limit':'50'}))
        self.assertEqual(len(full['items']),25); self.assertIsNone(full['next_cursor'])
        self.conn.data['orders'].clear(); self.conn.saved=deepcopy(self.conn.data); self.fixture.before=deepcopy(self.conn.data)
        empty=self.response(self.get()); self.assertEqual(empty['items'],[]); self.assertIsNone(empty['next_cursor'])

    def test_bigint_cursor_is_exact_and_injected_new_upper_row_is_excluded(self):
        first=self.response(self.get(params={'limit':'2'}))
        oid=9007199254740993
        row=deepcopy(self.conn.data['orders']['order-5']); row.update(order_id=oid,order_no='new-high')
        self.conn.data['orders']['new-high']=row; self.conn.data['details'][oid]=deepcopy(self.conn.data['details'][5])
        self.conn.saved=deepcopy(self.conn.data); self.fixture.before=deepcopy(self.conn.data)
        next_page=self.response(self.get(params={'cursor':first['next_cursor']}))
        self.assertEqual([r['order_no'] for r in next_page['items']],['order-3','order-2','order-1'])
        fresh=self.response(self.get(params={'limit':'1'}))
        cursor=fresh['next_cursor']; self.assertEqual(routes._cursor_decode(cursor),(oid,oid))
        decoded=json.loads(base64.urlsafe_b64decode(cursor+'='*(-len(cursor)%4)))
        self.assertEqual(decoded['upper_id'],str(oid)); self.assertEqual(decoded['after_id'],str(oid))
        self.assertEqual(decoded['scope'],routes._LIST_SCOPE)

    def test_native_bigint_snapshot_money_above_js_precision_remains_exact(self):
        unit=9007199254740993; total=unit*2+100
        row=self.conn.data['orders']['order-5']; row['total_amount']=total
        snapshot=self.conn.data['details'][5]['snapshot']
        snapshot['lines'][0]['unit_amount']=unit; snapshot['total']=total
        self.conn.saved=deepcopy(self.conn.data); self.fixture.before=deepcopy(self.conn.data)
        item=self.response(self.get(params={'limit':'1'}))['items'][0]
        self.assertEqual(item['total'],str(total)); self.assertEqual(item['lines'][0]['unit_amount'],str(unit))
        self.assertEqual(item['approved_amount'],'0'); self.assertEqual(item['refundable_amount'],'0')
        self.assertEqual(self.conn.data,self.fixture.before)

    def test_query_duplicates_unknown_filters_limit_formats_and_body_rejected_before_connect(self):
        queries=['limit=0','limit=51','limit=01','limit=1.0','limit=-1','limit=true','limit=',
                 'limit=2&limit=2','cursor=x&cursor=x','actor=1','status=paid','q=order-1','cursor=']
        for query in queries:
            with self.subTest(query=query): self.response(self.fixture.get(path=PATH+'?'+query),422)
        self.response(self.fixture.client.request('GET',PATH,headers={'Cookie':auth.COOKIE+'=session-21'},
                                                json={'actor':21,'grant':True}),422)
        self.no_page(); self.fixture.engine_loader.assert_not_called()

    def test_cursor_canonical_version_scope_native_bigint_fields_and_bounds_are_strict(self):
        valid=dict(v=1,scope=routes._LIST_SCOPE,upper_id='5',after_id='4')
        def encode(value, **kwargs):
            return base64.urlsafe_b64encode(json.dumps(value,**kwargs).encode()).decode().rstrip('=')
        values=['x','a'*257,routes._cursor_encode(5,4)+'=',encode(valid),
                encode(valid|{'v':True},sort_keys=True,separators=(',',':')),
                encode(valid|{'scope':'commerce.order.read'},sort_keys=True,separators=(',',':')),
                encode(valid|{'upper_id':5},sort_keys=True,separators=(',',':')),
                encode(valid|{'upper_id':'05'},sort_keys=True,separators=(',',':')),
                encode(valid|{'upper_id':str(2**63)},sort_keys=True,separators=(',',':')),
                encode(valid|{'after_id':'6'},sort_keys=True,separators=(',',':')),
                encode(valid|{'extra':'secret'},sort_keys=True,separators=(',',':'))]
        for value in values:
            with self.subTest(value=value): self.response(self.get(params={'cursor':value}),422)
        self.no_page(); self.fixture.engine_loader.assert_not_called()

    def test_missing_customer_cookie_and_invalid_operator_fail_before_business_engine(self):
        self.response(self.get(None),401)
        self.response(self.fixture.client.get(PATH,headers={'Cookie':'customer_session=fixture'}),401)
        for change in ({'operator_id':True},{'operator_id':0},{'operator_id':'21'},{'role':'customer'}):
            self.fixture.auth_engine.seed('session-21',21,**change)
            self.response(self.get(),403)
        self.no_page(); self.fixture.engine_loader.assert_not_called()

    def test_active_viewer_operator_owner_use_distinct_authenticated_contexts(self):
        self.fixture.auth_engine.seed('session-operator',24,'operator')
        for token in ('session-viewer','session-operator','session-22'):
            self.response(self.get(token))
        self.assertEqual(self.fixture.auth_engine.last_seen,['session-viewer','session-operator','session-22'])
        self.assertEqual(self.conn.data,self.fixture.before)

    def test_late_actor_switch_and_context_loss_are_403_before_page_select(self):
        for actor in (None,dict(operator_id=22,role='owner',status='활성')):
            self.reset(); self.fixture.bridge.on_first_clock=lambda:auth._current.set(actor)
            self.response(self.get(),403); self.no_page()
        self.fixture.bridge.on_first_clock=None

    def test_direct_call_cannot_use_fallback_principal_or_fake_grant(self):
        async def receive(): return {'type':'http.request','body':b'','more_body':False}
        for principal,status in ((None,401),({'operator_id':True,'role':'owner','status':'활성'},403)):
            request=isolated.Request({'type':'http','method':'GET','path':PATH,'query_string':b'','headers':[]},receive)
            token=auth._current.set(principal)
            try: response=asyncio.run(routes.read_order_list(request))
            finally: auth._current.reset(token)
            self.assertEqual(response.status_code,status); self.assertEqual(response.headers['cache-control'],'no-store')
        self.no_page(); self.fixture.engine_loader.assert_not_called()

    def test_any_proof_owner_null_money_sql_or_lifecycle_failure_is_whole_sanitized503(self):
        for mode in ('duplicate','null','owner','receipt','readonly','clock','clock_type','page_sql','rollback','close','connect'):
            with self.subTest(mode=mode):
                self.reset()
                if mode=='duplicate': self.conn.data['payments'].append(deepcopy(self.conn.data['payments'][1]))
                elif mode=='null': self.conn.row_change=lambda rows:rows[0].update(approved=None)
                elif mode=='owner': self.conn.data['details'][5]['owner_scope']='0'*64
                elif mode=='receipt': next(r for r in self.conn.data['operations'].values() if r['order_id']==3)['operation']['final_commit']['payment_id']=999
                elif mode in ('readonly','clock','rollback'): self.fixture.bridge.fail=mode
                elif mode=='clock_type': self.fixture.bridge.now=150.0
                elif mode=='page_sql': self.conn.fail_tag='admin_order_page'
                else: self.fixture.engine.fail=mode
                response=self.get(params={'limit':'2'}); self.response(response,503)
                self.assertEqual(response.json(),{'detail':{'code':'order_list_unavailable'}})
                self.assertNotIn('items',response.json())

    def test_auth_failure_no_store503_without_business_query_and_other_paths_unchanged(self):
        self.fixture.auth_engine.fail=True
        self.response(self.get(),503); self.no_page(); self.fixture.engine_loader.assert_not_called()
        self.assertEqual(self.get().json(),{'detail':{'code':'order_list_unavailable'}})
        async def run():
            request=isolated.Request({'type':'http','method':'POST','path':PATH,'query_string':b'','headers':[]})
            async def next_call(req): raise RuntimeError('original')
            with self.assertRaisesRegex(RuntimeError,'original'): await routes.admin_commerce_no_store(request,next_call)
        asyncio.run(run())

    def test_actual_main_ast_discovers_both_gets_with_original_outer_auth_order(self):
        namespace,_,_,_=registration._build_main()
        paths=namespace['app'].openapi()['paths']
        self.assertEqual(set(paths),{PATH,PATH+'/{order_no}'})
        self.assertTrue(all(set(value)=={'get'} for value in paths.values()))
        self.assertEqual([m.kwargs['dispatch'].__name__ for m in namespace['app'].user_middleware],
                         ['admin_commerce_no_store','auth_middleware','member_middleware'])
        client=isolated.TestClient(namespace['app'],base_url='https://example.invalid')
        self.addCleanup(client.close)
        self.response(client.get(PATH),401)
        self.response(client.get(PATH,headers={'Cookie':auth.COOKIE+'=session-21'}))
        registration.member.resolve_session.assert_not_called()

    def test_frozen_functions_protected_files_and_detail_contract_are_unchanged(self):
        compiler_sources=_historical_compiler_sources(self,
            (ROOT/'db/migrations/versions/0126_opening_commerce.py').read_bytes(),
            (ROOT/'tests/test_commerce_migration.py').read_bytes())
        for name in ('api/commerce_writer.py','api/admin_commerce_orders.py'):
            old=ast.parse((BASE/name).read_text(encoding='utf-8')); current=ast.parse((ROOT/name).read_text(encoding='utf-8'))
            functions={n.name:n for n in current.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
            for node in old.body:
                if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name!='admin_commerce_no_store':
                    self.assertEqual(ast.dump(node,include_attributes=False),ast.dump(functions[node.name],include_attributes=False),node.name)
        pins=json.loads((BASE.parent/'CODEMOCK-운영목록-변경전핀.json').read_text(encoding='utf-8'))
        approved={
            'tests/test_admin_commerce_orders.py':(
                'test_only_get_detail_route_exists_and_no_action_or_list_is_available',
                'test_only_two_get_routes_exist_and_no_actions_or_business_writes_are_available'),
            'tests/test_admin_commerce_main_registration.py':(
                'test_original_discovery_auto_includes_real_router_once_with_outer_auth_order',
                'test_original_discovery_auto_includes_real_router_once_with_outer_auth_order')}
        for name,value in pins.items():
            if value and name not in ('api/commerce_writer.py','api/admin_commerce_orders.py'):
                if name in approved:
                    self.assertEqual(hashlib.sha256((BASE/name).read_bytes()).hexdigest(),value,name)
                    original=ast.parse((BASE/name).read_text(encoding='utf-8'))
                    current_raw=(ROOT/name).read_bytes()
                    if name=='tests/test_admin_commerce_main_registration.py':
                        current_raw=_historical_registration_source(self,current_raw)
                    current=ast.parse(current_raw.decode('utf-8'))
                    for tree,test_name in zip((original,current),approved[name]):
                        removed=0
                        for node in tree.body:
                            if isinstance(node,ast.ClassDef):
                                removed+=sum(isinstance(child,ast.FunctionDef) and child.name==test_name for child in node.body)
                                node.body=[child for child in node.body
                                           if not (isinstance(child,ast.FunctionDef) and child.name==test_name)]
                        self.assertEqual(removed,1,(name,test_name))
                    self.assertEqual(ast.dump(current,include_attributes=False),
                                     ast.dump(original,include_attributes=False),name)
                else:
                    current_raw=(ROOT/name).read_bytes()
                    if name=='api/main.py':
                        current_raw=_historical_main_source(self,current_raw)
                    if name in compiler_sources:
                        current_raw=compiler_sources[name]
                    self.assertEqual(hashlib.sha256(current_raw).hexdigest(),value,name)
        self.assertEqual(self.fixture.client.get(PATH+'/order-1',headers={'Cookie':auth.COOKIE+'=session-21'}).status_code,200)
        self.assertEqual(self.fixture.client.post(PATH,headers={'Cookie':auth.COOKIE+'=session-21'}).status_code,405)


class SourceOverlayNegativeTests(unittest.TestCase):
    def test_compiler_adapter_rejects_unapproved_literal_capture_and_original_method(self):
        migration=(ROOT/'db/migrations/versions/0126_opening_commerce.py').read_bytes()
        test=(ROOT/'tests/test_commerce_migration.py').read_bytes()
        with self.assertRaisesRegex(AssertionError,'approved literal source shape'):
            _historical_compiler_sources(self,migration.replace(b"'\\:payment'",b"'\\:payment'||'unapproved'"),test)
        changed=test.replace(b'compiled.construct_params(params)',b'compiled.construct_params({})')
        self.assertNotEqual(changed,test)
        with self.assertRaisesRegex(AssertionError,'approved compiler shape: Capture'):
            _historical_compiler_sources(self,migration,changed)
        changed=test.replace(b"self.assertNotIn('DROP TABLE',sql)",b"self.assertNotIn('UNAPPROVED',sql)")
        self.assertNotEqual(changed,test)
        with self.assertRaisesRegex(AssertionError,'original seven methods AST identical'):
            _historical_compiler_sources(self,migration,changed)

    def test_main_adapter_rejects_duplicate_registration_and_factory(self):
        raw=(ROOT/'api/main.py').read_bytes()
        for statement in (MAIN_SUPPORT_NODES[1],MAIN_SHIPPING_NODES[1],MAIN_SHIPPING_NODES[2]):
            with self.subTest(statement=statement),self.assertRaisesRegex(AssertionError,'approved main node count/shape'):
                _historical_main_source(self,raw+b'\n'+statement.encode()+b'\n')

    def test_main_adapter_rejects_unapproved_middleware_order(self):
        raw=(ROOT/'api/main.py').read_bytes()
        support=MAIN_SUPPORT_NODES[1].encode(); shipping=MAIN_SHIPPING_NODES[1].encode()
        changed=raw.replace(support,b'APPROVED_SWAP').replace(shipping,support).replace(b'APPROVED_SWAP',shipping)
        with self.assertRaisesRegex(AssertionError,'approved middleware order'):
            _historical_main_source(self,changed)

    def test_registration_adapter_rejects_unapproved_function_and_duplicate(self):
        raw=(ROOT/'tests/test_admin_commerce_main_registration.py').read_bytes()
        changed=raw.replace(b"('commerce_support_no_store', 'fulfillment_no_store')",
                            b"('commerce_support_no_store', 'fulfillment_no_store', 'unapproved_no_store')")
        self.assertNotEqual(changed,raw)
        with self.assertRaisesRegex(AssertionError,'approved registration function shape'):
            _historical_registration_source(self,changed)
        tree=ast.parse(raw.decode('utf-8'))
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_build_main')
        duplicate=raw+b'\n'+ast.unparse(function).encode()+b'\n'
        with self.assertRaisesRegex(AssertionError,'approved registration function count'):
            _historical_registration_source(self,duplicate)


if __name__=='__main__': unittest.main()
