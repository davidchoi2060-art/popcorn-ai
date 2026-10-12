"""되묻기 대신 기본값으로 답한다 -- 2026-10-12 개발 서버 ③ 되물음 묶음 재점검(모델 OpenAI luna).

1. 「램 16기가면 충분해요 아니면 32기가 사야 돼요?」를 「메모리 16GB 조건으로 골라 볼게요」로 읽었다 -- 견주는 질문이다.
2. 「스팀 게임 이것저것 하는데 무난한 PC」: 설명 뒤 「주로 어떤 게임을 하실 예정인가요?」만 되묻고 카드가 없었다
   (등급 없는 이름 「스팀 인디(통칭)」이 붙어 이름 없는 게임 풀어 주기가 걸리지 않았다).
3. 「싸게 싸게 싸게 싸게」: 한 문장 안 되풀이가 예외로 잡혀 용도만 되묻고 카드가 없었다.
"""
import contextlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from api import talk, talk_pc_advice as PA, talk_rules as TR, talk_schema as TS
from api import reco_explore as X
from api import talk_answer as TA
from tests.test_talk_rules_20261010 import _Conn, vocab

ADVICE = "FHD 기준으로 중급형, 라이젠 5급 CPU와 RTX 5060급 그래픽카드, 램 16GB 구성이 무난해요."


def parse(text, ai_state, answer="", topic=None, reply="어떤 용도로 사용할 PC를 찾으세요?", voc=None):
    obj = {"pc": True, "state": ai_state, "missing": [], "evidence": [], "reply": reply}
    result = SimpleNamespace(text=json.dumps(obj, ensure_ascii=False), provider="t", model="t",
                             tokens_in=1, elapsed_sec=0.1)
    ans = TA.AnswerResult(answer=answer, narrowing=TS.NARROWING_WIDE,
                          kind="pc_advice" if answer else "game", topic=topic)
    with contextlib.ExitStack() as st:
        st.enter_context(patch.object(talk.engine, "connect", lambda: _Conn()))
        st.enter_context(patch.object(talk.engine, "begin", lambda: _Conn()))
        st.enter_context(patch.object(talk.access_gate, "check_rate", lambda *a, **k: None))
        st.enter_context(patch.object(talk.TS, "load_vocab", lambda conn: voc or vocab()))
        st.enter_context(patch.object(talk.TA, "run_parallel", lambda a, b: (result, ans)))
        st.enter_context(patch.object(talk.TA, "is_game_related", lambda *a: False))
        st.enter_context(patch.object(talk, "_record_hit", lambda *a, **k: None))
        return talk.parse_talk(talk.ParseBody(text=text), request=None)


class WeighOptions(unittest.TestCase):
    Q = "램 16기가면 충분해요 아니면 32기가 사야 돼요?"

    def test_either_or_is_not_a_condition(self):
        self.assertEqual(TR.unsupported_conditions(self.Q, None, _all=True), [])
        self.assertNotIn("min_ram_gb", X.extract(self.Q))
        self.assertEqual(TR.unsupported_conditions("RTX 5060 vs 5070 뭐가 나아요?", None, _all=True), [])
        self.assertNotIn("gpu_model", X.extract("RTX 5060 vs 5070 뭐가 나아요?"))
        self.assertEqual(TR.unsupported_conditions("게임용인데 램 16기가면 충분할까요?", None, _all=True), [])

    def test_plain_condition_still_read(self):
        self.assertEqual(TR.unsupported_conditions("개발용 PC, 램 64GB", None, _all=True), ["메모리 64GB"])
        self.assertEqual(X.extract("램 32GB로 게임용 150만원").get("min_ram_gb"), 32)
        self.assertEqual(X.extract("SSD 2TB 들어간 걸로").get("min_ssd_gb"), 2000)

    def test_reply_does_not_promise_the_condition(self):
        r = parse(self.Q, {"usages": []}, reply="용도에 따라 달라요.")
        self.assertNotIn("16GB 조건", r["reply"])


class GradelessGameName(unittest.TestCase):
    # 2026-10-12 코덱스 #194 검수 P2-1: 실제 게임 이름이 있는데 등급이 없으면 추천(grid_public)이 「적합성 확인 전 보류」로
    # 카드를 비운다 -- 상담도 풀지 않는다. 풀어 주는 것은 장르 통칭(「스팀 인디(통칭)」) 이름뿐이다.
    def test_explained_pc_with_generic_name_shows_cards(self):
        v = vocab()
        v.all_game_names.append("스팀 인디(통칭)")
        r = parse("스팀 게임 이것저것 하는데 무난한 PC 추천해 주세요",
                  {"usages": ["게임"], "game": {"names": ["스팀 인디(통칭)"]}},
                  answer=ADVICE, topic=PA.TOPIC_BUILD, reply="주로 어떤 게임을 하실 예정인가요?", voc=v)
        self.assertEqual(r["state"]["game"]["names"], ["스팀 인디(통칭)"])
        self.assertEqual(r["missing"], [])
        self.assertNotIn("어떤 게임", r["reply"])
        self.assertIn("FHD", r["reply"])

    def test_specific_gradeless_name_still_waits_for_grade(self):
        for answer in (ADVICE, ""):
            r = parse("메이플스토리 같은 거 하는데 무난한 PC 추천해 주세요",
                      {"usages": ["게임"], "game": {"names": ["메이플스토리"]}},
                      answer=answer, topic=PA.TOPIC_BUILD if answer else None,
                      reply="주로 어떤 게임을 하실 예정인가요?")
            self.assertEqual(r["missing"], ["game.grade"], answer)


class RepeatedPriceWord(unittest.TestCase):
    def test_cheap_repeated_assumes_general_use(self):
        r = parse("싸게 싸게 싸게 싸게", {"usages": []})
        self.assertEqual(r["missing"], [])                     # 화면이 이 턴에 카드를 부른다
        self.assertIn("일반 용도를 가정", r["reply"])
        self.assertIn("가장 싼 쪽", r["reply"])
        self.assertIn("repeat", r["exceptions"])               # 예외 기록은 그대로 남긴다

    def test_bare_request_still_asks_usage_once(self):
        # 조건이 하나도 없는 「추천해줘」는 용도를 한 번 묻는다(코덱스 PR157 검수 -- 기존 결정 유지).
        r = parse("추천해줘 추천해줘 추천해줘", {"usages": []})
        self.assertEqual(r["missing"], ["usages"])


if __name__ == "__main__":
    unittest.main()
