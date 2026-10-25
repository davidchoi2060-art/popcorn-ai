"""고객 PC 구성 실제 AI 상담 — 격리 검사(DB·네트워크 없음, 가짜 후보·가짜 LLM).

요청 pc-builder-llm-20261025-01a1672e §6 의 계약을 고정한다:
  예산 해석(전체/부품·단위 모호·0·음수·과대·여러 금액) · 허용목록 밖 상품번호 거절 · 고정 부품 유지 ·
  최소 구성/부족액/변경 대안 · AI 응답 검증(목록 밖 번호 재시도·두 번 실패 시 AI 설명 없이 서버 후보) ·
  제공자 장애·한도 구분 · 근거 없는 금액·FPS·재고 문장 제거 · 작업별 비용 한도 실제 적용.
실제 모델 호출 증거는 결과 보고(개발 서버)에 따로 남긴다.
"""
import json
import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

os.environ.setdefault('DATABASE_URL', 'postgresql+psycopg2://ci:ci@127.0.0.1:5432/ci')

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import llm
from api import pc_builder_advisor as A
from api import pc_builder_data as D


# ── 가짜 후보 ────────────────────────────────────────────────────────────
def part(code, cat, price, short, usable=True, reason=None, **facts):
    return D.Part(code=code, category=cat, name=short + ' 정식명', short=short, price=price, usable=usable, reason=reason,
                  updated_at='2026-10-20T10:00+09:00', revision=1, unit='1개', image=f'/p/{code}.jpg', source_url=None,
                  facts=facts, row={})


PARTS = [
    part(101, 'cpu', 100_000, '인텔 i3-14100F', 소켓='LGA1700'),
    part(102, 'cpu', 300_000, 'AMD 라이젠 7600', 소켓='AM5'),
    part(201, 'board', 80_000, 'H610 보드', 소켓='LGA1700'),
    part(202, 'board', 150_000, 'B650 보드', 소켓='AM5'),
    part(301, 'memory', 50_000, 'DDR4 16GB', 규격='DDR4'),
    part(302, 'memory', 70_000, 'DDR5 16GB', 규격='DDR5'),
    part(303, 'memory', 60_000, '검수중 메모리', usable=False, reason='review'),
    part(401, 'gpu', 380_000, 'RTX 3050', **{'권장 파워(W)': 550}),
    part(402, 'gpu', 800_700, 'RTX 5060 Ti', **{'권장 파워(W)': 600}),
    part(403, 'gpu', 1_500_000, 'RX 9070 XT', **{'권장 파워(W)': 750}),
    part(501, 'storage', 60_000, 'SSD 500GB'),
    part(502, 'storage', 120_000, 'SSD 1TB'),
    part(601, 'cooler', 20_000, '공랭 쿨러'),
    part(701, 'case', 45_000, '미들 케이스'),
    part(801, 'power', 40_000, '500W 파워', **{'정격(W)': 500}),
    part(802, 'power', 90_000, '800W 파워', **{'정격(W)': 800}),
    part(803, 'power', 160_000, '1000W 파워', **{'정격(W)': 1000}),
]
BOARD_MEM = {201: 'DDR4', 202: 'DDR5'}


def pool():
    return D.Pool(parts={p.code: p for p in PARTS}, specs={}, rules=[], advice={}, as_of='2026-10-23',
                  loaded_at='2026-10-25T10:00:00+09:00', source_name='test', presets=[
                      {'purpose': 'gaming', 'components': {'cpu': '101', 'board': '201', 'memory': '301', 'gpu': '402',
                                                           'storage': '502', 'cooler': '601', 'case': '701', 'power': '802'}}])


class FakeChecker:
    """소켓·메모리·파워(권장+100W) 세 규칙만 보는 가짜 판정기 — 서버 판정기와 같은 모양."""

    def __init__(self, _pool=None):
        pass

    def _bad(self, sel):
        bad = []
        cpu, board, mem, gpu, psu = (sel.get(k) for k in ('cpu', 'board', 'memory', 'gpu', 'power'))
        if cpu and board and cpu.facts.get('소켓') != board.facts.get('소켓'):
            bad.append('CPU 소켓 규격 일치')
        if board and mem and BOARD_MEM.get(board.code) != mem.facts.get('규격'):
            bad.append('메모리 규격 일치')
        if gpu and psu and psu.facts['정격(W)'] < gpu.facts['권장 파워(W)'] + 100:
            bad.append(D.PSU_LABEL)
        return bad

    def slot(self, sel, category):
        bad = self._bad(sel)
        return ('fail', bad) if bad else ('ok', [])

    def full(self, sel):
        if any(c not in sel for c in D.CATEGORIES):
            return 'incomplete', []
        return self.slot(sel, 'cpu')

    def psu_safe_watt(self, sel):
        g = sel.get('gpu')
        return g.facts['권장 파워(W)'] + 100 if g else None


class FakeResult:
    def __init__(self, text_, log_id=77):
        self.text, self.provider, self.model, self.log_id, self.elapsed_sec = text_, 'codex', 'gpt-test', log_id, 0.1


def answers(*items):
    """llm.call 을 순서대로 이 답(문자열/dict/예외)으로 바꾼다."""
    seq = list(items)
    calls = []

    def fake(prompt, **kw):
        calls.append(dict(prompt=prompt, **kw))
        x = seq.pop(0)
        if isinstance(x, Exception):
            raise x
        return FakeResult(x if isinstance(x, str) else json.dumps(x, ensure_ascii=False))
    return fake, calls


def adv(**kw):
    base = dict(category='gpu', selection={'cpu': '101', 'board': '201'}, purpose='gaming', budgetTotal=2_000_000)
    base.update(kw)
    return A.AdviseBody(**base)


# ── 예산 말 읽기 ──────────────────────────────────────────────────────────
class BudgetParseTests(unittest.TestCase):
    def test_part_and_total_are_separate(self):
        self.assertEqual(D.parse_budget('그래픽카드만 80만원 이하로 골라줘')['scope'], 'part')
        self.assertEqual(D.parse_budget('PC 전체 80만원')['scope'], 'total')
        b = D.parse_budget('예산 80만원')
        self.assertEqual((b['won'], b['scope'], b['problem']), (800_000, None, None))

    def test_problems_are_not_guessed(self):
        self.assertEqual(D.parse_budget('80')['problem'], 'unit')
        self.assertEqual(D.parse_budget('0원')['problem'], 'nonpositive')
        self.assertEqual(D.parse_budget('-50만원')['problem'], 'nonpositive')
        self.assertEqual(D.parse_budget('3억')['problem'], 'too_large')
        self.assertEqual(D.parse_budget('80만원이랑 100만원')['problem'], 'multiple')
        self.assertEqual(D.parse_budget('1,500,000원')['won'], 1_500_000)

    def test_model_numbers_and_capacities_are_not_money(self):
        self.assertIsNone(D.parse_budget('RTX 5060 Ti 랑 32GB 메모리, 700W'))
        self.assertEqual(D.parse_budget('i5-14400F 쓰고 150만원')['won'], 1_500_000)


