# -*- coding: utf-8 -*-
"""운영자 매뉴얼용 화면 캡처 — 공급처(ADM-SRC-030, 경로 /admin2/suppliers).

공통 부분(로그인·캡처·좌표 뽑기·비율 환산)은 `scripts/manual_capture_common.py`(공용
도구, 이 파일에서 고치지 않는다)를 그대로 쓴다. 이 파일에는 **이 화면에만 해당하는
것**(경로·선택자·무엇을 확대할지·좋은 예시 행 고르기)만 있다.

■ 개인정보 점검(2026-08-29 실측) — 지금은 이 화면이 담당자명·전화·발주번호를 «보여주지
  않는다.» `suppliers` 테이블에는 그 컬럼이 있다(`contact_name`·`contact_phone`·
  `order_phone`·`contact_raw` — 마이그레이션 0066, 몰 수집 도구 `tools/mall_supplier_fetch.py`
  가 채우는 자리). 그런데 **이 화면이 읽는 API·템플릿 어디에도 그 필드가 없다** —
  실측: `grep -n "contact\\|phone\\|담당자\\|전화\\|연락처" api/admin_suppliers.py
  templates/admin/suppliers.html.j2 api/admin_ui_suppliers.py` 결과 0건, 그리고
  `GET /api/admin/suppliers` 실응답(로그인 세션으로 직접 조회)의 항목 필드는 정확히
  `id·name·platform·brands·status·created·linked_products·price_files·preset_count`
  아홉 개뿐이다. 그래서 이번 캡처에는 가릴 대상이 없다 — 다만 화면이 나중에 바뀌어
  연락처를 노출하기 시작할 수 있으므로, `_scan_contact_leak()`이 **캡처 직전마다** 화면
  전체 텍스트에서 전화번호 모양(00-0000-0000류) 문자열을 훑고, 하나라도 걸리면 즉시
  캡처를 멈춘다(조용히 개인정보를 찍어 버리지 않도록 — 실패를 삼키지 않는다).

■ 절대 제출하지 않는 것 — 실제로 DB를 바꾸는 동작
  등록([등록]) · 수정 저장([저장]) · 중지 확정([중지로 바꿉니다]) · 되살리기([활성으로]/
  [이 공급처를 활성으로 되돌리기]) 는 전부 누르지 않는다. 이 스크립트가 실제로 누르는
  것은 [수정]·[중지] 버튼으로 모달을 «열기»와, 모달을 닫는 [닫기]/[취소]/[그만두기]
  뿐이다 — 전부 서버에 쓰기 요청을 보내지 않는 읽기 동작이다(수정 모달의 입력창은
  기존 값을 그대로 보여줄 뿐 아무것도 다시 채우지 않는다).

무엇을 하는가
    1. 로컬 서버(기본 127.0.0.1:8000 — **사장님 서버, 절대 죽이지 않는다**. 이 화면은
       코드 변경이 없어 8000을 그대로 캡처해도 된다)에 Playwright로 접속한다.
    2. GET /api/admin/auth/dev-login 으로 점검 계정(owner 등급) 세션을 심는다.
    3. /admin2/suppliers 를 열고 목록 로드를 기다린 뒤, 전체 화면 + 주요 영역을 PNG로
       저장한다. [수정] 모달과 [중지] 확인 모달도 열어서 캡처하지만 **어느 것도 제출
       하지 않고 닫는다**(위 참고).
    4. 「유일한 매입처」 카드가 0이 아닌 의미 있는 예시를 보여주기 위해, 연결 상품이
       많은 활성 공급처부터 `GET /api/admin/suppliers/{id}/impact`(읽기 전용)를 조회해
       중지 확인 모달의 대상으로 고른다.
    5. 각 캡처 안 주요 요소의 실측 bounding box를 좌표 JSON(suppliers-coords.json)에
       남긴다. 문서용 실측 수치(공급처 수·활성/중지 등)는 `_meta.stats`에 집계만 남긴다
       (원본 `items` 배열은 저장하지 않는다 — 이번엔 개인정보가 없지만 다른 화면과
       같은 관행을 지킨다).

다시 찍을 때
    .venv/Scripts/python scripts/manual_shots_suppliers.py
    다른 포트를 보려면: --base=http://127.0.0.1:8001 (또는 환경변수 MANUAL_CAPTURE_BASE)
    기존 PNG·JSON을 덮어쓴다(파일명 고정). 공급처 수·활성/중지 건수는 매일 바뀌므로
    `docs/manual/screens/suppliers.html`의 실측 수치도 함께 다시 확인해야 한다.

읽기 전용이다 — DB에 쓰지 않는다. 포트 8000에는 dev-login(GET) 1회와 그 뒤 화면이
스스로 부르는 GET들만 나간다(POST/PATCH는 전혀 없다).
"""
import re
import sys

