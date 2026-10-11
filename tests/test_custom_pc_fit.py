"""신규 조립PC 용도 평가(부품 사양 입구)·추천 카드 싣기·완제품 구성표 붙이기 가드 (부품 상품화 5단계)."""
import unittest

from fastapi import HTTPException

from api import admin_pc_attach as A
from api import custom_pc_fit as F
from api import sold_reco as S

GAME = [dict(usage='게임', level=l, level_rank=i + 1) for i, l in enumerate(['캐주얼', 'FHD', 'QHD', '4K'])]


def parts(cpu='AMD 라이젠5 7500F', gpu='RTX 5060 8GB', ram='DDR5-5600 16GB', ram_qty=2, ssd='NVMe 1TB'):
    out = [dict(slot='CPU', slot_label='CPU', name=cpu, quantity=1),
           dict(slot='RAM', slot_label='메모리', name=ram, quantity=ram_qty),
           dict(slot='SSD', slot_label='SSD', name=ssd, quantity=1),
           dict(slot='CASE', slot_label='케이스', name='케이스', quantity=1)]
    if gpu:
        out.insert(1, dict(slot='GPU', slot_label='그래픽카드', name=gpu, quantity=1))
    return out


def pc(code, price, **kw):
    p = parts(**kw)
    return dict(configuration_id=code, title='PC ' + code, price=price, price_note='합계', parts=p,
                fit_spec=F.spec_from_parts(p))


class Spec(unittest.TestCase):
    def test_reads_part_names_with_quantity(self):
        sp = F.spec_from_parts(parts())
        self.assertEqual((sp['ram'], sp['ssd']), (32, 1000))
        self.assertEqual(sp['cpu']['name'], '라이젠5 7500F')
        self.assertIsNotNone(sp['gpu'])

    def test_fit_unknown_short(self):
        self.assertEqual(F.judge(F.spec_from_parts(parts()), '게임', 'FHD'), 'fit')
        # 표에 없는 그래픽카드 -> 몰라서 못 넘음 = 정보 없음
        self.assertEqual(F.judge(F.spec_from_parts(parts(gpu='알수없는 그래픽 X1')), '게임', 'FHD'), 'unknown')
        # 용량을 못 읽은 SSD 도 정보 없음
        self.assertEqual(F.judge(F.spec_from_parts(parts(ssd='NVMe SSD')), '게임', 'FHD'), 'unknown')
        # 분명히 모자람(램 8GB) -> short
        self.assertEqual(F.judge(F.spec_from_parts(parts(ram='DDR4 8GB', ram_qty=1)), '게임', 'FHD'), 'short')


class Cards(unittest.TestCase):
    def test_budget_order_and_no_info(self):
        pcs = [pc('A0000000000000001', 1500000), pc('A0000000000000002', 900000, gpu='알수없는 그래픽 X1'),
               pc('A0000000000000003', 2500000), pc('A0000000000000004', 800000, ram='DDR4 8GB', ram_qty=1)]
        items = S.custom_items(pcs, '게임', 2, GAME, 2000000, '이하')
        self.assertEqual([i['configuration_id'] for i in items], ['A0000000000000001', 'A0000000000000002'])
        self.assertEqual(items[0]['fit'], 'fit')
        self.assertTrue(items[0]['level_text'].startswith('게임 '))
        self.assertEqual((items[1]['fit'], items[1]['level_text']), ('unknown', '정보 없음'))
        self.assertEqual(items[0]['url'], 'new-pcs.html#A0000000000000001')
        self.assertEqual({p['slot_label'] for p in items[0]['parts']}, {'CPU', '그래픽카드', '메모리', 'SSD'})
        self.assertEqual(len(S.custom_items(pcs, '게임', 2, GAME, None, None)), S.MAX_CUSTOM_ITEMS)


class Conn:
    def __init__(self, row): self.row = row
    def execute(self, sql, params=None):
        row = self.row
        return type('R', (), {'mappings': lambda _: type('M', (), {'first': lambda _: row})()})()


class AttachTarget(unittest.TestCase):
    def test_guards(self):
        base = dict(product_code=120221, product_name='사무용 PC', sale_price=590000, status='판매중', part_type='PC_COMPLETE', bound=False)
        self.assertEqual(A.target(Conn(base), 120221)['product_code'], 120221)
        for change, status in ((dict(bound=True), 409), (dict(status='품절'), 409), (dict(sale_price=None), 409),
                               (dict(part_type='CPU'), 404)):
            with self.assertRaises(HTTPException) as e:
                A.target(Conn(dict(base, **change)), 120221)
            self.assertEqual(e.exception.status_code, status)
        with self.assertRaises(HTTPException) as e:
            A.target(Conn(None), 1)
        self.assertEqual(e.exception.status_code, 404)



class AttachRetry(unittest.TestCase):
    """코덱스 검수 #114: 첫 요청이 붙이고 응답을 잃으면, 같은 요청 번호의 재시도는 409 가 아니라 그 결과를 받는다."""

    class Bound:
        def __init__(self, found): self.found, self.sql = found, []
        def execute(self, sql, params=None):
            q = str(sql); self.sql.append((q, params))
            if 'FROM products p' in q:
                row = dict(product_code=120221, product_name='PC', sale_price=590000, status='판매중',
                           part_type='PC_COMPLETE', bound=True)
                return type('R', (), {'mappings': lambda _: type('M', (), {'first': lambda _: row})()})()
            found = self.found
            return type('R', (), {'scalar': lambda _: found})()

    def body(self):
        return A.Attach(product_code=120221, title='t', parts=[{'code': 1, 'quantity': 1}],
                        request_id='req-0123456789abcdef')

    def test_same_request_returns_the_first_result(self):
        c = self.Bound('A0000000000000001')
        out = A.attach_build(c, self.body(), {'operator_id': 1})
        self.assertEqual(out, dict(configuration_id='A0000000000000001', status='review_required', reused=True))
        self.assertEqual(c.sql[1][1], dict(offer='P120221', rid='req-0123456789abcdef', code='120221'))

    def test_other_request_still_conflicts(self):
        with self.assertRaises(HTTPException) as e:
            A.attach_build(self.Bound(None), self.body(), {'operator_id': 1})
        self.assertEqual(e.exception.status_code, 409)


if __name__ == '__main__':
    unittest.main()
