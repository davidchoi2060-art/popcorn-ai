"""작업 기록(ADM-SYS-030) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery).

화면 자체는 `docs/design/dc-activity-logs.html`(사장님 Claude Design 승인 원안)을
`templates/admin/activity_logs.html.j2`로 옮긴 것이다. 요구사항 정의서:
`docs/design/req/req-activity-logs.md`. 원안·데이터 계약·알려진 결함 확인 결과·원안과
다르게 만든 지점은 전부 템플릿 파일 상단 주석에 있다(중복 기록하지 않는다).

■ 데이터 API — 새로 만들지 않았다. `GET /api/admin/activity-logs`(`api/admin_activity_logs.py`,
  읽기만 — 수정하지 않았다) 하나만 쓴다. 파라미터는 `date_from`·`date_to`(둘 다 옵션,
  KST 날짜) 뿐이고, 운영자·도메인·행위·되돌림 여부·자유검색은 서버 파라미터가 없어
  화면이 불러온 배치 안에서 클라이언트 필터로 처리한다(템플릿 주석 참조).

■ 이 화면은 조회 전용이다 — 쓰기 API를 하나도 부르지 않는다. `GET /api/admin/
  activity-logs`는 `api/auth.py`를 코드로 확인한 결과 GET 기본 규칙(viewer 이상)을
  그대로 따른다(`OWNER_WRITE_PREFIXES`에 이 경로가 없다 — 실측). 그래서 역할별로
  잠그는 UI가 없다.

■ 좌측 메뉴(LNB) 참고 — `api/admin_nav.py`의 "시스템" 그룹 "작업 기록" 항목은 이
  라우트가 만들어진 시점에도 여전히 `href=None`(신설 예정)이다. 그 파일은 이 작업의
  담당 범위 밖이라 고치지 않았다 — href를 `/admin2/activity-logs`로 올려야 LNB에서
  이 화면으로 갈 수 있다(제작 보고서에 남김).
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/activity-logs", response_class=HTMLResponse)
def activity_logs(request: Request) -> HTMLResponse:
    """작업 기록(ADM-SYS-030).

    전 도메인 감사 원장 조회 화면 — 14개 이상의 관리자 모듈이 `admin_orders._log()`
    한 함수로 남기는 기록을 기간으로 좁혀 보고, 행을 눌러 서버가 만든 요약 문장과
    "되돌려짐" 판정을 상세로 본다. 쓰기 기능이 없다(삭제·수정 UI 자체가 없다).
    """
    return render(request, "admin/activity_logs.html.j2",
                  screen_id="ADM-SYS-030", domain="activity_logs",
                  crumb_group="시스템", crumb_now="작업 기록")
