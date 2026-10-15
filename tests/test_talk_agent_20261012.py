"""도구 상담 경로(/api/talk/chat) -- 2026-10-12 LLM 중심 상담 ② 단계. 개발 서버 전용 스위치.

① llm.call_tools: 공급자와 무관한 대화 모양 -> 공급자별 번역, 캡·비용 기록·폴백은 call() 과 같은 길.
② talk_tools: AI 가 고른 인자를 서버가 다시 검사하고, 상품은 이 턴에 보여 준 번호로만 가리킨다. 기록을 남기지 않는다.
③ talk_agent: 턴 한도 · 같은 호출 재사용 · 카드는 사실 묶음에서만 · 묶음에 없는 금액과 약속 문장은 뺀다 · 실패는 실패로.
AI 응답은 흉내 낸다(실제 공급자 호출 없음).
"""
import contextlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from api import llm, talk_agent as AG, talk_tools as TT
from api.talk_schema import Vocab


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Engine:
    def connect(self):
        return _Conn()


# ── ① llm.call_tools ──────────────────────────────────────────────────────
CONVO = [
    {"role": "user", "text": "게임용 PC 150만원"},
    {"role": "assistant", "text": "찾아볼게요.", "tool_calls": [
        {"id": "c1", "name": "find_pcs", "args": {"usages": ["게임"]}},
        {"id": "c2", "name": "shop_policy", "args": {"topic": "os"}}]},
    {"role": "tool", "id": "c1", "name": "find_pcs", "content": '{"status":"ok"}'},
    {"role": "tool", "id": "c2", "name": "shop_policy", "content": '{"status":"ok"}'},
]


class Translate(unittest.TestCase):
    def test_claude_groups_tool_results_in_one_user_message(self):
        out = llm._claude_messages(CONVO)
        self.assertEqual([m["role"] for m in out], ["user", "assistant", "user"])
        self.assertEqual([b["type"] for b in out[1]["content"]], ["text", "tool_use", "tool_use"])
        self.assertEqual([b["tool_use_id"] for b in out[2]["content"]], ["c1", "c2"])

    def test_openai_function_call_items(self):
        out = llm._openai_input(CONVO)
        self.assertEqual(out[2]["type"], "function_call")
        self.assertEqual(json.loads(out[2]["arguments"]), {"usages": ["게임"]})
        self.assertEqual([o.get("type") for o in out[-2:]], ["function_call_output"] * 2)

    def test_same_provider_raw_is_replayed(self):
        convo = [CONVO[0], dict(CONVO[1], raw={"codex": [{"type": "reasoning", "id": "r1"}]})]
        self.assertEqual(llm._openai_input(convo)[1], {"type": "reasoning", "id": "r1"})
        # 다른 공급자로 넘어가면 원형이 아니라 번역본을 쓴다
        self.assertEqual(llm._claude_messages(convo)[1]["content"][1]["type"], "tool_use")

    def test_broken_arguments_are_marked(self):
        self.assertIn("__invalid__", llm._parse_args("{not json"))
        self.assertIn("__invalid__", llm._parse_args("[1,2]"))
        self.assertEqual(llm._parse_args('{"a":1}'), {"a": 1})


class CallTools(unittest.TestCase):
    def _run(self, callers):
        logged = []
        with patch.object(llm, "_TOOL_CALLERS", callers), \
                patch.object(llm, "_check_caps", lambda *a, **k: None), \
                patch.object(llm, "engine", _Engine()), \
                patch.object(llm, "_insert_cost_log", lambda row: logged.append(row) or 7), \
                patch.dict("os.environ", {"ANTHROPIC_API_KEY": "x", "OPENAI_API_KEY": "x", llm.REROUTE_ENV: "off"}):
            r = llm.call_tools(CONVO[:1], [], task_key="task.talk_agent", provider="claude",
                               fallback_order=["codex"])
        return r, logged

    def test_cost_logged_with_task_key(self):
        ok = lambda *a: ("답", [], [], 100, 20, 30, "end_turn")  # noqa: E731
        r, logged = self._run({"claude": ok, "codex": ok})
        self.assertEqual((r.provider, r.text, r.log_id, r.cached_in), ("claude", "답", 7, 30))
        self.assertEqual(logged[0]["tk"], "task.talk_agent")

    def test_transient_failure_falls_back_to_other_provider(self):
        def down(*a):
            raise llm.LLMProviderError("529", transient=True)
        ok = lambda *a: ("", [{"id": "x", "name": "find_pcs", "args": {}}], [], 1, 1, None, "completed")  # noqa: E731
        r, _ = self._run({"claude": down, "codex": ok})
        self.assertEqual(r.provider, "codex")
        self.assertEqual(r.tool_calls[0]["name"], "find_pcs")

    def test_empty_answer_is_an_error_not_success(self):
        empty = lambda *a: ("", [], [], 1, 1, None, "end_turn")  # noqa: E731
        with self.assertRaises(llm.LLMError):
            self._run({"claude": empty, "codex": empty})


