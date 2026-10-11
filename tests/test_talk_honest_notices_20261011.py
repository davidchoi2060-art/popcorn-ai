"""근거 없는 약속 막기 + 판매 안내 자료 — 2026-10-11 품질관리 고객 역할 회귀 고정.

고객 문장은 품질관리-20261011 고객1·2·3 결과.md 에 적힌 실제 문의다. AI 응답은 그때 받은
약속하는 말을 그대로 흉내 낸다 — 서버가 그 말을 안내 문장으로 바꾸는지 본다.
"""
import contextlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from api import talk, talk_rules as TR, talk_schema as TS
from tests.test_talk_rules_20261010 import run_parse as _run_parse, vocab, _Conn
from api import talk_answer as TA


def _ai(state, reply='네.'):
    obj = {'pc': True, 'state': state, 'missing': [], 'evidence': [], 'reply': reply}
    return SimpleNamespace(text=json.dumps(obj, ensure_ascii=False), provider='t', model='t',
                           tokens_in=1, elapsed_sec=0.1)


def run_parse(text, ai_state, *, written=None, **kw):
    with contextlib.ExitStack() as st:
        st.enter_context(patch.object(talk.shop_notices, 'load_written', lambda conn: dict(written or {})))
        return _run_parse(text, ai_state, **kw)


OFFICE = {'usages': ['사무·인강'], 'budget_won': 800000}


class PurchaseTopics(unittest.TestCase):
    def test_os_promise_replaced_with_default_notice(self):
        r = run_parse('윈도우 깔려서 오나요?', {}, ai_reply='네, 윈도우를 깔아서 배송해드립니다.')
        self.assertNotIn('배송해드립니다', r['reply'])
        self.assertIn('윈도우(운영체제) 설치 여부는 상품마다 달라', r['reply'])
        self.assertTrue(r['pc_related'])

    def test_admin_written_notice_wins_over_default(self):
        r = run_parse('윈도우 깔려서 오나요?', {}, ai_reply='네, 깔아 드려요.',
                      written={'os': '윈도우 11 홈을 설치해서 보내 드려요.'})
        self.assertTrue(r['reply'].startswith('윈도우 11 홈을 설치해서 보내 드려요.'))

    def test_quantity_order_not_confirmed(self):
        r = run_parse('이걸로 5대 주문하고 싶어요', OFFICE, ai_reply='80만원 PC 5대를 주문하시려는군요. 확인했습니다.')
        self.assertNotIn('확인했습니다', r['reply'])
        self.assertIn('한 대 기준', r['reply'])
        self.assertIn('주문과 결제를 받지 않아요', r['reply'])

    def test_payment_and_tax_invoice(self):
        for q in ('법인카드로 결제 되나요?', '세금계산서 발행 되나요?', '카드 영수증이나 현금영수증 되나요'):
            with self.subTest(q=q):
                r = run_parse(q, {}, ai_reply='결제 담당팀에 확인해 드릴게요.')
                self.assertNotIn('담당팀', r['reply'])
                self.assertIn('쇼핑몰', r['reply'])

    def test_monitor_included_not_promised(self):
        for q in ('모니터도 같이 오나요?', '모니터 포함해서 100만원이면요?', '모니터도 같이 사면 얼마'):
            with self.subTest(q=q):
                r = run_parse(q, {}, ai_reply='네, 모니터 포함 구성도 가능합니다.')
                self.assertNotIn('가능합니다', r['reply'])
                self.assertIn('본체 기준', r['reply'])

    def test_warranty_delivery_discount(self):
        cases = (('A/S 기간은 얼마나 돼요?', '보증 기간과 A/S'),
                 ('배송이랑 설치도 해주시나요?', '배송과 설치 안내'),
                 ('5대 사면 할인 되나요?', '할인과 가격 조정'))
        for q, want in cases:
            with self.subTest(q=q):
                r = run_parse(q, {}, ai_reply='상품 확정 후 안내해 드릴게요.')
                self.assertIn(want, r['reply'])

    def test_two_monitor_connection_is_not_quantity(self):
        self.assertEqual(TR.purchase_topics('모니터 두 대 연결되는 사무용 PC 100만원'), [])

    def test_plain_question_keeps_ai_reply(self):
        r = run_parse('사무용 80만원', OFFICE, ai_reply='사무용 PC를 찾고 계시는군요.')
        self.assertEqual(r['reply'], '사무용 PC를 찾고 계시는군요.')


