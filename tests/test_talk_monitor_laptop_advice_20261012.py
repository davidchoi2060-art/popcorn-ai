"""모니터·노트북 질문에도 설명을 먼저 한다 -- 2026-10-11 개발 서버 24문장 점검.

「모니터도 같이 사야 하는데 어떤 거 사야 돼요?」에는 본체 가격 안내만, 「이 가격이면 그냥 노트북 사는 게 낫지 않아요?」에는
「노트북은 판매하지 않습니다」와 되묻기만 나갔다. 안내는 그대로 두고 그 위에 설명을 둔다.
AI 응답은 흉내 낸다(LLM 미호출).
"""
import contextlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from api import talk, talk_pc_advice as PA, talk_schema as TS
from api import talk_answer as TA
from tests.test_talk_rules_20261010 import _Conn, vocab


def parse(text, *, pc, ans):
    obj = {"pc": pc, "state": {"usages": [], "budget_won": None}, "missing": [], "evidence": [],
           "reply": "어떤 용도로 쓰실 건가요?"}
    result = SimpleNamespace(text=json.dumps(obj, ensure_ascii=False), provider="t", model="t",
                             tokens_in=1, elapsed_sec=0.1)
    with contextlib.ExitStack() as st:
        st.enter_context(patch.object(talk.engine, "connect", lambda: _Conn()))
        st.enter_context(patch.object(talk.engine, "begin", lambda: _Conn()))
        st.enter_context(patch.object(talk.access_gate, "check_rate", lambda *a, **k: None))
        st.enter_context(patch.object(talk.TS, "load_vocab", lambda conn: vocab()))
        st.enter_context(patch.object(talk.TA, "run_parallel", lambda a, b: (result, ans)))
        st.enter_context(patch.object(talk.TA, "is_game_related", lambda *a: False))
        st.enter_context(patch.object(talk, "_record_hit", lambda *a, **k: None))
        return talk.parse_talk(talk.ParseBody(text=text), request=None)


class Topics(unittest.TestCase):
    def test_monitor_question_is_explained(self):
        self.assertEqual(PA.topic_of("모니터도 같이 사야 하는데 어떤 거 사야 돼요?", vocab()), PA.TOPIC_PART)

    def test_laptop_comparison(self):
        for s in ("이 가격이면 그냥 노트북 사는 게 낫지 않아요?", "노트북이랑 데스크톱 차이가 뭐예요"):
            with self.subTest(s=s):
                self.assertEqual(PA.topic_of(s, vocab()), PA.TOPIC_LAPTOP)
        self.assertIn("노트북", PA.build_prompt("노트북이 낫지 않아요?", [], topic=PA.TOPIC_LAPTOP))

    def test_laptop_part_is_a_part_question(self):
        self.assertEqual(PA.topic_of("노트북 램이랑 데스크톱 램 차이", vocab()), PA.TOPIC_PART)


class LaptopTurnKeepsExplanation(unittest.TestCase):
    ADVICE = "데스크톱은 같은 돈으로 성능이 높고 업그레이드가 쉬워요. 노트북은 들고 다니기 편해요."

    def test_explanation_stays_with_the_laptop_notice(self):
        ans = TA.AnswerResult(answer=self.ADVICE, narrowing=TS.NARROWING_WIDE, kind="pc_advice",
                              topic=PA.TOPIC_LAPTOP)
        r = parse("이 가격이면 그냥 노트북 사는 게 낫지 않아요?", pc=True, ans=ans)
        self.assertEqual(r["answer"], self.ADVICE)
        self.assertIn("노트북은 판매하지 않습니다", r["reply"])

    def test_other_laptop_turns_still_drop_advice(self):
        ans = TA.AnswerResult(answer=self.ADVICE, narrowing=TS.NARROWING_WIDE, kind="pc_advice",
                              topic=PA.TOPIC_BUILD)
        r = parse("게임용 노트북 추천해줘", pc=True, ans=ans)
        self.assertEqual(r["answer"], "")


if __name__ == "__main__":
    unittest.main()
