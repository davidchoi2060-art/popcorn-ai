"""New safe display projection only; no DB/network or previous suites."""
from contextlib import contextmanager
from datetime import datetime, timezone
import importlib
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

with patch.dict(sys.modules,{'api.db':SimpleNamespace(engine=None),
    'api.admin_pc_builder':SimpleNamespace(permission=None),
    'api.pc_configuration_review':SimpleNamespace(load_review=None),
    'api.pc_configuration_copy':SimpleNamespace(digest=None),
    'api.product_images':SimpleNamespace(MEDIA_BUCKET='mock',read_image=None)}):
    m=importlib.import_module('api.pc_media')

class Rows:
    def __init__(self,rows):self.rows=rows;self.calls=[]
    def execute(self,sql,params):self.calls.append((str(sql),params));return self
    def mappings(self):return self.rows

class DisplayTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime.now(timezone.utc)
        self.row=dict(job_id='safe-id',status='ready',phase='complete',visual_basis='a'*64,
            model=None,selected=False,created_at=self.now,updated_at=self.now,staged_available=False,
            origin_kind='existing_import',actor='private-server-actor',error='secret exception',
            import_provenance={'original_ref':'/private/server/path'},bucket='secret-bucket',key='private-key')
    def test_exact_origin_values_only(self):
        for raw,expected in [('generated','generated'),('existing_import','existing_import'),
            ('unknown',None),(None,None),('Generated',None),('',None)]:
            self.assertEqual(m._display_job({**self.row,'origin_kind':raw})['origin_kind'],expected)
    def test_missing_origin_not_inferred_from_model_date_or_selected(self):
        row={**self.row,'model':'recorded-model','selected':True};row.pop('origin_kind')
        out=m._display_job(row);self.assertIsNone(out['origin_kind']);self.assertEqual(out['model'],'recorded-model')
    def test_import_model_never_falls_back_to_generation_setting(self):
        for model in (None,'untrusted-model'):
            self.assertIsNone(m._display_job({**self.row,'model':model})['model'])
    def test_generated_null_model_stays_null_and_recorded_model_is_preserved(self):
        for value in (None,'recorded-generated-model'):
            self.assertEqual(m._display_job({**self.row,'origin_kind':'generated','model':value})['model'],value)
    def test_unverified_metadata_stays_null_and_selection_is_separate(self):
        out=m._display_job({**self.row,'selected':True})
        for key in ('registration_actor_label','original_created_at','original_creator_label',
                    'reuse_approval_status','publication_status'):self.assertIsNone(out[key])
        self.assertTrue(out['selected']);self.assertEqual(out['created_at'],self.now)
    def test_no_actor_provenance_object_or_exception_source_leak(self):
        out=m._display_job(self.row)
        for key in ('actor','import_provenance','bucket','key','original_ref'):self.assertNotIn(key,out)
        self.assertNotIn('secret',str(out));self.assertNotIn('/private',str(out));self.assertIsNone(out['error'])
    def test_failed_error_is_safe_origin_phase_message(self):
        cases=[('generated','generation','이미지 생성 실패'),('generated','storage','생성 이미지 저장 실패'),
            ('existing_import','import_failed','원본 등록 실패'),('existing_import','storage','원본 등록 처리 실패 · 단계 확인 필요'),
            (None,'storage','처리 실패')]
        for origin,phase,message in cases:
            out=m._display_job({**self.row,'status':'failed','origin_kind':origin,'phase':phase})
            self.assertEqual(out['error'],message)
    def test_jobs_query_safe_legacy_projection_bound_id_and_limit_without_dml(self):
        conn=Rows([self.row]);out=m.jobs(conn,'specific-config')
        sql,params=conn.calls[0]
        self.assertIn("to_jsonb(j)->>'origin_kind' AS origin_kind",sql)
        self.assertIn('WHERE j.configuration_id=:id',sql);self.assertIn('LIMIT 20',sql)
        self.assertEqual(params,dict(id='specific-config'));self.assertTrue(sql.startswith('SELECT '))
        self.assertEqual(out[0]['origin_kind'],'existing_import');self.assertNotIn('actor',out[0])
    def test_state_keeps_job_model_null_and_separate_config_model(self):
        conn=Rows([self.row])
        @contextmanager
        def connect():yield conn
        snap=dict(visual_basis='a'*64,snapshot={'parts':[]},errors=[])
        with patch.object(m,'engine',SimpleNamespace(connect=connect)),patch.object(m,'snapshot',return_value=snap),patch.object(m,'cloud_ready',return_value=False):
            out=m.state('specific-config')
        self.assertIsNone(out['jobs'][0]['model']);self.assertEqual(out['model'],m.MODEL)
        self.assertTrue(out['jobs'][0]['current']);self.assertFalse(out['jobs'][0]['interrupted'])
        self.assertEqual(out['jobs'][0]['image_url'],'/api/admin/pc-media/specific-config/images/safe-id')
    def test_projection_does_not_mutate_source(self):
        before=self.row.copy();m._display_job(self.row);self.assertEqual(self.row,before)

if __name__=='__main__':unittest.main()
