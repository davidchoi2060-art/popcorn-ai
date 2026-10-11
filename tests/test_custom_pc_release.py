"""신규 조립PC 고객 공개 — 지금 값으로 다시 보는 판정과 공개·중지 기록 (부품 상품화 4단계)."""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from api import admin_pc_release as R
from api import custom_pc as C
from api.mvp3_purchase_inquiry import InquiryBody
from api.orders import ASSEMBLY_FEE

RULES = [dict(rule_key='socket', label='CPU-보드 소켓', slot='MB', field='socket', ref_slot='CPU', ref_field='socket',
              op='eq', part_types=[], null_ref_mode=None, ref_offset=None, detail_fmt=None)]
SPECS = {1: dict(part_type='CPU', socket='AM5', cpu_gpu=True), 2: dict(part_type='MB', socket='AM5'),
         3: dict(part_type='MB', socket='LGA1700'), 4: dict(part_type='RAM')}
NOW = datetime(2026, 10, 11, tzinfo=timezone.utc)


def part(ordinal, slot, code, price=100000, status='판매중', qty=1, pseudo=False):
    return dict(configuration_id='A0123456789ABCDEF', ordinal=ordinal, slot=slot, quantity=qty, pseudo=pseudo,
                source_code=str(code), explanation_code=code, product_code=code, explanation_status='approved',
                has_photo=False, explanation_name=None, product_name=f'{slot} {code}', sale_price=price, sale_status=status)


BOM = [part(0, 'CPU', 1, 300000), part(1, 'MB', 2, 200000), part(2, 'RAM', 4, 50000, qty=2)]
CONFIG = dict(configuration_id='A0123456789ABCDEF', revision=3, status='approved', bom_fingerprint='f' * 64,
              content=dict(title='새 PC', intro='게임용으로 고른 구성', benefits=[['빠름', '설명']], checks=['확인'], facts={}),
              updated_at=NOW)
RELEASE = dict(event_id=7, configuration_id=CONFIG['configuration_id'], action='release', revision=3,
               bom_fingerprint='f' * 64, price_at_release=1, operator_id=1, note=None, created_at=NOW)


class Evaluate(unittest.TestCase):
    def test_price_is_sale_prices_plus_fee(self):
        s = C.evaluate_parts(BOM, SPECS, RULES)
        self.assertTrue(s['ok'])
        self.assertEqual(s['price'], 300000 + 200000 + 50000 * 2 + ASSEMBLY_FEE)

    def test_soldout_or_unpriced_part_blocks_and_hides_price(self):
        for bad in (part(2, 'RAM', 4, status='품절'), part(2, 'RAM', 4, price=0), dict(part(2, 'RAM', 4), product_code=None)):
            s = C.evaluate_parts(BOM[:2] + [bad], SPECS, RULES)
            self.assertFalse(s['ok'])
            self.assertIsNone(s['price'])

    def test_compat_failure_blocks_but_keeps_price(self):
        s = C.evaluate_parts([BOM[0], part(1, 'MB', 3), BOM[2]], SPECS, RULES)
        self.assertFalse(s['ok'])
        self.assertTrue(any('CPU-보드 소켓' in p for p in s['problems']))
        self.assertIsNotNone(s['price'])

    def test_pseudo_line_is_not_a_part(self):
        s = C.evaluate_parts(BOM + [part(9, 'ETC', None, price=None, status=None, pseudo=True)], SPECS, RULES)
        self.assertTrue(s['ok'])
        self.assertEqual(len(s['parts']), 3)


class Live(unittest.TestCase):
    def test_release_must_match_current_configuration(self):
        self.assertTrue(C.is_live_release(CONFIG, RELEASE))
        for change in (dict(revision=4), dict(bom_fingerprint='e' * 64), dict(status='review_required')):
            self.assertFalse(C.is_live_release(dict(CONFIG, **change), RELEASE))
        self.assertFalse(C.is_live_release(CONFIG, dict(RELEASE, action='withdraw')))
        self.assertFalse(C.is_live_release(CONFIG, None))

    def test_customer_list_drops_unavailable(self):
        ok = C.evaluate_parts(BOM, SPECS, RULES)
        bad = C.evaluate_parts(BOM[:2] + [part(2, 'RAM', 4, status='품절')], SPECS, RULES)
        rows = [(CONFIG, RELEASE, ok), (dict(CONFIG, configuration_id='A1'), RELEASE, bad), (CONFIG, None, ok)]
        with patch.object(C, 'load', return_value=rows):
            items = C.customer_list(None)
        self.assertEqual([i['price'] for i in items], [ok['price']])
        self.assertEqual(items[0]['benefits'], [dict(title='빠름', text='설명')])
        self.assertNotIn('sale_price', items[0]['parts'][0])


