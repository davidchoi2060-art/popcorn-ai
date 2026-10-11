"""고객 화면 문의 · 보관 견적(ADM-ORD-011 · 가칭) 페이지 라우트 — `api/main.py`가 자동으로 싣는다.

데이터 원천은 `api/admin_mvp3_consults.py`(`GET /api/admin/mvp3-consults`) — 이 파일은
페이지만 갖는다. 조회 전용이고 쓰기 API 를 부르지 않는다.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/mvp3-consults", response_class=HTMLResponse)
def mvp3_consults(request: Request) -> HTMLResponse:
    return render(request, "admin/mvp3_consults.html.j2",
                  screen_id="ADM-ORD-011", domain="mvp3-consults",
                  crumb_group="상품사양관리", crumb_now="고객 문의 · 보관 견적")
