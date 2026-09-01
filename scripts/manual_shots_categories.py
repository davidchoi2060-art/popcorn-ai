r"""운영자 매뉴얼용 화면 캡처 — 상품 분류 관리(ADM-CAT-010, 경로 /admin2/categories).

`scripts/manual_capture_common.py`(공용 로그인·캡처·좌표 뽑기)를 그대로 쓴다. 이 파일에는
**이 화면에만 해당하는 것**(선택자·무엇을 확대할지·이 화면 전용 통계 조회)만 있다.
공용 모듈은 고치지 않았다 — 다른 네 명(상품 관리 · 상품 분류 매핑 · 운영자·권한 · 오픈
단계 설정 · 대시보드 중 나머지)이 동시에 같은 모듈을 쓴다.

■★ 화면 실측으로 확인한 것 — **이 화면은 견적 엔진에 영향을 주지 않는다**
    작업 지시에는 "분류가 견적에 직결된다(category_group='core_part') · 분류를 잘못
    옮기면 상품이 조용히 후보에서 빠진다"고 적혀 있었지만, 코드를 실측한 결과 **이
    화면(`categories` 테이블, `api/admin_categories.py`)은 그 축이 아니다**:
      · `category_group`(core_part/peripheral)은 **다른 컬럼**이고 `api/recommend.py`에
        `category_id` 참조가 0건이다 — 엔진은 이 트리를 전혀 읽지 않는다.
      · 화면 자신도 이 사실을 배너("엔진은 이 트리를 읽지 않습니다 — 분류를 옮겨도
        견적 결과는 바뀌지 않습니다")로 이미 밝히고 있다(`.pc-banner`).
      · "일괄 이동 상한(MAX_MOVE=2000)"은 실재하지만 **다른 화면**
        (`/admin2/category-mapping`, `api/admin_category_mapping.py:43`)의 것이다 —
        이 화면(`/admin2/categories`)에는 일괄 이동 자체가 없다(트리 편집 화면이라
        상품을 옮기지 않는다).
    그래서 이 문서의 "조심할 것"은 지시서의 가정을 따르지 않고 **실측한 사실**을 적는다
    (지시서 자체가 "혼동하지 마라"고 경고해 둔 두 화면을 지시서 스스로 다시 섞은 사례로
    보인다 — 제작 보고서에 남긴다).

■★ 2026-09-01 추가 정정 — 마진·재고 표시 제거에 맞춰 선택자를 고쳤다
    사장님 지시(2026-09-01, `templates/admin/product_category.html.j2` 상단 주석 "■★ 마진·재고
    표시 제거" 참고)로 이 화면에서 마진·재고 관련 UI가 전부 빠졌다: 상단 지표 카드가 4장에서
    3장으로(개별 마진이 걸린 분류 카드 삭제), 우측 레일이 3상자에서 2상자로(마진 상속 안내
    상자 삭제), 목록 표가 5열에서 3열로(재고 있음·마진 열 삭제), 서랍에서 마진 입력칸·상속
    표시·"이 분류에 걸기"·"상속으로 되돌리기"가 삭제됐다. 이 스크립트가 그 UI를 겨누던
    선택자(`#pcStats .pc-stat:nth-child(4)` · `.pc-mgbox` · `.pc-mgfield` · `#pcMarginInput` ·
    `[data-action="set-margin"]` · `[data-action="clear-margin"]`)를 아래에서 지웠다 — 지우지
    않았으면 `shoot()`가 "못찾음"만 로그에 남기고 조용히 넘어가 아무도 몰랐을 것이다(운영자
    매뉴얼 작업 지시가 실제로 이 상태를 지적했다). 분류별 마진은 이제
    `scripts/manual_shots_margin_policy.py`가 찍는 화면(마진 정책, `/admin2/margin-policy`)
    소관이다.

무엇을 하는가
    1. 로컬 서버(127.0.0.1:8000 — **사장님 서버, 절대 죽이지 않는다**)에 Playwright로 접속한다.
    2. GET /api/admin/auth/dev-login 으로 점검 계정 세션을 심는다.
    3. /admin2/categories 를 열고 트리 로드를 기다린 뒤, 전체 + 주요 영역을 PNG로 저장한다.
    4. 허용 종류 위반이 있는(그러나 전량은 아닌) 소분류 하나를 서버 응답 기준으로 골라
       서랍을 열고, 정렬순서 입력만 살짝 바꿔 "저장 전 미확정 상태"도 함께 남긴다
       (아래 "읽기 전용" 참고 — 이 입력은 로컬 상태만 바꾸고 서버로 아무것도 보내지 않는다).
    5. 각 캡처 안 요소의 실측 bounding box를 좌표 JSON(categories-coords.json)에 남긴다.

읽기 전용이다 — DB에 쓰지 않는다. 이 화면은 「저장」・「삭제」・「이 분류에 걸기」・
「상속으로 되돌리기」・「+ 대분류 추가」・「+ 하위 분류 추가」를 누르면 **확인 절차 없이
즉시 API를 부른다**(코드 확인 — `deleteNode()`·`addTopCategory()`·`addSubCategory()`
어디에도 `confirm()`이 없다). 그래서 이 스크립트는 그 버튼들을 **한 번도 클릭하지
않는다.** 서랍을 열기 위한 행 클릭(select-node), 정렬순서 입력창에 값을 채우는 것
(`page.fill`)은 코드상 `input` 이벤트 핸들러가 `S.draft`(로컬 상태)만 바꾸고 fetch를
전혀 부르지 않는다(직접 확인) — 그래서 "저장" 버튼을 누르지 않는 한 서버는 이 스크립트가
연 세션이 다녀갔다는 것 말고는 아무것도 모른다.

진단(부작용 없음) — "+ 하위 분류 추가" 버튼이 서랍이 열린 상태에서 실제로 클릭 가능한지를
`document.elementFromPoint()`로 검사해 로그에 남긴다(클릭은 하지 않는다 — 클릭하면
`addSubCategory()`가 확인 없이 바로 카테고리를 만든다). 결과는 제작 보고서에 옮긴다.

개인정보: 이 화면은 분류 트리 · 마진 · 최근 변경 이력만 다룬다. 이력의 `operator` 필드는
실제 조회 결과 "관리자"(역할류 문자열, 2026-08-25 실측)였고 고객 개인정보는 이 화면
어디에도 없다 — 다만 그 값이 앞으로 실제 운영자의 표시 이름으로 바뀔 수 있어(추측이 아니라
가능성만 남겨 둔다), 확신이 없다는 사실 자체를 이 주석과 제작 보고서에 남긴다. 상단
roleBox·avatar는 reviews 화면과 같은 이유로 가리지 않는다(dev-login 점검 계정 "UI점검"
자신이라 실제 고객·타인 정보가 아니다).

다시 찍을 때
    .venv/Scripts/python scripts/manual_shots_categories.py
    기존 PNG·JSON을 덮어쓴다(파일명 고정) — 화면이 바뀌면 다시 돌린다.
"""
import sys

