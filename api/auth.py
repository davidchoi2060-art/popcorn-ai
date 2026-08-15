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
from starlette.concurrency import run_in_threadpool

from datetime import datetime

from .db import engine
from .passwords import (hash_password,
                        strength_problem, verify_password)

router = APIRouter(prefix="/api/admin/auth")

COOKIE = "popcorn_admin_session"
ABSOLUTE_HOURS = 8      # 절대 만료
IDLE_MINUTES = 30       # 유휴 만료
ROLE_RANK = {"viewer": 1, "operator": 2, "owner": 3}

# 미들웨어가 채우는 현재 운영자 — 시그니처 무변경으로 주체를 전달하는 수단
_current: ContextVar[dict | None] = ContextVar("current_operator", default=None)

# 게이트 예외 — 인증 자체와 정적 파일
OPEN_PREFIXES = ("/api/admin/auth/",)

# admin2 페이지 라우트 접두어 — 아래 `_is_gated`/`auth_middleware` 참조.
ADMIN2_PREFIX = "/admin2"

# `/admin2/*` 안에 있지만 "화면"이 아니라 AJAX가 읽는 "데이터" 엔드포인트 — 거절 응답도
# HTML이 아니라 JSON이어야 한다(2026-08-15, 제작자 신고). `handoff_log.html.j2`의
# 프런트가 `res.clone().json().catch(()=>null)`로 응답을 파싱하는데, 무세션 요청이
# HTML(로그인 안내 페이지)을 받으면 파싱이 조용히 null이 되어 "오류 401"로만 뭉개진다
# (크래시는 아니지만 실패 사유가 지워진다). AJAX에는 화면과 같은 이유로 JSON을 줘야
# 프런트가 실패 사유를 읽을 수 있다.
#
# 실측(2026-08-15, `admin_ui_handoff_log.py` 본문·나머지 `admin_ui_*.py` 라우트 대조):
# `/admin2` 아래 데이터 엔드포인트는 `/admin2/handoff-log/data` 하나뿐이다 — 나머지
# admin2 화면의 데이터 API는 전부 `/api/admin/...`(이미 `_is_gated`가 JSON으로 막는
# 경로)에 있다. 하나뿐이므로 **규칙**("경로 끝이 `/data`" 등)이 아니라 **명시적 예외
# 목록**으로 좁힌다 — 규칙으로 잡으면 다음에 생기는 진짜 "화면" 라우트가 우연히
# `/data`로 끝날 때 자동으로 걸려 그 화면이 HTML 대신 JSON을 받는다(그게 더 나쁘다 —
# 화면이 로그인 안내 대신 JSON 텍스트를 그대로 보여준다). 새 admin2 데이터 엔드포인트를
# 만들 때는 가능하면 `/api/admin/*` 아래 두는 쪽을 먼저 검토하고(그러면 이 목록에 넣을
# 필요가 없다), 불가피하면 여기 추가한다.
ADMIN2_JSON_DATA_PATHS = ("/admin2/handoff-log/data",)


def _is_admin2_path(path: str) -> bool:
    """이 요청이 `/admin2/*` 아래(화면이든 `ADMIN2_JSON_DATA_PATHS`의 데이터 엔드포인트든
    전부)인가 — **게이트 대상** 판정(`_is_gated`) 전용. 거절 «형식»(HTML/JSON)은 건드리지
    않는다 — 그건 `_is_admin2_page()`가 별도로 고른다. 이 함수와 그 함수를 하나로 합치면
    안 된다: 데이터 엔드포인트를 형식 판정에서 빼면서 게이트 판정에서도 같이 빠져
    미들웨어가 그 경로를 아예 통과시켜 버리는(=자체 게이트에만 의존하게 되는) 사고가
    난다(2026-08-15, 이 파일을 고치며 자체 발견 — 처음에 `_is_admin2_page` 하나로
    두 질문을 다 답하다가 `_is_gated`가 덩달아 False가 되는 것을 새 인터프리터로
    재현해서 잡았다).

    admin2 라우터는 `prefix="/admin2"` + `@router.get("")`/`@router.get("/")`로
    등록돼(`admin_ui_home.py` 실측) `/admin2`(슬래시 없음)와 `/admin2/`(있음) 둘 다
    유효한 경로다 — `startswith("/admin2/")`만으로는 슬래시 없는 루트를 놓친다.
    """
    return path == ADMIN2_PREFIX or path.startswith(ADMIN2_PREFIX + "/")


