"""메모리·저장장치 수량과 같은 구성 여러 대 -- 2026-10-12 중헌 님 고객단 7번.

「부품 변경 페이지에서 전체 구성품(세트)을 여러 대로 조정과 메모리와 저장 장치는 메인보드의 지원 조건까지
수량 조절이 가능하면 좋겠습니다」. 메인보드가 받는 개수는 사양 칸이 있으면 그 값, 없으면 사양 원문에서 읽는다.
"""
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from api import mvp3_build as b
from api import mvp3_quantity as Q

MB_RAW = '메인보드 / AMD / 소켓AM5 / DDR5 / 슬롯 : 4 / 최대 192(GB) / M.2 : 2 / SATA3 : 4 / ATX'
BOM = [
    dict(ordinal=1, slot='CPU', quantity=1, pseudo=False, product_code=101, name='CPU A', sale_price=300000, status='판매중'),
    dict(ordinal=2, slot='MB', quantity=1, pseudo=False, product_code=201, name='보드 AM5', sale_price=200000, status='판매중'),
    dict(ordinal=3, slot='RAM', quantity=2, pseudo=False, product_code=601, name='DDR5 16GB', sale_price=60000, status='판매중'),
    dict(ordinal=4, slot='SSD', quantity=1, pseudo=False, product_code=701, name='NVMe 1TB', sale_price=90000, status='판매중'),
    dict(ordinal=5, slot='ETC', quantity=1, pseudo=True, product_code=None, name='조립비', sale_price=None, status=None),
]
SPECS = {201: dict(part_type='MB'), 601: dict(part_type='RAM', capacity_gb=16),
         602: dict(part_type='RAM', capacity_gb=32), 701: dict(part_type='SSD', form_factor='M.2 2280', interface='NVMe')}
PARTS = {
    101: dict(product_code=101, product_name='CPU A', sale_price=300000, status='판매중', part_type='CPU', spec_source_text=''),
    201: dict(product_code=201, product_name='보드 AM5', sale_price=200000, status='판매중', part_type='MB', spec_source_text=MB_RAW),
    601: dict(product_code=601, product_name='DDR5 16GB', sale_price=60000, status='판매중', part_type='RAM',
              spec_source_text='데스크탑용 / DDR5 / 16GB / 패키지 구성 : 1'),
    602: dict(product_code=602, product_name='DDR5 32GB (16Gx2)', sale_price=120000, status='판매중', part_type='RAM',
              spec_source_text='데스크탑용 / DDR5 / 32GB / 패키지 구성 : 2'),
    701: dict(product_code=701, product_name='NVMe 1TB', sale_price=90000, status='판매중', part_type='SSD',
              spec_source_text='M.2 (2280) / PCIe4.0 NVMe'),
}


class Rows:
    def __init__(self, rows): self.rows = rows
    def mappings(self): return iter(self.rows)


class Conn:
    def __init__(self, parts=PARTS): self.parts = parts
    def execute(self, sql, p=None):
        if 'FROM products WHERE product_code = ANY' in str(sql):
            return Rows([self.parts[c] for c in p['codes'] if c in self.parts])
        raise AssertionError(str(sql))


def ch(ordinal, code, quantity=None):
    return b.Change(ordinal=ordinal, product_code=code, quantity=quantity)


def run(changes, parts=PARTS, specs=SPECS):
    with patch.object(b, 'load_specs', return_value=specs):
        return b.quote(Conn(parts), 1500000, BOM, changes, [])


class BoardFacts(unittest.TestCase):
    def test_reads_the_spec_text_when_columns_are_empty(self):
        self.assertEqual(Q.board({}, MB_RAW), dict(mem_slots=4, mem_max_gb=192, m2_slots=2, sata_ports=4))

    def test_column_wins_over_text(self):
        self.assertEqual(Q.board(dict(mem_slots=2), MB_RAW)['mem_slots'], 2)

    def test_pci_slot_is_not_a_memory_slot(self):
        self.assertIsNone(Q.board({}, '메인보드 / PCI슬롯 : 3')['mem_slots'])

    def test_ram_kit_counts_two_modules(self):
        self.assertEqual(Q.ram_unit({'capacity_gb': 32}, '패키지 구성 : 2', ''), (2, 32))
        self.assertEqual(Q.ram_unit({}, '', 'DDR5 32GB (16Gx2)'), (2, 32))

    def test_storage_kind(self):
        self.assertEqual(Q.storage_kind({'form_factor': 'M.2 2280', 'interface': 'SATA'}, '', 'SSD'), 'm2')
        self.assertEqual(Q.storage_kind({'form_factor': '6.4cm(2.5형)'}, '', 'SSD'), 'sata')
        self.assertEqual(Q.storage_kind({}, '', 'HDD'), 'sata')
        self.assertIsNone(Q.storage_kind({}, '용량 1TB', 'SSD'))


