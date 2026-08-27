"""요청 · 승인(ADM-SYS-060 · 제안) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery).

승인 디자인 `docs/design/dc-work-request.html` 은 두 안(1a·1b)을 나란히 담고 있는데
**사장님이 1b(상태별 레인)를 고르셨다** — `data-screen-label="1b 상태별 레인"` 안쪽만
구현 대상이고 1a 는 참고만 한다(하네스 지시서).

■ ⚠ README 는 1a 를 추천했는데 사장님은 1b 를 고르셨다 — 이것은 뒤집힌 결정이 아니다
  README 자신이 조건을 달아 뒀다: 「결정 5(하네스 알림)가 미정인 동안은 1b 가 낫다 —
  알림이 없으면 요청이 「접수」에 며칠 머무는데 레인은 그 정체를 숨기지 못한다」
  (하네스 지시서가 그대로 옮긴 문구). 지금 이 코드에도 그 사실이 그대로 남아 있다 —
  `api/admin_requests.py`의 `requests_meta()`가 `harness_notify.configured=false`를
  내려보내고, 이 화면은 그 값을 상단 띠로 그대로 드러낸다(아래 JS `notify` 처리 참조).
  **알림 수단이 정해지면(결정 5 해소) 이 조건이 사라지므로 1a 재검토 여지가 열린다** —
  이 주석이 그 경위를 남긴다.

■ 화면 구성·색·서체·간격은 원안 그대로 옮기고, 런타임만 순수 JS 로 바꿨다
  (`admin_ui_reviews.py` 가 세운 관례와 같다). 원안은 `<x-dc>`+`DCLogic`+더미 배열
  (`REQS`·`THREAD`)로 렌더하는 캔버스 전용 형식이라 여기서는 돌지 않는다 — 더미 대신
  전부 `GET/POST /api/admin/requests*` 실측 응답을 쓴다.

■ 나머지 요구사항 정의서 항목(⑤~⑨)의 구현 위치
    ④ 표 셋               db/migrations/versions/0070_admin_requests.py
    ⑤ 기능 · ⑥ 직원 시야    api/admin_requests.py(GET/POST 전부)
    ⑦ 방치 배지 · 상단 띠   이 템플릿의 `staleBanner`/`is_stale` 렌더 — 기준은
                           `GET .../meta`의 `stale_days`(설정값, 화면이 지어내지 않는다)
    ⑧ 판정 근거를 남긴다    상세 패널의 `verdict_note` 표시 + 스레드의 `[판정: …]` 댓글
    ⑨ 실패를 완료로 만들지 않는다   `resolve` 실패 시 상태 불변 + 스레드에 `[처리 실패]` 댓글

■ 좌측 메뉴는 아직 안 건다 — 하네스 지시서: 「메뉴에 거는 것은 검증 뒤에」
  (`api/admin_nav.py` 는 손대지 않았다). 화면은 이 경로(`/admin2/requests`)로 직접
  열어야 보인다 — 검증 통과 후 archivist 가 `admin_nav.NAV` 에 항목을 추가한다.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render
from .auth import COOKIE, resolve_session

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/requests", response_class=HTMLResponse)
def requests_screen(request: Request) -> HTMLResponse:
    """요청 · 승인(ADM-SYS-060 · 제안) — 1b 상태별 레인. 사장님 확정 안(2026-08-27).

    ■ 2026-08-27 정정(확인자 실측 결함① 수정) — owner 전용 두 구역(「하네스 판정 · 처리」·
      「사장님 결재」)을 예전에는 JS `hidden` 토글로만 감췄다. 직원 세션에서도 DOM 에는
      두 구역이 그대로 실려 있어, 개발자 도구로 `hidden` 속성만 지우면 결재 절차 UI 와
      내부 운영 방침 문구가 그대로 열렸다(API 는 403 으로 막혀 있어도 화면은 열렸다).
      지금은 **서버 렌더 시점**에 role 을 판정해 템플릿에 `is_owner`를 넘기고,
      템플릿(`templates/admin/requests.html.j2`)이 `{% if is_owner %}`로 그 두 구역을
      **아예 렌더하지 않는다** — 직원 세션에는 두 구역의 노드 자체가 DOM 에 없다.
      `resolve_session`을 한 번 더 부르는 것은 `admin_ui_home.py`·`admin_ui_handoff_log.py`
      와 같은 관례다(§`auth.py`의 `_current` 컨텍스트변수는 쓰기 라우트의 감사기록
      주체 전달용으로 도입된 것이라, 페이지 렌더에서 신원이 필요한 기존 두 화면도
      컨텍스트변수에 기대지 않고 직접 재조회했다 — 이 화면도 그 전례를 따른다).
      이 경로는 이미 `auth_middleware`가 최소 viewer 등급으로 막아 둔 뒤라 세션은
      항상 있지만, 방어적으로 `op is None`도 `is_owner=False`로 처리한다.
      JS 의 `hidden` 토글은 owner 세션 안에서 요청 상태(접수/검토/처리/승인/닫힘)에
      따라 두 구역을 접었다 펴는 용도로만 남았다 — 없는 노드를 만지면 예외가 나
      화면 전체가 죽으므로 null 가드를 추가했다(같은 파일 JS 참조).
    """
    op = resolve_session(request.cookies.get(COOKIE, ""))
    is_owner = bool(op and op.get("role") == "owner")
    return render(request, "admin/requests.html.j2",
                  screen_id="ADM-SYS-060", domain="requests",
                  crumb_group="시스템", crumb_now="요청 · 승인",
                  is_owner=is_owner)