# ── 후보·최소 구성 ────────────────────────────────────────────────────────
class PoolTests(unittest.TestCase):
    def setUp(self):
        self.pool, self.ck = pool(), FakeChecker()

    def test_resolve_rejects_unknown_wrong_slot_and_unusable(self):
        for sel in ({'gpu': '999999'}, {'gpu': '101'}, {'memory': '303'}, {'nope': '101'}):
            with self.subTest(sel=sel), self.assertRaises(D.SelectionError):
                D.resolve(self.pool, sel)
        self.assertEqual(D.resolve(self.pool, {'cpu': '101', 'gpu': None})['cpu'].code, 101)

    def test_min_build_keeps_fixed_and_respects_psu_margin(self):
        mb = D.min_build(self.pool, self.ck, {})
        self.assertEqual(self.ck.full(mb['sel'])[0], 'ok')
        self.assertEqual(mb['sel']['power'].code, 802)          # 500W 는 3050 권장 550+100 미달 -- 여유를 빼서 맞추지 않는다
        fixed = {'gpu': self.pool.get(403)}
        mb2 = D.min_build(self.pool, self.ck, fixed)
        self.assertEqual(mb2['sel']['gpu'].code, 403)
        self.assertEqual(mb2['total'], D.total_of(mb2['sel']))

    def test_impossible_budget_reports_min_total_shortfall_and_relax(self):
        fixed = {'gpu': self.pool.get(403)}
        f = D.feasibility(self.pool, self.ck, fixed, 100_000)
        self.assertEqual(f['status'], 'over')
        self.assertEqual(f['shortfall'], f['minTotal'] - 100_000)
        self.assertTrue(f['relax'] and f['relax'][0]['category'] == 'gpu')
        self.assertLess(f['relax'][0]['minTotal'], f['minTotal'])
        self.assertIn('전체 시장 최저가 아님', f['scope'])

    def test_fixed_parts_that_cannot_build_report_no_build(self):
        fixed = {'cpu': self.pool.get(101), 'board': self.pool.get(202)}      # 소켓 불일치
        f = D.feasibility(self.pool, self.ck, fixed, 2_000_000)
        self.assertEqual(f['status'], 'no_build')
        self.assertTrue(f['relax'])
        self.assertEqual(D.fill_options(self.pool, self.ck, fixed, 'gaming', 2_000_000), [])

    def test_fill_options_never_change_fixed_and_all_pass(self):
        fixed = {'gpu': self.pool.get(402)}
        opts = D.fill_options(self.pool, self.ck, fixed, 'gaming', 2_000_000)
        self.assertTrue(opts)
        for o in opts:
            self.assertEqual(o['sel']['gpu'].code, 402)
            self.assertEqual(self.ck.full(o['sel'])[0], 'ok')
            self.assertEqual(o['within'], o['total'] <= 2_000_000)

    def test_slot_candidates_split_part_and_total_budget(self):
        sel = D.resolve(self.pool, {'cpu': '101', 'board': '201'})
        c = D.slot_candidates(self.pool, self.ck, sel, 'gpu', 800_000, 1_000_000)
        by = {x['id']: x for x in c['ok']}
        self.assertTrue(by['401']['withinPartBudget'])
        self.assertEqual(by['402']['overPartBudget'], 700)
        # 부품 상한 초과(700)와 전체 예산 판정(완성 최소 기준)은 다른 금액이다
        self.assertEqual(by['402']['selectedTotal'], 100_000 + 80_000 + 800_700)
        self.assertEqual(by['402']['completeState'], 'exact')
        self.assertEqual(by['402']['overTotalBudget'], by['402']['completeMin'] - 1_000_000)
        self.assertNotEqual(by['402']['overTotalBudget'], by['402']['overPartBudget'])


class CpuMemoryTests(unittest.TestCase):
    """보드를 아직 고르지 않아도 CPU 소켓으로 확정되는 메모리 세대는 막는다(2026-10-25 실호출: AM5 CPU 에 DDR4 키트가 「저렴한 대안」)."""

    def test_socket_memory_rule(self):
        am5, lga1700 = part(1, 'cpu', 1, 'AM5 CPU', 소켓='AM5'), part(2, 'cpu', 1, '인텔', 소켓='LGA1700')
        ddr4, ddr5 = part(3, 'memory', 1, 'D4', **{'메모리 규격': 'DDR4'}), part(4, 'memory', 1, 'D5', **{'메모리 규격': 'DDR5'})
        self.assertFalse(D.cpu_memory_ok({'cpu': am5, 'memory': ddr4}))
        self.assertTrue(D.cpu_memory_ok({'cpu': am5, 'memory': ddr5}))
        self.assertTrue(D.cpu_memory_ok({'cpu': lga1700, 'memory': ddr4}))       # LGA1700 은 보드에 따라 둘 다 된다
        self.assertTrue(D.cpu_memory_ok({'cpu': lga1700, 'memory': ddr5}))
        self.assertTrue(D.cpu_memory_ok({'cpu': am5}))
        self.assertTrue(D.cpu_memory_ok({'cpu': part(5, 'cpu', 1, '모름'), 'memory': ddr4}))   # 근거가 없으면 막지 않는다

    def test_checker_uses_rule_without_board(self):
        am5, ddr4 = part(1, 'cpu', 1, 'AM5 CPU', 소켓='AM5'), part(3, 'memory', 1, 'D4', **{'메모리 규격': 'DDR4'})
        ck = D.Checker(pool())
        with patch.object(D.FB, 'judge', lambda *a, **k: ([], {})), patch.object(D.FB, 'ram_fits', lambda *a, **k: True):
            self.assertEqual(ck.slot({'cpu': am5, 'memory': ddr4}, 'memory'), ('fail', [D.CPU_MEM_LABEL]))
            self.assertEqual(ck.slot({'cpu': am5, 'memory': ddr4}, 'gpu')[0], 'ok')


