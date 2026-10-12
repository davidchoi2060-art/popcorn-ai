"""AI 설명이 권하는 램·SSD 용량을 카드가 따르는 기준표 숫자에 맞춘다 (2026-10-12 카드 검수 B5).

사무용에 「램 16GB 권장」이라 했는데 카드 두 장은 8GB(기준표 사무용 기본 = 램 8GB 이상)였다.
프롬프트가 최소 기준 숫자부터 말하고 윗단계는 그 작업을 할 때로 나누라고 시키는지 본다(LLM 미호출).
"""
import unittest

from api import talk_pc_advice as PA

BASIS = ["- 사무용 기본: 문서·웹·화상회의 (램 8GB 이상 · SSD 240GB 이상) <- 추천 카드의 최소 기준",
         "- 사무용 쾌적: 대용량 엑셀·다중 창 (램 16GB 이상 · SSD 480GB 이상)"]


class CardFloor(unittest.TestCase):
    def test_prompt_tells_capacities_to_follow_the_basis_floor(self):
        prompt = PA.build_prompt("사무실 직원용 PC 엑셀이랑 문서 작업만 하고 80만원 이하", BASIS)
        self.assertIn("램 8GB 이상", prompt)
        self.assertIn("램·SSD 용량은 기준표 숫자로 말한다", prompt)
        self.assertIn("「추천 카드의 최소 기준」 단계 숫자로 되는 작업을 먼저 말하고", prompt)
        self.assertIn("기준표보다 큰 용량은 권장처럼 말하지 않고", prompt)


if __name__ == "__main__":
    unittest.main()
