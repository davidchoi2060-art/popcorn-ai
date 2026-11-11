"""dev 사이트(/mvp4) 상담 결함 A·B·C 재현 -- 예산 안 판매 PC 가 있는데 「없음」으로 끝났다 (2026-11-07 W1 상담 시험).

  A 「예산을 넘으면 안 돼요. 150만원 안에서 맞춰 주세요.」(앞 턴: 배그·로아 QHD 150만)
     놓친 것: [12400F/16G/500GB/RTX5060TI] 1,705,900원 -- 「가장 가까운」 2,622,000원보다 916,100원 쌈
  B 「FHD로 낮춰도 돼요. 150만원 안으로 보여 주세요.」
     놓친 것: [14100F/8G/256GB/RX7600] 1,152,500원 · [5600/16G/1TB/RX7600] 1,464,300원 (예산 안)
  C 「흰색 아니어도 괜찮아요. 100만원 안으로 보여 주세요.」(앞 턴: 롤·발로란트·인강 100만)
     놓친 것: [5500GT/16G/256GB/Radeon 7] 759,300원 (예산 안 · 인강용)

원인: 요청 수준(QHD·FHD·캐주얼+인강)을 예산 안에서 못 맞추면 엔진(sold_reco.pick)이 「예산 안 상품 없음」과
요청 수준 최저가 한 장만 냈고, 예산 안의 낮은 수준 PC(RX 7600 등)는 상담 자료에 아예 오지 않았다.
수정: 요청 수준 카드는 그대로 두고(2026-10-09 결정 -- 낮은 수준을 «추천»으로 올리지 않는다) set 에 lower_options 를
싣고, 상담(talk_agent)은 답이 그 PC 를 빠뜨리면 서버가 한 줄로 밝힌다.

상품·수준·막힌 조건은 판매 평가 자료(db/migrations/data/product_fit_20260925.json)의 그 상품 행 모양 그대로이고,
가격만 W1 시험(2026-11-07) 값이다. 실제 AI 호출은 하지 않는다 -- 모델 답은 고정 대본이다.
"""
import json
import unittest
from unittest.mock import patch

from api import sold_reco as S
from api import talk_agent as AG
from api import talk_tools as TT
from api import llm
from api.talk_schema import GameState, TalkState, Vocab

LEVELS = [
    {'usage': '사무용', 'level': '기본', 'level_rank': 1, 'work': '문서·웹·화상회의 (한글·오피스·크롬 탭 몇 개)', 'conditions': ''},
    {'usage': '사무용', 'level': '쾌적', 'level_rank': 2, 'work': '대용량 엑셀·다중 창·탭 수십 개·듀얼 모니터', 'conditions': ''},
    {'usage': '게임', 'level': '캐주얼', 'level_rank': 1, 'work': '롤·발로란트·피파·메이플 FHD', 'conditions': ''},
    {'usage': '게임', 'level': 'FHD', 'level_rank': 2, 'work': '최신 대작 FHD 높음 옵션 60fps 이상', 'conditions': ''},
    {'usage': '게임', 'level': 'QHD', 'level_rank': 3, 'work': '최신 대작 QHD 높음 옵션', 'conditions': ''},
    {'usage': '게임', 'level': '4K', 'level_rank': 4, 'work': '최신 대작 4K 높음 옵션', 'conditions': ''},
]
RANK = {(l['usage'], l['level']): l['level_rank'] for l in LEVELS}
VOCAB = Vocab(
    usages=[('게임', []), ('사무·인강', [])],
    confirmed_games={'리그 오브 레전드': 'E', '발로란트': 'E', '배틀그라운드': 'E', '로스트아크': 'D'},
    all_game_names=['리그 오브 레전드', '발로란트', '배틀그라운드', '로스트아크'],
    game_aliases={'롤': '리그 오브 레전드', '배그': '배틀그라운드', '로아': '로스트아크'})


def pc(code, name, price, gpu, gpu_idx, ram, ssd, game, game_blocked, office='기본'):
    return {'code': code, 'name': name, 'price': price, 'price_src': '11월 7일 기준 쇼핑몰 가격 · 구매할 때 확정',
            'status': '판매중', 'url': f'https://www.popcornpc.co.kr/shop/system_detail.html?pd_no={code}',
            'includes': None, 'balance': None, 'dominated_by': None, 'band': None,
            'spec': {'cpu': 'CPU', 'gpu': gpu, 'ram_gb': ram, 'ssd_gb': ssd, 'cpu_mt': 11500, 'cpu_st': 1600,
                     'gpu_idx': gpu_idx, 'vram_gb': 8},
            'fit': {'게임': {'level': game, 'rank': RANK.get(('게임', game), 0), 'blocked': game_blocked},
                    '사무용': {'level': office, 'rank': RANK[('사무용', office)], 'blocked': []}}}


