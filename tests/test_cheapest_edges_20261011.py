"""코덱스 #161 검수 경계 둘(2026-10-11).

① 「램 64GB로 최대한 싸게」처럼 사양 숫자가 섞여도 「최대한 싸게」를 읽는다(예산 숫자만 방향을 막는다).
② 「150만원 이상」처럼 하한을 말한 뒤 「제일 싼 거」는 하한 안에서 가장 싼 것 -- 하한을 넘는 후보가 없을 때만 푼다.
"""
import unittest

from api import reco_explore as X
from api.talk_schema import TalkState
from tests.test_reco_explore import GAME, sets


class SpecNumbersDoNotBlockCheapest(unittest.TestCase):
    def test_spec_numbers_still_read_cheapest(self):
        for t, key, val in (("개발용 PC, 램 64GB로 최대한 싸게", "min_ram_gb", 64),
                            ("SSD 1TB 가장 저렴하게", "min_ssd_gb", 1000),
                            ("RTX 5060으로 제일 싸게", "gpu_model", "RTX 5060")):
            ex = X.extract(t)
            self.assertTrue(ex.get("cheapest"), t)
            self.assertEqual(ex.get(key), val, t)

    def test_budget_numbers_still_block_direction(self):
        for t in ("더 싸게 150으로", "120만원 더 싸게", "150 정도로 싸게"):
            self.assertNotIn("nav", X.extract(t), t)


class CheapestKeepsTheLowerBound(unittest.TestCase):
    def test_cheapest_above_the_lower_bound(self):
        cs = sets(TalkState(**GAME, budget_won=1500000, budget_bound="이상"),
                  {"wants": {}, "nav": X.CHEAPER, "cheapest": True})[0]
        self.assertEqual([i["price"] for i in cs["items"]], [1585100])   # 130만원이 아니라 150만원 이상 중 최저

    def test_lower_bound_is_released_only_when_nothing_is_above_it(self):
        cs = sets(TalkState(**GAME, budget_won=5000000, budget_bound="이상"),
                  {"wants": {}, "nav": X.CHEAPER, "cheapest": True})[0]
        self.assertEqual([i["price"] for i in cs["items"]], [1300000])

    def test_upper_bound_is_unchanged(self):
        cs = sets(TalkState(**GAME, budget_won=1500000, budget_bound="이하"),
                  {"wants": {}, "nav": X.CHEAPER, "cheapest": True})[0]
        self.assertEqual([i["price"] for i in cs["items"]], [1300000])


if __name__ == "__main__":
    unittest.main()
