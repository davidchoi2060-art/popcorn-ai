"""잔액이 바닥나면 다른 공급자로 넘기고 관리자에게 알린다 -- 2026-10-12 사장님 「추천한대로 하자」.

02:21 Anthropic 「credit balance is too low」(400)가 「설정 실수」로 분류돼 상담 [A] 가 전부 502 였다.
"""
import os
import unittest
from unittest.mock import patch

from api import llm


def credit_err():
    return llm.LLMProviderError("Claude API error 400: Your credit balance is too low",
                                out_of_credit=True)


class CreditMessage(unittest.TestCase):
    def test_anthropic_credit_message(self):
        self.assertTrue(llm._is_credit_message(
            400, "Your credit balance is too low to access the Anthropic API."))

    def test_openai_insufficient_quota(self):
        self.assertTrue(llm._is_credit_message(429, "You exceeded your current quota", "insufficient_quota"))

    def test_plain_bad_request_is_not_credit(self):
        self.assertFalse(llm._is_credit_message(400, "messages: field required"))
        self.assertFalse(llm._is_credit_message(500, "credit balance"))

    def test_credit_error_is_fallback_eligible(self):
        self.assertTrue(llm._is_fallback_eligible(credit_err()))
        self.assertFalse(llm._is_fallback_eligible(llm.LLMProviderError("bad key")))


class CreditFallback(unittest.TestCase):
    def setUp(self):
        llm._credit_out_until.clear()
        llm._last_alert.clear()
        self.addCleanup(llm._credit_out_until.clear)
        self.addCleanup(llm._last_alert.clear)
        self.alerts = []
        self.seen = []
        p = [patch.dict(os.environ, {llm.REROUTE_ENV: "off"}),
             patch.object(llm, "_send_admin_alert", self.alerts.append),
             patch.object(llm, "_resolve_task_default",
                          lambda tk: ("claude", "claude-haiku-4-5-20251001", "test")),
             # 폴백 순서가 gemini 먼저여도(코드 기본) 잔액 부족이면 정해 둔 codex 로 바로 간다
             patch.object(llm, "_resolve_fallback_order", lambda prov, tk: ["gemini", "codex"]),
             patch.object(llm, "_call_one", self.fake)]
        for x in p:
            x.start()
            self.addCleanup(x.stop)

    def fake(self, prompt, prov, task_key, model, *a, **k):
        self.seen.append((prov, model))
        if prov == "claude":
            raise credit_err()
        return "ok:" + prov

    def test_switches_to_luna_and_alerts_once(self):
        self.assertEqual(llm.call("hi", task_key="task.s1_parse"), "ok:codex")
        self.assertEqual(self.seen, [("claude", "claude-haiku-4-5-20251001"), ("codex", "gpt-5.6-luna")])
        self.assertEqual(len(self.alerts), 1)
        # 이어지는 호출은 막힌 Claude 를 다시 부르지 않고, 알림도 다시 보내지 않는다
        self.seen.clear()
        self.assertEqual(llm.call("hi", task_key="task.s1_parse"), "ok:codex")
        self.assertEqual(self.seen, [("codex", "gpt-5.6-luna")])
        self.assertEqual(len(self.alerts), 1)

    def test_claude_retried_after_hold(self):
        llm.call("hi", task_key="task.s1_parse")
        llm._credit_out_until["claude"] = 0.0     # 보류 시간이 지났다(충전됨)
        self.seen.clear()
        llm.call("hi", task_key="task.s1_parse")
        self.assertEqual(self.seen[0][0], "claude")

    def test_explicit_no_fallback_is_respected(self):
        with self.assertRaises(llm.LLMProviderError):
            llm.call("hi", provider="claude", model="claude-haiku-4-5-20251001", fallback_order=[])
        self.assertEqual(self.seen, [("claude", "claude-haiku-4-5-20251001")])


if __name__ == "__main__":
    unittest.main()
