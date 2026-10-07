"""Actual auth function AST + ASGI + stored-reader/projection simulation.

No api.auth/main/db module execution, production env, database or provider IO.
Auth session SQL and business SQL are different doubles/transactions. These
tests prove routing/control flow, not native authentication or PostgreSQL.
"""
import ast
import asyncio
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import re
import socket
import sys
import types
import unittest
from unittest.mock import patch


def _deny_external(event, args):
    fallback = getattr(socket, '_fallback_socketpair', None)
    if (event == 'socket.connect' and fallback is not None
            and sys._getframe(1).f_code is fallback.__code__
            and args[1][0] in ('127.0.0.1', '::1')):
        return
    if event in {'socket.connect', 'socket.connect_ex', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'}:
        raise AssertionError('external IO forbidden by isolated admin detail tests')
    if event == 'open' and args and isinstance(args[0], (str, bytes)):
        if str(args[0]).replace('\\', '/').lower().rstrip("'").endswith('/.env'):
            raise AssertionError('production environment forbidden')


sys.addaudithook(_deny_external)

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool
from api import commerce_contract as c
from api import commerce_writer as writer
from tests import test_commerce_writer as stored_fixtures
from tests.test_commerce_contract import owner, policy, sale, draft
from tests.test_commerce_payment_core import spec, evidence, verifier, OP, OTHER

ROOT = Path(__file__).resolve().parents[1]
AUTH_SOURCE = ROOT / 'api/auth.py'
AUTH_TREE = ast.parse(AUTH_SOURCE.read_text(encoding='utf-8'))
AUTH_FUNCTIONS = {'_schema_ready', 'resolve_session', 'current_operator', 'current_operator_id',
                  '_is_admin2_path', '_is_admin2_page', '_is_gated', '_is_operator_photo_path',
                  'required_role', 'auth_middleware'}
AUTH_CONSTANTS = {'COOKIE', 'IDLE_MINUTES', 'ROLE_RANK', '_current', 'OPEN_PREFIXES',
                  'ADMIN2_PREFIX', 'ADMIN2_OPEN_PATHS', 'ADMIN2_JSON_DATA_PATHS',
                  'OWNER_WRITE_PREFIXES', '_device_trust_ready'}
selected = []
for node in AUTH_TREE.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in AUTH_FUNCTIONS:
        selected.append(deepcopy(node))
    elif isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(n, ast.Name) and n.id in AUTH_CONSTANTS for n in targets):
            selected.append(deepcopy(node))
AUTH_AST = ast.Module(body=selected, type_ignores=[])
auth = types.ModuleType('api.auth')
auth.__dict__.update(Request=Request, ContextVar=ContextVar, text=text, run_in_threadpool=run_in_threadpool)


class BlockedEngine:
    def connect(self): raise AssertionError('unmocked database access')
    def begin(self): raise AssertionError('unmocked database access')


auth.engine = BlockedEngine()
exec(compile(AUTH_AST, str(AUTH_SOURCE), 'exec'), auth.__dict__)
fake_db = types.ModuleType('api.db'); fake_db.engine = BlockedEngine()
fake_main = types.ModuleType('api.main')
previous = {name: sys.modules.get(name) for name in ('api.auth', 'api.db', 'api.main')}
sys.modules.update({'api.auth': auth, 'api.db': fake_db, 'api.main': fake_main})
try:
    routes = importlib.import_module('api.admin_commerce_orders')
finally:
    for name, old in previous.items():
        if old is None: sys.modules.pop(name, None)
        else: sys.modules[name] = old

ORDER = 'fixture-order'
PATH = '/api/admin/commerce/orders/' + ORDER
PRIVATE = 'private-fixture-value'


class AuthResult:
    def __init__(self, row=None, value=None): self.row, self.value = row, value
    def mappings(self): return self
    def first(self): return deepcopy(self.row)
    def scalar(self): return self.value


class AuthEngine:
    """Session resolver's own transaction, including original last_seen write."""
    def __init__(self):
        self.sessions = {}
        self.trace = []; self.fail = False; self.last_seen = []
    def seed(self, token, actor=21, role='owner', **changes):
        self.sessions[token] = dict(operator_id=actor,name=PRIVATE,email=PRIVATE+'@example.invalid',
          role=role,status='활성',password_verified=True,revoked=False,expired=False,idle=False) | changes
    def connect(self): return AuthConnection(self, False)
    def begin(self): return AuthConnection(self, True)


