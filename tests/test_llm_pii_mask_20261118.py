"""AI 사업자로 보내기 전 개인정보 가림 -- 모든 고객 경로 (2026-11-18 사장님 승인 · 개인정보처리방침 2026-11-23).

가짜 공급자(SDK 를 부르는 자리)에 «실제로 넘어간 인자»를 기록해, 주민번호·카드번호·전화번호·이메일이 원문으로
남지 않는지 본다. 가림은 `api/pii_mask.py` 하나이고, `api/llm.py` 가 고객 호출(customer_facing=True)마다 한 번 더
가린다 -- 호출부가 빠뜨려도 공급자에게는 원문이 가지 않는다. 관리자 작업(customer_facing=False)은 바꾸지 않는다.
"""
import dataclasses
import os
import pathlib
import re
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://ci:ci@127.0.0.1:1/ci")

from api import llm, pii_mask  # noqa: E402
from api import talk  # noqa: E402
from api import talk_agent as AG  # noqa: E402
from api import talk_exceptions as TX  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ("010-1234-5678", "a@b.co", "900101-1234567", "1234-5678-9012-3456")
SENTENCE = "연락은 010-1234-5678 이나 a@b.co 로, 주민 900101-1234567, 카드 1234-5678-9012-3456 이에요"


class _Conn:
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _Engine:
    def connect(self): return _Conn()


def _assert_clean(tc, blob):
    for raw in RAW:
        tc.assertNotIn(raw, blob)
    for digits in ("1234-5678", "1234567"):
        tc.assertNotIn(digits, blob)


class Canonical(unittest.TestCase):
    def test_masks_each_kind_with_existing_labels(self):
        cases = {"010-1234-5678": "[전화번호]", "01012345678": "[전화번호]", "02-123-4567": "[전화번호]",
                 "a@b.co": "[이메일]", "900101-1234567": "[주민번호]", "1234-5678-9012-3456": "[카드번호]",
                 "1234 5678 9012 3456": "[카드번호]", "110-123-456789": "[계좌번호]"}
        for raw, label in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(pii_mask.mask(raw), (label, True))

    def test_leaves_conditions_dates_and_model_numbers(self):
        for t in ("예산 1500000원", "1,500,000원", "RTX 5070 Ti 16GB", "2026-11-18 주문", "2026-11-18T09:00:00Z",
                  "DDR5-5600 32GB", "100-100000910WOF", "i5-14400F", "[전화번호]"):
            with self.subTest(t=t):
                self.assertEqual(pii_mask.mask(t), (t, False))

    def test_idempotent_and_keeps_josa(self):
        once, _ = pii_mask.mask(SENTENCE)
        self.assertEqual(pii_mask.mask(once), (once, False))
        self.assertIn("[이메일] 로", once)
        self.assertEqual(pii_mask.mask("a@b.co로 주세요")[0], "[이메일]로 주세요")

    def test_every_old_entry_point_is_the_same_function(self):
        want = pii_mask.mask(SENTENCE)
        self.assertEqual(TX.mask_personal(SENTENCE), want)
        self.assertEqual(AG.mask(SENTENCE), want)
        self.assertEqual(talk.mask_pii(SENTENCE), want[0])
        from api import pc_builder_advisor as PB
        self.assertIs(PB.mask, AG.mask)

    def test_regex_lives_in_one_place(self):
        # 같은 정규식을 여러 벌 두지 않는다 -- 휴대전화 번호 모양은 pii_mask 에만 있다
        hits = [p.name for p in (ROOT / "api").glob("*.py")
                if "01[016789]" in p.read_text(encoding="utf-8") and p.name != "pii_mask.py"]
        self.assertEqual(hits, [])

    def test_basic_talk_history_is_masked(self):
        # 기본 상담(api/talk.py)의 대화 이력 -- 예전에는 주민·카드만 가렸다
        out = talk._trim_history([talk.HistoryTurn(role="user", text=SENTENCE),
                                  talk.HistoryTurn(role="assistant", text="확인 " + SENTENCE)])
        self.assertEqual(len(out), 2)
        _assert_clean(self, repr(out))


class OutgoingCall(unittest.TestCase):
    """llm.call -- 공급자 SDK 자리(spec.caller)에 넘어간 prompt·system."""

    def _call(self, *, customer_facing, task_key="task.s1_parse"):
        seen = []

        def fake(model, prompt, system, max_out, timeout):
            seen.append((prompt, system))
            return ("네.", 10, 5)

        spec = dataclasses.replace(llm.PROVIDERS["claude"], caller=fake)
        with patch.dict(llm.PROVIDERS, {"claude": spec}), \
                patch.object(llm, "_check_caps", lambda *a, **k: None), \
                patch.object(llm, "engine", _Engine()), \
                patch.object(llm, "_insert_cost_log", lambda row: 1), \
                patch.dict("os.environ", {spec.env_key: "x", llm.REROUTE_ENV: "off"}):
            llm.call("고객 문장: " + SENTENCE, provider="claude", model=spec.default_model, task_key=task_key,
                     system="참고 자료: " + SENTENCE, customer_facing=customer_facing, fallback_order=[])
        return seen

    def test_customer_calls_never_carry_raw_numbers(self):
        for key in ("task.s1_parse", "task.talk_answer", "task.pc_advice", "task.pc_builder", "task.s2_explain"):
            with self.subTest(task_key=key):
                (prompt, system), = self._call(customer_facing=True, task_key=key)
                _assert_clean(self, prompt + system)
                for label in ("[전화번호]", "[이메일]", "[주민번호]", "[카드번호]"):
                    self.assertIn(label, prompt)

    def test_admin_tasks_are_unchanged(self):
        (prompt, system), = self._call(customer_facing=False, task_key="task.ops_assist")
        self.assertEqual(prompt, "고객 문장: " + SENTENCE)
        self.assertEqual(system, "참고 자료: " + SENTENCE)


