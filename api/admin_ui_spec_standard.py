"""조립 사양 표준(ADM-STD-010) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery)."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/spec-standard", response_class=HTMLResponse)
def spec_standard(request: Request) -> HTMLResponse:
    """조립 사양 표준(ADM-STD-010) — **기존 화면에 대응물이 없는 신설**.

    `std.spec_defs` 를 사람이 늘릴 수 있게 하는 자리다. 기존 `상품 사양 정의`
    (`/admin/spec-fields.html`)는 `public.spec_field_defs`(wide)를 다루고 컬럼을
    ALTER 한다 — 여기는 EAV 라 정의 행 하나면 끝이라 성격이 다르다.
    """
    return render(request, "admin/spec_standard.html.j2",
                  screen_id="ADM-STD-010", domain="spec-standard",
                  crumb_group="상품사양관리", crumb_now="조립 사양 표준")
