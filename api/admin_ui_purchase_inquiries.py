"""구매 상담 신청(ADM-ORD-012 · 가칭) 페이지 라우트 — `api/main.py`가 자동으로 싣는다.

데이터 원천은 `api/admin_purchase_inquiries.py` — 이 파일은 페이지만 갖는다.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/purchase-inquiries", response_class=HTMLResponse)
def purchase_inquiries(request: Request) -> HTMLResponse:
    return render(request, "admin/purchase_inquiries.html.j2",
                  screen_id="ADM-ORD-012", domain="purchase-inquiries",
                  crumb_group="인계 · 성과", crumb_now="구매 상담 신청")