class BasicTalkPath(unittest.TestCase):
    """기본 상담(/api/talk/parse) 문장·이력 -> 좌표 추출 AI 호출 -> 공급자 자리까지 그대로 따라간다."""

    def test_sentence_and_history_reach_provider_masked(self):
        import contextlib
        import json
        from api import talk_answer as TA, talk_schema as TS
        from tests.test_talk_rules_20261010 import vocab, _Conn as TalkConn

        seen = []

        def fake(model, prompt, system, max_out, timeout):
            seen.append((prompt, system or ""))
            return (json.dumps({"pc": None, "state": {}, "reply": "네."}, ensure_ascii=False), 10, 5)

        spec = dataclasses.replace(llm.PROVIDERS["claude"], caller=fake)
        ans = TA.AnswerResult(answer="", narrowing=TS.NARROWING_WIDE)
        body = talk.ParseBody(text=SENTENCE, history=[talk.HistoryTurn(role="user", text="전에 말한 " + SENTENCE)])
        with contextlib.ExitStack() as st:
            st.enter_context(patch.object(talk.engine, "connect", lambda: TalkConn()))
            st.enter_context(patch.object(talk.engine, "begin", lambda: TalkConn()))
            st.enter_context(patch.object(talk.access_gate, "check_rate", lambda *a, **k: None))
            st.enter_context(patch.object(talk.TS, "load_vocab", lambda conn: vocab()))
            st.enter_context(patch.object(talk.TA, "run_parallel", lambda a, b: (a(), ans)))   # [A] 를 실제로 부른다
            st.enter_context(patch.object(talk.TA, "is_game_related", lambda *a: False))
            st.enter_context(patch.object(talk, "_record_hit", lambda *a, **k: None))
            st.enter_context(patch.dict(llm.PROVIDERS, {"claude": spec}))
            st.enter_context(patch.object(llm, "_route", lambda *a: (["claude"], "claude", spec.default_model)))
            st.enter_context(patch.object(llm, "_check_caps", lambda *a, **k: None))
            st.enter_context(patch.object(llm, "engine", _Engine()))
            st.enter_context(patch.object(llm, "_insert_cost_log", lambda row: 1))
            st.enter_context(patch.dict("os.environ", {spec.env_key: "x"}))
            talk.parse_talk(body, request=None)
        self.assertEqual(len(seen), 1)
        _assert_clean(self, seen[0][0] + seen[0][1])
        self.assertIn("[전화번호]", seen[0][0])


class OutgoingTools(unittest.TestCase):
    """llm.call_tools -- 도구 상담 공급자 자리에 넘어간 messages·system."""

    def test_messages_and_system_are_masked(self):
        seen = []

        def fake(model, messages, tools, system, max_out, timeout):
            seen.append((messages, system))
            return ("답", [], [], 1, 1, None, "end_turn")

        msgs = [{"role": "assistant", "text": "이전 안내 " + SENTENCE},          # 화면이 보낸 이력(원형 없음)
                {"role": "user", "text": SENTENCE},
                {"role": "tool", "id": "c1", "name": "find_pcs", "content": '{"price": 1500000}'}]
        with patch.object(llm, "_TOOL_CALLERS", {"claude": fake}), \
                patch.object(llm, "_check_caps", lambda *a, **k: None), \
                patch.object(llm, "engine", _Engine()), \
                patch.object(llm, "_insert_cost_log", lambda row: 1), \
                patch.dict("os.environ", {"ANTHROPIC_API_KEY": "x", llm.REROUTE_ENV: "off"}):
            llm.call_tools(msgs, [], task_key="task.talk_agent", provider="claude",
                           model=llm.PROVIDERS["claude"].default_model, system="자료 " + SENTENCE, fallback_order=[])
        (sent, system), = seen
        _assert_clean(self, repr(sent) + system)
        self.assertEqual(sent[2], msgs[2])                    # 서버가 만든 도구 결과는 그대로
        self.assertIn("010-1234-5678", msgs[1]["text"])       # 호출부의 목록은 고치지 않는다


class CallSites(unittest.TestCase):
    def test_every_llm_call_declares_who_waits(self):
        # 새 호출부가 customer_facing 을 빠뜨리면 기본값(False)으로 가림을 건너뛴다 -- 그것을 막는다.
        for p in (ROOT / "api").glob("*.py"):
            if p.name == "llm.py":
                continue
            src = p.read_text(encoding="utf-8")
            for m in re.finditer(r"llm\.call\((?!\))", src):           # 주석 속 `llm.call()` 은 뺀다
                window = src[m.end():m.end() + 400]
                with self.subTest(file=p.name, at=m.start()):
                    if "customer_facing=True" in window:
                        continue
                    self.assertIn("customer_facing=False", window)
                    self.assertIn("task.ops_assist", window)       # 관리자 작업만 가림 밖이다


if __name__ == "__main__":
    unittest.main()
