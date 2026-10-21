"""찜하기·찜목록 1번 시안 (2026-10-21 대표 확정 01~04).

01 추천 카드는 찜하기·자세히 보기, 찜목록 보기(N)·하단 「찜목록에서 N개 살펴보기」.
02 찜목록은 체크 0개에서 시작, 비교는 2~3개, 4번째 체크는 막고 앞의 3개를 둔다. 찜 해제는 목록 삭제(되돌리기 잠깐).
03 성능 비교는 공개 용도 기준표·CPU 코어만 쓰고 「팝콘 기준 · 실측 아님」을 밝힌다. 속도·FPS·% 를 지어내지 않는다.
04 상세는 구매 버튼 아래에 찜 줄을 두고, 비교에서 온 경우에만 「비교 결과로 돌아가기」·단계 표시를 둔다.
찜·비교는 서버 쓰기·AI 호출을 하지 않는다.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1] / "mockups/mvp4"
JS = ROOT / "assets/js"


def src(name):
    return (JS / name).read_text(encoding="utf-8")


class Wishlist(unittest.TestCase):
    def test_pick_rules(self):
        s = src("wishlist-compare.js")
        self.assertIn("MAX = 3", s)
        self.assertIn("비교는 한 번에 3개까지 고를 수 있어요. 앞서 고른 3개는 그대로 두었어요.", s)
        self.assertIn("var all = n >= 2 && n <= MAX && list.every(pickable);", s)   # 전체 선택은 2~3개일 때만
        self.assertIn("sessionStorage", s)   # 이번 비교 체크는 찜(목록)과 따로 둔다

    def test_compare_is_honest(self):
        s = src("wishlist-compare.js")
        self.assertIn("실측 아님", s)
        self.assertIn("코어 수 차이가 그대로 속도 차이는 아니며", s)
        code = re.sub(r"//[^\n]*|/\*.*?\*/", "", s, flags=re.S)
        self.assertNotIn("FPS", code)
        self.assertIsNone(re.search(r"\d+%", code))
        self.assertIn("확인 불가", s)

    def test_no_server_writes_or_ai(self):
        for name in ("wish-store.js", "wish-ui.js", "wishlist-compare.js"):
            s = src(name)
            for banned in ("fetch(", "XMLHttpRequest", "liveTalk", "savedQuotes", "method: 'POST'"):
                self.assertNotIn(banned, s, name)

    def test_ask_returns_to_chat_without_sending(self):
        c = src("design-conversation.js")
        self.assertIn("param(ctx, 'ask')", c)
        fn = c[c.index("if (action === 'ask-insert')"):]
        fn = fn[:fn.index("\n        }") if "\n        }" in fn else 400]
        self.assertNotIn("send(", fn)
        self.assertNotIn("model.selected", fn)   # 질문 대상을 덮지 않는다


class Detail(unittest.TestCase):
    def test_wish_row_under_buy_and_back_by_entry(self):
        s = src("live-cards.js")
        self.assertIn("cf-wish-row", s)
        self.assertIn("다시 누르면 찜이 해제돼요.", s)
        self.assertIn("P.wishSteps", s)

    def test_pages_load_wish_assets(self):
        for page in ("index.html", "review-flows.html", "supercomputer.html", "ai-service.html"):
            html = (ROOT / page).read_text(encoding="utf-8")
            for a in ("wish-store.js?v=20261021-wish1", "wish-ui.js?v=20261021-wish1", "wishlist.css?v=20261021-wish1"):
                self.assertIn(a, html, page)
            self.assertLess(html.index("wish-store.js"), html.index("wish-ui.js"), page)
        for page in ("index.html", "review-flows.html"):
            html = (ROOT / page).read_text(encoding="utf-8")
            self.assertLess(html.index("design-conversation.js"), html.index("wishlist-compare.js"), page)


if __name__ == "__main__":
    unittest.main()
