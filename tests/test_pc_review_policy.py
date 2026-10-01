import copy
import unittest
from uuid import uuid4
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from api import pc_quote_assembly
from api.pc_review_policy import route_checks, issue_stages
from api.part_explanations import fingerprint
from api.pc_quote_assembly import valid_agreement, unresolved, assembly_verified
from api.configuration_consultation import Conditions, Use, condition_requires_review


class PolicyTests(unittest.TestCase):
    def test_integrated_gpu_requires_explicit_bom_and_cpu_evidence(self):
        parts=[dict(slot='CPU',pseudo=False,ordinal=1,explanation_code=1),dict(slot='POWER',pseudo=False,ordinal=2,explanation_code=2),dict(slot='GPU',pseudo=True,ordinal=3)]
        checks=[dict(key='gpu_len',state='unknown'),dict(key='power',state='unknown')]
        specs={1:dict(cpu_gpu=True),2:dict(rated_watt=500)}
        out=route_checks(copy.deepcopy(checks),parts,specs)
        self.assertEqual(out[0]['state'],'not_applicable')
        self.assertEqual(out[1]['state'],'unknown')
        self.assertEqual(out[1]['stage'],'assembly')
        for invalid in ({1:dict(cpu_gpu=False),2:dict(rated_watt=500)}, {1:dict(cpu_gpu=True),2:{}}):
            out=route_checks(copy.deepcopy(checks),parts,invalid)
            self.assertEqual(out[1]['stage'],'recommendation')
        self.assertEqual(route_checks(copy.deepcopy(checks),parts[:2],specs)[0]['state'],'unknown')

    def test_tdp_deferral_requires_known_cooler_and_passing_socket(self):
        parts=[dict(slot='COOLER',pseudo=False,ordinal=1,explanation_code=1),dict(slot='CPU',pseudo=False,ordinal=2,explanation_code=2)]
        checks=[dict(key='cooler_tdp:1:2',state='unknown',detail='missing',missing_fields=['cooler_tdp']),dict(key='cooler_socket:1:2',state='pass')]
        specs={1:dict(part_type='COOLER_CPU_AIO')}
        self.assertEqual(route_checks(copy.deepcopy(checks),parts,specs)[0]['stage'],'assembly')
        checks[1]['state']='fail'
        self.assertEqual(route_checks(copy.deepcopy(checks),parts,specs)[0]['stage'],'recommendation')
        checks[1]['state']='pass';checks[0]['missing_fields'].append('tdp_watt')
        self.assertEqual(route_checks(copy.deepcopy(checks),parts,specs)[0]['stage'],'recommendation')

    def test_new_bom_can_explicitly_declare_integrated_without_placeholder(self):
        parts=[dict(slot='CPU',pseudo=False,ordinal=0,explanation_code=1),dict(slot='POWER',pseudo=False,ordinal=1,explanation_code=2)]
        checks=[dict(key='gpu_len',state='unknown'),dict(key='power',state='unknown')]
        specs={1:dict(cpu_gpu=True),2:dict(rated_watt=500)}
        config=dict(content=dict(facts=dict(discrete=False,gpu='내장 그래픽')))
        out=route_checks(copy.deepcopy(checks),parts,specs,config)
        self.assertEqual(out[0]['state'],'not_applicable')
        self.assertEqual(out[1]['stage'],'assembly')
        specs[1]['cpu_gpu']=False
        self.assertEqual(route_checks(copy.deepcopy(checks),parts,specs,config)[0]['state'],'unknown')
        specs[1]['cpu_gpu']=True
        parts.append(dict(slot='GPU',pseudo=False,ordinal=2,explanation_code=3))
        self.assertEqual(route_checks(copy.deepcopy(checks),parts,specs,config)[0]['state'],'unknown')

    def test_exact_issue_and_current_source_required(self):
        fp=fingerprint('SSD','256GB');row=dict(product_code=1,product_name='SSD',spec_source_text='256GB',source_fingerprint=fp,content=dict(review_issues=['P/N 확인'],review_issue_routes=[dict(issue='P/N 확인',stage='assembly',reason='공급 식별',source_url='https://example.com',source_fingerprint=fp,customer_conditions=['storage_speed'])]))
        self.assertEqual(issue_stages(row)[0]['stage'],'assembly')
        row['content']['review_issues'].append('용량 불일치')
        self.assertEqual(issue_stages(row)[1]['stage'],'recommendation')
        row['spec_source_text']='512GB'
        self.assertEqual(issue_stages(row)[0]['stage'],'recommendation')

    def test_customer_critical_requirement_reinstates_review(self):
        pc=dict(customer_conditions=['display_outputs','storage_speed'])
        p=Conditions(uses=[Use(description='사무용',monitor_count=1)])
        self.assertFalse(condition_requires_review(pc,p))
        p.uses[0].monitor_count=2
        self.assertTrue(condition_requires_review(pc,p))
        p.uses[0].monitor_count=1;p.uses[0].description='읽기 속도 7000MB/s 필수'
        self.assertTrue(condition_requires_review(pc,p))


class PhoneTests(unittest.TestCase):
    def test_phone_workflow_requires_write_role_and_same_site(self):
        app=FastAPI();app.include_router(pc_quote_assembly.router);client=TestClient(app)
        url='/api/admin/pc-quote-assembly/'+str(uuid4())+'/assembly'
        data=dict(version=1,action='issue',note='실제 조립 확인이 필요한 테스트')
        for actor in (None,dict(role='viewer')):
            with patch.object(pc_quote_assembly,'current_operator',return_value=actor):
                self.assertEqual(client.post(url,json=data).status_code,403)
        with patch.object(pc_quote_assembly,'current_operator',return_value=dict(role='owner')):
            self.assertEqual(client.post(url,json=data,headers={'sec-fetch-site':'cross-site'}).status_code,403)

    def test_only_latest_agreement_for_exact_proposal_counts(self):
        cid=str(uuid4());events=[dict(action='phone_decision',change_set_id=cid,payload=dict(decision='agreed',revision=2,proposal_basis='a'))]
        self.assertTrue(valid_agreement(events,cid,2,'a'))
        self.assertFalse(valid_agreement(events,cid,3,'a'))
        self.assertFalse(valid_agreement(events,cid,2,'b'))
        for decision in ('declined','no_response'):
            e=events+[dict(action='phone_decision',change_set_id=cid,payload=dict(decision=decision,revision=2,proposal_basis='a'))]
            self.assertFalse(valid_agreement(e,cid,2,'a'))

    def test_old_verification_invalid_after_issue_or_new_version(self):
        verify=dict(action='assembly_verify',payload=dict(version=1,bom_fingerprint='a'))
        issue=dict(event_id=uuid4(),action='assembly_issue',payload=dict(note='실제 장착 이슈'))
        resolved=dict(action='assembly_resolve',payload=dict(issue_id=str(issue['event_id'])))
        self.assertTrue(assembly_verified([verify],1,'a'))
        self.assertFalse(assembly_verified([verify],2,'b'))
        self.assertFalse(assembly_verified([verify,issue,resolved],1,'a'))
        self.assertEqual(unresolved([issue]),[issue])
        self.assertEqual(unresolved([issue,resolved]),[])


if __name__=='__main__':unittest.main()
