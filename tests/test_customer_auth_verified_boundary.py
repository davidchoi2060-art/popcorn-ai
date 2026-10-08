"""C4 explicit schema/repository + ASGI fixtures; no live issuer/DB/IO.

When C1 is not yet integrated into this checkout, the runner must explicitly set
CUSTOMER_IDENTITY_ACCEPTED_SOURCE to its accepted frozen API file. It is read
only, hash-pinned, and no completed C1/C3 test suite is imported or rerun.
"""
import ast
import asyncio
from dataclasses import replace
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.testclient import TestClient

_GUARD = False

def _deny_external(event,args):
    if not _GUARD:
        return
    fallback = getattr(socket,'_fallback_socketpair',None)
    if (event == 'socket.connect' and fallback is not None
            and sys._getframe(1).f_code is fallback.__code__
            and args[1][0] in ('127.0.0.1','::1')):
        return
    if event in ('socket.connect','socket.connect_ex','socket.getaddrinfo','subprocess.Popen','os.system'):
        raise AssertionError('C4 live IO forbidden')
    if event == 'import' and args and args[0] == 'api.db':
        raise AssertionError('C4 production DB import forbidden')
    if event == 'open' and args and isinstance(args[0],(str,bytes)):
        if str(args[0]).replace('\\','/').lower().rstrip("'").endswith('/.env'):
            raise AssertionError('C4 production secret file forbidden')

