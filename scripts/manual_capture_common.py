# -*- coding: utf-8 -*-
"""운영자 매뉴얼용 화면 캡처 — 공용 도구 (2026-08-25 분리, 회귀 [41] 후속 작업).

`scripts/manual_shots.py`가 상품 사양 검수(/admin2/reviews) 하나에 고정된 389줄
단일 파일이었다. 다섯 명이 각자 다른 화면(상품 관리 · 상품 분류 관리 · 운영자·권한 ·
오픈 단계 설정 · 대시보드)을 동시에 찍어야 하는데, 그 구조로는 한 파일을 다섯이
동시에 만져 충돌한다. 그래서 **공통 부분(로그인·캡처·좌표 뽑기·비율 환산)을 여기로,
화면별 부분(경로·선택자·무엇을 확대할지)을 화면마다 별도 파일로** 가른다.

기존 함수 `get_boxes`·`union_box`·`to_pct`·`shoot`는 이름·동작을 그대로 옮겼다(새로
짓지 않았다) — 이미 reviews 캡처 8장 + 좌표 JSON을 만들어 검증된 코드다.

■ 새 화면 캡처를 추가하려면 — **파일 하나만 만들면 된다**
    1. `scripts/manual_shots_<screen>.py` 를 새로 만든다(기존 파일은 건드리지 않는다 —
       화면 하나 추가가 파일 하나 추가다, 공용 파일을 다시 고치지 않는다).
    2. 이 모듈에서 필요한 것만 가져온다:

           from manual_capture_common import (
               BASE, OUT_DIR, VIEWPORT, CaptureError,
               log, get_boxes, union_box, to_pct, shoot,
               capture_session, write_coords, build_meta,
               redact_text, redact_blur,
           )

       (`scripts/` 를 스크립트 실행 디렉터리로 삼는 상대 import다 — 기존 관례대로
       `.venv/Scripts/python scripts/manual_shots_<screen>.py` 로 돌린다.)
    3. `main()` 에서 `with capture_session() as page:` 로 로그인된 `page` 를 받고,
       `page.goto(f"{BASE}/admin2/<경로>", wait_until="networkidle")` 로 화면을 연 뒤
       필요한 대기(`page.wait_for_function`/`wait_for_selector`)를 하고
       `shoot(page, "<파일이름>", clip, {선택자들}, coords)` 를 필요한 만큼 부른다.
    4. **개인정보(이름·이메일 등)가 보이는 선택자가 있으면 캡처 전에 반드시**
       `redact_text()` 또는 `redact_blur()` 로 가린다 — 특히 `/admin2/operators`
       (운영자·권한, 실제 사람 이름·이메일이 나온다). 다섯 명이 각자 만들면 누군가는
       빠뜨리므로 화면별 스크립트가 아니라 이 공용 모듈에 함수로 둔다(아래 참조).
    5. 마지막에 `coords["_meta"] = build_meta(...)` 로 메타를 채우고
       `write_coords("<screen>", coords)` 로 저장한다.

■ 왜 `scripts/manual_shots.py` 파일명을 그대로 남겼는가
    `docs/manual/screens/reviews.html`과 `docs/manual/운영자매뉴얼-상품사양검수.html`
    (둘 다 다른 제작자 소유 — 이번 작업에서 건드리지 않음)이 재촬영 명령으로
    `.venv/Scripts/python scripts/manual_shots.py` 를 **문서 본문에 그대로 박아** 뒀다.
    파일명을 바꾸면 그 문서만 조용히 낡는다 — 그래서 `manual_shots.py` 는 경로·산출물
    이름을 그대로 두고 **내용만** 이 공용 모듈을 쓰도록 얇게 다시 짰다.

■ 읽기 전용 원칙은 화면마다 같다
    이 모듈도, 이 모듈을 쓰는 화면별 스크립트도 DB에 쓰지 않는다. 포트 8000(사장님
    서버, 절대 죽이지 않는다)에는 dev-login 1회 + 화면이 부르는 GET들만 나간다.
"""
import json
import os
import pathlib
import sys
from contextlib import contextmanager
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright


def _resolve_base() -> str:
    """BASE 우선순위: CLI 인자(``--base=URL``) > 환경변수(``MANUAL_CAPTURE_BASE``) > 기본값.

    2026-08-28 신설 — **이 파일 «자신의 한계»를 고치는 예외다**(위 docstring의 "공용
    파일을 다시 고치지 않는다"는 화면을 추가할 때의 규약이지, 지금처럼 이 상수 자체가
    하드코딩이라 막힌 경우의 규약이 아니다). 포트 8000은 사장님 서버라 절대 재시작하지
    않는데, 캡처 대상 화면의 파이썬 코드를 고치면 그 변경을 반영한 서버를 8000이 «아닌»
    포트에 새로 띄워야 캡처할 수 있다 — 그런데 BASE가 상수라 가리킬 방법이 없었다
    (candidate-pool 매뉴얼의 "oos" REASON_TARGET_PATH 재촬영이 이 문제로 미뤄졌다).
    **기본값은 바꾸지 않는다** — 인자·환경변수를 안 주면 지금까지와 똑같이 8000을 본다.
    """
    for arg in sys.argv[1:]:
        if arg.startswith("--base="):
            return arg.split("=", 1)[1]
    return os.environ.get("MANUAL_CAPTURE_BASE", "http://127.0.0.1:8000")


