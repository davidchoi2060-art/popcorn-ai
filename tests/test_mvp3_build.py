"""고객 부품 직접 바꾸기 — 금액 재계산과 호환 판정 (부품 상품화 3단계)."""
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from api import mvp3_build as b
from api import mvp3_handoff as h

RULES = [
    dict(rule_key='socket', label='CPU-보드 소켓', slot='MB', field='socket', ref_slot='CPU', ref_field='socket',
         op='eq', part_types=[], null_ref_mode=None, ref_offset=None, detail_fmt=None),
    dict(rule_key='power', label='파워 용량', slot='POWER', field='rated_watt', ref_slot='GPU',
         ref_field='gpu_power_draw_watt', op='gte', part_types=[], null_ref_mode='skip', ref_offset=0, detail_fmt=None),
]
# 판매 PC 의 구성표: CPU(1) · 보드(2) · GPU(3) · 파워(4) · 조립비(5, 가상 줄)
BOM = [
    dict(ordinal=1, slot='CPU', quantity=1, pseudo=False, product_code=101, name='CPU A', sale_price=300000, status='판매중'),
    dict(ordinal=2, slot='MB', quantity=1, pseudo=False, product_code=201, name='보드 AM5', sale_price=200000, status='판매중'),
    dict(ordinal=3, slot='GPU', quantity=1, pseudo=False, product_code=301, name='GPU A', sale_price=500000, status='판매중'),
    dict(ordinal=4, slot='POWER', quantity=1, pseudo=False, product_code=401, name='파워 700W', sale_price=90000, status='판매중'),
    dict(ordinal=5, slot='ETC', quantity=1, pseudo=True, product_code=None, name='조립비', sale_price=None, status=None),
]
SPECS = {
    101: dict(part_type='CPU', socket='AM5', cpu_gpu=False),
    102: dict(part_type='CPU', socket='AM5', cpu_gpu=True),
    103: dict(part_type='CPU', socket='LGA1700', cpu_gpu=True),
    104: dict(part_type='CPU', socket=None),
    201: dict(part_type='MB', socket='AM5'),
    301: dict(part_type='GPU', gpu_power_draw_watt=300),
    302: dict(part_type='GPU', gpu_power_draw_watt=None),
    401: dict(part_type='POWER', rated_watt=700),
}
PARTS = {
    102: dict(product_code=102, product_name='CPU B', sale_price=350000, status='판매중', part_type='CPU'),
    103: dict(product_code=103, product_name='CPU C', sale_price=250000, status='판매중', part_type='CPU'),
    105: dict(product_code=105, product_name='CPU 품절', sale_price=250000, status='품절', part_type='CPU'),
    302: dict(product_code=302, product_name='GPU B', sale_price=450000, status='판매중', part_type='GPU'),
}


class Rows:
    def __init__(self, rows): self.rows = rows
    def mappings(self): return iter(self.rows)


class Conn:
    def __init__(self, candidates=()): self.candidates = list(candidates)
    def execute(self, sql, p=None):
        sql = str(sql)
        if 'FROM products WHERE product_code = ANY' in sql:
            return Rows([PARTS[c] for c in p['codes'] if c in PARTS])
        if 'JOIN product_specs' in sql:
            return Rows([PARTS[c] for c in self.candidates])
        raise AssertionError(sql)


def change(ordinal, code):
    return b.Change(ordinal=ordinal, product_code=code)


class Apply(unittest.TestCase):
    def test_delta_and_new_line(self):
        lines, applied = b.apply_changes(BOM, [change(1, 102)], PARTS)
        self.assertEqual(applied[0]['delta'], 50000)
        self.assertEqual((applied[0]['before']['product_code'], applied[0]['after']['product_code']), (101, 102))
        self.assertEqual(next(l for l in lines if l['ordinal'] == 1)['product_code'], 102)

    def test_guards(self):
        for changes, status in (([change(5, 102)], 422),            # 조립비 줄
                                ([change(1, 105)], 409),            # 품절
                                ([change(1, 302)], 422),            # 다른 종류
                                ([change(1, 102), change(1, 103)], 422)):  # 같은 줄 두 번
            with self.assertRaises(HTTPException) as e:
                b.apply_changes(BOM, changes, PARTS)
            self.assertEqual(e.exception.status_code, status)

    def test_same_part_is_no_change(self):
        parts = {**PARTS, 101: dict(product_code=101, product_name='CPU A', sale_price=300000, status='판매중', part_type='CPU')}
        _, applied = b.apply_changes(BOM, [change(1, 101)], parts)
        self.assertEqual(applied, [])


