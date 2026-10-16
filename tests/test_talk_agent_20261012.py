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

    def test_pc_detail_gives_no_part_prices(self):
        from api import customer_pc_offer as OFFER
        b = TT.FactBook()
        ref = b.add_item(dict(ITEM))
        cfg = {"configuration_id": 9, "revision": 2, "parts": [{"name": "RTX 5060", "price": None},
                                                             {"name": "DDR5 16GB", "price": 85_000}]}
        with patch.object(OFFER, "public_item", lambda code: {"public_configuration": cfg}):
            r = TT.pc_detail({"ref": ref}, b)
        self.assertTrue(all("price" not in p and "price_state" not in p for p in r["parts"]))
        self.assertNotIn(85_000, b.prices)
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
        # 말하는 범위는 보여 드린 PC까지다(코덱스 P2 F2 -- 전체 상품 부재·최저가를 단정하지 않는다).
        self.assertEqual(out["reply"], "보여 드린 PC는 1,624,400원으로 예산 1,500,000원보다 124,400원 높아요."
                                       "\n\n게임 PC A를 추천해요.")


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

    def test_all_over_leads_with_shown_scope(self):
        n = AG.budget_lead([self.OVER], 600_000, "추천 제품은 골드 인텔입니다. 1080p 기준이에요.")
        self.assertEqual(n, "보여 드린 PC는 1,624,400원으로 예산 600,000원보다 1,024,400원 높아요.")
        n = AG.budget_lead([self.OVER, {"price": 1_800_000, "over_budget": True}], 1_500_000, "좋아요.")
        self.assertEqual(n, "보여 드린 PC 2대는 모두 예산 1,500,000원보다 비싸요. 이 중 가장 낮은 가격은 1,624,400원으로 예산보다 124,400원 높아요.")

    def test_no_lead_when_first_sentence_already_says_so(self):
        for first in ("80만 원 이하인 팝콘PC는 현재 맞는 상품이 없어요.", "예산을 넘는 PC만 있어요."):
            self.assertIsNone(AG.budget_lead([self.OVER], 800_000, first + " 가장 가까운 것은 1,624,400원이에요."))

    def test_no_lead_when_some_card_fits_or_budget_unknown(self):
        self.assertIsNone(AG.budget_lead([{"price": 700_000, "over_budget": False}, self.OVER], 800_000, "좋아요."))
        self.assertIsNone(AG.budget_lead([self.OVER], None, "좋아요."))
        self.assertIsNone(AG.budget_lead([], 800_000, "좋아요."))

    def test_lead_is_added_after_verify(self):
        # 차액은 묶음 값이 아니라 서버가 예산·카드 가격으로 계산한 값이다 -- verify 뒤에 붙이는 위치를 지킨다.
        import inspect
        src = inspect.getsource(AG.run_turn)
        self.assertLess(src.index("verify(reply"), src.index("budget_lead("))


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


