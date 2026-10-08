"""Only the new snapshot boundary, without importing DB/provider/router modules."""
import ast
import copy
import hashlib
import json
import re
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'api' / 'pc_media.py'
ERROR = '호환 규격 불일치·미확인 항목 보완 필요'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), default=str).encode()).hexdigest()


class SnapshotBoundary(unittest.TestCase):
    def setUp(self):
        tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
        names = {'visual_snapshot', '_optional_image_check', '_blocking_image_check', '_image_blockers', 'snapshot'}
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        self.assertEqual({n.name for n in nodes}, names)
        self.parts = [dict(slot=slot, ordinal=i, explanation_code=i + 1,
                           quantity=1, pseudo=False, source_name=slot)
                      for i, slot in enumerate(('CPU', 'MB', 'RAM', 'SSD', 'POWER', 'CASE'))]
        self.parts.append(dict(slot='GPU', ordinal=6, explanation_code=None,
                               quantity=1, pseudo=True))
        self.rows = [dict(source_product_code=p['explanation_code'],
                         content=dict(name=p['slot'], facts=[], image_asset={'fixture': True}))
                     for p in self.parts if not p['pseudo']]
        self.review = dict(blockers=[], checks=[], cooling_plan=dict(installed='separate', method='air'),
                           basis='a' * 64, assembly_checks=[])
        namespace = dict(copy=copy, re=re, digest=digest, text=lambda sql: sql,
                         NOTICE='AI 조립 예시 이미지 · 실제 출고 외형과 다를 수 있음',
                         load_review=lambda c, identity, lock=False:
                         (dict(content={}), self.parts, [], self.review))
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), namespace)
        self.snapshot = namespace['snapshot']
        rows = self.rows
        class ReadOnlyFixture:
            def execute(self, statement, parameters):
                assert statement.startswith('SELECT * FROM product_explanations')
                return self
            def mappings(self):
                return rows
        self.connection = ReadOnlyFixture()

    def run_check(self, state, stage='none', key='gpu_len', identity='P113835'):
        self.review['checks'] = [dict(key=key, label='GPU length', state=state, stage=stage, detail='fixture original warning')]
        return self.snapshot(self.connection, identity)

    def test_current_two_integrated_gpu_cases(self):
        for identity in ('P113835', 'P113836'):
            with self.subTest(identity=identity):
                result = self.run_check('not_applicable', identity=identity)
                self.assertEqual(result['errors'], [])
                self.assertEqual(result['configuration_id'], identity)
                self.assertEqual(result['visual_basis'], digest(result['snapshot']))

    def test_pass_fail_unknown_unfamiliar_state(self):
        for state, blocked in [('pass', False), ('fail', False), ('unknown', False), ('future', True)]:
            with self.subTest(state=state):
                self.assertEqual(ERROR in self.run_check(state)['errors'], blocked)

    def test_assembly_exclusion_unchanged(self):
        for state in ('fail', 'unknown', 'future', 'not_applicable'):
            with self.subTest(state=state):
                self.assertNotIn(ERROR, self.run_check(state, 'assembly', 'power')['errors'])

    def test_other_nonapplicable_key_stays_blocked(self):
        self.assertIn(ERROR, self.run_check('not_applicable', key='unrecognized')['errors'])

    def test_gpu_length_optional_in_recommendation_stage(self):
        self.assertNotIn(ERROR, self.run_check('not_applicable', stage='recommendation')['errors'])

    def test_external_gpu_length_is_optional(self):
        self.parts[-1] = dict(slot='GPU', ordinal=6, explanation_code=99,
                              quantity=1, pseudo=False, source_name='external GPU')
        self.rows.append(dict(source_product_code=99, content=dict(name='external GPU')))
        self.assertNotIn(ERROR, self.run_check('not_applicable')['errors'])

    def test_snapshot_visual_and_other_blocker_unchanged(self):
        before = self.run_check('pass')
        self.review['blockers'] = ['fixture-existing-blocker']
        after = self.run_check('not_applicable')
        self.assertEqual(after['errors'], ['fixture-existing-blocker'])
        for key in ('snapshot', 'visual_basis', 'basis', 'assembly_checks'):
            self.assertEqual(before[key], after[key])

    def test_non_gpu_fail_unknown_unfamiliar_still_blocked(self):
        for state in ('fail', 'unknown', 'future', 'not_applicable'):
            with self.subTest(state=state):
                self.assertIn(ERROR, self.run_check(state, key='socket:0:1')['errors'])

    def test_optional_failure_blocker_and_warning_preserved(self):
        self.parts[-1].update(pseudo=False, explanation_code=99, source_name='GPU')
        self.rows.append(dict(source_product_code=99, content=dict(name='GPU')))
        self.review['blockers'] = ['GPU length · 현재 DB 사양 불일치', 'other blocker']
        self.review['recommendation_state'] = 'hold'
        self.review['customer_publishable'] = False
        before = copy.deepcopy(self.review)
        result = self.run_check('fail', key='gpu_len:6:5')
        self.assertEqual(result['errors'], ['other blocker'])
        self.assertEqual(result['optional_checks'], self.review['checks'])
        self.assertEqual(result['optional_checks'][0]['state'], 'fail')
        for key in ('blockers', 'recommendation_state', 'customer_publishable', 'basis'):
            self.assertEqual(self.review[key], before[key])
        result['optional_checks'][0]['state'] = 'changed'
        self.assertEqual(self.review['checks'][0]['state'], 'fail')

    def test_same_label_other_failure_blocker_is_retained(self):
        self.run_check('fail')
        self.review['checks'].append(dict(key='socket:0:1', label='GPU length', state='fail', stage='recommendation'))
        self.review['blockers'] = ['GPU length · 현재 DB 사양 불일치']
        result = self.snapshot(self.connection, 'P113835')
        self.assertIn('GPU length · 현재 DB 사양 불일치', result['errors'])
        self.assertIn(ERROR, result['errors'])

    def test_spoofed_or_ambiguous_key_stays_blocked(self):
        for key in ('gpu_length', 'gpu_len_other', None, 'gpu_len:foo:5', 'gpu_len:6:5:0', 'gpu_len:0:5', 'gpu_len:6:5', 'gpu_len:06:05'):
            with self.subTest(key=key):
                self.assertIn(ERROR, self.run_check('unknown', key=key)['errors'])

    def test_unattributed_blocker_remains(self):
        self.review['blockers'] = ['GPU length · current mismatch', 'unattributed']
        result = self.run_check('unknown')
        self.assertEqual(result['errors'], self.review['blockers'])

    def test_empty_active_checks_still_blocked(self):
        self.review['checks'] = []
        self.assertIn('활성 호환성 검사 필요', self.snapshot(self.connection, 'P113835')['errors'])


if __name__ == '__main__':
    unittest.main()
