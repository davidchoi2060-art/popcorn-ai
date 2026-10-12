"""용도와 예산만 말한 문장에도 설명을 먼저 낸다(api/talk_pc_advice.topic_of) -- 2026-10-12 Claude 복귀 뒤 점검.

「사무용 80만원」에 설명 없이 「문서 작업 중심인가요?」 질문만 나갔다. PC 낱말·요청 낱말이 없어
topic_of 가 None 을 돌려 [B] 설명이 아예 불리지 않았다."""
import unittest

from api import talk_pc_advice as PA
from tests.test_talk_pc_advice_20261011 import vocab


class UsageBudget(unittest.TestCase):
    def test_usage_and_budget_is_build(self):
        for s, want in (("사무용 80만원", ["사무·인강"]), ("게임용 150만원대", ["게임"])):
            with self.subTest(s=s):
                self.assertEqual(PA.topic_of(s, vocab()), PA.TOPIC_BUILD)
                self.assertEqual(PA.wants_advice(s, vocab()), want)

    def test_amount_without_usage_or_pc_stays_out(self):
        for s in ("80만원", "사무용 모니터 30만원", "사무용 80만원 환불 언제 돼요"):
            with self.subTest(s=s):
                self.assertNotEqual(PA.topic_of(s, vocab()), PA.TOPIC_BUILD)


if __name__ == "__main__":
    unittest.main()
