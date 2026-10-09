"""POST /api/grid/recommend (kind='sold') keeps the MVP3 field contract and leaks
no internal evaluation scores or raw DB error text (collaboration item 6).

Contract: https://github.com/davidchoi2060-art/popcorn-ai/pull/2#issuecomment-6054476845
"""
import json
import pathlib
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from api import grid_public as G
from api import sold_reco as S
from api.talk_schema import GameState, TalkState, Vocab

TOP_KEYS = {'ok', 'card_sets', 'cards', 'assumed', 'ai_estimated', 'needs', 'dropped',
            'platform', 'budget_won', 'budget_bound', 'game_grade', 'game_resolution', 'game_name'}
SET_KEYS = {'usage', 'usage_grid', 'kind', 'items', 'empty_reason', 'empty_note',
            'min_level', 'min_level_work'}
ITEM_KEYS = {'product_code', 'name', 'price', 'price_src', 'mall_url', 'spec', 'level',
             'tag', 'role', 'over_budget', 'reasons', 'photo', 'public_configuration'}
# 공개 구성·대표 사진 판정(customer_pc_offer)은 자기 검사가 지킨다. 여기서는 공개 아님 값으로 고정.
NOT_PUBLIC_ITEM = {'photo': {'state': 'unavailable', 'url': None}, 'public_configuration': None}
PUBLIC_SPEC = {'cpu', 'gpu', 'ram_gb', 'ssd_gb', 'vram_gb'}
FIXTURE = pathlib.Path(__file__).parent / 'fixtures' / 'grid_recommend_sold_response.json'
GAME_CONTEXT = {
    'game_name': '배틀그라운드', 'spec_summary': 'FHD 높음 옵션 기준 RTX 4060급 이상',
    'why_this_pc': 'FHD 높음 옵션에서 60fps 이상을 목표로 한 구성입니다.',
    'upgrade_hint': 'QHD로 올리려면 그래픽카드 상향이 먼저입니다.', 'caution': None,
    'source': {'kind': 'game_customer_copy', 'fields': ['why_this_pc'], 'url': None},
    'confidence': 'reviewed', 'reviewed_at': '2026-10-01T00:00:00+09:00'}
DB_ERROR = 'OperationalError: connection to server at "10.20.30.40" failed: password authentication failed'

LEVELS = [
    {'usage': '게임', 'level': '기본', 'level_rank': 1, 'work': '캐주얼 게임', 'conditions': None},
    {'usage': '게임', 'level': 'FHD', 'level_rank': 2, 'work': 'FHD 게임',
     'conditions': '그래픽 지수 100 이상 · 램 16GB 이상 · SSD 480GB 이상 · CPU 게임 등급 1.0 이상'},
    {'usage': '게임', 'level': 'QHD', 'level_rank': 3, 'work': 'QHD 게임', 'conditions': None},
    {'usage': '영상편집', 'level': '기본', 'level_rank': 1, 'work': 'FHD 편집', 'conditions': None},
]


def product(code, price):
    return {'code': code, 'name': f'조립PC {code}', 'price': price, 'price_src': '현재 판매가',
            'status': '판매중', 'url': f'https://mall.example/{code}', 'includes': None,
            'spec': {'cpu': '라이젠5 9600', 'gpu': 'RTX 5060 Ti 8GB', 'ram_gb': 32, 'ssd_gb': 500,
                     'vram_gb': 8, 'cpu_mt': 16500, 'cpu_st': 2100, 'gpu_idx': 118},
            'balance': None, 'dominated_by': None, 'band': None,
            'fit': {'게임': {'level': 'FHD', 'rank': 2,
                            'blocked': ['그래픽 지수 150 미만(현재 118)', 'CPU 게임 등급 1.1 미만(현재 1.0)',
                                        '램 미확인', '그래픽 지수 195 미만(현재 118)',
                                        'SSD 960GB 미만(현재 500GB)']},
                    '영상편집': {'level': '기본', 'rank': 1,
                             'blocked': ['CPU 멀티 지수 24,000 미만(현재 16,500)']}}}


def qhd_product(code, price):
    p = product(code, price)
    p['fit']['게임'] = {'level': 'QHD', 'rank': 3, 'blocked': ['그래픽 메모리 12GB 미만(현재 8GB)']}
    return p


# 게임: 1(FHD·싼 쪽) + 2(QHD) -> [알뜰 1, 추천 2]. 영상편집: 같은 수준 -> 추천 1 한 장.
PRODUCTS = {1: product(1, 1200000), 2: qhd_product(2, 1500000)}


