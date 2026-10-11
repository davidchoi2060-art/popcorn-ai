"""AI 답 점검(ADM-TLK-012 · 가칭) 페이지 라우트 — `api/main.py`가 자동으로 싣는다.

데이터 원천은 `api/admin_talk_review.py` — 이 파일은 페이지만 갖는다.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/talk-review", response_class=HTMLResponse)
def talk_review(request: Request) -> HTMLResponse:
    return render(request, "admin/talk_review.html.j2",
                  screen_id="ADM-TLK-012", domain="talk-review",
                  crumb_group="AI 관리", crumb_now="AI 답 점검")
