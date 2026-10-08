"""Real _PgTx.capture -> real plan_import, with temporary synthetic archive.
Success-only test pin overrides; no _binding/_original/hash/plan/CASE/session mocks.
Read results and imported DB snapshot wrappers are fake; native SQL is not run.
"""
from contextlib import contextmanager, ExitStack
from dataclasses import replace
import copy
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from api import admin_existing_pc_media as admin
from api.pc_existing_media_authority import ServerContext, SessionAuthority, ExplicitCaseReader, CasePins, FieldPin
from api.pc_existing_media_import import PgStore, _PgTx, ServerAuthority, Denied, digest
from tools import register_existing_pc_media as planner

OUTPUT=Path('D:/WORK/PopcornAI/outputs/existing-media-pg-capture-plan-code-mock-20261008')

class ReadConnection:
    def __init__(self,f):self.f=f;self.sql=[]
    def execute(self,sql,params=None):
        statement=str(sql).strip();self.sql.append(statement)
        if not statement.upper().startswith('SELECT '):raise AssertionError('read-only fake rejected write')
        if 'FROM products WHERE' in statement:self.row=dict(product_code=self.f.code,status='판매중')
        elif 'FROM product_explanations' in statement:self.row=copy.deepcopy(self.f.case_row)
        elif 'FROM admin_sessions' in statement:
            assert params==dict(s='synthetic-session',idle=480)
            self.row=self.f.session.copy()
        else:raise AssertionError('unsupported read: '+statement)
        return self
    def mappings(self):return self
    def first(self):return self.row

class Fixture:
    def __init__(self,folder,code):
        self.code=code;self.case_code=129552 if code==113835 else 129551
        self.color='black' if code==113835 else 'white'
        self.raw=b'\x89PNG\r\n\x1a\nsynthetic-plan-'+str(code).encode()
        self.original_sha=hashlib.sha256(self.raw).hexdigest()
        self.archive=Path(folder);(self.archive/'originals').mkdir()
        (self.archive/'originals'/f'P{code}.png').write_bytes(self.raw)
        self.item=dict(configuration_id=f'P{code}',original_sha256=self.original_sha,original_bytes=len(self.raw),
            generated_original=f'originals/P{code}.png',case_code=str(self.case_code),db_configuration_revision=1,qa_notes=['synthetic QA'])
        if code==113836:self.item.update(reused_from='P113838',reuse_exception='synthetic closed-panel exception')
        self.save_manifest()
        content=dict(model='DAVEN N1 MESH',color=self.color,side='closed_mesh_opaque',front='N1_MESH')
        self.case_row=dict(source_product_code=self.case_code,source_fingerprint='c'*64,content=content)
        pins=CasePins(self.case_code,'c'*64,digest(content),*[FieldPin((k,),v,'synthetic exact CASE field') for k,v in content.items()])
        self.case_reader=ExplicitCaseReader([pins])
        self.session=dict(operator_id=42,role='operator',status='활성',revoked=False,expired=False,idle=False)
        self.context=ServerContext('synthetic-session',42,'operator','same-origin')
        self.session_authority=SessionAuthority(lambda:self.context)
        self.conn=ReadConnection(self);self.grants=0;self.revoke_second=False;self.grant_mode='typed'
        self.authority=ServerAuthority(self.reuse,self.session_authority.operator_reader,self.session_authority.verify_registration)
        self.snapshot=dict(parts=[dict(slot='CASE',code=self.case_code)],notice='synthetic snapshot')
        self.visual=digest(self.snapshot)
        self.bound=dict(offer_id=f'P{code}',configuration_id='current-config',revision=7)
        self.current=dict(errors=[],snapshot=self.snapshot,visual_basis=self.visual,basis='b'*64)
    def save_manifest(self):
        self.manifest=json.dumps(dict(items=[self.item]),ensure_ascii=False,sort_keys=True).encode()
        self.manifest_sha=hashlib.sha256(self.manifest).hexdigest()
        (self.archive/'manifest.json').write_bytes(self.manifest)
    def reuse(self,subject,principal,connection):
        assert connection is self.conn
        self.grants+=1
        if self.revoke_second and self.grants==2:self.session['revoked']=True
        self.session_authority.verify_registration(subject,principal,connection)
        evidence=admin.FreshReuseEvidence(planner.Decision.ALLOW,admin.APPROVAL_RECORD,1,admin.APPROVAL_SHA,
            self.manifest_sha,f'P{self.code}',self.original_sha,self.case_code,False)
        if self.grant_mode!='typed':evidence=planner.Decision.UNKNOWN
        if not admin._matches_grant(evidence,subject):raise Denied('synthetic grant rejected')
        return planner.Decision.ALLOW
    def capture(self):
        # PgStore is real; engine is deliberately unusable and transaction isn't
        # invoked. _PgTx captures real source files/CASE/plan on read fake conn.
        store=PgStore(object(),self.archive,case_reader=self.case_reader)
        return _PgTx(self.conn,store,True).capture(self.code,self.authority,self.authority.principal())

