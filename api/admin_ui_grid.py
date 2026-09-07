# -*- coding: utf-8 -*-
"""격자 관리(ADM-GRD-010) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery).

원안 `docs/design/incoming/dc-grid-admin.html`(`data-screen-id="ADM-GRD-010"`
`data-domain="ai"`)을 계약 삼아, 다른 admin2 화면과 같은 관행으로 셸만 얹는다
(`api/admin_ui_candidate_pool.py` 참고 — **조회 전용**, 숫자는 화면의 인라인
스크립트가 브라우저에서 직접 `GET /api/admin/grid`(`api/admin_grid.py`, 담당
밖)를 불러 그린다. 이 라우트 자신은 페이지 뼈대만 내려준다.

칸의 내용물(생성된 견적)만 다루고 격자 축(티어 경계·용도 목록) 자체를 고치는
화면이 아니다 — 원안 하단 안내문 그대로("축은 별도 화면에서 관리").
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/grid", response_class=HTMLResponse)
def grid_page(request: Request) -> HTMLResponse:
    return render(
        request, "admin/grid.html.j2",
        screen_id="ADM-GRD-010", domain="ai",
        crumb_group="AI 관리", crumb_now="격자 관리",
    )
