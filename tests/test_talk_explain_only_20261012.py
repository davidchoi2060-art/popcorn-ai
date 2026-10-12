"""설명만 바라는 문장은 추천 조건으로 읽지 않는다 (2026-10-12 카드 검수 X2).

「RAM 16GB랑 32GB 차이만 설명해 주세요. 아직 PC 추천은 필요 없어요.」에 설명 뒤
「메모리 16GB 조건으로 판매 중인 PC를 골라 볼게요」와 카드 3장이 나왔다. AI 는 흉내 낸다(LLM 미호출).
"""
from types import SimpleNamespace
import unittest

from api import talk_rules as TR
from tests.test_talk_exceptions_20261011 import _parse_raw, _ai

ASK = 'RAM 16GB랑 32GB 차이만 설명해 주세요. 아직 PC 추천은 필요 없어요.'


def _state():
    return SimpleNamespace(prefs=[], budget=None, purpose=None, game=None)


class ExplainOnly(unittest.TestCase):
    def test_explain_only_sentences(self):
        for t in (ASK, 'SSD 500GB와 1TB 차이 기준만 알려 주세요', '추천 말고 설명해 주세요', 'PC 추천은 아직 필요 없어요'):
            self.assertTrue(TR.explain_only(t), t)

    def test_requests_for_cards_are_not_explain_only(self):
        for t in ('배그 PC 추천해 주세요', '이 추천 말고 더 싼 거 보여줘', 'i3랑 i5 차이가 큰가요? 80만원 이하요',
                  '차이만으로는 모르겠어요 추천해 줘', '램 32GB로 150만원 PC'):
            self.assertFalse(TR.explain_only(t), t)

    def test_parts_in_explain_only_sentence_are_not_conditions(self):
        self.assertEqual(TR.unsupported_conditions(ASK, _state(), _all=True), [])
        self.assertEqual(TR.condition_notices(ASK, _state()), [])

    def test_response_says_explain_only(self):
        raw = _ai({'pc': True, 'state': {'usages': ['게임'], 'budget_won': 1500000}, 'reply': '차이를 알려 드릴게요.'})
        r = _parse_raw(ASK, raw_ai=raw)
        self.assertIs(r['explain_only'], True)
        self.assertNotIn('골라 볼게요', r['reply'])
        r = _parse_raw('배그 하고 150만원이요', raw_ai=raw)
        self.assertIs(r['explain_only'], False)


if __name__ == '__main__':
    unittest.main()
