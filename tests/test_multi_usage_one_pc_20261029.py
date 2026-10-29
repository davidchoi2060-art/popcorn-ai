"""여러 용도 = PC 한 대 · 게임 이름만 온 문장은 바로 추천 (2026-10-29 사장님).

① 「웹디자인·포토샵·일러스트·동영상편집 및 롤·발로란트·리니지2 등 게임 컴퓨터 추천」에 용도마다 묶음이 나가
   「포토샵만 하는 오피스 PC / 게임만 하는 PC / 둘 다 하는 PC」가 섞였다 -- 「사무용 + 게임용 뭐 이런식으로 되어야 하지 않나?」
② 「FC 온라인」에 상담 AI 가 「FC 온라인용 PC를 찾으시나요?」로 되물어 추천이 한 번에 안 나왔다.
③ 용도 버튼이 누를 때마다 문장을 한 줄씩 덧붙였다.
"""
import pathlib
import unittest
from types import SimpleNamespace
from unittest import mock

from api import sold_reco as S
from api import talk_rules as TR

LEVELS = [
    {'usage': '게임', 'level': '기본', 'level_rank': 1, 'work': '캐주얼 게임', 'conditions': None},
    {'usage': '게임', 'level': 'FHD', 'level_rank': 2, 'work': 'FHD 게임', 'conditions': None},
    {'usage': '디자인·조판', 'level': '기본', 'level_rank': 1, 'work': '포토샵·일러스트', 'conditions': None},
    {'usage': '영상편집', 'level': '기본', 'level_rank': 1, 'work': 'FHD 컷편집', 'conditions': None},
]


def pc(code, price, **ranks):
    names = {1: '기본', 2: 'FHD'}
    fit = {u: {'level': names.get(r, '기본'), 'rank': r, 'blocked': []} for u, r in ranks.items()}
    return {'code': code, 'name': f'PC{code}', 'price': price, 'price_src': '현재 판매가', 'url': None,
            'spec': {}, 'includes': None, 'fit': fit}


# 1: 내장 그래픽 오피스 PC(디자인만) · 2: 캐주얼 게임 PC(게임만) · 3: 게임·디자인·영상편집 모두
PRODUCTS = {
    1: pc(1, 892700, **{'디자인·조판': 1}),
    2: pc(2, 1194500, **{'게임': 1, '디자인·조판': 1}),
    3: pc(3, 1624400, **{'게임': 2, '디자인·조판': 1, '영상편집': 1}),
}


def sets_for(other_usages, products=PRODUCTS, budget=None):
    state = SimpleNamespace(game=SimpleNamespace(names=['리그 오브 레전드'], resolution=None, grade='E'),
                            budget_won=budget, budget_bound='이하' if budget else None)
    notes = []
    with mock.patch.object(S, 'load', lambda: (LEVELS, products)), \
         mock.patch.object(S, 'public_codes', lambda: frozenset({1, 2, 3})), \
         mock.patch.object(S, 'load_custom_pcs', lambda notes: []), \
         mock.patch.object(S, 'light_game_state', lambda state, vocab=None: False), \
         mock.patch.object(S, 'game_min_rank', lambda *a, **k: 1):
        return S.card_sets(state, ['게임'], other_usages, notes), notes


