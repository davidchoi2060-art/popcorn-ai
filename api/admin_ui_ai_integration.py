"""AI 연동 설정(ADM-AI-040) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery)."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/ai-integration", response_class=HTMLResponse)
def ai_integration(request: Request) -> HTMLResponse:
    """AI 연동 설정(ADM-AI-040) — **신설**. `api/admin_nav.py` "AI 관리" 그룹,
    note: "신설 — 키는 서버 env".

    원안: 사장님이 Claude 디자인에서 확정한 `docs/design/dc-ai-integration.html`
    (`<x-dc>` + `DCLogic` + `support.js` 형식이라 여기서는 돌지 않는다 — `reviews`와 같은
    원칙: **화면 구성·색·서체·간격·인터랙션은 원안 그대로 옮기고, 런타임만 순수 JS로
    바꿨다.** 데이터는 원안의 더미(`INIT_LIMITS`·`LIVE_STATE`)를 걷어내고
    `GET/POST /api/admin/ai-integration/*` 실측 응답만 쓴다.

    요구사항 정본: `docs/design/req/req-ai-integration.md`. 키 값 자체는 이 화면에
    입력·표시하지 않는다(CANON §2-5) — 서버는 env 키 **존재 여부**만 판정해서 준다.
    """
    return render(request, "admin/ai_integration.html.j2",
                  screen_id="ADM-AI-040", domain="ai_integration",
                  crumb_group="AI 관리", crumb_now="AI 연동 설정")
