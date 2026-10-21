"""2026-10-21 외부 재검증(2차) P2-1·P2-3 -- 서버 상담 경로(/mvp4 카드·답변).

P2-1 예산을 풀어 찾은 PC도 손님이 말한 예산으로 over_budget 을 잰다(엔진은 예산 없이 판정해 모두 거짓이었다).
P2-3 「150만 원 이하 PC는 현재 없습니다」처럼 넘는다는 말만 하고 금액이 없으면 초과액을 붙인다.
AI 응답은 흉내 낸다(실제 공급자 호출 없음).
"""
import unittest
from unittest.mock import patch

from api import talk_agent as AG
from tests.test_talk_agent_20261012 import VOCAB, _Engine, _reco, _turn

NEAR = {"product_code": 2003, "name": "골드 인텔 [12400F/16GB/500GB/RTX5060]", "price": 1_624_400, "spec": {},
        "level": None, "over_budget": False, "reasons": []}


class P23OverAmountWhenOnlyNoneSaid(unittest.TestCase):
    def test_no_amount_gets_gap(self):
        note = AG.budget_note([dict(NEAR)], 1_500_000, "FHD로 바꿔도 150만 원 이하 PC는 현재 없습니다.")
        self.assertIn("124,400원", note)

    def test_amount_already_said_adds_nothing(self):
        self.assertIsNone(AG.budget_note([dict(NEAR)], 1_500_000,
                                         "150만 원 이하는 없고, 가장 가까운 PC는 1,624,400원이에요."))


class P21RelaxedBudgetStillMarksOver(unittest.TestCase):
    def test_card_found_without_budget_is_over_the_asked_budget(self):
        from api import grid_public as GP
        script = [_turn(calls=[{"id": "a", "name": "find_pcs",
                                "args": {"usages": ["게임"], "budget_won": 1_500_000, "budget_bound": "이하"}}]),
                  _turn("예산 조건을 빼고 찾으면 [12400F/16GB/500GB/RTX5060]이 1,624,400원이에요.")]

        def reco(body):
            if body.state.get("budget_won") is not None:
                return _reco(card_sets=[{"usage": "게임", "items": []}])
            return _reco(card_sets=[{"usage": "게임", "items": [dict(NEAR)]}])
        with patch.object(AG, "engine", _Engine()), patch.object(AG, "load_vocab", lambda c: VOCAB), \
                patch.object(AG.llm, "call_tools", lambda *a, **k: script.pop(0)), \
                patch.object(GP, "recommend", reco):
            out = AG.run_turn("게임용 150만원 이하요.", [])
        self.assertEqual([c["product_code"] for c in out["cards"]], [2003])
        self.assertTrue(out["cards"][0]["over_budget"])
        self.assertIn("124,400원", out["reply"])


if __name__ == "__main__":
    unittest.main()
