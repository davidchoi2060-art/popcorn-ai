"""2026-10-08 대표 지시: 고객 상담 문구 다섯 개를 고객 노출에서 뺀다(대체 문구 없음).

근거 수집(DB·위키)은 그대로 돌아야 하고, 수집한 근거에 고객용 라벨이 붙지 않아야 한다.
"""
import unittest
from pathlib import Path
from unittest import mock

from api import talk_answer as TA

ROOT = Path(__file__).resolve().parents[1]
REMOVED = (
    '저희 자료에 없는 내용이라 잠깐 찾아볼게요. 조금만 기다려 주세요.',
    '우리 자료',
    '저희가 정리해 둔 자료예요.',
    '찾아본 자료',
    '저희 자료엔 없어서 방금 찾아봤어요',
)
CUSTOMER_FILES = ('api/talk.py', 'api/talk_answer.py', 'mockups/mvp3/app.js',
                  'mockups/mvp3/live-flow.js', 'mockups/mvp3/live-model.js',
                  'mockups/mvp3/index.html', 'mockups/mvp2/app.js', 'mockups/mvp2/index.html')


class CopyRemovedTests(unittest.TestCase):
    def test_phrases_absent_from_customer_paths(self):
        for rel in CUSTOMER_FILES:
            src = (ROOT / rel).read_text(encoding='utf-8')
            for phrase in REMOVED:
                with self.subTest(file=rel, phrase=phrase):
                    self.assertNotIn(phrase, src)

    def test_evidence_still_collected_without_customer_labels(self):
        facts = [TA.GameFacts(name='테스트게임', genre='FPS')]
        wiki = mock.Mock(ok=True, url='https://ko.wikipedia.org/wiki/x', extract='본문 ' * 50)
        with mock.patch.object(TA, 'extract_game_names', return_value=['테스트게임']), \
             mock.patch.object(TA, 'match_genres', return_value=[]), \
             mock.patch.object(TA, 'load_game_facts', return_value=facts), \
             mock.patch.object(TA.WF, 'fetch_game', return_value=wiki) as fetch:
            ev = TA.collect_evidence(None, '테스트게임 어때요', None)
        fetch.assert_called_once_with('테스트게임')
        self.assertTrue(ev.used_web)
        self.assertTrue(ev.db_lines and ev.web_lines)
        self.assertEqual(ev.sources, [{'kind': 'own'},
                                      {'kind': 'web', 'url': 'https://ko.wikipedia.org/wiki/x'}])

    def test_answer_result_has_no_notice_by_default(self):
        self.assertIsNone(TA.AnswerResult().notice)
        self.assertFalse(hasattr(TA, 'NOTICE_WEB') or hasattr(TA, 'SOURCE_OWN') or hasattr(TA, 'SOURCE_WEB'))


if __name__ == '__main__':
    unittest.main()