class AuthConnection:
    def __init__(self, engine, write): self.engine, self.write = engine, write
    def __enter__(self):
        self.engine.trace.append('auth_begin' if self.write else 'auth_schema_open'); return self
    def __exit__(self, kind, value, tb):
        self.engine.trace.append('auth_rollback' if kind else 'auth_commit' if self.write else 'auth_schema_close')
    def execute(self, statement, params=None):
        sql = str(statement)
        if self.engine.fail: raise RuntimeError(PRIVATE+' auth SQL/session error')
        if 'information_schema.columns' in sql:
            self.engine.trace.append('auth_schema'); return AuthResult(value=True)
        if 'FROM admin_sessions s JOIN admin_operators' in sql:
            self.engine.trace.append('auth_session_select')
            return AuthResult(row=self.engine.sessions.get(params['s']))
        if sql.startswith('UPDATE admin_sessions SET last_seen_at'):
            self.engine.trace.append('auth_last_seen'); self.engine.last_seen.append(params['s']); return AuthResult()
        raise AssertionError('unexpected original auth SQL')


class ReadBridge:
    def __init__(self, stored):
        self.stored = stored; self.trace = []; self.now = 150; self.fail = None; self.clock_reads = 0
        self.on_first_clock = None; self.on_txid = None
    def in_transaction(self): return self.stored.in_transaction()
    def in_nested_transaction(self): return self.stored.in_nested_transaction()
    def get_execution_options(self): return self.stored.get_execution_options()
    def commit(self): raise AssertionError('business GET attempted COMMIT')
    def rollback(self):
        self.trace.append('rollback'); self.stored.rollback_simulation()
        if self.fail == 'rollback': raise RuntimeError(PRIVATE+' rollback SQL error')
    def execute(self, statement, params=None):
        sql = str(statement)
        if 'admin_commerce:readonly' in sql:
            self.trace.append('readonly')
            if self.fail == 'readonly': raise RuntimeError(PRIVATE+' read-only SQL error')
            return stored_fixtures.Result()
        if 'admin_commerce:clock' in sql:
            self.trace.append('clock'); self.clock_reads += 1
            if self.fail == 'clock': raise RuntimeError(PRIVATE+' clock SQL error')
            if self.clock_reads == 1 and self.on_first_clock: self.on_first_clock()
            return stored_fixtures.Result(scalar=self.now)
        if '/*commerce:txid*/' in sql and self.on_txid: self.on_txid()
        self.trace.append(re.search(r'/\*commerce:(\w+)\*/',sql)[1])
        return self.stored.execute(statement,params or {})


class ReadEngine:
    def __init__(self, bridge): self.bridge, self.trace, self.fail = bridge, [], None
    def connect(self):
        if self.fail == 'connect': raise RuntimeError(PRIVATE+' connect error')
        return self
    def __enter__(self): self.trace.append('open'); return self.bridge
    def __exit__(self, *args):
        self.trace.append('close')
        if self.fail == 'close': raise RuntimeError(PRIVATE+' close error')
    def begin(self): raise AssertionError('business GET attempted engine.begin')


