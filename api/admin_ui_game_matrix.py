# -*- coding: utf-8 -*-
"""게임·AI 연계 매트릭스(ADM-GRD-020 가칭) 페이지 라우트.

`api/main.py` 가 자동으로 싣는다(§discovery — `api/` 평면에 두어야 잡힌다).

이웃 화면 `api/admin_ui_grid.py`(ADM-GRD-010)와 같은 관행이다: 이 라우트는 셸을
얹은 페이지 뼈대만 내려주고, 숫자는 화면의 인라인 스크립트가 브라우저에서
`GET /api/admin/game-matrix`(`api/admin_game_matrix.py`)를 직접 불러 그린다.

⚠ `screen_id` 는 **가칭**이다 — `docs/design/req/req-game-matrix.md` §미정 첫 항이
「ADM-GRD-020 은 하네스가 그룹 내 다음 번호로 붙인 가칭, 사장님 확정 필요」라고
적었다. 확정되면 이 한 줄과 템플릿 머리 주석만 고치면 된다(화면 안에 ID 를 다시
박지 않았다 — 셸이 `data-screen-id` 로 한 번만 쓴다).
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/game-matrix", response_class=HTMLResponse)
def game_matrix_page(request: Request) -> HTMLResponse:
    return render(
        request, "admin/game_matrix.html.j2",
        screen_id="ADM-GRD-020", domain="ai",
        crumb_group="AI 관리", crumb_now="게임·AI 연계 매트릭스",
    )
