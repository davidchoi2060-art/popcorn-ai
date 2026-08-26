# -*- coding: utf-8 -*-
"""운영자 매뉴얼용 화면 캡처 — 운영자 · 권한(ADM-SYS-020, 경로 /admin2/operators).

공통 부분(로그인·캡처·좌표 뽑기·비율 환산·개인정보 가리기)은
`scripts/manual_capture_common.py`(공용 도구, 이 파일에서 고치지 않는다)를 그대로
쓴다. 이 파일에는 **이 화면에만 해당하는 것**(경로·선택자·무엇을 확대할지·개인정보를
어디서 가릴지)만 있다.

■★ 이 화면은 실제 사람 이름·이메일을 보여준다 — 반드시 가린다
  `manual_capture_common.py` 모듈 docstring이 신설 이유로 콕 집어 든 화면이 이것이다.
  ① 계정 표(각 행의 이름·이메일) ② 상세 서랍 머리글(이름·이메일 확대) ③ 상세 서랍의
  「이메일 정정」 입력창(`<input value>` — `redact_text`는 `textContent`만 바꾸므로
  이것만은 못 가린다, 아래 `redact_all()`에서 별도로 채운다) ④ 「신원 · 승인 근거」
  문장 중 "승인자: 실명"(승인해 준 사람의 실명이 문장 «안에» 섞여 나온다 —
  선택자 하나로 못 자르므로 문구 시작 패턴으로 찾아 지운다) ⑤ 상세 서랍의 「연락처·
  직무」 추가줄(있을 때만 렌더되므로, 없으면 아무 일도 안 하고 있으면 지운다)
  ⑥ 아바타 이니셜(이름 첫 글자 — 값을 바꿔도 어색해지는 자리라 공용 `redact_blur`로
  흐리게).

  **중요 — 매 스크린샷 직전에 다시 가려야 한다.** 이 화면은 상태가 바뀔 때마다
  (행 클릭·서랍 재렌더·탭 전환·비밀번호 발급 폼 토글) `innerHTML`을 실제 데이터로
  **통째로 다시 그린다**(JS 메모리의 `S.data`가 원본을 그대로 들고 있다 — DOM
  텍스트만 바꾼 것은 재렌더 한 번에 지워진다). 그래서 `redact_all()`을 한 번만
  부르고 끝내면 두 번째 스크린샷부터 실명이 다시 나온다 — 이 파일은 `shoot()`
  **직전마다** `redact_all()`을 다시 부른다.

■ 절대 누르지 않는 것 — 실제로 DB를 바꾸는 버튼
  `do-approve`(승인/정지해제) · `do-role-change`(등급 변경) · `do-suspend`(정지) ·
  `do-email-fix`(이메일 정정) · `do-issue-pw`(비밀번호 발급 — 실제 제출). 이 화면은
  `/api/admin/operators`가 **조회조차 owner 전용**이라 로그인만으로 이미 실제
  운영자 18명의 데이터를 그대로 읽는다 — 그런데도 **쓰기 버튼은 하나도 누르지
  않는다**(로컬 DB가 곧 운영 DB — 지시서 규약). 누르는 것은 행 열기·서랍 닫기·탭
  전환·「임시 비밀번호 발급」 입력창 펼치기·「무작위 생성」(순수 클라이언트 계산,
  네트워크 요청 없음)뿐이다 — 전부 되돌릴 필요가 없는 읽기/로컬 UI 상태 변경이다.

무엇을 하는가
    1. 로컬 서버(127.0.0.1:8000 — **사장님 서버, 절대 죽이지 않는다**)에 Playwright로 접속한다.
    2. GET /api/admin/auth/dev-login 으로 점검 계정(owner 등급) 세션을 심는다.
    3. /admin2/operators 를 열고 데이터 로드를 기다린 뒤, 화면 전체 + 주요 영역을
       PNG로 저장한다 — **저장 직전 매번 이름·이메일을 가짜 값으로 덮는다.**
    4. 각 캡처 안 주요 요소의 실측 bounding box를 좌표 JSON(operators-coords.json)에
       남긴다. **이 JSON에는 실명·이메일을 절대 담지 않는다** — 문서용 실측 수치는
       개수·비율 같은 집계만 `_meta.stats`에 넣는다(원본 `items` 배열은 저장하지 않음 —
       그 배열엔 이름·이메일이 그대로 있다).

다시 찍을 때
    .venv/Scripts/python scripts/manual_shots_operators.py
    기존 PNG·JSON을 덮어쓴다(파일명 고정). 화면이 바뀌면 이 스크립트를 그대로
    다시 돌리면 되지만, 계정 데이터(활성/정지 수·역할 분포)도 그때그때 바뀌므로
    `docs/manual/screens/operators.html`의 실측 수치도 함께 다시 확인해야 한다.

읽기 전용이다 — DB에 쓰지 않는다. 포트 8000에는 dev-login(GET) 1회와 그 뒤 페이지가
스스로 부르는 GET들만 나간다(POST는 전혀 없다).
"""
import sys
from collections import Counter

