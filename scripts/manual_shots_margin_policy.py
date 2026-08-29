r"""운영자 매뉴얼용 화면 캡처 — 마진 정책(ADM-PRC-020, 경로 /admin2/margin-policy).

`scripts/manual_capture_common.py`(공용 로그인·캡처·좌표 뽑기)를 그대로 쓴다. 이 파일에는
**이 화면에만 해당하는 것**(선택자·무엇을 확대할지·이 화면 전용 통계 조회)만 있다.
공용 모듈은 고치지 않았다 — 동시에 다른 화면을 만드는 제작자들이 같은 모듈을 쓴다.

■★ 화면 값의 출처 — 캡처 전에 코드로 확인한 것(제작 보고서에 그대로 옮긴다)
    ① 카드수수료 · ② 전역 마진   pricing_settings 테이블(이력형 · INSERT만) — 진짜 DB.
                                 POST /api/admin/pricing-settings(owner만)로 고칠 수 있다.
    ③ 분류별 예외                 category_margin_policies 테이블 — 진짜 DB, 지금 0행.
                                 0행이 이 표의 «정상 상태»다(운영자가 아직 예외를 안 걸었을
                                 뿐 — "설정을 못 불러온" 상태가 아니다). PUT
                                 /api/admin/categories/{cid}/margin(owner+operator)로
                                 고칠 수 있다 — 이 화면의 서랍이 그 API를 그대로 쓴다.
    ④ 부품별 예산 배분율          candidates.BUDGET_ALLOC — **진짜 코드 상수**(DB 테이블
                                 자체가 없다). 화면은 "읽기 전용 · 향후 사용예정" 배지를
                                 달아 이미 스스로 밝히고 있고, 입력칸도 버튼도 없다 — "바꿀
                                 수 있는 것처럼 보이는데 안 되는" 함정이 아니다(실측 확인).
    ⇒ 지시서가 인용한 "모듈 docstring이 '코드 상수로 대체 표시 중'이라고 적고 있다"는
      문장은 `api/admin_ui_margin_policy.py`에는 없다 — grep으로 찾아보니 실제로는
      **다른 화면**(`api/admin_engine_rules.py`, "추천 기준 보기" ADM-ENG-020)의
      모듈 docstring 4행에 있는 문장이었다. 그 화면이 코드 상수로 대체 표시 중인 항목도
      배분율(BUDGET_ALLOC)과 policy_weights(0행)이므로 대상은 같지만, 인용 출처가 이
      화면 자신이 아니라는 점은 정정해 둔다(제작 보고서 참고).

■★ 화면 자신의 문구가 이미 낡은 곳 하나 — 캡처 전에 발견(고치지 않음, 이 화면 담당 밖)
    우측 aside "이 화면에서 안 하는 것" 카드가 "대량 재계산 실행 → 판매가 재산정 —
    화면 없음"이라고 적어 뒀다. 그런데 `api/admin_nav.py`(2026-08-15 6차 이후)에는
    이미 ("판매가 재산정", "/admin2/reprice", None)가 등록돼 있고 라우트 파일
    `api/admin_ui_reprice.py`(ADM-PRC-050)도 실재한다 — 화면이 만들어질 당시(3차,
    "050은 제작 중")보다 nav가 나중에 갱신됐는데 이 화면의 정적 문구는 안 바뀐 것으로
    보인다. `templates/admin/margin_policy.html.j2`는 이번 작업 담당 파일 밖이라 고치지
    않았다 — 매뉴얼 본문에서 이 사실을 그대로 밝히고 실제 위치(/admin2/reprice)를
    안내한다.

■★ 페이지가 뷰포트(1680x1050)보다 훨씬 길다 — 캡처 설계를 바꾼 이유
    `.mp-page{overflow-y:auto}` 안에 카드 넷 + 우측 aside가 세로로 쌓여 있고, 실측
    전체 높이가 약 2,310px다(뷰포트 1,050px의 두 배 이상). 표준 뷰포트에서 아래쪽
    카드를 그대로 클립하면 Playwright가 "Clipped area is either empty or outside the
    resulting image"로 죽는다(카드③에서 실제로 죽는 것을 확인). 그래서 두 단계로 찍는다:
      1단계(표준 1680x1050) — 전체 화면 첫인상(그림 A) · 헤더 · 상단 경고 밴드 ·
        «서랍»(고정 위치 요소라 뷰포트를 키우면 이상하게 늘어난다 — 표준 크기라야 실제
        모습과 같다). 서랍을 열 때 대상 행이 접힌 화면 아래에 있으면 Playwright의 클릭이
        자동으로 스크롤한다(별도 스크롤 코드 불필요).
      2단계(뷰포트를 1680x2360으로 늘림, `page.set_viewport_size` — 재로그인·재로드
        없이 같은 세션에서 리플로우만 일어난다) — 늘어난 뷰포트 안에서는 `.mp-page`가
        더 이상 내부 스크롤을 하지 않아(전체 콘텐츠가 한 화면에 다 들어감) 카드 ①~④와
        aside를 스크롤 계산 없이 그대로 클립할 수 있다. 2,360px는 실측 콘텐츠 하단
        (footnote bottom ≈ 2,311px)에 여유 49px를 더한 값 — 화면이 더 길어지면 이
        상수를 다시 재야 한다(TALL_HEIGHT 주석 참고).

■ 쓰기 동작 다섯 개를 하나씩 확인해 클릭 여부를 정했다(전부 코드 확인, 실행 전에):
    · 「미리보기」(카드수수료·전역 마진 둘 다) — **GET** `/api/admin/reprice/preview`다
      (`apiGet()`만 부른다 — POST/PUT 아님). 값을 저장하지 않는다 — **클릭한다.**
    · 「확인하고 저장」(POST pricing-settings) · 서랍의 「확인하고 저장」(PUT category
      margin) · 「확인하고 삭제」(PUT margin:null) — 전부 실제 값을 바꾼다.
      **클릭하지 않는다.**
    · 서랍의 마진율 입력칸에 값을 채우는 것(`page.fill`)은 `input` 이벤트가
      `S.drawer.value`(로컬 상태)만 바꾸고 fetch를 전혀 부르지 않는다(직접 확인,
      categories 화면의 정렬순서 입력과 같은 패턴) — **입력은 하되 저장 버튼은 누르지
      않는다.** 실제로 「확인하고 저장」이 활성화되려면 ①②의 입력값이 저장된 값과
      달라야 하는데, 이 스크립트는 ①②의 입력칸을 한 번도 바꾸지 않으므로 그 버튼은
      캡처 내내 비활성 상태로 남는다(코드로 이중 확인).

삭제 확인 화면(그림에 없음, 의도적) — 서랍의 "예외 삭제" 버튼은 `hasOwn`(이 분류에 이미
자기 마진이 걸려 있음)일 때만 나타나는데, category_margin_policies가 0행이라 지금 어느
분류도 `hasOwn`이 아니다. 그 화면을 보여주려면 먼저 실제로 예외를 하나 저장해야 하는데
그건 위 금지 사항이라, 이 스크립트는 삭제 확인 뷰를 캡처하지 않는다 — 매뉴얼 본문이 그
이유를 밝힌다(지어낸 스크린샷을 만들지 않는다).

무엇을 하는가
    1. 로컬 서버(기본 127.0.0.1:8000 — **사장님 서버, 절대 죽이지 않는다**. `--base=`
       또는 MANUAL_CAPTURE_BASE로 다른 포트를 가리킬 수 있다)에 Playwright로 접속한다.
    2. GET /api/admin/auth/dev-login으로 점검 계정 세션을 심는다.
    3. 표준 뷰포트에서 전체 화면·헤더·상단 경고·서랍 흐름을 찍는다.
    4. 뷰포트를 늘려 카드 ①~④와 우측 aside를 스크롤 없이 찍는다.
    5. 각 캡처 안 요소의 실측 bounding box를 좌표 JSON(margin-policy-coords.json)에 남긴다.

다시 찍을 때
    .venv/Scripts/python scripts/manual_shots_margin_policy.py
    기존 PNG·JSON을 덮어쓴다(파일명 고정) — 화면이 바뀌면 다시 돌린다. 화면이 더 길어져
    카드③ 등이 다시 클립 오류를 내면 TALL_HEIGHT를 실측 footnote bottom + 40px 정도로
    올려라(간이 진단: `.mp-footnote`의 getBoundingClientRect().bottom을 표준 뷰포트에서
    그대로 읽으면 된다 — 레이아웃은 폭에만 의존하고 뷰포트 높이에는 의존하지 않는다).
"""
import sys