# ── ② talk_tools ──────────────────────────────────────────────────────────
ITEM = {"product_code": 1001, "name": "게임 PC A", "price": 1_498_000, "spec": {"gpu": "RTX 5060", "ram_gb": 16},
        "level": "상", "over_budget": False, "reasons": ["게임 상"], "mall_url": "https://x/1001"}


def _reco(**over):
    base = {"card_sets": [{"usage": "게임", "items": [ITEM]}], "needs": [], "assumed": [], "dropped": [],
            "talk_notes": [], "budget_won": 1_500_000, "budget_bound": "이하", "game_grade": "B",
            "game_resolution": "1080p", "platform": "인텔", "anchor_code": 1001}
    base.update(over)
    return base


class Tools(unittest.TestCase):
    def test_find_pcs_never_sends_grade_so_nothing_is_recorded(self):
        from api import grid_public as GP
        seen = {}
        def fake(body):
            seen["state"] = body.state
            return _reco()
        with patch.object(GP, "recommend", fake):
            book = TT.FactBook()
            r = TT.find_pcs({"usages": ["게임"], "games": ["발로란트"], "budget_won": 1_500_000,
                             "grade": "A", "grade_src": "ai_estimate"}, book)
        self.assertEqual(seen["state"]["game"], {"names": ["발로란트"], "resolution": None})
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["sets"][0]["items"][0]["ref"], "P1")
        self.assertIn(1_498_000, book.prices)
        self.assertEqual(book.condition["game_grade"], "B")

    def test_find_pcs_reports_needs_and_empty_separately(self):
        from api import grid_public as GP
        with patch.object(GP, "recommend", lambda b: _reco(card_sets=[], needs=["game.grade"])):
            self.assertEqual(TT.find_pcs({"usages": ["게임"]}, TT.FactBook())["status"], "needs")
        with patch.object(GP, "recommend", lambda b: _reco(card_sets=[{"usage": "게임", "items": []}])):
            self.assertEqual(TT.find_pcs({"usages": ["게임"]}, TT.FactBook())["status"], "empty")

    def test_bad_arguments_are_refused(self):
        b = TT.FactBook()
        self.assertEqual(TT.find_pcs({"usages": "게임"}, b)["status"], "invalid")
        self.assertEqual(TT.find_pcs({"usages": ["게임"], "budget_won": True}, b)["status"], "invalid")
        self.assertEqual(TT.find_pcs({"usages": ["게임"], "nav": "cheaper"}, b)["status"], "invalid")

    def test_products_only_by_refs_shown_this_turn(self):
        b = TT.FactBook()
        self.assertEqual(TT.pc_detail({"ref": "P1"}, b)["status"], "invalid")
        self.assertEqual(TT.show_pcs({"refs": ["P9"]}, b)["status"], "invalid")
        ref = b.add_item(dict(ITEM))
        self.assertEqual(b.add_item(dict(ITEM)), ref)          # 같은 상품은 같은 번호
        self.assertEqual(TT.show_pcs({"refs": [ref, ref]}, b), {"status": "ok", "shown": [ref]})
        ref2 = b.add_item(dict(ITEM, product_code=1002))
        self.assertEqual(TT.show_pcs({"refs": [ref2, ref]}, b)["shown"], [ref, ref2])   # 엔진 순서

    def test_pc_detail_unknown_price_stays_null(self):
        from api import customer_pc_offer as OFFER
        b = TT.FactBook()
        ref = b.add_item(dict(ITEM))
        cfg = {"configuration_id": 9, "revision": 2, "parts": [{"name": "RTX 5060", "price": None},
                                                             {"name": "DDR5 16GB", "price": 85_000}]}
        with patch.object(OFFER, "public_item", lambda code: {"public_configuration": cfg}):
            r = TT.pc_detail({"ref": ref}, b)
        self.assertEqual([p["price_state"] for p in r["parts"]], ["확인 중", "확인됨"])
        self.assertIn(85_000, b.prices)
        with patch.object(OFFER, "public_item", lambda code: {"public_configuration": None}):
            self.assertEqual(TT.pc_detail({"ref": ref}, b)["status"], "unknown")

    def test_tool_exception_is_not_leaked(self):
        b = TT.FactBook()
        with patch.dict(TT.EXECUTORS, {"find_pcs": lambda a, bk: 1 / 0}):
            r = TT.run("find_pcs", {"usages": ["게임"]}, b)
        self.assertEqual(r["status"], "error")
        self.assertNotIn("ZeroDivision", json.dumps(r, ensure_ascii=False))
        self.assertEqual(TT.run("drop_table", {}, b)["status"], "invalid")
        self.assertEqual(TT.run("find_pcs", {"__invalid__": "x"}, b)["status"], "invalid")

    def test_encode_truncates_lists_not_json(self):
        big = {"status": "ok", "sets": [{"x": "가" * 3000}] * 5}
        out = json.loads(TT.encode(big))
        self.assertTrue(out["truncated"])