# ── 부품 상담 ────────────────────────────────────────────────────────────
class AdviseTests(unittest.TestCase):
    def setUp(self):
        self.pool = pool()
        self.fb = patch.object(A, '_fallback_order', lambda: ['claude'])
        self.fb.start()

    def tearDown(self):
        self.fb.stop()

    def run_adv(self, body, *ans):
        fake, calls = answers(*ans)
        with patch.object(llm, 'call', side_effect=fake):
            return A.advise_core(self.pool, body, None, FakeChecker()), calls

    def test_valid_answer_uses_server_prices(self):
        r, calls = self.run_adv(adv(question='그래픽카드만 80만원 이하로 골라줘'), {
            'answer': 'RTX 3050은 380,000원이에요. 부품 예산 안이에요.',
            'recommendations': [{'product_code': 401, 'label': '추천', 'reason': '예산 안이에요.', 'tradeoff': '-'},
                                {'product_code': 402, 'label': '비교', 'reason': '700원 초과해요.', 'tradeoff': ''}],
            'follow_up_questions': ['해상도는요?']})
        self.assertEqual(r['ai']['status'], 'ok')
        self.assertEqual([x['id'] for x in r['recommendations']], ['401', '402'])
        self.assertEqual(r['recommendations'][0]['price'], 380_000)       # 가격은 서버 값
        self.assertEqual(r['conditions']['partBudget'], 800_000)
        self.assertIn('[자료]', calls[0]['prompt'])
        self.assertEqual(calls[0]['task_key'], A.TASK_KEY)
        self.assertTrue(calls[0]['customer_facing'])
        self.assertEqual(calls[0]['fallback_order'], ['claude'])          # 결제 꺼진 gemini 로 넘어가 사슬이 끊기지 않게

    def test_out_of_list_code_is_retried_then_accepted(self):
        good = {'answer': '추천해요.', 'recommendations': [{'product_code': 401, 'label': '추천', 'reason': 'r', 'tradeoff': 't'}]}
        r, calls = self.run_adv(adv(), {'answer': 'x', 'recommendations': [{'product_code': 999999}]}, good)
        self.assertEqual((r['ai']['status'], r['ai']['attempts'], len(calls)), ('ok', 2, 2))
        self.assertIn('허용 후보가 아니다', calls[1]['prompt'])

    def test_wrong_category_twice_falls_back_without_pretending(self):
        bad = {'answer': 'x', 'recommendations': [{'product_code': 101}]}      # CPU 번호를 그래픽카드 자리에
        r, calls = self.run_adv(adv(), bad, 'not json')
        self.assertEqual(r['ai']['status'], 'invalid')
        self.assertTrue(r['recommendations'])
        self.assertTrue(all(x['label'] == '서버 확인 후보' and x['reason'] is None for x in r['recommendations']))
        self.assertIn('AI 설명 없음', r['answer'])

    def test_provider_failure_and_limits_are_distinguished(self):
        cases = [(llm.LLMProviderError('timeout', transient=True), 'unavailable'),
                 (llm.LLMBlockedError('cap', kind='cost_task', provider='codex'), 'limited'),
                 (llm.LLMNotConfiguredError('no key'), 'unconfigured')]
        for exc, status in cases:
            with self.subTest(status=status):
                r, _ = self.run_adv(adv(), exc)
                self.assertEqual(r['ai']['status'], status)
                self.assertEqual(r['answer'], A.AI_MESSAGES[status])

    def test_ambiguous_budget_asks_without_calling_ai(self):
        for q, word in (('80으로 골라줘', '80원인지'), ('예산 80만원', 'PC 전체'), ('0원', '0원 이하'), ('100만원이랑 80만원', '여러 개')):
            with self.subTest(q=q):
                fake, calls = answers()
                with patch.object(llm, 'call', side_effect=fake):
                    r = A.advise_core(self.pool, adv(question=q), None, FakeChecker())
                self.assertEqual(r['kind'], 'clarify')
                self.assertIn(word, r['question'])
                self.assertEqual(calls, [])

    def test_invalid_sidebar_budget_asks(self):
        r, _ = self.run_adv(adv(budgetTotal=0))
        self.assertEqual(r['kind'], 'clarify')

    def test_invented_amounts_models_and_claims_are_removed(self):
        r, _ = self.run_adv(adv(), {
            'answer': 'RTX 3050은 380,000원이에요. 이 카드는 FHD에서 144fps가 나와요. RTX 4060은 450,000원이에요. 재고가 충분해요. 최저가예요.',
            'recommendations': [{'product_code': 401, 'label': '추천', 'reason': '예산 안이에요.', 'tradeoff': '-'}]})
        # 고객 화면의 AI 글에서는 금액 문장을 모두 지운다(금액은 서버 필드로만 -- E2E-01). 근거 없는 FPS·모델·재고·최저가도 지운다.
        self.assertNotIn('원', r['answer'])
        self.assertEqual(r['ai']['droppedSentences'], 5)
        self.assertEqual(r['recommendations'][0]['reason'], '예산 안이에요.')

    def test_no_compatible_candidates_is_explained_without_ai(self):
        # LGA1700 CPU + DDR5 메모리를 고르면 H610(DDR4)·B650(AM5) 둘 다 불가 -> 통과 후보 0건이면 AI 를 부르지 않고 판정 결과로 설명한다
        body = adv(selection={'cpu': '101', 'memory': '302'}, category='board')
        fake, calls = answers()
        with patch.object(llm, 'call', side_effect=fake):
            r = A.advise_core(self.pool, body, None, FakeChecker())
        self.assertEqual(r['recommendations'], [])
        self.assertEqual(r['ai']['status'], 'skipped')
        self.assertEqual(calls, [])


# ── 나머지 채우기 ─────────────────────────────────────────────────────────
class FillTests(unittest.TestCase):
    def setUp(self):
        self.pool = pool()
        self.fb = patch.object(A, '_fallback_order', lambda: ['claude'])
        self.fb.start()

    def tearDown(self):
        self.fb.stop()

    def run_fill(self, body, *ans):
        fake, calls = answers(*ans)
        with patch.object(llm, 'call', side_effect=fake):
            return A.fill_core(self.pool, body, None, FakeChecker()), calls

    def test_ai_choice_is_validated_and_fixed_parts_kept(self):
        body = A.FillBody(selection={'gpu': '402'}, purpose='gaming', budgetTotal=2_000_000)
        r0, _ = self.run_fill(body, llm.LLMProviderError('x', transient=True))
        ids = [o['id'] for o in r0['proposal']['options']]
        r, calls = self.run_fill(body, {'choice': 'opt99'}, {'choice': ids[0], 'summary': '좋아요.', 'slot_reasons': {'gpu': '바꿈?', 'cpu': '싸요.'}})
        self.assertEqual((r['ai']['status'], r['ai']['attempts']), ('ok', 2))
        chosen = next(o for o in r['proposal']['options'] if o['id'] == r['proposal']['chosen'])
        self.assertEqual(chosen['selection']['gpu'], '402')
        self.assertNotIn('gpu', chosen['changed'])
        self.assertNotIn('gpu', r['proposal']['slotReasons'])          # 고정 자리 이유는 받지 않는다

    def test_over_budget_choice_rejected_when_within_exists(self):
        body = A.FillBody(selection={}, purpose='gaming', budgetTotal=1_000_000)
        r0, _ = self.run_fill(body, llm.LLMProviderError('x', transient=True))
        opts = r0['proposal']['options']
        over = [o['id'] for o in opts if not o['within']]
        within = [o['id'] for o in opts if o['within']]
        self.assertTrue(over and within)
        r, calls = self.run_fill(body, {'choice': over[0]}, {'choice': within[0]})
        self.assertEqual(len(calls), 2)
        self.assertIn('예산을 넘는', calls[1]['prompt'])
        self.assertEqual(r['proposal']['chosen'], within[0])

    def test_ai_failure_still_gives_server_proposal_marked(self):
        body = A.FillBody(selection={}, purpose='gaming', budgetTotal=100_000)
        r, _ = self.run_fill(body, llm.LLMProviderError('x', transient=True))
        self.assertEqual(r['ai']['status'], 'unavailable')
        self.assertEqual(r['feasibility']['status'], 'over')
        chosen = next(o for o in r['proposal']['options'] if o['id'] == r['proposal']['chosen'])
        self.assertEqual(chosen['total'], r['feasibility']['minTotal'])     # 모두 초과면 가장 싼 구성
        self.assertEqual(r['feasibility']['shortfall'], chosen['total'] - 100_000)

    def test_request_text_budget_rules(self):
        r, calls = self.run_fill(A.FillBody(requestText='그래픽카드만 80만원'))
        self.assertEqual(r['kind'], 'clarify')
        r, _ = self.run_fill(A.FillBody(requestText='80'))
        self.assertEqual(r['kind'], 'clarify')
        r, _ = self.run_fill(A.FillBody(requestText='영상 작업용 전체 150만원'), llm.LLMProviderError('x', transient=True))
        self.assertEqual((r['purpose'], r['budgetTotal']), ('creator', 1_500_000))

    def test_refine_mode_keeps_only_locked(self):
        sel = {'cpu': '101', 'board': '201', 'memory': '301', 'gpu': '401', 'storage': '501', 'cooler': '601', 'case': '701', 'power': '802'}
        body = A.FillBody(selection=sel, locked={'gpu': True}, mode='refine', budgetTotal=3_000_000)
        r, _ = self.run_fill(body, llm.LLMProviderError('x', transient=True))
        self.assertEqual(r['fixed'], ['gpu'])


class FallbackOrderTests(unittest.TestCase):
    """codex 다음은 claude. DB 배정에 fallback_order 가 저장되면 그 값(llm 이 읽도록 None)을 따른다."""

    def run_with(self, row):
        @contextmanager
        def fake_connect():
            yield None
        with patch.object(A.engine, 'connect', fake_connect), patch.object(llm, '_load_task_assignment', lambda conn, key: row):
            return A._fallback_order()

    def test_default_skips_gemini(self):
        self.assertEqual(self.run_with(None), ['claude'])
        self.assertEqual(self.run_with({'providers': [], 'fallback_order': []}), ['claude'])

    def test_db_assignment_wins(self):
        self.assertIsNone(self.run_with({'providers': [], 'fallback_order': ['Gemini', 'Claude']}))


