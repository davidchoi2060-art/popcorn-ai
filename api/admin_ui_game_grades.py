"""게임 사양 등급(ADM-TLK-021 · 가칭) 페이지 라우트 — `api/main.py`가 자동으로 싣는다.

데이터 원천은 `api/admin_game_grades.py` — 이 파일은 페이지만 갖는다.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/game-grades", response_class=HTMLResponse)
def game_grades(request: Request) -> HTMLResponse:
    return render(request, "admin/game_grades.html.j2",
                  screen_id="ADM-TLK-021", domain="game-grades",
                  crumb_group="AI 관리", crumb_now="게임 사양 등급")
