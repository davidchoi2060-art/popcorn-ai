"""상담 문제 4개(2026-10-10 상담 품질 점검 높음 4건) + 카드 이름 광고 문구 — 회귀 고정.

  ① 「발로 백만원」 -> 예산 100만원 · 게임 발로란트 (AI 가 1,000만원 · 게임명 없음으로 내도)
  ② 「게임용 250만원」「게임 100만원」 -> 되묻기 없이 카드로(FHD 가정)
  ③ 「게임용 컴퓨터 추천해줘」 -> 「150만원이요」 -> 두 번째 턴은 카드로(같은 질문 반복 금지)
  ④ 「노트북 추천해줘」 -> 노트북은 팔지 않는다는 한 줄 + 데스크톱 상담 계속

parse_talk 는 LLM·DB·방문자 한도를 탄다 — 셋 다 바꿔 끼우고, AI 응답은 점검 때 실제로 받은
모양(customer-screens/상담품질-20261010/응답)을 그대로 흉내 낸다.
"""
import contextlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from api import talk, talk_rules as TR, talk_schema as TS, talk_answer as TA
from api.product_name import card_name, match_storage_shorthand


def vocab():
    names = ['리그 오브 레전드', '발로란트', '배틀그라운드', '오버워치2', '메이플스토리',
             '서든어택', '로스트아크', 'FC온라인', '던전앤파이터']
    return TS.Vocab(
        grades=[{'grade': 'E', 'label': '가벼움', 'sort_order': 1}, {'grade': 'C', 'label': '보통', 'sort_order': 3}],
        confirmed_games={'리그 오브 레전드': 'E', '발로란트': 'E', '배틀그라운드': 'C'},
        all_game_names=names,
        usages=[('고사양 게임', []), ('게임', ['게임']), ('캐주얼 게임', []), ('사무·인강', ['사무'])],
        game_aliases=TR.merged_game_aliases({'롤': '리그 오브 레전드', '배그': '배틀그라운드'},
                                            names, TS._norm_name),
        grade_weight={'E': 1, 'C': 3},
    )


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def run_parse(text, ai_state, *, ai_reply='주로 어떤 게임 하세요?', pc=True, prev=None,
              history=None, narrowing=TS.NARROWING_WIDE, answer=''):
    obj = {'pc': pc, 'state': ai_state, 'missing': [], 'evidence': [], 'reply': ai_reply}
    result = SimpleNamespace(text=json.dumps(obj, ensure_ascii=False), provider='t', model='t',
                             tokens_in=1, elapsed_sec=0.1)
    ans = TA.AnswerResult(answer=answer, narrowing=narrowing)
    body = talk.ParseBody(text=text, state=prev, history=history)
    with contextlib.ExitStack() as st:
        st.enter_context(patch.object(talk.engine, 'connect', lambda: _Conn()))
        st.enter_context(patch.object(talk.engine, 'begin', lambda: _Conn()))
        st.enter_context(patch.object(talk.access_gate, 'check_rate', lambda *a, **k: None))
        st.enter_context(patch.object(talk.TS, 'load_vocab', lambda conn: vocab()))
        st.enter_context(patch.object(talk.TA, 'run_parallel', lambda a, b: (result, ans)))
        st.enter_context(patch.object(talk.TA, 'is_game_related', lambda *a: False))
        st.enter_context(patch.object(talk, '_record_hit', lambda *a, **k: None))
        return talk.parse_talk(body, request=None)


class BudgetFromTextTest(unittest.TestCase):
    CASES = {
        '발로 백만원': 1_000_000, '천만원': 10_000_000, '백오십만원': 1_500_000,
        '백오십': 1_500_000, '백오십으로 맞춰줘': 1_500_000, '이백': 2_000_000,
        '천오백': 15_000_000, '2백만원': 2_000_000, '2백50만원': 2_500_000,
        '롤150만원으로추천': 1_500_000, '배그 150마넌': 1_500_000, '1,500만원': 15_000_000,
        '게임용 250만원': 2_500_000, '게임 100만원': 1_000_000, '1500000원': 1_500_000,
        '100-150만원': 1_500_000, '1억': 100_000_000,
    }
    NONE = ['-500만원', 'RTX 5070 들어간 거 있어요?', '백색 케이스', '천 원',
            '100만원에서 150만원 사이', '노트북 추천해줘', '예산이백만원']

    def test_amounts(self):
        for text, won in self.CASES.items():
            with self.subTest(text=text):
                self.assertEqual(TR.budget_from_text(text), won)

    def test_unreadable_or_ambiguous_is_left_to_ai(self):
        for text in self.NONE:
            with self.subTest(text=text):
                self.assertIsNone(TR.budget_from_text(text))


