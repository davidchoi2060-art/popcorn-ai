"""Selected original auth ASGI + actual owner lookup + simulated support SQL.

No real auth/main/db/env/provider execution. Import the existing selected-auth
fixture to reuse its exact AST resolver/ContextVar rather than invent a login.
"""
from copy import deepcopy
import importlib
import json
import sys
import unittest
from unittest.mock import patch
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests import test_admin_commerce_orders as auth_fixture
from tests.test_commerce_support_writer import Connection, Result, command, NO, CONTEXT, TOKEN, IDENTITY
from api import commerce_owner as owner
from api import commerce_support_core as s

previous = sys.modules.get('api.auth')
sys.modules['api.auth'] = auth_fixture.auth
try:
    routes = importlib.import_module('api.commerce_support_http')
finally:
    if previous is None: sys.modules.pop('api.auth',None)
    else: sys.modules['api.auth'] = previous

POLICY = owner.OwnerPolicy('https://example.invalid',900,True,True)
CUSTOMER = '/api/commerce/orders/' + NO + '/support'
ADMIN = '/api/admin/commerce/orders/' + NO + '/support'


class SQLConnection(Connection):
    def __init__(self, engine):
        super().__init__()
        self.engine=engine;self.data=deepcopy(engine.data);self.saved=deepcopy(self.data)
        self.txid=engine.next_txid;engine.next_txid+=1
        self.context=deepcopy(engine.context);self.now=engine.now
        self.fail_tag=engine.fail_tag;self.after_tag=engine.after_tag
        self.readonly=False
    def execute(self, statement, params=None):
        sql=str(statement)
        if 'commerce_support:readonly' in sql:self.readonly=True
        if self.readonly and ('INSERT INTO' in sql or 'UPDATE commerce_support' in sql):
            raise AssertionError('GET attempted write in read-only connection')
        return super().execute(statement,params)
    def rollback(self):
        self.engine.lifecycle.append(('rollback',self.txid))
        self.rollback_simulation()
        if self.engine.fail=='rollback':raise RuntimeError('private-fixture rollback error')


class Context:
    def __init__(self, engine, write):self.engine,self.write=engine,write
    def __enter__(self):
        self.conn=SQLConnection(self.engine);self.engine.connections.append(self.conn)
        self.engine.lifecycle.append(('begin' if self.write else 'open',self.conn.txid))
        if not self.write and self.engine.read_hook:self.engine.read_hook(self.conn)
        return self.conn
    def __exit__(self, typ, value, tb):
        if self.write:
            if typ is not None:
                self.engine.lifecycle.append(('rollback_write',self.conn.txid))
                self.conn.rollback_simulation()
            else:
                if self.conn.aborted:raise RuntimeError('private-fixture aborted TX')
                if self.engine.fail=='commit_before':raise RuntimeError('private-fixture commit error')
                self.engine.data=deepcopy(self.conn.data)
                self.engine.lifecycle.append(('commit',self.conn.txid))
                if self.engine.fail=='commit_after':raise RuntimeError('private-fixture lost commit ACK')
        self.engine.lifecycle.append(('close_write' if self.write else 'close_read',self.conn.txid))
        if self.engine.fail==('close_write' if self.write else 'close_read'):
            raise RuntimeError('private-fixture close error')


class Engine:
    def __init__(self):
        seed=Connection();self.data=deepcopy(seed.data);self.context=deepcopy(seed.context)
        self.connections=[];self.lifecycle=[];self.next_txid=100;self.now=100
        self.fail=None;self.fail_tag=None;self.after_tag=None;self.read_hook=None
    def connect(self):
        if self.fail=='connect':raise RuntimeError('private-fixture connect error')
        return Context(self,False)
    def begin(self):
        if self.fail=='begin':raise RuntimeError('private-fixture begin error')
        return Context(self,True)


