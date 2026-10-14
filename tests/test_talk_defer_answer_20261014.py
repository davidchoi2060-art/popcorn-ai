"""「카드 먼저」 -- 질문 읽기([A])가 끝나면 설명([B])을 기다리지 않고 첫 응답을 낸다(api/talk._parse_deferred).

2026-10-14 사장님 「답변이 너무 느린데」 -> 「그렇게 해」(카드 먼저). 개발 서버 실측: 질문 읽기 2.8~3.8초, 설명 7.3~8.6초,
화면은 둘 다 받은 뒤 카드를 불러 카드까지 9~11초였다."""
import contextlib
import json
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from api import talk, talk_answer as TA, talk_pc_advice as PA
from tests.test_talk_rules_20261010 import _Conn, vocab

ADVICE = '게임용이라면 그래픽카드가 가장 중요해요. 램은 16GB, SSD는 480GB 이상이면 무난해요.'


def _result(state):
    obj = {'pc': True, 'state': state, 'missing': [], 'evidence': [], 'reply': '주로 어떤 게임 하세요?'}
    return SimpleNamespace(text=json.dumps(obj, ensure_ascii=False), provider='t', model='t',
                           tokens_in=1, elapsed_sec=0.1, log_id=None)


@contextlib.contextmanager
def server(state, *, release, routed=True, hits=None):
    """[A] 는 즉시, [B] 는 release 가 열릴 때까지 기다린다."""
    def fake_answer_path(conn_factory, sentence, vocab_, **kw):
        res = TA.AnswerResult()
        if routed:
            res.kind, res.topic = 'pc_advice', PA.TOPIC_BUILD
            kw['on_route'](res)
            release.wait(5)
            res.answer = ADVICE
        return res

    with contextlib.ExitStack() as st:
        st.enter_context(patch.object(talk.engine, 'connect', lambda: _Conn()))
        st.enter_context(patch.object(talk.engine, 'begin', lambda: _Conn()))
        st.enter_context(patch.object(talk.access_gate, 'check_rate', lambda *a, **k: None))
        st.enter_context(patch.object(talk.TS, 'load_vocab', lambda conn: vocab()))
        st.enter_context(patch.object(talk.llm, 'call', lambda *a, **k: _result(state)))
        st.enter_context(patch.object(talk.TA, 'answer_path', fake_answer_path))
        st.enter_context(patch.object(talk.TA, 'is_game_related', lambda *a: False))
        st.enter_context(patch.object(talk, '_record_hit',
                                      lambda *a, **k: (hits.append(k['text_raw']) if hits is not None else None)))
        st.enter_context(patch.object(talk, '_record_reply', lambda *a, **k: None))
        st.enter_context(patch.object(talk, '_link_cost_logs', lambda *a, **k: None))
        yield


class CardsFirst(unittest.TestCase):
    STATE = {'usages': ['게임'], 'budget_won': 1_500_000}

    def test_first_reply_does_not_wait_for_the_explanation(self):
        release, hits = threading.Event(), []
        with server(self.STATE, release=release, hits=hits):
            t0 = time.time()
            first = talk.parse_talk(talk.ParseBody(text='게임용 150만원', defer_answer=True), request=None)
            self.assertLess(time.time() - t0, 2)
            self.assertEqual(first['answer'], '')
            self.assertTrue(first['answer_pending'])
            self.assertEqual(first['missing'], [])
            self.assertEqual(hits, [])                      # 첫 응답은 기록하지 않는다
            release.set()
            final = talk.answer_talk(talk.AnswerBody(token=first['answer_pending']))
        self.assertIn('그래픽카드', final['answer'])
        self.assertEqual(final['state'], first['state'])
        self.assertEqual(final['missing'], first['missing'])
        self.assertNotIn('answer_pending', final)
        self.assertEqual(hits, ['게임용 150만원'])          # 최종 조립이 한 번만 남긴다
        with self.assertRaises(HTTPException) as e:          # 한 번 받으면 표는 지워진다
            talk.answer_talk(talk.AnswerBody(token=first['answer_pending']))
        self.assertEqual(e.exception.status_code, 404)

    def test_nothing_to_explain_returns_at_once(self):
        with server(self.STATE, release=threading.Event(), routed=False):
            out = talk.parse_talk(talk.ParseBody(text='게임용 150만원', defer_answer=True), request=None)
        self.assertNotIn('answer_pending', out)
        self.assertEqual(out['answer'], '')

    def test_default_still_waits_for_the_explanation(self):
        release = threading.Event()
        release.set()
        with server(self.STATE, release=release):
            out = talk.parse_talk(talk.ParseBody(text='게임용 150만원'), request=None)
        self.assertIn('그래픽카드', out['answer'])
        self.assertNotIn('answer_pending', out)

    def test_unknown_token(self):
        with self.assertRaises(HTTPException) as e:
            talk.answer_talk(talk.AnswerBody(token='nope'))
        self.assertEqual(e.exception.status_code, 404)


if __name__ == '__main__':
    unittest.main()