class GamesFromTextTest(unittest.TestCase):
    def test_short_names(self):
        v = vocab()
        for text, name in [('발로 백만원', '발로란트'), ('메이플 할 컴퓨터', '메이플스토리'),
                           ('서든 150', '서든어택'), ('옵치랑 롤', '오버워치2'), ('로아 200만원', '로스트아크'),
                           ('던파용', '던전앤파이터'), ('피파 하려고요', 'FC온라인'), ('배그를 해요', '배틀그라운드')]:
            with self.subTest(text=text):
                self.assertIn(name, TR.games_from_text(text, v, TS.match_game))

    def test_negation_is_left_to_ai(self):
        self.assertEqual(TR.games_from_text('배그는 안 하고 롤만 해요', vocab(), TS.match_game), [])

    def test_alias_table_wins_and_missing_targets_are_skipped(self):
        merged = TR.merged_game_aliases({'발로': '다른게임'}, ['발로란트', '다른게임'], TS._norm_name)
        self.assertEqual(merged['발로'], '다른게임')
        self.assertNotIn('몬헌', merged)        # 몬스터헌터 와일즈가 목록에 없으면 넣지 않는다


class ParseTalkTest(unittest.TestCase):
    def test_valo_baekman(self):
        # 점검 20번 실제 응답: 예산 10,000,000 · names [] · 캐주얼 게임
        d = run_parse('발로 백만원', {'usages': ['캐주얼 게임'], 'budget_won': 10_000_000,
                                     'game': {'names': [], 'grade': None}})
        self.assertEqual(d['state']['budget_won'], 1_000_000)
        self.assertEqual(d['state']['game']['names'], ['발로란트'])
        self.assertEqual((d['state']['game']['grade'], d['state']['game']['grade_src']), ('E', 'catalog'))
        self.assertEqual(d['missing'], [])
        self.assertIn('budget_won', {x['field'] for x in d['dropped']})

    def test_game_with_budget_gets_cards(self):
        for text, won in [('게임용 250만원', 2_500_000), ('게임 100만원', 1_000_000)]:
            with self.subTest(text=text):
                d = run_parse(text, {'usages': ['게임'], 'budget_won': won,
                                     'game': {'names': [], 'grade': None}},
                              answer='점유율 1위는 …입니다. 주로 어떤 게임을 하실 예정인가요?')
                self.assertEqual(d['missing'], [])
                self.assertEqual(d['assumed'], ['game.resolution=1080p'])
                self.assertEqual(d['reply'], TR.UNNAMED_GAME_REPLY)
                self.assertEqual(d['answer'], '')
                self.assertNotIn('어떤 게임', d['reply'])

    def test_game_without_budget_asks_once_then_cards(self):
        first = run_parse('게임용 컴퓨터 추천해줘', {'usages': ['게임'], 'game': {'names': []}})
        self.assertEqual(first['missing'], ['game.grade'])
        self.assertIn('어떤 게임', first['reply'])
        second = run_parse('150만원이요', {'usages': ['게임'], 'budget_won': 1_500_000,
                                          'game': {'names': []}},
                           prev=first['state'],
                           history=[talk.HistoryTurn(role='user', text='게임용 컴퓨터 추천해줘'),
                                    talk.HistoryTurn(role='assistant', text=first['reply'])])
        self.assertEqual(second['missing'], [])
        self.assertNotIn('어떤 게임', second['reply'])

    def test_after_one_question_no_budget_still_moves_on(self):
        first = run_parse('게임용 컴퓨터 추천해줘', {'usages': ['게임'], 'game': {'names': []}})
        second = run_parse('잘 모르겠어요', {'usages': ['게임'], 'game': {'names': []}},
                           prev=first['state'])
        self.assertEqual(second['missing'], [])

    def test_named_game_without_grade_is_still_held(self):
        # 이름이 «있는데» 등급이 없으면(목록 밖 게임) 기존대로 보류한다.
        d = run_parse('목록밖게임 200만원', {'usages': ['게임'], 'budget_won': 2_000_000,
                                         'game': {'names': ['목록밖게임'], 'grade': None}})
        self.assertEqual(d['missing'], ['game.grade'])

    def test_laptop_notice(self):
        d = run_parse('노트북 추천해줘', {'usages': []},
                      ai_reply='어떤 용도로 쓰실 계획이세요?')
        self.assertTrue(d['reply'].startswith(TR.LAPTOP_NOTICE))
        self.assertIn('어떤 용도', d['reply'])
        self.assertTrue(d['pc_related'])
        d2 = run_parse('노트북 추천해줘', {'usages': []}, ai_reply='', pc=False)
        self.assertTrue(d2['reply'].startswith(TR.LAPTOP_NOTICE))
        self.assertEqual(d2['stage'], TS.STAGE_PC)

    def test_laptop_parts_do_not_get_notice(self):
        self.assertFalse(TR.mentions_laptop('노트북 램 있어요?'))
        self.assertTrue(TR.mentions_laptop('랩탑 하나 사려고요'))


