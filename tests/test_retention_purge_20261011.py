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


def _migration_0179():
    p = ROOT / 'db/migrations/versions/0179_visitor_last_used.py'
    spec = importlib.util.spec_from_file_location('m0179', p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Contract0179(unittest.TestCase):
    """방문자 식별값·보관 견적 1년 파기(2026-11-18 사장님 승인 · 개인정보처리방침 2026-11-23)."""

    def test_revision_follows_head(self):
        m = _migration_0179()
        self.assertEqual((m.revision, m.down_revision), ('0179', '0178'))

    def test_targets_keep_rows_and_skip_members(self):
        t = {name: (target, assign) for name, target, assign in RP.TARGETS}
        self.assertEqual(RP.IDLE_DAYS, 365)
        target, assign = t['visitor_key']
        self.assertTrue(target.startswith('users WHERE anon_key IS NOT NULL AND last_used_at <= :idle_before'))
        self.assertIn('m.withdrawn_at IS NULL', target)
        self.assertEqual(assign, 'anon_key = NULL, anon_key_purged_at = :now')
        target, assign = t['saved_quote']
        self.assertIn('member_id IS NULL', target)
        self.assertIn('purged_at IS NULL', target)
        for col in ('owner_key_hash = NULL', 'request_basis = NULL', 'product_snapshot', 'talk_state', 'purged_at = :now'):
            self.assertIn(col, assign)
        for name in ('visitor_key', 'saved_quote'):
            self.assertNotIn('DELETE', t[name][0] + t[name][1])


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
                ' CHECK(contact_phone IS NOT NULL OR contact_purged_at IS NOT NULL))',
                # 0001 users · members(0156 withdrawn_at) · 0123 보관 견적(+0156 member_id) -- 해당 칸만
                'CREATE TABLE users (user_id BIGSERIAL PRIMARY KEY, anon_key VARCHAR(64) UNIQUE,'
                ' created_at TIMESTAMP NOT NULL DEFAULT now())',
                'CREATE TABLE members (member_id BIGSERIAL PRIMARY KEY, user_id BIGINT REFERENCES users(user_id),'
                ' withdrawn_at TIMESTAMPTZ)',
                'CREATE TABLE mvp3_saved_recommendations (quote_id UUID PRIMARY KEY,'
                ' user_id BIGINT NOT NULL REFERENCES users(user_id),'
                ' owner_key_hash VARCHAR(64) NOT NULL CHECK(length(owner_key_hash)=64), request_id UUID NOT NULL,'
                ' request_basis VARCHAR(64) NOT NULL CHECK(length(request_basis)=64),'
                " product_snapshot JSONB NOT NULL CHECK(jsonb_typeof(product_snapshot)='object'),"
                " talk_state JSONB NOT NULL CHECK(jsonb_typeof(talk_state)='object'),"
                ' saved_at TIMESTAMPTZ NOT NULL DEFAULT now(), member_id BIGINT REFERENCES members(member_id),'
                ' UNIQUE(user_id,owner_key_hash,request_id))'):
                c.execute(text(stmt))
            # 0179 이전에 있던 행 -- 마이그레이션이 created_at · saved_at 으로 마지막 이용을 채운다
            old, recent = self.NOW - dt.timedelta(days=400), self.NOW - dt.timedelta(days=10)
            c.execute(text("INSERT INTO users (user_id, anon_key, created_at) VALUES"
                           " (1, 'k-old', :o), (2, 'k-new', :r), (3, 'k-member', :o), (4, 'k-withdrawn', :o)"),
                      {'o': old.replace(tzinfo=None), 'r': recent.replace(tzinfo=None)})
            c.execute(text("INSERT INTO members (member_id, user_id, withdrawn_at) VALUES (1, 3, NULL), (2, 4, :o)"),
                      {'o': old})
            h = 'a' * 64
            c.execute(text(
                "INSERT INTO mvp3_saved_recommendations (quote_id, user_id, owner_key_hash, request_id, request_basis,"
                " product_snapshot, talk_state, saved_at, member_id) VALUES"
                " ('00000000-0000-0000-0000-000000000001', 1, :h, '00000000-0000-0000-0000-0000000000a1', :h,"
                "  '{\"name\": \"옛 견적\"}', '{\"usages\": [\"게임\"]}', :o, NULL),"
                " ('00000000-0000-0000-0000-000000000002', 2, :h, '00000000-0000-0000-0000-0000000000a2', :h,"
                "  '{\"name\": \"새 견적\"}', '{}', :r, NULL),"
                " ('00000000-0000-0000-0000-000000000003', 3, :h, '00000000-0000-0000-0000-0000000000a3', :h,"
                "  '{\"name\": \"회원 견적\"}', '{}', :o, 1)"), {'h': h, 'o': old, 'r': recent})
            _migration_mod = _migration()
            with patch.object(_migration_mod, 'op', _Op(c)):
                _migration_mod.upgrade()
            self.migration = _migration_mod
            self.migration_0179 = _migration_0179()
            with patch.object(self.migration_0179, 'op', _Op(c)):
                self.migration_0179.upgrade()
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
        self.assertEqual(res['counts'], {'talk_raw': 1, 'talk_reply': 1, 'inquiry_contact': 1, 'visitor_contact': 1,
                                         'visitor_key': 2, 'saved_quote': 1, 'inquiry_memo': 1})
        self.assertTrue(res['dry_run'])
        self.assertEqual(self.q('SELECT count(*) FROM talk_intent_hits WHERE raw_text IS NOT NULL')[0][0], 2)
        self.assertEqual(self.q('SELECT count(*) FROM purchase_inquiries WHERE contact_purged_at IS NULL')[0][0], 2)
        run = self.q('SELECT moment, dry_run, counts, finished_at IS NOT NULL FROM retention_purge_runs')
        self.assertEqual(run, [('manual', True, res['counts'], True)])

    def test_apply_clears_only_expired_values(self):
        res = RP.purge('manual', apply=True, now=self.NOW)
        self.assertEqual(res['counts'], {'talk_raw': 1, 'talk_reply': 1, 'inquiry_contact': 1, 'visitor_contact': 1,
                                         'visitor_key': 2, 'saved_quote': 1, 'inquiry_memo': 1})
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
                         {'talk_raw': 0, 'talk_reply': 0, 'inquiry_contact': 0, 'visitor_contact': 0,
                          'visitor_key': 0, 'saved_quote': 0, 'inquiry_memo': 0})
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

    def test_migration_backfills_last_used_from_first_seen(self):
        rows = self.q('SELECT user_id, last_used_at < now() - interval \'300 days\' FROM users ORDER BY user_id')
        self.assertEqual(rows, [(1, True), (2, False), (3, True), (4, True)])
        rows = self.q('SELECT quote_id::text, last_used_at = saved_at FROM mvp3_saved_recommendations ORDER BY 1')
        self.assertTrue(all(r[1] for r in rows))

    def test_idle_visitor_key_and_saved_quote_are_emptied_rows_kept(self):
        RP.purge('manual', apply=True, now=self.NOW)
        users = self.q('SELECT user_id, anon_key, anon_key_purged_at FROM users ORDER BY user_id')
        self.assertEqual([(u, k) for u, k, _ in users], [(1, None), (2, 'k-new'), (3, 'k-member'), (4, None)])
        self.assertEqual([p for _, _, p in users], [self.NOW, None, None, self.NOW])
        quotes = self.q('SELECT user_id, owner_key_hash, request_basis, product_snapshot, talk_state, purged_at, member_id'
                        ' FROM mvp3_saved_recommendations ORDER BY user_id')
        self.assertEqual(quotes[0][:6], (1, None, None, {}, {}, self.NOW))          # 1년 쓰지 않은 비회원 견적
        self.assertEqual(quotes[1][1:4], ('a' * 64, 'a' * 64, {'name': '새 견적'}))  # 최근 견적은 그대로
        self.assertEqual((quotes[2][1], quotes[2][5], quotes[2][6]), ('a' * 64, None, 1))  # 회원 견적은 뺀다

    def test_live_saved_quote_still_needs_owner(self):
        from sqlalchemy.exc import IntegrityError
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as c:
                c.execute(self.text("UPDATE mvp3_saved_recommendations SET owner_key_hash = NULL WHERE user_id = 2"))

    def test_0179_downgrade_refuses_after_purge_and_roundtrips_before(self):
        from sqlalchemy.exc import DBAPIError
        with self.engine.begin() as c, patch.object(self.migration_0179, 'op', _Op(c)):
            self.migration_0179.downgrade()                    # 비운 행이 없으면 되돌아간다
        self.assertEqual(self.q("SELECT count(*) FROM information_schema.columns WHERE table_schema = current_schema()"
                                " AND column_name IN ('last_used_at', 'purged_at', 'anon_key_purged_at')")[0][0], 0)
        with self.engine.begin() as c, patch.object(self.migration_0179, 'op', _Op(c)):
            self.migration_0179.upgrade()
        RP.purge('manual', apply=True, now=self.NOW)
        with self.assertRaises(DBAPIError):
            with self.engine.begin() as c, patch.object(self.migration_0179, 'op', _Op(c)):
                self.migration_0179.downgrade()

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
