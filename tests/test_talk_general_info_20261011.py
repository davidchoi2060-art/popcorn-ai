"""구매 절차의 일반 기준은 먼저 답한다 -- 2026-10-11 일반 AI 비교 「확인 가능한 일반 정보도 회피」(R12·R13·E42·E44).

윈도우·배송·환불·취소처럼 쇼핑몰마다 다르지만 «보통 이렇다»는 말할 수 있는 질문에 「확인이 어렵다」만 하지 않는다.
위에는 일반 기준 설명(AI), 아래에는 우리 가게에서 확인할 곳(기존 안내 문장)을 둔다. AI 응답은 흉내 낸다.
"""
import unittest

from api import talk_answer as TA, talk_pc_advice as PA, talk_schema as TS
from tests.test_talk_answer_first_20261011 import parse, vocab

GENERAL = "조립 PC는 보통 주문 뒤 조립과 테스트를 거쳐 출고돼요. 일반적으로 출고 뒤 하루이틀이면 받아요."


def general(answer=GENERAL):
    return TA.AnswerResult(answer=answer, narrowing=TS.NARROWING_WIDE, kind="pc_advice", topic=PA.TOPIC_GENERAL)


class Routing(unittest.TestCase):
    def test_purchase_questions_get_general_answers(self):
        for t in ("윈도우 깔려서 오나요?", "배송은 얼마나 걸려요?", "환불 언제 들어와?", "배송 중에 취소할 수 있어?",
                  "중고 부품으로도 맞춰주나요?"):
            self.assertEqual(PA.topic_of(t, vocab()), PA.TOPIC_GENERAL, t)

    def test_build_request_with_delivery_stays_a_build_answer(self):
        t = "배그PC 추천하고 배송일과 환불도 알려줘"
        self.assertEqual(PA.topic_of(t, vocab()), PA.TOPIC_BUILD)
        self.assertIn("일반적인 기준을 한 문장", PA.build_prompt(t, [], topic=PA.TOPIC_BUILD))

    def test_part_question_unchanged(self):
        self.assertEqual(PA.topic_of("SSD랑 메모리 차이가 뭐예요", vocab()), PA.TOPIC_PART)

    def test_general_prompt_says_general_not_promise(self):
        p = PA.build_prompt("윈도우 깔려서 오나요?", [], topic=PA.TOPIC_GENERAL)
        self.assertIn("일반적", p)
        self.assertNotIn("- 재고·배송·할인·설치.", p)


class Cleaning(unittest.TestCase):
    def test_delivery_words_stay_but_shop_promises_go(self):
        raw = ("조립 PC는 보통 조립과 테스트 뒤 출고돼요. 배송은 일반적으로 출고 뒤 1~2일이 걸려요."
               " 저희가 오늘 바로 보내 드릴게요. 재고가 있으면 더 빨라요.")
        body, dropped = PA.clean(raw, PA.TOPIC_GENERAL)
        self.assertIn("배송은 일반적으로", body)
        self.assertEqual(sorted(d["reason"] for d in dropped), ["promise", "stock"])

    def test_build_cleaning_unchanged(self):
        body, _ = PA.clean("배송은 보통 이틀이에요. 램은 16GB면 충분해요.")
        self.assertEqual(body, "램은 16GB면 충분해요.")


class AnswerAboveNotice(unittest.TestCase):
    def test_windows_question_keeps_the_general_answer_and_the_notice(self):
        r = parse("윈도우 깔려서 오나요?", {"usages": [], "budget_won": None}, "확인이 어렵습니다.", ans=general())
        self.assertEqual(r["answer"], GENERAL)
        self.assertIn("윈도우(운영체제) 설치 여부는 상품마다", r["reply"])

    def test_refund_status_keeps_the_general_answer(self):
        r = parse("환불 언제 들어와?", {"usages": [], "budget_won": None}, "확인이 어렵습니다.", ans=general())
        self.assertIn("order_status", r["exceptions"])
        self.assertEqual(r["answer"], GENERAL)

    def test_build_advice_and_purchase_notice_together(self):
        # 「배그PC 추천하고 배송일과 환불도 알려줘」(E46): 구성 설명은 위에, 우리 가게 안내는 아래에 함께.
        ans = TA.AnswerResult(answer="개발용은 램이 중요해요.", narrowing=TS.NARROWING_WIDE,
                              kind="pc_advice", topic=PA.TOPIC_BUILD)
        r = parse("개발용 PC 추천해줘, 윈도우 설치돼서 오나요?", {"usages": ["개발"], "budget_won": None},
                  "개발용 PC를 찾고 계시는군요.", ans=ans)
        self.assertEqual(r["answer"], "개발용은 램이 중요해요.")
        self.assertIn("윈도우(운영체제) 설치 여부는 상품마다", r["reply"])


if __name__ == "__main__":
    unittest.main()