sys.addaudithook(_deny_external)
_GUARD = True
try:
    if importlib.util.find_spec('api.customer_identity') is None:
        path = Path(os.environ['CUSTOMER_IDENTITY_ACCEPTED_SOURCE'])
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != '43566f3e25ac826a9bb47e4e0eccf40b30f778c01ffb5bac87757fd12ce152a8':
            raise AssertionError('accepted C1 dependency pin mismatch')
        spec = importlib.util.spec_from_file_location('api.customer_identity',path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        # Execute the pinned bytes directly; do not write/read C1 pycache.
        exec(compile(raw,str(path),'exec'),module.__dict__)
    auth = importlib.import_module('api.customer_auth')
finally:
    _GUARD = False
identity = auth.identity
TOKEN = 'a'*64
OTHER_TOKEN = 'b'*64
DIGEST = hashlib.sha256(TOKEN.encode('ascii')).hexdigest()
STABLE = '22222222-2222-4222-8222-222222222222'
CONTEXT = '11111111-1111-4111-8111-111111111111'
ROTATED = '33333333-3333-4333-8333-333333333333'
ORIGIN = 'https://shop.example.invalid'


def snapshot(*,member_changes=None,mapping_changes=None,session_changes=None,**changes):
    registration = identity.IssuerRegistration('fixture-app','https://issuer.example.invalid',
        'fixture-registration','fixture-server-verified','kakao')
    principal = identity.VerifiedPrincipal._from_server_verifier(registration,
        subject='fixture-private-subject',verified_at=100)
    canonical = identity.CanonicalMember(**dict(dict(member_id=101,auth_subject=STABLE,
        principal_revision=1,status='active',nickname='회원',email=None),**(member_changes or {})))
    mapping = identity.VerifiedIdentityMapping(**dict(dict(identity_id=17,member=canonical,
        issuer_key=registration.issuer_key,issuer=registration.issuer,subject=principal.subject,
        verified_at=90,verification_method=registration.verification_method,
        registration_ref=registration.registration_ref),**(mapping_changes or {})))
    session = identity.SessionContext(**dict(dict(member_id=101,verified_identity_id=17,
        issued_auth_revision=1,session_context_id=CONTEXT,issued_at=100,expires_at=200),**(session_changes or {})))
    return auth.PersistedSessionSnapshot(**dict(dict(credential_hash=DIGEST,principal=principal,
        mappings=(mapping,),session=session,now=120),**changes))


class FixtureIssuer:
    def __init__(self,ready=True): self.enabled=ready; self.calls=0
    def ready(self): self.calls+=1; return self.enabled


class FixtureRepository:
    """Explicit v2 schema and persisted-row simulation, not a DB implementation."""
    def __init__(self):
        self.enabled=True; self.rows={DIGEST:snapshot()}; self.reads=[]
        self.schema_calls=0; self.sequence=[]; self.on_read=None
    def schema_ready(self):
        self.schema_calls+=1
        return self.enabled
    def read_verified_session(self,digest):
        self.reads.append(digest)
        if self.on_read is not None: self.on_read(len(self.reads))
        row = self.sequence.pop(0) if self.sequence else self.rows.get(digest)
        if isinstance(row,Exception): raise row
        return row


def headers(token=TOKEN,context=CONTEXT):
    result={}
    if token is not None: result['Cookie']=auth.COOKIE+'='+token
    if context is not None: result['X-Popcorn-Auth-Context']=context
    return result


class VerifiedBoundaryTests(unittest.TestCase):
    def setUp(self):
        global _GUARD
        _GUARD=True
        self.repository=FixtureRepository()
        self.issuer=FixtureIssuer()
        self.resolver=auth.VerifiedSessionResolver(self.repository,self.issuer)
        self.queries=[]; self.before_emit=None
        self.client=self.client_for(self.resolver)
    def tearDown(self):
        global _GUARD
        _GUARD=False
    def client_for(self,resolver):
        app=FastAPI()
        app.include_router(auth.create_auth_router(resolver))
        app.middleware('http')(auth.create_member_middleware(resolver))
        @app.get('/api/my/profile')
        def profile(request:Request):
            before=auth.require_verified_session()
            self.queries.append(before.member.member.member_id)
            if self.before_emit is not None: self.before_emit()
            current=auth.require_verified_session()
            return identity.profile_payload(current.member,current.session,now=current.now,
                expected_context=request.headers['X-Popcorn-Auth-Context'])
        @app.api_route('/api/my/orders',methods=['GET','POST'])
        def denied():
            raise AssertionError('other private handler was reached')
        for path in ('/api/orders','/api/admin/probe','/shared/probe','/api/commerce/owner-context',
                     '/api/commerce/orders/fixture','/api/commerce/orders/fixture/support',
                     '/api/commerce/orders/fixture/fulfillment'):
            def public():
                self.assertIsNone(auth.current_member())
                return {'fixture':'public-pass-through'}
            app.add_api_route(path,public,methods=['GET','POST'])
        client=TestClient(app,base_url=ORIGIN,follow_redirects=False)
        self.addCleanup(client.close)
        return client
    def assert_error(self,response,status,code):
        self.assertEqual(response.status_code,status,response.text)
        self.assertEqual(response.json(),{'detail':{'code':code}})
        self.assert_nostore(response)
        for secret in (TOKEN,DIGEST,STABLE,'fixture-private-subject','fixture-registration'):
            self.assertNotIn(secret,response.text)
    def assert_nostore(self,response):
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertNotIn('etag',response.headers)
        self.assertNotIn('last-modified',response.headers)
    def direct_error(self,status,code,call,*args,**kwargs):
        with self.assertRaises(HTTPException) as caught: call(*args,**kwargs)
        self.assertEqual((caught.exception.status_code,caught.exception.detail),(status,{'code':code}))
        self.assertEqual(caught.exception.headers['Cache-Control'],'no-store')

    def test_runtime_me_is_exact503_unavailable_with_or_without_claimed_cookie(self):
        client=self.client_for(auth.RUNTIME_RESOLVER)
        for token in (None,TOKEN,'previous-dev-session'):
            response=client.get('/api/auth/me',headers=headers(token))
            self.assert_error(response,503,'auth_unavailable')
            self.assertNotIn('set-cookie',response.headers)
        self.assertEqual(self.repository.reads,[])

    def test_runtime_private_scope_is_unavailable_and_never_queries(self):
        client=self.client_for(auth.RUNTIME_RESOLVER)
        for path in ('/api/my/profile','/api/my/orders'):
            self.assert_error(client.get(path,headers=headers()),503,'auth_unavailable')
        self.assertEqual(self.queries,[])

    def test_flags_client_fields_and_localhost_never_enable_runtime_or_dev(self):
        client=self.client_for(auth.RUNTIME_RESOLVER)
        with patch.dict(os.environ,{'CUSTOMER_AUTH_V2_ENABLED':'1','CUSTOMER_PROFILE_READ_ENABLED':'1',
             'ALLOW_DEV_LOGIN':'1','CUSTOMER_AUTH_VERIFIED':'1','COOKIE_SECURE':'0'}):
            response=client.get('/api/auth/me?member_id=101&verified=true&email=fixture@example.invalid',headers=headers())
            self.assert_error(response,503,'auth_unavailable')
            for provider in (*auth.VIA,'verified','unknown'):
                response=client.post('/api/auth/login',json={'email':'fixture@example.invalid',
                    'provider':provider,'verified':True,'member_id':101,'auth_subject':STABLE})
                self.assert_error(response,503,'auth_unavailable')
                self.assertNotIn('set-cookie',response.headers)

    def test_login400_and422_remain_nostore_without_identity_or_cookie(self):
        for body,status in (({'email':'invalid'},400),({},422)):
            response=self.client.post('/api/auth/login',json=body)
            self.assertEqual(response.status_code,status)
            self.assert_nostore(response)
            self.assertNotIn('set-cookie',response.headers)
        self.assertEqual(self.repository.reads,[])

    def test_logout_clears_only_browser_cookie_and_does_not_claim_persisted_success(self):
        response=self.client.post('/api/auth/logout',headers=headers())
        self.assert_error(response,503,'auth_unavailable')
        self.assertIn(auth.COOKIE+'=',response.headers['set-cookie'])
        self.assertIn('Max-Age=0',response.headers['set-cookie'])
        self.assertEqual(self.repository.reads,[])

    def test_legacy_resolver_and_new_session_port_cannot_restore_or_issue(self):
        for sid in (None,'',TOKEN,'previous-dev-session'):
            self.assertIsNone(auth.resolve_session(sid))
        self.direct_error(503,'auth_unavailable',auth._new_session,None,101,None)

    def test_runtime_issuer_is_unready_even_with_fixture_verified_principal(self):
        with self.assertRaises(identity.IdentityError) as caught:
            auth.RuntimeIssuerReadiness().verify(snapshot().principal)
        self.assertEqual((caught.exception.status,caught.exception.code),(503,'auth_unavailable'))

    def test_schema_unready_rejects_before_cookie_lookup(self):
        self.repository.enabled=False
        self.assert_error(self.client.get('/api/auth/me',headers=headers()),503,'auth_unavailable')
        self.assertEqual(self.repository.reads,[])

    def test_issuer_unready_rejects_before_schema_or_cookie_lookup(self):
        self.issuer.enabled=False
        self.assert_error(self.client.get('/api/auth/me',headers=headers()),503,'auth_unavailable')
        self.assertEqual(self.repository.reads,[])
        self.assertEqual(self.repository.schema_calls,0)

    def test_readiness_exception_is_sanitized_to_fixed_preparation_contract(self):
        with patch.object(self.repository,'schema_ready',side_effect=HTTPException(418,'private-token')):
            self.assert_error(self.client.get('/api/auth/me',headers=headers()),503,'auth_unavailable')

    def test_repository_failure_does_not_leak_secret_or_restore_member(self):
        self.repository.sequence=[RuntimeError('private-token')]
        self.assert_error(self.client.get('/api/auth/me',headers=headers()),503,'auth_unavailable')

    def test_missing_cookie_signed_out_fixture_has_no_lookup_or_member_context(self):
        response=self.client.get('/api/auth/me')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json(),identity.signed_out_payload())
        self.assert_nostore(response)
        self.assertEqual(self.repository.reads,[])

    def test_unknown_cookie_is401_without_email_or_client_identity_linking(self):
        response=self.client.get('/api/auth/me?email=fixture@example.invalid&member_id=101',headers=headers(OTHER_TOKEN))
        self.assert_error(response,401,'unauthenticated')
        self.assertEqual(self.repository.reads,[hashlib.sha256(OTHER_TOKEN.encode()).hexdigest()])

    def test_cookie_lookup_uses_hash_and_confirm_performs_two_fresh_reads(self):
        response=self.client.get('/api/auth/me',headers=headers())
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.repository.reads,[DIGEST,DIGEST])
        self.assertNotIn(TOKEN,self.repository.reads)
        self.assert_nostore(response)

    def test_me_fixture_emits_exact_safe_member_and_context_without_private_provenance(self):
        response=self.client.get('/api/auth/me',headers=headers())
        self.assertEqual(response.json(),{'auth_version':2,'phase':'authenticated','authenticated':True,
            'member':{'member_id':'101','nickname':'회원','email':None,'via':'kakao'},
            'auth_context':{'member_id':'101','session_context_id':CONTEXT,'principal_revision':'1'}})
        for value in (TOKEN,DIGEST,STABLE,'fixture-private-subject','fixture-registration','identity_id'):
            self.assertNotIn(value,response.text)

    def test_malformed_and_ambiguous_member_cookies_are_rejected_before_lookup(self):
        for cookie in (auth.COOKIE+'='+TOKEN.upper(),auth.COOKIE+'="'+TOKEN+'"',auth.COOKIE+'=short',
                       auth.COOKIE+'='+TOKEN+'; '+auth.COOKIE+'='+TOKEN,auth.COOKIE):
            response=self.client.get('/api/auth/me',headers={'Cookie':cookie})
            self.assert_error(response,401,'unauthenticated')
        self.assertEqual(self.repository.reads,[])

    def test_duplicate_cookie_headers_are_rejected_before_lookup(self):
        response=self.client.get('/api/auth/me',headers=[('Cookie',auth.COOKIE+'='+TOKEN),('Cookie','tracking=x')])
        self.assert_error(response,401,'unauthenticated')
        self.assertEqual(self.repository.reads,[])

    def test_direct_cookie_port_does_not_coerce_nonstring_or_string_subclass(self):
        class TextSubclass(str): pass
        class EqualityOnly:
            def __eq__(self,other): return True
        for sid in (True,17,TextSubclass(TOKEN),EqualityOnly()):
            self.direct_error(401,'unauthenticated',self.resolver.resolve,sid)
        self.assertEqual(self.repository.reads,[])

    def test_untyped_legacy_row_is_schema_unavailable_not_verified_identity(self):
        self.repository.rows[DIGEST]={'member_id':101,'joined_via':'kakao','provider_uid':'fixture@example.invalid'}
        self.assert_error(self.client.get('/api/auth/me',headers=headers()),503,'auth_unavailable')

    def test_wrong_persisted_credential_hash_is401(self):
        self.repository.rows[DIGEST]=snapshot(credential_hash='b'*64)
        self.assert_error(self.client.get('/api/auth/me',headers=headers()),401,'unauthenticated')

    def test_unverified_client_principal_never_becomes_member(self):
        self.repository.rows[DIGEST]=snapshot(principal={'verified':True,'member_id':101})
        self.assert_error(self.client.get('/api/auth/me',headers=headers()),401,'server_verified_principal_required')

    def test_mapping_without_exact_verified_subject_is_unlinked409(self):
        self.repository.rows[DIGEST]=snapshot(mapping_changes={'subject':'different-subject'})
        self.assert_error(self.client.get('/api/auth/me',headers=headers()),409,'identity_unlinked')

    def test_mapping_provenance_mismatch_and_revocation_are401(self):
        for changes,code in (({'registration_ref':'other-registration'},'verification_provenance_mismatch'),
                             ({'revoked_at':0},'identity_revoked')):
            self.repository.rows[DIGEST]=snapshot(mapping_changes=changes)
            self.assert_error(self.client.get('/api/auth/me',headers=headers()),401,code)

    def test_current_member_status_session_fk_and_revision_are_checked(self):
        cases=((snapshot(member_changes={'status':'blocked'}),'member_inactive'),
               (snapshot(session_changes={'member_id':102}),'session_identity_mismatch'),
               (snapshot(session_changes={'verified_identity_id':18}),'session_identity_mismatch'),
               (snapshot(member_changes={'principal_revision':2}),'principal_revision_changed'))
        for record,code in cases:
            self.repository.rows[DIGEST]=record
            self.assert_error(self.client.get('/api/auth/me',headers=headers()),401,code)

    def test_current_session_expiry_revocation_and_verification_time_are_checked(self):
        for changes in ({'expires_at':120},{'revoked_at':0},{'issued_at':121},{'issued_at':99}):
            self.repository.rows[DIGEST]=snapshot(session_changes=changes)
            self.assert_error(self.client.get('/api/auth/me',headers=headers()),401,'unauthenticated')

    def test_profile_header_alone_does_not_authorize_without_cookie(self):
        response=self.client.get('/api/my/profile',headers=headers(None))
        self.assert_error(response,401,'unauthenticated')
        self.assertEqual(self.queries,[])

    def test_profile_requires_single_exact_context_before_query(self):
        for context in (None,'',ROTATED,'private-token'):
            response=self.client.get('/api/my/profile',headers=headers(context=context))
            self.assert_error(response,409,'auth_context_changed')
        response=self.client.get('/api/my/profile',headers=[('Cookie',auth.COOKIE+'='+TOKEN),
            ('X-Popcorn-Auth-Context',CONTEXT),('X-Popcorn-Auth-Context',CONTEXT)])
        self.assert_error(response,409,'auth_context_changed')
        self.assertEqual(self.queries,[])

    def test_profile_fixture_reads_current_identity_before_query_and_before_emission(self):
        response=self.client.get('/api/my/profile',headers=headers())
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json(),{'auth_version':2,'auth_context':{'member_id':'101',
            'session_context_id':CONTEXT,'principal_revision':'1'},'profile':{'member_id':'101','nickname':'회원','email':None}})
        self.assertEqual(self.queries,[101])
        self.assertEqual(self.repository.reads,[DIGEST]*4)
        self.assert_nostore(response)

    def test_profile_revocation_between_query_and_emission_discards_private_result(self):
        self.before_emit=lambda:self.repository.rows.__setitem__(DIGEST,snapshot(session_changes={'revoked_at':120}))
        response=self.client.get('/api/my/profile',headers=headers())
        self.assert_error(response,401,'unauthenticated')
        self.assertEqual(self.queries,[101])
        self.assertNotIn('profile',response.json())

    def test_profile_schema_unavailable_between_query_and_emission_discards_result(self):
        self.before_emit=lambda:setattr(self.repository,'enabled',False)
        self.assert_error(self.client.get('/api/my/profile',headers=headers()),503,'auth_unavailable')
        self.assertEqual(self.queries,[101])

    def test_me_context_and_stable_owner_change_before_emission_is409(self):
        for changed in (snapshot(session_changes={'session_context_id':ROTATED}),snapshot(member_changes={'auth_subject':ROTATED})):
            self.repository.sequence=[snapshot(),changed]
            self.assert_error(self.client.get('/api/auth/me',headers=headers()),409,'auth_context_changed')

    def test_me_revocation_expiry_and_revision_change_on_confirm_never_emit_authenticated(self):
        for changed,code in ((snapshot(session_changes={'revoked_at':120}),'unauthenticated'),
                             (snapshot(now=200),'unauthenticated'),
                             (snapshot(member_changes={'principal_revision':2}),'principal_revision_changed')):
            self.repository.sequence=[snapshot(),changed]
            self.assert_error(self.client.get('/api/auth/me',headers=headers()),401,code)

    def test_previous_authenticated_response_is_not_recovered_after_schema_failure(self):
        first=self.client.get('/api/auth/me',headers=headers())
        self.assertTrue(first.json()['authenticated'])
        self.repository.enabled=False
        second=self.client.get('/api/auth/me',headers=headers())
        self.assert_error(second,503,'auth_unavailable')
        self.assertEqual(set(second.json()),{'detail'})

    def test_readiness_lost_during_last_repository_read_blocks_emission(self):
        for target in (self.issuer,self.repository):
            self.issuer.enabled=True; self.repository.enabled=True; self.repository.reads.clear()
            def lose_readiness(count):
                if count == 2: target.enabled=False
            self.repository.on_read=lose_readiness
            self.assert_error(self.client.get('/api/auth/me',headers=headers()),503,'auth_unavailable')
            self.assertEqual(self.repository.reads,[DIGEST,DIGEST])

    def test_concurrent_profile_requests_keep_distinct_member_contexts(self):
        second_repo=FixtureRepository()
        second_context='44444444-4444-4444-8444-444444444444'
        second_digest=hashlib.sha256(OTHER_TOKEN.encode()).hexdigest()
        second_repo.rows={second_digest:snapshot(member_changes={'member_id':202,'auth_subject':ROTATED},
            session_changes={'member_id':202,'session_context_id':second_context},credential_hash=second_digest)}
        second=auth.VerifiedSessionResolver(second_repo,FixtureIssuer())
        def request(token,context):
            return Request({'type':'http','method':'GET','path':'/api/my/profile','scheme':'https',
                'headers':[(b'cookie',(auth.COOKIE+'='+token).encode()),(b'x-popcorn-auth-context',context.encode())],
                'query_string':b''})
        async def run_one(resolver,token,context,expected):
            async def consume(request):
                before=auth.require_member()['member_id']
                await asyncio.sleep(0)
                after=auth.require_member()['member_id']
                self.assertEqual((before,after),(expected,expected))
                return Response()
            response=await auth.create_member_middleware(resolver)(request(token,context),consume)
            self.assertEqual(response.status_code,200)
            self.assertIsNone(auth.current_member())
        async def both():
            await asyncio.gather(run_one(self.resolver,TOKEN,CONTEXT,101),
                                 run_one(second,OTHER_TOKEN,second_context,202))
        asyncio.run(both())
        self.assertIsNone(auth.current_member())

    def test_nonprofile_private_get_and_writes_never_receive_member_or_handler(self):
        for method,path in (('GET','/api/my/orders'),('POST','/api/my/orders'),('POST','/api/my/profile'),
                            ('GET','/api/my/profile/')):
            self.assert_error(self.client.request(method,path,headers=headers()),503,'auth_unavailable')
        self.assertEqual(self.queries,[])

    def test_guest_admin_and_accepted_commerce_exceptions_have_no_member_lookup(self):
        for path in ('/api/orders','/api/admin/probe','/shared/probe','/api/commerce/owner-context',
                     '/api/commerce/orders/fixture','/api/commerce/orders/fixture/support',
                     '/api/commerce/orders/fixture/fulfillment'):
            response=self.client.get(path,headers=headers())
            self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.repository.reads,[])
        self.assertIsNone(auth.current_member())

    def test_existing_commerce_exception_shape_and_methods_stay_exact(self):
        for path,method,expected in (('/api/commerce/owner-context','POST',False),
            ('/api/commerce/orders/x','GET',False),('/api/commerce/orders/x','POST',True),
            ('/api/commerce/orders/x/support/','POST',False),('/api/commerce/orders/x/support/deeper','GET',True),
            ('/api/commerce/orders/x/fulfillment/','GET',False),('/api/commerce/orders/x/fulfillment','POST',True)):
            self.assertIs(auth._needs_member_resolution(path,method),expected)

    def test_contextvar_rejects_dict_and_restores_previous_value_after_profile(self):
        before={'member_id':999,'verified':True}
        token=auth._current.set(before)
        try:
            self.direct_error(401,'unauthenticated',auth.require_member)
            async def next_handler(request):
                self.assertEqual(auth.require_member()['member_id'],101)
                return Response()
            request=Request({'type':'http','method':'GET','path':'/api/my/profile','scheme':'https',
                'headers':[(b'cookie',(auth.COOKIE+'='+TOKEN).encode()),(b'x-popcorn-auth-context',CONTEXT.encode())],
                'query_string':b''})
            response=asyncio.run(auth.create_member_middleware(self.resolver)(request,next_handler))
            self.assertEqual(response.status_code,200)
            self.assertIs(auth._current.get(),before)
        finally: auth._current.reset(token)

    def test_protected_downstream_failure_is_nostore_and_restores_context(self):
        async def fail(request): raise RuntimeError('private-token')
        request=Request({'type':'http','method':'GET','path':'/api/auth/fixture','scheme':'https',
                         'headers':[],'query_string':b''})
        response=asyncio.run(auth.create_member_middleware(self.resolver)(request,fail))
        self.assertEqual(response.status_code,503)
        self.assertEqual(json.loads(response.body),{'detail':{'code':'auth_unavailable'}})
        self.assert_nostore(response)
        self.assertIsNone(auth.current_member())

    def test_private304_and_cache_validators_are_not_emitted(self):
        async def cached(request): return Response(status_code=304,headers={'ETag':'private-tag'})
        request=Request({'type':'http','method':'GET','path':'/api/auth/fixture','scheme':'https',
                         'headers':[],'query_string':b''})
        response=asyncio.run(auth.create_member_middleware(self.resolver)(request,cached))
        self.assertEqual(response.status_code,503)
        self.assert_nostore(response)

    def test_public_failure_still_propagates_without_context_leak(self):
        async def fail(request): raise RuntimeError('public-fixture-failure')
        request=Request({'type':'http','method':'GET','path':'/api/orders','scheme':'https','headers':[],'query_string':b''})
        with self.assertRaisesRegex(RuntimeError,'public-fixture-failure'):
            asyncio.run(auth.create_member_middleware(self.resolver)(request,fail))
        self.assertIsNone(auth.current_member())

    def test_current_bigint_member_is_lossless_and_public_ids_are_strings(self):
        number=identity.MAX_BIGINT
        self.repository.rows[DIGEST]=snapshot(member_changes={'member_id':number,'principal_revision':number},
            session_changes={'member_id':number,'issued_auth_revision':number})
        response=self.client.get('/api/auth/me',headers=headers())
        self.assertEqual(response.json()['member']['member_id'],str(number))
        self.assertEqual(response.json()['auth_context']['principal_revision'],str(number))

    def test_import_has_no_db_engine_secret_network_or_live_repository_initialization(self):
        source=Path(auth.__file__).read_text(encoding='utf-8')
        tree=ast.parse(source)
        modules={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}
        modules|={a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}
        self.assertNotIn('db',modules)
        self.assertNotIn('sqlalchemy',modules)
        self.assertNotIn('api.db',sys.modules)
        self.assertNotIn('engine',vars(auth))
        self.assertFalse(auth.RUNTIME_RESOLVER.issuer.ready())
        self.assertFalse(auth.RUNTIME_RESOLVER.repository.schema_ready())
        self.assertNotIn('INSERT INTO',source)
        self.assertNotIn('UPDATE members',source)
        self.assertNotIn('load_dotenv',source)


if __name__ == '__main__': unittest.main()
