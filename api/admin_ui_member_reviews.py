"""후기 관리(ADM-CUS-020) 페이지 라우트 — 구 관리자 `/admin/reviews.html` 을 admin2 로 옮겼다
(2026-10-11 사장님 결정 「둘 다」 중 후기). `api/main.py` 가 자동으로 싣는다.

데이터·쓰기는 기존 API 를 그대로 쓴다(`api/admin_member_reviews.py`):
  GET  /api/admin/member-reviews                 후기 목록(구매 인증 주문 라인 포함)
  POST /api/admin/member-reviews/{id}/moderate   숨김 · 게시 유지 · 게시 복원 · 근거 인용 표시
  POST /api/admin/member-reviews/undo/{log_id}   방금 처리 되돌리기
신 관리자 「회원 관리」 묶음에 속한다 — 회원 관리 화면에서 들어오고 돌아가기 줄로 돌아간다.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/member-reviews", response_class=HTMLResponse)
def member_reviews_page(request: Request) -> HTMLResponse:
    return render(request, "admin/member_reviews.html.j2", screen_id="ADM-CUS-020",
                  domain="member-reviews", crumb_group="회원 관리", crumb_now="후기 관리",
                  admin_mode="new")
