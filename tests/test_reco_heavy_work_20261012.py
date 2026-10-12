"""고객이 한 단계 위 작업을 직접 말하면 카드도 그 단계부터 -- 2026-10-11 사장님 비교 R25.

「엑셀 대용량 파일 돌리는 회계 사무실 PC」: 설명은 램 32GB 를 말했는데 카드는 램 8GB 1단계 PC 가 먼저 나왔고,
답 줄은 「사무용은 문서·웹·화상회의 기준으로 봤어요. 큰 엑셀 파일이나 … 한 단계 위 구성이 맞아요」였다.
"""
import unittest

from api import reco_explore as X, talk_defaults as TD, talk_schema as TS
from api.talk_schema import TalkState
from unittest.mock import patch

from api import sold_reco as S
from tests.test_reco_explore import LEVELS, PRODUCTS

OFFICE = [
    {"usage": "사무용", "level": "기본", "level_rank": 1, "work": "문서·웹·화상회의", "conditions": None},
    {"usage": "사무용", "level": "쾌적", "level_rank": 2, "work": "대용량 엑셀·다중 창·탭 수십 개·듀얼 모니터",
     "conditions": None},
]


def office_pc(code, price, rank, ram):
    return dict(PRODUCTS[1], code=code, name=f"PC {code}", price=price,
             spec=dict(PRODUCTS[1]["spec"], ram_gb=ram), fit={"사무용": {"level": "x", "rank": rank, "blocked": []}})


PCS = {11: office_pc(11, 595700, 1, 8), 12: office_pc(12, 893400, 2, 16)}


class Extract(unittest.TestCase):
    def test_reads_named_heavy_work(self):
        cases = {
            "엑셀 대용량 파일 돌리는 회계 사무실 PC 5대 필요해요": {"사무용": "쾌적"},
            "큰 엑셀 파일 많이 써요": {"사무용": "쾌적"},
            "사무용인데 듀얼 모니터 써요": {"사무용": "쾌적"},
            "도커 컨테이너 여러 개 돌려요": {"개발": "쾌적"},
            "가상머신 여러 개랑 도커": {"개발": "전문"},
            "솔리드웍스 쓸 거예요": {"캐드·설계": "쾌적"},
        }
        for t, want in cases.items():
            self.assertEqual(X.extract(t).get("heavy"), want, t)

    def test_plain_sentences_have_none(self):
        for t in ("사무용 컴퓨터 50만원 정도로 맞출 수 있어요?", "엑셀이랑 한글 정도 써요", "모니터도 같이 사야 하는데"):
            self.assertNotIn("heavy", X.extract(t), t)

    def test_screen_round_trip_only_known_pairs(self):
        self.assertEqual(X.clean_wants({"heavy": {"사무용": "쾌적", "게임": "4K", "x": 1}}), {"heavy": {"사무용": "쾌적"}})
        self.assertEqual(X.clean_wants({"heavy": "사무용"}), {})


class Cards(unittest.TestCase):
    def office_sets(self, wants):
        with patch.object(S, "load", lambda: (LEVELS + OFFICE, PCS)), \
             patch.object(S, "public_codes", lambda: frozenset()), \
             patch.object(X, "part_tags", lambda: {}):
            return S.card_sets(TalkState(usages=["사무용"]), [], ["사무용"], [], None, {"wants": wants})[0]

    def test_heavy_excel_starts_from_second_level(self):
        cs = self.office_sets({"heavy": {"사무용": "쾌적"}})
        self.assertEqual(cs["min_level"], "쾌적")
        self.assertNotIn(11, [i["product_code"] for i in cs["items"]])

    def test_plain_office_unchanged(self):
        cs = self.office_sets({})
        self.assertEqual(cs["min_level"], "기본")
        self.assertIn(11, [i["product_code"] for i in cs["items"]])


class BasisLine(unittest.TestCase):
    def work(self, fit, level=None):
        return {("사무용", None): "문서·웹·화상회의", ("사무용", "쾌적"): "대용량 엑셀·듀얼 모니터"}.get((fit, level))

    def test_basis_uses_named_level_and_drops_step_up_line(self):
        st = TalkState(usages=["사무용"], budget_won=1000000)
        out = TD.answer_first(st, None, is_game_usage=TS.is_game_usage, work_of=self.work,
                              heavy=X.heavy_levels("엑셀 대용량 파일 돌리는 회계 사무실 PC"))
        self.assertEqual(out, "사무용은 대용량 엑셀·듀얼 모니터 기준으로 봤어요.")

    def test_plain_basis_unchanged(self):
        st = TalkState(usages=["사무용"], budget_won=1000000)
        out = TD.answer_first(st, None, is_game_usage=TS.is_game_usage, work_of=self.work, heavy={})
        self.assertEqual(out, "사무용은 문서·웹·화상회의 기준으로 봤어요. " + TD.USAGE_AFTER["사무용"])


if __name__ == "__main__":
    unittest.main()
