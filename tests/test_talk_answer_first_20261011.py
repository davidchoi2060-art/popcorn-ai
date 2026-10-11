"""답 먼저, 되묻기는 끝에 한 번 -- 2026-10-11 사장님이 일반 AI 답과 비교하고 지적한 대화를 고정한다.

사장님 대화(개발 서버 그대로):
  1턴 「개발자용 PC를 가장 저렴하게 추천해줘」 -> AI 가 예산을 되물었다
  2턴 「웹 개발, 예산은 최대한 싸게」        -> 「찾아드리겠습니다」만 했다
  카드는 두 턴 다 나왔지만 «가장 싸게»에 248만원 카드를 «추천»으로 함께 냈다.
AI 응답은 흉내 낸다(LLM 미호출).
"""
import contextlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from api import talk, talk_defaults as TD, talk_schema as TS
from api import talk_answer as TA
from tests.test_reco_explore import PRODUCTS, sets
from tests.test_talk_rules_20261010 import _Conn, vocab as base_vocab

DEV_WORK = "웹·스크립트 개발 (VS Code·브라우저·로컬 서버)"
OFFICE_WORK = "문서·웹·화상회의 (한글·오피스·크롬 탭 몇 개)"
WORKS = {"개발": DEV_WORK, "사무용": OFFICE_WORK}


def vocab():
    v = base_vocab()
    v.usages = list(v.usages) + [("개발", ["개발", "코딩"])]
    return v


def parse(text, ai_state, ai_reply, *, prev=None, chat_flow=None, ans=None):
    obj = {"pc": True, "state": ai_state, "missing": [], "evidence": [], "reply": ai_reply}
    result = SimpleNamespace(text=json.dumps(obj, ensure_ascii=False), provider="t", model="t",
                             tokens_in=1, elapsed_sec=0.1)
    ans = ans or TA.AnswerResult(answer="", narrowing=TS.NARROWING_WIDE)
    body = talk.ParseBody(text=text, state=prev, chat_flow=chat_flow)
    with contextlib.ExitStack() as st:
        st.enter_context(patch.object(talk.engine, "connect", lambda: _Conn()))
        st.enter_context(patch.object(talk.engine, "begin", lambda: _Conn()))
        st.enter_context(patch.object(talk.access_gate, "check_rate", lambda *a, **k: None))
        st.enter_context(patch.object(talk.TS, "load_vocab", lambda conn: vocab()))
        st.enter_context(patch.object(talk.TA, "run_parallel", lambda a, b: (result, ans)))
        st.enter_context(patch.object(talk.TA, "is_game_related", lambda *a: False))
        st.enter_context(patch.object(talk, "_record_hit", lambda *a, **k: None))
        st.enter_context(patch.object(TD, "basis_work", lambda fit: WORKS.get(fit)))
        return talk.parse_talk(body, request=None)


DEV_AFTER = "AI 학습이나 게임 개발까지 하시면 그래픽카드가 필요해 구성이 달라져요."


class OwnerConversation(unittest.TestCase):
    """사장님이 개발 서버에서 한 두 턴을 그대로 넣는다."""

    def assert_answer_first(self, r):
        self.assertEqual(r["missing"], [])                 # 화면이 이 턴에 추천 카드를 부른다
        self.assertNotIn("?", r["reply"])                  # 예산을 되묻지 않는다
        self.assertNotIn("찾아드리", r["reply"])
        self.assertIn(DEV_WORK, r["reply"])                # 무엇을 가정했는지 밝힌다
        self.assertIn("가장 싼 쪽", r["reply"])
        self.assertTrue(r["reply"].endswith(DEV_AFTER))    # 끝은 안내 한 줄
        self.assertFalse(r["chat_flow"]["asked"])

    def test_turn1_cheapest_developer_pc_answers_without_budget_question(self):
        r = parse("개발자용 PC를 가장 저렴하게 추천해줘",
                  {"usages": ["개발"], "budget_won": None, "budget_bound": "이하"},
                  "개발자용 PC를 찾고 계시는군요. 예산은 어느 정도 생각하세요?")
        self.assert_answer_first(r)
        self.assertIsNone(r["state"]["budget_won"])        # 예산을 지어내지 않는다

    def test_turn2_after_budget_question_answers_with_cards(self):
        prev = {"usages": ["개발"], "budget_won": None, "budget_bound": "이하"}
        r = parse("웹 개발, 예산은 최대한 싸게", dict(prev),
                  "웹 개발용으로 가장 저렴한 구성을 찾아드리겠습니다.",
                  prev=prev, chat_flow={"smalltalk_turns": 0})
        self.assert_answer_first(r)

    def test_cheapest_shows_only_the_cheapest_card(self):
        # 2턴 문장이 추천까지 가면 「가장 싸게」에 한 단계 위 구성을 «추천»으로 붙이지 않는다.
        state = TS.TalkState(usages=["영상편집"])
        cs = sets(state, {"wants": {}, "nav": "cheaper"})[0]
        self.assertEqual(len(cs["items"]), 1)
        self.assertEqual(cs["items"][0]["price"],
                         min(p["price"] for p in PRODUCTS.values() if p["fit"]["영상편집"]["rank"] >= 1))
        self.assertTrue(cs["explore"]["has_better"])         # 더 높은 사양은 빠른 선택으로 연다