class FakeEngine:
    @contextmanager
    def connect(self):
        yield SimpleNamespace()


def call_recommend(game_context=None, state=None, needs=()):
    state = state or TalkState(usages=['게임', '영상편집'], budget_won=2000000, budget_bound='이하',
                               game=GameState(names=['배틀그라운드'], grade='C', grade_src='ai_estimate'))
    dropped = [{'field': 'game.resolution', 'value': '8K', 'reason': 'not in vocab'}]
    with patch.object(G, 'engine', FakeEngine()), \
         patch.object(G, 'RECO_SOURCE', 'sold'), \
         patch.object(G, 'load_vocab', lambda conn: Vocab()), \
         patch.object(G, 'validate_state', lambda raw, vocab: (state, dropped)), \
         patch.object(G, 'missing_for', lambda st, vocab: list(needs)), \
         patch.object(G, 'usage_map', lambda: {}), \
         patch.object(G, '_game_context', lambda conn, names, vocab: game_context), \
         patch.object(G, '_record_estimate', lambda st: (False, DB_ERROR)), \
         patch.object(S, 'load', lambda: (LEVELS, PRODUCTS)), \
         patch.object(S, 'public_codes', lambda: frozenset()), \
         patch.object(G._PC_OFFER, 'public_item', lambda code: dict(NOT_PUBLIC_ITEM)):
        return G.recommend(G.RecommendBody(state={'usages': ['게임', '영상편집']}))


class RecommendPublicResponseTest(unittest.TestCase):
    def test_top_level_shape_is_kept_without_notes(self):
        with self.assertLogs('grid_public', level='INFO'):
            d = call_recommend()
        self.assertEqual(set(d), TOP_KEYS)
        self.assertNotIn('notes', d)
        self.assertIs(d['ok'], True)
        self.assertEqual(d['dropped'][0]['field'], 'game.resolution')
        self.assertEqual(d['ai_estimated'], [{'game_names': ['배틀그라운드'], 'grade': 'C'}])

    def test_db_error_text_goes_to_log_not_response(self):
        with self.assertLogs('grid_public', level='INFO') as logs:
            d = call_recommend()
        body = json.dumps(d, ensure_ascii=False)
        for leaked in ('OperationalError', '10.20.30.40', 'password', 'insert failed'):
            self.assertNotIn(leaked, body)
        self.assertTrue(any('insert failed' in line and 'OperationalError' in line
                            for line in logs.output))

    def test_card_sets_and_items_keep_contract_fields(self):
        with self.assertLogs('grid_public', level='INFO'):
            d = call_recommend()
        self.assertEqual([s['usage_grid'] for s in d['card_sets']], ['영상편집', '게임'])
        for s in d['card_sets']:
            self.assertEqual(s['kind'], 'sold')
            self.assertLessEqual(SET_KEYS, set(s))
            self.assertTrue(s['items'])
            self.assertEqual(s['items'][-1]['role'], 'recommended')
            for item in s['items']:
                self.assertEqual(set(item), ITEM_KEYS)
                self.assertEqual(item['mall_url'], f"https://mall.example/{item['product_code']}")

    def test_spec_carries_only_public_keys(self):
        with self.assertLogs('grid_public', level='INFO'):
            d = call_recommend()
        for s in d['card_sets']:
            for item in s['items']:
                self.assertEqual(item['spec'], {'cpu': '라이젠5 9600', 'gpu': 'RTX 5060 Ti 8GB',
                                                'ram_gb': 32, 'ssd_gb': 500, 'vram_gb': 8})
        body = json.dumps(d, ensure_ascii=False)
        for internal in ('cpu_mt', 'cpu_st', 'gpu_idx', '16500', '2100'):
            self.assertNotIn(internal, body)

    def test_reasons_carry_no_internal_scores_or_raw_conditions(self):
        with self.assertLogs('grid_public', level='INFO'):
            d = call_recommend()
        body = json.dumps(d, ensure_ascii=False)
        for internal in ('다음 수준까지는', '충족 조건', '지수', '등급 1.', '미확인', '현재 118', '현재 16,500'):
            self.assertNotIn(internal, body)
        reasons = {s['usage_grid']: s['items'][0]['reasons'] for s in d['card_sets']}
        self.assertEqual(reasons['게임'], [
            '게임 FHD — FHD 게임',
            '다음 수준을 고려한다면 그래픽 처리 성능을 높여 보세요.',
            '다음 수준을 고려한다면 SSD 저장 용량을 늘려 보세요.'])
        self.assertEqual(reasons['영상편집'], [
            '영상편집 기본 — FHD 편집',
            '다음 수준을 고려한다면 여러 작업을 함께 처리할 수 있는 CPU 성능을 높여 보세요.'])

    def test_published_fixture_matches_live_response(self):
        # tests/fixtures/grid_recommend_sold_response.json is the sample the PC side builds
        # against; regenerate it with `python -m tests.test_grid_recommend_public_response`.
        with self.assertLogs('grid_public', level='INFO'):
            d = call_recommend(GAME_CONTEXT)
        self.assertEqual(json.loads(FIXTURE.read_text(encoding='utf-8')), json.loads(json.dumps(d)))

    def test_source_products_are_not_mutated(self):
        with self.assertLogs('grid_public', level='INFO'):
            call_recommend()
        self.assertIn('cpu_mt', PRODUCTS[1]['spec'])


