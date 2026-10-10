"""Cross-module admin flow only: real route/factory/refresh/runtime/session/CASE.
SQL row results, storage, object receipts and source callbacks are synthetic.
No old suite imports, actual PgStore execution or production grant selection.
"""
from contextlib import contextmanager
from dataclasses import replace
import copy
import hashlib
import json
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from api import admin_existing_pc_media as admin
from api.pc_existing_media_authority import ServerContext, ExplicitCaseReader, CasePins, FieldPin
from api.pc_existing_media_import import Capture, CommitUnknown, ObjectReceipt, canonical, digest
from api.pc_existing_media_refresh import Scope, SourceConfirmation, Stage, scope_hash
from tools.register_existing_pc_media import Decision, ImportBinding, OriginalProvenance, ImportPlan, ReuseSubject, MANIFEST_SHA, BUCKET

RAW=b'\x89PNG\r\n\x1a\nwhole-flow-synthetic'
REQUEST='b7c26ac6-38d7-4cbb-97ea-a0f8945374de'
OTHER='11111111-1111-4111-8111-111111111111'

class Connection:
    def __init__(self,flow):self.flow=flow;self.closed=False
    def in_transaction(self):return not self.closed
    def execute(self,sql,params):
        # Only actual SessionAuthority SELECT is supported. These are mock rows,
        # not evidence that native SQL/schema/DB time/auth races passed.
        assert 'FROM admin_sessions' in str(sql)
        assert params==dict(s='synthetic-session',idle=480)
        self.flow.log.append(('session',self));return self
    def mappings(self):return self
    def first(self):return self.flow.session.copy()

class Store:
    def __init__(self,flow):self.flow=flow
    def original_bytes(self,code):return RAW
    @contextmanager
    def transaction(self,readonly=False):
        f=self.flow;conn=Connection(f);f.connections.append(conn)
        rows=copy.deepcopy(f.rows)
        try:
            yield Transaction(f,conn,rows,readonly)
            if not readonly:
                f.commits+=1;f.rows=rows
                if f.commits==2 and f.final_unknown:raise CommitUnknown()
        finally:conn.closed=True

class Transaction:
    def __init__(self,f,conn,rows,readonly):self.f,self.conn,self.rows,self.readonly=f,conn,rows,readonly
    def capture(self,code,authority,principal):
        # Real CASE adapter validates current synthetic row on every capture.
        case=self.f.case_reader(self.conn,copy.deepcopy(self.f.case_row))
        binding=ImportBinding(code,'P113835','trusted-config',2,self.f.visual,case)
        plan=ImportPlan(self.f.original,binding)
        authority.verify_reuse(ReuseSubject(plan.provenance,plan.binding),principal,self.conn)
        return Capture(plan,'b'*64,canonical(self.f.snapshot))
    def get(self,request,lock=False):
        row=copy.deepcopy(self.rows.get(request))
        if row and self.readonly and self.f.mismatch_on_reconcile:row['job_id']=OTHER
        return row
    def reserve(self,wanted):self.rows.setdefault(wanted['request_id'],copy.deepcopy(wanted));return self.get(wanted['request_id'])
    def finalize(self,request,job,asset):self.rows[request].update(status='ready',phase='complete',asset=asset)

class Objects:
    def __init__(self,f):self.f=f
    def receipt(self,job,raw):return ObjectReceipt(BUCKET,f'pc-configurations/{job}/representative.png',hashlib.sha256(raw).hexdigest(),len(raw),'1')
    def create_or_verify(self,job,raw):
        assert self.f.runtime.store.active() is False
        self.f.log.append(('object-write',job));self.f.after_object();return self.receipt(job,raw)
    def verify_existing(self,job,raw,generation):
        assert self.f.runtime.store.active() is False and generation=='1'
        self.f.log.append(('object-read',job));return self.receipt(job,raw)

