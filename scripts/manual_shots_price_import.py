"""운영자 매뉴얼용 화면 캡처 — 단가표 반영(ADM-PRC-040, 경로 /admin2/price-import).

2026-08-29 신설 — `scripts/manual_capture_common.py`의 모듈 docstring §「새 화면 캡처를
추가하려면」 절차 그대로: 공통 부분(로그인·캡처·좌표 뽑기·비율 환산)은 공용 모듈에서
가져오고, 이 파일에는 **이 화면에만 해당하는 것**(경로·선택자·무엇을 확대할지)만 둔다.
공용 모듈은 다른 제작자들이 동시에 쓰므로 고치지 않는다.

무엇을 하는가
    1. 로컬 서버(127.0.0.1:8000 — **사장님 서버, 절대 죽이지 않는다**)에 Playwright로 접속한다.
    2. GET /api/admin/auth/dev-login 으로 점검 계정 세션을 심는다.
    3. /admin2/price-import 를 열고 목록이 채워지길 기다린 뒤, 전체·헤더·상단 경고줄·
       공급처 카드 목록·프리셋 없음 경고상자·파일 머리줄+분류카드·diff 표(매칭 없는
       공급처 → 매칭 있는 공급처로 전환)·신규 모델 목록·하단(매칭 순서+결과·이력)을
       PNG로 저장한다.
    4. 각 캡처 안 주요 요소의 "실제" bounding box를 함께 재서 JSON
       (price-import-coords.json)에 남긴다.

⚠ 이 화면은 공급처가 **127곳** 등록돼 있고(2026-08-29 실측 — ③ 몰 공급처 스크래핑이
  채운 수, req 정의서 작성 시점(2026-08-13, "5곳")과는 다르다) 그중 프리셋(파일명 인식
  규칙)이 있는 곳은 2곳뿐이라, 좌측 공급처 카드 목록 하나만으로 페이지 높이가 만 px를
  넘는다. 그래서 목록 아래(프리셋 없음 경고상자 등)와 우측 하단(신규 모델 목록·결과
  패널)은 **뷰포트 밖에 있다** — 캡처마다 `scroll_into_view_if_needed()`로 실제로
  스크롤한 뒤 좌표를 다시 잰다(스크롤 전 좌표를 그대로 쓰면 Playwright가
  "Clipped area is... outside the resulting image"로 죽는다 — 실제로 겪었다).

다시 찍을 때
    화면이 바뀌면 이 스크립트를 그대로 다시 돌리면 된다.
        .venv/Scripts/python scripts/manual_shots_price_import.py
    기존 PNG·JSON을 덮어쓴다(파일명 고정).

■■ 절대로 실제 반영을 실행하지 않는다 — 이 화면은 상품의 매입가·판매가를 실제로
   바꾼다(`_reprice()` 호출, 저장소 전체에서 4곳뿐인 호출처 중 둘이 이 화면의
   apply()·undo()다). 이 스크립트가 실제로 클릭하는 것은:
     · 공급처 카드 클릭(`data-action="select-supplier"`) — `S.selectedSupplierId` 만
       바꾸는 순수 클라이언트 상태 전환이다(코드 확인 — fetch 없음).
     · diff 표 체크박스 클릭(`data-action="toggle-row"`) — `S.checked` 만 바꾸는 순수
       DOM 상태다(코드 확인 — 'change' 리스너가 `renderRight()`만 부르고 fetch가 없다).
   **누르지 않는 것**: 「파일 올리기」(`#piUploadBtn`) · 「선택 N건 반영 = 승인」
   (`data-action="do-apply"`) · 「되돌리기」류(`undo-arm`/`undo-confirm`) 전부.
   체크박스를 켜서 반영 버튼이 "활성화"되는 상태까지는 보여주되, 그 버튼 자체는
   누르지 않는다 — 실제로 눌러야만 보이는 화면(반영 결과 패널의 실수치)은 이
   스크립트로 만들지 않는다(문서에는 "확인 못 한 것"으로 남긴다).

읽기 전용이다 — **DB에 쓰지 않는다.**

개인정보: 이 화면은 공급처(회사명)·상품·가격만 다룬다 — 고객 이름·이메일·전화번호가
나타나는 자리가 없다. 우측 상단 역할 표시는 실제 고객이 아니라 점검 전용 계정
("UI점검")이다. 그래서 `redact_*`를 쓰지 않는다.
"""
import sys

