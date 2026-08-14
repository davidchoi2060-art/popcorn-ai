"""조립 호환 조감도(ADM-STD-020) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery)."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/build-map", response_class=HTMLResponse)
def build_map(request: Request) -> HTMLResponse:
    """조립 호환 조감도(ADM-STD-020) — **신설**. 사용자 결정 2026-08-11.

    `spec-standard` 가 「무엇이 비었나」를 말한다면 여기는 「왜 그게 문제인가」를 말한다.
    읽는 목적과 고치는 목적이 달라 화면을 나눴다.

    **이 화면만 Phoenix 를 쓰지 않는다.** 첫 판은 Phoenix 조각(KPI 카드·카드뷰·리스트뷰)을
    조립했는데, 같은 데이터를 네 번 말하면서 정작 「조감도」인 지도가 화면의 1/4 이었다.
    Phoenix 는 CRUD 화면에는 맞지만 **읽는 화면**을 담을 그릇이 없다 — 형식이 내용을 이겼다.
    다시 만든 판은 사용자가 Claude 디자인으로 그린 원안을 옮긴 것이다(3안 탭 전환).
      원안 : claude.ai/design · 22248237-152f-4f13-8201-54afca75ebe4
             `조립 호환 조감도.dc.html`

    2026-08-13까지는 `_layout.html.j2`(Phoenix)를 상속하지 않고 자체 셸을 통째로
    그렸다. 지금은 `templates/admin/_admin2_shell.html.j2`(reviews.html.j2에서 뽑은
    admin2 공통 셸 — 사이드바·헤더·팔레트)를 상속한다. 지도·격자 같은 전체 화면
    구성은 그대로 `content` 블록 안에 있다.
    """
    return render(request, "admin/build_map.html.j2",
                  screen_id="ADM-STD-020", domain="compat-map",
                  crumb_group="상품사양관리", crumb_now="조립 호환 조감도")
