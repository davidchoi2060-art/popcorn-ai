"""MVP3 부품 직접 고르기(api/mvp3_free_build) — DB 없이 판정·채우기·가격 노출을 본다."""
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from api import mvp3_free_build as F
from api.orders import ASSEMBLY_FEE


def row(code, part_type, name, price, raw='', maker=None):
    return dict(product_code=code, product_name=name, sale_price=price, status='판매중', part_type=part_type,
                spec_source_text=raw, maker=maker)


ROWS = [
    row(1, 'CPU', '인텔 코어i9-14세대 14900K (랩터레이크 리프레시)', 700000, maker='인텔'),
    row(2, 'CPU', '인텔 코어i5-14세대 14400F', 250000, maker='인텔'),
    row(3, 'CPU', 'AMD 라이젠7-6세대 9700X', 450000, maker='AMD'),
    row(10, 'MB', 'ASUS PRIME B760M-A D5', 150000, '슬롯: 4 / 최대 192(GB)'),
    row(11, 'MB', 'MSI B650M 박격포', 200000, '슬롯: 4 / 최대 192(GB)'),
    row(12, 'MB', 'ASRock H610M-HDV DDR4', 90000, '슬롯: 2 / 최대 64(GB)'),
    row(20, 'RAM', '삼성전자 DDR5-5600 (16GB)', 60000),
    row(21, 'RAM', '삼성전자 DDR5-5600 (32GB)', 130000),
    row(22, 'RAM', 'TeamGroup DDR4-3200 (16GB)', 40000),
    row(23, 'RAM', '삼성전자 노트북 DDR5-5600 (32GB)', 90000, 'SO-DIMM'),
    row(30, 'GPU', 'MSI 지포스 RTX 5060 Ti 벤투스 2X OC D7 8GB', 600000),
    row(31, 'GPU', 'MSI 지포스 RTX 5060 벤투스 2X OC D7 8GB', 450000),
    row(32, 'GPU', 'ZOTAC RTX 5070 Ti', 1100000),
    row(40, 'CASE', '앱코 미들타워 케이스', 50000),
    row(50, 'COOLER_CPU_AIR', '쿨러 A', 30000),
    row(60, 'SSD', 'WD SN580 M.2 NVMe (500GB)', 60000),
    row(61, 'SSD', 'WD SN580 M.2 NVMe (1TB)', 90000),
    row(62, 'SSD', '구형 SSD (256GB)', 30000),
    row(70, 'POWER', '파워 500W', 50000),
    row(71, 'POWER', '파워 750W', 90000),
]
SPECS = {
    1: dict(part_type='CPU', socket='LGA1700', cpu_gpu=True), 2: dict(part_type='CPU', socket='LGA1700', cpu_gpu=False),
    3: dict(part_type='CPU', socket='AM5', cpu_gpu=True),
    10: dict(part_type='MB', socket='LGA1700', mem_type='DDR5'), 11: dict(part_type='MB', socket='AM5', mem_type='DDR5'),
    12: dict(part_type='MB', socket='LGA1700', mem_type='DDR4'),
    20: dict(part_type='RAM', mem_type='DDR5', capacity_gb=16), 21: dict(part_type='RAM', mem_type='DDR5', capacity_gb=32),
    22: dict(part_type='RAM', mem_type='DDR4', capacity_gb=16), 23: dict(part_type='RAM', mem_type='DDR5', capacity_gb=32),
    30: dict(part_type='GPU', gpu_watt=650), 31: dict(part_type='GPU', gpu_watt=550), 32: dict(part_type='GPU', gpu_watt=750),
    40: dict(part_type='CASE'), 50: dict(part_type='COOLER_CPU_AIR', socket_list=['LGA1700']),
    60: dict(part_type='SSD', capacity_gb=500), 61: dict(part_type='SSD', capacity_gb=1000), 62: dict(part_type='SSD', capacity_gb=256),
    70: dict(part_type='POWER', watt=500), 71: dict(part_type='POWER', watt=750),
}
RULES = [
    dict(rule_key='socket', label='CPU 소켓', slot='MB', ref_slot='CPU', field='socket', ref_field='socket', op='eq',
         part_types=[], ref_offset=0, null_ref_mode='block'),
    dict(rule_key='mem', label='메모리 규격', slot='RAM', ref_slot='MB', field='mem_type', ref_field='mem_type', op='eq',
         part_types=[], ref_offset=0, null_ref_mode='block'),
    dict(rule_key='power', label='파워 용량', slot='POWER', ref_slot='GPU', field='watt', ref_field='gpu_watt', op='gte',
         part_types=[], ref_offset=0, null_ref_mode='skip'),
    dict(rule_key='cooler_socket', label='쿨러 소켓', slot='COOLER', ref_slot='CPU', field='socket_list', ref_field='socket',
         op='contains', part_types=[], ref_offset=0, null_ref_mode='block'),
]