def _is_admin2_page(path: str) -> bool:
    """이 요청이 `/admin2/*` "화면" 라우트인가 — **거절 응답 형식**(HTML vs JSON) 분기
    전용. 게이트 대상 여부는 이 함수가 아니라 `_is_admin2_path()`/`_is_gated()`가 정한다
    (위 `_is_admin2_path` 참조 — 이 둘을 합치면 안 되는 이유가 거기 있다).

    화면이면 True(HTML 거절) · `ADMIN2_JSON_DATA_PATHS`에 있는 데이터 엔드포인트면
    False(JSON 거절, 위 주석 참조) — **그 경로도 계속 게이트된다**: `_is_gated()`는
    `_is_admin2_path()`를 보므로 세션이 없으면 미들웨어가 여전히 401을 (이번엔 JSON으로)
    돌려준다. "게이트를 푸는" 함수가 아니라 "거절 문서를 뭘로 줄지"만 고르는 함수다.
    """
    if path in ADMIN2_JSON_DATA_PATHS:
        return False
    return _is_admin2_path(path)


def _is_gated(path: str) -> bool:
    """인증 게이트 대상 경로인가 — `/api/admin/*`(2026-07-26부터) + `/admin2/*`
    (2026-08-15부터, 아래 참조).

    2026-08-15까지는 `/api/admin/*`만이었다. 그런데 `admin_ui_reprice.py`·
    `admin_ui_margin_policy.py`·`admin_ui_mall_sync.py` 세 화면이 `admin_ui_home.py`
    와 같은 방식(서버 렌더 시점에 실데이터를 페이지 셸에 직접 싣는다)이면서
    **자체 로그인 게이트가 없어서**, 무세션으로 열면 회차·정책·인계 실데이터가 그대로
    나갔다(조사자 실측, 2026-08-15 — 응답 전수를 개인정보 패턴으로 스캔해 고객
    개인정보는 0건이었지만 운영 내부 사실·집계가 새고 있었다). 화면마다 자체 게이트를
    추가하는 대신(반복이고, 실제로 셋이 빠뜨렸다) 여기 한 곳에서 `/admin2/*` 전체를
    막는다 — 새 `/admin2/*` 화면은 짓는 사람이 잊어도 자동으로 보호된다.
    `admin_ui_home.py`·`admin_ui_handoff_log.py`의 자체 게이트는 지우지 않았다
    (이중 방어는 해가 없다 — 각 파일 참조).

    **`_is_admin2_page()`가 아니라 `_is_admin2_path()`를 쓴다** — `/admin2/handoff-log/data`
    처럼 거절 형식만 JSON으로 다른 경로도 게이트 대상에서 빠지면 안 되기 때문이다.
    """
    return path.startswith("/api/admin/") or _is_admin2_path(path)


def cookie_secure() -> bool:
    """HTTPS 전용 쿠키 여부 — 환경변수로 켠다(COOKIE_SECURE=1).

    내부 베타는 도메인이 없어 HTTP로 시작한다(사용자 결정 2026-07-26). 그 상태에서 secure를
    켜면 브라우저가 쿠키를 아예 저장하지 않아 로그인이 되지 않는다. 도메인·인증서를 붙이는
    날 이 환경변수만 켜면 되도록 값으로 빼둔다 — 코드를 고치지 않는다.
    """
    return os.environ.get("COOKIE_SECURE", "").strip() in ("1", "true", "True", "yes")


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


