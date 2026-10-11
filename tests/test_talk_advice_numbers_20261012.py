"""설명에 숫자와 급 예시를 -- 2026-10-12 일반 AI 비교 네 번째 86개(추천 질문 31개 중 28개 「설명이 얕음」).

일반 AI 는 VRAM·해상도·와트·기간을 숫자로 말하는데 우리는 등급 낱말에서 멈췄다. 시중 가격대는 쓰고 가게 가격은 쓰지 않는
원칙은 그대로다.
"""
import unittest

from api import talk_pc_advice as PA


class Prompt(unittest.TestCase):
    def test_build_asks_for_both_tier_examples_and_numbers(self):
        p = PA.build_prompt("배그 QHD 144Hz 하려면?", [], topic=PA.TOPIC_BUILD)
        for w in ("라이젠 5급", "RTX 5060급", "VRAM", "4K", "시중에서는 보통"):
            self.assertIn(w, p)

    def test_part_asks_for_numbers(self):
        p = PA.build_prompt("파워는 몇 와트짜리 사야 돼요?", [], topic=PA.TOPIC_PART)
        for w in ("VRAM", "파워 ○W", "급 예시"):
            self.assertIn(w, p)

    def test_general_asks_for_typical_periods(self):
        p = PA.build_prompt("환불 언제 들어와?", [], topic=PA.TOPIC_GENERAL)
        for w in ("영업일", "7일", "보증"):
            self.assertIn(w, p)
        self.assertIn("약속하지 않는다", p)

    def test_length_room(self):
        self.assertGreaterEqual(PA.ADVICE_MAX_LEN, 700)


class Clean(unittest.TestCase):
    def test_numbers_and_tiers_stay(self):
        raw = ("QHD 144Hz 배그라면 그래픽카드는 RTX 5070급, VRAM 12GB 이상이 편해요. "
               "CPU는 라이젠 5급이면 충분하고 파워는 750W급이 좋아요.")
        self.assertEqual(PA.clean(raw, PA.TOPIC_BUILD, "배그 QHD 144Hz 하려면?")[0], raw)

    def test_general_periods_stay(self):
        raw = "카드 결제 취소 환불은 보통 3~5영업일 걸려요. 단순 변심은 받은 날부터 7일 이내에 청약철회할 수 있어요."
        self.assertEqual(PA.clean(raw, PA.TOPIC_GENERAL, "환불 언제 들어와?")[0], raw)


if __name__ == "__main__":
    unittest.main()
