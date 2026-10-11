"""쇼핑몰 가격 반영(ADM-PRC-070 · 가칭) 페이지 라우트 — `api/main.py`가 자동으로 싣는다.

데이터 원천은 `api/admin_mall_price.py`, 반영 규칙은 `api/mall_price.py` — 이 파일은 페이지만 갖는다.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/mall-price", response_class=HTMLResponse)
def mall_price(request: Request) -> HTMLResponse:
    return render(request, "admin/mall_price.html.j2",
                  screen_id="ADM-PRC-070", domain="mall-price",
                  crumb_group="판매가", crumb_now="쇼핑몰 가격 반영")
