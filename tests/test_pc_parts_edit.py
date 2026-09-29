import copy
import unittest
from unittest.mock import patch
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from api import pc_configuration_parts_edit as edit
from api.part_explanations import fingerprint


class PartsEditTests(unittest.TestCase):
    def setUp(self):
        def row(code,price,cap='16(GB)',slot='RAM'):
            name=f'부품 {code}'
            return dict(source_product_code=code,product_code=code,product_name=name,spec_source_text='spec',
                        source_fingerprint=fingerprint(name,'spec'),source_snapshot={},sale_status='판매중',
                        sale_price=price,part_type=slot,content=dict(name=name,slot=slot,review_issues=[],facts=[dict(label='상품 용량',value=cap)]))
        self.rows={1:row(1,30000),2:row(2,60000,'32(GB)'),3:row(3,20000)}
        self.parts=[dict(ordinal=0,slot='RAM',source_code='1',explanation_code=1,quantity=1,pseudo=False,selection_note='',explanation_hash='x')]
        self.prior=dict(configuration_id='P1',revision=2,content=dict(facts={'ram_gb':16},title='제목',source='기존'))
        self.offers=[dict(offer_id='P1',price_snapshot=1000000,payload={'price_note':'조립 포함','assembly_fee_added':0})]
        self.rep=edit.Replacement(ordinal=0,code=2,quantity=2)
        app=FastAPI();app.include_router(edit.router);self.client=TestClient(app)

    def calc(self,reps=None):
        return edit.compute_preview(self.prior,self.parts,self.offers,reps or [self.rep],self.rows,'P1')

    def test_package_capacity_and_price_not_multiplied_twice(self):
        r=self.calc()
        self.assertEqual(r['total'],1090000)
        self.assertEqual(r['delta'],90000)
        self.assertEqual(r['derived_facts']['ram_gb'],64)
        self.assertEqual(r['parts'][0]['quantity'],2)

    def test_assembly_fee_and_unchanged_prices_not_added(self):
        self.offers[0]['payload']['assembly_fee_added']=30000
        self.assertEqual(self.calc()['total'],1090000)

    def test_reduction_and_quantity_only(self):
        self.assertEqual(self.calc([edit.Replacement(ordinal=0,code=3,quantity=1)])['delta'],-10000)
        self.assertEqual(self.calc([edit.Replacement(ordinal=0,code=1,quantity=2)])['delta'],30000)

    def test_changed_price_or_evidence_invalidates_preview(self):
        token=self.calc()['preview_token'];self.rows[2]['sale_price']+=100
        self.assertNotEqual(token,self.calc()['preview_token'])
        token=self.calc()['preview_token'];self.rows[2]['content']['summary']='변경'
        self.assertNotEqual(token,self.calc()['preview_token'])

    def test_wrong_slot_unsold_stale_missing_price_rejected(self):
        for key,value in [('part_type','GPU'),('sale_status','품절'),('source_fingerprint','stale'),('sale_price',None)]:
            with self.subTest(key=key):
                rows=copy.deepcopy(self.rows);self.rows[2][key]=value
                with self.assertRaises(HTTPException):self.calc()
                self.rows=rows

    def test_pseudo_duplicate_and_no_change_rejected(self):
        with self.assertRaises(HTTPException):self.calc([self.rep,self.rep])
        with self.assertRaises(HTTPException):self.calc([edit.Replacement(ordinal=0,code=1,quantity=1)])
        self.parts[0]['pseudo']=True
        with self.assertRaises(HTTPException):self.calc()

    def test_original_input_unchanged_and_new_copy_requires_review(self):
        before=copy.deepcopy(self.prior);parts=copy.deepcopy(self.parts);r=self.calc()
        c=edit.revised_content(self.prior,r,'A1','new')
        self.assertEqual(c['facts']['ram_gb'],64)
        self.assertTrue(c['_admin_bom_edit']['review_required'])
        self.assertEqual(c['source'],'신규');self.assertEqual(self.prior,before);self.assertEqual(self.parts,parts)

    def test_capacity_requires_units_not_guess(self):
        self.assertEqual(edit.capacity('2(TB)'),2000)
        for value in ('32GB x 2','최대64GB',None,'16'):
            self.assertIsNone(edit.capacity(value))

    def test_fingerprint_ignores_order_not_quantity(self):
        a=self.parts+[{**self.parts[0],'ordinal':1,'slot':'SSD','source_code':'2'}]
        self.assertEqual(edit.bom_hash(a),edit.bom_hash(list(reversed(a))))
        b=copy.deepcopy(a);b[0]['quantity']=2
        self.assertNotEqual(edit.bom_hash(a),edit.bom_hash(b))

    def test_request_validation_and_auth(self):
        for quantity in (0,-1,17,True,1.5):
            with self.assertRaises(ValidationError):edit.Replacement(ordinal=0,code=2,quantity=quantity)
        body=dict(revision=2,offer_id='P1',replacements=[self.rep.model_dump()])
        for actor in (None,{'role':'viewer'}):
            with patch.object(edit,'current_operator',return_value=actor):
                self.assertEqual(self.client.put('/api/admin/pc-configurations/P1/parts',json=body).status_code,403)
        with patch.object(edit,'current_operator',return_value={'role':'owner'}):
            self.assertEqual(self.client.put('/api/admin/pc-configurations/P1/parts',json=body,headers={'sec-fetch-site':'cross-site'}).status_code,403)

    def test_stale_preview_rejected_before_write(self):
        body=edit.PartsEdit(revision=2,offer_id='P1',replacements=[self.rep],preview_token='old')
        with patch.object(edit,'prepare',return_value=(self.prior,self.parts,self.offers,self.calc())):
            with self.assertRaises(HTTPException) as e:edit.save_parts(None,'P1',body,{'operator_id':1})
        self.assertEqual(e.exception.status_code,409)

if __name__=='__main__':unittest.main()
