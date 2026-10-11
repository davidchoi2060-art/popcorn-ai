"""2026-10-12 개발 서버 재점검(8문장)에서 남은 넷을 고정한다.

2 「다나와가 더 싸던데요」 -> 「저희도 비슷하게 맞춰볼 수 있어요」: 사이에 낱말이 끼어 약속 문장을 못 걷었다.
5 「노트북이 낫지 않아요?」 -> 안내 뒤 「저희는 데스크톱 조립 PC를 전문으로 하고 있어요」가 한 번 더 나갔다.
6 「모니터도 같이 사야 하는데」 -> 「본체 예산을 알려 주시면…」 뒤에 「용도와 예산을 알려 주시면…」을 또 물었다.
8 「지금 쓰는 컴퓨터가 i5-8400에 GTX 1060인데 업그레이드할까요?」 -> 지금 가진 부품을 원하는 조건으로 읽었다.
"""
import unittest

from api import talk_exceptions as TE, talk_rules as TR


class CompetitorPromiseWithWordsBetween(unittest.TestCase):
    def test_promise_with_words_between_dropped(self):
        out = TE._drop_promises("다나와 링크 안의 구성이 어떻게 되는지 알려주시면, 저희도 비슷하게 맞춰볼 수 있어요. "
                                "그전에 주로 어떤 용도로 쓸 계획이신가요?")
        self.assertEqual(out, TE.NOTE_COMPETITOR + " 주로 어떤 용도로 쓸 계획이신가요?")

    def test_flag_label(self):
        self.assertIn("가격 맞춤 약속", TR.promise_flags("저희도 비슷하게 맞춰볼 수 있어요."))

    def test_unrelated_kept(self):
        self.assertEqual(TR.promise_flags("저희도 용도부터 같이 정해 볼게요."), [])


class LaptopSpecialtyDuplicate(unittest.TestCase):
    def test_specialty_sentence_dropped(self):
        out = TR.with_laptop_notice("저희는 데스크톱 조립 PC를 전문으로 하고 있어요. 어떤 용도로 사용할 계획이신가요?")
        self.assertEqual(out, TR.LAPTOP_NOTICE + " 어떤 용도로 사용할 계획이신가요?")


class NoDoubleAsk(unittest.TestCase):
    def test_note_already_asks(self):
        note = "모니터 값을 뺀 본체 예산을 알려 주시면 그 금액으로 다시 찾아 드릴게요."
        self.assertEqual(TR.honest_reply([note], False, ["usages"]), note)

    def test_note_without_ask_still_gets_tail(self):
        out = TR.honest_reply(["윈도우는 설치되지 않은 상태로 출고돼요."], False, ["usages"])
        self.assertIn("용도와 예산을 알려 주시면", out)


class CurrentPcPartsAreNotConditions(unittest.TestCase):
    def test_current_pc_parts_skipped(self):
        for s in ("지금 쓰는 컴퓨터가 i5-8400에 GTX 1060인데 업그레이드할까요 새로 살까요?",
                  "현재 PC가 GTX 1660이에요. 바꿀까요?"):
            with self.subTest(s=s):
                self.assertEqual(TR.unsupported_conditions(s, None, _all=True), [])

    def test_wanted_part_after_current_kept(self):
        self.assertEqual(TR.unsupported_conditions("지금 쓰는 컴퓨터가 GTX 1060인데 RTX 4070 들어간 걸로 사고 싶어요",
                                                   None, _all=True), ["그래픽카드 RTX 4070"])

    def test_plain_request_unchanged(self):
        self.assertEqual(TR.unsupported_conditions("RTX 4070 들어간 PC", None, _all=True), ["그래픽카드 RTX 4070"])


if __name__ == "__main__":
    unittest.main()
