"""G01(2026-10-20 중헌 님 신고) -- 가벼운 게임에 과도한 가격·성능 추천.

신고 원문 입력 세 줄(공백·철자 그대로): 「한게임 포커용」 · 「캐주얼 게임용」 · 「발로란트 게임용」.
예전에는 셋 다 FHD 대작 수준(RTX 5060 이상)에서 시작했고, 예산이 없으면 한 단계 위 + 더 높은 사양을
스스로 얹어 260만·320만원대 카드가 나왔다.

이 파일은 DB·LLM 없이 sold_reco.card_sets 를 고정 상품표(가짜 상품번호 9xx)로 돌린다.
가격·상품번호는 시험용 값이고 운영 상품의 정답이 아니다(정답을 SKU 로 박지 않는다 -- 판정은 수준·공개 여부·가격 순서로 한다).

    실행: DATABASE_URL=postgresql+psycopg2://x:y@127.0.0.1:1/z python3 -m pytest -q tests/test_casual_game_fit_20261020.py
    추적: G01_TRACE=<경로.json> 을 주면 입력별 분류·요구 수준·전체 후보·제외 이유·선택을 그 파일에 적는다.
"""
import json
import os
import unittest
from unittest.mock import patch

from api import reco_explore as X
from api import sold_reco as S
from api.talk_schema import GameState, TalkState, Vocab

LEVELS = [
    {'usage': '게임', 'level': '캐주얼', 'level_rank': 1, 'work': '롤·발로란트 FHD', 'conditions': None},
    {'usage': '게임', 'level': 'FHD', 'level_rank': 2, 'work': '최신 대작 FHD', 'conditions': None},
    {'usage': '게임', 'level': 'QHD', 'level_rank': 3, 'work': '최신 대작 QHD', 'conditions': None},
    {'usage': '사무용', 'level': '기본', 'level_rank': 1, 'work': '문서·웹', 'conditions': None},
]

VOCAB = Vocab(
    grades=[{'grade': 'E'}, {'grade': 'C'}],
    confirmed_games={'리그 오브 레전드': 'E', '발로란트': 'E'},
    all_game_names=['리그 오브 레전드', '발로란트', '배틀그라운드'],
    game_aliases={'롤': '리그 오브 레전드', '발로': '발로란트', '배그': '배틀그라운드'},
    grade_weight={'E': 1, 'C': 3},
    usages=[('고사양 게임', []), ('캐주얼 게임', [])],
)


def pc(code, price, game_rank, office_rank, gpu, gpu_idx, game_blocked=()):
    return {'code': code, 'name': f'시험 PC {code}', 'price': price, 'price_src': '시험 고정가',
            'status': '판매중', 'url': None, 'includes': None,
            'spec': {'cpu': 'i3-12100' if gpu_idx < 30 else 'i5-14400F', 'gpu': gpu, 'ram_gb': 16, 'ssd_gb': 500,
                     'vram_gb': 0 if gpu_idx < 30 else 8, 'cpu_mt': 12000, 'cpu_st': 1800, 'gpu_idx': gpu_idx},
            'balance': None, 'dominated_by': None, 'band': None,
            'fit': {'게임': {'level': 'x', 'rank': game_rank, 'blocked': list(game_blocked)},
                    '사무용': {'level': 'x', 'rank': office_rank, 'blocked': []}}}


# 공개(승인) 여부가 핵심 축이다: 공개 저가 오피스 · 비공개 더 싼 오피스 · 비공개 760M · 공개 3050 · 공개 5060 이상.
PRODUCTS = {
    901: pc(901, 590000, 0, 1, '내장그래픽', 10, ['외장 그래픽 없음']),     # 공개 · 오피스 최저 수준
    902: pc(902, 520000, 0, 1, '내장그래픽', 10, ['외장 그래픽 없음']),     # 비공개 · 더 싸다 -> 나오면 안 된다
    903: pc(903, 700000, 1, 1, 'Radeon 760M', 25),                         # 비공개 · 캐주얼 게임 수준
    904: pc(904, 1199600, 1, 1, 'RTX 3050 6GB', 60),                       # 공개 · 캐주얼 게임 수준
    905: pc(905, 1625800, 2, 1, 'RTX 5060 8GB', 100),                      # 공개 · FHD 대작 수준
    906: pc(906, 2622000, 3, 1, 'RTX 5070 Ti 16GB', 195),                  # 공개 · QHD
    907: pc(907, 3220500, 3, 1, 'RTX 5080 16GB', 240),                     # 공개 · QHD
}
PUBLIC = frozenset({901, 904, 905, 906, 907})
NO_LIGHT_PUBLIC = frozenset({905, 906, 907})     # 「적정 저가 공개 상품 없음」 상황

INPUTS = {
    '한게임 포커용': dict(names=['한게임 포커']),
    '캐주얼 게임용': dict(names=[]),
    '발로란트 게임용': dict(names=['발로란트']),
}