class LineQuantity(unittest.TestCase):
    def test_raise_ram_within_slots_recomputes_price(self):
        q = run([ch(3, 601, 4)])
        self.assertEqual(q['total'], 1500000 + 60000 * 2)
        c = q['changes'][0]
        self.assertEqual((c['quantity'], c['base_quantity'], c['delta']), (4, 2, 120000))

    def test_more_sticks_than_slots_is_refused(self):
        with self.assertRaises(HTTPException) as e:
            run([ch(3, 601, 5)])
        self.assertEqual(e.exception.status_code, 409)
        self.assertIn('메모리 슬롯 4개', e.exception.detail)
        self.assertIn('4개까지', e.exception.detail)

    def test_two_module_kit_uses_two_slots_each(self):
        with self.assertRaises(HTTPException):
            run([ch(3, 602, 3)])              # 3 × 2 = 6 모듈 > 4 슬롯
        with patch.object(b, 'refusal', return_value=None):     # 호환 규칙은 test_mvp3_build 몫이다
            q = run([ch(3, 602, 2)])
        self.assertEqual(q['changes'][0]['delta'], 120000 * 2 - 60000 * 2)

    def test_lowering_is_always_allowed(self):
        q = run([ch(3, 601, 1)])
        self.assertEqual(q['total'], 1500000 - 60000)

    def test_m2_ssd_limited_by_m2_slots(self):
        self.assertEqual(run([ch(4, 701, 2)])['total'], 1500000 + 90000)
        with self.assertRaises(HTTPException) as e:
            run([ch(4, 701, 3)])
        self.assertIn('M.2 슬롯 2개', e.exception.detail)

    def test_unknown_board_locks_raising(self):
        parts = {**PARTS, 201: dict(PARTS[201], spec_source_text='메인보드 / AMD')}
        with self.assertRaises(HTTPException) as e:
            run([ch(3, 601, 3)], parts=parts)
        self.assertIn('확인하지 못해', e.exception.detail)

    def test_only_memory_and_storage_take_a_quantity(self):
        with self.assertRaises(HTTPException) as e:
            run([ch(1, 101, 2)])
        self.assertEqual(e.exception.status_code, 422)

    def test_limit_for_the_options_panel(self):
        u = Q.usage([dict(l) for l in BOM], SPECS, {k: v['spec_source_text'] for k, v in PARTS.items()})
        self.assertEqual(Q.limit_for(u, 3, 2), dict(min=1, max=4, basis='메인보드 메모리 슬롯 4개 · 최대 192GB 기준이에요.', known=True))
        self.assertEqual(Q.limit_for(u, 4, 1)['max'], 2)


class SetsAndFingerprint(unittest.TestCase):
    def test_old_save_keeps_the_same_fingerprint(self):
        from uuid import uuid4
        from api import mvp3_saved_quotes as S
        rid = uuid4()
        old = S.SaveBody(request_id=rid, product_code=1, expected_price=1000, state={}, changes=[ch(3, 602)])
        same = S.SaveBody(request_id=rid, product_code=1, expected_price=1000, state={}, changes=[ch(3, 602)], sets=1)
        more = S.SaveBody(request_id=rid, product_code=1, expected_price=1000, state={}, changes=[ch(3, 602)], sets=2)
        self.assertEqual(S.fingerprint(old), S.fingerprint(same))
        self.assertNotEqual(S.fingerprint(old), S.fingerprint(more))

    def test_handoff_reads_sets_from_the_saved_quote(self):
        from api import mvp3_handoff as H
        self.assertEqual(H._sets({'sets': 3}), 3)
        self.assertEqual(H._sets({'sets': 0}), 1)
        self.assertEqual(H._sets({}), 1)


if __name__ == '__main__':
    unittest.main()
