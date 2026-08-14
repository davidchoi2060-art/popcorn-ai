"""견적 상담 기록(ADM-ORD-010) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery)."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/consult-sessions", response_class=HTMLResponse)
def consult_sessions(request: Request) -> HTMLResponse:
    """견적 상담 기록(ADM-ORD-010) — **신설**. 사장님 확정(2026-08-14): 1a 기준 + 우측 서랍(1b).

    계약 = `docs/design/spec-consult-sessions.md`. 기준은 1a(KPI 5장 · 방식 칩 · 목록 표 ·
    페이지네이션)이고, 상세는 1a의 행 아래 펼침 대신 **1b의 우측 서랍**으로 낸다(사장님
    지시: "1a 안을 기준으로 만드는데, 오른편에서 상세 창이 나오는 것은 포함시켜줘").

    조회 전용(읽기 전용 관측창) — 쓰기 API 를 호출하지 않는다.

    ■ 데이터 원천은 여전히 `api/admin_sessions.py`(`GET /api/admin/sessions`) — 이 화면
    자신은 데이터를 조회하지 않는다(정본 그대로, 이 파일은 페이지 라우트만 갖는다).

    ■ 2026-08-15 갱신 — API 가 handoffs·방문자 키·전체 집계를 갖춰 이전 간극 넷이
    해소됐다(실측: dev-login 후 `GET /api/admin/sessions` 직접 호출 + DB 직접 COUNT
    대조. 세션 4315·4247 를 표본으로 확인):

      ① handoffs 연결        쿼리가 이제 `handoffs` 를 세션당 최신 1건으로 LEFT JOIN
                             한다(`DISTINCT ON (session_id) ... ORDER BY session_id,
                             handoff_id DESC`). 응답 아이템에 `handoff_no·
                             handoff_status·handoff_total_quoted·handoff_total_mall·
                             handoff_price_checked·handoff_at` 6키가 채워진다(세션
                             4247 은 인계 2건 중 최신 HO-1002 가 선택됨을 DB 직접
                             대조로 검증). **서버 `status` 문자열 자체는 여전히 주문
                             전용 계산이다** — 세션 4315·4247 처럼 실제로 인계됐어도
                             `status`는 그대로 "완주"로 온다(API 제작자가 이 계산
                             로직은 건드리지 않았다고 명시). 이 화면은 원래도 `status`
                             원문을 표시에 그대로 쓰지 않고 `snapshots`/`order_no`
                             유무로 자체 4종 상태를 파생해 왔으므로(`statusMeta()`,
                             계약 "상태 4종"), 그 파생에 `handoff_no` 가지를 추가해
                             "완주 → 인계(handoffs)"를 만든다 — **서버 값은 덮어쓰지
                             않는다.**
      ② 전체 건수            `total`(consult_sessions 전체 행수, 실측 4,821건 — 매일
                             증가)·`done_total`·`drop_total`(전체 기준 완주/이탈,
                             `done_total + drop_total == total`)이 추가됐다. "전체
                             세션" KPI 와 완주율/이탈의 1차 분모를 전체 기준으로
                             채운다.
      ③ 창(窓) 기준 병기      기존 `done`/`drop`(이 페이지 LIMIT 행 안에서만 집계)은
                             그대로 남아 있다 — 전체 기준과 섞지 않고 각 KPI 에
                             두 기준을 함께 라벨로 밝힌다.
      ④ 방문자 키            아이템에 `user_id`(FK `users`, 익명 발급 — **회원이
                             아니다**)가 채워진다. 서랍 머리에 "방문자 키"로 표기하고
                             회원과 구분한다.

    `offset` 파라미터도 추가됐다(기본 0, API 제작자가 `?offset=5`의 `items[0]` ==
    `?offset=0`의 `items[5]`를 HTTP 레벨로 검증). 이 화면은 이제 실제 이전/다음 페이지
    이동을 붙인다 — 서버가 이미 지원하는데 화면만 잠가 두고 "백엔드 확장 후 열립니다"
    라고 말하면 그 안내 자체가 거짓이 된다(화면 정직성). 기간 필터는 API 가 여전히
    받지 않으므로 그 잠금만 유지한다.

    이 화면은 API 가 실제로 주는 값만으로 조립했고, 계약 문구(원안 예시 수치
    4,419·154·93.1%·303·16·3·3,488·928·3·0 등)를 코드에 박지 않았다(MAKER-CHECKLIST §1).

    ■ 2026-08-15(같은 날 2차) — 확인자가 실측으로 잡은 결함 둘. 담당 파일이 셋으로
    넓혀져 `api/admin_sessions.py`(서버 쿼리)도 함께 고쳤다(그 파일 자체 주석 참조):

      ① `rows`(LIMIT/OFFSET)와 `total`이 서버에서 별개 SELECT라 그 사이 세션이 늘면
         어긋나는 레이스가 실측 재현됐다(offset=4800에서 total=4918·items=117 →
         4800+117=4917≠4918). 서버는 REPEATABLE READ로 대부분 막고, 화면은
         `renderPagerInfo()`가 "마지막 페이지인가"를 total 비교가 아니라 이번 응답
         자체(N<limit)로만 판단하게 해 `pnow`/`nextBtn`이 항상 같은 근거를 쓴다.
      ② 6열 그리드 최소 합(866px)이 `@media (max-width:768px)` 상한보다 넓은
         769~1130px 구간(확인자 실측 1000×900: `#csScroll` scrollWidth 899 vs
         clientWidth 788)에서 콘텐츠 패널이 몰래 가로 스크롤됐다. `@media`를 확인
         상한(1130px)까지 넓혀 이미 검증된 단일 열 표기로 막는다.
    """
    return render(request, "admin/consult_sessions.html.j2",
                  screen_id="ADM-ORD-010", domain="consult-sessions",
                  crumb_group="상품사양관리", crumb_now="견적 상담 기록")
