"""조립 호환 검사 공용 판정 (부품 상품화 2단계)."""
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from api import build_check as bc
from api import pc_configuration_parts_edit as edit

RULES = [
    dict(rule_id=1, rule_key='socket', slot='MB', field='socket', op='eq', ref_slot='CPU', ref_field='socket',
         label='CPU 소켓 규격 일치', detail_fmt='{v} / {r}', part_types=[], ref_offset=0, null_ref_mode='block'),
    dict(rule_id=2, rule_key='mem', slot='RAM', field='mem_type', op='eq', ref_slot='MB', ref_field='mem_type',
         label='메모리 규격 일치', detail_fmt='{v} / {r}', part_types=[], ref_offset=0, null_ref_mode='block'),
    dict(rule_id=3, rule_key='cooler_height', slot='COOLER', field='cooler_height_mm', op='lte', ref_slot='CASE',
         ref_field='cooler_height_mm', label='쿨러 높이 여유', detail_fmt='{v} / {r}', part_types=['COOLER_CPU_AIR'],
         ref_offset=0, null_ref_mode='block'),
]
SPECS = {
    1: dict(part_type='CPU', socket='AM5', cpu_gpu=False),
    2: dict(part_type='MB', socket='AM5', mem_type='DDR5'),
    3: dict(part_type='RAM', mem_type='DDR5'),
    4: dict(part_type='RAM', mem_type='DDR4'),
    5: dict(part_type='GPU'),
    6: dict(part_type='COOLER_CPU_AIO'),
    7: dict(part_type='CASE', cooler_height_mm=160),
}


def lines(*pairs):
    return [dict(key=i, slot=slot, spec_key=code, label=str(code)) for i, (slot, code) in enumerate(pairs)]


class Evaluate(unittest.TestCase):
    def test_pass(self):
        out = bc.evaluate(lines(('CPU', 1), ('MB', 2), ('RAM', 3), ('GPU', 5)), SPECS, RULES[:2])
        self.assertTrue(out['ok'])
        self.assertEqual([c['state'] for c in out['checks']], ['pass', 'pass', 'pass'])

    def test_each_ram_line_is_judged(self):
        out = bc.evaluate(lines(('CPU', 1), ('MB', 2), ('RAM', 3), ('RAM', 4), ('GPU', 5)), SPECS, RULES[:2])
        self.assertFalse(out['ok'])
        self.assertEqual([f['key'] for f in out['failures']], ['mem:3:1'])

    def test_missing_value_is_unknown_not_pass(self):
        specs = {**SPECS, 2: dict(part_type='MB', mem_type='DDR5')}
        out = bc.evaluate(lines(('CPU', 1), ('MB', 2), ('GPU', 5)), specs, RULES[:1])
        self.assertTrue(out['ok'])
        self.assertEqual(out['unknown'][0]['missing_fields'], ['socket'])

    def test_type_scoped_rule_skips_other_type(self):
        out = bc.evaluate(lines(('CASE', 7), ('COOLER', 6), ('GPU', 5)), SPECS, RULES[2:])
        self.assertEqual([c['key'] for c in out['checks']], ['display_output'])

    def test_display_output(self):
        self.assertEqual(bc.display_check(lines(('CPU', 1)), SPECS)['state'], 'fail')
        self.assertEqual(bc.display_check(lines(('CPU', 1), ('GPU', 5)), SPECS)['state'], 'pass')
        self.assertEqual(bc.display_check(lines(('CPU', 9)), SPECS)['state'], 'unknown')
        self.assertEqual(bc.display_check(lines(('CPU', 1)), {**SPECS, 1: dict(part_type='CPU', cpu_gpu=True)})['state'], 'pass')

    def test_no_rules_is_never_ok(self):
        self.assertFalse(bc.evaluate(lines(('CPU', 1), ('GPU', 5)), SPECS, [])['ok'])

    def test_product_lines_skip_unlinked(self):
        self.assertEqual(bc.product_lines([dict(slot='CPU', product_code=1), dict(slot='MB', product_code=None)]),
                         [dict(key=0, slot='CPU', spec_key=1, label='1')])


class PartsEditRejectsIncompatibleSave(unittest.TestCase):
    def test_failure_blocks_before_write(self):
        result = dict(preview_token='t', duplicate_id=None,
                      compat=dict(failures=[dict(label='메모리 규격 일치')]))
        body = edit.PartsEdit(revision=1, offer_id='P1', replacements=[dict(ordinal=0, code=1, quantity=1)], preview_token='t')
        conn = unittest.mock.Mock()
        with patch.object(edit, 'prepare', return_value=({}, [], [], result)):
            with self.assertRaises(HTTPException) as e:
                edit.save_parts(conn, 'A1', body, dict(operator_id=1))
        self.assertEqual(e.exception.status_code, 409)
        self.assertIn('메모리 규격 일치', e.exception.detail)
        conn.execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
