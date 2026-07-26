"""관리자 인증 — 소셜 신원 + 승인 게이트 + 세션 + 권한 (슬라이스 37).

설계(사용자 확정 2026-07-26): **비밀번호를 저장하지 않는다.** 신원은 소셜 제공자가 확인하고
우리는 승인 여부와 권한만 관리한다. 자체 비밀번호를 더하면 이 이득이 사라지므로 만들지 않는다.

흐름: 소셜 로그인 → 계정 없으면 status='대기'로 신청 → **승인 전에는 어떤 데이터도 안 보인다**
→ owner 승인 + 권한 부여 → 세션 발급. 퇴사·사고 시 '정지'(세션 즉시 무효).

**provider 어댑터**: 지금은 `dev`(이메일 입력으로 신원 대체 — 앱 등록 없이 전 흐름 검증).
실제 구글 연동은 클라이언트 ID·시크릿이 준비되면 `_verify_google()`만 채우면 된다
(신청·승인·세션·권한 로직은 그대로 재사용). **dev 어댑터는 로컬 전용 — 공개 배포 차단 사유.**

주체 전달: 엔드포인트 시그니처를 건드리지 않기 위해 contextvar를 쓴다. 미들웨어가 세션을 해석해
현재 운영자를 담고, `_log`가 그것을 읽어 **작업 기록의 주체가 실제 로그인 운영자**가 된다
(그동안 operator_id=1 고정이라 "누가 했는지"를 남기지 못했다).
"""
import os
import secrets
from contextvars import ContextVar

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import text

from .db import engine

router = APIRouter(prefix="/api/admin/auth")

COOKIE = "popcorn_admin_session"
ABSOLUTE_HOURS = 8      # 절대 만료
IDLE_MINUTES = 30       # 유휴 만료
ROLE_RANK = {"viewer": 1, "operator": 2, "owner": 3}

# 미들웨어가 채우는 현재 운영자 — 시그니처 무변경으로 주체를 전달하는 수단
_current: ContextVar[dict | None] = ContextVar("current_operator", default=None)

# 게이트 예외 — 인증 자체와 정적 파일
OPEN_PREFIXES = ("/api/admin/auth/",)


def bootstrap_emails() -> set:
    """첫 관리자 — .env ADMIN_BOOTSTRAP_EMAILS(쉼표 구분)만 첫 로그인 시 자동 owner."""
    raw = os.environ.get("ADMIN_BOOTSTRAP_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def current_operator() -> dict | None:
    return _current.get()


def current_operator_id() -> int:
    """작업 기록 주체. 세션이 없으면 1(시드 운영자) — 인증 미적용 경로의 하위 호환."""
    op = _current.get()
    return op["operator_id"] if op else 1


def _new_session(conn, operator_id: int, ua: str | None) -> str:
    sid = secrets.token_hex(32)
    conn.execute(text(
        "INSERT INTO admin_sessions (session_id, operator_id, expires_at, user_agent)"
        " VALUES (:s, :o, now() + :h * interval '1 hour', :ua)"),
        {"s": sid, "o": operator_id, "h": ABSOLUTE_HOURS, "ua": (ua or "")[:300]})
    conn.execute(text(
        "UPDATE admin_operators SET last_login_at=now() WHERE operator_id=:o"),
        {"o": operator_id})
    return sid


def resolve_session(sid: str) -> dict | None:
    """세션 검증 + 유휴 갱신. 만료·유휴·정지·철회면 None.

    시각 비교는 **전부 DB의 now()** 로 한다 — 파이썬 로컬시각(KST)과 DB 시각(UTC)을
    비교하면 방금 만든 세션도 만료로 오판한다(실제로 겪은 함정).
    """
    if not sid:
        return None
    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT s.operator_id, o.name, o.email, o.role, o.status,"
            " (s.revoked_at IS NOT NULL) AS revoked,"
            " (s.expires_at <= now()) AS expired,"
            " (s.last_seen_at <= now() - :idle * interval '1 minute') AS idle"
            " FROM admin_sessions s JOIN admin_operators o USING (operator_id)"
            " WHERE s.session_id=:s"),
            {"s": sid, "idle": IDLE_MINUTES}).mappings().first()
        if row is None or row["revoked"] or row["expired"] or row["idle"]:
            return None
        if row["status"] != "활성":            # 대기·정지 계정의 세션은 즉시 무효
            return None
        conn.execute(text(
            "UPDATE admin_sessions SET last_seen_at=now() WHERE session_id=:s"), {"s": sid})
        return {"operator_id": row["operator_id"], "name": row["name"],
                "email": row["email"], "role": row["role"], "status": row["status"]}