# ── 경로 계약 ────────────────────────────────────────────────────────────
class RouteTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(A.router)
        self.client = TestClient(app)

        @contextmanager
        def fake_connect():
            yield None
        self.patches = [patch.object(A.engine, 'connect', fake_connect), patch.object(D, 'load_pool', lambda conn, src=None: pool()),
                        patch.object(D, 'Checker', FakeChecker), patch.object(A.access_gate, 'check_rate', lambda *a, **k: 'v'),
                        patch.object(A, '_fallback_order', lambda: ['claude'])]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_pool_quote_and_selection_error(self):
        r = self.client.get('/api/pc-builder/pool')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers['cache-control'], 'no-store')
        self.assertEqual(len(r.json()['parts']), len(PARTS))
        q = self.client.post('/api/pc-builder/quote', json={'selection': {'cpu': '101', 'board': '202'}}).json()
        self.assertEqual(q['total'], 250_000)
        self.assertEqual(q['compat']['state'], 'incomplete')
        bad = self.client.post('/api/pc-builder/quote', json={'selection': {'gpu': '123'}})
        self.assertEqual((bad.status_code, bad.json()['error']), (409, 'selection'))

    def test_advise_route_shape(self):
        fake, _ = answers({'answer': '좋아요.', 'recommendations': [{'product_code': 401, 'label': '추천', 'reason': 'r', 'tradeoff': 't'}]})
        with patch.object(llm, 'call', side_effect=fake):
            r = self.client.post('/api/pc-builder/advise', json={'category': 'gpu', 'selection': {'cpu': '101'}, 'budgetTotal': 2000000})
        body = r.json()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(body['ai']['requestId'], 77)
        self.assertEqual(body['recommendations'][0]['id'], '401')
        self.assertEqual(body['selectionKey'], 'cpu:101')

    def test_extra_fields_rejected(self):
        r = self.client.post('/api/pc-builder/advise', json={'category': 'gpu', 'price_override': 1})
        self.assertEqual(r.status_code, 422)


# ── 작업별 비용 한도(llm) ─────────────────────────────────────────────────
class _Res:
    def __init__(self, row=None, scalar=0):
        self.row, self.scalar = row, scalar

    def mappings(self):
        return self

    def first(self):
        return self.row

    def scalar_one(self):
        return self.scalar


class FakeConn:
    def __init__(self, sub_row, spent):
        self.sub_row, self.spent, self.sql = sub_row, spent, []

    def execute(self, stmt, params=None):
        q = str(stmt)
        self.sql.append((q, params))
        if 'FROM cost_thresholds' in q:
            return _Res(row=self.sub_row)
        return _Res(scalar=self.spent)


class TaskCapTests(unittest.TestCase):
    def setUp(self):
        llm._TASK_COLUMN[:] = [True]

    def tearDown(self):
        llm._TASK_COLUMN[:] = []

    def test_code_default_cap_blocks_without_fallback(self):
        conn = FakeConn(None, 3.5)
        with self.assertRaises(llm.LLMBlockedError) as e:
            llm._check_task_cap(conn, 'codex', 'task.pc_builder', None)
        self.assertEqual(e.exception.kind, 'cost_task')
        self.assertFalse(llm._is_fallback_eligible(e.exception))
        self.assertNotIn('provider = :p', conn.sql[-1][0])          # 코드 기본값은 모든 프로바이더 합계

    def test_under_cap_and_db_row_precedence(self):
        llm._check_task_cap(FakeConn(None, 1.0), 'codex', 'task.pc_builder', None)
        with self.assertRaises(llm.LLMBlockedError):
            llm._check_task_cap(FakeConn({'daily_usd': 0.5}, 0.6), 'codex', 'task.pc_builder', None)
        conn = FakeConn({'daily_usd': 10}, 5.0)
        llm._check_task_cap(conn, 'codex', 'task.pc_builder', None)
        self.assertIn('provider = :p', conn.sql[-1][0])

    def test_tasks_without_cap_and_missing_column_do_not_block(self):
        llm._check_task_cap(FakeConn(None, 999), 'codex', 'task.talk_answer', None)
        llm._TASK_COLUMN[:] = [False]
        llm._check_task_cap(FakeConn(None, 999), 'codex', 'task.pc_builder', None)

    def test_task_default_routes_to_registered_model(self):
        prov, model = llm.TASK_DEFAULTS[A.TASK_KEY]
        self.assertIn(model, llm.PROVIDERS[prov].pricing)


# ── 화면 정적 산출물 ──────────────────────────────────────────────────────
class BuiltScreenTests(unittest.TestCase):
    def test_built_bundle_calls_server_and_drops_rule_demo_copy(self):
        from pathlib import Path
        assets = Path(__file__).resolve().parents[1] / 'mockups' / 'mvp4' / 'pc-builder' / 'assets'
        js = '\n'.join(p.read_text(encoding='utf-8') for p in assets.glob('*.js'))
        self.assertIn('/api/pc-builder/', js)
        self.assertIn('서버가 확인한 후보 안에서 추천', js)
        for gone in ('실제 LLM 연결 전', '규칙형 상담 예시에 준비된 범위', '실제 LLM은 아직 연결하지 않았어요'):
            self.assertNotIn(gone, js)
        self.assertNotIn('api.openai.com', js)
        import re
        self.assertIsNone(re.search(r'sk-[A-Za-z0-9_-]{20,}', js))        # 키 모양 문자열이 번들에 없다



