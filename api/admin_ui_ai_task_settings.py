"""AI 작업 설정(ADM-AI-030) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery)."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/ai-task-settings", response_class=HTMLResponse)
def ai_task_settings(request: Request) -> HTMLResponse:
    """AI 작업 설정(ADM-AI-030) — **완전 신설**(old admin에 대응 화면 없음).

    A-35(decision-log.md, 2026-08-13 사장님 확정 — Codex·Claude·Gemini 3사 역할분담 +
    폴백 채택)를 화면으로 다룬다. 원안: 사장님이 Claude Design에서 확정한
    `docs/design/dc-ai-task-settings.html`(`<x-dc>` + `DCLogic` 형식이라 여기서는 돌지
    않는다 — `reviews`와 같은 이유로 화면 구성·색·서체·간격·인터랙션은 원안 그대로
    옮기고 런타임만 순수 JS로 바꿨다). 데이터는 원안의 더미 상수(TASK_CATALOG·
    INIT_TASKS·INIT_HISTORY·PROMPTS 등)를 전부 걷어내고 `api/admin_ai_tasks.py`의
    실측 API 응답만 쓴다.

    배정을 저장할 테이블이 이 화면 이전에는 없었다 — 마이그레이션 0046이 신설한다
    (DBA 적용 대기 — **미적용 상태에서는 API가 `ready:false`를 주고 화면은 "원천 준비
    중"으로 말한다**, 500으로 죽지 않는다).

    좌측 메뉴는 정본(`admin_nav.nav_for`)을 그대로 읽어 그린다 — 원안의 11항목
    사이드바는 목업용 축약이었다. 규격으로 삼는 것은 사이드바의 **동작**뿐이다
    (212px<->64px·접힘 시 아이콘+툴팁·`data-keep` 바깥클릭 규약, CLAUDE.md §관리자
    화면 규약).
    """
    return render(request, "admin/ai_task_settings.html.j2",
                  screen_id="ADM-AI-030", domain="ai_tasks",
                  crumb_group="AI 관리", crumb_now="AI 작업 설정")