# W1 이 짚은 판매 PC (평가 자료 행 모양 그대로 · 가격은 2026-11-07 시험값)
RX7600_8G = pc(96311, '골드 NO.03.96311  ★인기급상승★ [14100F/8G/256GB/RX7600]', 1152500, 'RX 7600', 85, 8, 256,
               None, ['램 16GB 미만(현재 8GB)'])
RX7600_16G = pc(128598, '[팝콘피씨] NO.04.128598  [5600/16G/1TB/RX7600]', 1464300, 'RX 7600', 85, 16, 1000,
                '캐주얼', ['그래픽 지수 100 미만(현재 85)', 'CPU 게임 등급 1.0 미만(현재 0.9)'])
RTX3050_8G = pc(93172, '골드 NO.03.93172  [13100F/8G/256GB/RTX 3050]', 1009300, 'RTX 3050 6GB', 50, 8, 256,
                None, ['램 16GB 미만(현재 8GB)'])
RTX3050_16G = pc(90675, '골드 NO.04.90675  [14100F/16GB/500GB/RTX 3050]', 1268900, 'RTX 3050 6GB', 50, 16, 500,
                 '캐주얼', ['그래픽 지수 100 미만(현재 50)', 'CPU 게임 등급 1.0 미만(현재 0.95)'])
APU_5500GT = pc(113193, '실버 NO.04.113193  [5500GT/16G/256GB/Radeon 7]', 759300, 'AMD Radeon(내장 2CU)', 5, 16, 256,
                None, ['그래픽 지수 25 미만(현재 5)', 'CPU 게임 등급 0.9 미만(현재 0.75)'])
RTX5060TI = pc(121228, '골드 NO.04.121228 [12400F/16G/500GB/RTX5060TI]', 1705900, 'RTX 5060 Ti 8GB', 118, 16, 500,
               'FHD', ['그래픽 지수 150 미만(현재 118)', 'SSD 960GB 미만(현재 500GB)'], office='쾌적')
QHD_PC = pc(130001, '골드 [9600X/32G/1TB/RTX5070]', 2622000, 'RTX 5070', 150, 32, 1000,
            'QHD', ['그래픽 지수 225 미만(현재 150)'], office='쾌적')
PRODUCTS = {p['code']: p for p in (RX7600_8G, RX7600_16G, RTX3050_8G, RTX3050_16G, APU_5500GT, RTX5060TI, QHD_PC)}


def sets_for(state, game_usages, other_usages):
    with patch.object(S, 'load', lambda: (LEVELS, PRODUCTS)), \
            patch.object(S, 'public_codes', lambda: frozenset(PRODUCTS)), \
            patch.object(S, 'load_custom_pcs', lambda notes: []):
        return S.card_sets(state, game_usages, other_usages, [], VOCAB)


def game_state(budget, names, resolution=None, others=()):
    return TalkState(usages=['게임', *others], budget_won=budget, budget_bound='이하',
                     game=GameState(names=names, grade='E', grade_src='catalog', resolution=resolution))


def within_codes(cs, budget):
    return [i['product_code'] for i in [*cs['items'], *cs.get('lower_options', [])] if i['price'] <= budget]


