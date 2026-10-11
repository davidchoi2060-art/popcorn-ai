"""AI 답 점검 — 문의마다 답을 남기고 약속하는 말을 표시한다(2026-10-11 관리자 확인 R2·M8).

AI 답 문장은 품질관리-20261011 고객 결과.md 에 적힌 실제 응답이다.
"""
import contextlib
import unittest
from unittest.mock import patch

from api import talk, talk_rules as TR, talk_schema as TS, talk_answer as TA
from tests.test_talk_rules_20261010 import vocab, _Conn
from tests.test_talk_honest_notices_20261011 import _ai


class PromiseFlags(unittest.TestCase):
    def test_real_promises_are_flagged(self):
        cases = {
            '네, 윈도우를 깔아서 배송해드립니다': '해 드린다는 약속',
            '흰색 케이스로 맞춰드리겠습니다': '해 드린다는 약속',
            '80만원 PC 5대를 주문하시려는군요. 확인했습니다.': '확인했다는 말',
            '네, 모니터 포함 구성도 가능합니다': '가능하다는 단정',
            '결제 담당팀에 확인해 드릴게요': '담당자·다른 단계로 미룸',
            'A/S 조건은 상품 확정 후 안내해 드리니까': '담당자·다른 단계로 미룸',
        }
        for reply, want in cases.items():
            with self.subTest(reply=reply):
                self.assertIn(want, TR.promise_flags(reply))

    def test_plain_questions_not_flagged(self):
        for reply in ('주로 어떤 게임 하세요?', '사무용 PC를 찾고 계시는군요.',
                      '용도와 예산을 알려 주시면 맞는 PC를 찾아 드릴게요.'):
            with self.subTest(reply=reply):
                self.assertEqual(TR.promise_flags(reply), [])

    def test_question_key_groups_same_question(self):
        a = TR.question_key('QA-고객2 윈도우 깔려서 오나요?')
        self.assertEqual(a, TR.question_key('윈도우 깔려서 오나요'))
        self.assertNotEqual(a, TR.question_key('모니터도 같이 오나요?'))
        self.assertEqual(len(a), 64)
        self.assertIsNone(TR.question_key('  ?! '))


class _Nested:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _RecConn:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def begin_nested(self):
        return _Nested()

    def execute(self, sql, params=None):
        if self.fail:
            raise RuntimeError('db down')
        self.calls.append(params)


class RecordReply(unittest.TestCase):
    def test_stores_flags_and_key_not_raw_text(self):
        c = _RecConn()
        talk._record_reply(c, 7, text_raw='윈도우 깔려서 오나요?', ai_reply='네, 깔아서 배송해드립니다',
                           shown_reply='안내', answer='', answer_error=False)
        p = c.calls[0]
        self.assertEqual(p['h'], 7)
        self.assertIn('해 드린다는 약속', p['fl'])
        self.assertEqual(p['qk'], TR.question_key('윈도우 깔려서 오나요?'))
        self.assertNotIn('윈도우 깔려서', ' '.join(str(v) for v in p.values() if v))

    def test_no_hit_no_row_and_failure_is_swallowed(self):
        c = _RecConn()
        talk._record_reply(c, None, text_raw='x', ai_reply='y', shown_reply='y', answer='', answer_error=False)
        self.assertEqual(c.calls, [])
        talk._record_reply(_RecConn(fail=True), 1, text_raw='x', ai_reply='y', shown_reply='y',
                           answer='', answer_error=True)

    def test_parse_passes_ai_reply_before_override(self):
        seen = {}
        ans = TA.AnswerResult(answer='', narrowing=TS.NARROWING_WIDE)
        with contextlib.ExitStack() as st:
            st.enter_context(patch.object(talk.engine, 'connect', lambda: _Conn()))
            st.enter_context(patch.object(talk.engine, 'begin', lambda: _Conn()))
            st.enter_context(patch.object(talk.access_gate, 'check_rate', lambda *a, **k: None))
            st.enter_context(patch.object(talk.TS, 'load_vocab', lambda conn: vocab()))
            st.enter_context(patch.object(talk.shop_notices, 'load_written', lambda conn: {}))
            st.enter_context(patch.object(talk.TA, 'run_parallel',
                                          lambda a, b: (_ai({}, '네, 윈도우를 깔아서 배송해드립니다'), ans)))
            st.enter_context(patch.object(talk.TA, 'is_game_related', lambda *a: False))
            st.enter_context(patch.object(talk, '_record_hit', lambda *a, **k: 5))
            st.enter_context(patch.object(talk, '_record_reply', lambda conn, h, **k: seen.update(k, hit=h)))
            r = talk.parse_talk(talk.ParseBody(text='윈도우 깔려서 오나요?'), request=None)
        self.assertEqual(seen['hit'], 5)
        self.assertEqual(seen['ai_reply'], '네, 윈도우를 깔아서 배송해드립니다')
        self.assertEqual(seen['shown_reply'], r['reply'])
        self.assertNotEqual(seen['ai_reply'], seen['shown_reply'])


if __name__ == '__main__':
    unittest.main()
