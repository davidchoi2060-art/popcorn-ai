"""설명 문장 정리(clean)와 카드 열기의 경계 -- 2026-10-12 소스 검수(9595·9da2) 지적을 고정한다.

① 「시중」 가격 문장에 가게 가격이 섞이면 걷는다(가격 문구 규칙 #172 의 빈틈).
② 라이젠은 모델 번호까지 대조한다 -- 「라이젠 5 7600」을 물었는데 「라이젠 5 9600」 문장이 남았다.
③ 게임 이름 없는 질문의 카드 열기는 본체 구성 설명(build)일 때만 -- 부품 설명 뒤에는 열지 않는다.
④ 본체 구성 + 배송을 함께 물으면 배송 기준 문장은 남기고 가게 약속은 걷는다.
"""
import unittest

from api import talk_pc_advice as PA
from tests.test_talk_game_advice_cards_20261012 import parse as game_parse


def kept(raw, topic=PA.TOPIC_BUILD, sentence=""):
    return PA.clean(raw, topic, sentence)[0]


class MarketPriceWithStorePrice(unittest.TestCase):
    def test_store_price_in_market_sentence_is_dropped(self):
        s = "시중에서는 보통 150만원이고 저희 가격은 140만원이에요."
        self.assertEqual(kept(s, sentence="게임용 PC 얼마 정도 해요?"), "")

    def test_plain_market_sentence_stays(self):
        s = "시중에서는 보통 150만원 안팎에서 많이 고르세요."
        self.assertEqual(kept(s, sentence="게임용 PC 얼마 정도 해요?"), s)


class RyzenFullModel(unittest.TestCase):
    def test_other_ryzen_model_is_dropped(self):
        out = kept("라이젠 5 9600은 한 세대 위 제품이에요.", topic=PA.TOPIC_PART,
                   sentence="라이젠 5 7600 어때요?")
        self.assertEqual(out, "")

    def test_asked_ryzen_model_and_its_series_stay(self):
        raw = "라이젠 5 7600은 게임용으로 무난해요. 라이젠 5는 6코어 제품군이에요."
        out = kept(raw, topic=PA.TOPIC_PART, sentence="라이젠 5 7600 어때요?")
        self.assertEqual(out, raw)


class PartTopicDoesNotOpenCards(unittest.TestCase):
    def test_part_answer_still_asks_the_game(self):
        r = game_parse("게임용 PC 램 역할이 뭐예요?", "램은 작업 공간이에요.", topic=PA.TOPIC_PART)
        self.assertEqual(r["missing"], ["game.grade"])

    def test_build_answer_still_opens_cards(self):
        r = game_parse("게임용 컴퓨터 추천해줘", "게임용이라면 그래픽카드가 가장 중요해요.")
        self.assertEqual(r["missing"], [])


class MixedBuildAndDelivery(unittest.TestCase):
    SENT = "게임용 PC 맞추려는데 배송은 보통 얼마나 걸려요?"

    def test_delivery_standard_stays(self):
        s = "조립 PC는 보통 조립과 점검 뒤 2~3일 안에 배송되는 경우가 많아요."
        self.assertEqual(kept(s, sentence=self.SENT), s)

    def test_store_promise_is_dropped(self):
        s = "저희는 내일까지 배송해 드릴게요."
        self.assertEqual(kept(s, sentence=self.SENT), "")


if __name__ == "__main__":
    unittest.main()
