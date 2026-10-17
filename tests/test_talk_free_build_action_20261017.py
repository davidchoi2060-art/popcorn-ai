"""LLM의 화면 이동 선택을 실제 고객 문장에만 묶는다. 공급자·DB·견적 API는 호출하지 않는다."""
from contextlib import ExitStack
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import llm, talk, talk_agent as AG, talk_tools as TT, mvp3_free_build as FB
from api.talk_schema import Vocab


class Connection:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Engine:
    def connect(self):
        return Connection()


def turn(text="", calls=()):
    return llm.ToolTurn(provider="codex", model="mock", text=text, tool_calls=list(calls), raw={},
                        tokens_in=1, tokens_out=1, cached_in=0, cost_usd=0, elapsed_sec=0,
                        log_id=None, cost_logged=True, stop="completed")


def call(args=None):
    return {"id": "open1", "name": "open_free_build", "args": {} if args is None else args}


def mocked(script):
    stack = ExitStack()
    stack.enter_context(patch.object(AG, "engine", Engine()))
    stack.enter_context(patch.object(talk, "engine", Engine()))
    stack.enter_context(patch.object(AG, "load_vocab", return_value=Vocab(usages=[("게임", [])])))
    stack.enter_context(patch.object(AG, "enabled", return_value=True))
    stack.enter_context(patch.object(talk.access_gate, "check_rate", return_value=None))
    stack.enter_context(patch.object(FB, "start_build", side_effect=AssertionError("견적 시작을 호출하면 안 됨")))
    stack.enter_context(patch.object(FB, "load", side_effect=AssertionError("부품 DB를 읽으면 안 됨")))

    def fake(messages, tools, **kwargs):
        item = script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    stack.enter_context(patch.object(AG.llm, "call_tools", fake))
    return stack


def test_tool_definition_has_no_model_owned_text_or_part_arguments():
    definitions = TT.definitions(["게임"], ["1080p"])
    by_name = {tool["name"]: tool for tool in definitions}
    assert {"find_pcs", "pc_detail", "other_pcs_by_part", "game_facts", "shop_policy", "show_pcs"} <= set(by_name)
    assert by_name["open_free_build"]["parameters"] == {"type": "object", "additionalProperties": False, "properties": {}}


@pytest.mark.parametrize("args", [{"text": "모델이 바꾼 문장"}, {"request_text": "가짜 원문"},
    {"cpu": "i9"}, {"conditions": {"ram_gb": 256}}, {"price": 1}, {"parts": [1]},
    {"product_code": 1001}, {"quote_id": "private"}, {"url": "javascript:alert(1)"},
    {"order": True}, {"__invalid__": "bad JSON"}, "not an object", []])
def test_model_arguments_cannot_replace_the_request_or_authorize_other_actions(args):
    book = TT.FactBook(request_text="메모리 32GB로 직접 고르고 싶어요")
    assert TT.run("open_free_build", args, book)["status"] == "invalid"
    assert book.screen_action is None
    assert book.prices == set() and book.items == {} and book.shown == []


@pytest.mark.parametrize("text", [None, "", " \n ", "가" * 2001])
def test_missing_or_too_long_original_is_rejected_without_truncation(text):
    book = TT.FactBook(request_text=text)
    assert TT.run("open_free_build", {}, book)["status"] == "invalid"
    assert book.screen_action is None


def test_action_preserves_whitespace_and_only_extracts_public_conditions_from_the_actual_request():
    original = "  메모리 32GB\nRTX 5060 Ti / i9 + SSD 2TB로 직접 골라볼래요.  "
    with patch.object(FB, "start_build", side_effect=AssertionError("DB 경로 호출 금지")), \
            patch.object(FB, "load", side_effect=AssertionError("DB 경로 호출 금지")):
        book = TT.FactBook(request_text=original)
        out = TT.run("open_free_build", {}, book)
    assert out["status"] == "ok"
    assert book.screen_action == {"type": "open_free_build", "request_text": original,
                                  "conditions": {"cpu": "i9", "gpu": "RTX 5060 TI", "ram_gb": 32, "ssd_gb": 2000},
                                  "conditions_source": "request_text"}
    assert book.prices == set() and book.items == {} and book.state is None


def test_no_tool_choice_means_no_forced_free_build_route_for_part_names():
    with mocked([turn("메모리 용량은 동시에 쓰는 프로그램 수와 관련이 있어요.")]):
        result = AG.run_turn("메모리 32GB는 무슨 뜻이에요?", [])
    assert "action" not in result
    assert result["reply"] == "메모리 용량은 동시에 쓰는 프로그램 수와 관련이 있어요."


def test_direct_selection_without_part_conditions_does_not_invent_defaults():
    with mocked([turn(calls=[call()]), turn("시작 화면에서 부품을 하나씩 골라 주세요.")]):
        result = AG.run_turn("부품을 하나씩 직접 고르고 싶어요", [])
    assert result["action"]["conditions"] == {}