ADVICE = ("개발용 PC는 그래픽카드보다 CPU와 메모리, SSD가 체감을 좌우해요. 웹 개발이라면 내장 그래픽으로도"
          " 충분해서 그래픽카드는 아껴도 돼요. 도커나 가상 머신을 여러 개 띄우면 램 32GB가 편해요.")


class ExplanationAboveCards(unittest.TestCase):
    """사장님 원칙: LLM 이 일반 AI 처럼 먼저 설명하고, 가정 한 줄로 마무리, 카드는 그 아래."""

    def test_turn1_has_explanation_then_assumption_and_cards(self):
        ans = TA.AnswerResult(answer=ADVICE, narrowing=TS.NARROWING_WIDE, kind="pc_advice")
        r = parse("개발자용 PC를 가장 저렴하게 추천해줘",
                  {"usages": ["개발"], "budget_won": None},
                  "개발자용 PC를 찾고 계시는군요.", ans=ans)
        self.assertEqual(r["answer"], ADVICE)               # 화면 말풍선 위쪽
        self.assertEqual(r["missing"], [])                  # 같은 턴에 저렴한 카드를 부른다
        self.assertIn("가장 싼 쪽", r["reply"])            # 가정 한 줄이 설명 끝에
        self.assertTrue(r["reply"].endswith(DEV_AFTER))
        self.assertNotIn("?", r["answer"] + r["reply"])

    def test_explanation_is_dropped_on_laptop_turns(self):
        ans = TA.AnswerResult(answer=ADVICE, narrowing=TS.NARROWING_WIDE, kind="pc_advice")
        r = parse("개발용 노트북 추천해줘", {"usages": ["개발"]},
                  "개발용 PC를 찾고 계시는군요.", ans=ans)
        self.assertEqual(r["answer"], "")              # 노트북 안내가 먼저다


class PriceWords(unittest.TestCase):
    CASES = {
        "최대한 싸게": TD.PREF_CHEAPEST, "가장 저렴하게": TD.PREF_CHEAPEST, "제일 싼 걸로": TD.PREF_CHEAPEST,
        "싼 거로 주세요": TD.PREF_CHEAPEST, "제일 좋은 걸로": TD.PREF_TOP, "최고 사양으로": TD.PREF_TOP,
        "좋은 걸로 해줘": TD.PREF_TOP, "적당히": TD.PREF_WIDE, "예산은 상관없어": TD.PREF_WIDE,
        "알아서 해줘": TD.PREF_WIDE, "150만원 정도": None, "롤 하려고요": None,
    }

    def test_price_words_map_to_defaults(self):
        for text, want in self.CASES.items():
            with self.subTest(text=text):
                self.assertEqual(TD.price_pref(text), want)

    def test_wide_and_top_skip_the_budget_question(self):
        for text, line in (("사무용 적당히", TD.PREF_LINE[TD.PREF_WIDE]),
                           ("사무용 제일 좋은 걸로", TD.PREF_LINE[TD.PREF_TOP])):
            with self.subTest(text=text):
                r = parse(text, {"usages": ["사무·인강"]}, "예산은 얼마 정도 생각하세요?")
                self.assertNotIn("?", r["reply"])
                self.assertIn(line, r["reply"])
                self.assertIn(OFFICE_WORK, r["reply"])

    def test_unnamed_game_with_price_word_gets_cards(self):
        r = parse("게임용 최대한 싸게", {"usages": ["게임"], "game": {"names": []}}, "어떤 게임 하세요?")
        self.assertEqual(r["missing"], [])
        self.assertIn("FHD(1080p)", r["reply"])
        self.assertTrue(r["reply"].endswith(TD.USAGE_AFTER["게임"]))
        self.assertNotIn("?", r["reply"])