# 콘솔이 cp949라 서버 응답 문구(예: diff 행의 "—"·"타 공급처 최저 …" 같은 em-dash·비교
# 문구)가 섞이면 log()의 print()가 UnicodeEncodeError로 죽을 수 있다(다른 화면 스크립트의
# 실측 전례 — manual_shots_products.py 주석 참조). 이 프로세스에서만 stdout을 UTF-8로
# 바꿔 근본적으로 막는다 — 공용 모듈(manual_capture_common.log)은 고치지 않는다.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from manual_capture_common import (
    BASE, VIEWPORT, CaptureError,
    build_meta, capture_session, get_boxes, log, shoot, union_box, write_coords,
)

FILECARD_COUNT_IN_SHOT = 8
NW_ROWS_IN_SHOT = 5


def shoot_scrolled(page, name, selector, element_selectors, coords, pad=14):
    """below-the-fold 요소 전용 — 실제로 스크롤한 뒤 그 시점 좌표로 캡처한다.

    이 화면은 공급처 127장 목록 때문에 페이지가 매우 길다(위 모듈 docstring 참조).
    스크롤 전 좌표(뷰포트 밖)로 `page.screenshot(clip=...)`를 부르면 Playwright가
    죽는다 — 그래서 `scroll_into_view_if_needed()`로 실제 스크롤 후 다시 잰다.
    반환: 성공하면 True, 요소를 못 찾으면 False(로그만 남기고 계속 진행).
    """
    loc = page.locator(selector).first
    if loc.count() == 0:
        log(f"[MISS] {selector} 를 못 찾았습니다 - {name}.png 건너뜀")
        return False
    loc.scroll_into_view_if_needed()
    page.wait_for_timeout(150)
    box = get_boxes(page, {"b": selector})["b"]
    if box is None:
        log(f"[MISS] {selector} 스크롤 후에도 못 쟀습니다 - {name}.png 건너뜀")
        return False
    clip = {"x": max(0, box["x"] - pad), "y": max(0, box["y"] - pad),
            "width": box["width"] + pad * 2, "height": box["height"] + pad * 2}
    shoot(page, name, clip, element_selectors, coords)
    return True


