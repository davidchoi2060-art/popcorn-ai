import copy
import unittest
from api.part_explanations import fingerprint
from api.pc_review_specs import specs_for_review


class AssemblySpecsTests(unittest.TestCase):
    def setUp(self):
        h = fingerprint('CPU 265', 'LGA1851')
        self.row = dict(product_code=None, source_snapshot=dict(name='CPU 265', spec='LGA1851'),
                        source_fingerprint=h, content=dict(slot='CPU', availability_scope='assembly_only',
                        sources=[dict(id='maker', kind='manufacturer', url='https://example.org/spec')],
                        review_specs=dict(source_id='maker', source_fingerprint=h,
                                          fields=dict(socket='LGA1851', tdp_watt=65, cpu_gpu=True, sale_price=100))))

    def test_only_scoped_specs_are_resolved(self):
        result = specs_for_review({1:self.row}, {})[1]
        self.assertEqual(result, dict(part_type='CPU', socket='LGA1851', tdp_watt=65, cpu_gpu=True))
        self.assertIsNone(self.row['product_code'])

    def test_retail_never_falls_back_to_inline_facts(self):
        self.row['product_code'] = 20
        self.assertEqual(specs_for_review({1:self.row}, {})[1], {})
        db = {20:dict(socket='AM5')}
        self.assertEqual(specs_for_review({1:self.row}, db)[1], db[20])

    def test_changed_source_or_missing_evidence_stays_unknown(self):
        for change in ('snapshot', 'fingerprint', 'source', 'scope'):
            r = copy.deepcopy(self.row)
            if change == 'snapshot': r['source_snapshot']['spec'] = 'AM5'
            if change == 'fingerprint': r['content']['review_specs']['source_fingerprint'] = 'old'
            if change == 'source': r['content']['sources'] = []
            if change == 'scope': r['content']['availability_scope'] = 'retail'
            with self.subTest(change=change):
                self.assertEqual(specs_for_review({1:r}, {})[1], {})

    def test_bad_numeric_values_do_not_pass_through(self):
        for value in (True, '65', -65, 0, 10001):
            self.row['content']['review_specs']['fields']['tdp_watt'] = value
            self.assertNotIn('tdp_watt', specs_for_review({1:self.row}, {})[1])

    def test_board_fields_are_separate_from_cpu_fields(self):
        self.row['content']['slot'] = 'MB'
        self.row['content']['review_specs']['fields'].update(mem_type='DDR5', form_factor='m-ATX')
        self.assertEqual(specs_for_review({1:self.row}, {})[1],
                         dict(part_type='MB', socket='LGA1851', mem_type='DDR5', form_factor='m-ATX'))


if __name__ == '__main__': unittest.main()