from manual_capture_common import (
    BASE, VIEWPORT, CaptureError,
    build_meta, capture_session, get_boxes, log, shoot, union_box, write_coords,
)

SCREEN_PATH = "/admin2/suppliers"
SCREEN_ID = "ADM-SRC-030"

TABLE_ROWS_IN_SHOT = 8
IMPACT_CANDIDATES_TO_TRY = 15

# 전화번호 모양 문자열(예: 02-706-0102, 010-1234-5678) — 이 화면이 지금은 이런 값을
# 렌더링하지 않는다(모듈 docstring 참고). 그래도 화면이 바뀌면 이 정규식이 잡는다.
PHONE_RE = re.compile(r"\d{2,4}-\d{3,4}-\d{4}")


def _scan_contact_leak(page, where: str) -> None:
    """캡처 직전 안전망 — 개인정보(전화번호 모양)가 화면에 나타나면 즉시 중단한다.

    이 화면은 2026-08-29 실측으로 담당자명·전화를 노출하지 않는 것을 확인했다(모듈
    docstring). 그 전제가 다음에도 성립하는지 매번 다시 재는 것이지, 통과를 당연히
    여기고 건너뛰지 않는다.
    """
    text = page.evaluate("() => document.body.innerText") or ""
    hits = PHONE_RE.findall(text)
    if hits:
        raise CaptureError(
            f"{where}: 전화번호 모양 문자열 발견 {hits[:5]} — 이 화면은 지금 담당자 연락처를"
            " 렌더링하지 않는 것으로 확인했었는데(모듈 docstring), 코드가 바뀌어 노출되기"
            " 시작했을 수 있습니다. redact 코드를 추가하기 전까지 캡처를 중단합니다.")
    log(f"[OK] {where}: 개인정보(전화번호 모양) 없음 확인")


def _find_best_deactivate_candidate(page) -> dict | None:
    """영향 미리보기의 「유일한 매입처」 카드가 의미 있게 보이는 공급처를 고른다.

    연결 상품이 많은 활성 공급처부터 순서대로 impact(읽기 전용 GET)를 조회해
    `sole_source_products`가 가장 큰 것을 고른다 — 그 카드가 이 모달의 존재 이유이므로
    (정의서 §⑥ "이 창의 «핵심»"), 0건짜리 예시로는 그 이유를 보여줄 수 없다.
    """
    resp = page.request.get(f"{BASE}/api/admin/suppliers")
    if not resp.ok:
        return None
    items = [x for x in resp.json().get("items", []) if x["status"] != "중지"]
    items.sort(key=lambda x: -x["linked_products"])

    best = None
    for it in items[:IMPACT_CANDIDATES_TO_TRY]:
        if it["linked_products"] <= 0:
            break  # 이후로는 전부 0(연결 상품 수 내림차순 정렬) — 더 봐도 소용없다
        imp_resp = page.request.get(f"{BASE}/api/admin/suppliers/{it['id']}/impact")
        if not imp_resp.ok:
            continue
        imp = imp_resp.json()
        if best is None or imp["sole_source_products"] > best["impact"]["sole_source_products"]:
            best = {"item": it, "impact": imp}
        if imp["sole_source_products"] > 0:
            break  # 첫 유의미한 예시로 충분하다 — 굳이 15개를 다 조회하지 않는다
    return best


