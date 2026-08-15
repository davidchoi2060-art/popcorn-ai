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
import os
import secrets
from contextvars import ContextVar

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

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

# OPEN_PREFIXES = 이 미들웨어가 고객 세션을 조회하지 않는 경로 (2026-08-15 확장).
#
# 예전엔 "/api/auth/" 하나뿐이었다 — 그 밖의 "모든" 요청(정적 CSS·폰트·admin2 화면·
# 관리자 API까지)이 매번 resolve_session()으로 DB를 쳤다. member_middleware가 비동기
# 함수인데 그 안의 DB 호출이 스레드풀 오프로드 없이 직접 돌아, 커넥션 풀이 마르면
# (pool_size=5+max_overflow=10, pool_timeout=30초) 이벤트 루프 전체가 최대 30초
# 멈춘다 — 그 30초 동안은 이 요청만이 아니라 서버의 "모든" 요청이 멈춘다(1코어
# uvicorn 단일 프로세스). 아래 항목은 전부 "고객 회원 세션을 실제로 읽는 코드가
# 있는지" grep으로 확인한 뒤 추가했다(전수: current_member()/require_member() 호출부는
# clicks.py·handoff.py·orders.py·my_account.py·my_payments.py·my_orders.py 여섯 곳뿐이고
# 전부 "/api/..."이며 아래 접두어 어디에도 속하지 않는다 — GUARDED_PREFIX("/api/my/")와도
# 겹치지 않는다).
#
#   /shared/         정적 자산(css·js·폰트·아이콘). mockups/shared/*를 캐치올
#                     StaticFiles가 서빙 — 이 경로를 처리하는 파이썬 라우트가 아예 없다
#                     (grep 확인: "/shared" 를 매칭하는 @router 없음). DB를 칠 코드 자체가 없다.
#   /design-system/   정적 토큰 CSS(design-system/tokens.css) — 마찬가지로 전용
#                     StaticFiles 마운트뿐, 라우트 없음.
#   /admin2/          관리자 화면 셸(Jinja 렌더). api/admin_ui_*.py 19개 전부 grep했고
#                     current_member/require_member 호출 0곳 — 관리자 화면은 고객
#                     세션을 쓰지 않는다.
#   /admin/           구 관리자 화면(P-09 동결: login·my-profile·operators 문·자산)
#                     + 남은 vendor 자산. 마찬가지로 고객 세션 미사용.
#   /api/admin/       관리자 API 전체. api/admin_*.py 전부 grep했고 current_member/
#                     require_member 호출 0곳 — 관리자 게이트(auth.py)가 별도로
#                     세션·권한을 검사하므로 여기서 고객 세션을 조회할 이유가 없다.
#                     ⚠ "/api/admin/auth/*"(관리자 로그인 자체)도 이 접두어에 포함된다 —
#                     장애 복구 중 관리자가 재로그인해야 하는 상황에서 고객 세션 DB
#                     조회가 그 로그인마저 막는 것은 특히 나쁘다.
#
# 위 다섯은 "고객이 접근하는 경로"가 아니다 — 그래서 뺐다. 고객 화면(/mvp1/*)과
# 게스트 허용 API(/api/orders·/api/handoff·/api/promo-click 등)는 그대로 둔다:
# 저 경로들은 current_member()로 "로그인했으면 회원으로, 아니면 게스트로" 붙이는
# 동작이 실제로 쓰이므로 세션 조회를 건너뛰면 안 된다.
OPEN_PREFIXES = (
    "/api/auth/",
    "/shared/",
    "/design-system/",
    "/admin2/",
    "/admin/",
    "/api/admin/",
)


def cookie_secure() -> bool:
    """HTTPS 전용 쿠키 여부 — 환경변수로 켠다(COOKIE_SECURE=1).

    내부 베타는 도메인이 없어 HTTP로 시작한다(사용자 결정 2026-07-26). 그 상태에서 secure를
    켜면 브라우저가 쿠키를 아예 저장하지 않아 로그인이 되지 않는다. 도메인·인증서를 붙이는
    날 이 환경변수만 켜면 되도록 값으로 빼둔다 — 코드를 고치지 않는다.
    """
    return os.environ.get("COOKIE_SECURE", "").strip() in ("1", "true", "True", "yes")


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
            # 동기 DB 호출(engine.begin())을 스레드풀로 넘긴다 — 미들웨어는 항상
            # 이벤트 루프에서 돌아 라우트처럼 자동 오프로드되지 않는다(2026-08-15).
            # resolve_session() 본체는 그대로 두고 부르는 방식만 바꾼다.
            m = await run_in_threadpool(resolve_session, request.cookies.get(COOKIE, ""))
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
        # 방문자 키를 이 회원에 붙인다 — **익명으로 상담하다 가입해도 앞의 행동이 이어진다.**
        # 지연 import: visitor 가 이 모듈의 cookie_secure 를 쓰므로 최상단에 두면 순환이 된다.
        from . import visitor
        visitor.promote(conn, visitor.resolve(conn, request, response), m["member_id"])

        sid = _new_session(conn, m["member_id"], request.headers.get("user-agent"))
        response.set_cookie(COOKIE, sid, httponly=True, samesite="lax", path="/",
                            max_age=ABSOLUTE_DAYS * 24 * 3600, secure=cookie_secure())
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