from manual_capture_common import (
    BASE, VIEWPORT, CaptureError,
    build_meta, capture_session, get_boxes, log, shoot, union_box, write_coords,
)


def _ascii_log(s) -> str:
    """콘솔 로그용 — cp949가 못 먹는 문자를 ASCII로 치환한다(em-dash 등).

    DOM에서 읽어온 값(버튼 라벨 등)은 화면 코드가 유니코드 em-dash를 그대로 쓰고
    있어(`renderAddBtn()`의 "+ 하위 분류 추가 — " + 이름), 그 값을 그대로 print()하면
    서버 stdout과 같은 이유(CLAUDE.md 「함정」 — cp949 콘솔)로 이 스크립트 자신이
    UnicodeEncodeError로 죽는다. 실제로 첫 실행에서 이 문제로 죽는 것을 확인했다.
    """
    return (str(s).replace("—", "-").replace("–", "-")
            .replace("→", "->").replace("▸", ">").replace("▾", "v"))


# 트리 확대컷에 담을 행 수(머리글 제외). 실데이터는 2단(대분류 6 · 소분류 28,
# 2026-08-25 실측)이라 10행이면 대분류 하나 + 그 소분류 대부분을 한 장에 담는다.
TREE_ROWS_IN_SHOT = 10

# "+ 하위 분류 추가" 버튼이 서랍(백드롭) 뒤에서 실제로 눌리는지 검사하는 진단 스크립트.
# 클릭은 하지 않는다 — elementFromPoint로 "이 좌표에서 실제로 맨 위에 있는 요소가
# 무엇인가"만 읽는다(addSubCategory()에 확인창이 없어 실제 클릭은 카테고리를 만든다).
_DIAG_ADDBTN_JS = r"""() => {
    const btn = document.getElementById('pcAddTop');
    if (!btn) return {ok:false, reason:'no-btn'};
    const r = btn.getBoundingClientRect();
    const cx = r.x + r.width/2, cy = r.y + r.height/2;
    const top = document.elementFromPoint(cx, cy);
    return {
        label: btn.textContent,
        action: btn.getAttribute('data-action'),
        disabled: btn.disabled,
        topElementId: top ? top.id : null,
        topElementClass: top ? String(top.className) : null,
        isButtonReachable: top === btn || (top ? btn.contains(top) : false),
    };
}"""

