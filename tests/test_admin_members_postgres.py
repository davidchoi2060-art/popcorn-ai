"""Opt-in member PostgreSQL checks. Never loads api.db, .env or DATABASE_URL.

Default/discovery: only safety checks; PostgreSQL cases are skipped.
Run in a fresh process, against an already available disposable local database:
  MEMBERS_TEST_PG_DSN=postgresql+psycopg2://.../popcorn_members_test_<name>
  python tests/test_admin_members_postgres.py --run --isolated-test-db
No database creation, software installation or shared configuration changes.
Creates/removes only its UUID schema, with original PostgreSQL SQL and _log.
"""
import argparse
import contextlib
import importlib
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
import types
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool


CONFIG = None  # Set by explicit CLI flags, never by unittest discovery.
SCHEMA_RE = re.compile(r'members_verify_[0-9a-f]{32}\Z')


def checked_url(dsn, attested):
    if not attested or not dsn:
        raise ValueError('Explicit isolated-test-db flag and test-only DSN required')
    try:
        url = make_url(dsn)
        valid = (url.drivername in ('postgresql', 'postgresql+psycopg2')
                 and url.host in ('127.0.0.1', '::1')
                 and bool(url.username)
                 and bool(re.fullmatch(r'popcorn_members_test_[a-z0-9_]{1,32}', url.database or ''))
                 and not url.query and 1 <= (url.port if url.port is not None else 5432) <= 65535)
    except Exception:
        raise ValueError('Invalid test-only DSN (value redacted)') from None
    if not valid:
        raise ValueError('Require explicit loopback IP, dedicated test DB name, no URL options')
    return url.set(drivername='postgresql+psycopg2')


def schema_sql(schema):
    if not SCHEMA_RE.fullmatch(schema):
        raise ValueError('Not a generated member verification schema')
    return '"' + schema + '"'


def connection_args(url, options, application_name):
    # Explicit address and port also override libpq's PGHOSTADDR/PGPORT/service defaults.
    return {'hostaddr': url.host, 'port': url.port if url.port is not None else 5432,
            'connect_timeout': 3, 'options': options, 'application_name': application_name}


class NeverConnect:
    def connect(self):
        raise AssertionError('Unpatched DB access')

    def begin(self):
        raise AssertionError('Unpatched DB access')


def target_modules():
    # Reject a process that has already loaded the actual production DB module.
    existing = sys.modules.get('api.db')
    if existing is not None and getattr(existing, '__file__', None):
        raise RuntimeError('Use a fresh process; actual api.db is already loaded')
    if existing is None:
        stub = types.ModuleType('api.db')
        stub.engine = NeverConnect()
        sys.modules['api.db'] = stub
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    return (importlib.import_module('api.admin_members'),
            importlib.import_module('api.my_account'))


# Minimal fixture: same relevant PG types, timestamp-without-zone, boolean,
# JSONB, BIGSERIAL and FK behavior. Does not run full application migrations.
DDL = (
    'CREATE TABLE admin_operators(operator_id BIGINT PRIMARY KEY)',
    'INSERT INTO admin_operators VALUES(1)',
    '''CREATE TABLE members(member_id BIGINT PRIMARY KEY, nickname VARCHAR(100) NOT NULL,
       email VARCHAR(255) UNIQUE, joined_via VARCHAR(20) NOT NULL,
       created_at TIMESTAMP NOT NULL, mall_member_id VARCHAR(100),
       mall_map_requested_at TIMESTAMP, status VARCHAR(20) NOT NULL,
       last_login_at TIMESTAMP, user_id BIGINT)''',
    '''CREATE TABLE orders(member_id BIGINT REFERENCES members(member_id),
       created_at TIMESTAMP NOT NULL, status VARCHAR(30))''',
    '''CREATE TABLE consult_sessions(member_id BIGINT REFERENCES members(member_id),
       created_at TIMESTAMP NOT NULL, data_origin VARCHAR(12) NOT NULL, user_id BIGINT)''',
    '''CREATE TABLE member_reviews(member_id BIGINT REFERENCES members(member_id),
       created_at TIMESTAMP NOT NULL, status VARCHAR(20))''',
    '''CREATE TABLE member_favorites(member_id BIGINT REFERENCES members(member_id),
       created_at TIMESTAMP NOT NULL, price_alert BOOLEAN NOT NULL)''',
    'CREATE TABLE ops_settings(key VARCHAR(30) PRIMARY KEY, mode VARCHAR(10) NOT NULL)',
    '''CREATE TABLE admin_operator_activity_logs(log_id BIGSERIAL PRIMARY KEY,
       operator_id BIGINT REFERENCES admin_operators(operator_id), action VARCHAR(100) NOT NULL,
       target_kind VARCHAR(50), target_id VARCHAR(100), detail JSONB,
       created_at TIMESTAMP NOT NULL DEFAULT now())''',
)


