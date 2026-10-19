"""/mvp4 AI 슈퍼컴퓨터(v15) — 고정 완제품 두 모델의 조회·문의 계약 (2026-10-19 대표 승인 v15).

DB 없이 확인하는 것: 조회 allowlist·판매 확인 상태 · 문의 입력 검사(주제·상품번호·수량·조합) ·
가격이 바뀌면 접수하지 않음 · 마이그레이션 사슬 · 고객 화면 소스에 외부 몰·로컬·시안 경로·관찰 가격이 없음.
"""
import importlib.util
import pathlib
import re
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from api import customer_supercomputer as SC
from api import mvp3_purchase_inquiry as PI
from api import admin_mvp3_links as L

ROOT = pathlib.Path(__file__).resolve().parents[1]
MVP4 = ROOT / 'mockups/mvp4'


def row(**kw):
    base = {'product_code': 129615, 'product_name': 'DELL Pro Max GB10 (128GB, M.2 2TB)', 'sale_price': 12052100,
            'status': '판매중', 'is_visible': True}
    base.update(kw)
    return base


class Catalog(unittest.TestCase):
    def test_on_sale_item_is_allowlisted(self):
        it = SC._item(row())
        self.assertEqual(set(it), {'product_code', 'name', 'official_name', 'storage', 'memory', 'price', 'sale_state'})
        self.assertEqual((it['storage'], it['price'], it['sale_state']), ('2TB', 12052100, 'on_sale'))
        self.assertEqual(SC._item(row(product_name='DELL Pro Max GB10 (128GB, M.2 4TB)'))['storage'], '4TB')

    def test_check_states_hide_price(self):
        for kw in ({'status': '품절'}, {'is_visible': False}, {'sale_price': 0}, {'sale_price': None},
                   {'product_name': '다른 상품 (M.2 2TB)'}, {'product_name': 'DELL Pro Max GB10 (128GB)'}):
            with self.subTest(kw=kw):
                it = SC._item(row(**kw))
                self.assertEqual((it['price'], it['sale_state']), (None, 'check'))

    def test_only_two_codes(self):
        self.assertEqual(SC.CODES, (129615, 129614))
        with self.assertRaises(HTTPException) as c:
            SC.supercomputer(100866, SC.Response())
        self.assertEqual(c.exception.status_code, 404)


def body(**kw):
    base = {'topic': 'AI 슈퍼컴퓨터 견적', 'consent': True, 'phone': '010-1234-5678', 'product_code': 129614,
            'fixed': {'intent': 'quote', 'quantity': 2, 'seen_unit_price': 14209400}}
    base.update(kw)
    return PI.InquiryBody(**base)


