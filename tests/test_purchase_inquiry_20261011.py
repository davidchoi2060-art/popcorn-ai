"""구매 상담 신청 — 고객이 연락처를 남기고 관리자가 처리한다(2026-10-11 관리자 확인 R4·F12·M4).

DB 없이 확인하는 것: 입력 검사 · 연락처 가리기 · 화면 등록(메뉴·머리말) · 마이그레이션 사슬.
DB 를 거치는 저장·권한은 로컬 Postgres 로 따로 확인했다(PR 본문).
"""
import importlib.util
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
        m = PI.form_meta()
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
        self.assertNotIn('contact_phone', src, 'consults screen never carries contacts')


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
