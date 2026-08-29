# -*- coding: utf-8 -*-
"""운영자 매뉴얼 — 핀(.pin 배지) 좌표 자동 검사 (2026-08-29 신설).

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

사용법(서버를 먼저 띄우고, --base로 «그 포트»를 가리킨다 — 기본값은 8000, 이 검사는
읽기 전용 GET만 나가므로 사장님 서버에 그대로 돌려도 안전하다):

    .venv/Scripts/python scripts/manual_check_pins.py
    .venv/Scripts/python scripts/manual_check_pins.py --base=http://127.0.0.1:8002
    .venv/Scripts/python scripts/manual_check_pins.py --slugs=catalog-import,margin-policy

종료 코드 0 = 전 폭·전 화면 위반 0건. 0이 아니면 위반이 있다(회귀·CI에서 그대로 쓸 수 있다).

대상 화면 목록은 `api/admin_ui_manual.py`의 `MANUAL_SCREENS`를 다시 읽지 않는다(그 파일은
이 작업의 담당 밖이라 import하지 않는다 — 순환 의존·부팅 부작용을 피한다). 대신
`docs/manual/screens/*.html` 파일명 자체가 슬러그다(그 딕셔너리의 `fragment` 값이 전부
`{slug}.html`이었다 — 2026-08-29 전수 확인).
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from manual_capture_common import BASE, capture_session, log  # noqa: E402

FRAGMENTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "docs" / "manual" / "screens"
WIDTHS = [1680, 1192, 768, 480]
HEIGHT = 1400  # 실측(2026-08-29): 이 페이지는 뷰포트 높이가 바뀌어도 배지·그림 렌더 크기에
# 영향이 없다(admin2 셸이 오버레이 스크롤바를 쓴다 — 스크롤이 가로폭을 잠식하지 않는다).
# 값 자체는 스크롤 걱정 없이 넉넉히만 잡으면 된다.

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


def main() -> int:
    base = BASE
    slugs = None
    for arg in sys.argv[1:]:
        if arg.startswith("--base="):
            base = arg.split("=", 1)[1]
        elif arg.startswith("--slugs="):
            slugs = [s.strip() for s in arg.split("=", 1)[1].split(",") if s.strip()]
    slugs = slugs or discover_slugs()

    violations = 0
    grand_total = 0
    with capture_session() as page:
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
                shots = page.evaluate(JS)
                total, b, o = analyze(shots)
                per_width[w] = (total, b, o)
            if not per_width:
                continue
            total0 = per_width[WIDTHS[0]][0]
            grand_total += total0
            bad = {w: (b, o) for w, (t, b, o) in per_width.items() if b or o}
            if not bad:
                log(f"[OK] {slug}  핀 {total0}개  전 폭 경계이탈 0 · 겹침 0")
                continue
            log(f"[FAIL] {slug}  핀 {total0}개")
            for w, (b, o) in bad.items():
                violations += len(b) + len(o)
                for v in b:
                    log(f"    {w}px [경계] {v['fig']} pin={v['pin']} {v['side']} {v['px']}px")
                for v in o:
                    log(f"    {w}px [겹침] {v['fig']} pins={v['pins']} {v['w']}x{v['h']}px")

    log(f"\n총 핀 {grand_total}개 · 위반 {violations}건 (0이면 통과)")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
