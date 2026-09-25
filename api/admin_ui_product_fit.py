# -*- coding: utf-8 -*-
"""판매 상품 용도 매트릭스(ADM-GRD-020) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery).

2026-09-25 재설계 3단계(사장님 「승인」). 칸마다 조합을 만들던 「상품 매트릭스 관리」
(ADM-GRD-010)와 달리, 이미 파는 몰 조립PC 를 용도·단계 x 가격대 칸에 «표시»만 한다.
**조회 전용** — 숫자는 화면이 `GET /api/admin/product-fit` 을 불러 그린다.
화면 배치는 사장님이 승인한 검토 엑셀의 「용도x가격 미리보기」 시트를 그대로 옮겼다.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/product-fit", response_class=HTMLResponse)
def product_fit_page(request: Request) -> HTMLResponse:
    return render(
        request, "admin/product_fit.html.j2",
        screen_id="ADM-GRD-020", domain="ai",
        crumb_group="상품관리", crumb_now="판매 상품 용도 매트릭스",
    )
