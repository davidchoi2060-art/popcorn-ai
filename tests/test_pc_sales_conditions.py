import copy
import unittest
from unittest.mock import patch, MagicMock
from datetime import date, timedelta
from pydantic import ValidationError
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from api import pc_sales_conditions as sales
from api.pc_copy_claims import claim_issues, filter_changes


class SalesTests(unittest.TestCase):
    def setUp(self):
        self.cfg=dict(configuration_id='N07',revision=1,bom_fingerprint='a'*64,status='draft',content={})
        self.parts=[dict(ordinal=1,slot='CPU',source_code='1',quantity=1,pseudo=False,explanation_hash='x')]
        self.offers=[dict(offer_id='N07',price_snapshot=100,payload={})]
        self.condition=dict(state='included',detail='Windows 11 Home',evidence='확정 판매 구성표 확인',source='내부 문서 S1',checked_date='2026-10-03')
        self.state={'basis':'b'*64}
        self.actor={'operator_id':7,'role':'owner'}

    def record(self,key='os',condition=None):
        c=sales.Condition(**(condition or self.condition)).model_dump(mode='json')
        self.cfg['content']['_sales_conditions']={key:dict(c,scope_basis=sales.scope_basis(self.cfg,self.parts,self.offers),operator_id=7,confirmed_at='now')}
        return sales.effective_conditions(self.cfg,self.parts,self.offers)

    def body(self,**changes):
        return sales.SalesEdit(revision=1,source_basis='b'*64,key='os',condition=self.condition,**changes)

    def test_confirmation_requires_source_evidence_and_date(self):
        for key in ('source','evidence','checked_date'):
            data=dict(self.condition);data[key]=None if key=='checked_date' else ' '
            with self.subTest(key=key),self.assertRaises(ValidationError):sales.Condition(**data)
        with self.assertRaises(ValidationError):sales.Condition(**dict(self.condition,checked_date='2099-01-01'))
        self.assertEqual(sales.Condition().state,'unknown')

    def test_states_are_target_specific_and_fields_protected(self):
        for data in [dict(revision=1,source_basis='b'*64,key='warranty',condition=self.condition),
                     dict(revision=1,source_basis='b'*64,key='os',condition=dict(self.condition,months=12)),
                     dict(revision=1,source_basis='b'*64,key='os',condition=dict(self.condition,operator_id=9))]:
            with self.assertRaises(ValidationError):sales.SalesEdit(**data)
        for months in (None,0,121,True):
            with self.assertRaises(ValidationError):sales.SalesEdit(revision=1,source_basis='b'*64,key='warranty',condition=dict(self.condition,state='verified',months=months))

    def test_current_terms_and_stale_bom_price_or_derived_identity(self):
        terms=self.record();self.assertEqual(terms['os']['state'],'included')
        self.cfg['content']['intro']='new copy'
        self.assertEqual(sales.effective_conditions(self.cfg,self.parts,self.offers)['os']['state'],'included')
        for scope in ('bom','price','identity','parts'):
            cfg=copy.deepcopy(self.cfg);parts=copy.deepcopy(self.parts);offers=copy.deepcopy(self.offers)
            if scope=='bom':cfg['bom_fingerprint']='z'*64
            if scope=='price':offers[0]['price_snapshot']+=1
            if scope=='identity':cfg['configuration_id']='NEW'
            if scope=='parts':parts[0]['quantity']+=1
            terms=sales.effective_conditions(cfg,parts,offers)
            self.assertEqual(terms['os']['state'],'unknown');self.assertTrue(terms['os']['stale'])

    def test_fact_or_copy_alone_cannot_become_confirmed_terms(self):
        self.cfg['content'].update(facts={'os_included':True},intro='OS 포함')
        self.assertEqual(sales.effective_conditions(self.cfg)['os']['state'],'unknown')

    def test_allow_only_canonical_matching_claim_not_other_subject_or_expansion(self):
        terms=self.record();canonical=terms['os']['customer_statement']
        self.assertEqual(claim_issues(canonical,conditions=terms),[])
        for claim in ['운영체제는 미포함입니다.',canonical+' 마우스는 미포함입니다.',canonical+' 보증 36개월을 제공합니다.',canonical+' 편집 프로그램 요구 사양을 충족합니다.']:
            self.assertTrue(claim_issues(claim,conditions=terms))
        p={'changes':[{'field':'checks','value':[canonical],'reason':'확정 근거'}],'notes':[]}
        self.assertEqual(len(filter_changes(p,terms)['changes']),1)

    def test_warranty_only_exact_confirmed_period_allowed(self):
        terms=self.record('warranty',dict(self.condition,state='verified',detail='판매자 조립 보증',months=12))
        self.assertEqual(claim_issues(terms['warranty']['customer_statement'],conditions=terms),[])
        self.assertIn('warranty',claim_issues('보증·AS 기간은 36개월입니다.',conditions=terms))

    def test_customer_contract_excludes_private_evidence_and_prior_assertions(self):
        self.record()
        result=sales.customer_conditions(self.cfg,self.parts,self.offers)
        self.assertEqual(result['os']['state'],'included')
        self.assertEqual(result['os']['detail'],'Windows 11 Home')
        self.assertEqual(set(result['os']),{'state','detail','months','needs_reconfirmation','customer_statement'})
        self.offers[0]['price_snapshot']+=1
        result=sales.customer_conditions(self.cfg,self.parts,self.offers)
        self.assertEqual(result['os']['state'],'unknown')
        self.assertTrue(result['os']['needs_reconfirmation'])
        self.assertEqual(result['os']['detail'],'')
        self.assertIsNone(result['os']['months'])
        self.assertNotIn('Windows',str(result))
        for private in ('evidence','source','operator_id','confirmed_at','scope_basis','previous'):
            self.assertNotIn(private,str(result))

    def test_unconfirmed_operator_notes_are_not_customer_detail(self):
        self.record(condition=dict(state='unknown',detail='private draft',evidence='private evidence',source='private source',months=None))
        result=sales.customer_conditions(self.cfg,self.parts,self.offers)
        self.assertEqual(result['os']['state'],'unknown')
        self.assertEqual(result['os']['detail'],'')
        self.assertNotIn('private',str(result))

    def test_customer_warranty_keeps_scope_and_period_without_approval(self):
        self.record('warranty',dict(self.condition,state='verified',detail='판매자 조립 보증',months=12))
        result=sales.customer_conditions(self.cfg,self.parts,self.offers)
        self.assertEqual(result['warranty']['months'],12)
        self.assertEqual(result['warranty']['detail'],'판매자 조립 보증')
        self.assertNotIn('publishable',result)
        self.assertNotIn('eligible',result)

    def test_stale_save_conflict_before_content_history_write(self):
        conn=MagicMock()
        with patch('api.pc_configuration_review.load_review',return_value=(self.cfg,self.parts,self.offers,{'basis':'c'*64})),patch('api.pc_configuration_edit.write_content') as write:
            with self.assertRaises(HTTPException) as caught:sales.save_condition(conn,'N07',self.body(),self.actor)
            self.assertEqual(caught.exception.status_code,409);write.assert_not_called()

    def test_save_bound_record_and_history_kind_without_mutating_baseline(self):
        before=copy.deepcopy(self.cfg)
        with patch('api.pc_configuration_review.load_review',return_value=(self.cfg,self.parts,self.offers,self.state)),patch('api.pc_configuration_edit.write_content',return_value={'revision':2}) as write:
            result=sales.save_condition(MagicMock(),'N07',self.body(),self.actor)
        self.assertEqual(result['revision'],2)
        payload=write.call_args.args[2]['_sales_conditions']['os']
        self.assertEqual(payload['operator_id'],7);self.assertEqual(payload['scope_basis'],sales.scope_basis(self.cfg,self.parts,self.offers))
        self.assertEqual(write.call_args.args[4],'sales_conditions');self.assertEqual(self.cfg,before)

    def test_unchanged_terms_do_not_create_history(self):
        self.record()
        with patch('api.pc_configuration_review.load_review',return_value=(self.cfg,self.parts,self.offers,self.state)),patch('api.pc_configuration_edit.write_content') as write:
            result=sales.save_condition(MagicMock(),'N07',self.body(),self.actor)
        self.assertFalse(result['changed']);write.assert_not_called()

    def test_endpoint_permissions_cross_site_and_retired(self):
        app=FastAPI();app.include_router(sales.router);client=TestClient(app)
        for actor in (None,{'role':'viewer'}):
            with patch.object(sales,'current_operator',return_value=actor):
                self.assertEqual(client.put('/api/admin/pc-configurations/N07/sales-conditions',json=self.body().model_dump(mode='json')).status_code,403)
        with patch.object(sales,'current_operator',return_value=self.actor):
            self.assertEqual(client.put('/api/admin/pc-configurations/N07/sales-conditions',headers={'sec-fetch-site':'cross-site'},json=self.body().model_dump(mode='json')).status_code,403)
        self.cfg['status']='retired'
        with patch('api.pc_configuration_review.load_review',return_value=(self.cfg,self.parts,self.offers,self.state)),self.assertRaises(HTTPException):
            sales.save_condition(MagicMock(),'N07',self.body(),self.actor)


if __name__=='__main__':unittest.main()
