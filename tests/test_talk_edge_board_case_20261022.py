"""오픈 전 엣지 점검 2건 (2026-10-22, 외부 점검표의 시험 질문을 개발 서버에 넣어 본 결과).

2-1 「CPU는 i7-14700K, 메인보드는 AMD B650」: 호환 안 됨은 잘 짚었지만, 바로잡은 구성의 보드를 «가장 싸서» H610 으로 골랐다
    -> 상급 CPU 면 보급형 칩셋 보드(H610·A620 등)를 뒤로 보낸다(그것밖에 없으면 그대로).
2-3 「ITX 케이스 + RTX 4080 SUPER 3팬 + 500W」: 파워 부족만 말하고 케이스에 그래픽카드가 안 들어갈 수 있다는 말이 없었다
    -> 작은 케이스와 큰 그래픽카드를 함께 말하면 확인 안내 한 줄.
"""
import unittest

from api import mvp3_free_build as F
from api import talk_pc_advice as PA


def opt(name):
    return {"name": name, "product_code": hash(name) % 10**6, "cost": 1}


class BoardOrder(unittest.TestCase):
    BOARDS = [opt("GIGABYTE H610M K D4"), opt("ASRock A620M-HDV"), opt("ASUS PRIME B760M-A"), opt("MSI PRO Z790-A")]

    def test_high_cpu_puts_entry_boards_last_keeping_price_order(self):
        for cpu in ("인텔 코어i7-14세대 14700K", "AMD 라이젠7-5세대 7800X3D", "인텔 코어 울트라7 265K", "인텔 코어i5-14세대 14600KF"):
            got = [o["name"] for o in F.mb_order(self.BOARDS, {"CPU": {"name": cpu}})]
            self.assertEqual(got, ["ASUS PRIME B760M-A", "MSI PRO Z790-A", "GIGABYTE H610M K D4", "ASRock A620M-HDV"], cpu)

    def test_mainstream_cpu_keeps_cheapest_first(self):
        for cpu in ("인텔 코어 i5-12400F", "AMD 라이젠5 7500F", None):
            picks = {"CPU": {"name": cpu}} if cpu else {}
            self.assertEqual(F.mb_order(self.BOARDS, picks), self.BOARDS)

    def test_only_entry_boards_still_usable(self):
        only = [opt("GIGABYTE H610M K D4")]
        self.assertEqual(F.mb_order(only, {"CPU": {"name": "i7-14700K"}}), only)


class CaseFit(unittest.TestCase):
    def test_small_case_with_big_gpu(self):
        s = "케이스는 초소형 미니 타워(ITX)로 예쁜 거 쓰고, 그래픽카드는 RTX 4080 슈퍼 3팬 넣고, 파워는 아끼게 500W로 해줘."
        self.assertEqual(PA.case_fit_note(s), PA.NOTE_CASE_FIT)
        self.assertTrue(PA.case_fit_note("미니 타워에 4090"))

    def test_not_for_other_sentences(self):
        for s in ("ITX 케이스에 RTX 5060 넣을래요", "배그용 PC 추천", "RTX 5080 게이밍 PC 300만원", "미니 PC 추천해줘", ""):
            self.assertIsNone(PA.case_fit_note(s), s)

    def test_both_paths_attach_the_note(self):
        import inspect
        from api import talk_agent
        self.assertIn("case_fit_note(sentence)", inspect.getsource(PA.advise))
        self.assertIn("PA.case_fit_note(sentence)", inspect.getsource(talk_agent._pc_checks))


if __name__ == "__main__":
    unittest.main()
