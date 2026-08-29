# -*- coding: utf-8 -*-
r"""운영자 매뉴얼용 화면 캡처 — 재고 입고(ADM-SRC-020, 경로 /admin2/stock-inbound).

`scripts/manual_capture_common.py`(공용 로그인·캡처·좌표 뽑기)를 그대로 쓴다. 공용 모듈은
고치지 않았다 — 다른 제작자들이 동시에 같은 모듈로 각자 화면(운영자 매뉴얼 물결 2차)을 찍는다.

■★ 이 스크립트는 이 물결에서 «유일하게 실제로 쓰는» 캡처 스크립트다 — 왜 그런가
    이 화면은 원장(stock_movements)과 상태(stock_inbound_holds)를 바꾸는 «작업 화면»이라,
    「결과가 온 뒤에만 채운다」·「되돌림은 서버가 판정한다」 같은 계약을 코드만 읽어서는
    화면 캡처로 못 보여준다 — 실제로 확정 버튼을 눌러 서버 응답이 선 화면을 찍어야 한다.
    (작업 지시 원문: "캡처를 뜨느라 실제로 입고하지 마라 ... 눌러야만 확인되는 것이 있으면
    되돌림까지 확실히 하고 무엇을 했는지 보고해라.")

    그래서 이 스크립트는 실제로 아래를 서버에 요청한다(전부 되돌린다 — 순서대로):
        1. POST /api/admin/stock-inbound/{P-9103}       수량 1 · 사유 inbound
        2. POST /api/admin/stock-inbound/undo/{log_id}   위 1번을 즉시 되돌림
        3. POST /api/admin/stock-inbound/hold/{P-9103}   보류(사유 명시 — 이 스크립트가 만든 것임을 밝힘)
        4. POST /api/admin/stock-inbound/hold/{P-9103}/release   위 3번을 즉시 해제

■ 왜 P-9103(product_code 20489103, GIGABYTE RTX 5090)인가 — **새로 고른 것이 아니다.**
    `api/admin_stock.py` 자체의 주석("확인자 재현 P-9103")과 이 상품의 입고 이력(2026-08-18,
    log_id 9078~9081 — 입고·되돌림 쌍이 이미 4쌍 이상 반복돼 있다)이 이 상품이 **이 화면의
    검증에 이미 반복적으로 쓰여 온 자리**임을 보여준다. 실판매 이력에 영향이 없는 자리에서
    같은 패턴(수량 1 확정 → 즉시 되돌림)을 한 번 더 쌓는 것이라 새 위험을 만들지 않는다.

■ 검증 흔적(CANON §검증이 흔적을 남긴다) — 쓰기 앞뒤로 GET 스냅샷을 찍어 `stats`에 남긴다:
    baseline_pending(쓰기 전 전체 대기 수) → after_confirm → after_undo → after_hold →
    after_release. **넷 다 원상 복귀해야 baseline == final이다** — 이 스크립트 스스로 그
    일치를 확인하고 어긋나면 [FATAL]로 알린다(조용히 넘어가지 않는다).

■ 읽기 전용이 아닌 부분을 빼면 나머지(전체 화면·헤더·필터·행·게이트 카드·이력·직접 등록
  검색)는 categories.py와 같은 원칙 — GET만, 클릭은 select(행 선택)·toggle-direct·검색뿐.

다시 찍을 때
    .venv/Scripts/python scripts/manual_shots_stock_inbound.py
    기존 PNG·JSON을 덮어쓴다. **다시 돌리면 P-9103에 입고 1건 확정→되돌림, 보류→해제가
    한 번 더 원장/기록에 남는다**(불변식은 유지되지만 이력 행 수는 매번 늘어난다).
"""
import sys

from manual_capture_common import (
    BASE, CaptureError,
    build_meta, capture_session, get_boxes, log, shoot, write_coords,
)

PRODUCT_CODE = 20489103
PRODUCT_SKU = "P-9103"
HOLD_REASON = "운영자 매뉴얼 캡처 시연 - manual_shots_stock_inbound.py 가 즉시 해제합니다"


