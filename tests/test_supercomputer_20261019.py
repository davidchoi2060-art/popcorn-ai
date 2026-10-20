"""/mvp4 AI 슈퍼컴퓨터(v15) — 고정 완제품 두 모델의 조회·문의 계약 (2026-10-19 대표 승인 v15).

DB 없이 확인하는 것: 조회 allowlist·판매 확인 상태 · 문의 입력 검사(주제·상품번호·수량·조합) ·
가격이 바뀌면 접수하지 않음 · 마이그레이션 사슬 · 고객 화면 소스에 외부 몰·로컬·시안 경로·관찰 가격이 없음.
"""
import importlib.util
import json
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
    """customer_supercomputer 의 조회 한 행(카테고리 분류 + ai_device_profiles). 기본은 프로필 없는 상품."""
    base = {'product_code': 129615, 'product_name': 'DELL Pro Max GB10 (128GB, M.2 2TB)', 'sale_price': 12052100,
            'status': '판매중', 'display_name': None, 'maker': None, 'model_name': None, 'accelerator': None,
            'processor': None, 'memory': None, 'storage': None, 'os': None, 'architecture': None, 'model_group': None,
            'model_label': None, 'featured_rank': None, 'images': None, 'detail': None, 'has_explained_photo': False}
    base.update(kw)
    return base


class Catalog(unittest.TestCase):
    def test_item_is_allowlisted_and_has_no_cost_fields(self):
        it = SC.item(row())
        self.assertEqual((it['price'], it['sale_state']), (12052100, 'on_sale'))
        for k in ('purchase_price', 'supplier', 'stock_qty', 'margin', 'detail'):
            self.assertNotIn(k, it)
        self.assertIn('detail', SC.item(row(), with_detail=True))

    def test_states(self):
        for kw, want in (({'status': '품절'}, (None, 'stopped')), ({'status': '단종'}, (None, 'stopped')),
                         ({'sale_price': 0}, (None, 'check')), ({'sale_price': None}, (None, 'check'))):
            with self.subTest(kw=kw):
                it = SC.item(row(**kw))
                self.assertEqual((it['price'], it['sale_state']), want)

    def test_missing_profile_values_stay_empty_not_gb10(self):
        it = SC.item(row(product_code=200001, product_name='<b>새 AI 장비</b> X1'))
        self.assertEqual(it['name'], '새 AI 장비 X1')
        for k in ('maker', 'accelerator', 'processor', 'memory', 'storage', 'os', 'architecture'):
            self.assertIsNone(it[k])
        self.assertEqual(it['images'], [])

    def test_images_only_safe_paths_and_explained_photo_fallback(self):
        it = SC.item(row(images=[{'src': 'assets/images/supercomputer/gb10-product.jpg'}, {'src': 'https://evil.example/x.png'},
                                 {'src': 'javascript:alert(1)'}, {'src': '/api/product-images/12/detail'}]))
        self.assertEqual([i['src'] for i in it['images']], ['assets/images/supercomputer/gb10-product.jpg', '/api/product-images/12/detail'])
        self.assertEqual(SC.item(row(product_code=7, has_explained_photo=True))['images'][0]['src'], '/api/product-images/7/detail')

    def test_unprofiled_product_is_filled_from_its_own_name(self):
        it = SC.item(row(product_code=300001, product_name='[ACER] Veriton GN100 [128GB/4TB NVME/AS 2Y] NVIDIA DGX Spark기반', p_maker='ACER'))
        self.assertEqual((it['maker'], it['memory'], it['storage'], it['accelerator'], it['os']), ('ACER', '128GB', '4TB', 'NVIDIA GB10', None))
        self.assertEqual(it['derived'], ['accelerator', 'processor', 'memory', 'storage', 'architecture'])   # 상품명 기준
        ws = SC.item(row(product_code=300002, product_name='워크스테이션 [14900K/64G/2TB+4TB/RTX5090]', p_maker='팝콘'))
        self.assertEqual((ws['memory'], ws['storage'], ws['accelerator'], ws['os']), ('64GB', '2TB', None, None))   # GB10 사양을 물려주지 않는다

    def test_migration_0167_chain(self):
        path = ROOT / 'db/migrations/versions/0167_ai_supercomputer_products.py'
        spec = importlib.util.spec_from_file_location('m0167', path)
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        self.assertEqual((mod.revision, mod.down_revision), ('0167', '0166'))
        for p in mod.PRODUCTS:
            self.assertTrue(p[8] is None or (MVP4 / 'assets/images/supercomputer' / p[8]).exists(), p)

    def test_list_is_queried_by_category_key_not_codes(self):
        src = (ROOT / 'api/customer_supercomputer.py').read_text(encoding='utf-8')
        self.assertIn("public_key = :key", src)
        self.assertNotRegex(src, r'1296(14|15)')
        self.assertFalse(hasattr(SC, 'CODES'))


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
        for kw in ({'product_code': None},
                   {'configuration_id': 'A0123456789ABCDEF'}, {'quote_id': '00000000-0000-0000-0000-000000000001'}):
            with self.subTest(kw=kw), self.assertRaises(HTTPException):
                PI._clean(body(**kw))

    def test_quantity_and_fields(self):
        for fixed in ({'intent': 'quote', 'quantity': 0}, {'intent': 'quote', 'quantity': 11}, {'intent': 'quote', 'quantity': '2'},
                      {'intent': 'buy', 'quantity': 1}, {'intent': 'quote', 'quantity': 1, 'purpose': 'x'},
                      {'intent': 'quote', 'quantity': 1, 'parts': []}):
            with self.subTest(fixed=fixed), self.assertRaises(ValidationError):
                body(fixed=fixed)

    def conn(self, item, inserts):
        class Conn:
            def execute(self, sql, params=None):
                if 'INSERT INTO purchase_inquiries' in str(sql):
                    inserts.append(params)
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

    def receive(self, item):
        inserts = []
        req = type('Req', (), {'headers': {}})()
        with patch.object(PI, 'same_origin', lambda r: None), patch.object(PI.engine, 'begin', self.conn(item, inserts)),              patch.object(PI.visitor, 'resolve', return_value=7), patch.object(PI.access_gate, 'check_rate', return_value=None),              patch.object(PI, '_no', return_value='PI-9999'), patch.object(PI, '_resolve_data_origin', return_value='test'):
            out = PI.create_inquiry(body(client_key='sc-abc123'), req, PI.Response())
        return out, json.loads(inserts[0]['fixed'])

    def test_price_change_is_received_and_flagged_for_counselor(self):
        # 2026-10-20 대표: 금액·사양이 안 맞으면 상담사가 전화로 조정해 판매한다 — 접수를 막지 않는다.
        out, fixed = self.receive(row(product_code=129614, product_name='DELL Pro Max GB10 (128GB, M.2 4TB)', sale_price=14300000))
        self.assertEqual(out['inquiry_no'], 'PI-9999')
        self.assertEqual((fixed['unit_price'], fixed['seen_unit_price'], fixed['price_differs'], fixed['total']),
                         (14300000, 14209400, True, 28600000))

    def test_product_out_of_category_is_still_received(self):
        out, fixed = self.receive(None)
        self.assertEqual((out['inquiry_no'], fixed['product_code'], fixed['unit_price'], fixed['sale_state']), ('PI-9999', 129614, None, 'unknown'))

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