def specs_for(_conn, codes):
    return {c: SPECS[c] for c in codes if c in SPECS}


def load_rows(_conn, codes=None):
    return [dict(r) for r in ROWS if codes is None or r['product_code'] in codes]


class ParseTests(unittest.TestCase):
    def test_owner_example(self):
        c = F.parse_text('메모리 32기가, RTS 5060ti, CPU는 i9 시리즈')
        self.assertEqual(c.ram_gb, 32)
        self.assertEqual(c.gpu, 'RTX 5060 TI')
        self.assertEqual(c.cpu, 'i9')

    def test_other_words(self):
        c = F.parse_text('라이젠 7 9700X에 램 64GB, SSD 2TB, RX 9070 XT')
        self.assertEqual((c.ram_gb, c.ssd_gb, c.gpu), (64, 2000, 'RX 9070 XT'))
        self.assertTrue(c.cpu.startswith('라이젠 7'))
        self.assertEqual(F.parse_text('인텔로 맞춰 주세요').platform, '인텔')
        self.assertEqual(F.parse_text('그냥 좋은 걸로').model_dump(exclude_none=True), {})

    def test_gpu_match_keeps_suffix(self):
        want = F.gpu_model('RTX 5060 Ti')
        self.assertTrue(F.gpu_matches('MSI 지포스 RTX 5060 Ti 벤투스 2X OC D7 8GB', want))
        self.assertFalse(F.gpu_matches('MSI 지포스 RTX 5060 벤투스 2X OC D7 8GB', want))
        self.assertFalse(F.gpu_matches('ZOTAC RTX 5070 Ti', want))
        self.assertTrue(F.gpu_matches('MSI RTX 5060 벤투스', F.gpu_model('5060')))

    def test_cpu_series_and_model(self):
        i9 = F.cpu_rule('i9 시리즈')
        self.assertTrue(i9('인텔 코어i9-14세대 14900K'))
        self.assertFalse(i9('인텔 코어i5-14세대 14400F'))
        k = F.cpu_rule('14900K')
        self.assertTrue(k('인텔 코어i9-14세대 14900K'))
        self.assertFalse(k('인텔 코어i9-14세대 14900KF'))
        self.assertTrue(F.cpu_rule('라이젠 7')('AMD 라이젠7-6세대 9700X'))
        self.assertIsNone(F.cpu_rule('빠른 거'))

    def test_ultra_exact_model_is_not_reduced_to_series(self):
        for request in ('인텔 코어 울트라 7 265K', 'Ultra 7 265K', '265K'):
            with self.subTest(request=request):
                self.assertIn('265K', F.parse_text(request).cpu)
                match = F.cpu_rule(request)
                self.assertTrue(match('인텔 코어 울트라 7 265K'))
                self.assertFalse(match('인텔 코어 울트라 7 255H'))
                self.assertFalse(match('인텔 코어 울트라 7 265KF'))
        self.assertIsNone(F.cpu_rule('Ultra 7 265ZZ'))
        self.assertIsNone(F.cpu_rule('i9 14900ZZ'))
        self.assertIn('265ZZ', F.parse_text('Ultra 7 265ZZ').cpu)
        self.assertIn('265V', F.parse_text('Ultra 7 265V').cpu)
        self.assertFalse(F.cpu_rule(F.parse_text('Ultra 7 265V').cpu)('인텔 코어 울트라 7 265K'))

    def test_exact_cpu_keeps_missing_suffix_brand_and_series(self):
        for request, exact, wrong in (
                ('Ultra 7 265', '인텔 코어 울트라 7 265', '인텔 코어 울트라 7 265K'),
                ('i9-14900', '인텔 코어i9-14900', '인텔 코어i9-14900KF'),
                ('인텔 i7-6700', '인텔 코어i7-6700', 'AMD A10-6700'),
                ('인텔 i7-6700', '인텔 코어i7-6700', '인텔 코어i5-6700')):
            with self.subTest(request=request, wrong=wrong):
                match = F.cpu_rule(request)
                self.assertTrue(match(exact))
                self.assertFalse(match(wrong))
        self.assertTrue(F.cpu_rule('i9')('인텔 코어i9-14900KF'))
        self.assertTrue(F.cpu_rule('라이젠 7')('AMD 라이젠7-9700X'))

    def test_text_keeps_unsupported_suffix_instead_of_cutting_it(self):
        for request, model in (('i9 14900ZZ', '14900ZZ'), ('i9 14900KFZZ', '14900KFZZ'),
                               ('라이젠7 9700ZZ', '9700ZZ')):
            with self.subTest(request=request):
                condition = F.parse_text(request)
                self.assertIn(model, condition.cpu)
                self.assertIsNone(F.cpu_rule(condition.cpu))

    def test_space_separated_cpu_suffix_stays_in_exact_model(self):
        for request, wanted, wrong in (
                ('i9 14900 K', '인텔 코어i9-14900K', '인텔 코어i9-14900'),
                ('i9 14900 KF', '인텔 코어i9-14900KF', '인텔 코어i9-14900K'),
                ('Ryzen 7 9700 X', 'AMD Ryzen 7 9700X', 'AMD Ryzen 7 9700'),
                ('Ultra 7 265 K', '인텔 코어 Ultra 7 265K', '인텔 코어 Ultra 7 265')):
            with self.subTest(request=request):
                condition = F.parse_text(request)
                self.assertTrue(F.cpu_rule(condition.cpu)(wanted))
                self.assertFalse(F.cpu_rule(condition.cpu)(wrong))
                self.assertTrue(F.cpu_rule(request)(wanted))

    def test_korean_explanation_after_number_is_not_a_model_suffix(self):
        for request, model, wanted in (
                ('i9 14900 게임용으로 부탁해요', '14900', '인텔 코어i9-14900'),
                ('Ryzen 7 9700 사무용으로 부탁해요', '9700', 'AMD Ryzen 7 9700'),
                ('Ultra 7 265 기본형으로 부탁해요', '265', '인텔 코어 Ultra 7 265')):
            with self.subTest(request=request):
                condition = F.parse_text(request)
                self.assertTrue(condition.cpu.endswith(model))
                self.assertTrue(F.cpu_rule(condition.cpu)(wanted))

    def test_space_separated_unknown_suffix_is_not_silently_cut(self):
        for request, token in (('i9 14900 ZZ', '14900ZZ'), ('i9 14900 KFZZ', '14900KFZZ'),
                               ('Ryzen 7 9700 ZZ', '9700ZZ')):
            with self.subTest(request=request):
                condition = F.parse_text(request)
                self.assertIn(token, condition.cpu)
                self.assertIsNone(F.cpu_rule(condition.cpu))

    def test_next_part_clause_is_not_a_cpu_suffix(self):
        for request, cpu, other in (
                ('i9 14900 RAM 32GB', 'i9 14900', {'ram_gb': 32}),
                ('i9 14900 RTX 5060 Ti', 'i9 14900', {'gpu': 'RTX 5060 TI'}),
                ('Ultra7 265 SSD 1TB', 'Ultra7 265', {'ssd_gb': 1000}),
                ('i9 14900 K RAM 32GB', 'i9 14900K', {'ram_gb': 32}),
                ('i9 14900 SSD1TB', 'i9 14900', {'ssd_gb': 1000}),
                ('Ryzen 7 9700 X RTX 5060 Ti', 'Ryzen 7 9700X', {'gpu': 'RTX 5060 TI'})):
            with self.subTest(request=request):
                condition = F.parse_text(request)
                self.assertEqual(condition.cpu, cpu)
                self.assertIsNotNone(F.cpu_rule(condition.cpu))
                for key, expected in other.items():
                    self.assertEqual(getattr(condition, key), expected)


