"""운영 도우미 설정(ADM-AI-070) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery)."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/ops-assistant", response_class=HTMLResponse)
def ops_assistant(request: Request) -> HTMLResponse:
    """운영 도우미 설정(ADM-AI-070) — **신설**(설정 화면 자체는 old admin 대응 없음).

    원안: `docs/design/dc-ops-assistant.html`. 요구사항: `docs/design/req/
    req-ops-assistant.md`. 데이터: `GET/POST/PATCH/DELETE /api/admin/ops-assistant*`
    (`api/admin_ops_assistant.py`) — `ops_assistant_faqs`·`ops_assistant_scopes`
    (마이그레이션 `db/migrations/versions/0048_ops_assistant_faq.py`, DBA 미적용 상태일
    수 있음. 미적용이어도 화면은 "원천 준비 중"으로 안내하고 죽지 않는다).

    원안과 다르게 구현한 지점(제작 보고서에 상세):
      ① 좌측 메뉴·헤더 — admin2 공용 셸 상속, 정본은 `admin_nav.py`.
      ② **"저장하면 위젯에 즉시 반영됩니다"라는 원안 문구를 쓰지 않는다** —
         `mockups/shared/admin-helper.js`(위젯 본체)는 이번 제작 범위 밖이라
         손대지 않았고, 위젯은 여전히 자기 코드 상수를 읽는다. 화면은 대신
         "DB에는 즉시 반영되지만 위젯 연동 배선은 별도"라고 정직하게 말한다.
      ③ 바로가기 경로 드롭다운은 원안의 `ROUTES` 상수가 아니라 서버가 매 요청마다
         `request.app.routes`를 훑어 만든 실제 목록을 쓴다(그 상수는 제작 시점
         실측으로 이미 낡아 있었다 — `/admin2/reviews`를 없다고 적어 뒀는데 실제로는
         있었다).
      ④ 위젯 미리보기 패널은 "참고용" 캡션을 덧붙였다 — 실제 위젯과 동기화돼
         있지 않다는 사실(②)을 이 패널에서도 반복해 밝힌다.
    """
    return render(request, "admin/ops_assistant.html.j2",
                  screen_id="ADM-AI-070", domain="ops_assistant",
                  crumb_group="AI 관리", crumb_now="운영 도우미 설정")
