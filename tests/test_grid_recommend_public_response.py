"""POST /api/grid/recommend (kind='sold') keeps the MVP3 field contract and leaks
no internal evaluation scores or raw DB error text (collaboration item 6).

Contract: https://github.com/davidchoi2060-art/popcorn-ai/pull/2#issuecomment-6054476845
"""
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from api import grid_public as G
from api import sold_reco as S
from api.talk_schema import GameState, TalkState

TOP_KEYS = {'ok', 'card_sets', 'cards', 'assumed', 'ai_estimated', 'needs', 'dropped',
            'platform', 'budget_won', 'budget_bound', 'game_grade', 'game_resolution', 'game_name'}
SET_KEYS = {'usage', 'usage_grid', 'kind', 'items', 'empty_reason', 'empty_note',
            'min_level', 'min_level_work'}
ITEM_KEYS = {'product_code', 'name', 'price', 'price_src', 'mall_url', 'spec', 'level',
             'tag', 'over_budget', 'reasons'}
PUBLIC_SPEC = {'cpu', 'gpu', 'ram_gb', 'ssd_gb', 'vram_gb'}
DB_ERROR = 'OperationalError: connection to server at "10.20.30.40" failed: password authentication failed'

LEVELS = [
    {'usage': '게임', 'level': '기본', 'level_rank': 1, 'work': '캐주얼 게임', 'conditions': None},
    {'usage': '게임', 'level': 'FHD', 'level_rank': 2, 'work': 'FHD 게임', 'conditions': 'GPU 8GB'},
    {'usage': '영상편집', 'level': '기본', 'level_rank': 1, 'work': 'FHD 편집', 'conditions': None},
]


def product(code, price):
    return {'code': code, 'name': f'조립PC {code}', 'price': price, 'price_src': '현재 판매가',
            'status': '판매중', 'url': f'https://mall.example/{code}', 'includes': None,
            'spec': {'cpu': '라이젠5 9600', 'gpu': 'RTX 5060 Ti 8GB', 'ram_gb': 32, 'ssd_gb': 500,
                     'vram_gb': 8, 'cpu_mt': 16500, 'cpu_st': 2100, 'gpu_idx': 118},
            'balance': None, 'dominated_by': None, 'band': None,
            'fit': {'게임': {'level': 'FHD', 'rank': 2, 'blocked': []},
                    '영상편집': {'level': '기본', 'rank': 1, 'blocked': []}}}


PRODUCTS = {1: product(1, 1200000), 2: product(2, 1500000)}


class FakeEngine:
    @contextmanager
    def connect(self):
        yield SimpleNamespace()


def call_recommend():
    state = TalkState(usages=['게임', '영상편집'], budget_won=2000000, budget_bound='이하',
                      game=GameState(names=['배틀그라운드'], grade='C', grade_src='ai_estimate'))
    dropped = [{'field': 'game.resolution', 'value': '8K', 'reason': 'not in vocab'}]
    with patch.object(G, 'engine', FakeEngine()), \
         patch.object(G, 'RECO_SOURCE', 'sold'), \
         patch.object(G, 'load_vocab', lambda conn: object()), \
         patch.object(G, 'validate_state', lambda raw, vocab: (state, dropped)), \
         patch.object(G, 'missing_for', lambda st, vocab: []), \
         patch.object(G, 'usage_map', lambda: {}), \
         patch.object(G, '_game_context', lambda conn, names, vocab: None), \
         patch.object(G, '_record_estimate', lambda st: (False, DB_ERROR)), \
         patch.object(S, 'load', lambda: (LEVELS, PRODUCTS)):
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

    def test_source_products_are_not_mutated(self):
        with self.assertLogs('grid_public', level='INFO'):
            call_recommend()
        self.assertIn('cpu_mt', PRODUCTS[1]['spec'])


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
    unittest.main()
