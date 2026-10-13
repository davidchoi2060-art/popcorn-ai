"""상담 답 품질 비교(일반 AI 대비) «못함» 12건 대응 -- 2026-10-13 main 3afe597 배포 뒤 결과(못함 12 · 나음 8).

  R05·R07·R20·E31  설명이 한 덩어리 문장이라 일반 AI(용도별 목록)보다 덜 구체적 -> 짧은 목록·줄바꿈을 살린다(700자 -> 1000자)
  R01·R03·E11       예산이 판매 카드 최저가보다 낮으면 «그 돈이면 무엇이 되는지»가 곧 답 -> 시세·예산 문장을 지우지 않고
                    「다만 판매 PC는 ○만원부터」를 붙인다(예산 안 낮은 등급 카드는 내지 않는다 -- 2026-10-09 배그 150만원 실사고)
  E16·E26           긴 글·예산과 사양이 안 맞는 말에 설명이 비었다 -> 설명을 남긴다
  E16               「150만원으로 맞춰 드리겠습니다」 AI 약속 -> 걷는다
  R04               설명을 못 받은 턴에 카드는 나가는데 AI 가 되묻기만 -> 기준 줄로 마무리
  R12·R13           구매 절차 답이 정책을 단정하거나 같은 확인 문장을 두 번 -> 프롬프트
"""
import unittest

from api import talk, talk_pc_advice as PA, talk_rules as TR


class ListsSurvive(unittest.TestCase):
    RAW = ("16GB면 대부분 충분해요.\n"
           "- 웹서핑·문서·일반 게임: 16GB\n"
           "- 4K 영상 편집·가상 머신 여러 개: 32GB\n"
           "\n"
           "오래 쓸 생각이면 32GB가 여유로워요.")

    def test_clean_keeps_lines_and_bullets(self):
        body, dropped = PA.clean(self.RAW, PA.TOPIC_PART, "램 16기가면 충분해요 아니면 32기가 사야 돼요?")
        self.assertEqual(body, self.RAW)
        self.assertEqual(dropped, [])

    def test_bullet_without_period_is_not_cut(self):
        body, dropped = PA.clean("기준은 이래요.\n- 사무: 8GB\n- 게임: 16GB", PA.TOPIC_PART, "램 얼마나")
        self.assertTrue(body.endswith("- 게임: 16GB"))
        self.assertFalse([d for d in dropped if d["reason"] == "cut"])

    def test_numbered_list_becomes_dash(self):
        body, _ = PA.clean("두 가지예요.\n1. 용도를 정해요.\n2) 예산을 정해요.", PA.TOPIC_PART, "고르는 법")
        self.assertEqual(body.splitlines()[1:], ["- 용도를 정해요.", "- 예산을 정해요."])

    def test_dropped_sentence_inside_list_keeps_other_lines(self):
        raw = "정리하면 이래요.\n- 게임: RTX 5060급\n- 저희 가게에서 140만원에 팔아요.\n- 사무: 내장 그래픽"
        body, dropped = PA.clean(raw, PA.TOPIC_BUILD, "PC 추천")
        self.assertEqual(body.splitlines(), ["정리하면 이래요.", "- 게임: RTX 5060급", "- 사무: 내장 그래픽"])
        self.assertEqual(dropped[0]["reason"], "price")

    def test_card_spec_align_keeps_lines(self):
        cards = [{"spec": {"gpu": "RTX 5060", "ram_gb": 16, "ssd_gb": 500, "psu": "600W"}, "price": 1_624_400}]
        out, dropped = PA.align_card_specs("요약이에요.\n- 그래픽: RTX 5060급\n- 파워: 750W급 권장", cards, fhd_game=True)
        self.assertEqual(out.splitlines()[:2], ["요약이에요.", "- 그래픽: RTX 5060급"])
        self.assertNotIn("750W", out)
        self.assertTrue(out.splitlines()[-1].startswith("아래 카드의 실제 구성은"))

    def test_prompt_allows_short_lists(self):
        p = PA.build_prompt("램 16 vs 32", [], topic=PA.TOPIC_PART)
        self.assertIn("「- 」로 시작하는 짧은 목록", p)
        self.assertIn("첫 문장에서 질문에 바로 답한다", p)
        self.assertEqual(PA.ADVICE_MAX_LEN, 1000)


