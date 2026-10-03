import copy
import json
import unittest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from starlette.requests import Request
from api import admin_pc_workspace as workspace
from api import pc_configuration_edit as edit
from api import admin_pc_batch as batch
from api.pc_copy_claims import claim_issues, filter_changes, sales_context


class ClaimTests(unittest.TestCase):
    def test_observed_failures_and_positive_inclusion(self):
        for text, key in [
            ('운영체제(OS)는 포함되어 있지 않으므로 별도 설치가 필요합니다.', 'os'),
            ('OS 및 키보드·마우스는 기본 구성에 포함되지 않습니다.', 'mouse'),
            ('Windows가 포함됩니다.', 'os'), ('모니터는 별도 구매가 필요합니다.', 'monitor'),
            ('주변기기는 기본 제공됩니다.', 'peripherals'), ('무상 AS 3년 제공', 'warranty'),
            ('편집 프로그램 실행에 필요한 메모리 조건을 갖췄습니다.', 'software')]:
            with self.subTest(text=text):
                self.assertIn(key, claim_issues(text))

    def test_neutral_guidance_and_real_specs_are_retained(self):
        for text in ['운영체제 포함 여부는 주문 전에 확인해 주세요.',
                     'OS 미포함 여부가 기본 구성과 일치하는지 확인 바랍니다.',
                     '키보드·마우스가 포함되는지 확인해 주세요.',
                     'OS가 포함된 경우 설치 상태를 확인하세요.',
                     '운영체제와 포맷 후 사용 가능한 공간은 줄어듭니다.',
                     'DDR5 32GB 메모리와 RTX 5060 8GB를 담았습니다.',
                     '실제 프로그램·버전·작업 조건과 사양을 비교하세요.',
                     '편집 프로그램 권장 사양 충족을 보장하지 않습니다.',
                     '보증 3년인지 확인해 주세요.',
                     '실시간 재생이나 렌더링 속도를 보장하지 않습니다.']:
            with self.subTest(text=text): self.assertEqual(claim_issues(text), [])

    def test_uncertainty_does_not_hide_other_assertion(self):
        self.assertIn('os', claim_issues('OS 포함 여부를 확인하세요. OS는 미포함입니다.'))
        self.assertIn('os', claim_issues('OS는 미포함이므로 최종 확인하세요.'))

    def test_nested_faq_checks_and_benefits(self):
        self.assertIn('os', claim_issues([{'question':'OS는 미포함인가요?', 'answer':'Windows는 미포함입니다.'}]))
        self.assertEqual(claim_issues([{'question':'OS는 미포함인가요?', 'answer':'포함 여부를 확인해 주세요.'}]), [])
        self.assertIn('software', claim_issues([['메모리','편집 프로그램의 요구 사양을 충족합니다.']]))
        self.assertIn('os', claim_issues([['운영체제','기본 구성에 포함됩니다.']], 'benefits'))

    def test_filter_preserves_safe_fields_and_never_mutates(self):
        p={'changes':[{'field':'title','value':'듀얼 SSD PC','reason':'사용 장면'},
                      {'field':'checks','value':['OS 미포함입니다.'],'reason':'안내'}], 'notes':['내부 확인']}
        before=copy.deepcopy(p); result=filter_changes(p)
        self.assertEqual([c['field'] for c in result['changes']], ['title'])
        self.assertIn('checks 제안 제외', result['notes'][0]); self.assertEqual(p,before)
        self.assertTrue(all(v['state']=='unknown' for v in sales_context().values()))

    def content(self):
        return dict(title='상품',intro='소개',benefits=[['사양','RAM 32GB']],scene='편집 후보',checks=[],faq=[],recommendation_policy={})

    def test_endpoint_filters_and_passes_unknown_context_without_retry(self):
        content=self.content(); content['facts']={'os_included':False}
        d=dict(configuration_id='N04',revision=1,status='draft',content=content,parts=[],current_review={'checks':[],'blockers':[],'basis':'a'*64})
        response=MagicMock(text=json.dumps({'changes':[{'field':'checks','value':['OS는 미포함입니다.'],'reason':'추정'}],'notes':[]}),provider='stub',model='stub',log_id=12)
        with patch.object(workspace,'current_operator',return_value={'role':'owner'}), patch.object(workspace,'engine'), patch.object(workspace,'read_configuration',return_value=d), patch.object(workspace.llm,'call',return_value=response) as call:
            result=workspace.propose('N04',workspace.SuggestionRequest(revision=1),Request({'type':'http','headers':[]}))
            self.assertEqual(result['changes'],[]); self.assertIn('근거 확인 필요',result['notes'][0])
            call.assert_called_once()
            product=json.loads(call.call_args.args[0])['product']
            self.assertEqual(product['sales_conditions']['os']['state'],'unknown')

    def connection(self, content):
        conn=MagicMock(); conn.execute.return_value.mappings.return_value.first.return_value=dict(revision=1,status='draft',content=content,updated_at='now')
        return conn

    def test_manual_save_rejects_before_history_or_update(self):
        conn=self.connection(self.content())
        body=edit.CopyEdit(revision=1,content=dict(self.content(),checks=['운영체제는 미포함입니다.']))
        with self.assertRaises(HTTPException) as error: edit.save_copy(conn,'N04',body,{'operator_id':1})
        self.assertEqual(error.exception.status_code,422)
        self.assertFalse(any('INSERT' in str(c.args[0]) or 'UPDATE pc_' in str(c.args[0]) for c in conn.execute.call_args_list))

    def test_legacy_unchanged_text_is_not_rejected(self):
        content=dict(self.content(),checks=['OS 미포함입니다.'])
        result=edit.save_copy(self.connection(content),'N04',edit.CopyEdit(revision=1,content=content),{'operator_id':1})
        self.assertFalse(result['changed'])

    def test_batch_cannot_bypass_common_save_guard(self):
        conn=self.connection(self.content())
        cfg={'revision':1,'content':self.content()}
        body=batch.BatchSave(items=[dict(configuration_id='N04',revision=1,source_basis='a'*64,changes=[dict(field='checks',value=['OS 미포함입니다.'],reason='추정')])])
        with patch.object(batch,'load_review',return_value=(cfg,None,None,{'basis':'a'*64})):
            result=batch.save_selected(conn,body,{'operator_id':1})
        self.assertEqual(result['items'][0]['status'],'failed')
        self.assertEqual(result['items'][0]['http_status'],422)


if __name__ == '__main__': unittest.main()