# ── ③ talk_agent ──────────────────────────────────────────────────────────
VOCAB = Vocab(usages=[("게임", []), ("사무·인강", [])])


def _turn(text="", calls=(), cost=0.001):
    return llm.ToolTurn(provider="codex", model="gpt-5.6-luna", text=text, tool_calls=list(calls), raw={},
                        tokens_in=100, tokens_out=20, cached_in=0, cost_usd=cost, elapsed_sec=0.1,
                        log_id=1, cost_logged=True, stop="completed")


class Agent(unittest.TestCase):
    def _run(self, script, text="게임용 PC 150만원 이하로 추천해줘", history=(), reco=None):
        from api import grid_public as GP
        sent = []
        def fake_call(msgs, tools, **kw):
            sent.append(([dict(m) for m in msgs], [t["name"] for t in tools]))
            step = script.pop(0)
            if isinstance(step, Exception):
                raise step
            return step
        with patch.object(AG, "engine", _Engine()), patch.object(AG, "load_vocab", lambda c: VOCAB), \
                patch.object(AG.llm, "call_tools", fake_call), \
                patch.object(GP, "recommend", lambda b: reco or _reco()):
            out = AG.run_turn(text, [AG.Turn(**h) for h in history])
        return out, sent

    def test_recommend_flow_cards_come_from_server_facts(self):
        out, sent = self._run([
            _turn(calls=[{"id": "a", "name": "find_pcs", "args": {"usages": ["게임"], "budget_won": 1_500_000}}]),
            _turn(calls=[{"id": "b", "name": "show_pcs", "args": {"refs": ["P1"]}}]),
            _turn("150만원 이하로는 게임 PC A가 맞아요. 판매가는 1,498,000원이에요. 비슷한 PC가 120만원에도 있어요."),
        ])
        self.assertEqual(out["status"], "ok")
        self.assertEqual([c["product_code"] for c in out["cards"]], [1001])
        self.assertEqual(out["cards"][0]["price"], 1_498_000)          # 서버 값
        self.assertIn("1,498,000원", out["reply"])
        self.assertNotIn("120만원", out["reply"])                      # 묶음에 없는 금액 -> 문장째 뺀다
        self.assertEqual(out["dropped_sentences"][0]["reason"], "price_not_in_snapshot")
        self.assertEqual(out["meta"]["rounds"], 3)
        self.assertEqual(out["snapshot"]["condition"]["budget_won"], 1_500_000)
        tool_msg = sent[1][0][-1]
        self.assertEqual(tool_msg["role"], "tool")
        self.assertEqual(json.loads(tool_msg["content"])["sets"][0]["items"][0]["ref"], "P1")

    def test_explanation_only_needs_no_tools_and_no_cards(self):
        out, sent = self._run([_turn("램은 여러 작업을 동시에 할 때, SSD는 저장과 로딩 속도에 영향을 줘요.")],
                              text="램이랑 SSD 차이가 뭐예요?")
        self.assertEqual((out["status"], out["cards"], out["meta"]["tool_calls"]), ("ok", [], 0))

    def test_repeated_same_call_is_not_rerun_and_last_round_has_no_tools(self):
        call = {"id": "a", "name": "find_pcs", "args": {"usages": ["게임"]}}
        out, sent = self._run([_turn(calls=[call]), _turn(calls=[dict(call, id="b")]),
                               _turn(calls=[dict(call, id="c")]), _turn("찾은 PC를 보여 드릴게요.")])
        self.assertEqual(out["meta"]["tool_calls"], 1)
        self.assertEqual(sent[-1][1], [])                 # 마지막 왕복은 도구 없이
        self.assertEqual(out["meta"]["rounds"], AG.MAX_ROUNDS)

    def test_llm_failure_is_reported_as_failure(self):
        out, _ = self._run([llm.LLMProviderError("down", transient=True)])
        self.assertEqual((out["ok"], out["status"], out["cards"]), (False, "failed", []))
        self.assertEqual(out["reply"], AG.TE.REPLY_AI_UNREADABLE)

    def test_self_harm_is_answered_without_ai(self):
        out, sent = self._run([], text="요즘 너무 힘들어서 죽고 싶어요")
        self.assertEqual((out["status"], out["kind"], sent), ("fixed", "self_harm", []))

    def test_personal_numbers_are_masked_before_ai(self):
        out, sent = self._run([_turn("네, 용도를 알려 주세요.")],
                              text="카드 1234-5678-1234-5678 로 사도 돼요? 연락은 010-1234-5678, a.b@ex.com",
                              history=[{"role": "assistant", "text": "안녕하세요"},
                                       {"role": "user", "text": "주민 900101-1234567"}])
        joined = json.dumps(sent[0][0], ensure_ascii=False)
        self.assertNotIn("1234-5678", joined)
        self.assertNotIn("1234567", joined)
        self.assertNotIn("010-1234", joined)
        self.assertNotIn("a.b@ex.com", joined)
        self.assertEqual(sent[0][0][0]["role"], "user")           # 앞쪽 상담원 말은 버린다
        self.assertTrue(out["notes"])

    def test_promise_sentences_are_dropped(self):
        out, _ = self._run([_turn("윈도우는 저희가 깔아 드릴게요. 설치 여부는 상품 페이지에서 확인해 주세요.")],
                           text="윈도우 깔려서 와요?")
        self.assertNotIn("깔아 드릴게요", out["reply"])

    def test_found_but_not_selected_shows_no_cards(self):
        out, _ = self._run([
            _turn(calls=[{"id": "a", "name": "find_pcs", "args": {"usages": ["게임"]}}]),
            _turn("게임용이면 그래픽카드가 가장 중요해요."),
        ])
        self.assertEqual(out["cards"], [])

    def test_switch_off_is_404(self):
        with patch.dict("os.environ", {AG.FLAG_ENV: ""}):
            with self.assertRaises(HTTPException) as e:
                AG.chat(AG.ChatBody(text="안녕"), SimpleNamespace())
        self.assertEqual(e.exception.status_code, 404)


