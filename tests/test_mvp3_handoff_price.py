"""mvp3 「쇼핑몰에서 구매」 순간의 쇼핑몰 현재가 확인(2겹 실시간 안전장치 · checkout).

DB 없이 SQL 을 흉내 내는 가짜 연결로 돈다. 확인 자체(api/mall_price_live.confirm)는 바꿔 끼우고,
여기서는 그 결과로 인계 기록 · 보관 견적 · 응답이 어떻게 남는지만 본다.
"""
import json
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from uuid import UUID

from fastapi import Response
from starlette.requests import Request

from api import mvp3_handoff as h

QID = UUID('6f1d2c1e-0d7a-4c55-9a43-9b6f1a3c0001')


def request():
    return Request({'type': 'http', 'scheme': 'https', 'server': ('example.invalid', 443),
                    'path': '/api/mvp3/saved-quotes/x/handoff', 'query_string': b'',
                    'headers': [(b'host', b'example.invalid'), (b'x-access-key', b'a' * 64)]})


class R:
    def __init__(self, rows=(), scalar=None): self.rows, self._s = list(rows), scalar
    def mappings(self): return self
    def first(self): return self.rows[0] if self.rows else None
    def all(self): return self.rows
    def scalar(self): return self._s


class DB:
    def __init__(self):
        self.snapshot = {'product_code': 98149, 'name': 'PC', 'price': 1585100}
        self.handoffs, self.items, self.updates = [], [], []
        self.locks, self.on_lock = [], None
        self.existing = None

    @contextmanager
    def begin(self): yield self

    def execute(self, sql, p=None):
        sql = str(sql)
        if 'SELECT product_snapshot' in sql:
            return R([{'product_snapshot': dict(self.snapshot)}])
        if 'FROM ops_settings' in sql:
            return R([('pay', 'mall')])
        if 'pg_advisory_xact_lock' in sql:
            self.locks.append(p['k'])
            if self.on_lock:
                self.on_lock()
            return R()
        if 'FROM handoffs WHERE' in sql:
            return R([self.existing[0]] if self.existing else [])
        if 'FROM handoff_items WHERE' in sql:
            return R([self.existing[1]] if self.existing else [])
        if 'INSERT INTO handoffs' in sql:
            self.handoffs.append(p)
            return R(scalar=1)
        if 'UPDATE mvp3_saved_recommendations' in sql:
            self.updates.append(p)
            self.snapshot.update(json.loads(p['f']))
            return R()
        if 'INSERT INTO handoff_items' in sql:
            self.items.append(p)
            return R()
        raise AssertionError(sql)


def check(status, mall, **kw):
    return {'status': status, 'quoted': 1585100, 'mall': mall,
            'diff': None if mall is None else mall - 1585100, 'saved': status == 'changed',
            'message': kw.get('message'), 'soldout': kw.get('soldout', False), 'checked_at': 't'}


class HandoffPriceTest(unittest.TestCase):
    def setUp(self):
        self.db = DB()
        for p in (patch.object(h, 'engine', self.db), patch.object(h.visitor, 'resolve', return_value=11),
                  patch.object(h.access_gate, 'check_rate'), patch.object(h.access_gate, 'column_ready', return_value=False),
                  patch.object(h, '_no', return_value='HO-1001')):
            p.start()
            self.addCleanup(p.stop)

    def run_with(self, result):
        with patch.object(h.mall_price_live, 'confirm', return_value=result) as c:
            out = h.handoff_saved_quote(QID, request(), Response())
        c.assert_called_once_with('checkout', 98149, 1585100, quote_id=str(QID), visitor_ref=11)
        return out

    def test_changed_price_updates_saved_quote_and_records_both_prices(self):
        msg = '쇼핑몰 현재 가격이 1,585,100원에서 1,624,400원으로 바뀌었습니다. 쇼핑몰에서는 바뀐 가격으로 결제됩니다.'
        out = self.run_with(check('changed', 1624400, message=msg))
        self.assertEqual((out['mall_status'], out['price_quoted'], out['price_mall']), ('가격변동', 1585100, 1624400))
        self.assertEqual(out['price_check']['message'], msg)
        self.assertEqual(self.db.snapshot['price'], 1624400)
        self.assertEqual(self.db.items[0]['pq'], 1585100)
        self.assertEqual(self.db.items[0]['pm'], 1624400)
        self.assertEqual(self.db.handoffs[0]['ch'], 1)

    def test_same_price_leaves_saved_quote(self):
        out = self.run_with(check('same', 1585100))
        self.assertEqual(out['mall_status'], '확인됨')
        self.assertEqual(self.db.updates, [])

    def test_unreadable_mall_does_not_block(self):
        out = self.run_with(check('unchecked', None, message='현재 가격 확인이 안 되어 쇼핑몰에서 최종 확인됩니다'))
        self.assertEqual((out['ok'], out['mall_status'], out['price_mall']), (True, '확인못함', None))
        self.assertEqual(self.db.updates, [])
        self.assertEqual(json.loads(self.db.handoffs[0]['note'])['unknown'], [98149])

    def test_soldout_is_told_and_changed_price_still_saved(self):
        out = self.run_with(check('changed', 1600000, soldout=True))
        self.assertEqual(out['mall_status'], '품절')
        self.assertEqual(self.db.snapshot['price'], 1600000)

    def test_changed_parts_quote_compares_base_pc_and_keeps_the_part_difference(self):
        self.db.snapshot.update(price=1635100, build={'base_price': 1585100, 'changes': [
            {'ordinal': 1, 'slot': 'CPU', 'delta': 50000}], 'compat': {'ok': True}})
        out = self.run_with(check('changed', 1624400))
        self.assertEqual((out['price_quoted'], out['price_mall'], len(out['changes'])), (1585100, 1624400, 1))
        self.assertEqual(self.db.snapshot['price'], 1674400)
        self.assertEqual(self.db.snapshot['build']['base_price'], 1624400)
        self.assertEqual(self.db.handoffs[0]['tm'], 1674400)

    def test_built_pc_link_is_the_system_detail_page(self):
        # 전에는 부품용 product_detail.html 로 보내 완제품은 쇼핑몰 첫 화면이 열렸다.
        out = self.run_with(check('same', 1585100))
        self.assertEqual(out['mall_url'], 'https://www.popcornpc.co.kr/shop/system_detail.html?pd_no=98149')

    def test_same_quote_waits_on_its_own_lock_then_returns_the_first_handoff(self):
        # 코덱스 검수 #82: 동시 요청 B 가 잠금을 기다리는 동안 A 가 기록을 끝냈다 -> B 는 새로 넣지 않는다
        first = ({'handoff_id': 7, 'handoff_no': 'HO-1000'},
                 {'product_code': 98149, 'name_snap': 'PC', 'price_quoted': 1585100,
                  'price_mall': 1585100, 'mall_status': '확인됨'})
        def a_finished():
            self.db.existing = first
        self.db.on_lock = a_finished
        out = self.run_with(check('same', 1585100))
        self.assertEqual(self.db.locks, ['mvp3_handoff:' + str(QID)])
        self.assertEqual(out['handoff_no'], 'HO-1000')
        self.assertEqual((self.db.handoffs, self.db.items), ([], []))


if __name__ == '__main__': unittest.main()
