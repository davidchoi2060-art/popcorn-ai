"""게임 견적 근거 검수(ADM-TLK-020) 페이지 라우트 — `api/main.py` 가 자동으로 싣는다(§discovery).

화면 ID·경로를 이렇게 정한 근거
  ■ ID `ADM-TLK-020` — 이 문구를 **읽는 쪽이 팝콘톡**이다
    (`api/talk_answer.py` `load_game_facts`). 같은 축의 기존 화면이
    「팝콘톡 응답 패턴」(`ADM-TLK-010`)이고, 그 다음 빈 번호가 020 이다.
    「상품 사양 검수」(`ADM-PRD-020`)와 이름이 비슷하지만 **다른 축**이다 —
    저쪽은 부품(products)의 사양 «사실»을 검수하고, 이쪽은 게임에 대해 **우리가 쓴 글**을
    검수한다(0103 이 표를 games 에서 분리한 이유와 같다: 출처가 다르고 검수 주기가 다르다).
  ■ 경로 `/admin2/game-copy-review` — 도메인(`game-copy`)과 하는 일(`review`)을 그대로.
  ■ 그룹 「AI 관리」 — 팝콘톡 응답 패턴 바로 다음. 이 문구는 LLM 이 생성해 사람이
    검수하는 것이고, 소비처가 팝콘톡이다.

셸은 admin2 공통 셸(`templates/admin/_admin2_shell.html.j2`)을 그대로 상속한다 —
배치·색을 새로 그리지 않는다. 좌측 메뉴 정본은 `api/admin_nav.py` 다.

데이터는 전부 `api/admin_game_copy.py`(`/api/admin/game-copy*`)가 준다. 이 파일은
**페이지 껍데기만** 서버 렌더한다(`admin_ui_reviews.py`·`admin_ui_price_review.py` 와 같은 패턴).
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/game-copy-review", response_class=HTMLResponse)
def game_copy_review(request: Request) -> HTMLResponse:
    """ADM-TLK-020 게임 견적 근거 검수 — 86종을 사람이 보고 고객 노출을 연다.

    ★ 승인 한 번이 곧 고객 노출이다. `api/talk_answer.py` 가 이 표를 이미 읽고 있고
      조회 조건이 `reviewed_by IS NOT NULL` 이라, 검수가 통과하면 **코드 수정 없이**
      팝콘톡 답변에 실린다. 그래서 이 화면은 «승인 버튼»이 아니라 «대조 도구»가 본체다 —
      상세가 그 게임의 `games` 원본 값을 문구와 나란히 놓는다.
    """
    return render(request, "admin/game_copy_review.html.j2",
                  screen_id="ADM-TLK-020", domain="game-copy",
                  crumb_group="AI 관리", crumb_now="게임 견적 근거 검수")
