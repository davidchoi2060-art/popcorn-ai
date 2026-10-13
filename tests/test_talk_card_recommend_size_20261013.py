"""설명이 권한 램·SSD 보다 작은 카드를 짚는다 (2026-10-13 코덱스 PR237 실화면 재검수 사례 11 · 6번).

사례 11(배그+롤 200만): 「SSD는 게임 여러 개를 설치할 수 있도록 960GB급을 권장해요」 아래 500GB·512GB 카드가 나왔다.
SSD 숫자 판독이 12자 한도라 이 문장을 아예 못 읽었고, 권장은 기준표 숫자라 맞지만 예산 안 카드는 더 작다 --
어느 카드가 권장보다 작은지와 메우는 길을 한 문장으로 말한다. 화면의 메모리 「합계 · 단가×수량」 줄 나눔도 함께 본다.
"""
import re
import unittest
from pathlib import Path

from api import talk_pc_advice as PA

CASE11 = ("램은 16GB 이상, SSD는 게임 여러 개를 설치할 수 있도록 960GB급을 권장해요. "
          "지금 이 조건에 맞는 판매 중인 PC는 아래 카드처럼 162만~187만원이에요.")
CARDS = [{"tag": "알뜰 구성", "spec": {"gpu": "RTX 5060", "ram_gb": 16, "ssd_gb": 500, "psu": "COOLMAX ELITE II 600W"}},
         {"tag": "추천 구성", "spec": {"gpu": "RTX 5060", "ram_gb": 16, "ssd_gb": 512, "psu": "MWE 브론즈 650 V3"}},
         {"tag": "더 높은 사양", "spec": {"gpu": "RTX 5060 Ti", "ram_gb": 32, "ssd_gb": 1000, "psu": "650W"}}]


class RecommendSizeTests(unittest.TestCase):
    def test_case11_names_small_cards_and_the_one_that_fits(self):
        out, _ = PA.align_card_specs(CASE11, CARDS, fhd_game=True)
        self.assertIn("960GB급을 권장", out)                              # 모든 카드보다 크진 않다 -- 남긴다
        self.assertIn("알뜰 구성·추천 구성 카드는 SSD가 500GB·512GB로 권장(960GB급)보다 작아요.", out)
        self.assertIn("더 높은 사양 카드는 권장 용량을 갖췄어요.", out)
        self.assertNotIn("램이", out)                                      # 램 16GB 이상은 모든 카드가 맞다

    def test_all_cards_below_keeps_the_fact_after_dropping_the_claim(self):
        out, dropped = PA.align_card_specs(CASE11, CARDS[:2], fhd_game=True)
        self.assertNotIn("960GB급을 권장", out)                            # 카드보다 큰 권장 문장은 걷는다(#237)
        self.assertEqual([d["reason"] for d in dropped], ["card ssd"])
        self.assertIn("아래 카드는 모두 SSD가 500GB·512GB로 권장(960GB급)보다 작아요.", out)
        self.assertNotIn("갖췄어요", out)

    def test_960_and_1tb_are_the_same_class(self):
        out, _ = PA.align_card_specs("SSD는 1TB 이상을 권장해요.", [CARDS[2], dict(CARDS[2], tag="x", spec=dict(CARDS[2]["spec"], ssd_gb=960))])
        self.assertNotIn("작아요", out)

    def test_ram_recommendation(self):
        out, _ = PA.align_card_specs("램은 32GB가 필요해요.", CARDS)
        self.assertIn("알뜰 구성·추천 구성 카드는 램이 16GB로 권장(32GB)보다 작아요.", out)

    def test_optional_or_plain_spec_sentences_are_not_recommendations(self):
        for s in ("작업이 늘면 SSD 2TB로 올려도 좋아요.", "이 카드는 SSD 2TB예요."):
            self.assertEqual(PA.under_recommendation_note(s, CARDS), "", s)

    def test_far_ssd_number_read_but_not_across_ram(self):
        self.assertEqual([m.group(1) for m in PA._SSD_CLAIM.finditer(CASE11)], ["960"])
        self.assertEqual(list(PA._SSD_CLAIM.finditer("SSD 속도보다 램 32GB가 중요해요.")), [])

    def test_no_promise_that_parts_can_be_changed(self):
        out, _ = PA.align_card_specs(CASE11, CARDS, fhd_game=True)
        self.assertIn("바꿀 수 있는지 확인해 보세요", out)                # 구성표 없는 PC 도 있다

    def test_ram_unit_price_on_its_own_line(self):
        css = (Path(__file__).resolve().parent.parent / "mockups" / "mvp3" / "styles.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.final-table \.final-part-price \.foot-note\{display:block")


if __name__ == "__main__":
    unittest.main()
