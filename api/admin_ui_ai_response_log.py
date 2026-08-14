"""AI 응답 기록(ADM-AI-060) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery)."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/ai-response-log", response_class=HTMLResponse)
def ai_response_log(request: Request) -> HTMLResponse:
    """AI 응답 기록(ADM-AI-060) — **신설**(old admin에 대응 화면 없음).

    원안: `docs/design/dc-ai-response-log.html`(`<x-dc>`+`DCLogic`+`support.js` 형식이라
    여기서는 돌지 않는다 — `reviews`와 같은 이유로 **화면 구성·색·서체·간격·인터랙션은
    원안 그대로 옮기고, 런타임만 순수 JS로 바꿨다**). 요구사항: `docs/design/req/
    req-ai-response-log.md`. 데이터: `GET /api/admin/ai-response-log`(`api/admin_ai_
    logs.py`) — 실측 0건 + 그 이유 네 갈래를 서버가 실측해 함께 내려준다.

    원안과 다르게 구현한 지점(제작 보고서에 상세):
      ① 좌측 메뉴 — admin2 공용 셸(`_admin2_shell.html.j2`) 상속, 정본은 `admin_nav.py`.
      ② "연동 후 미리보기" 모드의 예시 행 6개는 **클라이언트 전용 상수**로 남겼다 —
         서버는 실측 모드에서 예시 행을 절대 만들지 않는다(화면 정직성 규약).
      ③ 상세 서랍의 "플래그" 쓰기는 **서버 API를 두지 않았다** — 실측 모드는 행이
         0건이라 서랍이 열릴 일이 없고(플래그 대상이 없다), 미리보기 모드에서만
         클라이언트 메모리 위에서 토글된다(저장되지 않으며 그 사실을 밝힌다).
    """
    return render(request, "admin/ai_response_log.html.j2",
                  screen_id="ADM-AI-060", domain="ai_response_log",
                  crumb_group="AI 관리", crumb_now="AI 응답 기록")
