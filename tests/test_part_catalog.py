"""조립 부품 판매 준비 판정 (부품 상품화 1단계)."""
import importlib.util
import unittest
import unittest.mock
from pathlib import Path
from unittest.mock import patch

from api import part_catalog as pc

ROOT = Path(__file__).resolve().parents[1]
RULES = [
    dict(rule_key='cpu_mb_socket', slot='MB', field='socket', ref_slot='CPU', ref_field='socket', part_types=[], null_ref_mode=None),
    dict(rule_key='cooler_socket', slot='COOLER', field='socket_list', ref_slot='CPU', ref_field='socket', part_types=[], null_ref_mode=None),
    dict(rule_key='cooler_height', slot='COOLER', field='cooler_height_mm', ref_slot='CASE', ref_field='cooler_max_mm',
         part_types=['COOLER_CPU_AIR'], null_ref_mode=None),
    dict(rule_key='power', slot='POWER', field='rated_watt', ref_slot='GPU', ref_field='gpu_power_draw_watt', part_types=[], null_ref_mode='skip'),
]


def row(**kw):
    base = dict(product_code=1, slot='CPU', part_type='CPU', sale_status='판매중', sale_price=300000)
    base.update(kw)
    return base


class RequiredFields(unittest.TestCase):
    def test_left_and_reference_sides(self):
        self.assertEqual(pc.required_fields(RULES, 'CPU', 'CPU'), ['socket'])
        self.assertEqual(pc.required_fields(RULES, 'MB', 'MB'), ['socket'])

    def test_part_type_scoped_rule(self):
        self.assertEqual(pc.required_fields(RULES, 'COOLER', 'COOLER_CPU_AIR'), ['socket_list', 'cooler_height_mm'])
        self.assertEqual(pc.required_fields(RULES, 'COOLER', 'COOLER_CPU_AIO'), ['socket_list'])

    def test_type_scoped_reference_is_conditional(self):
        # 케이스의 쿨러 장착 높이는 공랭 쿨러와 짝지을 때만 필요하다.
        self.assertEqual(pc.required_fields(RULES, 'CASE', 'CASE'), [])
        self.assertEqual(pc.required_fields(RULES, 'CASE', 'CASE', conditional=True), ['cooler_max_mm'])
        v = pc.judge(row(slot='CASE', part_type='CASE'), {'part_type': 'CASE'}, RULES)
        self.assertEqual((v['state'], v['conditional_missing']), ('ready', ['cooler_max_mm']))

    def test_skip_mode_reference_is_not_required(self):
        # 그래픽카드 소비 전력이 없으면 파워 규칙은 「판정 못 함」으로 넘어간다 — 막힘으로 세지 않는다.
        self.assertEqual(pc.required_fields(RULES, 'GPU', 'GPU'), [])
        self.assertEqual(pc.required_fields(RULES, 'POWER', 'POWER'), ['rated_watt'])


class Judge(unittest.TestCase):
    def test_ready(self):
        v = pc.judge(row(), {'part_type': 'CPU', 'socket': 'AM5'}, RULES)
        self.assertEqual((v['state'], v['reasons'], v['missing_fields']), ('ready', [], []))

    def test_no_product_never_ready(self):
        v = pc.judge(row(product_code=None, sale_status=None, sale_price=None), {'part_type': 'CPU', 'socket': 'AM5'}, RULES)
        self.assertEqual(v['state'], 'no_product')
        self.assertEqual(v['reasons'], ['no_product'])

    def test_all_reasons_are_listed_in_order(self):
        v = pc.judge(row(sale_status='품절', sale_price=0), {'part_type': 'CPU'}, RULES)
        self.assertEqual(v['state'], 'not_on_sale')
        self.assertEqual(v['reasons'], ['not_on_sale', 'no_price', 'missing_specs'])
        self.assertEqual(v['missing_fields'], ['socket'])

    def test_empty_list_counts_as_missing(self):
        v = pc.judge(row(slot='COOLER', part_type='COOLER_CPU_AIO'), {'part_type': 'COOLER_CPU_AIO', 'socket_list': []}, RULES)
        self.assertEqual(v['missing_fields'], ['socket_list'])

    def test_no_specs_row(self):
        v = pc.judge(row(slot='MB', part_type='MB'), None, RULES)
        self.assertEqual((v['state'], v['missing_fields']), ('missing_specs', ['socket']))


