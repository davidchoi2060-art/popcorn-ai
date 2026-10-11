"""부품 설명 질문의 경계 둘 -- 코덱스 PR157 검수 v1 P2-1·P2-2(2026-10-11).

P2-1 「PC 메모리 구성과 SSD 차이가 뭐예요?」는 「구성」이 들어 있어도 사려는 말이 없으니 부품 설명이다.
P2-2 「PC에서 SSD가 왜 필요해요?」처럼 갈래 규칙에 안 걸리는 부품 질문도, 설명을 먼저 했으면 그 뒤에
      「새 PC / 업그레이드 / 부품 중 무엇인지」를 되묻지 않는다. 설명한 주제가 곧 갈래다.
"""
import unittest

from api import talk_answer as TA, talk_entry as TE, talk_pc_advice as PA, talk_schema as TS
from tests.test_talk_answer_first_20261011 import parse, vocab


def part_answer(topic="part"):
    return TA.AnswerResult(answer="SSD는 파일을 오래 저장하는 부품이에요.", narrowing=TS.NARROWING_WIDE,
                           kind="pc_advice", topic=topic)


class PartBeforeBuild(unittest.TestCase):
    def test_part_difference_with_the_word_composition_is_a_part_question(self):
        for t in ("PC 메모리 구성과 SSD 차이가 뭐예요?", "컴퓨터 구성에서 파워는 무슨 역할이에요?"):
            self.assertEqual(PA.topic_of(t, vocab()), PA.TOPIC_PART, t)

    def test_buying_words_keep_the_build_answer(self):
        for t in ("게임용 PC 구성 추천해줘", "100만원으로 PC 구성 짜줘", "SSD랑 메모리 차이 알고 싶은데 PC 추천해줘"):
            self.assertEqual(PA.topic_of(t, vocab()), PA.TOPIC_BUILD, t)


class NoBranchQuestionAfterExplanation(unittest.TestCase):
    def test_part_explanation_is_not_followed_by_the_branch_question(self):
        t = "PC에서 SSD가 왜 필요해요?"
        self.assertIsNone(TE.classify(t))                   # 갈래 규칙에는 안 걸리는 문장이다
        r = parse(t, {}, "어떤 용도로 쓰실 PC인가요?", ans=part_answer())
        self.assertEqual(r["reply"], "")
        self.assertNotIn(TE.ASK, r["reply"])
        self.assertFalse(r["chat_flow"]["asked"])
        self.assertEqual(r["chat_flow"]["entry"], "parts")

    def test_upgrade_explanation_sets_the_upgrade_branch(self):
        r = parse("컴퓨터가 너무 답답해요", {}, "어떤 용도로 쓰실 PC인가요?", ans=part_answer("upgrade"))
        self.assertNotIn(TE.ASK, r["reply"])
        self.assertEqual(r["chat_flow"]["entry"], "upgrade")

    def test_without_explanation_the_branch_question_stays(self):
        r = parse("PC에서 SSD가 왜 필요해요?", {}, "어떤 용도로 쓰실 PC인가요?")
        self.assertIn(TE.ASK, r["reply"])


if __name__ == "__main__":
    unittest.main()
