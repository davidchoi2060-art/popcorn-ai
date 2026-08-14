"""부품 등급 관리(ADM-ENG-050) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery)."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/part-grade", response_class=HTMLResponse)
def part_grade(request: Request) -> HTMLResponse:
    """부품 등급 관리(ADM-ENG-050) — **신설**.

    계약 = `docs/design/spec-part-grade.md`(2026-08-14 재확정: 본문은 1a 표 — 등급
    있음/없음을 한 표에 「아직 매기지 않은 것」 구분선으로 나눔, 입력은 1b 우측 패널
    한 곳뿐) · 요구사항 = `docs/design/req/req-part-grade.md`. 원안은 Claude Design
    프로젝트 `22248237-...`의 `부품 등급 관리.dc.html`(1a·1b 두 캔버스) — DesignSync
    서브에이전트가 막혀 있어(MAKER-CHECKLIST §1) 여기서는 계약 요약만 옮긴다.

    로직은 전부 `api/grades.py`(GET meta·GET grades·PUT/DELETE grades/{code})가 갖고
    있다 — 이 라우트는 셸에 얹는 것뿐이다(reviews·spec_fill과 같은 얇은 페이지 라우트,
    자체 비즈니스 로직 없음).
    """
    return render(request, "admin/part_grade.html.j2",
                  screen_id="ADM-ENG-050", domain="part-grade",
                  crumb_group="상품사양관리", crumb_now="부품 등급 관리")
