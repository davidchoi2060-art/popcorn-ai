"""구성 설명을 먼저 한 턴은 용도를 되묻지 않고 일반 용도를 가정해 카드를 낸다 -- 2026-10-12 일반 AI 비교 R10·R11.

「조용한 컴퓨터 원해요」·「화이트 감성 PC 100만원대로」에 설명 뒤 「용도를 알려 주시면」만 나오고 카드가 없었다.
모델명을 말한 질문(「RTX 5070 들어간 PC」)은 일반 용도로 가정하면 카드가 어긋나므로 기존대로 묻는다.
AI 응답은 흉내 낸다(LLM 미호출).
"""
import contextlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from api import talk, talk_defaults as TD, talk_pc_advice as PA, talk_schema as TS
from api import talk_answer as TA
from tests.test_talk_rules_20261010 import _Conn, vocab

ADVICE = "조용한 PC는 저소음 쿨러와 큰 팬을 낮은 속도로 돌리는 케이스가 중요해요."
OFFICE_WORK = "문서·웹·화상회의 (한글·오피스·크롬 탭 몇 개)"


def parse(text, answer, *, topic=PA.TOPIC_BUILD, prefs=("저소음",)):
    obj = {"pc": True, "state": {"usages": [], "budget_won": None, "prefs": list(prefs)}, "missing": [], "evidence": [],
           "reply": "어떤 용도로 쓰실 건가요?"}
    result = SimpleNamespace(text=json.dumps(obj, ensure_ascii=False), provider="t", model="t",
                             tokens_in=1, elapsed_sec=0.1)
    ans = TA.AnswerResult(answer=answer, narrowing=TS.NARROWING_WIDE,
                          kind="pc_advice" if answer else "game", topic=topic if answer else None)
    with contextlib.ExitStack() as st:
        st.enter_context(patch.object(talk.engine, "connect", lambda: _Conn()))
        st.enter_context(patch.object(talk.engine, "begin", lambda: _Conn()))
        st.enter_context(patch.object(talk.access_gate, "check_rate", lambda *a, **k: None))
        st.enter_context(patch.object(talk.TS, "load_vocab", lambda conn: vocab()))
        st.enter_context(patch.object(talk.TA, "run_parallel", lambda a, b: (result, ans)))
        st.enter_context(patch.object(talk.TA, "is_game_related", lambda *a: False))
        st.enter_context(patch.object(talk, "_record_hit", lambda *a, **k: None))
        st.enter_context(patch.object(TD, "basis_work", lambda fit: OFFICE_WORK))
        return talk.parse_talk(talk.ParseBody(text=text), request=None)


class AssumeUsageAfterAdvice(unittest.TestCase):
    def test_build_advice_shows_cards_with_general_use(self):
        r = parse("조용한 컴퓨터 원해요", ADVICE)
        self.assertEqual(r["missing"], [])                 # 화면이 이 턴에 카드를 부른다
        self.assertEqual(r["answer"], ADVICE)
        self.assertIn("일반 용도를 가정", r["reply"])
        self.assertNotIn("?", r["reply"])

    def test_named_model_still_asks(self):
        r = parse("RTX 5070 들어간 PC 얼마 정도 해요?", ADVICE)
        self.assertEqual(r["missing"], ["usages"])

    def test_part_advice_does_not_assume(self):
        r = parse("SSD랑 HDD 차이", ADVICE, topic=PA.TOPIC_PART)
        self.assertEqual(r["missing"], ["usages"])

    def test_bare_pc_request_still_asks_once(self):
        r = parse("PC 추천해줘", "PC는 쓰는 일에 따라 중요한 부품이 달라요.", prefs=())
        self.assertEqual(r["missing"], ["usages"])

    def test_without_advice_still_asks(self):
        r = parse("조용한 컴퓨터 원해요", "")
        self.assertEqual(r["missing"], ["usages"])


if __name__ == "__main__":
    unittest.main()
