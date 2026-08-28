r"""운영자 매뉴얼용 화면 캡처 — 조립 호환 지도(ADM-STD-020, 경로 /admin2/build-map).

`scripts/manual_capture_common.py`(공용 로그인·캡처·좌표 뽑기)를 그대로 쓴다. 이 파일에는
**이 화면에만 해당하는 것**(선택자·탭 전환·핀 고정·이 화면 전용 통계 조회)만 있다. 공용
모듈은 고치지 않았다 — 지금 다른 네 명이 각자 다른 화면을 동시에 찍고 있다.

■★ 화면 이름이 두 개다(실측 그대로 기록 — 문서 `docs/design/req/req-build-map.md` 32~40행
    이 이미 지적한 사실과 일치) — 좌측 메뉴(`api/admin_nav.py`)의 항목명은 "조립 호환
    지도"인데, 이 화면 자신(`<title>`·breadcrumb `.a2-now`·`api/admin_ui_build_map.py`의
    `crumb_now`)은 전부 "조립 호환 조감도"라고 표시한다. 이 스크립트는 두 값을 모두
    실측해 `_meta.stats`에 남긴다(어느 쪽도 지어내지 않는다) — 매뉴얼 문서가 이 불일치를
    설명할 때 실제 문자열을 그대로 인용할 수 있게 하기 위함이다.

■★ 세 가지 표현(탭) — 이 화면 하나가 지도형·진단형·매트릭스형 세 탭을 갖고 있고,
    셋 다 **같은 API 응답 한 번**(`GET /api/admin/std/compat-map`)으로 그려진다(탭 전환은
    `hidden` 속성만 바꿀 뿐 다시 조회하지 않음 — 코드 확인). 그래서 이 스크립트도 조회는
    한 번만 하고, 탭마다 버튼을 눌러 화면을 전환하며 캡처한다.

■★ 대상 고정(pin, UX-20 보강) — 부품 노드를 클릭하면 고정되고 **탭을 바꿔도 유지된다**
    (`templates/admin/build_map.html.j2`의 `sel = hover || pin`, `data-part` 클릭 위임).
    이 스크립트는 지도형 탭에서 부품 하나를 클릭해 고정한 뒤, 그 상태로 진단형·매트릭스형
    탭까지 전환하며 캡처한다 — "탭을 바꿔도 대상을 잃지 않는다"는 요구사항(req-build-map.md
    §⑥)이 실제로 지켜지는지를 캡처로 남긴다. 어떤 부품을 고정할지는 하드코딩하지 않고,
    캡처 시점에 API 응답을 직접 읽어 "규칙 미등록(norule)" 관계가 걸린 부품을 우선
    고른다(실무적으로 가장 흥미로운 상태 — "값은 찼는데 아무도 막지 않는다") — 없으면
    "사양 값 부족(missing)", 그것도 없으면 첫 번째 부품으로 물러선다. 즉 데이터가 바뀌어도
    스크립트가 죽지 않는다.

읽기 전용이다 — DB에 쓰지 않는다. 이 화면 자체가 "쓰기 API가 없다"(정의서 §④). 이 스크립트가
누르는 것은 탭 버튼과 부품 노드(고정)뿐이고 둘 다 클라이언트 상태만 바꾼다(코드 확인 —
`fetch`는 최초 1회뿐, 탭·핀 전환에서 추가 네트워크 요청이 없다).

개인정보: 이 화면은 관계·사양 충족률만 다룬다. 사람 이름·이메일이 없다 — 상단 roleBox·avatar는
dev-login 점검 계정("UI점검") 자신이라 가리지 않는다(reviews·categories 화면과 같은 이유).

다시 찍을 때
    .venv/Scripts/python scripts/manual_shots_build_map.py
    기존 PNG·JSON을 덮어쓴다(파일명 고정) — 화면이 바뀌면 다시 돌린다.
"""
import sys

from manual_capture_common import (
    BASE, VIEWPORT, CaptureError,
    build_meta, capture_session, get_boxes, log, shoot, write_coords,
)

