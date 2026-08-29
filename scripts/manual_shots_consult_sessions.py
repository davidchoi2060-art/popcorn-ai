# -*- coding: utf-8 -*-
"""운영자 매뉴얼용 화면 캡처 — 견적 상담 기록(ADM-ORD-010, 경로 /admin2/consult-sessions).

공통 부분(로그인·캡처·좌표 뽑기·비율 환산·개인정보 가리기)은
`scripts/manual_capture_common.py`(공용 도구, 이 파일에서 고치지 않는다)를 그대로
쓴다. 이 파일에는 **이 화면에만 해당하는 것**(경로·선택자·무엇을 확대할지·개인정보를
어디서 가릴지·어느 세션을 예시로 쓸지)만 있다.

■★ 이 화면의 데이터는 원장 전체로 보면 대부분 회귀 시험이 남긴 것이다 — 그런데
  화면 자신은 이미 그것을 걸러서 보여준다(A-81, `api/session_scope.py`). 캡처
  스크립트를 작성하며 DB를 직접 재서 확인한 사실(2026-08-28):

      consult_sessions 전체       10,509건 — data_origin 별: test 8,780(83.6%) ·
                                  real 1,719(16.4%) · demo 10
      화면이 실제로 보여주는 값   `GET /api/admin/sessions`의 `total`은 130건뿐이다
                                  — `api/session_scope.py`의 `session_scope_where()`가
                                  SQL WHERE 절에서 ① data_origin='real' ②
                                  2026-08-19 15:57:46(UTC, X-Popcorn-Test 헤더 게이트
                                  배포 시각) 이후만 남기고 나머지 10,379건(98.8%)을
                                  화면에 아예 안 보이게 걸러낸다(화면에 필터 버튼이
                                  없다 — 서버가 항상 이 조건으로만 조회한다). KPI
                                  「전체 세션」·목록 행·완주율 전부 이 130건 기준이다.

  **그래서 이 화면을 지금 캡처하면 "회귀 시험으로 가득한 화면"이 아니라 "이미 걸러진
  130건"이 나온다** — 지시서가 우려한 상황과 실측이 다르다는 사실을 문서 본문(⑤
  조심할 것)과 캡처 스크립트 양쪽에 남긴다. 다만 이 130건도 "확인된 고객 상담"이라는
  보장은 아니다 — X-Popcorn-Test 헤더가 없는 수동 점검(팀원이 화면·API를 직접 눌러본
  경우)도 구분 없이 이 안에 섞인다. 실제로 session_id=10497은 2026-08-27 확인자가
  검증 중 `POST /api/recommend`로 만든 세션이라고 지시서에 명시돼 있다 — 그래서 아래
  예시 선택에서 **이 ID를 알면서도 의도적으로 제외**한다(EXCLUDE_IDS). 그 밖의 세션은
  구분할 방법이 없으므로 손대지 않는다(값을 지어내거나 임의로 더 골라내지 않는다).

■★ 개인정보 — 이 화면은 회원 이름·이메일을 보여주지 않는다(member_id가 전부 NULL —
  화면 자체가 "비로그인 세션"이라 표기한다). user_id도 이름이 아니라 익명 발급
  방문자 키(숫자)라 그대로 둔다. **그런데 상담 제약 중 "요청:"(자유입력) 칩에는
  고객이 직접 타이핑한 문장이 그대로 들어간다** — 이것이 지시서가 말한 "고객이 입력한
  내용"이다. 목록 행의 「제약 요약」 셀과 상세 서랍의 제약 칩 양쪽에서, "요청:"으로
  시작하는 부분만 표준 문구로 치환한다(용도·예산·선호처럼 정해진 값 중에서 고르는
  칩은 자유 텍스트가 아니므로 그대로 둔다 — 전부 가리면 화면을 설명할 수 없다).
  **행 재렌더(모드 필터 클릭 등)·서랍 재렌더(다른 행 클릭)마다 다시 그려지므로, 이
  스크립트는 관련 스크린샷 직전마다 매번 다시 가린다**(operators 스크립트와 같은 이유
  — 공용 모듈의 `redact_text`/`redact_blur`는 textContent 전체 치환만 하므로, "요청:"
  부분만 남기고 나머지는 보존하는 이 화면 전용 로직은 여기 둔다).

■ 절대 누르지 않는 것 — 이 화면은 원래 조회 전용이라 쓰기 버튼 자체가 없다
  (`api/admin_ui_consult_sessions.py` docstring: "쓰기 API 를 호출하지 않는다").
  이 스크립트도 GET만 부르고, 새 상담 세션을 만들지 않는다(지시서 — 원장이 이미
  시험으로 오염돼 있는데 캡처하려고 더 만들면 안 된다). 클릭하는 것은 기존 행·닫기
  버튼뿐이다.

무엇을 하는가
    1. 로컬 서버(127.0.0.1:8000 — **사장님 서버, 절대 죽이지 않는다**)에 Playwright로 접속한다.
    2. GET /api/admin/auth/dev-login 으로 점검 계정(owner 등급) 세션을 심는다.
    3. /admin2/consult-sessions 를 열고 목록 로드를 기다린 뒤, GET /api/admin/sessions를
       한 번 더 직접 불러 예시로 쓸 세션 3종(완주·이탈·완주→인계)을 고른다.
    4. 화면 전체 + 주요 영역 + 상세 서랍 3종을 PNG로 저장한다 — **저장 직전 매번
       "요청:" 자유입력 칩을 표준 문구로 가린다.**
    5. 각 캡처 안 주요 요소의 실측 bounding box를 좌표 JSON(consult-sessions-coords.json)에
       남긴다. 이 JSON에는 상담 제약 원문(자유입력 문장)을 저장하지 않는다 — 문서용
       실측 수치는 집계(건수·모드 분포 등)만 `_meta.stats`에 넣는다.

다시 찍을 때
    .venv/Scripts/python scripts/manual_shots_consult_sessions.py
    기존 PNG·JSON을 덮어쓴다(파일명 고정). 이 화면은 시각이 지날수록 세션 수·완주율이
    계속 바뀌므로, `docs/manual/screens/consult-sessions.html`의 실측 수치도 재캡처
    때마다 다시 확인해야 한다(scope_note가 매번 "지금 몇 건 기준"인지 알려준다).

읽기 전용이다 — DB에 쓰지 않는다. 포트 8000에는 dev-login(GET) 1회와 그 뒤 화면이
스스로 부르는 GET들만 나간다(POST는 전혀 없다).
"""
import re
import sys

