"""상담 주고받기(api/reco_explore + sold_reco + grid_public) — 2026-10-11 중헌 님 지적
「무슨 말을 해도 가장 표준적인 PC 하나로 결론 — 더 높은 사양도, 최저가도, 되묻기도 없다」.

고객 역할 점검(2026-10-11)에서 나온 문장을 그대로 넣어 본다.
"""
import unittest
from unittest.mock import patch

from api import grid_public as G
from api import reco_explore as X
from api import sold_reco as S
from api.talk_schema import GameState, TalkState, Vocab
from tests.test_grid_recommend_public_response import FakeEngine, NOT_PUBLIC_ITEM

LEVELS = [
    {'usage': '게임', 'level': '캐주얼', 'level_rank': 1, 'work': '롤·발로란트 FHD', 'conditions': None},
    {'usage': '게임', 'level': 'FHD', 'level_rank': 2, 'work': '최신 대작 FHD', 'conditions': None},
    {'usage': '게임', 'level': 'QHD', 'level_rank': 3, 'work': '최신 대작 QHD', 'conditions': None},
    {'usage': '영상편집', 'level': '기본', 'level_rank': 1, 'work': 'FHD 컷편집', 'conditions': None},
    {'usage': '영상편집', 'level': '쾌적', 'level_rank': 2, 'work': '4K 편집·색보정', 'conditions': None},
]


def pc(code, price, rank, gpu_idx, ram=16, ssd=500, gpu='RTX 5060 8GB', includes=None, video=1, gap=0):
    return {'code': code, 'name': f'PC {code}', 'price': price, 'price_src': '현재 판매가',
            'status': '판매중', 'url': None, 'includes': includes,
            'spec': {'cpu': 'i5-14400F', 'gpu': gpu, 'ram_gb': ram, 'ssd_gb': ssd, 'vram_gb': 8,
                     'cpu_mt': 20000, 'cpu_st': 2000, 'gpu_idx': gpu_idx},
            'balance': None, 'dominated_by': None, 'band': None,
            'fit': {'게임': {'level': 'x', 'rank': rank, 'blocked': [f'램 {n}GB 미만' for n in range(gap)]},
                    '영상편집': {'level': 'x', 'rank': video, 'blocked': []}}}


# 캐주얼 120만(3050) · FHD 130만(5060, 다음 수준까지 셋 부족) · FHD 158만(5060 Ti, 하나 부족)
# · FHD 205만(5070, 하나 부족) · QHD 263만(5070 Ti, 모니터 포함) · QHD 320만(5080)
PRODUCTS = {
    1: pc(1, 1199600, 1, 60, gpu='RTX 3050 6GB'),
    2: pc(2, 1300000, 2, 100, gap=3),
    3: pc(3, 1585100, 2, 118, gpu='RTX 5060 Ti 8GB', gap=1),
    4: pc(4, 2046500, 2, 150, ram=32, ssd=1000, gpu='RTX 5070 12GB', video=2, gap=1),
    5: pc(5, 2633700, 3, 195, ram=32, ssd=2000, gpu='RTX 5070 Ti 16GB', includes='모니터', video=2),
    6: pc(6, 3200000, 3, 240, ram=32, ssd=2000, gpu='RTX 5080 16GB', video=2),
}


def sets(state, explore=None, tags=None, products=None):
    with patch.object(S, 'load', lambda: (LEVELS, products or PRODUCTS)), \
         patch.object(S, 'public_codes', lambda: frozenset()), \
         patch.object(X, 'part_tags', lambda: tags or {}):
        games = [u for u in state.usages if u == '게임']
        return S.card_sets(state, games, [u for u in state.usages if u != '게임'], [], None, explore)


def codes(cs):
    return [(i['product_code'], i['role']) for i in cs['items']]


GAME = dict(usages=['게임'], game=GameState(resolution='1080p'))


