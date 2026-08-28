# -*- coding: utf-8 -*-
"""운영자 매뉴얼용 화면 캡처 - 작업 기록(ADM-SYS-030, 경로 /admin2/activity-logs).

공통 부분(로그인·캡처·좌표 뽑기·비율 환산)은 `scripts/manual_capture_common.py`(공용
도구, 이 파일에서 고치지 않는다)를 그대로 쓴다. 이 파일에는 이 화면에만 해당하는 것
(경로·선택자·무엇을 확대할지·필터 조작·개인정보를 어디서 가릴지)만 있다.

■★ 이 화면은 실제 운영자 이름을 보여준다 - 반드시 가린다
  목록 표의 "운영자" 열(`.al-row .who .nm`), 상세 서랍의 운영자 줄(`#alDWho`), 운영자
  필터 드롭다운의 항목 목록(`#alFOperatorDrop .al-fitem .lb`) 셋 다 실제
  `admin_operators.name`을 그대로 보여준다. "자동"(operator_id가 NULL - 사람이 아니라
  자동 처리를 뜻하는 값, `api/admin_activity_logs.py`의 A-108 주석 참고)과 "전체"(필터
  드롭다운의 초기화 옵션)는 이름이 아니므로 바꾸지 않는다 - 그대로 두는 것 자체가 이
  화면의 실제 동작(자동 처리는 사람과 구분해 보여준다)을 정확히 보여준다.

  **중요 - 매 스크린샷 직전에 다시 가려야 한다.** `renderTable()`·`renderDrawer()`·
  `renderFilters()`는 상태가 바뀔 때마다(필터 적용·페이지 이동·행 선택) 해당 영역의
  `innerHTML`을 실제 데이터로 통째로 다시 그린다 - DOM 텍스트만 바꾼 것은 다음 렌더
  한 번에 지워진다. 그래서 `redact_operators()`를 `shoot()` 직전마다 다시 부른다
  (operators 화면 캡처 스크립트와 같은 이유·같은 패턴).

■ 절대 누르지 않는 것
  이 화면 자체가 조회 전용이라 쓰기 버튼이 없다(요구사항 정의서 §① "조회 화면 -
  쓰기 기능이 없다"). 누르는 것은 기간 pill·필터 드롭다운 토글·필터 항목 선택·검색어
  입력·행 클릭(상세 서랍 열기)·서랍 닫기뿐 - 전부 읽기 전용 UI 상태 변경이다. 유일하게
  서버에 새로 나가는 요청은 이 화면이 스스로 부르는 `GET /api/admin/activity-logs`
  (기간·필터 조작마다) 뿐이다.

■ 필터 조작으로 구체적 예시를 만든다
  이 화면은 500건까지 한 번에 불러온 뒤 그 배치 안에서 클라이언트가 거른다(서버는
  기간 파라미터만 지원 - `templates/admin/activity_logs.html.j2` 상단 주석 "데이터
  API" 참고). 그래서 "카테고리 매핑 이동" 실제 예시를 잡으려면 화면이 실제로 하는 것과
  똑같이 도메인·되돌림 드롭다운을 눌러 좁힌다(하드코딩한 log_id를 사용하지 않는다 -
  데이터가 바뀌어도 이 스크립트가 그대로 다시 돈다):
    ① 도메인="카테고리" + 되돌림="되돌려짐" -> 남는 행은 전부 "카테고리 매핑 이동"
       (되돌려진 원본)이다. 그중 첫 행(가장 최근)의 상세를 그림 G로 쓴다.
    ② 도메인="카테고리" + 검색어="되돌림" -> 요약 문장이 "원 기록 #.. 되돌림" 패턴인
       행만 남는다(검색은 target·summary만 본다 - action_label은 보지 않는다). 이
       중 첫 행("카테고리 매핑 이동 되돌림" 자체)의 상세를 그림 H로 쓴다.

무엇을 하는가
    1. 로컬 서버(127.0.0.1:8000 - 사장님 서버, 절대 죽이지 않는다)에 Playwright로 접속한다.
    2. GET /api/admin/auth/dev-login 으로 점검 계정(owner 등급) 세션을 심는다.
    3. /admin2/activity-logs 를 열고 목록 로드를 기다린 뒤, 화면 전체 + 주요 영역을
       PNG로 저장한다 - 저장 직전 매번 운영자 이름을 가짜 값으로 덮는다.
    4. 각 캡처 안 주요 요소의 실측 bounding box를 좌표 JSON(activity-logs-coords.json)에
       남긴다. 이 JSON에는 실명을 절대 담지 않는다 - 문서용 실측 수치는 건수·문구 같은
       집계·텍스트만 `_meta.stats`에 넣는다(원본 목록 배열은 저장하지 않는다).

다시 찍을 때
    .venv/Scripts/python scripts/manual_shots_activity_logs.py
    기존 PNG·JSON을 덮어쓴다(파일명 고정). 원장은 계속 쌓이므로 다시 찍을 때마다
    "카테고리 매핑 이동" 예시로 잡히는 실제 log_id·대상은 바뀔 수 있다 - 이 스크립트는
    특정 log_id를 하드코딩하지 않고 매번 그 시점의 첫 행을 동적으로 찾는다.

읽기 전용이다 - DB에 쓰지 않는다. 포트 8000에는 dev-login(GET) 1회와 그 뒤 화면이
스스로 부르는 GET들만 나간다(POST는 전혀 없다).
"""
import sys