class SafetyGuards(unittest.TestCase):
    def test_dedicated_loopback_only(self):
        valid = 'postgresql://tester:unused@127.0.0.1:55432/popcorn_members_test_local'
        self.assertEqual(checked_url(valid, True).drivername, 'postgresql+psycopg2')
        for dsn, flag in ((valid, False), ('', True),
                          (valid.replace('127.0.0.1', 'db.example.invalid'), True),
                          (valid.replace('127.0.0.1', 'localhost'), True),
                          (valid.replace('popcorn_members_test_local', 'popcorn'), True),
                          (valid + '?hostaddr=192.0.2.1', True),
                          (valid.replace('postgresql:', 'sqlite:'), True),
                          (valid.replace(':55432', ':0'), True), ('broken', True)):
            with self.subTest(dsn=dsn, flag=flag), self.assertRaises(ValueError):
                checked_url(dsn, flag)

    def test_only_generated_schema_can_be_removed(self):
        self.assertEqual(schema_sql('members_verify_' + 'a'*32),
                         '"members_verify_' + 'a'*32 + '"')
        for name in ('public', 'members', 'members_verify_old', 'members_verify_' + 'a'*32 + ';'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                schema_sql(name)

    def test_refuses_process_with_production_db_module(self):
        loaded = types.ModuleType('api.db')
        loaded.__file__ = 'production-db-module-must-not-be-imported'
        with patch.dict(sys.modules, {'api.db': loaded}), self.assertRaises(RuntimeError):
            target_modules()

    def test_libpq_environment_cannot_redirect_address_or_port(self):
        url = checked_url('postgresql://tester@127.0.0.1/popcorn_members_test_local', True)
        with patch.dict(os.environ, {'PGHOSTADDR': '192.0.2.1', 'PGPORT': '9999'}):
            args = connection_args(url, '-c search_path=pg_catalog', 'guard-only')
        self.assertEqual((args['hostaddr'], args['port']), ('127.0.0.1', 5432))


class PostgreSQLMembers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if CONFIG is None:
            raise unittest.SkipTest('PostgreSQL not executed: explicit --run and isolated DB required')
        cls.schema = 'members_verify_' + uuid.uuid4().hex
        cls.created = False
        cls.engine = None
        cls.bootstrap = create_engine(CONFIG, poolclass=NullPool, connect_args=connection_args(CONFIG,
            '-c search_path=pg_catalog -c statement_timeout=10000 -c lock_timeout=6000',
            'members_verify_bootstrap'))
        cls.addClassCleanup(cls.cleanup)
        with cls.bootstrap.begin() as conn:
            if conn.execute(text('SELECT current_database()')).scalar_one() != CONFIG.database:
                raise RuntimeError('Unexpected database identity')
            # Refuse databases with application/user tables outside prior fixture schemas.
            outside = conn.execute(text("""SELECT count(*) FROM pg_class c JOIN pg_namespace n
                ON n.oid=c.relnamespace WHERE c.relkind IN ('r','p','v','m','f')
                AND n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
                AND n.nspname !~ '^members_verify_[0-9a-f]{32}$'""")).scalar_one()
            if outside:
                raise RuntimeError('Dedicated test database contains unrelated tables/views')
            conn.execute(text('CREATE SCHEMA ' + schema_sql(cls.schema)))
        cls.created = True  # Only after committed CREATE; never drop preexisting schemas.
        cls.engine = create_engine(CONFIG, isolation_level='READ COMMITTED', poolclass=NullPool,
                                   connect_args=connection_args(CONFIG,
            '-c search_path=' + cls.schema + ',pg_catalog -c timezone=UTC '
            '-c statement_timeout=10000 -c lock_timeout=6000', cls.schema))
        with cls.engine.begin() as conn:
            for statement in DDL:
                conn.execute(text(statement))
            print('Isolated PostgreSQL:', conn.execute(text('SHOW server_version')).scalar_one(),
                  'schema:', cls.schema, flush=True)
        cls.members, cls.account = target_modules()

    @classmethod
    def cleanup(cls):
        if cls.engine is not None:
            cls.engine.dispose()
        try:
            if cls.created:
                with cls.bootstrap.begin() as conn:
                    owned = conn.execute(text('''SELECT n.nspowner=(SELECT oid FROM pg_roles
                        WHERE rolname=current_user) FROM pg_namespace n WHERE n.nspname=:n'''),
                        {'n': cls.schema}).scalar_one()
                    if not owned:
                        raise RuntimeError('Fixture schema owner changed; not removing')
                    conn.execute(text('DROP SCHEMA ' + schema_sql(cls.schema) + ' CASCADE'))
                print('Removed own fixture schema:', cls.schema, flush=True)
        finally:
            cls.bootstrap.dispose()

    def setUp(self):
        with self.engine.begin() as conn:
            conn.execute(text('''TRUNCATE admin_operator_activity_logs, orders, consult_sessions,
                member_reviews, member_favorites, members, ops_settings RESTART IDENTITY'''))
            conn.execute(text("INSERT INTO ops_settings VALUES('member','own')"))
            conn.execute(text('''INSERT INTO members(member_id,nickname,email,joined_via,created_at,status,user_id)
                VALUES(:i,:n,:e,'email',TIMESTAMP '2026-09-01 01:00:00','active',:u)'''),
                [{'i': i, 'n': f'회원{i}', 'e': f'member-{i}@example.invalid', 'u': i+100}
                 for i in range(1, 13)])
        self.enterContext(patch.object(self.members, 'engine', self.engine))
        self.enterContext(patch.object(self.account, 'engine', self.engine))
        self.enterContext(patch.object(self.account, 'require_member', return_value={'member_id': 1}))

    def sql(self, statement, **params):
        with self.engine.begin() as conn:
            result = conn.execute(text(statement), params)
            return result.mappings().all() if result.returns_rows else None

    def member_row(self):
        return self.sql('SELECT mall_member_id,mall_map_requested_at FROM members WHERE member_id=1')[0]

    def logs(self):
        return self.sql('SELECT * FROM admin_operator_activity_logs ORDER BY log_id')

    def agree(self, agree=True):
        return self.account.account_map(self.account.MapBody(agree=agree))

    def expect_conflict(self, fn):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as cm:
            fn()
        self.assertEqual(cm.exception.status_code, 409)

    def outcome(self, fn):
        from fastapi import HTTPException
        try:
            return 200, fn()
        except HTTPException as exc:
            return exc.status_code, exc.detail

    @contextlib.contextmanager
    def held_log(self, action):
        # Keep the real write and row lock uncommitted while the other connection waits.
        held, release = threading.Event(), threading.Event()
        original = self.members._log

        def logger(*args, **kwargs):
            log_id = original(*args, **kwargs)
            if args[1] == action:
                held.set()
                if not release.wait(10):
                    raise AssertionError('Timed out waiting for race release')
            return log_id

        with patch.object(self.members, '_log', logger):
            try:
                yield held, release
            finally:
                release.set()

    @contextlib.contextmanager
    def observe_waiter(self):
        ready = threading.Event()
        pids = []

        def before(conn, cursor, statement, params, context, executemany):
            if 'FOR UPDATE' in statement:
                pids.append(conn.connection.driver_connection.get_backend_pid())
                ready.set()

        event.listen(self.engine, 'before_cursor_execute', before)
        try:
            yield ready, pids
        finally:
            event.remove(self.engine, 'before_cursor_execute', before)

    def assert_blocked(self, ready, pids):
        self.assertTrue(ready.wait(2), 'Waiting query never started')
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            rows = self.sql('SELECT cardinality(pg_blocking_pids(:p)) AS blockers', p=pids[-1])
            if rows[0]['blockers']:
                return
            time.sleep(.02)
        self.fail('No actual PostgreSQL row-lock wait observed')

    def test_postgres_search_timestamp_boolean_and_greatest(self):
        self.sql("UPDATE members SET nickname=:n,email=:e WHERE member_id=1",
                 n='서울 Mixed %_\\ 이름', e="o'hara@example.invalid")
        for q in ('mixed', '%', '_', '\\', "o'hara", '1'):
            self.assertEqual([r['id'] for r in self.members.search_members(q=q)['items']], [1])
        self.assertEqual(self.members.search_members(q="%' OR TRUE--")['total'], 0)
        self.sql("""INSERT INTO consult_sessions VALUES
            (1,TIMESTAMP '2026-08-19 15:57:46','real',101),
            (1,TIMESTAMP '2026-10-02 00:00:00','demo',101),
            (NULL,TIMESTAMP '2026-10-02 00:00:00','real',101),
            (1,TIMESTAMP '2026-08-19 15:57:46.000001','real',999)""")
        self.sql("INSERT INTO orders VALUES(1,TIMESTAMP '2026-10-02 01:00:00','취소')")
        self.sql("INSERT INTO member_reviews VALUES(1,TIMESTAMP '2026-10-02 02:00:00','숨김')")
        self.sql("""INSERT INTO member_favorites VALUES
            (1,TIMESTAMP '2026-10-02 03:00:00',true),
            (1,TIMESTAMP '2026-10-02 04:00:00',false)""")
        result = self.members.member_detail(1)['member']
        self.assertEqual([result[k] for k in ('orders','consults','reviews','favs','alerts')], [1,1,1,2,1])
        self.assertEqual(result['last'], '2026-10-02T04:00:00+00:00')
        self.assertEqual([r['id'] for r in self.members.search_members(sort='activity_desc')['items']],
                         [1,12,11,10,9,8,7,6,5,4,3,2])
        legacy = self.members.list_members()['items']
        extended = self.members.search_members(sort='id_asc')['items']
        self.assertEqual(legacy, [{k:r[k] for k in legacy[0]} for r in extended])

    def test_repeatable_read_actual_concurrent_commit(self):
        changed = []

        def after(conn, cursor, statement, params, context, executemany):
            if statement.startswith('SELECT COUNT(*) FROM members m') and not changed:
                changed.append(conn.get_isolation_level())
                self.sql("""INSERT INTO members(member_id,nickname,email,joined_via,created_at,status)
                    VALUES(99,'snapshot','snapshot@example.invalid','apple',now(),'suspended')""")
                self.sql("UPDATE ops_settings SET mode='mall' WHERE key='member'")

        event.listen(self.engine, 'after_cursor_execute', after)
        try:
            first = self.members.search_members(page_size=20)
        finally:
            event.remove(self.engine, 'after_cursor_execute', after)
        self.assertEqual(changed, ['REPEATABLE READ'])
        self.assertEqual(first['total'], 12)
        self.assertEqual(len(first['items']), 12)
        self.assertNotIn(99, [r['id'] for r in first['items']])
        self.assertNotIn('apple', first['available_filters']['via'])
        self.assertNotIn('suspended', first['available_filters']['status'])
        self.assertEqual(first['member_mode'], 'own')
        second = self.members.search_members()
        self.assertEqual(second['total'], 13)
        self.assertIn('apple', second['available_filters']['via'])
        self.assertEqual(second['member_mode'], 'mall')

    def test_duplicate_requests_actual_row_lock(self):
        with self.held_log('member_map_request') as (held, release), ThreadPoolExecutor(2) as pool:
            first = pool.submit(self.outcome, lambda: self.members.map_request(1))
            self.assertTrue(held.wait(2))
            try:
                with self.observe_waiter() as (ready, pids):
                    second = pool.submit(self.outcome, lambda: self.members.map_request(1))
                    self.assert_blocked(ready, pids)
            finally:
                release.set()
            self.assertEqual(sorted([first.result(7)[0], second.result(7)[0]]), [200,409])
        self.assertEqual(len(self.logs()), 1)
        self.assertEqual(self.logs()[0]['detail']['after']['mall_map_requested_at'],
                         self.members.member_detail(1)['member']['requested_at'])

    def test_duplicate_undo_jsonb_and_integer_cast(self):
        request = self.members.map_request(1)
        undo = lambda: self.members.undo_map_request(request['undo_id'])
        with self.held_log('member_map_request_undo') as (held, release), ThreadPoolExecutor(2) as pool:
            first = pool.submit(self.outcome, undo)
            self.assertTrue(held.wait(2))
            try:
                with self.observe_waiter() as (ready, pids):
                    second = pool.submit(self.outcome, undo)
                    self.assert_blocked(ready, pids)
            finally:
                release.set()
            self.assertEqual([first.result(7)[0], second.result(7)[0]], [200,409])
        self.assertEqual(self.logs()[-1]['detail']['ref_log_id'], request['undo_id'])
        # Restore only the fixture timestamp to reach duplicate-undo JSONB ::int predicate.
        self.sql('UPDATE members SET mall_map_requested_at=CAST(:t AS timestamptz) WHERE member_id=1',
                 t=request['requested_at'])
        self.expect_conflict(undo)
        self.assertEqual(len(self.logs()), 2)

    def test_request_after_undo_waits_then_creates_new_generation(self):
        old = self.members.map_request(1)['undo_id']
        with self.held_log('member_map_request_undo') as (held, release), ThreadPoolExecutor(2) as pool:
            first = pool.submit(self.members.undo_map_request, old)
            self.assertTrue(held.wait(2))
            try:
                with self.observe_waiter() as (ready, pids):
                    second = pool.submit(self.members.map_request, 1)
                    self.assert_blocked(ready, pids)
            finally:
                release.set()
            self.assertTrue(first.result(7)['ok'])
            new = second.result(7)['undo_id']
        self.assertGreater(new, old)
        self.expect_conflict(lambda: self.members.undo_map_request(old))
        self.assertTrue(self.members.undo_map_request(new)['ok'])

    def test_stale_undo_waits_for_new_request_then_conflicts(self):
        old = self.members.map_request(1)['undo_id']
        self.agree(False)  # Actual customer rejection implementation, isolated engine.
        with self.held_log('member_map_request') as (held, release), ThreadPoolExecutor(2) as pool:
            first = pool.submit(self.members.map_request, 1)
            self.assertTrue(held.wait(2))
            try:
                with self.observe_waiter() as (ready, pids):
                    second = pool.submit(self.outcome, lambda: self.members.undo_map_request(old))
                    self.assert_blocked(ready, pids)
            finally:
                release.set()
            new = first.result(7)
            self.assertEqual(second.result(7)[0], 409)
        self.assertEqual(self.members.member_detail(1)['member']['requested_at'], new['requested_at'])
        self.assertTrue(self.members.undo_map_request(new['undo_id'])['ok'])

    def test_logger_failure_rolls_back_real_log_and_member_update(self):
        original = self.members._log

        def fail_after_insert(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('fixture logger failure after actual JSONB insert')

        with patch.object(self.members, '_log', fail_after_insert), self.assertRaises(RuntimeError):
            self.members.map_request(1)
        self.assertIsNone(self.member_row()['mall_map_requested_at'])
        self.assertEqual(self.logs(), [])
        request = self.members.map_request(1)
        before = self.member_row()['mall_map_requested_at']
        with patch.object(self.members, '_log', fail_after_insert), self.assertRaises(RuntimeError):
            self.members.undo_map_request(request['undo_id'])
        self.assertEqual(self.member_row()['mall_map_requested_at'], before)
        self.assertEqual([r['action'] for r in self.logs()], ['member_map_request'])
        self.assertTrue(self.members.undo_map_request(request['undo_id'])['ok'])

    def test_customer_agreement_wins_undo_waits_and_keeps_mapping(self):
        request = self.members.map_request(1)
        held, release = threading.Event(), threading.Event()
        original = self.account._member

        def hold_customer(conn, member_id):
            row = original(conn, member_id)
            held.set()
            if not release.wait(10):
                raise AssertionError('Customer lock release timeout')
            return row

        with patch.object(self.account, '_member', hold_customer), ThreadPoolExecutor(2) as pool:
            first = pool.submit(self.agree)
            self.assertTrue(held.wait(2))
            try:
                with self.observe_waiter() as (ready, pids):
                    second = pool.submit(self.outcome,
                                         lambda: self.members.undo_map_request(request['undo_id']))
                    self.assert_blocked(ready, pids)
            finally:
                release.set()
            self.assertEqual(first.result(7)['map_state'], 'mapped')
            self.assertEqual(second.result(7)[0], 409)
        self.assertEqual(self.member_row()['mall_member_id'], 'MALL-2201')
        self.assertEqual(len(self.logs()), 1)

    def test_undo_wins_customer_agreement_waits_then_conflicts(self):
        request = self.members.map_request(1)
        with self.held_log('member_map_request_undo') as (held, release), ThreadPoolExecutor(2) as pool:
            first = pool.submit(self.members.undo_map_request, request['undo_id'])
            self.assertTrue(held.wait(2))
            try:
                with self.observe_waiter() as (ready, pids):
                    second = pool.submit(self.outcome, self.agree)
                    self.assert_blocked(ready, pids)
            finally:
                release.set()
            self.assertTrue(first.result(7)['ok'])
            self.assertEqual(second.result(7)[0], 409)
        self.assertIsNone(self.member_row()['mall_member_id'])
        self.assertIsNone(self.member_row()['mall_map_requested_at'])

    def test_request_wins_customer_agreement_waits_then_maps(self):
        with self.held_log('member_map_request') as (held, release), ThreadPoolExecutor(2) as pool:
            first = pool.submit(self.members.map_request, 1)
            self.assertTrue(held.wait(2))
            try:
                with self.observe_waiter() as (ready, pids):
                    second = pool.submit(self.agree)
                    self.assert_blocked(ready, pids)
            finally:
                release.set()
            self.assertTrue(first.result(7)['ok'])
            self.assertEqual(second.result(7)['map_state'], 'mapped')
        self.assertEqual(self.member_row()['mall_member_id'], 'MALL-2201')
        self.assertEqual(len(self.logs()), 1)

    def test_legacy_log_generation_guard(self):
        old = self.members.map_request(1)['undo_id']
        self.sql("UPDATE admin_operator_activity_logs SET detail=detail-'after'-'before' WHERE log_id=:i", i=old)
        self.agree(False)
        new = self.members.map_request(1)['undo_id']
        self.expect_conflict(lambda: self.members.undo_map_request(old))
        self.assertTrue(self.members.undo_map_request(new)['ok'])
        legacy = self.members.map_request(1)['undo_id']
        self.sql("UPDATE admin_operator_activity_logs SET detail=detail-'after'-'before' WHERE log_id=:i", i=legacy)
        self.assertTrue(self.members.undo_map_request(legacy)['ok'])


def main():
    global CONFIG
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='Execute real PG cases (explicit test DSN required)')
    parser.add_argument('--isolated-test-db', action='store_true',
                        help='Attest the local endpoint is a disposable test DB, not an operational forward')
    parser.add_argument('--self-check', action='store_true', help='No-connection guard checks only')
    parser.add_argument('--report', type=Path, help='Save a small result JSON without DSN/credentials')
    args = parser.parse_args()
    if args.run and args.self_check:
        parser.error('--run and --self-check are mutually exclusive')
    if args.run:
        try:
            CONFIG = checked_url(os.environ.get('MEMBERS_TEST_PG_DSN', ''), args.isolated_test_db)
        except ValueError as exc:
            parser.error(str(exc))
    suite = unittest.TestSuite()
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(SafetyGuards))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(PostgreSQLMembers))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if args.report:
        args.report.write_text(json.dumps({'postgres_execution_requested': CONFIG is not None,
            'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
            'skipped': [{'test': str(test), 'reason': reason} for test, reason in result.skipped],
            'successful': result.wasSuccessful(),
            'postgres_verified': CONFIG is not None and result.wasSuccessful() and not result.skipped},
            ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