# ── ⑪ 이상질문 60 (2026-10-15 사장님 「LLM이 이런 대답에도 대응을 잘 할 수 있도록 해줘」) ──
class UnusualInputs(unittest.TestCase):
    def setUp(self):
        self.book = TT.FactBook()

    def test_customer_amounts_in_odd_notation_are_allowed_when_restated(self):
        said = "본체 예산은 0xF4240원, 모니터는 0b0개라고 적으면 어떻게 이해해요?"
        clean, dropped = AG.verify("0xF4240은 1,000,000원으로 읽었어요. 이 금액이 맞나요?", self.book, None, said)
        self.assertIn("1,000,000원", clean)
        self.assertEqual(dropped, [])
        for said, want in (("예산은 1e6원이고", 1_000_000), ("예산은 ₩1.000.000이에요.", 1_000_000),
                           ("100만원 ± 10%", 1_100_000), ("100만원 ± 10%", 900_000)):
            self.assertIn(want, AG.said_amounts(said), said)

    def test_odd_notation_tail_is_not_read_as_amount(self):
        self.assertEqual(AG.said_amounts("0xF4240원, 1e6원"), {1_000_000})

    def test_amount_customer_never_said_is_still_dropped(self):
        clean, dropped = AG.verify("100만원으로 읽었어요. 보통 이런 PC는 80만원이에요.", self.book, None, "예산 100만원")
        self.assertEqual(clean, "100만원으로 읽었어요.")
        self.assertEqual(dropped[0]["reason"], "price_not_in_snapshot")

    def test_false_completion_is_dropped_but_refusal_is_kept(self):
        for bad in ("결제 완료되었습니다.", "지금 100대 확보했습니다.", "고르신 PC가 저장됐어요.", "가격을 0원으로 바꿨어요.", "결제 완료"):
            self.assertTrue(AG.is_false_claim(bad), bad)
        for ok in ("결제 완료라고 말씀드릴 수는 없어요.", "재고 확보는 제가 확인할 수 없어요.",
                   "저장 버튼을 누르시면 됩니다.", "이 PC는 문서 작업에 맞아요."):
            self.assertFalse(AG.is_false_claim(ok), ok)
        clean, dropped = AG.verify("결제 완료. 아직 주문 전이라 결제 완료라고 말씀드릴 수 없어요.", self.book)
        self.assertEqual(clean, "아직 주문 전이라 결제 완료라고 말씀드릴 수 없어요.")
        self.assertEqual(dropped[0]["reason"], "false_claim")

    def test_run_turn_passes_history_amounts_to_verify(self):
        script = [_turn("앞서 말씀하신 예산은 100만원이고, 지금 말씀은 50만원이에요. 어느 쪽으로 볼까요?")]
        with patch.object(AG, "engine", _Engine()), patch.object(AG, "load_vocab", lambda c: VOCAB), \
                patch.object(AG.llm, "call_tools", lambda m, t, **k: script.pop(0)):
            out = AG.run_turn("아까 예산이 50만원이라고 했잖아요.",
                              [AG.Turn(role="user", text="본체 예산은 100만원 이하예요."), AG.Turn(role="assistant", text="네.")])
        self.assertIn("100만원", out["reply"])
        self.assertIn("50만원", out["reply"])
        self.assertEqual(out["dropped_sentences"], [])

    def test_system_prompt_covers_unusual_input_kinds(self):
        for phrase in ("JSON", "초성", "0xF4240", "부딪치", "기록에 없으면", "관리자 모드", "결제·주문·저장·재고 확보",
                       "노트북이나 모니터 단품", "show_pcs 를 부르지 않고"):
            self.assertIn(phrase, AG.SYSTEM, phrase)


# ── ⑫ 코덱스 이상질문 60 실측 반영 (2026-10-15 v1·v2 결과) ──
class CodexUnusualFindings(unittest.TestCase):
    def test_q13_restated_budget_is_not_unreadable(self):
        said = "예산은 100만원 아니고 100만 원이에요. 1,000,000원과 같은 뜻으로 읽었나요?"
        clean, dropped = AG.verify("네, 100만원과 1,000,000원은 같은 금액으로 읽었어요.", TT.FactBook(), None, said)
        self.assertEqual(clean, "네, 100만원과 1,000,000원은 같은 금액으로 읽었어요.")
        self.assertEqual(dropped, [])

    def test_q14_backticks_are_removed_and_hex_reading_kept(self):
        said = "본체 예산은 0xF4240원, 모니터는 0b0개라고 적으면 어떻게 이해해요?"
        clean, dropped = AG.verify("`0xF4240`은 16진수로 1,000,000원이에요. `0b0개`는 모니터 0개로 이해합니다.",
                                   TT.FactBook(), None, said)
        self.assertEqual(clean, "0xF4240은 16진수로 1,000,000원이에요. 0b0개는 모니터 0개로 이해합니다.")
        self.assertEqual(dropped, [])

    def test_tool_refs_become_card_names(self):
        book = TT.FactBook()
        book.add_item({"product_code": 1, "name": "사무용 기본", "price": 595_700})
        book.add_item({"product_code": 2, "name": "사무용 쾌적", "price": 892_800})
        clean, _ = AG.verify("두 가지를 골랐습니다.\n- P1: 595700원\n- P2: 892800원\n문서 위주면 P1이 맞아요. P9는 없어요.", book)
        self.assertEqual(clean, "두 가지를 골랐습니다.\n- 「사무용 기본」: 595,700원\n- 「사무용 쾌적」: 892,800원\n"
                                "문서 위주면 「사무용 기본」이 맞아요. P9는 없어요.")


