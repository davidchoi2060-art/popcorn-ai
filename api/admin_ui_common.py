"""admin2 페이지 라우트 공통 헬퍼 — **router 를 갖지 않는다**(2026-08-13).

화면 하나당 라우트 파일 하나(`admin_ui_<screen>.py`)로 쪼갠 이유는
`api/main.py`의 자동 라우터 탐색(`_discover_routers`) 주석에 있다 — 요약하면
제작자 여럿이 화면을 동시에 지어도 이 공유 파일 하나만 건드리면 되고, 서로 다른
화면 파일끼리는 충돌할 일이 없다.

이 모듈은 그 화면 파일들이 함께 쓰는 렌더 헬퍼(`_render`)만 담는다. **일부러
`router` 속성을 두지 않는다** — `main.py`의 자동 탐색은 `router`(APIRouter)가
있는 모듈만 싣는데, 이 파일까지 걸리면 "라우트 없는 라우터"를 실으려다 아무
효과 없이 지나가거나(엄밀히는 `router`가 없으니 그냥 스킵된다) 다음 사람이
헷갈린다. 로직만 있는 공용 모듈은 이렇게 조용히 discovery 밖에 둔다.
"""
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .admin_nav import counts as nav_counts, nav_for

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def render(request: Request, template: str, *, screen_id: str = "", domain: str = "",
           crumb_group: str = "", crumb_now: str = "", **ctx) -> HTMLResponse:  # noqa: D401
    """템플릿을 렌더하고 캐시를 막는다.

    캐시 정책은 정적 쪽 `NoCacheStatic` 과 같아야 한다 — 한쪽만 캐시하면
    "고쳤는데 안 바뀐다"가 한쪽에서만 일어나 비교가 오염된다.

    `screen_id`/`domain`/`crumb_group`/`crumb_now` — admin2 공통 셸(`_admin2_shell.
    html.j2`, 2026-08-13)이 헤더에 그리는 네 가지 사실. 화면마다 마크업에 박아
    6곳에 흩어져 있던 것을 여기로 모았다(§단일 원천). `crumb_group`은
    `api/admin_nav.NAV`의 그룹명과 맞춘다(정본은 여전히 admin_nav — 여기서 다시
    정의하지 않고 그대로 옮겨 적는다).
    """
    # 좌측 메뉴는 **서버가 그린다**(admin_nav 가 단일 원천). 셸이 한 벌이라
    # 모든 화면이 자동으로 같은 메뉴를 받는다 — 화면마다 복제되던 병이 구조적으로 사라진다.
    ctx.setdefault("nav", nav_for(request.url.path))
    ctx.setdefault("nav_counts", nav_counts())
    ctx.update(screen_id=screen_id, domain=domain, crumb_group=crumb_group, crumb_now=crumb_now)
    resp = templates.TemplateResponse(request, template, ctx)
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


# ── admin2 인증 게이트 안내 HTML (2026-08-15) ───────────────────────────────
#
# 원래 `admin_ui_home.py`에만 있던 `_login_required_html()`을 여기로 옮겼다.
# `api/auth.py`의 `auth_middleware`가 `/admin2/*`도 막게 되면서(그전엔 `/api/admin/*`
# 만 막았다) 그 미들웨어도 같은 HTML을 써야 하는데, `auth.py`가 `admin_ui_home.py`를
# 직접 import하면 순환이 된다 — `admin_ui_home.py`가 이미 최상단에서
# `from .auth import resolve_session, COOKIE`를 하기 때문이다(auth 모듈이 COOKIE·
# resolve_session을 정의하기 전에 admin_ui_home이 그걸 찾으려다 ImportError).
# 이 파일(`admin_ui_common.py`)은 `.admin_nav`만 import하고 `auth.py`를 전혀
# 참조하지 않으므로(실측 — 이 파일과 `admin_nav.py` 양쪽 다 `auth` import 0건),
# `auth.py`와 `admin_ui_home.py` 둘 다 여기서 가져오면 순환이 생기지 않는다.
# 같은 것을 두 벌 두지 않는다(CANON.md §1) — 문구를 바꿀 일이 생기면 여기 한 곳만 고친다.
_LOGIN_PAGE = "/admin/login.html"


def login_required_html() -> str:
    """admin2 인증 실패 안내 — 사유를 그대로 밝히고 로그인 화면으로 보낸다.

    `/api/admin/*`가 막힐 때는 순수 JSON(`{"detail": "..."}`)을 그대로 쓴다 — 기존
    화면 스크립트가 그 형식을 읽으므로 바꾸지 않는다(`api/auth.py` 참조). 이 HTML은
    **`/admin2/*` 페이지 요청**이 막힐 때만 쓴다 — 브라우저가 주소창으로 직접 여는
    자리라 날것의 JSON을 보여줄 수 없다. 문구는 특정 화면(대시보드 등) 이름을 박지
    않는다 — 이 함수를 쓰는 화면이 여럿이라서다.
    """
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="1;url={_LOGIN_PAGE}">
<title>로그인이 필요합니다 · 팝콘PC 관리자</title>
<link rel="stylesheet" href="/shared/admin2/admin2.css"></head>
<body style="display:flex;align-items:center;justify-content:center;height:100vh">
<div style="background:var(--card);border:1px solid rgba(0,0,0,.12);border-radius:8px;
        padding:26px 30px;text-align:center;font-family:var(--font);color:var(--on);
        max-width:360px">
  <div style="font:600 15px/1.4 var(--font);margin-bottom:8px">로그인이 필요합니다</div>
  <div style="font:400 12px/1.6 var(--font);color:var(--rv-faint);margin-bottom:16px">
    이 화면은 로그인한 운영자만 볼 수 있습니다. 1초 뒤 로그인 화면으로 이동합니다.
  </div>
  <a href="{_LOGIN_PAGE}" style="font:600 12px/1 var(--font);color:var(--on-primary);
      background:var(--rv-ink);border-radius:5px;padding:9px 14px;text-decoration:none;
      display:inline-block">로그인 화면으로 이동</a>
</div>
</body></html>"""
