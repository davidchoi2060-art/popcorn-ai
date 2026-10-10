"""New worker-origin tests only. Native dependencies, all IO ports mocked."""
import copy
from contextlib import contextmanager
import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import UUID

# Prevent production DB/auth/contract imports from constructing live resources.
with patch.dict(sys.modules,{
    'api.db':SimpleNamespace(engine=None),
    'api.admin_pc_builder':SimpleNamespace(permission=lambda request:None),
    'api.pc_configuration_review':SimpleNamespace(load_review=None),
    'api.pc_configuration_copy':SimpleNamespace(digest=None),
    'api.product_images':SimpleNamespace(MEDIA_BUCKET='test-bucket',read_image=None),
}):
    m=importlib.import_module('api.pc_media')


JOB='fa763c5e-2896-46e5-bbab-5afeb8030079'

class Engine:
    def __init__(self,row):
        self.row=copy.deepcopy(row);self.reads=[];self.writes=[];self.transactions=0;self.error=None
    @contextmanager
    def connect(self):yield self
    @contextmanager
    def begin(self):
        self.transactions+=1
        yield self
    def execute(self,sql,params):
        sql=str(sql)
        if sql.startswith('SELECT '):
            self.reads.append((sql,params))
            if self.error:raise self.error
        else:
            self.writes.append((sql,params))
        return self
    def mappings(self):return self
    def one(self):
        if self.row is None:raise LookupError('missing job')
        return copy.deepcopy(self.row)
    def first(self):return copy.deepcopy(self.row)


class WorkerGuardTests(unittest.TestCase):
    def setUp(self):
        self.row=dict(job_id=JOB,configuration_id='P113835',origin_kind='generated',
            status='running',phase='generation',snapshot={'parts':[]},model='generated-model',staged_png=None)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.spool=Path(self.tmp.name)
        self.engine=Engine(self.row)
        self.generate=Mock(return_value=b'generated-png');self.upload=Mock(return_value={'key':'mock-key'})
        for target,value in [('engine',self.engine),('SPOOL',self.spool),
                             ('generate_image',self.generate),('upload',self.upload)]:
            p=patch.object(m,target,value);p.start();self.addCleanup(p.stop)
    def blocked(self,origin,storage_only=False,missing=False):
        self.engine.row={**self.row,'origin_kind':origin,'model':None,'snapshot':None}
        if missing:self.engine.row.pop('origin_kind')
        before=copy.deepcopy(self.engine.row)
        with patch.object(m.Path,'read_bytes',side_effect=AssertionError('no source read')):
            m.work(JOB,storage_only)
        self.generate.assert_not_called();self.upload.assert_not_called()
        self.assertEqual(self.engine.writes,[]);self.assertEqual(self.engine.transactions,0)
        self.assertEqual(self.engine.row,before)
    def test_existing_import_generation_cannot_call_provider_or_overwrite_failed(self):
        self.blocked('existing_import')
    def test_existing_import_storage_only_cannot_read_upload_or_overwrite_failed(self):
        self.blocked('existing_import',True)
    def test_unknown_null_boolean_and_empty_origins_fail_closed(self):
        for origin in ('unknown','Generated','',None,True,False):
            for storage in (False,True):
                with self.subTest(origin=origin,storage=storage):self.blocked(origin,storage)
    def test_missing_origin_is_not_legacy_generated(self):
        self.blocked(None,missing=True);self.blocked(None,True,missing=True)
    def test_generated_success_preserves_provider_model_and_ready_updates(self):
        m.work(JOB)
        self.generate.assert_called_once_with(self.row['snapshot'],'generated-model')
        self.upload.assert_called_once_with(self.row,b'generated-png')
        self.assertEqual(len(self.engine.writes),3)
        self.assertIn("SET staged_png=:raw,phase='storage'",self.engine.writes[0][0])
        self.assertIn("SET status='ready',phase='complete'",self.engine.writes[-1][0])
        self.assertEqual(json.loads(self.engine.writes[-1][1]['a']),{'key':'mock-key'})
    def test_generated_storage_only_uses_staged_bytes_without_provider(self):
        self.engine.row['staged_png']=b'staged-original'
        m.work(JOB,True)
        self.generate.assert_not_called();self.assertEqual(self.upload.call_args.args[1],b'staged-original')
        self.assertEqual(len(self.engine.writes),2)
    def test_generated_storage_only_spool_fallback_preserved(self):
        path=self.spool/(JOB+'.png');path.write_bytes(b'spool-original')
        m.work(JOB,True)
        self.generate.assert_not_called();self.assertEqual(self.upload.call_args.args[1],b'spool-original')
        self.assertFalse(path.exists())
    def test_generated_provider_failure_keeps_generation_failure_state(self):
        self.generate.side_effect=RuntimeError('mock provider failure')
        m.work(JOB)
        self.upload.assert_not_called();self.assertEqual(len(self.engine.writes),1)
        sql,params=self.engine.writes[0]
        self.assertIn("status='failed'",sql);self.assertEqual(params['p'],'generation')
        self.assertEqual(params['e'],'이미지 생성 실패 · 자동 재호출 없음')
    def test_generated_upload_failure_keeps_storage_failure_state(self):
        self.upload.side_effect=RuntimeError('mock object failure')
        m.work(JOB)
        sql,params=self.engine.writes[-1]
        self.assertIn("status='failed'",sql);self.assertEqual(params['p'],'storage')
        self.assertEqual(params['e'],'클라우드 저장 실패 · 저장 재시도 가능')
    def test_generated_storage_missing_source_keeps_storage_failure_state(self):
        m.work(JOB,True)
        self.generate.assert_not_called();self.upload.assert_not_called()
        self.assertEqual(self.engine.writes[-1][1]['p'],'storage')
    def test_generated_non_running_unchanged(self):
        self.engine.row['status']='ready';m.work(JOB)
        self.generate.assert_not_called();self.upload.assert_not_called();self.assertFalse(self.engine.writes)
    def test_origin_unreadable_never_enters_general_failure_update(self):
        self.engine.error=RuntimeError('mock read error')
        with self.assertRaises(RuntimeError):m.work(JOB)
        self.generate.assert_not_called();self.upload.assert_not_called();self.assertFalse(self.engine.writes)
    def test_missing_job_never_creates_failure_write(self):
        self.engine.row=None
        with self.assertRaises(LookupError):m.work(JOB)
        self.assertFalse(self.engine.writes)


