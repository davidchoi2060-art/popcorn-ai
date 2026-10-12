"""[A] 응답이 JSON 이 아니면 한 번만 다시 묻는다 (2026-10-12 카드 검수 · 개발 서버 재현).

같은 업그레이드 문장 3번 중 1번 「방금 말씀을 제가 잘 정리하지 못했어요」가 났다(모델 luna). 형식이 깨진
응답은 가끔이라, 고객에게 다르게 말해 달라고 하기 전에 한 번 더 묻는다. 다시 물어도 깨지거나 실패하면
지금처럼 「못 읽었다」 길이다(502 로 끊지 않는다). AI 는 흉내 낸다(LLM 미호출).
"""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from api import llm, talk, talk_exceptions as TX
from tests.test_talk_exceptions_20261011 import _parse_raw, _ai

PREV = {'usages': ['게임'], 'budget_won': 1500000}
GOOD = _ai({'pc': True, 'state': {'usages': ['게임'], 'budget_won': 1500000}, 'reply': '배그용으로 찾아볼게요.'})


def _result(text):
    return SimpleNamespace(text=text, provider='t', model='t', tokens_in=1, elapsed_sec=0.1)


class RetryOnce(unittest.TestCase):
    def test_broken_answer_is_asked_once_more_and_the_second_answer_is_used(self):
        calls = []
        with patch.object(talk.llm, 'call', lambda *a, **k: calls.append(k.get('task_key')) or _result(GOOD)):
            r = _parse_raw('배그 하고 150만원이요', raw_ai='{"pc": true, "state": {"usages"', prev=PREV)
        self.assertEqual(calls, ['task.s1_parse'])
        self.assertIsNone(r['fallback'])
        self.assertNotIn('ai_unreadable', r['exceptions'])
        self.assertNotEqual(r['reply'], TX.REPLY_AI_UNREADABLE)

    def test_second_broken_answer_still_falls_back_without_502(self):
        calls = []
        with patch.object(talk.llm, 'call', lambda *a, **k: calls.append(1) or _result('여전히 JSON 아님')):
            r = _parse_raw('배그 하고 150만원이요', raw_ai='JSON 아님', prev=PREV)
        self.assertEqual(len(calls), 1)
        self.assertEqual(r['fallback'], 'ai_unreadable')
        self.assertEqual(r['state']['budget_won'], 1500000)

    def test_retry_failure_is_the_same_fallback_not_502(self):
        def boom(*a, **k):
            raise llm.LLMProviderError('down', transient=True)
        with patch.object(talk.llm, 'call', boom):
            r = _parse_raw('배그 하고 150만원이요', raw_ai='JSON 아님', prev=PREV)
        self.assertTrue(r['ok'])
        self.assertEqual(r['fallback'], 'ai_unreadable')

    def test_good_first_answer_is_not_asked_again(self):
        calls = []
        with patch.object(talk.llm, 'call', lambda *a, **k: calls.append(1) or _result(GOOD)):
            _parse_raw('배그 하고 150만원이요', raw_ai=GOOD, prev=PREV)
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