class Conn:
    def __init__(self): self.inserts = []
    def execute(self, sql, params=None):
        sql = str(sql)
        if 'INSERT INTO custom_pc_release_events' in sql:
            self.inserts.append(params)
            return type('R', (), {'scalar': lambda _: 99})()
        return None


def review(eligible=True):
    return patch.object(R, 'load_review', return_value=(None, None, None, dict(eligible=eligible, state='approved' if eligible else 'pending')))


class Gate(unittest.TestCase):
    def test_review_and_copy_are_required(self):
        s = C.evaluate_parts(BOM, SPECS, RULES)
        with review(False):
            self.assertIn('구성 검토 승인 필요', R.gate(None, CONFIG, None, s)['blockers'])
        placeholder = dict(CONFIG, content=dict(CONFIG['content'], intro=C.PLACEHOLDER_INTRO + ' 상품 설명과 장착 조건을 검토해 주세요.'))
        with review():
            self.assertEqual(R.gate(None, CONFIG, None, s)['blockers'], [])
            self.assertIn('고객에게 보일 상품 소개 문구 작성 필요', R.gate(None, placeholder, None, s)['blockers'])

    def test_release_and_withdraw(self):
        s = C.evaluate_parts(BOM, SPECS, RULES)
        actor = dict(operator_id=5)
        with review(), patch.object(R.custom_pc, 'load', return_value=[(CONFIG, None, s)]):
            with self.assertRaises(HTTPException) as e:
                R.release_one(Conn(), CONFIG['configuration_id'], R.ReleaseBody(expected_price=s['price'] - 1), actor)
            self.assertEqual(e.exception.status_code, 409)
            c = Conn()
            out = R.release_one(c, CONFIG['configuration_id'], R.ReleaseBody(expected_price=s['price']), actor)
            self.assertEqual((out['price'], c.inserts[0]['price'], c.inserts[0]['rev']), (s['price'], s['price'], 3))
            with self.assertRaises(HTTPException) as e:
                R.withdraw_one(Conn(), CONFIG['configuration_id'], R.WithdrawBody(reason='품절'), actor)
            self.assertEqual(e.exception.status_code, 409)
        with review(), patch.object(R.custom_pc, 'load', return_value=[(CONFIG, RELEASE, s)]):
            with self.assertRaises(HTTPException) as e:
                R.release_one(Conn(), CONFIG['configuration_id'], R.ReleaseBody(expected_price=s['price']), actor)
            self.assertEqual(e.exception.status_code, 409)
            c = Conn()
            R.withdraw_one(c, CONFIG['configuration_id'], R.WithdrawBody(reason='품절'), actor)
            self.assertEqual(c.inserts[0]['ref'], 7)
        with review(False), patch.object(R.custom_pc, 'load', return_value=[(CONFIG, None, s)]):
            with self.assertRaises(HTTPException) as e:
                R.release_one(Conn(), CONFIG['configuration_id'], R.ReleaseBody(expected_price=s['price']), actor)
            self.assertEqual(e.exception.status_code, 422)
        with patch.object(R.custom_pc, 'load', return_value=[]):
            with self.assertRaises(HTTPException) as e:
                R.release_one(Conn(), 'P1', R.ReleaseBody(expected_price=1), actor)
            self.assertEqual(e.exception.status_code, 404)


class Inquiry(unittest.TestCase):
    def test_configuration_id_shape(self):
        InquiryBody(topic='주문 희망', phone='010-1234-5678', consent=True, configuration_id='A0123456789ABCDEF')
        with self.assertRaises(ValidationError):
            InquiryBody(topic='주문 희망', phone='010-1234-5678', consent=True, configuration_id="A1' OR 1=1")


if __name__ == '__main__':
    unittest.main()