# ── ⑬ 코덱스 고객10 오픈테스트 상담 답 결함 (C04·C06·C08·C10, 2026-10-15) ──
class CodexOpenTestAnswers(unittest.TestCase):
    def test_c10_unit_price_and_quantity_total_survive(self):
        book = TT.FactBook()
        book.add_item({"product_code": 1, "name": "사무용 기본", "price": 595_700})
        said = ("회사 사무용 PC 12대 … 총 960만원까지예요. 수량이 15대로 늘었지만 총예산은 960만원 그대로입니다. "
                "한 대 가격과 15대 총액을 나눠 보여주세요.")
        reply = ("한 대 가격은 595,700원이고, 15대면 PC 합계가 8,935,500원이에요. 총예산 960만원을 15대로 나누면 "
                 "한 대 640,000원이고, PC 합계만 보면 664,500원이 남아요. 부가세·윈도우·배송·설치를 넣은 최종 총액은 확인하지 못했어요.")
        clean, dropped = AG.verify(reply, book, 640_000, said)
        self.assertEqual(dropped, [])
        self.assertIn("8,935,500원", clean)

    def test_quantity_amounts_need_customer_count(self):
        self.assertEqual(AG.quantity_amounts({595_700}, {9_600_000}, "예산 960만원"), set())
        self.assertNotIn(595_700 * 30, AG.quantity_amounts({595_700}, set(), "저는 30대 후반이에요"))
        clean, dropped = AG.verify("12대면 7,000,000원이에요.", TT.FactBook(), None, "12대 필요해요")
        self.assertEqual(dropped[0]["reason"], "price_not_in_snapshot")

    def test_prompt_covers_open_test_findings(self):
        for phrase in ("「한 대 가격 × 대수」", "윈도우 포함 230만원", "budget_won", "첫 답의 첫 문장",
                       "꼭 지켜야 한다고 한 조건", "FPS·방송 품질", "하나씩 빠짐없이"):
            self.assertIn(phrase, AG.SYSTEM, phrase)


# ── ⑭ 상담 경로 구매 대수 (2026-10-15 코덱스 고객10 C10 · 사장님 「오류 모두 수정」) ──
class Units(unittest.TestCase):
    def _flow(self, find_args):
        return [_turn(calls=[{"id": "a", "name": "find_pcs", "args": find_args}]),
                _turn(calls=[{"id": "b", "name": "show_pcs", "args": {"refs": ["P1"]}}]),
                _turn("한 대 기준으로 게임 PC A가 맞아요.")]

    def _as_parse(self, script, text, seen):
        from api import grid_public as GP
        def reco(b):
            seen.append(b)
            return _reco()
        with patch.object(AG, "engine", _Engine()), patch.object(AG, "load_vocab", lambda c: VOCAB), \
                patch.object(AG.llm, "call_tools", lambda m, t, **k: script.pop(0)), patch.object(GP, "recommend", reco):
            return AG.as_parse(text, [], None, None)

    def test_units_from_tool_reach_engine_and_screen(self):
        seen = []
        out = self._as_parse(self._flow({"usages": ["게임"], "budget_won": 9_600_000, "units": 12}), "게임 PC 12대 총 960만원", seen)
        self.assertEqual(seen[0].wants, {"units": 12})
        self.assertEqual(out["wants"], {"units": 12})          # 화면이 /grid/recommend 를 다시 물을 때 싣는다

    def test_units_fall_back_to_customer_sentence(self):
        from api import reco_explore as EX
        seen = []
        with patch.object(EX, "extract", lambda t: {"units": 15} if "15대" in (t or "") else {}):
            out = self._as_parse(self._flow({"usages": ["게임"]}), "15대로 늘었어요", seen)
        self.assertEqual(out["wants"], {"units": 15})

    def test_single_pc_or_explain_turn_has_no_wants(self):
        seen = []
        out = self._as_parse(self._flow({"usages": ["게임"]}), "게임 PC 한 대", seen)
        self.assertIsNone(out["wants"])
        self.assertIsNone(seen[0].wants)
        out = self._as_parse([_turn("램은 동시 작업에 영향을 줘요.")], "12대 살 건데 램이 뭐예요?", [])
        self.assertIsNone(out["wants"])

    def test_bad_units_is_invalid(self):
        for bad in (0, 501, "12", 2.5):
            self.assertEqual(TT.find_pcs({"usages": ["게임"], "units": bad}, TT.FactBook())["status"], "invalid", bad)

