"""상담 중 이어 한 말에도 AI 가 답한다 -- 2026-10-12 사장님 캡처(「모니터가 4대 임」).

「주로 업무, 학교, 회사일, 개인적인 용도로 두루두루 사용하는데, 모니터가 4대 임」에 규칙(topic_of)이 걸리지 않아
설명 AI 를 부르지 않았고, 고정 안내 두 줄만 나갔다. 사장님 「고객 소통채널은 LLM 이 되어야 함」.

① 규칙에 안 걸려도 상담 중이면(앞 턴 용도·예산 또는 상담원 답이 있으면) 이어 답하기(TOPIC_FOLLOW)로 AI 를 부른다.
② 인사·맞장구만 한 짧은 말은 부르지 않는다.
③ 이어 답하기는 잡담 판정(pc=false)을 뒤집지 않는다 -- 그때 답은 화면에서 빠진다.
④ 프롬프트가 「모니터 대수 ≠ 구매 대수」를 말한다.
"""
import contextlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from api import talk, talk_pc_advice as PA, talk_schema as TS
from api import talk_answer as TA
from tests.test_talk_rules_20261010 import _Conn, vocab

CAPTURE = "주로 업무, 학교, 회사일, 개인적인 용도로 두루두루 사용하는데, 모니터가 4대 임"
HISTORY = [("user", "PC 부품이나 구성에서 궁금한 점이 있어요."),
           ("assistant", "사무·학습과 일반적인 웹 작업용이라면 중급형 CPU에 램 16GB 구성이 무난해요.")]
FOLLOW = "모니터 4대를 쓰시려면 출력 단자가 4개 이상인 외장 그래픽카드가 필요해요."


class TopicInContext(unittest.TestCase):
    def test_capture_sentence_is_not_caught_by_rules(self):
        self.assertIsNone(PA.topic_of(CAPTURE, vocab()))      # 고치기 전 AI 를 안 부른 이유

    def test_in_consult_follow_up_calls_ai(self):
        self.assertEqual(PA.topic_in_context(CAPTURE, vocab(), None, HISTORY), PA.TOPIC_FOLLOW)

    def test_first_turn_with_pc_words_calls_ai(self):
        self.assertEqual(PA.topic_in_context("모니터가 4대 있어요", vocab()), PA.TOPIC_FOLLOW)

    def test_rule_topic_still_wins(self):
        self.assertEqual(PA.topic_in_context("사무용 컴퓨터 추천해줘", vocab(), None, HISTORY), PA.TOPIC_BUILD)

    def test_thanks_does_not_call_ai(self):
        self.assertIsNone(PA.topic_in_context("감사합니다", vocab(), None, HISTORY))

    def test_unrelated_first_line_does_not_call_ai(self):
        self.assertIsNone(PA.topic_in_context("오늘 날씨 어때요", vocab()))

    def test_prompt_reads_monitor_count_as_monitors(self):
        p = PA.build_prompt(CAPTURE, [], HISTORY, PA.TOPIC_FOLLOW)
        self.assertIn("모니터 4대를 연결해 쓴다", p)
        self.assertIn("[대화 이력", p)


def parse(pc, answer=FOLLOW):
    obj = {"pc": pc, "state": {"usages": ["사무·인강"] if pc else []}, "missing": [], "evidence": [],
           "reply": "네, 알겠습니다."}
    result = SimpleNamespace(text=json.dumps(obj, ensure_ascii=False), provider="t", model="t",
                             tokens_in=1, elapsed_sec=0.1)
    ans = TA.AnswerResult(answer=answer, narrowing=TS.NARROWING_WIDE, kind="pc_advice", topic=PA.TOPIC_FOLLOW)
    with contextlib.ExitStack() as st:
        st.enter_context(patch.object(talk.engine, "connect", lambda: _Conn()))
        st.enter_context(patch.object(talk.engine, "begin", lambda: _Conn()))
        st.enter_context(patch.object(talk.access_gate, "check_rate", lambda *a, **k: None))
        st.enter_context(patch.object(talk.TS, "load_vocab", lambda conn: vocab()))
        st.enter_context(patch.object(talk.TA, "run_parallel", lambda a, b: (result, ans)))
        st.enter_context(patch.object(talk.TA, "is_game_related", lambda *a: False))
        st.enter_context(patch.object(talk, "_record_hit", lambda *a, **k: None))
        return talk.parse_talk(talk.ParseBody(text="모니터는 듀얼로 써요"), request=None)


class FollowAnswerInParse(unittest.TestCase):
    def test_pc_turn_shows_follow_answer(self):
        r = parse(True)
        self.assertEqual(r["answer"], FOLLOW)

    def test_smalltalk_verdict_is_kept_and_answer_hidden(self):
        r = parse(False)
        self.assertIs(r["pc_related"], False)
        self.assertEqual(r["answer"], "")


if __name__ == "__main__":
    unittest.main()