class UnsupportedConditions(unittest.TestCase):
    def test_white_case_said_not_applied(self):
        st = {'usages': ['게임'], 'budget_won': 1700000, 'prefs': ['화이트'],
              'game': {'names': ['배틀그라운드'], 'grade': 'C', 'grade_src': 'catalog', 'resolution': None}}
        r = run_parse('배그랑 스팀게임 이것저것 170 정도 흰색 케이스', st,
                      ai_reply='흰색 케이스로 맞춰드리겠습니다.')
        self.assertNotIn('맞춰드리겠습니다', r['reply'])
        self.assertIn('흰색 케이스', r['reply'])
        self.assertIn('반영하지 못해요', r['reply'])

    def test_pref_from_previous_turn_not_repeated(self):
        prev = {'usages': ['사무·인강'], 'budget_won': 800000, 'prefs': ['저소음']}
        st = dict(prev, budget_won=900000)
        r = run_parse('90만원으로 올릴게요', st, prev=prev, ai_reply='90만원으로 찾아볼게요.')
        self.assertEqual(r['reply'], '90만원으로 찾아볼게요.')

    def test_ram_storage_gpu_listed(self):
        conds = TR.unsupported_conditions('영상 편집용인데 램 64GB에 2TB, RTX 4070 이상', TS.TalkState())
        self.assertIn('메모리 64GB', conds)
        self.assertIn('저장공간 2TB', conds)
        self.assertTrue(any(c.startswith('그래픽카드 RTX 4070') for c in conds))


class AdminTags(unittest.TestCase):
    def test_hit_records_topic_and_unapplied_tags(self):
        seen = {}
        ans = TA.AnswerResult(answer='', narrowing=TS.NARROWING_WIDE)
        with contextlib.ExitStack() as st:
            st.enter_context(patch.object(talk.engine, 'connect', lambda: _Conn()))
            st.enter_context(patch.object(talk.engine, 'begin', lambda: _Conn()))
            st.enter_context(patch.object(talk.access_gate, 'check_rate', lambda *a, **k: None))
            st.enter_context(patch.object(talk.TS, 'load_vocab', lambda conn: vocab()))
            st.enter_context(patch.object(talk.shop_notices, 'load_written', lambda conn: {}))
            st.enter_context(patch.object(talk.TA, 'run_parallel', lambda a, b: (_ai({}), ans)))
            st.enter_context(patch.object(talk.TA, 'is_game_related', lambda *a: False))
            st.enter_context(patch.object(talk, '_record_hit', lambda *a, **k: seen.update(k)))
            talk.parse_talk(talk.ParseBody(text='세금계산서 되나요? 램 64GB로'), request=None)
        self.assertIn('주제:payment', seen['matched'])
        self.assertIn('미반영:메모리 64GB', seen['matched'])

    def test_admin_screen_labels_tags(self):
        from api import admin_mvp3_consults as MC
        self.assertEqual(MC._terms(['budget_won', '주제:os', '미반영:흰색 케이스']),
                         ['예산', '문의 주제: 운영체제(윈도우) 설치', '반영 못 함: 흰색 케이스'])

    def test_test_rule_covers_qa_label(self):
        from api import admin_mvp3_consults as MC
        self.assertIn("ILIKE 'QA-%'", MC.HIT_IS_TEST)
        self.assertEqual(MC._hit_origin(True), 'TRUE')
        self.assertIn('t.raw_text', MC._saved_origin(False))


class ShopNoticeLoader(unittest.TestCase):
    def test_load_failure_falls_back_to_defaults(self):
        class Broken:
            def execute(self, *a, **k):
                raise RuntimeError('no table')
        self.assertEqual(talk.shop_notices.load_written(Broken()), {})

    def test_topics_have_unique_keys_and_labels(self):
        keys = [t[0] for t in TR.PURCHASE_TOPICS]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(t[1] and t[3] for t in TR.PURCHASE_TOPICS))


if __name__ == '__main__':
    unittest.main()