class AdminFlow(unittest.TestCase):
    def setUp(self):
        self.log=[];self.rows={};self.connections=[];self.commits=0;self.final_unknown=False;self.mismatch_on_reconcile=False
        self.after_object=lambda:None;self.source_allow=True;self.coverage=True;self.local_allow=True;self.grant_mode='typed'
        self.session=dict(operator_id=42,role='operator',status='활성',revoked=False,expired=False,idle=False)
        self.context=ServerContext('synthetic-session',42,'operator','same-origin')
        self.snapshot=dict(parts=[],notice='synthetic-notice');self.visual=digest(self.snapshot)
        self.original=OriginalProvenance('P113835','originals/P113835.png',hashlib.sha256(RAW).hexdigest(),MANIFEST_SHA,1,('synthetic QA',),None,None,None)
        content=dict(model='DAVEN N1 MESH',color='black',side='closed_mesh_opaque',front='N1_MESH')
        self.case_row=dict(source_product_code=129552,source_fingerprint='c'*64,content=content)
        fields=[FieldPin((key,),value,'synthetic explicit source') for key,value in content.items()]
        self.case_reader=ExplicitCaseReader([CasePins(129552,'c'*64,digest(content),*fields)])
        record_sha=hashlib.sha256(b'synthetic flow record').hexdigest()
        self.record=dict(path=admin.APPROVAL_RECORD,body='synthetic flow record',sha=record_sha,version=1,updated='2026-10-08T01:00:00Z')
        self.scope=Scope('P113835','P113835','trusted-config',2,self.visual,'b'*64,self.original.original_sha256,MANIFEST_SHA,129552,admin.APPROVAL_RECORD,record_sha,1)
        self.wiring=admin.ServerWiring(self.grant,self.case_reader,True,scope_reader=self.scope_reader,
            record_reader=self.record_reader,server_confirmer=self.confirm,local_verifier=self.local)
        self.store=Store(self);self.objects=Objects(self)
        for p in (patch.object(admin,'APPROVAL_SHA',record_sha),patch.dict(sys.modules,{'api.db':SimpleNamespace(engine=object()),'api.auth':SimpleNamespace(IDLE_MINUTES=480)}),
            patch('api.pc_existing_media_import.PgStore',return_value=self.store),patch('api.pc_existing_media_import.GcsObjects',return_value=self.objects)):
            p.start();self.addCleanup(p.stop)
        original_factory=admin.build_runtime
        def observe(*args,**kwargs):
            self.runtime=original_factory(*args,**kwargs);return self.runtime
        p=patch.object(admin,'build_runtime',side_effect=observe);p.start();self.addCleanup(p.stop)
        app=FastAPI();app.include_router(admin.router)
        app.dependency_overrides[admin.server_context]=lambda:self.context
        app.dependency_overrides[admin.server_wiring]=lambda:self.wiring
        self.client=TestClient(app)
        self.expected=dict(revision=2,visual_basis=self.visual,review_basis='b'*64,original_sha256=self.original.original_sha256,manifest_sha256=MANIFEST_SHA)
    def scope_reader(self,context,code):
        self.assertIs(context,self.context);self.assertEqual(code,113835);return self.scope
    def record_reader(self,path):
        self.assertIs(self.runtime.store.active(),False)
        self.log.append(('source',path));return self.record.copy()
    def confirm(self,record,scope,stage,number):
        self.assertIs(self.runtime.store.active(),False);self.log.append(('confirm',stage,number))
        return SourceConfirmation(stage,number,record.sha,scope_hash(scope),Decision.ALLOW if self.source_allow else Decision.UNKNOWN,
            'synthetic source',True,self.coverage,False)
    def local(self,scope,envelope,conn):
        self.runtime.store.verify_connection(conn)
        # Actual CASE validation forms part of current same-conn local evidence.
        case=self.case_reader(conn,copy.deepcopy(self.case_row))
        self.assertEqual(case.product_code,scope.case_product_code)
        self.log.append(('local',conn));return Decision.ALLOW if self.local_allow else Decision.UNKNOWN
    def grant(self,subject,principal,conn):
        self.runtime.store.verify_connection(conn);self.log.append(('grant',conn))
        if self.grant_mode!='typed':return Decision.UNKNOWN
        return admin.FreshReuseEvidence(Decision.ALLOW,admin.APPROVAL_RECORD,1,self.scope.record_sha256,
            MANIFEST_SHA,subject.original.configuration_id,subject.original.original_sha256,subject.current.case.product_code,False)
    def request(self,expected=None):
        response=self.client.post('/api/admin/pc-media/113835/existing-import',json=dict(mode='apply',request_id=REQUEST,expected=expected or self.expected))
        self.assertEqual(response.status_code,200);return response.json()
    def stages(self):return [x[1] for x in self.log if x[0]=='confirm']
    def test_whole_route_case_session_refresh_final_provenance_then_ready_retry(self):
        first=self.request();self.assertEqual(first['state'],'registered')
        old=self.runtime;row=self.rows[REQUEST]
        self.assertFalse(row['selected']);self.assertEqual(row['origin_kind'],'existing_import');self.assertIsNone(row['model'])
        p=row['import_provenance'];self.assertEqual(row['actor'],'operator:42')
        self.assertIsNone(p['original']['generation_actor']);self.assertIsNone(p['original']['generation_model']);self.assertIsNone(p['original']['generation_time'])
        self.assertEqual(p['current_binding']['case_product_code'],129552)
        self.assertIn('synthetic explicit source',p['current_binding']['case_evidence']['source_reference'])
        self.log=[];second=self.request()
        self.assertEqual(second['state'],'registered');self.assertEqual(second['job_id'],first['job_id'])
        self.assertIsNot(self.runtime.refresh.contract,old.refresh.contract)
        self.assertEqual(len([x for x in self.log if x[0]=='object-read']),1)
        self.assertFalse([x for x in self.log if x[0]=='object-write'])
        self.assertEqual(self.stages(),[Stage.BEFORE_RESERVE,Stage.BEFORE_FINALIZE]);self.assertFalse(self.rows[REQUEST]['selected'])
    def test_http_expected_mismatch_never_replaces_server_scope_or_reserves(self):
        changed=dict(self.expected,review_basis='d'*64)
        self.assertEqual(self.request(changed)['state'],'stale')
        self.assertEqual(self.runtime.refresh.scope.review_basis,'b'*64)
        self.assertFalse(self.rows);self.assertFalse(self.connections);self.assertFalse(self.stages())
    def test_valid_refresh_and_local_case_cannot_replace_missing_actual_grant(self):
        self.grant_mode='missing'
        self.assertEqual(self.request()['state'],'denied');self.assertFalse(self.rows)
        self.assertTrue([x for x in self.log if x[0]=='local'])
        self.assertTrue([x for x in self.log if x[0]=='session'])
    def test_session_revoked_after_reservation_blocks_final_ack(self):
        self.after_object=lambda:self.session.update(revoked=True)
        self.assertEqual(self.request()['state'],'denied')
        self.assertEqual(self.rows[REQUEST]['status'],'running');self.assertFalse(self.runtime.refresh.contract._finished)
        self.assertEqual(self.stages(),[Stage.BEFORE_RESERVE,Stage.BEFORE_FINALIZE])
    def test_CASE_changed_after_reservation_is_denied_by_real_case_adapter(self):
        self.after_object=lambda:self.case_row['content'].update(color='white')
        self.assertEqual(self.request()['state'],'denied')
        self.assertEqual(self.rows[REQUEST]['status'],'running');self.assertFalse(self.runtime.refresh.contract._finished)
    def test_fresh_coverage_withdrawal_unknown_after_reservation_is_not_SHA_allow(self):
        self.after_object=lambda:setattr(self,'coverage',None)
        self.assertEqual(self.request()['state'],'denied')
        self.assertEqual(self.rows[REQUEST]['status'],'running');self.assertFalse(self.runtime.refresh.contract._finished)
    def test_final_unknown_whole_route_new_round_sameconn_exact_job_ack(self):
        self.final_unknown=True
        self.assertEqual(self.request()['state'],'registered')
        self.assertEqual(self.stages(),[Stage.BEFORE_RESERVE,Stage.BEFORE_FINALIZE,Stage.READ_ONLY])
        self.assertEqual(len(set(self.connections)),3)
        locals_=[x[1] for x in self.log if x[0]=='local'];self.assertEqual(locals_,self.connections)
        self.assertTrue(self.runtime.refresh.contract._finished)
    def test_final_unknown_different_valid_job_whole_route_cannot_ack(self):
        self.final_unknown=True;self.mismatch_on_reconcile=True
        self.assertEqual(self.request()['state'],'conflict')
        self.assertFalse(self.runtime.refresh.contract._finished)
        self.assertEqual(self.stages()[-1],Stage.READ_ONLY)

if __name__=='__main__':unittest.main()