from manual_capture_common import (
    BASE, VIEWPORT, CaptureError,
    build_meta, capture_session, get_boxes, log, shoot, union_box, write_coords,
)

SCREEN_PATH = "/admin2/activity-logs"
SCREEN_ID = "ADM-SYS-030"

# 명백히 실존 인물이 아닌 예시 이름 순환 풀 - operators 캡처 스크립트의 관례를 따른다
# ("실제로 없는 이름으로"). 여러 명이 섞여 보이게 5개를 돌려쓴다(실제 배치에 등장하는
# 서로 다른 이름 수보다 넉넉하게).
FAKE_NAMES = ["이보라", "박준서", "정하은", "최도윤", "강서연"]


def redact_operators(page) -> None:
    """표 행·상세 서랍·운영자 필터 드롭다운의 실제 운영자 이름을 가짜 값으로 덮는다.

    "자동"·"전체"는 사람 이름이 아니므로 그대로 둔다(위 모듈 docstring 참고). DOM만
    바꾸고 서버에는 아무것도 보내지 않는다 - 페이지를 새로고침하지 않는 한 원래 값은
    서버에 그대로 남는다. `shoot()` 직전마다 다시 불러야 한다.
    """
    page.evaluate("""(pool) => {
        var i = 0;
        function next() { var n = pool[i % pool.length]; i++; return n; }
        document.querySelectorAll('.al-row .who .nm').forEach(function (el) {
            if (el.textContent && el.textContent !== '자동') el.textContent = next();
        });
        var dw = document.getElementById('alDWho');
        if (dw && dw.textContent && dw.textContent !== '자동') dw.textContent = next();
        document.querySelectorAll('#alFOperatorDrop .al-fitem .lb').forEach(function (el) {
            if (el.textContent !== '전체' && el.textContent !== '자동') el.textContent = next();
        });
    }""", FAKE_NAMES)
    log("[OK] 개인정보(운영자 이름) 치환: 표 행 / 상세 서랍 / 운영자 필터 드롭다운")


def _text(page, sel: str) -> str | None:
    """selector의 textContent(공백 정리) - 캡처와 같은 순간의 실제 문구를 문서에
    그대로 옮기기 위한 것(지어내지 않는다). 요소가 없으면 None."""
    return page.evaluate(
        "(sel) => { var el = document.querySelector(sel); "
        "return el ? el.textContent.replace(/\\s+/g, ' ').trim() : null; }", sel)


def _click(page, sel: str, timeout: int = 12000) -> bool:
    """force=True로 클릭한다 - 방어적 조치다.

    이 화면 자체의 서랍 열기는 클라이언트 연산뿐이라(이미 불러온 배치를 다시 그릴
    뿐) 원래는 순간적으로 끝난다. 그런데 `#alDrawerWrap`이 닫힌 채로 남아 있으면
    그 자식 `.al-overlay`가 화면 전체를 덮어 다음 클릭을 가로챌 수 있다(실측
    2026-08-28 - `_close_drawer_if_open()`을 넣은 이유와 같은 종류의 문제). force=True는
    "대상이 실제로 포인터 이벤트를 받는가" 확인을 건너뛰고 좌표에 그대로 클릭을
    내리꽂아, 그 확인 때문에 기본 30초까지 재시도하다 죽는 것을 막는다. 서랍이
    실제로 열렸는지는 이 함수가 아니라 `_wait_drawer_open()`이 확인한다."""
    try:
        page.locator(sel).click(force=True, timeout=timeout)
        return True
    except Exception as e:
        log(f"[MISS] 클릭 실패({sel}): {e}")
        return False