def state_of(raw, budget=None, bound=None):
    g = INPUTS[raw]
    return TalkState(usages=['캐주얼 게임'], game=GameState(names=g['names'], resolution='1080p'),
                     budget_won=budget, budget_bound=bound)


def run(state, text='', public=PUBLIC, explore=None):
    notes = []
    if explore is None and text:
        w = X.extract(text)
        explore = {'wants': {k: v for k, v in w.items() if k != 'nav'}, 'nav': w.get('nav'), 'anchor_code': None}
    with patch.object(S, 'load', lambda: (LEVELS, PRODUCTS)), \
         patch.object(S, 'public_codes', lambda: public), \
         patch.object(S, 'load_custom_pcs', lambda n: []), \
         patch.object(X, 'part_tags', lambda: {}):
        sets = S.card_sets(state, ['캐주얼 게임'], [], notes, VOCAB, explore)
    return sets[0], notes


def chosen(cs):
    return [(i['product_code'], i['role'], i['price']) for i in cs['items']]


TRACE = []


def trace(case, raw, cs, notes, public, text=''):
    target = next((n for n in notes if n.startswith('sold: light games')), None)
    usage = cs['usage_grid']
    need = next(l['level_rank'] for l in LEVELS if l['usage'] == usage and l['level'] == cs['min_level'])
    picked = {i['product_code'] for i in cs['items']}
    rows = []
    for code, p in sorted(PRODUCTS.items()):
        rank = p['fit'][usage]['rank']
        if code in picked:
            why = '선택'
        elif code not in public:
            why = '비공개(configuration_public=false) -- 가벼운 수요는 공개 구성만'
        elif need is not None and rank < need:
            why = f'{usage} 수준 {rank} < 요구 {need}'
        else:
            why = '요구 수준을 넘는 더 비싼 구성 -- 자동으로 얹지 않음'
        rows.append({'code': code, 'gpu': p['spec']['gpu'], 'price': p['price'], 'public': code in public,
                     f'{usage}_rank': rank, 'result': why})
    TRACE.append({'case': case, 'input': raw, 'extra_text': text,
                  'classification': '웹보드·가벼운 게임 -> 사무용 수준' if target else '게임',
                  'alias': [n for n in notes if 'light games' in n] or None,
                  'required': {'usage': usage, 'rank': need, 'level': cs['min_level'], 'work': cs.get('min_level_work')},
                  'explore': cs.get('explore'),
                  'demand_notes': (cs.get('demand') or {}).get('notes'),
                  'chosen': chosen(cs), 'empty_reason': cs.get('empty_reason'),
                  'candidates': rows, 'engine_notes': notes})


class OriginalInputs(unittest.TestCase):
    """신고 원문 세 줄 -- 예산 없음."""

    def test_poker_gets_one_public_office_pc(self):
        cs, notes = run(state_of('한게임 포커용'))
        trace('원문 · 예산 없음', '한게임 포커용', cs, notes, PUBLIC)
        self.assertEqual(chosen(cs), [(901, 'recommended', 590000)])       # 공개 오피스 최저 수준 한 장
        self.assertTrue(cs['demand']['light'])
        self.assertNotIn(902, [c for c, _, _ in chosen(cs)])                 # 비공개 더 싼 것은 제외

    def test_casual_unnamed_gets_casual_level_not_5060(self):
        cs, notes = run(state_of('캐주얼 게임용'))
        trace('원문 · 예산 없음', '캐주얼 게임용', cs, notes, PUBLIC)
        self.assertEqual(chosen(cs), [(904, 'recommended', 1199600)])      # 캐주얼 수준 공개 최저(760M 은 비공개)
        self.assertTrue(cs['demand']['light'])
        self.assertTrue(any('어떤 게임' in n or '게임' in n for n in cs['demand']['notes']))

    def test_valorant_gets_casual_level_one_card(self):
        cs, notes = run(state_of('발로란트 게임용'))
        trace('원문 · 예산 없음', '발로란트 게임용', cs, notes, PUBLIC)
        self.assertEqual(chosen(cs), [(904, 'recommended', 1199600)])
        self.assertFalse(any('light games' in n for n in notes))            # 포커와 다른 분류(게임 수준)

    def test_no_card_above_two_million(self):
        for raw in INPUTS:
            cs, _ = run(state_of(raw))
            self.assertTrue(all(p < 2000000 for _, _, p in chosen(cs)), raw)


