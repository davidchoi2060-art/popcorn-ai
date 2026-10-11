"""2026-10-11 개발 서버 「배그와 롤 150만원」 캡처 후속 -- 고객용 AI 문장 손질(talk_rules.tidy_customer_text)."""
import unittest
from pathlib import Path

from api import talk_rules as TR

ROOT = Path(__file__).resolve().parent.parent


class ForeignWordTest(unittest.TestCase):
    def test_hindi_word_in_korean_answer_is_removed(self):
        raw = ('배그는 현재 확인된 자료에 게임 설명이 없어 상세한 안내가 어렵습니다. '
               'उपलब्ध한 자료만으로는 두 게임에 대한 구체적인 추천을 판단하기 어렵습니다.')
        out = TR.tidy_customer_text(raw, '배그와 롤 150만원')
        self.assertEqual(out, '배그는 현재 확인된 자료에 게임 설명이 없어 상세한 안내가 어렵습니다. '
                              '자료만으로는 두 게임에 대한 구체적인 추천을 판단하기 어렵습니다.')

    def test_other_scripts_and_clean_text(self):
        self.assertEqual(TR.tidy_customer_text('Хорошо 좋아요 ありがとう.'), '좋아요.')
        plain = 'RTX 5060 · 16GB, 「롤」 FHD 144Hz 좋아요. 1μs'
        self.assertEqual(TR.tidy_customer_text(plain), plain)
        self.assertEqual(TR.tidy_customer_text(''), '')
        self.assertIsNone(TR.tidy_customer_text(None))


class BudgetWordTest(unittest.TestCase):
    def test_no_dae_when_the_customer_did_not_say_it(self):
        self.assertEqual(TR.tidy_customer_text('배틀그라운드와 리그 오브 레전드를 150만원대에서 찾을게요.', '배그와 롤 150만원'),
                         '배틀그라운드와 리그 오브 레전드를 150만원에서 찾을게요.')
        self.assertEqual(TR.tidy_customer_text('100만원대로 볼게요. 예산이 100만원대예요.', '사무용 100만원'),
                         '100만원으로 볼게요. 예산이 100만원이에요.')
        self.assertEqual(TR.tidy_customer_text('120만원대가 좋아요.', '롤 120'), '120만원이 좋아요.')

    def test_dae_stays_when_the_customer_said_it(self):
        self.assertEqual(TR.tidy_customer_text('100만원대로 볼게요.', '게임용 100만원대'), '100만원대로 볼게요.')

    def test_other_amounts_untouched(self):
        self.assertEqual(TR.tidy_customer_text('200만원대도 있어요.', '150만원'), '200만원대도 있어요.')


class WiringTest(unittest.TestCase):
    def test_reply_and_answer_both_pass_through_before_leaving(self):
        src = (ROOT / 'api/talk.py').read_text(encoding='utf-8')
        self.assertIn('reply = TR.tidy_customer_text(reply, text)', src)
        self.assertIn('answer = TR.tidy_customer_text(answer, text)', src)
        self.assertIn('「200만원대」처럼 「대」를 붙이지 않는다', src)


if __name__ == '__main__':
    unittest.main()
