"""New HTTP contract/factory tests. No native DB/GCS/provider or old suites."""
from dataclasses import replace
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from api import admin_existing_pc_media as route
from api.pc_existing_media_import import Denied, Outcome, Principal
from api.pc_existing_media_authority import ServerContext
from tools.register_existing_pc_media import (Decision, ReuseSubject, OriginalProvenance, ImportBinding, CaseEvidence, MANIFEST_SHA)


class RouteTests(unittest.TestCase):
    def setUp(self):
        app=FastAPI();app.include_router(route.router)
        self.context=ServerContext('private-server-session',42,'operator','same-origin')
        app.dependency_overrides[route.server_context]=lambda:self.context
        app.dependency_overrides[route.server_wiring]=lambda:route.ServerWiring()
        self.app=app;self.client=TestClient(app)
        self.expected=dict(revision=2,visual_basis='a'*64,review_basis='b'*64,
            original_sha256='c'*64,manifest_sha256='d'*64)
        self.request_id='fca842b1-8ae2-4c0c-97d1-23cf713c0bb4'
        self.calls=[]
        self.fake=SimpleNamespace(dry_run=lambda *args:self.result('dry_run',args),
            apply=lambda *args:self.result('apply',args))
    def result(self,mode,args):
        self.calls.append((mode,args));return Outcome('dry_run' if mode=='dry_run' else 'registered')
    def post(self,body=None,code='113835'):
        return self.client.post('/api/admin/pc-media/'+code+'/existing-import',
            json=body if body is not None else dict(expected=self.expected))
    def test_default_unwired_denies_before_db_or_runtime(self):
        with patch.dict(sys.modules,{'api.db':None}):
            r=self.post()
        self.assertEqual(r.status_code,403);self.assertNotIn('private-server-session',r.text)
    def test_default_dry_run_and_both_exact_skus(self):
        with patch.object(route,'build_runtime',return_value=self.fake) as factory:
            for code in ('113835','113836'):
                self.assertEqual(self.post(code=code).status_code,200)
        self.assertEqual([x[0] for x in self.calls],['dry_run','dry_run'])
        self.assertEqual([x[1][0] for x in self.calls],[113835,113836])
        self.assertEqual(factory.call_args[0][0],self.context)
    def test_alternate_and_other_path_forms_denied(self):
        with patch.object(route,'build_runtime') as factory:
            for code in ('0113835','P113835','+113835','113835.0','true','113837'):
                with self.subTest(code=code):self.assertEqual(self.post(code=code).status_code,422)
        factory.assert_not_called()
    def test_apply_requires_request_id(self):
        self.assertEqual(self.post(dict(mode='apply',expected=self.expected)).status_code,422)
    def test_apply_disabled_before_factory(self):
        with patch.object(route,'build_runtime') as factory:
            self.assertEqual(self.post(dict(mode='apply',request_id=self.request_id,expected=self.expected)).status_code,403)
        factory.assert_not_called()
    def test_explicit_mock_apply_and_same_request_preserved(self):
        self.app.dependency_overrides[route.server_wiring]=lambda:route.ServerWiring(apply_enabled=True)
        with patch.object(route,'build_runtime',return_value=self.fake):
            for _ in range(2):self.assertEqual(self.post(dict(mode='apply',request_id=self.request_id,expected=self.expected)).status_code,200)
        self.assertEqual([c[1][2] for c in self.calls],[self.request_id]*2)
    def test_forbidden_body_inputs(self):
        with patch.object(route,'build_runtime') as factory:
            for key in ('actor','role','session','session_id','permission','case','key','factory','apply_enabled'):
                self.assertEqual(self.post(dict(expected=self.expected,**{key:'injected'})).status_code,422)
        factory.assert_not_called()
    def test_expected_extra_and_coercion_rejected(self):
        for e in ({**self.expected,'actor':42},{**self.expected,'revision':True},
                  {**self.expected,'revision':'2'},{**self.expected,'visual_basis':'unknown'}):
            self.assertEqual(self.post(dict(expected=e)).status_code,422)
    def test_mode_and_uuid_strict(self):
        for body in (dict(mode=True),dict(mode='generate'),dict(request_id=42),
            dict(request_id=self.request_id.upper()),dict(request_id='bad')):
            self.assertEqual(self.post(dict(expected=self.expected,**body)).status_code,422)
    def test_one_post_route_no_background_endpoint(self):
        self.assertEqual(len(route.router.routes),1)
        self.assertEqual(route.router.routes[0].methods,{'POST'})
    def test_context_extracted_from_existing_server_permission_cookie(self):
        request=Request(dict(type='http',method='POST',path='/',headers=[
            (b'cookie',b'popcorn_admin_session=server-token'),(b'sec-fetch-site',b'same-origin')]))
        seen=[]
        with patch.dict(sys.modules,{'api.auth':SimpleNamespace(COOKIE='popcorn_admin_session'),
            'api.admin_pc_builder':SimpleNamespace(permission=lambda req:seen.append(req) or dict(operator_id=42,role='owner'))}):
            value=route.server_context(request)
        self.assertEqual(value,ServerContext('server-token',42,'owner','same-origin'))
        self.assertEqual(seen,[request])
    def test_missing_cookie_not_replaced_with_seed(self):
        request=Request(dict(type='http',method='POST',path='/',headers=[]))
        with patch.dict(sys.modules,{'api.auth':SimpleNamespace(COOKIE='popcorn_admin_session'),
            'api.admin_pc_builder':SimpleNamespace(permission=lambda _:dict(operator_id=42,role='operator'))}):
            context=route.server_context(request)
        with self.assertRaises(Denied):route.build_runtime(context,route.ServerWiring(lambda *a:Decision.UNKNOWN,lambda *a:None))


