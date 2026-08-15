"""용도별 최소 사양(ADM-ENG-040) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery)."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/usage-floors", response_class=HTMLResponse)
def usage_floors(request: Request) -> HTMLResponse:
    """용도별 최소 사양(ADM-ENG-040) — **신설**. 계약: `docs/design/spec-usage-floors.md`.

    ⚠ 화면 ID는 040이다. `api/admin_usage_floors.py`(기존 데이터 API)의 모듈
    docstring이 자신을 "ADM-ENG-030"이라 적었는데, 그건 이미 "추천 가능 재고 현황"
    (candidate-pool)의 ID다 — 복사·붙여넣기 오기(`docs/design/req/req-usage-floors.md`
    "실측 메모" 참조, 고치는 것은 이 화면의 범위 밖). 이 라우트·화면은 마크업 계약
    (`data-screen-id`)을 따라 040을 쓴다.

    데이터는 기존 API를 그대로 쓴다(이 화면의 담당 파일이 아니라 고치지 않았다):
      GET  /api/admin/usage-floors           — 8용도 그룹 + 21개 하한 행 + 통과/전체 건수
      POST /api/admin/usage-floors/{floor_id} — 값·활성 변경. preview:true면 저장 없이
                                                  영향(pass_before/after/slot_total)만 계산
    둘 다 `api/admin_usage_floors.py`(owner 전용 쓰기, `OWNER_WRITE_PREFIXES`에 등록됨)에
    이미 있고, 이 화면이 그리는 표(용도·매칭문구/슬롯·필드/지금 하한/통과·전체/통과율/
    바꾸기)에 필요한 필드를 전부 준다 — 추가 백엔드 작업 없이 바로 붙을 수 있었다.

    ■ 미리보기 배치 — **1a(행 내 펼침) 기준, 2026-08-14 사장님 재확정.** 처음 계약은
      "두 화면을 다 참고해서 작업 처리"로 배치를 제작자에게 열어 뒀고, 그래서 첫 판은
      우측 시뮬레이터 패널(1b)로 지었다. 곧이어 "1a 안으로 가되 다른 화면도 참조"로
      배치가 정해져 **패널을 걷어내고 행 내 펼침으로 옮겼다** — "바꾸기"를 누르면
      표의 그 행 바로 아래에 편집·미리보기 영역이 펼쳐진다(한 번에 하나만).
      1b에서 반드시 가져오라고 지시된 셋(사장님 지시, 2026-08-14 두 번째)은 전부 행
      펼침 안에 살아 있다: ① 후보 0 위험 경고(붉은 박스 + "위험을 알고 저장" 버튼)
      ② "활성·비활성" 토글 ③ "이 화면이 지키는 것" 5줄 — 다만 ③은 패널 자체가
      없어져 **표 위의 항상-노출 고정 박스**로 옮겼다(계약이 ③에는 ①과 달리 "행
      내에"라는 위치 지시가 없었다 — 매번 행을 펼쳐야만 보이면 "지키는 것"이 안
      보이는 게 되므로 상시 노출을 택했다). 1a 자신의 잠금 버튼 둘("+ 용도 만들기",
      그룹 헤더 "문구 편집")은 표 툴바·그룹 헤더에 그대로 있다. 두 하단 안내문은
      성격이 달라 합치지 않았다 — 1a 문구(우선순위·빈 하한·GPU 없는 용도)는 표
      아래에, 1b 문구(400/404/후보 0)는 패널이 사라진 자리 대신 **행 펼침의 저장
      버튼 근처**로 옮겼다(그 문구가 설명하는 게 정확히 그 버튼을 눌렀을 때 벌어지는
      일이기 때문). 상세 근거는 템플릿(`templates/admin/usage_floors.html.j2`) 상단
      주석에 있다.

    ■ 이 라우트는 컨텍스트를 더 얹지 않는다 — reviews·build_map·spec_standard와 같은
      최소 패턴(screen_id/domain/crumb만 넘기고 나머지는 템플릿의 클라이언트 스크립트가
      fetch로 채운다). 서버 렌더 시점에 DB를 미리 읽지 않는다.
    """
    return render(request, "admin/usage_floors.html.j2",
                  screen_id="ADM-ENG-040", domain="usage-floors",
                  crumb_group="상품사양관리", crumb_now="용도별 최소 사양")