class Conditions(unittest.TestCase):
    def test_value_word_does_not_raise_anything(self):
        for raw in INPUTS:
            cs, notes = run(state_of(raw), text='가성비로')
            trace('가성비', raw, cs, notes, PUBLIC, '가성비로')
            self.assertEqual(chosen(cs), chosen(run(state_of(raw))[0]), raw)

    def test_cheaper_never_goes_up(self):
        for raw in INPUTS:
            base = max(p for _, _, p in chosen(run(state_of(raw))[0]))
            cs, notes = run(state_of(raw), text='더 저렴하게')
            trace('더 저렴하게', raw, cs, notes, PUBLIC, '더 저렴하게')
            self.assertTrue(all(p <= base for _, _, p in chosen(cs)), raw)
            self.assertTrue(all(c in PUBLIC for c, _, _ in chosen(cs)), raw)

    def test_budget_cap_is_not_a_spending_target(self):
        for raw in INPUTS:
            cs, notes = run(state_of(raw, 3500000, '이하'))
            trace('예산 상한 350만', raw, cs, notes, PUBLIC)
            self.assertNotIn(907, [c for c, _, _ in chosen(cs)], raw)
            self.assertNotIn('premium', [r for _, r, _ in chosen(cs)], raw)
            self.assertLess(chosen(cs)[0][2], 1300000, raw)

    def test_better_on_request_shows_higher_with_reason(self):
        cs, notes = run(state_of('캐주얼 게임용'), explore={'wants': {}, 'nav': X.BETTER, 'anchor_code': 904})
        trace('더 좋게(고객 요청)', '캐주얼 게임용', cs, notes, PUBLIC, '더 좋은 걸로')
        self.assertTrue(all(p > 1199600 for _, _, p in chosen(cs)))


class Valorant(unittest.TestCase):
    def test_high_refresh_raises_level(self):
        for text in ('발로란트 144Hz로 하고 싶어요', '240fps 목표'):
            cs, notes = run(state_of('발로란트 게임용'), text=text)
            trace('144/240Hz', '발로란트 게임용', cs, notes, PUBLIC, text)
            self.assertEqual(chosen(cs)[0][:2], (905, 'recommended'), text)   # FHD 대작 수준으로 올린다
            self.assertTrue(any('주사율' in n or 'Hz' in n or '프레임' in n for n in cs['demand']['notes']), text)

    def test_sixty_fps_stays_casual(self):
        cs, notes = run(state_of('발로란트 게임용'), text='60프레임이면 충분해요')
        trace('60FPS', '발로란트 게임용', cs, notes, PUBLIC, '60프레임이면 충분해요')
        self.assertEqual(chosen(cs)[0][0], 904)

    def test_streaming_is_a_separate_usage_set(self):
        # 방송 동시 작업은 「방송」 용도 묶음이 따로 정한다 -- 게임 묶음의 가벼운 판정은 그대로다.
        st = TalkState(usages=['캐주얼 게임', '방송'], game=GameState(names=['발로란트'], resolution='1080p'))
        notes = []
        with patch.object(S, 'load', lambda: (LEVELS, PRODUCTS)), \
             patch.object(S, 'public_codes', lambda: PUBLIC), \
             patch.object(S, 'load_custom_pcs', lambda n: []), \
             patch.object(X, 'part_tags', lambda: {}):
            sets = S.card_sets(st, ['캐주얼 게임'], ['방송'], notes, VOCAB, None)
        self.assertEqual(chosen(sets[0])[0][0], 904)


class Names(unittest.TestCase):
    def test_name_gate(self):
        def ok(names):
            return S.game_names_ok(TalkState(usages=['캐주얼 게임'], game=GameState(names=names)), VOCAB)
        self.assertTrue(ok(['한게임 포커']))
        self.assertTrue(ok(['캐주얼 게임']))
        self.assertTrue(ok([]))
        self.assertFalse(ok(['처음 듣는 게임']))          # 알 수 없는 실제 게임 이름은 예전처럼 보류(등급 확인)
        self.assertFalse(ok(['한게임 포커', '처음 듣는 게임']))   # 하나라도 가볍지 않으면 가벼운 판정 아님


class Shortage(unittest.TestCase):
    def test_no_public_light_pc_explains_instead_of_silently_upgrading(self):
        cs, notes = run(state_of('한게임 포커용'), public=NO_LIGHT_PUBLIC)
        trace('적정 저가 공개 상품 없음', '한게임 포커용', cs, notes, NO_LIGHT_PUBLIC)
        got = chosen(cs)
        self.assertNotIn(902, [c for c, _, _ in got])
        self.assertNotIn(901, [c for c, _, _ in got])
        if got:
            # 위 수준을 낸다면 «필요한 사양보다 높다»는 사실을 함께 적는다(조용히 끼워 넣지 않는다)
            self.assertIn(S.LIGHT_ABOVE_NOTE, cs['demand']['notes'])
            self.assertEqual(len(got), 1)
        else:
            self.assertTrue(cs.get('empty_reason'))

    def test_non_public_never_appears_for_light_demand(self):
        for raw in INPUTS:
            for budget in (None, 800000):
                cs, _ = run(state_of(raw, budget, '이하' if budget else None))
                self.assertTrue(all(c in PUBLIC for c, _, _ in chosen(cs)), (raw, budget))


def tearDownModule():
    path = os.environ.get('G01_TRACE')
    if path:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(TRACE, f, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