# ── ④ /api/talk/parse 가 스위치 켜짐에서 도구 상담으로 넘긴다 (2026-10-14 「고객 상담을 LLM 중심으로 해」) ──
class AsParse(unittest.TestCase):
    _run = Agent._run
    FLOW = [
        _turn(calls=[{"id": "a", "name": "find_pcs", "args": {"usages": ["게임"], "budget_won": 1_500_000}}]),
        _turn(calls=[{"id": "b", "name": "show_pcs", "args": {"refs": ["P1"]}}]),
        _turn("150만원 이하로는 게임 PC A가 맞아요. 판매가는 1,498,000원이에요."),
    ]

    def test_cards_turn_hands_engine_state_to_the_screen(self):
        out, _ = self._run(list(self.FLOW))
        self.assertEqual(out["state"]["usages"], ["게임"])               # 화면이 같은 조건으로 /grid/recommend 를 다시 묻는다
        self.assertEqual(out["state"]["budget_won"], 1_500_000)
        self.assertIsNone(out["nav"])

    def _as_parse(self, script, prev=None):
        from api import grid_public as GP
        with patch.object(AG, "engine", _Engine()), patch.object(AG, "load_vocab", lambda c: VOCAB), \
                patch.object(AG.llm, "call_tools", lambda m, t, **k: script.pop(0) if not isinstance(script[0], Exception) else (_ for _ in ()).throw(script.pop(0))), \
                patch.object(GP, "recommend", lambda b: _reco()):
            return AG.as_parse("게임용 PC 150만원", [SimpleNamespace(role="user", text="안녕")], prev, {"smalltalk_turns": 0})

    def test_parse_shape_with_cards(self):
        r = self._as_parse(list(self.FLOW))
        self.assertTrue(r["ok"] and r["agent"])
        self.assertFalse(r["explain_only"])
        self.assertEqual((r["missing"], r["pc_related"], r["answer"]), ([], True, ""))
        self.assertIn("1,498,000원", r["reply"])
        self.assertEqual(r["agent_meta"]["cards"], [1001])
        self.assertEqual(r["chat_flow"], {"smalltalk_turns": 0})

    def test_explanation_keeps_previous_state(self):
        prev = {"usages": ["사무·인강"], "budget_won": 800_000}
        r = self._as_parse([_turn("램은 동시 작업, SSD는 저장 속도에 영향을 줘요.")], prev)
        self.assertTrue(r["explain_only"])
        self.assertEqual(r["state"], prev)                               # 화면이 보던 견적을 그대로 둔다

    def test_failure_returns_none_so_parse_path_answers(self):
        self.assertIsNone(self._as_parse([llm.LLMProviderError("down", transient=True)]))

    def test_parse_route_delegates_only_when_switch_is_on(self):
        import inspect
        from api import talk
        src = inspect.getsource(talk.parse_talk)
        gate = src.index("AGENT.enabled()")
        self.assertLess(gate, src.index("TS.load_vocab"))                # 지금 경로의 AI 호출보다 앞
        self.assertIn("if agent_res is not None:", src)                  # 실패면 지금 경로가 받는다
        with patch.dict("os.environ", {AG.FLAG_ENV: ""}):
            self.assertFalse(AG.enabled())