class Quote(unittest.TestCase):
    def run_quote(self, changes):
        with patch.object(b, 'load_specs', return_value=SPECS):
            return b.quote(Conn(), 1200000, BOM, changes, RULES)

    def test_total_is_base_plus_delta(self):
        q = self.run_quote([change(1, 102), change(3, 302)])
        self.assertEqual(q['total'], 1200000 + 50000 - 50000)
        self.assertEqual([c['ordinal'] for c in q['changes']], [1, 3])
        self.assertEqual(q['compat']['failures'], [])

    def test_incompatible_change_is_refused(self):
        with self.assertRaises(HTTPException) as e:
            self.run_quote([change(1, 103)])
        self.assertEqual(e.exception.status_code, 409)
        self.assertIn('CPU-보드 소켓', e.exception.detail)

    def test_no_change_returns_base(self):
        q = self.run_quote([])
        self.assertEqual((q['total'], q['changes']), (1200000, []))


class Touches(unittest.TestCase):
    def test_key_parts_not_substrings(self):
        self.assertTrue(b.touches(dict(key='socket:2:1'), [1]))
        self.assertFalse(b.touches(dict(key='socket:12:11'), [1]))
        self.assertFalse(b.touches(dict(key='socket'), [1]))

    def test_skip_rule_with_missing_reference_is_settled(self):
        by = {r['rule_key']: r for r in RULES}
        self.assertTrue(b.settled(dict(key='power:4:3', state='unknown', missing_fields=['gpu_power_draw_watt']), by))
        self.assertFalse(b.settled(dict(key='power:4:3', state='unknown', missing_fields=['rated_watt']), by))
        self.assertFalse(b.settled(dict(key='socket:2:1', state='unknown', missing_fields=['socket']), by))


class Options(unittest.TestCase):
    def test_only_passing_candidates(self):
        PARTS[104] = dict(product_code=104, product_name='CPU 사양 없음', sale_price=280000, status='판매중', part_type='CPU')
        try:
            with patch.object(b, 'load_specs', return_value=SPECS):
                res = b.options_for(Conn([102, 103, 104]), [dict(l) for l in BOM], 1, RULES)
        finally:
            del PARTS[104]
        self.assertEqual([o['product_code'] for o in res['options']], [102])
        self.assertEqual(res['options'][0]['price_diff'], 50000)
        self.assertEqual((res['checked'], res['untested']), (3, 1))

    def test_gpu_without_power_draw_is_offered(self):
        # 파워 규칙은 GPU 소비 전력이 없으면 엔진도 넘긴다(null_ref_mode skip).
        with patch.object(b, 'load_specs', return_value=SPECS):
            res = b.options_for(Conn([302]), [dict(l) for l in BOM], 3, RULES)
        self.assertEqual([o['product_code'] for o in res['options']], [302])

    def test_pseudo_line_cannot_be_swapped(self):
        with self.assertRaises(HTTPException) as e:
            b.options_for(Conn(), [dict(l) for l in BOM], 5, RULES)
        self.assertEqual(e.exception.status_code, 422)


class Handoff(unittest.TestCase):
    def test_build_read_from_snapshot(self):
        snap = {'price': 1250000, 'build': {'base_price': 1200000, 'changes': [{'ordinal': 1, 'delta': 50000}]}}
        self.assertEqual(h._build(snap)['base_price'], 1200000)
        self.assertIsNone(h._build({'price': 1200000}))
        self.assertIsNone(h._build({'build': {'base_price': 1, 'changes': []}}))


# 2026-10-11 코덱스 검수: 영상 PC 에서 노트북 DDR5 로 바꾸기가 받아들여졌다(mem 규칙은 DDR 세대만 본다).
MEM_RULE = dict(rule_key='mem', label='메모리-보드 규격', slot='RAM', field='mem_type', ref_slot='MB', ref_field='mem_type',
                op='eq', part_types=[], null_ref_mode='block', ref_offset=None, detail_fmt=None)
