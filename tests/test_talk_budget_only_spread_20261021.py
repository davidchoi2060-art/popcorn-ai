"""예산만 말하면 게임용만 소개하던 문제 (2026-10-21 중헌 님 「70만원만 입력하면 무조건 게임용으로만 소개함」).

손님이 용도·게임을 말한 적이 없으면 상담 AI 가 게임을 넣어 불러도 서버가 사무·인강 / 가벼운 게임 / 최신 게임(FHD)으로
고루 찾는다. 예산 안 PC 가 있으면 예산 넘는 PC 는 카드 후보에서 빼고 그 용도는 「○원부터」로만 준다.
"""
import unittest
from unittest.mock import patch

from api import talk_agent as AG, talk_tools as TT
from api.talk_schema import Vocab
from tests.test_talk_agent_20261012 import _Engine, _turn

VOCAB = Vocab(usages=[("게임", []), ("사무·인강", [])])
OFFICE = {"product_code": 2001, "name": "오피스 PC", "price": 529_000, "over_budget": False, "spec": {}, "level": "기본"}
OFFICE2 = {"product_code": 2002, "name": "오피스 PC 플러스", "price": 649_000, "over_budget": False, "spec": {}, "level": "쾌적"}
CASUAL_OVER = {"product_code": 3001, "name": "캐주얼 게임 PC", "price": 890_000, "over_budget": True, "spec": {}, "level": "캐주얼"}
FHD_OVER = {"product_code": 4001, "name": "골드 RTX5060", "price": 1_090_000, "over_budget": True, "spec": {}, "level": "FHD"}


def _fake_recommend(seen):
    def fake(body):
        st = body.state
        seen.append(st)
        assert len(st.get("usages") or []) <= 1, "용도마다 따로 부른다(여러 용도는 엔진이 한 대로 합친다)"
        if st.get("game") and st["game"].get("names") == [TT.SPREAD_CASUAL]:
            sets = [{"usage": "게임", "items": [CASUAL_OVER], "empty_note": "이 작업은 890,000원부터 가능합니다."}]
        elif st.get("usages") == ["사무·인강"]:
            sets = [{"usage": "사무·인강", "items": [OFFICE, OFFICE2]}]
        elif st.get("usages") == ["게임"]:
            sets = [{"usage": "게임", "items": [FHD_OVER], "empty_note": "이 작업은 1,090,000원부터 가능합니다."}]
        else:
            sets = []
        return {"card_sets": sets, "needs": [], "budget_won": st.get("budget_won"), "budget_bound": "이하",
                "platform": None, "anchor_code": None}
    return fake


