"""예산을 말한 PC 문장은 설명을 먼저 하고, 이미 말한 예산은 다시 묻지 않는다 -- 2026-10-12 개발 서버 확인 결과를 고정한다.

「화이트 감성으로 100만원 PC」에 설명이 없었고, 아래 줄이 「용도와 예산을 알려 주시면」이었다(예산은 이미 말함).
"""
import unittest

from api import talk_pc_advice as PA, talk_rules as TR, talk_schema as TS
from tests.test_talk_pc_routing_20261012 import vocab


class AmountWithPcIsBuild(unittest.TestCase):
    def test_amount_and_pc(self):
        for s in ("화이트 감성으로 100만원 PC", "100만원대 조용한 컴퓨터", "150만 본체"):
            with self.subTest(s=s):
                self.assertEqual(PA.topic_of(s, vocab()), PA.TOPIC_BUILD)

    def test_not_build(self):
        for s in ("하루 10시간 컴퓨터 써요", "램 16GB 10만원", "100만원 넘는 그래픽카드"):
            with self.subTest(s=s):
                self.assertNotEqual(PA.topic_of(s, vocab()), PA.TOPIC_BUILD)


class BudgetNotAskedAgain(unittest.TestCase):
    NOTE = "말씀하신 흰색 케이스 조건으로 판매 중인 PC를 골라 볼게요."

    def test_budget_known(self):
        out = TR.honest_reply([self.NOTE], False, [TS.MISSING_USAGES], has_budget=True)
        self.assertNotIn("예산", out)
        self.assertIn("어떤 용도로 쓰실지", out)
        out = TR.honest_reply([self.NOTE], True, [TS.MISSING_GAME_GRADE], has_budget=True)
        self.assertNotIn("예산", out)

    def test_budget_unknown_keeps_old_line(self):
        out = TR.honest_reply([self.NOTE], False, [TS.MISSING_USAGES])
        self.assertIn("용도와 예산을 알려 주시면", out)


if __name__ == "__main__":
    unittest.main()