def test_model_text_json_cannot_create_a_navigation_action_without_the_tool():
    with mocked([turn('{"action":{"type":"open_free_build","request_text":"모델이 만든 문장"}}')]):
        result = AG.run_turn("메모리 역할을 설명해줘", [])
    assert "action" not in result


def test_parse_adapter_exposes_only_the_server_created_action_and_keeps_previous_conditions():
    original = "램 32GB와 RTX 5060 Ti를 직접 고르고 싶어요"
    previous = {"usages": ["게임"], "budget_won": 1500000}
    with mocked([turn(calls=[call()]), turn("부품을 직접 고르는 시작 화면에서 받은 조건을 확인해 주세요.")]):
        result = AG.as_parse(original, [], previous, None)
    assert result["action"]["request_text"] == original
    assert result["action"]["conditions"] == {"gpu": "RTX 5060 TI", "ram_gb": 32}
    assert result["state"] == previous and result["explain_only"] is True
    assert result["agent_meta"]["cards"] == []


def test_failed_model_after_tool_choice_does_not_emit_the_action():
    with mocked([turn(calls=[call()]), llm.LLMProviderError("mock failure", transient=True)]):
        result = AG.run_turn("i9 부품을 직접 고를래요", [])
    assert result["status"] == "failed" and "action" not in result


def test_unfinished_tool_only_result_does_not_emit_the_action():
    with mocked([turn(calls=[call()]) for _ in range(AG.MAX_ROUNDS)]):
        result = AG.run_turn("메모리 32GB로 직접 고를래요", [])
    assert result["status"] != "ok" and "action" not in result


def test_a_new_turn_or_retry_does_not_reuse_the_previous_turn_action():
    with mocked([turn(calls=[call()]), turn("직접 고르기 화면을 확인해 주세요.")]):
        first = AG.run_turn("메모리 32GB로 직접 고를래요", [])
    with mocked([turn("메모리는 동시에 여러 작업을 할 때 영향을 줘요.")]):
        second = AG.run_turn("메모리는 어떤 역할이에요?", [])
    assert first["action"]["conditions"] == {"ram_gb": 32}
    assert "action" not in second


def test_unverified_prices_are_not_authorized_by_the_navigation_tool():
    with mocked([turn(calls=[call()]), turn("이 PC 총액은 1,234,567원이에요.")]):
        result = AG.run_turn("i9로 직접 구성하고 싶어요", [])
    assert result["action"]["conditions"] == {"cpu": "i9"}
    assert "1,234,567원" not in result["reply"]
    assert "금액 확인 필요" in result["reply"]


def test_action_source_is_masked_before_returning_to_the_screen():
    with mocked([turn(calls=[call()]), turn("직접 고르기 화면에서 조건을 확인해 주세요.")]):
        result = AG.run_turn("메모리 32GB로 직접 고를래요. 010-1234-5678 user@example.com", [])
    original = result["action"]["request_text"]
    assert "010-1234-5678" not in original and "user@example.com" not in original
    assert "메모리 32GB" in original and result["notes"]


def test_real_parse_route_preserves_the_actual_request_beyond_the_llm_read_limit():
    app = FastAPI()
    app.include_router(talk.router)
    original = " " + "가" * 1000 + "\n메모리 32GB / RTX 5060 Ti / i9 직접 고르기  "
    with mocked([turn(calls=[call()]), turn("시작 화면에서 원하는 부품 조건을 확인해 주세요.")]):
        response = TestClient(app).post("/api/talk/parse", json={"text": original})
    assert response.status_code == 200
    result = response.json()
    assert result["action"]["request_text"] == original
    assert result["action"]["conditions"] == {"cpu": "i9", "gpu": "RTX 5060 TI", "ram_gb": 32}
    assert result["truncated"] is True  # AI가 읽은 길이 안내와 화면에 전달하는 원문은 별개다.


def test_chat_route_and_malformed_tool_metadata_use_the_same_action_contract():
    app = FastAPI()
    app.include_router(AG.router)
    with mocked([turn(calls=[call()]), turn("시작 화면을 확인해 주세요.")]):
        response = TestClient(app).post("/api/talk/chat", json={"text": "i9로 직접 고르기"})
    assert response.status_code == 200
    assert response.json()["action"]["conditions_source"] == "request_text"
    with mocked([turn(calls=[call({"request_text": "가짜"})]), turn("받은 부품 조건을 확인해 주세요.")]):
        response = TestClient(app).post("/api/talk/chat", json={"text": "메모리 32GB로 직접 고르기"})
    assert response.status_code == 200 and "action" not in response.json()