if __name__ == "__main__":
    unittest.main()


# ── ⑤ 예산 초과를 설명이 숨기지 않는다 · 마크다운 기호를 남기지 않는다 (2026-10-14 3턴 결함 점검) ──
class BudgetNote(unittest.TestCase):
    def test_over_budget_card_gets_fact_sentence(self):
        n = AG.budget_note([{"price": 1_624_400, "over_budget": True}], 1_500_000, "이 PC가 좋아요.")
        self.assertEqual(n, "보여 드린 PC는 예산 1,500,000원보다 124,400원 높습니다.")

    def test_no_note_when_reply_already_says_so(self):
        self.assertIsNone(AG.budget_note([{"price": 1_624_400, "over_budget": True}], 1_500_000,
                                         "예산을 124,400원 넘어요."))

    def test_no_note_within_budget_or_unknown_budget(self):
        self.assertIsNone(AG.budget_note([{"price": 1_400_000, "over_budget": False}], 1_500_000, "좋아요."))
        self.assertIsNone(AG.budget_note([{"price": 1_624_400, "over_budget": True}], None, "좋아요."))

    def test_mixed_cards_counts_over(self):
        n = AG.budget_note([{"price": 1_400_000, "over_budget": False},
                            {"price": 1_700_000, "over_budget": True}], 1_500_000, "둘 다 괜찮아요.")
        self.assertIn("2대 중 1대", n)
        self.assertIn("200,000원 초과", n)

    def test_note_passes_verify(self):
        book = TT.FactBook()
        book.prices = {1_624_400}
        n = AG.budget_note([{"price": 1_624_400, "over_budget": True}], 1_500_000, "")
        clean, dropped = AG.verify(n, book, 1_500_000)
        # 차액(124,400)은 묶음 값이 아니지만 서버가 verify 뒤에 붙이므로 상관없다 -- 붙이는 위치를 지킨다.
        self.assertTrue(dropped)
        import inspect
        src = inspect.getsource(AG.run_turn)
        self.assertLess(src.index("verify(reply"), src.index("budget_note("))

    def test_markdown_is_stripped(self):
        clean, _ = AG.verify("**추천**은 __이것__입니다.\n## 요약\n좋아요.", TT.FactBook())
        self.assertEqual(clean, "추천은 이것입니다.\n요약\n좋아요.")          # 줄은 살린다(⑨)

    def test_run_turn_appends_note_for_over_budget_card(self):
        over = dict(ITEM, price=1_624_400, over_budget=True)
        reco = _reco(card_sets=[{"usage": "게임", "items": [over]}])
        out, _ = Agent._run(self, [
            _turn(calls=[{"id": "a", "name": "find_pcs", "args": {"usages": ["게임"], "budget_won": 1_500_000}}]),
            _turn(calls=[{"id": "b", "name": "show_pcs", "args": {"refs": ["P1"]}}]),
            _turn("**게임 PC A**를 추천해요."),
        ], reco=reco)
        # 보여 준 카드가 모두 예산을 넘으면 끝에 붙이는 대신 맨 앞에서 먼저 말한다(K1 솔직히 알림).
        self.assertEqual(out["reply"], "예산 1,500,000원 안에는 지금 판매 중인 PC가 없어요. 조건에 맞는 가장 싼 PC는"
                                       " 1,624,400원이에요.\n\n게임 PC A를 추천해요.")


