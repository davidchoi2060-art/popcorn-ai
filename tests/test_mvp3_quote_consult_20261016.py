"""견적 보관 연락처 · 보관 견적으로 상담 신청 접수 (2026-10-16 대표 지시).

· 가짜 저장소(Store)로 확인: 처음 보관은 전화번호+동의 필수(422 contact_required) · 두 번째는 연락처 없이 ·
  재전송은 연락처 없이 같은 견적 · 쇼핑몰 이동용 보관('handoff')은 연락처를 받지 않는다.
· 로컬 Postgres(마이그레이션 0158 적용본)가 있으면 실제 DB 로 확인: 연락처 GET/PUT · 상담 신청 접수 ·
  중복 방지 · 남의 견적 404 · 연락처 없음 409 · 지우기 작업. 없으면 건너뛴다.
"""
import datetime as dt
import os
import unittest
import uuid
from unittest.mock import patch
from uuid import UUID

from fastapi import FastAPI, HTTPException, Response
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api import mvp3_contact as C, mvp3_purchase_inquiry as PI, mvp3_quote_consult as QC, mvp3_saved_quotes as m
from tests import test_mvp3_saved_quotes as base


def contact(**kw):
    return C.ContactIn(**{'phone': '010-1234-5678', 'consent': True, **kw})


class ContactRules(unittest.TestCase):
    def test_clean_requires_phone_and_consent(self):
        self.assertEqual(C.clean(contact(name=' 홍 ', email=' a@b.co ')), ('010-1234-5678', '홍', 'a@b.co'))
        for kw in ({'consent': False}, {'phone': None}, {'phone': ''}, {'phone': '1234'}, {'email': 'no-at'}):
            with self.subTest(kw=kw), self.assertRaises(HTTPException) as c:
                C.clean(contact(**kw))
            self.assertEqual(c.exception.status_code, 422)

    def test_consent_must_be_a_real_boolean_and_no_unknown_fields(self):
        with self.assertRaises(ValidationError):
            C.ContactIn(phone='010-1234-5678', consent='true')
        with self.assertRaises(ValidationError):
            C.ContactIn(phone='010-1234-5678', consent=True, marketing=True)

    def test_mask_never_shows_the_middle(self):
        self.assertEqual(C.mask_phone('010-1234-5678'), '010-****-5678')
        self.assertEqual(C.mask_phone('01012345678'), '010-****-5678')
        self.assertEqual(C.mask_phone('02-123-4567'), '02-****-4567')
        self.assertEqual(C.mask_phone('031-123-4567'), '031-****-4567')
        self.assertIsNone(C.mask_phone(None))
        self.assertNotIn('1234', C.mask_phone('010-1234-5678'))

    def test_view_is_masked_only(self):
        v = C.view({'contact_phone': '010-1234-5678', 'contact_name': '홍', 'contact_email': 'a@b.co'})
        self.assertEqual(v, {'has_contact': True, 'masked_phone': '010-****-5678', 'name': '홍'})
        self.assertEqual(C.view(None), {'has_contact': False, 'masked_phone': None, 'name': None})

    def test_one_definition_of_regex_and_keep_days(self):
        self.assertIs(PI.PHONE_RE, C.PHONE_RE)
        self.assertIs(PI.EMAIL_RE, C.EMAIL_RE)
        self.assertEqual(PI.KEEP_DAYS, C.KEEP_DAYS)

    def test_from_quote_topic_is_an_existing_one(self):
        self.assertIn(QC.FROM_QUOTE_TOPIC, PI.TOPICS)
        self.assertEqual(QC.FROM_QUOTE_TOPIC, '주문 희망')