from manual_capture_common import (
    BASE, VIEWPORT, CaptureError,
    build_meta, capture_session, get_boxes, log, redact_blur, redact_text, shoot,
    union_box, write_coords,
)

SCREEN_PATH = "/admin2/operators"
SCREEN_ID = "ADM-SYS-020"

TABLE_ROWS_IN_SHOT = 8

# 명백히 실존 인물이 아닌 예시 이름 — 실제 성씨 + 관리도구스러운 가짜 이름 조합.
# 두 인물(활성 계정 예시 · 정지 계정 예시)로 화면을 구분해 두 그림이 똑같아 보이지
# 않게 한다. 지시서: "가짜 이름을 쓸 때는 실제로 없는 이름으로".
FAKE_ACTIVE = ("홍길동", "hong.gildong@example.com")
FAKE_SUSPENDED = ("김운영", "kim.unyoung@example.com")


def redact_all(page, name: str, email: str) -> None:
    """표 전체 행 + (열려 있으면) 상세 서랍까지 이름·이메일을 가짜 값으로 덮는다.

    행 클릭·서랍 재렌더·탭 전환마다 `innerHTML`이 실데이터로 다시 그려지므로,
    **`shoot()` 직전마다 매번 다시 부른다** — 한 번만 부르면 두 번째 캡처부터
    실명이 되살아난다(위 모듈 docstring 참조).
    """
    redact_text(page, {
        "#orTbody .or-acct-name": name,
        "#orTbody .or-acct-email": email,
        "#orDrawer .or-drawer-name": name,
        "#orDrawer .or-drawer-email": email,
    })
    redact_blur(page, [".or-avatar"], px=6)
    # 공용 redact_text/redact_blur는 textContent만 다룬다 — <input value>와
    # "승인자: 실명"처럼 문장 «안에» 섞인 이름, 있을 때만 나오는 연락처·직무 줄은
    # 이 화면 전용으로 보강한다(공용 모듈은 고치지 않는다 — 다섯 명이 같이 쓴다).
    page.evaluate("""(email) => {
        var ei = document.getElementById('orEmailInput');
        if (ei) ei.value = email;
        document.querySelectorAll('#orDrawer .or-idrow .tx').forEach(function (el) {
            if (el.textContent.indexOf('승인자: ') === 0) el.textContent = '승인자: (가림)';
        });
        var me = document.querySelector('.or-metaextra');
        if (me) me.textContent = '';
    }""", email)


def _find_row_id(page, want: str) -> str | None:
    """want='active'|'suspended' — 조건에 맞는 첫 행의 data-id. 없으면 None.

    상태 칩 텍스트로 찾는다(`.pending` 클래스는 '대기'에만 붙어 있어 정지 판별에
    못 쓴다 — 행 구조상 상태 칸은 3번째 span, `renderTable()`의 컬럼 순서 그대로).
    """
    return page.evaluate("""(want) => {
        var rows = Array.from(document.querySelectorAll('#orTbody .or-row'));
        var target = rows.find(function (r) {
            var statusSpan = r.children[2];
            var isMe = !!r.querySelector('.or-chip-me');
            var txt = statusSpan ? statusSpan.textContent : '';
            if (want === 'active') return txt.indexOf('활성') >= 0 && !isMe;
            return txt.indexOf('정지') >= 0;
        });
        return target ? target.getAttribute('data-id') : null;
    }""", want)


