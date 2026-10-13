"""Q1 PostgreSQL read executor -- customer_auth_sql_read.ReadExecutor 의 실제 구현 (설계 customer-social-login-v1 §5, P1).

0156 이 만든 표를 짧은 읽기 전용 · READ COMMITTED 트랜잭션 하나로 읽고 닫는다. 드라이버 값 모양만 계약에 맞춘다:
psycopg2 는 UUID 열을 uuid.UUID 로 주는데 해석기(_uuid)는 정규 문자열만 받는다 -- 여기서 str 로 바꾼다.
그 밖의 값은 손대지 않는다(정수 epoch · EXTRACT 의 Decimal 그대로). 해석·검증은 해석기(SQLReadPort)가 한다.

★ 이 모듈은 아직 어디에도 연결하지 않는다. api/customer_auth.RUNTIME_RESOLVER 는 그대로 503 이다 --
  켜는 것은 P2(CUSTOMER_AUTH_ENABLED 스위치 + 공급자 검증기 + 발급 증거 대조)다.
"""
from itertools import count
from threading import Lock
import uuid

from sqlalchemy import text

from .customer_auth_sql_read import ReadRequirements, SCHEMA_CONTRACT, StatementObservation

# 0156 이 만드는 표. 하나라도 없으면 «준비 안 됨»(503) -- 마이그레이션 전 서버가 조회를 지어내지 않게.
REQUIRED_TABLES = ("public.members", "public.member_verified_identities",
                   "public.member_session_issuance_receipts", "public.member_verified_sessions")
REQUIRED_MEMBER_COLUMNS = ("auth_subject", "auth_revision")
_SCHEMA_SQL = text(
    "SELECT (SELECT count(*) FROM unnest(CAST(:tables AS text[])) t WHERE to_regclass(t) IS NOT NULL) AS tables,"
    " (SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name='members'"
    "  AND column_name = ANY(CAST(:cols AS text[]))) AS cols")


def normalize_row(row) -> dict:
    """드라이버 행 -> 계약 모양. uuid.UUID 만 정규 문자열로 바꾼다."""
    return {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in dict(row).items()}


class PostgresReadExecutor:
    """engine 을 받아 문장마다 새 연결 · 새 읽기 전용 트랜잭션으로 읽는다(캐시 없음)."""

    def __init__(self, engine):
        self._engine = engine
        self._seq = count(1)
        self._lock = Lock()

    def _requirements_ok(self, requirements) -> bool:
        return (isinstance(requirements, ReadRequirements) and requirements.schema_contract == SCHEMA_CONTRACT
                and requirements.isolation == "read committed" and requirements.read_only is True
                and requirements.primary is True and requirements.fresh_statement is True)

    def ready(self, requirements) -> bool:
        if not self._requirements_ok(requirements):
            return False
        try:
            with self._engine.connect() as conn:
                r = conn.execute(_SCHEMA_SQL, {"tables": list(REQUIRED_TABLES),
                                               "cols": list(REQUIRED_MEMBER_COLUMNS)}).mappings().first()
            return bool(r) and r["tables"] == len(REQUIRED_TABLES) and r["cols"] == len(REQUIRED_MEMBER_COLUMNS)
        except Exception:  # noqa: BLE001 - 읽지 못하면 준비 안 됨(503)으로 닫는다
            return False

    def observe(self, query, parameters, *, requirements):
        if not self._requirements_ok(requirements):
            raise RuntimeError("requirements")
        with self._engine.connect().execution_options(isolation_level="READ COMMITTED") as conn:
            trans = conn.begin()
            try:
                conn.execute(text("SET TRANSACTION READ ONLY"))
                rows = tuple(normalize_row(r) for r in conn.execute(text(query), dict(parameters)).mappings())
            finally:
                trans.rollback()        # 읽기만 했다 -- 닫는다
        with self._lock:
            seq = next(self._seq)
        return StatementObservation(sequence=seq, schema_contract=SCHEMA_CONTRACT, isolation="read committed",
                                    read_only=True, primary=True, transaction_closed=True, rows=rows)
