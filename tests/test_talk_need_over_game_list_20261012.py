"""「~하려면 뭐가 필요해요?」는 PC 낱말이 없어도 PC 설명이다 -- 2026-10-12 개발 서버 확인 결과를 고정한다.

「유튜브 방송하면서 게임도 하려면 뭐가 필요해요?」에 인기 게임 목록 소개가 나갔다.
「요즘 게임 추천해줘」는 여전히 게임 이야기다.
"""
import unittest
from unittest.mock import patch

from api import talk_answer as TA, talk_pc_advice as PA
from tests.test_talk_pc_routing_20261012 import vocab


def route(sentence):
    seen = []
    with patch.object(TA, "extract_game_names", lambda *a: []), \
         patch.object(TA, "match_genres", lambda *a: []), \
         patch.object(TA, "is_game_related", lambda *a: True), \
         patch.object(PA, "advise", lambda *a, **k: seen.append(k.get("topic")) or TA.AnswerResult()):
        TA.answer_path(lambda: None, sentence, vocab())
    return seen


class NeedQuestionIsPcAdvice(unittest.TestCase):
    def test_need_question_goes_to_pc_advice(self):
        for s in ("유튜브 방송하면서 게임도 하려면 뭐가 필요해요?", "게임 하려면 뭐가 필요해요?",
                  "영상 편집이랑 게임 같이 하려면?"):
            with self.subTest(s=s):
                self.assertEqual(route(s), [PA.TOPIC_BUILD])

    def test_game_recommendation_stays_game(self):
        self.assertEqual(route("요즘 게임 추천해줘"), [])


if __name__ == "__main__":
    unittest.main()