class Category(unittest.TestCase):
    """카테고리 확장(2026-10-20): 상품번호를 화면 코드에 적지 않고, 새 상품은 분류·표시 정보만으로 들어온다."""
    SCREENS = ('assets/js/live-supercomputer.js', 'assets/js/supercomputer-home.js', 'assets/js/supercomputer-detail.js',
               'assets/js/supercomputer-inquiry.js', 'assets/js/supercomputer-list.js', 'supercomputers.html')

    def test_no_product_codes_in_screens(self):
        for f in self.SCREENS:
            with self.subTest(f=f):
                self.assertNotRegex((MVP4 / f).read_text(encoding='utf-8'), r'1296(14|15)')

    def test_gb10_content_lives_in_product_data(self):
        detail = (MVP4 / 'assets/js/supercomputer-detail.js').read_text(encoding='utf-8')
        code = re.sub(r'/\*.*?\*/', '', detail, flags=re.S)
        for gb10 in ('DGX', 'ConnectX', 'gb10-', '2TB와 4TB', 'Grace Blackwell'):
            self.assertNotIn(gb10, code)
        mig = (ROOT / 'db/migrations/versions/0166_ai_supercomputer_category.py').read_text(encoding='utf-8')
        for gb10 in ('DGX OS', 'ConnectX-7', 'gb10-rear-1600.webp', '2TB와 4TB'):
            self.assertIn(gb10, mig)

    def test_list_back_links_and_install_intent(self):
        detail = (MVP4 / 'assets/js/supercomputer-detail.js').read_text(encoding='utf-8')
        self.assertIn('AI 슈퍼컴퓨터 목록', detail)
        self.assertIn("route('adoption')", detail)
        self.assertNotIn('package=business', re.sub(r'/\*.*?\*/', '', detail, flags=re.S))
        header = (MVP4 / 'assets/js/header-ui.js').read_text(encoding='utf-8')
        self.assertIn("['AI 슈퍼컴퓨터', null, 'cpu', 'AI 전용 장비', 'supercomputers.html', 'supercomputers']", header)
        home = (MVP4 / 'assets/js/supercomputer-home.js').read_text(encoding='utf-8')
        self.assertIn('AI 슈퍼컴퓨터 전체 보기', home)
        for claim in ('FP4 로컬 추론', 'CPU·GPU 통합 메모리', 'FP4 · 희소성 적용 기준', 'AI 설치·교육은 별도 상담'):
            self.assertIn(claim, home)
        for bad in ('VRAM', '대분', '학습까지'):
            self.assertNotIn(bad, home)

    def test_migration_0166_chain_and_key(self):
        path = ROOT / 'db/migrations/versions/0166_ai_supercomputer_category.py'
        spec = importlib.util.spec_from_file_location('m0166', path)
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        self.assertEqual((mod.revision, mod.down_revision, mod.KEY), ('0166', '0165', SC.KEY))

    def test_admin_profile_paths(self):
        from api import admin_ai_device_profiles as A
        ok = A.ProfileBody(images=[{'src': 'assets/images/x/a.webp'}, {'src': '/api/product-images/9/detail'}])
        A.clean(ok)
        for bad in ('https://cdn.example/a.png', '../secret.png', 'assets/images/a.svg'):
            with self.subTest(bad=bad), self.assertRaises(HTTPException):
                A.clean(A.ProfileBody(images=[{'src': bad}]))


if __name__ == '__main__':
    unittest.main()