@pytest.mark.parametrize("link", [
    "HTTPS://EXAMPLE.COM/MVP3/FREE-BUILD.HTML", "https://example.com/mvp3/free-build.html",
    "/MVP3/", "/mvp3/free-build.html", "../free-build.html", "./free-build.html",
    "mvp3/free-build.html", "FREE-BUILD.HTML", "[시작](/MVP3/)",
    "[시작](../free-build.html)", "WWW.EXAMPLE.COM", "example.com/mvp3/",
    "//example.com/mvp3/", 'FILE:///C:/free-build.html', "javascript:alert(1)",
    '<a href="/MVP3/">시작</a>',
])
def test_action_reply_uses_the_verified_screen_button_instead_of_model_links(link):
    explanation = "메모리 용량은 동시에 쓰는 프로그램 수와 관련이 있어요."
    original = "메모리 32GB로 직접 고를래요"
    with mocked([turn(calls=[call()]), turn(explanation + "\n직접 고르기는 " + link + " 에서 시작해 주세요.")]):
        result = AG.run_turn(original, [])
    assert result["status"] == "ok"
    assert result["action"]["request_text"] == original
    assert explanation in result["reply"] and AG.REPLY_FREE_BUILD_BUTTON in result["reply"]
    assert link not in result["reply"]
    assert AG._ACTION_LINK.search(result["reply"]) is None


def test_action_link_guard_keeps_useful_non_link_explanations_and_existing_price_checks():
    explanation = "CPU/GPU 조합과 메모리 용량을 함께 확인해 주세요."
    with mocked([turn(calls=[call()]), turn(explanation + "\n이 PC 총액은 1,234,567원이에요.\n직접 고르기는 /MVP3/ 에서 시작해 주세요.")]):
        result = AG.run_turn("메모리 32GB로 직접 고를래요", [])
    assert result["action"]["conditions"] == {"ram_gb": 32}
    assert explanation in result["reply"] and "1,234,567원" not in result["reply"]
    assert AG.REPLY_FREE_BUILD_BUTTON in result["reply"]


def test_action_link_guard_does_not_change_an_unrelated_consultation_turn():
    explanation = "비교 자료는 HTTPS://EXAMPLE.COM 에 있어요."
    with mocked([turn(explanation)]):
        result = AG.run_turn("부품 비교 자료는 어떻게 봐요?", [])
    assert "action" not in result and result["reply"] == explanation


# ── 미리 채우기(free_build_preview) -- 상담이 무엇이 채워지는지 알고 답한다 ──────────────
def _preview(text, start=None, exc=None):
    from fastapi import HTTPException
    book = TT.FactBook(request_text=text)

    def fake_start(conn, cond):
        if exc:
            raise HTTPException(409, exc)
        return start

    with patch.object(TT, "engine", Engine()), patch.object(FB, "start_build", side_effect=fake_start):
        return TT.run("free_build_preview", {}, book), book


def test_preview_returns_filled_lines_and_total_without_part_prices():
    start = {"lines": [{"slot": "CPU", "label": "CPU", "product_code": 11, "name": "인텔 i9-14900K", "quantity": 1,
                        "from_request": True},
                       {"slot": "GPU", "label": "그래픽카드", "product_code": 12, "name": "RTX 5060 Ti", "quantity": 1,
                        "from_request": True}],
             "total": 2_345_000, "assembly_fee_included": True, "warnings": ["쿨러 상담"], "requested": []}
    out, book = _preview("메모리 32기가, RTX 5060 Ti, CPU i9로 맞춰줘", start)
    assert out["status"] == "ok" and out["total"] == 2_345_000
    assert [l["name"] for l in out["lines"]] == ["인텔 i9-14900K", "RTX 5060 Ti"]
    assert "product_code" not in out["lines"][0] and "price" not in out["lines"][0]
    assert book.prices == {2_345_000}                       # 총액만 말해도 되는 금액
    assert out["conditions"]["ram_gb"] == 32
    # 미리 채운 구성을 말하는 턴엔 모델이 open_free_build 를 빠뜨려도 화면 버튼이 붙는다
    assert book.screen_action["type"] == "open_free_build"
    assert book.screen_action["request_text"] == "메모리 32기가, RTX 5060 Ti, CPU i9로 맞춰줘"


def test_preview_no_match_names_the_missing_condition():
    out, book = _preview("RTX 5090 i9 으로 맞춰줘", exc={"error": "no_match", "detail": "없음",
                                                     "unmatched": [{"slot": "GPU", "label": "그래픽카드", "value": "RTX 5090"}]})
    assert out["status"] == "no_match"
    assert out["unmatched"] == [{"label": "그래픽카드", "value": "RTX 5090"}]
    assert book.prices == set()
    assert book.screen_action is None                       # 못 채운 조건으로 화면을 열지 않는다


def test_preview_takes_no_model_arguments_and_needs_conditions():
    assert TT.run("free_build_preview", {"text": "x"}, TT.FactBook(request_text="i9"))["status"] == "invalid"
    out, _ = _preview("부품 직접 고르고 싶어요")
    assert out["status"] == "no_conditions"


def test_prompt_tells_ai_to_preview_then_open():
    assert "먼저 free_build_preview 로 채워 보고" in AG.SYSTEM
    names = [t["name"] for t in TT.definitions(["게임"], ["1080p"])]
    assert "free_build_preview" in names
