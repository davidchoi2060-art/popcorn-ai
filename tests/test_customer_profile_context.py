"""C5 native profile handler with explicit members/auth fixtures only.

Accepted C1/C4 APIs are SHA-pinned read-only dependencies, not completed suites.
Legacy api.db is a blocked import stub; profile has no actual DB adapter.
"""
import ast
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import types
import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

_GUARD=False
_FAKE_DB=None

def _deny_external(event,args):
    if not _GUARD:return
    fallback=getattr(socket,'_fallback_socketpair',None)
    if (event=='socket.connect' and fallback is not None
            and sys._getframe(1).f_code is fallback.__code__ and args[1][0] in ('127.0.0.1','::1')):return
    if event in ('socket.connect','socket.connect_ex','socket.getaddrinfo','subprocess.Popen','os.system'):
        raise AssertionError('C5 live IO forbidden')
    if event=='import' and args:
        name=args[0]
        if name=='api.db' and sys.modules.get(name) is not _FAKE_DB:
            raise AssertionError('C5 production DB startup forbidden')
        if name in ('api.main','api.auth') or name.split('.')[0] in ('psycopg','psycopg2','pg8000'):
            raise AssertionError('C5 live main/auth/driver startup forbidden')
    if event=='open' and args and isinstance(args[0],(str,bytes)):
        if str(args[0]).replace('\\','/').lower().rstrip("'").endswith('/.env'):
            raise AssertionError('C5 secret file access forbidden')


def accepted_api(name,variable,digest):
    provided=os.environ.get(variable)
    spec=importlib.util.find_spec(name) if not provided else None
    path=Path(provided) if provided else (Path(spec.origin) if spec is not None else None)
    if path is None:raise AssertionError('Set explicit accepted dependency: '+variable)
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=digest:
        raise AssertionError('Accepted dependency pin mismatch: '+variable)
    if name in sys.modules:
        existing=sys.modules[name]
        if hashlib.sha256(Path(existing.__file__).read_bytes()).hexdigest()!=digest:
            raise AssertionError('Already-loaded dependency collision: '+name)
        return existing
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    exec(compile(raw,str(path),'exec'),module.__dict__)
    return module


class NoDatabase:
    def __init__(self):self.calls=[]
    def connect(self):self.calls.append('connect');raise AssertionError('legacy DB connect forbidden')
    def begin(self):self.calls.append('begin');raise AssertionError('legacy DB transaction forbidden')


sys.addaudithook(_deny_external)
_GUARD=True
legacy_database=NoDatabase()
try:
    identity=accepted_api('api.customer_identity','CUSTOMER_IDENTITY_ACCEPTED_SOURCE',
        '43566f3e25ac826a9bb47e4e0eccf40b30f778c01ffb5bac87757fd12ce152a8')
    auth=accepted_api('api.customer_auth','CUSTOMER_AUTH_ACCEPTED_SOURCE',
        'fa5e74a14be681ed9b1b8bffa54475ece5c8aa53b6f2e2004812a4eee588027e')
    _FAKE_DB=types.ModuleType('api.db');_FAKE_DB.engine=legacy_database
    previous_db=sys.modules.get('api.db');sys.modules['api.db']=_FAKE_DB
    try:profile=importlib.import_module('api.my_account')
    finally:
        if previous_db is None:sys.modules.pop('api.db',None)
        else:sys.modules['api.db']=previous_db
finally:_GUARD=False

TOKEN='a'*64
SECOND_TOKEN='b'*64
DIGEST=hashlib.sha256(TOKEN.encode()).hexdigest()
SECOND_DIGEST=hashlib.sha256(SECOND_TOKEN.encode()).hexdigest()
STABLE='22222222-2222-4222-8222-222222222222'
CONTEXT='11111111-1111-4111-8111-111111111111'
OTHER_STABLE='44444444-4444-4444-8444-444444444444'
OTHER_CONTEXT='33333333-3333-4333-8333-333333333333'
ORIGIN='https://shop.example.invalid'