class NeverAskTwice(unittest.TestCase):
    def test_usage_question_once_then_assumed_general_use(self):
        first = parse("컴퓨터 하나 사려고요", {}, "어떤 용도로 쓰실 건가요?")
        self.assertEqual(first["missing"], [TS.MISSING_USAGES])
        self.assertTrue(first["chat_flow"]["asked"])
        second = parse("음 잘 모르겠어요", {}, "주로 어떤 작업을 하시나요?",
                       prev=first["state"], chat_flow=first["chat_flow"])
        self.assertEqual(second["missing"], [])
        self.assertEqual(second["state"]["usages"], ["사무·인강"])
        self.assertIn("일반 용도를 가정했어요", second["reply"])
        self.assertIn(OFFICE_WORK, second["reply"])
        self.assertNotIn("?", second["reply"])
        self.assertFalse(second["chat_flow"]["asked"])

    def test_question_after_question_becomes_an_answer(self):
        r = parse("개발이요", {"usages": ["개발"]}, "어떤 개발을 하시나요?",
                  chat_flow={"asked": True})
        self.assertNotIn("?", r["reply"])
        self.assertIn(DEV_WORK, r["reply"])


class LeavesGoodAnswersAlone(unittest.TestCase):
    def test_budget_given_and_no_question_keeps_ai_reply(self):
        r = parse("개발용 150만원", {"usages": ["개발"], "budget_won": 1500000},
                  "개발용 PC를 150만원으로 찾고 계시는군요.")
        self.assertEqual(r["reply"], "개발용 PC를 150만원으로 찾고 계시는군요.")

    def test_first_usage_question_is_still_asked_once(self):
        r = parse("PC 추천해줘", {}, "어떤 용도로 쓰실 건가요?")
        self.assertEqual(r["reply"], "어떤 용도로 쓰실 건가요?")
        self.assertTrue(r["chat_flow"]["asked"])

    def test_no_basis_when_fit_table_unreadable(self):
        line = TD.answer_first(TS.TalkState(usages=["개발"]), TD.PREF_CHEAPEST,
                               is_game_usage=TS.is_game_usage, work_of=lambda fit: None)
        self.assertEqual(line, TD.PREF_LINE[TD.PREF_CHEAPEST] + " " + DEV_AFTER)

    def test_every_after_line_is_a_known_usage(self):
        from api.sold_reco import USAGE_RULES
        self.assertTrue(set(TD.USAGE_AFTER) <= {fit for _key, fit in USAGE_RULES})
        for line in TD.USAGE_AFTER.values():
            self.assertNotIn("?", line)


if __name__ == "__main__":
    unittest.main()


class PartQuestionDoesNotStartBuying(unittest.TestCase):
    def test_part_question_gets_explanation_without_usage_question(self):
        ans = TA.AnswerResult(answer="SSD는 저장 공간이고 메모리는 작업 공간이에요.", narrowing=TS.NARROWING_WIDE,
                              kind="pc_advice", topic="part")
        r = parse("SSD랑 메모리 차이가 뭐예요", {}, "어떤 용도로 쓰실 PC인가요?", ans=ans)
        self.assertEqual(r["answer"], "SSD는 저장 공간이고 메모리는 작업 공간이에요.")
        self.assertEqual(r["reply"], "")                    # 새 PC 용도를 묻지 않는다
        self.assertFalse(r["chat_flow"]["asked"])

    def test_plain_pc_request_without_usage_still_asks_once(self):
        ans = TA.AnswerResult(answer="PC는 쓰는 일에 따라 중요한 부품이 달라요.", narrowing=TS.NARROWING_WIDE,
                              kind="pc_advice", topic="build")
        r = parse("PC 추천해줘", {}, "주로 어떤 일에 쓰실 PC인가요?", ans=ans)
        self.assertEqual(r["reply"], "주로 어떤 일에 쓰실 PC인가요?")   # 설명 뒤 핵심 질문 하나
        self.assertTrue(r["chat_flow"]["asked"])
