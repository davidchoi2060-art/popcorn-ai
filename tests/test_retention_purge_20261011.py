"""보관 기한이 지난 고객 개인정보 지우기 (2026-10-11 코덱스 검수 #84 · #85)."""
import datetime as dt
import importlib.util
import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://u:p@127.0.0.1:1/x")

from api import retention_purge as RP  # noqa: E402

UTC = dt.timezone.utc
KST = dt.timezone(dt.timedelta(hours=9))


def _migration():
    p = ROOT / 'db/migrations/versions/0153_retention_purge.py'
    spec = importlib.util.spec_from_file_location('m0153', p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Contract(unittest.TestCase):
    def test_revision_follows_main_head(self):
        m = _migration()
        self.assertEqual((m.revision, m.down_revision), ('0153', '0142'))

    def test_default_is_dry_run(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(RP.APPLY_ENV, None)
            self.assertFalse(RP.apply_enabled())
        with patch.dict(os.environ, {RP.APPLY_ENV: 'on'}):
            self.assertTrue(RP.apply_enabled())

    def test_scheduler_off_on_loopback_and_by_switch(self):
        with patch.dict(os.environ, {'DATABASE_URL': 'postgresql://u:p@127.0.0.1/x'}):
            self.assertFalse(RP.scheduler_enabled())
        with patch.dict(os.environ, {'DATABASE_URL': 'postgresql://u:p@db.example/x', RP.SCHEDULE_ENV: 'off'}):
            self.assertFalse(RP.scheduler_enabled())
        with patch.dict(os.environ, {'DATABASE_URL': 'postgresql://u:p@db.example/x', RP.SCHEDULE_ENV: ''}):
            self.assertTrue(RP.scheduler_enabled())

    def test_startup_hook_registered(self):
        self.assertIn(RP.start_scheduler, RP.router.on_startup)
        self.assertEqual(RP.router.routes, [])

    def test_due_slot(self):
        at = lambda h, m=0, d=11: dt.datetime(2026, 10, d, h, m, tzinfo=KST)
        # 04:00 전이면 어제 04:00 이 몫이다
        self.assertEqual(RP.due_slot(at(3), None), at(4, d=10))
        self.assertEqual(RP.due_slot(at(5), None), at(4))
        self.assertIsNone(RP.due_slot(at(5), at(4, 1)))
        self.assertEqual(RP.due_slot(at(5), at(4, d=10)), at(4))


def _local_url():
    from tests.test_mall_price import _local_url as f
    return f()


class _Op:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql):
        from sqlalchemy import text
        self.conn.execute(text(sql))


@unittest.skipUnless(_local_url(), '루프백 Postgres 가 없어 DB 검사를 건너뜁니다')
class PurgeOnPostgres(unittest.TestCase):
    NOW = dt.datetime(2026, 10, 11, 0, 0, tzinfo=UTC)

    def setUp(self):
        from sqlalchemy import create_engine, text
        self.text = text
        self.schema = 'retention_t_' + uuid.uuid4().hex[:12]
        with create_engine(_local_url()).begin() as c:
            c.execute(text('CREATE SCHEMA "%s"' % self.schema))
        self.engine = create_engine(_local_url(), connect_args={'options': '-csearch_path=%s' % self.schema})
        past, future = self.NOW - dt.timedelta(days=1), self.NOW + dt.timedelta(days=1)
        with self.engine.begin() as c:
            for stmt in (
                # 0061 · 0138 · 0139 의 해당 칸만(CHECK 는 원본 그대로 — 이름 없음)
                'CREATE TABLE talk_intent_hits (hit_id BIGSERIAL PRIMARY KEY, raw_text TEXT,'
                ' raw_masked_yn BOOLEAN NOT NULL DEFAULT true, raw_purge_at TIMESTAMP,'
                ' CONSTRAINT ck_talk_hits_purge CHECK (raw_text IS NULL OR raw_purge_at IS NOT NULL))',
                'CREATE TABLE talk_reply_reviews (hit_id BIGINT PRIMARY KEY REFERENCES talk_intent_hits(hit_id),'
                ' ai_reply TEXT, shown_reply TEXT, answer TEXT, memo TEXT, purge_at TIMESTAMPTZ)',
                'CREATE TABLE purchase_inquiries (inquiry_id BIGSERIAL PRIMARY KEY, contact_name VARCHAR(30),'
                ' contact_phone VARCHAR(20), contact_email VARCHAR(120), message TEXT, memo TEXT,'
                ' purge_at TIMESTAMPTZ NOT NULL,'
                ' CHECK(contact_phone IS NOT NULL OR contact_email IS NOT NULL))',
                # 0158 의 해당 칸만(방문자 연락처 -- users FK 는 이 격리 스키마에 두지 않는다)
                'CREATE TABLE mvp3_visitor_contacts (user_id BIGINT PRIMARY KEY, contact_phone VARCHAR(20),'
                ' contact_name VARCHAR(30), contact_email VARCHAR(120), purge_at TIMESTAMPTZ NOT NULL,'
                ' contact_purged_at TIMESTAMPTZ,'
                ' CHECK(contact_phone IS NOT NULL OR contact_purged_at IS NOT NULL))'):
                c.execute(text(stmt))
            _migration_mod = _migration()
            with patch.object(_migration_mod, 'op', _Op(c)):
                _migration_mod.upgrade()
            self.migration = _migration_mod
            n = lambda d: d.astimezone(UTC).replace(tzinfo=None)
            c.execute(text("INSERT INTO talk_intent_hits (hit_id, raw_text, raw_purge_at) VALUES"
                           " (1, '옛 질문', :p), (2, '새 질문', :f), (3, NULL, :p)"), {'p': n(past), 'f': n(future)})
            c.execute(text("INSERT INTO talk_reply_reviews (hit_id, ai_reply, shown_reply, answer, memo, purge_at)"
                           " VALUES (1, 'a', 's', 'n', '운영 메모', :p), (2, 'a', 's', 'n', NULL, :f)"),
                      {'p': past, 'f': future})
            c.execute(text("INSERT INTO purchase_inquiries (contact_name, contact_phone, contact_email, message,"
                           " memo, purge_at) VALUES ('홍', '010', NULL, '문의', '010-1234-5678 로 연락함', :p),"
                           " ('김', NULL, 'a@b.c', '문의', NULL, :f)"), {'p': past, 'f': future})
            c.execute(text("INSERT INTO mvp3_visitor_contacts (user_id, contact_phone, contact_name, purge_at)"
                           " VALUES (1, '010-1234-5678', '옛', :p), (2, '010-2222-3333', '새', :f)"), {'p': past, 'f': future})
        self.patch = patch.object(RP, 'engine', self.engine)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.engine.dispose()
        from sqlalchemy import create_engine
        with create_engine(_local_url()).begin() as c:
            c.execute(self.text('DROP SCHEMA "%s" CASCADE' % self.schema))

    def q(self, sql):
        with self.engine.connect() as c:
            return c.execute(self.text(sql)).all()

    def test_dry_run_counts_only_and_records(self):
        res = RP.purge('manual', apply=False, now=self.NOW)
        self.assertEqual(res['counts'], {'talk_raw': 1, 'talk_reply': 1, 'inquiry_contact': 1, 'visitor_contact': 1, 'inquiry_memo': 1})
        self.assertTrue(res['dry_run'])
        self.assertEqual(self.q('SELECT count(*) FROM talk_intent_hits WHERE raw_text IS NOT NULL')[0][0], 2)
        self.assertEqual(self.q('SELECT count(*) FROM purchase_inquiries WHERE contact_purged_at IS NULL')[0][0], 2)
        run = self.q('SELECT moment, dry_run, counts, finished_at IS NOT NULL FROM retention_purge_runs')
        self.assertEqual(run, [('manual', True, res['counts'], True)])

    def test_apply_clears_only_expired_values(self):
        res = RP.purge('manual', apply=True, now=self.NOW)
        self.assertEqual(res['counts'], {'talk_raw': 1, 'talk_reply': 1, 'inquiry_contact': 1, 'visitor_contact': 1, 'inquiry_memo': 1})
        self.assertEqual(self.q('SELECT hit_id, raw_text FROM talk_intent_hits ORDER BY hit_id'),
                         [(1, None), (2, '새 질문'), (3, None)])
        self.assertEqual(self.q('SELECT hit_id, ai_reply, shown_reply, answer, memo FROM talk_reply_reviews'
                                ' ORDER BY hit_id'),
                         [(1, None, None, None, '운영 메모'), (2, 'a', 's', 'n', None)])
        rows = self.q('SELECT contact_name, contact_phone, contact_email, message, memo, contact_purged_at'
                      ' FROM purchase_inquiries ORDER BY inquiry_id')
        self.assertEqual(rows[0][:4], (None, None, None, None))
        self.assertNotIn('1234-5678', rows[0][4])
        self.assertIn('로 연락함', rows[0][4])
        self.assertEqual(rows[0][5], self.NOW)
        self.assertEqual(rows[1][:5], ('김', None, 'a@b.c', '문의', None))
        self.assertIsNone(rows[1][5])
        # 다시 돌리면 지울 것이 없다
        self.assertEqual(RP.purge('manual', apply=True, now=self.NOW)['counts'],
                         {'talk_raw': 0, 'talk_reply': 0, 'inquiry_contact': 0, 'visitor_contact': 0, 'inquiry_memo': 0})
        # 비운 뒤 운영자가 메모에 연락처를 다시 적어도 다음 실행이 가린다
        with self.engine.begin() as c:
            c.execute(self.text("UPDATE purchase_inquiries SET memo = 'a@b.co 재연락' WHERE inquiry_id = 1"))
        self.assertEqual(RP.purge('manual', apply=True, now=self.NOW)['counts']['inquiry_memo'], 1)
        self.assertNotIn('a@b.co', self.q('SELECT memo FROM purchase_inquiries WHERE inquiry_id = 1')[0][0])

    def test_visitor_contact_values_cleared_row_kept(self):
        RP.purge('manual', apply=True, now=self.NOW)
        rows = self.q('SELECT user_id, contact_phone, contact_name, contact_purged_at FROM mvp3_visitor_contacts'
                      ' ORDER BY user_id')
        self.assertEqual(rows[0], (1, None, None, self.NOW))
        self.assertEqual(rows[1][:3], (2, '010-2222-3333', '새'))
        self.assertIsNone(rows[1][3])

    def test_contact_check_still_guards_live_rows(self):
        from sqlalchemy.exc import IntegrityError
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as c:
                c.execute(self.text("INSERT INTO purchase_inquiries (contact_name, purge_at) VALUES ('x', now())"))

    def test_scheduled_slot_runs_once(self):
        slot = dt.datetime(2026, 10, 11, 4, 0, tzinfo=KST)
        now = slot + dt.timedelta(minutes=5)
        self.assertTrue(RP.purge('auto', apply=False, now=now, slot=slot)['ok'])
        again = RP.purge('auto', apply=False, now=now, slot=slot)
        self.assertEqual((again['ok'], again['run_id']), (False, None))
        self.assertEqual(self.q("SELECT count(*) FROM retention_purge_runs WHERE moment='auto'")[0][0], 1)
        # 손으로 돌린 것은 정기 시각을 채우지 않는다
        RP.purge('manual', apply=False, now=now)
        with self.engine.connect() as c:
            self.assertEqual(RP._last_auto_started(c), now)

    def test_failure_is_recorded(self):
        bad = (('talk_raw', 'no_such_table WHERE x <= :now', 'x = NULL'),)
        with patch.object(RP, 'TARGETS', bad):
            with self.assertRaises(Exception):
                RP.purge('manual', apply=False, now=self.NOW)
        err = self.q('SELECT error FROM retention_purge_runs')
        self.assertEqual(len(err), 1)
        self.assertIn('no_such_table', err[0][0])

    def test_failed_scheduled_run_is_retried_same_day(self):
        slot = dt.datetime(2026, 10, 11, 4, 0, tzinfo=KST)
        now = slot + dt.timedelta(minutes=5)
        bad = (('talk_raw', 'no_such_table WHERE x <= :now', 'x = NULL'),)
        with patch.object(RP, 'TARGETS', bad), self.assertRaises(Exception):
            RP.purge('auto', apply=True, now=now, slot=slot)
        with self.engine.connect() as c:
            self.assertIsNone(RP._last_auto_started(c))          # 실패는 그 시각을 채우지 않는다
            self.assertEqual(RP.due_slot(now + dt.timedelta(minutes=5), RP._last_auto_started(c)), slot)
        res = RP.purge('auto', apply=True, now=now + dt.timedelta(minutes=5), slot=slot)
        self.assertTrue(res['ok'])
        self.assertEqual(res['counts']['inquiry_contact'], 1)
        with self.engine.connect() as c:
            self.assertEqual(RP._last_auto_started(c), now + dt.timedelta(minutes=5))

    def test_tick_stops_after_repeated_failures(self):
        now = dt.datetime.now(dt.timezone.utc)
        slot = RP.due_slot(now, None)
        with self.engine.begin() as c:
            for _ in range(RP.MAX_FAILURES):
                c.execute(self.text("INSERT INTO retention_purge_runs (moment, dry_run, error, started_at)"
                                    " VALUES ('auto', true, 'x', :s)"), {'s': slot})
        with patch.object(RP, 'purge') as run:
            RP._tick()
        run.assert_not_called()
        with self.engine.begin() as c:
            c.execute(self.text("DELETE FROM retention_purge_runs"))
        with patch.object(RP, 'purge', return_value={'ok': True}) as run:
            RP._tick()
        run.assert_called_once()
        self.assertEqual(run.call_args.kwargs['slot'], slot)

    def test_downgrade_refuses_after_purge(self):
        RP.purge('manual', apply=True, now=self.NOW)
        from sqlalchemy.exc import DBAPIError
        with self.assertRaises(DBAPIError):
            with self.engine.begin() as c, patch.object(self.migration, 'op', _Op(c)):
                self.migration.downgrade()


if __name__ == '__main__':
    unittest.main()
