# -*- coding: utf-8 -*-
"""2겹 실시간 안전장치(api/mall_price_live) — 장바구니·결제 순간 쇼핑몰 현재가 확인.

DB 검사는 tests/test_mall_price.py 와 같이 루프백 Postgres 에서만, 전용 스키마를 만들어 돌린다.
"""
import io
import json
import os
import unittest
import uuid
from unittest.mock import patch

from api import mall_price_live as L
from tests.test_mall_price import SCHEMA_SQL, _local_url, _upgrade_sql

QID = "6f1d2c1e-0d7a-4c55-9a43-9b6f1a3c0001"


@unittest.skipUnless(_local_url(), "루프백 Postgres 가 없어 DB 검사를 건너뜁니다")
class SettleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sqlalchemy import create_engine, text
        cls.text = staticmethod(text)
        cls.schema = "mall_live_t_" + uuid.uuid4().hex[:12]
        cls.engine = create_engine(_local_url())
        mig = os.path.join(os.path.dirname(__file__), "..", "db", "migrations", "versions",
                           "0145_mall_price_checks.py")
        with cls.engine.begin() as c:
            c.execute(text('CREATE SCHEMA "%s"' % cls.schema))
            c.execute(text('SET search_path TO "%s"' % cls.schema))
            for stmt in SCHEMA_SQL.split(";"):
                if stmt.strip():
                    c.execute(text(stmt))
            for stmt in _upgrade_sql(io.open(mig, encoding="utf-8").read()):
                c.execute(text(stmt))

    @classmethod
    def tearDownClass(cls):
        with cls.engine.begin() as c:
            c.execute(cls.text('DROP SCHEMA "%s" CASCADE' % cls.schema))
        cls.engine.dispose()

    def conn(self, rows):
        # 한 테스트 안에서는 한 트랜잭션만 쓴다(둘을 열면 TRUNCATE 가 서로를 기다린다).
        if not hasattr(self, "_c"):
            cm = self.engine.begin()
            self._c = cm.__enter__()
            self.addCleanup(cm.__exit__, None, None, None)
            self._c.execute(self.text('SET LOCAL search_path TO "%s"' % self.schema))
        c = self._c
        c.execute(self.text("TRUNCATE products, product_price_history, mall_price_checks,"
                            " mall_price_runs, admin_operator_activity_logs CASCADE"))
        for pc, pt, price, locked in rows:
            c.execute(self.text(
                "INSERT INTO products (product_code, product_name, part_type, sale_price, locked_fields)"
                " VALUES (:pc, 'x', :pt, :p, CAST(:l AS JSONB))"),
                {"pc": pc, "pt": pt, "p": price, "l": json.dumps(locked)})
        return c

    def got(self, price, code=98149):
        url = "https://www.popcornpc.co.kr/shop/system_detail.html?pd_no=%d" % code
        return ({"ok": True, "price": price, "err": None, "url": url} if price is not None
                else {"ok": False, "price": None, "err": "URLError", "url": url})

    def checks(self, c):
        return [tuple(r) for r in c.execute(self.text(
            "SELECT moment, product_code, our_price, mall_price, outcome, CAST(quote_id AS TEXT),"
            " visitor_ref FROM mall_price_checks ORDER BY check_id")).all()]

    def test_changed_price_updates_sale_price_history_and_tells_customer(self):
        c = self.conn([(98149, "PC_COMPLETE", 1585100, [])])
        out = L._settle(c, "cart", 98149, 1585100, self.got(1624400), quote_id=QID, visitor_ref=11)
        self.assertEqual((out["status"], out["mall"], out["diff"], out["saved"]),
                         ("changed", 1624400, 39300, True))
        self.assertIn("1,585,100원에서 1,624,400원으로", out["message"])
        self.assertEqual(c.execute(self.text("SELECT sale_price FROM products")).scalar(), 1624400)
        hist = c.execute(self.text(
            "SELECT old_price, new_price, reason, changed_by FROM product_price_history")).all()
        self.assertEqual([tuple(h) for h in hist], [(1585100, 1624400, "mall_price_cart", None)])
        self.assertEqual(self.checks(c), [("cart", 98149, 1585100, 1624400, "changed", QID, "11")])
        url = c.execute(self.text("SELECT source_url FROM mall_price_checks")).scalar()
        self.assertIn("system_detail.html?pd_no=98149", url)

    def test_checkout_message_says_mall_charges_new_price(self):
        c = self.conn([(98149, "PC_COMPLETE", 1585100, [])])
        out = L._settle(c, "checkout", 98149, 1585100, self.got(1600000), quote_id=QID, visitor_ref=11)
        self.assertIn("바뀐 가격으로 결제", out["message"])
        self.assertEqual(c.execute(self.text("SELECT reason FROM product_price_history")).scalar(),
                         "mall_price_checkout")

    def test_same_price_records_same_and_says_nothing(self):
        c = self.conn([(98149, "PC_COMPLETE", 1585100, [])])
        out = L._settle(c, "cart", 98149, 1585100, self.got(1585100), quote_id=QID, visitor_ref=11)
        self.assertEqual((out["status"], out["message"], out["saved"]), ("same", None, False))
        self.assertEqual(self.checks(c)[0][4], "same")

    def test_read_failure_does_not_block_and_records_failed(self):
        c = self.conn([(98149, "PC_COMPLETE", 1585100, [])])
        out = L._settle(c, "cart", 98149, 1585100, self.got(None), quote_id=QID, visitor_ref=11)
        self.assertEqual((out["status"], out["mall"]), ("unchecked", None))
        self.assertEqual(out["message"], "현재 가격 확인이 안 되어 쇼핑몰에서 최종 확인됩니다")
        self.assertEqual(self.checks(c)[0][3:5], (None, "failed"))
        self.assertEqual(c.execute(self.text("SELECT sale_price FROM products")).scalar(), 1585100)

    def test_big_change_locked_and_parts_tell_customer_but_keep_sale_price(self):
        for rows, mall, outcome in (([(98149, "PC_COMPLETE", 1000000, [])], 1500000, "held"),
                                    ([(98149, "PC_COMPLETE", 1000000, ["sale_price"])], 1010000, "locked"),
                                    ([(98149, "GPU", 1000000, [])], 1010000, "held")):
            c = self.conn(rows)
            out = L._settle(c, "cart", 98149, 1000000, self.got(mall), quote_id=QID, visitor_ref=11)
            self.assertEqual((out["status"], out["mall"], out["saved"]), ("changed", mall, False))
            self.assertEqual(c.execute(self.text("SELECT sale_price FROM products")).scalar(), 1000000)
            self.assertEqual(c.execute(self.text("SELECT count(*) FROM product_price_history")).scalar(), 0)
            self.assertEqual(self.checks(c)[0][4], outcome)

    def test_card_price_differs_from_sale_price(self):
        # 카드 가격(고객이 보던 값)과 우리 판매가가 다를 수 있다 — 고객 문장은 카드 가격 기준,
        # 판매가 반영은 지금 판매가 기준으로 한다.
        c = self.conn([(98149, "PC_COMPLETE", 1600000, [])])
        out = L._settle(c, "cart", 98149, 1585100, self.got(1600000), quote_id=QID, visitor_ref=11)
        self.assertEqual((out["status"], out["saved"]), ("changed", False))
        self.assertEqual(self.checks(c)[0][4], "same")


