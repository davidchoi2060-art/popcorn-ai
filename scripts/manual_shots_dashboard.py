"""운영자 매뉴얼용 화면 캡처 - 운영 대시보드(ADM-DASH-010, 경로 /admin2/).

`scripts/manual_capture_common.py`의 공용 캡처 도구를 쓴다(그 모듈 docstring
"새 화면 캡처를 추가하려면" 절차 그대로) - 로그인/캡처/좌표 뽑기/비율 환산은
공용 모듈 것을 그대로 쓰고, 이 파일에는 이 화면(대시보드)에만 해당하는 것
(경로/선택자/무엇을 확대할지)만 남는다. 공용 모듈 자체는 고치지 않았다.

⚠ 담당 화면 혼동 주의 - `/admin2/`(이 화면, 운영 대시보드)와 `/admin2/dash`
(AI 작업 현황판, api/admin_ui_dash.py + api/dash.py)는 이름이 비슷하지만
**다른 화면**이다. 이 스크립트는 `/admin2/`(api/admin_ui_home.py가 그리는
home.html.j2)만 찍는다.

무엇을 하는가
    1. 로컬 서버(127.0.0.1:8000 - 사장님 서버, 절대 죽이지 않는다)에 Playwright로 접속한다.
    2. GET /api/admin/auth/dev-login 으로 점검 계정 세션을 심는다
       (.env 의 UI_CHECK_DEV_LOGIN=1 · UI_CHECK_EMAIL 전제 - CLAUDE.md §브라우저 점검 계정).
    3. /admin2/ 를 열고 카드 영역이 채워지길 기다린 뒤, 화면 전체 + 주요 영역을 PNG로 저장한다.
    4. 각 캡처 안 주요 요소의 "실제" bounding box를 함께 재서 dashboard-coords.json에 남긴다.
       매뉴얼 HTML의 번호 핀·테두리 상자는 이 JSON의 좌표를 %로 환산해 쓴다 - 지어내지 않는다.
    5. 문서용 실측 수치는 화면이 이미 부르는 것과 같은 API(/api/admin/dashboard 등)를
       다시 불러 그대로 남긴다.

다시 찍을 때
    화면이 바뀌면 이 스크립트를 그대로 다시 돌리면 된다.
        .venv/Scripts/python scripts/manual_shots_dashboard.py
    기존 PNG·JSON을 덮어쓴다(파일명 고정).

읽기 전용이다 - DB에 쓰지 않는다. 포트 8000에는 dev-login(GET, 세션 생성) 1회와
그 뒤 페이지 로드·API 재조회가 부르는 GET들만 나간다. 이 화면 자체에 쓰기 버튼이
없다(새로고침 버튼도 location.reload() 뿐, "지금 할 일" 카드는 전부 다른 화면으로
가는 GET 링크다) - 그래서 클릭도 실제로 누르지 않았다(이동하면 이 화면을 못 찍는다).

개인정보: 우측 상단 role 배지는 실제 고객이 아니라 점검 전용 계정("UI점검")이다.
"최근 운영자 활동" 패널에는 실제 운영자 활동 로그가 나오지만 이름은 이 회사
운영팀 계정이고, 이 화면 쿼리(api/admin_dashboard.py 실측)에는 고객
이름·이메일·전화번호 테이블 JOIN이 없다. 그래서 이 화면은 redact_* 를 쓰지
않는다(운영자·권한 화면처럼 실제 개인정보가 나오는 화면은 반드시 써야 한다).
"""
import sys

from manual_capture_common import (
    BASE, VIEWPORT, CaptureError,
    build_meta, capture_session, get_boxes, log, shoot, write_coords,
)


