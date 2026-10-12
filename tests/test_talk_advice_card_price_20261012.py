"""설명의 시중 가격대를 아래 카드 가격으로 맞춘다 -- 2026-10-12 중헌 님 고객단 3번.

「시중에서는 보통 50~70만원대예요」 아래에 89만원·142만원 카드가 나왔다. 「다를 수 있어요」 한 줄로는
어긋남이 그대로 보였다. 카드가 있으면 그 카드 가격 범위를 말하고, 카드가 없으면 예전 그대로 둔다.
"""
import unittest

from api import talk_pc_advice as PA


class AlignMarketPrice(unittest.TestCase):
    def test_market_sentence_becomes_card_range(self):
        raw, _ = PA.clean("개발용은 램 16GB면 충분해요. 시중에서는 보통 50~70만원대예요.", PA.TOPIC_BUILD, "개발자용 PC")
        out = PA.align_market_price(raw, [891_000, 1_419_600, 1_199_600])
        self.assertEqual(out, "개발용은 램 16GB면 충분해요. 지금 이 조건에 맞는 판매 중인 PC는 아래 카드처럼 89만~142만원이에요.")
        self.assertNotIn(PA.NOTE_MARKET, out)
        self.assertNotIn("시중", out)

    def test_single_card(self):
        out = PA.align_market_price("시중에서는 보통 100만원대예요. 램은 16GB면 돼요.", [1_199_600])
        self.assertEqual(out, "지금 이 조건에 맞는 판매 중인 PC는 아래 카드처럼 120만원 정도예요. 램은 16GB면 돼요.")

    def test_no_cards_keeps_answer(self):
        raw = "시중에서는 보통 50~70만원대예요. " + PA.NOTE_MARKET
        self.assertEqual(PA.align_market_price(raw, []), raw)

    def test_no_market_sentence_keeps_answer(self):
        raw = "개발용은 램 16GB면 충분해요."
        self.assertEqual(PA.align_market_price(raw, [891_000]), raw)

    def test_two_market_sentences_become_one_line(self):
        out = PA.align_market_price("시중에서는 보통 60만원대예요. 시중 가격은 70만원 안팎이에요. 끝이에요.", [800_000, 900_000])
        self.assertEqual(out.count("아래 카드처럼"), 1)
        self.assertTrue(out.endswith("끝이에요."))


if __name__ == "__main__":
    unittest.main()