def member(member_id=101,**changes):
    values=dict(member_id=member_id,auth_subject=STABLE if member_id==101 else OTHER_STABLE,
        principal_revision=1,status='active',nickname='회원',email=None)
    values.update(changes)
    return identity.CanonicalMember(**values)


def record(canonical=None,*,context=CONTEXT,token=TOKEN,principal_changes=None,mapping_changes=None,session_changes=None,now=120):
    canonical=member() if canonical is None else canonical
    registration=identity.IssuerRegistration('fixture-app','https://issuer.example.invalid',
        'fixture-registration','fixture-server-verified','kakao')
    principal=identity.VerifiedPrincipal._from_server_verifier(registration,
        subject='fixture-subject-'+str(canonical.member_id),verified_at=100)
    if principal_changes:
        reg=identity.IssuerRegistration(**dict(dict(issuer_key=registration.issuer_key,issuer=registration.issuer,
            registration_ref=registration.registration_ref,verification_method=registration.verification_method,via='kakao'),
            **{k:v for k,v in principal_changes.items() if k!='subject'}))
        principal=identity.VerifiedPrincipal._from_server_verifier(reg,
            subject=principal_changes.get('subject',principal.subject),verified_at=100)
    mapping=identity.VerifiedIdentityMapping(**dict(dict(identity_id=17,member=canonical,
        issuer_key=principal.issuer_key,issuer=principal.issuer,subject=principal.subject,verified_at=90,
        verification_method=principal.verification_method,registration_ref=principal.registration_ref),**(mapping_changes or {})))
    session=identity.SessionContext(**dict(dict(member_id=canonical.member_id,verified_identity_id=17,
        issued_auth_revision=canonical.principal_revision,session_context_id=context,issued_at=100,expires_at=200),**(session_changes or {})))
    return auth.PersistedSessionSnapshot(hashlib.sha256(token.encode()).hexdigest(),principal,(mapping,),session,now)


class FixtureIssuer:
    enabled=True
    def ready(self):return self.enabled


class FixtureSessions:
    def __init__(self):
        self.enabled=True;self.rows={DIGEST:record()};self.reads=[];self.on_read=None
    def schema_ready(self):return self.enabled
    def read_verified_session(self,digest):
        self.reads.append(digest)
        if self.on_read:self.on_read(len(self.reads))
        return self.rows.get(digest)


class FixtureMembers:
    """Explicit members-only read repository; no orders/reviews/mall capability."""
    def __init__(self):
        self.enabled=True;self.rows={101:member()};self.reads=[];self.on_read=None;self.error=None
    def ready(self):return self.enabled
    def read_member(self,member_id):
        self.reads.append(('members',member_id))
        if self.on_read:self.on_read()
        if self.error:raise self.error
        return self.rows.get(member_id)


def headers(token=TOKEN,context=CONTEXT):
    out={}
    if token is not None:out['Cookie']=auth.COOKIE+'='+token
    if context is not None:out['X-Popcorn-Auth-Context']=context
    return out