# ── Codex 독립 재검수(codex-fix-request-20261025.txt, 기준 36971267) 잔여 P2 4건 ──────────────
class CodexRecheckTests(unittest.TestCase):
    """재현 입력을 그대로 고정하고, 정상 상품번호·정상 소수 금액·정상 형식 응답·탐색 완료 구성도 함께 본다."""

    def test_p2_1_code_used_as_currency_is_checked(self):
        self.assertEqual(A.clean_text('이 제품의 가격은 128424원이에요.', {800_700}, set(), frozenset({128424})), ('', 1))
        self.assertEqual(A.clean_text('이 제품의 가격은 12만 8,424원이에요.', {800_700}, set(), frozenset({128424}))[1], 1)
        self.assertEqual(A.clean_text('상품번호 128424 제품이에요.', {800_700}, set(), frozenset({128424}))[1], 0)   # 상품번호 표기는 남는다
        self.assertEqual(A.clean_text('가격은 800,700원이에요.', {800_700}, set(), frozenset({128424}))[1], 0)

    def test_p2_2_decimal_man_won(self):
        self.assertEqual(A.money_in('이 제품의 가격은 65.5만원이에요.'), [(655_000, True)])
        self.assertEqual(A.clean_text('이 제품의 가격은 65.5만원이에요.', {800_700}, set(), frozenset({128424})), ('', 1))
        self.assertEqual(A.clean_text('이 제품의 가격은 65.5만원이에요.', {655_000}, set())[1], 0)
        self.assertEqual(A.money_in('차이는 0.5만원이에요.'), [(5_000, True)])
        for spec in ('DDR5-5600 16GB 키트예요.', '2.5인치 SSD와 1.5TB 저장장치예요.', '정격 750W·길이 281mm예요.', 'i5-14400F와 RTX 5060 Ti예요.'):
            with self.subTest(spec=spec):
                self.assertEqual(A.money_in(spec), [])

    def test_p2_3_malformed_fields_are_validation_failures(self):
        self.assertIn('choice', A.shape_problem({'choice': []}, A.FILL_SHAPE))
        for bad in ({'choice': {}}, {'choice': None}, {'choice': 3}, {'choice': 'opt1', 'slot_reasons': ['x']},
                    {'choice': 'opt1', 'constraints': 'x'}, {'choice': 'opt1', 'summary': 5}, {'choice': 'opt1', 'follow_up_questions': [1]}):
            with self.subTest(bad=bad):
                self.assertIsNotNone(A.shape_problem(bad, A.FILL_SHAPE))
        self.assertIsNone(A.shape_problem({'choice': 'opt1', 'slot_reasons': {'gpu': '이유'}, 'constraints': ['a']}, A.FILL_SHAPE))
        for bad in ({'recommendations': []}, {'recommendations': [1]}, {'recommendations': [{'product_code': True}]},
                    {'recommendations': [{'product_code': 401, 'reason': 5}]}, {'recommendations': [{'product_code': 401}], 'answer': []}):
            with self.subTest(bad=bad):
                self.assertIsNotNone(A.shape_problem(bad, A.ADVISE_SHAPE))
        self.assertIsNone(A.shape_problem({'recommendations': [{'product_code': '401', 'label': '추천'}]}, A.ADVISE_SHAPE))

    def test_p2_3_fill_malformed_twice_is_invalid_with_server_proposal(self):
        fake, calls = answers({'choice': []}, {'choice': {'id': 'opt1'}, 'slot_reasons': []})
        with patch.object(llm, 'call', side_effect=fake), patch.object(A, '_fallback_order', lambda: ['claude']):
            r = A.fill_core(pool(), A.FillBody(selection={'gpu': '402'}, budgetTotal=2_000_000), None, FakeChecker())
        self.assertEqual((r['ai']['status'], len(calls)), ('invalid', 2))
        self.assertIn('choice 의 형식이 틀렸다', calls[1]['prompt'])
        chosen = next(o for o in r['proposal']['options'] if o['id'] == r['proposal']['chosen'])
        self.assertEqual(chosen['selection']['gpu'], '402')                 # 고정 부품 보존
        self.assertEqual(r['proposal']['slotReasons'], {})

    def test_p2_3_malformed_then_valid_advise(self):
        fake, calls = answers({'recommendations': [{'product_code': [401]}]},
                              {'answer': '좋아요.', 'recommendations': [{'product_code': 401, 'label': '추천', 'reason': 'r', 'tradeoff': 't'}]})
        with patch.object(llm, 'call', side_effect=fake), patch.object(A, '_fallback_order', lambda: ['claude']):
            r = A.advise_core(pool(), adv(), None, FakeChecker())
        self.assertEqual((r['ai']['status'], r['ai']['attempts']), ('ok', 2))

    def test_p2_3_validator_crash_becomes_retry_not_500(self):
        fake, calls = answers({'a': 1}, {'a': 1})

        def boom(data):
            raise KeyError('x')
        with patch.object(llm, 'call', side_effect=fake), patch.object(A, '_fallback_order', lambda: ['claude']):
            with self.assertRaises(A.AIFailure) as e:
                A.ask_ai('[자료]', boom, None)
        self.assertEqual((e.exception.status, len(calls)), ('invalid', 2))

    # P2-4 -- Codex codex-budget-recheck.py 와 같은 합성 32개 후보: 첫 CPU 는 비싼 파워·나머지 최저가일 때만 호환,
    # 둘째 CPU 이상은 무엇이든 호환. 기본 탐색 한도로는 비싼 구성(1,700,000원)만 찾고 끝난다 -- 실제 최소는 900,000원.
    def synthetic(self):
        from types import SimpleNamespace
        parts = []
        for c in D.CATEGORIES:
            prices = ([100_000, 200_000, 300_000, 400_000] if c == 'cpu' else [100_000, 110_000, 120_000, 1_000_000] if c == 'power'
                      else [100_000, 110_000, 120_000, 130_000])
            for price in prices:
                parts.append(SimpleNamespace(code=len(parts) + 1, category=c, price=price, usable=True, updated_at=None, short=f'{c}{price}'))

        class SynPool:
            loaded_at = 'synthetic'
            presets = []

            def __init__(self):
                self.parts = {p.code: p for p in parts}

            def by_category(self, c, usable_only=True):
                return sorted([p for p in parts if p.category == c], key=lambda p: p.price)

        class SynChecker:
            def slot(self, sel, category):
                if 'power' not in sel:
                    return 'ok', []
                if sel['cpu'].price == 100_000:
                    ok = sel['power'].price == 1_000_000 and all(p.price == 100_000 for c, p in sel.items() if c not in ('cpu', 'power'))
                else:
                    ok = True
                return ('ok', []) if ok else ('fail', ['synthetic'])

            def full(self, sel):
                return self.slot(sel, 'power')
        return SynPool(), SynChecker()

    def test_p2_4_exhausted_search_never_claims_min_or_shortfall(self):
        p, ck = self.synthetic()
        self.assertEqual(D.node_cap(p), 12_800)                              # 기본 한도 그대로(임의로 낮추지 않음)
        mb = D.min_build(p, ck, {})
        self.assertEqual((mb['total'], mb['exhausted']), (1_700_000, True))
        f = D.feasibility(p, ck, {}, 1_000_000)
        self.assertEqual((f['status'], f['minTotal'], f['shortfall'], f['foundTotal'], f['minExact']),
                         ('unknown', None, None, 1_700_000, False))
        f2 = D.feasibility(p, ck, {}, 2_000_000)                             # 찾은 구성이 예산 안이면 가능은 확정, 최소는 미확정
        self.assertEqual((f2['status'], f2['minTotal'], f2['headroom'], f2['minExact']), ('feasible', None, 300_000, False))
        opts = D.fill_options(p, ck, {}, 'gaming', 1_000_000)
        self.assertIn('최소 여부 확인 못 함', opts[0]['label'])

    def test_p2_4_complete_search_is_exact(self):
        p, ck = self.synthetic()
        with patch.object(D, 'node_cap', lambda pool: 10 ** 7):
            f = D.feasibility(p, ck, {}, 1_000_000)
        self.assertEqual((f['status'], f['minTotal'], f['minExact'], f['headroom']), ('feasible', 900_000, True, 100_000))

    def test_p2_4_ai_context_marks_inexact_minimum(self):
        b = A._feas_brief({'status': 'unknown', 'minTotal': None, 'minExact': False, 'foundTotal': 1_700_000, 'relax': []})
        self.assertIn('최소 금액이 아니다', b['search_note'])
        self.assertIn(1_700_000, A._allowed_amounts({'feasibility': b}))


class CodexResidualPriceContextTests(unittest.TestCase):
    """Codex 잔여 확인(residual-context-price-recheck, 기준 900d3366) -- 단위 없는 가격 문맥의 상품번호 같은 수치."""

    def test_unitless_price_context_is_checked(self):
        codes = frozenset({128424})
        self.assertEqual(A.clean_text('이 제품의 가격은 128424입니다.', {800_700}, set(), codes), ('', 1))
        self.assertEqual(A.clean_text('판매가 128424', {800_700}, set(), codes), ('', 1))

    def test_product_number_and_real_price_are_kept(self):
        codes = frozenset({128424})
        self.assertEqual(A.clean_text('상품번호 128424 제품이에요.', {800_700}, set(), codes)[1], 0)
        self.assertEqual(A.clean_text('가격은 800,700원이에요.', {800_700}, set(), codes)[1], 0)
        self.assertEqual(A.clean_text('판매가 800700', {800_700}, set(), codes)[1], 0)

if __name__ == '__main__':
    unittest.main()


