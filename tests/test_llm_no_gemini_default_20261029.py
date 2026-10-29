"""Gemini 키 프로젝트 삭제 뒤 기본값을 codex 로 (2026-10-29 사장님 「응 진행해줘」).

davidchoi2060 계정 프로젝트(gen-lang-client · Gemini API 키 소속)를 삭제했다. 운영 도우미(task.ops_assist)와
작업 근거 없이 부르는 옛 호출이 Gemini 를 기본으로 써서, 그대로 두면 죽은 키로 먼저 부르게 된다.
"""
import os
import unittest
from unittest.mock import patch

from api import llm


class NoGeminiDefault(unittest.TestCase):
    def first_provider(self, **kw):
        seen = []

        def fail(prompt, prov, *a, **k):
            seen.append(prov)
            raise llm.LLMProviderError("down", transient=True)
        with patch.object(llm, "_call_one", fail), \
             patch.object(llm, "_resolve_fallback_order", lambda p, tk: []), \
             patch.dict(os.environ, {}, clear=False):
            os.environ.pop(llm.REROUTE_ENV, None)
            with self.assertRaises(llm.LLMError):
                llm.call("hi", **kw)
        return seen[0]

    def test_ops_assist_uses_codex(self):
        self.assertEqual(llm.TASK_DEFAULTS["task.ops_assist"], ("codex", "gpt-5.6-luna"))
        with patch.object(llm, "_load_task_assignment", lambda conn, tk: None), \
             patch.object(llm, "engine", unittest.mock.MagicMock()):
            self.assertEqual(self.first_provider(task_key="task.ops_assist"), "codex")

    def test_call_without_task_or_provider_uses_codex(self):
        self.assertEqual(llm.DEFAULT_PROVIDER, "codex")
        self.assertEqual(self.first_provider(), "codex")

    def test_no_task_default_points_at_gemini(self):
        self.assertNotIn("gemini", {p for p, _ in llm.TASK_DEFAULTS.values()})


if __name__ == "__main__":
    unittest.main()