STATUS_KO = {
    "checking": "검사 적용", "norule": "규칙 미등록",
    "missing": "사양 값 부족", "out": "범위 밖",
}


def _ascii_log(s) -> str:
    """콘솔 로그용 — cp949가 못 먹는 문자를 ASCII로 치환한다(CLAUDE.md 「함정」)."""
    return (str(s).replace("—", "-").replace("–", "-")
            .replace("→", "->").replace("↔", "<->").replace("📌", "[pin]"))


def _pick_pin_target(data: dict):
    """API 응답에서 고정할 부품을 고른다 — 하드코딩하지 않고 실측한다.

    우선순위: norule(규칙 미등록) 관계에 걸린 부품 > missing(사양 값 부족) > 첫 부품.
    반환: (part_type, 근거 status 또는 None, 그 관계 pair_key 또는 None)
    """
    parts = data.get("parts") or []
    pairs = data.get("pairs") or []
    part_types = {p["part_type"] for p in parts}
    for want in ("norule", "missing", "checking"):
        for pr in pairs:
            if pr.get("status") != want:
                continue
            for side in (pr.get("left_part"), pr.get("right_part")):
                if side in part_types:
                    return side, want, pr.get("pair_key")
    if parts:
        return parts[0]["part_type"], None, None
    return None, None, None


