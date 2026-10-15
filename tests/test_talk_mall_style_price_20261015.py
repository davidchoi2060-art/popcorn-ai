"""상담 답변 규칙 -- 부품 가격 「확인 중」을 말하지 않고 PC 총액과 확인된 차액만 말한다(2026-10-15 사장님 결정)."""
import unittest

from api import talk_agent as TA


class MallStylePriceRule(unittest.TestCase):
    def test_no_part_price_pending_line(self):
        # 옛 규칙: price 가 null 이면 「가격 확인 중」이라고 한다 -> 부품 단품 가격이 없는 것이 오류처럼 읽혔다.
        self.assertNotIn("price 가 null 이면 「가격 확인 중」이라고 한다", TA.SYSTEM)

    def test_part_price_not_quoted(self):
        self.assertIn("부품 하나하나의 판매가는 말하지 않는다", TA.SYSTEM)
        self.assertIn("「부품 가격 확인 중」이라고 하지 않는다", TA.SYSTEM)

    def test_only_pc_total_and_confirmed_diff(self):
        self.assertIn("PC 총액과, 도구가 확인해 준 부품 변경 차액(price_diff)만 말한다", TA.SYSTEM)
        self.assertIn("차액 확인 필요", TA.SYSTEM)


if __name__ == "__main__":
    unittest.main()
