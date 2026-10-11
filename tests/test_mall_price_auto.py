# -*- coding: utf-8 -*-
"""쇼핑몰 가격 자동 갱신(api/mall_price_auto.py) — 로그인 폼 읽기 · 공개 페이지 수집 · 한 번 실행.

쇼핑몰에는 요청하지 않는다(읽기 함수를 바꿔 끼운다). 실행 검사는 test_mall_price 와 같이
**루프백 Postgres** 가 있을 때만 이 검사 전용 스키마에서 돈다 — 정본을 쓰지 않는다.
"""
import io
import json
import os
import unittest
import uuid
from unittest.mock import patch

from api import mall_price_auto as AUTO
from tests.test_mall_price import SCHEMA_SQL, _local_url, _upgrade_sql

LOGIN_HTML = """<html><body>
<form name="search" action="/shop/search.php"><input type="text" name="q"></form>
<form name="flogin" action="/bbs/login_check.php" method="post">
  <input type="hidden" name="url" value="/adm/">
  <input type="text" name="mb_id"><input type="password" name="mb_password">
  <input type="checkbox" name="auto_login">
</form></body></html>"""


class LoginFormTests(unittest.TestCase):
    def test_picks_the_form_with_a_password_and_keeps_hidden_fields(self):
        p = AUTO._LoginForm()
        p.feed(LOGIN_HTML)
        form = next(f for f in p.forms if f["pw"] and f["user"])
        self.assertEqual((form["action"], form["user"], form["pw"]),
                         ("/bbs/login_check.php", "mb_id", "mb_password"))
        self.assertEqual(form["fields"], {"url": "/adm/"})

    def test_login_refused_when_admin_page_bounces_to_login(self):
        class Op:
            def __init__(self): self.posted = None
            def open(self, url, data=None, timeout=None):
                if data:
                    self.posted = data
                final = AUTO.LOGIN_URL if url == AUTO.ADMIN_URL else url
                body = LOGIN_HTML.encode("cp949")
                return _Resp(final, body)
        op = Op()
        with self.assertRaises(AUTO.CollectError) as e:
            AUTO.login(op, "아이디", "pw!@#")
        self.assertIn("거부", str(e.exception))
        self.assertNotIn("pw!@#", str(e.exception))           # 비밀번호가 사유 문장에 안 들어간다
        self.assertIn(b"mb_id=%BE%C6%C0%CC%B5%F0", op.posted)    # cp949 로 보낸다

    def test_settings_report_names_never_values(self):
        env = {AUTO.ENV_ID: "secret-id", AUTO.ENV_PW: "secret-pw", AUTO.ENV_EXPORT: "/adm/x.php"}
        with patch.dict(os.environ, env):
            cfg = AUTO.settings()
        self.assertEqual((cfg["login"], cfg["export_url"]), (True, True))
        self.assertNotIn("secret", json.dumps(cfg))

    def test_export_skipped_without_settings(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(AUTO.collect_export(), ({}, None))


class _Resp(io.BytesIO):
    def __init__(self, url, body):
        super().__init__(body)
        self._url = url
    def geturl(self): return self._url
    def __enter__(self): return self
    def __exit__(self, *a): self.close()


class CollectPublicTests(unittest.TestCase):
    def test_spacing_and_counts(self):
        sleeps = []
        got = {1: {"ok": True, "price": 1000}, 2: {"ok": False, "err": "http"}, 3: {"ok": True, "price": 3000}}
        prices, info = AUTO.collect_public([(1, "PC_COMPLETE"), (2, "PC_COMPLETE"), (3, "PC_COMPLETE")],
                                           sleep=sleeps.append, read=lambda c, pt: got[c])
        self.assertEqual(prices, {1: 1000, 3: 3000})
        self.assertEqual(sleeps, [AUTO.DELAY, AUTO.DELAY])     # 요청 사이마다 1.5초
        self.assertEqual((info["read"], info["failed"], info["errors"]), (2, 1, {"http": 1}))

    def test_more_than_half_failed_is_a_failed_run(self):
        with self.assertRaises(AUTO.CollectError) as e:
            AUTO.collect_public([(1, "x"), (2, "x"), (3, "x")], sleep=lambda s: None,
                                read=lambda c, pt: {"ok": c == 1, "price": 5, "err": "timeout"})
        self.assertEqual(e.exception.args[1]["failed"], 2)


@unittest.skipUnless(_local_url(), "루프백 Postgres 가 없어 DB 검사를 건너뜁니다")
class RunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sqlalchemy import create_engine, text
        cls.text = staticmethod(text)
        cls.schema = "mall_price_auto_t_" + uuid.uuid4().hex[:12]
        with create_engine(_local_url()).begin() as c:
            c.execute(text('CREATE SCHEMA "%s"' % cls.schema))
        cls.engine = create_engine(_local_url(), connect_args={"options": "-csearch_path=%s" % cls.schema})
        mig = os.path.join(os.path.dirname(__file__), "..", "db", "migrations", "versions",
                           "0145_mall_price_checks.py")
        with cls.engine.begin() as c:
            for stmt in SCHEMA_SQL.split(";"):
                if stmt.strip():
                    c.execute(text(stmt))
            c.execute(text("ALTER TABLE products ADD COLUMN status TEXT DEFAULT '판매중'"))
            for stmt in _upgrade_sql(io.open(mig, encoding="utf-8").read()):
                c.execute(text(stmt))

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        from sqlalchemy import create_engine
        with create_engine(_local_url()).begin() as c:
            c.execute(cls.text('DROP SCHEMA "%s" CASCADE' % cls.schema))

    def setUp(self):
        for p in (patch.object(AUTO, "engine", self.engine), patch.dict(os.environ, {}, clear=False)):
            p.start()
            self.addCleanup(p.stop)
        for k in (AUTO.ENV_ID, AUTO.ENV_PW, AUTO.ENV_EXPORT):
            os.environ.pop(k, None)
        with self.engine.begin() as c:
            c.execute(self.text("TRUNCATE products, product_price_history, mall_price_checks,"
                                " mall_price_runs, admin_operator_activity_logs CASCADE"))
            for pc, pt, price, st in [(1, "PC_COMPLETE", 1000, "판매중"), (2, "PC_COMPLETE", 2000, "판매중"),
                                      (3, "PC_COMPLETE", 3000, "품절"), (4, "GPU", 400, "판매중")]:
                c.execute(self.text("INSERT INTO products (product_code, product_name, part_type, sale_price,"
                                    " status) VALUES (:pc, 'p', :pt, :p, :st)"),
                          {"pc": pc, "pt": pt, "p": price, "st": st})

    def last_run(self):
        with self.engine.connect() as c:
            return c.execute(self.text("SELECT * FROM mall_price_runs ORDER BY run_id DESC LIMIT 1")).mappings().first()

    def price(self, code):
        with self.engine.connect() as c:
            return c.execute(self.text("SELECT sale_price FROM products WHERE product_code=:c"), {"c": code}).scalar()

    def test_public_run_reads_only_selling_built_pcs_and_applies(self):
        asked = []
        def fake(codes):
            asked.extend(codes)
            return {1: 1100, 2: 2000}, {"source": "pages", "asked": len(codes), "read": 2, "failed": 0}
        run_id = AUTO.begin("auto")
        out = AUTO.execute(run_id, "auto", collect_public_fn=fake)
        self.assertTrue(out["ok"], out)
        self.assertEqual(asked, [(1, "PC_COMPLETE"), (2, "PC_COMPLETE")])
        self.assertEqual((self.price(1), self.price(2)), (1100, 2000))
        run = self.last_run()
        self.assertEqual((run["ok"], run["moment"], run["source"], run["changed_count"]), (True, "auto", "pages", 1))
        with self.engine.connect() as c:
            reason = c.execute(self.text("SELECT reason FROM product_price_history WHERE product_code=1")).scalar()
        self.assertEqual(reason, "mall_price_auto")

    def test_failed_collect_changes_nothing_and_records_reason(self):
        def boom(codes):
            raise AUTO.CollectError("공개 상품 페이지 2건 중 2건을 읽지 못했습니다", {"failed": 2})
        out = AUTO.execute(AUTO.begin("auto"), "auto", collect_public_fn=boom)
        self.assertFalse(out["ok"])
        run = self.last_run()
        self.assertEqual(run["ok"], False)
        self.assertIn("읽지 못했습니다", run["fail_reason"])
        self.assertEqual(run["detail"]["collect"], {"failed": 2})
        self.assertEqual(self.price(1), 1000)

    def test_big_change_is_held(self):
        out = AUTO.execute(AUTO.begin("auto"), "auto",
                           collect_public_fn=lambda codes: ({1: 5000}, {"source": "pages"}))
        self.assertEqual((out["ok"], out["held"], out["changed"]), (True, 1, 0))
        self.assertEqual(self.price(1), 1000)

    def test_last_auto_start_is_an_aware_time_and_blocks_the_same_slot(self):
        import datetime as dt
        AUTO.begin("auto")
        last = AUTO._last_auto_started()
        now = dt.datetime.now(dt.timezone.utc)
        self.assertIsNotNone(last.tzinfo)
        self.assertLess(abs((now - last).total_seconds()), 120)
        self.assertIsNone(AUTO.due_slot(now, last))

    def test_second_run_while_one_is_running_is_refused(self):
        AUTO.begin("manual", operator_id=None)
        with self.assertRaises(AUTO.AlreadyRunning):
            AUTO.begin("auto")
        self.assertEqual(AUTO.run("auto")["fail_reason"], "이미 실행 중입니다")


class SchedulerTests(unittest.TestCase):
    """API 안 스케줄러 — 매일 06:00 · 13:00 KST, 놓치면 3시간 안에 한 번 만회, 같은 시각은 한 번만."""

    def at(self, day, h, m=0):
        import datetime as dt
        return dt.datetime(2026, 10, day, h, m, tzinfo=AUTO._KST)

    def test_due_after_each_slot_once(self):
        self.assertIsNone(AUTO.due_slot(self.at(11, 5, 59), self.at(10, 13, 1)))
        self.assertEqual(AUTO.due_slot(self.at(11, 6, 1), self.at(10, 13, 1)), self.at(11, 6))
        self.assertIsNone(AUTO.due_slot(self.at(11, 6, 2), self.at(11, 6, 1)))     # 이미 돌았다
        self.assertEqual(AUTO.due_slot(self.at(11, 13, 0), self.at(11, 6, 1)), self.at(11, 13))
        self.assertEqual(AUTO.due_slot(self.at(11, 6, 1), None), self.at(11, 6))

    def test_missed_slot_is_caught_up_only_within_three_hours(self):
        self.assertEqual(AUTO.due_slot(self.at(11, 8, 59), self.at(10, 13, 1)), self.at(11, 6))
        self.assertIsNone(AUTO.due_slot(self.at(11, 9, 1), self.at(10, 13, 1)))
        self.assertEqual(AUTO.due_slot(self.at(12, 0, 30), self.at(11, 6, 1)), None)  # 전날 13시는 지났다

    def test_utc_now_is_read_in_korean_time(self):
        import datetime as dt
        now = dt.datetime(2026, 10, 10, 21, 5, tzinfo=dt.timezone.utc)     # = 10/11 06:05 KST
        self.assertEqual(AUTO.due_slot(now, None), self.at(11, 6))

    def test_scheduler_off_on_loopback_db_or_switch(self):
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql+psycopg2://ci:ci@127.0.0.1:5432/ci"}):
            self.assertFalse(AUTO.scheduler_enabled())
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql+psycopg2://u:p@10.1.2.3:5432/db"}):
            self.assertTrue(AUTO.scheduler_enabled())
            with patch.dict(os.environ, {"MALL_PRICE_AUTO_SCHEDULE": "off"}):
                self.assertFalse(AUTO.scheduler_enabled())

    def test_api_starts_it_at_startup(self):
        from api import admin_mall_price
        self.assertIn(AUTO.start_scheduler, admin_mall_price.router.on_startup)


if __name__ == "__main__":
    unittest.main()