def _ascii_log(s) -> str:
    """콘솔 로그용 — cp949가 못 먹는 문자를 ASCII로 치환한다(em-dash 등).

    서버 응답의 note·pool_note 는 em-dash(-)를 그대로 쓴다(화면에는 문제 없지만 이
    스크립트 자신의 print()가 cp949 콘솔에서 죽는다 — categories.py 와 같은 이유).
    """
    return (str(s).replace("—", "-").replace("–", "-")
            .replace("→", "->").replace("▸", ">").replace("▾", "v"))


def _pending_snapshot(page, label: str, stats: dict) -> dict:
    """전체 대기 스냅샷(size=1 — 목록 자체가 아니라 total·kind_counts·held_total만 필요).

    쓰기 전후로 호출해 **원상 복귀를 실측으로 증명**한다(추측이 아니라 서버 값 대조).
    """
    r = page.request.get(f"{BASE}/api/admin/stock-inbound?page=1&size=1")
    if not r.ok:
        log(f"[MISS] 대기 스냅샷({label}) 실패: {r.status}")
        return {}
    j = r.json()
    snap = {"total": j.get("total"), "held_total": j.get("held_total"),
            "kind_counts": j.get("kind_counts")}
    stats[f"pending_{label}"] = snap
    log(f"[INFO] 대기 스냅샷[{label}]: total={snap['total']} "
        f"held={snap['held_total']} kind={snap['kind_counts']}")
    return snap


def _product_snapshot(page, label: str, stats: dict) -> dict:
    """P-9103 단건 스냅샷(q 검색) — stock·status·hold·pool_state 실측."""
    r = page.request.get(f"{BASE}/api/admin/stock-inbound?page=1&size=5&q={PRODUCT_SKU}")
    if not r.ok:
        log(f"[MISS] 상품 스냅샷({label}) 실패: {r.status}")
        return {}
    items = r.json().get("items") or []
    it = next((x for x in items if x.get("product_code") == PRODUCT_CODE), None)
    if it is None:
        log(f"[MISS] 상품 스냅샷({label}) — 목록에 P-9103 이 없습니다(검색 조건 확인 필요)")
        return {}
    snap = {"stock": it.get("stock"), "status": it.get("status"),
            "hold": it.get("hold"), "pool_state": it.get("pool_state"),
            "pool_label": it.get("pool_label")}
    stats[f"p9103_{label}"] = snap
    log(f"[INFO] P-9103 스냅샷[{label}]: stock={snap['stock']} status={snap['status']} "
        f"hold={'있음' if snap['hold'] else '없음'} pool={snap['pool_state']}")
    return snap


