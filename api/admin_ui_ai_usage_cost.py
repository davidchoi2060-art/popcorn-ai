"""AI 사용량 · 비용(ADM-AI-050) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery)."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/ai-usage-cost", response_class=HTMLResponse)
def ai_usage_cost(request: Request) -> HTMLResponse:
    """AI 사용량 · 비용(ADM-AI-050) — `api/admin_nav.py` "AI 관리" 그룹 5번째 항목.

    옛 화면 `mockups/admin/ai-cost.html`(옛 ID ADM-SYS-010)이 있었으나 P-09에 따라
    백업용 동결 — 참고만 하고 옮기지 않았다. 원안: 사장님이 확정한
    `docs/design/dc-ai-usage-cost.html`(`reviews`·`ai-integration`과 같은 원칙 — 화면
    구성·색·서체·간격은 원안 그대로, 데이터는 `GET /api/admin/ai-usage-cost/summary`
    실측만).

    **읽기 전용** — 쓰기 액션이 없다(요구사항 `req-ai-usage-cost.md` ①·⑥). 지표 자리는
    전부 그리되 각 자리에 서버가 실측한 "원천 없음"/"스키마 없음"을 그대로 표시한다 —
    지어낸 숫자를 두지 않는다(화면 정직성 규약).
    """
    return render(request, "admin/ai_usage_cost.html.j2",
                  screen_id="ADM-AI-050", domain="ai_usage_cost",
                  crumb_group="AI 관리", crumb_now="AI 사용량 · 비용")