from manual_capture_common import (
    BASE, VIEWPORT, CaptureError,
    build_meta, capture_session, get_boxes, log, shoot, union_box, write_coords,
)

SCREEN_PATH = "/admin2/consult-sessions"
SCREEN_ID = "ADM-ORD-010"

TABLE_ROWS_IN_SHOT = 6

# 2026-08-27 지시서 원문 — 확인자가 검증 중 POST /api/recommend로 직접 만든 세션이라고
# 명시했다. "실제 고객 상담"이 아님을 이미 아는 유일한 사례라 예시에서 제외한다. 그
# 밖의 세션은 구분할 방법이 없으므로(§본문 docstring) 임의로 더 골라내지 않는다.
EXCLUDE_IDS = {10497}

FREE_TEXT_PLACEHOLDER = "요청: (자유입력 예시 — 실제 문구 대신 표시)"


def _redact_free_text_segment(text: str) -> str:
    """" · "로 이어진 제약 요약 문자열에서 "요청:"으로 시작하는 조각만 치환한다.

    용도·예산·선호처럼 정해진 값 중에서 고르는 칩은 자유 텍스트가 아니므로 그대로
    둔다 — "요청:"(자유입력)만 고객이 직접 타이핑한 문장이다.
    """
    if not text or "요청:" not in text:
        return text
    parts = text.split(" · ")
    out = [FREE_TEXT_PLACEHOLDER if p.strip().startswith("요청:") else p for p in parts]
    return " · ".join(out)