def main() -> int:
    coords: dict = {}

    try:
        with capture_session() as page:
            # ---- 1) 화면 열기 -------------------------------------------------------
            page.goto(f"{BASE}{SCREEN_PATH}", wait_until="networkidle")
            try:
                page.wait_for_selector("#orTbody .or-row", timeout=15000)
            except Exception as e:
                log(f"[FATAL] 계정 목록이 15초 안에 안 채워졌습니다: {e}")
                return 1
            page.wait_for_timeout(300)

            full_clip = {"x": 0, "y": 0, "width": VIEWPORT["width"], "height": VIEWPORT["height"]}

            # ---- 2) 전체 화면(계정 목록 탭, 서랍 닫힘) --------------------------------
            redact_all(page, *FAKE_ACTIVE)
            shoot(page, "operators-full", full_clip, {
                "lnb": ".a2-lnb",
                "lnb_active_item": ".a2-lnb-b a.on",
                "header": ".a2-hd",
                "crumb": ".a2-crumb",
                "permhint": ".or-permhint",
                "hub": ".a2-hub",
                "role_box": "#roleBox",
                "avatar": ".a2-avatar",
                "note": "#orNote",
                "pending_note": "#orPendingNote",
                "general_note": "#orGeneralNoteSub",
                "tabs": "#orTabs",
                "tab_accounts": "#orTabAccounts",
                "tab_ips": "#orTabIps",
                "stats": "#orStats",
                "thead": ".or-thead",
                "first_row": "#orTbody .or-row:first-child",
                "tbody": "#orTbody",
            }, coords)

            # ---- 3) 헤더 확대 --------------------------------------------------------
            hdr_box = get_boxes(page, {"header": ".a2-hd"})["header"]
            if hdr_box:
                shoot(page, "operators-header", hdr_box, {
                    "crumb": ".a2-crumb",
                    "now": ".a2-now",
                    "permhint": ".or-permhint",
                    "hub": ".a2-hub",
                    "role_box": "#roleBox",
                    "avatar": ".a2-avatar",
                }, coords)
            else:
                log("[MISS] .a2-hd 를 못 찾았습니다 — operators-header.png 건너뜀")

            # ---- 4) 통계 카드 확대 ----------------------------------------------------
            stats_box = get_boxes(page, {"stats": "#orStats"})["stats"]
            if stats_box:
                shoot(page, "operators-stats", stats_box, {
                    "stat_1": ".or-stat:nth-child(1)",
                    "stat_2": ".or-stat:nth-child(2)",
                    "stat_3": ".or-stat:nth-child(3)",
                    "stat_4": ".or-stat:nth-child(4)",
                    "stat_5": ".or-stat:nth-child(5)",
                }, coords)
            else:
                log("[MISS] #orStats 를 못 찾았습니다 — operators-stats.png 건너뜀")

            # ---- 5) 목록 표 확대(머리글 + 앞쪽 N행) -----------------------------------
            row_count = page.evaluate("document.querySelectorAll('#orTbody .or-row').length")
            n = min(TABLE_ROWS_IN_SHOT, row_count)
            if n > 0:
                row_selectors = [".or-thead"] + [
                    f"#orTbody .or-row:nth-child({i})" for i in range(1, n + 1)]
                table_clip = union_box(page, row_selectors)
                el_sel = {"thead": ".or-thead"}
                for i in range(1, n + 1):
                    el_sel[f"row_{i}"] = f"#orTbody .or-row:nth-child({i})"
                shoot(page, "operators-table", table_clip, el_sel, coords)
            else:
                log("[MISS] 표 행이 없습니다 — operators-table.png 건너뜀")

            # ---- 6) 「접근 IP 허용」 탭 — 향후 사용예정 자리 표시(서랍 닫힌 상태에서) ----
            page.locator('[data-action="pick-tab"][data-t="ips"]').click()
            try:
                page.wait_for_selector("#orIpsPanel:not([hidden])", timeout=5000)
                page.wait_for_timeout(150)
                ips_box = get_boxes(page, {"ips": "#orIpsPanel"})["ips"]
                if ips_box:
                    shoot(page, "operators-ips-placeholder", ips_box, {
                        "tab_ips": "#orTabIps",
                        "title": ".or-ipplaceholder .ti",
                        "desc": ".or-ipplaceholder .ds",
                    }, coords)
                else:
                    log("[MISS] #orIpsPanel 박스를 못 쟀습니다")
            except Exception as e:
                log(f"[MISS] IP 탭 캡처 실패: {e}")
            # 계정 목록 탭으로 되돌린다(이후 단계 전제)
            page.locator('[data-action="pick-tab"][data-t="accounts"]').click()
            page.wait_for_selector("#orAccountsPanel:not([hidden])", timeout=5000)

            # ---- 7) 활성 계정 행을 열어 상세 서랍 확인 --------------------------------
            active_id = _find_row_id(page, "active")
            if active_id:
                page.locator(f'#orTbody .or-row[data-id="{active_id}"]').click()
                try:
                    page.wait_for_selector("#orDrawer:not([hidden])", timeout=5000)
                    page.wait_for_timeout(200)
                except Exception as e:
                    log(f"[MISS] 상세 서랍이 안 열렸습니다(id={active_id}): {e}")
                    active_id = None

            if active_id:
                redact_all(page, *FAKE_ACTIVE)
                # 7a) 드로어가 열린 상태의 전체 화면 — "행을 누르면 여기로 열린다"는 것 자체
                shoot(page, "operators-full-detail", full_clip, {
                    "selected_row": f'#orTbody .or-row[data-id="{active_id}"]',
                    "drawer": "#orDrawer",
                }, coords)

                # 7b) 상세 서랍 확대(활성 계정 — 등급 변경 · 비밀번호 · 이메일 정정 · 정지)
                drawer_box = get_boxes(page, {"drawer": "#orDrawer"})["drawer"]
                if drawer_box:
                    shoot(page, "operators-drawer-active", drawer_box, {
                        "hd": ".or-drawer-hd",
                        "name": ".or-drawer-name",
                        "email": ".or-drawer-email",
                        "role_chip": ".or-drawer-hdrow > span:nth-child(3)",
                        "status_chip": ".or-drawer-hdrow > span:nth-child(4)",
                        "close_btn": ".or-drawer-close",
                        "meta": ".or-drawer-meta",
                        "idrows_label": ".or-drawer-body > div:first-child .or-label",
                        "idrows_list": ".or-idrows",
                        "role_change_pillrow": ".or-pillrow",
                        "role_pill_owner": '[data-action="do-role-change"][data-r="owner"]',
                        "role_pill_operator": '[data-action="do-role-change"][data-r="operator"]',
                        "role_pill_viewer": '[data-action="do-role-change"][data-r="viewer"]',
                        "password_toggle_btn": '[data-action="toggle-issue-pw"]',
                        "email_input": "#orEmailInput",
                        "email_fix_btn": '[data-action="do-email-fix"]',
                        "suspend_btn": '[data-action="do-suspend"]',
                    }, coords)
                else:
                    log("[MISS] #orDrawer 박스를 못 쟀습니다 — operators-drawer-active.png 건너뜀")

                # ---- 8) 「임시 비밀번호 발급」 입력창 펼치기(읽기 전용 — 발급 버튼은 안 누른다) --
                page.locator('[data-action="toggle-issue-pw"]').click()
                try:
                    page.wait_for_selector(".or-rules, .or-rulesloading", timeout=5000)
                    page.wait_for_timeout(150)
                    # 규칙 목록이 늦게 도착하는 경우까지 한 번 더 대기
                    page.wait_for_selector(".or-rules", timeout=3000)
                except Exception as e:
                    log(f"[MISS] 비밀번호 규칙 로드 대기 실패(그래도 캡처는 진행합니다): {e}")
                # 순수 클라이언트 계산(네트워크 요청 없음) — 입력창을 채워 보여준다.
                # 실제 발급([발급] 버튼)은 절대 누르지 않는다.
                gen_btn = page.locator('[data-action="gen-pw"]')
                if gen_btn.count():
                    gen_btn.click()
                    page.wait_for_timeout(150)
                redact_all(page, *FAKE_ACTIVE)  # 토글·생성이 서랍을 다시 그려 이름/이메일이 되살아났다
                drawer_box2 = get_boxes(page, {"drawer": "#orDrawer"})["drawer"]
                if drawer_box2:
                    shoot(page, "operators-drawer-issuepw", drawer_box2, {
                        "toggle_btn": '[data-action="toggle-issue-pw"]',
                        "pw_input": "#orPwInput",
                        "gen_btn": '[data-action="gen-pw"]',
                        "copy_btn": '[data-action="copy-pw"]',
                        "cancel_btn": '[data-action="cancel-issue-pw"]',
                        "issue_btn": '[data-action="do-issue-pw"]',
                        "rules_list": ".or-rules, .or-rulesloading",
                        "note": ".or-issuenote",
                    }, coords)
                else:
                    log("[MISS] #orDrawer(비밀번호 발급) 박스를 못 쟀습니다")

                # 서랍을 닫고 다음 대상으로 넘어간다
                # ⚠ data-action="close-drawer"가 두 곳(오버레이 div + 닫기 버튼)에 있어
                # 일반 선택자는 "strict mode violation"으로 죽는다 — 버튼으로 좁힌다.
                page.locator('.or-drawer-close[data-action="close-drawer"]').click()
                page.wait_for_timeout(150)
            else:
                log("[MISS] 열 수 있는 활성 계정 행이 없습니다 — 활성 계정 서랍 캡처 3종 건너뜀")

            # ---- 9) 정지 계정 행을 열어 「정지 해제」 상태 확인 -------------------------
            susp_id = _find_row_id(page, "suspended")
            if susp_id:
                page.locator(f'#orTbody .or-row[data-id="{susp_id}"]').click()
                try:
                    page.wait_for_selector("#orDrawer:not([hidden])", timeout=5000)
                    page.wait_for_timeout(200)
                except Exception as e:
                    log(f"[MISS] 정지 계정 상세 서랍이 안 열렸습니다(id={susp_id}): {e}")
                    susp_id = None

            if susp_id:
                redact_all(page, *FAKE_SUSPENDED)
                drawer_box3 = get_boxes(page, {"drawer": "#orDrawer"})["drawer"]
                if drawer_box3:
                    shoot(page, "operators-drawer-suspended", drawer_box3, {
                        "hd": ".or-drawer-hd",
                        "name": ".or-drawer-name",
                        "email": ".or-drawer-email",
                        "status_chip": ".or-drawer-hdrow > span:nth-child(4)",
                        "approve_box": ".or-approvebox",
                        "approve_pillrow": ".or-pillrow",
                        "approve_btn": '[data-action="do-approve"]',
                        "suspend_box": ".or-suspendbox",
                        "suspend_btn": '[data-action="do-suspend"]',
                    }, coords)
                else:
                    log("[MISS] #orDrawer(정지 계정) 박스를 못 쟀습니다")
            else:
                log("[MISS] 정지 상태 행이 없습니다 — operators-drawer-suspended.png 건너뜀"
                    "(지금 정지 계정이 0건이라는 뜻일 수 있습니다 — 실측치와 대조하십시오)")

            # ---- 10) 문서용 실측 수치 — 집계만 남긴다(이름·이메일 원본은 저장하지 않는다) --
            stats: dict = {}
            try:
                r1 = page.request.get(f"{BASE}/api/admin/operators")
                if r1.ok:
                    j1 = r1.json()
                    items = j1.get("items", [])
                    active = [x for x in items if x["status"] == "활성"]
                    suspended = [x for x in items if x["status"] == "정지"]
                    acts_sorted = sorted((x["acts"] for x in items), reverse=True)
                    acts_sum = sum(acts_sorted)
                    top2 = sum(acts_sorted[:2])
                    stats["operators"] = {
                        "total": len(items),
                        "active": len(active),
                        "suspended": len(suspended),
                        "pending": sum(1 for x in items if x["status"] == "대기"),
                        "by_role_active": dict(Counter(x["role"] for x in active)),
                        "by_role_suspended": dict(Counter(x["role"] for x in suspended)),
                        "no_password": sum(1 for x in items if not x["has_password"]),
                        "must_change_password": sum(1 for x in items if x["must_change_password"]),
                        "is_locked": sum(1 for x in items if x["is_locked"]),
                        "live_sessions_sum": sum(x["live_sessions"] for x in items),
                        "acts_sum": acts_sum,
                        "acts_top2_sum": top2,
                        "acts_top2_pct": round(top2 / acts_sum * 100, 1) if acts_sum else None,
                        "acts_zero_count": sum(1 for a in acts_sorted if a == 0),
                        "provider_dist": dict(Counter(x["provider"] for x in items)),
                        "provider_verified_true_count": sum(1 for x in items if x["provider_verified"]),
                        "bad_email_count": sum(1 for x in items if str(x["email"]).count("@") > 1),
                        "pending_note": j1.get("pending_note"),
                        "note": j1.get("note"),
                    }
                r2 = page.request.get(f"{BASE}/api/admin/auth/password-policy")
                if r2.ok:
                    stats["password_policy"] = r2.json()
            except Exception as e:
                log(f"[MISS] 문서용 수치 조회 실패(캡처는 이미 끝났습니다): {e}")

    except CaptureError as e:
        log(f"[FATAL] {e}")
        return 1

    coords["_meta"] = build_meta(SCREEN_ID, SCREEN_PATH, VIEWPORT, stats)
    write_coords("operators", coords)

    op = coords["_meta"]["stats"].get("operators")
    if op:
        log(f"[INFO] 등록 {op['total']}건 - 활성 {op['active']} / 정지 {op['suspended']} / 대기 {op['pending']}"
            f" · 비밀번호없음 {op['no_password']} · 활동합계 {op['acts_sum']}"
            f"(상위2계정 {op['acts_top2_sum']}={op['acts_top2_pct']}%)"
            f" · 실명확인0(dev어댑터) provider_verified_true={op['provider_verified_true_count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
