"""상담 갈래 판정(api/talk_entry) -- 사장님 2026-10-11 「위 채팅 내용을 보고 적당한 화면으로 보내야지」.

처음 화면 채팅창에 쓴 글로 새 PC 찾기 / 쓰던 PC 업그레이드 / 부품·구성 물어보기 중 하나로 시작한다.
단추 > 지난 턴 > 규칙 > AI 가 읽은 용도·예산 순이고, 그래도 모르면 상담에 한 번만 되묻는다.
AI 응답은 흉내 낸다(LLM 미호출).
"""
import contextlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from api import talk, talk_entry as TE, talk_schema as TS
from api import talk_answer as TA
from tests.test_talk_rules_20261010 import vocab, _Conn


def _run(text, *, state=None, pc=True, reply='네, 도와드릴게요.', entry=None, chat_flow=None, prompts=None):
    raw = json.dumps({'pc': pc, 'state': state or {}, 'reply': reply}, ensure_ascii=False)
    result = SimpleNamespace(text=raw, provider='t', model='t', tokens_in=1, elapsed_sec=0.1)
    ans = TA.AnswerResult(answer='', narrowing=TS.NARROWING_WIDE)
    body = talk.ParseBody(text=text, entry=entry, chat_flow=chat_flow)

    original = talk._build_prompt

    def build(*a, **k):
        out = original(*a, **k)
        if prompts is not None:
            prompts.append(out)
        return out
    with contextlib.ExitStack() as st:
        st.enter_context(patch.object(talk.engine, 'connect', lambda: _Conn()))
        st.enter_context(patch.object(talk.engine, 'begin', lambda: _Conn()))
        st.enter_context(patch.object(talk.access_gate, 'check_rate', lambda *a, **k: None))
        st.enter_context(patch.object(talk.TS, 'load_vocab', lambda conn: vocab()))
        st.enter_context(patch.object(talk.TA, 'run_parallel', lambda a, b: (result, ans)))
        st.enter_context(patch.object(talk, '_build_prompt', build))
        st.enter_context(patch.object(talk.TA, 'is_game_related', lambda *a: False))
        st.enter_context(patch.object(talk, '_record_hit', lambda *a, **k: None))
        return talk.parse_talk(body, request=None)


class Classify(unittest.TestCase):
    def test_three_sentences(self):
        cases = {
            '150만원으로 게임용 PC 맞추고 싶어요': 'new_pc',
            '지금 쓰는 컴퓨터가 너무 느려요. 램만 바꾸면 될까요?': 'upgrade',
            'SSD랑 메모리는 뭐가 달라요?': 'parts',
            '그래픽카드만 바꾸고 싶어요': 'upgrade',
            '새 컴퓨터 추천해 주세요': 'new_pc',
            '안녕하세요': None,
            '그냥 상담 좀 하려고요': None,
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(TE.classify(text), want)


class Route(unittest.TestCase):
    def test_rule_sets_entry_and_prompt_line(self):
        prompts = []
        r = _run('지금 쓰는 PC가 느려요', prompts=prompts)
        self.assertEqual(r['chat_flow']['entry'], 'upgrade')
        self.assertIn('쓰던 PC 업그레이드', prompts[0])
        self.assertNotIn(TE.ASK, r['reply'])

    def test_button_wins_and_entry_is_kept_next_turn(self):
        r = _run('새 PC를 찾고 있어요.', entry='parts')
        self.assertEqual(r['chat_flow']['entry'], 'parts')
        prompts = []
        r2 = _run('그건 뭐예요', chat_flow=r['chat_flow'], prompts=prompts)
        self.assertEqual(r2['chat_flow']['entry'], 'parts')
        self.assertIn('부품·구성 물어보기', prompts[0])

    def test_ai_read_usage_means_new_pc(self):
        r = _run('롤 하려고요', state={'usages': ['게임']})
        self.assertEqual(r['chat_flow']['entry'], 'new_pc')
        self.assertNotIn(TE.ASK, r['reply'])

    def test_unclear_pc_talk_asks_once(self):
        r = _run('PC 상담 좀 하려고요')
        self.assertIsNone(r['chat_flow']['entry'])
        self.assertTrue(r['reply'].endswith(TE.ASK))
        self.assertTrue(r['chat_flow']['entry_asked'])
        r2 = _run('음 글쎄요', chat_flow=r['chat_flow'])
        self.assertNotIn(TE.ASK, r2['reply'])

    def test_answer_to_the_question_sets_the_entry(self):
        r = _run('PC 상담 좀 하려고요')
        r2 = _run('쓰던 PC 업그레이드요', chat_flow=r['chat_flow'])
        self.assertEqual(r2['chat_flow']['entry'], 'upgrade')

    def test_small_talk_is_not_asked(self):
        r = _run('비 오네', pc=False, reply='비 오는 날엔 쉬기 좋죠.')
        self.assertNotIn(TE.ASK, r['reply'])
        self.assertIsNone(r['chat_flow']['entry'])


if __name__ == '__main__':
    unittest.main()
