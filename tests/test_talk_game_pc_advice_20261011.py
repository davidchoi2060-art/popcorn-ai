"""게임 이름과 함께 PC 를 물으면 게임 소개가 아니라 PC 설명을 먼저 한다 -- 2026-10-11 일반 AI 비교 「묻지 않은 게임 소개」.

「120만원 롤·오버워치·로아 구성 짜줘」에 게임 소개와 「PC 구성은 답변하지 않습니다」가 나갔다.
게임 이름은 용도로 치고, 설명 프롬프트에 «게임 소개를 쓰지 않는다»를 적는다. 「롤 재밌어?」는 기존 게임 답 그대로다.
"""
import contextlib
import unittest
from unittest.mock import patch

from api import talk_answer as TA, talk_pc_advice as PA
from tests.test_talk_answer_first_20261011 import vocab

BUILD_ASKS = ("120만원으로 롤, 오버워치2, 로스트아크 할 건데 구성 좀 짜줘",
              "배그랑 롤 하려는데 150만원이면 어떤 PC가 좋아요?")


class Intent(unittest.TestCase):
    def test_pc_questions_with_games_have_pc_intent(self):
        for t in BUILD_ASKS:
            self.assertTrue(PA.pc_intent(t), t)

    def test_game_talk_has_no_pc_intent(self):
        for t in ("롤 재밌어?", "요즘 롤 티어 어떻게 올려요?"):
            self.assertFalse(PA.pc_intent(t), t)

    def test_games_count_as_usage_for_the_build_topic(self):
        for t in BUILD_ASKS:
            self.assertEqual(PA.topic_of(t, vocab(), game=True), PA.TOPIC_BUILD, t)

    def test_without_game_flag_topic_is_unchanged(self):
        self.assertIsNone(PA.topic_of("롤 재밌어?", vocab()))


class Prompt(unittest.TestCase):
    def test_prompt_names_the_games_and_forbids_introductions(self):
        p = PA.build_prompt(BUILD_ASKS[0], [], topic=PA.TOPIC_BUILD, games=["리그 오브 레전드", "오버워치 2"])
        self.assertIn("[고객이 말한 게임] 리그 오브 레전드, 오버워치 2", p)
        self.assertIn("게임 소개", p)

    def test_prompt_without_games_has_no_game_line(self):
        self.assertNotIn("[고객이 말한 게임]", PA.build_prompt("사무용 PC 추천해줘", [], topic=PA.TOPIC_BUILD))


class Routing(unittest.TestCase):
    def run_path(self, text, names):
        calls = []

        def fake_advise(conn_factory, sentence, labels, res, **kw):
            calls.append((labels, kw))
            return res

        with contextlib.ExitStack() as st:
            st.enter_context(patch.object(TA, "extract_game_names", lambda s, v: list(names)))
            st.enter_context(patch.object(TA, "match_genres", lambda s, v: []))
            st.enter_context(patch.object(TA, "is_game_related", lambda *a: False))
            st.enter_context(patch.object(PA, "advise", fake_advise))
            TA.answer_path(lambda: None, text, vocab())
        return calls

    def test_game_build_request_goes_to_pc_advice_with_games(self):
        calls = self.run_path(BUILD_ASKS[0], ["리그 오브 레전드", "오버워치 2", "로스트아크"])
        self.assertEqual(len(calls), 1)
        labels, kw = calls[0]
        self.assertEqual(kw["topic"], PA.TOPIC_BUILD)
        self.assertEqual(kw["games"], ["리그 오브 레전드", "오버워치 2", "로스트아크"])
        self.assertTrue(labels)                         # 게임 용도 라벨로 설명한다

    def test_game_chat_does_not_go_to_pc_advice(self):
        self.assertEqual(self.run_path("롤 재밌어?", ["리그 오브 레전드"]), [])


if __name__ == "__main__":
    unittest.main()