# ── Antigravity 설계 검토(design-review.md, 2026-10-25) 반영 ──────────────────
class AntigravityReviewTests(unittest.TestCase):
    """발견점 1~6 의 재현 입력을 그대로 고정한다."""

    def test_1_banned_word_order_and_stock_counts(self):
        for s in ('이 메인보드는 부품 간 호환성을 100% 보장합니다.', '현재 해당 그래픽카드는 재고 2개 남았습니다.',
                  '당사에서 성능과 호환에 대해 100% 만족을 보장해 드립니다.', '완벽하게 맞아요.'):
            with self.subTest(s=s):
                self.assertEqual(A.clean_text(s, set(), set())[1], 1)
        self.assertEqual(A.clean_text('성능을 보장하지는 않아요.', set(), set()), ('성능을 보장하지는 않아요.', 0))

    def test_2_amounts_without_won(self):
        for s in ('이 제품의 실구매 가격은 500000 입니다.', '특가 기준 약 65만 정도로 구성 가능합니다.'):
            with self.subTest(s=s):
                self.assertEqual(A.clean_text(s, {800_700}, set())[1], 1)
        self.assertEqual(A.clean_text('상품번호 128424 제품이에요.', set(), set(), frozenset({128424}))[1], 0)
        self.assertEqual(A.clean_text('16GB 두 개, 2026년 기준이에요.', set(), set())[1], 0)

    def test_3_compound_and_paired_budgets(self):
        self.assertEqual(D.parse_budget('1억 5천만원으로 견적 내줘')['won'], 150_000_000)        # 「여러 금액」이 아니라 한 금액(→ 1억 초과 확인)
        for t in ('전체 예산은 150만원이고 그래픽카드는 80만원 이하로 추천해줘', '그래픽카드는 80만원 이하, 전체 150만원'):
            with self.subTest(t=t):
                b = D.parse_budget(t)
                self.assertEqual((b['scope'], b['total'], b['part']), ('both', 1_500_000, 800_000))
        self.assertEqual(D.parse_budget('80만원이랑 100만원')['problem'], 'multiple')

    def test_3_paired_budget_in_advise_and_fill(self):
        fake, calls = answers({'answer': '좋아요.', 'recommendations': [{'product_code': 401, 'label': '추천', 'reason': 'r', 'tradeoff': 't'}]})
        with patch.object(llm, 'call', side_effect=fake), patch.object(A, '_fallback_order', lambda: ['claude']):
            r = A.advise_core(pool(), adv(question='전체 예산은 150만원이고 그래픽카드는 80만원 이하로 추천해줘'), None, FakeChecker())
        self.assertEqual(r['conditions'], {'partBudget': 800_000, 'totalBudget': 1_500_000})
        fake, _ = answers(llm.LLMProviderError('x', transient=True))
        with patch.object(llm, 'call', side_effect=fake), patch.object(A, '_fallback_order', lambda: ['claude']):
            r = A.fill_core(pool(), A.FillBody(requestText='게임용 전체 150만원, 그래픽카드는 80만원 이하'), None, FakeChecker())
        self.assertEqual(r['budgetTotal'], 1_500_000)
        self.assertIn('부품 하나의 예산', r['note'])

    def test_4_condition_budget_zero_is_clarify_not_422(self):
        fake, calls = answers()
        with patch.object(llm, 'call', side_effect=fake):
            r = A.advise_core(pool(), A.AdviseBody(category='gpu', conditions={'totalBudget': 0}), None, FakeChecker())
        self.assertEqual(r['kind'], 'clarify')
        self.assertEqual(calls, [])

    def test_5_search_limit_is_not_reported_as_no_build(self):
        with patch.object(D, 'node_cap', lambda p: 3):
            mb = D.min_build(pool(), FakeChecker(), {})
            self.assertEqual((mb['sel'], mb['exhausted']), (None, True))
            f = D.feasibility(pool(), FakeChecker(), {}, 1_000_000)
        self.assertEqual(f['status'], 'unknown')
        self.assertIsNone(f['minTotal'])

    def test_6_conflicts_named_when_single_relax_cannot_fix(self):
        p = pool()
        fixed = {'cpu': p.get(101), 'board': p.get(202), 'memory': p.get(301)}     # 소켓·메모리 둘 다 어긋남
        f = D.feasibility(p, FakeChecker(), fixed, 2_000_000)
        self.assertEqual(f['status'], 'no_build')
        self.assertTrue(f['conflicts'])
        self.assertTrue(any('CPU 소켓 규격 일치' in c['checks'] for c in f['conflicts']))
        fake, calls = answers()
        with patch.object(llm, 'call', side_effect=fake):
            r = A.fill_core(p, A.FillBody(selection={'cpu': '101', 'board': '202', 'memory': '301'}, budgetTotal=2_000_000), None, FakeChecker())
        self.assertIsNone(r['proposal'])
        self.assertEqual(calls, [])


# ── 고객 E2E(2026-10-25, pc-builder-customer-e2e-20261025) E2E-01 · E2E-02 ──────────────────────
def brute_complete_min(pool_, checker, fixed):
    """후보 전부를 다 조합해 본 완성 최소 합계(독립 계산 -- min_build 와 대조용)."""
    import itertools
    cats = [c for c in D.CATEGORIES]
    choices = [[fixed[c]] if c in fixed else pool_.by_category(c) for c in cats]
    best = None
    for combo in itertools.product(*choices):
        sel = dict(zip(cats, combo))
        if checker.full(sel)[0] == 'ok':
            t = sum(p.price for p in combo)
            best = t if best is None or t < best else best
    return best


