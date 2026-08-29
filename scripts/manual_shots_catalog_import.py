# -*- coding: utf-8 -*-
"""운영자 매뉴얼용 화면 캡처 — 상품 일괄 등록(ADM-CSV-010, 경로 /admin2/catalog-import).

공통 부분(로그인·캡처·좌표 뽑기·비율 환산·개인정보 가리기)은
`scripts/manual_capture_common.py`(공용 도구, 이 파일에서 고치지 않는다)를 그대로
쓴다. 이 파일에는 **이 화면에만 해당하는 것**(경로·선택자·무엇을 확대할지·더미 CSV·
개인정보를 어디서 가릴지)만 있다.

■★ 이 화면은 가장 위험한 쓰기 화면이다 — 그런데도 안전하게 캡처할 수 있는 이유
  ① 미리보기(드라이런, `POST /api/admin/catalog-import/dryrun`)는 **DB를 전혀 쓰지
    않는다** — `api/catalog_ingest.py`의 `build_plan()` 독스트링이 스스로 "DB를 바꾸지
    않는다 — 이 결과가 곧 드라이런 리포트다"라고 명시한다. 서버 임시 폴더에 업로드
    파일 사본만 최대 1시간 남긴다(자동 청소).
  ② **반영(`POST .../apply`)은 이 스크립트가 절대 호출하지 않는다** — 지시서 금지 사항.
    `[적용]` 단추(문구 "되돌릴 수 없음을 알고 N건 적용")는 화면에 나타나되 클릭하지 않는다.
  ③ 업로드하는 더미 CSV는 실카탈로그와 절대 겹치지 않는 가짜 상품코드(9999901·9999902)를
    쓰고 `origin=demo`를 명시적으로 고른다 — 어차피 apply를 안 부르니 DB에는 아무 것도
    안 들어가지만, 화면에 뜨는 문구(부품 종류별 분포 등)가 실제로 뭔가 반영하는
    것처럼 보이지 않도록 이중으로 안전하게 갔다.

■★ 배치 이력의 «업로더» 열은 실제 사람 이름이다 — 반드시 가린다
  `GET /api/admin/import-jobs`가 `admin_operators.name`을 그대로 돌려준다(과거 실제
  배치를 올린 사람 이름 — operators.html 매뉴얼이 이미 같은 이유로 가린 것과 같은
  종류의 개인정보). 표 열(`.ci-row-body .who`)과 배치 상세 서랍의 메타줄(`#ciDwMeta`)
  둘 다에 나온다 — 서랍 메타줄은 클래스가 없는 `<span>`이라 공용 `redact_text`로
  못 자르므로 이 화면 전용 패턴 매칭(`redact_operator_names()`)을 따로 둔다
  (operators.html이 "승인자: 실명" 문장을 접두어로 찾아 지운 것과 같은 방식).

  **중요 — 매 스크린샷 직전에 다시 가려야 한다.** `renderJobs()`가 이력 표
  `innerHTML`을 실데이터로 통째로 다시 그리고, 배치 행 클릭(`openDrawer()`)도 그
  함수를 다시 부른다 — 그래서 이 파일은 `shoot()` **직전마다** `redact_operator_names()`를
  다시 부른다(operators.html과 같은 이유).

■ 절대 누르지 않는 것
  `ci-apply`(적용 — 되돌릴 수 없는 실제 반영). 누르는 것은 파일 선택(더미 CSV)·
  `ci-preview`(드라이런 = DB 미변경)·`ci-reset`(폼 초기화)·`ci-origin-demo`(원천 선택,
  클라이언트 상태일 뿐)·배치 이력 행 클릭(조회)·서랍 닫기뿐이다.

무엇을 하는가
    1. 로컬 서버(127.0.0.1:8000 — **사장님 서버, 절대 죽이지 않는다**)에 Playwright로 접속한다.
    2. GET /api/admin/auth/dev-login 으로 점검 계정(owner 등급) 세션을 심는다.
    3. /admin2/catalog-import 를 열고 업로드 폼 + 배치 이력이 그려지길 기다린 뒤,
       화면 전체 + 주요 영역을 PNG로 저장한다 — **저장 직전 매번 업로더 실명을 가린다.**
    4. 더미 CSV(가짜 상품코드 · origin=demo)를 올려 드라이런까지만 진행하고 미리보기
       화면을 캡처한다 — [적용]은 누르지 않는다.
    5. 배치 이력에서 행 하나를 눌러 상세 서랍(거부 행·반영 상품 탭)을 캡처한다.
    6. 각 캡처 안 주요 요소의 실측 bounding box를 좌표 JSON(catalog-import-coords.json)에
       남긴다. **이 JSON에는 실명을 절대 담지 않는다** — 문서용 실측 수치는
       `GET /api/admin/import-jobs`의 `summary`(집계)만 `_meta.stats`에 넣는다.

다시 찍을 때
    .venv/Scripts/python scripts/manual_shots_catalog_import.py
    기존 PNG·JSON을 덮어쓴다(파일명 고정). 배치 이력은 이 스크립트를 다시 돌릴 때마다
    실제로 늘어날 수 있다(더미 업로드도 드라이런만 하므로 이력에 새 배치가 쌓이지는
    않는다 — apply를 안 부르므로 `csv_import_jobs` 행 자체가 생기지 않는다).

읽기 전용에 가깝다 — 정본 DB에는 쓰지 않는다(드라이런은 DB 미변경). 포트 8000에는
dev-login(GET) 1회, 페이지가 스스로 부르는 GET들, 그리고 dryrun(POST, DB 미변경) 1회가
나간다. apply(POST)는 전혀 없다.
"""
import sys

