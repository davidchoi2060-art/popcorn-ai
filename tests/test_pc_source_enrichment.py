import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from api.part_explanations import fingerprint
from tools.enrich_pc_catalog_sources import validate_source
from tools.triage_pc_catalog import triage


class SourceEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.row = dict(product_code=1, product_name='Exact black model', spec_source_text='spec',
                        source_fingerprint=fingerprint('Exact black model', 'spec'), sale_status='판매중')
        self.item = dict(code=1, source=dict(kind='merchant', url='https://example.com/1'),
                         reviewed_evidence=dict(product_name=self.row['product_name'],
                             source_fingerprint=self.row['source_fingerprint'], locator='spec table',
                             observed_at='2026-09-30', exact_model=True, conflict=False, version_sensitive=False))

    def test_merchant_is_never_labelled_manufacturer(self):
        self.assertEqual(validate_source(self.item, self.row), '판매처 게시 사양 대조')

    def test_wrong_variant_or_changed_local_source_rejected(self):
        for field, value in [('product_code', 2), ('product_name', 'white model'),
                             ('spec_source_text', 'new revision'), ('sale_status', '품절')]:
            with self.subTest(field=field):
                row = dict(self.row, **{field: value})
                with self.assertRaises(ValueError): validate_source(self.item, row)

    def test_conflict_version_or_missing_proof_rejected(self):
        for field, value in [('exact_model', False), ('conflict', True), ('version_sensitive', True),
                             ('locator', ''), ('observed_at', ''), ('source_fingerprint', 'wrong')]:
            with self.subTest(field=field):
                item = copy.deepcopy(self.item)
                item['reviewed_evidence'][field] = value
                with self.assertRaises(ValueError): validate_source(item, self.row)

    def test_unknown_source_and_assembly_retailer_rejected(self):
        for kind in ['community', 'llm', None]:
            item = copy.deepcopy(self.item); item['source']['kind'] = kind
            with self.assertRaises(ValueError): validate_source(item, self.row)
        self.item['assembly_specs'] = dict(socket='LGA1851')
        with self.assertRaises(ValueError): validate_source(self.item, self.row)

    def test_existing_manufacturer_plans_preserve_attribution(self):
        plan = json.loads((Path(__file__).resolve().parents[1] / 'tools/data/pc_catalog_enrichment_20260930.json').read_text(encoding='utf8'))
        for item in plan:
            self.assertEqual(validate_source(item, {}), '제조사 자료 대조')

    def triage_fixture(self):
        row = dict(self.row, source_product_code=1, status='draft', content=dict(sources=[], review_issues=[]))
        cpu = dict(product_code=2, source_product_code=2)
        rule = dict(rule_key='tdp', slot='COOLER', ref_slot='CPU', field='cooler_tdp', ref_field='tdp_watt')
        configs = [dict(id=key, group='보완 필요', failed=[], structural=[], price_notes=[],
                        review=dict(blockers=[]), unknown=[dict(key='tdp:1:2', label='냉각', state='unknown', detail='missing')])
                   for key in ['C1', 'C2']]
        data = dict(at='test', rows=[row, cpu], specs=[dict(product_code=1, part_type='COOLER'),
                    dict(product_code=2, part_type='CPU', tdp_watt=65)], rules=[rule],
                    parts=[dict(configuration_id=key, ordinal=n, slot=slot, explanation_code=n, pseudo=False)
                           for key in ['C1', 'C2'] for n, slot in [(1, 'COOLER'), (2, 'CPU')]])
        audit = dict(configurations=configs, common_parts=[], counts={'보완 필요':2}, total=2)
        item = dict(self.item, specs=dict(cooler_tdp=290))
        return data, audit, item

    def test_shared_missing_part_is_one_task_for_two_configs(self):
        data, audit, item = self.triage_fixture()
        with patch('tools.triage_pc_catalog.analyze', return_value=audit):
            result = triage(data, [item])
        self.assertEqual(len(result['tasks']), 1)
        self.assertEqual(result['tasks'][0]['affected_count'], 2)
        self.assertEqual(result['auto_only_configurations'], ['C1', 'C2'])

    def test_other_blocker_prevents_auto_only_and_stale_evidence_blocks_plan(self):
        data, audit, item = self.triage_fixture()
        audit['configurations'][0]['review']['blockers'] = ['가격 기준 없음']
        with patch('tools.triage_pc_catalog.analyze', return_value=audit):
            result = triage(data, [item])
        self.assertEqual(result['auto_only_configurations'], ['C2'])
        item['reviewed_evidence']['source_fingerprint'] = 'old'
        with patch('tools.triage_pc_catalog.analyze', return_value=audit):
            result = triage(data, [item])
        self.assertEqual(result['auto_only_configurations'], [])
        self.assertEqual(len(result['rejected_plan']), 1)


if __name__ == '__main__': unittest.main()
