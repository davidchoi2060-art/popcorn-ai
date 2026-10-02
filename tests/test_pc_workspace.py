import copy
import json
import unittest
from unittest.mock import patch,MagicMock
from starlette.requests import Request
from fastapi import HTTPException
from api import admin_pc_workspace as workspace
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
            with self.assertRaises(workspace.ProposalFormatError):
                parse_proposal(json.dumps(dict(changes=[dict(field=field,value='approved',reason='변경')],notes=[])),self.content)

    def test_malformed_and_duplicate_changes_rejected(self):
        with self.assertRaises(workspace.ProposalFormatError):
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

    def test_new_empty_copy_accepts_individual_valid_proposals(self):
        empty=dict(title='신규 PC',intro='구성 안내',benefits=[],scene='',checks=[],faq=[])
        proposal=parse_proposal(json.dumps(dict(changes=[dict(field='scene',value='일상 작업',reason='빈 항목 작성'),dict(field='benefits',value=[['저장장치','등록된 SSD 구성입니다.']],reason='빈 특장점')],notes=[])),empty)
        self.assertEqual(len(proposal['changes']),2)
        self.assertEqual(empty['scene'],'')
        with self.assertRaises(workspace.ProposalFormatError):
            parse_proposal(json.dumps(dict(changes=[dict(field='scene',value='',reason='빈 값')],notes=[])),empty)

    def test_private_component_audit_is_not_sent_to_ai(self):
        d=dict(configuration_id='A1',revision=1,content=self.content,parts=[dict(slot_label='CPU',quantity=1,source_code='1',pseudo=False,explanation={'name':'CPU','role':'연산','_admin_part_history':[{'operator_id':'private'}],'updated_at':'private','supplier_price':'private'})],current_review=dict(checks=[],blockers=[]))
        value=json.dumps(source_context(d))
        self.assertNotIn('private',value);self.assertNotIn('_admin_part_history',value)

    def test_proposal_rejects_price_basis_change_after_generation(self):
        d=dict(configuration_id='N01',revision=1,status='draft',content=self.content,parts=[],current_review={'checks':[],'blockers':[],'basis':'a'*64})
        later=copy.deepcopy(d);later['current_review']['basis']='b'*64
        response=MagicMock(text=json.dumps({'changes':[],'notes':['등록자료 확인']}),provider='stub',model='stub',log_id=None)
        with patch.object(workspace,'current_operator',return_value={'role':'owner'}),patch.object(workspace,'engine'),patch.object(workspace,'read_configuration',side_effect=[d,later]),patch.object(workspace.llm,'call',return_value=response) as call:
            with self.assertRaises(HTTPException) as error:workspace.propose('N01',SuggestionRequest(revision=1),Request({'type':'http','headers':[]}))
            self.assertEqual(error.exception.status_code,409)
            self.assertEqual(call.call_args.kwargs['fallback_order'],[])
            system = call.call_args.kwargs['system']
            self.assertIn(workspace.COPY_QUALITY_GUIDE, system)
            self.assertIn('[["특장점 제목","설명"]', system)
            self.assertIn('운영체제 포함 여부', system)
            self.assertIn('자료 간 모델명·용량이 다르면', system)

    def test_request_extra_keys_cannot_set_model_or_apply(self):
        with self.assertRaises(ValidationError):
            SuggestionRequest(revision=1,model='arbitrary',apply=True)

    def test_safe_format_diagnostic_categories(self):
        samples = [
            (None, 'response_type'), (' ', 'empty_response'), ('{"changes":', 'invalid_json'),
            ('[]', 'proposal_schema'),
            (json.dumps({'changes':[{'field':'benefits','value':[],'reason':'確認'}],'notes':[]}), 'field_schema'),
            (json.dumps({'changes':[{'field':'intro','value':'文','reason':'確認'}]*2,'notes':[]}), 'duplicate_fields')]
        for raw, expected in samples:
            with self.subTest(expected=expected), self.assertRaises(workspace.ProposalFormatError) as caught:
                parse_proposal(raw, self.content)
            self.assertEqual(caught.exception.code, expected)
        raw = json.dumps({'changes':[], 'notes':[], 'SECRET-PRIVATE-KEY':'private value'})
        with self.assertRaises(workspace.ProposalFormatError) as caught:
            parse_proposal(raw, self.content)
        self.assertEqual(caught.exception.paths, ['?'])
        self.assertNotIn('SECRET', str(caught.exception))

    def test_format_failure_logs_safe_metadata_without_retry_or_catalog_write(self):
        d=dict(configuration_id='N01',revision=1,status='draft',content=self.content,parts=[],current_review={'checks':[],'blockers':[],'basis':'a'*64})
        for mode, raw, code in [('copy','{"private-secret":', 'invalid_json'),
                                ('copy',json.dumps({'changes':[{'field':'intro','value':'','reason':'private-secret'}],'notes':[]}), 'field_schema'),
                                ('review',json.dumps({'changes':[{'field':'intro','value':'private-secret','reason':'private-secret'}],'notes':[]}), 'review_changes')]:
            with self.subTest(mode=mode, code=code):
                response=MagicMock(text=raw,log_id=123)
                original=copy.deepcopy(d)
                with patch.object(workspace,'current_operator',return_value={'role':'owner'}),patch.object(workspace,'engine'),patch.object(workspace,'read_configuration',return_value=d) as read,patch.object(workspace.llm,'call',return_value=response) as call,patch.object(workspace.log,'warning') as warn:
                    with self.assertRaises(HTTPException) as caught:
                        workspace.propose('N01',SuggestionRequest(revision=1,mode=mode),Request({'type':'http','headers':[]}))
                    self.assertEqual(caught.exception.status_code,502)
                    self.assertIn('비용 기록 123',caught.exception.detail)
                    self.assertIn('자동 재시도하지 않았습니다',caught.exception.detail)
                    call.assert_called_once(); read.assert_called_once(); warn.assert_called_once()
                    metadata=json.loads(warn.call_args.args[1])
                    self.assertEqual(metadata['code'],code)
                    self.assertEqual(len(metadata['diagnostic_id']),32)
                    self.assertEqual(metadata['cost_log_id'],123)
                    self.assertNotIn('private-secret',warn.call_args.args[1])
                    self.assertNotIn('private-secret',caught.exception.detail)
                    self.assertEqual(d,original)


if __name__ == '__main__':
    unittest.main()
