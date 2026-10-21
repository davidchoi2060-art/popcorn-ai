"""검수 F1~F4 (2026-10-21 구매·비교·견적 독립 검수).

F1 다른 화면을 다녀와도 대화·작성 중 질문·조건·비교·선택이 남는다(이 탭 sessionStorage, 「새 대화」만 비운다).
F2 「이미 저장」은 지금 내 견적 목록에 그 견적이 있을 때만 말한다. 지워졌으면 새 요청 번호로 다시 보관한다.
F3 비교 화면에서 뺀 상품은 대화의 관심·비교상품에서도 빠진다.
F4 모바일 견적 카드의 「삭제」 글자와 수량은 한 줄로 둔다.
"""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1] / "mockups/mvp4"
JS = ROOT / "assets/js"


def src(name):
    return (JS / name).read_text(encoding="utf-8")


class F1Keep(unittest.TestCase):
    def test_chat_state_kept_per_tab(self):
        s = src("design-conversation.js")
        self.assertIn("KEEP = 'pai-finder-chat-v1'", s)
        for k in ("'draft'", "'conditions'", "'compare'", "'log'", "'convo'"):
            self.assertIn(k, s[s.index("SAVED = ["):s.index("restoredScroll = null;")])
        self.assertIn("window.sessionStorage.setItem(KEEP", s)
        self.assertNotIn("localStorage.setItem(KEEP", s)   # 다른 탭·다음 방문으로 새지 않는다
        self.assertIn("root.innerHTML = markup();\n      remember(false);", s)
        self.assertIn("remember(true); stop();", s)

    def test_new_conversation_clears(self):
        s = src("design-conversation.js")
        fn = s[s.index("if (action === 'new')"):]
        fn = fn[:fn.index("\n")]
        self.assertIn("model.draft = ''", fn)
        self.assertIn("model.compare = []", fn)
        self.assertIn("render()", fn)   # render 가 빈 상태를 보관한다


class F2Resave(unittest.TestCase):
    def test_already_saved_checks_the_list(self):
        s = src("supercomputer-detail.js")
        fn = s[s.index("  function save(btn) {"):s.index("  function compare() {")]
        self.assertIn("P.savedQuotes.list()", fn)
        self.assertIn("x.id === saved[key]", fn)
        self.assertIn("delete saveIds[key]", fn)   # 지워졌으면 새 요청 번호
        self.assertLess(fn.index("P.savedQuotes.list()"), fn.index("이미 내 견적에 저장한 구성이에요"))


class F3Sync(unittest.TestCase):
    def test_compare_screen_removal_reaches_chat(self):
        s = src("design-conversation.js")
        self.assertIn("function forget(id, kind)", s)
        self.assertIn("forget(node.dataset.dcRemove, node.dataset.dcKind || 'pc')", s)


class F4Label(unittest.TestCase):
    def test_delete_label_one_line(self):
        css = (ROOT / "assets/css/purchase-controls.css").read_text(encoding="utf-8")
        self.assertIn(".ds-saved-delete{flex:none;white-space:nowrap;", css)
        self.assertIn(".ds-saved-card .ds-price-line b{white-space:nowrap}", css)


if __name__ == "__main__":
    unittest.main()