# ── ⑥ 옛 경로의 PC 설명 검사를 도구 상담에도 건다 (2026-10-14 사장님 결함 2·3 · 권고 7, 「이어서 연결」) ──
class _PsuConn(_Conn):
    def __init__(self, watt):
        self.watt = watt

    def execute(self, *a, **k):
        return SimpleNamespace(first=lambda: (self.watt,) if self.watt else None)


class _PsuEngine:
    def __init__(self, watt):
        self.watt = watt

    def connect(self):
        return _PsuConn(self.watt)


class PcChecks(unittest.TestCase):
    def test_unasked_fps_numbers_are_dropped(self):
        out = AG.pc_checks("RTX 5060이면 충분해요. FHD에서 100fps 이상 나와요.", "게임용 150만원", [], None)
        self.assertEqual(out, "RTX 5060이면 충분해요.")

    def test_fps_the_customer_said_stays(self):
        out = AG.pc_checks("144fps 목표면 RTX 5070급을 보세요.", "144fps 나오는 PC", [], None)
        self.assertIn("144fps", out)

    def test_psu_question_gets_reference_line_and_hedge_is_dropped(self):
        with patch.object(AG, "engine", _PsuEngine(650)):
            out = AG.pc_checks("500W로는 충분하다고 단정하기 어려워요. 정격 파워를 고르세요.",
                               "RTX 5070에 500W 파워면 돼요?", [], None)
        self.assertTrue(out.startswith("RTX 5070 권장 파워는 650W라 500W 파워는 부족해요."))
        self.assertNotIn("단정하기 어려워요", out)
        self.assertIn("정격 파워를 고르세요.", out)

    def test_unknown_chip_leaves_reply_alone(self):
        with patch.object(AG, "engine", _PsuEngine(None)):
            out = AG.pc_checks("500W면 애매해요.", "RTX 9999에 500W 파워면 돼요?", [], None)
        self.assertEqual(out, "500W면 애매해요.")

    def test_no_db_read_without_psu_question(self):
        class Boom:
            def connect(self):
                raise AssertionError("DB 를 읽으면 안 된다")
        with patch.object(AG, "engine", Boom()):
            self.assertEqual(AG.pc_checks("램은 16GB면 돼요.", "램 얼마나 필요해요?", [], None), "램은 16GB면 돼요.")

    def test_budget_yes_dropped_when_all_cards_over(self):
        cards = [{"price": 1_624_400, "over_budget": True}]
        out = AG.pc_checks("네, 150만원이면 충분히 가능해요. 게임 PC A를 보세요.", "150만원으로 게임 PC 돼요?", cards, 1_500_000)
        self.assertNotIn("충분히 가능해요", out)
        self.assertIn("게임 PC A를 보세요.", out)

    def test_budget_yes_kept_when_a_card_fits(self):
        cards = [{"price": 1_400_000, "over_budget": False}, {"price": 1_624_400, "over_budget": True}]
        out = AG.pc_checks("네, 150만원이면 충분히 가능해요.", "150만원으로 게임 PC 돼요?", cards, 1_500_000)
        self.assertIn("충분히 가능해요", out)

    def test_run_turn_applies_checks_after_verify(self):
        import inspect
        src = inspect.getsource(AG.run_turn)
        self.assertLess(src.index("verify(reply"), src.index("pc_checks("))
        self.assertLess(src.index("pc_checks("), src.index("budget_note("))



