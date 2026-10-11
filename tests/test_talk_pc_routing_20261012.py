"""일반 PC 질문에 설명을 먼저 한다 -- 2026-10-11 개발 서버에서 24문장을 넣어 본 결과를 고정한다.

1. 규칙이 PC·부품 질문으로 보고 설명을 지었으면, AI 가 「PC 이야기 아님」이라 해도 설명을 지우지 않는다
   (「발로란트 240프레임 그래픽카드 뭐 사야 돼?」·「RTX 5070 들어간 PC 얼마 정도 해요?」).
2. 그래픽카드 모델명도 부품이다(「RTX 5060이랑 RTX 5060 Ti 차이가 뭐예요?」).
3. 「맞출 수 있어요?」「5대 필요해요」「같이 하려면?」「~용 컴퓨터요」도 새 PC 질문이다.
AI 응답은 흉내 낸다(LLM 미호출).
"""
import contextlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from api import talk, talk_pc_advice as PA, talk_schema as TS
from api import talk_answer as TA
from tests.test_talk_rules_20261010 import _Conn, vocab as base_vocab


def vocab():
    v = base_vocab()
    v.usages = list(v.usages) + [("개발", ["개발", "코딩"]), ("영상편집", ["영상 편집", "영상편집", "렌더링"])]
    return v


ADVICE = "발로란트는 가벼운 편이라 240프레임은 CPU 영향이 커요. 그래픽카드는 중급형이면 충분해요."


def parse(text, *, pc, ans):
    obj = {"pc": pc, "state": {"usages": [], "budget_won": None}, "missing": [], "evidence": [],
           "reply": "부품 가격은 다른 시스템에서 확인하시면 돼요."}
    result = SimpleNamespace(text=json.dumps(obj, ensure_ascii=False), provider="t", model="t",
                             tokens_in=1, elapsed_sec=0.1)
    body = talk.ParseBody(text=text)
    with contextlib.ExitStack() as st:
        st.enter_context(patch.object(talk.engine, "connect", lambda: _Conn()))
        st.enter_context(patch.object(talk.engine, "begin", lambda: _Conn()))
        st.enter_context(patch.object(talk.access_gate, "check_rate", lambda *a, **k: None))
        st.enter_context(patch.object(talk.TS, "load_vocab", lambda conn: vocab()))
        st.enter_context(patch.object(talk.TA, "run_parallel", lambda a, b: (result, ans)))
        st.enter_context(patch.object(talk.TA, "is_game_related", lambda *a: False))
        st.enter_context(patch.object(talk, "_record_hit", lambda *a, **k: None))
        return talk.parse_talk(body, request=None)


class AiVerdictDoesNotEraseAdvice(unittest.TestCase):
    def test_advice_stays_when_ai_says_not_pc(self):
        ans = TA.AnswerResult(answer=ADVICE, narrowing=TS.NARROWING_WIDE, kind="pc_advice", topic=PA.TOPIC_PART)
        r = parse("발로란트 240프레임 나오려면 그래픽카드 뭐 사야 돼?", pc=False, ans=ans)
        self.assertEqual(r["answer"], ADVICE)
        self.assertTrue(r["pc_related"])
        self.assertNotIn("off_topic", r["exceptions"])

    def test_small_talk_without_advice_is_still_off_topic(self):
        r = parse("오늘 날씨 어때", pc=False, ans=TA.AnswerResult(answer="", narrowing=TS.NARROWING_WIDE))
        self.assertFalse(r["pc_related"])
        self.assertIn("off_topic", r["exceptions"])


class Topics(unittest.TestCase):
    def test_new_pc_questions(self):
        for s in ("사무용 컴퓨터 50만원 정도로 맞출 수 있어요?", "엑셀 대용량 파일 돌리는 회계 사무실 PC 5대 필요해요",
                  "4K 영상 편집이랑 3D 렌더링 같이 하려면?", "초등학생 아이 공부용이랑 마인크래프트용 컴퓨터요",
                  "유튜브 방송하면서 게임도 하려면 뭐가 필요해요?"):
            with self.subTest(s=s):
                self.assertEqual(PA.topic_of(s, vocab()), PA.TOPIC_BUILD)

    def test_model_names_are_parts(self):
        for s in ("RTX 5060이랑 RTX 5060 Ti 차이가 뭐예요?", "라데온이랑 지포스 차이"):
            with self.subTest(s=s):
                self.assertEqual(PA.topic_of(s, vocab()), PA.TOPIC_PART)

    def test_part_need_stays_a_part_question(self):
        # 부품을 말한 「필요해요」는 부품 설명이다 -- 새 PC 용도를 되묻지 않게.
        for s in ("PC 램 몇 기가 필요해요?", "SSD 몇 기가 필요해요?"):
            with self.subTest(s=s):
                self.assertEqual(PA.topic_of(s, vocab()), PA.TOPIC_PART)

    def test_plain_need_is_not_pc(self):
        for s in ("돈 필요해요", "오늘 뭐 하려면 좋을까", "개발이요"):
            with self.subTest(s=s):
                self.assertIsNone(PA.topic_of(s, vocab()))


if __name__ == "__main__":
    unittest.main()