# 허용 종류 위반이 "일부만"(0 < 위반 < 직속 상품수) 있는 소분류를 고른다 — 위반이 100%인
# 노드(예: 실측 당시 "완제품 PC")보다 "일부만 어긋난" 사례가 화면의 "막지 않고 알린다"
# 취지를 더 잘 보여준다. 클릭은 select-node(읽기 전용, 로컬 상태만 바뀜)뿐이다.
_PICK_ROW_JS = r"""() => {
    const rows = Array.from(document.querySelectorAll('#pcRows .pc-row'));
    const cands = rows.map(r => {
        const b = r.querySelector('.bdg.viol-b');
        const violN = b ? parseInt((b.textContent.match(/[\d,]+/)||['0'])[0].replace(/,/g,''), 10) : 0;
        const countsTxt = (r.querySelector('.counts')||{}).textContent || '';
        const prodN = parseInt((countsTxt.match(/[\d,]+/)||['0'])[0].replace(/,/g,''), 10);
        return {id: r.getAttribute('data-id'), violN: violN, prodN: prodN};
    }).filter(x => x.violN > 0);
    const partial = cands.filter(x => x.violN < x.prodN).sort((a, b) => b.violN - a.violN);
    if (partial.length) return partial[0].id;
    cands.sort((a, b) => b.violN - a.violN);
    if (cands.length) return cands[0].id;
    return rows.length ? rows[0].getAttribute('data-id') : null;
}"""