class ConfirmNeverRaisesTests(unittest.TestCase):
    def test_reader_and_database_failures_become_unchecked(self):
        with patch.object(L, "_part_type", side_effect=RuntimeError("db down")), \
             patch.object(L, "engine") as eng:
            eng.begin.side_effect = RuntimeError("db down")
            out = L.confirm("cart", 98149, 1585100, quote_id=QID, visitor_ref=1)
        self.assertEqual(out["status"], "unchecked")
        self.assertEqual(out["message"], L.MSG_UNCHECKED)
        self.assertTrue(out["checked_at"])

    def test_read_ok_but_record_failure_still_tells_customer(self):
        got = {"ok": True, "price": 1624400, "url": "u"}
        with patch.object(L, "_part_type", return_value="PC_COMPLETE"), \
             patch.object(L.mall_price_reader, "read_price", return_value=got) as rp, \
             patch.object(L, "engine") as eng:
            eng.begin.side_effect = RuntimeError("db down")
            out = L.confirm("checkout", 98149, 1585100)
        rp.assert_called_once_with(98149, "PC_COMPLETE", timeout=L.TIMEOUT)
        self.assertEqual((out["status"], out["mall"], out["saved"]), ("changed", 1624400, False))
        self.assertIn("결제", out["message"])

    def test_timeout_is_short(self):
        self.assertLessEqual(L.TIMEOUT, 3.0)


if __name__ == "__main__":
    unittest.main()
