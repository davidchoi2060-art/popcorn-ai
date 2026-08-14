"""작업 현황판(ADM-AI-010) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery)."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/dash", response_class=HTMLResponse)
def dash(request: Request) -> HTMLResponse:
    """작업 현황판(ADM-AI-010) — **신설**. 사용자 요청 2026-08-12.

    "해당 업무가 어떻게 진행되는지를 보면서 직접 대화할 수 있는 웹 대시보드."

    새 배선이 없다 — Claude Code 가 세션 전사본을 이미 디스크에 쌓고(`~/.claude/projects/`)
    이 화면은 그걸 읽는다. 말을 거는 쪽은 큐 파일이고, 텔레그램과 같은 구조·같은 한계다
    (도구가 도는 중에는 못 읽는다 — 화면이 그 사실을 먼저 말한다).

    파서는 `api/dash.py`. `templates/admin/_admin2_shell.html.j2`(admin2 공통 셸)를
    상속한다(2026-08-13 셸 통합 — 예전엔 이 화면도 사이드바·헤더·팔레트를 자체
    구현으로 들고 있었다). 좌측 메뉴는 정본(`admin_nav`)을 그대로 싣는다.
    """
    return render(request, "admin/dash.html.j2",
                  screen_id="ADM-AI-010", domain="dash",
                  crumb_group="AI 관리", crumb_now="작업 현황판")
