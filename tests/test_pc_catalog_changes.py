import copy
import unittest
from api.pc_catalog_changes import changes_for, issue_groups


class ChangesTests(unittest.TestCase):
    def setUp(self):
        self.config=dict(configuration_id='N1',content=dict(source='신규'),observed_date='2026-09-28')
        self.parts=[dict(pseudo=False,explanation_code=1,quantity=2)]
        self.explanations={1:dict(product_code=10,sale_price=100)}
        self.offers=[dict(offer_id='N1',price_snapshot=30200,payload=dict(assembly_fee_added=30000))]
        self.products={'10':dict(status='판매중',sale_price=100)}
        self.history={}
        self.baselines={'N1':'2026-09-28T12:00:00+00:00'}

    def alerts(self):
        return changes_for(self.config,self.parts,self.offers,self.explanations,self.products,self.history,self.baselines)

    def test_new_prices_use_quantity_and_one_assembly_fee(self):
        self.assertEqual(self.alerts(),[])
        self.explanations[1]['sale_price']=150
        self.assertEqual(self.alerts()[0]['current_price'],30300)
        self.assertEqual(self.offers[0]['price_snapshot'],30200)

    def test_bundle_and_modified_quote_are_not_retail_sums(self):
        self.config['content']['source']='기존'
        self.offers[0]['offer_id']='P123'
        self.products['123']=dict(status='판매중',sale_price=30200)
        self.explanations[1]['sale_price']=99999
        self.assertEqual(self.alerts(),[])
        self.products['123']['sale_price']=30500
        self.assertEqual(self.alerts()[0]['current_price'],30500)
        self.config['content']['source']='신규'
        self.offers[0].update(offer_id='ADMIN-N1',payload=dict(quote_only=True))
        self.assertEqual(self.alerts(),[])

    def test_sale_state_does_not_disappear_on_review(self):
        self.products['10']['status']='품절'
        self.config['content']['_review']=dict(state='approved',at='2026-10-01T00:00:00+00:00')
        self.assertEqual(self.alerts()[0]['kind'],'sale')

    def test_only_history_after_precise_capture_or_approval(self):
        self.history['10']=dict(old_price=90,new_price=100,changed_at='2026-09-28T06:00:00+00:00')
        self.assertEqual(self.alerts(),[])
        self.history['10']['changed_at']='2026-09-29T00:00:00+00:00'
        self.assertEqual(self.alerts()[0]['kind'],'price_history')
        self.config['content']['_review']=dict(state='pending',at='2026-10-01T00:00:00+00:00')
        self.assertEqual(len(self.alerts()),1)
        self.config['content']['_review']['state']='approved'
        self.assertEqual(self.alerts(),[])
        self.products['10']['status']='단종'
        self.assertEqual(len(self.alerts()),1)

    def test_missing_capture_does_not_invent_change_time(self):
        self.history['10']=dict(old_price=90,new_price=100,changed_at='2026-09-28T06:00:00+00:00')
        self.baselines={}
        self.assertEqual(self.alerts(),[])

    def test_common_reasons_keep_affected_ids_once(self):
        rows=[dict(configuration_id='A',review_reasons=['쿨러 소켓 · 근거 없음','쿨러 소켓 · 모델 미상']),dict(configuration_id='B',review_reasons=['쿨러 소켓 · 근거 없음'])]
        original=copy.deepcopy(rows)
        self.assertEqual(issue_groups(rows),[dict(label='쿨러 소켓',configurations=['A','B'])])
        self.assertEqual(rows,original)
