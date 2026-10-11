"""노트북 안내는 한 번만 -- 2026-10-12 개발 서버 확인 결과를 고정한다.

「노트북이 낫지 않아요?」의 아래 줄이 「노트북은 판매하지 않습니다. 조립 PC를 안내해 드릴게요.
저희는 조립 PC(데스크톱)만 취급하고 있어요. 어떤 용도로…」로 같은 말을 두 번 했다.
"""
import unittest

from api import talk_rules as TR


class LaptopNoticeOnce(unittest.TestCase):
    def test_same_sentence_from_ai_is_dropped(self):
        out = TR.with_laptop_notice("저희는 조립 PC(데스크톱)만 취급하고 있어요. 어떤 용도로 컴퓨터를 찾고 계신가요?")
        self.assertEqual(out, TR.LAPTOP_NOTICE + " 어떤 용도로 컴퓨터를 찾고 계신가요?")
        out = TR.with_laptop_notice("노트북은 취급하지 않아요. 용도를 알려 주세요.")
        self.assertEqual(out, TR.LAPTOP_NOTICE + " 용도를 알려 주세요.")

    def test_other_sentences_kept(self):
        out = TR.with_laptop_notice("들고 다니실 일이 많으신가요?")
        self.assertEqual(out, TR.LAPTOP_NOTICE + " 들고 다니실 일이 많으신가요?")
        self.assertEqual(TR.with_laptop_notice(""), TR.LAPTOP_NOTICE)


if __name__ == "__main__":
    unittest.main()
