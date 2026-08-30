# -*- coding: utf-8 -*-
"""운영자 매뉴얼 — 핀(.pin 배지) 좌표 자동 검사 (2026-08-29 신설, 같은 날 인쇄 폭 추가,
같은 날 「그림이 지금 화면과 같은가」 신선도 검사 추가).

⚠ **이 파일이 원래 못 보는 것 (2026-08-29 결함⑥ — 왜 신선도 검사를 더했는가)**:
아래 두 검사(경계 이탈·상호 겹침)는 **매뉴얼 문서 안의 그림·핀만** 본다 — "이미지 «안»
에서 핀끼리 안 겹치는가"다. **"그 이미지가 지금 관리자 화면과 같은가"는 이 두 검사
어느 쪽도 보지 않는다.** 2026-08-27 커밋 f888e07(`admin2.css`, `--a2-zoom:1.15` 신설 —
이 파일은 그 커밋을 건드리지 않는다)이 콘텐츠 영역을 15% 키우고 재배치했는데, 그 전에
찍은 캡처 6개(dashboard·products·reviews·categories·operators·ops-settings)가 낡은
채로도 이 스크립트는 계속 "위반 0건"을 냈다 — 거짓말은 아니었다(원래 그건 안 재는
검사였다), 다만 아무도 신선도를 자동으로 재고 있지 않았다. 그래서 **셋째 검사**
(`scripts/manual_check_freshness.py`, 좌표 JSON의 실측 px를 지금 화면에서 같은
선택자로 다시 재 비교)를 추가해 **기본 실행에 넣는다** — "기본에 안 들어간 검사는
아무도 안 돌린다"가 바로 위 인쇄 검사가 두 달 숨어 있던 이유였다.

배경 — 2026-08-28에 핀 9쌍 겹침을 고쳤는데, 2026-08-29에 새 매뉴얼 5개(259개 핀)에서
또 6곳(경계 이탈 3곳 · 상호 겹침 3곳)이 나왔다. 「핀을 어디에 두면 안 되는지」가 코드
어디에도 적혀 있지 않아 다음 제작자도 같은 실수를 반복할 수 있었다 — 그래서 **적어두는
것에 더해 자동으로 걸리는 검사**를 만든다(작업 지시: "가능하면 검사로 만들어라").

무엇을 잰다 — 근사(거리) 기준이 아니라 **실제 렌더된 사각형의 교차**다(어제 "배지 간
거리 < 18px" 기준이 19px 겹침을 놓친 전례가 있다 — 그 기준을 다시 안 쓴다):

    경계 이탈   그 배지가 속한 <div class="shot"> 안 <img>의 getBoundingClientRect() 밖으로
                배지 rect가 나가는가(.shot이 overflow:hidden이라 img 경계 밖은 실제로
                반원으로 잘려 보인다 — img rect가 곧 시각적 클리핑 경계다)
    상호 겹침   같은 <div class="shot"> 안 배지 rect끼리 교차하는가(사각형 교차 계산 —
                x·y 둘 다 겹쳐야 겹침으로 센다)

왜 4개 폭(1680·1192·768·480)을 다 본다 — 배지는 CSS로 고정 픽셀(23px 높이 · 두 자리
번호는 26.05px 폭 — 이 파일이 실측한 값, admin2 전역 `zoom:1.15`가 이미 반영된 «실제
렌더 크기»다)인데 그림은 뷰포트에 비례해 줄어든다(`.shot[style*="max-width:...px"]`에
걸린 최소폭 바닥까지). **바닥에 닿으면 1192·768·480이 완전히 같은 값을 낼 수 있고,
`max-width:300px` 이하 그림(축소 규칙 없음)은 «모든 폭에서 값이 동일»할 수도 있다**
(margin-policy 핀 47·50 실례 — 1680px에서도 위반이었다). 즉 "좁은 폭에서만 보면 된다"는
가정 자체가 틀렸다 — 네 폭을 다 재야 하는 이유다.

⚠ **왜 인쇄(print) 폭도 본다 (2026-08-29 결함⑤ 후속)** — 이 스크립트는 원래 화면(screen)
4폭만 쟀다. 그런데 `@media print`는 **전혀 다른 CSS 규칙 집합**이라(그림 min-width 바닥이
풀리는 폭도 다르고, `.pin` 배지 크기도 print 전용 규칙으로 따로 줄어든다 — `manual.html.j2`
`@media print` 안 `.manual-doc .pin{transform:...scale(...)}` 참고) 화면 4폭이 0건이어도
인쇄에서는 별개로 위반이 날 수 있다 — 실제로 그랬다: 화면은 늘 0건이었는데 인쇄
전용 폭(A4 186mm ≈ 703px)에서 74장이 폭 초과, 그걸 고치자 핀 겹침이 79건 새로 났고,
**둘 다 이 스크립트가 스크린 폭만 재는 한 영원히 안 걸렸을 것이다**(확인자가 별도
스크립트로 재현해서야 드러났다). 그래서 화면 검사와 **같은 `analyze()`**로, 미디어만
print·폭만 PRINT_WIDTH로 바꿔 같은 판정을 추가한다 — 판정 기준(사각형 교차)을 두 벌로
적지 않는다.

사용법(서버를 먼저 띄우고, --base로 «그 포트»를 가리킨다 — 기본값은 8000, 이 검사는
읽기 전용 GET만 나가므로 사장님 서버에 그대로 돌려도 안전하다):

    .venv/Scripts/python scripts/manual_check_pins.py                 # 화면4폭+인쇄+신선도, 기본값
    .venv/Scripts/python scripts/manual_check_pins.py --base=http://127.0.0.1:8002
    .venv/Scripts/python scripts/manual_check_pins.py --slugs=catalog-import,margin-policy
    .venv/Scripts/python scripts/manual_check_pins.py --print-only     # 인쇄만(빠른 반복용)
    .venv/Scripts/python scripts/manual_check_pins.py --screen-only    # 화면 4폭만(기존 동작)
    .venv/Scripts/python scripts/manual_check_pins.py --freshness-only # 신선도만(빠른 반복용)
    .venv/Scripts/python scripts/manual_check_pins.py --no-freshness   # 핀 검사만(기존 동작 그대로)
    .venv/Scripts/python scripts/manual_check_pins.py --fresh-threshold=3.0

종료 코드 0 = 전 폭(화면 4 + 인쇄) 핀 위반 0건 **그리고** 신선도 위반 0건. 0이 아니면
위반이 있다(회귀·CI에서 그대로 쓸 수 있다). **기본값이 인쇄·신선도까지 포함한다** —
옵션으로 두면 다음 사람이 잊고 안 돌린다(인쇄 검사가 정확히 그렇게 두 달 숨어
있었다). `--screen-only`/`--print-only`는 **핀 검사 쪽 폭 선택만** 바꾼다(기존 동작
그대로 — 신선도는 폭 개념이 없어 이 두 옵션과 무관하게 계속 돈다). 신선도만 끄거나
신선도만 돌리려면 `--no-freshness`/`--freshness-only`를 따로 쓴다.

신선도 검사가 «무엇을»·«왜»·«어떻게» 재는지는 `scripts/manual_check_freshness.py`
모듈 docstring 참고 — 이 파일은 그 판정 로직을 다시 적지 않고 그 모듈의
`run_freshness_checks()`를 그대로 불러 쓴다(판정 기준을 두 곳에 적지 않는다, 이
파일 자신이 화면 검사·인쇄 검사에서 이미 지키는 원칙과 같다).

대상 화면 목록은 `api/admin_ui_manual.py`의 `MANUAL_SCREENS`를 다시 읽지 않는다(그 파일은
이 작업의 담당 밖이라 import하지 않는다 — 순환 의존·부팅 부작용을 피한다). 대신
`docs/manual/screens/*.html` 파일명 자체가 슬러그다(그 딕셔너리의 `fragment` 값이 전부
`{slug}.html`이었다 — 2026-08-29 전수 확인).
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from manual_capture_common import BASE, capture_session, log  # noqa: E402
from manual_check_freshness import PX_THRESHOLD as FRESH_PX_THRESHOLD  # noqa: E402
from manual_check_freshness import run_freshness_checks  # noqa: E402

FRAGMENTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "docs" / "manual" / "screens"
WIDTHS = [1680, 1192, 768, 480]
HEIGHT = 1400  # 실측(2026-08-29): 이 페이지는 뷰포트 높이가 바뀌어도 배지·그림 렌더 크기에
# 영향이 없다(admin2 셸이 오버레이 스크롤바를 쓴다 — 스크롤이 가로폭을 잠식하지 않는다).
# 값 자체는 스크롤 걱정 없이 넉넉히만 잡으면 된다.

# 인쇄 폭 — `manual.html.j2`의 `@media print{ @page{size:A4;margin:14mm 12mm} }`와
# 같은 계산이다: 210mm(A4 폭) - 12mm*2(좌우 여백) = 186mm, 96dpi 환산 186*96/25.4 ≈
# 703px(둘을 따로 적지 않으려 했지만 이 스크립트는 CSS를 파싱하지 않으므로 상수로 둔다 —
# `@page` 여백이 바뀌면 이 값도 함께 고친다). 확인자의 재현 스크립트와 같은 값.
PRINT_WIDTH = 703
PRINT_HEIGHT = 4000  # emulate_media("print")는 `page.pdf()`처럼 실제 페이지를 나누지 않고
# 연속 레이아웃으로 그린다(page-break-*는 무시됨) — 그래서 세로로 긴 매뉴얼 한 장을 통째로
# 담을 넉넉한 높이만 있으면 된다(스크롤·페이지 경계 걱정 없음). 확인자 재현 스크립트와 동일.

# 사각형 교차를 셀 때 부동소수 렌더링 잡음을 무시하는 문턱(px). 0에 가깝게 잡아도 되지만
# 완전히 0으로 하면 브라우저 서브픽셀 반올림(0.0x px 수준)이 "위반"으로 잘못 잡힌다.
NOISE_PX = 0.1

JS = r"""
() => {
  const shots = Array.from(document.querySelectorAll('.manual-doc .shot'));
  const out = [];
  shots.forEach(shot => {
    const img = shot.querySelector('img');
    if (!img) return;
    const ir = img.getBoundingClientRect();
    const fig = shot.closest('figure');
    let figTitle = '';
    if (fig) {
      const prev = fig.previousElementSibling;
      if (prev && prev.tagName === 'H3') figTitle = prev.textContent.trim();
    }
    // ⚠ shot.querySelectorAll('img')가 «둘 이상»인 그림이 있다(예: price-import 그림 J —
    // 체크박스 전/후 상태를 <div class="shot"> 두 개로 나눠 한 <figure>에 담는다). 배지는
    // 각 shot의 «직계 자식»만 그 shot 소속이므로 shot 단위로 순회하면 자동으로 맞게 갈린다
    // (figure 단위로 첫 img·첫 shot만 보면 두 번째 shot의 핀을 놓친다 — 2026-08-29 확인자
    // 보고 사례. 이 스크립트는 처음부터 shot 단위라 이 함정에 걸리지 않는다).
    const pins = Array.from(shot.children).filter(c => c.tagName === 'B' && c.classList.contains('pin'));
    out.push({
      fig: figTitle,
      img: {x: ir.x, y: ir.y, w: ir.width, h: ir.height},
      pins: pins.map(p => {
        const r = p.getBoundingClientRect();
        return {num: p.textContent.trim(), x: r.x, y: r.y, w: r.width, h: r.height};
      }),
    });
  });
  return out;
}
"""


def _console_safe(s: str) -> str:
    """콘솔이 인코딩 못 하는 문자를 안전하게 바꾼다 — 크래시 대신 이스케이프로 남긴다.

    ⚠ 여기서 고치는 것은 "정적 로그 문자열에 em-dash를 썼다"가 «아니다» — 이 스크립트의
    로그 문자열 자체는 이미 ASCII다. 문제는 fig 제목이 `docs/manual/screens/*.html`
    원문 <h3> 텍스트를 그대로 읽어온 **동적** 값이라는 점이다(다른 제작자 소유 —
    이 스크립트가 원문을 고치지 않는다). 그 원문에 em-dash(U+2014) 같은 문자가 있으면
    cp949 콘솔에서 print() 자체가 UnicodeEncodeError로 죽는다(2026-08-29 확인자 재현 —
    products.html 그림 E "…일괄 변경 — 행 선택…"이 실제 그 문자를 담고 있다, 실측
    확인: '\\u2014'.encode('cp949')가 실패한다). 이 스크립트가 원문 문자열 «값»을 바꿀
    수는 없으니, print() 직전에만 — 실제 콘솔 인코딩(sys.stdout.encoding)이 못 담는
    문자만 골라 — 이스케이프 표기로 바꾼다. cp949를 가정하지 않는다: UTF-8 콘솔에서는
    그대로 통과한다(encode 성공 시 원문 그대로 반환).
    """
    enc = sys.stdout.encoding or "utf-8"
    try:
        s.encode(enc)
        return s
    except UnicodeEncodeError:
        return s.encode(enc, errors="backslashreplace").decode(enc)


def _sanitize_shots(shots):
    """`page.evaluate(JS)`가 돌려준 fig 제목·핀 번호를 로그에 안전하게 만들어 둔다.

    `analyze()`가 만드는 `boundary`/`overlap` 딕셔너리도, 화면 루프·`_check_print()`
    양쪽의 `log()` 호출부도 전부 이 값을 그대로 이어받는다 — 호출부마다 각자
    `_console_safe()`를 부르게 하면 하나를 빠뜨릴 수 있으므로(CANON.md "한 문단에
    수정이 둘일 때 하나만 적용" 함정과 같은 모양), `page.evaluate(JS)` 직후 딱 한
    곳에서만 적용해 이후 경로 전체가 안전해지게 한다.
    """
    for s in shots:
        s["fig"] = _console_safe(s["fig"])
        for p in s["pins"]:
            p["num"] = _console_safe(p["num"])
    return shots


def analyze(shots, noise=NOISE_PX):
    boundary, overlap, total = [], [], 0
    for s in shots:
        img = s["img"]
        pins = s["pins"]
        total += len(pins)
        for p in pins:
            over = {
                "left": max(0.0, img["x"] - p["x"]),
                "right": max(0.0, (p["x"] + p["w"]) - (img["x"] + img["w"])),
                "top": max(0.0, img["y"] - p["y"]),
                "bottom": max(0.0, (p["y"] + p["h"]) - (img["y"] + img["h"])),
            }
            for side, amt in over.items():
                if amt > noise:
                    boundary.append({"fig": s["fig"], "pin": p["num"], "side": side, "px": round(amt, 2)})
        for i in range(len(pins)):
            for j in range(i + 1, len(pins)):
                a, b = pins[i], pins[j]
                ix = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
                iy = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
                if ix > noise and iy > noise:
                    overlap.append({
                        "fig": s["fig"], "pins": f"{a['num']}x{b['num']}",
                        "w": round(ix, 2), "h": round(iy, 2),
                    })
    return total, boundary, overlap


def discover_slugs() -> list[str]:
    return sorted(p.stem for p in FRAGMENTS_DIR.glob("*.html"))


def _check_print(page, base: str, slug: str):
    """슬러그 하나를 인쇄 미디어(emulate_media="print") · PRINT_WIDTH(703px)에서 잰다.

    화면 검사와 **같은 `analyze()`**를 그대로 쓴다 — 판정 기준(사각형 교차)을 두 곳에
    다시 적지 않는다. 반환값은 화면 루프의 `per_width[w]`와 같은 `(total, boundary,
    overlap)` 튜플, `.manual-doc`이 없으면(설명서 없음) `None`.

    끝나기 전에 `emulate_media("screen")`으로 되돌린다 — 이 함수가 화면 루프 «뒤»에
    슬러그마다 한 번씩 불리므로, 되돌려 놓지 않으면 다음 슬러그의 goto가 print 미디어를
    문 채로 남는다(같은 페이지·세션을 화면·인쇄 양쪽이 순서대로 재사용하기 때문).
    """
    page.emulate_media(media="print")
    page.set_viewport_size({"width": PRINT_WIDTH, "height": PRINT_HEIGHT})
    page.goto(f"{base}/admin2/manual/{slug}", wait_until="networkidle")
    if not page.query_selector(".manual-doc"):
        page.emulate_media(media="screen")
        return None
    page.wait_for_timeout(80)
    shots = _sanitize_shots(page.evaluate(JS))
    result = analyze(shots)
    page.emulate_media(media="screen")
    return result


def main() -> int:
    base = BASE
    slugs = None
    check_screen = True
    check_print = True
    # 신선도(그림 vs 실화면) — 기본 True. `--screen-only`/`--print-only`는 «핀 검사의
    # 폭 선택»만 바꾸는 기존 옵션이라 건드리지 않는다(신선도는 폭 개념이 없다 — 위
    # docstring 참고) — 끄거나 단독으로 돌리려면 별도 옵션을 쓴다.
    check_fresh = True
    fresh_threshold = FRESH_PX_THRESHOLD
    # 신선도 상세(`[건너뜀]`·`[안보임]`·`[LIVE]` 줄)를 보려면 이 옵션이 필요하다.
    # ⚠ 2026-08-30 확인자가 잡은 결함 — 이 분기가 «없어서» 여기서는 상세를 영영 볼 수
    # 없었다. 에러도 경고도 없이 조용히 무시됐고, 이 파일이 자기 docstring에서 「기본
    # 진입점」이라 부르는 곳이라 별도 모듈을 직접 돌려야 한다는 걸 몰라야만 안 걸리는
    # 함정이었다. 핀 검사 쪽은 원래 상세 개념이 없어 이 플래그를 안 본다.
    verbose = False
    for arg in sys.argv[1:]:
        if arg.startswith("--base="):
            base = arg.split("=", 1)[1]
        elif arg.startswith("--slugs="):
            slugs = [s.strip() for s in arg.split("=", 1)[1].split(",") if s.strip()]
        elif arg == "--screen-only":
            check_print = False
        elif arg == "--print-only":
            check_screen = False
        elif arg == "--freshness-only":
            check_screen = False
            check_print = False
        elif arg == "--no-freshness":
            check_fresh = False
        elif arg in ("--verbose", "-v"):
            verbose = True
        elif arg.startswith("--fresh-threshold="):
            fresh_threshold = float(arg.split("=", 1)[1])
    slugs = slugs or discover_slugs()

    screen_violations = 0
    screen_total = 0
    print_violations = 0
    print_total = 0
    fresh_checked = fresh_bad_screens = fresh_bad_elements = 0
    fresh_skip = fresh_live = 0

    with capture_session() as page:
        if check_screen:
            for slug in slugs:
                per_width = {}
                for w in WIDTHS:
                    page.set_viewport_size({"width": w, "height": HEIGHT})
                    page.goto(f"{base}/admin2/manual/{slug}", wait_until="networkidle")
                    if not page.query_selector(".manual-doc"):
                        log(f"[SKIP] {slug} - /admin2/manual/{slug} 에 .manual-doc 없음(설명서 없음)")
                        per_width = None
                        break
                    page.wait_for_timeout(80)
                    shots = _sanitize_shots(page.evaluate(JS))
                    total, b, o = analyze(shots)
                    per_width[w] = (total, b, o)
                if not per_width:
                    continue
                total0 = per_width[WIDTHS[0]][0]
                screen_total += total0
                bad = {w: (b, o) for w, (t, b, o) in per_width.items() if b or o}
                if not bad:
                    log(f"[OK] {slug}  핀 {total0}개  화면 4폭 경계이탈 0 · 겹침 0")
                    continue
                log(f"[FAIL] {slug}  핀 {total0}개  (화면)")
                for w, (b, o) in bad.items():
                    screen_violations += len(b) + len(o)
                    for v in b:
                        log(f"    {w}px [경계] {v['fig']} pin={v['pin']} {v['side']} {v['px']}px")
                    for v in o:
                        log(f"    {w}px [겹침] {v['fig']} pins={v['pins']} {v['w']}x{v['h']}px")

        if check_print:
            # 인쇄 폭 검사(2026-08-29 결함⑤ 후속) — 왜 필요한지는 파일 docstring 참고.
            for slug in slugs:
                result = _check_print(page, base, slug)
                if result is None:
                    log(f"[SKIP] {slug} - print({PRINT_WIDTH}px) 에도 .manual-doc 없음")
                    continue
                total, b, o = result
                print_total += total
                if not (b or o):
                    log(f"[OK] {slug}  핀 {total}개  print({PRINT_WIDTH}px) 경계이탈 0 · 겹침 0")
                    continue
                log(f"[FAIL] {slug}  핀 {total}개  (print {PRINT_WIDTH}px)")
                print_violations += len(b) + len(o)
                for v in b:
                    log(f"    print [경계] {v['fig']} pin={v['pin']} {v['side']} {v['px']}px")
                for v in o:
                    log(f"    print [겹침] {v['fig']} pins={v['pins']} {v['w']}x{v['h']}px")

        if check_fresh:
            # 신선도(그림 vs 실화면) — 판정 로직은 여기 다시 적지 않는다(정의는
            # scripts/manual_check_freshness.py 한 곳). 같은 브라우저 세션(page)을
            # 그대로 넘겨 브라우저를 두 번 띄우지 않는다. 반환 5개(건너뜀·동적 제외
            # 총합 포함) — 그 모듈의 `run_freshness_checks()` docstring 참고.
            (fresh_checked, fresh_bad_screens, fresh_bad_elements,
             fresh_skip, fresh_live) = run_freshness_checks(
                page, base, slugs, threshold=fresh_threshold, verbose=verbose)

    total_violations = screen_violations + print_violations + fresh_bad_elements
    log("")
    if check_screen:
        log(f"화면 4폭 - 핀 {screen_total}개 · 위반 {screen_violations}건")
    if check_print:
        log(f"인쇄(print {PRINT_WIDTH}px) - 핀 {print_total}개 · 위반 {print_violations}건")
    if check_fresh:
        fresh_extras = []
        if fresh_skip:
            fresh_extras.append(f"건너뜀 {fresh_skip}건")
        if fresh_live:
            fresh_extras.append(f"동적 요소 제외 {fresh_live}건")
        fresh_extra_s = f" · {' · '.join(fresh_extras)}" if fresh_extras else ""
        log(f"신선도(그림 vs 실화면, {fresh_threshold}px 문턱) - 화면 {fresh_checked}개 검사 "
            f"· 위반 화면 {fresh_bad_screens}개 · 위반 요소 {fresh_bad_elements}개{fresh_extra_s}")
    log(f"합계 위반 {total_violations}건 (0이면 통과)")
    return 1 if total_violations else 0


if __name__ == "__main__":
    sys.exit(main())
