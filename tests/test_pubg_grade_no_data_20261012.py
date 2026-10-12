"""2026-10-12 사장님 시험 「배그만」 -- 배그가 캐주얼 게임으로 읽히고 「확인된 자료가 없어」가 나왔다.

① 0156 이 배틀그라운드 등급을 E -> A 로 올린다(FHD 칸은 E·A 둘 다 T1 이라 기본 견적은 그대로).
② 「확인된 자료가 없어」 같은 내부 자료 사정 문장은 게임 답·PC 설명 둘 다에서 걷는다.
"""
import importlib.util
import pathlib
import unittest

from api import talk_answer as TA
from api import talk_filter as TF
from api import talk_pc_advice as PA

VERS = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations" / "versions"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, VERS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class PubgGradeMigration(unittest.TestCase):
    def setUp(self):
        self.m = _load("0156_pubg_grade_a")
        self.g = _load("0091_spec_tiers_game_grades")

    def test_chain(self):
        self.assertEqual((self.m.revision, self.m.down_revision), ("0156", "0155"))

    def test_old_note_matches_0091(self):
        row = next(r for r in self.g.GAME_ASSIGNMENTS if r[1] == "배틀그라운드")
        self.assertEqual(row[2], "E")
        self.assertEqual(row[4], self.m.OLD_NOTE)       # downgrade 가 원래 근거를 그대로 되돌린다

    def test_fhd_tier_unchanged(self):
        tiers = {(r[0], r[1]): r[2] for r in self.g.GAME_GRADE_TIERS}
        self.assertEqual(tiers[("E", "1080p")], tiers[("A", "1080p")])


class DataExcuseDropped(unittest.TestCase):
    def test_confirmed_data_excuse(self):
        for s in ("배틀그라운드는 확인된 자료가 없어요.",
                  "배틀그라운드에 대한 관련 정보가 부족해요.",
                  "제공된 자료에는 세부 재미 요소가 없어요."):
            with self.subTest(s=s):
                self.assertTrue(TF.is_data_excuse(s))

    def test_customer_limits_kept(self):
        for s in ("확인된 자료가 없어 성능을 단정할 수는 없어요.",
                  "주어진 자료에는 호환 정보가 없어 동작을 보장할 수 없어요."):
            with self.subTest(s=s):
                self.assertFalse(TF.is_data_excuse(s))

    def test_game_answer_drops_without_facts(self):
        out = TA.tidy_game_list("배그는 백 명이 끝까지 살아남는 게임이에요. 배틀그라운드는 확인된 자료가 없어요.", [])
        self.assertEqual(out, "배그는 백 명이 끝까지 살아남는 게임이에요.")

    def test_pc_advice_drops(self):
        body, dropped = PA.clean("배틀그라운드는 확인된 자료가 없어요. 배그는 그래픽카드가 체감을 좌우해요.",
                                 PA.TOPIC_BUILD, "배그만 할 컴퓨터")
        self.assertNotIn("자료", body)
        self.assertIn("그래픽카드", body)
        self.assertIn("data excuse", [d["reason"] for d in dropped])


if __name__ == "__main__":
    unittest.main()
