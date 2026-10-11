"""판매 안내 자료(ADM-TLK-011 · 가칭) 페이지 라우트 — `api/main.py`가 자동으로 싣는다.

데이터 원천은 `api/admin_shop_notices.py` — 이 파일은 페이지만 갖는다.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/shop-notices", response_class=HTMLResponse)
def shop_notices(request: Request) -> HTMLResponse:
    return render(request, "admin/shop_notices.html.j2",
                  screen_id="ADM-TLK-011", domain="shop-notices",
                  crumb_group="상품사양관리", crumb_now="판매 안내 자료")
