"""게임 이름 없이 PC 를 물었을 때 설명을 먼저 했으면 「어떤 게임?」 대신 카드를 낸다 -- 2026-10-11 개발 서버.

「게임용 컴퓨터 추천해줘」·「스팀 게임 이것저것 하는데 무난한 PC」에 설명 뒤 「어떤 게임을 하세요?」만 나오고
카드가 없었다(사장님 「계속 되물어보면 짜증 · 우리 제품도 같이 보여줘야」). 설명이 없을 때는 기존대로 한 번 묻는다.
"""
import contextlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from api import talk, talk_pc_advice as PA, talk_schema as TS
from api import talk_answer as TA
from tests.test_talk_rules_20261010 import _Conn, vocab

ADVICE = "게임용이라면 그래픽카드가 가장 중요해요. 캐주얼 게임은 램 16GB면 충분하고, 최신 대작은 한 단계 위가 좋아요."


def parse(text, answer, topic=None):
    obj = {"pc": True, "state": {"usages": ["게임"], "game": {"names": []}}, "missing": [], "evidence": [],
           "reply": "어떤 게임을 주로 하실 생각이세요?"}
    result = SimpleNamespace(text=json.dumps(obj, ensure_ascii=False), provider="t", model="t",
                             tokens_in=1, elapsed_sec=0.1)
    ans = TA.AnswerResult(answer=answer, narrowing=TS.NARROWING_WIDE,
                          kind="pc_advice" if answer else "game", topic=topic or (PA.TOPIC_BUILD if answer else None))
    with contextlib.ExitStack() as st:
        st.enter_context(patch.object(talk.engine, "connect", lambda: _Conn()))
        st.enter_context(patch.object(talk.engine, "begin", lambda: _Conn()))
        st.enter_context(patch.object(talk.access_gate, "check_rate", lambda *a, **k: None))
        st.enter_context(patch.object(talk.TS, "load_vocab", lambda conn: vocab()))
        st.enter_context(patch.object(talk.TA, "run_parallel", lambda a, b: (result, ans)))
        st.enter_context(patch.object(talk.TA, "is_game_related", lambda *a: False))
        st.enter_context(patch.object(talk, "_record_hit", lambda *a, **k: None))
        return talk.parse_talk(talk.ParseBody(text=text), request=None)


class GameAdviceCards(unittest.TestCase):
    def test_explained_game_pc_shows_cards_without_asking_the_game(self):
        r = parse("게임용 컴퓨터 추천해줘", ADVICE)
        self.assertEqual(r["missing"], [])                    # 화면이 이 턴에 카드를 부른다
        self.assertEqual(r["answer"], ADVICE)
        self.assertNotIn("어떤 게임", r["reply"])
        self.assertIn("FHD", r["reply"])                      # 무엇을 가정했는지 밝힌다

    def test_without_explanation_still_asks_once(self):
        r = parse("게임용 컴퓨터 추천해줘", "")
        self.assertEqual(r["missing"], ["game.grade"])


if __name__ == "__main__":
    unittest.main()
