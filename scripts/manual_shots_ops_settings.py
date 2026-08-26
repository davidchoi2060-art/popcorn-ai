# -*- coding: utf-8 -*-
"""운영자 매뉴얼용 화면 캡처 — 오픈 단계 설정(ADM-OPS-010, 경로 /admin2/ops-settings).

공통 부분(로그인·캡처·좌표 뽑기·비율 환산)은 `scripts/manual_capture_common.py`를 그대로
쓴다(고치지 않았다 — 다섯 명이 동시에 다른 화면을 찍는 물결이라 공용 파일은 한 명만
만진다). 이 파일에는 **이 화면에만 해당하는 것**(경로·선택자·무엇을 확대할지·클릭
순서)만 있다.

■★ 이 화면은 서비스 전체 동작을 바꾸는 스위치 화면이다 — **절대 누르지 않는다.**
    `templates/admin/ops_stage.html.j2`를 코드로 대조한 결과, 아래 넷은 클라이언트
    상태(JS 변수)만 바꿀 뿐 서버에 아무것도 보내지 않는다(`fetch`/`apiPost` 호출 없음):
        · 탭 전환(`data-action="set-tab"`)      — `S.tab`만 바뀐다
        · 축 상세 열기/닫기(`open-drawer`/`close-drawer`) — `S.drawerKey`만 바뀐다
    이 스크립트는 **이 둘만** 쓴다. 아래는 실제로 `POST /api/admin/ops-settings*`를
    부르거나 그 직전 상태를 만드는 동작이라 **한 줄도 쓰지 않는다**:
        set-mode(스위치 자체를 own/mall로 누르기) · apply-preset(프리셋 채우기) ·
        open-confirm/commit(저장) · revert(되돌리기) · undo(이력 되돌리기)
    그래서 이 스크립트가 찍는 화면은 **서버 저장을 한 번도 부르지 않고** 도달할 수 있는
    상태만 담는다 — "확인 모달"(저장 전 위험 경고)은 스위치를 먼저 눌러야 열리므로
    이 스크립트는 찍지 않는다(문서 본문은 코드 대조로 그 모달의 문구를 옮긴다).

무엇을 하는가
    1. 로컬 서버(127.0.0.1:8000 — **사장님 서버, 절대 죽이지 않는다**)에 Playwright로 접속한다.
    2. GET /api/admin/auth/dev-login 으로 점검 계정 세션을 심는다.
    3. /admin2/ops-settings 를 열고, MVP1(기본) → MVP2 → MVP3 → 단계 미정 탭을
       순서대로 눌러가며 전체·부분 캡처를 남긴다. 탭 전환·상세 열람 외에는 아무것도
       누르지 않는다(위 경고 참고).
    4. 각 캡처 안 요소의 실제 bounding box를 재서 JSON(ops-settings-coords.json)에 남긴다.

다시 찍을 때
    .venv/Scripts/python scripts/manual_shots_ops_settings.py
    기존 PNG·JSON을 덮어쓴다(파일명 고정, "ops-settings-" 접두).

개인정보: 이력 패널의 "담당자" 열이 실제 계정 이름을 보여준다. 확인 결과(읽기 전용
SELECT, 2026-08-25) 이 화면의 활동 로그에 등장하는 이름은 "관리자"·"UI점검" 둘뿐이다
(역할성 이름 — 회귀(`tests/regression.py::test_ops`)가 owner 시드 계정으로 pay를 반대로
바꿨다 되돌리는 절차를 반복해서 남긴 흔적이다). 실제 개인 이름·이메일이 아니므로
`redact_*`를 쓰지 않는다.
"""
import sys

from manual_capture_common import (
    BASE, VIEWPORT, CaptureError,
    build_meta, capture_session, get_boxes, log, shoot, union_box, write_coords,
)

# 이력·구축 축 표는 행 수가 매일 바뀐다(회귀·수동 조작이 이력을 계속 늘린다) —
# 캡처 한 장에 담을 상한만 고정한다(reviews 캡처의 TABLE_ROWS_IN_SHOT 관행과 동일).
HIST_ROWS_IN_SHOT = 6


