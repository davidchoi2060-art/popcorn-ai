"""대화가 이어지는 부분 -- 2026-10-20 대표 승인(형광펜 노트 + 카드 브리핑 패킷 · 수용 기준 C01~C09).

신고 화면: 영상편집 200만원 이하로 2대를 소개한 뒤 「위 2번째 상품으로 오버워치 게임도가능한가요?」에
두 번째 PC 도 오버워치도 아닌 「영상편집용은 프리미어·다빈치 FHD 컷편집 (유튜브) 기준으로 봤어요. 4K 편집이나
색보정까지 하시면 사양이 달라져요.」만 나갔다. 아래는 그 대화를 흉내 낸다(AI 응답은 흉내 -- 실제 공급자 호출 없음).

  ① 「N번째」는 서버가 화면이 보낸 «직전 답변 묶음»의 상품번호로 정한다 -- 오른쪽 목록과 순서가 달라도 섞지 않는다.
  ② 도구 상담(agent)·지금 경로(fallback) 둘 다 같은 PC 를 받는다.
  ③ 앞 PC 를 가리킨 후속 질문의 답을 앞 용도 정형문(answer_first)으로 덮지 않는다.
"""
import contextlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from api import llm, talk, talk_agent as AG, talk_answer as TA, talk_defaults as TD, talk_schema as TS, talk_tools as TT
from tests.test_talk_rules_20261010 import _Conn, vocab as base_vocab

A, B, C = 98149, 129823, 97000
ITEMS = {
    A: {"product_code": A, "name": "골드 인텔 [12400F/16GB/500GB/RTX5060]", "price": 1_625_800,
        "spec": {"cpu": "i5-12400F", "gpu": "RTX 5060", "ram_gb": 16, "ssd_gb": 500}},
    B: {"product_code": B, "name": "[14400F/32G/1TB/RTX5060Ti]", "price": 1_889_500,
        "spec": {"cpu": "i5-14400F", "gpu": "RTX 5060 Ti 8GB", "ram_gb": 32, "ssd_gb": 1000}},
    C: {"product_code": C, "name": "다이아 [14400F/32G/1TB/RTX5060Ti]", "price": 2_313_600,
        "spec": {"cpu": "i5-14400F", "gpu": "RTX 5060 Ti 8GB", "ram_gb": 32, "ssd_gb": 1000}},
}
PREV = {"usages": ["영상편집"], "budget_won": 2_000_000, "budget_bound": "이하"}
ASKED = "위 2번째 상품으로 오버워치 게임도가능한가요?"
CANNED = TD.AFTER["영상편집"] if hasattr(TD, "AFTER") else "4K 편집이나 색보정까지 하시면 사양이 달라져요."


def ctx(answer=(A, B), right=(A, C), selected=None, set_id="t3-s"):
    return TS.DisplayContext(screen="results", source="catalog", cards=[{"product_code": c} for c in right],
                             selected={"product_code": selected} if selected else None,
                             answer_sets=[{"set_id": set_id, "cards": [{"product_code": c} for c in answer]}])


def screen_item(items=ITEMS):
    return patch.object(TT, "_screen_item", lambda state, code: dict(items[code]) if code in items else None)


class Ordinal(unittest.TestCase):
    CASES = {
        ASKED: ("answer", 2), "그럼 첫 번째는?": ("answer", 1), "세 번째 PC 메모리 얼마예요": ("answer", 3),
        "2번 상품 사양 알려줘": ("answer", 2), "둘째 거는요?": ("answer", 2),
        "오른쪽 두 번째는 어때요": ("right", 2), "오른쪽 목록에서 2번째": ("right", 2),
        "선택한 상품 게임 돼요?": ("selected", None),
    }
    NONE = ("RTX 2060 들어간 거", "예산을 150만원으로 바꿀게요", "11번째", "1TB 2개", "한 번 더 보여줘", "게임은 가끔, 편집이 주용도예요")

    def test_cases(self):
        for text, (kind, n) in self.CASES.items():
            self.assertEqual(TT.ordinal_reference(text), {"kind": kind, "ordinal": n}, text)
        for text in self.NONE:
            self.assertIsNone(TT.ordinal_reference(text), text)


