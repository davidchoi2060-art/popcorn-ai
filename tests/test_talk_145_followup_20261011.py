"""코덱스 #145 검수 남은 문제 보완(2026-10-11).

1 정상 PC 설명은 권유로 보지 않는다 · 3 흐름 상태가 비어 와도 이미 한 권유는 이어진다 ·
4 성능·호환을 단정할 수 없다는 고객용 한계는 지우지 않는다. AI 응답은 흉내 낸다(LLM 미호출).
「3번째 대화마다 권유」는 소스상 아니다 -- 상담에 한 번(pc_offered)이고, 아래 마지막 검사가 고정한다.
"""
import contextlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from api import talk, talk_exceptions as TX, talk_schema as TS
from api import talk_answer as TA
from tests.test_talk_rules_20261010 import vocab, _Conn


def _talk(text, reply, *, chat_flow=None, history=None):
    raw = json.dumps({'pc': False, 'state': {}, 'reply': reply}, ensure_ascii=False)
    result = SimpleNamespace(text=raw, provider='t', model='t', tokens_in=1, elapsed_sec=0.1)
    ans = TA.AnswerResult(answer='', narrowing=TS.NARROWING_WIDE)
    body = talk.ParseBody(text=text, chat_flow=chat_flow, history=history or [])
    with contextlib.ExitStack() as st:
        st.enter_context(patch.object(talk.engine, 'connect', lambda: _Conn()))
        st.enter_context(patch.object(talk.engine, 'begin', lambda: _Conn()))
        st.enter_context(patch.object(talk.access_gate, 'check_rate', lambda *a, **k: None))
        st.enter_context(patch.object(talk.TS, 'load_vocab', lambda conn: vocab()))
        st.enter_context(patch.object(talk.TA, 'run_parallel', lambda a, b: (result, ans)))
        st.enter_context(patch.object(talk.TA, 'is_game_related', lambda *a: False))
        st.enter_context(patch.object(talk, '_record_hit', lambda *a, **k: None))
        return talk.parse_talk(body, request=None)


class PlainPcExplanationKept(unittest.TestCase):
    def test_definition_with_purchase_word_is_kept(self):
        s = '견적은 구매할 부품과 비용을 적은 문서예요.'
        self.assertEqual(talk.drop_pc_push(s), s)

    def test_plain_build_sentence_kept(self):
        s = '컴퓨터를 맞추는 일은 부품을 고르는 데서 시작해요.'
        self.assertEqual(talk.drop_pc_push(s), s)

    def test_offer_without_question_mark_is_removed(self):
        self.assertEqual(talk.drop_pc_push('좋은 하루예요. 원하시면 PC 구성도 함께 볼 수 있어요.'), '좋은 하루예요.')

    def test_customer_directed_buy_is_removed(self):
        self.assertEqual(talk.drop_pc_push('날이 좋네요. 컴퓨터 구매하실 때 말씀만 주세요.'), '날이 좋네요.')


class OfferRemembered(unittest.TestCase):
    def test_empty_flow_after_reopening_a_quote_does_not_offer_again(self):
        hist = [{'role': 'assistant', 'text': '그것도 좋네요. ' + TX.NOTE_SMALLTALK_LONG}]
        r = _talk('주말 뭐 하지', '푹 쉬세요.', chat_flow={'smalltalk_turns': 5}, history=hist)
        self.assertNotIn(TX.NOTE_SMALLTALK_LONG, r['reply'])
        self.assertTrue(r['chat_flow']['pc_offered'])

    def test_game_pick_line_in_history_counts_as_offered(self):
        hist = [{'role': 'assistant', 'text': talk.REPLY_GAME_PICK}]
        r = _talk('주말 뭐 하지', '푹 쉬세요.', chat_flow={'smalltalk_turns': 5}, history=hist)
        self.assertNotIn(TX.NOTE_SMALLTALK_LONG, r['reply'])

    def test_offer_happens_once_not_every_third_turn(self):
        flow, offers = {'smalltalk_turns': 0}, 0
        for i in range(9):
            r = _talk('심심해', '그렇군요.', chat_flow=flow)
            flow = r['chat_flow']; offers += TX.NOTE_SMALLTALK_LONG in r['reply']
        self.assertEqual(offers, 1)


class CustomerLimitKept(unittest.TestCase):
    def test_performance_and_compat_limits_survive(self):
        for s in ('제공된 자료가 부족해 성능은 단정할 수 없어요.',
                  '주어진 자료에는 호환 정보가 없어 동작을 보장할 수 없어요.'):
            with self.subTest(s=s):
                self.assertIn(s, TA._drop_data_excuse('롤은 팀 전략 게임이에요. ' + s))

    def test_internal_excuse_still_removed(self):
        out = TA._drop_data_excuse('롤은 팀 전략 게임이에요. 제공된 자료에는 세부 재미 요소가 없어요.')
        self.assertNotIn('자료', out)


if __name__ == '__main__':
    unittest.main()
