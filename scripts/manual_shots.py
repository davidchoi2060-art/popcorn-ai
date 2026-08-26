"""운영자 매뉴얼용 화면 캡처 — 상품 사양 검수(ADM-PRD-020, 경로 /admin2/reviews).

2026-08-25 분리(회귀 [41] 후속 작업): 로그인·캡처·좌표 뽑기·비율 환산 같은 공통 부분은
`scripts/manual_capture_common.py`로 옮겼다. 이 파일에는 **이 화면에만 해당하는 것**
(경로·선택자·무엇을 확대할지·이 화면 전용 통계 조회)만 남는다. 새 화면을 찍으려면 이
파일을 고치지 말고 `scripts/manual_shots_<screen>.py`를 새로 만든다 —
`manual_capture_common.py`의 모듈 docstring §「새 화면 캡처를 추가하려면」 참조.

이 파일명·산출물 이름은 바꾸지 않는다 — `docs/manual/screens/reviews.html`과
`docs/manual/운영자매뉴얼-상품사양검수.html`(둘 다 다른 제작자 소유)이 재촬영 명령으로
`.venv/Scripts/python scripts/manual_shots.py`를 문서 본문에 그대로 적어 뒀다.

무엇을 하는가
    1. 로컬 서버(127.0.0.1:8000 — **사장님 서버, 절대 죽이지 않는다**)에 Playwright로 접속한다.
    2. GET /api/admin/auth/dev-login 으로 점검 계정 세션을 심는다
       (.env 의 UI_CHECK_DEV_LOGIN=1 · UI_CHECK_EMAIL 전제 — CLAUDE.md §브라우저 점검 계정).
    3. /admin2/reviews 를 열고 데이터 로드를 기다린 뒤, 화면 전체 + 주요 영역을 PNG로 저장한다.
    4. 각 캡처 안 주요 요소의 "실제" bounding box를 함께 재서 JSON(reviews-coords.json)에 남긴다.
       매뉴얼 HTML의 번호 핀·테두리 상자는 이 JSON의 좌표를 %로 환산해 쓴다 — 지어내지 않는다.

다시 찍을 때
    화면이 바뀌면 이 스크립트를 그대로 다시 돌리면 된다.
        .venv/Scripts/python scripts/manual_shots.py
    기존 PNG·JSON을 덮어쓴다(파일명 고정).

읽기 전용이다 — DB에 쓰지 않는다. 포트 8000에는 dev-login(GET, 세션 생성) 1회와
그 뒤 페이지 로드가 부르는 GET들만 나간다. 화면을 쓰는 동작(승인·기각·되돌리기 등)은
절대 누르지 않는다.

개인정보: 이 화면은 상품 사양(원문값·제안값)만 다룬다 — 고객 이름·이메일·전화번호가
나타나는 자리가 없다(코드 확인: templates/admin/reviews.html.j2 어디에도 고객 테이블
JOIN이 없다 — product_reviews/products/product_specs/spec_web_suggestions/
supplier_price_rows 뿐). 우측 상단 역할 표시에 뜨는 이름은 실제 고객이 아니라
이 점검 전용 계정("UI점검")이다. 그래서 이 화면은 `redact_*`를 쓰지 않는다 — 가릴
개인정보가 애초에 없다(운영자·권한 화면 등 실제 이름이 나오는 화면은 반드시 쓴다).
"""
import sys

from manual_capture_common import (
    BASE, VIEWPORT, CaptureError,
    build_meta, capture_session, get_boxes, log, shoot, union_box, write_coords,
)

# 캡처 후보 개수 상한(테이블 확대컷에 담을 행 수) — 화면이 실제로 대기 건이 적어도
# 예외 없이 동작하도록 최소 1행까지 허용한다.
TABLE_ROWS_IN_SHOT = 6


