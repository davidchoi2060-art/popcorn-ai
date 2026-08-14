"""상품 관리(ADM-PRD-010) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery)."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/products", response_class=HTMLResponse)
def products(request: Request) -> HTMLResponse:
    """상품 관리(ADM-PRD-010) — 기존 `/admin/products.html` 의 대조군."""
    return render(request, "admin/products.html.j2",
                  screen_id="ADM-PRD-010", domain="product",
                  crumb_group="상품관리", crumb_now="상품 관리")