def main() -> int:
    coords: dict = {}
    stats: dict = {}

    try:
        with capture_session() as page:
            # ---- 1) 화면 열기 -------------------------------------------------------
            page.goto(f"{BASE}/admin2/price-import", wait_until="networkidle")
            try:
                page.wait_for_selector("#piLayout:not([hidden])", timeout=15000)
            except Exception as e:
                log(f"[FATAL] 목록 데이터가 15초 안에 안 채워졌습니다: {e}")
                return 1
            page.wait_for_timeout(300)  # 렌더 안정화

            full_clip = {"x": 0, "y": 0, "width": VIEWPORT["width"], "height": VIEWPORT["height"]}

            # ---- 2) 전체 화면(뷰포트, 스크롤 맨 위 · 기본 선택 상태) --------------------
            # 아래(프리셋 없음 경고상자·diff 표 일부·신규 모델·하단)는 페이지가 길어
            # 이 한 장(뷰포트 1050px)에는 안 들어온다 — 각각 별도 그림으로 다룬다.
            shoot(page, "price-import-full", full_clip, {
                "lnb": ".a2-lnb",
                "lnb_active_item": ".a2-lnb-b a.on",
                "header": ".a2-hd",
                "hub": ".a2-hub",
                "role_box": "#roleBox",
                "avatar": ".a2-avatar",
                "topbar": ".pi-topbar",
                "upload_btn": "#piUploadBtn",
                "routine_note": ".pi-topbar-r",
                "noticebar": ".pi-noticebar",
                "permnote": ".pi-permnote",
                "filelist_top": "#piFileList",
                "filehead": ".pi-filehead",
                "cards": ".pi-cards",
            }, coords)

            # ---- 3) 헤더 확대 --------------------------------------------------------
            hdr_box = get_boxes(page, {"header": ".a2-hd"})["header"]
            if hdr_box:
                shoot(page, "price-import-header", hdr_box, {
                    "crumb": ".a2-crumb",
                    "now": ".a2-now",
                    "hub": ".a2-hub",
                    "role_box": "#roleBox",
                    "avatar": ".a2-avatar",
                }, coords)
            else:
                log("[MISS] .a2-hd 를 못 찾았습니다 - price-import-header.png 건너뜀")

            # ---- 4) 상단 바 + 상시 경고줄 + 권한 안내 확대 ----------------------------
            topbar_box = union_box(page, [".pi-topbar", ".pi-noticebar", ".pi-permnote"])
            if topbar_box:
                shoot(page, "price-import-topbar", topbar_box, {
                    "upload_btn": "#piUploadBtn",
                    "upload_status": "#piUploadStatus",
                    "routine_note": ".pi-topbar-r",
                    "noticebar": ".pi-noticebar",
                    "permnote": ".pi-permnote",
                }, coords)
            else:
                log("[MISS] 상단 바/경고줄을 못 찾았습니다 - price-import-topbar.png 건너뜀")

            # ---- 5) 좌측 공급처 카드 목록 확대(앞쪽 N장 — 대부분 "프리셋 없음" 상태다) --
            # ⚠ 버그 전례: `#piFileList` 자신을 union에 넣으면 127장 전체 높이(만 px대)가
            # 잡힌다 — 반드시 개별 카드 N장만으로 union한다.
            card_sel = [f"#piFileList .pi-filecard:nth-child({i})" for i in range(1, FILECARD_COUNT_IN_SHOT + 1)]
            filelist_box = union_box(page, card_sel)
            if filelist_box:
                el_sel = {f"card_{i}": f"#piFileList .pi-filecard:nth-child({i})"
                          for i in range(1, FILECARD_COUNT_IN_SHOT + 1)}
                shoot(page, "price-import-filelist", filelist_box, el_sel, coords)
            else:
                log("[MISS] 공급처 카드 목록을 못 찾았습니다 - price-import-filelist.png 건너뜀")

            # ---- 6) "프리셋 없는 공급처" / "이 목록이 감추는 것" 경고상자(below-the-fold) --
            shoot_scrolled(page, "price-import-nopreset-box", ".pi-warnbox:not(.muted)", {}, coords)
            shoot_scrolled(page, "price-import-hidden-files-box", ".pi-warnbox.muted", {}, coords)

            # ---- 7) 우측 파일 머리줄 + 분류 카드 4장(기본 선택된 공급처) ----------------
            shoot_scrolled(page, "price-import-filehead-default", ".pi-filehead", {
                "filehead": ".pi-filehead",
            }, coords)
            cards_box = get_boxes(page, {"c": ".pi-cards"})["c"]
            if cards_box:
                shoot(page, "price-import-cards-default", cards_box, {}, coords)

            # ---- 8) 매칭된 행이 있는 공급처로 전환(순수 클라이언트 상태 — fetch 없음) ----
            # 서버 응답(§ GET /api/admin/price-import)을 미리 읽어, chg 중 matched(product_code
            # not null) 행이 있는 공급처를 고른다 — 지어내지 않고 실측으로 고른다.
            target_sup_id = None
            try:
                r = page.request.get(f"{BASE}/api/admin/price-import")
                if r.ok:
                    body = r.json()
                    stats["fee_rate"] = body.get("fee_rate")
                    stats["margin_rate"] = body.get("margin_rate")
                    stats["files"] = []
                    for f in body.get("files", []):
                        chg = f.get("chg") or []
                        matched = [c for c in chg if c.get("product_code") is not None]
                        stats["files"].append({
                            "supplier": f.get("supplier"), "supplier_id": f.get("supplier_id"),
                            "status": f.get("status"), "row_count": f.get("row_count"),
                            "same": f.get("same"), "chg": len(chg), "chg_matched": len(matched),
                            "nw": len(f.get("nw") or []), "stat": len(f.get("stat") or []),
                        })
                        if target_sup_id is None and matched:
                            target_sup_id = f.get("supplier_id")
                    log(f"[INFO] 서버 실측 - 파일 {len(stats['files'])}건, "
                        f"매칭 반영 가능 공급처 = {target_sup_id}")
            except Exception as e:
                log(f"[MISS] 사전 diff 조회 실패(그래도 캡처는 계속합니다): {e}")

            if target_sup_id is not None:
                card = page.locator(f'#piFileList [data-action="select-supplier"][data-sup="{target_sup_id}"]')
                if card.count():
                    card.first.scroll_into_view_if_needed()
                    card.first.click()
                    page.wait_for_timeout(300)
                else:
                    log(f"[MISS] 공급처 카드(id={target_sup_id})를 화면에서 못 찾았습니다")
                    target_sup_id = None

            if target_sup_id is not None:
                # ---- 8a) diff 표 — 매칭됨 상태. 62행 전체를 담으면 5,700px대(재는 만큼
                # 나온다 — 1차 실행 실측)라 **머리글 + 앞쪽 N행만** 담는다(다른 화면들의
                # "표는 6행만" 관행과 동일 — products-table 선례).
                diff_sel = "#piRight > section.pi-section:nth-of-type(1)"
                DIFF_ROWS_IN_SHOT = 6
                hd_loc = page.locator(f"{diff_sel} .pi-section-hd").first
                if hd_loc.count():
                    hd_loc.scroll_into_view_if_needed()
                    page.wait_for_timeout(150)
                    row_sels = [f"{diff_sel} .pi-difftable tbody tr:nth-child({i})"
                                for i in range(1, DIFF_ROWS_IN_SHOT + 1)]
                    table_box = union_box(page, [f"{diff_sel} .pi-section-hd", f"{diff_sel} .pi-difftable thead"]
                                           + row_sels)
                    if table_box:
                        pad = 10
                        clip = {"x": max(0, table_box["x"] - pad), "y": max(0, table_box["y"] - pad),
                                "width": table_box["width"] + pad * 2, "height": table_box["height"] + pad * 2}
                        el_sel = {"hd": f"{diff_sel} .pi-section-hd", "thead": f"{diff_sel} .pi-difftable thead",
                                  "toggle_all": '[data-action="toggle-all"]'}
                        for i, sel in enumerate(row_sels, start=1):
                            el_sel[f"row_{i}"] = sel
                        shoot(page, "price-import-difftable-matched", clip, el_sel, coords)
                    else:
                        log("[MISS] diff 표 union 실패 - price-import-difftable-matched.png 건너뜀")
                else:
                    log("[MISS] diff 표 섹션 헤더를 못 찾았습니다 - price-import-difftable-matched.png 건너뜀")

                # ---- 8b) 반영 버튼 줄만 별도로(표 아래, 선택 0건 상태) ----------------------
                shoot_scrolled(page, "price-import-actions-empty", f"{diff_sel} .pi-actions", {
                    "apply_btn": '[data-action="do-apply"]',
                }, coords, pad=8)

                # ---- 8c) 매칭된 행 체크박스 하나를 켠다(순수 DOM — 서버 요청 없음) --------
                try:
                    chk = page.locator('.pi-difftable tbody input[type="checkbox"]:not([disabled])').first
                    if chk.count():
                        chk.scroll_into_view_if_needed()
                        chk.check()
                        page.wait_for_timeout(200)
                        # 체크한 행 자체(작은 영역)와, 버튼 줄(선택 1건으로 바뀐 상태)을 각각.
                        shoot_scrolled(page, "price-import-row-checked", "tr.pi-row:has(input:checked)",
                                       {}, coords, pad=6)
                        shoot_scrolled(page, "price-import-actions-checked", f"{diff_sel} .pi-actions", {
                            "apply_btn": '[data-action="do-apply"]',
                        }, coords, pad=8)
                        # 다음 캡처에 영향 주지 않도록 되돌린다(순수 DOM — 서버 요청 없음).
                        # ⚠ 반영 버튼은 이 상태에서도 "누르지 않는다" — 여기서 껐다 켰다 하는
                        # 것도 fetch가 전혀 없는 것을 코드로 이미 확인했다(위 모듈 docstring).
                        chk.uncheck()
                        page.wait_for_timeout(150)
                    else:
                        log("[MISS] 매칭돼 선택 가능한 체크박스가 없습니다 - price-import-*-checked.png 건너뜀")
                except Exception as e:
                    log(f"[MISS] 체크박스 상태 캡처 실패: {e}")

                # ---- 8c) 신규 모델(nw) 목록 — 머리글 + 앞쪽 N행만(전체는 매우 길다) --------
                nw_sel_root = "#piRight > section.pi-section:nth-of-type(2)"
                nw_row_sels = [f"{nw_sel_root} .pi-nwrow:nth-child({i})" for i in range(1, NW_ROWS_IN_SHOT + 1)]
                loc = page.locator(f"{nw_sel_root} .pi-section-hd").first
                if loc.count():
                    loc.scroll_into_view_if_needed()
                    page.wait_for_timeout(150)
                    nw_box = union_box(page, [f"{nw_sel_root} .pi-section-hd"] + nw_row_sels)
                    if nw_box:
                        pad = 10
                        clip = {"x": max(0, nw_box["x"] - pad), "y": max(0, nw_box["y"] - pad),
                                "width": nw_box["width"] + pad * 2, "height": nw_box["height"] + pad * 2}
                        el_sel = {"hd": f"{nw_sel_root} .pi-section-hd"}
                        for i, sel in enumerate(nw_row_sels, start=1):
                            el_sel[f"row_{i}"] = sel
                        shoot(page, "price-import-nwlist", clip, el_sel, coords)
                    else:
                        log("[MISS] 신규 모델 목록 union 실패 - price-import-nwlist.png 건너뜀")
                else:
                    log("[MISS] 신규 모델 섹션 헤더를 못 찾았습니다 - price-import-nwlist.png 건너뜀")
            else:
                log("[INFO] 지금 매칭된 반영 대상 행이 있는 공급처가 없습니다 - 8번 단계 전체 건너뜀"
                    "(기본 선택 공급처 캡처만으로 대체됩니다)")

            # ---- 9) 하단 2단 — 매칭 순서 · 결과/되돌리기·지난 이력(below-the-fold) ------
            shoot_scrolled(page, "price-import-bottom", ".pi-bottom", {
                "matchorder_section": ".pi-bottom > section.pi-section:nth-of-type(1)",
                "result_section": ".pi-bottom > section.pi-section:nth-of-type(2)",
                "recent_table": ".pi-recent-table",
            }, coords, pad=10)

            # ---- 10) 문서용 실측 수치 — 지어내지 않고 API 응답을 그대로 남긴다 -----------
            try:
                # 공급처 전체 수·프리셋 보유 수는 화면 DOM에서 직접 센다(서버가 SSR로 준
                # preset_total/preset_with와 같은 값을 말하는지 대조하는 셈이다).
                total_cards = page.locator("#piFileList .pi-filecard").count()
                nopreset_cards = page.locator("#piFileList .pi-filecard.nopreset").count()
                stats["suppliers_total_dom"] = total_cards
                stats["suppliers_nopreset_dom"] = nopreset_cards
                stats["suppliers_with_preset_dom"] = total_cards - nopreset_cards
            except Exception as e:
                log(f"[MISS] 문서용 수치 조회 실패(캡처는 이미 끝났습니다): {e}")

    except CaptureError as e:
        log(f"[FATAL] {e}")
        return 1

    coords["_meta"] = build_meta("ADM-PRC-040", "/admin2/price-import", VIEWPORT, stats)
    write_coords("price-import", coords)

    log(f"[INFO] 공급처 전체 {stats.get('suppliers_total_dom')} - "
        f"프리셋 있음 {stats.get('suppliers_with_preset_dom')} / "
        f"프리셋 없음 {stats.get('suppliers_nopreset_dom')}")
    for f in stats.get("files", []):
        log(f"[INFO] {f['supplier']} - 상태 {f['status']} - chg {f['chg']}(매칭 {f['chg_matched']}) "
            f"- nw {f['nw']} - stat {f['stat']} - 무변동 {f['same']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