class Inquiry(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(PI._clean(body())[0], '010-1234-5678')
        self.assertEqual(PI._clean(body(topic='AI 도입 상담', fixed={'intent': 'adoption', 'quantity': 1, 'purpose': 'documents'}))[0], '010-1234-5678')

    def test_topic_must_match_intent_and_stays_out_of_general_list(self):
        for topic in ('AI 도입 상담', '여러 대 구매'):
            with self.subTest(topic=topic), self.assertRaises(HTTPException):
                PI._clean(body(topic=topic))
        with self.assertRaises(HTTPException):          # 고정 문의가 아니면 새 주제를 받지 않는다
            PI._clean(body(fixed=None))
        self.assertNotIn('AI 슈퍼컴퓨터 견적', PI.TOPICS)

    def test_product_and_combinations(self):
        for kw in ({'product_code': 100866}, {'product_code': None},
                   {'configuration_id': 'A0123456789ABCDEF'}, {'quote_id': '00000000-0000-0000-0000-000000000001'}):
            with self.subTest(kw=kw), self.assertRaises(HTTPException):
                PI._clean(body(**kw))

    def test_quantity_and_fields(self):
        for fixed in ({'intent': 'quote', 'quantity': 0}, {'intent': 'quote', 'quantity': 11}, {'intent': 'quote', 'quantity': '2'},
                      {'intent': 'buy', 'quantity': 1}, {'intent': 'quote', 'quantity': 1, 'purpose': 'x'},
                      {'intent': 'quote', 'quantity': 1, 'parts': []}):
            with self.subTest(fixed=fixed), self.assertRaises(ValidationError):
                body(fixed=fixed)

    def conn(self, item):
        class Conn:
            def execute(self, *a, **k):
                class R:
                    def scalar(self_inner):
                        return None
                    def mappings(self_inner):
                        return [item] if item else []
                return R()
        @contextmanager
        def ctx():
            yield Conn()
        return ctx

    def test_price_change_is_not_received(self):
        req = type('Req', (), {'headers': {}})()
        with patch.object(PI, 'same_origin', lambda r: None), \
             patch.object(PI.engine, 'begin', self.conn(row(product_code=129614, product_name='DELL Pro Max GB10 (128GB, M.2 4TB)', sale_price=14300000))), \
             patch.object(PI.visitor, 'resolve', return_value=7), patch.object(PI.access_gate, 'check_rate', return_value=None), \
             patch.object(PI, '_no', side_effect=AssertionError('must not number a changed-price inquiry')):
            with self.assertRaises(HTTPException) as c:
                PI.create_inquiry(body(client_key='sc-abc123'), req, PI.Response())
        self.assertEqual(c.exception.status_code, 409)
        self.assertEqual((c.exception.detail['error'], c.exception.detail['price']), ('price_changed', 14300000))

    def test_admin_kind(self):
        self.assertEqual(L.kind(None, None, None, {'product_code': 129614}), ('fixed_product', 'AI 슈퍼컴퓨터 완제품'))
        self.assertEqual(L.kind(None, None, None)[0], None)

    def test_migration_0165_chain(self):
        path = ROOT / 'db/migrations/versions/0165_purchase_inquiry_fixed_product.py'
        spec = importlib.util.spec_from_file_location('m0165', path)
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        self.assertEqual((mod.revision, mod.down_revision), ('0165', '0164'))
        for t in PI.FIXED_TOPICS.values():
            self.assertIn("'%s'" % t, mod.NEW)
            self.assertLessEqual(len(t), 16)           # topic VARCHAR(16)


class CustomerScreens(unittest.TestCase):
    FILES = ('supercomputer.html', 'supercomputer-inquiry.html', 'assets/js/live-supercomputer.js',
             'assets/js/supercomputer-home.js', 'assets/js/supercomputer-detail.js', 'assets/js/supercomputer-inquiry.js')

    def test_no_external_mall_local_design_or_observed_price(self):
        for f in self.FILES:
            src = (MVP4 / f).read_text(encoding='utf-8')
            with self.subTest(f=f):
                for bad in ('popcornpc', 'localhost', '127.0.0.1', 'design-only', 'supercomputer-data.js', 'GB10_DATA',
                            '12052100', '14209400', '12,052,100', '14,209,400', 'preview'):
                    self.assertNotIn(bad, src)

    def test_inquiry_posts_real_endpoint_and_success_needs_receipt(self):
        src = (MVP4 / 'assets/js/supercomputer-inquiry.js').read_text(encoding='utf-8')
        self.assertIn("call('POST', '/api/mvp3/purchase-inquiries'", src)
        self.assertIn("'X-Popcorn-Surface': 'mvp4'", src)
        self.assertIn('client_key: key()', src)
        # «접수 완료»(phase = 'success')는 서버 응답(inquiry_no)을 받은 자리에서만 정한다.
        for m in re.finditer(r"phase = 'success'", src):
            self.assertIn('inquiry_no', src[max(0, m.start() - 80):m.start()])

    def test_home_order_and_routes(self):
        src = (MVP4 / 'assets/js/supercomputer-home.js').read_text(encoding='utf-8')
        self.assertIn('hm-gaming', src)
        self.assertEqual(set(re.findall(r'href="([a-z-]+\.html)', src)), {'supercomputer.html'})
        index = (MVP4 / 'index.html').read_text(encoding='utf-8')
        self.assertLess(index.index('supercomputer-home.js'), index.index('design-boot.js'))


if __name__ == '__main__':
    unittest.main()