# 정책 발행급 쓰기 — 운영자 관리와 운영 모드 전환은 owner만.
# 운영 모드는 주문·결제 흐름을 실제로 바꾼다(pay='mall'이면 자체 주문이 409로 거부된다).
# 카탈로그 일괄 적재도 owner다(슬라이스 50): 파일 하나가 22,000건 정본을 덮고,
# upsert이라 되돌릴 수단이 없다 — 운영자 등급에게 열 수 있는 일이 아니다.
OWNER_WRITE_PREFIXES = ("/api/admin/operators", "/api/admin/ops-settings",
                        "/api/admin/catalog-import",
                        # 사양 항목 추가는 스키마를 바꾼다 — owner만(슬라이스 56)
                        "/api/admin/spec-fields",
                        # 용도 하한·마진은 견적과 가격을 직접 바꾼다 — owner만(슬라이스 74·75)
                        "/api/admin/usage-floors",
                        "/api/admin/pricing-settings",
                        "/api/admin/category-margins",
                        # AI 관리 3화면 — 배정·연동 한도·FAQ 저장은 정책 발행급 쓰기다.
                        # 각 모듈이 자체 _owner() 이중 가드를 갖고 있었고(등록 전 방어),
                        # 여기 등록으로 미들웨어가 먼저 막는다 — 같은 판정이라 충돌 없음.
                        "/api/admin/ai-task-settings",
                        "/api/admin/ai-integration",
                        "/api/admin/ops-assistant")


def required_role(method: str, path: str) -> str:
    """경로·메서드별 최소 권한 — 읽기 viewer / 쓰기 operator / 운영자·정책 owner."""
    # 내 정보(ADM-SYS-030)는 **자기 것만** 다루므로 쓰기도 viewer로 연다(슬라이스 92).
    # 조회 등급 직원도 자기 이름·연락처는 고칠 수 있어야 한다. 권한 상승은 등급이 아니라
    # `admin_profile.EDITABLE` 화이트리스트가 막는다 — role·status·email은 아예 못 보낸다.
    # `/operators`보다 **먼저** 검사한다: 아래 owner 규칙이 접두어로 걸리지 않게.
    if path.startswith("/api/admin/my-profile"):
        return "viewer"
    if path.startswith("/api/admin/operators"):
        return "owner"                      # 조회조차 owner(계정 목록은 민감)
    if path.startswith(OWNER_WRITE_PREFIXES) and method not in ("GET", "HEAD", "OPTIONS"):
        return "owner"
    return "viewer" if method in ("GET", "HEAD", "OPTIONS") else "operator"


async def auth_middleware(request: Request, call_next):
    """`/api/admin/*` + `/admin2/*` 게이트(§`_is_gated`). 예외는 인증 엔드포인트뿐 —
    승인 전에는 어떤 데이터도 주지 않는다.

    거절 응답은 **경로로 형식을 가른다**(2026-08-15): `/api/admin/*`는 그대로 JSON
    (기존 화면 스크립트가 그 형식을 읽으므로 바꾸지 않는다) · `/admin2/*`는 브라우저가
    주소창으로 직접 여는 페이지라 HTML 안내로 로그인 화면으로 보낸다
    (`admin_ui_common.login_required_html()` — `admin_ui_home.py`가 쓰던 것을 그리로
    옮겨 여기서도 같이 쓴다. 단일 원천, 복제하지 않는다 — `admin_ui_home.py` 모듈
    docstring 「2026-08-15 정정」 절 참조).
    **예외 하나**: `/admin2/*` 안에도 화면이 아니라 AJAX가 읽는 데이터 엔드포인트가
    하나 있다(`ADMIN2_JSON_DATA_PATHS` — 지금은 `/admin2/handoff-log/data`뿐).
    그 경로는 **게이트는 그대로 받되**(무세션이면 여전히 401) 거절 문서만 JSON이다 —
    `is_page`(아래) 판정을 `_is_admin2_page()`가 홀로 진다.
    """
    path = request.url.path
    token = _current.set(None)
    try:
        if _is_gated(path) and not path.startswith(OPEN_PREFIXES):
            is_page = _is_admin2_page(path)
            # 동기 DB 호출을 스레드풀로 넘긴다 — 미들웨어는 항상 이벤트 루프에서
            # 돌아 라우트처럼 자동 오프로드되지 않는다(2026-08-15). resolve_session()
            # 본체는 그대로 두고 부르는 방식만 바꾼다.
            op = await run_in_threadpool(resolve_session, request.cookies.get(COOKIE, ""))
            if op is None:
                if is_page:
                    from fastapi.responses import HTMLResponse

                    from .admin_ui_common import login_required_html
                    return HTMLResponse(login_required_html(), status_code=401)
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "로그인이 필요합니다"}, status_code=401)
            need = required_role(request.method, path)
            if ROLE_RANK.get(op["role"], 0) < ROLE_RANK[need]:
                if is_page:
                    from fastapi.responses import HTMLResponse

                    from .admin_ui_common import login_required_html
                    return HTMLResponse(login_required_html(), status_code=403)
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
    password: str | None = None  # 활성 계정은 필수(슬라이스 70) — 신청 단계에서는 없다
    name: str | None = None
    provider: str = "dev"        # dev | google — 구글 연동 시 id_token 검증으로 교체
    phone: str | None = None
    duty: str | None = None