class Resolve(unittest.TestCase):
    def _r(self, text, context=None, items=ITEMS):
        book = TT.FactBook()
        with screen_item(items):
            return TT.resolve_reference(text, context or ctx(), PREV, book), book

    def test_c01_second_of_the_last_answer_not_the_right_list(self):
        r, book = self._r(ASKED)
        self.assertEqual((r["source"], r["ordinal"], r["status"], r["product_code"], r["set_id"]),
                         ("last_answer", 2, "ok", B, "t3-s"))
        self.assertEqual(book.items[r["ref"]]["product_code"], B)
        self.assertIn(1_889_500, book.prices)               # 그 PC 의 지금 판매가를 말해도 된다

    def test_c02_then_the_first(self):
        r, _ = self._r("그럼 첫 번째는?")
        self.assertEqual((r["product_code"], r["ordinal"]), (A, 1))

    def test_c06_right_second_is_the_right_list(self):
        r, _ = self._r("오른쪽 두 번째는 오버워치 돼요?")
        self.assertEqual((r["source"], r["product_code"]), ("right_list", C))

    def test_selected(self):
        r, _ = self._r("선택한 상품 게임 돼요?", ctx(selected=C))
        self.assertEqual((r["source"], r["product_code"]), ("selected", C))

    def test_missing_ordinal_is_not_invented(self):
        r, book = self._r("세 번째 PC 는요?")
        self.assertEqual((r["status"], r["count"]), ("missing", 2))
        self.assertNotIn("ref", r)
        self.assertEqual(book.items, {})

    def test_c06_not_on_sale_is_not_swapped(self):
        r, book = self._r(ASKED, items={A: ITEMS[A], C: ITEMS[C]})
        self.assertEqual((r["status"], r["product_code"]), ("not_on_sale", B))
        self.assertEqual(book.items, {})                     # 다른 PC(C)로 바꾸지 않는다

    def test_no_answer_set_falls_back_to_the_screen_and_says_so(self):
        c = TS.DisplayContext(screen="results", source="catalog", cards=[{"product_code": A}, {"product_code": C}])
        r, _ = self._r(ASKED, c)
        self.assertEqual((r["source"], r["product_code"]), ("right_list_fallback", C))

    def test_plain_turn_reads_nothing(self):
        with patch.object(TT, "_screen_item", side_effect=AssertionError("read")):
            self.assertIsNone(TT.resolve_reference("예산을 150만원으로 바꿀게요", ctx(), PREV, TT.FactBook()))

    def test_schema_limits(self):
        with self.assertRaises(Exception):
            TS.DisplayContext(screen="results", source="catalog",
                              answer_sets=[{"set_id": "x y", "cards": []}])
        with self.assertRaises(Exception):
            TS.DisplayContext(screen="results", source="catalog", answer_sets=[{"set_id": "a", "cards": []}] * 4)


VOCAB = TS.Vocab(usages=[("영상편집", []), ("게임", [])])


def _turn(text="", calls=()):
    return llm.ToolTurn(provider="codex", model="m", text=text, tool_calls=list(calls), raw={},
                        tokens_in=1, tokens_out=1, cached_in=0, cost_usd=0.0, elapsed_sec=0.1,
                        log_id=1, cost_logged=True, stop="completed")


class _Engine:
    def connect(self):
        return _Conn()


