"""ADM-SYS-020 운영자 · 권한 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery).

화면 자체는 `docs/design/dc-operators-roles.html`(사장님 Claude Design 승인 원안)을
`templates/admin/operators_roles.html.j2`로 옮긴 것이다. 요구사항 정의서:
`docs/design/req/req-operators-roles.md`.

■ 데이터 API — 새로 만들지 않았다. 이미 구현·실사용 중이던 것을 그대로 소비한다.
  `GET /api/admin/operators` · `POST /api/admin/operators/{id}/approve` ·
  `POST /api/admin/operators/{id}/role` · `POST /api/admin/operators/{id}/suspend` ·
  `POST /api/admin/operators/{id}/email` (전부 `api/admin_operators.py`) ·
  `POST /api/admin/auth/operators/{id}/password` · `GET /api/admin/auth/password-policy`
  (전부 `api/auth.py`). 전부 **읽기만** 했다 — 이 화면 작업으로 두 API 파일은 손대지 않았다.

■ 이 화면은 목록 조회부터 owner 전용이다(`api/auth.py` `required_role()`:
  `/api/admin/operators`는 GET도 owner — "계정 목록은 민감"). 그래서 서버 응답이
  403이면 그대로 "권한 부족" 화면을 보여준다 — 클라이언트가 먼저 등급을 판정해
  감추는 방식을 쓰지 않는다(서버가 최종 판정자). 반대로 **본문이 그려졌다는 것
  자체가 이미 owner임을 서버가 증명한 것**이므로, 본문 안의 개별 동작 버튼들은
  "등급이 owner인가"를 다시 검사하지 않는다(다른 admin2 화면들과 다른 점 — 거기는
  GET이 열려 있어 화면은 보이는데 쓰기만 막혀서 매 버튼마다 등급 검사가 필요하다).
  대신 **자기 계정 강등/정지 금지·마지막 owner 정지 금지**처럼 등급과 무관한
  업무 규칙만 클라이언트에서도 미리 막아 `title`로 이유를 보여준다.

■★ 원안에 있는 "접근 IP 허용" 탭은 백엔드가 없다(실측 2026-08-14 —
  `api/admin_operators.py`·`api/auth.py`는 물론 `api/` 전체에 cidr·ip_allow·
  allowlist류 코드가 0건이다). 디자인 원안(`dc-operators-roles.html`)의 그 탭은
  DCLogic 목업 안에 하드코딩된 예시 배열(`this.state.ips`)일 뿐 실제 서버 자원이
  아니다. CANON "숫자를 지어내지 않는다" 원칙에 따라 그 탭을 가짜로 동작하게
  만들지 않고 "향후 사용예정" 안내로 비워 두었다(탭 자체와 자리는 원안대로
  유지) — 상세 근거는 템플릿 상단 주석과 제작 보고서 참조.

■★ 정지된 계정도 이 화면에서 다시 살릴 수 있다 — 요구사항 정의서 ⑤가 놓친 부분.
  `POST /operators/{id}/approve`의 서버 코드는 `status == '활성'`일 때만 409를
  던진다(`대기`뿐 아니라 `정지`도 통과한다). 요구사항 정의서 §④ 표는 "대기→활성"
  이라고만 적어 두었지만 코드는 더 넓게 허용한다 — 코드를 그대로 따라 이 화면은
  정지 계정에도 "정지 해제" 동작을 노출한다(문서보다 코드를 믿으라는 지시에 따른
  판단, 제작 보고서에 근거를 남김).

■ 좌측 메뉴(LNB) — `api/admin_nav.py`의 "시스템" 그룹 "운영자 · 권한" 항목은
  이 라우트가 만들어진 시점에도 여전히 `href=None`(신설 예정)이다. 그 파일은 이
  작업의 담당 범위 밖이라 고치지 않았다 — href를 `/admin2/operators`로 올려야
  LNB에서 이 화면으로 갈 수 있다(제작 보고서에 남김).
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/operators", response_class=HTMLResponse)
def operators_roles(request: Request) -> HTMLResponse:
    """운영자 · 권한(ADM-SYS-020).

    승인 게이트 + 권한 관리 — owner 전용(조회조차). 활성 계정 전량이 owner인 지금
    분포에서 "누가 어떤 등급인지"·"정지 계정이 몇인지"가 한눈에 들어오게 보여준다.
    """
    return render(request, "admin/operators_roles.html.j2",
                  screen_id="ADM-SYS-020", domain="operators_roles",
                  crumb_group="시스템", crumb_now="운영자 · 권한")
