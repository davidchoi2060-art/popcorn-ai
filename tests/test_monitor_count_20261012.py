"""2026-10-12 사장님 시험 「주로 업무, 학교, 회사일, 개인적인 용도로 두루두루 사용하는데, 모니터가 4대 임」.

① 「모니터가 4대」를 여러 대 구매로 읽어 「한 대 기준」 안내가 나갔다 -> 모니터 수는 수량이 아니다.
② 설명 없이 안내와 카드만 나갔다 -> 쓰는 환경(모니터 여러 대)을 말하면 구성 설명을 먼저 한다.
③ 내장 그래픽 PC 두 장이 나왔다 -> 모니터 3대 이상은 외장 그래픽카드가 든 PC 만.
④ 추천 「사무용 쾌적」 옆 「더 높은 사양」이 「사무용 기본」이었다 -> 추천보다 낮은 수준은 내지 않는다.
"""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://u:p@localhost:5432/x")

from api import reco_explore as X, sold_reco as S, talk_pc_advice as PA, talk_rules as TR
from api.talk_schema import TalkState, Vocab
from tests.test_reco_explore import PRODUCTS

SENT = "주로 업무, 학교, 회사일, 개인적인 용도로 두루두루 사용하는데, 모니터가 4대 임"


class MonitorCountIsNotQuantity(unittest.TestCase):
    def test_count(self):
        for t, n in ((SENT, 4), ("모니터 두 대 써요", 2), ("듀얼 모니터", 2), ("3대 모니터 연결", 3),
                     ("사무용 PC 5대", None), ("모니터 추천해줘", None)):
            self.assertEqual(TR.monitor_count(t), n, t)

    def test_no_quantity_notice(self):
        self.assertNotIn("quantity", TR.purchase_topics(SENT))
        self.assertNotIn("multi", X.extract(SENT))

    def test_real_quantity_still_read(self):
        for t in ("회계 사무실 PC 5대 필요해요", "모니터 2대 쓰는 PC 3대 사려고요"):
            self.assertIn("quantity", TR.purchase_topics(t), t)
            self.assertTrue(X.extract(t).get("multi"), t)


class ExplainFirst(unittest.TestCase):
    def test_monitor_setup_gets_build_explanation(self):
        v = Vocab(tiers=[], grades=[], confirmed_games={}, all_game_names=[], usages=[("사무용", ["사무"])],
                  genres=[], genre_aliases={}, game_aliases={})
        self.assertEqual(PA.topic_of(SENT, v), PA.TOPIC_BUILD)
        self.assertEqual(PA.topic_of("듀얼 모니터 차이가 뭐예요", v), PA.TOPIC_PART)


def office(code, price, rank, gpu):
    p = dict(PRODUCTS[1])
    return dict(p, code=code, name=f"PC {code}", price=price, spec=dict(p["spec"], gpu=gpu),
                fit={"사무용": {"level": "x", "rank": rank, "blocked": []}})


LEVELS = [
    {"usage": "사무용", "level": "기본", "level_rank": 1, "work": "문서·웹·화상회의", "conditions": None},
    {"usage": "사무용", "level": "쾌적", "level_rank": 2, "work": "대용량 엑셀·듀얼 모니터", "conditions": None},
]
PCS = {21: office(21, 593400, 1, "인텔 UHD(내장)"), 22: office(22, 892800, 2, "인텔 UHD(내장)"),
       23: office(23, 1338500, 1, "RTX 3050 6GB"), 24: office(24, 1190000, 2, "RTX 3050 6GB"),
       25: office(25, 1450000, 2, "RTX 5060 8GB")}


def sets(explore):
    with patch.object(S, "load", lambda: (LEVELS, PCS)), patch.object(S, "public_codes", lambda: frozenset()), \
         patch.object(X, "part_tags", lambda: {}):
        return S.card_sets(TalkState(usages=["사무용"]), [], ["사무용"], [], None, explore)[0]


class Cards(unittest.TestCase):
    def test_four_monitors_need_display_gpu(self):
        ex = X.extract(SENT)
        cs = sets({"wants": {k: ex[k] for k in ("monitors", "heavy")}})
        got = [i["product_code"] for i in cs["items"]]
        self.assertTrue(got)
        self.assertFalse({21, 22, 23} & set(got), got)
        self.assertIn("모니터 4대 연결(외장 그래픽카드)", cs["explore"]["applied"])

    def test_premium_not_below_recommended_level(self):
        cs = sets({"wants": {"heavy": {"사무용": "쾌적"}}})
        prem = [i for i in cs["items"] if i["role"] == "premium"]
        for i in prem:
            self.assertNotEqual(i["product_code"], 23)

    def test_screen_round_trip(self):
        self.assertEqual(X.clean_wants({"monitors": 4}), {"monitors": 4})
        self.assertEqual(X.clean_wants({"monitors": 2}), {})
        self.assertEqual(X.clean_wants({"monitors": "4"}), {})


if __name__ == "__main__":
    unittest.main()
