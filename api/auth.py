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
import ipaddress
import os
import secrets
from contextvars import ContextVar

from fastapi import APIRouter, Depends, HTTPException, Request, Response
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
# 유휴 만료 — 2026-08-15 사장님 지시로 30 → 480(=8시간)으로 올렸다.
# **사실상 위 ABSOLUTE_HOURS와 같은 값이 됐다** — 그 결과 유휴 만료가 절대 만료보다
# 먼저 세션을 끊는 일은 거의 없어지고, 사실상 절대 만료(하루 근무 시간)만 남는다.
# 이게 사장님 뜻이다("하루 일하다 퇴근하면 끝").
#
# 근거(조사자 실측 2026-08-15): admin_sessions 전체 1,485건 중 그 시점에 "유효"한
# 세션은 0건이었다. 실브라우저 owner 세션들은 철회 이력 없이 전부 30분 유휴로만
# 끊겨 있었다(예: 로그인 11:35 → 마지막 활동 13:52 → 유휴 58분). "비밀번호를 자주
# 다시 친다"와 "화면을 보다 401이 뜬다"는 서로 다른 신고였지만 원인은 이 하나였다.
# 회귀 탓이 아니었다 — session_revoke_others 기록은 전부 시드 계정(operator_id=1)
# 에서만 났고, 그 계정은 7월 28일 이후 사람이 브라우저로 로그인한 적이 없다.
#
# 값을 올리면 이미 유휴로 끊긴(그러나 절대 만료 전인) 세션이 다음 조회부터 다시
# 유효해진다 — resolve_session()의 idle 판정이 조회 시점 계산이라 그렇다(실측:
# 활성 계정 기준 "idle 30분 이내 + 절대만료 전" 10건 → "idle 480분 이내 + 절대만료
# 전" 40건, 2026-08-15). **절대 만료(ABSOLUTE_HOURS)는 이 값과 무관하게 그대로
# 걸린다** — 로그인 후 8시간이 지난 세션은 여전히 무효다. 같은 브라우저를 근무
# 시간 안에 다른 사람이 이어 쓸 수 있다는 위험은 남지만, 그건 "유휴 만료를 8시간
# 근무 시간만큼 늘려 달라"는 요청 자체가 감수하기로 한 몫이다(사장님 확정).
IDLE_MINUTES = 480      # 유휴 만료 (2026-08-15까지 30이었다 — 위 참조)
ROLE_RANK = {"viewer": 1, "operator": 2, "owner": 3}

# ── 기기 기억(device trust) — 2026-08-15 사장님 지시 ──────────────────────
# "이 기기에서 로그인 유지": 비밀번호를 매번 치지 않되, 신원은 계정에 그대로
# 묶고(①) 비밀번호 자체만 생략하며(②) 철회할 수 있고(③) 민감한 쓰기는 다시
# 확인한다(④). 스키마·설계 근거는 db/migrations/versions/0051_admin_operator_devices.py
# 참조. 쿠키 이름을 세션(COOKIE)과 분리한다 — 하나는 최대 8시간짜리 로그인,
# 하나는 최대 30일짜리 "이 브라우저를 안다"이고 성격이 다르다.
DEVICE_COOKIE = "popcorn_admin_device"
REMEMBER_DEVICE_DAYS = 30      # 상수로 뺀다 — 나중에 바꾸기 쉽게(사장님 지시)

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