class GameWithoutGradeTest(unittest.TestCase):
    """2026-10-09 조정 결정: 판매 경로는 등급 없이도 추천한다 — 「게임용 250만원」이 0장이었다."""

    def run_state(self, game):
        state = TalkState(usages=['게임'], budget_won=2500000, budget_bound='이하', game=game)
        with self.assertLogs('grid_public', level='INFO'):
            return call_recommend(state=state, needs=['game.grade'])

    def test_game_without_names_or_grade_gets_fhd_cards(self):
        for game in (None, GameState()):
            d = self.run_state(game)
            self.assertEqual(len(d['card_sets']), 1)
            cs = d['card_sets'][0]
            self.assertEqual((cs['usage_grid'], cs['min_level']), ('게임', 'FHD'))
            self.assertEqual([i['product_code'] for i in cs['items']], [1, 2])
            self.assertEqual(d['needs'], ['game.grade'])
            self.assertEqual(d['assumed'], ['game.resolution=1080p'])
            self.assertEqual(d['ai_estimated'], [])
            self.assertIsNone(d['game_grade'])

    def test_resolution_without_grade_sets_level(self):
        d = self.run_state(GameState(resolution='1440p'))
        cs = d['card_sets'][0]
        self.assertEqual(cs['min_level'], 'QHD')
        self.assertEqual([i['product_code'] for i in cs['items']], [2])
        self.assertEqual(d['assumed'], [])

    def test_named_games_without_grade_stay_held(self):
        # validate_state 가 「전체 게임 적합성 확인 전 추천 보류」로 등급을 비운 경우 — 보류 유지.
        d = self.run_state(GameState(names=['목록 밖 게임']))
        self.assertEqual(d['card_sets'], [])
        self.assertEqual(d['needs'], ['game.grade'])
        self.assertEqual(d['assumed'], [])