def main() -> int:
    coords: dict = {}

    try:
        with capture_session() as page:
            # ---- 1) 화면 열기 -------------------------------------------------------
            page.goto(f"{BASE}/admin2/reviews", wait_until="networkidle")
            try:
                page.wait_for_function(
                    "document.getElementById('scopeCount') &&"
                    " document.getElementById('scopeCount').textContent !== '—'",
                    timeout=15000)
            except Exception as e:
                log(f"[FATAL] 목록 데이터가 15초 안에 안 채워졌습니다: {e}")
                return 1
            page.wait_for_timeout(400)  # 렌더 안정화(필드별 대기 막대 애니메이션 등)

            # ---- 2) 전체 화면(뷰포트, 스크롤 없음 — 이 화면은 100vh 고정 레이아웃) ------
            full_clip = {"x": 0, "y": 0, "width": VIEWPORT["width"], "height": VIEWPORT["height"]}
            shoot(page, "reviews-full", full_clip, {
                "lnb": ".a2-lnb",
                "lnb_active_item": ".a2-lnb-b a.on",
                "header": ".a2-hd",
                "crumb": ".a2-crumb",
                "done_today": ".donetoday",
                "undo_btn": "#undoBtn",
                "hub": ".a2-hub",
                "role_box": "#roleBox",
                "avatar": ".a2-avatar",
                "qside": ".qside",
                "scope_count": ".scope-n",
                "live_line": "#liveLine",
                "chunks": "#chunks",
                "id_box": "#idBox",
                "fstats": ".fstats",
                "filterbar": ".filterbar",
                "search_box": "#searchBox",
                "pill_part": "#pillPart",
                "pill_live": "#pillLive",
                "pill_field": "#pillField",
                "pill_status": "#pillStatus",
                "bulk_btn": "#bulkBtn",
                "thead": ".thead",
                "first_row": "#tbody .row:first-child",
                "pager": "#pager",
                "tab_review": "#tabReview",
                "tab_sourcing": "#tabSourcing",
            }, coords)

            # ---- 3) 헤더 확대 --------------------------------------------------------
            hdr_box = get_boxes(page, {"header": ".a2-hd"})["header"]
            if hdr_box:
                shoot(page, "reviews-header", hdr_box, {
                    "crumb": ".a2-crumb",
                    "now": ".a2-now",
                    "done_today": ".donetoday",
                    "undo_btn": "#undoBtn",
                    "hub": ".a2-hub",
                    "role_box": "#roleBox",
                    "avatar": ".a2-avatar",
                }, coords)
            else:
                log("[MISS] .a2-hd 를 못 찾았습니다 — reviews-header.png 건너뜀")

            # ---- 4) 좌측 집계 패널 확대(필터 범위 · 할 수 있는 일 · 정체성 충돌 · 필드별 대기) --
            qside_box = get_boxes(page, {"qside": ".qside"})["qside"]
            if qside_box:
                shoot(page, "reviews-sidebar", qside_box, {
                    "scope_count": ".scope-n",
                    "live_line": "#liveLine",
                    "chunk_all": '.chunk-row[data-chunk="all"]',
                    "chunk_a": '.chunk-row[data-chunk="A"]',
                    "chunk_b": '.chunk-row[data-chunk="B"]',
                    "id_box": "#idBox",
                    "id_count": "#idCount",
                    "id_link": '#idBox [data-action="go-identity"]',
                    "fstats_title": ".fstats-hd",
                    "fstats_list": "#fstatsList",
                    "fstats_first": "#fstatsList .fstat-row:first-child",
                }, coords)
            else:
                log("[MISS] .qside 를 못 찾았습니다 — reviews-sidebar.png 건너뜀")

            # ---- 5) 필터 바 확대 -----------------------------------------------------
            fb_box = get_boxes(page, {"filterbar": ".filterbar"})["filterbar"]
            if fb_box:
                shoot(page, "reviews-filterbar", fb_box, {
                    "search_box": "#searchBox",
                    "pill_part": "#pillPart",
                    "pill_live": "#pillLive",
                    "pill_field": "#pillField",
                    "pill_status": "#pillStatus",
                    "sel_count": "#selCount",
                    "bulk_btn": "#bulkBtn",
                }, coords)
            else:
                log("[MISS] .filterbar 를 못 찾았습니다 — reviews-filterbar.png 건너뜀")

            # ---- 6) 목록 표 확대(머리글 + 앞쪽 N행) -----------------------------------
            row_selectors = [".thead"] + [
                f"#tbody .row:nth-child({i})" for i in range(1, TABLE_ROWS_IN_SHOT + 1)
            ]
            table_clip = union_box(page, row_selectors)
            if table_clip:
                el_sel = {"thead": ".thead"}
                for i in range(1, TABLE_ROWS_IN_SHOT + 1):
                    el_sel[f"row_{i}"] = f"#tbody .row:nth-child({i})"
                shoot(page, "reviews-table", table_clip, el_sel, coords)
            else:
                log("[MISS] 표 행을 못 찾았습니다(대기 0건?) — reviews-table.png 건너뜀")

            # ---- 7) 상세 패널(드로어) — 제안값 있는 행을 우선 골라 연다 -----------------
            target_id = page.evaluate("""() => {
                const rows = Array.from(document.querySelectorAll('#tbody .row'));
                const withSuggestion = rows.find(r => {
                    const sv = r.querySelector('.sv');
                    return sv && !sv.classList.contains('noval');
                });
                const target = withSuggestion || rows[0];
                return target ? target.getAttribute('data-id') : null;
            }""")
            if target_id:
                page.locator(f'#tbody .row[data-id="{target_id}"]').click()
                try:
                    page.wait_for_selector("#drawer:not([hidden])", timeout=5000)
                except Exception as e:
                    log(f"[MISS] 상세 패널이 안 열렸습니다(review_id={target_id}): {e}")
                    target_id = None
                else:
                    page.wait_for_timeout(500)  # loadSiblings() 비동기 응답 대기

            if target_id:
                drawer_box = get_boxes(page, {"drawer": "#drawer"})["drawer"]
                if drawer_box:
                    shoot(page, "reviews-drawer", drawer_box, {
                        "name": "#dwName",
                        "code": "#dwCode",
                        "part": "#dwPart",
                        "created": "#dwCreated",
                        "body": "#dwBody",
                        "compare": ".compare-grid",
                        "specs_cap": ".specs-cap",
                        "specs_wrap": ".specs-wrap",
                        "note": "#dwNote",
                        "btn_reject": '.dw-foot [data-action="reject"]',
                        "btn_manual": '.dw-foot [data-action="manual-open"]',
                        "btn_approve": "#dwApprove",
                    }, coords)

                    # 드로어가 열린 상태의 전체 화면도 하나 남긴다 — "행을 누르면 여기로
                    # 패널이 열린다"는 것 자체를 보여주는 캡처(번호 핀은 드로어 위치만).
                    shoot(page, "reviews-full-detail", full_clip, {
                        "selected_row": f'#tbody .row[data-id="{target_id}"]',
                        "drawer": "#drawer",
                        "btn_approve": "#dwApprove",
                    }, coords)
                else:
                    log("[MISS] #drawer 박스를 못 쟀습니다 — reviews-drawer.png 건너뜀")
            else:
                log("[MISS] 열 수 있는 행이 없습니다 — reviews-drawer.png / reviews-full-detail.png 건너뜀")

            # ---- 7b) "제안 있음" 사례도 하나 더 — 승인 버튼이 실제로 활성화된 상태 --------
            # 위 7)에서 연 행은 정렬 1순위(created_at 오름차순)라 우연히 "값 없음"이었다
            # (큐의 95.7%가 그쪽이라 자연스러운 결과이지만, "제안값 승인" 버튼이 눌리는
            # 모습은 따로 보여줘야 한다). A 청크(제안 있음)로 좁히고 첫 행을 연다.
            page.locator('#chunks .chunk-row[data-chunk="A"]').click()
            try:
                page.wait_for_function(
                    "document.querySelector('#chunks .chunk-row[data-chunk=\"A\"]').classList.contains('on')",
                    timeout=5000)
                page.wait_for_timeout(500)  # 목록 재조회
                sugg_id = page.evaluate("""() => {
                    const row = document.querySelector('#tbody .row');
                    return row ? row.getAttribute('data-id') : null;
                }""")
                if sugg_id:
                    page.locator(f'#tbody .row[data-id="{sugg_id}"]').click()
                    page.wait_for_selector("#drawer:not([hidden])", timeout=5000)
                    page.wait_for_timeout(500)
                    drawer_box2 = get_boxes(page, {"drawer": "#drawer"})["drawer"]
                    if drawer_box2:
                        shoot(page, "reviews-drawer-suggested", drawer_box2, {
                            "name": "#dwName",
                            "body": "#dwBody",
                            "compare": ".compare-grid",
                            "sig_box": ".sig-box",
                            "specs_cap": ".specs-cap",
                            "specs_wrap": ".specs-wrap",
                            "sib_cap": ".sib-cap",
                            "sib_list": ".sib-list",
                            "note": "#dwNote",
                            "btn_reject": '.dw-foot [data-action="reject"]',
                            "btn_manual": '.dw-foot [data-action="manual-open"]',
                            "btn_approve": "#dwApprove",
                        }, coords)
                    else:
                        log("[MISS] #drawer(제안 있음) 박스를 못 쟀습니다")
                else:
                    log("[MISS] A 청크(제안 있음)에 표시된 행이 없습니다 — reviews-drawer-suggested.png 건너뜀")
            except Exception as e:
                log(f"[MISS] 제안 있음 사례 캡처 실패: {e}")

            # ---- 8) 문서용 실측 수치 — 지어내지 않고 API 응답을 그대로 남긴다 ------------
            stats = {}
            try:
                r1 = page.request.get(f"{BASE}/api/admin/reviews?page=1&size=1")
                if r1.ok:
                    j1 = r1.json()
                    stats["queue"] = j1.get("queue")
                    stats["remaining"] = j1.get("remaining")
                    stats["my_today"] = j1.get("my_today")
                    stats["status_counts"] = j1.get("status_counts")
                r2 = page.request.get(f"{BASE}/api/admin/spec-fields")
                if r2.ok:
                    stats["spec_fields"] = r2.json()
            except Exception as e:
                log(f"[MISS] 문서용 수치 조회 실패(캡처는 이미 끝났습니다): {e}")

    except CaptureError as e:
        log(f"[FATAL] {e}")
        return 1

    coords["_meta"] = build_meta("ADM-PRD-020", "/admin2/reviews", VIEWPORT, stats)

    write_coords("reviews", coords)
    q = coords["_meta"]["stats"].get("queue")
    if q:
        log(f"[INFO] 대기 {q.get('total')}건 - 일괄확정 {q.get('bulkable')} / 단건검수 {q.get('single')}"
            f" / 값없음(manual) {q.get('manual')} / 제안있음 {q.get('suggested')}"
            f" / 정체성충돌 {q.get('identity_conflict')} / 판매중재고있음 {q.get('sellable')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