class AgentTurn(unittest.TestCase):
    """도구 상담 경로 -- AI 에게 그 PC 가 먼저 주어지고, 답·응답에 같은 상품번호가 남는다."""

    def _run(self, script, text, history=(), context=None, marks=False):
        sent = []

        def fake_call(msgs, tools, **kw):
            sent.append({"system": kw["system"], "msgs": [dict(m) for m in msgs]})
            return script.pop(0)
        with screen_item(), patch.object(AG, "engine", _Engine()), patch.object(AG, "load_vocab", lambda c: VOCAB), \
                patch.object(AG.llm, "call_tools", fake_call), patch.object(TT, "display_facts", lambda c: None):
            out = AG.run_turn(text, [AG.Turn(**h) for h in history], prev_state=PREV,
                              display_context=context or ctx(), marks=marks)
        return out, sent

    def test_c01_referenced_pc_and_last_answer_are_given_first(self):
        reply = ("두 번째 PC([14400F/32G/1TB/RTX5060Ti])는 RTX 5060 Ti 8GB라 오버워치 2 같은 가벼운 게임은 무리 없이 돌아가요. "
                 "정확한 프레임은 자료로 확인되지 않았어요. 영상편집용 200만원 이하 조건은 그대로예요.")
        out, sent = self._run([_turn(reply)], ASKED)
        ctx_json = json.loads(sent[0]["system"].split("\n")[-1])
        ref = ctx_json["referenced_pc"]
        self.assertEqual((ref["source"], ref["ordinal"], ref["product_code"]), ("last_answer", 2, B))
        self.assertEqual([i["product_code"] for i in ctx_json["last_answer_pcs"]["items"]], [A, B])
        self.assertEqual(out["reference"], {"source": "last_answer", "ordinal": 2, "set_id": "t3-s",
                                            "status": "ok", "product_code": B})
        self.assertIn("오버워치", out["reply"])
        self.assertNotIn(CANNED, out["reply"])

    def test_c05_long_answer_history_is_not_the_only_memory(self):
        long_answer = "영상 편집용으로 200만 원 이하에서 3가지를 찾았습니다. " + "설명 " * 200 + "- 다이아 [14400F/32G/1TB/RTX5060Ti]"
        history = [{"role": "user", "text": "영상편집 200만원 이하"}, {"role": "assistant", "text": long_answer}]
        out, sent = self._run([_turn("세 번째 PC 메모리는 32GB예요.")], "세 번째 PC 메모리는요?", history,
                              ctx(answer=(A, B, C)))
        ctx_json = json.loads(sent[0]["system"].split("\n")[-1])
        self.assertEqual(ctx_json["referenced_pc"]["product_code"], C)   # 잘린 기록이 아니라 묶음의 3번째
        hist = [m for m in sent[0]["msgs"] if m["role"] == "assistant"]
        self.assertLessEqual(len(hist[0]["text"]), AG.HISTORY_CHARS)

    def test_marks_rule_only_when_asked(self):
        _, sent = self._run([_turn("답")], "게임용 PC 추천해줘", marks=False)
        self.assertNotIn("==어구==", sent[0]["system"])
        _, sent = self._run([_turn("답")], "게임용 PC 추천해줘", marks=True)
        self.assertIn("==어구==", sent[0]["system"])

    def test_marks_are_stripped_from_history(self):
        _, sent = self._run([_turn("답")], "그럼 첫 번째는?",
                            [{"role": "user", "text": "a"}, {"role": "assistant", "text": "그래픽카드의 ==VRAM과 메모리==가 중요합니다."}])
        self.assertIn("그래픽카드의 VRAM과 메모리가 중요합니다.", [m["text"] for m in sent[0]["msgs"]])

    def test_as_parse_reports_reference(self):
        fake = {"ok": True, "status": "ok", "reply": "답", "notes": [], "state": None, "nav": None, "units": None,
                "cards": [], "reference": {"source": "last_answer", "ordinal": 2, "set_id": "t3-s", "status": "ok",
                                           "product_code": B}}
        with patch.object(AG, "run_turn", lambda *a, **k: fake):
            r = AG.as_parse(ASKED, [], PREV, None, display_context=ctx())
        self.assertEqual(r["agent_meta"]["reference"]["product_code"], B)

    def test_prompt_rules(self):
        self.assertIn("referenced_pc", AG.SYSTEM)
        self.assertIn("새 추천을 다시 시작하거나 앞의 용도 안내만 되풀이하지 않는다", AG.SYSTEM)
        self.assertIn("last_answer_pcs", AG.SYSTEM)


