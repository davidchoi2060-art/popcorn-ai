"""회원 탈퇴(L4) · 임시 행 정리 -- 2026-11-18 사장님 확정 「탈퇴는 회원 연결만 끊고, 기록은 180일 보관 뒤 자동 삭제」.

실제 DB 없이 SQL 을 기록하는 가짜 연결로 «무엇을 어떤 순서로 쓰는지»를 고정한다. 실제 PostgreSQL 흐름은
개발 서버 점검(가입 -> 탈퇴 -> 같은 공급자로 재가입 = 새 회원)에서 본다.
"""
import os
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://ci:ci@127.0.0.1:1/ci")

from api import customer_auth_issuer as ISS            # noqa: E402
from api import customer_auth_oauth as R               # noqa: E402


class _Result:
    def __init__(self, rows, rowcount):
        self._rows, self.rowcount = rows, rowcount

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return self._rows[0] if self._rows else None


class _Conn:
    """SQL 과 매개변수를 순서대로 기록한다. members 조회만 status 를 돌려준다."""

    def __init__(self, status="active"):
        self.status, self.calls = status, []

    def execute(self, clause, params=None):
        sql = " ".join(str(clause).split())
        self.calls.append((sql, dict(params or {})))
        if sql.startswith("SELECT status FROM members"):
            return _Result([{"status": self.status}] if self.status else [], 1)
        return _Result([], 3)


def _sql(conn, prefix):
    return [s for s, _ in conn.calls if s.startswith(prefix)]


def test_withdraw_revokes_everything_and_detaches_records():
    conn = _Conn()
    out = ISS.withdraw(conn, 5, now=1_700_000_000)
    sqls = [s for s, _ in conn.calls]
    assert sqls[0].startswith("SELECT status FROM members") and "FOR UPDATE" in sqls[0]
    # 세션 전부 철회 -> 신원 철회(+묘비 subject) -> 동의 철회 시각 -> 회원 행 -> 기록 연결 해제
    assert "UPDATE member_verified_sessions SET revoked_at_epoch" in sqls[1]
    assert "UPDATE member_verified_identities SET revoked_at_epoch" in sqls[2] and "'withdrawn:'" in sqls[2]
    assert "UPDATE member_consents SET withdrawn_at_epoch" in sqls[3]
    assert re.search(r"UPDATE members SET status = 'withdrawn', nickname = :n, email = NULL, withdrawn_at = now\(\),"
                     r" auth_revision = COALESCE\(auth_revision, 0\) \+ 1", sqls[4])
    assert conn.calls[4][1] == {"n": ISS.WITHDRAWN_NICKNAME, "m": 5}
    for table in ("mvp3_saved_recommendations", "purchase_inquiries", "handoffs"):
        assert f"UPDATE {table} SET member_id = NULL WHERE member_id = :m" in sqls
    # DELETE 는 하나도 없다 -- 기록은 보존기간 파기가 180일 뒤 값만 비운다
    assert not any(s.startswith("DELETE") for s in sqls)
    assert all(p.get("m") == 5 for _, p in conn.calls)
    assert all(p["t"] == 1_700_000_000 for _, p in conn.calls if "t" in p)
    assert out["sessions"] == 3 and out["identities"] == 3


@pytest.mark.parametrize("status", ["withdrawn", "suspended", None])
def test_withdraw_refuses_non_active_member_before_writing(status):
    conn = _Conn(status)
    with pytest.raises(ISS.AuthFlowError) as e:
        ISS.withdraw(conn, 5)
    assert e.value.code == "member_inactive" and e.value.status == 409
    assert len(conn.calls) == 1                      # 조회 한 번 뒤 멈춘다


def test_cleanup_deletes_only_day_old_temporary_rows():
    conn = _Conn()
    out = ISS.cleanup_expired(conn, now=1_700_000_000)
    deletes = _sql(conn, "DELETE")
    assert deletes == ["DELETE FROM oauth_login_attempts WHERE created_at_epoch < :c AND purpose = 'login'",
                       "DELETE FROM member_join_pending WHERE created_at_epoch < :c"]
    assert all(p == {"c": 1_700_000_000 - 86400} for _, p in conn.calls)
    assert out == {"attempts": 3, "pending": 3}
    assert ISS.CLEANUP_AFTER == 86400


def test_begin_attempt_runs_cleanup_first():
    conn = _Conn()
    ISS.begin_attempt(conn, "google", "/mvp4/", now=1_700_000_000)
    sqls = [s for s, _ in conn.calls]
    assert sqls[0].startswith("DELETE FROM oauth_login_attempts") and sqls[1].startswith("DELETE FROM member_join_pending")
    assert sqls[2].startswith("INSERT INTO oauth_login_attempts")


# ── 경로 ──────────────────────────────────────────────────────────────────────
class _Begin:
    def __enter__(self):
        return _Conn()

    def __exit__(self, *a):
        return False


class _Engine:
    def begin(self):
        return _Begin()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CUSTOMER_AUTH_ENABLED", "on")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "gid.apps")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "gsec")
    monkeypatch.setattr(R, "engine", _Engine())
    app = FastAPI()
    app.include_router(R.router)
    return TestClient(app, base_url="https://www.popcornai.co.kr", follow_redirects=False)


def test_withdraw_route_closed_when_disabled(client, monkeypatch):
    monkeypatch.delenv("CUSTOMER_AUTH_ENABLED")
    assert client.post("/api/auth/withdraw").status_code == 503


def test_withdraw_route_requires_same_origin_and_session(client, monkeypatch):
    assert client.post("/api/auth/withdraw", headers={"origin": "https://evil.example"}).status_code == 403
    monkeypatch.setattr(ISS, "session_member", lambda conn, token: None)
    r = client.post("/api/auth/withdraw")
    assert r.status_code == 401 and r.json()["detail"]["code"] == "unauthenticated"


def test_withdraw_route_clears_cookie_and_reports_ok(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(ISS, "session_member", lambda conn, token: 5)
    monkeypatch.setattr(ISS, "withdraw", lambda conn, m: seen.setdefault("m", m) and {"sessions": 1, "identities": 1})
    client.cookies.set("popcorn_member_session", "a" * 64)
    r = client.post("/api/auth/withdraw")
    assert r.status_code == 200 and r.json() == {"ok": True} and seen == {"m": 5}
    cookie = [c for c in r.headers.get_list("set-cookie") if c.startswith("popcorn_member_session=")][0]
    assert "Max-Age=0" in cookie or "expires=" in cookie.lower()
    assert r.headers["cache-control"] == "no-store"


def test_withdraw_route_maps_flow_error(client, monkeypatch):
    monkeypatch.setattr(ISS, "session_member", lambda conn, token: 5)
    monkeypatch.setattr(ISS, "withdraw", lambda conn, m: (_ for _ in ()).throw(ISS.AuthFlowError(409, "member_inactive")))
    client.cookies.set("popcorn_member_session", "a" * 64)
    r = client.post("/api/auth/withdraw")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "member_inactive"