class CardNameTest(unittest.TestCase):
    def test_ad_labels_removed(self):
        self.assertEqual(card_name('골드 NO.04.98149 [인기상품1위]인텔  [12400F/16GB/500GB/RTX5060]'),
                         '골드 인텔 [12400F/16GB/500GB/RTX5060]')
        self.assertEqual(card_name('골드 NO.04.121509  [화이트상품 1위] [13세대 판매 2위] [게이밍 3위] '
                                   '[13400F/16G/1TB/RTX5060]'), '골드 [13400F/16G/1TB/RTX5060]')
        self.assertEqual(card_name('초저가 가성비짱 골드 NO.04.121257  [12400F/16G/500GB/RTX3050]'),
                         '골드 [12400F/16G/500GB/RTX3050]')

    def test_plain_names_untouched(self):
        for n in ('PC 1', '조립PC 3', 'ASUS ROG STRIX [WHITE EDITION]'):
            self.assertEqual(card_name(n), n)

    def test_internal_no_with_suffix_removed(self):
        self.assertEqual(card_name('골드 NO.04.90926MW [14400F/16G/250GB/RTX5060]'),
                         '골드 [14400F/16G/250GB/RTX5060]')
        self.assertEqual(card_name('엠에스파워 골드 NO.04 .123380 RTX 3050 [13500/16G/1TB/RTX3050]'),
                         '엠에스파워 골드 RTX 3050 [13500/16G/1TB/RTX3050]')


class StorageShorthandTest(unittest.TestCase):
    """카드 이름의 「250GB」와 사양표의 「256GB SSD」가 한 카드에 함께 보이던 문제(93454)."""

    def test_shorthand_follows_spec(self):
        spec = {'cpu': 'i5-12400', 'ram_gb': 16, 'ssd_gb': 256}
        self.assertEqual(match_storage_shorthand('골드 RTX 3050 [12400F/16G/250GB/RTX3050]', spec),
                         '골드 RTX 3050 [12400F/16G/256GB/RTX3050]')
        self.assertEqual(match_storage_shorthand('오피스 [12100/8G/250G/UHD 730]', {'ssd_gb': 256}),
                         '오피스 [12100/8G/256GB/UHD 730]')
        self.assertEqual(match_storage_shorthand('[7500F/16G/500GB/RTX5060]', {'ssd_gb': 512}),
                         '[7500F/16G/512GB/RTX5060]')

    def test_unexplained_difference_untouched(self):
        # 250GB 대 500GB 는 줄임 표기가 아니다 — 어느 쪽이 맞는지 몰라 바꾸지 않는다.
        for name, spec in (('골드 [9600/16G/250GB/RTX3050]', {'ssd_gb': 500}),
                           ('[14700KF/64G/1TB/RTX5070 TI]', {'ssd_gb': 2000}),
                           ('[12400F/16G/500GB/RTX5060]', {'ssd_gb': 500}),
                           # CPU 칸이 크기 모양이어도 저장장치로 보지 않는다
                           ('[8500G/250G/Radeon 7]', {'ssd_gb': 256}),
                           ('[12400F/16G/250GB/RTX3050]', None),
                           ('[12400F/16G/250GB/RTX3050]', {'ssd_gb': None}),
                           ('ASUS ROG STRIX [WHITE EDITION]', {'ssd_gb': 256})):
            self.assertEqual(match_storage_shorthand(name, spec), name)


if __name__ == '__main__':
    unittest.main()