def fallback_parse(text, ai_reply, *, context=None, ans=None):
    """도구 상담이 실패해 지금 경로가 받는 턴(talk.parse_talk). [A]·[B] 응답은 흉내."""
    obj = {"pc": True, "state": dict(PREV), "missing": [], "evidence": [], "reply": ai_reply}
    result = SimpleNamespace(text=json.dumps(obj, ensure_ascii=False), provider="t", model="t", tokens_in=1, elapsed_sec=0.1)
    ans = ans or TA.AnswerResult(answer="", narrowing=TS.NARROWING_WIDE)
    seen = {}

    def run_parallel(a, b):
        seen["prompt"] = a.__closure__ and None
        return result, ans
    v = base_vocab()
    v.usages = list(v.usages) + [("영상편집", ["영상", "편집"])]
    body = talk.ParseBody(text=text, state=dict(PREV), chat_flow={"smalltalk_turns": 0, "asked": True},
                          display_context=context)
    built = {}
    real_build = talk._build_prompt

    def build(text_, vocab_, prev, history, entry):
        built["history"] = list(history)
        return real_build(text_, vocab_, prev, history, entry)
    with contextlib.ExitStack() as st:
        st.enter_context(patch.object(talk.engine, "connect", lambda: _Conn()))
        st.enter_context(patch.object(talk.engine, "begin", lambda: _Conn()))
        st.enter_context(patch.object(talk.access_gate, "check_rate", lambda *a, **k: None))
        st.enter_context(patch.object(talk.TS, "load_vocab", lambda conn: v))
        st.enter_context(patch.object(talk.TA, "run_parallel", run_parallel))
        st.enter_context(patch.object(talk.TA, "is_game_related", lambda *a: False))
        st.enter_context(patch.object(talk, "_record_hit", lambda *a, **k: None))
        st.enter_context(patch.object(talk, "_build_prompt", build))
        st.enter_context(patch.object(AG, "enabled", lambda: False))
        st.enter_context(screen_item())
        return talk.parse_talk(body, request=None), built


class FallbackTurn(unittest.TestCase):
    """지금 경로 -- 신고 화면과 같은 「?」 있는 답이 앞 용도 정형문으로 바뀌던 분기."""

    AI = "두 번째 PC는 RTX 5060 Ti 8GB라 오버워치 2는 무난히 돌아가요. 더 높은 프레임을 원하시나요?"

    # 시험 어휘에는 확정 게임이 없어 「오버워치」 문장은 게임 등급을 되묻는 분기로 간다. 정형문 덮어쓰기 자체는
    # 용도가 그대로인 같은 꼴의 질문으로 재현한다(운영 어휘에서는 오버워치도 이 분기로 들어갔다 -- 신고 화면).
    ASKED_EDIT = "위 2번째 상품으로 프리미어도 잘 되나요?"
    AI_EDIT = "두 번째 PC는 RTX 5060 Ti 8GB라 프리미어 FHD 컷편집은 넉넉해요. 4K 도 하시나요?"

    def test_without_reference_the_old_branch_still_replaces(self):
        # 묶음을 안 보내는 예전 화면 -- 지금 동작 그대로(이 분기 자체를 지우지 않는다)
        r, built = fallback_parse(self.ASKED_EDIT, self.AI_EDIT)
        self.assertNotIn("넉넉해요", r["reply"])
        self.assertIn("4K 편집이나 색보정", r["reply"])          # 신고 화면의 정형문이 이렇게 나왔다

    def test_with_reference_the_answer_survives(self):
        r, built = fallback_parse(self.ASKED_EDIT, self.AI_EDIT, context=ctx())
        self.assertIn("넉넉해요", r["reply"])
        self.assertNotIn("4K 편집이나 색보정", r["reply"])

    def test_c01_reference_keeps_the_answer_and_names_the_pc(self):
        r, built = fallback_parse(ASKED, self.AI, context=ctx())
        self.assertIn("오버워치", r["reply"])
        self.assertNotIn("4K 편집이나 색보정", r["reply"])
        note = built["history"][-1]
        self.assertEqual(note[0], "assistant")
        self.assertIn("직전 답변의 2번째", note[1])
        self.assertIn("[14400F/32G/1TB/RTX5060Ti]", note[1])
        self.assertEqual(r["state"]["budget_won"], 2_000_000)   # 예산·주용도는 그대로
        self.assertEqual(r["state"]["usages"], ["영상편집"])

    def test_missing_ordinal_note(self):
        r, built = fallback_parse("세 번째 PC 는 오버워치 돼요?", self.AI, context=ctx())
        self.assertIn("없다(2대만 있었다)", built["history"][-1][1])


if __name__ == "__main__":
    unittest.main()


class ExplicitChange(unittest.TestCase):
    def test_change_words_are_explicit(self):
        import api.talk as T
        self.assertTrue(T._RE_EXPLICIT_CHANGE.search("위 2번째 말고 게임용으로 바꿔줘"))
        self.assertFalse(T._RE_EXPLICIT_CHANGE.search("위 2번째 상품으로 오버워치 게임도가능한가요?"))