class ExtractTest(unittest.TestCase):
    def test_reads_the_customer_sentences_from_the_role_test(self):
        cases = {
            '램 64기가로 올려주세요': {'min_ram_gb': 64},
            '배그랑 스팀게임 이것저것 170 정도 흰색 케이스': {'white': True},
            '영상편집용 300만원, 램 32GB 이상, 저장공간 2TB 이상으로 해주세요': {'min_ram_gb': 32, 'min_ssd_gb': 2000},
            '배그 할라는데 그래픽카드 4060이면 됨?': {'gpu_model': 'RTX 4060'},
            'RTX 4070 Ti 이상으로요': {'gpu_model': 'RTX 4070 Ti'},
            '조용한 컴퓨터요': {'silent': True},
            '모니터도 같이 사면 얼마': {'monitor': True},
            '다빈치 리졸브로 4K 편집할 거예요. 400만원': {'uhd': True},
        }
        for text, want in cases.items():
            got = X.extract(text)
            for k, v in want.items():
                self.assertEqual(got.get(k), v, text)

    def test_direction_words_and_budget_numbers(self):
        self.assertEqual(X.extract('더 싼 거 없어요?')['nav'], X.CHEAPER)
        self.assertEqual(X.extract('롤만 할 건데 제일 싼 거')['nav'], X.CHEAPER)
        self.assertEqual(X.extract('더 좋은 거 보여줘')['nav'], X.BETTER)
        self.assertEqual(X.extract('최고사양으로')['nav'], X.BETTER)
        # 숫자가 있으면 예산 변경이다 — 해석(talk)이 예산을 바꾼다. 방향은 걸지 않는다.
        self.assertNotIn('nav', X.extract('좀 더 싸게 150으로'))
        self.assertNotIn('nav', X.extract('250 이하로 게임 최고사양'))

    def test_more_multi_range_and_negatives(self):
        self.assertEqual(X.extract('램 더 크게 해 주세요')['more'], ['ram'])
        self.assertEqual(X.extract('저장공간 좀 더 늘려 주세요')['more'], ['ssd'])
        self.assertTrue(X.extract('직원용 사무 PC 5대 사려고요')['multi'])
        self.assertTrue(X.extract('10대 필요해요')['multi'])
        self.assertNotIn('budget_range', X.extract('대학생인데 게임용 컴퓨터 100만원대'))   # 예산은 파서 몫
        self.assertNotIn('monitor', X.extract('모니터는 있어요'))
        self.assertNotIn('gpu_model', X.extract('예산 1500000원'))       # 그래픽 맥락 없는 네 자리 수
        self.assertEqual(X.extract(''), {})

    def test_client_wants_are_cleaned(self):
        self.assertEqual(X.clean_wants({'min_ram_gb': 32, 'white': True, 'gpu_model': 'RTX 4070',
                                        'silent': 'yes', 'min_ssd_gb': '2TB', 'evil': 1,
                                        'monitor': False}),
                         {'min_ram_gb': 32, 'white': True, 'gpu_model': 'RTX 4070'})
        self.assertEqual(X.clean_wants({'gpu_model': '<script>'}), {})
        self.assertEqual(X.clean_wants(None), {})