def _open_dropdown(page, btn_sel: str, drop_sel: str, timeout: int = 12000) -> bool:
    if not _click(page, btn_sel, timeout=timeout):
        return False
    try:
        page.wait_for_selector(f"{drop_sel}:not([hidden])", timeout=timeout)
        page.wait_for_timeout(150)
        return True
    except Exception as e:
        log(f"[MISS] 드롭다운이 안 열렸습니다({btn_sel}): {e}")
        return False


def _pick(page, drop_sel: str, action: str, key: str, timeout: int = 300) -> None:
    _click(page, f'{drop_sel} [data-action="{action}"][data-k="{key}"]')
    page.wait_for_timeout(timeout)


def _wait_drawer_open(page, timeout: int = 15000) -> None:
    """서랍이 열릴 때까지 기다린다 - `hidden` **속성**이 아니라 `hidden` **JS 프로퍼티**를
    직접 본다(2026-08-28 실측으로 찾은 함정).

    `#alDrawerWrap`은 자기 자신에게는 위치·크기 CSS가 없고(자식인 `.al-overlay`·
    `.al-drawer`만 `position:absolute`) `[hidden]` 규칙만 `display:none`을 정의한다.
    그래서 `wrap.hidden = false`로 attribute가 사라져도(`renderDrawer()`가 정확히
    그렇게 한다 - 실측: 클릭 직후 `el.hidden`은 바로 `false`가 된다) 이 요소 자체의
    렌더 박스는 여전히 0×0에 가깝다(안의 내용이 전부 absolute라 static 부모 높이에
    안 잡힌다). `page.wait_for_selector(':not([hidden])')`는 기본값 `state="visible"`
    이라 **속성 매칭과 별개로 "실제로 보이는 크기인가"까지 요구**해서, hidden 속성이
    이미 사라졌는데도 "hidden으로 판정됨"을 반복하며 타임아웃까지 간다(실측 33회 폴링
    ×15초). 그래서 크기와 무관하게 오직 `hidden` 프로퍼티만 보는 `wait_for_function`
    으로 바꿨다 - 렌더링이 실제로 어떻게 보이는지는 이 스크립트가 찍는 스크린샷으로
    확인하지, 이 대기 조건이 확인할 일이 아니다.
    """
    page.wait_for_function(
        "() => { var el = document.getElementById('alDrawerWrap'); return !!el && el.hidden === false; }",
        timeout=timeout)


def _close_drawer_if_open(page) -> None:
    """서랍이 열려 있으면 닫는다(오버레이가 다음 클릭을 가로채는 것을 막는 방어
    장치) - 열려 있지 않으면 아무 일도 하지 않는다."""
    try:
        is_hidden = page.evaluate(
            "() => { var el = document.getElementById('alDrawerWrap'); return !el || el.hidden; }")
        if not is_hidden:
            _click(page, ".al-drawer-hd .x")
            page.wait_for_timeout(200)
    except Exception as e:
        log(f"[MISS] 서랍 닫기 확인 실패(무시하고 진행합니다): {e}")