# `/admin2/*` 안에서 게이트를 **면제**하는 경로 — 2026-08-17 신설(사장님 확정, A-44).
#
# ■ 왜 필요한가 — 순환
#   `_is_gated()`가 `/admin2` 전체를 게이트 대상으로 보므로, 로그인 화면(ADM-SYS-021 ·
#   `/admin2/login` · `api/admin_ui_login.py`)도 무세션이면 401을 받는다. **로그인하려는
#   사람이 로그인 화면에 못 들어오는 순환**이라 이 한 경로만 예외로 연다.
#
# ■ 왜 «접두어»가 아니라 «완전 일치 집합»인가
#   `path.startswith("/admin2/login")`으로 열면 `/admin2/login-xxx`·`/admin2/loginsecret`
#   처럼 **뒤에 무엇이든 붙은 경로가 함께 열린다**. 지금은 그런 라우트가 없지만, 여는 쪽의
#   실수는 «없는 화면이 404가 되는» 것으로 끝나지 않는다 — 나중에 누가 `/admin2/login-audit`
#   같은 화면을 만들면 그 화면이 **아무 표시 없이 무세션으로 열린다**(짓는 사람은 이 파일을
#   읽을 이유가 없다). `in` 판정이라 그 위험이 구조적으로 사라진다.
#   ⚠ 2026-08-15에 정확히 반대 방향의 사고가 있었다(서버 렌더 화면 3종이 자체 게이트 없이
#   실데이터를 흘렸다, 커밋 `7ccb68d`) — 이번은 그 반대다: **예외가 넓으면 다른 화면이
#   무세션으로 열린다.** 그래서 이 집합은 «늘리기 어렵게» 두는 것이 목적이다.
#
# ■ 끝 슬래시(`/admin2/login/`)는 **넣지 않는다**
#   실제 라우트는 `/admin2/login` 하나다(`api/admin_ui_login.py` — `prefix="/admin2"` +
#   `@router.get("/login")`). `/admin2/login/`은 우리 라우트가 아니라 Starlette의
#   `redirect_slashes` 편의가 307로 되돌려 줄 뿐인 **다른 문자열**이고, 미들웨어는 라우팅보다
#   먼저 돌기 때문에 그 리다이렉트를 기다려 주지도 않는다. 즉 넣지 않으면 그 경로는 401이고,
#   넣으면 **같은 화면을 여는 문자열이 둘**이 된다(면제 대상이 하나라는 사실을 다음 사람이
#   두 번 확인해야 한다). 게이트에 걸린 사람을 보내는 목적지(`admin_ui_common._LOGIN_PAGE`,
#   전환 예정)도 슬래시 없는 형태를 쓰므로 **열어야 할 문자열은 하나로 족하다.**
#
# ■ 메서드를 가리지 않는다
#   `GET`만 열지 않고 경로 단위로 면제한다 — `/admin2/login`에 등록된 라우트는 GET 하나뿐이라
#   다른 메서드는 라우터가 405로 거절한다. 여기서 메서드까지 따지면 «게이트 대상인가»만
#   답하던 `_is_gated()`의 계약이 넓어진다(그 함수는 경로만 받는다).
#
# ⚠ **이 집합에 무엇을 더하는 것은 인증 경계를 넓히는 일이다.** 화면이 서버 렌더로 데이터를
#   싣지 않는지, 그 화면이 부르는 API가 `/api/admin/*`(여전히 게이트된다)인지 먼저 확인한다.
#
# ■ 항목을 더할 때 «반드시» 함께 할 것 — 감사 호출 (이 파일 맨 아래)
#   `_audit_admin2_open_paths()`가 항목의 «모양»을 이 파일 가져오기 시점에 검사하고,
#   `_audit_admin2_open_routes(router)`가 그 경로의 «메서드»를 검사한다. 후자는 라우트를
#   봐야 하므로 **경로를 소유한 모듈이 자기 맨 아래에서 부른다**(지금은
#   `api/admin_ui_login.py`). 새 면제 경로를 만들면 그 모듈에도 같은 한 줄을 넣어라 —
#   빠뜨리면 그 모듈은 검사되지 않는다(두 함수의 docstring 참조).
ADMIN2_OPEN_PATHS = frozenset({"/admin2/login"})


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

    **면제는 `ADMIN2_OPEN_PATHS`(완전 일치) 하나뿐이다** — 지금은 로그인 화면
    `/admin2/login` 이고, 근거·범위·왜 접두어가 아닌지는 그 상수 위 주석에 있다
    (2026-08-17 신설). 판정을 **여기 한 곳**에서 하는 이유는 위와 같다: 미들웨어가
    아니라 이 함수가 「게이트 대상인가」의 단일 원천이라, 나중에 다른 곳에서
    `_is_gated()`를 부르게 되어도 면제가 함께 따라간다.
    ⚠ 이 면제가 `/api/admin/*`에는 닿지 않는다 — `ADMIN2_OPEN_PATHS`의 문자열이
    `/admin2/`로 시작하므로 `/api/admin/...`과는 어떤 경우에도 같아질 수 없다.
    """
    if path in ADMIN2_OPEN_PATHS:
        return False
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


def _client_ip(request: Request) -> str | None:
    """접속 IP — **기록만** 한다(차단 아님, 2026-08-15 사장님 확정). `login_ip`
    (마이그레이션 0049 · admin_sessions, inet)에 담을 값을 고른다.

    ■ 왜 `request.client.host`를 그대로 쓰고 `X-Forwarded-For`를 직접 읽지 않는가
    운영 배포(`deploy/popcorn-api.service`)는 uvicorn을
    `--proxy-headers --forwarded-allow-ips=127.0.0.1`로 띄운다. nginx
    (`deploy/nginx-popcorn.conf:74-76`)는 앱에 127.0.0.1로 접속하며
    `X-Real-IP`·`X-Forwarded-For`·`X-Forwarded-Proto`를 실어 보낸다. uvicorn의
    `ProxyHeadersMiddleware`(신뢰 목록이 127.0.0.1 하나뿐)가 그 조합을 보고
    **직접 접속한 피어가 신뢰 목록에 있을 때만** `X-Forwarded-For`를 검증해
    `request.client.host`를 실제 클라이언트 IP로 이미 바꿔 둔다(실측:
    `.venv/Lib/site-packages/uvicorn/middleware/proxy_headers.py`). 즉 배포
    환경에서는 이 값이 이미 "프록시를 신뢰해 걸러낸" 클라이언트 IP다 — 여기서
    `X-Forwarded-For`를 또 읽으면 그 검증을 우회해 **클라이언트가 헤더를 위조한
    값을 그대로 믿는** 중복·퇴행이 된다.
    로컬 개발 서버(`.claude/launch.json` — `--proxy-headers` 없음)는 프록시가
    없어 이 값이 곧 TCP 접속지 그 자체다 — dev-login의 로컬 판정(아래
    `dev_login()`)이 이미 같은 값으로 "127.0.0.1"을 실측해 왔다.

    ■ 못 알아내도, 형식이 안 맞아도 **NULL** — 로그인을 막지 않는다
    `login_ip`는 `inet` 타입이라 형식이 안 맞는 문자열은 INSERT 자체가 실패한다.
    `request.client`가 없거나(테스트 클라이언트 등) 값이 유효한 IP 리터럴이
    아니면(`LOCAL_HOSTS`의 방어적 문자열 "localhost"처럼 실제로는 안 나오지만
    구조상 가능한 값 포함) 조용히 None을 돌려준다 — 그 필드만 비고 로그인
    자체는 그대로 진행된다.
    """
    host = (request.client.host if request.client else "") or ""
    if not host:
        return None
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return None
    return host


_device_trust_ready: bool | None = None    # 프로세스 수명 동안 캐싱 — 아래 참조


def _schema_ready() -> bool:
    """마이그레이션 0051(admin_operator_devices · admin_sessions.password_verified)이
    이 DB에 실제로 적용됐는가.

    **왜 이 함수가 필요한가**: 이 마이그레이션은 작성 시점(2026-08-15)에 DB에
    적용하지 못했다 — 하네스 권한 분류기가 공유 Cloud SQL에 대한 DDL 실행을
    막았다(CLAUDE.md 「.env 의 DATABASE_URL 이 Cloud SQL 이라 로컬과 배포가 DB 를
    공유한다」와 같은 이유로 신중한 게 맞다). `resolve_session()`은 **모든**
    `/api/admin/*`·`/admin2/*` 요청이 지나는 자리라, 여기서 없는 컬럼을
    무조건 SELECT하면 마이그레이션 적용 전에 이 코드가 배포되는 순간 로그인
    전체가 500으로 죽는다("인증이 깨지면 아무도 못 들어온다"). 그래서
    마이그레이션 0046(ai_task_assignments)이 쓴 것과 같은 방식 — **미적용
    상태에서도 죽지 않고 기능만 꺼진다** — 을 로그인의 핵심 경로에도 적용한다.

    결과를 프로세스 안에서 캐싱한다 — 매 요청마다 information_schema를 또
    조회하면 그 자체가 로그인 경로에 쿼리 하나를 더 얹는 것이다(스키마는
    이 프로세스가 떠 있는 동안 바뀌지 않는다 — 마이그레이션은 항상 재배포로
    적용된다).
    """
    global _device_trust_ready
    if _device_trust_ready is None:
        with engine.connect() as conn:
            _device_trust_ready = bool(conn.execute(text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns"
                "  WHERE table_name='admin_sessions' AND column_name='password_verified')"
                " AND EXISTS (SELECT 1 FROM information_schema.tables"
                "  WHERE table_name='admin_operator_devices')"
            )).scalar())
    return _device_trust_ready


def _new_session(conn, operator_id: int, ua: str | None, ip: str | None = None,
                 password_verified: bool = True) -> str:
    sid = secrets.token_hex(32)
    params = {"s": sid, "o": operator_id, "h": ABSOLUTE_HOURS,
             "ua": (ua or "")[:300], "ip": ip}
    if _schema_ready():
        # password_verified 컬럼이 실제로 있을 때만 심는다 — 마이그레이션 0051
        # 미적용 상태에서 이 컬럼을 INSERT에 넣으면 "column does not exist"로
        # 로그인 전체가 죽는다(위 _schema_ready 참조).
        params["pv"] = password_verified
        conn.execute(text(
            "INSERT INTO admin_sessions"
            " (session_id, operator_id, expires_at, user_agent, login_ip, password_verified)"
            " VALUES (:s, :o, now() + :h * interval '1 hour', :ua, :ip, :pv)"), params)
    else:
        conn.execute(text(
            "INSERT INTO admin_sessions (session_id, operator_id, expires_at, user_agent, login_ip)"
            " VALUES (:s, :o, now() + :h * interval '1 hour', :ua, :ip)"), params)
    conn.execute(text(
        "UPDATE admin_operators SET last_login_at=now() WHERE operator_id=:o"),
        {"o": operator_id})
    return sid


def resolve_session(sid: str) -> dict | None:
    """세션 검증 + 유휴 갱신. 만료·유휴·정지·철회면 None.

    시각 비교는 **전부 DB의 now()** 로 한다 — 파이썬 로컬시각(KST)과 DB 시각(UTC)을
    비교하면 방금 만든 세션도 만료로 오판한다(실제로 겪은 함정).

    반환 dict의 `password_verified`는 마이그레이션 0051이 적용됐을 때만 실제
    컬럼값이고, 미적용이면 True로 채운다(그 스키마가 없다는 것은 device-login이
    아직 아무 세션도 만들 수 없었다는 뜻이므로 True가 사실과 다르지 않다 —
    위 `_schema_ready()` 참조. 이 요청마다 실행되는 함수라 여기서도 컬럼을
    무조건 SELECT하면 안 된다).
    """
    if not sid:
        return None
    ready = _schema_ready()
    pv_col = ", s.password_verified" if ready else ""
    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT s.operator_id, o.name, o.email, o.role, o.status" + pv_col + ","
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
                "email": row["email"], "role": row["role"], "status": row["status"],
                "password_verified": bool(row["password_verified"]) if ready else True}


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


def _is_operator_photo_path(path: str) -> bool:
    """`/api/admin/operators/{정수}/photo` 정확히 그것인가.

    접두어(`startswith`)로 판정하지 «않는다» — `/operators/1/photo-and-role` 같은
    경로가 생기면 함께 열려 버린다. 정규식 대신 조각을 세는 이유는 이 파일이 `re`를
    쓰지 않기 때문이고(의존 하나를 늘리지 않는다), 조각 판정이 눈으로 읽기 쉽다.
    """
    parts = path.split("/")
    #      ['', 'api', 'admin', 'operators', '<id>', 'photo']
    return (len(parts) == 6 and parts[1] == "api" and parts[2] == "admin"
            and parts[3] == "operators" and parts[4].isdigit() and parts[5] == "photo")


def required_role(method: str, path: str) -> str:
    """경로·메서드별 최소 권한 — 읽기 viewer / 쓰기 operator / 운영자·정책 owner."""
    # 내 정보(ADM-SYS-030)는 **자기 것만** 다루므로 쓰기도 viewer로 연다(슬라이스 92).
    # 조회 등급 직원도 자기 이름·연락처는 고칠 수 있어야 한다. 권한 상승은 등급이 아니라
    # `admin_profile.EDITABLE` 화이트리스트가 막는다 — role·status·email은 아예 못 보낸다.
    # `/operators`보다 **먼저** 검사한다: 아래 owner 규칙이 접두어로 걸리지 않게.
    if path.startswith("/api/admin/my-profile"):
        return "viewer"
    # 남의 «프로필 사진»만 예외로 연다 — 사장님 확정 2026-08-17 ③「전 운영자가 서로 본다」.
    # 아래 `/operators` owner 규칙보다 **먼저** 봐야 접두어로 걸리지 않는다(위 my-profile과
    # 같은 이유). 예외는 이 «한 경로 · GET» 뿐이다 — 계정 목록·역할·정지는 그대로 owner다.
    # 판정을 여기 한 곳에서만 한다(`api/admin_profile_photo.py`는 다시 판정하지 않는다 —
    # 두 곳이 갈리면 한쪽만 고치는 사고가 난다).
    if method in ("GET", "HEAD") and _is_operator_photo_path(path):
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

    ■ 아래 JSON 401 문구는 「~다」체다(2026-08-19 결함① 수정). 예전 「로그인이
    필요합니다」는 이 게이트가 `/api/admin/*` 전체(관리자 화면 41개)를 지나므로
    **바꾸면 그 41개가 전부 같이 바뀐다** — 그래서 바꾸기 전 전수 grep 했다(결과는
    이 세션 보고 참조, 이 파일엔 옮기지 않는다 — 코드가 아니라 보고 소관).
    ⚠ **이 함수의 HTML 분기(`login_required_html()`, `api/admin_ui_common.py`)는
    같이 고치지 않았다** — 다른 파일이고(19+ 화면이 공유하는 정본 파일이라 "동시에
    한 명"만 만진다는 CANON 규칙 대상), 이번 지시 범위(`api/auth.py`·
    `templates/admin/my_profile.html.j2` 둘)도 아니다. 그래서 지금은 `/admin2/*`
    **페이지**를 세션 없이 직접 열면(HTML 분기) 옛 문체가, `/api/admin/*` **API**
    호출이 401을 받으면(아래 JSON 분기) 새 문체가 뜬다 — 같은 게이트인데 분기별로
    문체가 다른 상태다. 다음에 그 파일을 만지는 사람이 맞춘다.
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
                return JSONResponse({"detail": "로그인이 필요하다"}, status_code=401)
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
            # 기기 기억(비밀번호 생략)으로 만든 세션이 «정책 발행급 쓰기»를 시도하면
            # 한 번 더 확인한다(2026-08-15 사장님 지시 — "민감한 일엔 다시 묻는다").
            # OWNER_WRITE_PREFIXES를 **그대로 재사용**한다(좁히지 않는다) — 그
            # 목록은 이미 "값이 실제 동작을 바꾸는 자리"로 슬라이스 50·56·74·75·
            # AI 관리 3화면이 쌓아 온 정의이고, 여기서 또 다른 경계를 만들면 두
            # 목록이 갈라져 나중에 한쪽만 고치는 사고가 난다(§단일 원천).
            #
            # ⚠ 정정(2026-08-15, 확인자 실측으로 발견 — 이전 버전은 이 자리에 반대로
            # 적혀 있었다): `/api/admin/operators`(운영자 목록·역할·정지 —
            # api/admin_operators.py)는 **OWNER_WRITE_PREFIXES의 첫 항목**이다(위
            # 선언 참조) — 그래서 role·suspend 쓰기는 이미 이 게이트를 그대로
            # 받는다(실측: 401 reauth_required 확인됨).
            # **혼동하지 말 것 — 진짜 구멍은 다른 경로였다**: `/api/admin/auth/
            # operators/{id}/password`(비밀번호 발급, 이 파일의 issue_password)는
            # `/api/admin/operators`와 전혀 다른 문자열이다 — `/api/admin/auth/`
            # 접두어라 OPEN_PREFIXES에 걸려 **이 미들웨어 게이트를 아예 타지
            # 않는다**(이 함수 맨 위 `not path.startswith(OPEN_PREFIXES)` 분기
            # 참조 — 그 조건이 참이면 이 아래 코드 전체가 실행되지 않는다). 그
            # 경로는 owner 검사만
            # 손으로 하고 reauth 검사를 빠뜨려서, 기기 기억 세션이 남의 비밀번호를
            # 재발급할 수 있었다 — issue_password가 `_require_owner_reauth`
            # 의존성으로 스스로 막는다(아래 정의 참조). `OPEN_PREFIXES` 아래
            # 새 mutating 엔드포인트가 이 방어를 또 빠뜨리면 `_audit_open_auth_routes()`
            # (이 파일 맨 끝, 가져오기 시점 실행)가 앱을 못 뜨게 막는다.
            # `op.get(...)`으로 읽는다 — 마이그레이션 0051 미적용 DB에서는
            # `resolve_session()`이 `password_verified` 키 자체를 True로
            # 채워 주므로(위 참조) 이 분기가 아예 걸리지 않는다.
            #
            # ⚠ 응답 모양 정정(2026-08-15, 확인자 실측으로 발견): 이 자리는
            # `JSONResponse`를 직접 구성해 FastAPI의 `HTTPException` 래핑을
            # 거치지 않는다 — 그래서 처음엔 `{"detail":..., "error":...}`를
            # 평평하게 보냈다. 그런데 같은 신호(`error: "reauth_required"`)를
            # 내는 `_require_owner_reauth`(아래, `HTTPException` 경유라
            # FastAPI가 `{"detail": {...}}`로 한 겹 더 감싼다)와 응답 모양이
            # 달라져, 같은 문서(`/reauth`, 아래)가 약속한 계약을 두 곳이 다르게
            # 지키는 상태였다. 여기서 **`{"detail": {"error":..., "message":...}}`
            # 모양을 손으로 재현**해 맞춘다 — 이 파일의 다른 32곳(`login()` 등)과
            # 같은 관례이기도 하다(위 `_require_owner_reauth` 문서 참조).
            if (path.startswith(OWNER_WRITE_PREFIXES)
                    and request.method not in ("GET", "HEAD", "OPTIONS")
                    and not op.get("password_verified", True)):
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    {"detail": {"error": "reauth_required",
                                "message": "비밀번호 확인이 필요합니다"}},
                    status_code=401)
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
    # 기기 기억(2026-08-15) — 기본 False. 안 보내는 기존 화면·클라이언트는
    # Pydantic이 자동으로 False를 채우므로 동작이 그대로다(1번 자기검증 항목).
    remember_device: bool = False


# 무차별 대입 방어 — fail2ban이 없으므로 앱에서 막는다.
# 계정 잠금은 그 계정만 막고 IP는 막지 않는다(공유 IP에서 남의 작업을 끊지 않게).
MAX_FAILS = 5
LOCK_MINUTES = 15


def _verify_password_lockout(operator_id: int, password: str) -> None:
    """비밀번호 재확인 + 무차별 대입 방어 — `/reauth`(아래) 전용.

    `login()`의 잠금 판정과 **같은 컬럼·같은 MAX_FAILS·LOCK_MINUTES**를 쓰지만
    같은 함수를 호출하지는 않는다 — `login()`은 이메일 조회·상태 분기(대기/정지)·
    부트스트랩까지 한 트랜잭션에 얽혀 있고, 그 트랜잭션 경계(실패를 예외 밖에서
    별도 커밋으로 기록하는 방식 — 바로 위 `login()`의 같은 주석 참조)를 다치면
    "인증이 깨지면 아무도 못 들어온다"는 이 파일에서 가장 되돌리기 비싼 실수가
    된다. `reauth()`는 이미 로그인된 사람에게 "비밀번호를 한 번 더" 묻는
    것뿐이라 필요한 조회가 훨씬 단순하므로, `login()`을 뜯어고치는 대신
    같은 잠금 SQL 패턴을 **이 함수 하나**로 독립시켜 새로 만든다(login()은
    한 글자도 건드리지 않는다 — 위험 최소화).

    통과하면 조용히 반환. 막히면 HTTPException(401/429)을 던진다. `login()`과
    달리 "이메일이 존재하는지"를 숨길 이유가 없다 — 이미 로그인된 세션의
    operator_id로 호출하므로 계정 존재는 이미 알려진 사실이다.
    """
    with engine.begin() as conn:
        st = conn.execute(text(
            "SELECT password_hash, login_fail_count,"
            " (locked_until IS NOT NULL AND locked_until > now()) AS is_locked,"
            " GREATEST(0, CEIL(EXTRACT(EPOCH FROM (locked_until - now())) / 60)) AS lock_min"
            " FROM admin_operators WHERE operator_id=:i FOR UPDATE"),
            {"i": operator_id}).mappings().first()
        if st is None:
            raise HTTPException(404, "계정을 찾을 수 없습니다")
        if st["is_locked"]:
            left = int(st["lock_min"] or 1)
            raise HTTPException(429, {
                "error": "locked",
                "message": f"로그인 시도가 많아 잠겼습니다 — {left}분 뒤에 다시 시도하세요"})
        bad_pw = not verify_password(password, st["password_hash"])
        if bad_pw:
            fails = (st["login_fail_count"] or 0) + 1
        else:
            conn.execute(text(
                "UPDATE admin_operators SET login_fail_count=0, locked_until=NULL"
                " WHERE operator_id=:i"), {"i": operator_id})
    if bad_pw:
        lock = fails >= MAX_FAILS
        # login()과 같은 이유로 실패 기록은 성공한(별도) 트랜잭션으로 남긴다.
        with engine.begin() as conn2:
            conn2.execute(text(
                "UPDATE admin_operators SET login_fail_count=:f,"
                " locked_until = CASE WHEN :lk THEN now() + (:m || ' minutes')::interval"
                "                     ELSE locked_until END"
                " WHERE operator_id=:i"),
                {"f": 0 if lock else fails, "lk": lock, "m": str(LOCK_MINUTES),
                 "i": operator_id})
        raise HTTPException(401, {
            "error": "bad_credentials",
            "message": ("비밀번호가 올바르지 않습니다"
                        + (f" — {LOCK_MINUTES}분간 잠겼습니다" if lock else
                           f" (남은 시도 {max(0, MAX_FAILS - fails)}회)"))})


def _remember_device(operator_id: int, request: Request, response: Response) -> bool:
    """기기 기억 등록 — `login()`이 비밀번호를 **실제로 확인한 직후**에만 부른다
    (device-login·부트스트랩·dev-login에서는 부르지 않는다 — 비밀번호를 증명한
    적이 없는데 "생략해도 되는 기기"를 등록하면 ②의 전제가 깨진다).

    셀렉터(device_id)+검증값(secret) 패턴 — 왜 이렇게 나누는지, 왜 새 표인지는
    `db/migrations/versions/0051_admin_operator_devices.py` 참조. `secret`은
    쿠키에만 있고 반환하지 않는다 — 이 함수를 나가면 서버는 해시만 갖는다.

    **호출자의 커넥션을 받지 않고 자기 트랜잭션을 새로 연다** — `login()`이
    세션을 만든 바로 그 트랜잭션에 얹으면, 여기서 나는 어떤 실패든(이론상 거의
    없지만) 그 트랜잭션 전체를 오염시킨다(Postgres는 문장 하나가 실패하면 같은
    트랜잭션의 나머지를 전부 거부한다). 그러면 **이미 성공한 세션 생성까지 롤백**
    되는데 쿠키(`response.set_cookie`)는 이미 응답에 실려 나간 뒤라 — "쿠키는
    있는데 세션 행은 DB에 없는" 조용히 깨진 로그인이 만들어진다. 그래서 실패를
    여기서 **완전히 가둔다**(try/except) — 로그인 자체는 항상 그대로 성공하고,
    기기만 "기억 안 됨"으로 남는다(이번 사양의 절대 규칙, IP 기록 때와 같은
    원칙: "부가 기능 때문에 로그인이 막히면 안 된다").

    스키마가 아직 없으면(`_schema_ready()`) 같은 이유로 조용히 False.
    """
    if not _schema_ready():
        return False
    device_id = secrets.token_hex(16)
    secret = secrets.token_hex(32)
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO admin_operator_devices"
                " (device_id, operator_id, token_hash, user_agent, expires_at)"
                " VALUES (:d, :o, :h, :ua, now() + :days * interval '1 day')"),
                {"d": device_id, "o": operator_id, "h": hash_password(secret),
                 "ua": (request.headers.get("user-agent") or "")[:300],
                 "days": REMEMBER_DEVICE_DAYS})
    except Exception:                                 # noqa: BLE001 — 아래 참조
        # 무엇이 잘못됐든 로그인을 막지 않는다는 규칙이 우선이다. 흔한 실패는
        # 없다(스키마는 위에서 이미 확인했고, device_id 충돌 확률은 사실상 0,
        # operator_id FK는 방금 로그인한 계정이라 항상 유효하다) — 그래도
        # "절대 로그인을 막지 않는다"는 이번 사양의 절대 규칙이라 광범위하게 잡는다.
        return False
    response.set_cookie(DEVICE_COOKIE, f"{device_id}:{secret}", httponly=True,
                        samesite="lax", path="/", secure=cookie_secure(),
                        max_age=REMEMBER_DEVICE_DAYS * 86400)
    return True


def _revoke_devices(conn, operator_id: int) -> None:
    """이 운영자의 기기 기억을 전부 철회한다 — 비밀번호 변경·재발급(아래
    `change_my_password`·`issue_password`)에서 부른다. 이유는 "다른 기기의
    세션은 끊는다"는 기존 주석과 같다: 비밀번호를 바꾸는 이유가 유출 의심일 수
    있는데, 기기 기억이 살아 있으면 훔친 device 쿠키로 **비밀번호 없이** 계속
    새 세션을 받을 수 있다 — 비밀번호를 바꾼 보람이 없어진다.

    삭제가 아니라 철회다(`revoked_at`) — admin_sessions·다른 기기 로그아웃과
    같은 규칙(되돌림은 삭제가 아니라 역방향 전이). 스키마가 없으면 조용히
    아무 것도 하지 않는다(부가 기능이 비밀번호 변경 자체를 막으면 안 된다).
    """
    if not _schema_ready():
        return
    conn.execute(text(
        "UPDATE admin_operator_devices SET revoked_at=now()"
        " WHERE operator_id=:i AND revoked_at IS NULL"), {"i": operator_id})


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
                sid = _new_session(conn, new_id, request.headers.get("user-agent"),
                                  _client_ip(request))
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
        sid = _new_session(conn, op_id, request.headers.get("user-agent"), _client_ip(request))
        response.set_cookie(COOKIE, sid, httponly=True, samesite="lax", path="/",
                                    secure=cookie_secure())
        # 기기 기억 — 비밀번호를 **여기서 막 확인했으므로**(위 verify_password) 등록
        # 자격이 있다. 요청한 경우에만, 스키마가 있을 때만(_remember_device 내부 확인).
        remembered = bool(body.remember_device) and _remember_device(op_id, request, response)
        return {"state": "active", "operator": {"id": op_id, "name": op_name,
                "email": op_email, "role": op_role},
                "must_change_password": must_change, "device_remembered": remembered}


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


# ---- 2026-08-15: 기기 기억(비밀번호 생략) ----


@router.post("/device-login")
def device_login(request: Request, response: Response):
    """기기 기억 쿠키로 비밀번호 없이 세션을 발급한다.

    프런트가 (예: 로그인 화면을 그리기 전에) 매번 이 엔드포인트를 먼저 불러
    본다고 가정한다 — httponly 쿠키는 JS가 읽을 수 없어 "이 브라우저에 기기
    쿠키가 있는지"를 클라이언트가 미리 알 방법이 없기 때문이다.

    ■ 실패는 전부 같은 모양이다 — `{"state": "no_device"}`, 예외를 던지지 않는다
    잘못된/철회된/만료된/계정정지된 기기는 "그냥 이 브라우저는 기억된 기기가
    아니다"와 똑같이 취급한다(사유를 구분해 응답하면 공격자에게 어느 값이
    맞았는지 힌트를 준다). **`admin_operators.login_fail_count`(로그인 잠금)는
    전혀 건드리지 않는다** — 여기서의 실패는 "비밀번호를 여러 번 틀렸다"가
    아니라 "기기 쿠키가 없거나 낡았다"이고, 후자는 매우 흔한 정상 상황(기기를
    잊어버림·다른 브라우저·쿠키 삭제)이라 계정을 잠그면 안 된다.

    ■ 계정 정지는 자동으로 막힌다
    `o.status`를 매번 조인해서 본다 — `resolve_session()`이 세션마다 상태를
    다시 확인하는 것과 같은 방식이라, 계정을 '정지'하면 이미 발급된 기기
    쿠키도 다음 호출부터 즉시 막힌다(별도로 기기 행을 지우지 않아도 된다).
    """
    if not _schema_ready():
        return {"state": "no_device"}
    raw = request.cookies.get(DEVICE_COOKIE, "")
    device_id, sep, secret = raw.partition(":")
    if not sep or not device_id or not secret:
        return {"state": "no_device"}
    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT d.token_hash, d.operator_id, o.name, o.email, o.role, o.status"
            " FROM admin_operator_devices d JOIN admin_operators o USING (operator_id)"
            " WHERE d.device_id=:d AND d.revoked_at IS NULL AND d.expires_at > now()"
            " FOR UPDATE OF d"),
            {"d": device_id}).mappings().first()
        if (row is None or not verify_password(secret, row["token_hash"])
                or row["status"] != "활성"):
            response.delete_cookie(DEVICE_COOKIE, path="/")
            return {"state": "no_device"}
        # 슬라이딩 30일 — 쓸 때마다 만료를 늘린다(정적 30일이 아니라 "마지막
        # 사용으로부터 30일". db/migrations/versions/0051 docstring 참조).
        # 토큰 자체는 회전시키지 않는다(매번 새 secret을 발급하면 탈취 재사용
        # 창이 더 짧아지지만, 이번 범위에서는 단순함을 택했다 — 후속 강화 후보로
        # 남겨 둔다. 판단 근거를 여기 적어 다음 사람이 "왜 회전 안 하나"를
        # 묻지 않게 한다).
        conn.execute(text(
            "UPDATE admin_operator_devices SET last_used_at=now(),"
            " expires_at=now() + :days * interval '1 day' WHERE device_id=:d"),
            {"d": device_id, "days": REMEMBER_DEVICE_DAYS})
        sid = _new_session(conn, row["operator_id"], request.headers.get("user-agent"),
                          _client_ip(request), password_verified=False)
    response.set_cookie(COOKIE, sid, httponly=True, samesite="lax", path="/",
                        secure=cookie_secure())
    return {"state": "active", "operator": {"id": row["operator_id"], "name": row["name"],
            "email": row["email"], "role": row["role"]},
            "note": "기기 기억으로 비밀번호 없이 로그인했습니다."}


class ReauthBody(BaseModel):
    password: str


@router.post("/reauth")
def reauth(body: ReauthBody, request: Request):
    """민감한 동작 전 비밀번호 재확인 — 기기 기억으로 만든 세션이
    OWNER_WRITE_PREFIXES 쓰기에서 막혔을 때(`error: "reauth_required"`,
    §auth_middleware) 프런트가 부르는 자리.

    성공하면 **이 세션**을 password_verified=true로 승격한다 — 남은 세션
    수명(최대 8시간) 동안 다시 묻지 않는다. 비밀번호로 직접 로그인한 세션과
    그 순간부터 같은 신뢰 수준이 된다(로그인 한 번으로 세션 전체를 신뢰하는
    기존 규칙과 일관된다 — 요청마다 비밀번호를 물으면 그건 별도 기능이다).
    """
    sid = request.cookies.get(COOKIE, "")
    op = resolve_session(sid)
    if op is None:
        raise HTTPException(401, "로그인이 필요합니다")
    _verify_password_lockout(op["operator_id"], body.password)
    if _schema_ready():
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE admin_sessions SET password_verified=true WHERE session_id=:s"),
                {"s": sid})
    return {"ok": True, "note": "비밀번호를 확인했습니다 — 이 세션에서는 다시 묻지 않습니다."}


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
    """본인 비밀번호 변경. 현재 비밀번호를 확인한다.

    ■ 401 이 «둘»이고 원인이 다르다(2026-08-19 결함② 수정 — 확인자 실측).
    아래 첫 401(세션 없음)과 둘째 401(현재 비밀번호 불일치)은 **같은 상태코드**를
    쓴다. 화면(`templates/admin/my_profile.html.j2`)이 옛날엔 401을 전부 "세션
    만료"로 보고 전면 오버레이(z-index 30)를 띄웠다 — 그래서 오타를 낸 운영자에게
    「세션이 만료됐다 — 다시 로그인하면…」이 뜨고, 결과상자(`#mpResPw`)에 이미
    적힌 정확한 사유는 그 오버레이에 완전히 가려 안 보였다.

    상태코드(401)는 계약이라 바꾸지 않는다(사장님 결정 사안 · 다른 화면·회귀가 그
    코드를 보고 있을 수 있다) — 대신 `detail`을 **이 파일에 이미 있는 관례**로
    구조화해 화면이 자연어 문장이 아니라 안정적인 코드로 가르게 한다. 그 관례는
    `_require_owner_reauth`(이 파일 아래)의
    `{"error": "reauth_required", "message": "..."}`다 — `ui-progress.js`의
    `errText()`가 "32곳 전수 검사"(2026-08-15)로 이미 `detail`이 객체면
    `.message`(또는 `.error`)를 읽도록 돼 있고, **레거시 화면
    `mockups/admin/my-profile.html`도 이미 그 모양을 대비하고 있었다**
    (`dt.message || dt.error`, 580-583행) — 그래서 이 변경은 새 계약이 아니라
    저장소가 이미 반쯤 전제하던 모양을 실제로 채운 것에 가깝다.

    **문구(자연어 메시지) 문자열로 가르지 않는다.** 이 저장소는 "문자열 모양"으로
    동작을 추정하는 검사가 원문 표기가 바뀌는 날 조용히 못 잡은 사고를 이미 둘
    겪었다(`CLAUDE.md` §회귀 세트 `[26]` 재고 원장 · `[42]` 상품명) — 문구를 다듬을
    때마다(이번 물결처럼) 매칭이 조용히 깨지는 것과 같은 모양의 함정이다. `message`는
    여전히 사람이 읽는 문장이라 화면 표시엔 그대로 쓰되, **분기 판단에는 쓰지
    않는다** — 화면은 `error` 코드만 본다(`templates/admin/my_profile.html.j2`의
    `resFail()` 참조).
    """
    op = resolve_session(request.cookies.get(COOKIE, ""))
    if op is None:
        raise HTTPException(401, {"error": "not_authenticated",
                                   "message": "로그인이 필요하다"})
    with engine.begin() as conn:
        cur = conn.execute(text(
            "SELECT email, password_hash FROM admin_operators WHERE operator_id=:i"
            " FOR UPDATE"), {"i": op["operator_id"]}).mappings().first()
        if cur["password_hash"] and not verify_password(body.current or "",
                                                        cur["password_hash"]):
            raise HTTPException(401, {"error": "bad_current_password",
                                       "message": "현재 비밀번호가 올바르지 않다"})
        bad = strength_problem(body.new, cur["email"])
        if bad:
            raise HTTPException(400, bad)
        if cur["password_hash"] and verify_password(body.new, cur["password_hash"]):
            raise HTTPException(400, "이전과 다른 비밀번호를 써야 한다")
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
        # 기기 기억도 함께 철회한다 — 안 그러면 훔친 device 쿠키가 새 비밀번호를
        # 몰라도 계속 로그인을 만들어낼 수 있다(위 _revoke_devices 참조).
        _revoke_devices(conn, op["operator_id"])
    return {"ok": True, "note": "비밀번호를 바꿨다. 다른 기기의 로그인과 기기 기억이 해제됐다."}


# ── /api/admin/auth/* 안의 "정책 발행급 쓰기" 전용 방벽 (2026-08-15 결함 수정) ──
#
# ■ 무엇이 뚫려 있었나 (확인자 실측 2026-08-15)
#   같은 password_verified=false(기기 기억) 세션으로:
#     POST /api/admin/usage-floors/999999999        -> 401 reauth_required   정상
#     POST /api/admin/operators/{id}/role            -> 401 reauth_required   정상
#     POST /api/admin/operators/{id}/suspend         -> 401 reauth_required   정상
#     POST /api/admin/auth/operators/{id}/password   -> **200 성공**          뚫림
#   원인은 이 마지막 경로가 `/api/admin/auth/`로 시작해 OPEN_PREFIXES에 걸리고,
#   `auth_middleware`가 그 접두어는 게이트 자체를 통과시키기 때문이다(로그인·
#   device-login이 세션 없이 동작해야 하므로 그 자체는 불가피하다 — 위
#   `OPEN_PREFIXES` 주석 참조). `issue_password`는 함수 안에서 owner 등급만
#   손으로 확인하고 password_verified(reauth)는 보지 않고 있었다.
#
# ■ 왜 OPEN_PREFIXES를 좁히지 않았나
#   `/api/admin/auth/`를 좁히면 그 아래 login·device-login까지 게이트를 타게
#   되기 쉽다 — 세션이 아직 없어야 정상 동작하는 두 엔드포인트라 잘못 좁히면
#   **로그인 경로 자체가 막혀 아무도 못 들어온다.** 미들웨어 쪽을 안 건드리고
#   이 라우터 안에서 스스로 막는 쪽을 택했다.
#
# ■ 왜 issue_password 안에 검사를 인라인으로 넣지 않았나
#   그렇게 고치면 "지금 아는 구멍 하나"만 막는다. 지시대로 같은 프리픽스 아래
#   다른 mutating 엔드포인트를 전수 확인했다(아래 표) — 지금은 이 하나뿐이지만
#   **다음에 이 프리픽스 아래 새 owner 전용 쓰기가 생기면 똑같이 조용히 뚫릴
#   수 있다.** 그래서 두 겹으로 막는다:
#     ① `_require_owner_reauth` — owner 등급 + reauth를 한 번에 강제하는
#        재사용 가능한 의존성. 새 엔드포인트는 이것만 `Depends()`로 달면 된다.
#     ② `_audit_open_auth_routes()`(이 파일 맨 끝, **가져오기 시점에 실행**) —
#        이 라우터의 모든 쓰기(POST/PUT/PATCH/DELETE) 경로를 훑어 ①을 달았는지,
#        또는 "의도적으로 연다"고 등록돼 있는지 확인한다. 둘 다 아니면 **앱이
#        뜨지 않는다** — 조용히 뚫리는 대신 시끄럽게 막는다.
#
# ■ 같은 프리픽스의 다른 mutating 엔드포인트 전수 확인 (2026-08-15)
#     POST /login          의도적으로 열려 있다 — 세션이 없어야 정상 동작
#     POST /device-login   〃
#     POST /logout         자기 세션만 끊는다 — owner·reauth와 무관, 상태를 약화만 시킨다
#     POST /reauth         이 메커니즘 자체 — 자기 자신에게 reauth를 요구할 수 없다(순환)
#     POST /password       change_my_password — **현재 비밀번호 확인으로 자체 방어**
#                           됨(확인자도 같은 결론). `cur["password_hash"]`가 있으면
#                           반드시 `body.current`로 검증하며, 기기 기억 세션이라도
#                           비밀번호를 모르면 통과 못 한다 — reauth와 동등하거나 더 강함.
#     POST /operators/{id}/password   issue_password — **이번에 고친 것**
#   (`_INTENTIONALLY_OPEN_AUTH_ROUTES`, 아래에 근거와 함께 등록)
def _require_owner_reauth(request: Request) -> dict:
    """owner 등급 + 비밀번호 재확인(reauth)을 함께 요구하는 FastAPI 의존성.

    `/api/admin/auth/*` 아래에서 "정책 발행급 쓰기"를 하는 엔드포인트가 달아야
    하는 표준 방벽 — `auth_middleware`가 다른 경로(OWNER_WRITE_PREFIXES)에
    자동으로 주는 것과 같은 보호를 스스로 재현한다(이 프리픽스는 미들웨어
    게이트를 타지 않는다 — 위 큰 주석 참조).

    ■ 응답 모양 — `{"error": "...", "message": "..."}` (2026-08-15 정정)
    이 파일의 다른 구조화 오류(`login()`의 `bad_credentials`·`locked`·
    `password_not_set`, `_verify_password_lockout()`의 `bad_credentials`·
    `locked`) **전부** `HTTPException(status, {"error": "...", "message": "..."})`
    형태를 쓴다 — `ui-progress.js`의 `errText()`가 "32곳 전수 검사"로 확인한
    저장소 전체 관례이기도 하다(FastAPI가 `detail`을 `{"detail": <넘긴 값>}`으로
    한 겹 더 감싸므로, 최종 모양은 `{"detail": {"error":..., "message":...}}`다).
    처음 이 함수를 짤 때 `{"detail":..., "error":...}`(내부 키가 "detail")로 써서
    같은 `error: reauth_required` 신호인데 `auth_middleware`(아래, `JSONResponse`를
    직접 구성해 감싸이지 않는다)와 **응답 모양이 달랐다**(확인자 실측 — top-level
    `.error`는 None, `.detail.error`라야 값을 읽을 수 있었다). `/reauth`의 문서
    (`error:"reauth_required"`를 프런트가 본다는 계약)가 정확히 뭘 읽어야 하는지
    두 곳에서 다르게 말한 것이라 여기서 통일한다 — `auth_middleware`도 같은 모양이
    되도록 고쳤다(아래 참조). 이제 두 경로 다 `resp.detail.error`로 읽는다.
    """
    op = resolve_session(request.cookies.get(COOKIE, ""))
    if op is None:
        raise HTTPException(401, "로그인이 필요합니다")
    if op.get("role") != "owner":
        raise HTTPException(403, "관리자(owner)만 할 수 있습니다")
    if not op.get("password_verified", True):
        raise HTTPException(401, {"error": "reauth_required",
                                  "message": "비밀번호 확인이 필요합니다"})
    return op


class IssuePasswordBody(BaseModel):
    password: str


@router.post("/operators/{operator_id}/password")
def issue_password(operator_id: int, body: IssuePasswordBody, request: Request,
                   _op: dict = Depends(_require_owner_reauth)):
    """owner가 임시 비밀번호를 발급한다 — 받은 사람은 최초 로그인에서 바꿔야 한다.

    owner 등급 + reauth(비밀번호 재확인)를 `_require_owner_reauth`(위)가 막는다.
    2026-08-15까지는 owner 검사만 손으로 하고 reauth를 빠뜨려, 기기 기억
    (password_verified=false) 세션이 다른 운영자의 비밀번호를 재발급할 수
    있었다(확인자 실측으로 발견).
    """
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
        # 비밀번호 변경(change_my_password)과 같은 이유로 대상 계정의 기기
        # 기억도 철회한다 — 새 비밀번호를 모르는 채로 device 쿠키만으로 계속
        # 로그인이 만들어지면 재발급이 무의미해진다.
        _revoke_devices(conn, operator_id)
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
        # 위 `host`는 LOCAL_HOSTS 멤버십(게이트 판정)만 검증됐다 — `inet` 컬럼에
        # 담을 값은 `_client_ip()`로 다시 얻는다(IP 리터럴 검증까지 포함, 위 함수
        # 참조). 실제로는 항상 같은 값("127.0.0.1"/"::1")이지만 게이트 로직은
        # 건드리지 않는다.
        sid = _new_session(conn, op["operator_id"], request.headers.get("user-agent"),
                          _client_ip(request))

    response.set_cookie(COOKIE, sid, httponly=True, samesite="lax", path="/",
                        secure=cookie_secure())
    return {"ok": True, "operator": {"id": op["operator_id"], "name": op["name"],
                                     "role": op["role"]},
            "note": "화면 점검용 세션을 심었습니다(개발 서버 전용). "
                    "끄려면 .env 의 UI_CHECK_DEV_LOGIN 을 지우십시오."}


# ── 감사: OPEN_PREFIXES 아래 mutating 라우트가 방벽 없이 새로 생기지 않는가 ──
# (2026-08-15, issue_password가 reauth 없이 뚫려 있던 결함을 고치며 신설)
#
# `/api/admin/auth/*`는 auth_middleware의 게이트를 통째로 건너뛴다(OPEN_PREFIXES —
# login·device-login이 세션 없이 동작해야 하므로 불가피하다). 그래서 이 라우터
# 안의 mutating(POST/PUT/PATCH/DELETE) 엔드포인트는 **자기 인증을 스스로 챙겨야**
# 하고, 하나라도 빠뜨리면 이번 issue_password처럼 조용히 뚫린다 — 정상 동작
# 테스트로는 절대 드러나지 않고(가진 사람은 여전히 잘 쓴다), 훔친 기기 쿠키를
# 가진 사람만 그 구멍을 이용할 수 있다.
#
# 그래서 사람이 "다음에도 기억하기"에 기대지 않고, **가져오기 시점에 기계로
# 확인한다.** 이 라우터의 모든 쓰기 경로를 훑어 각각이 다음 중 하나인지 본다:
#   ① `_INTENTIONALLY_OPEN_AUTH_ROUTES`에 **근거와 함께** 등록돼 있다(세션이
#      아직 없어야 하거나, 자기 방식으로 이미 동등하게 방어돼 있다)
#   ② `_require_owner_reauth`를 `Depends()`로 달고 있다
# 둘 다 아니면 **앱이 뜨지 않는다**(RuntimeError) — 다음 사람이 새 owner 전용
# 쓰기를 이 프리픽스 아래 추가하면서 방벽을 빠뜨리면, 그 요청이 조용히 성공하는
# 대신 **서버 기동 자체가 실패**해 그 자리에서 바로 알아차리게 된다.
#
# 실측(2026-08-15, 이 시점의 라우트 전수): login·device-login·logout·reauth·
# password(change_my_password) 다섯만 열려 있고 근거는 각 튜플 옆 주석 —
# `_require_owner_reauth`를 재사용한 곳(issue_password 하나) 검증은
# `tests/regression.py`가 아니라 이 함수 자체가 가져오기 시점에 한다(회귀는
# 서버가 이미 뜬 뒤에 도는 것이라 "뜨지 못하게 막는다"는 이 목적에는 안 맞는다).
_INTENTIONALLY_OPEN_AUTH_ROUTES = {
    ("POST", "/api/admin/auth/login"):
        "세션이 아직 없어야 정상 동작한다 — 로그인 그 자체",
    ("POST", "/api/admin/auth/device-login"):
        "세션이 아직 없어야 정상 동작한다 — 기기 기억으로 세션을 발급받는 자리",
    ("POST", "/api/admin/auth/logout"):
        "자기 세션만 끊는다 — 권한을 넓히지 않고 약화만 시키므로 owner·reauth 무관",
    ("POST", "/api/admin/auth/reauth"):
        "reauth 메커니즘 자기 자신 — 자신에게 reauth를 요구하면 순환이 된다",
    ("POST", "/api/admin/auth/password"):
        "change_my_password — 현재 비밀번호 일치를 요구해 자체 방어된다"
        "(기기 기억 세션도 비밀번호를 모르면 통과 못 한다 — reauth와 동등 이상)",
}


def _audit_open_auth_routes() -> None:
    """가져오기 시점에 한 번 실행 — 위 큰 주석 참조.

    ⚠ **이 검사는 이 모듈(`api/auth.py`)의 `router.routes`만 훑는다 — 그
    범위 밖은 참이라고 보장하지 않는다.** `/api/admin/auth` 접두어를 쓰는
    라우터가 **다른 파일**에 새로 생기면(예: 다른 모듈이
    `APIRouter(prefix="/api/admin/auth")`를 또 선언하는 경우), 그 라우트도
    `OPEN_PREFIXES`에 걸려 `auth_middleware` 게이트를 건너뛰지만, **이 함수는
    그 라우터의 존재 자체를 모른다** — `router.routes`가 이 파일에서 만든
    `router` 객체 하나뿐이기 때문이다. issue_password가 겪은 것과 같은
    클래스의 구멍이 그런 파일에서 또 생겨도 이 감사로는 안 잡힌다(2026-08-15,
    확인자 지적 — 지금 시점엔 이 접두어를 쓰는 파일이 `api/auth.py` 하나뿐이라
    안전하다고 확인됐지만, 그 사실이 앞으로도 유지된다는 보장은 이 함수에
    없다). "이 프리픽스 아래는 전부 잡힌다"고 과신하지 말 것 — 새 파일이 같은
    접두어를 쓰려 한다면 그 파일 자신도 같은 방식(자기 라우터에 이런 감사를
    두거나, `_require_owner_reauth`를 재사용하거나)으로 스스로 방어해야 한다.
    """
    problems = []
    for route in router.routes:
        methods = getattr(route, "methods", None) or set()
        for method in methods:
            if method in ("GET", "HEAD", "OPTIONS"):
                continue                      # 안전 메서드는 이 감사 대상이 아니다
            key = (method, route.path)
            if key in _INTENTIONALLY_OPEN_AUTH_ROUTES:
                continue
            dependant = getattr(route, "dependant", None)
            dep_calls = {d.call for d in (dependant.dependencies if dependant else [])}
            if _require_owner_reauth not in dep_calls:
                problems.append(key)
    if problems:
        raise RuntimeError(
            "보안 감사 실패(api/auth.py _audit_open_auth_routes): 다음 경로가 "
            "OPEN_PREFIXES 아래 mutating 라우트인데 _require_owner_reauth도, "
            "_INTENTIONALLY_OPEN_AUTH_ROUTES 등록도 없습니다 — issue_password가 "
            f"겪은 것과 같은 구멍입니다: {problems}. 의도적으로 연다면 근거와 함께 "
            "_INTENTIONALLY_OPEN_AUTH_ROUTES에 등록하고, 아니라면 "
            "Depends(_require_owner_reauth)를 다십시오.")


_audit_open_auth_routes()


# ── 감사: ADMIN2_OPEN_PATHS 가 넓어지거나 쓰기 경로를 품지 않는가 (2026-08-17 신설) ──
#
# 위 `_audit_open_auth_routes()`와 **같은 방식**이다: 사람이 "다음에도 기억하기"에
# 기대지 않고 **기동 시점에 기계로 확인**하고, 어긋나면 `RuntimeError`로 **앱이 뜨지
# 않게** 한다. 새 장치를 만들지 않고 그 함수의 결을 그대로 따랐다(안전 메서드
# 판정까지 같은 `("GET", "HEAD", "OPTIONS")` 목록을 쓴다).
#
# ■ 왜 필요한가 — `ADMIN2_OPEN_PATHS`(위)는 인증 게이트를 «면제»하는 집합이다.
#   `OPEN_PREFIXES` 아래에서 `issue_password`가 조용히 뚫려 있던 것과 **같은 클래스의
#   구멍**이 여기서도 생길 수 있다: 이 집합에 쓰기 경로가 들어오면 그 경로는 세션도
#   권한도 없이 실행된다. 정상 동작 테스트로는 절대 드러나지 않는다.
#
# ■ 두 겹으로 나눈 이유 — 검사 시점이 다르다
#   ① 집합 «모양» 검사는 이 파일 가져오기 시점에 할 수 있다(라우트가 필요 없다).
#   ② 집합에 걸린 경로의 «메서드» 검사는 라우트를 봐야 하는데, `/admin2/*` 라우트는
#      다른 모듈(`api/admin_ui_login.py` 등)에 있고 그 모듈들은 `api/main.py`의
#      라우터 탐색이 **이 파일보다 뒤에** 가져온다(실측: `main.py`가 16행에서
#      `from .auth import auth_middleware`, 74행에서 `_discover_routers()`). 그래서
#      ②는 여기서 실행하지 못하고, **경로를 소유한 모듈이 자기 가져오기 시점에**
#      `_audit_admin2_open_routes(router)`를 부른다 — 그것도 결국 기동 시점이다.
#      (`auth.py`가 그 모듈을 직접 가져오면 순환이다 — 그 모듈이 이미 auth를 읽는다.)
#
# ⚠ ①이 막는 것이 무엇인지 분명히 해 둔다 — `"/admin2"`나 `"/admin2/"`를 이 집합에
#   넣으면 `_is_gated()`가 그 **정확한 문자열**에만 False를 주므로 `/admin2/dash`가
#   함께 열리지는 않지만, `/admin2/`(admin2 홈, `admin_ui_home.py`가 서버 렌더로
#   실데이터를 싣는 화면)가 **무세션으로 열린다.** 2026-08-15에 새어 나간 것과 같은
#   종류다. 그래서 그 두 문자열을 기동 시점에 거절한다.


def _audit_admin2_open_paths() -> None:
    """`ADMIN2_OPEN_PATHS`의 «모양»을 기동 시점에 확인한다 — 위 주석 참조.

    검사하는 것: `/admin2/` 아래인가 · 그 아래 실제 이름이 있는가(`/admin2`·
    `/admin2/` 자체가 아닌가) · 끝 슬래시가 없는가(면제 문자열이 둘이 되지 않게 —
    `ADMIN2_OPEN_PATHS` 위 주석 §끝 슬래시) · 한 항목이 여러 경로를 뜻하게 만드는
    글자(`?`·`#`·`*`·`{`·공백)가 없는가. `_is_gated()`는 `in` 판정이므로 그런 글자가
    섞이면 «맞을 리 없는 문자열»이 되어 조용히 아무것도 면제하지 않거나(오탐 없음
    쪽이라 그나마 안전하다), 사람이 접두어처럼 읽고 잘못 늘리게 된다.
    """
    problems = []
    for path in sorted(ADMIN2_OPEN_PATHS):
        if not path.startswith(ADMIN2_PREFIX + "/") or len(path) <= len(ADMIN2_PREFIX) + 1:
            problems.append((path, "'/admin2/<name>' 형태가 아니다"))
            continue
        if path.endswith("/"):
            problems.append((path, "끝 슬래시는 넣지 않는다"))
        if any(ch in path for ch in "?#*{} \t"):
            problems.append((path, "한 항목이 여러 경로를 뜻하게 만드는 글자가 있다"))
    if problems:
        raise RuntimeError(
            "보안 감사 실패(api/auth.py _audit_admin2_open_paths): ADMIN2_OPEN_PATHS "
            "항목이 게이트 면제 규칙에 맞지 않습니다 -> "
            f"{problems}. 이 집합은 '/admin2/<name>' 완전 일치만 받습니다 "
            "(상수 위 주석 참조).")


def _audit_admin2_open_routes(open_router) -> None:
    """`ADMIN2_OPEN_PATHS`에 걸린 경로가 «안전 메서드»만 노출하는지 확인한다.

    **게이트 면제 경로를 가진 모듈이 자기 가져오기 시점에 부른다** — 예:

        from .auth import _audit_admin2_open_routes
        _audit_admin2_open_routes(router)      # 모듈 맨 아래

    `api/main.py`의 라우터 탐색이 그 모듈을 가져올 때 함께 돌아 **기동 시점에**
    드러난다(위 주석 ② 참조 — 이 파일에서 직접 돌리지 못하는 이유가 거기 있다).
    쓰기 경로가 이 집합에 걸려 있으면 `RuntimeError`로 **앱이 뜨지 않는다**:
    그 경로는 세션도 권한도 없이 실행되므로, 요청이 조용히 성공하는 것보다
    서버가 그 자리에서 실패하는 쪽이 낫다(`_audit_open_auth_routes()`와 같은 판단).

    ⚠ **이 함수는 넘겨받은 라우터만 훑는다** — 위 `_audit_open_auth_routes()`가
    자기 docstring에 적어 둔 것과 같은 한계다. 면제 경로를 새로 만드는 모듈이 이
    호출을 빠뜨리면 그 모듈은 검사되지 않는다. 그래서 `ADMIN2_OPEN_PATHS`에
    항목을 더하는 사람이 읽도록 **상수 위 주석에 이 호출을 함께 적어 둔다.**
    """
    problems = []
    for route in getattr(open_router, "routes", []):
        if getattr(route, "path", None) not in ADMIN2_OPEN_PATHS:
            continue
        for method in (getattr(route, "methods", None) or set()):
            if method in ("GET", "HEAD", "OPTIONS"):
                continue                      # 안전 메서드는 이 감사 대상이 아니다
            problems.append((method, route.path))
    if problems:
        raise RuntimeError(
            "보안 감사 실패(api/auth.py _audit_admin2_open_routes): 다음 경로가 "
            "ADMIN2_OPEN_PATHS 로 인증 게이트를 면제받는데 안전 메서드가 아닙니다 -> "
            f"{sorted(problems)}. 면제 경로는 세션도 권한도 없이 실행되므로 쓰기를 "
            "둘 수 없습니다. 쓰기가 필요하면 그 엔드포인트를 '/api/admin/*' 아래로 "
            "옮기십시오(그쪽은 게이트가 그대로 걸립니다).")


_audit_admin2_open_paths()
