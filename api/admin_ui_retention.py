"""보관 기한 · 파기 이력(ADM-SYS-031 · 가칭) 페이지 라우트 — `api/main.py`가 자동으로 싣는다.

데이터 원천은 `api/admin_retention.py` — 이 파일은 페이지만 갖는다(2026-10-18 관리자 정리 기획 A05).
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/retention", response_class=HTMLResponse)
def retention(request: Request) -> HTMLResponse:
    return render(request, "admin/retention.html.j2",
                  screen_id="ADM-SYS-031", domain="retention",
                  crumb_group="인계 · 성과", crumb_now="보관 기한 · 파기 이력")
