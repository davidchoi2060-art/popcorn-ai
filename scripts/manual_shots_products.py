"""운영자 매뉴얼용 화면 캡처 — 상품 관리(ADM-PRD-010, 경로 /admin2/products).

2026-08-25 신설 — `scripts/manual_capture_common.py`의 모듈 docstring §「새 화면 캡처를
추가하려면」 절차 그대로: 공통 부분(로그인·캡처·좌표 뽑기·비율 환산)은 공용 모듈에서
가져오고, 이 파일에는 **이 화면에만 해당하는 것**(경로·선택자·무엇을 확대할지)만 둔다.
공용 모듈은 다섯 명이 동시에 쓰므로 고치지 않는다.

무엇을 하는가
    1. 로컬 서버(127.0.0.1:8000 — **사장님 서버, 절대 죽이지 않는다**)에 Playwright로 접속한다.
    2. GET /api/admin/auth/dev-login 으로 점검 계정 세션을 심는다.
    3. /admin2/products 를 열고 목록이 채워지길 기다린 뒤, 전체·헤더·필터·표·일괄선택·
       상세 서랍(기본/사양/공급처 탭)·등록 서랍을 PNG로 저장한다.
    4. 각 캡처 안 주요 요소의 "실제" bounding box를 함께 재서 JSON(products-coords.json)에 남긴다.

다시 찍을 때
    화면이 바뀌면 이 스크립트를 그대로 다시 돌리면 된다.
        .venv/Scripts/python scripts/manual_shots_products.py
    기존 PNG·JSON을 덮어쓴다(파일명 고정).

읽기 전용이다 — **DB에 쓰지 않는다.** 이 화면은 등록·수정·일괄 상태 변경·삭제 등 실제
쓰기 API를 여럿 갖고 있는데, 이 스크립트는 그중 어느 것도 호출하지 않는다:
  · 체크박스 선택(일괄 변경 바 캡처용)은 순수 DOM 상태(SEL 객체)만 바꾸고 서버에
    아무 요청도 보내지 않는다 — "상태 바꾸기"·"되돌리기" 버튼은 누르지 않는다.
  · 상세 서랍의 [수정]을 눌러 편집 모드 화면은 찍지만(이것도 fetch 없이 클라이언트
    상태만 바뀐다), **[저장]은 절대 누르지 않는다** — 편집을 마치면 [취소]로 되돌린다.
  · 등록 서랍은 열어서 빈 초기 상태만 찍는다 — 이름을 입력하지 않고, [등록]·
    [그래도 등록]은 누르지 않는다(실제로 새 상품이 생긴다 — 운영 DB와 같은 DB다).
  · 상세를 여는 것(GET /api/admin/products/{code})과 탭 전환은 전부 읽기다.

개인정보: 이 화면은 상품(제조사·공급처·가격·재고·사양)만 다룬다 — 고객 이름·이메일·
전화번호가 나타나는 자리가 없다. 우측 상단 역할 표시는 실제 고객이 아니라 점검
전용 계정("UI점검")이다. 그래서 `redact_*`를 쓰지 않는다(운영자·권한 화면 등 실제
사람 이름이 나오는 화면은 반드시 써야 한다 — 공용 모듈 docstring 참고).
"""
import sys

# 콘솔이 cp949라 이 화면의 서버 응답 문구(예: gate_note 안의 "—") 자체가 em-dash를
# 담고 있으면 log()의 print()가 UnicodeEncodeError로 죽는다(2026-08-25 실측 — 내
# 로그 문자열이 아니라 서버가 돌려준 자유 텍스트가 원인이라 문자열을 ASCII로 바꿔도
# 못 막는다). 이 스크립트 프로세스에서만 stdout을 UTF-8로 바꿔 근본적으로 막는다 —
# 공용 모듈(manual_capture_common.log)은 고치지 않는다.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from manual_capture_common import (
    BASE, VIEWPORT, CaptureError,
    build_meta, capture_session, get_boxes, log, shoot, union_box, write_coords,
)

TABLE_ROWS_IN_SHOT = 6
# 잠금(locked_fields) 실사례를 찾으려고 상세를 조회하는 상한 — 값을 지어내지 않고
# 실측하되, 카탈로그 전체(2만여 건)를 다 훑지 않도록 비용을 제한한다.
LOCK_EXAMPLE_SEARCH_LIMIT = 25