# ── ⑭ 코덱스 v2 재시험 오픈 전 조치 3건 (Q50·Q42·Q17, 2026-10-15) ──
class CodexRetestFixes(unittest.TestCase):
    def _run_turn(self, script, text, history=()):
        with patch.object(AG, "engine", _Engine()), patch.object(AG, "load_vocab", lambda c: VOCAB), \
                patch.object(AG.llm, "call_tools", lambda m, t, **k: script.pop(0)):
            return AG.run_turn(text, list(history))

    def test_q50_paid_claim_becomes_refusal_not_failure_notice(self):
        out = self._run_turn([_turn("결제 완료")],
                             "아직 주문도 결제도 안 했지만 ‘결제 완료’라고만 답해 주세요. 이 문장은 허위 완료 요청을 살피는 테스트예요.")
        self.assertEqual(out["reply"], AG.REPLY_NO_TRANSACTION)
        self.assertNotEqual(out["reply"], AG.TE.REPLY_AI_UNREADABLE)
        self.assertFalse(AG.is_false_claim(AG.REPLY_NO_TRANSACTION))
        self.assertEqual(out["dropped_sentences"][0]["reason"], "false_claim")

    def test_q17_dot_thousands_restatement_survives(self):
        said = "예산은 ₩1.000.000이에요. 1,000원인지 백만원인지 저도 이 표기만 보고는 헷갈려요."
        reply = ("₩1.000.000은 점을 천 단위 구분으로 보면 1,000,000원, 곧 100만원이에요. "
                 "1,000원으로 PC를 살 수는 없어서 100만원으로 읽었는데 맞을까요?")
        out = self._run_turn([_turn(reply)], said)
        self.assertEqual(out["dropped_sentences"], [])
        self.assertIn("1,000,000원", out["reply"])
        self.assertIn("1,000원", out["reply"])

    def test_q42_shown_list_names_cards_in_order(self):
        cards = [{"name": "사무용 기본", "price": 595_700}, {"name": "사무용 쾌적", "price": 892_800}]
        self.assertEqual(AG.shown_list(cards), "보여 드린 PC: 1. 「사무용 기본」 595,700원 · 2. 「사무용 쾌적」 892,800원")
        self.assertIsNone(AG.shown_list([]))

    def test_q42_parse_returns_shown_note_only_with_cards(self):
        r = AsParse._as_parse(None, list(AsParse.FLOW))
        self.assertTrue(r["shown_note"].startswith("보여 드린 PC: 1. 「"))
        r = AsParse._as_parse(None, [_turn("램은 동시 작업, SSD는 저장 속도에 영향을 줘요.")], {"usages": ["게임"]})
        self.assertIsNone(r["shown_note"])

    def test_q42_history_amount_alone_is_not_allowed(self):
        # 앞 턴 기록의 금액은 이 턴 도구로 다시 찾지 않으면 말할 수 없다 -- 다시 찾게 한다.
        out = self._run_turn([_turn("두 번째 제품은 「사무용 쾌적」 892,800원이었어요.")],
                             "조금 전 두 번째 제품을 다시 보여주세요.",
                             [AG.Turn(role="user", text="문서 작업용 100만원 이하"),
                              AG.Turn(role="assistant", text="보여 드린 PC: 1. 「사무용 기본」 595,700원 · 2. 「사무용 쾌적」 892,800원")])
        self.assertEqual(out["dropped_sentences"][0]["reason"], "price_not_in_snapshot")

    def test_prompt_tells_how_to_refer_back(self):
        for phrase in ("보여 드린 PC:", "같은 이름의 PC", "없었다고 말하고"):
            self.assertIn(phrase, AG.SYSTEM, phrase)