class CustomerE2ETests(unittest.TestCase):
    """E2E-01: CPU 만 고르고 그래픽카드 상담 -- 남은 자리 비용에 상담 자리 최저가가 한 번 더 들어가던 중복과
    부분 합계를 전체 합계로 설명하던 의미 오류. E2E-02: 채우기 탭을 바꿔도 AI 설명이 남던 문제(프런트 node 테스트를 함께 돌린다)."""

    def setUp(self):
        self.pool, self.ck = pool(), FakeChecker()

    def test_e2e01_rest_cost_excludes_advised_slot(self):
        sel = D.resolve(self.pool, {'cpu': '102'})
        c = D.slot_candidates(self.pool, self.ck, sel, 'gpu', None, 2_000_000)
        cheapest = {cat: self.pool.by_category(cat)[0].price for cat in D.CATEGORIES}
        six = sum(cheapest[cat] for cat in ('board', 'memory', 'storage', 'cooler', 'case', 'power'))
        self.assertEqual(c['restMin'], six)                                     # 7개(그래픽카드 최저가 포함)가 아니라 6개
        self.assertEqual(D.min_rest_cost(self.pool, {'cpu', 'gpu'}), six)
        self.assertEqual(D.min_rest_cost(self.pool, {'cpu'}), six + cheapest['gpu'])

    def test_e2e01_amount_roles_are_consistent(self):
        sel = D.resolve(self.pool, {'cpu': '102'})
        budget = 2_000_000
        c = D.slot_candidates(self.pool, self.ck, sel, 'gpu', None, budget)
        for item in c['ok']:
            gpu = self.pool.get(item['id'])
            with self.subTest(gpu=item['shortName']):
                self.assertEqual(item['selectedTotal'], 300_000 + gpu.price)        # 부분 합계: CPU + 이 그래픽카드
                expect = brute_complete_min(self.pool, self.ck, {'cpu': sel['cpu'], 'gpu': gpu})
                self.assertEqual(item['completeMin'], expect)                      # 완성 최소: 호환 확인한 전체 합계
                self.assertGreaterEqual(item['completeMin'], item['selectedTotal'] + c['restMin'])
                if expect <= budget:
                    self.assertEqual((item['withinTotalBudget'], item['totalHeadroom'], item['overTotalBudget']), (True, budget - expect, None))
                else:
                    self.assertEqual((item['withinTotalBudget'], item['overTotalBudget'], item['totalHeadroom']), (False, expect - budget, None))

    def test_e2e01_ai_money_sentences_removed_and_roles_named(self):
        bad = '가장 저렴한 나머지 부품을 더한 기준 전체 합계가 1,038,400원으로 예산을 33,000원 초과해요.'
        fake, calls = answers({'answer': f'MSI 를 비교해 보세요. {bad}',
                               'recommendations': [{'product_code': 402, 'label': '추천', 'reason': f'길이가 짧아요. {bad}', 'tradeoff': bad}],
                               'follow_up_questions': ['예산을 33,000원 늘릴까요?', '해상도는요?']})
        with patch.object(llm, 'call', side_effect=fake), patch.object(A, '_fallback_order', lambda: ['claude']):
            r = A.advise_core(self.pool, adv(selection={'cpu': '102'}), None, FakeChecker())
        self.assertEqual(r['answer'], 'MSI 를 비교해 보세요.')
        rec = r['recommendations'][0]
        self.assertEqual((rec['reason'], rec['tradeoff']), ('길이가 짧아요.', None))
        self.assertEqual(r['followUps'], ['해상도는요?'])
        self.assertIn('selected_total', calls[0]['prompt'])
        self.assertIn('complete_min_total', calls[0]['prompt'])
        self.assertNotIn('total_after_choose', calls[0]['prompt'])
        self.assertNotIn('with_cheapest_rest', calls[0]['prompt'])
        self.assertIn('금액 숫자', A.SYSTEM)

    def test_e2e01_fill_texts_drop_money(self):
        fake, _ = answers(llm.LLMProviderError('x', transient=True))
        with patch.object(llm, 'call', side_effect=fake), patch.object(A, '_fallback_order', lambda: ['claude']):
            r0 = A.fill_core(self.pool, A.FillBody(budgetTotal=2_000_000), None, FakeChecker())
        first = r0['proposal']['options'][0]['id']
        fake, _ = answers({'choice': first, 'summary': '부품 합계 1,997,000원으로 예산에서 3,000원 남아요. 균형 잡힌 구성이에요.',
                           'budget_advice': '예산에서 3,000원 남아요.', 'slot_reasons': {'storage': '1TB 로 넉넉해요.'}})
        with patch.object(llm, 'call', side_effect=fake), patch.object(A, '_fallback_order', lambda: ['claude']):
            r = A.fill_core(self.pool, A.FillBody(budgetTotal=2_000_000), None, FakeChecker())
        self.assertEqual(r['proposal']['summary'], '균형 잡힌 구성이에요.')
        self.assertIsNone(r['proposal']['budgetAdvice'])

    def test_e2e01_regressions_kept(self):
        # 정상 가격·상품번호 처리(검증 모드)는 그대로
        self.assertEqual(A.clean_text('가격은 800,700원이에요.', {800_700}, set(), frozenset({128424}))[1], 0)
        self.assertEqual(A.clean_text('상품번호 128424 제품이에요.', {800_700}, set(), frozenset({128424}))[1], 0)
        self.assertEqual(A.clean_text('이 제품의 가격은 128424입니다.', {800_700}, set(), frozenset({128424}))[1], 1)
        # 고객 화면 모드: 상품번호 표기와 규격 숫자는 남고 금액 문장만 빠진다
        self.assertEqual(A.clean_text('상품번호 128424, VRAM 8GB, 길이 281mm예요.', {800_700}, set(), frozenset({128424}), no_money=True)[1], 0)
        self.assertEqual(A.clean_text('가격은 800,700원이에요.', {800_700}, set(), frozenset(), no_money=True)[1], 1)

    def test_e2e01_money_guard_short_and_cheon_units(self):
        # E2E-01 예비검사(money-guard-wip-recheck) 잔여 2입력 + 보존 대조
        codes, models = frozenset({128424}), {'5060'}
        for s in ('차이는5천원이에요.', '50원남아요.', '차이는 5천 원이에요.', '3만 정도 남아요.', '1.5억이 들어요.'):
            with self.subTest(s=s):
                self.assertEqual(A.clean_text(s, set(), models, codes, no_money=True), ('', 1))
        for s in ('RTX5060 모델을 확인해 보세요.', '상품번호128424입니다.', '16GB 메모리예요.', '만족스러운 구성이에요.',
                  'DDR5-5600 메모리와 2.5인치 SSD예요.', '정격 750W·길이 281mm예요.'):
            with self.subTest(s=s):
                self.assertEqual(A.clean_text(s, set(), models, codes, no_money=True)[1], 0)
        self.assertIn('금액 숫자는 쓰지 않는다', A.FILL_FORMAT)
        self.assertNotIn('부족액과 대안을 budget_advice', A.FILL_FORMAT)

    def test_e2e02_e2e04_proposal_node_regression(self):
        import shutil
        import subprocess
        from pathlib import Path
        node = shutil.which('node')
        if not node:
            self.skipTest('node 없음')
        root = Path(__file__).resolve().parents[1] / 'frontend' / 'pc-builder'
        r = subprocess.run([node, '--test', str(root / 'tests' / 'proposal-view.test.mjs')], capture_output=True, text=True,
                           encoding='utf-8', cwd=root)
        self.assertEqual(r.returncode, 0, r.stdout[-1500:] + r.stderr[-800:])
        self.assertIn('# fail 0', r.stdout)
        self.assertIn('# pass 7', r.stdout)                                       # 탭 3 + E2E-04 4(버튼·재조회 합계·재계산 표시)



