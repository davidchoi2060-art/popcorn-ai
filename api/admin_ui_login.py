"""로그인(ADM-SYS-021) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery).

승인 디자인 계약 = `docs/design/spec-login.md`(1b 안, 사장님 확정 2026-08-15) ·
요구사항 정의서 = `docs/design/req/req-login.md`.

■ 이 화면은 공통 셸(`templates/admin/_admin2_shell.html.j2`)을 **상속하지 않는다**
  admin2 화면은 예외 없이 그 셸을 상속해 왔다(`req-login.md` §⑦ ㉰가 이 긴장을 사실로
  남겨 두고 사장님 결정 1로 올렸다). 그 결정의 답이 계약의 **1b 안**이다 —
  「상단바(최소 셸)」만 두고 「사이드바를 그리지 않는다」. 셸은 사이드바 메뉴·권한
  표시를 **로그인한 운영자**를 전제로 그리는데 이 화면에는 그릴 운영자가 없다.
  그래서 셸을 상속하는 대신 팔레트·서체 정본(`/shared/admin2/admin2.css`)과 그 셸의
  헤더 클래스(`.a2-hd`)를 **그대로 읽어** 상단바 한 줄만 세운다. 팔레트를 다시
  정의하지 않으므로 §단일 원천을 어기지 않는다(`.claude/CANON.md` §1).

■ 세션 규칙 숫자를 마크업에 박지 않는다
  계약 §「숫자·값 — 하드코딩 금지」가 못박은 것이다: 8시간·15분·5회·30일을 문구에
  박으면 낡는다(실제로 `IDLE_MINUTES`가 30 → 480으로 바뀌며 `req-operators-roles.md`가
  반나절 만에 낡은 전례가 있다). 그래서 **`api/auth.py`의 상수를 그대로 읽어**
  템플릿 컨텍스트로 넘긴다 — 상수를 고치면 화면 문구가 따라 바뀐다.
  `IDLE_MINUTES`는 넘기지 않는다: 계약의 하단 한 줄이 말하는 것은 「세션은 8시간 뒤
  만료」(절대 만료)이고, 지금 유휴 만료는 그와 같은 값이라 둘을 함께 적으면 같은
  사실을 두 번 말한다.

  ⚠ `from .auth import ...`는 순환이 아니다 — `api/auth.py`는 `admin_ui_*`를 모듈
  수준에서 가져오지 않는다(`admin_ui_common`을 함수 안에서만 늦게 가져온다).
  `api/admin_ui_home.py`가 이미 같은 방식으로 `from .auth import ...`를 한다.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render
from .auth import (ABSOLUTE_HOURS, LOCK_MINUTES, MAX_FAILS, REMEMBER_DEVICE_DAYS,
                   _audit_admin2_open_routes)

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    """로그인(ADM-SYS-021) — 관문 화면. 좌: 로그인 · 우: 계정 사용 신청.

    ⚠⚠ **이 경로는 게이트 «면제»로 열려 있다** — `api/auth.py`의 `_is_gated()`가
    `/admin2` 전체를 게이트 대상으로 보므로, 무세션 요청이 로그인 화면 대신 401을 받는
    순환이 있었다. 그래서 같은 파일의 `ADMIN2_OPEN_PATHS`(**완전 일치 집합**, 2026-08-17
    신설 · 사장님 확정 A-44)에 **이 경로 하나만** 넣었다. 근거·왜 접두어가 아닌지·끝
    슬래시를 왜 안 넣는지는 그 상수 위 주석에 있다.

    ⚠ **그래서 이 화면은 무세션으로 열린다 — 서버 렌더로 데이터를 싣지 않는다.**
    템플릿 컨텍스트로 넘기는 것은 세션 규칙 상수 넷(`api/auth.py`에서 읽은 8·5·15·30)과
    화면 자기 식별자뿐이고, 운영자·상품·집계는 **한 건도 싣지 않는다.** 2026-08-15에
    서버 렌더 화면 3종이 자체 게이트 없이 실데이터를 흘린 사고가 있었다 —
    **이 화면에 서버 렌더 데이터를 추가하려면 그 사고를 먼저 읽어라**(게이트가 면제된
    경로라 미들웨어가 막아 주지 않는다). 화면이 부르는 API는 전부 `/api/admin/*`이고
    그쪽은 여전히 게이트된다.

    라우트가 화면의 사실(ID·이름)을 말하는 유일한 곳이다 — 마크업에 박지 않는다
    (`api/admin_ui_common.render` docstring §단일 원천).
    """
    return render(request, "admin/login.html.j2",
                  screen_id="ADM-SYS-021", domain="auth",
                  crumb_now="관리자 로그인",
                  session_hours=ABSOLUTE_HOURS,
                  max_fails=MAX_FAILS,
                  lock_minutes=LOCK_MINUTES,
                  remember_days=REMEMBER_DEVICE_DAYS)


# ── 감사: 이 모듈의 게이트 면제 경로가 «안전 메서드»만 노출하는가 (2026-08-17) ──
#
# `/admin2/login`은 `api/auth.py`의 `ADMIN2_OPEN_PATHS`로 인증 게이트를 면제받는다 —
# 즉 **세션도 권한도 없이 실행된다.** 그래서 이 경로에 쓰기(POST/PUT/PATCH/DELETE)가
# 붙으면 그 순간 무인증 쓰기가 된다. 사람이 "다음에도 기억하기"에 기대지 않고
# **가져오기 시점에 기계로 확인**한다(`api/main.py`의 라우터 탐색이 이 모듈을 가져올 때
# 함께 돈다 — 즉 기동 시점이고, 어긋나면 `RuntimeError`로 **앱이 뜨지 않는다**).
#
# 판정 자체는 `api/auth.py`가 한다 — 면제 집합의 정본이 거기이고, 검사 규칙까지 여기서
# 다시 쓰면 두 벌이 되어 언젠가 갈라진다(§단일 원천). 이 파일은 **자기 라우터를 넘겨주는
# 한 줄**만 진다. 새 면제 경로를 만드는 모듈도 같은 한 줄을 자기 맨 아래에 둔다.
_audit_admin2_open_routes(router)
