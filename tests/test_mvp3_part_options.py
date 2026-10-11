"""부품 바꾸기(api/sold_reco.part_options + api/mvp3_part_options) — 2026-10-11 중헌 님
「제품을 선택하고 부품 변경하는 부분 — 아직 안 되는 것 같다」.

고른 판매 PC 에서 한 부품만 다른 «다른 판매 PC» 를 찾는다. 새 가격을 만들지 않고, 핵심 부품이
다른 PC 를 섞지 않고, 함께 바뀌는 것은 숨기지 않는다.
"""
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import grid_public as G
from api import mvp3_part_options as R
from api import sold_reco as S
from api.talk_schema import GameState, TalkState
from tests.test_reco_explore import LEVELS, pc

# 같은 i5-14400F · RTX 5060 PC 들 — 램·저장장치만 다르다. 7 은 그래픽카드가, 8 은 CPU 가 다르다.
PRODUCTS = {
    1: pc(1, 1300000, 2, 100, ram=16, ssd=500),
    2: pc(2, 1350000, 2, 100, ram=32, ssd=500),
    3: pc(3, 1420000, 2, 100, ram=32, ssd=1000),       # 32GB 는 2 가 더 잘 맞는다(함께 바뀌는 것 없음)
    4: pc(4, 1360000, 2, 100, ram=16, ssd=960),        # 960GB = 1TB
    5: pc(5, 1500000, 2, 100, ram=64, ssd=2000),       # 64GB 는 이것뿐 — 저장장치도 함께 바뀐다
    6: pc(6, 1100000, 1, 60, ram=8, ssd=500),          # 캐주얼 — FHD 상담의 최소 수준 미달
    7: pc(7, 1600000, 2, 150, ram=32, ssd=500, gpu='RTX 5070 12GB'),
    8: {**pc(8, 1340000, 2, 100, ram=32, ssd=500), 'spec': {**pc(8, 0, 2, 100)['spec'], 'cpu': 'i7-14700F', 'ram_gb': 32}},
    9: {**pc(9, 1250000, 2, 100), 'price': None},      # 가격 없음 — 판매 중 아님
}
GAME = TalkState(usages=['게임'], game=GameState(resolution='1080p'), budget_won=1500000, budget_bound='이하')


def options(code, slot, products=PRODUCTS, state=GAME, preferred=frozenset()):
    with patch.object(S, 'load', lambda: (LEVELS, products)), \
         patch.object(S, 'public_codes', lambda: preferred):
        return S.part_options(state, ['게임'], [], code, slot, [], None)


def by_value(res):
    return {o['swap']['value']: o for o in res['options']}


class PartOptions(unittest.TestCase):
    def test_ram_keeps_cpu_and_gpu_and_prefers_fewest_other_changes(self):
        res = options(1, 'ram')
        self.assertEqual((res['label'], res['current']), ('메모리', '16GB'))
        got = by_value(res)
        self.assertEqual(list(got), ['32GB', '64GB'])           # 작은 용량부터, 8GB(수준 미달)·7·8 없음
        self.assertEqual(got['32GB']['product_code'], 2)
        self.assertEqual(got['32GB']['swap']['also'], [])
        self.assertEqual(got['64GB']['product_code'], 5)
        self.assertEqual(got['64GB']['swap']['also'], [{'label': '저장장치', 'from': '500GB', 'to': '2TB'}])

    def test_price_is_the_sold_price_and_diff_is_only_the_difference(self):
        o = by_value(options(1, 'ram'))['32GB']
        self.assertEqual(o['price'], 1350000)
        self.assertEqual(o['swap']['price_diff'], 50000)
        self.assertEqual((o['tag'], o['role']), ('고른 구성', 'chosen'))

    def test_ssd_treats_960gb_as_1tb_and_picks_one_per_size(self):
        got = by_value(options(1, 'ssd'))
        self.assertEqual(list(got), ['1TB', '2TB'])
        self.assertEqual(got['1TB']['product_code'], 4)          # 3 은 램도 바뀌어 4 가 먼저

    def test_gpu_keeps_cpu(self):
        got = by_value(options(1, 'gpu'))
        self.assertEqual(list(got), ['RTX 5070 12GB'])
        self.assertEqual(got['RTX 5070 12GB']['swap']['also'], [{'label': '메모리', 'from': '16GB', 'to': '32GB'}])

    def test_cpu_keeps_gpu(self):
        self.assertEqual([o['product_code'] for o in options(1, 'cpu')['options']], [8])

    def test_over_budget_option_is_marked(self):
        o = by_value(options(1, 'gpu'))['RTX 5070 12GB']
        self.assertTrue(o['over_budget'])

    def test_customer_public_configuration_wins_a_tie(self):
        products = {**PRODUCTS, 10: pc(10, 1350000, 2, 100, ram=32, ssd=500)}
        self.assertEqual(by_value(options(1, 'ram', products))['32GB']['product_code'], 2)
        self.assertEqual(by_value(options(1, 'ram', products, preferred=frozenset({10})))['32GB']['product_code'], 10)

    def test_unknown_or_ineligible_base_is_none(self):
        self.assertIsNone(options(99, 'ram'))
        self.assertIsNone(options(9, 'ram'))
        self.assertIsNone(options(6, 'ram'))                      # 이 상담 수준을 못 채운다

    def test_no_internal_index_leaks(self):
        for o in options(1, 'ram')['options']:
            self.assertFalse({'cpu_mt', 'cpu_st', 'gpu_idx'} & set(o['spec']))


class Route(unittest.TestCase):
    def client(self, result):
        app = FastAPI()
        app.include_router(R.router)
        self.calls = []

        def fake(state, code, slot):
            self.calls.append((state, code, slot))
            return result
        patcher = patch.object(G, 'sold_part_options', fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return TestClient(app)

    def test_ok(self):
        c = self.client({'slot': 'ram', 'label': '메모리', 'current': '16GB', 'base_code': 1,
                         'base_price': 1, 'options': []})
        r = c.post('/api/mvp3/part-options', json={'state': {'usages': ['게임']}, 'product_code': 1, 'slot': 'ram'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ok'])
        self.assertEqual(r.headers['cache-control'], 'no-store')
        self.assertEqual(self.calls, [({'usages': ['게임']}, 1, 'ram')])

    def test_not_sold_is_409(self):
        c = self.client(None)
        r = c.post('/api/mvp3/part-options', json={'state': {}, 'product_code': 1, 'slot': 'gpu'})
        self.assertEqual(r.status_code, 409)

    def test_rejects_other_slots_and_extra_keys(self):
        c = self.client(None)
        for body in ({'state': {}, 'product_code': 1, 'slot': 'case'},
                     {'state': {}, 'product_code': '1', 'slot': 'ram'},
                     {'state': {}, 'product_code': 1, 'slot': 'ram', 'price': 1}):
            self.assertEqual(c.post('/api/mvp3/part-options', json=body).status_code, 422)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
