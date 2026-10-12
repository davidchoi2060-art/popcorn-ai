"""「성능 좋은 사무용 컴퓨터」 -- 작업 없이 성능만 높여 달라고 하면 기준표 2단계(쾌적)부터 고른다.

2026-10-12 사장님 시험 「지금 사무용으로 쓸만한 성능좋은 컴퓨터」: 「성능좋은」이 무시돼 1단계 사무용 기본 카드가 나왔다.
"""
import unittest
from unittest.mock import patch

from api import reco_explore as X, sold_reco as S, talk_defaults as TD, talk_schema as TS
from api.talk_schema import TalkState
from tests.test_reco_explore import LEVELS
from tests.test_reco_heavy_work_20261012 import OFFICE, PCS


class Extract(unittest.TestCase):
    def test_good_performance_words(self):
        for t in ("지금 사무용으로 쓸만한 성능좋은 컴퓨터", "성능 좋은 사무용 PC", "고성능 개발용 컴퓨터",
                  "사양 좋은 걸로 사무용", "성능이 뛰어난 컴퓨터 필요해요"):
            self.assertEqual(X.heavy_levels(t).get("사무용"), "쾌적", t)

    def test_negated_or_plain_sentences(self):
        for t in ("성능 좋을 필요 없어요 사무용이에요", "고성능은 필요 없고 문서만 써요", "사무용 컴퓨터 50만원",
                  "가성비 좋은 사무용"):
            self.assertNotIn("사무용", X.heavy_levels(t), t)

    def test_named_work_still_wins(self):
        self.assertEqual(X.heavy_levels("고성능으로 가상머신 돌려요").get("개발"), "전문")

    def test_screen_round_trip(self):
        self.assertEqual(X.clean_wants({"heavy": {"사무용": "쾌적", "주식·트레이딩": "쾌적"}}),
                         {"heavy": {"사무용": "쾌적", "주식·트레이딩": "쾌적"}})


class Cards(unittest.TestCase):
    def test_office_good_performance_starts_from_second_level(self):
        ex = X.extract("지금 사무용으로 쓸만한 성능좋은 컴퓨터")
        with patch.object(S, "load", lambda: (LEVELS + OFFICE, PCS)), \
             patch.object(S, "public_codes", lambda: frozenset()), \
             patch.object(X, "part_tags", lambda: {}):
            cs = S.card_sets(TalkState(usages=["사무용"]), [], ["사무용"], [], None,
                             {"wants": {"heavy": ex["heavy"]}})[0]
        self.assertEqual(cs["min_level"], "쾌적")
        self.assertNotIn(11, [i["product_code"] for i in cs["items"]])

    def test_basis_line_says_second_level(self):
        work = {("사무용", None): "문서·웹·화상회의", ("사무용", "쾌적"): "대용량 엑셀·듀얼 모니터"}
        out = TD.answer_first(TalkState(usages=["사무용"], budget_won=1000000), None,
                              is_game_usage=TS.is_game_usage, work_of=lambda f, l=None: work.get((f, l)),
                              heavy=X.heavy_levels("성능 좋은 사무용 PC"))
        self.assertEqual(out, "사무용은 대용량 엑셀·듀얼 모니터 기준으로 봤어요.")


if __name__ == "__main__":
    unittest.main()
