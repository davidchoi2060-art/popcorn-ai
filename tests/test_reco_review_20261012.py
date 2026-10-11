"""추천 탐색·지난 제안 표시의 경계 -- 2026-10-12 소스 검수(5812·9da2) 지적을 고정한다.

① 「예산 150 기가 막히게 좋은 걸로」는 예산 숫자가 있는 문장이다 -- 「150 기가」를 용량으로 지워 「더 좋게」로 읽었다.
② 「150만원 이상」 뒤 「제일 싼 거」에서 하한을 풀었으면 그 사실을 밝힌다.
③ 지난 제안이 비어 있어도 「이전 제안」 표시(is-past·머리)를 단다 -- 지난 「못 찾았어요」가 지금 답처럼 보였다.
"""
import pathlib
import unittest

from api import reco_explore as X
from api.talk_schema import TalkState
from tests.test_reco_explore import GAME, sets

ROOT = pathlib.Path(__file__).resolve().parents[1]


class BudgetNumberNotSpec(unittest.TestCase):
    def test_budget_then_number_blocks_direction(self):
        for t in ("예산 150 기가 막히게 좋은 걸로", "예산은 200 더 좋은 걸로"):
            self.assertNotIn("nav", X.extract(t), t)

    def test_idiom_is_not_a_capacity(self):
        self.assertNotIn("nav", X.extract("150 기가 막히게 좋은 걸로"))

    def test_capacity_still_reads(self):
        ex = X.extract("램 64기가로 더 좋은 걸로")
        self.assertEqual((ex.get("nav"), ex.get("min_ram_gb")), (X.BETTER, 64))


class FloorRelaxedIsSaid(unittest.TestCase):
    def test_note_when_floor_released(self):
        cs = sets(TalkState(**GAME, budget_won=5000000, budget_bound="이상"),
                  {"wants": {}, "nav": X.CHEAPER, "cheapest": True})[0]
        self.assertEqual(cs["explore"]["nav_note"], X.NOTE_FLOOR_RELAXED)

    def test_plain_note_when_floor_kept(self):
        cs = sets(TalkState(**GAME, budget_won=1500000, budget_bound="이상"),
                  {"wants": {}, "nav": X.CHEAPER, "cheapest": True})[0]
        self.assertEqual(cs["explore"]["nav_note"], X.NOTE_CHEAPEST)


class EmptyPastProposalIsMarked(unittest.TestCase):
    def test_empty_branch_has_past_markers(self):
        js = (ROOT / "mockups/mvp3/talk.js").read_text(encoding="utf-8")
        fn = js[js.index("function proposalBlock("):js.index("function card(")]
        empty = fn[fn.index("if(!products.length)"):]
        empty = empty[:empty.index("</div>';")]
        self.assertIn("is-past", empty)
        self.assertIn("+head+", empty)
        self.assertLess(fn.index("const head="), fn.index("if(!products.length)"))


if __name__ == "__main__":
    unittest.main()