RAM_BOM = BOM[:2] + [dict(ordinal=6, slot='RAM', quantity=2, pseudo=False, product_code=601, name='램 16GB', sale_price=60000, status='판매중')] + BOM[2:]
RAM_SPECS = {**SPECS, 201: dict(part_type='MB', socket='AM5', mem_type='DDR5'), 601: dict(part_type='RAM', mem_type='DDR5'),
             602: dict(part_type='RAM', mem_type='DDR5'), 603: dict(part_type='RAM', mem_type='DDR5'),
             604: dict(part_type='RAM', mem_type='DDR5'), 605: dict(part_type='RAM', mem_type='DDR4'),
             606: dict(part_type='RAM', mem_type=None)}
RAM_PARTS = {
    602: dict(product_code=602, product_name='삼성 DDR5 32GB', sale_price=110000, status='판매중', part_type='RAM',
              spec_source_text='삼성전자 / 데스크탑용 / DDR5 / 32GB'),
    603: dict(product_code=603, product_name='Crucial 노트북 DDR5-5600 16GB', sale_price=55000, status='판매중', part_type='RAM',
              spec_source_text='마이크론 / DDR5 / 16GB'),
    604: dict(product_code=604, product_name='Crucial DDR5 16GB', sale_price=56000, status='판매중', part_type='RAM',
              spec_source_text='마이크론 / 노트북 / DDR5 / 16GB'),
    605: dict(product_code=605, product_name='DDR4 16GB', sale_price=40000, status='판매중', part_type='RAM', spec_source_text=''),
    606: dict(product_code=606, product_name='사양 없는 램', sale_price=50000, status='판매중', part_type='RAM', spec_source_text=''),
}


class RamConn(Conn):
    def execute(self, sql, p=None):
        sql = str(sql)
        if 'FROM products WHERE product_code = ANY' in sql:
            return Rows([RAM_PARTS[c] for c in p['codes'] if c in RAM_PARTS])
        if 'JOIN product_specs' in sql:
            return Rows([RAM_PARTS[c] for c in self.candidates])
        raise AssertionError(sql)


class DesktopRam(unittest.TestCase):
    rules = RULES + [MEM_RULE]

    def quote(self, code, bom=RAM_BOM):
        with patch.object(b, 'load_specs', return_value=RAM_SPECS):
            return b.quote(RamConn(), 1500000, bom, [change(6, code)], self.rules)

    def test_options_hide_laptop_and_unknown_memory(self):
        with patch.object(b, 'load_specs', return_value=RAM_SPECS):
            res = b.options_for(RamConn([602, 603, 604, 605, 606]), [dict(l) for l in RAM_BOM], 6, self.rules)
        self.assertEqual([o['product_code'] for o in res['options']], [602])
        self.assertEqual(res['options'][0]['price_diff'], 100000)   # 수량 2 x 50,000
        self.assertEqual(res['untested'], 1)                        # 606 사양 없음

    def test_direct_quote_refuses_what_the_list_hides(self):
        for code in (603, 604, 605, 606):
            with self.assertRaises(HTTPException) as e:
                self.quote(code)
            self.assertEqual(e.exception.status_code, 409, code)
        self.assertEqual(self.quote(602)['total'], 1600000)

    def test_rule_with_no_board_is_not_a_pass(self):
        # 보드 줄이 없으면 mem 규칙은 줄 번호 없는 unknown 하나다 — 바꾼 램을 본 판정이 없으므로 받지 않는다.
        with self.assertRaises(HTTPException) as e:
            self.quote(602, bom=[l for l in RAM_BOM if l['slot'] != 'MB'])
        self.assertIn('확인하지 못해', e.exception.detail)

    def test_no_active_rules_is_not_a_pass(self):
        with patch.object(b, 'load_specs', return_value=RAM_SPECS), self.assertRaises(HTTPException):
            b.quote(RamConn(), 1500000, RAM_BOM, [change(6, 602)], [])

    def test_unknown_cpu_socket_is_refused_on_direct_quote(self):
        PARTS[104] = dict(product_code=104, product_name='CPU 사양 없음', sale_price=280000, status='판매중', part_type='CPU')
        try:
            with patch.object(b, 'load_specs', return_value=SPECS), self.assertRaises(HTTPException) as e:
                b.quote(Conn(), 1200000, BOM, [change(1, 104)], RULES)
        finally:
            del PARTS[104]
        self.assertIn('CPU-보드 소켓', e.exception.detail)


if __name__ == '__main__':
    unittest.main()