class PickRuleTest(unittest.TestCase):
    """승인 시안 R01: 카드 두 장은 「알뜰 구성」(싼 쪽, 앞) · 「추천 구성」(강조, 뒤)."""

    @staticmethod
    def p(code, price, rank):
        return {'code': code, 'name': f'PC{code}', 'price': price, 'price_src': '현재 판매가',
                'url': None, 'spec': {}, 'includes': None,
                'fit': {'게임': {'level': f'L{rank}', 'rank': rank, 'blocked': []}}}

    def pick(self, items, budget, bound='이하'):
        prods = {i['code']: i for i in items}
        return S.pick('게임', 1, budget, bound, [], prods)

    def roles(self, res):
        return [(i['product_code'], i['tag'], i['role']) for i in res['items']]

    def test_budget_pair_is_value_then_recommended(self):
        res = self.pick([self.p(1, 900000, 1), self.p(2, 1200000, 2), self.p(3, 1400000, 2),
                         self.p(4, 1600000, 3)], 1500000)
        self.assertEqual(self.roles(res), [(1, '알뜰 구성', 'value'), (2, '추천 구성', 'recommended')])
        self.assertLess(res['items'][0]['price'], res['items'][1]['price'])

    def test_budget_single_when_cheapest_is_best(self):
        res = self.pick([self.p(1, 900000, 2), self.p(2, 1000000, 2), self.p(3, 1100000, 1)], 1500000)
        self.assertEqual(self.roles(res), [(1, '추천 구성', 'recommended')])

    def test_over_budget_reference_is_not_recommended(self):
        res = self.pick([self.p(1, 2000000, 1)], 1500000)
        self.assertEqual(self.roles(res), [(1, '예산을 넘는 최저가', 'reference')])
        self.assertEqual(res['empty_reason'], '예산 안 상품 없음')
        self.assertIs(res['items'][0]['over_budget'], True)

    def test_no_budget_value_then_one_level_up(self):
        res = self.pick([self.p(1, 900000, 1), self.p(2, 1000000, 1), self.p(3, 1300000, 2)], None)
        self.assertEqual(self.roles(res), [(1, '알뜰 구성', 'value'), (3, '추천 구성', 'recommended')])

    def test_no_budget_single_is_recommended(self):
        res = self.pick([self.p(1, 900000, 1), self.p(2, 1000000, 1)], None)
        self.assertEqual(self.roles(res), [(1, '추천 구성', 'recommended')])

    def test_at_least_budget_uses_pool_from_budget(self):
        res = self.pick([self.p(1, 900000, 2), self.p(2, 1600000, 1), self.p(3, 1800000, 2)],
                        1500000, '이상')
        self.assertEqual(self.roles(res), [(2, '알뜰 구성', 'value'), (3, '추천 구성', 'recommended')])

    def test_every_tag_has_a_role_and_old_tags_are_gone(self):
        self.assertEqual(set(S.ROLE_OF.values()), {'value', 'recommended', 'reference'})
        src = pathlib.Path(S.__file__).read_text(encoding='utf-8')
        for old in ('예산 안 최고 수준', '같은 수준 다른 구성', '가장 저렴한 선택', '한 단계 위"'):
            self.assertNotIn(old, src.split('"""', 2)[2])


class PublicPreferenceTest(unittest.TestCase):
    """2026-10-09 조정 결정: 같은 판정 안에서만 고객 공개 승인(사진 있음) 상품을 먼저 고른다."""
    p = staticmethod(PickRuleTest.p)

    def pick(self, items, budget, bound='이하', preferred=frozenset()):
        return S.pick('게임', 1, budget, bound, [], {i['code']: i for i in items}, preferred)

    def roles(self, res):
        return [(i['product_code'], i['role']) for i in res['items']]

    ITEMS = [(1, 900000, 1), (2, 1000000, 1), (3, 1200000, 2), (4, 1400000, 2), (5, 1600000, 3)]

    def items(self):
        return [self.p(*x) for x in self.ITEMS]

    def test_empty_preference_matches_previous_rule(self):
        for budget, bound in ((1500000, '이하'), (None, None), (1300000, '이상'), (800000, '이하')):
            self.assertEqual(self.pick(self.items(), budget, bound),
                             self.pick(self.items(), budget, bound, frozenset({999})))

    def test_recommended_prefers_public_within_top_level(self):
        res = self.pick(self.items(), 1500000, preferred=frozenset({4}))
        self.assertEqual(self.roles(res), [(1, 'value'), (4, 'recommended')])

    def test_public_never_beats_level_or_budget(self):
        # 5 는 예산 밖, 1 은 수준이 낮다 — 승인돼 있어도 추천 자리를 얻지 못한다.
        res = self.pick(self.items(), 1500000, preferred=frozenset({1, 5}))
        self.assertEqual(self.roles(res), [(1, 'value'), (3, 'recommended')])

    def test_value_prefers_public_among_cheaper_than_recommended(self):
        res = self.pick(self.items(), 1500000, preferred=frozenset({2}))
        self.assertEqual(self.roles(res), [(2, 'value'), (3, 'recommended')])

    def test_both_cards_public_when_available(self):
        res = self.pick(self.items(), 1500000, preferred=frozenset({2, 4}))
        self.assertEqual(self.roles(res), [(2, 'value'), (4, 'recommended')])
        self.assertLess(res['items'][0]['price'], res['items'][1]['price'])

    def test_no_budget_prefers_public_at_each_card(self):
        res = self.pick(self.items(), None, preferred=frozenset({2, 4}))
        self.assertEqual(self.roles(res), [(2, 'value'), (4, 'recommended')])

    def test_reference_stays_cheapest_over_budget(self):
        res = self.pick(self.items(), 800000, preferred=frozenset({3}))
        self.assertEqual(self.roles(res), [(1, 'reference')])

    def test_card_sets_reads_public_codes_once_and_passes_them(self):
        state = TalkState(usages=['영상편집'], budget_won=2000000, budget_bound='이하')
        prods = {1: product(1, 1200000), 2: product(2, 1500000)}
        with patch.object(S, 'load', lambda: (LEVELS, prods)), \
             patch.object(S, 'public_codes', lambda: frozenset({2})):
            sets = S.card_sets(state, [], ['영상편집'], [])
        self.assertEqual([i['product_code'] for i in sets[0]['items']], [1, 2])

    def test_public_codes_failure_is_empty(self):
        class Broken:
            def connect(self):
                raise RuntimeError('db down')
        with patch.object(S, 'engine', Broken()), self.assertLogs('sold_reco', level='ERROR'):
            self.assertEqual(S.public_codes(), frozenset())


