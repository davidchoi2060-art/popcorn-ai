import copy
import json
import unittest
from pydantic import ValidationError
from api.admin_pc_workspace import task_for, parse_proposal, source_context, SuggestionRequest


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.content = dict(title='상품', intro='상품 소개', scene='사용 상황', benefits=[['특징','설명']], checks=[], faq=[], recommendation_policy={'알뜰':'설명'})
        self.row = dict(status='draft', management_state='ready', market_alerts=[], description_ready=True,
                        review_state=None, needs_review=False, review_reasons=[])

    def test_no_approval_is_review_task_not_missing_description(self):
        task = task_for(self.row)
        self.assertEqual(task['task_kind'], 'review')
        self.assertTrue(task['description_ready'])

    def test_price_alert_is_next_action(self):
        self.row.update(market_alerts=['price'])
        self.assertEqual(task_for(self.row)['task_kind'], 'price')

    def test_current_approved_has_no_task_and_excluded_not_promoted(self):
        self.row.update(review_state='approved')
        self.assertIsNone(task_for(self.row))
        self.row.update(management_state='excluded', description_ready=False)
        self.assertIsNone(task_for(self.row))

    def test_valid_single_field_does_not_mutate_baseline(self):
        original=copy.deepcopy(self.content)
        p=parse_proposal(json.dumps(dict(changes=[dict(field='intro',value='새 소개',reason='쉽게 설명')],notes=[])),self.content)
        self.assertEqual(p['changes'][0]['value'],'새 소개')
        self.assertEqual(self.content,original)

    def test_invented_fields_are_rejected(self):
        for field in ('price','status','recommendation_policy','_review'):
            with self.assertRaises(ValidationError):
                parse_proposal(json.dumps(dict(changes=[dict(field=field,value='approved',reason='변경')],notes=[])),self.content)

    def test_malformed_and_duplicate_changes_rejected(self):
        with self.assertRaises(ValidationError):
            parse_proposal(json.dumps(dict(changes=[dict(field='benefits',value=[],reason='변경')],notes=[])),self.content)
        c=dict(field='intro',value='내용',reason='변경')
        with self.assertRaises(ValueError):
            parse_proposal(json.dumps(dict(changes=[c,c],notes=[])),self.content)

    def test_sources_exclude_actor_offers_supplier_prices(self):
        d=dict(configuration_id='N01',revision=1,content=self.content,
               offers=[dict(supplier_cost=100)],actor='private operator',
               parts=[dict(slot_label='SSD',quantity=2,source_code='1',pseudo=False,explanation={'role':'저장'},current_unit_price=10)],
               current_review=dict(checks=[],blockers=[],actor='private'))
        serialized=json.dumps(source_context(d))
        for forbidden in ('private','supplier_cost','current_unit_price','offers'):
            self.assertNotIn(forbidden,serialized)
        self.assertEqual(source_context(d)['parts'][0]['quantity'],2)

    def test_request_extra_keys_cannot_set_model_or_apply(self):
        with self.assertRaises(ValidationError):
            SuggestionRequest(revision=1,model='arbitrary',apply=True)


if __name__ == '__main__':
    unittest.main()