def main() -> int:
    coords: dict = {}
    stats: dict = {}

    try:
        with capture_session() as page:
            # ---- 1) 화면 열기 -------------------------------------------------------
            page.goto(f"{BASE}{SCREEN_PATH}", wait_until="networkidle")
            try:
                page.wait_for_selector("#spTbody .sp-row", timeout=15000)
            except Exception as e:
                log(f"[FATAL] 공급처 목록이 15초 안에 안 채워졌습니다: {e}")
                return 1
            page.wait_for_timeout(300)
            _scan_contact_leak(page, "목록 로드 직후")

            full_clip = {"x": 0, "y": 0, "width": VIEWPORT["width"], "height": VIEWPORT["height"]}

            # ---- 2) 전체 화면 --------------------------------------------------------
            shoot(page, "suppliers-full", full_clip, {
                "lnb": ".a2-lnb",
                "lnb_active_item": ".a2-lnb-b a.on",
                "header": ".a2-hd",
                "crumb": ".a2-crumb",
                "headbadge": ".sp-headbadge",
                "hub": ".a2-hub",
                "role_box": "#roleBox",
                "avatar": ".a2-avatar",
                "register": ".sp-register",
                "summary": "#spSummary",
                "empty_banner": "#spEmptyBanner",
                "thead": ".sp-thead",
                "tbody": "#spTbody",
                "first_row": "#spTbody .sp-row:first-child",
                "footpanels": ".sp-footpanels",
                "footnote": ".sp-footnote",
            }, coords)

            # ---- 3) 헤더 확대 --------------------------------------------------------
            hdr_box = get_boxes(page, {"header": ".a2-hd"})["header"]
            if hdr_box:
                shoot(page, "suppliers-header", hdr_box, {
                    "crumb": ".a2-crumb",
                    "now": ".a2-now",
                    "headbadge": ".sp-headbadge",
                    "hub": ".a2-hub",
                    "role_box": "#roleBox",
                    "avatar": ".a2-avatar",
                }, coords)
            else:
                log("[MISS] .a2-hd 를 못 찾았습니다 — suppliers-header.png 건너뜀")

            # ---- 4) 등록줄 확대 ------------------------------------------------------
            reg_box = get_boxes(page, {"register": ".sp-register"})["register"]
            if reg_box:
                shoot(page, "suppliers-register", reg_box, {
                    "title": ".sp-register-title",
                    "sub": ".sp-register-sub",
                    "name_field": "#spName",
                    "platform_field": "#spPlatform",
                    "brands_field": "#spBrands",
                    "register_btn": "#spRegisterBtn",
                }, coords)
            else:
                log("[MISS] .sp-register 를 못 찾았습니다 — suppliers-register.png 건너뜀")

            # ---- 5) 목록 표 확대(머리글 + 앞쪽 N행) -----------------------------------
            row_count = page.evaluate("document.querySelectorAll('#spTbody .sp-row').length")
            n = min(TABLE_ROWS_IN_SHOT, row_count)
            if n > 0:
                row_selectors = [".sp-thead"] + [
                    f"#spTbody .sp-row:nth-child({i})" for i in range(1, n + 1)]
                table_clip = union_box(page, row_selectors)
                el_sel = {"thead": ".sp-thead"}
                for i in range(1, n + 1):
                    el_sel[f"row_{i}"] = f"#spTbody .sp-row:nth-child({i})"
                shoot(page, "suppliers-table", table_clip, el_sel, coords)
            else:
                log("[MISS] 표 행이 없습니다 — suppliers-table.png 건너뜀")

            # ---- 6) 중지 상태 행 확대(흐린 배경 · 「활성으로」 버튼) --------------------
            # 정렬 규칙(`ORDER BY (status='중지'), name`)상 중지 행은 목록 맨 끝에
            # 몰려 있다 — 스크롤해야 보인다(thead는 tbody 밖 형제라 스크롤과 무관하게
            # 계속 보인다).
            page.evaluate("""() => {
                var row = document.querySelector('#spTbody .sp-row.inactive');
                if (row) row.scrollIntoView({block: 'center'});
            }""")
            page.wait_for_timeout(150)
            # ⚠ `:first-of-type`를 쓰지 않는다 — 그 가상클래스는 "같은 태그의 형제
            # 중 몇 번째"만 보고 클래스는 안 본다. `.sp-row.inactive:first-of-type`는
            # "inactive이면서 동시에 부모의 첫 <div> 자식"이어야 하는데, 활성 행이
            # 먼저 정렬되므로(`ORDER BY (status='중지'), name`) 그 조건을 만족하는
            # 요소가 영원히 없다 — 1차 실행에서 실제로 못 찾아 thead만 찍혔다(clip이
            # thead 높이 31px과 정확히 같았다). `querySelector`는 클래스 선택자만으로도
            # 이미 문서 순서상 «첫» 일치를 돌려주므로 `.sp-row.inactive`만으로 충분하다.
            inactive_box = union_box(page, [".sp-thead", "#spTbody .sp-row.inactive"])
            if inactive_box:
                shoot(page, "suppliers-row-inactive", inactive_box, {
                    "thead": ".sp-thead",
                    "inactive_row": "#spTbody .sp-row.inactive",
                }, coords)
            else:
                log("[MISS] 중지 상태 행이 없습니다 — suppliers-row-inactive.png 건너뜀"
                    "(지금 중지 0건이라는 뜻일 수 있습니다 — 실측치와 대조하십시오)")
            # 표를 다시 위로 — 다음 단계([수정] 모달)가 위쪽 행을 기준으로 하기 때문
            # (Playwright의 click()이 알아서 스크롤해 주지만, 이후 캡처를 자연스러운
            # 스크롤 위치에서 찍기 위해 미리 되돌린다).
            page.evaluate("""() => {
                var b = document.getElementById('spTbody'); if (b) b.scrollTop = 0;
            }""")
            page.wait_for_timeout(100)

            # ---- 7) 하단 2단 + 삭제 없음 안내 -----------------------------------------
            foot_box = union_box(page, [".sp-footpanels", ".sp-footnote"])
            if foot_box:
                shoot(page, "suppliers-footpanels", foot_box, {
                    "preset_warn_panel": ".sp-panel-warn",
                    "preset_warn_count": "#spPresetWarnCount",
                    "judge_panel": ".sp-footpanels .sp-panel:not(.sp-panel-warn)",
                    "footnote": ".sp-footnote",
                }, coords)
            else:
                log("[MISS] .sp-footpanels 를 못 찾았습니다 — suppliers-footpanels.png 건너뜀")

            # ---- 8) [수정] 모달(제출하지 않는다) --------------------------------------
            edit_btn = page.locator('#spTbody [data-action="open-edit"]').first
            edit_id = edit_btn.get_attribute("data-id") if edit_btn.count() else None
            if edit_id:
                edit_btn.click()
                try:
                    page.wait_for_selector("#spModalOverlay:not([hidden])", timeout=5000)
                    page.wait_for_timeout(200)
                except Exception as e:
                    log(f"[MISS] 수정 모달이 안 열렸습니다(id={edit_id}): {e}")
                    edit_id = None
            else:
                log("[MISS] 열 수 있는 [수정] 버튼이 없습니다 — 수정 모달 캡처 건너뜀")

            if edit_id:
                _scan_contact_leak(page, "수정 모달 열림")
                shoot(page, "suppliers-full-editmodal", full_clip, {
                    "clicked_row": f'#spTbody .sp-row[data-id="{edit_id}"]',
                    "modal": "#spModal",
                }, coords)
                modal_box = get_boxes(page, {"modal": "#spModal"})["modal"]
                if modal_box:
                    shoot(page, "suppliers-modal-edit", modal_box, {
                        "title": ".sm-title",
                        "close_btn": ".sm-close",
                        "name_input": "#smName",
                        "platform_input": "#smPlatform",
                        "brands_input": "#smBrands",
                        "status_note": ".sm-inlinenote",
                        # ⚠ 헤더 X(.sm-close)와 하단 [취소]가 둘 다 data-action="close-modal"을
                        # 쓴다 — 선택자를 `.sm-close`와 똑같이 두면 querySelector가 항상 같은
                        # (첫) 요소만 돌려줘 두 좌표가 겹쳐 찍혔다(1~2차 실행에서 실제로 겹침).
                        # `.sm-foot` 안으로 좁혀 하단 버튼만 가리키게 한다.
                        "cancel_btn": '.sm-foot [data-action="close-modal"]',
                        "save_btn": '[data-action="save-edit"]',
                    }, coords)
                else:
                    log("[MISS] #spModal 박스를 못 쟀습니다 — suppliers-modal-edit.png 건너뜀")
                # 저장하지 않고 닫는다 — data-action="close-modal"은 헤더 X·하단 취소
                # 두 곳에 있어(strict mode) .first로 좁힌다.
                # ⚠ state="hidden"이어야 한다 — 기본값 state="visible"은 "표시된 요소를
                # 기다림"이라 [hidden] 속성 선택자와 모순돼(숨어야 맞는데 보여야 통과) 항상
                # 타임아웃 났다(1차 실행에서 실제로 걸림).
                page.locator('[data-action="close-modal"]').first.click()
                page.wait_for_selector("#spModalOverlay", state="hidden", timeout=5000)
                page.wait_for_timeout(150)

            # ---- 9) [중지] 확인 모달(제출하지 않는다) — 「유일한 매입처」 유의미 예시 ---
            best = _find_best_deactivate_candidate(page)
            deact_id = best["item"]["id"] if best else None
            if deact_id:
                page.evaluate("""(sid) => {
                    var row = document.querySelector('#spTbody .sp-row[data-id="' + sid + '"]');
                    if (row) row.scrollIntoView({block: 'center'});
                }""", str(deact_id))
                page.wait_for_timeout(150)
                deact_btn = page.locator(
                    f'#spTbody .sp-row[data-id="{deact_id}"] [data-action="open-deactivate"]')
                if deact_btn.count():
                    deact_btn.first.click()
                    try:
                        page.wait_for_selector("#spModalOverlay:not([hidden])", timeout=5000)
                        page.wait_for_function(
                            "document.querySelector('.sm-cards') !== null", timeout=5000)
                        page.wait_for_timeout(200)
                    except Exception as e:
                        log(f"[MISS] id={deact_id} 중지 확인 모달의 영향 카드가 안 열렸습니다: {e}")
                        deact_id = None
                else:
                    log(f"[MISS] id={deact_id} 행의 [중지] 버튼을 못 찾았습니다")
                    deact_id = None
            else:
                log("[MISS] 중지 예시로 쓸 활성 공급처를 찾지 못했습니다")

            if deact_id:
                _scan_contact_leak(page, "중지 확인 모달 열림")
                shoot(page, "suppliers-full-deactivatemodal", full_clip, {
                    "clicked_row": f'#spTbody .sp-row[data-id="{deact_id}"]',
                    "modal": "#spModal",
                }, coords)
                modal_box2 = get_boxes(page, {"modal": "#spModal"})["modal"]
                if modal_box2:
                    shoot(page, "suppliers-modal-deactivate", modal_box2, {
                        "title": ".sm-title",
                        "id_tag": ".sm-idtag",
                        "cards": ".sm-cards",
                        "card_linked": ".sm-card:nth-child(1)",
                        "card_files": ".sm-card:nth-child(2)",
                        "card_sole": ".sm-card.danger",
                        "callout": ".sm-callout",
                        "result": ".sm-result",
                        "close_btn": ".sm-close",
                        # 위 수정 모달과 같은 이유로 `.sm-foot` 안으로 좁힌다 — 안 좁히면
                        # querySelector가 DOM 순서상 앞선 헤더 X를 돌려준다.
                        "cancel_btn": '.sm-foot [data-action="close-modal"]',
                        "confirm_btn": '[data-action="confirm-deactivate"]',
                    }, coords)
                else:
                    log("[MISS] #spModal 박스를 못 쟀습니다 — suppliers-modal-deactivate.png 건너뜀")
                page.locator('[data-action="close-modal"]').first.click()
                page.wait_for_selector("#spModalOverlay", state="hidden", timeout=5000)

            # ---- 10) 문서용 실측 수치 — 집계만 남긴다 ---------------------------------
            try:
                r1 = page.request.get(f"{BASE}/api/admin/suppliers")
                if r1.ok:
                    j1 = r1.json()
                    items = j1.get("items", [])
                    stats["suppliers"] = {
                        "total": j1.get("total"),
                        "active": j1.get("active"),
                        "inactive": j1.get("inactive"),
                        "no_preset_count": j1.get("no_preset_count"),
                        "empty": j1.get("empty"),
                        "zero_usage_count": sum(
                            1 for x in items if x["linked_products"] == 0 and x["price_files"] == 0),
                        "max_linked": max((x["linked_products"] for x in items), default=0),
                        "best_example": ({
                            "id": best["item"]["id"],
                            "linked_products": best["impact"]["linked_products"],
                            "price_files": best["impact"]["price_files"],
                            "sole_source_products": best["impact"]["sole_source_products"],
                        } if best else None),
                    }
            except Exception as e:
                log(f"[MISS] 문서용 수치 조회 실패(캡처는 이미 끝났습니다): {e}")

    except CaptureError as e:
        log(f"[FATAL] {e}")
        return 1

    coords["_meta"] = build_meta(SCREEN_ID, SCREEN_PATH, VIEWPORT, stats)
    write_coords("suppliers", coords)

    sp = coords["_meta"]["stats"].get("suppliers")
    if sp:
        log(f"[INFO] 공급처 {sp['total']}곳 - 활성 {sp['active']} / 중지 {sp['inactive']}"
            f" · 프리셋 없음 {sp['no_preset_count']}곳 · 미사용(연결0·파일0) {sp['zero_usage_count']}곳"
            f" · 최대연결 {sp['max_linked']}건"
            + (f" · 예시 id={sp['best_example']['id']}(유일매입처 {sp['best_example']['sole_source_products']}개)"
               if sp.get("best_example") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
