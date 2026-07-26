"""고객 인증 — 소셜 신원 + 세션 (슬라이스 38).

**공개 배포 차단 사유를 닫는 작업.** 그동안 `/api/my/*`는 `?email=` 하나로 아무나
남의 주문·결제·후기를 볼 수 있었다. 이제 회원 경계는 **세션이 정한다**(요청이 주장하는
이메일이 아니라).

관리자 인증(슬라이스 37)과 **의도적으로 다른 3가지** — 지키는 대상이 다르기 때문:
  ① **승인 게이트 없음** — 첫 로그인이 곧 가입이고 즉시 이용한다.
  ② **절대 14일 · 유휴 만료 없음**(관리자는 8시간/30분) — 고객은 재방문 간격이 길고
     다루는 권한이 자기 데이터뿐이다.
  ③ **권한 등급 없음** — 회원은 자기 데이터만 본다. 경계는 member_id 하나.

같은 원칙: **비밀번호를 저장하지 않는다.** 지금은 `dev` 어댑터(입력 이메일을 신원으로
신뢰) — 카카오·네이버·구글 연동은 `_verify_*()`만 채우면 되고 세션 로직은 그대로다.
**dev 어댑터는 로컬 전용 — 공개 배포 차단 사유.**

게스트는 그대로 열려 있다: 상담·추천·주문 생성(`/api/candidates`·`/api/recommend`·
`/api/orders`)은 로그인을 요구하지 않는다. 견적을 보려고 가입을 강요하지 않는다는
UX 결정(A-10)을 인증이 뒤집지 않는다.
"""
import secrets
from contextvars import ContextVar

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import text

from .db import engine

router = APIRouter(prefix="/api/auth")

COOKIE = "popcorn_member_session"
ABSOLUTE_DAYS = 14            # 절대 만료(유휴 만료는 두지 않는다 — 위 ② 참조)
VIA = {"카카오": "kakao", "네이버": "naver", "구글": "google", "이메일": "email",
       "kakao": "kakao", "naver": "naver", "google": "google", "email": "email",
       "dev": "email"}

_current: ContextVar[dict | None] = ContextVar("current_member", default=None)

# 게이트 대상 = 회원 전용 경로. 인증 엔드포인트 자체는 예외.
GUARDED_PREFIX = "/api/my/"
OPEN_PREFIXES = ("/api/auth/",)


def current_member() -> dict | None:
    return _current.get()


def require_member() -> dict:
    """회원 전용 데이터 접근 — 세션이 없으면 401. 미들웨어가 이미 막지만, 라우터가
    스스로도 보장하게 둔다(미들웨어 경로 규칙이 바뀌어도 데이터가 새지 않도록)."""
    m = _current.get()
    if m is None:
        raise HTTPException(401, "로그인이 필요합니다")
    return m


def _new_session(conn, member_id: int, ua: str | None) -> str:
    sid = secrets.token_hex(32)
    conn.execute(text(
        "INSERT INTO member_sessions (session_id, member_id, expires_at, user_agent)"
        " VALUES (:s, :m, now() + :d * interval '1 day', :ua)"),
        {"s": sid, "m": member_id, "d": ABSOLUTE_DAYS, "ua": (ua or "")[:300]})
    conn.execute(text(
        "UPDATE members SET last_login_at=now() WHERE member_id=:m"), {"m": member_id})
    return sid


def resolve_session(sid: str) -> dict | None:
    """세션 검증. 시각 비교는 전부 DB now()로 한다(슬라이스 37에서 겪은 함정 — 로컬
    KST와 DB UTC를 비교하면 방금 만든 세션도 만료로 오판된다)."""
    if not sid:
        return None
    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT s.member_id, m.email, m.nickname, m.joined_via, m.status,"
            " (s.revoked_at IS NOT NULL) AS revoked,"
            " (s.expires_at <= now()) AS expired"
            " FROM member_sessions s JOIN members m USING (member_id)"
            " WHERE s.session_id=:s"), {"s": sid}).mappings().first()
        if row is None or row["revoked"] or row["expired"]:
            return None
        if row["status"] != "active":          # 탈퇴·정지 회원의 세션은 즉시 무효
            return None
        conn.execute(text(
            "UPDATE member_sessions SET last_seen_at=now() WHERE session_id=:s"), {"s": sid})
        return {"member_id": row["member_id"], "email": row["email"],
                "nickname": row["nickname"], "via": row["joined_via"]}