def main() -> int:
    coords: dict = {}
    stats: dict = {}

    try:
        with capture_session() as page:
            # ---- 1) 화면 열기 -------------------------------------------------------
            page.goto(f"{BASE}/admin2/categories", wait_until="networkidle")
            try:
                page.wait_for_function(
                    "document.getElementById('pcStats') &&"
                    " document.getElementById('pcStats').children.length > 0",
                    timeout=15000)
            except Exception as e:
                log(f"[FATAL] 통계 카드가 15초 안에 안 채워졌습니다: {e}")
                return 1
            page.wait_for_timeout(400)  # roleBox 등 meReady 후속 렌더 안정화

            # ---- 2) 전체 화면 --------------------------------------------------------
            full_clip = {"x": 0, "y": 0, "width": VIEWPORT["width"], "height": VIEWPORT["height"]}
            shoot(page, "categories-full", full_clip, {
                "lnb": ".a2-lnb",
                "lnb_active_item": ".a2-lnb-b a.on",
                "header": ".a2-hd",
                "crumb": ".a2-crumb",
                "permhint": ".pc-permhint",
                "undo_btn": ".pc-undo-hd",
                "hub": ".a2-hub",
                "role_box": "#roleBox",
                "avatar": ".a2-avatar",
                "banner": ".pc-banner",
                "stats": "#pcStats",
                "thead": ".pc-thead",
                "first_row": "#pcRows .pc-row:first-child",
                "addrow": "#pcAddTop",
                "rail": ".pc-rail",
            }, coords)

            # ---- 3) 헤더 확대 --------------------------------------------------------
            hdr_box = get_boxes(page, {"header": ".a2-hd"})["header"]
            if hdr_box:
                shoot(page, "categories-header", hdr_box, {
                    "crumb": ".a2-crumb",
                    "now": ".a2-now",
                    "permhint": ".pc-permhint",
                    "undo_btn": ".pc-undo-hd",
                    "hub": ".a2-hub",
                    "role_box": "#roleBox",
                    "avatar": ".a2-avatar",
                }, coords)
            else:
                log("[MISS] .a2-hd 를 못 찾았습니다 - categories-header.png 건너뜀")

            # ---- 4) 상단 지표 카드 확대 ------------------------------------------------
            stats_box = get_boxes(page, {"stats": "#pcStats"})["stats"]
            if stats_box:
                # 2026-09-01 사장님 지시로 "개별 마진이 걸린 분류" 카드가 빠져 지금은 3장뿐이다
                # (템플릿 renderStats() 실측 — card_4 자리에 대응하는 4번째 카드가 없다). 예전
                # 4장짜리 선택자를 그대로 두면 조용히 "못찾음"만 남고 아무도 모른다(파일 상단
                # docstring 결함 사례와 같은 함정) — 3장으로 맞춘다.
                shoot(page, "categories-stats", stats_box, {
                    "card_1": "#pcStats .pc-stat:nth-child(1)",
                    "card_2": "#pcStats .pc-stat:nth-child(2)",
                    "card_3": "#pcStats .pc-stat:nth-child(3)",
                }, coords)
            else:
                log("[MISS] #pcStats 를 못 찾았습니다 - categories-stats.png 건너뜀")

            # ---- 5) 분류 트리 확대(머리글 + 앞쪽 N행) -----------------------------------
            row_selectors = [".pc-thead"] + [
                f"#pcRows .pc-row:nth-child({i})" for i in range(1, TREE_ROWS_IN_SHOT + 1)
            ]
            tree_clip = union_box(page, row_selectors)
            if tree_clip:
                el_sel = {"thead": ".pc-thead"}
                for i in range(1, TREE_ROWS_IN_SHOT + 1):
                    el_sel[f"row_{i}"] = f"#pcRows .pc-row:nth-child({i})"
                shoot(page, "categories-tree", tree_clip, el_sel, coords)
            else:
                log("[MISS] 트리 행을 못 찾았습니다(분류 0건?) - categories-tree.png 건너뜀")

            # ---- 6) 우측 레일 확대(사각지대 · 최근 변경 — 2026-09-01부터 마진 상속 상자 삭제) ----
            rail_box = get_boxes(page, {"rail": ".pc-rail"})["rail"]
            if rail_box:
                # 2026-09-01 마진·재고 표시 제거로 ".pc-mgbox"(마진 상속 안내 상자) 자체가
                # 화면에서 없어졌다 — 남은 것은 사각지대·최근 변경 2상자뿐이다.
                shoot(page, "categories-rail", rail_box, {
                    "blind_box": ".pc-blindbox",
                    "hist_box": ".pc-histbox",
                    "hist_first": "#pcHistBody .pc-hist-row:first-child",
                }, coords)
            else:
                log("[MISS] .pc-rail 을 못 찾았습니다 - categories-rail.png 건너뜀")

            # ---- 7) 서랍 — 허용 종류 위반이 "일부만" 있는 소분류를 골라 연다 ----------------
            target_id = page.evaluate(_PICK_ROW_JS)
            if not target_id:
                log("[MISS] 열 수 있는 행이 없습니다 - 서랍 캡처 전체 건너뜀")
            else:
                page.locator(f'#pcRows .pc-row[data-id="{target_id}"]').click()
                try:
                    page.wait_for_selector("#pcDrawer:not([hidden])", timeout=5000)
                except Exception as e:
                    log(f"[MISS] 상세 서랍이 안 열렸습니다(category_id={target_id}): {e}")
                    target_id = None
                else:
                    page.wait_for_timeout(300)

            if target_id:
                # 진단 - 클릭 없이 "지금 이 버튼을 누르면 실제로 버튼에 닿는가"만 읽는다.
                diag = page.evaluate(_DIAG_ADDBTN_JS)
                log(f"[INFO] '+ 하위 분류 추가' 버튼 진단(서랍 열린 상태, 클릭하지 않음): {_ascii_log(diag)}")
                stats["addsub_button_diag"] = diag

                drawer_box = get_boxes(page, {"drawer": "#pcDrawer"})["drawer"]
                if drawer_box:
                    # 2026-09-01 마진·재고 표시 제거로 마진 입력칸("pc-mgfield"/"pcMarginInput")과
                    # "이 분류에 걸기"/"상속으로 되돌리기" 버튼(data-action="set-margin"/
                    # "clear-margin")이 서랍에서 통째로 빠졌다 — 셋 다 지금 화면엔 없는 선택자라
                    # 지웠다(남겨 두면 조용히 "못찾음"만 로그에 남고 아무도 모른다 — 파일 상단
                    # docstring 참고).
                    shoot(page, "categories-drawer", drawer_box, {
                        "name_row": ".pc-dw-hd .row1",
                        "depth_badge": ".pc-dw-hd .depth",
                        "close_btn": ".pc-dw-hd .x",
                        "meta": ".pc-dw-hd .meta",
                        "name_input": "#pcNameInput",
                        "parent_sel": ".pc-parentsel",
                        "sort_input": "#pcSortInput",
                        "chips": ".pc-chips",
                        "visbox": ".pc-visbox",
                        "violnote": ".pc-violnote",
                        "diff_area": "#pcDiffArea",
                        "foot": ".pc-dw-foot",
                        "foot_note": "#pcFootNote",
                        "btn_delete": '[data-action="delete-node"]',
                        "btn_revert": "#pcRevertBtn",
                        "btn_save": "#pcSaveBtn",
                    }, coords)

                    # 서랍이 열린 상태의 전체 화면 — "행을 누르면 여기로 열린다" + 뒤에서
                    # 흐려지는 좌측 버튼(진단 대상)을 함께 보여준다.
                    shoot(page, "categories-full-detail", full_clip, {
                        "selected_row": f'#pcRows .pc-row[data-id="{target_id}"]',
                        "drawer": "#pcDrawer",
                        "backdrop": "#pcBackdrop",
                        "addrow_dimmed": "#pcAddTop",
                    }, coords)
                else:
                    log("[MISS] #pcDrawer 박스를 못 쟀습니다 - categories-drawer.png 건너뜀")

                # ---- 7b) 미저장(dirty) 상태 — 정렬순서만 바꾼다(로컬 상태, API 호출 없음) ----
                try:
                    cur = page.eval_on_selector("#pcSortInput", "el => el.value")
                    try:
                        new_val = str(int(cur) + 1)
                    except (TypeError, ValueError):
                        new_val = "1"
                    page.fill("#pcSortInput", new_val)
                    page.wait_for_timeout(200)
                    drawer_box2 = get_boxes(page, {"drawer": "#pcDrawer"})["drawer"]
                    if drawer_box2:
                        shoot(page, "categories-drawer-dirty", drawer_box2, {
                            "sort_input": "#pcSortInput",
                            "diff_area": "#pcDiffArea",
                            "foot": ".pc-dw-foot",
                            "foot_note": "#pcFootNote",
                            "btn_revert": "#pcRevertBtn",
                            "btn_save": "#pcSaveBtn",
                        }, coords)
                    else:
                        log("[MISS] dirty 상태 #pcDrawer 박스를 못 쟀습니다")
                except Exception as e:
                    log(f"[MISS] 미저장 상태 캡처 실패(정렬순서 입력 - 서버로는 아무것도 안 나갑니다): {e}")

            # ---- 8) 문서용 실측 수치 — 지어내지 않고 API 응답을 그대로 남긴다 --------------
            try:
                r1 = page.request.get(f"{BASE}/api/admin/categories")
                if r1.ok:
                    j1 = r1.json()
                    items = j1.get("items") or []
                    stats["total"] = len(items)
                    stats["top"] = sum(1 for i in items if i.get("parent_id") is None)
                    stats["sub"] = stats["total"] - stats["top"]
                    stats["margin_set"] = sum(1 for i in items if i.get("margin_rate") is not None)
                    stats["violations_total"] = sum((i.get("violations") or 0) for i in items)
                    stats["violations_nodes"] = sum(1 for i in items if (i.get("violations") or 0) > 0)
                    stats["unmapped"] = j1.get("unmapped")
                    stats["unmapped_in_stock"] = j1.get("unmapped_in_stock")
                    stats["default_margin"] = j1.get("default_margin")
                    stats["part_types_n"] = len(j1.get("part_types") or [])
                    if target_id:
                        picked = next((i for i in items if str(i.get("category_id")) == str(target_id)), None)
                        stats["picked_node"] = picked
                r2 = page.request.get(f"{BASE}/api/admin/activity-logs")
                if r2.ok:
                    j2 = r2.json()
                    hist_items = j2.get("items") or []
                    cat_items = [h for h in hist_items if h.get("kind") == "category"]
                    stats["activity_total"] = j2.get("total")
                    stats["activity_window"] = len(hist_items)
                    stats["activity_category_in_window"] = len(cat_items)
                    # kind='category' 안에 "카테고리 매핑 이동" 류(다른 화면 소관)가 섞여
                    # 오는지 실측 — 섞여 있으면 이 화면 이력 목록의 "미구현" 표시가
                    # 그 항목에도 그대로 붙는다는 뜻이다(그 항목은 실제로는 다른 화면에서
                    # 되돌릴 수 있는데도).
                    stats["activity_category_mapping_mixed_in"] = sum(
                        1 for h in cat_items if "매핑" in (h.get("action_label") or ""))
            except Exception as e:
                log(f"[MISS] 문서용 수치 조회 실패(캡처는 이미 끝났습니다): {e}")

    except CaptureError as e:
        log(f"[FATAL] {e}")
        return 1

    coords["_meta"] = build_meta("ADM-CAT-010", "/admin2/categories", VIEWPORT, stats)
    write_coords("categories", coords)

    if stats.get("total") is not None:
        log(f"[INFO] 분류 {stats.get('total')}건(대분류 {stats.get('top')} · 소분류 {stats.get('sub')}) "
            f"- 위반 합계 {stats.get('violations_total')}건({stats.get('violations_nodes')}개 노드) "
            f"· 개별 마진 걸림 {stats.get('margin_set')} · 미배정 {stats.get('unmapped')}"
            f"(재고있음 {stats.get('unmapped_in_stock')}) · 표시 종류 {stats.get('part_types_n')}종")
    if stats.get("activity_category_mapping_mixed_in"):
        log(f"[INFO] 이력 목록(kind=category) 안에 '분류 매핑 이동'류 {stats['activity_category_mapping_mixed_in']}건 혼재"
            " - 전부 '미구현' 되돌리기로 표시되지만 실제로는 다른 화면에서 되돌릴 수 있는 항목입니다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
