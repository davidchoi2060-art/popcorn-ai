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