async def member_middleware(request: Request, call_next):
    """`/api/my/*` 게이트 + 주체 전달. 게스트 경로는 건드리지 않는다."""
    path = request.url.path
    token = _current.set(None)
    try:
        if not path.startswith(OPEN_PREFIXES):
            m = resolve_session(request.cookies.get(COOKIE, ""))
            if m is not None:
                _current.set(m)          # 게스트 경로에서도 세션이 있으면 주체를 안다
            elif path.startswith(GUARDED_PREFIX):
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "로그인이 필요합니다"}, status_code=401)
        return await call_next(request)
    finally:
        _current.reset(token)


# ───────────────────────────── 인증 엔드포인트 ─────────────────────────────
class LoginBody(BaseModel):
    email: str
    nickname: str | None = None
    provider: str = "dev"        # 카카오 | 네이버 | 구글 | 이메일 — dev 어댑터가 신원 대체


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response):
    """로그인 = 가입. 계정이 없으면 만들고 바로 세션을 준다(승인 게이트 없음)."""
    email = (body.email or "").strip().lower()
    if "@" not in email:
        raise HTTPException(400, "이메일 형식이 올바르지 않습니다")
    via = VIA.get(body.provider, "email")
    with engine.begin() as conn:
        m = conn.execute(text(
            "SELECT member_id, email, nickname, joined_via, status FROM members"
            " WHERE lower(email)=:e FOR UPDATE"), {"e": email}).mappings().first()
        created = False
        if m is None:
            member_id = conn.execute(text(
                "INSERT INTO members (email, nickname, joined_via, provider_uid, status)"
                " VALUES (:e, :n, :v, :uid, 'active') RETURNING member_id"),
                {"e": email, "n": (body.nickname or email.split("@")[0])[:50],
                 "v": via, "uid": email}).scalar()
            created = True
            m = conn.execute(text(
                "SELECT member_id, email, nickname, joined_via, status FROM members"
                " WHERE member_id=:i"), {"i": member_id}).mappings().first()
        elif m["status"] != "active":
            raise HTTPException(403, "이용할 수 없는 계정입니다 — 고객센터에 문의해 주세요")
        sid = _new_session(conn, m["member_id"], request.headers.get("user-agent"))
        response.set_cookie(COOKIE, sid, httponly=True, samesite="lax", path="/",
                            max_age=ABSOLUTE_DAYS * 24 * 3600)
        return {"state": "active", "created": created,
                "member": {"id": m["member_id"], "email": m["email"],
                           "nickname": m["nickname"], "via": m["joined_via"]},
                "message": ("가입 완료 — 이제 상담·견적이 저장됩니다" if created
                            else "다시 오셨네요, 반가워요!")}


@router.post("/logout")
def logout(request: Request, response: Response):
    sid = request.cookies.get(COOKIE, "")
    if sid:
        with engine.begin() as conn:      # 삭제하지 않고 철회 기록
            conn.execute(text(
                "UPDATE member_sessions SET revoked_at=now()"
                " WHERE session_id=:s AND revoked_at IS NULL"), {"s": sid})
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    m = resolve_session(request.cookies.get(COOKIE, ""))
    return {"authenticated": m is not None, "member": m,
            "note": ("신원 확인은 현재 dev 어댑터입니다(입력 이메일을 신원으로 신뢰) —"
                     " 카카오·네이버·구글 연동 시 검증부만 교체되며 세션 로직은 그대로입니다."
                     " **로컬 전용 — 공개 배포 차단 사유.**"
                     " 상담·추천·주문은 로그인 없이도 됩니다(게스트 유지).")}
