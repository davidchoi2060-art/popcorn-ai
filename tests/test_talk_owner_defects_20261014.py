"""사장님 상담 결함 보고(2026-10-14) 회귀 고정 -- 결함 1·2·3과 권고 7.

  결함 1  「배틀그라운드랑 로스트아크, QHD 모니터, 본체 예산 150만 원」에 게임 백과사전 소개와 「구성 상담은 여기서
          다루지 않겠습니다」가 나간 뒤 바로 아래 「구성을 찾아 드리겠습니다」가 나왔다.
  결함 2  「FHD로 낮추면 150만 원 안에 되나요?」에 「네, 그 예산 안에서 구성하기 훨씬 수월해요」 -- 아래 카드는 「150만 원
          안에는 맞는 PC가 없어요」·최저 1,624,400원.
  결함 3  같은 답의 「FHD 높음 옵션으로 60fps 이상 목표라면…」 -- 상품 FAQ 는 「부품 이름만으로 프레임을 확정하지 않습니다」.
  권고 7  「RTX 5070에 500W 파워」에 「충분하다고 단정하기 어렵다」만 -- 상품 자료 권장 파워 650W 면 부족하다고 말한다.
"""
import contextlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from api import grid_public, talk, talk_answer as TA, talk_pc_advice as PA
from tests.test_talk_answer_first_20261011 import vocab as af_vocab
from tests.test_talk_rules_20261010 import _Conn, vocab

ASK1 = "배틀그라운드랑 로스트아크, QHD 모니터, 본체 예산 150만 원"
ASK2 = "FHD로 낮추면 150만 원 안에 되나요?"
ASK7 = "RTX 5070에 500W 파워면 충분한가요?"


class Routing(unittest.TestCase):
    """결함 1 -- 해상도가 붙은 «쓰는 모니터»는 부품 질문이 아니다. 예산과 게임을 말했으니 구성 설명 갈래다."""

    def test_setup_monitor_with_budget_is_build(self):
        self.assertEqual(PA.topic_of(ASK1, af_vocab(), game=True), PA.TOPIC_BUILD)

    def test_monitor_request_is_still_a_part_question(self):
        self.assertEqual(PA.topic_of("QHD 모니터 추천해줘", af_vocab()), PA.TOPIC_PART)
        self.assertEqual(PA.topic_of("모니터 어떤 거 사야 돼요?", af_vocab()), PA.TOPIC_PART)

    def test_game_build_goes_to_pc_advice_not_game_intro(self):
        calls = []

        def fake_advise(conn_factory, sentence, labels, res, **kw):
            calls.append(kw["topic"])
            return res

        with contextlib.ExitStack() as st:
            st.enter_context(patch.object(TA, "extract_game_names", lambda s, v: ["배틀그라운드", "로스트아크"]))
            st.enter_context(patch.object(TA, "match_genres", lambda s, v: []))
            st.enter_context(patch.object(PA, "advise", fake_advise))
            TA.answer_path(lambda: None, ASK1, af_vocab())
        self.assertEqual(calls, [PA.TOPIC_BUILD])


class BudgetYes(unittest.TestCase):
    def test_drops_yes_on_budget_question(self):
        out, n = PA.drop_budget_yes("네, 그 예산 안에서 구성하기 훨씬 수월해요. 그래픽카드가 가장 중요해요.", ASK2)
        self.assertEqual(n, 1)
        self.assertEqual(out, "그래픽카드가 가장 중요해요.")

    def test_keeps_no_and_unrelated_sentences(self):
        for s in ("150만원 안에서는 QHD 구성이 어려워요.", "그래픽카드가 가장 중요해요.", "무리 없이 쓰려면 16GB가 좋아요."):
            self.assertEqual(PA.drop_budget_yes(s, ASK2), (s, 0), s)

    def test_bare_yes_kept_when_budget_not_asked(self):
        self.assertEqual(PA.drop_budget_yes("네, 화이트 구성도 볼 수 있어요.", "화이트로 바꿀 수 있어요?")[1], 0)

    def test_no_line(self):
        self.assertEqual(PA.budget_no_line(1_500_000, 1_624_400, "게임 FHD"),
                         "아쉽지만 지금 판매 중인 PC로는 게임 FHD 기준으로도 150만원 안에 맞는 구성이 없어요.")


class Fps(unittest.TestCase):
    def test_drops_unasked_frame_numbers(self):
        out, n = PA.drop_fps_claims("FHD 높음 옵션으로 60fps 이상 목표라면 RTX 5060급이 맞아요. 램은 16GB면 돼요.", ASK2)
        self.assertEqual((out, n), ("램은 16GB면 돼요.", 1))

    def test_keeps_number_the_customer_said(self):
        s = "240프레임을 원하시면 그래픽카드 등급을 더 봐야 해요."
        self.assertEqual(PA.drop_fps_claims(s, "발로란트 240프레임 그래픽카드 뭐 사야 돼?"), (s, 0))


