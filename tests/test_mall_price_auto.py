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


    def test_reading_stops_before_a_live_run_could_look_dead(self):
        # 코덱스 검수 #106·#109: 살아 있는 수집이 STALE_RUNNING 을 넘기면 다른 실행이 겹친다
        t = [0.0]
        def clock():
            return t[0]
        def read(code, pt):
            t[0] += AUTO.COLLECT_LIMIT / 2 + 1
            return {"ok": True, "price": 1000}
        with self.assertRaises(AUTO.CollectError) as e:
            AUTO.collect_public([(1, "x"), (2, "x"), (3, "x")], sleep=lambda s: None,
                                read=read, clock=clock)
        self.assertEqual(e.exception.args[1]["stopped_at"], 2)
        self.assertLess(AUTO.COLLECT_LIMIT, 2 * 3600)            # STALE_RUNNING = 2 hours

    def test_command_line_run_is_recorded_as_manual(self):
        from tools import mall_price_auto as CLI
        with patch.object(CLI.AUTO, "run", return_value={"ok": True}) as run:
            self.assertEqual(CLI.main([]), 0)
        run.assert_called_once_with("manual")

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

    def test_slot_is_checked_again_inside_the_lock(self):
        # 코덱스 검수 #106·#109: 잠금 밖에서 「미실행」을 읽은 두 프로세스가 같은 시각을 두 번 돌지 않는다
        import datetime as dt
        slot = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)
        first = AUTO.begin("auto", slot=slot)
        AUTO.execute(first, "auto", collect_public_fn=lambda codes: ({1: 1000}, {"source": "pages"}))
        with self.assertRaises(AUTO.SlotDone):
            AUTO.begin("auto", slot=slot)
        out = AUTO.run("auto", slot=slot)
        self.assertEqual((out["ok"], out["run_id"]), (False, None))
        with self.engine.connect() as c:
            self.assertEqual(c.execute(self.text("SELECT count(*) FROM mall_price_runs")).scalar(), 1)

    def test_manual_run_does_not_fill_the_scheduled_slot(self):
        import datetime as dt
        slot = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)
        AUTO.execute(AUTO.begin("manual"), "manual",
                     collect_public_fn=lambda codes: ({1: 1000}, {"source": "pages"}))
        self.assertIsNone(AUTO._last_auto_started())
        AUTO.begin("auto", slot=slot)                             # 정기 실행은 그대로 돈다

    def _orphan(self, moment="auto"):
        # 이 프로세스보다 먼저 시작해 끝나지 못한 실행(배포 재시작에 죽은 실행)
        with self.engine.begin() as c:
            return c.execute(self.text(
                "INSERT INTO mall_price_runs (moment, source, started_at)"
                " VALUES (:m, 'pages', now() - interval '20 minutes') RETURNING run_id"), {"m": moment}).scalar()

    def test_run_killed_by_a_restart_does_not_fill_the_slot(self):
        import datetime as dt
        self._orphan()
        with patch.object(AUTO, "PROCESS_STARTED", dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)):
            self.assertIsNone(AUTO._last_auto_started())
            slot = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=30)
            self.assertEqual(AUTO.abandon_orphans(), 1)
            run_id = AUTO.begin("auto", slot=slot)                # 「이미 실행 중」으로 막히지 않는다
        self.assertIsNotNone(run_id)
        with self.engine.connect() as c:
            row = c.execute(self.text("SELECT ok, fail_reason FROM mall_price_runs ORDER BY run_id LIMIT 1")).one()
        self.assertEqual(tuple(row), (False, AUTO.ORPHAN_REASON))

    def test_a_finished_or_live_run_still_fills_the_slot(self):
        import datetime as dt
        AUTO.execute(AUTO.begin("auto"), "auto", collect_public_fn=lambda codes: ({1: 1000}, {"source": "pages"}))
        AUTO.begin("auto")                                        # 이 프로세스에서 돌고 있는 실행
        self.assertEqual(AUTO.abandon_orphans(), 0)
        self.assertIsNone(AUTO.due_slot(dt.datetime.now(dt.timezone.utc), AUTO._last_auto_started()))

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



class StageExpiryTests(unittest.TestCase):
    """코덱스 검수 #99: 반영도 미리보기 보존 기한(1시간)을 직접 본다 — 다음 미리보기만 지우던 구멍."""

    def test_old_preview_file_is_refused_and_removed(self):
        import tempfile
        import time
        from fastapi import HTTPException
        from api import admin_mall_price as AMP
        d = tempfile.mkdtemp()
        p = os.path.join(d, "abc123.json")
        with io.open(p, "w", encoding="utf-8") as f:
            json.dump({"file_name": "a.csv", "prices": {"1": 1000}}, f)
        old = time.time() - AMP.STAGE_TTL - 5
        os.utime(p, (old, old))
        with patch.object(AMP, "STAGE_DIR", d), \
                patch.object(AMP, "_owner", return_value={"operator_id": 1}), \
                patch.object(AMP, "engine", side_effect=AssertionError("DB 에 닿으면 안 된다")):
            with self.assertRaises(HTTPException) as e:
                AMP.apply(staging_id="abc123", token="t", include_parts=False)
        self.assertEqual(e.exception.status_code, 410)
        self.assertFalse(os.path.exists(p))

if __name__ == "__main__":
    unittest.main()
