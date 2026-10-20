"""/mvp4 AI 대화: 후속 질문마다 대화 기록이 첫 질문으로 올라가던 문제 (2026-10-20 사용자 신고).

원인: render() 가 화면을 통째로 다시 그려 .dc-chat-log 의 스크롤 위치가 0 으로 돌아갔다.
새 질문을 보냈을 때만 그 질문에 맞추고, 그 밖에는 읽던 위치를 지킨다.
"""
import pathlib
import unittest

CONV = pathlib.Path(__file__).resolve().parents[1] / 'mockups/mvp4/assets/js/design-conversation.js'


class ChatScrollTest(unittest.TestCase):
    def test_render_keeps_or_follows_scroll(self):
        s = CONV.read_text(encoding='utf-8')
        start = s.index('    function render() {\n      if (!root) return;')
        body = s[start:s.index('\n    }\n', start)]
        self.assertIn("keep = old ? { top: old.scrollTop", body)
        self.assertIn('users.length > keep.users', body)
        self.assertIn('log.scrollTop = keep.top', body)


if __name__ == '__main__':
    unittest.main()