from manual_capture_common import (
    BASE, VIEWPORT, CaptureError,
    build_meta, capture_session, get_boxes, log, redact_text, shoot, write_coords,
)

SCREEN_PATH = "/admin2/catalog-import"
SCREEN_ID = "ADM-CSV-010"
FAKE_OPERATOR = "홍길동"

# 안전한 더미 CSV — 실카탈로그 상품코드(수천~수만대)와 절대 안 겹치는 9999900번대,
# origin=demo를 화면에서 명시적으로 고른다(아래 main()). 미리보기(dryrun)는 DB를
# 전혀 쓰지 않으므로(위 모듈 docstring) 이 코드가 실제로 products에 들어가는 일은
# 없다 — apply를 부르지 않기 때문이다.
DEMO_CSV = (
    "자체상품코드,상품명,카테고리1,카테고리2,카테고리3,상태값,매입가,일반회원,시중가,"
    "공급처,스펙,제조사,모델명,다나와No\r\n"
    "9999901,[매뉴얼 캡처용 테스트] 테스트 메모리 8GB,테스트분류,메모리(RAM),테스트,"
    "판매중,30000,39000,45000,테스트공급처,DDR4 8GB PC4-25600 CL18,테스트제조사,"
    "TEST-DDR4-8G,\r\n"
    "9999902,[매뉴얼 캡처용 테스트] 미분류 테스트 상품,테스트분류,테스트미분류카테고리,"
    "테스트,품절,10000,15000,20000,,,,,\r\n"
).encode("utf-8-sig")


def redact_operator_names(page) -> None:
    """배치 이력 표의 «업로더» 열 + 상세 서랍 메타줄의 실명을 가짜 값으로 덮는다."""
    redact_text(page, {".ci-row-body .who": FAKE_OPERATOR})
    # #ciDwMeta는 span마다 클래스가 없어 선택자로 못 자른다 — 날짜(YYYY-MM-DD로 시작)·
    # 원천 라벨('데모'/'실데이터')·건수 문구('반영' 포함)가 아닌 span만 실명으로 보고
    # 가짜 값으로 바꾼다(operators.html의 "승인자: " 접두어 매칭과 같은, 이 화면
    # 전용 보강 — 공용 모듈은 고치지 않는다).
    page.evaluate("""(fake) => {
        document.querySelectorAll('#ciDwMeta span').forEach(function (el) {
            var t = el.textContent || '';
            var isDate = /^\\d{4}-\\d{2}-\\d{2}/.test(t);
            var isOrigin = (t === '데모' || t === '실데이터');
            var isCounts = t.indexOf('반영') >= 0;
            var isDash = (t === '\\u2014' || t === '');
            if (!isDate && !isOrigin && !isCounts && !isDash) el.textContent = fake;
        });
    }""", FAKE_OPERATOR)