def main() -> int:
    coords: dict = {}

    try:
        with capture_session() as page:
            # ---- 1) 화면 열기 ------------------------------------------------------
            page.goto(f"{BASE}/admin2/", wait_until="networkidle")
            try:
                page.wait_for_selector(".dash-grid, .dash-empty", timeout=15000)
            except Exception as e:
                log(f"[FATAL] 카드 영역이 15초 안에 안 채워졌습니다: {e}")
                return 1
            page.wait_for_timeout(400)  # 막대 폭 등 렌더 안정화

            full_clip = {"x": 0, "y": 0, "width": VIEWPORT["width"], "height": VIEWPORT["height"]}

            # ---- 2) 전체 화면 --------------------------------------------------------
            shoot(page, "dashboard-full", full_clip, {
                "lnb": ".a2-lnb",
                "lnb_active_item": ".a2-lnb-b a.on",
                "header": ".a2-hd",
                "crumb": ".a2-crumb",
                "time_badge": ".dash-time",
                "refresh_btn": ".dash-refresh",
                "hub": ".a2-hub",
                "role_box": "#roleBox",
                "avatar": ".a2-avatar",
                "todo_hd": ".dash-todo-hd",
                "todo_count": ".dash-todo-hd .n b",
                "todo_note": ".dash-todo-hd .note",
                "grid": ".dash-grid",
                "card_1": ".dash-grid .dash-card:nth-child(1)",
                "card_2": ".dash-grid .dash-card:nth-child(2)",
                "card_3": ".dash-grid .dash-card:nth-child(3)",
                "card_4": ".dash-grid .dash-card:nth-child(4)",
                "card_5": ".dash-grid .dash-card:nth-child(5)",
                "flow": ".dash-flow",
                "row3": ".dash-row3",
                "panel_1": ".dash-row3 > .dash-panel:nth-child(1)",
                "panel_2": ".dash-row3 > .dash-panel:nth-child(2)",
                "panel_3": ".dash-row3 > .dash-panel:nth-child(3)",
                "foot": ".dash-foot",
            }, coords)

            # ---- 3) 헤더 확대 ---------------------------------------------------------
            hdr_box = get_boxes(page, {"header": ".a2-hd"})["header"]
            if hdr_box:
                shoot(page, "dashboard-header", hdr_box, {
                    "crumb": ".a2-crumb",
                    "now": ".a2-now",
                    "time_badge": ".dash-time",
                    "refresh_btn": ".dash-refresh",
                    "hub": ".a2-hub",
                    "role_box": "#roleBox",
                    "avatar": ".a2-avatar",
                }, coords)
            else:
                log("[MISS] .a2-hd 를 못 찾았습니다 - dashboard-header.png 건너뜀")

            # ---- 4) "지금 할 일" 카드 5개 확대 ------------------------------------------
            grid_box = get_boxes(page, {"grid": ".dash-grid"})["grid"]
            if grid_box:
                shoot(page, "dashboard-cards", grid_box, {
                    "card_1": ".dash-grid .dash-card:nth-child(1)",
                    "card_2": ".dash-grid .dash-card:nth-child(2)",
                    "card_3": ".dash-grid .dash-card:nth-child(3)",
                    "card_4": ".dash-grid .dash-card:nth-child(4)",
                    "card_5": ".dash-grid .dash-card:nth-child(5)",
                    "card_1_badge": ".dash-grid .dash-card:nth-child(1) .badge",
                    "card_4_badge": ".dash-grid .dash-card:nth-child(4) .badge",
                    "card_5_badge": ".dash-grid .dash-card:nth-child(5) .badge",
                }, coords)
            else:
                log("[MISS] .dash-grid 를 못 찾았습니다(작업 0건?) - dashboard-cards.png 건너뜀")

            # ---- 5) 오늘의 흐름 바 확대 -------------------------------------------------
            flow_box = get_boxes(page, {"flow": ".dash-flow"})["flow"]
            if flow_box:
                shoot(page, "dashboard-flow", flow_box, {
                    "consult": ".dash-flow > .metric:nth-child(2)",
                    "quoted": ".dash-flow > .metric:nth-child(4)",
                    "pending": ".dash-flow .pending",
                    "stock": ".dash-flow .stock",
                    "stock_badge": ".dash-flow .stock .badge",
                }, coords)
            else:
                log("[MISS] .dash-flow 를 못 찾았습니다 - dashboard-flow.png 건너뜀")

            # ---- 6) 하단 3패널 확대 -----------------------------------------------------
            row3_box = get_boxes(page, {"row3": ".dash-row3"})["row3"]
            if row3_box:
                el_sel = {
                    "panel_1": ".dash-row3 > .dash-panel:nth-child(1)",
                    "panel_1_hd": ".dash-row3 > .dash-panel:nth-child(1) .hd",
                    "panel_1_sample": ".dash-row3 > .dash-panel:nth-child(1) .sample",
                    "rate": ".dash-rate",
                    "rate_b": ".dash-rate b",
                    "modes": ".dash-modes",
                    "panel_2": ".dash-row3 > .dash-panel:nth-child(2)",
                    "panel_2_hd": ".dash-row3 > .dash-panel:nth-child(2) .hd",
                    "funnel": ".dash-funnel",
                    "funnel_foot": ".dash-foot-note",
                    "panel_3": ".dash-row3 > .dash-panel:nth-child(3)",
                    "panel_3_hd": ".dash-row3 > .dash-panel:nth-child(3) .hd",
                    "panel_3_link": ".dash-row3 > .dash-panel:nth-child(3) .hd .link a",
                    "logs": ".dash-logs",
                }
                for i in range(1, 4):
                    el_sel[f"mode_row_{i}"] = f".dash-modes .row:nth-child({i})"
                for i in range(1, 6):
                    el_sel[f"funnel_row_{i}"] = f".dash-funnel .row:nth-child({i})"
                for i in range(1, 4):
                    el_sel[f"log_row_{i}"] = f".dash-logs .row:nth-child({i})"
                shoot(page, "dashboard-panels", row3_box, el_sel, coords)
            else:
                log("[MISS] .dash-row3 를 못 찾았습니다 - dashboard-panels.png 건너뜀")

            # ---- 7) 문서용 실측 수치 - 지어내지 않고 API 응답을 그대로 남긴다 -------------
            stats = {}
            try:
                for key, path in (
                    ("dashboard", "/api/admin/dashboard"),
                    ("quote_quality", "/api/admin/quote-quality"),
                    ("funnel", "/api/admin/funnel"),
                    ("worklist", "/api/admin/worklist"),
                ):
                    r = page.request.get(f"{BASE}{path}")
                    if r.ok:
                        stats[key] = r.json()
                    else:
                        log(f"[MISS] {path} 응답 실패: {r.status}")
            except Exception as e:
                log(f"[MISS] 문서용 수치 조회 실패(캡처는 이미 끝났습니다): {e}")

    except CaptureError as e:
        log(f"[FATAL] {e}")
        return 1

    coords["_meta"] = build_meta("ADM-DASH-010", "/admin2/", VIEWPORT, stats)
    write_coords("dashboard", coords)

    wl = coords["_meta"]["stats"].get("worklist")
    if wl:
        log(f"[INFO] worklist total={wl.get('total')} pool={wl.get('pool')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