def redact_all(page) -> None:
    """목록 행의 「제약 요약」 셀 + (열려 있으면) 상세 서랍의 제약 칩에서 "요청:" 자유입력만 가린다.

    행 재렌더(모드 필터)·서랍 재렌더(다른 행 클릭)마다 innerHTML이 다시 그려지므로
    **`shoot()` 직전마다 매번 다시 부른다**(operators 스크립트와 같은 이유 — 위 모듈
    docstring 참조).
    """
    page.evaluate("""(placeholder) => {
        function redact(text) {
            if (!text || text.indexOf('요청:') === -1) return text;
            return text.split(' · ').map(function (p) {
                return p.trim().indexOf('요청:') === 0 ? placeholder : p;
            }).join(' · ');
        }
        document.querySelectorAll('#tbody .row .cons').forEach(function (el) {
            el.textContent = redact(el.textContent);
            if (el.getAttribute('title')) el.setAttribute('title', redact(el.getAttribute('title')));
        });
        document.querySelectorAll('#dwBody .cchip').forEach(function (el) {
            el.textContent = redact(el.textContent);
        });
    }""", FREE_TEXT_PLACEHOLDER)
    log("[OK] 자유입력(\"요청:\") 칩 가림 처리 완료")


def _fetch_samples(page) -> tuple[dict | None, dict | None, dict | None, dict]:
    """GET /api/admin/sessions를 직접 불러 예시 3종(완주·이탈·완주->인계)의 session_id와
    문서용 집계만 뽑는다. 상담 제약 원문(자유입력 포함)은 반환값에 담지 않는다 —
    좌표 JSON에 개인 입력 문장을 남기지 않기 위해서다(위 모듈 docstring 참조).
    """
    r = page.request.get(f"{BASE}/api/admin/sessions")
    if not r.ok:
        raise CaptureError(f"GET /api/admin/sessions 실패: {r.status} {r.text()}")
    j = r.json()
    items = j.get("items", [])

    done = next((it for it in items if it.get("rep") and not it.get("handoff_no")
                 and not it.get("order_no") and it["session_id"] not in EXCLUDE_IDS), None)
    dropped = next((it for it in items if not it["snapshots"]
                     and it["session_id"] not in EXCLUDE_IDS), None)
    handoff = next((it for it in items if it.get("handoff_no")
                     and it["session_id"] not in EXCLUDE_IDS), None)

    mode_dist: dict = {}
    for it in items:
        mode_dist[it["mode"]] = mode_dist.get(it["mode"], 0) + 1
    stats = {
        "total": j.get("total"), "done_total": j.get("done_total"), "drop_total": j.get("drop_total"),
        "today": j.get("today"), "limit": j.get("limit"), "offset": j.get("offset"),
        "items_in_page": len(items),
        "mode_dist_in_page": mode_dist,
        "handoff_n_in_page": sum(1 for it in items if it.get("handoff_no")),
        "order_n_in_page": sum(1 for it in items if it.get("order_no")),
        # em-dash 등 cp949 콘솔에서 깨지는 기호가 섞여 있어 로그에는 안 찍는다(파일에만 남긴다).
        "scope_note": j.get("scope_note"),
        "examples": {
            "done": ({"session_id": done["session_id"], "mode": done["mode"],
                       "tier_total": done["rep"]["total"], "part_count": len(done["rep"]["parts"])}
                      if done else None),
            "dropped": ({"session_id": dropped["session_id"], "mode": dropped["mode"]}
                         if dropped else None),
            "handoff": ({"session_id": handoff["session_id"], "mode": handoff["mode"],
                          "handoff_no": handoff["handoff_no"]}
                         if handoff else None),
        },
    }
    return done, dropped, handoff, stats