BASE = _resolve_base()
ROOT = pathlib.Path(__file__).resolve().parent.parent
# 2026-08-25 확정 위치 — **바꾸지 않는다**(운영자 매뉴얼 화면 `/admin2/manual/*` 이
# `/shared/manual/shots/…` 로 읽는 실제 서빙 경로 — `mockups/` 가 서버 루트에 통째로
# 마운트돼 있어 `mockups/shared/` 아래가 곧 `/shared/` 다). 최초 촬영(2026-08-25)은
# `docs/manual/shots/`에도 남아 있다 — 지우지 않고 대조용으로 둔다.
OUT_DIR = ROOT / "mockups" / "shared" / "manual" / "shots"
VIEWPORT = {"width": 1680, "height": 1050}


class CaptureError(Exception):
    """캡처를 계속할 수 없는 상태(로그인 실패 등). 화면별 스크립트의 main()이 잡아
    log() 후 종료 코드 1로 나가면 된다."""


def log(msg: str) -> None:
    # 서버 stdout 이 아니라 이 스크립트 자신의 콘솔 출력이지만, 팀 관례(ASCII 기호만)를
    # 그대로 따른다 — em-dash·화살표 대신 "-"·"->"(CLAUDE.md — cp949 콘솔에서 깨진다).
    print(msg, flush=True)


def get_boxes(page, selectors: dict) -> dict:
    """selectors: {이름: css선택자}. 보이지 않거나(hidden/display:none) 없으면 None.

    getBoundingClientRect() 실측값 그대로 — 지어낸 좌표가 아니다.
    """
    js = """(sel) => {
        const out = {};
        for (const name in sel) {
            const css = sel[name];
            const el = document.querySelector(css);
            if (!el) { out[name] = null; continue; }
            const cs = getComputedStyle(el);
            if (cs.display === 'none' || cs.visibility === 'hidden' || el.hidden) { out[name] = null; continue; }
            const r = el.getBoundingClientRect();
            if (r.width === 0 && r.height === 0) { out[name] = null; continue; }
            out[name] = {x: r.x, y: r.y, width: r.width, height: r.height};
        }
        return out;
    }"""
    return page.evaluate(js, selectors)


def union_box(page, selector_list):
    """여러 요소의 bounding box를 합친 사각형(표 헤더+행 여러 개를 한 캡처에 담을 때 씀).

    반환: {x, y, width, height} 또는 아무것도 못 찾으면 None.
    """
    js = """(sels) => {
        const rects = [];
        for (const css of sels) {
            const el = document.querySelector(css);
            if (!el) continue;
            const r = el.getBoundingClientRect();
            if (r.width === 0 && r.height === 0) continue;
            rects.push(r);
        }
        if (!rects.length) return null;
        const x = Math.min(...rects.map(r => r.x));
        const y = Math.min(...rects.map(r => r.y));
        const right = Math.max(...rects.map(r => r.x + r.width));
        const bottom = Math.max(...rects.map(r => r.y + r.height));
        return {x, y, width: right - x, height: bottom - y};
    }"""
    return page.evaluate(js, selector_list)


def to_pct(clip: dict, box: dict) -> dict:
    """clip(캡처 영역, 페이지 좌표) 안에서 box가 차지하는 자리를 %로 환산.

    HTML 쪽 CSS 오버레이가 이 값을 그대로 --x/--y(중심점)·left/top/width/height(%)로 쓴다.
    """
    cx = box["x"] + box["width"] / 2
    cy = box["y"] + box["height"] / 2
    return {
        "x_pct": round((box["x"] - clip["x"]) / clip["width"] * 100, 2),
        "y_pct": round((box["y"] - clip["y"]) / clip["height"] * 100, 2),
        "w_pct": round(box["width"] / clip["width"] * 100, 2),
        "h_pct": round(box["height"] / clip["height"] * 100, 2),
        "cx_pct": round((cx - clip["x"]) / clip["width"] * 100, 2),
        "cy_pct": round((cy - clip["y"]) / clip["height"] * 100, 2),
    }


