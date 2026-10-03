"""Offline safety preparation for a future isolated pricing PostgreSQL harness.

No driver imports, connections, SQL execution, schema creation or application
imports occur here. A valid plan is NOT authorization or proof of an isolated
server. A future executor must verify server facts before any fixture write.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
import importlib.abc
import os
import re
import sys
import threading
from urllib.parse import unquote, urlsplit
import uuid


DSN_SETTING = "PRICING_TEST_PG_DSN"
TEST_ROLE = "popcorn_pricing_test_runner"
DB_RE = re.compile(r"popcorn_pricing_test_[a-z0-9_]{1,32}\Z")
SCHEMA_RE = re.compile(r"pricing_verify_[0-9a-f]{32}\Z")
_BLOCKED_MODULES = {"api.db", "api.main"}


class HarnessGuardError(ValueError):
    """Fixed error codes only; caller inputs and underlying exceptions stay private."""


def _fail(code):
    raise HarnessGuardError(code) from None


def _check_process(environ):
    if any(name in sys.modules for name in _BLOCKED_MODULES):
        _fail("application_module_already_loaded")
    for key in environ:
        if type(key) is not str:
            _fail("invalid_environment_key")
        upper = key.upper()
        if upper.startswith("PG") or upper == "DATABASE_URL":
            _fail("production_or_libpq_environment_present")


@dataclass(frozen=True, repr=False)
class HarnessPlan:
    host: str
    port: int
    database: str
    schema: str
    _password: str = field(repr=False)

    def __repr__(self):
        return "HarnessPlan(offline_only=True, credentials=redacted)"

    def safe_summary(self):
        return {"state": "prepared_not_connected", "postgres_verified": False,
                "fixtures_executed": 0, "schema": self.schema}

    def verification_kwargs(self, *, run=False, isolated_test_db=False, environ=None):
        """Future read-only connector arguments, after rechecking the process.

        This exports a password to the caller for a future driver; NEVER print,
        log, serialize or include the returned mapping in diagnostics. It does
        not import a driver or connect. Fresh runtime flags are required again.
        """
        if run is not True or isolated_test_db is not True:
            _fail("explicit_opt_in_required")
        _check_process(dict(os.environ))
        if environ is not None:
            _check_process(environ)
        _validate_plan(self)
        return {"host": self.host, "hostaddr": self.host, "port": self.port,
                "dbname": self.database, "user": TEST_ROLE, "password": self._password,
                "passfile": os.devnull, "connect_timeout": 3,
                "application_name": "pricing_verify_guard",
                "options": "-c search_path=pg_catalog -c timezone=UTC "
                           "-c statement_timeout=10000 -c lock_timeout=5000 "
                           "-c idle_in_transaction_session_timeout=10000 "
                           "-c default_transaction_read_only=on"}


def _validate_plan(plan):
    if (not isinstance(plan, HarnessPlan) or type(plan.host) is not str
            or plan.host not in ("127.0.0.1", "::1") or type(plan.port) is not int
            or not 1 <= plan.port <= 65535 or type(plan.database) is not str
            or not DB_RE.fullmatch(plan.database) or type(plan.schema) is not str
            or not SCHEMA_RE.fullmatch(plan.schema) or type(plan._password) is not str
            or not plan._password or any(ord(c) < 32 or ord(c) == 127 for c in plan._password)):
        _fail("invalid_plan")


def prepare_harness(*, run=False, isolated_test_db=False, environ=None):
    """None means skip; enabled preparation only reads the dedicated setting.

    Default discovery/import remains disconnected even if a DSN is configured.
    Literal loopback IP and explicit port are required; hosts, Unix sockets,
    multi-host URLs, query options, service redirects and production variables
    are refused. Password escapes are decoded strictly, never shown on failure.
    """
    if type(run) is not bool or type(isolated_test_db) is not bool:
        _fail("boolean_flags_required")
    if not run:
        return None
    if not isolated_test_db:
        _fail("explicit_isolation_attestation_required")
    actual_environment = dict(os.environ)
    _check_process(actual_environment)
    environment = actual_environment if environ is None else environ
    if environ is not None:
        _check_process(environ)
    dsn = environment.get(DSN_SETTING)
    if type(dsn) is not str or not dsn:
        _fail("dedicated_test_setting_required")
    try:
        if any(c.isspace() for c in dsn) or "?" in dsn or "#" in dsn:
            raise ValueError
        parsed = urlsplit(dsn)
        if parsed.scheme not in ("postgresql", "postgresql+psycopg2"):
            raise ValueError
        if parsed.netloc.count("@") != 1 or parsed.username != TEST_ROLE:
            raise ValueError
        if parsed.hostname not in ("127.0.0.1", "::1") or parsed.port is None:
            raise ValueError
        # Require the literal authority spelling, rejecting encoded/suffixed hosts.
        authority = parsed.netloc.rsplit("@", 1)[1]
        if not re.fullmatch(r"(?:127\.0\.0\.1|\[::1\]):[0-9]{1,5}", authority):
            raise ValueError
        if not DB_RE.fullmatch(parsed.path.removeprefix("/")):
            raise ValueError
        password = parsed.password
        if password is None or re.search(r"%(?![0-9a-fA-F]{2})", password):
            raise ValueError
        password = unquote(password, encoding="utf-8", errors="strict")
        plan = HarnessPlan(parsed.hostname, parsed.port, parsed.path[1:],
                           "pricing_verify_" + uuid.uuid4().hex, password)
        _validate_plan(plan)
    except (ValueError, TypeError, UnicodeError):
        _fail("invalid_test_connection_input")
    return plan


def validate_server_facts(plan, facts):
    """Offline acceptance of future read-only server probes; never queries PG.

    The future executor must obtain these facts itself on EVERY independent
    connection, not trust owner-supplied assertions. Matching names alone cannot
    establish a disposable cluster or absence of grants to other databases.
    """
    _validate_plan(plan)
    expected = {"current_database": plan.database, "current_user": TEST_ROLE,
                "session_user": TEST_ROLE, "database_owner": TEST_ROLE,
                "server_addr": plan.host, "server_port": plan.port,
                "role_superuser": False, "role_createdb": False,
                "role_createrole": False, "role_replication": False,
                "role_bypassrls": False, "role_memberships": 0,
                "unrelated_relations": 0, "database_create_allowed": True}
    if not isinstance(facts, dict):
        _fail("server_verification_failed")
    for key, value in expected.items():
        actual = facts.get(key)
        if type(actual) is not type(value) or actual != value:
            _fail("server_verification_failed")
    return True


class _BlockApplicationDB(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in _BLOCKED_MODULES:
            _fail("application_import_blocked")
        return None


@contextmanager
def blocked_application_imports():
    """Fresh-process scoped guard, not a sandbox for arbitrary untrusted code."""
    if any(name in sys.modules for name in _BLOCKED_MODULES):
        _fail("application_module_already_loaded")
    blocker = _BlockApplicationDB()
    sys.meta_path.insert(0, blocker)
    try:
        yield
    finally:
        sys.meta_path.remove(blocker)


def transaction_contract(plan):
    """Future executor requirements only; no fixture write or SQL execution API."""
    _validate_plan(plan)
    return {"schema": plan.schema, "independent_connections": True,
            "verify_every_connection": True, "isolation_level": "READ COMMITTED",
            "statement_timeout_ms": 10000, "lock_timeout_ms": 5000,
            "barrier_timeout_seconds": 5, "rollback_on_exception": True,
            "assert_before_after_on_separate_connection": True,
            "cleanup_requires_committed_creation_and_current_ownership": True,
            "fixture_writes_enabled": False}


def new_barrier(parties):
    if type(parties) is not int or not 2 <= parties <= 8:
        _fail("invalid_barrier_parties")
    return threading.Barrier(parties, timeout=5)