def required_role(method: str, path: str) -> str:
    """경로·메서드별 최소 권한 — 읽기 viewer / 쓰기 operator / 운영자·정책 owner."""
    if path.startswith("/api/admin/operators"):
        return "owner"
    return "viewer" if method in ("GET", "HEAD", "OPTIONS") else "operator"


async def auth_middleware(request: Request, call_next):
    """/api/admin/* 게이트. 예외는 인증 엔드포인트뿐 — 승인 전에는 어떤 데이터도 주지 않는다."""
    path = request.url.path
    token = _current.set(None)
    try:
        if path.startswith("/api/admin/") and not path.startswith(OPEN_PREFIXES):
            op = resolve_session(request.cookies.get(COOKIE, ""))
            if op is None:
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "로그인이 필요합니다"}, status_code=401)
            need = required_role(request.method, path)
            if ROLE_RANK.get(op["role"], 0) < ROLE_RANK[need]:
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    {"detail": f"권한이 부족합니다(필요: {need}, 현재: {op['role']})"},
                    status_code=403)
            _current.set(op)
        return await call_next(request)
    finally:
        _current.reset(token)


# ───────────────────────────── 인증 엔드포인트 ─────────────────────────────
class LoginBody(BaseModel):
    email: str
    name: str | None = None
    provider: str = "dev"        # dev | google — 구글 연동 시 id_token 검증으로 교체
    phone: str | None = None
    duty: str | None = None


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response):
    """소셜 신원으로 로그인·신청. dev 어댑터는 이메일을 신원으로 신뢰한다(로컬 전용)."""
    email = (body.email or "").strip().lower()
    if "@" not in email:
        raise HTTPException(400, "이메일 형식이 올바르지 않습니다")
    with engine.begin() as conn:
        op = conn.execute(text(
            "SELECT operator_id, name, email, role, status FROM admin_operators"
            " WHERE lower(email)=:e FOR UPDATE"), {"e": email}).mappings().first()
        if op is None:
            # 신청 생성 — 승인 전에는 어떤 데이터도 볼 수 없다
            auto_owner = email in bootstrap_emails()
            new_id = conn.execute(text(
                "INSERT INTO admin_operators (name, email, role, status, provider, provider_uid,"
                " phone, duty, approved_at)"
                " VALUES (:n, :e, :r, :st, :p, :uid, :ph, :du, CASE WHEN :st='활성' THEN now() END)"
                " RETURNING operator_id"),
                {"n": (body.name or email.split("@")[0])[:100], "e": email,
                 "r": "owner" if auto_owner else "viewer",
                 "st": "활성" if auto_owner else "대기",
                 "p": body.provider, "uid": email, "ph": body.phone, "du": body.duty}).scalar()
            if auto_owner:
                sid = _new_session(conn, new_id, request.headers.get("user-agent"))
                response.set_cookie(COOKIE, sid, httponly=True, samesite="lax", path="/")
                return {"state": "active", "operator": {"id": new_id, "email": email,
                        "role": "owner"}, "bootstrap": True,
                        "message": "부트스트랩 계정으로 자동 승인됐습니다(관리자 권한)"}
            return {"state": "pending", "operator": {"id": new_id, "email": email},
                    "message": "신청이 접수됐습니다 — 관리자 승인 후 이용할 수 있습니다"}
        if op["status"] == "대기":
            return {"state": "pending", "operator": {"id": op["operator_id"], "email": email},
                    "message": "승인 대기 중입니다 — 관리자에게 승인을 요청하세요"}
        if op["status"] == "정지":
            raise HTTPException(403, "정지된 계정입니다 — 관리자에게 문의하세요")
        sid = _new_session(conn, op["operator_id"], request.headers.get("user-agent"))
        response.set_cookie(COOKIE, sid, httponly=True, samesite="lax", path="/")
        return {"state": "active", "operator": {"id": op["operator_id"], "name": op["name"],
                "email": op["email"], "role": op["role"]}}


@router.post("/logout")
def logout(request: Request, response: Response):
    sid = request.cookies.get(COOKIE, "")
    if sid:
        with engine.begin() as conn:      # 삭제하지 않고 철회 기록(감사)
            conn.execute(text(
                "UPDATE admin_sessions SET revoked_at=now()"
                " WHERE session_id=:s AND revoked_at IS NULL"), {"s": sid})
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    op = resolve_session(request.cookies.get(COOKIE, ""))
    return {"authenticated": op is not None, "operator": op,
            "note": ("provider는 현재 dev 어댑터입니다(이메일을 신원으로 신뢰) —"
                     " 구글 연동은 클라이언트 ID 준비 시 교체하며 신청·승인·세션 로직은 그대로입니다."
                     " **dev 어댑터는 로컬 전용이며 공개 배포 차단 사유입니다.**")}
