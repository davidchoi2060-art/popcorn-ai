import copy,json,unittest
from pathlib import Path
from pydantic import ValidationError
from api.configuration_consultation import Conditions,Use,Body,ground_conditions,parse_output,required_questions,match

ROOT=Path(__file__).resolve().parents[1]
class ConsultationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d=json.loads((ROOT/'db/migrations/data/pc_usage_rules_20260928.json').read_text(encoding='utf-8'))
        cls.registry={s['id']:dict(s,_version=d['rule_version'],_rules=d) for s in d['scenarios']}
        cls.catalog=json.loads((ROOT/'db/migrations/data/pc_configuration_catalog_20260928.json').read_text(encoding='utf-8'))['records']
        for pc in cls.catalog:pc.update(stale_parts=[],observed_date='2026-09-28',revision=1)
    def profile(self,**kw):
        return Conditions(uses=[Use(scenario_id='O01',description='문서')],budget_won=1000000,budget_scope='body',**kw)
    def test_model_cannot_inject_product_or_price(self):
        with self.assertRaises(ValidationError):parse_output(json.dumps({'conditions':{},'summary':'ok','questions':[],'products':[{'price':1}]}))
    def test_malformed_output_does_not_become_empty_profile(self):
        with self.assertRaises(ValueError):parse_output('문서용 PC를 추천합니다')
    def test_unknown_scenario_requires_questions(self):
        p=Conditions(uses=[Use(scenario_id='G99',description='등록 안 된 게임')])
        self.assertEqual(match(p,self.registry,self.catalog)['state'],'needs_conditions')
    def test_game_target_not_assumed(self):
        p=Conditions(uses=[Use(scenario_id='G02',description='롤')])
        self.assertTrue(required_questions(p,self.registry))
        p.uses[0].resolution='1920×1080';p.uses[0].target_fps=144
        self.assertFalse(required_questions(p,self.registry))
    def test_total_budget_requires_expense_split(self):
        p=self.profile();p.budget_scope='total'
        self.assertTrue(required_questions(p,self.registry))
    def test_concurrent_does_not_use_maximum_memory_shortcut(self):
        p=self.profile();p.uses.append(Use(scenario_id='O02',description='엑셀'));p.concurrent='together'
        r=match(p,self.registry,self.catalog);self.assertEqual(r['state'],'evidence_pending');self.assertEqual(r['candidates'],[])
    def test_candidate_values_come_from_catalog_and_not_publishable(self):
        r=match(self.profile(extra_limit_won=150000),self.registry,self.catalog)
        self.assertEqual([c['price_snapshot'] for c in r['candidates']],[509600,627500]);self.assertFalse(r['customer_publishable'])
    def test_stale_part_excludes_affected_configuration(self):
        catalog=copy.deepcopy(self.catalog)
        next(p for p in catalog if p['id']=='N02')['stale_parts']=['112789']
        r=match(self.profile(),self.registry,catalog)
        self.assertNotIn('N02',[c['configuration_id'] for c in r['candidates']])
    def test_unknown_extra_allowance_does_not_force_second_card(self):
        self.assertEqual(len(match(self.profile(),self.registry,self.catalog)['candidates']),1)
    def test_budget_shortfall_preserves_requirement(self):
        p=self.profile();p.budget_won=100000
        r=match(p,self.registry,self.catalog);self.assertEqual(r['state'],'budget_exceeded');self.assertEqual(r['candidates'],[])
    def test_unresolved_preferences_never_silently_dropped(self):
        p=self.profile();p.unresolved=['화이트 케이스 필수']
        self.assertEqual(match(p,self.registry,self.catalog)['state'],'evidence_pending')
    def test_local_ai_does_not_imply_gpu_load_support(self):
        p=self.profile();p.uses=[Use(scenario_id='A01',description='로컬 AI',model_tag='a-model')]
        self.assertEqual(match(p,self.registry,self.catalog)['state'],'evidence_pending')
    def test_unsupported_llm_defaults_are_removed(self):
        p=Conditions(uses=[Use(scenario_id='G01',description='롤',resolution='1920×1080',target_fps=60)])
        ground_conditions(p,Body(message='롤을 하고 싶어요',profile_revision=1))
        self.assertIsNone(p.uses[0].resolution);self.assertIsNone(p.uses[0].target_fps)
    def test_quote_must_exist_and_match_value(self):
        u=Use(scenario_id='G02',description='롤',resolution='1920×1080',target_fps=144,resolution_evidence='FHD',fps_evidence='144프레임')
        p=Conditions(uses=[u]);ground_conditions(p,Body(message='롤 FHD 144프레임',profile_revision=1))
        self.assertEqual(p.uses[0].target_fps,144)
        p.uses[0].target_fps=240
        ground_conditions(p,Body(message='롤 FHD 144프레임',profile_revision=2))
        self.assertIsNone(p.uses[0].target_fps)
    def test_explicit_resolution_aliases_are_normalized(self):
        for value in ('FHD','1920x1080','1920×1080'):
            p=Conditions(uses=[Use(scenario_id='G02',description='롤',resolution=value,target_fps=144,resolution_evidence='FHD',fps_evidence='144프레임')])
            ground_conditions(p,Body(message='롤은 FHD 144프레임 목표입니다',profile_revision=2))
            self.assertEqual(p.uses[0].resolution,'1920×1080')
            self.assertFalse(required_questions(p,self.registry))
    def test_same_use_verified_quote_can_ground_two_fields(self):
        p=Conditions(uses=[Use(scenario_id='G02',description='롤',resolution='1920×1080',target_fps=144,fps_evidence='FHD 144프레임')])
        ground_conditions(p,Body(message='롤은 FHD 144프레임 목표입니다',profile_revision=2))
        self.assertEqual(p.uses[0].resolution,'1920×1080')
        self.assertFalse(required_questions(p,self.registry))

if __name__=='__main__':unittest.main()
