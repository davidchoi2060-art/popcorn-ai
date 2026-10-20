"""/mvp4 상품 유형별 구매 경로 분리 (2026-10-20 대표 승인 「개발PM에게 복구 요청까지 전달」).

일반 완제조립PC·완성 제품(PC 카탈로그 상품) -> 그 상품의 팝콘PC몰 페이지에서 구매. 견적 보관·구매 상담 CTA 와
연락처 입력을 구매 앞에 두지 않고, 직접 주소(save·quote·consult + id/quote)로 들어와도 같은 몰 구매 안내로 간다.
AI 패키지·AI 슈퍼컴퓨터의 견적 문의·도입 상담은 각자의 전용 화면에 그대로 둔다. 기존 보관 기록은 「내 견적」에 남긴다.
"""
import json
import pathlib
import re
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
JS = ROOT / "mockups/mvp4/assets/js"


def src(name):
    return (JS / name).read_text(encoding="utf-8")


def mall_url(product):
    s = src("live-catalog.js")
    fn = s[s.index("  P.mallBuyUrl = function"):s.index("  P.mallBuyLink = function")]
    code = "var P={};" + fn + ";console.log(JSON.stringify(P.mallBuyUrl(" + json.dumps(product) + ")))"
    return json.loads(subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout)


class MallUrl(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node 없음")
    def test_only_the_same_products_mall_page(self):
        good = "https://www.popcornpc.co.kr/shop/system_detail.html?pd_no=113835"
        self.assertEqual(mall_url({"id": "113835", "mallUrl": good}), good)
        for bad in ("https://www.popcornpc.co.kr/shop/system_detail.html?pd_no=113836",   # 다른 상품
                    "https://www.popcornpc.co.kr/", "https://www.popcornpc.co.kr/shop/search.html?q=113835",
                    "http://www.popcornpc.co.kr/shop/system_detail.html?pd_no=113835",
                    "https://evil.example/shop/system_detail.html?pd_no=113835", "not a url"):
            self.assertEqual(mall_url({"id": "113835", "mallUrl": bad}), "", bad)
        self.assertEqual(mall_url({"id": "113835", "mallUrl": None}), "")


class OrdinaryPurchase(unittest.TestCase):
    def test_detail_purchase_is_mall_only(self):
        s = src("configuration-concept.js")
        part = s[s.index("  function purchase(p, q)"):s.index("  function render(p, q, state)")]
        self.assertIn("P.mallBuyLink(p, 'btn btn-primary cf-mall-buy'", part)
        for gone in ("견적 보관하기", "구매 상담 신청", "data-cf-action=\"save\"", "data-cf-action=\"consult\"", "route('save'", "route('consult'"):
            self.assertNotIn(gone, part)
        self.assertIn("구매 전에 견적 보관이나 연락처 입력은 필요 없습니다.", part)

    def test_answer_cards_selection_compare_link_the_mall(self):
        self.assertIn("type === 'pc' && p && P.mallBuyLink ? P.mallBuyLink(p, 'pa-mall-buy'", src("chat-answer.js"))
        c = src("design-conversation.js")
        self.assertEqual(c.count("buyButton("), 4)                          # 정의 + 선택 + 비교 + 사람 상담 옆
        self.assertIn("P.mallBuyLink(p, 'dc-mall-buy'", c)                  # 오른쪽 추천 카드
        self.assertNotIn("선택 상품 견적 확인", c)
        self.assertNotIn("'consult', 'normal', { id:", c)                    # 일반 PC 를 상품 상담으로 넘기지 않는다
        self.assertNotIn("buttonLink('사람 상담 신청하기', 'consult', 'normal', model.selected", c)

    def test_direct_save_quote_consult_entry_goes_to_mall(self):
        s = src("live-checkout.js")
        for screen in ("quote", "save"):
            body = s[s.index("P.designScreens." + screen + " = function"):]
            body = body[:body.index("\n  };")]
            self.assertIn("mallOnly(p)", body, screen)
            self.assertNotIn("POST", body, screen)
        consult = s[s.index("P.designScreens.consult = function"):]
        self.assertIn("if (p) return", consult)
        self.assertIn("if (quoteId) return", consult)
        self.assertNotIn("purchase-inquiries/from-quote", s)                # 보관 견적 -> 구매 상담 접수 경로 없음
        self.assertNotIn("POST', '/api/mvp3/saved-quotes'", s)              # 새 보관(연락처 수집) 없음
        self.assertNotIn("'구매 상담 신청', 'consult'", s)
        self.assertNotIn("이 견적으로 구매 상담 신청", s)

    def test_saved_records_and_option_link_stay(self):
        s = src("live-checkout.js")
        self.assertIn("call('GET', '/api/mvp3/saved-quotes?limit=20'", s)  # 기존 보관 기록 조회는 그대로
        self.assertIn("buy(live, '팝콘PC몰에서 구매하기')", s)
        self.assertIn("mallLink(p, '팝콘PC에서 부품 변경하기')", s)
        self.assertIn("팝콘PC에서 부품 옵션 변경하기", src("live-cards.js"))


class AiFlowsUntouched(unittest.TestCase):
    def test_ai_package_and_supercomputer_keep_their_own_inquiry(self):
        self.assertIn("ai-consult.html?package=", src("ai.js"))
        d = src("supercomputer-detail.js")
        self.assertIn("data-sc-action=\"quote\"", d)
        self.assertIn("장비 견적 문의", d)
        self.assertIn("qs.get('intent') === 'adoption' ? 'adoption' : 'quote'", src("supercomputer-inquiry.js"))
        self.assertIn("supercomputer.html?id=", src("chat-answer.js"))
        self.assertNotIn("mallBuy", src("supercomputer-detail.js") + src("ai-inquiry.js") + src("supercomputer-inquiry.js"))


class Assets(unittest.TestCase):
    def test_pages_load_new_versions(self):
        for page in ("index.html", "review-flows.html"):
            t = (ROOT / "mockups/mvp4" / page).read_text(encoding="utf-8")
            for a in ("configuration-concept.js?v=20261021-acc2", "chat-answer.js?v=20261020-buy1", "design-conversation.js?v=20261020-buy1",
                      "live-catalog.js?v=20261020-buy1", "live-checkout.js?v=20261020-buy1"):
                self.assertIn(a, t, page)


if __name__ == "__main__":
    unittest.main()