def _click_tab(page, tab_key: str) -> None:
    page.click(f'#osTabs [data-tab="{tab_key}"]')
    page.wait_for_function(
        "(k) => { const el = document.querySelector('#osTabs [data-tab=\"' + k + '\"]');"
        " return !!el && el.classList.contains('on'); }", arg=tab_key, timeout=5000)
    page.wait_for_timeout(200)


def main() -> int:
    coords: dict = {}

    try:
        with capture_session() as page:
            # ---- 1) 화면 열기 -------------------------------------------------------
            page.goto(f"{BASE}/admin2/ops-settings", wait_until="networkidle")
            try:
                page.wait_for_selector("#osBody:not([hidden])", timeout=15000)
            except Exception as e:
                log(f"[FATAL] 화면이 15초 안에 안 열렸습니다(조회 실패 상자만 보이는 상태일 수 있음): {e}")
                return 1
            page.wait_for_timeout(400)

            full_clip = {"x": 0, "y": 0, "width": VIEWPORT["width"], "height": VIEWPORT["height"]}

            # ---- 2) 전체 화면 — 기본 진입(MVP1 탭, 전환 축 0종이 정상) -------------------
            shoot(page, "ops-settings-full", full_clip, {
                "lnb": ".a2-lnb",
                "lnb_active_item": ".a2-lnb-b a.on",
                "header": ".a2-hd",
                "stagechip": ".os-stagechip",
                "verdictnote": ".os-verdictnote",
                "hub": ".a2-hub",
                "role_box": "#roleBox",
                "avatar": ".a2-avatar",
                "tabs": "#osTabs",
                "tab_mvp1": '#osTabs [data-tab="mvp1"]',
                "tab_mvp2": '#osTabs [data-tab="mvp2"]',
                "tab_mvp3": '#osTabs [data-tab="mvp3"]',
                "tab_unmapped": '#osTabs [data-tab="unmapped"]',
                "stagenote": "#osStageNote",
                "axes_section": 'section[aria-labelledby="osAxesTitle"]',
                "no_axes": "#osNoAxes",
                "no_axes_title": "#osNoAxesTi",
                "build_section": 'section[aria-labelledby="osBuildTitle"]',
                "build_msg_mvp1": '.os-buildmsg[data-tabpanel="mvp1"]',
                "hist_section": 'section[aria-labelledby="osHistTitle"]',
                "hist_body": "#osHistBody",
                "rail": ".os-rail",
                "presets": "#osPresets",
                "legend": ".os-legend",
                "facts": ".os-facts",
                "foot": ".os-foot",
                "foot_note": "#osFootNote",
                "revert_btn": "#osRevertBtn",
                "save_btn": "#osSaveBtn",
            }, coords)

            # ---- 3) 헤더 확대 --------------------------------------------------------
            hdr_box = get_boxes(page, {"header": ".a2-hd"})["header"]
            if hdr_box:
                shoot(page, "ops-settings-header", hdr_box, {
                    "crumb": ".a2-crumb",
                    "now": ".a2-now",
                    "stagechip": ".os-stagechip",
                    "verdictnote": ".os-verdictnote",
                    "hub": ".a2-hub",
                    "role_box": "#roleBox",
                    "avatar": ".a2-avatar",
                }, coords)
            else:
                log("[MISS] .a2-hd 를 못 찾았습니다 — ops-settings-header.png 건너뜀")

            # ---- 4) 탭 + 단계 안내 배너 확대 ------------------------------------------
            tabs_clip = union_box(page, ["#osTabs", "#osStageNote"])
            if tabs_clip:
                shoot(page, "ops-settings-tabs", tabs_clip, {
                    "tab_mvp1": '#osTabs [data-tab="mvp1"]',
                    "tab_mvp2": '#osTabs [data-tab="mvp2"]',
                    "tab_mvp3": '#osTabs [data-tab="mvp3"]',
                    "tab_unmapped": '#osTabs [data-tab="unmapped"]',
                    "stagenote_mark": "#osStageNote .mark",
                    "stagenote_title": "#osStageNote .ti",
                    "stagenote_desc": "#osStageNote .ds",
                }, coords)
            else:
                log("[MISS] #osTabs/#osStageNote 를 못 찾았습니다 — ops-settings-tabs.png 건너뜀")

            # ---- 5) MVP2 탭 — 전환 축 4종(결제·환불·배송·회원)이 나타난다 ----------------
            _click_tab(page, "mvp2")
            shoot(page, "ops-settings-full-mvp2", full_clip, {
                "tab_mvp2": '#osTabs [data-tab="mvp2"]',
                "stagenote": "#osStageNote",
                "axes_list": "#osAxesList",
                "row_pay": "#osAxesList .os-axis:nth-child(1)",
                "row_refund": "#osAxesList .os-axis:nth-child(2)",
                "row_ship": "#osAxesList .os-axis:nth-child(3)",
                "row_member": "#osAxesList .os-axis:nth-child(4)",
                "build_hints_mvp2": '.os-hints[data-tabpanel="mvp2"]',
            }, coords)

            axes_box = get_boxes(page, {"axes": 'section[aria-labelledby="osAxesTitle"]'})["axes"]
            if axes_box:
                shoot(page, "ops-settings-axes-mvp2", axes_box, {
                    "axes_title": "#osAxesTitle",
                    "switch_note": "#osSwitchNote",
                    "row_1": "#osAxesList .os-axis:nth-child(1)",
                    "row_2": "#osAxesList .os-axis:nth-child(2)",
                    "row_3": "#osAxesList .os-axis:nth-child(3)",
                    "row_4": "#osAxesList .os-axis:nth-child(4)",
                    "badge_1": "#osAxesList .os-axis:nth-child(1) .os-badge",
                    "badge_2": "#osAxesList .os-axis:nth-child(2) .os-badge",
                    "badge_3": "#osAxesList .os-axis:nth-child(3) .os-badge",
                    "badge_4": "#osAxesList .os-axis:nth-child(4) .os-badge",
                    "name_1": "#osAxesList .os-axis:nth-child(1) .nm",
                    "toggle_1": "#osAxesList .os-axis:nth-child(1) .os-axistoggle",
                    "toggle_2": "#osAxesList .os-axis:nth-child(2) .os-axistoggle",
                    "toggle_3": "#osAxesList .os-axis:nth-child(3) .os-axistoggle",
                    "toggle_4": "#osAxesList .os-axis:nth-child(4) .os-axistoggle",
                    "upd_1": "#osAxesList .os-axis:nth-child(1) .upd",
                }, coords)
            else:
                log("[MISS] 전환 축 패널을 못 찾았습니다 — ops-settings-axes-mvp2.png 건너뜀")

            # ---- 6) 'pay' 축 상세 열람(읽기 전용 — 값을 누르지 않는다) ------------------
            page.click('[data-action="open-drawer"][data-key="pay"]')
            try:
                page.wait_for_selector("#osDrawer:not([hidden])", timeout=5000)
                page.wait_for_timeout(300)
            except Exception as e:
                log(f"[MISS] 'pay' 상세 패널이 안 열렸습니다: {e}")
            else:
                drawer_box = get_boxes(page, {"drawer": "#osDrawer"})["drawer"]
                if drawer_box:
                    shoot(page, "ops-settings-drawer-pay", drawer_box, {
                        "name": "#osDrawerName",
                        "key": "#osDrawerKey",
                        "verdict_badge": "#osDrawerVerdict",
                        "stage_chip": "#osDrawerStage",
                        "opts": "#osDrawerOpts",
                        "opt_own": "#osDrawerOpts .os-optcard:nth-child(1)",
                        "opt_mall": "#osDrawerOpts .os-optcard:nth-child(2)",
                        "verdict_box": "#osDrawerVerdictBox",
                        "verdict_title": "#osDrawerVerdictTitle",
                        "verdict_desc": "#osDrawerVerdictDesc",
                        "verdict_src": "#osDrawerVerdictSrc",
                        "effects": "#osDrawerEffects",
                    }, coords)
                else:
                    log("[MISS] #osDrawer 박스를 못 쟀습니다 — ops-settings-drawer-pay.png 건너뜀")
            # 닫기(읽기 전용 액션) — 다음 탭 캡처를 가리지 않도록
            if page.locator("#osDrawer:not([hidden])").count():
                page.click('[data-action="close-drawer"]')
                page.wait_for_timeout(200)

            # ---- 7) MVP3 탭 — 전환 축 1종(정산), 잠듦 배지 + 잠긴 토글 ------------------
            _click_tab(page, "mvp3")
            axes_box3 = get_boxes(page, {"axes": 'section[aria-labelledby="osAxesTitle"]'})["axes"]
            if axes_box3:
                shoot(page, "ops-settings-axes-mvp3", axes_box3, {
                    "axes_title": "#osAxesTitle",
                    "switch_note": "#osSwitchNote",
                    "row_settle": "#osAxesList .os-axis:nth-child(1)",
                    "badge_settle": "#osAxesList .os-axis:nth-child(1) .os-badge",
                    "toggle_settle": "#osAxesList .os-axis:nth-child(1) .os-axistoggle",
                }, coords)
            else:
                log("[MISS] 전환 축 패널(MVP3)을 못 찾았습니다 — ops-settings-axes-mvp3.png 건너뜀")

            # ---- 8) '단계 미정' 탭 — 구축 축 실제 표(8그룹) ----------------------------
            _click_tab(page, "unmapped")
            build_row_count = page.evaluate(
                "document.querySelectorAll('[data-tabpanel=\"unmapped\"] tbody tr').length")
            build_box = get_boxes(page, {"build": 'section[aria-labelledby="osBuildTitle"]'})["build"]
            if build_box and build_row_count:
                el_sel = {
                    "build_title": "#osBuildTitle",
                    "thead": '[data-tabpanel="unmapped"] thead',
                    "tfoot": '[data-tabpanel="unmapped"] tfoot',
                }
                for i in range(1, build_row_count + 1):
                    el_sel[f"row_{i}"] = f'[data-tabpanel="unmapped"] tbody tr:nth-child({i})'
                shoot(page, "ops-settings-buildtable", build_box, el_sel, coords)
            else:
                log(f"[MISS] 구축 축 표를 못 찾았습니다(행 {build_row_count}) — ops-settings-buildtable.png 건너뜀")

            # ---- 9) 최근 변경 이력 확대(머리글 + 앞쪽 N행) ------------------------------
            hist_row_count = page.evaluate("document.querySelectorAll('#osHistBody tr').length")
            n = min(hist_row_count, HIST_ROWS_IN_SHOT)
            if n:
                row_selectors = ["section[aria-labelledby=\"osHistTitle\"] thead"] + [
                    f"#osHistBody tr:nth-child({i})" for i in range(1, n + 1)
                ]
                hist_clip = union_box(page, row_selectors)
                if hist_clip:
                    el_sel = {
                        "hist_title": "#osHistTitle",
                        "thead": 'section[aria-labelledby="osHistTitle"] thead',
                    }
                    for i in range(1, n + 1):
                        el_sel[f"row_{i}"] = f"#osHistBody tr:nth-child({i})"
                        el_sel[f"undo_btn_{i}"] = f"#osHistBody tr:nth-child({i}) .os-undobtn"
                    shoot(page, "ops-settings-history", hist_clip, el_sel, coords)
                else:
                    log("[MISS] 이력 표 영역을 못 쟀습니다 — ops-settings-history.png 건너뜀")
            else:
                log("[MISS] 이력이 0건입니다 — ops-settings-history.png 건너뜀(빈 상태 문구만 있음)")

            # ---- 10) 우측 레일(프리셋 · 판정 기준 · 감추지 않는 사실) 확대 ---------------
            rail_box = get_boxes(page, {"rail": ".os-rail"})["rail"]
            if rail_box:
                preset_count = page.evaluate("document.querySelectorAll('#osPresets .os-preset').length")
                fact_count = page.evaluate("document.querySelectorAll('.os-facts .fact').length")
                el_sel = {
                    "presets": "#osPresets",
                    "legend": ".os-legend",
                    "facts": ".os-facts",
                }
                for i in range(1, preset_count + 1):
                    el_sel[f"preset_{i}"] = f"#osPresets .os-preset:nth-child({i})"
                for i in range(1, fact_count + 1):
                    el_sel[f"fact_{i}"] = f".os-facts .fact:nth-child({i})"
                shoot(page, "ops-settings-rail", rail_box, el_sel, coords)
            else:
                log("[MISS] .os-rail 을 못 찾았습니다 — ops-settings-rail.png 건너뜀")

            # ---- 10b) 우측 레일 아래쪽 — "감추지 않는 사실" 패널은 자체 스크롤(overflow:auto)
            # 이라 5종 전부가 1050px 뷰포트 안에 한 번에 안 들어온다(위 캡처는 앞쪽 3개까지만
            # 보인다). 그 패널만 바닥까지 스크롤해 나머지(스냅샷 경고 등)를 한 장 더 남긴다.
            scrolled = page.evaluate("""() => {
                const panel = document.querySelector('.os-rail > .os-panel:nth-child(3)');
                if (!panel) return false;
                panel.scrollTop = panel.scrollHeight;
                return true;
            }""")
            if scrolled and rail_box:
                page.wait_for_timeout(150)
                fact_count2 = page.evaluate("document.querySelectorAll('.os-facts .fact').length")
                el_sel2 = {"facts": ".os-facts"}
                for i in range(1, fact_count2 + 1):
                    el_sel2[f"fact_{i}"] = f".os-facts .fact:nth-child({i})"
                shoot(page, "ops-settings-rail-facts-more", rail_box, el_sel2, coords)

            # ---- 11) 문서용 실측 수치 — 지어내지 않고 API·DOM 값을 그대로 남긴다 --------
            stats = {}
            try:
                r = page.request.get(f"{BASE}/api/admin/ops-settings")
                if r.ok:
                    j = r.json()
                    stats["modes"] = j.get("modes")
                    stats["items"] = j.get("items")
                    stats["preset_keys"] = [p.get("key") for p in (j.get("presets") or [])]
                    stats["effects_count"] = len(j.get("effects") or [])
                    hist = j.get("history") or []
                    stats["history_count"] = len(hist)
                    stats["history_undone_count"] = sum(1 for h in hist if h.get("undone"))
                stats["nav"] = page.evaluate("""() => {
                    const el = document.getElementById('osTabs');
                    return el ? {
                        groups: el.getAttribute('data-nav-groups'),
                        total: el.getAttribute('data-nav-total'),
                        new: el.getAttribute('data-nav-new'),
                        todo: el.getAttribute('data-nav-todo'),
                    } : null;
                }""")
                stats["build_row_count"] = build_row_count
                stats["hist_row_count_shown"] = hist_row_count
            except Exception as e:
                log(f"[MISS] 문서용 수치 조회 실패(캡처는 이미 끝났습니다): {e}")

    except CaptureError as e:
        log(f"[FATAL] {e}")
        return 1

    coords["_meta"] = build_meta("ADM-OPS-010", "/admin2/ops-settings", VIEWPORT, stats)
    write_coords("ops-settings", coords)

    m = coords["_meta"]["stats"].get("modes")
    if m:
        log(f"[INFO] 현재 값 — member={m.get('member')} pay={m.get('pay')} refund={m.get('refund')}"
            f" settle={m.get('settle')} ship={m.get('ship')}"
            f" · 이력 {coords['_meta']['stats'].get('history_count')}건"
            f"(되돌려짐 {coords['_meta']['stats'].get('history_undone_count')})"
            f" · 구축 축 {coords['_meta']['stats'].get('build_row_count')}그룹")
    return 0


if __name__ == "__main__":
    sys.exit(main())
