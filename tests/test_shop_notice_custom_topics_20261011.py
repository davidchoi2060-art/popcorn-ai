"""판매 안내 자료 — 관리자가 직접 더하는 주제 (2026-10-11 품질관리 · 개편 12번).

「인텔이 좋아요 AMD가 좋아요?」(고객3 F11) 같은 질문은 기본 주제 일곱 개 어디에도 걸리지 않아
AI 가 질문을 넘기고 용도만 되물었다. 관리자가 주제 · 낱말 · 안내를 더하면 그 안내로 답한다.

DB 없이 확인하는 것: 낱말 판정 · 말풍선 교체 · 문의 꼬리표 · 관리자 입력 검사 · 표 없을 때 건너뛰기 ·
마이그레이션 사슬. DB 를 거치는 저장은 로컬 Postgres 로 따로 확인했다(PR 본문).
"""
import contextlib
import importlib.util
import pathlib
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from api import admin_shop_notices as AS, talk, talk_rules as TR, talk_schema as TS, talk_answer as TA
from tests.test_talk_rules_20261010 import run_parse as _run_parse, vocab, _Conn
from tests.test_talk_honest_notices_20261011 import _ai

ROOT = pathlib.Path(__file__).resolve().parents[1]
CPU = {'label': 'CPU 고르기', 'keywords': ['인텔', 'AMD', '라이젠'],
       'body': '영상 편집은 인텔·AMD 모두 충분해요. 카드의 CPU 사양을 비교해 보세요.'}


def run_parse(text, ai_state, *, custom=(), **kw):
    with contextlib.ExitStack() as st:
        st.enter_context(patch.object(talk.shop_notices, 'load_written', lambda conn: {}))
        st.enter_context(patch.object(talk.shop_notices, 'load_custom', lambda conn: list(custom)))
        return _run_parse(text, ai_state, **kw)


class Matching(unittest.TestCase):
    def test_keyword_ignores_space_and_case(self):
        for q in ('CPU는 인텔이 좋아요 amd가 좋아요?', '라 이젠 괜찮나요', 'Amd 어때요'):
            with self.subTest(q=q):
                self.assertEqual(TR.custom_topic_hits(q, [CPU]), [CPU])

    def test_no_hit_and_one_letter_keyword_ignored(self):
        self.assertEqual(TR.custom_topic_hits('사무용 80만원', [CPU]), [])
        one = dict(CPU, keywords=['캠'])
        self.assertEqual(TR.custom_topic_hits('캠핑 가요', [one]), [])


class CustomerReply(unittest.TestCase):
    def test_question_answered_with_admin_notice(self):
        r = run_parse('영상 편집할 건데 CPU는 인텔이 좋아요 AMD가 좋아요?', {},
                      ai_reply='어떤 해상도로 편집하세요?', custom=[CPU])
        self.assertTrue(r['reply'].startswith(CPU['body']))
        self.assertTrue(r['pc_related'])

    def test_without_custom_topic_ai_reply_stays(self):
        r = run_parse('영상 편집할 건데 CPU는 인텔이 좋아요 AMD가 좋아요?', {},
                      ai_reply='어떤 해상도로 편집하세요?')
        self.assertNotIn(CPU['body'], r['reply'])

    def test_hit_records_topic_label(self):
        seen = {}
        ans = TA.AnswerResult(answer='', narrowing=TS.NARROWING_WIDE)
        with contextlib.ExitStack() as st:
            st.enter_context(patch.object(talk.engine, 'connect', lambda: _Conn()))
            st.enter_context(patch.object(talk.engine, 'begin', lambda: _Conn()))
            st.enter_context(patch.object(talk.access_gate, 'check_rate', lambda *a, **k: None))
            st.enter_context(patch.object(talk.TS, 'load_vocab', lambda conn: vocab()))
            st.enter_context(patch.object(talk.shop_notices, 'load_written', lambda conn: {}))
            st.enter_context(patch.object(talk.shop_notices, 'load_custom', lambda conn: [CPU]))
            st.enter_context(patch.object(talk.TA, 'run_parallel', lambda a, b: (_ai({}), ans)))
            st.enter_context(patch.object(talk.TA, 'is_game_related', lambda *a: False))
            st.enter_context(patch.object(talk, '_record_hit', lambda *a, **k: seen.update(k)))
            talk.parse_talk(talk.ParseBody(text='AMD 어때요'), request=None)
        self.assertIn(TR.TOPIC_TAG + 'CPU 고르기', seen['matched'])


class Loader(unittest.TestCase):
    def test_missing_table_is_skipped(self):
        class Broken:
            def execute(self, *a, **k):
                raise RuntimeError('relation "shop_notice_topics" does not exist')
        self.assertEqual(talk.shop_notices.load_custom(Broken()), [])


class AdminInput(unittest.TestCase):
    def clean(self, **kw):
        base = dict(label='CPU 고르기', keywords=['인텔', ' AMD ', 'amd', ''], body=' 안내 ', status='사용')
        base.update(kw)
        return AS._clean_custom(AS.CustomTopicBody(**base))

    def test_cleaned_and_deduplicated(self):
        self.assertEqual(self.clean(), ('CPU 고르기', ['인텔', 'AMD'], '안내', '사용'))

    def test_rejects(self):
        for kw in ({'label': ' '}, {'label': '가' * 41}, {'keywords': []}, {'keywords': ['캠']},
                   {'keywords': ['가' * 31]}, {'keywords': ['키%d' % i for i in range(21)]},
                   {'body': ''}, {'body': '가' * 401}, {'status': '보류'},
                   {'label': '할인'}, {'label': 'os'}):
            with self.subTest(kw=kw), self.assertRaises(HTTPException) as c:
                self.clean(**kw)
            self.assertEqual(c.exception.status_code, 400)

    def test_owner_only(self):
        with patch.object(AS, 'current_operator', lambda: {'role': 'operator'}):
            with self.assertRaises(HTTPException) as c:
                AS.add_custom(AS.CustomTopicBody(label='x', keywords=['인텔'], body='y'))
        self.assertEqual(c.exception.status_code, 403)


class Migration(unittest.TestCase):
    def test_revision(self):
        p = ROOT / 'db/migrations/versions/0150_shop_notice_topics.py'
        spec = importlib.util.spec_from_file_location('m0150', p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        self.assertEqual(m.revision, '0150')
        self.assertTrue(list((ROOT / 'db/migrations/versions').glob(m.down_revision + '_*.py')))


if __name__ == '__main__':
    unittest.main()