# ── 자유 입력 카드(pc-builder-intent-input-20261025) ─────────────────────────────────────────
class IntentInputTests(unittest.TestCase):
    """입력창 원문은 지우지 않고 그대로 보낸다. 글을 쓴 뒤 예산 칸·용도 버튼을 바꾸면 그때의 글(pin)을 함께 보내고,
    지금 글이 말하는 금액·용도가 그때와 같으면 나중에 바꾼 칸 값이 이긴다. 확인 질문의 답은 원문과 따로 받는다."""
    TEXT = '프리미어로 영상 편집하고 가끔 게임도 해요.\n조용했으면 좋겠고, 본체 예산은 100만원이에요.'

    def setUp(self):
        self.pool = pool()
        self.fb = patch.object(A, '_fallback_order', lambda: ['claude'])
        self.fb.start()

    def tearDown(self):
        self.fb.stop()

    def fill(self, **kw):
        fake, calls = answers(llm.LLMProviderError('x', transient=True))
        with patch.object(llm, 'call', side_effect=fake):
            r = A.fill_core(self.pool, A.FillBody(**kw), None, FakeChecker())
        return r, (calls[0]['prompt'] if calls else None)

    def test_request_text_reaches_llm_with_newlines(self):
        r, prompt = self.fill(requestText=self.TEXT, purpose='gaming', budgetTotal=2_000_000)
        self.assertEqual((r['purpose'], r['budgetTotal'], r['purposeFrom'], r['budgetFrom']), ('creator', 1_000_000, 'text', 'text'))
        self.assertIn('[고객 요청]\n' + self.TEXT + '\n\n', prompt)               # 줄바꿈까지 원문 그대로 AI 에게 간다
        self.assertNotIn('화면에서 조건을 바꿨다', prompt)
        self.assertIsNone(r['note'])

    def test_text_budget_then_close_and_raise_field_then_rerecommend(self):
        # ① 글의 100만원으로 추천 -> 화면 예산 칸이 1,000,000 이 된다
        r1, _ = self.fill(requestText=self.TEXT, budgetTotal=2_000_000)
        self.assertEqual((r1['budgetTotal'], r1['budgetFrom']), (1_000_000, 'text'))
        # ② 제안을 닫고 예산 칸을 2,000,000 으로 올림(그때 글이 표식) -> 같은 글로 다시 추천: 칸 값이 이긴다
        r2, prompt = self.fill(requestText=self.TEXT, budgetTotal=2_000_000, budgetPin=self.TEXT)
        self.assertEqual((r2['budgetTotal'], r2['budgetFrom']), (2_000_000, 'field'))
        self.assertEqual(r2['note'], '예산은 적어 주신 100만원 대신 예산 칸의 2,000,000원으로 추천했어요.')
        self.assertIn('[고객 요청]\n' + self.TEXT, prompt)                         # 원문은 지우지 않고 그대로
        self.assertIn('전체 예산 → 2,000,000원', prompt)
        self.assertIn('"totalBudget": 2000000', prompt)
        self.assertEqual(r2['purpose'], 'creator')                                 # 글의 용도는 그대로 읽는다
        # ③ 금액은 그대로 두고 말만 덧붙이거나 띄어쓰기만 바꿔도 칸 값 유지
        more = self.TEXT.replace('100만원', '100 만원') + ' 흰색 케이스면 좋겠어요.'
        r3, _ = self.fill(requestText=more, budgetTotal=2_000_000, budgetPin=self.TEXT)
        self.assertEqual((r3['budgetTotal'], r3['budgetFrom']), (2_000_000, 'field'))
        # ④ 글의 금액을 고쳐 쓰면(나중에 바꾼 쪽이 글) 글이 이긴다
        r4, _ = self.fill(requestText=self.TEXT.replace('100만원', '150만원'), budgetTotal=2_000_000, budgetPin=self.TEXT)
        self.assertEqual((r4['budgetTotal'], r4['budgetFrom']), (1_500_000, 'text'))

    def test_both_scope_spacing_keeps_pin_but_real_change_releases(self):
        # Codex 재현: 전체·부품 금액을 나눠 받은 정상 해석은 원 단위 값으로 비교한다(띄어쓰기만 바꾸면 표식 유지)
        pin = 'PC 전체 100만원, 그래픽카드 80만원'
        r, _ = self.fill(requestText=pin, budgetTotal=2_000_000, budgetPin=pin)
        self.assertEqual((r['budgetTotal'], r['budgetFrom']), (2_000_000, 'field'))
        r, _ = self.fill(requestText='PC 전체 100 만원, 그래픽카드 80 만원', budgetTotal=2_000_000, budgetPin=pin)
        self.assertEqual((r['kind'], r['budgetTotal'], r['budgetFrom']), ('proposal', 2_000_000, 'field'))
        # 대조: 전체 금액을 150만원으로 실제로 바꾸면 표식이 풀리고 글의 금액(전체 150만원)을 쓴다
        r, _ = self.fill(requestText='PC 전체 150만원, 그래픽카드 80만원', budgetTotal=2_000_000, budgetPin=pin)
        self.assertEqual((r['budgetTotal'], r['budgetFrom']), (1_500_000, 'text'))
        self.assertIn('800,000원', r['note'])                                     # 부품 금액은 부품 상담에서 반영한다는 안내
        # 해석하지 못한 금액(단위 없음)은 원문으로 비교 -- 띄어쓰기는 같은 말, 숫자를 바꾸면 다시 묻는다
        r, _ = self.fill(requestText='본체 150', budgetTotal=1_500_000, budgetPin='본체  150 ')
        self.assertEqual((r['kind'], r['budgetTotal']), ('proposal', 1_500_000))
        r, _ = self.fill(requestText='본체 200', budgetTotal=1_500_000, budgetPin='본체 150')
        self.assertEqual(r['kind'], 'clarify')

    def test_purpose_button_after_text_wins_until_text_changes(self):
        r, _ = self.fill(requestText='영상 편집 위주로 써요', purpose='gaming')
        self.assertEqual((r['purpose'], r['purposeFrom']), ('creator', 'text'))
        r, prompt = self.fill(requestText='영상 편집 위주로 써요', purpose='gaming', purposePin='영상 편집 위주로 써요')
        self.assertEqual((r['purpose'], r['purposeFrom']), ('gaming', 'field'))
        self.assertIn('「게임」', r['note'])
        self.assertIn('용도 → 게임', prompt)
        r, _ = self.fill(requestText='영상 편집 위주로 써요', purpose='gaming', purposePin='')    # 버튼을 먼저 누르고 글을 씀
        self.assertEqual(r['purpose'], 'creator')

    def test_empty_budget_field_after_text(self):
        r, _ = self.fill(requestText='본체 100만원', budgetTotal=None, budgetPin='본체 100만원')
        self.assertEqual((r['budgetTotal'], r['budgetFrom']), (None, 'field'))
        self.assertIn('예산 칸을 비워', r['note'])

    def test_clarify_answer_keeps_original_context(self):
        # Codex 재현: 「영상 편집용, 전체80」 -> 단위 확인 -> 「전체 80만원 이하」. 답만 보내면 용도·원문이 사라졌다.
        text = '영상 편집용, 전체80'
        q, _ = self.fill(requestText=text, purpose='gaming')
        self.assertEqual(q['kind'], 'clarify')
        answer = q['choices'][0]
        self.assertEqual(answer, '전체 80만원 이하')
        r, prompt = self.fill(requestText=text, answer=answer, purpose='gaming', budgetTotal=2_000_000)
        self.assertEqual((r['kind'], r['purpose'], r['purposeFrom']), ('proposal', 'creator', 'text'))   # 원문의 용도
        self.assertEqual((r['budgetTotal'], r['budgetFrom']), (800_000, 'answer'))                       # 답의 예산
        self.assertIn('[고객 요청]\n' + text, prompt)                                # AI 가 원문을 받는다
        self.assertIn('확인 질문에 고객이 고른 답: 전체 80만원 이하', prompt)
        self.assertIsNone(r['note'])
        # 답한 뒤 같은 원문을 다시 보내면(화면이 원문을 답에 묶은 표식) 다시 묻지 않고 답한 예산을 쓴다
        r, _ = self.fill(requestText=text, purpose='creator', budgetTotal=800_000, budgetPin=text)
        self.assertEqual((r['kind'], r['budgetTotal']), ('proposal', 800_000))

    def test_fields_limits(self):
        A.FillBody(requestText='가' * 300, budgetPin='가' * 300, purposePin='가' * 300, answer='가' * 100)
        for k, n in (('requestText', 301), ('budgetPin', 301), ('purposePin', 301), ('answer', 101)):
            with self.subTest(k=k), self.assertRaises(Exception):
                A.FillBody(**{k: '가' * n})

    def test_route_accepts_intent_fields(self):
        app = FastAPI()
        app.include_router(A.router)

        @contextmanager
        def fake_connect():
            yield None
        fake, _ = answers(llm.LLMProviderError('x', transient=True))
        with patch.object(A.engine, 'connect', fake_connect), patch.object(D, 'load_pool', lambda conn, src=None: pool()), \
                patch.object(D, 'Checker', FakeChecker), patch.object(A.access_gate, 'check_rate', lambda *a, **k: 'v'), \
                patch.object(llm, 'call', side_effect=fake):
            r = TestClient(app).post('/api/pc-builder/fill', json={
                'selection': {}, 'locked': {}, 'mode': 'fill', 'purpose': 'gaming', 'budgetTotal': 2_000_000,
                'requestText': self.TEXT, 'answer': None, 'budgetPin': self.TEXT, 'purposePin': None})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()['budgetTotal'], r.json()['budgetFrom']), (2_000_000, 'field'))

    def test_built_bundle_has_intent_card(self):
        from pathlib import Path
        assets = Path(__file__).resolve().parents[1] / 'mockups' / 'mvp4' / 'pc-builder' / 'assets'
        js = '\n'.join(p.read_text(encoding='utf-8') for p in assets.glob('*.js'))
        for s in ('어떤 PC가 필요하세요?', '용도와 원하는 조건을 편하게 적어 주세요.', '사용할 용도와 원하는 조건', '용도를 빠르게 고르려면',
                  '이 내용으로 PC 추천받기', '선택한 부품 유지하고 추천받기', '원하는 PC 설명하기', 'budgetPin', 'purposePin'):
            self.assertIn(s, js)
        for gone in ('원하는 조건을 말로 입력하기', 'AI로 빈칸 채우기', '모든 조건', '완벽하게', '100% 반영'):
            self.assertNotIn(gone, js)

    def test_intent_node_regression(self):
        import shutil
        import subprocess
        from pathlib import Path
        node = shutil.which('node')
        if not node:
            self.skipTest('node 없음')
        root = Path(__file__).resolve().parents[1] / 'frontend' / 'pc-builder'
        r = subprocess.run([node, '--test', str(root / 'tests' / 'intent.test.mjs')], capture_output=True, text=True,
                           encoding='utf-8', cwd=root)
        self.assertEqual(r.returncode, 0, r.stdout[-1500:] + r.stderr[-800:])
        self.assertIn('# fail 0', r.stdout)
        self.assertIn('# pass 5', r.stdout)
