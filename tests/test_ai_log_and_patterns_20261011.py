"""AI 응답 기록 · 응답 패턴 · 목록 밖 게임 추정 — 2026-10-11 품질관리 F4·F7·F9·F10 회귀 고정."""
import unittest

from api import admin_ai_logs, admin_game_grades as GG, admin_talk_patterns as TP, admin_talk_review as TRV


class _Res:
    def __init__(self, scalar=0, rows=None, one=None):
        self._s, self._rows, self._one = scalar, rows or [], one

    def scalar(self): return self._s
    def scalar_one(self): return self._s
    def mappings(self): return self
    def all(self): return self._rows
    def one(self): return self._one


class _Conn:
    def __init__(self, answer):
        self.sql, self.answer = [], answer

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execution_options(self, **k): return self

    def execute(self, stmt, params=None):
        q = str(stmt)
        self.sql.append(q)
        return self.answer(q)


class _Engine:
    def __init__(self, conn): self.conn = conn
    def connect(self): return self.conn


def _swap(mod, conn):
    orig = mod.engine
    mod.engine = _Engine(conn)
    return lambda: setattr(mod, 'engine', orig)


class AiResponseLog(unittest.TestCase):
    def test_customer_ai_calls_are_counted_not_denied(self):
        def answer(q):
            if 'llm_called' in q: return _Res(11)
            if 'talk_reply_reviews' in q: return _Res(5)
            return _Res(0)
        undo = _swap(admin_ai_logs, _Conn(answer))
        try:
            d = admin_ai_logs.get_ai_response_log()
        finally:
            undo()
        r = next(x for x in d['reasons'] if x['key'] == 'llm_calls')
        self.assertNotIn('호출 경로 없음', r['chip'])
        self.assertIn('11건', r['measured'])
        self.assertIn('5건', r['measured'])
        self.assertEqual(r['link'], '/admin2/talk-review')
        self.assertNotIn('연동 보류', r['why'])
        self.assertIn('AI 답 점검', d['note'])

    def test_template_no_longer_claims_no_path(self):
        html = open('templates/admin/ai_response_log.html.j2', encoding='utf-8').read()
        self.assertNotIn('그레프 실측 0건', html)
        self.assertNotIn('감사할 대상이 아직 생성되지 않습니다', html)
        self.assertIn('reason-link', html)


class PatternQueue(unittest.TestCase):
    def test_asked_back_is_out_of_unanswered_queue(self):
        self.assertIn(TP.NOTHING_READ, TP.UNANSWERED)
        self.assertIn('AND NOT EXISTS', TP.UNANSWERED)
        self.assertIn(TP.NOTHING_READ, TP.ASKED_BACK)
        self.assertNotIn('NOT EXISTS', TP.ASKED_BACK)
        self.assertIn('shown_reply', TP.ASKED_BACK)

    def test_queue_reports_asked_back_with_review_link(self):
        def answer(q):
            if 'GROUP BY' in q: return _Res(rows=[])
            if 'AND NOT EXISTS' in q: return _Res(3)
            return _Res(7)
        conn = _Conn(answer)
        undo = _swap(TP, conn)
        try:
            d = TP.queue()
        finally:
            undo()
        self.assertEqual(d['total_hits'], 3)
        self.assertEqual(d['asked_back'], 7)
        self.assertEqual(d['review_link'], '/admin2/talk-review?unread=1')

    def test_review_unread_filter_uses_same_definition(self):
        seen = []

        def answer(q):
            seen.append(q)
            if 'AS logged' in q: return _Res(one={'logged': 0})
            if 'jsonb_array_elements_text' in q: return _Res(rows=[])
            return _Res(0, rows=[])
        undo = _swap(TRV, _Conn(answer))
        orig = TRV.current_operator
        TRV.current_operator = lambda: {'role': 'owner', 'operator_id': 1}
        try:
            d = TRV.list_reviews(unread=True, flagged=False)
        finally:
            undo(); TRV.current_operator = orig
        self.assertTrue(d['unread'])
        self.assertTrue(any(TP.NOTHING_READ in q for q in seen))

    def test_screens_link_queue_and_review(self):
        tp = open('templates/admin/talk_patterns.html.j2', encoding='utf-8').read()
        tr = open('templates/admin/talk_review.html.j2', encoding='utf-8').read()
        self.assertIn('tp-askedback', tp)
        self.assertIn('trUnread', tr)
        self.assertIn('unread=true', tr)


class GameEstimates(unittest.TestCase):
    def test_unresolved_estimates_grouped_by_name(self):
        rows = [{'name': '스타듀밸리', 'n': 3, 'grades': {'E': 2, 'A': 1}, 'first_at': None, 'last_at': None}]

        def answer(q):
            if 'FILTER' in q: return _Res(one={'open': 4, 'resolved': 1})
            return _Res(rows=rows)
        conn = _Conn(answer)
        undo = _swap(GG, conn)
        orig = GG.current_operator
        GG.current_operator = lambda: {'role': 'viewer', 'operator_id': 2}
        try:
            d = GG.estimates()
        finally:
            undo(); GG.current_operator = orig
        self.assertEqual(d['items'][0], {'name': '스타듀밸리', 'count': 3, 'grades': {'E': 2, 'A': 1},
                                         'first_at': None, 'last_at': None})
        self.assertEqual((d['open'], d['resolved']), (4, 1))
        q = ' '.join(conn.sql)
        self.assertIn('resolved_game_id IS NULL', q)
        self.assertNotIn('UPDATE', q.upper().split('FILTER')[0])

    def test_screen_shows_estimates(self):
        html = open('templates/admin/game_grades.html.j2', encoding='utf-8').read()
        self.assertIn("API+'/estimates'", html)
        self.assertIn('목록 밖 게임 추정', html)


if __name__ == '__main__':
    unittest.main()
