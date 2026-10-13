"""상담 답 품질 비교 재측정(2026-10-14) 남은 「우리가 못함」 대응 -- R05 · E06 · E26 (R07·R20 은 설명 지시문 보강).

R05 「발로란트 240프레임」: 설명은 「RTX 5060급이 적당」, 카드 하나는 RTX 3050 -> 낮은 카드를 짚는다.
E06 「너 바보야?」: 사과만 하고 끝났다 -> 무엇이 불편했는지 묻는 한 문장.
E26 「10만원으로 모든 게임4K 최고옵션」: 4K 카드 아래 「최고 사양 조건은 아직 추천에 반영하지 못해요」 -> 4K 게임이면 붙이지 않는다.
"""
from types import SimpleNamespace
import unittest

from api import talk, talk_pc_advice as PA, talk_rules as TR

R05 = ("발로란트 240프레임은 그래픽카드보다 CPU 성능이 더 크게 좌우되므로, FHD 경쟁 설정에서는 RTX 5060급 그래픽카드와 "
       "라이젠 5급 이상 CPU 조합이 적당해요. QHD나 높은 그래픽 옵션까지 원하면 한 단계 높은 등급을 고르면 돼요.")
CARDS = [{"tag": "알뜰 구성", "spec": {"gpu": "RTX 3050 6GB", "ram_gb": 16, "ssd_gb": 256}},
         {"tag": "추천 구성", "spec": {"gpu": "RTX 5060", "ram_gb": 16, "ssd_gb": 500}},
         {"tag": "더 높은 사양", "spec": {"gpu": "RTX 5060 Ti 8GB", "ram_gb": 16, "ssd_gb": 500}}]


class GpuBelowRecommendation(unittest.TestCase):
    def test_r05_names_the_lower_card(self):
        out, _ = PA.align_card_specs(R05, CARDS, fhd_game=True)
        self.assertIn("알뜰 구성 카드는 그래픽카드가 RTX 3050 6GB로 설명한 RTX 5060급보다 낮아요.", out)
        self.assertIn("추천 구성·더 높은 사양 카드는 RTX 5060급 이상이에요.", out)

    def test_optional_upgrade_sentence_is_not_the_baseline(self):
        self.assertIsNone(PA._recommended_gpu("QHD까지 원하면 RTX 5070급이 좋아요."))

    def test_dropped_claim_is_not_brought_back(self):
        out, dropped = PA.align_card_specs("그래픽카드는 RTX 5070급이 필요해요.", CARDS[:2], fhd_game=True)
        self.assertEqual([d["reason"] for d in dropped], ["card gpu"])
        self.assertNotIn("5070", out)

    def test_unnamed_cards_do_not_read_as_card_card(self):
        out, _ = PA.align_card_specs(R05, [dict(c, tag=None) for c in CARDS], fhd_game=True)
        self.assertNotIn("카드 카드", out)
        self.assertIn("일부 카드는 그래픽카드가", out)


class ApologyFollow(unittest.TestCase):
    def test_e06_apology_only_gets_a_question(self):
        r = "기분 상하셨나 봐요. 저희가 뭔가 불편하게 해드렸다면 죄송합니다."
        self.assertEqual(talk.follow_apology(r), r + " " + talk.REPLY_APOLOGY_FOLLOW)

    def test_already_asking_or_no_apology_left_alone(self):
        for r in ("죄송해요. 어떤 점이 불편하셨어요?", "저녁이라면 국밥이 무난해요.", ""):
            self.assertEqual(talk.follow_apology(r), r)
        self.assertFalse(talk.is_pc_push(talk.REPLY_APOLOGY_FOLLOW))


class TopSpecWith4KGame(unittest.TestCase):
    def state(self, res):
        return SimpleNamespace(game=SimpleNamespace(resolution=res), prefs=[], usages=["게임"])

    def test_e26_4k_game_top_option_is_not_unreflected(self):
        self.assertNotIn("최고 사양", TR.unsupported_conditions("10만원으로 모든 게임4K 최고옵션", self.state("4K")))

    def test_top_spec_without_4k_still_noted(self):
        self.assertIn("최고 사양", TR.unsupported_conditions("최고 사양으로 맞춰 주세요", self.state(None)))


class PartPrompt(unittest.TestCase):
    def test_comparison_answers_include_self_check_and_upgrade(self):
        t = PA._TOPIC_TASK[PA.TOPIC_PART]
        self.assertIn("작업 관리자", t)
        self.assertIn("나중에 바꾸기 쉬운지", t)
        self.assertIn("F 붙은 모델은 내장 그래픽이 없다", t)


if __name__ == "__main__":
    unittest.main()


class MildInsult(unittest.TestCase):
    def test_short_reply_to_mild_insult_gets_apology_and_question(self):
        r = talk.follow_mild_insult("너 바보야?", "기분이 안 좋으신 것 같네요. 편하게 말씀해 주세요.")
        self.assertTrue(r.endswith(talk.REPLY_MILD_INSULT))
        self.assertFalse(talk.is_pc_push(talk.REPLY_MILD_INSULT))

    def test_left_alone_when_not_insult_or_already_asked(self):
        self.assertEqual(talk.follow_mild_insult("오늘 저녁 뭐 먹지?", "국밥이 무난해요."), "국밥이 무난해요.")
        done = "죄송해요. 어떤 점이 불편하셨는지 알려 주세요."
        self.assertEqual(talk.follow_mild_insult("너 바보야?", done), done)
        self.assertEqual(talk.follow_mild_insult("너 바보야?", talk.follow_apology("죄송합니다.")),
                         talk.follow_apology("죄송합니다."))


class OverBudgetSaysGapOnce(unittest.TestCase):
    def test_e26_no_gap_in_explanation_and_not_read_as_market_price(self):
        raw = "10만원으로는 구성할 수 없어요. 시중에서는 보통 300만원대 이상으로 예상해요."
        out = PA.align_market_price(raw, [4_809_800], budget_won=100_000, sentence="10만원으로 모든 게임4K 최고옵션")
        self.assertNotIn("예산보다", out)          # 차이는 카드 아래 안내·카드가 말한다
        self.assertIn("시중에서는 보통 300만원대 이상으로 예상해요. 다만 지금 판매 중인 PC 중 이 조건에 맞는 것은"
                      " 아래 카드처럼 481만원부터예요.", out)
