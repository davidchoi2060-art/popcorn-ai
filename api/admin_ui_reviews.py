"""상품 사양 검수(ADM-PRD-020) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery)."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/reviews", response_class=HTMLResponse)
def reviews(request: Request) -> HTMLResponse:
    """상품 사양 검수(ADM-PRD-020) — **신설**. 사장님 확정 화면(2026-08-13).

    원안: 사장님이 Claude 디자인에서 확정한 `docs/design/dc-review-screen.html`
    (`<x-dc>` + `DCLogic` + `support.js` 형식이라 여기서는 돌지 않는다 — `build_map`과
    같은 이유로 **화면 구성·색·서체·간격·인터랙션은 원안 그대로 옮기고, 런타임만
    순수 JS로 바꿨다**). 데이터는 원안의 더미 배열 대신 전부 실측 API 응답을 쓴다
    (`GET/POST /api/admin/reviews*`, `GET /api/admin/spec-fields`, `GET /api/admin/auth/me`).

    이 화면의 사이드바·헤더·팔레트가 **admin2 공통 셸의 원본**이 됐다(2026-08-13 —
    `templates/admin/_admin2_shell.html.j2`가 이 화면에서 그대로 뽑은 것). 지금은
    이 화면도 그 공용 셸을 상속한다(자기 자신에서 뽑은 것을 자기가 다시 상속 —
    사본이 둘 남지 않게). **좌측 메뉴는 정본(`admin_nav.nav_for`)을 그대로 읽어
    그린다** — 원안의 11항목 사이드바는 목업용 축약이었고, 항목 구성(IA)의 정본은
    여전히 `api/admin_nav.py`다(2026-08-13 사장님 확인). 규격으로 삼는 것은
    사이드바의 **동작**(212px↔64px·접힘 시 아이콘+툴팁·`data-keep` 바깥클릭 규약)뿐이다.
    """
    return render(request, "admin/reviews.html.j2",
                  screen_id="ADM-PRD-020", domain="reviews",
                  crumb_group="상품사양관리", crumb_now="상품 사양 검수")
