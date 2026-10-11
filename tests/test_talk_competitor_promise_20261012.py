"""다른 쇼핑몰 비교에 가게가 가격을 맞춰 주겠다고 약속하지 않는다 -- 2026-10-12 개발 서버 확인 결과를 고정한다.

「다나와가 더 싸던데요」에 아래 줄이 「다른 곳 가격은 확인할 수 없지만, 저희도 맞춰드릴 수 있습니다.」였다.
남의 가격을 모르는 채 한 근거 없는 약속이라 서버가 그 문장을 걷고 확인 불가 한 줄을 둔다.
"""
import unittest

from api import talk, talk_exceptions as TX, talk_rules as TR

TEXT = "다나와가 더 싸던데요"


class CompetitorPromise(unittest.TestCase):
    def test_price_match_sentence_is_dropped(self):
        out, _ = TX.respond("다른 곳 가격은 확인할 수 없지만, 저희도 맞춰드릴 수 있습니다. 어떤 용도로 컴퓨터가 필요하신가요?",
                            TX.classify(TEXT, pc=True), pc=True, text=TEXT)
        self.assertNotIn("맞춰", out)
        self.assertTrue(out.startswith(TX.NOTE_COMPETITOR))
        self.assertIn("어떤 용도로 컴퓨터가 필요하신가요?", out)

    def test_other_price_promises(self):
        for s in ("더 싸게 해 드릴게요.", "최저가 보장해 드려요.", "우리도 가격 맞춰 볼게요."):
            with self.subTest(s=s):
                out, _ = TX.respond(s, ["competitor"], pc=True, text=TEXT)
                self.assertEqual(out, TX.NOTE_COMPETITOR)

    def test_reply_without_promise_is_kept(self):
        r = "같은 부품과 구성인지 먼저 비교해 보세요. 어떤 용도로 쓰세요?"
        self.assertEqual(TX.respond(r, ["competitor"], pc=True, text=TEXT)[0], r)

    def test_only_on_competitor(self):
        # 다른 예외에서는 손대지 않는다(서버 안내 문장을 걷지 않게).
        r = "램 64GB로 맞춰드리겠습니다."
        self.assertEqual(TX.respond(r, [], pc=True, text="램 64GB")[0], r)

    def test_flag_and_prompt(self):
        self.assertIn("가격 맞춤 약속", TR.promise_flags("저희도 맞춰드릴 수 있습니다."))
        self.assertIn("가격을 맞춰 주겠다고 약속하지 않는다", talk.EXCEPTION_BLOCK)


if __name__ == "__main__":
    unittest.main()
