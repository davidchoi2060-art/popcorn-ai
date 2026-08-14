"""웹 사양 채움(ADM-AI-020) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery)."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/spec-fill", response_class=HTMLResponse)
def spec_fill(request: Request) -> HTMLResponse:
    """웹 사양 채움(ADM-AI-020) — **신설**. B안(전용 실행 화면), 사장님 확정 2026-08-13.

    제안서(`docs/design/spec-fill-ui-direction-2026-08-13.md`)는 A안(화면 신설 없음)을
    추천했으나 사장님이 B안을 택했다(decision-log P-10). B의 단점(정본 복제)을 줄이려고
    이 화면은 로직을 갖지 않는다 — 실행은 기존 대시보드 큐(`POST /api/admin/dash/say`,
    `api/dash.py`)를 그대로 쓰고, 승인은 검수 화면(ADM-PRD-020)으로 필터 링크만 한다.
    이 화면이 갖는 유일한 신규 로직은 집계 조회(`api/admin_spec_fill.status`)뿐이다.

    카드형 실행/진행/미리보기 화면이라 `products`/`spec-standard`와 같은 도메인(CRUD·
    조회) — `dash`/`build-map`처럼 자체 캔버스가 필요하지 않다. 2026-08-13까지는
    `_layout.html.j2`(Phoenix)를 상속했다 — 지금은 admin2 공통 셸(`_admin2_shell.
    html.j2`)을 상속하되, 본문 카드·표는 여전히 Phoenix(Bootstrap) 컴포넌트라
    `head_extra`/`foot_extra` 블록으로 그 벤더 자산을 함께 싣는다.
    """
    return render(request, "admin/spec_fill.html.j2",
                  screen_id="ADM-AI-020", domain="spec-fill",
                  crumb_group="AI 관리", crumb_now="웹 사양 채움")