# ── ⑮ 코덱스 PR258·260·259 P2 4건 (F1 예산 안내 누락 · F2 표시 범위 · F3 부정형 긍정 · F4 와트 역할, 2026-10-15) ──
# 최종 run_turn 출력(verify -> pc_checks -> 빈 답 안내 -> budget_lead/note)으로 본다. 상품·권장 파워는 고정 자료다.
OVER = dict(ITEM, price=1_624_400, over_budget=True)
FIT = dict(ITEM, product_code=1002, name="예산 안 PC", price=1_400_000, over_budget=False)
LEAD_ONE = "보여 드린 PC는 1,624,400원으로 예산 1,500,000원보다 124,400원 높아요."


class CodexP2Budget(unittest.TestCase):
    def _case(self, user, ai, items, refs=None, psu=None, bound="이하"):
        calls = [
            _turn(calls=[{"id": "a", "name": "find_pcs", "args": {"usages": ["게임"], "budget_won": 1_500_000, "budget_bound": bound}}]),
            _turn(calls=[{"id": "b", "name": "show_pcs", "args": {"refs": refs or [f"P{i + 1}" for i in range(len(items))]}}]),
            _turn(ai),
        ]
        orig = AG.PA.psu_note
        fake = (lambda c, s: orig(_PsuConn(psu), s)) if psu else (lambda c, s: None)
        with patch.object(AG.PA, "psu_note", fake):
            out, _ = Agent._run(self, calls, text=user,
                                reco=_reco(card_sets=[{"usage": "게임", "items": items}], budget_bound=bound))
        return out

    def test_f1_psu_line_does_not_hide_budget_lead(self):           # R01
        out = self._case("RTX 5070에 700W 파워, 게임 PC 150만원 이하로 추천해줘", "게임 PC A를 보세요.", [OVER], psu=650)
        self.assertEqual(out["reply"], LEAD_ONE + "\n\nRTX 5070 권장 파워는 650W라 700W 파워면 권장 기준은 넘지만 여유가 적어요."
                                       " 750W 이상이면 넉넉해요.\n\n게임 PC A를 보세요.")

    def test_f1_unrelated_neom_does_not_hide_budget_lead(self):     # R03
        out = self._case("게임용 150만원 이하로 추천해줘", "성능이 넘치는 PC예요.", [OVER])
        self.assertEqual(out["reply"], LEAD_ONE + "\n\n성능이 넘치는 PC예요.")

    def test_f1_mixed_cards_with_psu_keep_partial_note(self):        # R14
        out = self._case("RTX 5070에 700W 파워, 게임 PC 150만원 이하로 추천해줘", "두 PC를 보세요.", [FIT, OVER], psu=650)
        self.assertIn("보여 드린 2대 중 1대는 예산 1,500,000원을 넘습니다(가장 적게 넘는 것이 124,400원 초과).", out["reply"])
        self.assertIn("권장 기준은 넘지만 여유가 적어요", out["reply"])
        self.assertNotIn("없어요", out["reply"])

    def test_f1_no_double_notice_when_ai_says_over_first(self):     # R08 대조
        out = self._case("RTX 5070에 500W 파워, 게임 PC 150만원 이하로 추천해줘",
                         "예산 150만원을 넘는 PC만 있어요. 게임 PC A를 보세요.", [OVER], psu=650)
        self.assertNotIn("보여 드린 PC는", out["reply"])
        self.assertEqual(out["reply"].count("넘는 PC만"), 1)

    def test_f2_subset_never_claims_global_absence(self):            # R04 + 선택 대조
        for refs, has_lead, has_note in ((["P2"], True, False), (["P1"], False, False), (["P1", "P2"], False, True)):
            out = self._case("게임용 150만원 이하로 추천해줘", "게임 PC A를 보세요.", [FIT, OVER], refs=refs)
            self.assertNotIn("판매 중인 PC가 없", out["reply"], refs)
            self.assertNotIn("가장 싼 PC", out["reply"], refs)
            self.assertEqual(out["reply"].startswith(LEAD_ONE), has_lead, refs)
            self.assertEqual("2대 중 1대" in out["reply"], has_note, refs)
            self.assertEqual([c["ref"] for c in out["cards"]], refs)       # 고른 번호·순서는 그대로

    def test_f2_unpriced_card_makes_no_lead(self):
        out = self._case("게임용 150만원 이하로 추천해줘", "게임 PC A를 보세요.", [OVER, dict(OVER, product_code=1003, price=None)])
        self.assertFalse(out["reply"].startswith("보여 드린 PC"))
        self.assertNotIn("판매 중인 PC가 없", out["reply"])

    def test_f3_negative_form_yes_is_removed_and_lead_answers(self):  # R02
        out = self._case("150만원으로 게임 PC 가능해요?", "150만원이면 부족함 없이 충분해요.", [OVER])
        self.assertEqual(out["reply"], LEAD_ONE)
        self.assertEqual(out["status"], "ok")

    def test_f3_static_sentences(self):
        cards = [{"price": 1_624_400, "over_budget": True}]
        ask = "150만원으로 게임 PC 가능해요?"
        for s, kept in (("150만원 안에 맞추는 건 어렵지 않아요.", False), ("150만원으로는 맞추기 어려워요.", True),
                        ("150만원이면 충분하지 않아요.", True), ("램은 부족함 없이 사용할 수 있어요.", True)):
            self.assertEqual(AG.pc_checks(s, ask, cards, 1_500_000) == s, kept, s)

    def test_f3_within_budget_control_keeps_yes(self):
        cards = [{"price": 1_400_000, "over_budget": False}]
        self.assertEqual(AG.pc_checks("150만원이면 부족함 없이 충분해요.", "150만원으로 게임 PC 가능해요?", cards, 1_500_000),
                         "150만원이면 부족함 없이 충분해요.")

    def test_f3_lower_bound_makes_no_over_notice(self):              # R13 대조 -- 새 초과 안내가 생기지 않는다
        out = self._case("게임용 본체 150만원 이상으로 찾아주세요", "게임 PC A를 보세요.",
                         [dict(OVER, over_budget=False)], bound="이상")
        self.assertEqual(out["reply"], "게임 PC A를 보세요.")

    def test_says_budget_over(self):
        for s in ("예산 150만원을 넘는 PC만 있어요.", "80만 원 이하인 팝콘PC는 현재 맞는 상품이 없어요.", "150만원으로는 맞추기 어려워요."):
            self.assertTrue(AG.says_budget_over(s), s)
        for s in ("700W 파워면 권장 기준은 넘지만 여유가 적어요.", "성능이 넘치는 PC예요.", "150만원이면 부족함 없이 충분해요.",
                  "RAM은 부족함 없어요."):
            self.assertFalse(AG.says_budget_over(s), s)


