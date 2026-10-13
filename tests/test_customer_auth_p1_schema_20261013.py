"""고객 회원 P1 -- 0156 저장 구조 · Q1 PostgreSQL 실행기 (설계 docs/design/customer-social-login-v1.md §4·§5).

로그인은 여전히 닫혀 있어야 한다(RUNTIME_RESOLVER 503). 이 단계는 표와 읽기 실행기만 만든다.
개발 DB 에서 0156 upgrade -> 견본 행 -> SESSION_QUERY/MEMBER_QUERY 해석 -> downgrade 를 한 트랜잭션으로 돌리고
ROLLBACK 한 검증 기록은 PR 본문에 있다(이 파일은 DB 없이 도는 계약 검사).
"""
import importlib.util
import re
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from api import customer_auth_sql_read as Q
from api.customer_auth_pg_read import PostgresReadExecutor, REQUIRED_TABLES, normalize_row

ROOT = Path(__file__).resolve().parent.parent
MIG = ROOT / "db" / "migrations" / "versions" / "0156_customer_verified_identity.py"


def _mig():
    spec = importlib.util.spec_from_file_location("m0156", MIG)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_revision_chain():
    m = _mig()
    assert (m.revision, m.down_revision) == ("0156", "0155")
    heads = sorted(p.name for p in (ROOT / "db" / "migrations" / "versions").glob("0156_*.py"))
    assert heads == ["0156_customer_verified_identity.py"]


def _ddl_columns(src: str, table: str) -> set[str]:
    body = src.split(f"CREATE TABLE {table} (", 1)[1].split("\n        )", 1)[0]
    return {ln.strip().split()[0] for ln in body.splitlines()
            if ln.strip() and not ln.strip().startswith(("CHECK", "UNIQUE", "FOREIGN", "REFERENCES", "issued_auth_revision,", "auth_context_id,"))
            and re.match(r"^[a-z_]+\s", ln.strip())}


def test_migration_creates_every_column_q1_reads():
    src = MIG.read_text(encoding="utf-8")
    alias = {"s": "member_verified_sessions", "i": "member_verified_identities", "r": "member_session_issuance_receipts"}
    cols = {t: _ddl_columns(src, t) for t in alias.values()}
    used = set(re.findall(r"\b([sir])\.([a-z_]+)", Q.SESSION_QUERY))
    missing = [(a, c) for a, c in used if c not in cols[alias[a]]]
    assert missing == [], missing
    for c in re.findall(r"\bm\.([a-z_]+)", Q.SESSION_QUERY + Q.MEMBER_QUERY):
        assert c in {"member_id", "auth_subject", "auth_revision", "status", "nickname", "email"}
    assert "ADD COLUMN auth_subject UUID NULL UNIQUE" in src and "ADD COLUMN auth_revision BIGINT NULL" in src


def test_contract_rules_in_ddl():
    src = MIG.read_text(encoding="utf-8")
    assert "UNIQUE (issuer_key, subject)" in src                      # 이메일이 아니라 (공급자, 고유 ID)
    assert 'COLLATE "C"' in src and "lower(" not in src               # 정규화 금지
    assert "member_sessions " not in src.replace("member_verified_sessions", "")   # 옛 표는 쓰지 않는다
    assert "token" not in _ddl_columns(src, "oauth_login_attempts")    # 공급자 토큰 저장 없음
    assert "RAISE EXCEPTION 'customer identity records must be preserved'" in src


def test_tables_match_executor_readiness():
    src = MIG.read_text(encoding="utf-8")
    for t in REQUIRED_TABLES:
        name = t.split(".", 1)[1]
        assert name == "members" or f"CREATE TABLE {name} (" in src


def test_normalize_row_only_touches_uuid():
    u = uuid.uuid4()
    row = {"a": u, "b": 5, "c": Decimal("1.5"), "d": "x", "e": None}
    assert normalize_row(row) == {"a": str(u), "b": 5, "c": Decimal("1.5"), "d": "x", "e": None}


class _Boom:
    def connect(self):
        raise RuntimeError("down")


def test_executor_closes_on_bad_requirements_or_db_error():
    ex = PostgresReadExecutor(_Boom())
    assert ex.ready(Q.ReadRequirements()) is False                     # DB 를 못 읽으면 준비 안 됨
    assert ex.ready(Q.ReadRequirements(isolation="serializable")) is False
    with pytest.raises(RuntimeError):
        ex.observe(Q.MEMBER_QUERY, {"member_id": 1}, requirements=Q.ReadRequirements(read_only=False))


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return iter(self._rows)


class _Conn:
    def __init__(self, log, rows):
        self.log, self.rows = log, rows

    def execution_options(self, **kw):
        self.log.append(("options", kw))
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.log.append("closed")
        return False

    def begin(self):
        log = self.log

        class T:
            def rollback(self):
                log.append("rollback")
        return T()

    def execute(self, stmt, params=None):
        self.log.append(str(stmt))
        return _Result(self.rows if params is not None else [])


class _Engine:
    def __init__(self, rows):
        self.log, self.rows = [], rows

    def connect(self):
        return _Conn(self.log, self.rows)


def test_observe_is_read_only_read_committed_closed_and_sequenced():
    sub = uuid.uuid4()
    eng = _Engine([{"member_id": 7, "auth_subject": sub}])
    ex = PostgresReadExecutor(eng)
    a = ex.observe(Q.MEMBER_QUERY, {"member_id": 7}, requirements=Q.ReadRequirements())
    b = ex.observe(Q.MEMBER_QUERY, {"member_id": 7}, requirements=Q.ReadRequirements())
    assert ("options", {"isolation_level": "READ COMMITTED"}) in eng.log
    assert "SET TRANSACTION READ ONLY" in eng.log and "rollback" in eng.log and "closed" in eng.log
    assert a.rows == ({"member_id": 7, "auth_subject": str(sub)},)
    assert (a.transaction_closed, a.read_only, a.primary, a.isolation) == (True, True, True, "read committed")
    assert b.sequence > a.sequence


def test_login_stays_closed_and_executor_not_wired():
    auth = (ROOT / "api" / "customer_auth.py").read_text(encoding="utf-8")
    assert "customer_auth_pg_read" not in auth                         # P2 전까지 연결하지 않는다
    from api import customer_auth
    assert customer_auth.RUNTIME_RESOLVER is not None
    assert customer_auth.RuntimeIssuerReadiness().ready() is False
