import copy
import unittest
from unittest.mock import patch
from fastapi import HTTPException, FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from api import admin_pc_builder as builder
from api.part_explanations import fingerprint


# 아래 시험들은 상품코드(1~8)로 슬롯을 가리킨다. 순서를 builder.SLOTS(=taxonomy.SLOTS)에
# 기대면 어휘 순서가 바뀔 때 시험이 엉뚱한 슬롯을 건드린다 — 시험 쪽 고정 순서를 쓴다.
FIXTURE_SLOTS=('CPU','GPU','RAM','SSD','MB','COOLER','POWER','CASE')


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(set(FIXTURE_SLOTS),set(builder.SLOTS))
        self.rows={};self.specs={};selection=[]
        for code,slot in enumerate(FIXTURE_SLOTS,1):
            kind='COOLER_CPU_AIR' if slot=='COOLER' else slot
            facts=[dict(label='상품 용량',value='32(GB)')] if slot=='RAM' else [dict(label='용량',value='1(TB)')] if slot=='SSD' else []
            self.rows[code]=dict(product_code=code,source_product_code=code,product_name=slot,
                spec_source_text='spec',source_fingerprint=fingerprint(slot,'spec'),source_snapshot={},
                content=dict(slot=slot,name=slot,facts=facts,review_issues=[]),sale_status='판매중',
                sale_price=10000,part_type=kind,stock_qty=2)
            self.specs[code]=dict(part_type=kind,socket='AM5',cpu_gpu=True)
            selection.append(dict(code=code,quantity=1))
        self.body=builder.Build(title='신규 구성',parts=selection,request_id='test-request-123456')
        self.rules=[dict(rule_key='socket',label='CPU 소켓',slot='MB',ref_slot='CPU',field='socket',ref_field='socket',op='eq',part_types=[],ref_offset=0)]

    def calculate(self,body=None):return builder.calculate(body or self.body,self.rows,self.specs,self.rules)

    def test_fee_once_and_pack_capacity(self):
        r=self.calculate();self.assertEqual(r['total'],80000+builder.ASSEMBLY_FEE)
        self.assertEqual(r['content']['facts']['ram_gb'],32)
        self.body.parts[2].quantity=2
        self.assertEqual(self.calculate()['content']['facts']['ram_gb'],64)
        self.assertTrue(r['content']['_admin_bom_edit']['review_required'])
        self.assertFalse(r['offer']['payload']['customer_publishable'])

    def test_missing_component_and_same_code(self):
        self.body.parts.pop()
        with self.assertRaises(HTTPException):self.calculate()
        self.setUp();self.body.parts.append(self.body.parts[0])
        with self.assertRaises(HTTPException):self.calculate()

    def test_multiple_cpu_and_quantity_bounds(self):
        self.body.parts[0].quantity=2
        with self.assertRaises(HTTPException):self.calculate()
        for qty in [0,17,1.5,True]:
            with self.assertRaises(ValidationError):builder.Selection(code=1,quantity=qty)

    def test_sale_stale_and_slot_disagreement(self):
        for mutation in [('sale_status','품절'),('source_fingerprint','changed'),('part_type','MONITOR'),('status','retired')]:
            self.setUp();self.rows[1][mutation[0]]=mutation[1]
            with self.assertRaises(HTTPException):self.calculate()

    def test_owned_quantity_checked_without_stock_changes(self):
        self.body.parts[2].source='owned';self.body.parts[2].quantity=3
        with self.assertRaises(HTTPException):self.calculate()
        self.body.parts[2].quantity=2;before=copy.deepcopy(self.rows);self.calculate()
        self.assertEqual(self.rows,before)

    def test_known_conflict_blocks_save_unknown_stays_pending(self):
        self.specs[5]['socket']='LGA1700';self.assertFalse(self.calculate()['can_save'])
        self.specs[5]['socket']=None;r=self.calculate()
        self.assertTrue(r['can_save']);self.assertEqual(r['review']['recommendation_state'],'hold')
        self.assertFalse(r['review']['eligible'])
        self.rules=[];self.assertFalse(self.calculate()['can_save'])

    def test_integrated_requires_evidence_and_no_discrete_gpu(self):
        self.body.integrated_gpu=True
        with self.assertRaises(HTTPException):self.calculate()
        self.body.parts=[p for p in self.body.parts if p.code!=2]
        self.calculate();self.specs[1]['cpu_gpu']=None
        with self.assertRaises(HTTPException):self.calculate()

    def test_bundled_requires_verified_package(self):
        self.body.parts=[p for p in self.body.parts if p.code!=6];self.body.bundled_cooler=True
        with self.assertRaises(HTTPException):self.calculate()
        with patch.object(builder,'cooling_plan',return_value={'verified_bundle':True}):self.calculate()

    def test_preview_token_changes_when_inputs_or_evidence_change(self):
        token=self.calculate()['preview_token']
        for mutate in [lambda:setattr(self.body,'title','다른 이름'),lambda:self.rows[1].update(sale_price=12000),lambda:self.rows[1].update(stock_qty=3),lambda:self.rules[0].update(label='변경 규칙')]:
            self.setUp();mutate();self.assertNotEqual(token,self.calculate()['preview_token'])

    def test_unauthorized_and_cross_site_writes(self):
        app=FastAPI();app.include_router(builder.router);client=TestClient(app)
        with patch.object(builder,'current_operator',return_value={'role':'viewer'}):
            self.assertEqual(client.post('/api/admin/pc-builder/save',json=self.body.model_dump()).status_code,403)
        with patch.object(builder,'current_operator',return_value={'role':'owner','operator_id':1}):
            self.assertEqual(client.post('/api/admin/pc-builder/preview',json=self.body.model_dump(),headers={'sec-fetch-site':'cross-site'}).status_code,403)

    def test_save_refuses_changed_preview(self):
        r=self.calculate();self.body.preview_token='wrong'
        with patch.object(builder,'prepare',return_value=(r,None)),self.assertRaises(HTTPException) as exc:
            builder.save_build(None,self.body,{'operator_id':1})
        self.assertEqual(exc.exception.status_code,409)

    def test_duplicate_and_idempotent_request(self):
        r=self.calculate();dup=dict(configuration_id='A1',content={'_admin_creation':{}})
        with patch.object(builder,'prepare',return_value=(r,dup)),self.assertRaises(HTTPException):
            builder.save_build(None,self.body,{'operator_id':1})
        dup['content']['_admin_creation']=dict(request_id=self.body.request_id,input_hash=builder.digest(self.body.model_dump(exclude={'preview_token'})))
        with patch.object(builder,'prepare',return_value=(r,dup)):
            self.assertTrue(builder.save_build(None,self.body,{'operator_id':1})['reused'])



