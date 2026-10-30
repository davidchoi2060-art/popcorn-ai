"""AI 슈퍼컴퓨터 표시 정보(ADM-PRD-060 · 가칭) 페이지 라우트 — `api/main.py`가 자동으로 싣는다.

데이터 원천은 `api/admin_ai_device_profiles.py` — 이 파일은 페이지만 갖는다.
2026-10-31 관리자단 개선 PR-2: API(GET/PUT)는 2026-10-20 부터 있었는데 화면이 없어 운영자가 표시 정보를 고칠 수 없었다.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/ai-device-profiles", response_class=HTMLResponse)
def ai_device_profiles(request: Request) -> HTMLResponse:
    return render(request, "admin/ai_device_profiles.html.j2",
                  screen_id="ADM-PRD-060", domain="ai-device-profiles",
                  crumb_group="상품관리", crumb_now="AI 슈퍼컴퓨터 표시 정보")