def _close_drawer_if_open(page) -> None:
    """서랍이 열려 있으면 닫는다 — 열린 채로 두면 `.scrim`(z-index 7)이 목록 위를 덮어

    다음 행 클릭이 실제로는 scrim에서 막힌다("intercepts pointer events", 2026-08-28
    1차 실행에서 실측). 행 전환마다 앱 자신의 클릭 위임이 "닫고 다시 연다"를 한 이벤트
    안에서 처리하긴 하지만, 그건 DOM 이벤트가 실제로 그 행에 도달했을 때 얘기이고
    Playwright의 실제 히트테스트는 화면에 보이는 최상위 요소(scrim)에서 막힌다.
    """
    is_open = page.evaluate("() => { var d = document.getElementById('drawer'); return !!d && !d.hidden; }")
    if not is_open:
        return
    page.locator('.dw-hd .close[data-action="close-drawer"]').click()
    # state="attached"다 — `[hidden]`이 매칭된 순간 바로 참이고, 기본값(visible)을 쓰면
    # "hidden 속성이 있어서 안 보인다"는 정확히 우리가 기다리는 상태와 어긋난다(2026-08-28
    # 1차 실행에서 실측 — Playwright가 "locator resolved to hidden <aside>"라며 타임아웃).
    page.wait_for_selector("#drawer[hidden]", state="attached", timeout=5000)
    page.wait_for_timeout(150)


def _open_row(page, sid: int) -> None:
    _close_drawer_if_open(page)
    page.locator(f'#tbody .row[data-sid="{sid}"]').click()
    page.wait_for_selector("#drawer:not([hidden])", timeout=5000)
    page.wait_for_timeout(200)


