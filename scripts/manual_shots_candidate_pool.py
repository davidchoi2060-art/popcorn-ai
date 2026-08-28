r"""운영자 매뉴얼용 화면 캡처 — 추천 가능 재고 현황(ADM-ENG-030, 경로 /admin2/candidate-pool).

`scripts/manual_capture_common.py`(공용 로그인·캡처·좌표 뽑기)를 그대로 쓴다 — 이 파일에는
**이 화면에만 해당하는 것**(선택자·무엇을 확대할지·이 화면 전용 통계 조회)만 있다. 공용
모듈은 고치지 않았다 — 지금 다른 넷이 각자 다른 화면을 동시에 찍고 있다.

■ 이 화면은 조회 전용이다 — 클릭 가능한 조작이 하나도 없다
    상세 서랍(categories)도, 필터 폼(reviews)도 없다. 페이지 로드 즉시
    `GET /api/admin/candidate-pool` 하나를 부르고, 그 응답 그대로 카드·표·레일을
    그린다(템플릿 자신의 주석: "이 화면은 그 응답을 그대로 그리고, **카테고리별
    통과율(ok/total)만** 자체 계산한다"). 그래서 이 스크립트는 로드 대기 하나만
    하면 되고, 클릭·입력으로 상태를 바꾸는 단계가 없다 — 서버에 쓰기 요청이 전혀
    나가지 않는다(GET만).

■★ 코드로 확인한 것 — 「사유별로 가야 하는 화면」 5개 중 4개만 실제로 눌린다
    `api/admin_ui_candidate_pool.py`의 `REASON_TARGET_PATH` 딕셔너리에 "oos"(재고
    없음) 키가 **아예 없다**. `_reason_targets()`는 없는 키를 `None`으로 처리해
    href를 비운다 — 그래서 "재고 없음 · 매입" 이동 버튼은 **코드가 아는 한 항상
    비활성**이다. 반면 `api/admin_nav.py`를 실측하면 "재고 입고"(`/admin2/
    stock-inbound`)는 2026-08-18(9차)에 이미 NAV에 올라가 있다(href 有) — 즉
    **목적지 화면 자체는 지금 존재하는데, 이 화면의 링크표가 그 사실을 모른다.**
    담당 파일(`api/admin_ui_candidate_pool.py`)이 아니므로 고치지 않고, 이 사실을
    캡처 대상으로 남긴다(아래 "go-list" 확대컷에서 5번째 행만 배경색이 다르게
    찍히는지가 그 증거다 — `a.go-btn`은 진한 배경, `span.go-btn`은 옅은 배경).
    나머지 넷(사양 미등록→상품 관리, 검수 대기·후보 미승격→상품 사양 검수,
    가격 검토 대기→가격 검토 대기 화면)은 전부 NAV에 살아 있어 실제로 이동한다.

무엇을 하는가
    1. 로컬 서버(127.0.0.1:8000 — **사장님 서버, 절대 죽이지 않는다**)에 Playwright로 접속한다.
    2. GET /api/admin/auth/dev-login 으로 점검 계정 세션을 심는다.
    3. /admin2/candidate-pool 을 열고 렌더 완료(비동기 fetch 응답 반영)를 기다린 뒤,
       전체 + 주요 영역을 PNG로 저장한다.
    4. 각 캡처 안 요소의 실측 bounding box를 좌표 JSON(candidate-pool-coords.json)에 남긴다.
    5. 문서용 실측 수치는 같은 세션으로 GET /api/admin/candidate-pool 을 한 번 더 불러
       그대로 남긴다(지어내지 않는다 — 캡처 시점의 스냅샷이라고 문서에 명시할 재료).

읽기 전용이다 — DB에 쓰지 않는다. 화면 자체에 쓰기 버튼이 없어(조회 전용 배지) 실수로
무언가를 만들 위험도 없다.

개인정보: 이 화면은 부품 종류별 집계 숫자만 다룬다. 상품명·담당자·고객 정보가 전혀
나오지 않는다(아래 "SELECT에 있지만 응답에 안 실리는 컬럼" 참고) — 가릴 것이 없다.

■ SELECT에 product_name이 있지만 응답에 실리지 않는다 — 코드로 확인
    `api/admin_pool.py`의 `_Q`가 `p.product_name`을 SELECT하지만, 이후 파이썬 루프
    (`for r in rows: ...`)가 `r["part_type"]`·`r["review_required_yn"]` 등만 읽고
    `r["product_name"]`은 한 번도 참조하지 않는다 — DB에서 퍼오기만 하고 버리는
    죽은 컬럼이다. 응답 JSON에도, 화면 어디에도 개별 상품명이 없다 — 애초에 이
    화면은 "부품 종류(카테고리) × 사유"의 **집계표**이지 상품 목록이 아니다. 개별
    상품을 알아보려면 이 화면에서 사유 칸을 눌러 다른 화면(상품 관리 등)으로 넘어가야
    하고, 거기서 비로소 상품명·상품코드가 보인다 — 제작 보고서에 남긴다.

다시 찍을 때
    .venv/Scripts/python scripts/manual_shots_candidate_pool.py
    기존 PNG·JSON을 덮어쓴다(파일명 고정) — 화면이 바뀌면 다시 찍는다.
"""
import sys