class SaveWithContact(base.SavedQuotesTest):
    """base 의 가짜 저장소·패치를 그대로 쓴다(그쪽 검사도 이 클래스에서 한 번 더 돈다 — 기본은 연락처가 등록된 방문자)."""

    def test_first_save_without_contact_is_422_with_machine_flag(self):
        self.store.contact = None
        with self.assertRaises(HTTPException) as c:
            m.save_quote(base.body(), base.request(), Response())
        self.assertEqual(c.exception.status_code, 422)
        self.assertTrue(c.exception.detail['contact_required'])
        self.assertEqual(self.store.rows, [], 'nothing saved')
        self.assertEqual(self.confirm.call_count, 0, 'mall not asked')

    def test_first_save_with_contact_registers_and_masks(self):
        self.store.contact = None
        r = m.save_quote(base.body(contact=contact(name='홍')), base.request(), Response())
        self.assertEqual(r['contact'], {'has_contact': True, 'masked_phone': '010-****-5678', 'name': '홍'})
        self.assertEqual(len(self.store.rows), 1)
        self.assertEqual(self.store.contact['contact_phone'], '010-1234-5678')
        self.assertNotIn('010-1234-5678', str(r), 'full phone never returned')

    def test_second_save_reuses_contact_without_input(self):
        self.store.contact = None
        m.save_quote(base.body(contact=contact()), base.request(), Response())
        before = dict(self.store.contact)
        r = m.save_quote(base.body(request_id=UUID(int=2), expected_price=1500000), base.request(), Response())
        self.assertEqual(len(self.store.rows), 2)
        self.assertEqual(r['contact']['masked_phone'], '010-****-5678')
        self.assertEqual(self.store.contact, before, 'profile untouched')

    def test_bad_contact_is_422_before_rate_limit_and_saves_nothing(self):
        self.store.contact = None
        for bad in (contact(consent=False), contact(phone='abc')):
            with self.assertRaises(HTTPException) as c:
                m.save_quote(base.body(contact=bad), base.request(), Response())
            self.assertEqual(c.exception.status_code, 422)
        self.assertEqual((self.store.rows, self.store.contact), ([], None))

    def test_replay_needs_no_contact_and_same_fingerprint(self):
        self.store.contact = None
        first = m.save_quote(base.body(contact=contact()), base.request(), Response())
        self.store.contact = None            # 기한이 지나 사라진 뒤에도 같은 요청의 재전송은 같은 견적을 돌려준다
        again = m.save_quote(base.body(), base.request(), Response())
        self.assertEqual(again['quote']['id'], first['quote']['id'])
        self.assertEqual(len(self.store.rows), 1)

    def test_contact_and_purpose_are_not_in_the_fingerprint(self):
        a = m.fingerprint(base.body())
        self.assertEqual(a, m.fingerprint(base.body(contact=contact())))
        self.assertEqual(a, m.fingerprint(base.body(purpose='handoff')))

    def test_handoff_purpose_saves_without_asking_or_storing_contact(self):
        self.store.contact = None
        r = m.save_quote(base.body(purpose='handoff'), base.request(), Response())
        self.assertEqual(len(self.store.rows), 1)
        self.assertIsNone(self.store.contact)
        self.assertFalse(r['contact']['has_contact'])

    def test_purpose_is_closed_set(self):
        with self.assertRaises(ValidationError):
            base.body(purpose='anything')

    def test_http_422_body_carries_flag_and_consent_text(self):
        self.store.contact = None
        with self.client() as client:
            headers = {'X-Access-Key': 'a' * 64, 'Origin': 'https://example.invalid'}
            res = client.post('/api/mvp3/saved-quotes', json=base.body().model_dump(mode='json'), headers=headers)
            self.assertEqual(res.status_code, 422)
            d = res.json()['detail']
            self.assertEqual((d['error'], d['contact_required']), ('contact_required', True))
            self.assertEqual(d['consent_text'], C.CONSENT_TEXT)


# ---- 실제 Postgres -----------------------------------------------------------------------------------
def _db_ready():
    url = os.environ.get('DATABASE_URL') or ''
    if '127.0.0.1' not in url and 'localhost' not in url:
        return False
    try:
        from sqlalchemy import text
        from api.db import engine
        with engine.connect() as c:
            return bool(c.execute(text("SELECT to_regclass('public.mvp3_visitor_contacts')")).scalar())
    except Exception:                                               # noqa: BLE001
        return False