class EngineReproducesW1(unittest.TestCase):
    """엔진(sold_reco) -- 예산 안 등록 상품이 있으면 상담 자료에 반드시 들어간다."""

    def test_A_qhd_150_offers_within_budget_and_the_cheaper_nearest(self):
        cs = sets_for(game_state(1500000, ['배틀그라운드', '로스트아크'], '1440p'), ['게임'], [])[0]
        self.assertEqual(cs['min_level'], 'QHD')
        # 요청 수준 카드는 그대로(2,622,000원 참고 카드) -- 낮은 수준을 «추천»으로 올리지 않는다.
        self.assertEqual([(i['product_code'], i['role']) for i in cs['items']], [(130001, 'reference')])
        alts = [(i['product_code'], i['tag'], i['over_budget']) for i in cs['lower_options']]
        # 예산 안 낮춘 안(RX 7600) + 한 단계 낮춘 최저가 1,705,900원(2,622,000원보다 916,100원 쌈)
        self.assertEqual(alts, [(128598, S.TAG_LOWER, False), (121228, S.TAG_LOWER_NEAREST, True)])
        self.assertEqual(QHD_PC['price'] - RTX5060TI['price'], 916100)

    def test_B_fhd_150_includes_amd_rx7600_within_budget(self):
        cs = sets_for(game_state(1500000, ['배틀그라운드', '로스트아크'], '1080p'), ['게임'], [])[0]
        self.assertEqual(cs['min_level'], 'FHD')
        self.assertEqual(cs['empty_reason'], '예산 안 상품 없음')
        self.assertIn(128598, within_codes(cs, 1500000))
        alt = cs['lower_options'][0]
        self.assertEqual((alt['product_code'], alt['price'], alt['over_budget']), (128598, 1464300, False))
        self.assertIn('RX7600', alt['name'])
        self.assertIn('요청하신 게임 FHD 수준보다 낮은 구성', alt['short_of'])
        self.assertIn(S.LOWER_NOTE, cs['empty_note'])

    def test_C_casual_plus_lecture_100_offers_the_lecture_pc_within_budget(self):
        st = game_state(1000000, ['리그 오브 레전드', '발로란트'], others=['사무·인강'])
        cs = sets_for(st, ['게임'], ['사무·인강'])[0]
        self.assertTrue(all(i['price'] > 1000000 for i in cs['items']))      # 둘 다 하는 PC 는 예산 밖
        self.assertIn(113193, within_codes(cs, 1000000))                       # 인강용 5500GT 759,300원
        alt = next(i for i in cs['lower_options'] if i['product_code'] == 113193)
        self.assertIn('사무·인강 용도만 충족', alt['short_of'])

    def test_lower_options_never_include_a_pc_that_cannot_run_the_game_class(self):
        # 내장 그래픽(그래픽 지수 미달)은 게임 낮춘 안이 아니다 -- 램·저장공간만 모자란 것만 «rank 0 낮춘 안»이다.
        alts = S.lower_options('게임', 1, 1000000, '이하', LEVELS, PRODUCTS)
        self.assertNotIn(113193, [a['product_code'] for a in alts])

    def test_no_budget_or_floor_budget_has_no_lower_options(self):
        self.assertEqual(S.lower_options('게임', 2, None, None, LEVELS, PRODUCTS), [])
        self.assertEqual(S.lower_options('게임', 2, 1500000, '이상', LEVELS, PRODUCTS), [])

    def test_within_budget_request_level_is_unchanged(self):
        # 요청 수준이 예산 안에 있으면 지금 규칙 그대로 -- 낮춘 안을 붙이지 않는다.
        res = S.pick('게임', 1, 1500000, '이하', LEVELS, PRODUCTS)
        self.assertNotIn('lower_options', res)
        self.assertTrue(all(not i['over_budget'] for i in res['items']))


# ── 상담 3문장(앞 턴 포함) -- 모델 답은 고정 대본, 도구 결과는 위 엔진 그대로 ─────────────────────
class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        raise RuntimeError('no db in test')


class _Engine:
    def connect(self):
        return _Conn()


def _turn(text='', calls=()):
    return llm.ToolTurn(provider='codex', model='gpt-test', text=text, tool_calls=list(calls), raw={},
                        tokens_in=1, tokens_out=1, cached_in=0, cost_usd=0.0, elapsed_sec=0.0,
                        log_id=1, cost_logged=True, stop='completed')


def _fake_recommend(body):
    raw = body.state
    g = raw.get('game') or {}
    st = TalkState(usages=raw['usages'], budget_won=raw.get('budget_won'), budget_bound=raw.get('budget_bound'),
                   game=GameState(names=g.get('names') or [], grade='E', grade_src='catalog',
                                  resolution=g.get('resolution')) if g else None)
    games = [u for u in st.usages if '게임' in u]
    sets = sets_for(st, games, [u for u in st.usages if u not in games])
    return {'card_sets': sets, 'needs': [], 'assumed': [], 'dropped': [], 'talk_notes': [],
            'budget_won': st.budget_won, 'budget_bound': st.budget_bound, 'game_grade': 'E',
            'game_resolution': (g or {}).get('resolution'), 'platform': None, 'anchor_code': None}