class CustomerProfileContextTests(unittest.TestCase):
    def setUp(self):
        global _GUARD
        _GUARD=True
        legacy_database.calls.clear()
        self.sessions=FixtureSessions();self.issuer=FixtureIssuer();self.members=FixtureMembers()
        self.resolver=auth.VerifiedSessionResolver(self.sessions,self.issuer)
        self.app,self.client=self.make_client(self.resolver,self.members)
    def tearDown(self):
        self.assertEqual(legacy_database.calls,[])
        global _GUARD
        _GUARD=False
    def make_client(self,resolver,members=None):
        app=FastAPI();app.include_router(profile.router)
        app.middleware('http')(auth.create_member_middleware(resolver))
        if members is not None:app.dependency_overrides[profile.get_profile_repository]=lambda:members
        client=TestClient(app,base_url=ORIGIN,follow_redirects=False)
        self.addCleanup(client.close)
        return app,client
    def get(self,**kwargs):return self.client.get('/api/my/profile',headers=headers(),**kwargs)
    def assert_error(self,response,status,code):
        self.assertEqual(response.status_code,status,response.text)
        self.assertEqual(response.json(),{'detail':{'code':code}})
        self.assert_nostore(response)
        self.assertNotIn('set-cookie',response.headers)
        for value in (TOKEN,DIGEST,STABLE,'fixture-subject','fixture-registration','private-token','other@example.invalid'):
            self.assertNotIn(value,response.text)
    def assert_nostore(self,response):
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertNotIn('etag',response.headers)
        self.assertNotIn('last-modified',response.headers)
    def mutate_after_query(self,**changes):
        self.members.on_read=lambda:self.sessions.rows.__setitem__(DIGEST,record(**changes))

    def test_native_profile_route_queries_only_authenticated_member_and_emits_exact_C1_DTO(self):
        response=self.get()
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json(),{'auth_version':2,'auth_context':{'member_id':'101',
            'session_context_id':CONTEXT,'principal_revision':'1'},
            'profile':{'member_id':'101','nickname':'회원','email':None}})
        self.assertEqual(self.members.reads,[('members',101)])
        self.assertEqual(self.sessions.reads,[DIGEST]*4)
        self.assert_nostore(response)

    def test_actual_handler_calls_query_and_emit_fresh_helpers_in_order(self):
        calls=[]
        original=profile.require_verified_session
        def confirmed():calls.append('confirm');return original()
        self.members.on_read=lambda:calls.append('members-read')
        with patch.object(profile,'require_verified_session',side_effect=confirmed):response=self.get()
        self.assertEqual(response.status_code,200)
        self.assertEqual(calls,['confirm','members-read','confirm'])

    def test_default_runtime_auth_never_reaches_profile_repository(self):
        _,client=self.make_client(auth.RUNTIME_RESOLVER,self.members)
        self.assert_error(client.get('/api/my/profile',headers=headers()),503,'auth_unavailable')
        self.assertEqual(self.members.reads,[])

    def test_default_profile_repository_is_unconnected_even_with_explicit_verified_auth_fixture(self):
        _,client=self.make_client(self.resolver)
        self.assert_error(client.get('/api/my/profile',headers=headers()),503,'auth_unavailable')
        self.assertEqual(self.members.reads,[])

    def test_flags_client_owner_email_and_provider_cannot_enable_runtime(self):
        _,client=self.make_client(auth.RUNTIME_RESOLVER,self.members)
        with patch.dict(os.environ,{'CUSTOMER_AUTH_V2_ENABLED':'1','CUSTOMER_PROFILE_READ_ENABLED':'1','ALLOW_DEV_LOGIN':'1'}):
            response=client.get('/api/my/profile?member_id=101&email=fixture@example.invalid&verified=true&provider=kakao',headers=headers())
        self.assert_error(response,503,'auth_unavailable')
        self.assertEqual(self.members.reads,[])

    def test_query_body_like_identity_parameters_never_choose_another_member(self):
        response=self.get(params={'member_id':'202','email':'other@example.invalid','auth_subject':OTHER_STABLE,'verified':'true'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['profile']['member_id'],'101')
        self.assertEqual(self.members.reads,[('members',101)])

    def test_header_without_member_cookie_is401_and_members_query_zero(self):
        response=self.client.get('/api/my/profile',headers=headers(None))
        self.assert_error(response,401,'unauthenticated')
        self.assertEqual(self.members.reads,[])

    def test_unknown_cookie_with_matching_header_is401_and_members_query_zero(self):
        response=self.client.get('/api/my/profile',headers=headers(SECOND_TOKEN))
        self.assert_error(response,401,'unauthenticated')
        self.assertEqual(self.members.reads,[])

    def test_missing_mismatched_malformed_or_duplicate_context_never_queries_members(self):
        for context in (None,'',OTHER_CONTEXT,'private-token'):
            response=self.client.get('/api/my/profile',headers=headers(context=context))
            self.assert_error(response,409,'auth_context_changed')
        response=self.client.get('/api/my/profile',headers=[('Cookie',auth.COOKIE+'='+TOKEN),
            ('X-Popcorn-Auth-Context',CONTEXT),('X-Popcorn-Auth-Context',CONTEXT)])
        self.assert_error(response,409,'auth_context_changed')
        self.assertEqual(self.members.reads,[])

    def test_members_repository_unready_is503_without_query(self):
        self.members.enabled=False
        self.assert_error(self.get(),503,'auth_unavailable')
        self.assertEqual(self.members.reads,[])

    def test_members_readiness_strict_true_and_exceptions_are_sanitized(self):
        for value in (1,'ready',None):
            self.members.enabled=value
            self.assert_error(self.get(),503,'auth_unavailable')
        with patch.object(self.members,'ready',side_effect=HTTPException(409,'private-token')):
            self.assert_error(self.get(),503,'auth_unavailable')
        self.assertEqual(self.members.reads,[])

    def test_members_query_error_is_typed503_without_private_result_or_legacy_fallback(self):
        self.members.error=RuntimeError('private-token')
        self.assert_error(self.get(),503,'auth_unavailable')
        self.assertEqual(self.members.reads,[('members',101)])

    def test_repository_http_exception_cannot_leak_detail_or_restore_identity(self):
        self.members.error=HTTPException(418,'private-token')
        self.assert_error(self.get(),503,'auth_unavailable')

    def test_missing_member_row_is401_without_profile(self):
        self.members.rows={}
        self.assert_error(self.get(),401,'unauthenticated')
        self.assertEqual(self.members.reads,[('members',101)])

    def test_untyped_member_row_is_schema503_without_echoing_row_fields(self):
        self.members.rows[101]={'member_id':101,'nickname':'other@example.invalid','mall_member_id':'MALL-private'}
        self.assert_error(self.get(),503,'auth_unavailable')

    def test_other_member_row_and_stable_owner_mismatch_are409(self):
        for row in (member(202,email='other@example.invalid'),member(auth_subject=OTHER_STABLE)):
            self.members.rows[101]=row
            self.assert_error(self.get(),409,'auth_context_changed')

    def test_members_row_revision_mismatch_and_inactive_status_discard_profile(self):
        self.members.rows[101]=member(principal_revision=2)
        self.assert_error(self.get(),409,'auth_context_changed')
        self.members.rows[101]=member(status='blocked')
        self.assert_error(self.get(),401,'member_inactive')

    def test_expiry_just_before_actual_member_query_prevents_query(self):
        def expire(count):
            if count==3:self.sessions.rows[DIGEST]=record(now=200)
        self.sessions.on_read=expire
        self.assert_error(self.get(),401,'unauthenticated')
        self.assertEqual(self.members.reads,[])

    def test_auth_schema_or_issuer_loss_just_before_query_prevents_query(self):
        for target in (self.sessions,self.issuer):
            self.sessions.enabled=True;self.issuer.enabled=True;self.sessions.reads.clear()
            def unavailable(count):
                if count==3:target.enabled=False
            self.sessions.on_read=unavailable
            self.assert_error(self.get(),503,'auth_unavailable')
        self.assertEqual(self.members.reads,[])

    def test_session_expired_or_revoked_after_members_query_discards_data(self):
        for changes in ({'now':200},{'session_changes':{'revoked_at':120}}):
            self.sessions.rows[DIGEST]=record();self.mutate_after_query(**changes)
            self.assert_error(self.get(),401,'unauthenticated')
        self.assertEqual(self.members.reads,[('members',101)]*2)

    def test_current_member_blocked_or_mapping_revoked_after_query_discards_data(self):
        for changes,code in (({'canonical':member(status='blocked')},'member_inactive'),
                             ({'mapping_changes':{'revoked_at':120}},'identity_revoked')):
            self.sessions.rows[DIGEST]=record();self.mutate_after_query(**changes)
            self.assert_error(self.get(),401,code)

    def test_context_and_stable_owner_change_after_query_are409(self):
        for changes in ({'context':OTHER_CONTEXT},{'canonical':member(auth_subject=OTHER_STABLE)}):
            self.sessions.rows[DIGEST]=record();self.mutate_after_query(**changes)
            self.assert_error(self.get(),409,'auth_context_changed')

    def test_revision_change_after_query_discards_profile_with_typed_error(self):
        self.mutate_after_query(canonical=member(principal_revision=2),session_changes={'issued_auth_revision':1})
        self.assert_error(self.get(),401,'principal_revision_changed')
        self.sessions.rows[DIGEST]=record()
        self.mutate_after_query(canonical=member(principal_revision=2))
        self.assert_error(self.get(),409,'auth_context_changed')

    def test_other_authenticated_member_after_query_cannot_take_over_profile_result(self):
        self.mutate_after_query(canonical=member(202,email='other@example.invalid'),context=CONTEXT)
        self.assert_error(self.get(),409,'auth_context_changed')
        self.assertEqual(self.members.reads,[('members',101)])

    def test_registered_identity_provenance_change_after_query_discards_profile(self):
        for changes in ({'issuer_key':'other-app'},{'issuer':'https://other.example.invalid'},
                        {'subject':'other-subject'},{'verification_method':'other-method'},
                        {'registration_ref':'other-registration'}):
            self.sessions.rows[DIGEST]=record();self.mutate_after_query(principal_changes=changes)
            self.assert_error(self.get(),409,'auth_context_changed')

    def test_members_repository_unready_after_query_discards_rows(self):
        self.members.on_read=lambda:setattr(self.members,'enabled',False)
        self.assert_error(self.get(),503,'auth_unavailable')
        self.assertEqual(self.members.reads,[('members',101)])

    def test_members_readiness_lost_during_final_auth_confirm_discards_rows(self):
        def unavailable(count):
            if count==4:self.members.enabled=False
        self.sessions.on_read=unavailable
        self.assert_error(self.get(),503,'auth_unavailable')
        self.assertEqual(self.members.reads,[('members',101)])

    def test_auth_schema_or_issuer_unready_after_query_discards_rows(self):
        for target in (self.sessions,self.issuer):
            self.sessions.enabled=True;self.issuer.enabled=True
            self.members.on_read=lambda:setattr(target,'enabled',False)
            self.assert_error(self.get(),503,'auth_unavailable')

    def test_final_confirmed_contact_fields_are_used_instead_of_stale_query_fields(self):
        self.members.rows[101]=member(nickname='old query',email='old-query@example.invalid')
        self.mutate_after_query(canonical=member(nickname='현재 회원',email='current@example.invalid'))
        response=self.get()
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['profile'],{'member_id':'101','nickname':'현재 회원','email':'current@example.invalid'})
        self.assertNotIn('old-query',response.text)

    def test_profile_public_allowlist_never_includes_issuer_cookie_owner_mall_orders_or_reviews(self):
        response=self.get()
        self.assertEqual(set(response.json()),{'auth_version','auth_context','profile'})
        self.assertEqual(set(response.json()['profile']),{'member_id','nickname','email'})
        for text in (TOKEN,DIGEST,STABLE,'fixture-subject','fixture-registration','mall_member_id','reviewable','order_no','map_state'):
            self.assertNotIn(text,response.text)
        self.assertNotIn('set-cookie',response.headers)

    def test_prior_profile_success_does_not_restore_after_expiry_error(self):
        self.assertEqual(self.get().status_code,200)
        self.sessions.rows[DIGEST]=record(now=200)
        response=self.get()
        self.assert_error(response,401,'unauthenticated')
        self.assertNotIn('profile',response.json())
        self.assertNotIn('auth_context',response.json())

    def test_existing_account_map_review_and_other_private_methods_stay_closed(self):
        for method,path,body in (('GET','/api/my/account',None),('POST','/api/my/account/map',{'agree':True}),
            ('POST','/api/my/reviews',{'item_id':1,'rating':5,'body':'fixture review text'}),
            ('POST','/api/my/profile',{}),('HEAD','/api/my/profile',None),('GET','/api/my/profile/',None)):
            response=self.client.request(method,path,json=body,headers=headers())
            self.assertEqual(response.status_code,503)
            self.assert_nostore(response)
        self.assertEqual(self.members.reads,[])

    def test_admin_cookie_and_public_context_do_not_supply_customer_authority(self):
        response=self.client.get('/api/my/profile',headers={'Cookie':'popcorn_admin_session=fixture-operator',
            'X-Popcorn-Auth-Context':CONTEXT})
        self.assert_error(response,401,'unauthenticated')
        self.assertEqual(self.members.reads,[])

    def test_direct_profile_handler_requires_verified_request_scope_before_query(self):
        request=Request({'type':'http','method':'GET','path':'/api/my/profile','headers':[],
                         'scheme':'https','query_string':b''})
        with self.assertRaises(HTTPException) as caught:profile.profile(request,self.members)
        self.assertEqual(caught.exception.status_code,401)
        self.assertEqual(caught.exception.headers['Cache-Control'],'no-store')
        self.assertEqual(self.members.reads,[])

    def test_bigint_authenticated_owner_query_and_public_id_are_lossless(self):
        canonical=member(identity.MAX_BIGINT,auth_subject=STABLE)
        self.sessions.rows[DIGEST]=record(canonical)
        self.members.rows={identity.MAX_BIGINT:canonical}
        response=self.get()
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['profile']['member_id'],str(identity.MAX_BIGINT))
        self.assertEqual(self.members.reads,[('members',identity.MAX_BIGINT)])
        self.assertIs(type(self.members.reads[0][1]),int)

    def test_concurrent_native_profile_handlers_return_distinct_owners(self):
        self.sessions.rows[SECOND_DIGEST]=record(member(202),context=OTHER_CONTEXT,token=SECOND_TOKEN)
        self.members.rows[202]=member(202)
        _,second_client=self.make_client(self.resolver,self.members)
        def first():return self.get()
        def second():return second_client.get('/api/my/profile',headers=headers(SECOND_TOKEN,OTHER_CONTEXT))
        with ThreadPoolExecutor(max_workers=2) as executor:
            a,b=list(executor.map(lambda call:call(),(first,second)))
        self.assertEqual((a.status_code,b.status_code),(200,200))
        self.assertEqual((a.json()['profile']['member_id'],b.json()['profile']['member_id']),('101','202'))
        self.assertEqual((a.json()['auth_context']['session_context_id'],b.json()['auth_context']['session_context_id']),(CONTEXT,OTHER_CONTEXT))
        self.assertEqual(sorted(self.members.reads),[('members',101),('members',202)])
        self.assertIsNone(auth.current_member())

    def test_profile_source_uses_only_member_port_and_never_legacy_engine_or_account_handler(self):
        tree=ast.parse(Path(profile.__file__).read_text(encoding='utf-8'))
        handler=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='profile')
        names={n.id for n in ast.walk(handler) if isinstance(n,ast.Name)}
        self.assertTrue(names.isdisjoint({'engine','account','_member','account_map','write_review','MALL_BASE','write_locked'}))
        reads=[n for n in ast.walk(handler) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='read_member']
        self.assertEqual(len(reads),1)
        helper_calls=[n for n in ast.walk(handler) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='require_verified_session']
        self.assertEqual(len(helper_calls),2)
        self.assertIs(profile.engine,legacy_database)
        self.assertNotIn('api.db',sys.modules)


if __name__=='__main__':unittest.main()