def shoot(page, name: str, clip: dict, element_selectors: dict, coords: dict,
          out_dir: pathlib.Path = OUT_DIR) -> None:
    """clip 영역을 PNG로 저장하고, element_selectors 안 요소들의 %좌표를 coords[name]에 적는다."""
    path = out_dir / f"{name}.png"
    page.screenshot(path=str(path), clip=clip)
    boxes = get_boxes(page, element_selectors)
    elements = {}
    missing = []
    for ename, box in boxes.items():
        if box is None:
            missing.append(ename)
            continue
        elements[ename] = {**to_pct(clip, box), "px": box}
    coords[name] = {
        "file": f"{name}.png",
        "clip_px": clip,
        "elements": elements,
    }
    log(f"[OK] {name}.png  clip={int(clip['width'])}x{int(clip['height'])}  요소 {len(elements)}개"
        + (f"  못찾음={missing}" if missing else ""))


# ── 개인정보 가리기 (2026-08-25 신설 — /admin2/operators 대비) ──────────────────────
#
# 운영자·권한 화면은 실제 사람 이름·이메일을 보여준다. 그대로 캡처하면 개인정보가
# 문서에 박힌다. 지시서 원문: "다섯 명이 각자 만들면 누군가는 빠뜨린다" — 그래서
# 화면별 스크립트가 아니라 **공용 도구 쪽에** 둔다. screenshot 을 찍기 «전»에 부른다.
def redact_text(page, replacements: dict) -> None:
    """selectors 안 텍스트를 가짜 값으로 바꾼다(이름·이메일 등 — 모양은 남기고 값만 지운다).

    replacements: {css선택자: 대체할 문자열}. 선택자에 맞는 요소가 여럿이면 전부 바뀐다.
    DOM 만 바꾸고 서버에는 아무것도 보내지 않는다(읽기 전용 — 페이지를 새로고침하지
    않는 한 원래 값은 서버에 그대로 남는다). 캡처 직전에 부른다.
    """
    js = """(reps) => {
        for (const sel in reps) {
            document.querySelectorAll(sel).forEach(el => { el.textContent = reps[sel]; });
        }
    }"""
    page.evaluate(js, replacements)
    log(f"[OK] 개인정보 텍스트 치환: {list(replacements.keys())}")


def redact_blur(page, selectors, px: int = 6) -> None:
    """selectors 요소를 흐리게 만든다 — 값은 안 바꾸고 읽지 못하게만 한다(레이아웃 보존).

    이름을 무엇으로 바꿔도 어색해지는 자리(아바타 이니셜 등)에 쓴다.
    """
    js = """(args) => {
        const [sels, px] = args;
        for (const css of sels) {
            document.querySelectorAll(css).forEach(el => {
                el.style.filter = `blur(${px}px)`;
                el.style.userSelect = 'none';
            });
        }
    }"""
    page.evaluate(js, [list(selectors), px])
    log(f"[OK] 개인정보 흐림 처리({px}px): {list(selectors)}")


@contextmanager
def capture_session(viewport: dict | None = None):
    """브라우저를 열고 점검 계정 세션을 심은 `page` 를 내준다 — 화면별 스크립트의 진입점.

    사용:
        with capture_session() as page:
            page.goto(f"{BASE}/admin2/<경로>", wait_until="networkidle")
            ... shoot(page, ...) ...

    dev-login 실패는 `CaptureError` 로 던진다 — 화면별 스크립트의 `main()` 이 잡아
    `log()` 후 종료 코드 1로 나가면 된다. 브라우저 정리(`browser.close()`)는 정상
    종료·예외·조기 return 어느 경우든 `finally` 로 보장한다(화면별 스크립트가 각자
    챙기지 않아도 된다).
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport=viewport or VIEWPORT, device_scale_factor=1)
        page = context.new_page()
        try:
            resp = page.request.get(f"{BASE}/api/admin/auth/dev-login")
            if resp.status != 200:
                raise CaptureError(
                    f"dev-login 실패: {resp.status} {resp.text()} — .env 의 "
                    "UI_CHECK_DEV_LOGIN=1 · UI_CHECK_EMAIL 및 tools/ui_check_account.py "
                    "실행 여부를 확인하십시오.")
            info = resp.json()
            log(f"[OK] dev-login: {info['operator']['name']} ({info['operator']['role']})")
            yield page
        finally:
            browser.close()


def build_meta(screen_id: str, path: str, viewport: dict, stats: dict | None = None) -> dict:
    """coords JSON 맨 끝 `_meta` 블록 — 화면별 스크립트는 `stats`(서버 응답 실측치)만 채운다."""
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "base_url": BASE,
        "viewport": viewport,
        "screen": {"screen_id": screen_id, "path": path},
        "stats": stats or {},
    }


def write_coords(slug: str, coords: dict, out_dir: pathlib.Path = OUT_DIR) -> pathlib.Path:
    """coords 를 `<slug>-coords.json` 으로 저장하고 경로를 돌려준다."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{slug}-coords.json"
    path.write_text(json.dumps(coords, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"[OK] 좌표 JSON 저장: {path}")
    return path