class CapturePlanTests(unittest.TestCase):
    @contextmanager
    def fixture(self,code=113835,override=True):
        OUTPUT.mkdir(exist_ok=True)
        saved={name:sys.modules.get(name) for name in ('api.pc_configuration_copy','api.pc_media','api.auth')}
        expected_before=planner._expected;manifest_before=planner.MANIFEST_SHA;admin_before=admin.MANIFEST_SHA
        try:
            with TemporaryDirectory(dir=OUTPUT,prefix='synthetic-') as folder:
                f=Fixture(folder,code)
                def sold(connection,product_code):
                    self.assertIs(connection,f.conn);self.assertEqual(product_code,code);return f.bound.copy()
                def snapshot(connection,identity,lock=False):
                    self.assertIs(connection,f.conn);self.assertEqual(identity,'current-config');self.assertIs(lock,False)
                    return copy.deepcopy(f.current)
                with ExitStack() as stack:
                    stack.enter_context(patch.dict(sys.modules,{'api.pc_configuration_copy':SimpleNamespace(read_sold_offer_configuration=sold),
                        'api.pc_media':SimpleNamespace(snapshot=snapshot),'api.auth':SimpleNamespace(IDLE_MINUTES=480)}))
                    if override:
                        # Only expected fixture SHA is replaced. Actual production
                        # CASE/color mapping is obtained from the untouched reader.
                        def fixture_expected(value):
                            original=expected_before(value)
                            return (f.original_sha,*original[1:]) if value==code else original
                        stack.enter_context(patch.object(planner,'_expected',fixture_expected))
                        stack.enter_context(patch.object(planner,'MANIFEST_SHA',f.manifest_sha))
                        stack.enter_context(patch.object(admin,'MANIFEST_SHA',f.manifest_sha))
                    yield f
        finally:
            self.assertIs(planner._expected,expected_before)
            self.assertEqual(planner.MANIFEST_SHA,manifest_before);self.assertEqual(admin.MANIFEST_SHA,admin_before)
            for name,value in saved.items():self.assertIs(sys.modules.get(name),value)
    def test_success_both_codes_real_capture_returns_actual_plan_provenance(self):
        for code in (113835,113836):
            with self.subTest(code=code),self.fixture(code) as f:
                capture=f.capture();self.assertIs(type(capture.plan),planner.ImportPlan)
                self.assertEqual(capture.plan.provenance.original_sha256,f.original_sha)
                self.assertEqual(capture.plan.provenance.original_revision,1)
                self.assertEqual(capture.plan.binding.revision,7)
                self.assertEqual(capture.plan.binding.case.product_code,f.case_code)
                self.assertIsNone(capture.plan.provenance.generation_actor)
                self.assertEqual(f.grants,2)
                self.assertEqual(sum('FROM admin_sessions' in s for s in f.conn.sql),2)
                if code==113836:self.assertEqual(capture.plan.provenance.reused_from,'P113838')
    def test_unmodified_production_pins_reject_synthetic_source_before_grant(self):
        with self.fixture(override=False) as f:
            with self.assertRaises(Denied):f.capture()
            self.assertEqual(f.grants,0)
    def test_changed_original_bytes_rejected_by_real_sha_check(self):
        with self.fixture() as f:
            (f.archive/'originals/P113835.png').write_bytes(f.raw+b'changed')
            with self.assertRaises(Denied):f.capture()
            self.assertEqual(f.grants,0)
    def test_changed_manifest_bytes_rejected_by_real_sha_check(self):
        with self.fixture() as f:
            (f.archive/'manifest.json').write_bytes(f.manifest+b' ')
            with self.assertRaises(Denied):f.capture()
            self.assertEqual(f.grants,0)
    def test_manifest_internal_bytes_path_CASE_revision_checked_after_valid_SHA(self):
        changes={'original_bytes':1,'generated_original':'originals/wrong.png','case_code':'129551','db_configuration_revision':2}
        for key,value in changes.items():
            with self.subTest(field=key),self.fixture() as f:
                f.item[key]=value;f.save_manifest()
                # Re-pin only the changed synthetic manifest to reach semantic
                # validation rather than merely fail the enclosing SHA check.
                with patch.object(planner,'MANIFEST_SHA',f.manifest_sha),patch.object(admin,'MANIFEST_SHA',f.manifest_sha):
                    with self.assertRaises(Denied):f.capture()
                self.assertEqual(f.grants,0)
    def test_white_reuse_exception_missing_rejected_by_actual_original_validation(self):
        with self.fixture(113836) as f:
            f.item.pop('reuse_exception');f.save_manifest()
            with patch.object(planner,'MANIFEST_SHA',f.manifest_sha),patch.object(admin,'MANIFEST_SHA',f.manifest_sha):
                with self.assertRaises(Denied):f.capture()
            self.assertEqual(f.grants,0)
    def test_actual_CASE_adapter_rejects_changed_current_content(self):
        with self.fixture() as f:
            f.case_row['content']['color']='white'
            with self.assertRaises(Denied):f.capture()
            self.assertEqual(f.grants,0)
    def test_grant_unknown_rejected_inside_actual_planner(self):
        with self.fixture() as f:
            f.grant_mode='unknown'
            with self.assertRaises(Denied):f.capture()
            self.assertEqual(f.grants,1)
    def test_second_planner_reuse_call_rechecks_actual_session_adapter(self):
        with self.fixture() as f:
            f.revoke_second=True
            with self.assertRaises(Denied):f.capture()
            self.assertEqual(f.grants,2)
            self.assertEqual(sum('FROM admin_sessions' in s for s in f.conn.sql),2)
    def test_readonly_fake_explicitly_refuses_write(self):
        with self.fixture() as f:
            with self.assertRaisesRegex(AssertionError,'read-only fake rejected write'):
                f.conn.execute('UPDATE pc_media_jobs SET selected=true',{})

if __name__=='__main__':unittest.main(failfast=True)