class SpectrumTest(unittest.TestCase):
    def test_budget_shows_value_recommended_and_higher(self):
        cs = sets(TalkState(**GAME, budget_won=2300000, budget_bound='이하'))[0]
        self.assertEqual(codes(cs), [(2, 'value'), (3, 'recommended'), (4, 'premium')])
        self.assertEqual(cs['items'][-1]['tag'], '더 높은 사양')
        self.assertFalse(cs['items'][-1]['over_budget'])

    def test_higher_card_may_go_a_little_over_budget_and_says_so(self):
        cs = sets(TalkState(**GAME, budget_won=1700000, budget_bound='이하'))[0]
        self.assertEqual(codes(cs)[-1], (4, 'premium'))
        self.assertTrue(cs['items'][-1]['over_budget'])
        # 예산의 1.3배를 넘는 것은 내밀지 않는다.
        cs = sets(TalkState(**GAME, budget_won=1400000, budget_bound='이하'),
                  products={c: PRODUCTS[c] for c in (2, 5)})[0]
        self.assertEqual(codes(cs), [(2, 'recommended')])

    def test_no_budget_steps_up(self):
        cs = sets(TalkState(**GAME))[0]
        self.assertEqual(codes(cs), [(2, 'value'), (5, 'recommended'), (6, 'premium')])
        prices = [i['price'] for i in cs['items']]
        self.assertEqual(prices, sorted(prices))

    def test_higher_card_prefers_a_public_pc_with_photo(self):
        # 2026-10-11 개발 서버: 사진·소개 없는 PC가 「더 높은 사양」에 올랐다 — pick 과 같은 공개 승인 우선(#50).
        prods = {**PRODUCTS, 7: pc(7, 2100000, 2, 160, ram=32, ssd=1000, gpu='RTX 5070 12GB', gap=1)}
        state = TalkState(**GAME, budget_won=2300000, budget_bound='이하')
        self.assertEqual(codes(sets(state, products=prods)[0])[-1], (7, 'premium'))
        with patch.object(S, 'load', lambda: (LEVELS, prods)), \
             patch.object(S, 'public_codes', lambda: frozenset({3, 4})), \
             patch.object(X, 'part_tags', lambda: {}):
            cs = S.card_sets(state, ['게임'], [], [], None, None)[0]
        self.assertEqual(codes(cs)[-1], (4, 'premium'))

    def test_reference_only_gets_no_higher_card_beyond_the_limit(self):
        # 예산을 넘는 최저가(130만)보다 높은 사양이 예산의 1.3배(117만) 안에 없으면 한 장 그대로.
        cs = sets(TalkState(**GAME, budget_won=900000, budget_bound='이하'))[0]
        self.assertEqual(codes(cs), [(2, 'reference')])

    def test_over_budget_cheapest_still_gets_a_higher_card(self):
        # 2026-10-11 개발 서버 「배그와 롤 150만원」: 예산 초과 한 장만 나와 고를 폭이 없었다.
        cs = sets(TalkState(**GAME, budget_won=1250000, budget_bound='이하'))[0]
        self.assertEqual(codes(cs), [(2, 'reference'), (3, 'premium')])
        self.assertTrue(cs['items'][-1]['over_budget'])
        self.assertLessEqual(cs['items'][-1]['price'], 1250000 * S.PREMIUM_OVER_X)
        self.assertEqual(cs['explore']['anchor_code'], 2)
        self.assertTrue(cs['explore']['has_better'])


class ConditionTest(unittest.TestCase):
    def test_ram_and_ssd_are_applied(self):
        ex = {'wants': {'min_ram_gb': 32, 'min_ssd_gb': 1000}}
        cs = sets(TalkState(**GAME, budget_won=3000000, budget_bound='이하'), ex)[0]
        self.assertTrue(all(PRODUCTS[c]['spec']['ram_gb'] >= 32 for c, _ in codes(cs)))
        self.assertEqual(cs['explore']['applied'], ['램 32GB 이상', '저장공간 1TB 이상'])
        self.assertEqual(cs['explore']['unmet'], [])

    def test_impossible_condition_is_said_not_promised(self):
        ex = {'wants': {'min_ram_gb': 64, 'white': True}}
        cs = sets(TalkState(**GAME, budget_won=2000000, budget_bound='이하'), ex, tags={9: {'white': True}})[0]
        self.assertEqual([u[0] for u in cs['explore']['unmet']], ['램 64GB 이상', '흰색 케이스'])
        self.assertTrue(cs['items'])                       # 카드는 조건 없이 그대로 보여 준다

    def test_white_case_from_part_tags(self):
        ex = {'wants': {'white': True}}
        cs = sets(TalkState(**GAME, budget_won=2300000, budget_bound='이하'), ex,
                  tags={4: {'white': True, 'silent': False}})[0]
        self.assertEqual([c for c, _ in codes(cs)], [4])
        self.assertEqual(cs['explore']['applied'], ['흰색 케이스'])

    def test_gpu_model_floor_comes_from_sold_pcs_with_that_model(self):
        cs = sets(TalkState(**GAME), {'wants': {'gpu_model': 'RTX 5070'}})[0]
        self.assertTrue(all(PRODUCTS[c]['spec']['gpu_idx'] >= 150 for c, _ in codes(cs)))
        cs = sets(TalkState(**GAME), {'wants': {'gpu_model': 'RTX 4090'}})[0]
        self.assertEqual(cs['explore']['unmet'][0][0], '그래픽카드 RTX 4090급 이상')

    def test_monitor_included(self):
        cs = sets(TalkState(**GAME), {'wants': {'monitor': True}})[0]
        self.assertEqual([c for c, _ in codes(cs)], [5])

    def test_ram_more_uses_the_card_being_looked_at(self):
        ex = {'wants': {}, 'anchor_code': 3, 'more': ['ram']}
        cs = sets(TalkState(**GAME), ex)[0]
        self.assertEqual(ex['wants']['min_ram_gb'], 32)
        self.assertTrue(all(PRODUCTS[c]['spec']['ram_gb'] >= 32 for c, _ in codes(cs)))
        ex = {'wants': {}, 'more': ['ram']}
        sets(TalkState(**GAME), ex)
        self.assertEqual(ex['talk_notes'], [X.NOTE_MORE_NO_ANCHOR])

    def test_uhd_raises_video_level(self):
        cs = sets(TalkState(usages=['영상편집']), {'wants': {'uhd': True}})[0]
        self.assertEqual(cs['min_level'], '쾌적')
        self.assertTrue(all(c in (4, 5) for c, _ in codes(cs)))


