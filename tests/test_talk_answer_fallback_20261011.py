"""게임 소개 글이 빠지지 않게 — 답변 AI 가 실패하면 우리 DB 사실로 짧게 소개한다(2026-10-11 개편 15번).

고객1 기능 11 · R11: 26턴 중 2턴에서 답변 AI 가 9.3초 걸려 8초 상한에서 끊겼고 소개 글이 통째로 빠졌다.
관리자 「AI 답 점검」에는 실패한 턴이 몇 초 걸렸는지 꼬리표로 남는다.
"""
import contextlib
import unittest
from unittest.mock import patch

from api import llm, talk, talk_answer as TA
from tests.test_talk_rules_20261010 import vocab
from tests.test_talk_reply_review_20261011 import _RecConn


class _C:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


LOL = TA.GameFacts(name='리그 오브 레전드', genre='AOS', vendor='라이엇 게임즈', grade='E',
                   pcbang_rank=1, steam_ccu=None)
VALO = TA.GameFacts(name='발로란트', genre='FPS', vendor='라이엇 게임즈',
                    copy_spec='가벼운 사양으로도 높은 프레임이 나옵니다.')


def run_path(facts, llm_call):
    ev = TA.Evidence(db_lines=['x'], facts=list(facts))
    with contextlib.ExitStack() as st:
        st.enter_context(patch.object(TA, 'is_game_related', lambda *a: True))
        st.enter_context(patch.object(TA, 'collect_evidence', lambda *a, **k: ev))
        st.enter_context(patch.object(TA.TF, 'price_floors', lambda conn: {}))
        st.enter_context(patch.object(TA.llm, 'call', llm_call))
        return TA.answer_path(lambda: _C(), '롤이랑 발로 어때요', vocab())


def _timeout(*a, **k):
    raise llm.LLMAllProvidersFailedError('timeout', [('p', TimeoutError())])


class FallbackIntro(unittest.TestCase):
    def test_uses_reviewed_copy_then_genre_vendor(self):
        ev = TA.Evidence(facts=[LOL, VALO])
        self.assertEqual(TA.fallback_intro(ev),
                         '리그 오브 레전드는 라이엇 게임즈가 만든 AOS 장르 게임이에요.\n'
                         '발로란트: 가벼운 사양으로도 높은 프레임이 나옵니다.')

    def test_no_facts_no_text_and_at_most_three_games(self):
        self.assertEqual(TA.fallback_intro(TA.Evidence(facts=[TA.GameFacts(name='무명')])), '')
        many = [TA.GameFacts(name='g%d' % i, genre='RPG') for i in range(5)]
        self.assertEqual(TA.fallback_intro(TA.Evidence(facts=many)).count('장르'), 3)
        self.assertEqual(TA.fallback_intro(TA.Evidence(facts=[TA.GameFacts(name='배틀그라운드', vendor='크래프톤')])),
                         '배틀그라운드는 크래프톤이 만든 게임이에요.')


class AnswerPath(unittest.TestCase):
    def test_llm_timeout_gives_short_intro(self):
        r = run_path([LOL], _timeout)
        self.assertTrue(r.error)
        self.assertTrue(r.fallback)
        self.assertEqual(r.answer, '리그 오브 레전드는 라이엇 게임즈가 만든 AOS 장르 게임이에요.')

    def test_no_usable_fact_keeps_empty(self):
        r = run_path([TA.GameFacts(name='무명')], _timeout)
        self.assertEqual((r.answer, r.fallback), ('', False))
        self.assertTrue(r.error)

    def test_success_is_not_fallback(self):
        out = type('O', (), {'text': '롤은 가벼운 게임입니다.', 'provider': 'p', 'model': 'm',
                             'cost_usd': 0, 'tokens_in': 1, 'tokens_out': 1, 'log_id': None})()
        r = run_path([LOL], lambda *a, **k: out)
        self.assertFalse(r.fallback)
        self.assertIsNone(r.error)


class AdminFlag(unittest.TestCase):
    def test_flags(self):
        self.assertEqual(talk._answer_flags(TA.AnswerResult()), [])
        self.assertEqual(talk._answer_flags(TA.AnswerResult(error='x', fallback=True, elapsed_sec=9.31)),
                         ['게임 소개 기본 문구로 대신함(9.3초)'])
        self.assertEqual(talk._answer_flags(TA.AnswerResult(error='x', elapsed_sec=10.0)),
                         ['게임 소개 실패(10.0초)'])

    def test_flag_stored_with_promise_flags(self):
        c = _RecConn()
        talk._record_reply(c, 3, text_raw='롤 어때요', ai_reply='주로 어떤 게임 하세요?', shown_reply='x',
                           answer='리그 오브 레전드: 장르 AOS', answer_error=True,
                           extra_flags=['게임 소개 기본 문구로 대신함(9.3초)'])
        self.assertIn('게임 소개 기본 문구로 대신함(9.3초)', c.calls[0]['fl'])
        self.assertTrue(c.calls[0]['ae'])

    def test_path_b_timeout_measures_time(self):
        def slow():
            raise TimeoutError()
        _, b = TA.run_parallel(lambda: 'a', slow, timeout_sec=0.01)
        self.assertTrue(b.error)
        self.assertGreaterEqual(b.elapsed_sec, 0)


if __name__ == '__main__':
    unittest.main()


class DataExcuseTrim(unittest.TestCase):
    """2026-10-11 개발 서버: 인기 게임 답 끝에 「제공된 자료에는 … 없어」가 붙었다 -- 걷는다."""

    def test_trailing_excuse_removed(self):
        from types import SimpleNamespace as NS
        body = ("요즘 인기 게임이에요.\n- 발로란트: 라이엇 게임즈의 슈팅 게임이에요.\n"
                "- 서든어택: 넥슨의 슈팅 게임이에요. 제공된 자료에는 각 게임의 세부 재미 요소가 없어,"
                " 확인된 장르와 인기도 중심으로 소개해 드렸습니다.")
        out = TA.tidy_game_list(body, [NS(name="발로란트"), NS(name="서든어택")])
        self.assertNotIn("자료", out)
        self.assertTrue(out.endswith("넥슨의 슈팅 게임이에요."))

    def test_normal_text_kept(self):
        from types import SimpleNamespace as NS
        body = "- 발로란트: 자료 화면이 깔끔한 슈팅 게임이에요.\n- 롤: 팀 전략 게임이에요."
        self.assertEqual(TA.tidy_game_list(body, [NS(name="발로란트"), NS(name="롤")]), body)


class WidePromptGeneralAI(unittest.TestCase):
    """사장님 기준(2026-10-11): 인기 게임 답은 일반 AI 수준 -- 노는 방식·재미는 일반 지식, 순위는 한 번만."""

    def test_wide_prompt_allows_gameplay_knowledge_and_single_rank_mention(self):
        ev = TA.Evidence()
        p = TA.build_answer_prompt("요즘 인기 게임 뭐 있어?", ev, TA.TS.NARROWING_WIDE)
        self.assertIn("일반 지식으로 말해도 된다", p)
        self.assertIn("도입에서 한 번만", p)
        self.assertIn("[근거] 에 적힌 것만", p)