class Psu(unittest.TestCase):
    def test_question(self):
        self.assertEqual(PA.psu_question(ASK7), ("RTX 5070", 500))
        self.assertEqual(PA.psu_question("RTX 5070 Ti에 750W 파워 괜찮아요?"), ("RTX 5070 TI", 750))
        self.assertIsNone(PA.psu_question("RTX 5070 성능 어때요?"))
        self.assertIsNone(PA.psu_question("500W 파워 추천해줘"))

    def test_line(self):
        self.assertEqual(PA.psu_line("RTX 5070", 500, 650),
                         "RTX 5070 권장 파워는 650W라 500W 파워는 부족해요. 650W 이상 정격 파워를 쓰셔야 안정적으로 쓸 수 있어요.")
        self.assertIn("권장 기준을 넘어요", PA.psu_line("RTX 5070", 750, 650))
        self.assertIsNone(PA.psu_line("RTX 9999", 500, None))

    def test_advise_puts_verdict_first_and_drops_hedge(self):
        class Conn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, *a, **k):
                return SimpleNamespace(first=lambda: (650,), mappings=lambda: SimpleNamespace(all=lambda: []))

        raw = "500W로도 켜질 수는 있지만 충분하다고 단정하기 어려워요. 파워는 정격 출력과 효율 등급을 함께 봐야 해요."
        out = SimpleNamespace(text=raw, provider="t", model="t", cost_usd=0, tokens_in=1, tokens_out=1, log_id=None)
        with patch.object(PA.llm, "call", lambda *a, **k: out):
            res = PA.advise(Conn, ASK7, [], TA.AnswerResult(), topic=PA.TOPIC_PART)
        self.assertTrue(res.answer.startswith("RTX 5070 권장 파워는 650W라 500W 파워는 부족해요."))
        self.assertNotIn("단정하기 어려워요", res.answer)
        self.assertIn("효율 등급", res.answer)
        self.assertEqual(res.psu_watt, 500)

    def test_advise_keeps_verdict_when_llm_fails(self):
        class Conn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, *a, **k):
                return SimpleNamespace(first=lambda: (650,), mappings=lambda: SimpleNamespace(all=lambda: []))

        def boom(*a, **k):
            raise PA.llm.LLMProviderError("x")
        with patch.object(PA.llm, "call", boom):
            res = PA.advise(Conn, ASK7, [], TA.AnswerResult(), topic=PA.TOPIC_PART)
        self.assertIn("부족해요", res.answer)


# ── 조립(talk._finish) 끝에서 끝까지 ──────────────────────────────────────────────
def _result(state, reply):
    obj = {"pc": True, "state": state, "missing": [], "evidence": [], "reply": reply}
    return SimpleNamespace(text=json.dumps(obj, ensure_ascii=False), provider="t", model="t",
                           tokens_in=1, elapsed_sec=0.1, log_id=None)


@contextlib.contextmanager
def server(state, reply, answer_res, prices=(1_624_400, 1_741_000)):
    with contextlib.ExitStack() as st:
        st.enter_context(patch.object(talk.engine, "connect", lambda: _Conn()))
        st.enter_context(patch.object(talk.engine, "begin", lambda: _Conn()))
        st.enter_context(patch.object(talk.access_gate, "check_rate", lambda *a, **k: None))
        st.enter_context(patch.object(talk.TS, "load_vocab", lambda conn: vocab()))
        st.enter_context(patch.object(talk.llm, "call", lambda *a, **k: _result(state, reply)))
        st.enter_context(patch.object(talk.TA, "answer_path", lambda *a, **k: answer_res))
        st.enter_context(patch.object(talk.TA, "is_game_related", lambda *a: False))
        st.enter_context(patch.object(talk, "_record_hit", lambda *a, **k: None))
        st.enter_context(patch.object(talk, "_record_reply", lambda *a, **k: None))
        st.enter_context(patch.object(talk, "_link_cost_logs", lambda *a, **k: None))
        st.enter_context(patch.object(grid_public, "sold_card_items",
                                      lambda *a, **k: [{"price": p, "spec": {}} for p in prices]))
        yield


class EndToEnd(unittest.TestCase):
    STATE = {"usages": ["게임"], "budget_won": 1_500_000, "budget_bound": "이하"}

    def test_reply_does_not_promise_budget_or_frames(self):
        ans = TA.AnswerResult()
        with server(self.STATE, "네, 그 예산 안에서 구성하기 훨씬 수월해요. FHD 높음 옵션으로 60fps 이상 목표라면 좋아요.", ans):
            out = talk.parse_talk(talk.ParseBody(text=ASK2), request=None)
        self.assertNotIn("수월", out["reply"])
        self.assertNotIn("60fps", out["reply"])

    def test_answer_yes_replaced_when_cards_over_budget(self):
        ans = TA.AnswerResult(kind="pc_advice", topic=PA.TOPIC_BUILD,
                              answer="네, FHD로 낮추면 150만원 안에서 충분해요. 그래픽카드는 RTX 5060급이 맞아요.")
        with server(self.STATE, "", ans):
            out = talk.parse_talk(talk.ParseBody(text=ASK2), request=None)
        self.assertNotIn("충분해요", out["answer"])
        self.assertTrue(out["answer"].startswith("아쉽지만 지금 판매 중인 PC로는"), out["answer"])

    def test_answer_yes_kept_when_cards_fit(self):
        ans = TA.AnswerResult(kind="pc_advice", topic=PA.TOPIC_BUILD,
                              answer="네, FHD로 낮추면 150만원 안에서 충분해요. 그래픽카드는 RTX 5060급이 맞아요.")
        with server(self.STATE, "", ans, prices=(1_390_000,)):
            out = talk.parse_talk(talk.ParseBody(text=ASK2), request=None)
        self.assertNotIn("아쉽지만", out["answer"])        # 예산 안 카드가 있으면 «없다» 줄을 붙이지 않는다

    def test_game_intro_hidden_on_card_turn_with_budget(self):
        state = dict(self.STATE, game={"names": ["배틀그라운드"], "resolution": "1440p"})
        ans = TA.AnswerResult(kind="game", narrowing="ready",
                              answer="배틀그라운드는 크래프톤이 2017년에 출시한 게임이에요. 구성 상담은 여기서 다루지 않겠습니다.")
        with server(state, "", ans):
            out = talk.parse_talk(talk.ParseBody(text=ASK1), request=None)
        self.assertEqual(out["answer"], "")


if __name__ == "__main__":
    unittest.main()
