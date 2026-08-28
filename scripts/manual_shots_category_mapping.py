r"""운영자 매뉴얼용 화면 캡처 — 상품 분류 매핑(ADM-CAT-020, 경로 /admin2/category-mapping).

`scripts/manual_capture_common.py`(공용 로그인·캡처·좌표 뽑기)를 그대로 쓴다 — 그 파일은
읽기만 했고 고치지 않았다(다섯 명이 동시에 각자 다른 화면을 찍는 중이라 공용 파일을 다시
고치면 서로 덮어쓴다). 이 파일에는 **이 화면에만 해당하는 것**(선택자·무엇을 확대할지·
이 화면 전용 실측)만 있다.

■★ 이 화면은 다섯 중 유일하게 «쓰기»가 있다 — 그래서 이 스크립트는 절대 쓰지 않는다
    이동(`POST /api/admin/category-mapping/move`)·되돌리기(`POST .../undo`) 버튼은
    **한 번도 클릭하지 않는다.** 이 스크립트가 실제로 하는 상호작용은 전부 로컬 상태만
    바꾸고 서버에는 아무것도 보내지 않는다(코드로 직접 확인):
      · 범위(탭) 전환 — `pick-tab` → `setScope()` → **GET** `/api/admin/category-mapping`뿐
      · 상품 체크박스 선택 — `toggle-row` → `S.sel[code] = true` (fetch 없음)
      · 대상 분류 드롭다운 열기·고르기 — `toggle-target`·`pick-target` → `S.target = id`
        (fetch 없음 — `renderBar()`만 다시 그린다)
      · "최근 이동" 팝오버 열기 — `toggle-recent` (fetch 없음, `S.moves`는 이 화면을 연
        뒤로 한 번도 안 채워졌으므로 항상 빈 상태로 열린다 — 아래 참고)
    그래서 이 스크립트가 남기는 유일한 흔적은 세션 쿠키로 남는 로그인 1회와, 화면이 여는
    GET 요청들뿐이다 — `POST`는 **0건**(전수 확인 — 아래 main()에 `apiPost`·`fetch(...,
    {method:'POST'`에 해당하는 Playwright 호출이 없다).

■★ "최근 이동" 팝오버는 이 세션에서 항상 비어 있다 — 그것 자체가 매뉴얼의 근거다
    `S.moves`는 순수 JS 배열이고(localStorage 등 영속 저장 없음, 페이지 코드 전수 확인),
    이 화면 코드 자신의 주석이 명시한다: "«최근 이동»은 세션 안에서 실행한 이동만 담는다".
    이 스크립트는 이동을 한 번도 실행하지 않으므로, 캡처된 팝오버는 항상
    "이 세션에서 옮긴 것이 없습니다" 빈 상태다 — **이것이 실제로 관찰한 사실**이지,
    캡처 실패가 아니다(운영자 매뉴얼 ⑤ "조심할 것"의 핵심 근거로 그대로 쓴다).

■★ 활동 기록(이동 405건 · 되돌림 374건, 2026-08-28 실측)은 이 스크립트가 다시 재지 않는다
    `GET /api/admin/activity-logs`는 최근 500건(전체 kind 통틀어)만 주므로, kind='category'
    action='카테고리 매핑 이동' 전체 건수를 이 API로는 정확히 셀 수 없다(대부분이 그 500건
    창 밖에 있다 — 하루 전체 로그가 14,000건대). 정확한 전체 건수는 이 스크립트 실행
    **전에** `.venv/Scripts/python`으로 `api.db.engine`을 통해
    `admin_operator_activity_logs`를 직접 SELECT(읽기 전용)해 별도로 쟀다 — 그 값은
    이 스크립트가 아니라 제작 보고서·매뉴얼 본문에 옮긴다(재현 방법도 함께 적는다).

읽기 전용 — DB에 쓰지 않는다. 포트 8000(사장님 서버, 절대 죽이지 않는다)에는 dev-login
1회 + 화면이 부르는 GET들만 나간다.

무엇을 하는가
    1. 로컬 서버(127.0.0.1:8000)에 Playwright로 접속해 점검 계정 세션을 심는다.
    2. /admin2/category-mapping(기본 진입 — 서버가 고른 open_at)을 열고 전체 + 헤더 +
       범위(탭) + 필터 바 + 분류 트리를 PNG로 저장한다.
    3. '미분류'(unclassified) 범위로 바꿔 행이 많은 표를 예시로 저장한다.
    4. 상품 2건을 체크(로컬 상태만) → 대상 분류 드롭다운을 열어 캡처 → 하나를 고른다
       (역시 로컬 상태만 — **"이동" 버튼은 누르지 않는다**).
    5. 선택을 해제하고 "최근 이동" 팝오버를 연다 — 빈 상태를 그대로 캡처한다.
    6. `?scope=violation` 딥링크로 새로 열어 사장님이 자주 보시는 자리를 별도로 담는다.
    7. 각 캡처 안 요소의 실측 bounding box를 좌표 JSON(category-mapping-coords.json)에 남긴다.

개인정보: 이 화면은 상품·분류 데이터만 다룬다 — 실제 고객·타인 개인정보가 없다. 상단
roleBox·avatar는 dev-login 점검 계정("UI점검") 자신이라 categories 화면과 같은 이유로
가리지 않는다.

다시 찍을 때
    .venv/Scripts/python scripts/manual_shots_category_mapping.py
    기존 PNG·JSON을 덮어쓴다(파일명 고정) — 화면이 바뀌면 다시 돌린다.
"""
import sys