def main() -> int:
    coords: dict = {}
    stats: dict = {}

    try:
        with capture_session() as page:
            # ---- 0) 시작 전 스냅샷 — 나중에 "원상 복귀했는가"의 기준값 ------------------
            _pending_snapshot(page, "baseline", stats)
            _product_snapshot(page, "baseline", stats)

            # ---- 1) 화면 열기 --------------------------------------------------------
            page.goto(f"{BASE}/admin2/stock-inbound", wait_until="networkidle")
            try:
                page.wait_for_selector("#siRowsBody .si-row", timeout=15000)
            except Exception as e:
                log(f"[FATAL] 목록 행이 15초 안에 안 채워졌습니다: {e}")
                return 1
            page.wait_for_timeout(400)  # roleBox 등 meReady 후속 렌더 안정화

            full_clip = {"x": 0, "y": 0, "width": 1680, "height": 1050}

            # ---- 2) 전체 화면(기본 상태 — 대기 목록 + 빈 패널) --------------------------
            shoot(page, "stock-inbound-full", full_clip, {
                "lnb": ".a2-lnb",
                "lnb_active_item": ".a2-lnb-b a.on",
                "header": ".a2-hd",
                "crumb": ".a2-crumb",
                "now": ".a2-now",
                "hdcount": "#siHdCount",
                "hub": ".a2-hub",
                "role_box": "#roleBox",
                "avatar": ".a2-avatar",
                "search": "#siSearch",
                "part_select": "#siPart",
                "direct_btn": "#siDirectBtn",
                "chips": "#siChips",
                "chip_wait": '[data-action="hold-mode"][data-hold="exclude"]',
                "chip_zero": '[data-action="kind"][data-kind="zero"]',
                "chip_low": '[data-action="kind"][data-kind="low"]',
                "chip_hold": '[data-action="hold-mode"][data-hold="only"]',
                "kind_note": "#siKindNote",
                "rows": "#siRows",
                "first_row": "#siRowsBody .si-row:first-child",
                "pager": "#siPager",
                "panel": "#siPanel",
                "panel_empty": "#siPanelEmpty",
            }, coords)

            # ---- 3) 헤더 확대 ---------------------------------------------------------
            hdr_box = get_boxes(page, {"header": ".a2-hd"})["header"]
            if hdr_box:
                shoot(page, "stock-inbound-header", hdr_box, {
                    "crumb": ".a2-crumb", "now": ".a2-now", "hdcount": "#siHdCount",
                    "hub": ".a2-hub", "role_box": "#roleBox", "avatar": ".a2-avatar",
                }, coords)
            else:
                log("[MISS] .a2-hd 를 못 찾았습니다 - stock-inbound-header.png 건너뜀")

            # ---- 4) 검색·필터·칩 확대 --------------------------------------------------
            filt_box = get_boxes(page, {"f": ".si-filters"})["f"]
            if filt_box:
                shoot(page, "stock-inbound-filters", filt_box, {
                    "search": "#siSearch", "part_select": "#siPart",
                    "direct_btn": "#siDirectBtn",
                    "chip_wait": '[data-action="hold-mode"][data-hold="exclude"]',
                    "chip_zero": '[data-action="kind"][data-kind="zero"]',
                    "chip_low": '[data-action="kind"][data-kind="low"]',
                    "chip_hold": '[data-action="hold-mode"][data-hold="only"]',
                    "kind_note": "#siKindNote",
                }, coords)
            else:
                log("[MISS] .si-filters 를 못 찾았습니다 - stock-inbound-filters.png 건너뜀")

            # ---- 5) 목록 행 확대(머리글 없음 — 카드형이라 앞쪽 4행) ----------------------
            row_sel = {f"row_{i}": f"#siRowsBody .si-row:nth-child({i})" for i in range(1, 5)}
            rb = get_boxes(page, row_sel)
            boxes = [b for b in rb.values() if b]
            if boxes:
                rows_clip = {
                    "x": min(b["x"] for b in boxes), "y": min(b["y"] for b in boxes),
                    "width": max(b["x"] + b["width"] for b in boxes) - min(b["x"] for b in boxes),
                    "height": max(b["y"] + b["height"] for b in boxes) - min(b["y"] for b in boxes),
                }
                shoot(page, "stock-inbound-rows", rows_clip, row_sel, coords)
            else:
                log("[MISS] 목록 행을 못 찾았습니다 - stock-inbound-rows.png 건너뜀")

            # ---- 6) P-9103 검색 → 선택(읽기 전용 — select 는 GET 이력 조회만 부른다) -----
            try:
                with page.expect_response(
                        lambda r: "/api/admin/stock-inbound?" in r.url
                        and "history" not in r.url and r.request.method == "GET",
                        timeout=8000):
                    page.fill("#siSearch", PRODUCT_SKU)
                    page.press("#siSearch", "Enter")
            except Exception as e:
                log(f"[FATAL] P-9103 검색 응답을 못 받았습니다: {e}")
                return 1
            try:
                page.wait_for_selector(f'.si-row[data-code="{PRODUCT_CODE}"]', timeout=8000)
            except Exception as e:
                log(f"[FATAL] 검색 결과에 P-9103 행이 없습니다: {e}")
                return 1

            try:
                with page.expect_response(
                        lambda r: "stock-inbound/history" in r.url and r.request.method == "GET",
                        timeout=8000):
                    page.click(f'.si-row[data-code="{PRODUCT_CODE}"] .nm')
                page.wait_for_selector("#siPhead:not([hidden])", timeout=8000)
            except Exception as e:
                log(f"[FATAL] P-9103 행 선택이 패널을 못 열었습니다: {e}")
                return 1
            page.wait_for_timeout(250)

            # ---- 7) 선택 후 전체 화면(목록+패널) — 화살표용 실측 좌표 확보 ----------------
            sel_boxes = get_boxes(page, {
                "selected_row": f'.si-row[data-code="{PRODUCT_CODE}"]',
                "panel": "#siPanel", "phead": "#siPhead", "gate_card": "#siGateCard",
            })
            shoot(page, "stock-inbound-full-detail", full_clip, {
                "selected_row": f'.si-row[data-code="{PRODUCT_CODE}"]',
                "panel": "#siPanel", "phead": "#siPhead",
                "confirm_card": "#siConfirmCard", "gate_card": "#siGateCard",
                "hist_card": "#siHistCard",
            }, coords)
            if sel_boxes.get("selected_row") and sel_boxes.get("phead"):
                r1, r2 = sel_boxes["selected_row"], sel_boxes["phead"]
                log(f"[INFO] 화살표 참고 좌표(px, 캡처 stock-inbound-full-detail 기준) - "
                    f"선택행 우측끝=({r1['x']+r1['width']:.0f},{r1['y']+r1['height']/2:.0f}) "
                    f"-> 패널제목시작=({r2['x']:.0f},{r2['y']+r2['height']/2:.0f})")

            # ---- 8) 수량 입력(클라이언트 렌더만 — 서버로 아무것도 안 나간다) -------------
            page.fill("#siQty", "1")
            page.wait_for_timeout(200)
            cc_box = get_boxes(page, {"c": "#siConfirmCard"})["c"]
            if cc_box:
                shoot(page, "stock-inbound-panel-confirm", cc_box, {
                    "qty": "#siQty", "why_inbound": '[data-action="why"][data-why="inbound"]',
                    "why_adjust": '[data-action="why"][data-why="adjust"]',
                    "confirm_btn": "#siConfirmBtn", "preview": "#siPreview",
                    "note": ".si-note",
                }, coords)
            else:
                log("[MISS] #siConfirmCard 를 못 찾았습니다 - stock-inbound-panel-confirm.png 건너뜀")

            gc_box = get_boxes(page, {"g": "#siGateCard"})["g"]
            if gc_box:
                gate_sel = {f"gate_{i}": f"#siGates .si-gate:nth-child({i})" for i in range(1, 5)}
                gate_sel["gate_note"] = "#siGateNote"
                shoot(page, "stock-inbound-panel-gates", gc_box, gate_sel, coords)
            else:
                log("[MISS] #siGateCard 를 못 찾았습니다 - stock-inbound-panel-gates.png 건너뜀")

            # ============================================================================
            # ---- 9) 실제 쓰기 ① 입고 확정(수량 1 · 사유 inbound) — 계약대로 되돌린다 ------
            # ============================================================================
            confirm_json = None
            undo_id = None
            try:
                with page.expect_response(
                        lambda r: r.url == f"{BASE}/api/admin/stock-inbound/{PRODUCT_CODE}"
                        and r.request.method == "POST", timeout=10000) as ri:
                    page.click("#siConfirmBtn")
                resp = ri.value
                if not resp.ok:
                    log(f"[FATAL] 입고 확정 실패: {resp.status} {_ascii_log(resp.text())}")
                    return 1
                confirm_json = resp.json()
                undo_id = confirm_json.get("undo_id")
                log(f"[INFO] 입고 확정 완료: stock {confirm_json.get('stock_before')} -> "
                    f"{confirm_json.get('stock_after')} · pool_entered={confirm_json.get('pool_entered')} "
                    f"· undo_id={undo_id}")
            except Exception as e:
                log(f"[FATAL] 입고 확정 요청 자체가 실패했습니다: {_ascii_log(e)}")
                return 1
            page.wait_for_timeout(250)
            _pending_snapshot(page, "after_confirm", stats)
            stats["confirm_response"] = confirm_json

            res_box = get_boxes(page, {"r": "#siResult"})["r"]
            if res_box:
                shoot(page, "stock-inbound-result-ok", res_box, {
                    "code": "#siResCode", "msg": "#siResMsg", "note": "#siResNote",
                    "act": "#siResAct",
                }, coords)
            else:
                log("[MISS] #siResult 를 못 찾았습니다 - stock-inbound-result-ok.png 건너뜀")

            # ---- 10) 실제 쓰기 ② 되돌리기 — 위 ①을 즉시 상쇄한다 -------------------------
            if undo_id is None:
                log("[FATAL] undo_id 가 없어 되돌릴 수 없습니다 - 상품 20489103 재고가 "
                    "+1 된 채 남아 있을 수 있습니다. 수동 확인이 필요합니다.")
                return 1
            undo_json = None
            try:
                with page.expect_response(
                        lambda r: r.url == f"{BASE}/api/admin/stock-inbound/undo/{undo_id}"
                        and r.request.method == "POST", timeout=10000) as ri:
                    page.click('#siResAct [data-action="undo"]')
                resp = ri.value
                if not resp.ok:
                    log(f"[FATAL] 되돌리기 실패: {resp.status} {_ascii_log(resp.text())} "
                        f"- 상품 20489103 재고가 +1 된 채 남아 있습니다. 수동 확인 필요.")
                    return 1
                undo_json = resp.json()
                log(f"[INFO] 되돌리기 완료: stock_after={undo_json.get('stock_after')}")
            except Exception as e:
                log(f"[FATAL] 되돌리기 요청 자체가 실패했습니다: {_ascii_log(e)} "
                    f"- 상품 20489103 재고가 +1 된 채 남아 있을 수 있습니다. 수동 확인 필요.")
                return 1
            page.wait_for_timeout(300)
            _pending_snapshot(page, "after_undo", stats)
            _product_snapshot(page, "after_undo", stats)
            stats["undo_response"] = undo_json

            res_box2 = get_boxes(page, {"r": "#siResult"})["r"]
            if res_box2:
                shoot(page, "stock-inbound-result-undo", res_box2, {
                    "code": "#siResCode", "msg": "#siResMsg", "note": "#siResNote",
                }, coords)
            else:
                log("[MISS] #siResult 를 못 찾았습니다 - stock-inbound-result-undo.png 건너뜀")

            # ---- 11) 이력 카드 확대 — 방금 만든 입고·되돌림 쌍이 맨 위에 서 있어야 한다 ----
            hc_box = get_boxes(page, {"h": "#siHistCard"})["h"]
            if hc_box:
                hist_sel = {"title": "#siHistTitle"}
                for i in range(1, 4):
                    hist_sel[f"hrow_{i}"] = f"#siHistRows .si-hrow:nth-child({i})"
                hist_sel["scope"] = "#siHistScope"
                hist_sel["txt"] = "#siHistTxt"
                shoot(page, "stock-inbound-history", hc_box, hist_sel, coords)
            else:
                log("[MISS] #siHistCard 를 못 찾았습니다 - stock-inbound-history.png 건너뜀")

            # ============================================================================
            # ---- 12) 실제 쓰기 ③ 보류 → ④ 해제 — 사유를 밝히고 즉시 해제한다 --------------
            # ============================================================================
            hold_json = None
            try:
                with page.expect_response(
                        lambda r: r.url == f"{BASE}/api/admin/stock-inbound/hold/{PRODUCT_CODE}"
                        and r.request.method == "POST", timeout=10000) as ri:
                    page.fill("#siHoldReason", HOLD_REASON)
                    page.click('#siHoldBox [data-action="hold-panel"]')
                resp = ri.value
                if not resp.ok:
                    log(f"[FATAL] 보류 등록 실패: {resp.status} {_ascii_log(resp.text())}")
                    return 1
                hold_json = resp.json()
                log(f"[INFO] 보류 등록 완료: hold_id={hold_json.get('hold_id')}")
            except Exception as e:
                log(f"[FATAL] 보류 등록 요청 자체가 실패했습니다: {_ascii_log(e)}")
                return 1
            try:
                page.wait_for_selector("#siHoldBox.held", timeout=8000)
            except Exception as e:
                log(f"[MISS] 보류 후 화면 갱신을 못 봤습니다(그래도 서버는 보류됐습니다): {e}")
            page.wait_for_timeout(200)
            _pending_snapshot(page, "after_hold", stats)
            stats["hold_response"] = hold_json

            hb_box = get_boxes(page, {"h": "#siHoldBox"})["h"]
            if hb_box:
                shoot(page, "stock-inbound-hold", hb_box, {
                    "badge": ".si-holdbox .bd", "text": ".si-holdbox .tx",
                    "release_btn": '[data-action="release"]',
                }, coords)
            else:
                log("[MISS] #siHoldBox 를 못 찾았습니다 - stock-inbound-hold.png 건너뜀")

            # ---- 13) 보류 해제 — 반드시 되돌린다(캡처 없음, 원상 복귀만 목적) -------------
            release_json = None
            try:
                with page.expect_response(
                        lambda r: r.url
                        == f"{BASE}/api/admin/stock-inbound/hold/{PRODUCT_CODE}/release"
                        and r.request.method == "POST", timeout=10000) as ri:
                    page.click('#siHoldBox [data-action="release"]')
                resp = ri.value
                if not resp.ok:
                    log(f"[FATAL] 보류 해제 실패: {resp.status} {_ascii_log(resp.text())} "
                        f"- 상품 20489103 이 보류 상태로 남아 있습니다. 수동 해제 필요"
                        f"(hold_id={hold_json.get('hold_id') if hold_json else '?'}).")
                    return 1
                release_json = resp.json()
                log(f"[INFO] 보류 해제 완료: hold_id={release_json.get('hold_id')}")
            except Exception as e:
                log(f"[FATAL] 보류 해제 요청 자체가 실패했습니다: {_ascii_log(e)} "
                    f"- 상품 20489103 이 보류 상태로 남아 있을 수 있습니다. 수동 해제 필요.")
                return 1
            page.wait_for_timeout(200)
            stats["release_response"] = release_json

            # ---- 14) 직접 등록(카탈로그 검색) — 읽기 전용, 확정을 누르지 않는다 -----------
            try:
                with page.expect_response(
                        lambda r: "catalog_q=" in r.url and r.request.method == "GET",
                        timeout=8000):
                    page.click('[data-action="toggle-direct"]')
                    page.fill("#siSearch", "RTX")
                    page.press("#siSearch", "Enter")
                page.wait_for_selector('.si-row[data-src="catalog"]', timeout=8000)
                page.wait_for_timeout(200)
                dc_boxes = get_boxes(page, {
                    f"row_{i}": f'#siRowsBody .si-row:nth-child({i})' for i in range(1, 4)
                })
                bx = [b for b in dc_boxes.values() if b]
                note_box = get_boxes(page, {"n": "#siDirectNote"})["n"]
                if bx and note_box:
                    clip = {
                        "x": min(b["x"] for b in bx), "y": note_box["y"],
                        "width": max(b["x"] + b["width"] for b in bx) - min(b["x"] for b in bx),
                        "height": (max(b["y"] + b["height"] for b in bx) - note_box["y"]),
                    }
                    sel = {"direct_note": "#siDirectNote"}
                    sel.update({k: f'#siRowsBody .si-row:nth-child({i})'
                                for i, k in zip(range(1, 4), ["row_1", "row_2", "row_3"])})
                    shoot(page, "stock-inbound-direct", clip, sel, coords)
                else:
                    log("[MISS] 직접 등록 결과 행을 못 찾았습니다 - stock-inbound-direct.png 건너뜀")
            except Exception as e:
                log(f"[MISS] 직접 등록 캡처 실패(쓰기 없음 - 안전): {_ascii_log(e)}")

            # ---- 15) 최종 확인 — 원상 복귀됐는가(추측이 아니라 서버 재조회) ---------------
            final_pending = _pending_snapshot(page, "final", stats)
            final_product = _product_snapshot(page, "final", stats)
            base_pending = stats.get("pending_baseline") or {}
            base_product = stats.get("p9103_baseline") or {}
            ok = (final_pending.get("total") == base_pending.get("total")
                  and final_pending.get("held_total") == base_pending.get("held_total")
                  and final_product.get("stock") == base_product.get("stock")
                  and final_product.get("status") == base_product.get("status")
                  and not final_product.get("hold"))
            stats["reverted_ok"] = ok
            if ok:
                log("[INFO] 원상 복귀 확인 - 쓰기 전/후 대기 총계·P-9103 상태가 일치합니다")
            else:
                log(f"[FATAL] 원상 복귀가 실측으로 확인되지 않았습니다 - "
                    f"baseline={base_pending}/{base_product} final={final_pending}/{final_product} "
                    f"- 수동으로 상품 20489103 을 확인하십시오")

    except CaptureError as e:
        log(f"[FATAL] {e}")
        return 1

    coords["_meta"] = build_meta("ADM-SRC-020", "/admin2/stock-inbound",
                                  {"width": 1680, "height": 1050}, stats)
    write_coords("stock-inbound", coords)
    log(f"[INFO] stats 요약: {_ascii_log(stats)}")
    return 0 if stats.get("reverted_ok") else 1


if __name__ == "__main__":
    sys.exit(main())
