import copy
import unittest
from unittest.mock import patch
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from api import pc_configuration_review as review
from api.part_explanations import fingerprint
from api.pc_configuration_copy import explanation_digest


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.config=dict(configuration_id='T1',status='review_required',revision=1,
                         content=dict(title='구성',intro='소개',facts=dict(cpu='CPU',ram_gb=16,storage_gb=512),
                                      _admin_bom_edit=dict(review_required=True)))
        self.rows={}
        self.parts=[]
        for i,slot in enumerate(['CPU','MB'],1):
            e=dict(source_product_code=i,product_code=i,product_name=slot,spec_source_text='spec',
                   sale_status='판매중',sale_price=100,source_fingerprint=fingerprint(slot,'spec'),
                   source_snapshot={},content=dict(review_issues=[]))
            self.rows[i]=e
            self.parts.append(dict(ordinal=i,slot=slot,source_code=str(i),explanation_code=i,pseudo=False,
                                   quantity=1,explanation_hash=explanation_digest(e)))
        self.specs={1:dict(part_type='CPU',socket='AM5'),2:dict(part_type='MB',socket='AM5')}
        self.offers=[dict(offer_id='T1',price_snapshot=100000,payload={'price':100000})]
        self.rules=[dict(rule_key='socket',label='CPU 소켓',slot='MB',ref_slot='CPU',field='socket',ref_field='socket',op='eq',part_types=[],ref_offset=0)]
        app=FastAPI();app.include_router(review.router);self.client=TestClient(app)

    def assess(self):
        return review.assess(self.config,self.parts,self.offers,self.rows,self.specs,self.rules)

    def approve_fixture(self):
        self.config['content']['_review']=dict(state='approved',basis=self.assess()['basis'],findings={})
        self.config['status']='approved'

    def test_fixed_bom_uses_rule_and_cannot_override_known_conflict(self):
        self.assertEqual(self.assess()['checks'][0]['state'],'pass')
        self.specs[2]['socket']='LGA1700'
        self.assertEqual(self.assess()['checks'][0]['state'],'fail')
        self.assertTrue(self.assess()['blockers'])

    def test_null_specs_are_unknown_not_pass_or_known_conflict(self):
        self.specs[2]['socket']=None
        r=self.assess()
        self.assertEqual(r['checks'][0]['state'],'unknown')
        self.assertIn('socket:2:1',r['required'])
        self.assertFalse(r['blockers'])

    def test_manual_requirements_always_present(self):
        self.assertEqual(set(self.assess()['required']),set(review.MANUAL))

    def test_missing_rules_or_parts_block_approval(self):
        self.rules=[]
        self.assertIn('활성 호환 규칙 없음',self.assess()['blockers'])
        self.parts=[]
        self.assertIn('구성 부품 또는 가격 기준 없음',self.assess()['blockers'])

    def test_source_change_or_unsold_component_blocks(self):
        self.rows[1]['product_name']='changed'
        self.assertTrue(self.assess()['blockers'])
        self.rows[1]['sale_status']='품절'
        self.assertTrue(any('판매중' in x for x in self.assess()['blockers']))

    def test_unknown_op_never_passes(self):
        self.rules[0]['op']='surprise'
        self.assertEqual(self.assess()['checks'][0]['state'],'unknown')

    def test_rules_apply_to_all_pairs_in_repeated_slots(self):
        self.parts.append(dict(self.parts[1],ordinal=3))
        self.assertEqual(len(self.assess()['checks']),2)

    def test_other_cooler_kind_not_checked(self):
        self.rules[0]['part_types']=['COOLER_CPU_AIO']
        self.assertEqual(self.assess()['checks'],[])

    def test_approved_only_for_current_basis(self):
        self.approve_fixture()
        self.assertTrue(self.assess()['eligible'])
        self.config['content']['intro']='new copy'
        self.assertFalse(self.assess()['eligible'])
        self.assertEqual(self.assess()['state'],'stale')
        self.assertEqual(self.assess()['findings'],{})

    def test_price_spec_rules_or_quantity_change_invalidates(self):
        for target,key,value in [(self.rows[1],'sale_price',200),(self.specs[1],'socket','AM4'),
                                 (self.rules[0],'label','revised'),(self.parts[0],'quantity',2),
                                 (self.offers[0],'price_snapshot',200000)]:
            with self.subTest(key=key):
                self.approve_fixture();old=target[key];target[key]=value
                self.assertFalse(self.assess()['eligible']);target[key]=old

    def test_workflow_metadata_does_not_invalidate_own_approval(self):
        self.approve_fixture();self.config['content']['_admin_bom_edit']['review_required']=False
        self.config['revision']+=1
        self.assertTrue(self.assess()['eligible'])
        self.config['status']='retired'
        self.assertFalse(self.assess()['eligible'])

    def test_legacy_catalog_preserved_until_review_started(self):
        c=dict(configuration_id='T',content={})
        self.assertTrue(review.review_allows(None,c))
        c['content']['_admin_bom_edit']={'review_required':True}
        self.assertFalse(review.review_allows(None,c))

    def test_save_checks_revision_evidence_and_required_findings(self):
        state=self.assess()
        data=dict(revision=1,basis=state['basis'],action='approve')
        with patch.object(review,'load_review',return_value=(self.config,self.parts,self.offers,state)):
            for change,status in [({'revision':2},409),({'basis':'0'*64},409),({},422),
                                  ({'action':'revoke'},422),({'findings':{'fake':{'confirmed':True}}},422)]:
                with self.subTest(change=change),self.assertRaises(HTTPException) as ctx:
                    review.save_review(None,'T1',review.ReviewEdit(**(data|change)),{'operator_id':1})
                self.assertEqual(ctx.exception.status_code,status)

    def test_write_auth_and_cross_site(self):
        data=dict(revision=1,basis='0'*64,action='draft')
        for actor in (None,{'role':'viewer'}):
            with patch.object(review,'current_operator',return_value=actor):
                self.assertEqual(self.client.put('/api/admin/pc-configurations/T1/review',json=data).status_code,403)
        with patch.object(review,'current_operator',return_value={'role':'owner'}):
            self.assertEqual(self.client.put('/api/admin/pc-configurations/T1/review',json=data,headers={'sec-fetch-site':'cross-site'}).status_code,403)


if __name__=='__main__':unittest.main()