def main() -> int:
    coords: dict = {}
    stats: dict = {}

    try:
        with capture_session() as page:
            # ---- 1) 화면 열기 -------------------------------------------------------
            page.goto(f"{BASE}/admin2/products", wait_until="networkidle")
            try:
                page.wait_for_selector("#rows .pp-row", timeout=15000)
            except Exception as e:
                log(f"[FATAL] 목록 데이터가 15초 안에 안 채워졌습니다: {e}")
                return 1
            page.wait_for_timeout(300)  # 탭 배지 등 렌더 안정화

            # ---- 2) 전체 화면(뷰포트, 기본 "전체" 탭·1페이지) -------------------------
            full_clip = {"x": 0, "y": 0, "width": VIEWPORT["width"], "height": VIEWPORT["height"]}
            shoot(page, "products-full", full_clip, {
                "lnb": ".a2-lnb",
                "lnb_active_item": ".a2-lnb-b a.on",
                "header": ".a2-hd",
                "badge": ".a2-badge",
                "roles_req": ".a2-hd > .a2-roles",
                "hub": ".a2-hub",
                "role_box": "#roleBox",
                "avatar": ".a2-avatar",
                "tabs": "#tabs",
                "tab_review": '#tabs [data-k="review"]',
                "filters": ".pp-filters",
                "search_box": "#q",
                "cat_select": "#fcat",
                "mfr_input": "#fmfr",
                "btn_new": "#btnNew",
                "filters_note": ".pp-filters-note",
                "bulk": ".pp-bulk",
                "table_wrap": ".pp-table-wrap",
                "thead": "#thead",
                "first_row": "#rows .pp-row:first-child",
                "pager": "#pgBar",
                "legend": ".pp-legend",
            }, coords)

            # ---- 3) 헤더 확대 --------------------------------------------------------
            hdr_box = get_boxes(page, {"header": ".a2-hd"})["header"]
            if hdr_box:
                shoot(page, "products-header", hdr_box, {
                    "crumb": ".a2-crumb",
                    "now": ".a2-now",
                    "badge": ".a2-badge",
                    "roles_req": ".a2-hd > .a2-roles",
                    "hub": ".a2-hub",
                    "role_box": "#roleBox",
                    "avatar": ".a2-avatar",
                }, coords)
            else:
                log("[MISS] .a2-hd 를 못 찾았습니다 - products-header.png 건너뜀")

            # ---- 4) 필터 + 일괄 변경 바 확대(선택 전 기본 상태) -----------------------
            fb_box = union_box(page, [".pp-filters", ".pp-filters-note", ".pp-bulk"])
            if fb_box:
                shoot(page, "products-filterbar", fb_box, {
                    "search_box": "#q",
                    "cat_select": "#fcat",
                    "mfr_input": "#fmfr",
                    "btn_purchase_quote": ".pp-filters button:nth-of-type(1)",
                    "btn_price_review": ".pp-filters button:nth-of-type(2)",
                    "btn_new": "#btnNew",
                    "filters_note": ".pp-filters-note",
                    "bulk_hint": "#bulkHintWrap",
                }, coords)
            else:
                log("[MISS] 필터·일괄 변경 바를 못 찾았습니다 - products-filterbar.png 건너뜀")

            # ---- 5) 표 확대(머리글 + 앞쪽 N행) ----------------------------------------
            row_selectors = ["#thead"] + [
                f"#rows .pp-row:nth-child({i})" for i in range(1, TABLE_ROWS_IN_SHOT + 1)
            ]
            table_clip = union_box(page, row_selectors)
            if table_clip:
                el_sel = {"thead": "#thead"}
                for i in range(1, TABLE_ROWS_IN_SHOT + 1):
                    el_sel[f"row_{i}"] = f"#rows .pp-row:nth-child({i})"
                shoot(page, "products-table", table_clip, el_sel, coords)
            else:
                log("[MISS] 표 행을 못 찾았습니다 - products-table.png 건너뜀")

            # ---- 6) 일괄 선택 상태 — 체크박스 2개(서버에 아무 요청도 보내지 않는다) ----
            try:
                n_rows = page.locator("#rows .pp-row").count()
                if n_rows >= 2:
                    page.locator("#rows .pp-row:nth-child(1) .pp-chk").check()
                    page.locator("#rows .pp-row:nth-child(2) .pp-chk").check()
                    page.wait_for_selector("#bulkActive:not([hidden])", timeout=3000)
                    bulk_box = get_boxes(page, {"bulk": ".pp-bulk"})["bulk"]
                    if bulk_box:
                        shoot(page, "products-bulk-active", bulk_box, {
                            "sel_count": "#selCount",
                            "bulk_status": "#bulkStatus",
                            "btn_bulk": "#btnBulk",
                            "bulk_note": ".pp-bulk-note",
                            "btn_undo": "#btnUndo",
                        }, coords)
                    else:
                        log("[MISS] .pp-bulk 박스를 못 쟀습니다 - products-bulk-active.png 건너뜀")
                    # 다음 캡처에 영향 주지 않도록 선택을 되돌린다(순수 DOM — 서버 요청 없음)
                    page.locator("#rows .pp-row:nth-child(1) .pp-chk").uncheck()
                    page.locator("#rows .pp-row:nth-child(2) .pp-chk").uncheck()
                else:
                    log(f"[MISS] 선택할 행이 2개 미만입니다({n_rows}) - products-bulk-active.png 건너뜀")
            except Exception as e:
                log(f"[MISS] 일괄 선택 상태 캡처 실패: {e}")

            # ---- 7) "검수 대기" 탭으로 좁혀 대표 상품을 고른다 -------------------------
            # 가능하면 잠금(locked_fields)이 실제로 걸린 예시를 우선한다 — 오늘(2026-08-25)
            # 잠금 대상이 2컬럼에서 13컬럼으로 늘어난 것을 실제 화면으로 보여주기 위함.
            # 못 찾으면 그냥 첫 행을 쓴다(잠금 없는 상태도 사실 그대로의 문서화다).
            page.locator('#tabs [data-k="review"]').click()
            target_pc = None
            try:
                page.wait_for_function(
                    "document.querySelector('#tabs [data-k=\"review\"]').classList.contains('on')",
                    timeout=5000)
                page.wait_for_selector("#rows .pp-row", timeout=10000)
                page.wait_for_timeout(200)
            except Exception as e:
                log(f"[MISS] 검수 대기 탭 전환 실패: {e}")

            try:
                r = page.request.get(f"{BASE}/api/admin/products?page=1&size=100&status=review")
                if r.ok:
                    review_items = r.json().get("items", [])
                    codes = [it["product_code"] for it in review_items]
                    for pc in codes[:LOCK_EXAMPLE_SEARCH_LIMIT]:
                        rd = page.request.get(f"{BASE}/api/admin/products/{pc}")
                        if rd.ok and (rd.json().get("locked_fields") or []):
                            target_pc = str(pc)
                            log(f"[INFO] 잠금 실사례로 상품 {pc} 를 골랐습니다")
                            break
                    if target_pc is None and codes:
                        target_pc = str(codes[0])
                        log(f"[INFO] 잠금 예시를 못 찾아 검수 대기 첫 행({target_pc})을 씁니다"
                            f"(상위 {min(len(codes), LOCK_EXAMPLE_SEARCH_LIMIT)}건 조회)")
            except Exception as e:
                log(f"[MISS] 대표 상품 탐색 실패: {e}")

            if not target_pc:
                # 검수 대기가 0건이면 지금 탭(전체)의 첫 행으로 대체한다.
                first_pc = page.evaluate(
                    "() => { const r = document.querySelector('#rows .pp-row');"
                    " return r ? r.getAttribute('data-pc') : null; }")
                target_pc = first_pc
                if target_pc:
                    log(f"[INFO] 검수 대기 행이 없어 현재 목록의 첫 행({target_pc})을 씁니다")

            if target_pc:
                row_sel = f'#rows .pp-row[data-pc="{target_pc}"]'
                if page.locator(row_sel).count() == 0:
                    log(f"[MISS] 대표 상품({target_pc})이 지금 목록에 안 보입니다 - 상세 캡처 건너뜀")
                    target_pc = None

            if target_pc:
                page.locator(f'#rows .pp-row[data-pc="{target_pc}"] [data-open]').first.click()
                opened = True
                try:
                    page.wait_for_selector("#drawer:not([hidden])", timeout=5000)
                    page.wait_for_function(
                        "document.getElementById('drTitle') &&"
                        " document.getElementById('drTitle').textContent !== '불러오는 중…'",
                        timeout=8000)
                    page.wait_for_timeout(300)
                except Exception as e:
                    log(f"[MISS] 상세 패널이 안 열렸습니다(product_code={target_pc}): {e}")
                    opened = False

                if opened:
                    # ---- 7a) 전체 화면 + 상세 패널(화살표로 어디서 열리는지 보여준다) ----
                    shoot(page, "products-full-detail", full_clip, {
                        "selected_row": row_sel,
                        "drawer": "#drawer",
                        "dr_title": "#drTitle",
                    }, coords)

                    # ---- 7b) 기본 정보 탭 — 읽기 전용 ---------------------------------
                    drawer_box = get_boxes(page, {"drawer": "#drawer"})["drawer"]
                    if drawer_box:
                        shoot(page, "products-drawer-basic", drawer_box, {
                            "title": "#drTitle",
                            "mall_link": "#drMallLink",
                            "status_badge": "#drStatusBadge",
                            "close": "#drClose",
                            "sub": "#drSub",
                            "tabs": "#drTabs",
                            "gate": "#drBody > div:nth-child(1)",
                            "supplier_row": "#drBody > div:nth-child(4)",
                            "body": "#drBody",
                            "foot": "#drFoot",
                            "btn_edit": "#drEdit",
                        }, coords)
                    else:
                        log("[MISS] #drawer 박스를 못 쟀습니다 - products-drawer-basic.png 건너뜀")

                    # ---- 7c) 기본 정보 탭 — 편집 모드(fetch 없음 · [저장]을 누르지 않는다) --
                    try:
                        page.locator("#drEdit").click()
                        page.wait_for_selector('#drBody [data-f="supplier"]', timeout=3000)
                        page.wait_for_timeout(150)
                        drawer_box2 = get_boxes(page, {"drawer": "#drawer"})["drawer"]
                        if drawer_box2:
                            shoot(page, "products-drawer-basic-edit", drawer_box2, {
                                "tabs": "#drTabs",
                                "name_input": '#drBody [data-f="name"]',
                                "supplier_input": '#drBody [data-f="supplier"]',
                                "status_select": '#drBody [data-f="status"]',
                                "body": "#drBody",
                                "foot": "#drFoot",
                                "btn_save": "#drSave",
                                "btn_cancel": "#drCancel",
                            }, coords)
                        else:
                            log("[MISS] 편집 모드 드로어 박스를 못 쟀습니다")
                    except Exception as e:
                        log(f"[MISS] 기본 정보 편집 모드 캡처 실패: {e}")
                    finally:
                        # 저장하지 않고 취소로 되돌린다 — 서버에는 아무 것도 남지 않는다.
                        cancel = page.locator("#drCancel")
                        if cancel.count():
                            cancel.click()
                            page.wait_for_timeout(150)

                    # ---- 7d) 사양 탭 — 읽기 전용 --------------------------------------
                    try:
                        page.locator('#drTabs [data-tab="spec"]').click()
                        page.wait_for_timeout(250)
                        drawer_box3 = get_boxes(page, {"drawer": "#drawer"})["drawer"]
                        if drawer_box3:
                            shoot(page, "products-drawer-spec", drawer_box3, {
                                "tabs": "#drTabs",
                                "progress": ".pp-dr-hint",
                                "body": "#drBody",
                                "foot": "#drFoot",
                            }, coords)
                        else:
                            log("[MISS] 사양 탭 드로어 박스를 못 쟀습니다")
                    except Exception as e:
                        log(f"[MISS] 사양 탭 캡처 실패: {e}")

                    # ---- 7e) 공급처 탭 — 읽기 전용(공급처별 매입가 표) -------------------
                    try:
                        page.locator('#drTabs [data-tab="supplier"]').click()
                        page.wait_for_timeout(250)
                        drawer_box4 = get_boxes(page, {"drawer": "#drawer"})["drawer"]
                        if drawer_box4:
                            shoot(page, "products-drawer-supplier", drawer_box4, {
                                "tabs": "#drTabs",
                                "body": "#drBody",
                                "foot": "#drFoot",
                            }, coords)
                        else:
                            log("[MISS] 공급처 탭 드로어 박스를 못 쟀습니다")
                    except Exception as e:
                        log(f"[MISS] 공급처 탭 캡처 실패: {e}")

                    close_btn = page.locator("#drClose")
                    if close_btn.count():
                        close_btn.click()
                        page.wait_for_timeout(150)
            else:
                log("[MISS] 열 수 있는 상품이 없습니다 - 상세 패널 캡처 전부 건너뜀")

            # ---- 8) 등록 서랍 — 빈 초기 상태만(이름 입력·제출 없음) ----------------------
            try:
                page.locator("#btnNew").click()
                page.wait_for_selector("#regDrawer:not([hidden])", timeout=5000)
                page.wait_for_timeout(200)
                reg_box = get_boxes(page, {"reg": "#regDrawer"})["reg"]
                if reg_box:
                    shoot(page, "products-reg", reg_box, {
                        "name_input": "#regName",
                        "choice_host": "#regChoiceHost",
                        "maker_input": "#regMaker",
                        "supplier_input": "#regSupplier",
                        "body": "#regBody",
                        "foot": "#regFoot",
                    }, coords)
                else:
                    log("[MISS] #regDrawer 박스를 못 쟀습니다 - products-reg.png 건너뜀")
                reg_close = page.locator("#regClose")
                if reg_close.count():
                    reg_close.click()
                    page.wait_for_timeout(150)
            except Exception as e:
                log(f"[MISS] 등록 서랍 캡처 실패: {e}")

            # ---- 9) 문서용 실측 수치 — 지어내지 않고 API 응답을 그대로 남긴다 -----------
            try:
                r1 = page.request.get(f"{BASE}/api/admin/products?page=1&size=1")
                if r1.ok:
                    j1 = r1.json()
                    stats["kpis"] = j1.get("kpis")
                    stats["total"] = j1.get("total")
                r2 = page.request.get(f"{BASE}/api/admin/product-meta")
                if r2.ok:
                    j2 = r2.json()
                    stats["used_parts_count"] = len(j2.get("used_parts") or [])
                    stats["makers_count"] = len(j2.get("makers") or [])
                    stats["status_options"] = j2.get("status_options")
                r3 = page.request.get(f"{BASE}/api/admin/spec-fields")
                if r3.ok:
                    stats["spec_fields_count"] = len((r3.json() or {}).get("items") or [])
                if target_pc:
                    r4 = page.request.get(f"{BASE}/api/admin/products/{target_pc}")
                    if r4.ok:
                        j4 = r4.json()
                        stats["example_product"] = {
                            "product_code": j4.get("product_code"), "name": j4.get("name"),
                            "cat": j4.get("cat"), "status_key": j4.get("status_key"),
                            "verdict": j4.get("verdict"), "gate_note": j4.get("gate_note"),
                            "gate_blocked": j4.get("gate_blocked"),
                            "locked_fields": j4.get("locked_fields"),
                            "spec_done": j4.get("spec_done"), "spec_total": j4.get("spec_total"),
                            "supplier": j4.get("supplier"),
                            "suppliers_count": len(j4.get("suppliers") or []),
                            "in_pool": j4.get("in_pool"),
                        }
            except Exception as e:
                log(f"[MISS] 문서용 수치 조회 실패(캡처는 이미 끝났습니다): {e}")

    except CaptureError as e:
        log(f"[FATAL] {e}")
        return 1

    coords["_meta"] = build_meta("ADM-PRD-010", "/admin2/products", VIEWPORT, stats)
    write_coords("products", coords)

    k = stats.get("kpis")
    if k:
        log(f"[INFO] 전체 {stats.get('total')}건 - 추천가능 {k.get('ok')} / 검수대기 {k.get('review')}"
            f" / 재고없음 {k.get('oos')} / 가격검토 {k.get('price')}")
    ex = stats.get("example_product")
    if ex:
        log(f"[INFO] 대표 상품 {ex.get('product_code')} '{ex.get('name')}' - {ex.get('gate_note')}"
            f" / 잠금 {ex.get('locked_fields')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
