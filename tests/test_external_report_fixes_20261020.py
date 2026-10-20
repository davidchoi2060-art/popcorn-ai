"""2026-10-20 외부 검증 요청서 M1·M2·M3 -- 서버 상담 경로(/mvp3·/mvp4 공통).

M1 답에서 판매가까지 말한 PC는 show_pcs 를 빠뜨려도 카드로 올라간다(대화 ≠ 오른쪽 카드 방지).
M2 예산 초과 대수·금액은 카드의 over_budget 표시가 아니라 이번 턴 예산과 판매가로 센다.
M3 「GTX 1660 쓰는데 RTX 5070으로 바꾸면」 파워 판정은 바꿀 카드 기준이다.
AI 응답은 흉내 낸다(실제 공급자 호출 없음).
"""
import unittest
from unittest.mock import patch

from api import talk_agent as AG, talk_pc_advice as PA, talk_tools as TT
from tests.test_talk_agent_20261012 import VOCAB, _Engine, _reco, _turn

OLD = {"product_code": 2001, "name": "골드 인텔 [12400F/16GB/500GB/RTX5060]", "price": 1_625_800, "spec": {},
       "level": None, "over_budget": False, "reasons": []}
NEW = {"product_code": 2002, "name": "[9600X/16G/1TB/RTX5070]", "price": 2_622_000, "spec": {},
       "level": None, "over_budget": True, "reasons": []}


class M1SaidPcBecomesCard(unittest.TestCase):
    def _run(self, reply):
        from api import grid_public as GP
        script = [_turn(calls=[{"id": "a", "name": "find_pcs",
                                "args": {"usages": ["게임"], "budget_won": 1_500_000, "resolution": "1440p"}}]),
                  _turn(reply)]
        reco = _reco(card_sets=[{"usage": "게임", "items": [NEW]}], game_resolution="1440p")
        with patch.object(AG, "engine", _Engine()), patch.object(AG, "load_vocab", lambda c: VOCAB), \
                patch.object(AG.llm, "call_tools", lambda *a, **k: script.pop(0)), \
                patch.object(GP, "recommend", lambda b: reco):
            return AG.run_turn("배그랑 로아, QHD, 본체 150만 원이에요.", [])

    def test_priced_pc_in_reply_is_shown_with_new_condition(self):
        out = self._run("QHD용으로 150만 원 이하는 없어요. 가장 가까운 [9600X/16G/1TB/RTX5070]은 2,622,000원이에요.")
        self.assertEqual([c["product_code"] for c in out["cards"]], [2002])
        self.assertEqual(out["state"]["budget_won"], 1_500_000)
        self.assertEqual(out["state"]["game"]["resolution"], "1440p")

    def test_reply_without_price_keeps_explain_only(self):
        out = self._run("QHD에서는 그래픽카드가 더 중요해요.")
        self.assertEqual((out["cards"], out["state"]), ([], None))


class M2BudgetCountUsesThisTurnBudget(unittest.TestCase):
    def test_stale_flag_does_not_hide_an_over_budget_card(self):
        cards = [dict(OLD), {"price": 1_707_400, "over_budget": True}]
        lead = AG.budget_lead(cards, 1_500_000, "FHD로 낮추면 이 두 대가 가까워요.")
        self.assertIn("2대는 모두", lead)
        self.assertIn("125,800원", lead)
        note = AG.budget_note([dict(OLD), {"price": 1_400_000}], 1_500_000, "좋아요.")
        self.assertIn("2대 중 1대", note)
        self.assertIn("125,800원", note)

    def test_minimum_budget_is_not_over(self):
        self.assertIsNone(AG.budget_lead([dict(OLD)], 1_500_000, "좋아요.", "이상"))
        self.assertIsNone(AG.budget_note([dict(OLD)], 1_500_000, "좋아요.", "이상"))


class M3UpgradeTargetGpu(unittest.TestCase):
    def test_target_gpu_is_the_one_switched_to(self):
        q = "지금 i5-9400F에 GTX 1660 쓰는데 그래픽카드만 RTX 5070으로 바꾸면 될까요? 파워는 500W예요."
        self.assertEqual(PA.psu_question(q), ("RTX 5070", 500))
        line = PA.psu_line("RTX 5070", 500, 650)
        self.assertIn("부족", line)
        self.assertIn("750W", line)

    def test_two_gpus_without_target_are_left_to_ai(self):
        self.assertIsNone(PA.psu_question("RTX 5070이랑 RTX 4070 중 500W 파워면 뭐가 나아요?"))

    def test_single_gpu_unchanged(self):
        self.assertEqual(PA.psu_question("RTX 5070에 500W 파워면 돼요?"), ("RTX 5070", 500))


if __name__ == "__main__":
    unittest.main()
