"""잡담에서 AI 가 먼저 게임 이야기를 꺼내지 않는다 — 2026-10-11 사장님 「게임 이런 건 빼고 편하게 대화로 상담」.

기준은 「그 말의 답이 PC 추천 조건이 되는가」다. 잡담 중 「혹시 할 게임 있으세요?」·「그럴 때 게임하면
좋지요」는 조건 질문이 아니라서 걷는다. 고객이 게임을 말했으면(이번 문장이든 최근 대화든) 걷지 않는다.
PC 상담 턴의 「어떤 게임을 하세요?」는 잡담 경로를 타지 않으므로 그대로다. AI 응답은 흉내 낸다.
"""
import contextlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from api import talk, talk_schema as TS
from api import talk_answer as TA
from tests.test_talk_rules_20261010 import vocab, _Conn


def _turn(text, reply, *, pc=False, game=False, history=None, state=None):
    raw = json.dumps({"pc": pc, "state": state or {}, "reply": reply}, ensure_ascii=False)
    result = SimpleNamespace(text=raw, provider='t', model='t', tokens_in=1, elapsed_sec=0.1)
    ans = TA.AnswerResult(answer='', narrowing=TS.NARROWING_WIDE)
    body = talk.ParseBody(text=text, history=history or [])
    with contextlib.ExitStack() as st:
        st.enter_context(patch.object(talk.engine, 'connect', lambda: _Conn()))
        st.enter_context(patch.object(talk.engine, 'begin', lambda: _Conn()))
        st.enter_context(patch.object(talk.access_gate, 'check_rate', lambda *a, **k: None))
        st.enter_context(patch.object(talk.TS, 'load_vocab', lambda conn: vocab()))
        st.enter_context(patch.object(talk.TA, 'run_parallel', lambda a, b: (result, ans)))
        st.enter_context(patch.object(talk.TA, 'is_game_related', lambda s, v: game and s == text or '게임' in s))
        st.enter_context(patch.object(talk, '_record_hit', lambda *a, **k: None))
        return talk.parse_talk(body, request=None)


class NoGameNudgeInSmallTalk(unittest.TestCase):
    def test_question_about_games_is_removed_when_customer_did_not_mention_games(self):
        r = _turn('비 오네', '비가 오니까 집에서 쉬기 좋네요. 혹시 할 게임 있으세요?')
        self.assertEqual(r['reply'], '비가 오니까 집에서 쉬기 좋네요.')

    def test_game_only_suggestion_falls_back_to_a_plain_line(self):
        r = _turn('심심해', '그럴 때 게임하면 좋지요.')
        self.assertNotIn('게임', r['reply'])
        self.assertEqual(r['reply'], talk.REPLY_SMALLTALK_EMPTY)

    def test_customer_game_talk_keeps_the_game_reply(self):
        r = _turn('게임 뭐 할까', '요즘 인기 있는 게임은 발로란트예요. 해 보셨어요?', game=True)
        self.assertIn('발로란트', r['reply'])

    def test_recent_game_talk_in_history_keeps_it(self):
        r = _turn('심심해', '그럴 때 아까 말씀하신 게임하면 좋지요.',
                  history=[{'role': 'user', 'text': '게임 좋아해요'}])
        self.assertIn('게임', r['reply'])

    def test_game_listed_among_options_is_taken_out_of_the_list(self):
        # 2026-10-11 개발 서버 실측 문장들 -- 고객이 게임을 말하지 않았는데 할 거리로 끼워 넣었다.
        cases = {
            '심심해': ('그럴 땐 게임을 하거나 영상 봐도 좋지요.', '그럴 땐 영상 봐도 좋지요.'),
            '비 오네': ('비 오는 날엔 실내에서 게임이나 영상 감상도 괜찮습니다.',
                        '비 오는 날엔 실내에서 영상 감상도 괜찮습니다.'),
            '주말 뭐 하지': ('집에서 쉬거나 게임, 영상 보는 것도 좋죠.', '집에서 쉬거나 영상 보는 것도 좋죠.'),
        }
        for text, (reply, want) in cases.items():
            with self.subTest(text=text):
                self.assertEqual(_turn(text, reply)['reply'], want)

    def test_any_other_game_sentence_is_dropped(self):
        r = _turn('주말 뭐 하지', '푹 쉬세요. 영화나 게임도 좋죠.')
        self.assertEqual(r['reply'], '푹 쉬세요.')

    def test_compound_words_with_game_stay_intact(self):
        # 코덱스 #150 검수 P2: 합성어 끝의 「게임이나」를 지우면 「보드독서」처럼 문장이 깨졌다.
        cases = {
            '보드게임이나 독서를 해보세요.': '보드게임이나 독서를 해보세요.',
            '비디오게임, 영화 감상도 좋아요.': '비디오게임, 영화 감상도 좋아요.',
            '미니게임이 들어 있는 앱도 있어요.': '미니게임이 들어 있는 앱도 있어요.',
            '게임기는 거실에 두면 좋아요.': '게임기는 거실에 두면 좋아요.',
        }
        for reply, want in cases.items():
            with self.subTest(reply=reply):
                self.assertEqual(talk.drop_game_nudge(reply), want)
                self.assertEqual(_turn('심심해', reply)['reply'], want)

    def test_standalone_option_next_to_compound_is_still_removed(self):
        self.assertEqual(talk.drop_game_nudge('게임이나 보드게임 말고 산책도 좋아요.'),
                         '보드게임 말고 산책도 좋아요.')
        self.assertEqual(talk.drop_game_nudge('쉬거나 겜, 보드게임도 좋죠.'), '쉬거나 보드게임도 좋죠.')
        self.assertEqual(talk.drop_game_nudge('독서나 게임이나 산책도 좋아요.'), '독서나 산책도 좋아요.')

    def test_prompt_says_not_to_open_with_games(self):
        self.assertIn('게임 이야기도 먼저 꺼내지 않는다', talk.SMALLTALK_BLOCK)


class GameNudgeShape(unittest.TestCase):
    def test_shapes(self):
        self.assertTrue(talk.is_game_nudge('혹시 할 게임 있으세요?'))
        self.assertTrue(talk.is_game_nudge('그럼 게임 해보거나 뭔가 재밌는 거 찾아보세요.'))
        self.assertTrue(talk.is_game_nudge('요즘 인기 많은 게임도 있어요.'))
        self.assertFalse(talk.is_game_nudge('루나 같은 이름 어떠세요?'))
        self.assertFalse(talk.is_game_nudge('비가 오니까 집에서 쉬기 좋네요.'))


if __name__ == '__main__':
    unittest.main()
