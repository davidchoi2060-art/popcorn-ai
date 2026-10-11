"""잡담에도 두세 문장으로 충실히 답한다 -- 2026-10-12 일반 AI 비교 두 번째 86개 「잡담에 한 줄로 끝남」(E01~E08).

권유 규칙(PC 권유는 서버만, 잡담 3턴째에 한 번)은 사장님 결정이라 그대로 둔다 -- 바꾸는 것은 잡담 답의 길이와 알맹이다.
"""
import unittest

from api import talk


class Prompt(unittest.TestCase):
    def test_smalltalk_asks_for_two_or_three_sentences(self):
        self.assertIn("두세 문장", talk.SMALLTALK_BLOCK)
        self.assertIn("한 문장으로 끝내지 않는다", talk.SMALLTALK_BLOCK)
        self.assertIn("PC 이야기를 붙이지 않는다", talk.SMALLTALK_BLOCK)     # 권유 규칙은 그대로


class ReplyCut(unittest.TestCase):
    def test_long_reply_is_cut_at_a_sentence_end(self):
        long = "국밥이 든든해요. " * 30
        r = talk._reply_text({"reply": long}, False, False)
        self.assertLessEqual(len(r), talk.REPLY_MAX_LEN)
        self.assertTrue(r.endswith("든든해요."))

    def test_short_reply_is_untouched(self):
        self.assertEqual(talk._reply_text({"reply": "국밥이 든든해요."}, False, False), "국밥이 든든해요.")


if __name__ == "__main__":
    unittest.main()
