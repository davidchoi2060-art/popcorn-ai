"""판매 안내를 AI 답의 «바꿔치기»가 아니라 AI 가 읽는 «가게 사실»로 -- 2026-10-12 사장님 「고객 소통채널은 LLM 이 되어야 함」.

캡처: 「…모니터가 4대 임」에 「여러 대 구매」 안내가 AI 답을 통째로 바꿨다. 이제 «여러 대»·«모니터 포함»처럼 낱말만으로
걸리는 주제는 설명 AI 에 안내 원문을 넘기고, AI 가 고객이 실제로 그 주제를 물었을 때만 자기 말로 전한다.

① 설명 AI 가 답했으면 말풍선에 고정 안내를 다시 싣지 않는다.
② 설명이 화면에서 빠지면(잡담 판정 등) 고정 안내를 되살린다 -- 안내가 사라지지 않는다.
③ 배송·윈도우처럼 절차 낱말을 직접 쓴 문장은 기존대로 관리자 안내 원문을 아래에 둔다(E46).
④ 프롬프트가 안내를 사실로 싣고 「낱말만 비슷하면 쓰지 않는다」를 말한다.
"""
import unittest
from unittest.mock import patch

from api import talk_answer as TA, talk_pc_advice as PA, talk_schema as TS
from tests import test_talk_answer_first_20261011 as AF

QTY = "회계 사무실 PC 5대 필요해요"
ADVICE = "회계 사무실이면 사무용 기본 구성으로 충분해요. 여러 대 할인은 쇼핑몰 주문 때 확인하시면 돼요."


def advice(topic=PA.TOPIC_BUILD):
    return TA.AnswerResult(answer=ADVICE, narrowing=TS.NARROWING_WIDE, kind="pc_advice", topic=topic)


def parse(text, ans):
    return AF.parse(text, {"usages": ["사무·인강"]}, "네, 5대 확인했습니다.", ans=ans)


class ShopFactsGoToAI(unittest.TestCase):
    def test_ai_answer_is_not_replaced_by_the_fixed_notice(self):
        r = parse(QTY, advice())
        self.assertEqual(r["answer"], ADVICE)
        self.assertNotIn("한 대 기준", r["reply"])
        self.assertNotIn("확인했습니다", r["reply"])          # AI [A] 의 약속은 여전히 안 나간다

    def test_notice_comes_back_when_the_answer_is_hidden(self):
        # 예외 응대 턴(여기서는 링크)은 설명을 비운다 -- 그때도 안내는 남아야 한다
        r = parse(QTY + " https://example.com/a", advice())
        self.assertIn("link", r["exceptions"])
        self.assertEqual(r["answer"], "")
        self.assertIn("한 대 기준", r["reply"])

    def test_without_ai_answer_the_notice_stays(self):
        r = parse(QTY, TA.AnswerResult(answer="", narrowing=TS.NARROWING_WIDE))
        self.assertIn("한 대 기준", r["reply"])

    def test_procedure_word_keeps_the_admin_text_below(self):
        r = parse("사무용 PC 추천해줘, 윈도우 설치돼서 오나요?", advice())
        self.assertIn("윈도우(운영체제) 설치 여부는 상품마다", r["reply"])


class PromptAndRouting(unittest.TestCase):
    def test_prompt_carries_notes_as_facts(self):
        p = PA.build_prompt(QTY, [], [], PA.TOPIC_BUILD, shop_notes=["추천과 가격은 한 대 기준이에요."])
        self.assertIn("[우리 가게 안내", p)
        self.assertIn("- 추천과 가격은 한 대 기준이에요.", p)
        self.assertIn("「모니터가 4대」는 PC 여러 대 구매가 아니다", p)

    def test_notes_alone_route_to_the_ai(self):
        seen = {}

        def fake_advise(conn_factory, sentence, labels, res, **k):
            seen.update(k, labels=labels)
            return res
        with patch.object(PA, "advise", fake_advise), patch.object(TA, "is_game_related", lambda *a: False):
            TA.answer_path(lambda: None, "할인 돼요?", AF.vocab(), shop_notes=["할인 안내"])
        self.assertEqual(seen.get("topic"), PA.TOPIC_GENERAL)
        self.assertEqual(seen.get("shop_notes"), ["할인 안내"])

    def test_store_promise_dropped_when_notes_given(self):
        body, _ = PA.clean("사무용이면 기본형이면 돼요. 저희가 할인해 드릴게요.", PA.TOPIC_FOLLOW, QTY, strict=True)
        self.assertEqual(body, "사무용이면 기본형이면 돼요.")


if __name__ == "__main__":
    unittest.main()