def main() -> int:
    coords: dict = {}
    stats: dict = {}

    try:
        with capture_session() as page:
            # ---- 1) 화면 열기 -------------------------------------------------------
            page.goto(f"{BASE}{SCREEN_PATH}", wait_until="networkidle")
            try:
                page.wait_for_selector(".ci-drop, .ci-lock", timeout=15000)
            except Exception as e:
                log(f"[FATAL] 업로드 영역이 15초 안에 안 그려졌습니다: {e}")
                return 1
            try:
                page.wait_for_selector("#ciJobsBody .ci-row-body, .ci-empty, .ci-errbox",
                                        timeout=15000)
            except Exception as e:
                log(f"[MISS] 배치 이력이 15초 안에 안 채워졌습니다: {e}")
            page.wait_for_timeout(300)

            full_clip = {"x": 0, "y": 0, "width": VIEWPORT["width"], "height": VIEWPORT["height"]}
            is_owner = bool(page.evaluate("!!document.querySelector('.ci-drop')"))
            log(f"[INFO] 업로드 가능(owner) 여부: {is_owner}")

            # ---- 2) 전체 화면(첫 진입 — 업로드 전, 배치 이력 로드됨) --------------------
            redact_operator_names(page)
            shoot(page, "catalog-import-full", full_clip, {
                "lnb": ".a2-lnb",
                "lnb_active_item": ".a2-lnb-b a.on",
                "header": ".a2-hd",
                "scope": "#ciScope",
                "aside": "#ciAside",
                "panel": "#ciPanel",
                "drop": ".ci-drop",
                "hist": ".ci-hist",
            }, coords)

            # ---- 3) 헤더 확대 --------------------------------------------------------
            hdr_box = get_boxes(page, {"header": ".a2-hd"})["header"]
            if hdr_box:
                shoot(page, "catalog-import-header", hdr_box, {
                    "crumb": ".a2-crumb", "now": ".a2-now",
                    "hub": ".a2-hub", "avatar": ".a2-avatar",
                }, coords)
            else:
                log("[MISS] .a2-hd 를 못 찾았습니다 - catalog-import-header.png 건너뜀")

            # ---- 4) 좌측 aside(고정 계약 카드) 확대 -----------------------------------
            aside_box = get_boxes(page, {"aside": "#ciAside"})["aside"]
            if aside_box and aside_box["width"] > 0:
                shoot(page, "catalog-import-aside", aside_box, {
                    # .ci-cap(첫 div, 라벨)이 nth-of-type(1)을 차지한다 — 카드는 2·3·4번째
                    # div다(nth-of-type은 같은 태그끼리만 세고 클래스는 안 본다).
                    "cap": "#ciAside .ci-cap",
                    "card_1": "#ciAside .ci-card:nth-of-type(2)",
                    "card_2": "#ciAside .ci-card:nth-of-type(3)",
                    "card_3": "#ciAside .ci-card:nth-of-type(4)",
                }, coords)
            else:
                log("[MISS] #ciAside 가 비어 있습니다(owner 아님?) - catalog-import-aside.png 건너뜀")

            # ---- 5) 업로드 패널 확대(드롭존 · EAV 두 줄 · 원천 선택 · 경고 · 버튼) ------
            panel_box = get_boxes(page, {"panel": "#ciPanel"})["panel"]
            if panel_box:
                shoot(page, "catalog-import-form", panel_box, {
                    "drop": ".ci-drop",
                    "eav": ".ci-eav",
                    "origin": ".ci-origin",
                    "warn": ".ci-warn",
                    "preview_btn": '[data-action="ci-preview"]',
                }, coords)
            else:
                log("[MISS] #ciPanel 을 못 찾았습니다 - catalog-import-form.png 건너뜀")

            # ---- 6) 배치 이력 표 확대(업로더 실명은 위에서 이미 가림) -------------------
            redact_operator_names(page)
            hist_box = get_boxes(page, {"hist": ".ci-hist"})["hist"]
            if hist_box:
                shoot(page, "catalog-import-history", hist_box, {
                    "title": ".ci-hist-title", "count": "#ciHistCount", "cat": "#ciHistCat",
                    "thead": ".ci-row-head",
                    "row_1": "#ciJobsBody .ci-row-body:nth-of-type(1)",
                    "row_2": "#ciJobsBody .ci-row-body:nth-of-type(2)",
                    "row_3": "#ciJobsBody .ci-row-body:nth-of-type(3)",
                }, coords)
            else:
                log("[MISS] .ci-hist 를 못 찾았습니다 - catalog-import-history.png 건너뜀")

            # ---- 7) 더미 CSV 업로드 -> 드라이런(미리보기) — DB 미변경, apply는 호출 안 함 --
            if is_owner:
                try:
                    with page.expect_file_chooser() as fc_info:
                        page.click('[data-action="ci-pick-master"]')
                    fc_info.value.set_files({
                        "name": "manual-capture-test.csv",
                        "mimeType": "text/csv",
                        "buffer": DEMO_CSV,
                    })
                    page.wait_for_timeout(200)
                    # 데이터 원천을 명시적으로 "데모"로 — 화면 요구사항이자(정의서 ⑥)
                    # 이 캡처가 실카탈로그를 흉내내지 않는다는 이중 안전장치.
                    page.click('[data-action="ci-origin-demo"]')
                    page.wait_for_timeout(100)
                    page.click('[data-action="ci-preview"]')
                    page.wait_for_selector(".ci-verdict", timeout=20000)
                    page.wait_for_timeout(200)
                except Exception as e:
                    log(f"[MISS] 드라이런 미리보기를 못 띄웠습니다 - "
                        f"catalog-import-report.png 건너뜀: {e}")
                else:
                    panel_box2 = get_boxes(page, {"panel": "#ciPanel"})["panel"]
                    if panel_box2:
                        shoot(page, "catalog-import-report", panel_box2, {
                            "verdict": ".ci-verdict",
                            "dist": ".ci-dist",
                            "warn": ".ci-warn",
                            "apply_btn": '[data-action="ci-apply"]',
                            "reset_btn": '[data-action="ci-reset"]',
                        }, coords)
                    log("[OK] 드라이런 미리보기 확인 - [적용] 단추는 누르지 않았습니다"
                        "(지시서 금지 사항, DB 미변경 상태를 유지)")
                    # apply를 부르지 않고 화면만 처음으로 되돌린다(다음 단계 전제 정리).
                    page.click('[data-action="ci-reset"]')
                    page.wait_for_selector(".ci-drop", timeout=5000)
            else:
                log("[INFO] owner 계정이 아니라 업로드·드라이런 단계를 건너뜁니다")

            # ---- 8) 배치 이력에서 행을 눌러 상세 서랍 열기 ------------------------------
            job_pick = page.evaluate("""() => {
                var rows = Array.from(document.querySelectorAll('#ciJobsBody .ci-row-body'));
                if (!rows.length) return null;
                var withErr = rows.find(function (r) { return r.querySelector('.num.err.has'); });
                var target = withErr || rows[0];
                return target.getAttribute('data-jobid');
            }""")
            if job_pick:
                page.click(f'#ciJobsBody .ci-row-body[data-jobid="{job_pick}"]')
                try:
                    page.wait_for_selector("#ciDrawer:not([hidden])", timeout=10000)
                    page.wait_for_function(
                        "() => !document.querySelector('#ciDrawer .ci-loading')", timeout=10000)
                    page.wait_for_timeout(200)
                except Exception as e:
                    log(f"[MISS] 배치 #{job_pick} 상세 서랍이 안 열렸습니다: {e}")
                    job_pick = None

            if job_pick:
                redact_operator_names(page)
                shoot(page, "catalog-import-full-detail", full_clip, {
                    "selected_row": f'#ciJobsBody .ci-row-body[data-jobid="{job_pick}"]',
                    "drawer": "#ciDrawer",
                }, coords)

                drawer_box = get_boxes(page, {"drawer": "#ciDrawer"})["drawer"]
                if drawer_box:
                    shoot(page, "catalog-import-drawer", drawer_box, {
                        "title": "#ciDwTitle", "meta": "#ciDwMeta", "tabs": "#ciDwTabs",
                        "body": "#ciDwBody", "foot": "#ciDwFoot",
                    }, coords)
                else:
                    log("[MISS] #ciDrawer 박스를 못 쟀습니다 - catalog-import-drawer.png 건너뜀")
            else:
                log("[MISS] 열 수 있는 배치 이력 행이 없습니다 - 서랍 캡처 2종 건너뜀")

            # ---- 9) 문서용 실측 수치 — 집계만 남긴다(업로더 실명은 저장하지 않는다) ------
            try:
                r1 = page.request.get(f"{BASE}/api/admin/import-jobs")
                if r1.ok:
                    j1 = r1.json()
                    stats["import_jobs"] = j1.get("summary")
            except Exception as e:
                log(f"[MISS] 문서용 수치 조회 실패(캡처는 이미 끝났습니다): {e}")

    except CaptureError as e:
        log(f"[FATAL] {e}")
        return 1

    coords["_meta"] = build_meta(SCREEN_ID, SCREEN_PATH, VIEWPORT, stats)
    write_coords("catalog-import", coords)

    ij = stats.get("import_jobs")
    if ij:
        log(f"[INFO] 배치 {ij.get('batches')}건 - 반영 {ij.get('ok')} · 오류 {ij.get('error')} "
            f"· 검수 {ij.get('review')} · 카탈로그 {ij.get('catalog')}건"
            f"(실데이터 {ij.get('real')} · 데모 {ij.get('demo')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