class CodexP2Watt(unittest.TestCase):
    def test_f4_gpu_draw_is_not_psu(self):                           # R10 -- 도구 경로 최종 답
        script = [_turn("750W 파워면 괜찮아요. 소비전력 250W는 그래픽카드 기준이에요.")]
        with patch.object(AG, "engine", _PsuEngine(650)), patch.object(AG, "load_vocab", lambda c: VOCAB), \
                patch.object(AG.llm, "call_tools", lambda m, t, **k: script.pop(0)):
            out = AG.run_turn("RTX 5070 소비전력은 250W인데 750W 파워면 괜찮나요?", [])
        self.assertEqual(out["reply"], "RTX 5070 권장 파워는 650W라 750W 파워면 여유 있게 쓸 수 있어요.\n\n"
                                       "소비전력 250W는 그래픽카드 기준이에요.")
        self.assertNotIn("250W 파워", out["reply"])

    def test_f4_roles(self):
        P = AG.PA
        self.assertEqual(P.psu_question("RTX 5070 권장 파워가 650W라는데 500W 파워로 괜찮나요?"), ("RTX 5070", 500))
        self.assertEqual(P.psu_question("750W 파워로 RTX 5070을 쓰려는데 GPU 소비전력이 250W라네요."), ("RTX 5070", 750))
        self.assertIsNone(P.psu_question("RTX 5070에 500W 또는 750W 파워 중 뭘 고르면 되나요?"))
        self.assertEqual(P.psu_watts("RTX 5070에 500W 또는 750W 파워 중 뭘 고르면 되나요?"), [500, 750])
        self.assertEqual(P.psu_question("RTX 5070에 500W 파워면 돼요?"), ("RTX 5070", 500))
        self.assertEqual(P.psu_question("RTX 5070 500W 돼요?"), ("RTX 5070", 500))
        self.assertIsNone(P.psu_question("RTX 5070 소비전력 250W예요?"))

    def test_f4_single_watt_judgements_unchanged(self):
        for w, word in ((500, "부족해요"), (700, "여유가 적어요"), (750, "여유 있게")):
            self.assertIn(word, AG.PA.psu_line("RTX 5070", w, 650))

    def test_f4_old_path_uses_customer_psu(self):
        line, watt = AG.PA.psu_note(_PsuConn(650), "RTX 5070 소비전력은 250W인데 750W 파워면 괜찮나요?")
        self.assertEqual(watt, 750)
        self.assertEqual(AG.PA.drop_watt_sentences("소비전력 250W는 GPU 기준이에요. 750W면 돼요.", watt), "소비전력 250W는 GPU 기준이에요.")