# ── ⑦ 카드가 모두 예산을 넘으면 설명 맨 앞에서 먼저 말한다 (2026-10-14 사장님 K1 「솔직히 알림」) ──
class BudgetLead(unittest.TestCase):
    OVER = {"price": 1_624_400, "over_budget": True}

    def test_all_over_leads_with_none_in_budget(self):
        n = AG.budget_lead([self.OVER], 600_000, "추천 제품은 골드 인텔입니다. 1080p 기준이에요.")
        self.assertEqual(n, "예산 600,000원 안에는 지금 판매 중인 PC가 없어요. 조건에 맞는 가장 싼 PC는 1,624,400원이에요.")

    def test_no_lead_when_first_sentence_already_says_so(self):
        for first in ("80만 원 이하인 팝콘PC는 현재 맞는 상품이 없어요.", "예산을 넘는 PC만 있어요."):
            self.assertIsNone(AG.budget_lead([self.OVER], 800_000, first + " 가장 가까운 것은 1,624,400원이에요."))

    def test_no_lead_when_some_card_fits_or_budget_unknown(self):
        self.assertIsNone(AG.budget_lead([{"price": 700_000, "over_budget": False}, self.OVER], 800_000, "좋아요."))
        self.assertIsNone(AG.budget_lead([self.OVER], None, "좋아요."))
        self.assertIsNone(AG.budget_lead([], 800_000, "좋아요."))

    def test_lead_amounts_pass_verify(self):
        book = TT.FactBook()
        book.prices = {1_624_400}
        n = AG.budget_lead([self.OVER], 600_000, "")
        clean, dropped = AG.verify(n, book, 600_000)
        self.assertEqual(dropped, [])
        self.assertEqual(clean, n)


# ── ⑧ 모델의 속말 메모를 고객 답에 내지 않는다 (2026-10-15 사장님 영상편집 상담 「бюджет? budget question Korean…」) ──
LEAK = ("영상 편집용으로는 아래 3가지가 적합합니다. P1 골드 인텔: 1,624,400원 — i5-12400F, RAM 16GB, RTX 5060. "
        "FHD 위주면 P1을 우선 추천합니다. бюджет? budget question Korean. Need ask one question, maybe "
        "\"주로 FHD인가 4K인가요?\" Since already results. 2-5 sentences. \"주로 FHD와 4K 중 어느 해상도...\" Good. "
        "⟂ no need mention show. maybe \"화면에...\" Fine.")


class Scratch(unittest.TestCase):
    def test_leaked_notes_and_everything_after_are_dropped(self):
        book = TT.FactBook()
        book.prices = {1_624_400}
        clean, dropped = AG.verify(LEAK, book)
        self.assertEqual(clean, "영상 편집용으로는 아래 3가지가 적합합니다. P1 골드 인텔: 1,624,400원 — i5-12400F, RAM 16GB, "
                                "RTX 5060. FHD 위주면 P1을 우선 추천합니다.")
        self.assertTrue(all(d["reason"] == "scratch" for d in dropped))
        self.assertNotIn("주로 FHD인가", clean)

    def test_part_names_and_fps_are_not_scratch(self):
        for s in ("RTX 5060 Ti", "i5-12400F, RAM 16GB, SSD 1TB.", "144fps 목표면 RTX 5070급을 보세요.",
                  "윈도우 11 home 버전은 따로 사셔야 해요.", "Intel Core i7-14700K"):
            self.assertFalse(AG.is_scratch(s), s)

    def test_scratch_shapes(self):
        for s in ("бюджет?", "budget question Korean.", "2-5 sentences.", "⟂ no need mention show.",
                  "Need ask one question, maybe \"주로 FHD인가요?\""):
            self.assertTrue(AG.is_scratch(s), s)


