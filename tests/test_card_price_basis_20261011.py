"""카드 가격 기준 문구 — 2026-10-11 품질관리 R10 회귀 고정.

카드 판매가는 9/28 쇼핑몰 CSV 적재 값에서 멈춰 있었는데 「현재 판매가」라고 적혀 있었다
(R10-가격-조회-결과.txt). 값은 그대로 두고 언제 어디서 온 값인지 밝힌다.
"""
from datetime import datetime, timezone
import unittest

from api import admin_product_fit as F


class PriceBasis(unittest.TestCase):
    def test_csv_import_date_in_korea(self):
        # 개발 서버 실측: 2026-09-28 06:37 UTC CSV 적재
        self.assertEqual(F.price_basis(datetime(2026, 9, 28, 6, 37), 'csv'),
                         '9월 28일 기준 쇼핑몰 가격 · 구매할 때 확정')

    def test_late_utc_rolls_to_next_korean_day(self):
        self.assertTrue(F.price_basis(datetime(2026, 9, 28, 16, 0), 'csv').startswith('9월 29일 기준'))
        aware = datetime(2026, 9, 28, 16, 0, tzinfo=timezone.utc)
        self.assertTrue(F.price_basis(aware, 'csv').startswith('9월 29일 기준'))

    def test_other_reason_is_not_called_mall_price(self):
        self.assertEqual(F.price_basis(datetime(2026, 10, 1, 1, 0), 'manual'),
                         '10월 1일 기준 판매가 · 구매할 때 확정')

    def test_no_history_says_unknown(self):
        self.assertIn('기준일 미확인', F.price_basis(None, None))

    def test_never_claims_current(self):
        for args in ((datetime(2026, 9, 28), 'csv'), (None, None), (datetime(2026, 9, 28), 'manual')):
            self.assertNotIn('현재', F.price_basis(*args))

    def test_load_reads_latest_sale_change(self):
        captured = []

        class Conn:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def execute(self, sql, *a):
                captured.append(str(sql))
                class R:
                    def all(self_inner): return []
                    def __iter__(self_inner): return iter([])
                return R()

        class Eng:
            def connect(self): return Conn()

        orig = F.engine
        F.engine = Eng()
        try:
            F.load()
        finally:
            F.engine = orig
        sql = ' '.join(captured)
        self.assertIn("h.field = 'sale'", sql)
        self.assertIn('ORDER BY h.changed_at DESC LIMIT 1', sql)


if __name__ == '__main__':
    unittest.main()