class ConsultReproducesW1(unittest.TestCase):
    """상담(talk_agent) -- 예산 안 등록 상품이 있으면 「없음」으로 끝내지 않는다(서버 검산 한 줄)."""

    def _run(self, history, text, find_args, reply):
        from api import grid_public as GP
        sent = []
        script = [_turn(calls=[{'id': 'a', 'name': 'find_pcs', 'args': find_args}]), _turn(reply)]

        def fake_call(msgs, tools, **kw):
            sent.append([dict(m) for m in msgs])
            return script.pop(0)
        with patch.object(AG, 'engine', _Engine()), patch.object(AG, 'load_vocab', lambda c: VOCAB), \
                patch.object(AG.llm, 'call_tools', fake_call), patch.object(GP, 'recommend', _fake_recommend):
            out = AG.run_turn(text, [AG.Turn(**h) for h in history])
        tool_msgs = [m for m in sent[-1] if m.get('role') == 'tool']
        return out, json.loads(tool_msgs[-1]['content'])

    HIST_150 = [{'role': 'user', 'text': '배그랑 로아를 QHD로 하고 싶어요. 150만원 PC 추천해 주세요.'},
                {'role': 'assistant', 'text': 'QHD 기준 PC를 찾아 보여 드렸어요.'},
                {'role': 'user', 'text': '예산을 넘으면 안 돼요. 150만원 안에서 맞춰 주세요.'},
                {'role': 'assistant', 'text': '150만원 안에는 QHD 수준 PC가 없어요.'}]

    def test_B_reply_saying_none_gets_the_rx7600_line(self):
        out, tool = self._run(
            self.HIST_150, 'FHD로 낮춰도 돼요. 150만원 안으로 보여 주세요.',
            {'usages': ['게임'], 'games': ['배틀그라운드', '로스트아크'], 'resolution': '1080p', 'budget_won': 1500000},
            '150만원 안에는 FHD 게임 PC가 없어요.')
        # 도구 결과에 AMD RX 7600 PC 가 예산 안 낮춘 안으로 실려 AI 에게 간다.
        alts = tool['sets'][0]['budget_alternatives']
        self.assertEqual(alts[0]['price'], 1464300)
        self.assertIn('RX7600', alts[0]['name'])
        self.assertIn('budget_alternatives_rule', tool['sets'][0])
        # 답이 「없어요」로 끝나도 서버가 예산 안 판매 PC 를 밝힌다.
        self.assertIn('1,464,300원', out['reply'])
        self.assertIn('RX7600', out['reply'])
        self.assertIn('예산 1,500,000원 안에서는', out['reply'])

    def test_A_reply_mentioning_the_alternative_gets_no_duplicate_line(self):
        out, tool = self._run(
            self.HIST_150[:2], '예산을 넘으면 안 돼요. 150만원 안에서 맞춰 주세요.',
            {'usages': ['게임'], 'games': ['배틀그라운드', '로스트아크'], 'resolution': '1440p', 'budget_won': 1500000},
            'QHD 수준은 150만원 안에 없지만, 한 단계 낮춘 RX7600 PC가 1,464,300원이에요. '
            'FHD 수준 가장 가까운 PC는 1,705,900원이에요.')
        prices = [a['price'] for a in tool['sets'][0]['budget_alternatives']]
        self.assertEqual(prices, [1464300, 1705900])
        self.assertNotIn('예산 1,500,000원 안에서는', out['reply'])
        self.assertIn('1,705,900원', out['reply'])      # 낮춘 안 금액은 서버 사실이라 검증을 통과한다

    def test_C_lecture_pc_is_named_when_reply_says_none(self):
        hist = [{'role': 'user', 'text': '롤, 발로란트, 인강용으로 100만원 흰색 PC 찾아요.'},
                {'role': 'assistant', 'text': '흰색 케이스 조건으로 찾아 봤어요.'}]
        out, _ = self._run(
            hist, '흰색 아니어도 괜찮아요. 100만원 안으로 보여 주세요.',
            {'usages': ['게임', '사무·인강'], 'games': ['리그 오브 레전드', '발로란트'], 'budget_won': 1000000},
            '100만원 안에는 맞는 PC가 없어요.')
        self.assertIn('759,300원', out['reply'])
        self.assertIn('5500GT', out['reply'])


class SmallDefects(unittest.TestCase):
    """같은 W1 문서의 작은 결함 -- 조사(1)와 상품명 표기(5)."""

    def test_particle_after_part_noun(self):
        self.assertEqual(AG.fix_particles('흰색 케이스을 원하시면'), '흰색 케이스를 원하시면')
        self.assertEqual(AG.fix_particles('램를 늘리고 파워은 그대로'), '램을 늘리고 파워는 그대로')
        self.assertEqual(AG.fix_particles('그래픽카드이 좋아요.'), '그래픽카드가 좋아요.')
        # 정해 둔 낱말 밖·낱말의 일부는 건드리지 않는다.
        for keep in ('가을에 사요', '케이스를 바꿔요', '구성이 좋아요', '케이스이다'):
            self.assertEqual(AG.fix_particles(keep), keep)

    def test_card_name_drops_hash_star_and_duplicate_gpu(self):
        from api.product_name import card_name
        self.assertEqual(card_name('골드 NO.03.96311  ★인기급상승★ [14100F/8G/256GB/RX7600]'),
                         '골드 [14100F/8G/256GB/RX7600]')
        self.assertEqual(card_name('골드 NO.04.93454  RTX 3050 [12400F/16G/250GB/RTX3050]'),
                         '골드 [12400F/16G/250GB/RTX3050]')
        self.assertEqual(card_name('## 골드 [5600/16G/500GB/RTX3050] ##'), '골드 [5600/16G/500GB/RTX3050]')
        # 대괄호 안에 없는 다른 그래픽카드 이름은 남긴다.
        self.assertEqual(card_name('골드 RTX 5060 [12400F/16G/500GB/RTX3050]'), '골드 RTX 5060 [12400F/16G/500GB/RTX3050]')


if __name__ == '__main__':
    unittest.main()