class NavigationTest(unittest.TestCase):
    def test_cheaper_than_the_card_being_looked_at(self):
        cs = sets(TalkState(**GAME, budget_won=2300000, budget_bound='이하'),
                  {'wants': {}, 'nav': X.CHEAPER, 'anchor_code': 3})[0]
        self.assertTrue(all(i['price'] < PRODUCTS[3]['price'] for i in cs['items']))
        self.assertEqual(cs['explore']['nav_note'], X.NOTE_CHEAPER)

    def test_cheaper_when_nothing_cheaper(self):
        cs = sets(TalkState(**GAME), {'wants': {}, 'nav': X.CHEAPER, 'anchor_code': 2})[0]
        self.assertEqual(cs['explore']['nav_note'], X.NOTE_CHEAPER_NONE)
        self.assertTrue(cs['items'])

    def test_better_than_the_card_being_looked_at(self):
        cs = sets(TalkState(**GAME, budget_won=1700000, budget_bound='이하'),
                  {'wants': {}, 'nav': X.BETTER, 'anchor_code': 3})[0]
        self.assertTrue(all(i['price'] > PRODUCTS[3]['price'] for i in cs['items']))
        self.assertTrue(all(i['over_budget'] for i in cs['items']))     # 고객 예산 기준으로 표시
        self.assertEqual(cs['explore']['nav_note'], X.NOTE_BETTER)

    def test_better_at_the_top(self):
        cs = sets(TalkState(**GAME), {'wants': {}, 'nav': X.BETTER, 'anchor_code': 6})[0]
        self.assertEqual(cs['explore']['nav_note'], X.NOTE_BETTER_NONE)

    def test_choice_flags_follow_the_recommended_card(self):
        cs = sets(TalkState(**GAME, budget_won=2300000, budget_bound='이하'))[0]
        e = cs['explore']
        self.assertEqual(e['anchor_code'], 3)
        self.assertTrue(e['has_cheaper'] and e['has_better'])


