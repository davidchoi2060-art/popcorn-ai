"""사양 표준(std) 값을 부품 행에 붙인다 — 케이스 지원 파워 규격(0161)."""
import unittest

from api import std_specs


class FakeConn:
    def __init__(self, has_std, rows):
        self.has_std, self.rows, self.calls = has_std, rows, 0

    def execute(self, sql, params=None):
        self.calls += 1
        conn = self

        class R:
            def scalar(self):
                return conn.has_std

            def all(self):
                return conn.rows
        return R()


class Attach(unittest.TestCase):
    def test_case_gets_std_list(self):
        rows = [dict(product_code=1, part_type='CASE'), dict(product_code=2, part_type='POWER')]
        std_specs.attach(FakeConn(True, [(1, 'psu_form_factor_list', ['ATX'])]), rows)
        self.assertEqual(rows[0]['psu_form_factor_list'], ['ATX'])
        self.assertIsNone(rows[1]['psu_form_factor_list'])

    def test_no_std_schema_leaves_none(self):
        conn = FakeConn(False, [])
        rows = std_specs.attach(conn, [dict(product_code=1)])
        self.assertIsNone(rows[0]['psu_form_factor_list'])
        self.assertEqual(conn.calls, 1)

    def test_empty_list_is_unknown(self):
        rows = std_specs.attach(FakeConn(True, [(1, 'psu_form_factor_list', [])]), [dict(product_code=1)])
        self.assertIsNone(rows[0]['psu_form_factor_list'])
