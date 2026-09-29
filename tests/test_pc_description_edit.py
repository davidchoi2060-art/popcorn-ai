import copy
import json
import unittest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from api import pc_configuration_edit as edit


class DescriptionEditTests(unittest.TestCase):
    def setUp(self):
        self.content=dict(title='기존 제목',intro='소개',benefits=[['특징','설명']],scene='사용 상황',
                          checks=['확인'],faq=[dict(question='질문',answer='답변')],recommendation_policy={'알뜰 구성':'설명'})
        self.prior=dict(configuration_id='P1',revision=2,content=dict(self.content,facts={'ram_gb':8},evidence={'source':'original'}),
                        updated_at='2026-09-29',observed_date='2026-09-28',status='draft',bom_fingerprint='a'*64)
        self.actor=dict(operator_id=7,name='관리자',role='owner')
        app=FastAPI();app.include_router(edit.router);self.client=TestClient(app)

    def body(self, **changes):
        return edit.CopyEdit(revision=2,content=dict(self.content,**changes))

    def connection(self):
        conn=MagicMock();conn.execute.return_value.mappings.return_value.first.return_value=self.prior
        return conn

    def test_allowlist_blocks_price_bom_facts_and_publication(self):
        for key in ('facts','price','parts','status','customer_publishable','evidence'):
            with self.assertRaises(ValidationError):self.body(**{key:'unexpected'})

    def test_empty_and_oversized_fields_rejected(self):
        for fields in ({'title':'  '},{'title':'x'*201},{'benefits':[]},{'checks':['x']*31}, {'faq':[{'question':'?','answer':' '}]}):
            with self.assertRaises(ValidationError):self.body(**fields)

    def test_stale_revision_rejected_before_any_write(self):
        conn=self.connection();self.prior['revision']=3
        with self.assertRaises(HTTPException) as error:edit.save_copy(conn,'P1',self.body(title='변경'),self.actor)
        self.assertEqual(error.exception.status_code,409)
        self.assertFalse(any('INSERT' in str(c.args[0]) or 'UPDATE pc_' in str(c.args[0]) for c in conn.execute.call_args_list))

    def test_no_change_does_not_create_revision(self):
        conn=self.connection();result=edit.save_copy(conn,'P1',self.body(),self.actor)
        self.assertFalse(result['changed']);self.assertEqual(result['revision'],2)
        self.assertEqual(conn.execute.call_count,2)

    def test_cannot_rename_recommendation_policy(self):
        with self.assertRaises(HTTPException) as error:edit.save_copy(self.connection(),'P1',self.body(recommendation_policy={'other':'new'}),self.actor)
        self.assertEqual(error.exception.status_code,422)

    def test_save_archives_prior_content_and_preserves_protected_values(self):
        conn=self.connection();conn.execute.return_value.mappings.return_value.one.return_value={'revision':3,'updated_at':'now'}
        result=edit.save_copy(conn,'P1',self.body(title='수정 제목'),self.actor)
        self.assertTrue(result['changed']);self.assertEqual(result['content']['facts'],{'ram_gb':8})
        self.assertEqual(result['content']['evidence'],{'source':'original'})
        calls=conn.execute.call_args_list
        archive=next(c.args[1] for c in calls if 'INSERT INTO pc_configuration_history' in str(c.args[0]))
        snap=json.loads(archive['snapshot']);self.assertEqual(snap['content']['title'],'기존 제목')
        self.assertEqual(snap['edit']['fields'],['title']);self.assertEqual(snap['edit']['operator_id'],7)
        statement=str(next(c.args[0] for c in calls if 'UPDATE pc_configurations' in str(c.args[0])))
        for protected in ('status=', 'bom_fingerprint=', 'observed_date='):
            self.assertNotIn(protected,statement)

    def test_writes_require_actual_operator_even_without_middleware(self):
        for actor in (None,dict(role='viewer')):
            with patch.object(edit,'current_operator',return_value=actor):
                result=self.client.put('/api/admin/pc-configurations/P1/description',json=self.body().model_dump())
            self.assertEqual(result.status_code,403)

    def test_cross_site_write_rejected(self):
        with patch.object(edit,'current_operator',return_value=self.actor):
            result=self.client.put('/api/admin/pc-configurations/P1/description',headers={'sec-fetch-site':'cross-site'},json=self.body().model_dump())
        self.assertEqual(result.status_code,403)

    def test_retired_record_rejected(self):
        self.prior['status']='retired'
        with self.assertRaises(HTTPException):edit.save_copy(self.connection(),'P1',self.body(title='변경'),self.actor)


if __name__=='__main__':unittest.main()