class RetryGuardTests(unittest.TestCase):
    def setUp(self):
        self.engine=Engine(dict(job_id=JOB,configuration_id='P113835',origin_kind='generated',
            status='failed',phase='storage',staged_png=b'source'))
        self.permission=Mock();self.background=Mock();self.request=object()
        for target,value in [('engine',self.engine),('permission',self.permission)]:
            p=patch.object(m,target,value);p.start();self.addCleanup(p.stop)
    def retry(self):return m.retry_storage('P113835',UUID(JOB),self.request,self.background)
    def test_existing_import_cannot_update_or_reserve_background_even_storage_phase(self):
        self.engine.row['origin_kind']='existing_import'
        before=copy.deepcopy(self.engine.row)
        with self.assertRaises(m.HTTPException) as error:self.retry()
        self.assertEqual(error.exception.status_code,409)
        self.assertEqual(self.engine.writes,[]);self.background.add_task.assert_not_called()
        self.assertEqual(self.engine.row,before);self.permission.assert_called_once_with(self.request)
    def test_unknown_and_missing_origin_cannot_reserve_background(self):
        for origin in ('unknown',None,False,''):
            with self.subTest(origin=origin):
                self.engine.row['origin_kind']=origin
                with self.assertRaises(m.HTTPException):self.retry()
        self.engine.row.pop('origin_kind')
        with self.assertRaises(m.HTTPException):self.retry()
        self.assertFalse(self.engine.writes);self.background.add_task.assert_not_called()
    def test_generated_storage_retry_preserves_update_and_exact_background_task(self):
        result=self.retry()
        self.assertEqual(result,dict(job_id=UUID(JOB)))
        self.assertEqual(len(self.engine.writes),1)
        self.assertIn("status='running'",self.engine.writes[0][0])
        self.background.add_task.assert_called_once_with(m.work,JOB,True)
    def test_generated_wrong_phase_keeps_existing_conflict(self):
        self.engine.row['phase']='generation'
        with self.assertRaises(m.HTTPException):self.retry()
        self.assertFalse(self.engine.writes);self.background.add_task.assert_not_called()
    def test_import_source_path_is_not_probed(self):
        self.engine.row['origin_kind']='existing_import';self.engine.row['staged_png']=None
        with patch.object(m.Path,'exists',side_effect=AssertionError('no spool probe')):
            with self.assertRaises(m.HTTPException):self.retry()
        self.background.add_task.assert_not_called()


if __name__=='__main__':unittest.main()