class BudgetBelowCards(unittest.TestCase):
    def test_budget_sentence_kept_when_cards_over_budget(self):
        raw = "50만원이면 사무용으로 충분히 맞출 수 있어요. 램은 8GB면 돼요."
        body, _ = PA.clean(raw, PA.TOPIC_BUILD, "사무용 컴퓨터 50만원 정도로 맞출 수 있어요?")
        self.assertIn("50만원이면", body)                      # 예전에는 가격 문장으로 걷혔다
        out = PA.align_market_price(body, [593_400, 626_100], budget_won=500_000,
                                    sentence="사무용 컴퓨터 50만원 정도로 맞출 수 있어요?")
        self.assertIn("50만원이면 사무용으로 충분히 맞출 수 있어요.", out)
        self.assertIn("다만 지금 판매 중인 PC 중 이 조건에 맞는 것은 아래 카드처럼 59만원부터예요.", out)

    def test_market_sentence_kept_with_from_price_when_over_budget(self):
        raw = "시중에서는 보통 130만~150만원대면 RTX 5060급 구성이 가능해요. 램은 16GB면 돼요."
        out = PA.align_market_price(raw, [1_624_400, 1_741_000], budget_won=1_500_000, sentence="배그 150만원")
        self.assertIn("시중에서는 보통", out)
        self.assertIn("이 조건에 맞는 것은 아래 카드처럼 162만원부터예요", out)
        self.assertNotIn(PA.NOTE_MARKET, out)

    def test_within_budget_still_replaced_by_card_range(self):
        raw = "시중에서는 보통 100만원대예요. 램은 16GB면 돼요."
        out = PA.align_market_price(raw, [1_199_600], budget_won=1_500_000, sentence="게임 150만원")
        self.assertEqual(out, "지금 이 조건에 맞는 판매 중인 PC는 아래 카드처럼 120만원 정도예요. 램은 16GB면 돼요.")

    def test_no_market_sentence_gets_from_price_line(self):
        out = PA.align_market_price("램은 16GB면 돼요.", [1_624_400], budget_won=1_500_000, sentence="150만원")
        self.assertTrue(out.endswith("이 조건에 맞는 것은 아래 카드처럼 162만원부터예요."))


class ReplyPromises(unittest.TestCase):
    def test_budget_promise_dropped(self):
        self.assertEqual(TR.drop_budget_promise("다양한 게임을 즐기셨군요. 150만원으로 맞춰 드리겠습니다."),
                         "다양한 게임을 즐기셨군요.")
        self.assertEqual(TR.drop_budget_promise("FHD 게임 PC를 찾으시는군요. 예산 60만원 이하의 게임 PC를 찾겠습니다."),
                         "FHD 게임 PC를 찾으시는군요.")

    def test_conditional_ask_and_facts_kept(self):
        for t in ("예산을 알려 주시면 찾아 드릴게요.", "100만원 예산이면 충분해요.", "게임은 FHD 기준으로 봤어요."):
            self.assertEqual(TR.drop_budget_promise(t), t)

    def test_only_sentence_kept(self):
        self.assertEqual(TR.drop_budget_promise("90만원으로 찾아볼게요."), "90만원으로 찾아볼게요.")


class AdviceInExceptionTurns(unittest.TestCase):
    def test_contradiction_and_too_long_keep_advice(self):
        self.assertEqual(talk.ADVICE_OK_EXCEPTIONS, frozenset({"contradiction", "too_long"}))
        src = open(talk.__file__, encoding="utf-8").read()
        self.assertIn("- ADVICE_OK_EXCEPTIONS", src)
        self.assertIn('or "?" in reply', src)                 # R04: 카드가 나가는 턴의 되묻기 -> 기준 줄
        self.assertIn("TR.drop_budget_promise(reply)", src)
        self.assertIn("for note in (TX.NOTE_CONTRADICTION, TX.NOTE_LOW_BUDGET):", src)   # E26: 설명이 있으면 모순 안내 생략


if __name__ == "__main__":
    unittest.main()
