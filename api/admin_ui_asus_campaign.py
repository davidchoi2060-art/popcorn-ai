"""ASUS 기획전 관리(ADM-PRD-061 · 가칭) 페이지 라우트 — `api/main.py`가 자동으로 싣는다.

데이터 원천은 `api/admin_asus_campaign.py` — 이 파일은 페이지만 갖는다.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/asus-campaign", response_class=HTMLResponse)
def asus_campaign(request: Request) -> HTMLResponse:
    return render(request, "admin/asus_campaign.html.j2",
                  screen_id="ADM-PRD-061", domain="asus-campaign",
                  crumb_group="상품관리", crumb_now="ASUS 기획전 관리")