class FactoryTests(unittest.TestCase):
    def setUp(self):
        self.context=ServerContext('s',42,'operator','same-origin')
        self.engine=object();self.seen=[];self.decision=Decision.UNKNOWN
        self.wiring=route.ServerWiring(self.grant,self.case)
        self.subject=ReuseSubject(OriginalProvenance('P113835','originals/P113835.png','c'*64,
            MANIFEST_SHA,1,('qa',),None,None,None),ImportBinding(113835,'P113835','config',2,
            'a'*64,CaseEvidence(129552,'DAVEN N1 MESH','black','closed_mesh_opaque','N1_MESH','test-ref')))
        self.principal=Principal(42,'operator')
        self.allowed=route.FreshReuseEvidence(Decision.ALLOW,route.APPROVAL_RECORD,1,
            route.APPROVAL_SHA,MANIFEST_SHA,'P113835','c'*64,129552,False)
        self.row=dict(operator_id=42,role='operator',status='활성',revoked=False,expired=False,idle=False)
        self.conn=SimpleNamespace(execute=self.execute,mappings=lambda:self.conn,first=lambda:self.row)
        self.patcher=patch.dict(sys.modules,{'api.db':SimpleNamespace(engine=self.engine),
            'api.auth':SimpleNamespace(IDLE_MINUTES=480)})
        self.patcher.start();self.addCleanup(self.patcher.stop)
    def execute(self,sql,params):
        self.seen.append(('session',self.conn,str(sql),params));return self.conn
    def grant(self,subject,principal,connection):
        self.seen.append(('grant',connection));return self.decision
    def case(self,*args):return None
    def test_real_runtime_composition_with_existing_engine_archive_and_lazy_cloud(self):
        runtime=route.build_runtime(self.context,self.wiring)
        self.assertIs(runtime.store.engine,self.engine)
        self.assertIs(runtime.store.case_reader,self.wiring.case_reader)
        self.assertEqual(runtime.store.archive,route.ROOT.parents[1]/'outputs'/'assembled-pc-images-20260929')
        self.assertFalse(self.seen)
    def test_no_connection_no_grant(self):
        runtime=route.build_runtime(self.context,self.wiring)
        with self.assertRaises(Denied):runtime.authority.verify_reuse(self.subject,self.principal,None)
        self.assertFalse(self.seen)
    def test_reuse_read_callback_rechecks_session_on_same_connection_every_time(self):
        runtime=route.build_runtime(self.context,self.wiring);self.decision=self.allowed
        for _ in range(2):runtime.authority.verify_reuse(self.subject,self.principal,self.conn)
        self.assertEqual([x[0] for x in self.seen],['session','grant','session','grant'])
        self.assertTrue(all(x[1] is self.conn for x in self.seen))
    def test_unknown_withdrawn_bool_or_dict_grant_denied(self):
        runtime=route.build_runtime(self.context,self.wiring)
        for decision in (Decision.UNKNOWN,Decision.WITHDRAWN,Decision.DENY,True,{'allow':True},None):
            self.decision=decision
            with self.assertRaises(Denied):runtime.authority.verify_reuse(self.subject,self.principal,self.conn)
    def test_session_revoked_before_grant_blocks_ready_recheck(self):
        runtime=route.build_runtime(self.context,self.wiring);self.decision=self.allowed
        runtime.authority.verify_reuse(self.subject,self.principal,self.conn)
        self.seen=[];self.row['revoked']=True
        with self.assertRaises(Denied):runtime.authority.verify_reuse(self.subject,self.principal,self.conn)
        self.assertEqual([x[0] for x in self.seen],['session'])
    def test_record_version_hash_scope_and_withdrawal_must_match(self):
        runtime=route.build_runtime(self.context,self.wiring)
        for field,value in [('record_sha256','0'*64),('record_version',2),
            ('record_version',True),('record_path','other-record'),('manifest_sha256','0'*64),
            ('source_sku','P113836'),('original_sha256','0'*64),('case_product_code',129551),
            ('withdrawn',None),('withdrawn',True)]:
            with self.subTest(field=field,value=value):
                self.decision=replace(self.allowed,**{field:value})
                with self.assertRaises(Denied):runtime.authority.verify_reuse(self.subject,self.principal,self.conn)
    def test_bare_typed_allow_is_not_fresh_evidence(self):
        runtime=route.build_runtime(self.context,self.wiring);self.decision=Decision.ALLOW
        with self.assertRaises(Denied):runtime.authority.verify_reuse(self.subject,self.principal,self.conn)
    def test_cross_site_and_viewer_denied_before_setup(self):
        for c in (replace(self.context,sec_fetch_site='cross-site'),replace(self.context,role='viewer')):
            with self.assertRaises(Denied):route.build_runtime(c,self.wiring)
    def test_missing_providers_not_granted_by_apply_flag(self):
        with self.assertRaises(Denied):route.build_runtime(self.context,route.ServerWiring(apply_enabled=True))


if __name__=='__main__':unittest.main()