def main() -> int:
    coords: dict = {}

    try:
        with capture_session() as page:
            # ---- 1) 화면 열기 -------------------------------------------------------
            page.goto(f"{BASE}{SCREEN_PATH}", wait_until="networkidle")
            try:
                page.wait_for_selector("#tbody .row", timeout=15000)
            except Exception as e:
                log(f"[FATAL] 목록이 15초 안에 안 채워졌습니다: {e}")
                return 1
            page.wait_for_timeout(300)

            full_clip = {"x": 0, "y": 0, "width": VIEWPORT["width"], "height": VIEWPORT["height"]}

            # ---- 2) 예시 세션 3종 선정(문서용 집계도 함께) ----------------------------
            done, dropped, handoff, stats = _fetch_samples(page)
            if not done:
                log("[MISS] 완주(핸드오프·주문 없는) 예시를 못 찾았습니다 — 관련 캡처 건너뜁니다")
            if not dropped:
                log("[MISS] 이탈 예시를 못 찾았습니다 — 관련 캡처 건너뜁니다")
            if not handoff:
                log("[MISS] 완주->인계 예시를 못 찾았습니다 — 관련 캡처 건너뜁니다"
                    "(지금 in-scope 130건 중 orders 연결 0건 · handoffs 연결 3건뿐이라"
                    " 표본이 원래 적습니다 — 실측치와 대조하십시오)")

            # ---- 3) 전체 화면(목록, 서랍 닫힘) ---------------------------------------
            redact_all(page)
            shoot(page, "consult-sessions-full", full_clip, {
                "lnb": ".a2-lnb",
                "lnb_active_item": ".a2-lnb-b a.on",
                "header": ".a2-hd",
                "crumb": ".a2-crumb",
                "now": ".a2-now",
                "ro_badge": ".ro-badge",
                "last_at": "#lastAt",
                "refresh_btn": "#refreshBtn",
                "hub": ".a2-hub",
                "avatar": ".a2-avatar",
                "banner": ".ledger-banner",
                "kpis": "#kpis",
                "mchip_row": "#mchipRow",
                "listwrap": ".listwrap",
                "thead": ".thead",
                "tbody": "#tbody",
                "pager": ".pager",
                "limit_note": ".limit-note",
                "boundary_note": ".boundary-note",
            }, coords)

            # ---- 4) 헤더 확대 --------------------------------------------------------
            hdr_box = get_boxes(page, {"header": ".a2-hd"})["header"]
            if hdr_box:
                shoot(page, "consult-sessions-header", hdr_box, {
                    "crumb": ".a2-crumb",
                    "now": ".a2-now",
                    "ro_badge": ".ro-badge",
                    "last_at": "#lastAt",
                    "refresh_btn": "#refreshBtn",
                    "hub": ".a2-hub",
                    "avatar": ".a2-avatar",
                }, coords)
            else:
                log("[MISS] .a2-hd 를 못 찾았습니다 — consult-sessions-header.png 건너뜀")

            # ---- 5) KPI 카드 확대 -----------------------------------------------------
            kpi_box = get_boxes(page, {"kpis": "#kpis"})["kpis"]
            if kpi_box:
                shoot(page, "consult-sessions-kpis", kpi_box, {
                    "kpi_total": "#kpis > *:nth-child(1)",
                    "kpi_today": "#kpis > *:nth-child(2)",
                    "kpi_donerate": "#kpis > *:nth-child(3)",
                    "kpi_drop": "#kpis > *:nth-child(4)",
                    "kpi_after": "#kpis > *:nth-child(5)",
                }, coords)
            else:
                log("[MISS] #kpis 를 못 찾았습니다 — consult-sessions-kpis.png 건너뜀")

            # ---- 6) 방식 칩 확대 — 2026-08-29 결함③ 해소로 중단 ------------------------
            # 실제 #mchipRow는 세로 31px(줌 반영)뿐인 가로 한 줄이라, "화면 네 폭에서 전부
            # 보이기"와 "인쇄에서 안 잘리기"를 동시에 만족하는 이미지 크기가 없었다(강제로
            # 넓히면 인쇄에서 A4 인쇄 가능 폭을 447px 넘겨 칩이 잘리고, 풀면 좁은 화면에서
            # 칩이 안 보였다 — docs/manual/screens/consult-sessions.html 그림 D 주석 참고).
            # 그래서 그 문서는 이 캡처 대신 설명 목록만 쓴다. 여기서 더 안 찍는다 — 안 그러면
            # 아무도 안 쓰는 이미지·좌표가 매 캡처마다 계속 새로 생긴다.
            #
            # ---- 7) 목록 표 확대(머리글 + 앞쪽 N행) -----------------------------------
            redact_all(page)
            row_count = page.evaluate("document.querySelectorAll('#tbody .row').length")
            n = min(TABLE_ROWS_IN_SHOT, row_count)
            if n > 0:
                row_selectors = [".thead"] + [f"#tbody .row:nth-child({i})" for i in range(1, n + 1)]
                table_clip = union_box(page, row_selectors)
                el_sel = {"thead": ".thead"}
                for i in range(1, n + 1):
                    el_sel[f"row_{i}"] = f"#tbody .row:nth-child({i})"
                shoot(page, "consult-sessions-table", table_clip, el_sel, coords)
            else:
                log("[MISS] 표 행이 없습니다 — consult-sessions-table.png 건너뜀")

            # ---- 8) 완주 예시 — 행 클릭 -> 전체 화면(서랍 열림, 화살표용 실측) + 서랍 확대 --
            if done:
                _open_row(page, done["session_id"])
                redact_all(page)
                shoot(page, "consult-sessions-full-detail", full_clip, {
                    "selected_row": f'#tbody .row[data-sid="{done["session_id"]}"]',
                    "drawer": "#drawer",
                }, coords)
                # 화살표(원시 px) — 실측 bounding box로 기계적으로 계산한다(눈으로 보고
                # 맞춘 것이 아니다 — 지시서: "자동 변환이 없으니 캡처를 보고 사람이
                # 맞춰야 한다"는 원칙에 따라, 사람이 확인하기 전 1차값으로 남긴다).
                boxes = get_boxes(page, {
                    "selected_row": f'#tbody .row[data-sid="{done["session_id"]}"]',
                    "drawer": "#drawer",
                })
                if boxes.get("selected_row") and boxes.get("drawer"):
                    row_b, drw_b = boxes["selected_row"], boxes["drawer"]
                    y = round(row_b["y"] + row_b["height"] / 2)
                    x2 = round(drw_b["x"] + 15)
                    x1 = round(max(x2 - 90, row_b["x"] + row_b["width"] * 0.5))
                    coords["_arrow_full_detail"] = {"x1": x1, "y1": y, "x2": x2, "y2": y,
                                                     "viewBox": f"0 0 {VIEWPORT['width']} {VIEWPORT['height']}",
                                                     "note": "실측 bounding box로 계산한 1차값 — 렌더 확인 전"}
                    log(f"[OK] 화살표 좌표 계산: x1={x1} y1={y} x2={x2} y2={y}")
                else:
                    log("[MISS] 화살표 계산용 박스(selected_row/drawer)를 못 쟀습니다")

                drawer_box = get_boxes(page, {"drawer": "#drawer"})["drawer"]
                if drawer_box:
                    shoot(page, "consult-sessions-drawer-done", drawer_box, {
                        "status": "#dwStatus",
                        "title": "#dwTitle",
                        "close_btn": ".dw-hd .close",
                        "meta": ".dw-hd .meta",
                        "constraints_cap": "#dwBody > div:nth-child(1) .dw-cap",
                        "constraints_chips": "#dwBody .cchips",
                        "tier_cap": "#dwBody .tiercards",
                        "tiercard_1": "#dwBody .tiercard:nth-child(1)",
                        "tiercard_2": "#dwBody .tiercard:nth-child(2)",
                        "tiercard_3": "#dwBody .tiercard:nth-child(3)",
                        "parts_box": "#dwBody .partsbox",
                    }, coords)
                else:
                    log("[MISS] #drawer 박스를 못 쟀습니다 — consult-sessions-drawer-done.png 건너뜀")

            # ---- 9) 이탈 예시 — 상세 서랍 확대(스냅샷 없음) ---------------------------
            if dropped:
                _open_row(page, dropped["session_id"])
                redact_all(page)
                drawer_box2 = get_boxes(page, {"drawer": "#drawer"})["drawer"]
                if drawer_box2:
                    shoot(page, "consult-sessions-drawer-dropped", drawer_box2, {
                        "status": "#dwStatus",
                        "title": "#dwTitle",
                        "constraints_chips": "#dwBody .cchips",
                        "dropbox": "#dwBody .dropbox",
                        "ledgerlines": "#dwBody .ledgerline:nth-child(2), #dwBody .ledgerline:nth-child(3)",
                        "dist_box": "#dwBody .distbox",
                    }, coords)
                else:
                    log("[MISS] #drawer(이탈) 박스를 못 쟀습니다 — consult-sessions-drawer-dropped.png 건너뜀")

            # ---- 10) 완주->인계 예시 — ④ 원장 두 줄이 보이게 스크롤 후 확대 -----------
            if handoff:
                _open_row(page, handoff["session_id"])
                redact_all(page)
                # dw-body는 자체 overflow:auto라, ④ 완주 이후 상태(handoffs 줄)가 아래쪽에
                # 있으면 스크롤 없이는 화면 밖이다 — 마지막 .ledgerline(= handoffs 줄)을
                # 기준으로 가운데 정렬 스크롤한다.
                page.evaluate("""() => {
                    var els = document.querySelectorAll('#dwBody .ledgerline');
                    if (els.length) els[els.length - 1].scrollIntoView({block: 'center'});
                }""")
                page.wait_for_timeout(150)
                redact_all(page)  # 스크롤 자체는 재렌더가 아니지만, 순서를 보수적으로 지킨다
                drawer_box3 = get_boxes(page, {"drawer": "#drawer"})["drawer"]
                if drawer_box3:
                    shoot(page, "consult-sessions-drawer-handoff", drawer_box3, {
                        "status": "#dwStatus",
                        "ledger_cap": "#dwBody > div:nth-last-child(2) .dw-cap",
                        "ledgerline_orders": "#dwBody .ledgerline:nth-child(2)",
                        "ledgerline_handoffs": "#dwBody .ledgerline:nth-child(3)",
                    }, coords)
                else:
                    log("[MISS] #drawer(완주->인계) 박스를 못 쟀습니다 — consult-sessions-drawer-handoff.png 건너뜀")

    except CaptureError as e:
        log(f"[FATAL] {e}")
        return 1

    coords["_meta"] = build_meta(SCREEN_ID, SCREEN_PATH, VIEWPORT, stats)
    write_coords("consult-sessions", coords)

    log(f"[INFO] 전체(scope 적용) {stats['total']}건 - 완주 {stats['done_total']} / 이탈 {stats['drop_total']}"
        f" · 오늘 {stats['today']}건 · 이 페이지 {stats['items_in_page']}건"
        f"(handoff연결 {stats['handoff_n_in_page']} / order연결 {stats['order_n_in_page']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