from manual_capture_common import (
    BASE, VIEWPORT, CaptureError,
    build_meta, capture_session, get_boxes, log, shoot, union_box, write_coords,
)

# 실측 콘텐츠 하단(footnote bottom) ≈ 2,311px(2026-08-29) + 여유 49px. 위 docstring
# "페이지가 뷰포트보다 훨씬 길다" 참고 — 화면이 더 길어지면 이 값을 다시 잰다.
TALL_VIEWPORT = {"width": VIEWPORT["width"], "height": 2360}

# 분류 목록 서랍 데모용 — 하위(leaf) 분류 하나를 고른다(대분류보다 실제 운영에서 예외를
# 거는 자리에 더 가깝다 — GPU·SSD 같은 소분류). 첫 leaf 행을 고르되, 없으면 대분류로
# 대체한다(방어적 — 트리 깊이가 바뀌어도 스크립트가 죽지 않게).
_PICK_LEAF_JS = r"""() => {
    const rows = Array.from(document.querySelectorAll('#mpCatList .mp-cat-row'));
    const leaf = rows.find(r => !r.classList.contains('top'));
    if (leaf) return leaf.getAttribute('data-cid');
    return rows.length ? rows[0].getAttribute('data-cid') : null;
}"""


def main() -> int:
    coords: dict = {}
    stats: dict = {}

    try:
        with capture_session() as page:
            # ---- 1) 화면 열기(표준 뷰포트) --------------------------------------------
            page.goto(f"{BASE}/admin2/margin-policy", wait_until="networkidle")
            try:
                page.wait_for_function(
                    "document.getElementById('mpCatList') &&"
                    " document.getElementById('mpCatList').children.length > 0 &&"
                    " document.getElementById('mpMarginSaved') &&"
                    " document.getElementById('mpMarginSaved').textContent !== '—'",
                    timeout=15000)
            except Exception as e:
                log(f"[FATAL] 분류 목록/마진 기준값이 15초 안에 안 채워졌습니다: {e}")
                return 1
            page.wait_for_timeout(400)  # roleBox 등 meReady 후속 렌더 안정화

            std_clip = {"x": 0, "y": 0, "width": VIEWPORT["width"], "height": VIEWPORT["height"]}

            # ---- 2) 전체 화면 첫인상(스크롤 전) — 아래쪽 카드는 접혀 있어 안 보인다 -------
            shoot(page, "margin-policy-full", std_clip, {
                "lnb": ".a2-lnb",
                "lnb_active_item": ".a2-lnb-b a.on",
                "header": ".a2-hd",
                "crumb": ".a2-crumb",
                "hub": ".a2-hub",
                "role_box": "#roleBox",
                "avatar": ".a2-avatar",
                "warn": ".mp-warn",
                "permnote": ".mp-permnote",
                "card_fee_title": ".mp-card.mp-card-red h2",
                "card_margin_title": ".mp-card.mp-card-blue h2",
                "aside_title": ".mp-aside-amber .mp-aside-t",
            }, coords)

            # ---- 3) 헤더 확대 ---------------------------------------------------------
            hdr_box = get_boxes(page, {"header": ".a2-hd"})["header"]
            if hdr_box:
                shoot(page, "margin-policy-header", hdr_box, {
                    "crumb": ".a2-crumb",
                    "now": ".a2-now",
                    "hub": ".a2-hub",
                    "role_box": "#roleBox",
                    "avatar": ".a2-avatar",
                }, coords)
            else:
                log("[MISS] .a2-hd 를 못 찾았습니다 - margin-policy-header.png 건너뜀")

            # ---- 4) 상단 경고 + 권한 안내 확대 -----------------------------------------
            warn_clip = union_box(page, [".mp-warn", ".mp-permnote"])
            if warn_clip:
                shoot(page, "margin-policy-warn", warn_clip, {
                    "warn": ".mp-warn",
                    "warn_title": ".mp-warn-t",
                    "warn_ref": ".mp-warn-ref",
                    "permnote": ".mp-permnote",
                }, coords)
            else:
                log("[MISS] .mp-warn/.mp-permnote 를 못 찾았습니다 - margin-policy-warn.png 건너뜀")

            # ---- 5) 서랍 — 하위 분류(leaf) 행을 골라 연다(읽기 전용 — API 호출 없음) -----
            # 표준 뷰포트에서 한다 — 서랍은 position:fixed라 뷰포트를 늘리면 실제보다
            # 길게 늘어져 보인다(2단계로 미루지 않는 이유). 대상 행이 접힌 화면 아래
            # 있으면 Playwright의 click()이 actionability 체크의 일부로 자동 스크롤한다.
            target_cid = page.evaluate(_PICK_LEAF_JS)
            if not target_cid:
                log("[MISS] 열 수 있는 분류 행이 없습니다 - 서랍 캡처 전체 건너뜀")
            else:
                page.locator(
                    f'#mpCatList .mp-cat-row[data-cid="{target_cid}"]'
                    f' [data-action="open-drawer"]').click()
                try:
                    page.wait_for_selector("#mpDrawer:not([hidden])", timeout=5000)
                except Exception as e:
                    log(f"[MISS] 서랍이 안 열렸습니다(category_id={target_cid}): {e}")
                    target_cid = None
                else:
                    page.wait_for_timeout(300)

            if target_cid:
                # 서랍이 열린 전체 화면 — "행을 누르면 여기로 열린다"를 보여준다.
                shoot(page, "margin-policy-full-drawer", std_clip, {
                    "selected_row": f'#mpCatList .mp-cat-row[data-cid="{target_cid}"]',
                    "scrim": "#mpScrim",
                    "drawer": "#mpDrawer",
                }, coords)

                drawer_box = get_boxes(page, {"drawer": "#mpDrawer"})["drawer"]
                if drawer_box:
                    shoot(page, "margin-policy-drawer", drawer_box, {
                        "title": "#mpDrawerTitle",
                        "sub": "#mpDrawerSub",
                        "close_btn": ".mp-drawer-x",
                        "value_input": "#mpDrawerValueInput",
                        "hint": ".mp-drawer-body .mp-hint",
                        "impact_grid": ".mp-drawer-body .mp-impact-grid",
                        "notice": ".mp-drawer-body .mp-notice",
                        "redbox": ".mp-drawer-body .mp-redbox",
                        "footbtns": ".mp-drawer-footbtns",
                        "save_btn": '[data-action="confirm-save"]',
                    }, coords)
                else:
                    log("[MISS] #mpDrawer 박스를 못 쟀습니다 - margin-policy-drawer.png 건너뜀")

                # ---- 5b) 미저장(dirty) 상태 — 마진율 입력만 바꾼다(로컬 상태, API 호출 없음) --
                try:
                    cur = page.eval_on_selector("#mpDrawerValueInput", "el => el.value")
                    try:
                        new_val = str(round(float(cur) + 3, 3))
                    except (TypeError, ValueError):
                        new_val = "15"
                    page.fill("#mpDrawerValueInput", new_val)
                    page.wait_for_timeout(200)
                    drawer_box2 = get_boxes(page, {"drawer": "#mpDrawer"})["drawer"]
                    if drawer_box2:
                        shoot(page, "margin-policy-drawer-dirty", drawer_box2, {
                            "value_input": "#mpDrawerValueInput",
                            "formula": ".mp-drawer-body .mp-formula",
                            "save_btn": '[data-action="confirm-save"]',
                            "footbtns": ".mp-drawer-footbtns",
                        }, coords)
                    else:
                        log("[MISS] dirty 상태 #mpDrawer 박스를 못 쟀습니다")
                except Exception as e:
                    log(f"[MISS] 미저장 상태 캡처 실패(입력칸에 값만 채웠고 서버로는 아무것도 "
                        f"안 나갑니다): {e}")

                # 서랍 안에 「닫기(✕)」와 「취소」 둘 다 data-action="close-drawer"라
                # 일반 선택자는 strict-mode 위반(요소 2개)이다 — 헤더 ✕ 버튼으로 좁힌다.
                page.locator('.mp-drawer-x[data-action="close-drawer"]').click()
                page.wait_for_timeout(150)

            # ---- 6) 뷰포트를 늘린다 — 이제부터 `.mp-page` 내부 스크롤이 없다 --------------
            page.set_viewport_size(TALL_VIEWPORT)
            page.wait_for_timeout(300)
            page.evaluate("() => { const p = document.querySelector('.mp-page');"
                           " if (p) p.scrollTop = 0; }")
            page.wait_for_timeout(150)

            # ---- 7) ① 카드수수료 — 「미리보기」(GET, 값 변경 없음)를 눌러 영향 표를 채운다 --
            page.locator('#mpCardPreviewBtn').click()
            try:
                page.wait_for_function(
                    "document.getElementById('mpCardImpact') &&"
                    " document.getElementById('mpCardImpact').querySelector('.mp-impact-grid') !== null",
                    timeout=15000)
            except Exception as e:
                log(f"[MISS] 카드수수료 미리보기가 15초 안에 안 채워졌습니다(캡처는 계속합니다): {e}")
            page.wait_for_timeout(200)

            card_box = get_boxes(page, {"card": ".mp-card.mp-card-red"})["card"]
            if card_box:
                shoot(page, "margin-policy-card-fee", card_box, {
                    "title": ".mp-card.mp-card-red h2",
                    "badge": ".mp-card.mp-card-red .mp-badge",
                    "saved": "#mpCardSaved",
                    "input": "#mpCardInput",
                    "impact": "#mpCardImpact",
                    "compare_note": "#mpCardCompareNote",
                    "preview_btn": "#mpCardPreviewBtn",
                }, coords)
            else:
                log("[MISS] .mp-card-red 를 못 찾았습니다 - margin-policy-card-fee.png 건너뜀")

            # ---- 8) ② 전역 기본 마진율(boot 시 이미 로드됨) ----------------------------
            margin_box = get_boxes(page, {"card": ".mp-card.mp-card-blue"})["card"]
            if margin_box:
                shoot(page, "margin-policy-card-margin", margin_box, {
                    "title": ".mp-card.mp-card-blue h2",
                    "saved": "#mpMarginSaved",
                    "input": "#mpMarginInput",
                    "formula": "#mpFormula",
                    "impact": "#mpMarginImpact",
                    "notice": ".mp-card.mp-card-blue .mp-notice",
                    "preview_btn": "#mpMarginPreviewBtn",
                    "save_btn": "#mpPricingSaveBtn",
                    "cancel_btn": "#mpPricingCancelBtn",
                    "savenote": ".mp-card.mp-card-blue .mp-savenote",
                }, coords)
            else:
                log("[MISS] .mp-card-blue 를 못 찾았습니다 - margin-policy-card-margin.png 건너뜀")

            # ---- 9) ③ 분류별 예외 — 34행(현재 전부 전역 상속) ---------------------------
            cat_box = get_boxes(page, {"card": ".mp-card.mp-card-green"})["card"]
            if cat_box:
                shoot(page, "margin-policy-card-category", cat_box, {
                    "title": ".mp-card.mp-card-green h2",
                    "badge": "#mpCatBadge",
                    "text": "#mpCatText",
                    "chips": "#mpCatChips",
                    "first_chip": "#mpCatChips .mp-chip:first-child",
                    "list": "#mpCatList",
                    "first_row": "#mpCatList .mp-cat-row:first-child",
                    "bottom1": "#mpCatBottom1",
                    "add_btn": '[data-action="add-exception"]',
                }, coords)
            else:
                log("[MISS] .mp-card-green 를 못 찾았습니다 - margin-policy-card-category.png 건너뜀")

            # ---- 10) ④ 부품별 예산 배분율(읽기 전용) -----------------------------------
            budget_box = get_boxes(page, {"card": ".mp-card.mp-card-gray"})["card"]
            if budget_box:
                shoot(page, "margin-policy-card-budget", budget_box, {
                    "title": ".mp-card.mp-card-gray h2",
                    "badge": ".mp-card.mp-card-gray .mp-badge",
                    "chips": "#mpBudgetChips",
                    "first_chip": "#mpBudgetChips .mp-budget-chip:first-child",
                    "note": ".mp-card.mp-card-gray .mp-card-note",
                }, coords)
            else:
                log("[MISS] .mp-card-gray 를 못 찾았습니다 - margin-policy-card-budget.png 건너뜀")

            # ---- 11) 우측 aside(이력 요약 · 저장 시점 · 이 화면에서 안 하는 것) ----------
            aside_box = get_boxes(page, {"aside": ".mp-aside"})["aside"]
            if aside_box:
                shoot(page, "margin-policy-aside", aside_box, {
                    "hist_card": ".mp-aside-amber",
                    "hist_big": "#mpHistBig",
                    "hist_link": "#mpHistLink",
                    "scope_card": ".mp-aside-card:nth-child(3)",
                    "go_price_review": "#mpGoPriceReview",
                    "go_sale_price": "#mpGoSalePrice",
                    "go_price_history": "#mpGoPriceHistory",
                }, coords)
            else:
                log("[MISS] .mp-aside 를 못 찾았습니다 - margin-policy-aside.png 건너뜀")

            # ---- 12) 문서용 실측 수치 — 지어내지 않고 API 응답을 그대로 남긴다 -----------
            try:
                r1 = page.request.get(f"{BASE}/api/admin/categories")
                if r1.ok:
                    j1 = r1.json()
                    items = j1.get("items") or []
                    stats["categories_total"] = len(items)
                    stats["categories_top"] = sum(1 for i in items if i.get("parent_id") is None)
                    stats["categories_sub"] = stats["categories_total"] - stats["categories_top"]
                    stats["categories_with_own_margin"] = sum(
                        1 for i in items if i.get("margin_rate") is not None)
                    stats["unmapped"] = j1.get("unmapped")
                    stats["default_margin"] = j1.get("default_margin")

                r2 = page.request.get(f"{BASE}/api/admin/reprice/preview?scope=live")
                if r2.ok:
                    stats["preview_live"] = r2.json()
                r3 = page.request.get(f"{BASE}/api/admin/reprice/preview?scope=all")
                if r3.ok:
                    stats["preview_all"] = r3.json()

                hist_text = page.eval_on_selector("#mpHistBig", "el => el.textContent").strip()
                stats["history_summary_text"] = hist_text
                stats["cat_badge_text"] = page.eval_on_selector(
                    "#mpCatBadge", "el => el.textContent").strip()
                stats["cat_text"] = page.eval_on_selector(
                    "#mpCatText", "el => el.textContent").strip()
                stats["nav_reprice_linked"] = page.evaluate(
                    "() => !!Array.from(document.querySelectorAll('.a2-lnb-b a'))"
                    ".find(a => a.getAttribute('href') === '/admin2/reprice')")
            except Exception as e:
                log(f"[MISS] 문서용 수치 조회 실패(캡처는 이미 끝났습니다): {e}")

    except CaptureError as e:
        log(f"[FATAL] {e}")
        return 1

    coords["_meta"] = build_meta("ADM-PRC-020", "/admin2/margin-policy", VIEWPORT, stats)
    write_coords("margin-policy", coords)

    if stats.get("categories_total") is not None:
        log(f"[INFO] 분류 {stats.get('categories_total')}건(대분류 {stats.get('categories_top')} "
            f"· 소분류 {stats.get('categories_sub')}) - 자기 마진 걸림 "
            f"{stats.get('categories_with_own_margin')} · 미배정 {stats.get('unmapped')} "
            f"· 전역 마진 {stats.get('default_margin')}")
    pl = stats.get("preview_live") or {}
    if pl:
        log(f"[INFO] scope=live 미리보기 - 대상 {pl.get('target')} · 오름 {pl.get('up_count')} "
            f"· 내림 {pl.get('down_count')} · 변화없음 {pl.get('same')} · 잠김 {pl.get('locked_count')}")
    if stats.get("history_summary_text"):
        log(f"[INFO] 이력 요약 카드 텍스트: {stats['history_summary_text']}")
    log(f"[INFO] '판매가 재산정' LNB 링크 실재 여부: {stats.get('nav_reprice_linked')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