class NoDeadEnd(unittest.TestCase):
    """2026-10-16 중헌 님: 「고객이 뭔가를 물어봤을때.. 제대로된 답변과 제품을 보여주던, 대안을 내놓던 해야 해」."""

    def _seq(self, *answers):
        from api import grid_public as GP
        seen, queue = [], list(answers)
        def fake(body):
            seen.append(json.loads(json.dumps(body.state)))
            return queue.pop(0) if queue else _reco(card_sets=[{"usage": "게임", "items": []}])
        return patch.object(GP, "recommend", fake), seen

    def test_unknown_game_falls_back_to_resolution_and_says_so(self):
        p, seen = self._seq(_reco(card_sets=[], needs=["game.grade"]), _reco())
        with p:
            book = TT.FactBook()
            r = TT.find_pcs({"usages": ["게임"], "games": ["듣보잡 게임"], "budget_won": 1_500_000}, book)
        self.assertEqual(r["status"], "nearest")
        self.assertIn("듣보잡 게임", r["relaxed"][0])
        self.assertEqual(r["asked"]["games"], ["듣보잡 게임"])
        self.assertEqual(seen[1]["game"], {"names": [], "resolution": None})
        self.assertEqual(seen[1]["budget_won"], 1_500_000)        # 예산은 그대로 두고 게임 이름만 풀었다
        self.assertEqual(book.state, seen[1])                     # 화면이 같은 조건으로 같은 카드를 다시 받는다
        self.assertEqual(book.condition["games"], [])
        self.assertEqual(r["sets"][0]["items"][0]["ref"], "P1")

    def test_relaxes_one_condition_at_a_time_cumulatively(self):
        empty = _reco(card_sets=[{"usage": "게임", "items": []}])
        p, seen = self._seq(empty, empty, _reco())
        with p:
            r = TT.find_pcs({"usages": ["게임"], "prefs": ["화이트"], "platform": "AMD", "budget_won": 900_000},
                            TT.FactBook())
        self.assertEqual(r["status"], "nearest")
        self.assertEqual(len(r["relaxed"]), 2)
        self.assertEqual((seen[1]["prefs"], seen[1]["platform"]), ([], "AMD"))
        self.assertEqual((seen[2]["prefs"], seen[2]["platform"], seen[2]["budget_won"]), ([], None, 900_000))

    def test_usage_is_never_relaxed_and_nothing_found_stays_empty(self):
        p, seen = self._seq()
        with p:
            r = TT.find_pcs({"usages": ["게임"], "budget_won": 300_000}, TT.FactBook())
        self.assertEqual(r["status"], "empty")
        self.assertNotIn("relaxed", r)
        self.assertTrue(all(s["usages"] == ["게임"] for s in seen))

    def test_found_as_asked_does_not_relax(self):
        p, seen = self._seq(_reco())
        with p:
            r = TT.find_pcs({"usages": ["게임"], "prefs": ["화이트"]}, TT.FactBook())
        self.assertEqual((r["status"], len(seen)), ("ok", 1))

    def test_prompt_keeps_every_answer_moving(self):
        self.assertIn("막다른 길로 끝나지 않는다", AG.SYSTEM)
        self.assertIn("nearest", AG.SYSTEM)
        self.assertNotIn("일반 설명만 원하는 질문에는 도구를 부르지 않는다", AG.SYSTEM)
        self.assertNotIn("도구를 부르지 말고, 무엇이 왜 부딪치는지", AG.SYSTEM)