class RecommendEndpointTest(unittest.TestCase):
    def call(self, state, **body):
        with patch.object(G, 'engine', FakeEngine()), \
             patch.object(G, 'RECO_SOURCE', 'sold'), \
             patch.object(G, 'load_vocab', lambda conn: Vocab()), \
             patch.object(G, 'validate_state', lambda raw, vocab: (state, [])), \
             patch.object(G, 'missing_for', lambda st, vocab: []), \
             patch.object(G, 'usage_map', lambda: {}), \
             patch.object(G, '_game_context', lambda conn, names, vocab: None), \
             patch.object(S, 'load', lambda: (LEVELS, PRODUCTS)), \
             patch.object(S, 'public_codes', lambda: frozenset()), \
             patch.object(X, 'part_tags', lambda: {}), \
             patch.object(G._PC_OFFER, 'public_item', lambda code: dict(NOT_PUBLIC_ITEM)):
            return G.recommend(G.RecommendBody(state={'usages': ['게임']}, **body))

    def test_plain_request_offers_choices_and_asks(self):
        d = self.call(TalkState(**GAME, budget_won=2300000, budget_bound='이하'))
        self.assertEqual([c['id'] for c in d['choices'] if c['enabled']], ['cheaper', 'better', 'change'])
        self.assertEqual(d['anchor_code'], 3)
        self.assertEqual(d['talk_notes'], [X.ASK_NEXT])
        self.assertNotIn('explore', d['card_sets'][0])

    def test_prefs_read_by_the_parser_become_conditions(self):
        d = self.call(TalkState(**GAME, budget_won=2300000, budget_bound='이하', prefs=['화이트']))
        self.assertTrue(d['wants']['white'])
        self.assertIn('「흰색 케이스」 조건은 지금 못 맞춥니다.', ' '.join(d['talk_notes']))

    def test_unmet_is_said_and_wants_round_trip(self):
        d = self.call(TalkState(**GAME, budget_won=2000000, budget_bound='이하'), text='램 64기가로 올려주세요')
        self.assertIn('「램 64GB 이상」 조건은 지금 못 맞춥니다.', d['talk_notes'][0])
        self.assertEqual(d['wants'], {'min_ram_gb': 64})

    def test_quick_choice_button(self):
        d = self.call(TalkState(**GAME, budget_won=2300000, budget_bound='이하'), nav='cheaper', anchor_code=3)
        self.assertEqual(d['talk_notes'][0], X.NOTE_CHEAPER)
        self.assertTrue(all(i['price'] < PRODUCTS[3]['price'] for i in d['card_sets'][0]['items']))

    def test_over_budget_single_card_says_so_and_asks_only_what_can_be_pressed(self):
        # 2026-10-11 개발 서버 「발로 100만원」: 예산 초과 한 장인데 「맞춰 볼게요」·「더 싼 PC나」라고 했다.
        d = self.call(TalkState(**GAME, budget_won=900000, budget_bound='이하'))
        self.assertEqual([c['id'] for c in d['choices'] if c['enabled']], ['better', 'change'])
        # 얼마나 넘는지까지 말한다 -- 카드 줄(「예산보다 ○원 높아요」)과 같은 표현(2026-10-12).
        self.assertEqual(d['talk_notes'], ['90만원 안에는 맞는 PC가 없어요. 가장 가까운 PC는 예산보다 400,000원 높아요.',
                                           X.ASK_BETTER_ONLY])

    def test_ask_matches_the_enabled_buttons(self):
        self.assertEqual(X.ask_next(True, True), X.ASK_NEXT)
        self.assertEqual(X.ask_next(True, False), X.ASK_CHEAPER_ONLY)
        self.assertEqual(X.ask_next(False, True), X.ASK_BETTER_ONLY)
        self.assertIsNone(X.ask_next(False, False))
        self.assertEqual(X.over_budget_sentence(1234500), '1,234,500원 안에는 맞는 PC가 없어서 가장 가까운 PC를 보여 드려요.')
        self.assertEqual(X.over_budget_sentence(1500000, 1624400),
                         '150만원 안에는 맞는 PC가 없어요. 가장 가까운 PC는 예산보다 124,400원 높아요.')

    def test_multi_pc_is_honest(self):
        d = self.call(TalkState(**GAME), text='직원용 PC 5대 사려고요')
        self.assertEqual(d['talk_notes'][0], X.NOTE_MULTI)

    def test_internal_scores_stay_out(self):
        import json
        d = self.call(TalkState(**GAME), text='RTX 5070 이상, 더 좋은 거')
        body = json.dumps(d, ensure_ascii=False)
        for internal in ('gpu_idx', 'cpu_mt', '지수'):
            self.assertNotIn(internal, body)


if __name__ == '__main__':
    unittest.main()