class GameMinRankTest(unittest.TestCase):
    """여러 게임이면 가장 까다로운 게임이 최소 수준을 정한다 — 용도 최소 수준 밑으로 가지 않는다."""
    LV = [
        {'usage': '게임', 'level': '캐주얼', 'level_rank': 1, 'work': '롤·발로란트·피파·메이플 FHD'},
        {'usage': '게임', 'level': 'FHD', 'level_rank': 2, 'work': '최신 대작 FHD'},
        {'usage': '게임', 'level': 'QHD', 'level_rank': 3, 'work': '최신 대작 QHD'},
    ]
    VOCAB = Vocab(
        confirmed_games={'리그 오브 레전드': 'E', '배틀그라운드': 'E', '발로란트': 'E',
                         '메이플스토리': 'L', 'FC온라인': 'E'},
        all_game_names=['리그 오브 레전드', '배틀그라운드', '발로란트', '메이플스토리', 'FC온라인'],
        game_aliases={'롤': '리그 오브 레전드', '배그': '배틀그라운드'})

    def rank(self, names, grade='E', resolution=None):
        g = GameState(names=names, grade=grade, grade_src='catalog', resolution=resolution)
        return S.game_min_rank(g, self.LV, self.VOCAB, [])

    def test_pubg_with_lol_is_fhd_not_casual(self):
        # 2026-10-09 실사고: 배그·롤 둘 다 E 라 캐주얼로 내려갔다.
        self.assertEqual(self.rank(['배그', '롤']), 2)
        self.assertEqual(self.rank(['롤', '배그']), 2)

    def test_casual_only_when_every_game_is_casual(self):
        self.assertEqual(self.rank(['롤']), 1)
        self.assertEqual(self.rank(['롤', '발로란트']), 1)
        self.assertEqual(self.rank(['메이플'], grade='L'), 1)
        self.assertEqual(self.rank(['배그']), 2)

    def test_resolution_beats_casual_and_no_names_never_casual(self):
        self.assertEqual(self.rank(['롤'], resolution='1440p'), 3)
        self.assertEqual(self.rank([]), 2)
        self.assertEqual(S.game_min_rank(None, self.LV, self.VOCAB, []), 2)
        # 게임명을 대조할 어휘가 없으면 캐주얼로 내리지 않는다.
        self.assertEqual(S.game_min_rank(GameState(names=['롤'], grade='E'), self.LV, None, []), 2)

    def test_unknown_game_is_not_casual(self):
        self.assertEqual(self.rank(['롤', '처음 보는 게임']), 2)

    def test_screenshot_case_returns_reference_not_casual_pc(self):
        # 배그·롤 · 150만원 이하 · FHD: FHD 이상 상품이 예산 안에 없으면 참고 상품 1개.
        def prod(code, price, rank):
            return {'code': code, 'name': f'PC {code}', 'price': price, 'price_src': '현재 판매가',
                    'status': '판매중', 'url': None, 'includes': None, 'spec': {}, 'balance': None,
                    'dominated_by': None, 'band': None,
                    'fit': {'게임': {'level': 'x', 'rank': rank, 'blocked': []}}}
        prods = {93454: prod(93454, 1199600, 1), 98149: prod(98149, 1585100, 2)}
        st = TalkState(usages=['게임'], budget_won=1500000, budget_bound='이하',
                       game=GameState(names=['배그', '롤'], grade='E', grade_src='catalog'))
        with patch.object(S, 'load', lambda: (self.LV, prods)):
            sets = S.card_sets(st, ['게임'], [], [], self.VOCAB)
        self.assertEqual(len(sets), 1)
        self.assertEqual(sets[0]['min_level'], 'FHD')
        self.assertEqual(sets[0]['empty_reason'], '예산 안 상품 없음')
        self.assertEqual([(i['product_code'], i['role']) for i in sets[0]['items']], [(98149, 'reference')])


