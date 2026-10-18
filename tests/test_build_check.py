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


class CasePowerForm(unittest.TestCase):
    """케이스-파워 규격(0160): 둘 다 알 때만 판정하고, 표기가 달라도 같은 규격이면 통과한다."""
    RULE = dict(rule_id=9, rule_key='case_psu_form', slot='POWER', field='form_factor', op='in', ref_slot='CASE',
                ref_field='psu_form_factor_list', label='파워 규격 수용', detail_fmt='{v} 파워 · 케이스 지원 {r}',
                part_types=[], ref_offset=0, null_ref_mode='skip_any')

    def judge(self, power, case):
        specs = {1: dict(part_type='CASE', psu_form_factor_list=case), 2: dict(part_type='POWER', form_factor=power)}
        out = bc.evaluate([dict(key=0, slot='CASE', spec_key=1, label='케이스'),
                           dict(key=1, slot='POWER', spec_key=2, label='파워')], specs, [self.RULE], display=False)
        return [c['state'] for c in out['checks']]

    def test_slim_power_in_atx_case_fails(self):
        self.assertEqual(self.judge('TFX', ['ATX']), ['fail'])

    def test_same_form_with_other_spelling_passes(self):
        self.assertEqual(self.judge('ATX', ['ATX']), ['pass'])
        self.assertEqual(self.judge('Flex-ATX', ['FLEX']), ['pass'])

    def test_unknown_either_side_is_not_judged(self):
        self.assertEqual(self.judge(None, ['ATX']), [])
        self.assertEqual(self.judge('TFX', None), [])
        self.assertEqual(self.judge('TFX', []), [])
        self.assertEqual(self.judge('mini-ITX', ['ATX']), [])    # 파워 규격이 아닌 값

    def test_engine_verdict_matches(self):
        from api.recommend import rule_verdict
        self.assertFalse(rule_verdict(self.RULE, 'TFX', ['ATX']))
        self.assertTrue(rule_verdict(self.RULE, 'SFX', ['ATX', 'SFX']))
        self.assertIsNone(rule_verdict(self.RULE, None, ['ATX']))
        self.assertIsNone(rule_verdict(self.RULE, 'ATX', None))
