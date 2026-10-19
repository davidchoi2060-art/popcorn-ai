"""구매 상담 신청 — 고객이 연락처를 남기고 관리자가 처리한다(2026-10-11 관리자 확인 R4·F12·M4).

DB 없이 확인하는 것: 입력 검사 · 연락처 가리기 · 화면 등록(메뉴·머리말) · 마이그레이션 사슬.
DB 를 거치는 저장·권한은 로컬 Postgres 로 따로 확인했다(PR 본문).
"""
import importlib.util
from contextlib import contextmanager
from unittest.mock import patch
import pathlib
import unittest

from fastapi import HTTPException
from pydantic import ValidationError

from api import mvp3_purchase_inquiry as PI, admin_purchase_inquiries as AP
from api import admin_nav, admin_page_intro

ROOT = pathlib.Path(__file__).resolve().parents[1]


def body(**kw):
    base = {'topic': '여러 대 구매', 'consent': True, 'phone': '010-1234-5678'}
    base.update(kw)
    return PI.InquiryBody(**base)


class CustomerInput(unittest.TestCase):
    def test_ok_and_cleaned(self):
        phone, email, name, msg = PI._clean(body(phone=' 010 1234 5678 ', name='  QA-김 ', message=' 3대 '))
        self.assertEqual((phone, email, name, msg), ('01012345678', None, 'QA-김', '3대'))

    def test_needs_contact(self):
        with self.assertRaises(HTTPException) as c:
            PI._clean(body(phone=None))
        self.assertEqual(c.exception.status_code, 422)
        self.assertIn('전화번호나 이메일', c.exception.detail)

    def test_email_only_is_enough(self):
        self.assertEqual(PI._clean(body(phone=None, email='qa@example.com'))[1], 'qa@example.com')

    def test_bad_formats(self):
        for kw in ({'phone': '1234'}, {'phone': None, 'email': 'no-at'}, {'topic': '환불'}):
            with self.subTest(kw=kw), self.assertRaises(HTTPException):
                PI._clean(body(**kw))

    def test_consent_required_and_strict(self):
        with self.assertRaises(HTTPException):
            PI._clean(body(consent=False))
        with self.assertRaises(ValidationError):
            body(consent='true')

    def test_unknown_fields_and_lengths_rejected(self):
        with self.assertRaises(ValidationError):
            body(price=1)
        with self.assertRaises(ValidationError):
            body(message='가' * 501)

    def test_form_meta_comes_from_server(self):
        from contextlib import contextmanager
        from unittest.mock import patch
        @contextmanager
        def begin():
            yield object()
        # 방문자 연결(쿠키)을 맺는다 -- 신청 전에 맺어야 응답 불명 신청을 같은 브라우저로 확인할 수 있다(by-key).
        with patch.object(PI.engine, 'begin', begin), patch.object(PI.visitor, 'resolve', return_value=7) as resolve:
            m = PI.form_meta(object(), PI.Response())
        self.assertEqual(resolve.call_count, 1)
        self.assertEqual(m['topics'], list(PI.TOPICS))
        self.assertIn('%d일' % PI.KEEP_DAYS, m['consent_text'])

    def test_note_does_not_promise_order_or_price(self):
        src = (ROOT / 'api/mvp3_purchase_inquiry.py').read_text(encoding='utf-8')
        for word in ('주문을 받', '결제', '할인해', '확정'):
            self.assertNotIn(word, src.split("'note':", 1)[1][:120])