from manual_capture_common import (
    BASE, VIEWPORT, CaptureError,
    build_meta, capture_session, get_boxes, log, shoot, union_box, write_coords,
)


def _ascii_log(s):
    """콘솔 로그용 — cp949가 못 먹는 문자(em-dash·화살표 등)를 ASCII로 치환한다.

    DOM에서 읽어온 값(카테고리 경로 등)을 그대로 print()하면 이 스크립트 자신이
    UnicodeEncodeError로 죽을 수 있다(CLAUDE.md 「함정」 — cp949 콘솔, categories 캡처
    스크립트에서 이미 겪은 문제와 같은 종류).
    """
    if s is None:
        return s
    return (str(s).replace("—", "-").replace("–", "-")
            .replace("→", "->").replace("▸", ">").replace("▾", "v").replace("▲", "^"))


# 표 확대컷에 담을 행 수(머리글 제외) — reviews·categories 캡처와 같은 관례(6행).
TABLE_ROWS_IN_SHOT = 6


def main() -> int:
    coords: dict = {}
    stats: dict = {}
    full_clip = {"x": 0, "y": 0, "width": VIEWPORT["width"], "height": VIEWPORT["height"]}

    try:
        with capture_session() as page:
            # ---- 1) 화면 열기(기본 진입 — 서버가 고른 open_at) ------------------------
            page.goto(f"{BASE}/admin2/category-mapping", wait_until="networkidle")
            try:
                page.wait_for_function(
                    "document.getElementById('cmTabs') &&"
                    " document.getElementById('cmTabs').children.length > 0",
                    timeout=15000)
            except Exception as e:
                log(f"[FATAL] 범위 탭이 15초 안에 안 채워졌습니다: {e}")
                return 1
            page.wait_for_timeout(400)

            # ---- 2) 그림 A: 전체 화면(기본 진입) --------------------------------------
            shoot(page, "category-mapping-full", full_clip, {
                "lnb": ".a2-lnb",
                "lnb_active_item": ".a2-lnb-b a.on",
                "header": ".a2-hd",
                "crumb": ".a2-crumb",
                "permhint": ".cm-permhint",
                "recent_btn": "#cmRecentBtn",
                "hub": ".a2-hub",
                "role_box": "#roleBox",
                "avatar": ".a2-avatar",
                "banner": ".cm-banner",
                "tabs": "#cmTabs",
                "filters": ".cm-filters",
                "tree": ".cm-tree",
                "thead": ".cm-thead",
                "first_row": "#cmTbody > button:nth-of-type(1)",
                "pager": ".cm-pager",
                "bar": "#cmBar",
            }, coords)

            # ---- 3) 그림 B: 헤더 확대 --------------------------------------------------
            hdr_box = get_boxes(page, {"header": ".a2-hd"})["header"]
            if hdr_box:
                shoot(page, "category-mapping-header", hdr_box, {
                    "crumb": ".a2-crumb",
                    "now": ".a2-now",
                    "permhint": ".cm-permhint",
                    "recent_btn": "#cmRecentBtn",
                    "recent_count": "#cmRecentCount",
                    "hub": ".a2-hub",
                    "role_box": "#roleBox",
                    "avatar": ".a2-avatar",
                }, coords)
            else:
                log("[MISS] .a2-hd 를 못 찾았습니다 - category-mapping-header.png 건너뜀")

            # ---- 4) 그림 C: 범위(탭) 확대 ------------------------------------------------
            tabs_box = get_boxes(page, {"tabs": "#cmTabs"})["tabs"]
            if tabs_box:
                shoot(page, "category-mapping-tabs", tabs_box, {
                    "tab_unmapped": '#cmTabs [data-scope="unmapped"]',
                    "tab_violation": '#cmTabs [data-scope="violation"]',
                    "tab_unclassified": '#cmTabs [data-scope="unclassified"]',
                    "tab_category": '#cmTabs [data-scope="category"]',
                    "tab_all": '#cmTabs [data-scope="all"]',
                }, coords)
            else:
                log("[MISS] #cmTabs 를 못 찾았습니다 - category-mapping-tabs.png 건너뜀")

            # ---- 5) 그림 D: 검색·필터 바 확대 -------------------------------------------
            filters_box = get_boxes(page, {"filters": ".cm-filters"})["filters"]
            if filters_box:
                shoot(page, "category-mapping-filters", filters_box, {
                    "search": "#cmSearch",
                    "part_btn": "#cmPartBtn",
                    "stock_btn": "#cmStockBtn",
                    "reset_btn": "#cmResetBtn",
                    "note": "#cmFilterNote",
                }, coords)
            else:
                log("[MISS] .cm-filters 를 못 찾았습니다 - category-mapping-filters.png 건너뜀")

            # ---- 6) 그림 E: 분류 트리 확대 ------------------------------------------------
            tree_box = get_boxes(page, {"tree": ".cm-tree"})["tree"]
            if tree_box:
                shoot(page, "category-mapping-tree", tree_box, {
                    "mode_cat": "#cmModeCat",
                    "mode_sub": "#cmModeSub",
                    "note": "#cmTreeNote",
                    "first_node": "#cmTreeBody .cm-tree-row:first-child",
                }, coords)
            else:
                log("[MISS] .cm-tree 를 못 찾았습니다 - category-mapping-tree.png 건너뜀")

            # ---- 7) '미분류' 범위로 바꿔 행이 많은 표를 예시로 남긴다 ----------------------
            page.locator('#cmTabs [data-scope="unclassified"]').click()
            try:
                page.wait_for_selector('#cmTabs [data-scope="unclassified"].on', timeout=8000)
            except Exception as e:
                log(f"[MISS] '미분류' 범위 전환 확인 실패: {e}")
            page.wait_for_timeout(300)

            row_sel = [".cm-thead"] + [
                f"#cmTbody > button:nth-of-type({i})" for i in range(1, TABLE_ROWS_IN_SHOT + 1)
            ]
            table_clip = union_box(page, row_sel)
            if table_clip:
                el_sel = {"thead": ".cm-thead"}
                for i in range(1, TABLE_ROWS_IN_SHOT + 1):
                    el_sel[f"row_{i}"] = f"#cmTbody > button:nth-of-type({i})"
                shoot(page, "category-mapping-table", table_clip, el_sel, coords)
            else:
                log("[MISS] 표 행을 못 찾았습니다(미분류 0건?) - category-mapping-table.png 건너뜀")

            # ---- 8) 상품 2건 선택 + 대상 분류 드롭다운(로컬 상태만, API 호출 없음) ----------
            rows = page.locator('#cmTbody > button.cm-row')
            picked_n = min(2, rows.count())
            for i in range(picked_n):
                rows.nth(i).click()
            if picked_n == 0:
                log("[MISS] 선택할 행이 없습니다(목록 0건) - 선택 상태 캡처를 건너뜁니다")
            page.wait_for_timeout(150)

            page.locator('#cmTargetBtn').click()
            try:
                page.wait_for_selector('#cmTargetDrop:not([hidden])', timeout=5000)
            except Exception as e:
                log(f"[MISS] 대상 분류 드롭다운이 안 열렸습니다: {e}")
            else:
                page.wait_for_timeout(200)
                # 그림 G: 대상 분류 드롭다운(열림) — 버튼+목록을 함께 담는다
                # (펼침 방향이 위쪽 — CSS `bottom:42px`, 실측 bounding box로 합친다).
                td_clip = union_box(page, ["#cmTargetBtn", "#cmTargetDrop"])
                if td_clip:
                    shoot(page, "category-mapping-target-drop", td_clip, {
                        "target_btn": "#cmTargetBtn",
                        "target_drop": "#cmTargetDrop",
                        "opt_1": "#cmTargetDrop .cm-targetopt:first-child",
                    }, coords)
                else:
                    log("[MISS] 대상 분류 드롭다운 영역을 못 쟀습니다")

                opt = page.locator('#cmTargetDrop .cm-targetopt').first
                opt_label = None
                try:
                    opt_label = opt.inner_text()
                except Exception:
                    pass
                opt.click()   # 로컬 상태만 바뀐다(S.target = id) — "이동" 버튼은 누르지 않는다
                stats["picked_target_label"] = _ascii_log(opt_label)
                page.wait_for_timeout(200)
                log(f"[INFO] 대상 분류로 고른 예시(실행하지 않음): {_ascii_log(opt_label)}")

            # ---- 9) 그림 H: 선택 + 대상 지정 상태의 전체 화면(아직 이동 실행 전) ------------
            shoot(page, "category-mapping-full-detail", full_clip, {
                "selected_row_1": "#cmTbody > button:nth-of-type(1)",
                "selected_row_2": "#cmTbody > button:nth-of-type(2)",
                "bar": "#cmBar",
                "move_btn": "#cmMoveBtn",
            }, coords)

            # ---- 10) 그림 I: 하단 이동 바 확대 -------------------------------------------
            bar_box = get_boxes(page, {"bar": "#cmBar"})["bar"]
            if bar_box:
                shoot(page, "category-mapping-bar", bar_box, {
                    "sel_count": "#cmSelCount",
                    "limit_note": "#cmLimitNote",
                    "clear_btn": "#cmClearSelBtn",
                    "target_btn": "#cmTargetBtn",
                    "move_btn": "#cmMoveBtn",
                }, coords)
            else:
                log("[MISS] #cmBar 를 못 찾았습니다 - category-mapping-bar.png 건너뜀")

            # ---- 11) 선택 해제 후 '최근 이동' 팝오버(되돌리기 자리 — 항상 빈 상태) ----------
            try:
                page.locator('#cmClearSelBtn').click(timeout=3000)
                page.wait_for_timeout(150)
            except Exception as e:
                log(f"[INFO] 선택 해제 버튼을 못 눌렀습니다(있어도 그만, 없어도 그만): {e}")

            page.locator('#cmRecentBtn').click()
            try:
                page.wait_for_selector('#cmRecentPop:not([hidden])', timeout=5000)
            except Exception as e:
                log(f"[MISS] '최근 이동' 팝오버가 안 열렸습니다: {e}")
            else:
                page.wait_for_timeout(200)
                empty_text = None
                try:
                    empty_text = page.locator('#cmRecentPop .cm-recent-empty').inner_text()
                except Exception:
                    pass
                stats["recent_popover_text"] = _ascii_log(empty_text)
                shoot(page, "category-mapping-recent", full_clip, {
                    "recent_btn": "#cmRecentBtn",
                    "recent_pop": "#cmRecentPop",
                }, coords)
                log(f"[INFO] '최근 이동' 팝오버 실제 내용(이 스크립트는 이동을 한 번도 "
                    f"실행하지 않았다): {_ascii_log(empty_text)}")

            # ---- 12) 그림 K: '?scope=violation' 딥링크로 새로 연다 -------------------------
            page.goto(f"{BASE}/admin2/category-mapping?scope=violation", wait_until="networkidle")
            try:
                page.wait_for_selector('#cmTabs [data-scope="violation"].on', timeout=10000)
            except Exception as e:
                log(f"[MISS] scope=violation 전환 확인 실패: {e}")
            page.wait_for_timeout(400)
            shoot(page, "category-mapping-violation", full_clip, {
                "tabs": "#cmTabs",
                "tab_violation": '#cmTabs [data-scope="violation"]',
                "filters": ".cm-filters",
                "thead": ".cm-thead",
                "first_row": "#cmTbody > button:nth-of-type(1)",
            }, coords)

            # ---- 13) 문서용 실측 수치 — counts는 scope·필터와 무관하게 항상 전체 기준이라
            #          호출 한 번으로 미매핑·위반·미분류·전체를 전부 얻는다(코드 주석 실측 —
            #          "범위별 배지 4종은 검색어·부품 종류·재고 필터의 영향을 받지 않는다").
            try:
                r1 = page.request.get(f"{BASE}/api/admin/category-mapping?scope=all&size=1")
                if r1.ok:
                    j1 = r1.json()
                    stats["counts"] = j1.get("counts")
                    stats["open_at"] = j1.get("open_at")
                    stats["max_move"] = j1.get("max_move")
                    stats["part_types_n"] = len(j1.get("part_types") or [])
                r4 = page.request.get(f"{BASE}/api/admin/categories")
                if r4.ok:
                    j4 = r4.json()
                    items = j4.get("items") or []
                    stats["cat_total"] = len(items)
                    stats["cat_top"] = sum(1 for i in items if i.get("parent_id") is None)
                    stats["cat_sub"] = stats["cat_total"] - stats["cat_top"]
            except Exception as e:
                log(f"[MISS] 문서용 수치 조회 실패(캡처는 이미 끝났습니다): {e}")

    except CaptureError as e:
        log(f"[FATAL] {e}")
        return 1

    coords["_meta"] = build_meta("ADM-CAT-020", "/admin2/category-mapping", VIEWPORT, stats)
    write_coords("category-mapping", coords)

    if stats.get("counts") is not None:
        c = stats["counts"]
        log(f"[INFO] counts: 미매핑 {c.get('unmapped')}(재고>0 {c.get('unmapped_stock')}) - "
            f"위반 {c.get('violation')} - 미분류 {c.get('unclassified')}(재고>0 {c.get('unclassified_stock')}) - "
            f"전체 {c.get('all_products')} - open_at={stats.get('open_at')} - max_move={stats.get('max_move')}")
    if stats.get("cat_total") is not None:
        log(f"[INFO] 분류 트리: 전체 {stats.get('cat_total')}(대분류 {stats.get('cat_top')} - "
            f"소분류 {stats.get('cat_sub')}) - 표시 부품종류 {stats.get('part_types_n')}종")
    return 0


if __name__ == "__main__":
    sys.exit(main())