class OpenAIAnswerText(unittest.TestCase):
    def _resp(self, *items):
        return SimpleNamespace(output=list(items), output_text="".join(
            c.text for it in items if it.type == "message" for c in it.content))

    def _msg(self, text, phase=None):
        return SimpleNamespace(type="message", phase=phase, content=[SimpleNamespace(type="output_text", text=text)])

    def test_commentary_message_is_not_customer_text(self):
        r = self._resp(self._msg("budget question Korean. Need ask one question.", "commentary"),
                       self._msg("영상 편집용으로는 P1을 추천해요.", "final_answer"))
        self.assertEqual(llm._openai_answer_text(r), "영상 편집용으로는 P1을 추천해요.")

    def test_unlabelled_message_is_kept(self):
        self.assertEqual(llm._openai_answer_text(self._resp(self._msg("네, 찾아볼게요."))), "네, 찾아볼게요.")

    def test_commentary_only_is_empty(self):
        r = self._resp(self._msg("thinking about tools", "commentary"),
                       SimpleNamespace(type="function_call", content=None))
        self.assertEqual(llm._openai_answer_text(r), "")


# ── ⑨ 줄바꿈을 살린다 (2026-10-15 사장님 「줄바꿈도 안되고」) ──
class Lines(unittest.TestCase):
    def setUp(self):
        self.book = TT.FactBook()
        self.book.prices = {1_624_400, 3_220_500}

    def test_line_breaks_and_list_marks_are_kept(self):
        clean, _ = AG.verify("추천은 둘이에요.\n\n- P1 골드: 1,624,400원\n- P2 다이아: 3,220,500원\n\nFHD면 P1이에요.", self.book)
        self.assertEqual(clean, "추천은 둘이에요.\n\n- P1 골드: 1,624,400원\n- P2 다이아: 3,220,500원\n\nFHD면 P1이에요.")

    def test_inline_list_is_split_into_lines(self):
        clean, _ = AG.verify("아래 둘이 맞아요. - P1 골드: 1,624,400원 — FHD 편집용 - P2 다이아: 3,220,500원 — 4K 편집용", self.book)
        self.assertEqual(clean, "아래 둘이 맞아요.\n- P1 골드: 1,624,400원 — FHD 편집용\n- P2 다이아: 3,220,500원 — 4K 편집용")

    def test_single_dash_and_number_ranges_are_not_split(self):
        clean, _ = AG.verify("램은 16 - 32GB면 돼요. 영상 편집 - 특히 4K는 32GB가 편해요.", self.book)
        self.assertEqual(clean, "램은 16 - 32GB면 돼요. 영상 편집 - 특히 4K는 32GB가 편해요.")

    def test_dropped_line_leaves_no_double_blank(self):
        clean, _ = AG.verify("좋아요.\n\n120만원짜리도 있어요.\n\n이걸 보세요.", self.book)
        self.assertEqual(clean, "좋아요.\n\n이걸 보세요.")


# ── ⑩ 금액은 세 자리마다 쉼표 (2026-10-15 사장님 「금액은 중간에 , 표시가 들어가야 해」) ──
class WonCommas(unittest.TestCase):
    def test_bare_amounts_get_commas(self):
        book = TT.FactBook()
        book.prices = {3_220_500, 12_954_900}
        clean, dropped = AG.verify("- P1 다이아: RTX 5070, RAM 32GB — 3220500원\n- P2 익스트림: RTX 5090 — 12954900 원", book)
        self.assertEqual(clean, "- P1 다이아: RTX 5070, RAM 32GB — 3,220,500원\n- P2 익스트림: RTX 5090 — 12,954,900 원")
        self.assertEqual(dropped, [])

    def test_other_numbers_are_untouched(self):
        for s in ("150만원이면 충분해요.", "1,624,400원이에요.", "2026년형이고 RTX 5090 32GB예요.", "500원 차이예요."):
            self.assertEqual(AG._won_commas(s), s)
