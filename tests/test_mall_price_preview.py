# -*- coding: utf-8 -*-
"""tools/mall_price_preview 순수 함수 -- 3단계(_reprice_from_mall)와 같은 판정을 내는가."""
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://u:p@localhost:5432/x")

from tools.mall_price_preview import live_min, merged_supply, plan  # noqa: E402


def prod(purchase, sale, locked=None, cand=True):
    return {"purchase_price": purchase, "sale_price": sale,
            "locked_fields": locked or [], "ai_candidate_yn": cand}


class MallPricePreviewTest(unittest.TestCase):
    def test_fresh_rows_override_db_rows_and_keep_others(self):
        s = merged_supply([(1, 100, "가능", 0), (2, 90, "가능", 1)], [(1, 80, "가능", 0)])
        self.assertEqual(s, {1: (80, "가능", 0), 2: (90, "가능", 1)})

    def test_live_min_ignores_sold_out_and_unranked(self):
        self.assertEqual(live_min({1: (50, "품절", 0), 2: (70, "가능", None),
                                   3: (90, "가능", 2)}), 90)
        self.assertIsNone(live_min({1: (50, "품절", 0)}))

    def test_fee_only_sale_when_price_drops(self):
        verdict, sale = plan(prod(100000, 102600), 90000, 0.02585, 0.0, 2.0)
        self.assertEqual((verdict, sale), ("apply", 92000))

    def test_rise_below_sale_price_is_not_applied(self):
        # 3단계와 같다: 오르지만 아직 판매가보다 낮으면(손해가 아니면) 건드리지 않는다.
        self.assertEqual(plan(prod(100000, 102600), 101000, 0.02585, 0.0, 2.0)[0], "skip")

    def test_rise_above_sale_price_is_applied(self):
        self.assertEqual(plan(prod(100000, 102600), 110000, 0.02585, 0.0, 2.0),
                         ("apply", 113000))

    def test_big_swing_and_locks(self):
        self.assertEqual(plan(prod(100000, 102600), 30000, 0.02585, 0.0, 2.0)[0], "held")
        self.assertEqual(plan(prod(100000, 102600, ["purchase_price"]), 90000,
                              0.02585, 0.0, 2.0)[0], "locked")
        self.assertEqual(plan(prod(100000, 102600, cand=False), 90000,
                              0.02585, 0.0, 2.0)[0], "skip")


if __name__ == "__main__":
    unittest.main()
