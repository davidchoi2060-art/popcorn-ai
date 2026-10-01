import copy
import unittest
from api.part_explanations import fingerprint
from api.pc_cooling_plan import cooling_plan
from api.pc_review_policy import route_checks
from api.configuration_consultation import condition_requires_review, Conditions, Use


class CoolingTests(unittest.TestCase):
    def setUp(self):
        self.parts = [dict(slot='CPU', pseudo=False, ordinal=1, explanation_code=1, source_code=1),
                      dict(slot='COOLER', pseudo=True, ordinal=2, explanation_code=None, source_code=101309)]
        name, spec = 'AMD 라이젠5 5500GT (멀티팩(정품))', '멀티팩(Wraith Stealth쿨러 포함)'
        self.row = dict(product_code=1, product_name=name, spec_source_text=spec,
                        source_fingerprint=fingerprint(name, spec))

    def test_exact_included_model_resolves_placeholder_not_numeric_specs(self):
        plan = cooling_plan(self.parts, {1:self.row})
        self.assertTrue(plan['verified_bundle'])
        self.assertEqual(plan['installed'], 'bundled')
        checks = [dict(key=k, state='unknown') for k in ('cooler_socket','cooler_tdp','cooler_height','radiator')]
        result = route_checks(checks, self.parts, {}, rows={1:self.row})
        self.assertEqual([r['state'] for r in result], ['pass','unknown','unknown','not_applicable'])
        self.assertEqual(result[1]['stage'], 'assembly')

    def test_separate_cooler_is_never_deleted_or_bypassed(self):
        self.parts.append(dict(slot='COOLER',pseudo=False,ordinal=3,explanation_code=3,source_code=3))
        self.assertEqual(cooling_plan(self.parts,{1:self.row})['installed'],'separate')
        for state in ('fail','unknown'):
            c=route_checks([dict(key='cooler_socket:3:1',state=state)],self.parts,{},rows={1:self.row})[0]
            self.assertEqual(c['state'],state)
            self.assertEqual(c['stage'],'recommendation')

    def test_stale_source_and_ambiguous_multipack_do_not_resolve_cooler(self):
        self.row['spec_source_text']='멀티팩'
        self.assertFalse(cooling_plan(self.parts,{1:self.row})['verified_bundle'])
        self.row['source_fingerprint']=fingerprint(self.row['product_name'],'멀티팩')
        self.assertEqual(cooling_plan(self.parts,{1:self.row})['bundle_status'],'unknown')

    def test_no_cooler_and_bulk_do_not_mean_included(self):
        for name,spec in [('AMD 정품BOX','쿨러미포함'),('Intel 벌크','')]:
            row=dict(self.row,product_name=name,spec_source_text=spec,source_fingerprint=fingerprint(name,spec))
            self.assertEqual(cooling_plan(self.parts,{1:row})['bundle_status'],'not_included')

    def test_conflict_and_multiple_cpu_are_not_resolved(self):
        row=copy.deepcopy(self.row);row['spec_source_text']+=' / 쿨러없음'
        row['source_fingerprint']=fingerprint(row['product_name'],row['spec_source_text'])
        self.assertEqual(cooling_plan(self.parts,{1:row})['bundle_status'],'conflict')
        self.parts.append(dict(self.parts[0],ordinal=4))
        self.assertFalse(cooling_plan(self.parts,{1:self.row})['verified_bundle'])

    def test_noise_requirement_needs_additional_evidence(self):
        pc=dict(customer_conditions=['cooling_usage'])
        self.assertFalse(condition_requires_review(pc,Conditions(uses=[Use(description='사무용')])) )
        self.assertTrue(condition_requires_review(pc,Conditions(uses=[Use(description='조용한 사무용')])) )