class Spread(unittest.TestCase):
    def _run(self, script, text="70만원", prev_state=None):
        from api import grid_public as GP
        seen = []
        with patch.object(AG, "engine", _Engine()), patch.object(AG, "load_vocab", lambda c: VOCAB), \
                patch.object(AG.llm, "call_tools", lambda m, t, **k: script.pop(0)), \
                patch.object(GP, "recommend", _fake_recommend(seen)):
            out = AG.run_turn(text, [], prev_state=prev_state)
        return out, seen

    def test_budget_only_game_assumption_becomes_spread(self):
        out, seen = self._run([
            _turn(calls=[{"id": "a", "name": "find_pcs", "args": {"usages": ["게임"], "budget_won": 700_000}}]),
            _turn(calls=[{"id": "b", "name": "show_pcs", "args": {"refs": ["P1", "P2"]}}]),
            _turn("70만원이면 사무·인강용 오피스 PC가 529,000원이에요. 어디에 주로 쓰실 건가요?"),
        ])
        # 사무·인강 · 가벼운 게임 · 최신 게임(FHD) 을 따로 부른다(2026-10-29 -- 한 번에 부르면 «한 대로 모두»로 합쳐졌다).
        self.assertEqual(len(seen), 3)
        self.assertEqual(seen[0]["usages"], ["사무·인강"])
        self.assertEqual(seen[1]["game"]["names"], [TT.SPREAD_CASUAL])
        self.assertEqual(seen[2]["game"], {"names": [], "resolution": "1080p"})   # 이름 없는 게임은 캐주얼 기본형 -- FHD 는 직접 말한다
        self.assertEqual([c["product_code"] for c in out["cards"]], [2001, 2002])
        self.assertEqual(out["state"]["usages"], [])                        # 화면에 「게임」 조건을 넘기지 않는다
        self.assertEqual(out["state"]["budget_won"], 700_000)

    def test_over_budget_items_dropped_when_something_fits(self):
        book = TT.FactBook(spread_labels=("사무·인강", "게임"), usage_unknown=True)
        from api import grid_public as GP
        with patch.object(GP, "recommend", _fake_recommend([])):
            r = TT.find_pcs({"usages": ["게임"], "budget_won": 700_000}, book)
        self.assertTrue(r["usage_unknown"])
        by = {s["usage"]: s for s in r["sets"]}
        self.assertEqual([i["name"] for i in by["사무·인강"]["items"]], ["오피스 PC", "오피스 PC 플러스"])
        self.assertEqual(by["가벼운 게임(롤 같은)"]["items"], [])
        self.assertIn("890,000원부터", by["가벼운 게임(롤 같은)"]["empty_reason"])
        self.assertIn("1,090,000원부터", by["최신 게임(FHD)"]["empty_reason"])
        self.assertEqual(list(by)[0], "사무·인강")                          # 사무·인강 먼저

    def test_nothing_in_budget_keeps_nearest(self):
        def fake(body):
            return {"card_sets": [{"usage": "게임", "items": [FHD_OVER]}], "needs": [], "budget_won": 300_000}
        from api import grid_public as GP
        book = TT.FactBook(spread_labels=("사무·인강", "게임"))
        with patch.object(GP, "recommend", fake):
            r = TT.find_pcs({"usages": [], "budget_won": 300_000}, book)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["sets"][0]["items"][0]["name"], "골드 RTX5060")

    def test_said_game_is_kept(self):
        out, seen = self._run([
            _turn(calls=[{"id": "a", "name": "find_pcs", "args": {"usages": ["게임"], "budget_won": 700_000}}]),
            _turn("게임용은 1,090,000원부터예요."),
        ], text="게임용 70만원")
        self.assertEqual(seen, [{"usages": ["게임"], "budget_won": 700_000, "budget_bound": None, "platform": None,
                                 "prefs": []}])

    def test_named_game_is_kept(self):
        book = TT.FactBook(spread_labels=("사무·인강", "게임"), usage_unknown=True)
        self.assertFalse(TT._spread_wanted(["게임"], ["발로란트"], {}, book))
        self.assertFalse(TT._spread_wanted(["게임"], [], {"resolution": "1440p"}, book))
        self.assertFalse(TT._spread_wanted(["사무·인강"], [], {}, book))   # AI 가 문맥으로 고른 다른 용도는 그대로
        self.assertTrue(TT._spread_wanted([], [], {}, TT.FactBook(spread_labels=("사무·인강", "게임"))))

    def test_previous_usage_counts_as_said(self):
        self.assertTrue(AG.usage_said(["70만원"], VOCAB, {"usages": ["게임"]}))
        self.assertFalse(AG.usage_said(["70만원", "추천해줘"], VOCAB, None))
        self.assertTrue(AG.usage_said(["인강용으로 70만원"], VOCAB, None))
        self.assertTrue(AG.usage_said(["롤 할 거"], Vocab(usages=VOCAB.usages, game_aliases={"롤": "리그 오브 레전드"},
                                                         all_game_names=["리그 오브 레전드"]), None))

    def test_prompt_no_longer_assumes_game(self):
        self.assertNotIn("가장 흔한 용도(게임, FHD)", AG.SYSTEM)
        self.assertIn("게임용으로 단정하지 않는다", AG.SYSTEM)


if __name__ == "__main__":
    unittest.main()
