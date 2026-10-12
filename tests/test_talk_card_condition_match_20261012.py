"""조건과 추천 PC 불일치 -- 2026-10-12 코덱스 24조합 검수 v2(용도 4 x 예산 6) 회귀 고정. 요청자 중헌 님.

  1번 영상편집 4K: 안내는 「4K 해상도 조건은 아직 추천에 반영하지 못해요」·「FHD 컷편집 기준」인데 카드는 「4K 편집·색보정·효과」
  2번 설명의 파워·그래픽카드·SSD·해상도가 아래 카드와 다름(고사양150 650W vs 600W · 고사양200 RTX 5070·750W·QHD vs 5060·600W·FHD)
  3번 「예산 안에서 가장 가까운 구성」·「60만원 이하 예산으로 구성을 준비해드리겠습니다」 아래 전부 예산 초과 카드
  4번 8600G 상품 카드 GPU 「AMD Radeon(내장 2CU)」
  5번 카드 CPU 12400/14400(상세·상품명은 12400F/14400F)

AI 문장은 검수 캡처(D:/WORK/코덱스-검수/2026-10-12-1935-조건추천일치-검수-v2/captures)의 실제 답을 그대로 쓴다.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from api import talk, talk_defaults as TD, talk_exceptions as TX, talk_pc_advice as PA, talk_rules as TR
from api import talk_answer as TA, talk_schema as TS
from api import sold_reco as SR


def _state(*usages, game=None):
    return SimpleNamespace(usages=list(usages), game=game, prefs=[], budget_won=1_000_000, budget_bound="이하")


def _card(gpu, ram, ssd, psu, price=1_624_400, level="FHD"):
    return {"price": price, "level": level, "usage_grid": "게임",
            "spec": {"cpu": "i5-12400F", "gpu": gpu, "ram_gb": ram, "ssd_gb": ssd, "psu": psu}}


HIGH150_CARDS = [_card("RTX 5060", 16, 500, "마이크로닉스 COOLMAX ELITE II 600W"),
                 _card("RTX 5060 Ti 8GB", 16, 500, "마이크로닉스 COOLMAX ELITE II 600W", 1_741_000)]
HIGH200_CARDS = HIGH150_CARDS[:1] + [_card("RTX 5060", 16, 512, "[마이크로닉스] Classic II 650W", 1_771_800),
                                     _card("RTX 5060 Ti 8GB", 32, 1000, "COOLMAX ELITE II 600W", 1_871_100)]
VIDEO_CARD = [{"price": 3_230_400, "level": "쾌적", "usage_grid": "영상편집",
               "spec": {"cpu": "코어 울트라7 265", "gpu": "RTX 5070", "ram_gb": 32, "ssd_gb": 1000, "vram_gb": 12,
                        "psu": "[마이크로닉스] Classic II 풀체인지 700W 80PLUS 실버 ATX3.1"}}]


class UhdNotice(unittest.TestCase):
    """1번 -- 영상편집은 추천이 4K 를 실제로 거르므로(sold_reco._uhd_rank) 「반영 못 함」이라 말하지 않는다."""

    TEXT = "프리미어로 4K 컷편집과 자막 작업을 할 영상편집용 새 PC를 찾습니다. 본체 예산은 100만원 이하입니다."

    def test_video_4k_is_applied_not_unsupported(self):
        notes = " ".join(TR.condition_notices(self.TEXT, _state("영상편집")))
        self.assertNotIn("반영하지 못해요", notes)
        self.assertIn("4K 해상도 조건으로 판매 중인 PC를 골라 볼게요", notes)
        self.assertEqual(TR.unsupported_conditions(self.TEXT, _state("영상편집")), [])

    def test_office_4k_still_unsupported(self):
        text = "사무용 PC에 4K 해상도 원해요. 예산 100만원"
        self.assertIn("4K 해상도", TR.unsupported_conditions(text, _state("사무·인강")))
        self.assertIn("반영하지 못해요", " ".join(TR.condition_notices(text, _state("사무·인강"))))

    def test_uhd_level_from_requirements(self):
        from api import reco_explore as X
        self.assertEqual(X.uhd_level("영상편집"), "쾌적")
        self.assertIsNone(X.uhd_level("사무용"))
        self.assertIsNone(X.uhd_level("게임"))

    def test_basis_line_uses_4k_level(self):
        seen = []

        def work_of(fit, level=None):
            seen.append((fit, level))
            return {"기본": "프리미어·다빈치 FHD 컷편집 (유튜브)", "쾌적": "4K 편집·색보정·효과"}[level or "기본"]

        st = TS.TalkState(usages=["영상편집"], budget_won=1_000_000)
        line = TD.answer_first(st, None, is_game_usage=TS.is_game_usage, work_of=work_of, uhd=True)
        self.assertEqual(line, "영상편집용은 4K 편집·색보정·효과 기준으로 봤어요.")
        self.assertNotIn("FHD", line)
        # 4K 를 말하지 않았으면 예전 그대로 1단계 + 끝 안내
        line = TD.answer_first(st, None, is_game_usage=TS.is_game_usage, work_of=work_of)
        self.assertIn("FHD 컷편집", line)


class CardSpecAlign(unittest.TestCase):
    """2번 -- 카드보다 높은 사양을 기본처럼 말한 문장은 걷고 실제 카드 사양 한 문장을 붙인다."""

    def test_high150_power_sentence(self):
        raw = ("배그와 롤을 함께 하는 용도라면 FHD 기준 중상급형, 라이젠 5급·코어 i5급 CPU와 RTX 5060급 그래픽카드 구성이 잘 맞아요. "
               "케이스의 RGB나 고급 외관, 저장장치 용량은 아껴도 되지만 파워는 안정적인 650W급 이상을 유지하는 것이 좋아요. "
               "QHD 고주사율로 배그를 즐기려면 RTX 5060 Ti급 이상과 그래픽카드 VRAM 8GB 이상을 고려하고, 방송·영상 편집이나 여러 "
               "프로그램을 함께 실행하면 램 32GB가 더 적합해요.")
        out, dropped = PA.align_card_specs(raw, HIGH150_CARDS, fhd_game=True)
        self.assertNotIn("650W", out)
        self.assertEqual([d["reason"] for d in dropped], ["card power"])
        self.assertIn("RTX 5060급 그래픽카드 구성이 잘 맞아요", out)
        self.assertIn("QHD 고주사율로", out)         # 「고려」로 말한 윗사양은 선택이라 남긴다
        self.assertTrue(out.endswith("아래 카드의 실제 구성은 그래픽 RTX 5060·RTX 5060 Ti 8GB, 램 16GB, SSD 500GB, 파워 600W예요."))

    def test_high200_gpu_ssd_qhd_power(self):
        raw = ("배그와 롤을 고사양으로 즐기려면 중상급형 CPU인 라이젠 5급·코어 i5급과 상급 그래픽카드인 RTX 5070급 구성이 적합해요. "
               "램은 16GB 이상, SSD는 QHD 게임 기준 960GB로 맞추면 최신 게임 설치와 로딩에 여유가 있어요. "
               "예산 안에서는 RGB 케이스나 고급 쿨러는 아끼고 그래픽카드와 파워에 우선 투자하는 것이 체감이 크며, 파워는 750W급을 고르는 편이 안정적이에요. "
               "FHD 위주라면 RTX 5060 Ti급으로 낮춰도 되고, 더 높은 주사율을 원하면 그래픽카드 등급을 유지하는 편이 좋아요.")
        out, dropped = PA.align_card_specs(raw, HIGH200_CARDS, fhd_game=True)
        for word in ("RTX 5070급", "750W", "QHD 게임 기준"):
            self.assertNotIn(word, out)
        self.assertEqual(sorted(d["reason"] for d in dropped), ["card gpu", "card power", "card resolution"])
        self.assertIn("FHD 위주라면 RTX 5060 Ti급", out)
        self.assertIn("램 16~32GB, SSD 500GB~1TB, 파워 600~650W예요.", out)

    def test_video_750w_vs_700w_and_matching_examples_kept(self):
        raw = ("프리미어 4K 컷편집과 자막 작업에는 중상급형 CPU인 라이젠 7급·코어 i7급과 상급형 그래픽카드인 RTX 5070급·RX 9070급 구성이 적합해요. "
               "램은 32GB 이상, SSD는 960GB 이상으로 구성하고, 그래픽 메모리는 12GB 이상을 선택하면 4K 타임라인과 자막 작업이 쾌적해요. "
               "파워는 그래픽카드에 맞춰 750W급 이상을 권장해요.")
        out, dropped = PA.align_card_specs(raw, VIDEO_CARD, fhd_game=False)
        self.assertIn("RTX 5070급·RX 9070급", out)   # 나란히 든 예시는 가장 낮은 것(5070)이 카드와 같다
        self.assertIn("SSD는 960GB 이상", out)        # 960GB <= 카드 1TB
        self.assertNotIn("750W", out)
        self.assertIn("4K", out)                      # 영상편집 4K 카드라 해상도 문장은 걷지 않는다
        self.assertEqual([d["reason"] for d in dropped], ["card power"])

    def test_old_generation_example_above_cards(self):
        raw = "중급형 CPU인 라이젠 5급과 보급형~중급형 그래픽카드인 RTX 4060급·RX 7600급 구성이 적합해요. 램은 16GB면 돼요."
        cards = [_card("RTX 3050 6GB", 16, 250, "500W", 1_194_500, "캐주얼")]
        out, dropped = PA.align_card_specs(raw, cards, fhd_game=True)
        self.assertNotIn("RTX 4060급", out)
        self.assertEqual(dropped[0]["reason"], "card gpu")

    def test_psu_name_without_w(self):
        # 실제 카드 129832 의 파워 이름 -- W 없이 적혀 있어도 750W 로 읽어야 「750W급」 문장을 잘못 걷지 않는다
        self.assertEqual(PA._psu_watt("쿨러마스터 MWE GOLD 750 V3 ATX3.1 블랙"), 750)
        self.assertEqual(PA._psu_watt("쿨러마스터 MWE 브론즈 650 V3 230V ATX3.1"), 650)
        self.assertEqual(PA._psu_watt("[마이크로닉스] Classic II 풀체인지 700W 80PLUS 실버 ATX3.1"), 700)
        self.assertIsNone(PA._psu_watt("정보 없음"))

    def test_no_cards_keeps_answer(self):
        raw = "파워는 750W급이 좋아요."
        self.assertEqual(PA.align_card_specs(raw, []), (raw, []))

    def test_card_sentence_skips_unknown_parts(self):
        self.assertEqual(PA.card_spec_sentence([{"spec": {"gpu": "인텔 UHD(내장)", "ram_gb": 16, "ssd_gb": 500}}]),
                         "아래 카드의 실제 구성은 그래픽 인텔 UHD(내장), 램 16GB, SSD 500GB예요.")
        self.assertEqual(PA.card_spec_sentence([{"spec": None}]), "")


ADVICE_HIGH150 = ("배그와 롤을 함께 하는 용도라면 FHD 기준 중상급형, 라이젠 5급·코어 i5급 CPU와 RTX 5060급 그래픽카드 구성이 잘 맞아요. "
                  "파워는 안정적인 650W급 이상을 유지하는 것이 좋아요.")


def _run(text, ai_state, ans, ai_reply):
    import contextlib
    import json
    obj = {"pc": True, "state": ai_state, "missing": [], "evidence": [], "reply": ai_reply}
    result = SimpleNamespace(text=json.dumps(obj, ensure_ascii=False), provider="t", model="t",
                             tokens_in=1, elapsed_sec=0.1)
    from tests.test_talk_rules_20261010 import _Conn, vocab
    with contextlib.ExitStack() as st:
        st.enter_context(patch.object(talk.engine, "connect", lambda: _Conn()))
        st.enter_context(patch.object(talk.engine, "begin", lambda: _Conn()))
        st.enter_context(patch.object(talk.access_gate, "check_rate", lambda *a, **k: None))
        st.enter_context(patch.object(talk.TS, "load_vocab", lambda conn: vocab()))
        st.enter_context(patch.object(talk.TA, "run_parallel", lambda a, b: (result, ans)))
        st.enter_context(patch.object(talk.TA, "is_game_related", lambda *a: False))
        st.enter_context(patch.object(talk, "_record_hit", lambda *a, **k: None))
        return talk.parse_talk(talk.ParseBody(text=text), request=None)


class ParseTurn(unittest.TestCase):
    """2·3번을 parse_talk 한 턴으로 -- 설명은 카드에 맞춰지고, AI 의 「예산으로 구성을 준비해드리겠습니다」는 나가지 않는다."""

    def _advice(self, text):
        ans = TA.AnswerResult(answer=ADVICE_HIGH150, narrowing=TS.NARROWING_WIDE)
        ans.kind, ans.topic = "pc_advice", PA.TOPIC_BUILD
        ans.filter_report = {"kept": 2, "replaced": [], "dropped": [], "gate_hit": False}
        return ans

    def test_reply_promise_dropped_and_answer_aligned(self):
        text = "롤과 발로란트를 FHD로 할 게임용 새 PC를 찾습니다. 본체 예산은 150만원 이하입니다."
        state = {"usages": ["게임"], "budget_won": 1_500_000,
                 "game": {"names": ["리그 오브 레전드", "발로란트"], "resolution": "1080p"}}
        ans = self._advice(text)
        with patch("api.grid_public.sold_card_items", lambda s, t=None: HIGH150_CARDS):
            r = _run(text, state, ans, "롤과 발로란트를 FHD 해상도로 즐기실 PC를 찾으시는군요. 본체 150만원 이하 예산으로 구성을 준비해드리겠습니다.")
        self.assertNotIn("준비해드리겠습니다", r["reply"])
        self.assertNotIn("650W", r["answer"])
        self.assertIn("아래 카드의 실제 구성은", r["answer"])
        self.assertIn("card power", [d["reason"] for d in r["answer_filter"]["dropped"]])

    def test_card_lookup_failure_keeps_answer(self):
        text = "롤과 발로란트를 FHD로 할 게임용 새 PC를 찾습니다. 본체 예산은 150만원 이하입니다."
        state = {"usages": ["게임"], "budget_won": 1_500_000,
                 "game": {"names": ["리그 오브 레전드", "발로란트"], "resolution": "1080p"}}

        def boom(*a, **k):
            raise RuntimeError("db down")
        with patch("api.grid_public.sold_card_items", boom):
            r = _run(text, state, self._advice(text), "")
        self.assertEqual(r["answer"], ADVICE_HIGH150)


class BudgetPromise(unittest.TestCase):
    """3번 -- 예산 안 카드가 없을 수도 있는데 「예산 안에서 가장 가까운 구성」을 약속하지 않는다."""

    def test_contradiction_note_has_no_within_budget_promise(self):
        self.assertNotIn("예산 안에서 가장 가까운", TX.NOTE_CONTRADICTION)
        self.assertIn("예산 안에 맞는 PC가 없으면 그렇다고 알려 드리고", TX.NOTE_CONTRADICTION)


class CardLabels(unittest.TestCase):
    """4·5번 -- 카드 CPU·GPU 이름을 상품명·CPU 모델에 맞춘다."""

    def test_cpu_suffix_from_product_name(self):
        cases = [("i5-12400", "골드 NO.04.93454  RTX 3050 [12400F/16G/250GB/RTX3050]", "i5-12400F"),
                 ("i5-14400", "견적왕 추천PC NO.04.129823 [14400F/32G/1TB/RTX5060Ti]", "i5-14400F"),
                 ("i5-12400", "오피스 NO.04.113836 초슬림/미니타워[12400/16G/500G/UHD 730]", "i5-12400"),
                 ("코어 울트라7 265", "다이아 NO.05.127317 [인텔 15세대 애로우레이크][265/32G/1TB/RTX5070]", "코어 울트라7 265"),
                 ("라이젠5 7500F", "견적왕 추천PC NO.04.129804 [7500F/16G/500GB/RTX5060]", "라이젠5 7500F"),
                 ("코어 울트라7 265K", "[265KF/32G/1TB/RTX5070]", "코어 울트라7 265KF")]
        for cpu, name, want in cases:
            with self.subTest(name=name):
                self.assertEqual(SR.cpu_label(cpu, name), want)

    def test_apu_igpu_label(self):
        self.assertEqual(SR.gpu_label("AMD Radeon(내장 2CU)", "라이젠5 8600G"), "Radeon 760M(내장)")
        self.assertEqual(SR.gpu_label("AMD Radeon(내장 2CU)", "라이젠5 7600X"), "AMD Radeon(내장 2CU)")
        self.assertEqual(SR.gpu_label("RTX 5060", "라이젠5 8600G"), "RTX 5060")

    def test_card_spec_applies_both(self):
        p = {"name": "오피스 NO.03.120221 초슬림/미니타워[8600G/16G/500G/Radeon 7]",
             "spec": {"cpu": "라이젠5 8600G", "gpu": "AMD Radeon(내장 2CU)", "ram_gb": 16, "ssd_gb": 500,
                      "cpu_mt": 16000, "gpu_idx": 5},
             "case_psu": {"psu": "[마이크로닉스] COOLMAX VISION II 500W"}}
        spec = SR.card_spec(p)
        self.assertEqual(spec["gpu"], "Radeon 760M(내장)")
        self.assertNotIn("gpu_idx", spec)
        self.assertEqual(p["spec"]["gpu"], "AMD Radeon(내장 2CU)")   # 원천(평가 스냅샷)은 그대로 둔다
        q = {"name": "[12400F/16GB/500GB/RTX5060]", "spec": {"cpu": "i5-12400", "gpu": "RTX 5060"}}
        self.assertEqual(SR.card_spec(q)["cpu"], "i5-12400F")


if __name__ == "__main__":
    unittest.main()