class AdminView(unittest.TestCase):
    def test_masks_for_viewer(self):
        self.assertEqual(AP._mask_phone('010-1234-5678'), '010-****-5678')
        self.assertEqual(AP._mask_email('qa.user@example.com'), 'qa***@example.com')
        self.assertIsNone(AP._mask_phone(None))

    def test_write_roles(self):
        self.assertTrue(AP._can_write({'role': 'operator'}))
        self.assertTrue(AP._can_write({'role': 'owner'}))
        self.assertFalse(AP._can_write({'role': 'viewer'}))
        self.assertFalse(AP._can_write(None))

    def test_registered_in_menu_and_intro(self):
        hrefs = [i[1] for g in admin_nav.NAV for i in g[2]]
        self.assertIn('/admin2/purchase-inquiries', hrefs)
        self.assertIn('/admin2/purchase-inquiries', admin_page_intro.INTRO)
        groups = admin_nav.new_admin_nav('/admin2/purchase-inquiries')
        self.assertEqual([g['label'] for g in groups if g['active']], ['주문 운영'])

    def test_consults_drawer_links_inquiries(self):
        src = (ROOT / 'api/admin_mvp3_consults.py').read_text(encoding='utf-8')
        self.assertIn('FROM purchase_inquiries', src)
        tpl = (ROOT / 'templates/admin/mvp3_consults.html.j2').read_text(encoding='utf-8')
        self.assertIn("/admin2/purchase-inquiries#", tpl)
        # 2026-10-18 관리자 정리 기획 A02: 등록 연락처 카드는 생겼지만 가린 번호만 싣는다.
        # 원래 번호가 응답으로 나가는 자리는 _mask_phone 를 거치는 한 곳뿐이어야 한다.
        uses = [ln for ln in src.splitlines() if 'contact_phone' in ln]
        self.assertEqual(len(uses), 2, uses)
        self.assertIn('_mask_phone(row["contact_phone"])', src)
        self.assertNotIn("'contact_phone':", src)
        self.assertNotIn('"contact_phone":', src)


class Migration(unittest.TestCase):
    def test_chain(self):
        p = ROOT / 'db/migrations/versions/0139_purchase_inquiries.py'
        spec = importlib.util.spec_from_file_location('m0139', p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        self.assertEqual((m.revision, m.down_revision), ('0139', '0138'))
        src = p.read_text(encoding='utf-8')
        for must in ('consent_at', 'purge_at', 'contact_phone IS NOT NULL OR contact_email IS NOT NULL'):
            self.assertIn(must, src)


if __name__ == '__main__':
    unittest.main()


class ClientKey(unittest.TestCase):
    """같은 요청 키는 한 번만 접수하고, 응답을 못 받은 화면은 같은 키로 결과를 확인한다(0163 · /mvp4 v11)."""

    def test_key_format(self):
        self.assertEqual(body(client_key='iq-abc123-1').client_key, 'iq-abc123-1')
        for bad in ('short', 'has space x', 'x' * 65, '한글키입니다요'):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                body(client_key=bad)

    def conn(self, found):
        class Conn:
            def execute(self, *a, **k):
                class R:
                    def scalar(self_inner):
                        return found
                return R()
        @contextmanager
        def ctx():
            yield Conn()
        return ctx

    def test_replay_returns_same_number_without_new_insert(self):
        req = type('Req', (), {'headers': {'origin': 'https://popcornai.co.kr', 'host': 'popcornai.co.kr'}})()
        with patch.object(PI, 'same_origin', lambda r: None),              patch.object(PI.engine, 'begin', self.conn('PI-1234')),              patch.object(PI.visitor, 'resolve', return_value=7),              patch.object(PI.access_gate, 'check_rate', side_effect=AssertionError('rate limit must not run on replay')):
            out = PI.create_inquiry(body(client_key='iq-abc123-1'), req, PI.Response())
        self.assertEqual((out['inquiry_no'], out['already']), ('PI-1234', True))

    def test_lookup_found_and_not_found(self):
        for found in ('PI-1234', None):
            with self.subTest(found=found), patch.object(PI.engine, 'connect', self.conn(found)),                  patch.object(PI.visitor, 'resolve', return_value=7):
                out = PI.inquiry_by_key('iq-abc123-1', object(), PI.Response())
            self.assertEqual(out['found'], found is not None)

    def test_lookup_without_visitor_is_not_a_no(self):
        with patch.object(PI.engine, 'connect', self.conn(None)), patch.object(PI.visitor, 'resolve', return_value=None):
            with self.assertRaises(HTTPException) as c:
                PI.inquiry_by_key('iq-abc123-1', object(), PI.Response())
        self.assertEqual(c.exception.status_code, 403)

    def test_migration_0163_chain(self):
        path = ROOT / 'db/migrations/versions/0163_purchase_inquiry_client_key.py'
        spec = importlib.util.spec_from_file_location('m0163', path)
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        self.assertEqual((mod.revision, mod.down_revision), ('0163', '0162'))