# 무차별 대입 방어 — fail2ban이 없으므로 앱에서 막는다.
# 계정 잠금은 그 계정만 막고 IP는 막지 않는다(공유 IP에서 남의 작업을 끊지 않게).
MAX_FAILS = 5
LOCK_MINUTES = 15


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
                response.set_cookie(COOKIE, sid, httponly=True, samesite="lax", path="/",
                                    secure=cookie_secure())
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

        # ── 비밀번호 검증 (슬라이스 70) ──────────────────────────────
        # 예전에는 이메일만 맞으면 들여보냈다(dev 어댑터). 그래서 nginx Basic Auth가
        # 유일한 방벽이었고, 그 팝업이 모바일에서 불편했다. 이제 앱이 직접 확인한다.
        op_id, op_name = op["operator_id"], op["name"]
        op_email, op_role = op["email"], op["role"]
        # 잠금 판정은 **DB가 한다**. datetime.now()는 서버 로컬(KST)이고 DB는 UTC라
        # 파이썬에서 비교하면 9시간 어긋나 잠금이 통째로 무시된다(슬라이스 62 전례).
        st = conn.execute(text(
            "SELECT password_hash, must_change_password, login_fail_count,"
            " (locked_until IS NOT NULL AND locked_until > now()) AS is_locked,"
            " GREATEST(0, CEIL(EXTRACT(EPOCH FROM (locked_until - now())) / 60))"
            "   AS lock_min"
            " FROM admin_operators WHERE operator_id=:i FOR UPDATE"),
            {"i": op["operator_id"]}).mappings().first()
        if not st["password_hash"]:
            # 비밀번호가 없는 계정은 **들어올 수 없다** — 자동 발급은 곧 뒷문이다
            raise HTTPException(403, {
                "error": "password_not_set",
                "message": "비밀번호가 아직 설정되지 않았습니다 — 관리자에게 발급을 요청하세요"})
        if st["is_locked"]:
            left = int(st["lock_min"] or 1)
            raise HTTPException(429, {
                "error": "locked",
                "message": f"로그인 시도가 많아 잠겼습니다 — {left}분 뒤에 다시 시도하세요"})
        # 실패는 여기서 **판정만** 한다. 이 블록 안에서 예외를 던지면 트랜잭션이
        # 통째로 되감겨 실패 기록까지 사라진다 — 그러면 아무리 시도해도 잠기지 않는다.
        bad_pw = not verify_password(body.password or "", st["password_hash"])
        if bad_pw:
            fails = (st["login_fail_count"] or 0) + 1
        else:
            must_change = bool(st["must_change_password"])
            conn.execute(text(
                "UPDATE admin_operators SET login_fail_count=0, locked_until=NULL,"
                " last_login_at=now() WHERE operator_id=:i"), {"i": op["operator_id"]})

    if bad_pw:
        lock = fails >= MAX_FAILS
        # 기록은 **성공한 트랜잭션**으로 남긴다(예외 밖)
        with engine.begin() as conn2:
            conn2.execute(text(
                "UPDATE admin_operators SET login_fail_count=:f,"
                " locked_until = CASE WHEN :lk THEN now() + (:m || ' minutes')::interval"
                "                     ELSE locked_until END"
                " WHERE operator_id=:i"),
                {"f": 0 if lock else fails, "lk": lock, "m": str(LOCK_MINUTES),
                 "i": op_id})
        # 어느 쪽이 틀렸는지 말하지 않는다 — 계정 존재 여부가 새어 나간다
        raise HTTPException(401, {
            "error": "bad_credentials",
            "message": ("이메일 또는 비밀번호가 올바르지 않습니다"
                        + (f" — {LOCK_MINUTES}분간 잠겼습니다" if lock else
                           f" (남은 시도 {max(0, MAX_FAILS - fails)}회)"))})

    with engine.begin() as conn:
        sid = _new_session(conn, op_id, request.headers.get("user-agent"))
        response.set_cookie(COOKIE, sid, httponly=True, samesite="lax", path="/",
                                    secure=cookie_secure())
        return {"state": "active", "operator": {"id": op_id, "name": op_name,
                "email": op_email, "role": op_role},
                "must_change_password": must_change}


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