class Summary(unittest.TestCase):
    def test_used_counts_only_active_configurations(self):
        items = [dict(state='ready', active_configuration_count=2), dict(state='no_product', active_configuration_count=1),
                 dict(state='missing_specs', active_configuration_count=0)]
        s = pc.summarize(items)
        self.assertEqual((s['total'], s['used']), (3, 2))
        self.assertEqual(s['used_by_state']['missing_specs'], 0)
        self.assertEqual(s['by_state']['missing_specs'], 1)

    def test_endpoint_filters_and_puts_blocked_first(self):
        items = [dict(code=1, slot='CPU', state='ready', active_configuration_count=5),
                 dict(code=2, slot='CPU', state='no_price', active_configuration_count=1),
                 dict(code=3, slot='GPU', state='missing_specs', active_configuration_count=0)]
        with patch.object(pc, 'load', return_value=(items, 4)), patch.object(pc, 'engine'):
            out = pc.catalog(state='', slot='', used=True, offset=0, limit=20)
            self.assertEqual([i['code'] for i in out['items']], [2, 1])
            out = pc.catalog(state='missing_specs', slot='', used=False, offset=0, limit=20)
            self.assertEqual([i['code'] for i in out['items']], [3])
        self.assertEqual(out['rule_count'], 4)


class PcsWithoutBom(unittest.TestCase):
    def test_lists_on_sale_complete_pcs_without_offer(self):
        self.assertIn("part_type = 'PC_COMPLETE'", pc.NO_BOM_SQL)
        self.assertIn("'P' || p.product_code::text", pc.NO_BOM_SQL)
        rows = [dict(product_code=120221, product_name='<b>[8600G/16G] 사무용</b> 회원가입 할인', sale_price=990000, stock_qty=0)]
        conn = unittest.mock.MagicMock()
        conn.__enter__.return_value.execute.return_value.mappings.return_value = rows
        with patch.object(pc, 'engine') as eng:
            eng.connect.return_value = conn
            out = pc.pcs_without_bom(offset=0, limit=20)
        self.assertEqual(out['total'], 1)
        self.assertNotIn('<b>', out['items'][0]['name'])


class Migration(unittest.TestCase):
    def test_view_only_and_reversible(self):
        p = ROOT / 'db/migrations/versions/0140_assembly_parts_view.py'
        spec = importlib.util.spec_from_file_location('m0140', p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        self.assertEqual((m.revision, m.down_revision), ('0140', '0139'))
        src = p.read_text(encoding='utf-8')
        body = src.split('def upgrade', 1)[1]
        for word in ('UPDATE ', 'DELETE ', 'INSERT ', 'ALTER TABLE', 'DROP TABLE'):
            self.assertNotIn(word, body.upper().split('DEF DOWNGRADE')[0])


class Screen(unittest.TestCase):
    def test_template_mounts_section_and_script(self):
        t = (ROOT / 'templates/admin/part_explanations.html.j2').read_text(encoding='utf-8')
        self.assertIn('id="pc-cat"', t)
        self.assertIn('/shared/part-catalog.js', t)
        js = (ROOT / 'mockups/shared/part-catalog.js').read_text(encoding='utf-8')
        self.assertIn('/api/admin/part-catalog', js)
        # 화면이 수를 세지 않는다 — 칩 수는 서버 summary 만 쓴다.
        self.assertIn('data.summary', js)


if __name__ == '__main__':
    unittest.main()