class UpgradeHintsTest(unittest.TestCase):
    CASES = [
        ('CPU 멀티 지수 20,000 미만(현재 16,500)',
         '다음 수준을 고려한다면 여러 작업을 함께 처리할 수 있는 CPU 성능을 높여 보세요.'),
        ('CPU 싱글 지수 1,950 미만(현재 1,850)', '다음 수준을 고려한다면 CPU의 단일 작업 처리 성능을 높여 보세요.'),
        ('그래픽 지수 150 미만(현재 118)', '다음 수준을 고려한다면 그래픽 처리 성능을 높여 보세요.'),
        ('그래픽 지수 100 미만', '다음 수준을 고려한다면 그래픽 처리 성능을 높여 보세요.'),
        ('그래픽 메모리 12GB 미만(현재 8GB)',
         '다음 수준을 고려한다면 그래픽 메모리 용량이 더 큰 구성을 살펴보세요.'),
        ('그래픽 메모리 8GB 미만', '다음 수준을 고려한다면 그래픽 메모리 용량이 더 큰 구성을 살펴보세요.'),
        ('램 32GB 미만(현재 16GB)', '다음 수준을 고려한다면 메모리 용량을 늘려 보세요.'),
        ('SSD 960GB 미만(현재 500GB)', '다음 수준을 고려한다면 SSD 저장 용량을 늘려 보세요.'),
        ('외장 그래픽 없음', '다음 수준을 고려한다면 별도 그래픽카드가 있는 구성을 살펴보세요.'),
        ('엔비디아 그래픽 아님', '다음 수준은 NVIDIA 그래픽카드가 필요한 조건입니다.'),
    ]

    def test_each_generator_template_maps_to_its_sentence(self):
        for raw, hint in self.CASES:
            with self.subTest(raw=raw):
                self.assertEqual(S.upgrade_hints([raw]), [hint])

    def test_unknown_unmapped_or_partial_kinds_are_omitted_and_logged(self):
        for raw in ('램 미확인', '그래픽 지수 미확인', 'CPU 게임 등급 1.1 미만(현재 1.0)',
                    '고성능 램 32GB 미만(현재 16GB)', 'SSD 960GB 미만(현재 500GB) 및 외장 그래픽 없음',
                    '', None, 42):
            with self.subTest(raw=raw):
                with self.assertLogs('sold_reco', level='INFO'):
                    self.assertEqual(S.upgrade_hints([raw]), [])

    def test_dedup_and_at_most_two_in_source_order(self):
        hints = S.upgrade_hints(['램 32GB 미만(현재 16GB)', '램 64GB 미만(현재 16GB)',
                                 '외장 그래픽 없음', 'SSD 960GB 미만(현재 500GB)'])
        self.assertEqual(hints, ['다음 수준을 고려한다면 메모리 용량을 늘려 보세요.',
                                 '다음 수준을 고려한다면 별도 그래픽카드가 있는 구성을 살펴보세요.'])
        self.assertEqual(S.upgrade_hints([]), [])
        self.assertEqual(S.upgrade_hints(None), [])


class PublicSpecTest(unittest.TestCase):
    def test_filters_to_public_component_fields(self):
        self.assertEqual(S.public_spec({'cpu': 'i5', 'gpu': 7, 'ram_gb': 16, 'ssd_gb': -1,
                                        'vram_gb': True, 'cpu_mt': 1, 'operator_note': 'x'}),
                         {'cpu': 'i5', 'ram_gb': 16})
        self.assertEqual(set(S.public_spec({k: 1 for k in PUBLIC_SPEC})), {'ram_gb', 'ssd_gb', 'vram_gb'})

    def test_string_and_missing_spec(self):
        self.assertEqual(S.public_spec('i5 / RTX 4060'), 'i5 / RTX 4060')
        self.assertIsNone(S.public_spec(None))
        self.assertIsNone(S.public_spec(['cpu']))


if __name__ == '__main__':
    FIXTURE.parent.mkdir(exist_ok=True)
    FIXTURE.write_text(json.dumps(call_recommend(GAME_CONTEXT), ensure_ascii=False, indent=2) + '\n',
                       encoding='utf-8')
    print(f'wrote {FIXTURE}')
