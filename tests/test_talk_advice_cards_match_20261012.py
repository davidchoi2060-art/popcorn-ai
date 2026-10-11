"""설명과 카드가 어긋나 보이지 않게 -- 2026-10-12 일반 AI 비교 네 번째 86개(R02·R10·R11).

설명은 「시중에서는 보통 50~70만원대」인데 카드는 89만원이었다. 설명이 「가능해요.」로 시작했는데 카드 안내는
「저소음 조건은 지금 못 맞춥니다」였다. 한 문장이 길이 상한을 넘으면 글자 중간에서 잘렸다(검수 9595 잔여).
"""
import unittest

from api import talk_pc_advice as PA


class MarketNote(unittest.TestCase):
    def test_market_sentence_gets_the_note(self):
        raw = "개발용은 램 16GB면 충분해요. 시중에서는 보통 50~70만원대예요."
        body, _ = PA.clean(raw, PA.TOPIC_BUILD, "개발자용 PC를 가장 저렴하게 추천해줘")
        self.assertEqual(body, raw + " " + PA.NOTE_MARKET)

    def test_no_market_sentence_no_note(self):
        raw = "개발용은 램 16GB면 충분해요."
        self.assertEqual(PA.clean(raw, PA.TOPIC_BUILD, "개발자용 PC")[0], raw)


class BareYes(unittest.TestCase):
    def test_bare_yes_is_dropped(self):
        raw = "가능해요. 저소음 쿨러와 통풍 좋은 케이스를 고르면 조용해요."
        body, dropped = PA.clean(raw, PA.TOPIC_BUILD, "소음 적은 구성 가능해요?")
        self.assertEqual(body, "저소음 쿨러와 통풍 좋은 케이스를 고르면 조용해요.")
        self.assertEqual(dropped[0]["reason"], "promise")

    def test_longer_sentence_with_possible_stays(self):
        raw = "램은 나중에 늘리는 것도 가능해요."
        self.assertEqual(PA.clean(raw, PA.TOPIC_BUILD, "램 16GB")[0], raw)

    def test_prompt_says_not_to_promise_conditions(self):
        self.assertIn("가능하다는 답", PA.build_prompt("조용한 PC", [], topic=PA.TOPIC_BUILD))


class NoMidCharacterCut(unittest.TestCase):
    def test_one_long_sentence_is_not_cut(self):
        raw = "그래픽카드는 " + "중급형이 좋고 " * 80 + "충분해요."
        body, _ = PA.clean(raw, PA.TOPIC_BUILD)
        self.assertTrue(body.endswith("충분해요."))


if __name__ == "__main__":
    unittest.main()