@patch.object(F, 'load_specs', side_effect=specs_for)
@patch.object(F, 'load', side_effect=load_rows)
class BuildTests(unittest.TestCase):
    def start(self, **cond):
        return F.start_build(None, F.Conditions(**cond), RULES)

    def test_owner_example_fills_the_rest(self, *_):
        res = self.start(**F.parse_text('메모리 32기가, RTS 5060ti, CPU는 i9 시리즈').model_dump())
        by = {l['slot']: l for l in res['lines']}
        self.assertEqual(by['CPU']['product_code'], 1)
        self.assertEqual(by['GPU']['product_code'], 30)
        self.assertEqual(by['MB']['product_code'], 12)          # 소켓이 맞는 보드 중 가장 싼 DDR4 보드
        self.assertEqual((by['RAM']['product_code'], by['RAM']['quantity']), (22, 2))  # 그 보드에 맞는 DDR4 16GB × 2
        self.assertEqual(by['POWER']['product_code'], 71)       # 500W 는 650W 그래픽카드를 못 받는다
        self.assertEqual(by['SSD']['product_code'], 60)         # 말하지 않으면 500GB 이상 중 싼 것
        self.assertTrue(by['CPU']['from_request'] and by['GPU']['from_request'] and by['RAM']['from_request'])
        self.assertFalse(by['MB']['from_request'])
        expected = 700000 + 90000 + 40000 * 2 + 600000 + 50000 + 30000 + 60000 + 90000 + ASSEMBLY_FEE
        self.assertEqual(res['total'], expected)

    def test_no_part_price_in_lines(self, *_):
        res = self.start(cpu='i9')
        for line in res['lines']:
            self.assertFalse({'price', 'sale_price', 'cost', 'row'} & set(line), line)

    def test_integrated_graphics_when_gpu_not_asked(self, *_):
        by = {l['slot']: l for l in self.start(cpu='i9')['lines']}
        self.assertIsNone(by['GPU']['product_code'])
        self.assertEqual(by['GPU']['name'], 'CPU 내장 그래픽')
        # 내장 그래픽이 없는 CPU 면 그래픽카드를 넣는다
        by = {l['slot']: l for l in self.start(cpu='14400F')['lines']}
        self.assertEqual(by['GPU']['product_code'], 31)

    def test_cooler_left_empty_when_none_fits(self, *_):
        res = self.start(cpu='라이젠 7')             # 쿨러 A 는 LGA1700 만 받는다
        by = {l['slot']: l for l in res['lines']}
        self.assertEqual(by['MB']['product_code'], 11)
        self.assertIsNone(by['COOLER']['product_code'])
        self.assertIn(F.WARNING_COOLER, res['warnings'])

    def test_unmatched_condition_is_named(self, *_):
        with self.assertRaises(HTTPException) as e:
            self.start(gpu='RTX 5090')
        self.assertEqual(e.exception.status_code, 409)
        self.assertEqual(e.exception.detail['unmatched'][0]['slot'], 'GPU')

    def test_unreadable_structured_cpu_is_rejected_before_catalog(self, *_):
        for cpu in ('빠른 거', '', '   ', 'Ultra 7 265ZZ'):
            with self.subTest(cpu=cpu), patch.object(F, 'load', side_effect=AssertionError('must reject before DB read')):
                with self.assertRaises(HTTPException) as e:
                    self.start(cpu=cpu)
                self.assertEqual(e.exception.status_code, 422)

    def test_text_with_unsupported_cpu_suffix_is_rejected_before_catalog(self, *_):
        for request in ('i9 14900ZZ', 'i9 14900KFZZ', '라이젠7 9700ZZ',
                        'i9 14900 ZZ', 'i9 14900 KFZZ', 'Ryzen 7 9700 ZZ'):
            with self.subTest(request=request), patch.object(F, 'load', side_effect=AssertionError('must reject before DB read')):
                with self.assertRaises(HTTPException) as e:
                    F.start_build(None, F.parse_text(request), RULES)
                self.assertEqual(e.exception.status_code, 422)

    def test_text_spaced_model_suffix_selects_exact_variant(self, *_):
        models = [row(203, 'CPU', '인텔 코어i9-14900KF', 200000), row(204, 'CPU', '인텔 코어i9-14900', 100000)]
        with patch(__name__ + '.ROWS', ROWS + models), patch.dict(SPECS, {203: dict(SPECS[1]), 204: dict(SPECS[1])}):
            for request, code in (('i9 14900 K', 1), ('i9 14900 KF', 203),
                                  ('Ryzen 7 9700 X', 3), ('i9 14900 게임용으로 부탁해요', 204)):
                with self.subTest(request=request):
                    res = F.start_build(None, F.parse_text(request), RULES)
                    self.assertEqual(next(l for l in res['lines'] if l['slot'] == 'CPU')['product_code'], code)

    def test_multi_part_text_build_preserves_cpu_and_other_requests(self, *_):
        models = [row(204, 'CPU', '인텔 코어i9-14900', 100000), row(205, 'CPU', '인텔 코어 Ultra7 265', 200000)]
        with patch(__name__ + '.ROWS', ROWS + models), patch.dict(SPECS, {204: dict(SPECS[1]), 205: dict(SPECS[1])}):
            for request, cpu_code, other_slot, other_code in (
                    ('i9 14900 RAM 32GB', 204, 'RAM', 22),
                    ('i9 14900 RTX 5060 Ti', 204, 'GPU', 30),
                    ('Ultra7 265 SSD 1TB', 205, 'SSD', 61)):
                with self.subTest(request=request):
                    res = F.start_build(None, F.parse_text(request), RULES)
                    by = {l['slot']: l for l in res['lines']}
                    self.assertEqual(by['CPU']['product_code'], cpu_code)
                    self.assertEqual(by[other_slot]['product_code'], other_code)
                    if other_slot == 'RAM':
                        self.assertEqual(by['RAM']['quantity'], 2)

    def test_requested_ultra_model_does_not_pick_cheaper_same_series(self, *_):
        # 호환 사양은 합성 fixture다. 실제 제품 지원 여부를 주장하지 않는다.
        models = [row(201, 'CPU', '인텔 코어 울트라 7 255H', 100000),
                  row(202, 'CPU', '인텔 코어 울트라 7 265K', 200000)]
        with patch(__name__ + '.ROWS', ROWS + models), patch.dict(SPECS, {201: dict(SPECS[1]), 202: dict(SPECS[1])}):
            res = self.start(cpu='인텔 코어 울트라 7 265K')
        cpu = next(l for l in res['lines'] if l['slot'] == 'CPU')
        self.assertEqual(cpu['product_code'], 202)
        self.assertTrue(cpu['from_request'])

    def test_ssd_quantity_respects_known_board_capacity(self, *_):
        res = self.start(cpu='i9')
        parts = [F.Pick(slot=l['slot'], product_code=l['product_code'], quantity=2 if l['slot'] == 'SSD' else l['quantity'])
                 for l in res['lines'] if l['product_code']]
        for kind, key in (('M.2', 'm2_slots'), ('2.5 SATA', 'sata_ports')):
            for limit in (1, None):
                with self.subTest(kind=kind, limit=limit), patch.dict(SPECS, {
                        12: dict(SPECS[12], **{key: limit}), 60: dict(SPECS[60], form_factor=kind)}):
                    with self.assertRaises(HTTPException) as e:
                        F.quote_build(None, parts, RULES)
                    self.assertEqual(e.exception.status_code, 409)
            with patch.dict(SPECS, {12: dict(SPECS[12], **{key: 2}), 60: dict(SPECS[60], form_factor=kind)}):
                _, quote = F.quote_build(None, parts, RULES)
            self.assertEqual(next(l for l in quote['lines'] if l['slot'] == 'SSD')['quantity'], 2)

    def test_board_options_keep_room_for_both_ssds(self, *_):
        parts = [F.Pick(slot='CPU', product_code=1), F.Pick(slot='MB', product_code=10), F.Pick(slot='RAM', product_code=20),
                 F.Pick(slot='CASE', product_code=40), F.Pick(slot='COOLER', product_code=50),
                 F.Pick(slot='SSD', product_code=60, quantity=2), F.Pick(slot='POWER', product_code=70)]
        boards = [row(13, 'MB', '합성 DDR5 보드 M.2 하나', 130000), row(14, 'MB', '합성 DDR5 보드 M.2 둘', 140000)]
        with patch(__name__ + '.ROWS', ROWS + boards), patch.dict(SPECS, {
                10: dict(SPECS[10], m2_slots=2), 13: dict(SPECS[10], m2_slots=1),
                14: dict(SPECS[10], m2_slots=2), 60: dict(SPECS[60], form_factor='M.2')}):
            res = F.options_build(None, parts, 'MB', RULES)
        codes = {o['product_code'] for o in res['options']}
        self.assertNotIn(13, codes)
        self.assertIn(14, codes)

    def test_quote_rejects_incompatible(self, *_):
        parts = [F.Pick(slot='CPU', product_code=3), F.Pick(slot='MB', product_code=10), F.Pick(slot='RAM', product_code=21),
                 F.Pick(slot='CASE', product_code=40), F.Pick(slot='SSD', product_code=60), F.Pick(slot='POWER', product_code=70)]
        with self.assertRaises(HTTPException) as e:
            F.quote_build(None, parts, RULES)
        self.assertIn('CPU 소켓', e.exception.detail)

    def test_quote_refuses_laptop_ram_and_wrong_slot(self, *_):
        parts = [F.Pick(slot='CPU', product_code=1), F.Pick(slot='MB', product_code=10), F.Pick(slot='RAM', product_code=23),
                 F.Pick(slot='CASE', product_code=40), F.Pick(slot='SSD', product_code=60), F.Pick(slot='POWER', product_code=70)]
        with self.assertRaises(HTTPException):
            F.quote_build(None, parts, RULES)
        with self.assertRaises(HTTPException):
            F.quote_build(None, [F.Pick(slot='GPU', product_code=1)] + parts[1:], RULES)

    def test_options_show_diff_only_and_compatible(self, *_):
        parts = [F.Pick(slot='CPU', product_code=1), F.Pick(slot='MB', product_code=10), F.Pick(slot='RAM', product_code=20, quantity=2),
                 F.Pick(slot='GPU', product_code=30), F.Pick(slot='CASE', product_code=40), F.Pick(slot='COOLER', product_code=50),
                 F.Pick(slot='SSD', product_code=60), F.Pick(slot='POWER', product_code=71)]
        _, base = F.quote_build(None, parts, RULES)
        res = F.options_build(None, parts, 'MB', RULES)
        codes = [o['product_code'] for o in res['options']]
        self.assertEqual(codes, [])                    # 11 은 소켓이, 12 는 DDR4 라 메모리가 안 맞는다
        res = F.options_build(None, parts, 'GPU', RULES)
        by = {o['product_code']: o for o in res['options']}
        self.assertEqual(set(by), {31, 32})            # 5070 Ti 750W 는 750W 파워와 같아 통과한다
        self.assertEqual(by[31]['price_diff'], 450000 - 600000)
        self.assertEqual(by[31]['total'], base['total'] - 150000)
        self.assertFalse({'price', 'sale_price'} & set(by[31]))
        self.assertEqual(res['clear']['price_diff'], -600000)