def main() -> int:
    coords: dict = {}
    stats: dict = {}

    try:
        with capture_session() as page:
            # ---- 1) 화면 열기 -------------------------------------------------------
            page.goto(f"{BASE}{SCREEN_PATH}", wait_until="networkidle")
            try:
                page.wait_for_function(
                    "() => { var el = document.getElementById('alLoading'); "
                    "return el && el.hidden === true; }", timeout=15000)
            except Exception as e:
                log(f"[FATAL] 목록이 15초 안에 안 불러와졌습니다: {e}")
                return 1
            if page.locator("#alErrBox:not([hidden])").count():
                msg = _text(page, "#alErrMsg")
                log(f"[FATAL] 목록 조회 API가 실패했습니다: {msg}")
                return 1
            try:
                page.wait_for_selector("#alTbody .al-row", timeout=10000)
            except Exception as e:
                log(f"[FATAL] 목록 행이 15초 안에 안 채워졌습니다(0건일 수 있습니다): {e}")
                return 1
            page.wait_for_timeout(250)

            full_clip = {"x": 0, "y": 0, "width": VIEWPORT["width"], "height": VIEWPORT["height"]}

            # ---- A) 전체 화면(필터 없음 · 기간 전체 기간 · 서랍 닫힘) ------------------
            redact_operators(page)
            shoot(page, "activity-logs-full", full_clip, {
                "lnb": ".a2-lnb",
                "lnb_active_item": ".a2-lnb-b a.on",
                "header": ".a2-hd",
                "crumb": ".a2-crumb",
                "ro_badge": ".al-ro",
                "scopeline": "#alScopeLine",
                "hub": ".a2-hub",
                "role_box": "#roleBox",
                "avatar": ".a2-avatar",
                "banner": "#alBanner",
                "filterbar": ".al-filterbar",
                "note": ".al-note",
                "statusbar": ".al-statusbar",
                "tablewrap": ".al-tablewrap",
                "pager": ".al-pager",
            }, coords)

            # ---- B) 헤더 확대 --------------------------------------------------------
            hdr_box = get_boxes(page, {"header": ".a2-hd"})["header"]
            if hdr_box:
                shoot(page, "activity-logs-header", hdr_box, {
                    "crumb": ".a2-crumb",
                    "now": ".a2-now",
                    "ro_badge": ".al-ro",
                    "scopeline": "#alScopeLine",
                    "hub": ".a2-hub",
                    "role_box": "#roleBox",
                    "avatar": ".a2-avatar",
                }, coords)
            else:
                log("[MISS] .a2-hd 를 못 찾았습니다 - activity-logs-header.png 건너뜀")

            # ---- C) 필터 바 확대 ------------------------------------------------------
            fb_box = get_boxes(page, {"filterbar": ".al-filterbar"})["filterbar"]
            if fb_box:
                shoot(page, "activity-logs-filterbar", fb_box, {
                    "periods": ".al-periods",
                    "operator_btn": "#alFOperatorBtn",
                    "kind_btn": "#alFKindBtn",
                    "action_btn": "#alFActionBtn",
                    "undone_btn": "#alFUndoneBtn",
                    "search": "#alSearchBox",
                    "reset": "#alResetBtn",
                }, coords)
            else:
                log("[MISS] .al-filterbar 를 못 찾았습니다 - activity-logs-filterbar.png 건너뜀")

            # ---- D) 운영자 필터 드롭다운 연 상태(이름 가려짐) --------------------------
            if _open_dropdown(page, "#alFOperatorBtn", "#alFOperatorDrop"):
                redact_operators(page)
                op_clip = union_box(page, ["#alFOperatorBtn", "#alFOperatorDrop"])
                if op_clip:
                    shoot(page, "activity-logs-operator-filter", op_clip, {
                        "btn": "#alFOperatorBtn",
                        "drop": "#alFOperatorDrop",
                    }, coords)
                else:
                    log("[MISS] 운영자 드롭다운 박스를 못 쟀습니다")
                # 같은 버튼을 다시 눌러 닫는다(토글) - 다음 단계 전제(드롭다운 닫힘)
                _click(page, "#alFOperatorBtn")
                page.wait_for_timeout(150)

            # ---- E) 도메인=카테고리 + 되돌림=되돌려짐 필터 적용 결과 -------------------
            filtered_ok = False
            if _open_dropdown(page, "#alFKindBtn", "#alFKindDrop"):
                _pick(page, "#alFKindDrop", "pick-kind", "category")
                if _open_dropdown(page, "#alFUndoneBtn", "#alFUndoneDrop"):
                    _pick(page, "#alFUndoneDrop", "pick-undone", "undone")
                    filtered_ok = True

            g_target_id = None
            if filtered_ok:
                row_count = page.evaluate("document.querySelectorAll('#alTbody .al-row').length")
                stats["category_undone_filtered_count"] = row_count
                if row_count > 0:
                    redact_operators(page)
                    n = min(6, row_count)
                    row_sels = [".al-thead"] + [f"#alTbody .al-row:nth-child({i})" for i in range(1, n + 1)]
                    e_clip = union_box(page, [".al-filterbar", ".al-statusbar"] + row_sels)
                    el_sel = {
                        "kind_btn": "#alFKindBtn", "undone_btn": "#alFUndoneBtn",
                        "count_line": "#alCountLine", "cap_chip": "#alCapChip",
                        "thead": ".al-thead",
                    }
                    for i in range(1, n + 1):
                        el_sel[f"row_{i}"] = f"#alTbody .al-row:nth-child({i})"
                    if e_clip:
                        shoot(page, "activity-logs-filtered-table", e_clip, el_sel, coords)
                    stats["count_line_text"] = _text(page, "#alCountLine")
                    stats["cap_chip_text"] = _text(page, "#alCapChip")
                    # 그림 F·G에 쓸 대상 - "지금" 필터 결과의 첫 행(가장 최근 것)을
                    # 동적으로 고른다(하드코딩 금지 - 모듈 docstring 참고).
                    g_target_id = page.locator("#alTbody .al-row").first.get_attribute("data-id")
                else:
                    log("[MISS] 도메인=카테고리 + 되돌림=되돌려짐 조건에 걸리는 행이 0건입니다"
                        " - activity-logs-filtered-table.png / 그림 F·G 건너뜀")
            else:
                log("[MISS] 도메인·되돌림 필터를 적용하지 못했습니다 - 그림 E·F·G 건너뜀")

            # ---- F) 행을 클릭하면 열리는 위치(전체 화면) + G) 상세 서랍 확대(되돌려짐) --
            if g_target_id:
                row_sel = f'#alTbody .al-row[data-id="{g_target_id}"]'
                _click(page, row_sel)
                try:
                    _wait_drawer_open(page)
                    page.wait_for_timeout(200)
                except Exception as e:
                    log(f"[MISS] 상세 서랍이 안 열렸습니다(data-id={g_target_id}): {e}")
                    g_target_id = None

            if g_target_id:
                redact_operators(page)
                shoot(page, "activity-logs-full-detail", full_clip, {
                    "selected_row": row_sel,
                    "drawer": ".al-drawer",
                }, coords)

                stats["drawer_undone_example"] = {
                    "kind_label": _text(page, "#alDKind"),
                    "action_label": _text(page, "#alDAction"),
                    "undone_badge": _text(page, "#alDUndone"),
                    "state_title": _text(page, "#alDStateTitle"),
                    "state_desc": _text(page, "#alDStateDesc"),
                }

                drawer_box = get_boxes(page, {"drawer": ".al-drawer"})["drawer"]
                if drawer_box:
                    shoot(page, "activity-logs-drawer-undone", drawer_box, {
                        "hd": ".al-drawer-hd",
                        "kind_chip": "#alDKindWrap",
                        "action": "#alDAction",
                        "undone_badge": "#alDUndone",
                        "close_btn": ".al-drawer-hd .x",
                        "meta": ".al-drawer-meta",
                        "summary_block": ".al-drawer-body > .al-block:first-child",
                        "summary_box": "#alDSummary",
                        "state_box": "#alDStateBox",
                        "detail_note_block": ".al-drawer-body > .al-block:last-child",
                        "footer": ".al-drawer-ft",
                        "copy_btn": '[data-action="copy-logid"]',
                    }, coords)
                else:
                    log("[MISS] .al-drawer 박스를 못 쟀습니다 - activity-logs-drawer-undone.png 건너뜀")
            else:
                log("[MISS] 되돌려짐 예시 행을 열지 못했습니다 - 그림 F·G 건너뜀")

            # ---- H) 상세 서랍 확대 - 되돌림 행 자체(정상/미발견 상태) ------------------
            # 도메인=카테고리는 유지한 채, 되돌림 필터를 지우고 검색어로 좁힌다 - 검색은
            # target·summary만 보므로("카테고리 매핑 이동 되돌림" 행의 summary는 항상
            # "원 기록 #.. 되돌림" 패턴) action_label을 몰라도 정확히 그 행들만 남는다.
            # 먼저 그림 G에서 연 서랍을 확실히 닫는다(오버레이가 이번 절의 첫 클릭을
            # 가로채는 것을 막는다 - 위 F·G 주석의 지연 문제와 같은 원인).
            _close_drawer_if_open(page)
            h_target_id = None
            if _open_dropdown(page, "#alFUndoneBtn", "#alFUndoneDrop"):
                _pick(page, "#alFUndoneDrop", "pick-undone", "")  # "전체"(리셋) 옵션
            _click(page, "#alSearch")
            page.locator("#alSearch").fill("되돌림")
            page.wait_for_timeout(300)
            h_row_count = page.evaluate("document.querySelectorAll('#alTbody .al-row').length")
            if h_row_count > 0:
                h_target_id = page.locator("#alTbody .al-row").first.get_attribute("data-id")
                _click(page, f'#alTbody .al-row[data-id="{h_target_id}"]')
                try:
                    _wait_drawer_open(page)
                    page.wait_for_timeout(200)
                    redact_operators(page)
                    stats["drawer_undo_row_example"] = {
                        "kind_label": _text(page, "#alDKind"),
                        "action_label": _text(page, "#alDAction"),
                        "undone_badge": _text(page, "#alDUndone"),
                        "summary": _text(page, "#alDSummary"),
                        "state_title": _text(page, "#alDStateTitle"),
                        "state_desc": _text(page, "#alDStateDesc"),
                    }
                    drawer_box2 = get_boxes(page, {"drawer": ".al-drawer"})["drawer"]
                    if drawer_box2:
                        shoot(page, "activity-logs-drawer-undorow", drawer_box2, {
                            "hd": ".al-drawer-hd",
                            "kind_chip": "#alDKindWrap",
                            "action": "#alDAction",
                            "undone_badge": "#alDUndone",
                            "meta": ".al-drawer-meta",
                            "summary_box": "#alDSummary",
                            "state_box": "#alDStateBox",
                        }, coords)
                    else:
                        log("[MISS] .al-drawer(되돌림 행) 박스를 못 쟀습니다")
                except Exception as e:
                    log(f"[MISS] 되돌림 행 상세 서랍이 안 열렸습니다(data-id={h_target_id}): {e}")
            else:
                log("[MISS] 검색어 '되돌림'에 걸리는 행이 0건입니다 - activity-logs-drawer-undorow.png 건너뜀")

            # ---- 9) 문서용 실측 수치 - 집계·문구만 남긴다(운영자 이름 원본은 저장하지 않는다) --
            try:
                r1 = page.request.get(f"{BASE}/api/admin/activity-logs")
                if r1.ok:
                    j1 = r1.json()
                    items = j1.get("items", [])
                    from collections import Counter
                    kind_counts = Counter(i["kind"] for i in items)
                    stats["overview"] = {
                        "total": j1.get("total"),
                        "limit": j1.get("limit"),
                        "batch_count": len(items),
                        "kind_counts_in_batch": dict(kind_counts.most_common()),
                        "undone_true_in_batch": sum(1 for i in items if i["undone"]),
                        "unmapped_kinds": j1.get("unmapped_kinds"),
                        "unmapped_actions": j1.get("unmapped_actions"),
                        "distinct_operator_count_in_batch": len({i["operator"] for i in items}),
                    }
                    cat_move = [i for i in items if i["kind"] == "category" and i["action_label"] == "카테고리 매핑 이동"]
                    stats["category_move_example"] = {
                        "count_in_batch": len(cat_move),
                        "undone_true_count": sum(1 for i in cat_move if i["undone"]),
                    }
            except Exception as e:
                log(f"[MISS] 문서용 수치 조회 실패(캡처는 이미 끝났습니다): {e}")

    except CaptureError as e:
        log(f"[FATAL] {e}")
        return 1

    coords["_meta"] = build_meta(SCREEN_ID, SCREEN_PATH, VIEWPORT, stats)
    write_coords("activity-logs", coords)

    ov = coords["_meta"]["stats"].get("overview")
    if ov:
        log(f"[INFO] 원장 전체 {ov['total']}건 · 이번 배치(상한 {ov['limit']}) {ov['batch_count']}건"
            f" · undone=true {ov['undone_true_in_batch']}건 · 배치 내 서로 다른 운영자 수"
            f" {ov['distinct_operator_count_in_batch']} · 미번역 kind={ov['unmapped_kinds']}"
            f" action={ov['unmapped_actions']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