class OnePcForAllUsages(unittest.TestCase):
    def test_several_usages_give_one_set_of_pcs_meeting_all(self):
        sets, _ = sets_for(['디자인', '영상편집'])
        self.assertEqual(len(sets), 1)
        cs = sets[0]
        self.assertEqual(cs['usages'], ['게임', '디자인', '영상편집'])
        self.assertEqual(cs['usage'], '게임 + 디자인 + 영상편집')
        # 디자인만 되는 오피스 PC(1)·게임만 되는 PC(2)는 빠지고 모두 충족하는 3만 남는다.
        self.assertEqual([i['product_code'] for i in cs['items']], [3])
        self.assertIn('게임 기본 · 디자인 기본 · 영상편집 기본', cs['min_level'])
        self.assertTrue(cs['demand']['notes'][0].startswith('말씀하신 용도(게임·디자인·영상편집)를 PC 한 대로'))
        # 이유 첫 줄은 고르기 기준(게임), 이어서 함께 충족한 용도의 수준.
        self.assertEqual(cs['items'][0]['reasons'][:3],
                         ['게임 FHD — FHD 게임', '디자인·조판 기본 — 포토샵·일러스트', '영상편집 기본 — FHD 컷편집'])

    def test_casual_game_with_office_keeps_cheapest_pick(self):
        # 캐주얼 게임 + 사무용 기본 -- 가벼운 수요 그대로(예산을 채우지 않는다). 사무용 수준이 없는 3도 후보가 아니다.
        products = {k: dict(v, fit=dict(v['fit'], 사무용={'level': '기본', 'rank': 1, 'blocked': []}))
                    for k, v in PRODUCTS.items() if k != 1}
        sets, _ = sets_for(['사무용'], products, budget=2000000)
        self.assertEqual(len(sets), 1)
        self.assertEqual([i['product_code'] for i in sets[0]['items']], [2])
        self.assertTrue(sets[0]['demand']['light'])

    def test_split_back_per_usage_only_when_no_pc_meets_all(self):
        products = {1: PRODUCTS[1], 2: PRODUCTS[2]}      # 영상편집이 되는 PC 가 하나도 없다
        sets, notes = sets_for(['디자인', '영상편집'], products)
        self.assertEqual([s['usage'] for s in sets], ['게임', '디자인', '영상편집'])
        for s in sets:
            self.assertIn(S.DEMAND_SPLIT, s['demand']['notes'])
        self.assertTrue(any('per-usage sets' in n for n in notes))

    def test_single_usage_is_unchanged(self):
        sets, _ = sets_for([])
        self.assertEqual(len(sets), 1)
        self.assertEqual(sets[0]['usage'], '게임')
        self.assertNotIn('usages', sets[0])


class GameOnlyText(unittest.TestCase):
    GAMES = {'FC온라인', '리그 오브 레전드', '배틀그라운드', '발로란트'}
    ALIASES = {'fc': 'FC온라인', '피파': 'FC온라인', '롤': '리그 오브 레전드', '배그': '배틀그라운드', '발로': '발로란트'}

    def match(self, raw, vocab):
        key = raw.replace(' ', '').lower()
        if raw in self.GAMES:
            return raw
        if key in self.ALIASES:
            return self.ALIASES[key]
        return next((g for g in self.GAMES if len(key) >= 2 and key in g.replace(' ', '').lower()), None)

    def names(self, text):
        return TR.game_only_names(text, None, self.match)

    def test_game_name_alone_is_read(self):
        self.assertEqual(self.names('FC 온라인'), ['FC온라인'])
        self.assertEqual(self.names('FC온라인'), ['FC온라인'])
        self.assertEqual(self.names('피파'), ['FC온라인'])
        self.assertEqual(self.names('롤'), ['리그 오브 레전드'])
        self.assertEqual(self.names('발로'), ['발로란트'])
        self.assertEqual(self.names('롤 할 컴퓨터'), ['리그 오브 레전드'])
        self.assertEqual(self.names('배그용 PC 추천'), ['배틀그라운드'])
        self.assertEqual(self.names('롤, 배그'), ['리그 오브 레전드', '배틀그라운드'])

    def test_other_words_leave_it_to_the_consultant(self):
        for text in ('롤 돌아가요?', '배그 150만원', '롤 말고 배그', '게임용 PC를 찾고 있어요.', '', '영상편집'):
            self.assertEqual(self.names(text), [], text)


class PurposeButtons(unittest.TestCase):
    def setUp(self):
        self.js = (pathlib.Path(__file__).resolve().parents[1]
                   / 'mockups/mvp4/assets/js/design-conversation.js').read_text(encoding='utf-8')

    def test_buttons_carry_purpose_and_pressed_state(self):
        for purpose in ('게임', '영상 편집', '사무·업무'):
            self.assertIn(f'data-dc-purpose="{purpose}"', self.js)
            self.assertIn(f"aria-pressed=\"' + pressed('{purpose}') + '\"", self.js)

    def test_purposes_join_into_one_sentence(self):
        self.assertIn("list.join(' + ') + '용 PC를 찾고 있어요. 한 대로 모두 할 거예요.'", self.js)
        # 예전처럼 버튼 문장을 줄마다 덧붙이지 않는다.
        self.assertNotIn("model.draft + '\\n' + node.dataset.dcDraft", self.js)
        self.assertIn("'purposes', 'purposeLine'", self.js)   # 화면 왕복에도 고른 용도가 남는다


if __name__ == '__main__':
    unittest.main()
