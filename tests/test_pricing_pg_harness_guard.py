import importlib
import importlib.util
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("pricing_guard_test", ROOT / "tests/pricing_pg_harness.py")
harness = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = harness
spec.loader.exec_module(harness)
DSN = "postgresql://popcorn_pricing_test_runner:synthetic-secret@127.0.0.1:55432/popcorn_pricing_test_guard"


def prepare(dsn=DSN, **extra):
    return harness.prepare_harness(run=True, isolated_test_db=True,
                                  environ={harness.DSN_SETTING: dsn, **extra})


def facts(plan):
    return dict(current_database=plan.database, current_user=harness.TEST_ROLE,
                session_user=harness.TEST_ROLE, database_owner=harness.TEST_ROLE,
                server_addr=plan.host, server_port=plan.port, role_superuser=False,
                role_createdb=False, role_createrole=False, role_replication=False,
                role_bypassrls=False, role_memberships=0, unrelated_relations=0,
                database_create_allowed=True)


class PricingHarnessGuardTests(unittest.TestCase):
    def setUp(self):
        # Deterministic tests, never a replacement-environment bypass in production.
        self.environment_patch = patch.dict('os.environ', {}, clear=True)
        self.environment_patch.start()
        self.addCleanup(self.environment_patch.stop)

    def test_default_is_skip_even_with_config_and_production_environment(self):
        with patch.dict('os.environ', {harness.DSN_SETTING: DSN, 'DATABASE_URL': 'private'}):
            self.assertIsNone(harness.prepare_harness())
        self.assertIsNone(harness.prepare_harness(environ={harness.DSN_SETTING: DSN}))

    def test_flags_must_be_explicit_booleans(self):
        for flags in ({'run': 'yes'}, {'run': 1}, {'isolated_test_db': 1},
                      {'run': True}, {'run': True, 'isolated_test_db': False}):
            with self.subTest(flags=flags), self.assertRaises(harness.HarnessGuardError):
                harness.prepare_harness(environ={harness.DSN_SETTING: DSN}, **flags)

    def test_missing_setting_refuses_without_reading_production_value(self):
        with self.assertRaises(harness.HarnessGuardError):
            harness.prepare_harness(run=True, isolated_test_db=True, environ={})
        with self.assertRaises(harness.HarnessGuardError) as caught:
            prepare(DATABASE_URL='production-private')
        self.assertNotIn('production-private', str(caught.exception))

    def test_only_literal_loopback_and_explicit_port(self):
        for host in ('localhost', '127.1', '2130706433', '127.0.0.2', '192.0.2.1',
                     '127.0.0.1.evil', '%31%32%37.0.0.1', '127.0.0.1,127.0.0.2', '[::ffff:127.0.0.1]'):
            with self.subTest(host=host), self.assertRaises(harness.HarnessGuardError):
                prepare(DSN.replace('127.0.0.1', host))
        for authority in ('127.0.0.1', '127.0.0.1:0', '127.0.0.1:65536', '127.0.0.1:-1'):
            with self.assertRaises(harness.HarnessGuardError):
                prepare(DSN.replace('127.0.0.1:55432', authority))
        self.assertEqual(prepare(DSN.replace('127.0.0.1', '[::1]')).host, '::1')

    def test_dedicated_role_database_and_no_options(self):
        invalid = [DSN.replace(harness.TEST_ROLE, 'postgres'), DSN.replace(harness.TEST_ROLE, '%70opcorn_pricing_test_runner'),
                   DSN.replace('popcorn_pricing_test_guard', 'production'),
                   DSN.replace('popcorn_pricing_test_guard', 'popcorn_members_test_guard'),
                   DSN.replace('popcorn_pricing_test_guard', 'popcorn_pricing_test_%67uard'),
                   DSN+'/other', DSN+'?host=192.0.2.1', DSN+'?', DSN+'#fragment',
                   DSN.replace('postgresql://', 'sqlite://'), DSN+'\n']
        for dsn in invalid:
            with self.subTest(case=invalid.index(dsn)), self.assertRaises(harness.HarnessGuardError):
                prepare(dsn)

    def test_password_validation_and_redacted_error_repr(self):
        for password in ('', '%', '%FF', '%00', '%0A', 'raw@secret'):
            with self.assertRaises(harness.HarnessGuardError) as caught:
                prepare(DSN.replace('synthetic-secret', password))
            self.assertNotIn(DSN, str(caught.exception))
        plan = prepare(DSN.replace('synthetic-secret', 'synthetic%40secret'))
        self.assertNotIn('synthetic', repr(plan))
        self.assertNotIn('postgresql://', repr(plan))
        self.assertNotIn('synthetic', repr(plan.safe_summary()))

    def test_libpq_environment_cannot_redirect_or_load_service_passfile(self):
        for key in ('PGHOST', 'PGHOSTADDR', 'PGPORT', 'PGDATABASE', 'PGUSER', 'PGPASSWORD',
                    'PGSERVICE', 'PGSERVICEFILE', 'PGPASSFILE', 'PGOPTIONS', 'PGSSLMODE', 'pghost'):
            with self.subTest(key=key), self.assertRaises(harness.HarnessGuardError):
                prepare(**{key: 'private-redirect'})

    def test_kwargs_require_fresh_opt_in_and_process_recheck(self):
        plan = prepare()
        with self.assertRaises(harness.HarnessGuardError):
            plan.verification_kwargs(environ={})
        with self.assertRaises(harness.HarnessGuardError):
            plan.verification_kwargs(run=True, isolated_test_db=True, environ={'PGHOSTADDR': 'private'})
        kwargs = plan.verification_kwargs(run=True, isolated_test_db=True, environ={})
        self.assertEqual(kwargs['hostaddr'], '127.0.0.1')
        self.assertEqual(kwargs['port'], 55432)
        self.assertEqual(kwargs['user'], harness.TEST_ROLE)
        self.assertEqual(kwargs['passfile'], harness.os.devnull)
        self.assertIn('default_transaction_read_only=on', kwargs['options'])
        self.assertNotIn('synthetic', repr(plan.safe_summary()))

    def test_actual_environment_cannot_be_hidden_by_injected_environment(self):
        plan = prepare()
        for key in ('PGHOSTADDR', 'PGSERVICE', 'DATABASE_URL'):
            for injected in ({}, {harness.DSN_SETTING: DSN}):
                with self.subTest(key=key, injected=bool(injected)):
                    with patch.dict('os.environ', {key: 'synthetic-private'}, clear=True):
                        with self.assertRaises(harness.HarnessGuardError):
                            plan.verification_kwargs(run=True, isolated_test_db=True, environ=injected)
                        with self.assertRaises(harness.HarnessGuardError):
                            harness.prepare_harness(run=True, isolated_test_db=True, environ=injected)

    def test_loaded_application_modules_are_refused(self):
        for module in ('api.db', 'api.main'):
            with patch.dict(sys.modules, {module: object()}):
                with self.assertRaises(harness.HarnessGuardError):
                    prepare()
                with self.assertRaises(harness.HarnessGuardError):
                    with harness.blocked_application_imports():
                        pass

    def test_scoped_import_guard_blocks_and_restores(self):
        before = list(sys.meta_path)
        with harness.blocked_application_imports():
            with self.assertRaises(harness.HarnessGuardError):
                sys.meta_path[0].find_spec('api.db')
            self.assertIsNone(sys.meta_path[0].find_spec('decimal'))
        self.assertEqual(sys.meta_path, before)

    def test_directly_constructed_or_tampered_plans_are_rechecked(self):
        plan = prepare()
        for changes in ({'host': '192.0.2.1'}, {'port': True}, {'database': None},
                        {'database': 'production'}, {'schema': 'public'}, {'schema': None},
                        {'_password': ''}):
            with self.subTest(changes=changes), self.assertRaises(harness.HarnessGuardError):
                replace(plan, **changes).verification_kwargs(run=True, isolated_test_db=True, environ={})

    def test_server_facts_reject_privileged_roles_wrong_identity_and_user_relations(self):
        plan = prepare()
        self.assertTrue(harness.validate_server_facts(plan, facts(plan)))
        for key in facts(plan):
            invalid = facts(plan); invalid[key] = None
            with self.subTest(key=key), self.assertRaises(harness.HarnessGuardError):
                harness.validate_server_facts(plan, invalid)
        for key in ('role_superuser', 'role_createdb', 'role_createrole', 'role_replication', 'role_bypassrls'):
            invalid = facts(plan); invalid[key] = True
            with self.assertRaises(harness.HarnessGuardError):
                harness.validate_server_facts(plan, invalid)
        for key in ('role_memberships', 'unrelated_relations'):
            invalid = facts(plan); invalid[key] = 1
            with self.assertRaises(harness.HarnessGuardError):
                harness.validate_server_facts(plan, invalid)

    def test_generated_schema_and_contract_are_offline_only(self):
        a, b = prepare(), prepare()
        self.assertNotEqual(a.schema, b.schema)
        self.assertRegex(a.schema, harness.SCHEMA_RE)
        result = harness.transaction_contract(a)
        self.assertFalse(result['fixture_writes_enabled'])
        self.assertTrue(result['independent_connections'])
        self.assertTrue(result['rollback_on_exception'])
        self.assertTrue(result['cleanup_requires_committed_creation_and_current_ownership'])
        self.assertFalse(a.safe_summary()['postgres_verified'])

    def test_barrier_is_bounded_without_waiting(self):
        barrier = harness.new_barrier(2)
        self.assertEqual(barrier.parties, 2)
        for parties in (True, 1, 9, '2'):
            with self.assertRaises(harness.HarnessGuardError):
                harness.new_barrier(parties)

    def test_isolated_import_has_no_driver_application_or_connection_side_effects(self):
        code = '''import sys, socket
sys.path.insert(0, PATH)
socket.socket = lambda *a, **k: (_ for _ in ()).throw(AssertionError('network forbidden'))
import pricing_pg_harness as h
assert h.prepare_harness() is None
import importlib
with h.blocked_application_imports():
    try:
        importlib.import_module('api.db')
    except h.HarnessGuardError:
        pass
    else:
        raise AssertionError('application import was not blocked')
assert not any(n.startswith(('api.', 'psycopg', 'sqlalchemy', 'dotenv')) for n in sys.modules)
assert not hasattr(h, 'connect')
'''.replace('PATH', repr(str(ROOT/'tests')))
        code = 'import sys; sys.path.insert(0, ' + repr(str(ROOT)) + ')\n' + code
        result = subprocess.run([sys.executable, '-I', '-B', '-c', code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
