"""구매 절차 질문 -- 물은 것에 바로 답하고, 답했으면 PC 를 다시 묻지 않는다(2026-10-12 일반 AI 비교 R13·E44·R26).

「배송은 얼마나 걸려요?」에 운영체제·환불·보증을 늘어놓고 배송 기간은 말하지 않았고, 끝에 「용도와 예산을 알려
주시면」이 붙었다. 「중고 부품으로도 맞춰주나요?」에는 「다른 시스템에서 확인해 드립니다」가 나갔다(없는 곳으로 미룸).
"""
import unittest

from api import talk_pc_advice as PA, talk_rules as TR, talk_schema as TS
from api import talk_answer as TA
from tests.test_talk_answer_first_20261011 import parse

DELIVERY = "조립 PC는 보통 결제 뒤 2~5영업일 안에 출고돼요. 출고 뒤에는 택배로 하루이틀 걸려요."


class Prompt(unittest.TestCase):
    def test_general_focuses_on_the_asked_item(self):
        p = PA.build_prompt("배송은 얼마나 걸려요?", [], topic=PA.TOPIC_GENERAL)
        self.assertIn("고객이 물은 항목만 답한다", p)
        self.assertNotIn("고객이 물은 항목만 답한다", PA.build_prompt("게임용 PC", [], topic=PA.TOPIC_BUILD))


class NoReaskAfterGeneralAnswer(unittest.TestCase):
    def test_delivery_answered_keeps_notice_without_pc_question(self):
        ans = TA.AnswerResult(answer=DELIVERY, narrowing=TS.NARROWING_WIDE, kind="pc_advice", topic=PA.TOPIC_GENERAL)
        r = parse("배송은 얼마나 걸려요?", {}, "배송은 쇼핑몰에서 안내해요.", ans=ans)
        self.assertIn("배송", r["reply"])
        self.assertNotIn("용도와 예산", r["reply"])

    def test_without_answer_still_asks(self):
        r = parse("배송은 얼마나 걸려요?", {}, "배송은 쇼핑몰에서 안내해요.")
        self.assertIn("용도와 예산", r["reply"])


class Deferrals(unittest.TestCase):
    def test_other_system_sentence_is_dropped(self):
        out = TR.drop_deferrals("중고 부품 구성도 가능한지는 다른 시스템에서 확인해 드립니다. 먼저 어떤 용도로 쓸 컴퓨터를 찾으세요?")
        self.assertEqual(out, "먼저 어떤 용도로 쓸 컴퓨터를 찾으세요?")

    def test_only_deferral_is_kept(self):
        r = "담당 팀에서 안내해 드려요."
        self.assertEqual(TR.drop_deferrals(r), r)

    def test_plain_reply_untouched(self):
        r = "중고 부품은 상태와 보증 기간이 제각각이에요. 새 부품과 나눠 따져 보세요."
        self.assertEqual(TR.drop_deferrals(r), r)

    def test_parse_drops_deferral(self):
        r = parse("중고 부품으로도 맞춰주나요?", {},
                  "중고 부품 구성도 가능한지는 다른 시스템에서 확인해 드립니다. 먼저 어떤 용도로 쓸 컴퓨터를 찾으세요?")
        self.assertNotIn("다른 시스템", r["reply"])


if __name__ == "__main__":
    unittest.main()
