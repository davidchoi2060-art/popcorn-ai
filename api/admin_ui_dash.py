"""작업 현황판(ADM-AI-010) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery)."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/dash", response_class=HTMLResponse)
def dash(request: Request) -> HTMLResponse:
    """작업 현황판(ADM-AI-010). 사용자 요청 2026-08-12 신설, 2026-08-14 재구축.

    "해당 업무가 어떻게 진행되는지를 보면서 직접 대화할 수 있는 웹 대시보드."

    새 배선이 없다 — Claude Code 가 세션 전사본을 이미 디스크에 쌓고(`~/.claude/projects/`)
    이 화면은 그걸 읽는다. 말을 거는 쪽은 큐 파일이고, 텔레그램과 같은 구조·같은 한계다
    (도구가 도는 중에는 못 읽는다 — 화면이 그 사실을 먼저 말한다).

    파서는 `api/dash.py`(이 라우트는 건드리지 않는다 — 담당 밖). 이 함수 자체는
    2026-08-14 재구축(승인 디자인 `docs/design/dc-dash.html`, UX-25)에서도 바뀌지
    않았다 — 바뀐 것은 템플릿의 레이아웃·문구뿐이고, 이 라우트가 넘기는
    screen_id/domain/crumb는 그대로다.

    `templates/admin/_admin2_shell.html.j2`(admin2 공통 셸)를 상속한다(2026-08-13
    셸 통합). 좌측 메뉴는 정본(`admin_nav`)을 그대로 싣는다.
    """
    return render(request, "admin/dash.html.j2",
                  screen_id="ADM-AI-010", domain="dash",
                  crumb_group="AI 관리", crumb_now="작업 현황판")
