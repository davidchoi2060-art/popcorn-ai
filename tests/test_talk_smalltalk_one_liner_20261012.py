"""잡담·감정 표현에 한 마디로 끝내지 않는다 -- 2026-10-12 일반 AI 비교 네 번째 86개(E06·E07·E08·E53).

「너 바보야?」에 「그런 말씀 마세요.」, 「이런 가격 미쳤냐」에 「뭔가 마음에 안 드셨나 봐요.」만 나갔다.
예외 지시가 끝에 PC 를 묻게 했고, 잡담 규칙이 그 PC 권유 문장을 걷어 한 줄만 남은 것이 원인이다.
"""
import contextlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from api import talk, talk_schema as TS
from api import talk_answer as TA
from tests.test_talk_rules_20261010 import _Conn, vocab


def parse(text, reply, chat_flow=None):
    obj = {"pc": False, "state": {}, "missing": [], "evidence": [], "reply": reply}
    result = SimpleNamespace(text=json.dumps(obj, ensure_ascii=False), provider="t", model="t",
                             tokens_in=1, elapsed_sec=0.1)
    ans = TA.AnswerResult(answer="", narrowing=TS.NARROWING_WIDE)
    with contextlib.ExitStack() as st:
        st.enter_context(patch.object(talk.engine, "connect", lambda: _Conn()))
        st.enter_context(patch.object(talk.engine, "begin", lambda: _Conn()))
        st.enter_context(patch.object(talk.access_gate, "check_rate", lambda *a, **k: None))
        st.enter_context(patch.object(talk.TS, "load_vocab", lambda conn: vocab()))
        st.enter_context(patch.object(talk.TA, "run_parallel", lambda a, b: (result, ans)))
        st.enter_context(patch.object(talk.TA, "is_game_related", lambda *a: False))
        st.enter_context(patch.object(talk, "_record_hit", lambda *a, **k: None))
        return talk.parse_talk(talk.ParseBody(text=text, chat_flow=chat_flow), request=None)


class OneLinerIsExtended(unittest.TestCase):
    def test_short_reply_gets_a_follow_sentence(self):
        self.assertEqual(talk.extend_one_liner("그런 말씀 마세요."),
                         "그런 말씀 마세요. " + talk.REPLY_SMALLTALK_FOLLOW)

    def test_two_sentences_or_long_reply_left_alone(self):
        two = "비 오는 날엔 실내가 좋죠. 영화관이나 카페가 편해요."
        self.assertEqual(talk.extend_one_liner(two), two)
        long_one = "고양이가 좋아할 만한 높이의 스탠드나 박스를 키보드 옆에 놔두면 관심을 돌릴 수 있어요."
        self.assertEqual(talk.extend_one_liner(long_one), long_one)
        self.assertEqual(talk.extend_one_liner(""), "")

    def test_follow_sentence_is_not_a_pc_push(self):
        self.assertFalse(talk.is_pc_push(talk.REPLY_SMALLTALK_FOLLOW))

    def test_insult_after_pc_push_dropped(self):
        r = parse("너 바보야?", "그런 말씀 마세요. 혹시 컴퓨터 맞추실 생각 있으세요?")
        self.assertEqual(r["reply"], "그런 말씀 마세요. " + talk.REPLY_SMALLTALK_FOLLOW)

    def test_full_answer_untouched(self):
        a = "저녁이라면 국밥이나 카레가 무난해요. 든든하게 드시고 싶으면 국밥이 좋아요."
        self.assertEqual(parse("오늘 저녁 뭐 먹지?", a)["reply"], a)


class Prompt(unittest.TestCase):
    def test_exception_rule_no_longer_asks_for_a_pc_after_insults(self):
        self.assertNotIn("차분하게 받아 주고 원하는 PC 를 묻는다", talk.EXCEPTION_BLOCK)
        self.assertIn("두세 문장", talk.EXCEPTION_BLOCK)


if __name__ == "__main__":
    unittest.main()
