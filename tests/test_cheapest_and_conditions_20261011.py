"""코덱스 #155 검수 보완(2026-10-11) -- 「가장 싸게」 카드와 구성 조건 안내.

P2-1 앞 추천 카드가 있어도 「가장 싸게」는 조건 안의 최저가 한 장이다(상대 이동이 아니다).
P2-2 공개 승인 구성이 더 비싸면 최저가를 밀어내지 않는다(같은 가격일 때만 앞).
P2-3 「램 64GB」 같은 정상 구성 조건 안내가 설명 답을 지우지 않는다.
"""
import unittest
from unittest.mock import patch

from api import reco_explore as X
from api import sold_reco as S
from api import talk_answer as TA, talk_schema as TS
from api.talk_schema import TalkState
from tests import test_reco_explore as TRE
from tests.test_reco_explore import GAME, LEVELS, PRODUCTS, pc, sets
from tests.test_talk_answer_first_20261011 import ADVICE, parse

# FHD 게임은 2단계부터 -- 그 안의 최저가는 2번(130만원)이다.
CHEAPEST = min(p["price"] for p in PRODUCTS.values() if p["fit"]["게임"]["rank"] >= 2)


class CheapestIntent(unittest.TestCase):
    def test_absolute_words_are_read_apart_from_relative(self):
        for t in ("웹 개발, 예산은 최대한 싸게", "개발자용 PC를 가장 저렴하게 추천해줘", "롤만 할 건데 제일 싼 거",
                  "최저가로 보여 주세요"):
            self.assertTrue(X.extract(t).get("cheapest"), t)
        for t in ("더 싼 거 없어요?", "좀 더 저렴하게요"):
            self.assertEqual(X.extract(t).get("nav"), X.CHEAPER, t)
            self.assertFalse(X.extract(t).get("cheapest"), t)

    def test_cheapest_after_a_previous_card_is_still_one_cheapest_card(self):
        # 첫 턴 카드(최저가 2번)를 보고 「최대한 싸게」를 다시 말했다 -- 두 장으로 돌아가지 않는다.
        cs = sets(TalkState(**GAME), {"wants": {}, "nav": X.CHEAPER, "cheapest": True, "anchor_code": 2})[0]
        self.assertEqual([i["price"] for i in cs["items"]], [CHEAPEST])
        self.assertEqual(cs["explore"]["nav_note"], X.NOTE_CHEAPEST)
        cs = sets(TalkState(**GAME), {"wants": {}, "nav": X.CHEAPER, "cheapest": True, "anchor_code": 4})[0]
        self.assertEqual([i["price"] for i in cs["items"]], [CHEAPEST])

    def test_relative_cheaper_still_moves_from_the_card(self):
        cs = sets(TalkState(**GAME, budget_won=2300000, budget_bound="이하"),
                  {"wants": {}, "nav": X.CHEAPER, "anchor_code": 3})[0]
        self.assertEqual(cs["explore"]["nav_note"], X.NOTE_CHEAPER)

    def test_public_card_does_not_push_out_the_cheapest(self):
        products = dict(PRODUCTS)
        products[7] = pc(7, 1400000, 2, 100)      # 같은 수준, 더 비싼 공개 승인 구성
        with patch.object(S, "public_codes", lambda: frozenset({7})), \
             patch.object(S, "load", lambda: (LEVELS, products)), \
             patch.object(X, "part_tags", lambda: {}):
            cs = S.card_sets(TalkState(**GAME), ["게임"], [], [], None,
                             {"wants": {}, "nav": X.CHEAPER, "cheapest": True})[0]
        self.assertEqual([i["product_code"] for i in cs["items"]], [2])

    def test_public_card_wins_only_at_the_same_price(self):
        products = dict(PRODUCTS)
        products[7] = pc(7, CHEAPEST, 2, 100)
        with patch.object(S, "public_codes", lambda: frozenset({7})), \
             patch.object(S, "load", lambda: (LEVELS, products)), \
             patch.object(X, "part_tags", lambda: {}):
            cs = S.card_sets(TalkState(**GAME), ["게임"], [], [], None,
                             {"wants": {}, "nav": X.CHEAPER, "cheapest": True})[0]
        self.assertEqual([i["product_code"] for i in cs["items"]], [7])


class ScreenRoundTrip(unittest.TestCase):
    """화면은 앞 카드 번호(anchor_code)를 다음 문장과 함께 보낸다 -- 그 왕복 그대로."""

    def call(self, **body):
        return TRE.RecommendEndpointTest.call(self, TalkState(**GAME), **body)

    def test_cheapest_sentence_with_anchor(self):
        d = self.call(text="예산은 최대한 싸게", anchor_code=2)
        self.assertEqual([i["price"] for i in d["card_sets"][0]["items"]], [CHEAPEST])

    def test_cheaper_button_stays_relative(self):
        d = self.call(nav="cheaper", anchor_code=3, text="제일 싼 거")
        self.assertEqual(d["talk_notes"][0], X.NOTE_CHEAPER)


class ConditionKeepsExplanation(unittest.TestCase):
    def test_ram_condition_does_not_erase_the_explanation(self):
        ans = TA.AnswerResult(answer=ADVICE, narrowing=TS.NARROWING_WIDE, kind="pc_advice")
        r = parse("개발용 PC 추천해줘, 램 64GB", {"usages": ["개발"], "budget_won": None},
                  "개발용 PC를 찾고 계시는군요.", ans=ans)
        self.assertEqual(r["answer"], ADVICE)                 # 설명은 위에 그대로
        self.assertIn("메모리 64GB", r["reply"])                  # 조건 안내는 짧게 곁들인다
        self.assertIn("가격대를 넓게", r["reply"])            # 가정 한 줄도 남는다

    def test_purchase_topic_still_comes_first(self):
        ans = TA.AnswerResult(answer=ADVICE, narrowing=TS.NARROWING_WIDE, kind="pc_advice")
        r = parse("개발용 PC 추천해줘, 윈도우 설치돼서 오나요?", {"usages": ["개발"], "budget_won": None},
                  "개발용 PC를 찾고 계시는군요.", ans=ans)
        self.assertEqual(r["answer"], "")


if __name__ == "__main__":
    unittest.main()