# ---- 슬라이스 70: 비밀번호 발급·변경 ----
# 원문은 이 파일에서도 저장·기록하지 않는다. 해시만 DB로 간다.


class SetPasswordBody(BaseModel):
    current: str | None = None      # 본인 변경일 때 필요
    new: str


@router.get("/password-policy")
def password_policy():
    """강도 규칙 — 화면이 **거절당하기 전에** 보여주기 위한 것(슬라이스 100).

    규칙 문구는 `passwords.password_rules()`가 만든다. 판정(`strength_problem`)과
    같은 파일이라 어긋나지 않는다 — 화면이 베껴 쓰면 MIN_LENGTH를 올린 날 거짓이 된다.
    """
    from .passwords import password_rules
    return password_rules()


@router.post("/password")
def change_my_password(body: SetPasswordBody, request: Request):
    """본인 비밀번호 변경. 현재 비밀번호를 확인한다."""
    op = resolve_session(request.cookies.get(COOKIE, ""))
    if op is None:
        raise HTTPException(401, "로그인이 필요합니다")
    with engine.begin() as conn:
        cur = conn.execute(text(
            "SELECT email, password_hash FROM admin_operators WHERE operator_id=:i"
            " FOR UPDATE"), {"i": op["operator_id"]}).mappings().first()
        if cur["password_hash"] and not verify_password(body.current or "",
                                                        cur["password_hash"]):
            raise HTTPException(401, "현재 비밀번호가 올바르지 않습니다")
        bad = strength_problem(body.new, cur["email"])
        if bad:
            raise HTTPException(400, bad)
        if cur["password_hash"] and verify_password(body.new, cur["password_hash"]):
            raise HTTPException(400, "이전과 다른 비밀번호를 쓰세요")
        conn.execute(text(
            "UPDATE admin_operators SET password_hash=:h, password_set_at=now(),"
            " must_change_password=false, login_fail_count=0, locked_until=NULL"
            " WHERE operator_id=:i"),
            {"h": hash_password(body.new), "i": op["operator_id"]})
        # 다른 기기의 세션은 끊는다 — 비밀번호를 바꾼 이유가 유출일 수 있다
        conn.execute(text(
            "UPDATE admin_sessions SET revoked_at=now()"
            " WHERE operator_id=:i AND revoked_at IS NULL"
            "   AND session_id <> :s"),
            {"i": op["operator_id"], "s": request.cookies.get(COOKIE, "")})
    return {"ok": True, "note": "비밀번호를 바꿨습니다. 다른 기기의 로그인은 해제됐습니다."}


class IssuePasswordBody(BaseModel):
    password: str