from manual_capture_common import (
    BASE, VIEWPORT, CaptureError,
    build_meta, capture_session, get_boxes, log, shoot, union_box, write_coords,
)

# 사유 5종 — 표 열 순서·상단 카드 순서·「사유별로 가야 하는 화면」 순서가 전부 같다
# (화면 JS `REASON_KEYS` 그대로: no_specs, need_review, not_candidate, no_price, oos).
REASON_KEYS = ["no_specs", "need_review", "not_candidate", "no_price", "oos"]


def main() -> int:
    coords: dict = {}
    stats: dict = {}

    try:
        with capture_session() as page:
            # ---- 1) 화면 열기 -----------------------------------------------------
            page.goto(f"{BASE}/admin2/candidate-pool", wait_until="networkidle")
            # render()의 마지막 문장이 asof 배지의 display를 바꾼다 — 그게 바뀌었다는
            # 것은 카드·표·레일 전체 렌더가 동기적으로 다 끝났다는 뜻이다(중간 상태를
            # 안 찍기 위한 대기 기준).
            try:
                page.wait_for_function(
                    "() => { var e = document.querySelector('[data-bind=\"asof\"]');"
                    " return !!e && getComputedStyle(e).display !== 'none'; }",
                    timeout=15000)
            except Exception as e:
                log(f"[FATAL] 집계 렌더가 15초 안에 안 끝났습니다(로그인 401 연쇄 가능성 — "
                    f"동시 접속 5명 중 하나일 수 있습니다): {e}")
                return 1
            page.wait_for_timeout(300)  # 레이아웃 안정화

            full_clip = {"x": 0, "y": 0, "width": VIEWPORT["width"], "height": VIEWPORT["height"]}

            # ---- 2) 전체 화면 -------------------------------------------------------
            shoot(page, "candidate-pool-full", full_clip, {
                "lnb": ".a2-lnb",
                "lnb_active_item": ".a2-lnb-b a.on",
                "header": ".a2-hd",
                "kicker": ".kicker",
                "cards": ".cards",
                "band": ".band",
                "grid_wrap": ".grid-wrap",
                "rail": ".rail",
                "foot": ".foot",
            }, coords)

            # ---- 3) 상단 헤더 확대 ----------------------------------------------------
            hdr_box = get_boxes(page, {"header": ".a2-hd"})["header"]
            if hdr_box:
                shoot(page, "candidate-pool-header", hdr_box, {
                    "crumb": ".a2-crumb",
                    "now": ".a2-now",
                    "badge_readonly": ".a2-badge:not([data-bind])",
                    "badge_asof": ".a2-badge[data-bind=\"asof\"]",
                    "hub": ".a2-hub",
                    "role_box": "#roleBox",
                    "avatar": ".a2-avatar",
                }, coords)
            else:
                log("[MISS] .a2-hd 를 못 찾았습니다 - candidate-pool-header.png 건너뜀")

            # ---- 4) 상단 카드 줄 확대(통과 카드 + 사유 5종 카드) -------------------------
            cards_box = get_boxes(page, {"cards": ".cards"})["cards"]
            if cards_box:
                el_sel = {
                    "pass_card": "[data-bind=\"pass-card\"]",
                    "pass_lbl": "[data-bind=\"pass-card\"] .lbl",
                    "pass_v": "[data-bind=\"pass-v\"]",
                    "pass_sub": "[data-bind=\"pass-card\"] .sub",
                }
                for i in range(1, 6):
                    el_sel[f"rc_{i}"] = f".reason-cards .rc:nth-child({i})"
                    el_sel[f"rc_{i}_v"] = f".reason-cards .rc:nth-child({i}) .v"
                    el_sel[f"rc_{i}_gobtn"] = f".reason-cards .rc:nth-child({i}) .go-btn"
                shoot(page, "candidate-pool-cards", cards_box, el_sel, coords)
            else:
                log("[MISS] .cards 를 못 찾았습니다 - candidate-pool-cards.png 건너뜀")

            # ---- 5) 배타 안내 띠 확대 --------------------------------------------------
            band_box = get_boxes(page, {"band": ".band"})["band"]
            if band_box:
                shoot(page, "candidate-pool-band", band_box, {
                    "band_right": "[data-bind=\"band-right\"]",
                }, coords)
            else:
                log("[MISS] .band 를 못 찾았습니다 - candidate-pool-band.png 건너뜀")

            # ---- 6) 본표(부품 종류 x 사유) 확대 ------------------------------------------
            grid_box = get_boxes(page, {"grid_wrap": ".grid-wrap"})["grid_wrap"]
            if grid_box:
                el_sel = {
                    "grid_title": ".grid-title",
                    "thead": "table.grid thead",
                    "tfoot": "table.grid tfoot",
                }
                # 실데이터 부품 종류 수만큼 행을 잡는다(최대 12행까지 대비 — core_part는
                # 보통 10종이지만 지어내지 않고 실제 행 수를 세어 그만큼만 선택자를 만든다).
                n_rows = page.eval_on_selector_all(
                    "[data-repeat=\"grid-body\"] tr", "els => els.length") or 0
                for i in range(1, min(n_rows, 12) + 1):
                    el_sel[f"row_{i}"] = f"[data-repeat=\"grid-body\"] tr:nth-child({i})"
                shoot(page, "candidate-pool-table", grid_box, el_sel, coords)
            else:
                log("[MISS] .grid-wrap 을 못 찾았습니다 - candidate-pool-table.png 건너뜀")

            # ---- 7) 우측 레일 확대(얇은 카테고리 + 결합 조건 + 사유별 이동) ------------------
            rail_box = get_boxes(page, {"rail": ".rail"})["rail"]
            if rail_box:
                shoot(page, "candidate-pool-rail", rail_box, {
                    "sec_thin": ".rail .rail-sec:nth-child(1)",
                    "sec_combined": ".rail .rail-sec:nth-child(2)",
                    "sec_golist": ".rail .rail-sec:nth-child(3)",
                    "thin_threshold_badge": "[data-bind=\"thin-threshold\"]",
                    "thin_lock_badge": ".rail .rail-sec:nth-child(1) .lock:not([data-bind])",
                }, coords)
            else:
                log("[MISS] .rail 을 못 찾았습니다 - candidate-pool-rail.png 건너뜀")

            # ---- 8) 「사유별로 가야 하는 화면」만 확대 — 활성/비활성 이동 버튼 대조 ------------
            golist_box = get_boxes(
                page, {"sec": ".rail .rail-sec:nth-child(3)"})["sec"]
            if golist_box:
                el_sel = {"title": ".rail .rail-sec:nth-child(3) h3"}
                for i in range(1, 6):
                    el_sel[f"go_row_{i}"] = f"[data-repeat=\"go-list\"] .go-row:nth-child({i})"
                    el_sel[f"go_row_{i}_btn"] = f"[data-repeat=\"go-list\"] .go-row:nth-child({i}) .go-btn"
                shoot(page, "candidate-pool-golist", golist_box, el_sel, coords)
            else:
                log("[MISS] 「사유별로 가야 하는 화면」 박스를 못 찾았습니다 - "
                    "candidate-pool-golist.png 건너뜀")

            # ---- 9) 문서용 실측 수치 — 지어내지 않고 API 응답을 그대로 남긴다 ---------------
            try:
                r1 = page.request.get(f"{BASE}/api/admin/candidate-pool")
                if r1.ok:
                    j1 = r1.json()
                    stats["pool_total"] = j1.get("pool_total")
                    stats["core_total"] = j1.get("core_total")
                    stats["ok_total"] = j1.get("ok_total")
                    stats["rate"] = j1.get("rate")
                    stats["pool_matches_ok"] = (j1.get("pool_total") == j1.get("ok_total"))
                    stats["reasons"] = j1.get("reasons")
                    stats["reason_total"] = j1.get("reason_total")
                    stats["categories"] = j1.get("categories")
                    stats["categories_n"] = len(j1.get("categories") or [])
                    stats["thin"] = j1.get("thin")
                    stats["thin_threshold"] = j1.get("thin_threshold")
                    stats["note"] = j1.get("note")
                else:
                    log(f"[MISS] GET /api/admin/candidate-pool 실패: {r1.status}")
            except Exception as e:
                log(f"[MISS] 문서용 수치 조회 실패(캡처는 이미 끝났습니다): {e}")

            # window.REASON_TARGETS — 서버 라우트가 렌더 시점에 심어 주는 값(사유별 실제
            # 이동 가능 여부). 화면 새로고침 없이 그대로 읽는다 — 지어낸 판정이 아니다.
            try:
                targets = page.evaluate("() => window.REASON_TARGETS || null")
                stats["reason_targets"] = targets
            except Exception as e:
                log(f"[MISS] window.REASON_TARGETS 읽기 실패: {e}")

    except CaptureError as e:
        log(f"[FATAL] {e}")
        return 1

    coords["_meta"] = build_meta("ADM-ENG-030", "/admin2/candidate-pool", VIEWPORT, stats)
    write_coords("candidate-pool", coords)

    if stats.get("ok_total") is not None:
        log(f"[INFO] 대상 {stats.get('core_total')} - 통과 {stats.get('ok_total')} "
            f"({stats.get('rate')}%) - pool_total {stats.get('pool_total')} "
            f"- 일치 {stats.get('pool_matches_ok')} - 카테고리 {stats.get('categories_n')}종")
    if stats.get("reasons"):
        for r in stats["reasons"]:
            t = (stats.get("reason_targets") or {}).get(r.get("key"), {})
            log(f"[INFO]   사유 {r.get('key')}({r.get('label')}) = {r.get('count')}건"
                f" - 이동가능={bool(t.get('href'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