class DraftRestoreTests(unittest.TestCase):
    setUp = BuilderTests.setUp
    def draft(self):
        return builder.Draft(title='작성 중인 상품',parts=[p.model_dump() for p in self.body.parts],request_id=self.body.request_id)

    def test_restore_reads_current_price_and_preserves_quantities(self):
        self.rows[1]['sale_price']=12345
        self.body.parts[2].quantity=2
        result=builder.resolve_draft(self.draft(),self.rows)
        self.assertEqual(result['items'][0]['unit_price'],12345)
        self.assertEqual(result['items'][2]['quantity'],2)
        self.assertEqual(result['rejected'],[])
        self.assertNotIn('preview_token',result)

    def test_unavailable_stale_archived_and_low_stock_are_reported(self):
        for key,value in [('sale_status','품절'),('source_fingerprint','stale'),('status','retired'),('sale_price',0)]:
            self.setUp();self.rows[1][key]=value
            result=builder.resolve_draft(self.draft(),self.rows)
            self.assertEqual(len(result['items']),7);self.assertEqual(result['rejected'][0]['code'],1)
        self.setUp();self.body.parts[2].source='owned';self.rows[3]['stock_qty']=0
        self.assertIn('수량 부족',builder.resolve_draft(self.draft(),self.rows)['rejected'][0]['reason'])

    def test_restore_does_not_mutate_rows_or_trust_client_prices(self):
        before=copy.deepcopy(self.rows);builder.resolve_draft(self.draft(),self.rows)
        self.assertEqual(before,self.rows)
        body=self.draft().model_dump();body['parts'][0]['unit_price']=1
        with self.assertRaises(ValidationError):builder.Draft.model_validate(body)

    def test_restore_permission_and_unknown_codes(self):
        app=FastAPI();app.include_router(builder.router);client=TestClient(app)
        with patch.object(builder,'current_operator',return_value={'role':'viewer'}):
            self.assertEqual(client.post('/api/admin/pc-builder/draft/resolve',json=self.draft().model_dump()).status_code,403)
        result=builder.resolve_draft(self.draft(),{})
        self.assertEqual(len(result['rejected']),8);self.assertFalse(result['items'])