@unittest.skipUnless(_db_ready(), '0158 이 적용된 루프백 Postgres 가 없어 실DB 검사를 건너뜁니다')
class OnPostgres(unittest.TestCase):
    ORIGIN = {'Origin': 'https://example.invalid'}

    def setUp(self):
        from sqlalchemy import text
        from api.db import engine
        self.text, self.engine = text, engine
        app = FastAPI()
        app.include_router(QC.router)
        app.include_router(m.router)
        self.client = TestClient(app, base_url='https://example.invalid')
        self.key = uuid.uuid4().hex * 2
        self.headers = {'X-Access-Key': self.key, **self.ORIGIN}
        self.made_users = []
        m.access_gate._reset_for_test()
        # 방문자 쿠키를 받는다(GET 목록이 심는다)
        r = self.client.get('/api/mvp3/saved-quotes?limit=1', headers=self.headers)
        self.assertEqual(r.status_code, 200)
        self.uid = self.one('SELECT user_id FROM users WHERE anon_key = :k', k=self.client.cookies.get('pc_vid'))
        self.addCleanup(self.cleanup)

    def one(self, sql, **p):
        with self.engine.connect() as c:
            return c.execute(self.text(sql), p).scalar()

    def run_sql(self, sql, **p):
        with self.engine.begin() as c:
            c.execute(self.text(sql), p)

    def cleanup(self):
        self.run_sql('DELETE FROM purchase_inquiries WHERE user_id = :u', u=self.uid)
        self.run_sql('DELETE FROM mvp3_saved_recommendations WHERE user_id = :u', u=self.uid)
        self.run_sql('DELETE FROM mvp3_visitor_contacts WHERE user_id = :u', u=self.uid)
        self.run_sql('DELETE FROM users WHERE user_id = :u', u=self.uid)

    def quote(self, key=None):
        qid = str(uuid.uuid4())
        self.run_sql("INSERT INTO mvp3_saved_recommendations (quote_id, user_id, owner_key_hash, request_id,"
                     " request_basis, product_snapshot, talk_state) VALUES (:q, :u, :o, :r, repeat('b', 64),"
                     " CAST('{\"product_code\": 123, \"name\": \"t\", \"price\": 1000000}' AS jsonb), CAST('{}' AS jsonb))",
                     q=qid, u=self.uid, o=m.hashlib.sha256((key or self.key).encode('ascii')).hexdigest(), r=str(uuid.uuid4()))
        return qid

    def put(self, **body):
        return self.client.put('/api/mvp3/contact', json={'phone': '010-1234-5678', 'consent': True, **body},
                               headers=self.headers)

    def test_contact_get_put_masked_only(self):
        r = self.client.get('/api/mvp3/contact', headers=self.headers).json()
        self.assertEqual((r['has_contact'], r['masked_phone']), (False, None))
        self.assertEqual(r['consent_text'], C.CONSENT_TEXT)
        self.assertEqual(self.put(name='홍').status_code, 200)
        r = self.client.get('/api/mvp3/contact', headers=self.headers).json()
        self.assertEqual((r['has_contact'], r['masked_phone'], r['name']), (True, '010-****-5678', '홍'))
        self.assertNotIn('1234', str(r))
        row = self.one('SELECT purge_at - now() FROM mvp3_visitor_contacts WHERE user_id = :u', u=self.uid)
        self.assertTrue(dt.timedelta(days=179) < row <= dt.timedelta(days=180))
        self.assertEqual(self.put(phone='010-9999-0000').json()['masked_phone'], '010-****-0000')
        self.assertEqual(self.one('SELECT count(*) FROM mvp3_visitor_contacts WHERE user_id = :u', u=self.uid), 1)

    def test_put_rejects_bad_input_and_cross_origin(self):
        self.assertEqual(self.put(consent=False).status_code, 422)
        self.assertEqual(self.put(phone='12').status_code, 422)
        res = self.client.put('/api/mvp3/contact', json={'phone': '010-1234-5678', 'consent': True},
                              headers={'X-Access-Key': self.key, 'Origin': 'https://evil.invalid'})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.one('SELECT count(*) FROM mvp3_visitor_contacts WHERE user_id = :u', u=self.uid), 0)

    def test_expired_contact_is_treated_as_missing(self):
        self.put()
        self.run_sql("UPDATE mvp3_visitor_contacts SET purge_at = now() - interval '1 day' WHERE user_id = :u", u=self.uid)
        self.assertFalse(self.client.get('/api/mvp3/contact', headers=self.headers).json()['has_contact'])

    def from_quote(self, qid, **extra):
        return self.client.post('/api/mvp3/purchase-inquiries/from-quote', json={'quote_id': qid, **extra},
                                headers=self.headers)

    def test_from_quote_creates_one_inquiry_then_reports_already(self):
        qid = self.quote()
        self.put(name='홍', email='a@b.co')
        a = self.from_quote(qid, message=' 급해요 ')
        self.assertEqual(a.status_code, 200, a.text)
        a = a.json()
        self.assertEqual((a['already'], a['quote_id'], a['masked_phone']), (False, qid, '010-****-5678'))
        self.assertRegex(a['inquiry_no'], r'^PI-\d+$')
        row = self.run_row('SELECT topic, contact_phone, contact_name, contact_email, message, product_code,'
                           ' purge_at - now() AS keep FROM purchase_inquiries WHERE inquiry_no = :n', n=a['inquiry_no'])
        self.assertEqual((row['topic'], row['contact_phone'], row['contact_name'], row['contact_email'], row['message'],
                          row['product_code']), ('주문 희망', '010-1234-5678', '홍', 'a@b.co', '급해요', 123))
        self.assertTrue(dt.timedelta(days=179) < row['keep'] <= dt.timedelta(days=180))
        b = self.from_quote(qid).json()
        self.assertEqual((b['already'], b['inquiry_no']), (True, a['inquiry_no']))
        self.assertEqual(self.one('SELECT count(*) FROM purchase_inquiries WHERE quote_id = :q', q=qid), 1)

    def run_row(self, sql, **p):
        with self.engine.connect() as c:
            return c.execute(self.text(sql), p).mappings().one()

    def test_save_alone_creates_no_inquiry(self):
        self.quote(); self.put()
        self.assertEqual(self.one('SELECT count(*) FROM purchase_inquiries WHERE user_id = :u', u=self.uid), 0)

    def test_from_quote_without_contact_is_409_and_creates_nothing(self):
        qid = self.quote()
        r = self.from_quote(qid)
        self.assertEqual(r.status_code, 409)
        self.assertTrue(r.json()['detail']['contact_required'])
        self.assertEqual(self.one('SELECT count(*) FROM purchase_inquiries WHERE user_id = :u', u=self.uid), 0)

    def test_from_quote_unknown_or_foreign_quote_is_404(self):
        self.put()
        self.assertEqual(self.from_quote(str(uuid.uuid4())).status_code, 404)
        foreign = self.quote()
        other = {'X-Access-Key': uuid.uuid4().hex * 2, **self.ORIGIN}        # 다른 보관 키
        res = self.client.post('/api/mvp3/purchase-inquiries/from-quote', json={'quote_id': foreign}, headers=other)
        self.assertEqual(res.status_code, 404)
        self.assertEqual(self.one('SELECT count(*) FROM purchase_inquiries WHERE user_id = :u', u=self.uid), 0)

    def test_from_quote_cross_origin_and_extra_fields_rejected(self):
        qid = self.quote(); self.put()
        res = self.client.post('/api/mvp3/purchase-inquiries/from-quote', json={'quote_id': qid},
                               headers={'X-Access-Key': self.key, 'Origin': 'https://evil.invalid'})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.from_quote(qid, topic='기타').status_code, 422)

    def test_purged_inquiry_is_not_reused(self):
        qid = self.quote(); self.put()
        first = self.from_quote(qid).json()
        self.run_sql("UPDATE purchase_inquiries SET contact_phone = NULL, contact_email = NULL, contact_purged_at = now()"
                     " WHERE inquiry_no = :n", n=first['inquiry_no'])
        second = self.from_quote(qid).json()
        self.assertEqual(second['already'], False)
        self.assertNotEqual(second['inquiry_no'], first['inquiry_no'])

    def test_retention_purge_clears_visitor_contact(self):
        self.put(name='홍')
        self.run_sql("UPDATE mvp3_visitor_contacts SET purge_at = now() - interval '1 day' WHERE user_id = :u", u=self.uid)
        from api import retention_purge as RP
        with patch.object(RP, 'TARGETS', tuple(t for t in RP.TARGETS if t[0] == 'visitor_contact')), \
                patch.object(RP, '_mask_memos', return_value=0):
            res = RP.purge('manual', apply=True)
        self.assertGreaterEqual(res['counts']['visitor_contact'], 1)
        row = self.run_row('SELECT contact_phone, contact_name, contact_purged_at FROM mvp3_visitor_contacts'
                           ' WHERE user_id = :u', u=self.uid)
        self.assertEqual((row['contact_phone'], row['contact_name']), (None, None))
        self.assertIsNotNone(row['contact_purged_at'])
        self.assertFalse(self.client.get('/api/mvp3/contact', headers=self.headers).json()['has_contact'])
        self.assertEqual(self.put().status_code, 200, 'can register again after purge')
        self.assertIsNone(self.one('SELECT contact_purged_at FROM mvp3_visitor_contacts WHERE user_id = :u', u=self.uid))


class Migration(unittest.TestCase):
    def test_chain_and_check(self):
        import importlib.util, pathlib
        p = pathlib.Path(__file__).resolve().parents[1] / 'db/migrations/versions/0158_mvp3_visitor_contacts.py'
        spec = importlib.util.spec_from_file_location('m0158', p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual((mod.revision, mod.down_revision), ('0158', '0157'))
        src = p.read_text(encoding='utf-8')
        for must in ('consent_at', 'purge_at', 'contact_purged_at', 'contact_phone IS NOT NULL OR contact_purged_at IS NOT NULL'):
            self.assertIn(must, src)


if __name__ == '__main__':
    unittest.main()
