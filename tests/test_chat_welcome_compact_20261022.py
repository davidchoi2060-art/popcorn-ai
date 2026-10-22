"""AI로 PC 찾기 첫 질문 화면 정리 (2026-10-22 대표 승인 「AI 이미지 줄이고 용도 버튼 넓혀서 글자 안 깨지게, 입력창까지 한눈에 보이게」)."""
import pathlib
import unittest

MVP4 = pathlib.Path(__file__).resolve().parents[1] / 'mockups/mvp4'


class WelcomeCompact(unittest.TestCase):
    def setUp(self):
        self.js = (MVP4 / 'assets/js/design-conversation.js').read_text(encoding='utf-8')
        self.cobalt = (MVP4 / 'assets/css/finder-cobalt.css').read_text(encoding='utf-8')

    def test_labels_and_hint(self):
        for label in ('<b>게임용 PC</b>', '<b>영상편집용 PC</b>', '<b>사무·업무용 PC</b>'):
            self.assertIn(label, self.js)
        self.assertEqual(self.js.count('<small class="dc-prompt-hint">이 용도로 질문하기</small>'), 3)
        self.assertNotIn('질문에 담기', self.js)

    def test_button_only_fills_draft(self):
        # 버튼은 입력창에 넣고 초점만 옮긴다 — 자동 전송 없음.
        line = next(l for l in self.js.splitlines() if "hasAttribute('data-dc-draft')" in l)
        self.assertIn("root.querySelector('textarea').focus(); return;", line)
        self.assertNotIn('send(', line)

    def test_welcome_box_fits_content_and_words_stay_whole(self):
        self.assertIn("' is-welcome'", self.js)
        self.assertIn('.dc-chat-main.is-welcome{height:auto;min-height:0}', self.cobalt)
        self.assertIn('word-break:keep-all', self.cobalt)
        self.assertIn('@container (max-width:440px)', self.cobalt)


if __name__ == '__main__':
    unittest.main()