@router.post("/operators/{operator_id}/password")
def issue_password(operator_id: int, body: IssuePasswordBody, request: Request):
    """owner가 임시 비밀번호를 발급한다 — 받은 사람은 최초 로그인에서 바꿔야 한다."""
    op = resolve_session(request.cookies.get(COOKIE, ""))
    if op is None or op.get("role") != "owner":
        raise HTTPException(403, "관리자(owner)만 발급할 수 있습니다")
    with engine.begin() as conn:
        target = conn.execute(text(
            "SELECT email, name FROM admin_operators WHERE operator_id=:i"),
            {"i": operator_id}).mappings().first()
        if target is None:
            raise HTTPException(404, "운영자가 없습니다")
        bad = strength_problem(body.password, target["email"])
        if bad:
            raise HTTPException(400, bad)
        conn.execute(text(
            "UPDATE admin_operators SET password_hash=:h, password_set_at=now(),"
            " must_change_password=true, login_fail_count=0, locked_until=NULL"
            " WHERE operator_id=:i"),
            {"h": hash_password(body.password), "i": operator_id})
    # 발급한 비밀번호를 응답에 되돌려 주지 않는다 — 로그·화면에 남는다
    return {"ok": True, "operator": target["name"],
            "note": f"{target['name']} 님의 임시 비밀번호를 발급했습니다."
                    " 본인이 최초 로그인에서 바꿔야 합니다."}


# ── 개발 전용: 화면 점검용 세션 심기 (슬라이스 · 2026-08-11) ───────────────────
#
# ■ 왜 필요한가
#   운영자 화면을 브라우저로 열어 확인하려면 세션이 필요한데, 세션 쿠키가 `HttpOnly`라
#   **서버가 심어야** 한다. 그러면 로그인 요청을 브라우저 안에서 보내야 하고
#   **그때 비밀번호가 기록에 남는다**(CLAUDE.md 「브라우저 점검 계정」이 적어 둔 문제).
#   이 엔드포인트는 서버가 `.env` 에서 직접 읽어 세션만 심는다 —
#   **비밀번호가 요청에도, 응답에도, 화면에도 나오지 않는다.**
#
# ■ 이게 열리면 누구나 관리자가 된다. 그래서 셋을 동시에 건다:
#     ① `.env` 의 `UI_CHECK_DEV_LOGIN=1` (기본 꺼짐)
#     ② **localhost 요청만** — 원격에서는 스위치가 켜져 있어도 거부
#     ③ `UI_CHECK_EMAIL` 계정이 실제로 활성일 때만
#   회귀가 「운영에서 꺼져 있는가」를 검사한다.
#
# ■ 로그인 이력을 남긴다 — 검사가 흔적 없이 지나가면 나중에 구분할 수 없다
#   (슬라이스 78 전례: 검증이 만든 계정이 운영 목록에 남았다).

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


def dev_login_enabled() -> bool:
    return os.environ.get("UI_CHECK_DEV_LOGIN", "").strip() in ("1", "true", "True", "yes")


@router.get("/dev-login")
def dev_login(request: Request, response: Response):
    """점검 계정으로 세션만 심는다. **개발 서버·localhost 전용.**"""
    if not dev_login_enabled():
        raise HTTPException(404, "사용할 수 없습니다")
    host = (request.client.host if request.client else "") or ""
    if host not in LOCAL_HOSTS:
        # 어디서 왔는지는 남기되 그 이상은 말하지 않는다
        raise HTTPException(403, "로컬에서만 사용할 수 있습니다")
    email = os.environ.get("UI_CHECK_EMAIL", "").strip().lower()
    if not email:
        raise HTTPException(500, "UI_CHECK_EMAIL 이 설정돼 있지 않습니다")

    with engine.begin() as conn:
        op = conn.execute(text(
            "SELECT operator_id, name, role, status FROM admin_operators"
            " WHERE lower(email)=:e"), {"e": email}).mappings().first()
        if op is None:
            raise HTTPException(404, "점검 계정이 없습니다 — tools/ui_check_account.py 를 실행하십시오")
        if op["status"] != "활성":
            # 상태가 한글 '활성'이 아니면 resolve_session 이 세션을 버린다(실제로 겪었다)
            raise HTTPException(403, f"점검 계정이 활성이 아닙니다: {op['status']}")
        sid = _new_session(conn, op["operator_id"], request.headers.get("user-agent"))

    response.set_cookie(COOKIE, sid, httponly=True, samesite="lax", path="/",
                        secure=cookie_secure())
    return {"ok": True, "operator": {"id": op["operator_id"], "name": op["name"],
                                     "role": op["role"]},
            "note": "화면 점검용 세션을 심었습니다(개발 서버 전용). "
                    "끄려면 .env 의 UI_CHECK_DEV_LOGIN 을 지우십시오."}
