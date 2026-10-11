"""서버 env 한 줄로 막힌 공급자 대신 다른 공급자를 부른다 -- 2026-10-12 사장님 「다른 API 를 일단 사용하자」.

Anthropic 잔액 부족(400)은 _is_fallback_eligible 이 넘기지 않아 상담 [A] 가 전부 502 였다.
"""
import os
import unittest
from unittest.mock import patch

from api import llm


class Reroute(unittest.TestCase):
    def run_call(self, env, **kw):
        seen = []

        def fake(prompt, prov, task_key, model, *a, **k):
            seen.append((prov, model))
            return "ok"
        with patch.dict(os.environ, {llm.REROUTE_ENV: env} if env is not None else {}, clear=False), \
             patch.object(llm, "_call_one", fake), \
             patch.object(llm, "_resolve_task_default",
                          lambda tk: ("claude", "claude-haiku-4-5-20251001", "test")), \
             patch.object(llm, "_resolve_fallback_order", lambda p, tk: [x for x in llm.PROVIDERS if x != p]):
            if env is None:
                os.environ.pop(llm.REROUTE_ENV, None)
            self.assertEqual(llm.call("hi", task_key="task.s1_parse", **kw), "ok")
        return seen

    def test_no_env_keeps_claude(self):
        self.assertEqual(self.run_call(None), [("claude", "claude-haiku-4-5-20251001")])

    def test_reroute_to_named_model(self):
        self.assertEqual(self.run_call("claude=codex:gpt-5.6-luna"), [("codex", "gpt-5.6-luna")])

    def test_unknown_model_uses_target_default(self):
        self.assertEqual(self.run_call("claude=codex:nope"), [("codex", None)])

    def test_bad_entries_ignored(self):
        self.assertEqual(self.run_call("x=codex, claude=claude, ,"), [("claude", "claude-haiku-4-5-20251001")])

    def test_blocked_provider_left_out_of_fallback(self):
        def fail(prompt, prov, *a, **k):
            seen.append(prov)
            raise llm.LLMProviderError("down", transient=True)
        seen = []
        with patch.dict(os.environ, {llm.REROUTE_ENV: "claude=codex:gpt-5.6-luna"}), \
             patch.object(llm, "_call_one", fail), \
             patch.object(llm, "_resolve_task_default",
                          lambda tk: ("claude", "claude-haiku-4-5-20251001", "test")), \
             patch.object(llm, "_resolve_fallback_order", lambda p, tk: [x for x in llm.PROVIDERS if x != p]):
            with self.assertRaises(llm.LLMAllProvidersFailedError):
                llm.call("hi", task_key="task.s1_parse")
        self.assertEqual(seen, ["codex", "gemini"])


if __name__ == "__main__":
    unittest.main()