if __name__ == '__main__':
    unittest.main()


class InquiryHookTests(unittest.TestCase):
    def test_inquiry_refuses_ssd_over_capacity_before_insert(self):
        from fastapi import Request, Response
        from api import mvp3_purchase_inquiry as PI
        parts = [F.Pick(slot='CPU', product_code=1), F.Pick(slot='MB', product_code=10), F.Pick(slot='RAM', product_code=20),
                 F.Pick(slot='CASE', product_code=40), F.Pick(slot='COOLER', product_code=50),
                 F.Pick(slot='SSD', product_code=60, quantity=2), F.Pick(slot='POWER', product_code=70)]
        body = PI.InquiryBody(topic='주문 희망', consent=True, email='qa@example.invalid', free_build=parts)
        request = Request({'type': 'http', 'method': 'POST', 'path': '/api/mvp3/purchase-inquiries',
                           'headers': [(b'host', b'mock.invalid'), (b'origin', b'https://mock.invalid')],
                           'scheme': 'https', 'server': ('mock.invalid', 443), 'query_string': b''})
        with patch.object(PI, 'engine') as engine, patch.object(PI.visitor, 'resolve', return_value=1), \
             patch.object(PI.access_gate, 'check_rate'), patch.object(F, 'load', side_effect=load_rows), \
             patch.object(F, 'load_specs', side_effect=specs_for), patch.object(F, 'load_rules', return_value=RULES), \
             patch.dict(SPECS, {10: dict(SPECS[10], m2_slots=1), 60: dict(SPECS[60], form_factor='M.2')}):
            conn = engine.begin.return_value.__enter__.return_value
            with self.assertRaises(HTTPException) as e:
                PI.create_inquiry(body, request, Response())
            self.assertEqual(e.exception.status_code, 409)
            conn.execute.assert_not_called()

    def test_inquiry_body_takes_picks_only(self):
        from pydantic import ValidationError
        from api import mvp3_purchase_inquiry as PI
        b = PI.InquiryBody(topic='주문 희망', consent=True, phone='010-1234-5678',
                           free_build=[{'slot': 'CPU', 'product_code': 1}])
        self.assertEqual(b.free_build[0].quantity, 1)
        for bad in ([{'slot': 'CPU', 'product_code': 1, 'sale_price': 1}], [{'slot': 'HDD', 'product_code': 1}], []):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                PI.InquiryBody(topic='주문 희망', consent=True, phone='010-1234-5678', free_build=bad)

    def test_admin_row_carries_build(self):
        from datetime import datetime, timedelta, timezone
        from api import admin_purchase_inquiries as AP
        now = datetime.now(timezone.utc)
        r = dict(inquiry_id=1, inquiry_no='PI-1001', created_at=now, topic='주문 희망', status='대기', contact_name=None,
                 contact_phone='01012345678', contact_email=None, message=None, memo=None, user_id=None, quote_id=None,
                 product_code=None, product_name='직접 고른 PC · 1,000원', configuration_id=None,
                 free_build={'parts': [], 'total': 1000}, assignee_name=None, assignee_id=None, updated_at=now,
                 purge_at=now + timedelta(days=1), is_test=False)
        self.assertEqual(AP._row(r, True)['free_build']['total'], 1000)
