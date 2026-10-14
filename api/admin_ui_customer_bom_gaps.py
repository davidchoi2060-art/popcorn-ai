"""고객 화면 부품 정보 확인 페이지 -- `api/main.py`가 자동으로 싣는다(§discovery).

데이터·판정은 `api/customer_bom_gaps.py`(GET/POST /api/admin/customer-bom-gaps*) 한 곳이다. 이 파일은 페이지 껍데기만
서버 렌더하고, 목록·「팝콘PC에서 다시 확인」·「확인 완료」는 템플릿 스크립트가 그 API를 부른다.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render
from .customer_bom_gaps import EVIDENCE_DAYS

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/customer-bom-gaps", response_class=HTMLResponse)
def page(request: Request):
    return render(request, "admin/customer_bom_gaps.html.j2", screen_id="ADM-PRD-031", domain="catalog",
                  crumb_group="상품관리", crumb_now="고객 화면 부품 정보 확인", evidence_days=EVIDENCE_DAYS)