class AdminDetailTests(unittest.TestCase):
    def setUp(self):
        self.fixture = stored_fixtures.WriterTests(); self.fixture.setUp(); self.fixture.paid()
        self.stored = self.fixture.conn; self.before = deepcopy(self.stored.data); self.stored.trace.clear()
        self.bridge = ReadBridge(self.stored); self.engine = ReadEngine(self.bridge)
        self.auth_engine = AuthEngine(); self.auth_engine.seed('session-21',21)
        self.auth_engine.seed('session-22',22); self.auth_engine.seed('session-viewer',23,'viewer',password_verified=False)
        auth.engine = self.auth_engine; auth._device_trust_ready = None
        self.app = FastAPI(); self.app.include_router(routes.router)
        self.app.middleware('http')(auth.auth_middleware)
        self.app.middleware('http')(routes.admin_commerce_no_store)
        self.client = TestClient(self.app, base_url='https://example.invalid',follow_redirects=False)
        self.addCleanup(self.client.close)
        p = patch.object(routes,'get_engine',return_value=self.engine)
        self.engine_loader = p.start(); self.addCleanup(p.stop)

    def get(self, token='session-21', path=PATH, **kwargs):
        headers = {'Cookie': auth.COOKIE+'='+token} if token is not None else {}
        return self.client.get(path,headers=headers,**kwargs)

    def response(self, response, status=200):
        self.assertEqual(response.status_code,status); self.assertEqual(response.headers.get('cache-control'),'no-store')
        self.assertNotIn('set-cookie',response.headers)
        for value in (PRIVATE,'session-21','session-22',owner()['owner_hash'],stored_fixtures.CONTEXT,
                      'fixture-merchant','fixture-result-ref','commerce_order_details','SELECT '):
            self.assertNotIn(value,response.text)
        if self.engine.trace:
            self.assertEqual(self.engine.trace[-1],'close'); self.assertEqual(self.bridge.trace[-1],'rollback')
        return response.json()

    def no_finance(self):
        self.assertFalse(any(tag in ('order_bundle','balance','committed_approval') for tag,_,_ in self.stored.trace))

    def test_original_auth_ast_resolver_middleware_and_principal_binding_are_used(self):
        self.assertIs(routes.current_operator,auth.current_operator)
        for node in AUTH_AST.body:
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                original=next(n for n in AUTH_TREE.body if getattr(n,'name',None)==node.name)
                self.assertEqual(ast.dump(node,include_attributes=False),ast.dump(original,include_attributes=False))
        with patch.object(auth,'current_operator_id',side_effect=AssertionError('fallback forbidden')):
            data=self.response(self.get())
        self.assertEqual(self.auth_engine.last_seen,['session-21'])
        self.assertIn('auth_last_seen',self.auth_engine.trace); self.assertIn('auth_commit',self.auth_engine.trace)
        self.assertEqual(self.bridge.trace[0],'readonly'); self.assertEqual(self.bridge.trace.count('clock'),2)
        self.assertEqual(self.bridge.trace.count('order_bundle'),1)
        self.assertNotIn('context',self.bridge.trace); self.assertNotIn('balance',self.bridge.trace)
        self.assertEqual(self.stored.data,self.before)
        self.assertEqual(set(data),{'commerce_version','checked_at','context','item'})
        self.assertEqual(data['context']['state'],'confirmed')
        self.assertEqual(data['item']['basis_state'],'unconfirmed'); self.assertIsNone(data['item']['basis_id'])
        self.assertEqual(data['item']['verification_state'],'unknown'); self.assertIsNone(data['item']['provider_checked_at'])
        self.assertTrue(all(x==dict(allowed=False,reason='route_unavailable',expected_basis=None)
                            for x in data['item']['actions'].values()))

    def test_owner21_owner22_viewer_requests_use_distinct_actual_session_contexts(self):
        captured=[]; original=writer.read_committed_admin_order
        def read(conn,order_no,*,now,authorize):
            captured.append(authorize(order_no=order_no,now=now)['actor'])
            return original(conn,order_no,now=now,authorize=authorize)
        with patch.object(routes.writer,'read_committed_admin_order',side_effect=read):
            bodies=[self.response(self.get(token)) for token in ('session-21','session-22','session-viewer')]
        self.assertEqual([x['operator_id'] for x in captured],[21,22,23])
        self.assertEqual([x['role'] for x in captured],['owner','owner','viewer'])
        self.assertEqual(len({x['context']['binding_id'] for x in bodies}),3)
        self.assertEqual(self.auth_engine.last_seen,['session-21','session-22','session-viewer'])
        self.assertEqual(self.stored.data,self.before)

    def test_original_resolver_rejects_missing_unknown_revoked_expired_idle_or_suspended_session(self):
        for token, change in ((None,{}),('unknown',{}),('session-21',{'revoked':True}),
                             ('session-21',{'expired':True}),('session-21',{'idle':True}),
                             ('session-21',{'status':'정지'})):
            with self.subTest(token=token,change=change):
                self.auth_engine.seed('session-21',21,**change)
                self.response(self.get(token),401); self.no_finance()
        self.engine_loader.assert_not_called(); self.assertFalse(self.auth_engine.last_seen)

    def test_original_role_denial_and_invalid_native_principal_block_before_business_connection(self):
        for change in ({'role':'customer'},{'operator_id':True},{'operator_id':0},{'operator_id':'21'}):
            with self.subTest(change=change):
                self.auth_engine.seed('session-21',21,**change)
                self.response(self.get(),403); self.no_finance()
        self.engine_loader.assert_not_called()

    def test_direct_route_call_cannot_use_missing_fallback_or_invalid_context_principal(self):
        async def receive(): return {'type':'http.request','body':b'','more_body':False}
        request=Request({'type':'http','method':'GET','path':PATH,'query_string':b'','headers':[]},receive)
        for principal,status in ((None,401),(1,403),({},403),
            ({'operator_id':1,'role':'owner'},403),({'operator_id':True,'role':'owner','status':'활성'},403),
            ({'operator_id':21,'role':'owner','status':'정지'},403)):
            with self.subTest(principal=principal):
                token=auth._current.set(principal)
                try: result=asyncio.run(routes.read_order_detail(ORDER,request))
                finally: auth._current.reset(token)
                self.assertEqual(result.status_code,status); self.assertEqual(result.headers['cache-control'],'no-store')
                self.no_finance()
        self.engine_loader.assert_not_called()

    def test_request_actor_role_grant_query_or_body_never_supplies_authorization(self):
        self.response(self.get(None,params={'actor':21,'role':'owner','authenticated':'true'}),401)
        self.response(self.get(params={'actor':21,'role':'owner'}),422)
        self.response(self.client.request('GET',PATH,headers={'Cookie':auth.COOKIE+'=session-21'},
          json={'authorize':True,'actor':{'operator_id':1,'role':'owner'}}),422)
        self.no_finance(); self.engine_loader.assert_not_called()

    def test_ascii_opaque_order_no_validation_and_absence_are_distinct(self):
        for identifier in ('가','a'*21,'bad!','-leading'):
            with self.subTest(identifier=identifier): self.response(self.get(path='/api/admin/commerce/orders/'+identifier),422)
        self.no_finance()
        self.response(self.get(path='/api/admin/commerce/orders/missing'),404)
        self.assertEqual(self.bridge.trace.count('order_bundle'),1)

    def test_customer_context_expiry_revocation_and_cookie_have_no_admin_scope_role(self):
        self.stored.context.update(expires_at=1,revoked_at=2,owner_identity=owner()|{'owner_hash':'f'*64})
        self.response(self.get())
        self.assertNotIn('context',self.bridge.trace)
        self.assertEqual(self.stored.data,self.before)

    def test_late_context_loss_or_actor_switch_is_denied_before_bundle_and_rolled_back(self):
        for changed in (None,dict(operator_id=22,role='owner',status='활성')):
            with self.subTest(changed=changed):
                self.bridge.clock_reads=0; self.stored.trace.clear()
                self.bridge.on_first_clock=lambda:auth._current.set(changed)
                self.response(self.get(),403); self.no_finance()
        self.bridge.on_first_clock=None

    def test_actual_middleware_resets_context_after_response_and_exception(self):
        async def run(fail):
            request=Request({'type':'http','method':'GET','path':PATH,'query_string':b'',
              'headers':[(b'cookie',(auth.COOKIE+'=session-21').encode())]})
            async def next_response(req):
                self.assertEqual(auth.current_operator()['operator_id'],21)
                if fail: raise RuntimeError(PRIVATE)
                return routes._error(404,'order_not_found')
            sentinel={'unexpected_prior_context':True}; token=auth._current.set(sentinel)
            try:
                if fail:
                    with self.assertRaises(RuntimeError): await auth.auth_middleware(request,next_response)
                else: await auth.auth_middleware(request,next_response)
                self.assertIs(auth.current_operator(),sentinel)
            finally: auth._current.reset(token)
        asyncio.run(run(False)); asyncio.run(run(True)); self.no_finance()

    def test_native_money_over_2pow53_from_actual_mock_flow_is_public_exact_string(self):
        self.fixture.setUp(); self.stored=self.fixture.conn
        unit=9007199254740993; total=unit*2+100
        def big_reader(conn,source,now):
            value=stored_fixtures.reader(conn,source,now)
            value['sale_basis']['lines'][0]['unit_amount']=unit; value['sale_basis']['total']=total
            return value
        writer.create_draft(self.stored,draft(),context_id=stored_fixtures.CONTEXT,owner=owner(),order_no=ORDER,
          sale_basis=sale(),policy=policy(),now=100,revalidate=big_reader)
        self.stored.commit_simulation(); intent=spec(order_basis=self.fixture.basis(),amount=total,order_total=total)
        writer.prepare(self.stored,intent,context_id=stored_fixtures.CONTEXT,owner=owner(),expected_basis=intent['order_basis'],
          policy=policy(),now=105,revalidate=big_reader)
        self.stored.commit_simulation(); writer.dispatch(self.stored,OP,expected_revision=1,now=110,lease_expires_at=130)
        self.stored.commit_simulation(); operation=writer.read_committed_operation(self.stored,OP,now=120)
        event=evidence(operation); writer.finalize(self.stored,OP,event,verifier(operation,event),expected_revision=2,now=120)
        self.stored.commit_simulation(); self.bridge.stored=self.stored; self.before=deepcopy(self.stored.data)
        item=self.response(self.get())['item']
        self.assertEqual(item['total'],str(total)); self.assertEqual(item['approved_amount'],str(total))
        self.assertEqual(item['lines'][0]['unit_amount'],str(unit)); self.assertEqual(self.stored.data,self.before)

    def test_proof_schema_driver_and_business_lifecycle_errors_are_sanitized_503(self):
        cases=('duplicate','proof_missing','same_tx','attestation','receipt','readonly','clock',
               'clock_type','bundle_sql','rollback','close','connect')
        for case in cases:
            with self.subTest(case=case):
                self.stored.data=deepcopy(self.before); self.stored.aborted=False; self.stored.fail_tag=None
                self.bridge.fail=None; self.bridge.now=150; self.engine.fail=None
                if case=='duplicate': self.stored.data['payments'].append(deepcopy(self.stored.data['payments'][0]))
                elif case=='proof_missing': self.stored.data['operations'].clear()
                elif case=='same_tx': self.stored.data['details'][1]['write_txid']=self.stored.txid
                elif case=='attestation': self.stored.data['operations'][OP]['verification']['evidence_basis']='0'*64
                elif case=='receipt': self.stored.data['operations'][OP]['operation']['final_commit']['payment_id']=999
                elif case in ('readonly','clock','rollback'): self.bridge.fail=case
                elif case=='clock_type': self.bridge.now=150.0
                elif case=='bundle_sql': self.stored.fail_tag='order_bundle'
                elif case in ('close','connect'): self.engine.fail=case
                self.response(self.get(),503)
        self.assertEqual(self.stored.data,self.before)

    def test_auth_database_failure_is_sanitized_by_narrow_outer_wrapper(self):
        self.auth_engine.fail=True
        self.response(self.get(),503); self.no_finance(); self.engine_loader.assert_not_called()

    def test_only_two_get_routes_exist_and_no_actions_or_business_writes_are_available(self):
        collection='/api/admin/commerce/orders'
        self.assertEqual([(r.path,r.methods) for r in routes.router.routes],
                         [(collection+'/{order_no}',{'GET'}),(collection,{'GET'})])
        for path in (PATH,collection):
            self.assertEqual(self.client.post(path,headers={'Cookie':auth.COOKIE+'=session-21'}).status_code,405)
        self.engine_loader.assert_not_called()
        self.no_finance()
        from tests.test_admin_commerce_order_list_writer import seed
        self.stored=seed(2,paid_ids=(1,)); self.before=deepcopy(self.stored.data)
        self.bridge.stored=self.stored
        payload=self.response(self.get(path=collection))
        self.assertEqual([item['order_no'] for item in payload['items']],['order-2','order-1'])
        self.assertEqual([item['approved_amount'] for item in payload['items']],['0','2100'])
        self.assertIsNone(payload['next_cursor'])
        self.assertTrue(set(tag for tag,_,_ in self.stored.trace) <= {'txid','admin_order_page'})
        self.assertEqual(self.bridge.trace.count('admin_order_page'),1)
        self.assertEqual(self.bridge.trace[0],'readonly'); self.assertEqual(self.bridge.trace[-1],'rollback')
        self.assertEqual(self.engine.trace,['open','close'])
        self.assertEqual(self.stored.data,self.before)
        self.no_finance()


if __name__=='__main__': unittest.main()
