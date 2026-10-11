"""PC 구성 설명을 구체적으로 -- 등급·용량·시중 가격대(2026-10-12 일반 AI 비교 두 번째 86개, 「추천 설명이 얕음」).

일반 AI 는 「이 정도 구성, 이 가격대」를 바로 말하는데 우리 설명은 일반론에서 끝났다. 시중 시세는 「시중에서는 보통」으로만
말하고 우리 가게 가격처럼 말하지 않는다(우리 가격은 카드가 보여 준다). 토큰이 다해 끊긴 끝 문장은 내지 않는다(R05·R23).
"""
import unittest

from api import talk_pc_advice as PA


class Prompt(unittest.TestCase):
    def test_build_asks_for_grades_sizes_and_market_price(self):
        p = PA.build_prompt("배그 150만원 PC 추천해줘", [], topic=PA.TOPIC_BUILD)
        for w in ("등급", "RTX 5060급", "시중에서는 보통"):
            self.assertIn(w, p)

    def test_part_topic_still_has_no_prices(self):
        self.assertIn("가격·금액·예산 숫자", PA.build_prompt("SSD랑 HDD 차이", [], topic=PA.TOPIC_PART))


class Clean(unittest.TestCase):
    def test_market_price_and_tier_examples_stay_in_build(self):
        raw = ("배그 FHD 라면 그래픽카드는 RTX 5060급, CPU는 중급형이면 충분해요. 램은 16GB, SSD는 1TB가 편해요. "
               "이 정도 구성은 시중에서는 보통 130만원대예요.")
        body, dropped = PA.clean(raw, PA.TOPIC_BUILD)
        self.assertEqual(body, raw + " " + PA.NOTE_MARKET)   # 시중 시세와 카드 가격이 다를 수 있다는 한 줄(2026-10-12 R02)
        self.assertEqual(dropped, [])

    def test_shop_like_price_and_bare_model_are_dropped(self):
        raw = "그래픽카드는 중급형이 좋아요. 저희는 130만원에 드려요. RTX 4060을 사세요."
        body, dropped = PA.clean(raw, PA.TOPIC_BUILD)
        self.assertEqual(body, "그래픽카드는 중급형이 좋아요.")
        self.assertEqual([d["reason"] for d in dropped], ["price", "part model"])

    def test_market_price_is_not_kept_outside_build(self):
        body, _ = PA.clean("SSD는 빨라요. 시중에서는 보통 10만원대예요.", PA.TOPIC_PART)
        self.assertEqual(body, "SSD는 빨라요.")

    def test_cut_tail_is_dropped(self):
        body, dropped = PA.clean("발로란트는 가벼운 게임이에요. 그래픽카드는 해상도를 처리하고, CPU는 높은 프",
                                 PA.TOPIC_BUILD)
        self.assertEqual(body, "발로란트는 가벼운 게임이에요.")
        self.assertEqual(dropped[0]["reason"], "cut")

    def test_length_cut_keeps_whole_sentences(self):
        raw = " ".join(["그래픽카드는 중급형이면 충분하고 램은 16GB 이상이면 좋아요."] * 20)
        body, _ = PA.clean(raw, PA.TOPIC_BUILD)
        self.assertLessEqual(len(body), PA.ADVICE_MAX_LEN)
        self.assertTrue(body.endswith("좋아요."))


if __name__ == "__main__":
    unittest.main()