def main() -> int:
    coords: dict = {}
    stats: dict = {}

    try:
        with capture_session() as page:
            # ---- 0) 같은 API를 직접 조회 — 화면이 쓰는 것과 같은 원천, 핀 대상 선정용 ----
            api_resp = page.request.get(f"{BASE}/api/admin/std/compat-map")
            if not api_resp.ok:
                log(f"[FATAL] GET /api/admin/std/compat-map 실패: {api_resp.status}")
                return 1
            api_data = api_resp.json()
            pin_part, pin_reason, pin_pair_key = _pick_pin_target(api_data)
            s = api_data.get("summary") or {}
            stats["summary"] = s
            stats["part_count"] = len(api_data.get("parts") or [])
            stats["pin_target"] = {"part_type": pin_part, "reason": pin_reason, "pair_key": pin_pair_key}
            log(f"[INFO] compat-map 실측: pairs_total={s.get('pairs_total')} "
                f"in_scope={s.get('pairs_in_scope')} checked={s.get('pairs_checked')} "
                f"ready={s.get('pairs_ready')} specs_total={s.get('specs_total')} "
                f"parts={stats['part_count']}")
            log(f"[INFO] 핀 고정 대상 선정: {pin_part} (근거 status={pin_reason}, pair={pin_pair_key})")

            # ---- 1) 화면 열기 --------------------------------------------------------
            page.goto(f"{BASE}/admin2/build-map", wait_until="networkidle")
            try:
                page.wait_for_function(
                    "document.querySelector('[data-bind=\"asof\"]') && "
                    "document.querySelector('[data-bind=\"asof\"]').textContent !== '—'",
                    timeout=15000)
            except Exception as e:
                log(f"[FATAL] 데이터가 15초 안에 안 채워졌습니다: {e}")
                return 1
            page.wait_for_timeout(300)

            # 이름 불일치 실측 — 지어내지 않고 그대로 남긴다.
            title_text = page.title()
            now_text = page.eval_on_selector(".a2-now", "el => el.textContent") if \
                get_boxes(page, {"now": ".a2-now"})["now"] else None
            stats["title"] = title_text
            stats["breadcrumb_now"] = now_text
            log(f"[INFO] 화면 표시 이름 실측: <title>={_ascii_log(title_text)!r} "
                f"breadcrumb-now={_ascii_log(now_text)!r} (좌측 메뉴 라벨은 '조립 호환 지도')")

            full_clip = {"x": 0, "y": 0, "width": VIEWPORT["width"], "height": VIEWPORT["height"]}

            # ---- 2) 전체 화면 — 지도형(기본 탭), 핀 없음 ------------------------------
            shoot(page, "build-map-full", full_clip, {
                "lnb": ".a2-lnb",
                "lnb_active_item": ".a2-lnb-b a.on",
                "header": ".a2-hd",
                "crumb": ".a2-crumb",
                "now": ".a2-now",
                "tab_map": '.tab[data-view="map"]',
                "tab_diag": '.tab[data-view="diag"]',
                "tab_matrix": '.tab[data-view="matrix"]',
                "asof": '[data-bind="asof"]',
                "hub": ".a2-hub",
                "role_box": "#roleBox",
                "avatar": ".a2-avatar",
                "pinbar": ".pinbar",
                "stats_row": '[data-repeat="stats"]',
                "map_area": ".map-area",
                "legend": ".legend",
                "rail": ".rail",
            }, coords)

            # ---- 3) 헤더 확대 ----------------------------------------------------------
            hdr_box = get_boxes(page, {"header": ".a2-hd"})["header"]
            if hdr_box:
                shoot(page, "build-map-header", hdr_box, {
                    "crumb": ".a2-crumb",
                    "now": ".a2-now",
                    "tab_map": '.tab[data-view="map"]',
                    "tab_diag": '.tab[data-view="diag"]',
                    "tab_matrix": '.tab[data-view="matrix"]',
                    "asof": '[data-bind="asof"]',
                    "hub": ".a2-hub",
                    "role_box": "#roleBox",
                    "avatar": ".a2-avatar",
                }, coords)
            else:
                log("[MISS] .a2-hd 를 못 찾았습니다 - build-map-header.png 건너뜀")

            # ---- 4) 지도 영역 확대(SVG 관계선 + 노드 + 범례) ----------------------------
            map_box = get_boxes(page, {"map_area": ".map-area"})["map_area"]
            if map_box:
                shoot(page, "build-map-mapview", map_box, {
                    "legend": ".legend",
                    "node_cpu": '.node[data-part="CPU"]',
                    "node_ssd": '.node[data-part="SSD"]',
                }, coords)
            else:
                log("[MISS] .map-area 를 못 찾았습니다 - build-map-mapview.png 건너뜀")

            # ---- 5) 우측 레일 확대(부품별 충족률 + 관계 목록, 핀 없음) --------------------
            rail_box = get_boxes(page, {"rail": ".rail"})["rail"]
            if rail_box:
                shoot(page, "build-map-rail", rail_box, {
                    "cap_parts": ".rail .cap:first-of-type",
                    "rail_parts": '[data-repeat="rail-parts"]',
                    "rail_title": '[data-bind="rail-title"]',
                    "rail_rels": '[data-repeat="rail-rels"]',
                }, coords)
            else:
                log("[MISS] .rail 을 못 찾았습니다 - build-map-rail.png 건너뜀")

            # ---- 6) 부품 고정(pin) — 지도형 탭에서 클릭 ---------------------------------
            pinned_ok = False
            if pin_part:
                target = page.locator(f'.prow[data-part="{pin_part}"]').first
                try:
                    target.click(timeout=5000)
                    page.wait_for_timeout(250)
                    pinned_ok = True
                except Exception as e:
                    log(f"[MISS] 부품 고정 클릭 실패({pin_part}): {e}")

            if pinned_ok:
                shoot(page, "build-map-pin-full", full_clip, {
                    "pinbar": ".pinbar",
                    "pin_clear_btn": '[data-action="clear-pin"]',
                    "node_pinned": f'.node[data-part="{pin_part}"]',
                    "rail_title": '[data-bind="rail-title"]',
                }, coords)

                rail_box2 = get_boxes(page, {"rail": ".rail"})["rail"]
                if rail_box2:
                    shoot(page, "build-map-pin-rail", rail_box2, {
                        "rail_parts": '[data-repeat="rail-parts"]',
                        "prow_pinned": f'.prow[data-part="{pin_part}"]',
                        "rail_title": '[data-bind="rail-title"]',
                        "rail_rels": '[data-repeat="rail-rels"]',
                    }, coords)
                else:
                    log("[MISS] 핀 이후 .rail 을 못 쟀습니다 - build-map-pin-rail.png 건너뜀")
            else:
                log("[MISS] 핀 고정에 실패해 pin-full/pin-rail 캡처를 건너뜁니다")

            # ---- 7) 진단형 탭 — 핀이 유지된 채로 전환 -----------------------------------
            page.locator('[data-action="view"][data-view="diag"]').click()
            page.wait_for_timeout(300)
            body_box = get_boxes(page, {"body": ".body"})["body"]
            diag_clip = body_box or full_clip
            shoot(page, "build-map-diag", diag_clip, {
                "gap": ".gap",
                "g_checked": '[data-bind="g-checked"]',
                "g_scope": '[data-bind="g-scope"]',
                "g_text": '[data-bind="g-text"]',
                "lanes": '[data-repeat="lanes"]',
                "diag_parts": '[data-repeat="diag-parts"]',
                "pinbar": ".pinbar",
            }, coords)

            lane1_box = get_boxes(page, {"lane1": '[data-repeat="lanes"] > .lane:nth-child(1)'})["lane1"]
            if lane1_box:
                shoot(page, "build-map-diag-lane", lane1_box, {
                    "lane_hd": '[data-repeat="lanes"] > .lane:nth-child(1) .lane-hd',
                    "lcard_1": '[data-repeat="lanes"] > .lane:nth-child(1) .lcard:nth-child(1)',
                }, coords)
            else:
                log("[MISS] 첫 레인(규칙 미등록)을 못 찾았습니다 - build-map-diag-lane.png 건너뜀")

            # ---- 8) 매트릭스형 탭 — 핀이 유지된 채로 전환 --------------------------------
            page.locator('[data-action="view"][data-view="matrix"]').click()
            page.wait_for_timeout(300)
            body_box2 = get_boxes(page, {"body": ".body"})["body"]
            matrix_clip = body_box2 or full_clip
            shoot(page, "build-map-matrix", matrix_clip, {
                "m_checked": '[data-bind="m-checked"]',
                "m_scope": '[data-bind="m-scope"]',
                "legend_cards": '[data-repeat="legend-cards"]',
                "mx_cols": '[data-repeat="mx-cols"]',
                "mx_rows": '[data-repeat="mx-rows"]',
                "heat_rows": '[data-repeat="heat-rows"]',
                "pinbar": ".pinbar",
            }, coords)

            grid_box = get_boxes(
                page, {"grid": 'section[data-view-panel="matrix"] .split > div.card'})["grid"]
            if grid_box:
                shoot(page, "build-map-matrix-grid", grid_box, {
                    "mx_cols": '[data-repeat="mx-cols"]',
                    "mx_rows": '[data-repeat="mx-rows"]',
                    "row_pinned": f'[data-repeat="mx-rows"] [data-part="{pin_part}"]' if pin_part else '[data-repeat="mx-rows"] > div:first-child',
                }, coords)
            else:
                log("[MISS] 매트릭스 격자 카드를 못 찾았습니다 - build-map-matrix-grid.png 건너뜀")

    except CaptureError as e:
        log(f"[FATAL] {e}")
        return 1

    coords["_meta"] = build_meta("ADM-STD-020", "/admin2/build-map", VIEWPORT, stats)
    write_coords("build-map", coords)

    s = stats.get("summary") or {}
    log(f"[INFO] 문서용 실측 요약 - pairs_total={s.get('pairs_total')} "
        f"in_scope={s.get('pairs_in_scope')} checked={s.get('pairs_checked')} "
        f"ready={s.get('pairs_ready')} specs_total={s.get('specs_total')} "
        f"parts={stats.get('part_count')} "
        f"title={_ascii_log(stats.get('title'))!r} now={_ascii_log(stats.get('breadcrumb_now'))!r} "
        f"pin={stats.get('pin_target')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