class SupportHTTPTests(unittest.TestCase):
    def setUp(self):
        self.engine=Engine();self.auth=auth_fixture.auth
        self.auth_engine=auth_fixture.AuthEngine()
        self.auth_engine.seed('session-21',21)
        self.auth_engine.seed('session-22',22)
        self.auth_engine.seed('session-viewer',23,'viewer',password_verified=False)
        self.auth.engine=self.auth_engine;self.auth._device_trust_ready=None
        self.app=FastAPI();self.app.include_router(routes.router)
        self.app.middleware('http')(self.auth.auth_middleware)
        self.app.middleware('http')(routes.commerce_support_no_store)
        self.client=TestClient(self.app,base_url=POLICY.origin)
        self.addCleanup(self.client.close)
        for key,value in [('get_engine',self.engine),('get_policy',POLICY)]:
            p=patch.object(routes,key,return_value=value);p.start();self.addCleanup(p.stop)
    def headers(self,audience='customer',token=None):
        token=TOKEN if token is None and audience=='customer' else ('session-21' if token is None else token)
        cookie=(owner.COOKIE if audience=='customer' else self.auth.COOKIE)+'='+token
        return {'Cookie':cookie,'Origin':POLICY.origin,'Content-Type':'application/json'}
    def request(self, *, post=False, audience='customer', cmd=None, path=None, query=None, token=None, **kw):
        path=path or (CUSTOMER if audience=='customer' else ADMIN)
        params={'expected_binding_id':CONTEXT} if audience=='customer' else {}
        if query:params.update(query)
        method=self.client.post if post else self.client.get
        return method(path,params=params,headers=self.headers(audience,token),**({'json':cmd or command()} if post else {}),**kw)
    def create(self,op=1,audience='customer'):
        action='create_inquiry' if audience=='customer' else 'record_external_contact'
        response=self.request(post=True,audience=audience,cmd=command(action,op=op))
        self.assertEqual(200,response.status_code,response.text)
        return response.json()['current_case']['case_id']
    def assert_code(self,response,status,code):
        self.assertEqual(status,response.status_code,response.text)
        self.assertEqual(code,response.json()['detail']['code'])
        self.assertEqual('no-store',response.headers['cache-control'])
        self.assertNotIn('private-fixture',response.text)
    def test_customer_create_uses_actual_guest_lookup_commit_then_distinct_readonly_tx(self):
        case=self.create()
        self.assertEqual(2,len(self.engine.connections))
        write,read=self.engine.connections
        self.assertNotEqual(write.txid,read.txid);self.assertFalse(write.readonly);self.assertTrue(read.readonly)
        self.assertEqual(['begin','commit','close_write','open','rollback','close_read'],[x[0] for x in self.engine.lifecycle])
        self.assertTrue(any(d=='commerce_owner' and tag=='lookup' for d,tag,_,_ in write.trace))
        response=self.request(query={'case_id':case})
        self.assertEqual('create_inquiry',response.json()['events'][0]['action'])
        self.assertEqual('no-store',response.headers['cache-control'])
    def test_direct_guest_missing_or_bad_cookie_never_uses_email_or_visitor_key(self):
        for value in ('','bad','b'*43):
            with self.subTest(value=value):
                response=self.client.get(CUSTOMER,params={'expected_binding_id':CONTEXT},headers={'Cookie':owner.COOKIE+'='+value+'; member_id=17; visitor_key=17'})
                self.assert_code(response,401,'owner_context_lost')
    def test_owner_foreign_or_absent_order_same404_before_support_content_and_receipt(self):
        case=self.create();event=next(iter(self.engine.data['events'].values()))
        for kind in ('foreign','absent'):
            with self.subTest(kind=kind):
                if kind=='foreign':self.engine.data['order']['context_id']=str(UUID(int=901))
                path=CUSTOMER if kind=='foreign' else CUSTOMER.replace(NO,'absent-order')
                response=self.request(path=path,query={'operation_id':event['operation_id'],'request_hash':event['request_hash']})
                self.assert_code(response,404,'order_not_found')
                self.assertFalse(any(tag in ('operation','case','event_page','case_page') for _,tag,_,_ in self.engine.connections[-1].trace))
    def test_expired_revoked_binding_change_and_member_shape_have_no_issuer_bypass(self):
        for key,value,code,status in [('expires_at',100,'owner_context_lost',401),('revoked_at',1,'owner_context_lost',401),
                                    ('context_id',str(UUID(int=901)),'owner_context_changed',409)]:
            with self.subTest(key=key):
                old=deepcopy(self.engine.context);self.engine.context[key]=value
                self.assert_code(self.request(),status,code);self.engine.context=old
        from api import commerce_contract as c
        member=dict(kind='member',member_id=17,auth_subject='shape-only')
        self.engine.context.update(owner_identity=member,owner_scope=c.fingerprint(member))
        self.assert_code(self.request(),401,'verified_member_adapter_unready')
    def test_selected_original_auth_early_denials_and_viewer_write_no_store(self):
        response=self.client.get(ADMIN);self.assertEqual(401,response.status_code)
        self.assertEqual('no-store',response.headers['cache-control']);self.assertEqual([],self.engine.connections)
        response=self.request(post=True,audience='admin',token='session-viewer',cmd=command('record_external_contact'))
        self.assertEqual(403,response.status_code);self.assertEqual('no-store',response.headers['cache-control'])
        self.assertEqual([],self.engine.connections)
        self.assertEqual(200,self.request(audience='admin',token='session-viewer').status_code)
    def test_direct_route_without_auth_context_and_invalid_native_operator_fails(self):
        app=FastAPI();app.include_router(routes.router)
        with TestClient(app,base_url=POLICY.origin) as client:
            response=client.get(ADMIN)
        self.assert_code(response,401,'admin_authentication_required')
        for actor in [dict(operator_id=True,role='operator',status='활성'),dict(operator_id=21,role='operator',status='정지')]:
            with self.subTest(actor=actor),patch.object(routes,'current_operator',return_value=actor):
                self.assert_code(self.request(audience='admin'),403,'support_permission_required')
    def test_admin_write_native_context_is_rechecked_and_private_case_never_customer(self):
        case=self.create(audience='admin')
        self.assertEqual([],self.request().json()['cases'])
        self.assert_code(self.request(query={'case_id':case}),404,'support_case_not_found')
        op=next(iter(self.engine.data['events'].values()))
        self.assert_code(self.request(audience='admin',token='session-22',query={'operation_id':op['operation_id'],'request_hash':op['request_hash']}),404,'support_operation_not_found')
        calls=0
        original=routes.current_operator
        def changed():
            nonlocal calls
            calls+=1
            return original() if calls<=2 else dict(operator_id=22,role='operator',status='활성')
        with patch.object(routes,'current_operator',side_effect=changed):
            response=self.request(post=True,audience='admin',cmd=command('record_external_contact',op=2))
        self.assert_code(response,403,'support_authorization_changed')
        self.assertEqual(1,len(self.engine.data['cases']))
    def test_strict_origin_https_json_duplicate_unknown_and_size_before_sql(self):
        for additions,status,code in [({'Origin':'https://evil.invalid'},403,'same_origin_required'),
                                      ({'Sec-Fetch-Site':'cross-site'},403,'same_origin_required'),
                                      ({'Content-Type':'text/plain'},415,'json_required')]:
            with self.subTest(headers=additions):
                response=self.client.post(CUSTOMER,params={'expected_binding_id':CONTEXT},headers=self.headers()|additions,content=json.dumps(command()))
                self.assert_code(response,status,code)
        raw=json.dumps(command())[:-1]+',"operation_id":"'+command()['operation_id']+'"}'
        self.assert_code(self.client.post(CUSTOMER,params={'expected_binding_id':CONTEXT},headers=self.headers(),content=raw),422,'invalid_support_json')
        self.assert_code(self.request(post=True,cmd=command()|{'role':'owner'}),422,'invalid_support_request')
        self.assert_code(self.client.post(CUSTOMER,params={'expected_binding_id':CONTEXT},headers=self.headers(),content='x'*(routes.MAX_REQUEST_BYTES+1)),422,'support_request_too_large')
        self.assertEqual([],self.engine.connections)
        with TestClient(self.app,base_url='http://example.invalid') as plain:
            response=plain.get(CUSTOMER,params={'expected_binding_id':CONTEXT},headers=self.headers())
        self.assert_code(response,503,'owner_configuration_unready')
    def test_no_implicit_configuration_and_admin_origin_validation(self):
        with patch.object(routes,'get_policy',side_effect=owner.OwnerError(503,'owner_configuration_unready')):
            self.assert_code(self.request(),503,'owner_configuration_unready')
        response=self.client.post(ADMIN,headers=self.headers('admin')|{'Origin':'https://evil.invalid'},json=command('record_external_contact'))
        self.assert_code(response,403,'same_origin_required')
    def test_query_exact_modes_duplicate_binding_limit_body_and_unknown_fields(self):
        for query,code in [({'case_id':str(UUID(int=1)),'operation_id':str(UUID(int=2))},'invalid_support_mode'),
                           ({'operation_id':str(UUID(int=1))},'invalid_support_mode'),
                           ({'request_hash':'a'*64},'invalid_support_mode'),({'limit':'01'},'invalid_support_limit'),
                           ({'limit':'51'},'invalid_support_limit'),({'role':'owner'},'invalid_support_query')]:
            with self.subTest(query=query):self.assert_code(self.request(query=query),422,code)
        response=self.client.get(CUSTOMER,params=[('expected_binding_id',CONTEXT),('expected_binding_id',CONTEXT)],headers=self.headers())
        self.assert_code(response,422,'invalid_support_query')
        self.assert_code(self.client.request('GET',CUSTOMER,params={'expected_binding_id':CONTEXT},headers=self.headers(),content='{}'),422,'invalid_support_query')
        self.assertEqual([],self.engine.connections)
    def test_replay_after_later_event_exact_immutable_response_and_separate_current_case(self):
        case=self.create();cmd=command('close',op=2,case=case,revision=1,body='종결 판단 기록')
        original=self.request(post=True,audience='admin',cmd=cmd).json()['operation_result']
        self.assertEqual(200,self.request(post=True,cmd=command('reopen',op=3,case=case,revision=2)).status_code)
        response=self.request(post=True,audience='admin',cmd=cmd)
        self.assertEqual(200,response.status_code,response.text)
        self.assertEqual(original,response.json()['operation_result']);self.assertEqual('open',response.json()['current_case']['state'])
        self.assertEqual(3,len(self.engine.data['events']))
    def test_draft_and_internal_note_private_then_explicit_publication_only(self):
        case=self.create()
        for op,action in [(2,'internal_note'),(3,'record_reply')]:
            response=self.request(post=True,audience='admin',cmd=command(action,op=op,case=case,revision=op-1,body='PRIVATE-'+action))
            self.assertEqual(200,response.status_code,response.text)
        before=self.request(query={'case_id':case}).json()
        self.assertEqual(1,before['current_case']['revision']);self.assertNotIn('PRIVATE',json.dumps(before))
        draft=self.engine.data['events'][str(UUID(int=3))]
        response=self.request(post=True,audience='admin',cmd=command('publish_customer_reply',op=4,case=case,revision=3,reply=draft['event_id']))
        self.assertEqual(200,response.status_code,response.text)
        after=self.request(query={'case_id':case}).json()
        self.assertEqual('PRIVATE-record_reply',after['events'][-1]['body'])
        self.assertNotIn('internal_note',json.dumps(after));self.assertNotIn('reply_event_id',json.dumps(after))
        self.assertEqual('not_attempted',response.json()['operation_result']['result']['delivery'])
    def test_commit_before_after_and_write_close_unknown_never_false_success(self):
        for failure,stored in [('commit_before',False),('commit_after',True),('close_write',True)]:
            with self.subTest(failure=failure):
                self.engine=Engine();self.engine.fail=failure
                with patch.object(routes,'get_engine',return_value=self.engine):response=self.request(post=True)
                self.assert_code(response,503,'support_record_unconfirmed')
                self.assertEqual(stored,bool(self.engine.data['events']))
                self.assertEqual(1,len(self.engine.connections))
    def test_fresh_read_absence_uncommitted_proof_and_schema_fail_are_unknown_after_commit(self):
        for mutation in ('absence','txid','invalid'):
            with self.subTest(mutation=mutation):
                self.engine=Engine()
                def change(conn):
                    if mutation=='absence':conn.data['events'].clear()
                    elif mutation=='txid':next(iter(conn.data['events'].values()))['write_txid']=conn.txid
                    else:next(iter(conn.data['events'].values()))['visible']=1
                self.engine.read_hook=change
                with patch.object(routes,'get_engine',return_value=self.engine):response=self.request(post=True)
                self.assert_code(response,503,'support_record_unconfirmed')
                self.assertTrue(self.engine.data['events'])
    def test_read_connect_clock_sql_rollback_close_failures_sanitized_not_zero_cases(self):
        self.create()
        for fail in ('connect','rollback','close_read'):
            with self.subTest(fail=fail):
                self.engine.fail=fail;self.assert_code(self.request(),503,'support_unavailable')
        self.engine.fail=None
        for tag in ('readonly','clock','scope','case_page','case_proof'):
            with self.subTest(tag=tag):
                self.engine.fail_tag=tag;self.assert_code(self.request(),503,'support_unavailable')
    def test_missing_uuid_recovery_is_not_rejection_or_success(self):
        response=self.request(query={'operation_id':str(UUID(int=99)),'request_hash':'a'*64})
        self.assert_code(response,404,'support_operation_not_found')
        self.assertNotIn('declined',response.text);self.assertNotIn('confirmed',response.text)
    def test_post_infrastructure_and_fresh_rollback_close_failures_are_unknown(self):
        for fail in ('begin','connect','rollback','close_read'):
            with self.subTest(fail=fail):
                engine=Engine();engine.fail=fail
                with patch.object(routes,'get_engine',return_value=engine):response=self.request(post=True)
                self.assert_code(response,503,'support_record_unconfirmed')
        for tag in ('clock','scope','insert_case','insert_event'):
            with self.subTest(tag=tag):
                engine=Engine();engine.fail_tag=tag
                with patch.object(routes,'get_engine',return_value=engine):response=self.request(post=True)
                self.assert_code(response,503,'support_record_unconfirmed')
                self.assertEqual({},engine.data['events'])
    def test_customer_close_and_admin_direct_customer_impersonation_are_forbidden(self):
        self.assert_code(self.request(post=True,cmd=command('close')),403,'support_action_forbidden')
        self.assert_code(self.request(post=True,audience='admin',cmd=command()),403,'support_action_forbidden')
        self.assertEqual([],self.engine.connections)
    def test_get_uses_readonly_rollback_close_without_business_commit(self):
        self.create();self.engine.lifecycle.clear();self.engine.connections.clear()
        response=self.request();self.assertEqual(200,response.status_code,response.text)
        self.assertEqual(['open','rollback','close_read'],[x[0] for x in self.engine.lifecycle])
        conn=self.engine.connections[0];self.assertEqual('readonly',conn.trace[0][1])
        self.assertFalse(any(tag in ('insert_case','update_case','insert_event') for _,tag,_,_ in conn.trace))
    def test_mid_write_owner_revocation_and_late_read_expiry_fail_closed(self):
        count=0
        def revoke(tag):
            nonlocal count
            if tag=='lookup':
                count+=1
                if count==2:self.engine.connections[-1].context['revoked_at']=101
        self.engine.after_tag=revoke
        self.assert_code(self.request(post=True),401,'owner_context_lost')
        self.assertEqual({},self.engine.data['events'])
        self.engine.after_tag=None;self.create();self.engine.context['expires_at']=102
        count=0
        def expire(tag):
            nonlocal count
            if tag=='clock':
                count+=1
                if count==2:self.engine.connections[-1].now=103
        self.engine.after_tag=expire
        self.assert_code(self.request(),401,'owner_context_lost')
    def test_support_wrapper_is_exact_path_and_main_registration_is_not_claimed(self):
        for path in (CUSTOMER,ADMIN,CUSTOMER+'/',ADMIN+'/'):
            self.assertTrue(routes._PATH.fullmatch(path))
        for path in (CUSTOMER+'/else','/api/admin/reprice/operations',CUSTOMER.replace('/support','/support-extra')):
            self.assertFalse(routes._PATH.fullmatch(path))
        self.assertEqual(4,len(routes.router.routes))
        # The selected mock registers the wrapper; application main is untouched.
        self.assertNotIn('api.main',sys.modules)


if __name__ == '__main__':
    unittest.main()
