"""관리자 고객 흐름 연결 읽기(2026-10-18 관리자 정리 기획 1묶음) — DB 없이 확인하는 것.

규칙 한 곳(api/admin_mvp3_links)이 미기록을 지어내지 않는지, 인계 note 표시가 쓰는 쪽(api/mvp3_handoff)과
같은 모양인지, 세 화면이 그 규칙을 가져다 쓰는지 본다. 실제 조회는 로컬 Postgres(alembic head + 시험 행)로
따로 확인했다(PR 본문).
"""
import json
import pathlib
import unittest

from api import admin_mvp3_links as L
from api import mvp3_handoff

ROOT = pathlib.Path(__file__).resolve().parents[1]
QID = '11111111-1111-4111-8111-111111111111'
SNAP = {'name': 'QA PC', 'price': 1500000, 'product_code': 121257, 'sets': 2, 'mall_url': 'https://x',
        'build': {'base_price': 1450000, 'changes': [
            {'slot': 'gpu', 'label': '그래픽카드', 'quantity': 1, 'before': {'name': 'A', 'price': 1},
             'after': {'name': 'B', 'price': 2}, 'delta': 50000},
            {'slot': 'ram', 'delta': 'x'}]}}


class QuoteView(unittest.TestCase):
    def test_total_is_one_pc_times_sets_and_changes_keep_names_and_delta_only(self):
        v = L.quote_view(SNAP)
        self.assertEqual((v['price'], v['sets'], v['total'], v['delta_sum']), (1500000, 2, 3000000, 50000))
        self.assertEqual(v['changes'], [{'label': '그래픽카드', 'before': 'A', 'after': 'B', 'quantity': 1, 'delta': 50000}])
        self.assertNotIn('price', v['changes'][0])          # 부품 단품가는 싣지 않는다

    def test_never_claims_purpose_or_fixed_price(self):
        v = L.quote_view(SNAP)
        self.assertEqual(v['purpose'], '목적 미기록')
        self.assertIn('접수 당시 확정 금액 아님', v['price_note'])

    def test_old_or_odd_snapshots(self):
        self.assertIsNone(L.quote_view(None))
        v = L.quote_view({'name': 'x', 'price': '1', 'sets': 99})
        self.assertEqual((v['price'], v['total'], v['sets'], v['changes']), (None, None, 1, []))


class KindAndLink(unittest.TestCase):
    def test_kind_reads_only_stored_marks(self):
        self.assertEqual(L.kind(None, None, {'parts': []})[0], 'free_build')
        self.assertEqual(L.kind({'ai_composed': True})[0], 'ai_composed')
        self.assertEqual(L.kind({'ai_composed': 'true'})[0], 'mall')        # 문자열은 표시로 읽지 않는다
        self.assertEqual(L.kind(None, 'A0123456789ABCDEF')[0], 'configuration')
        self.assertEqual(L.kind(), (None, '상품 연결 없음'))

    def test_quote_link_does_not_claim_source(self):
        self.assertEqual(L.link_label(QID), '견적 연결 있음 · 접수 경로 미기록')
        self.assertIn('접수 경로 미기록', L.link_label(None, 'A0123456789ABCDEF'))
        self.assertEqual(L.link_label(), '연결 자료 없음')


class HandoffNote(unittest.TestCase):
    def note(self, **extra):
        # api/mvp3_handoff 가 남기는 모양 그대로(json.dumps 기본 구분자 · ensure_ascii=False)
        return json.dumps({'source': 'mvp3', 'mvp3_quote_id': QID, 'unknown': [], **extra}, ensure_ascii=False)

    def test_same_marker_as_writer(self):
        self.assertIn(mvp3_handoff._marker(QID), self.note())
        self.assertIn('\'%"mvp3_quote_id": "\' || i.quote_id::text || \'"%\'', L.ho_for_quote_sql('i.quote_id'))

    def test_reads_quote_sets_changes_and_never_a_reason(self):
        n = L.handoff_note(self.note(sets=3, build={'base_price': 1, 'changes': SNAP['build']['changes']}))
        self.assertEqual((n['quote_id'], n['sets'], n['delta_sum']), (QID, 3, 50000))
        self.assertEqual((n['reason'], n['result']), ('이동 이유 미기록', '구매 결과 미확인'))

    def test_unreadable_or_other_source(self):
        self.assertIsNone(L.handoff_note('not json'))
        self.assertIsNone(L.handoff_note('{"source": "consult"}'))
        self.assertIsNone(L.handoff_note(None))


class Screens(unittest.TestCase):
    def read(self, rel):
        return (ROOT / rel).read_text(encoding='utf-8')

    def test_three_screens_use_the_shared_rules(self):
        for rel in ('api/admin_purchase_inquiries.py', 'api/admin_mvp3_consults.py', 'api/admin_ui_handoff_log.py'):
            with self.subTest(rel=rel):
                self.assertIn('admin_mvp3_links as L', self.read(rel))

    def test_inquiry_table_columns_match_empty_row(self):
        src = self.read('templates/admin/purchase_inquiries.html.j2')
        head = src.split('<thead>', 1)[1].split('</thead>', 1)[0]
        self.assertEqual(head.count('<th '), 7)
        self.assertIn('colspan="7"', src)
        self.assertIn('td.colSpan=7', src)
        self.assertNotIn('colSpan=6', src)

    def test_contact_rules_are_spelled_out(self):
        pi = self.read('templates/admin/purchase_inquiries.html.j2')
        self.assertIn('현재 등록 연락처와 다릅니다. 이 신청에 남긴 연락처를 확인해 주세요.', pi)
        self.assertIn('보관 기한이 지나 연락처와 신청 내용을 표시하지 않습니다.', pi)
        mc = self.read('api/admin_mvp3_consults.py')
        self.assertIn('연락 대상 아님 · 고객이 상담을 신청하기 전에는 먼저 연락하지 않습니다.', mc)

    def test_no_fixed_retention_days_on_screens(self):
        # 보유 기간 180일은 대표 미확정 — 화면에 고정 문구로 박지 않는다.
        for rel in ('templates/admin/purchase_inquiries.html.j2', 'templates/admin/mvp3_consults.html.j2',
                    'templates/admin/handoff_log.html.j2'):
            with self.subTest(rel=rel):
                self.assertNotIn('180일', self.read(rel))

    def test_new_filters_rejected_when_unknown(self):
        from api import admin_purchase_inquiries as AP
        self.assertEqual(set(AP.LINKS), {'quote', 'config', 'none'})
        self.assertEqual(set(AP.DUES), {'soon', 'expired'})


if __name__ == '__main__':
    unittest.main()
