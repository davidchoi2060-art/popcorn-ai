"""구매 절차 일반 정보를 넓힌다 -- 2026-10-12 일반 AI 비교 두 번째 86개 「일반 정보 회피」.

「다나와가 더 싸요?」·「쿠팡 이 구성보다 좋아?」·「A업체 사기인가요?」에 비교 요령·확인 방법조차 주지 않았고,
「가격 배송 설치 AS 할부 한 번에 설명해줘」에는 게임 소개가 나갔다(게임 이름 비슷한 낱말이 걸렸다).
AI 응답은 흉내 낸다(LLM 미호출).
"""
import unittest
from unittest.mock import patch

from api import talk_answer as TA, talk_pc_advice as PA, talk_schema as TS
from tests.test_talk_pc_routing_20261012 import parse, vocab

TIP = "보통 같은 부품 모델인지, 조립비·운영체제·배송·A/S 포함 여부를 맞춰 비교하면 정확해요."


class Topics(unittest.TestCase):
    def test_comparison_and_trust_questions_are_general(self):
        for s in ("다나와가 더 싸요?", "쿠팡 이 구성보다 좋아?", "A업체 사기인가요?", "가격 배송 설치 AS 할부 한 번에 설명해줘"):
            with self.subTest(s=s):
                self.assertEqual(PA.topic_of(s, vocab()), PA.TOPIC_GENERAL)

    def test_prompt_has_comparison_tips_without_judging(self):
        p = PA.build_prompt("다나와가 더 싸요?", [], topic=PA.TOPIC_GENERAL)
        self.assertIn("비교하는 요령", p)
        self.assertIn("단정하지 않는다", p)


class Routing(unittest.TestCase):
    def test_purchase_question_beats_a_game_name_lookalike(self):
        seen = []
        with patch.object(TA, "extract_game_names", lambda *a: ["EA SPORTS FC 26"]), \
             patch.object(TA, "is_game_related", lambda *a: True), \
             patch.object(PA, "advise", lambda *a, **k: seen.append(k.get("topic")) or TA.AnswerResult()):
            TA.answer_path(lambda: None, "가격 배송 설치 AS 할부 한 번에 설명해줘", vocab())
        self.assertEqual(seen, [PA.TOPIC_GENERAL])

    def test_competitor_question_keeps_the_explanation(self):
        ans = TA.AnswerResult(answer=TIP, narrowing=TS.NARROWING_WIDE, kind="pc_advice", topic=PA.TOPIC_GENERAL)
        r = parse("다나와가 더 싸요?", pc=False, ans=ans)
        self.assertEqual(r["answer"], TIP)
        self.assertIn("competitor", r["exceptions"])


if __name__ == "__main__":
    unittest.main()
