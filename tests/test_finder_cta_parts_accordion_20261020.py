"""2026-10-20 승인 「AI 찾기 CTA 3번 + 움직이는 말풍선」 · 「부품 목록 2/3 높이 + 누른 항목만 여는 아코디언」.

브라우저 실측(3폭 · 말풍선 위상 · reduced-motion · 단일 열림 · 스크롤 맥락)은 PR 근거 폴더에 있다.
여기서는 소스가 승인 범위를 벗어나지 않는지만 고정한다.
"""
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MVP4 = ROOT / "mockups/mvp4"
ASSETS = {  # 승인 ZIP manifest 와 같은 원본 바이트
    "pc-ribbon.png": "fa4d98072ea9ff776f3ec51696018f80f0427b3198abf8df189825ab280bec25",
    "bubble-purple.png": "a609a4933ad7bf93b818060f3bfee78db7b3faef90e5a7e67e254cd3ef5d9494",
    "bubble-white.png": "a999547ae2b1f8acb815b51f0fb121e2faca207b57520557b3307efd23eba2d3",
}


def read(rel):
    return (MVP4 / rel).read_text(encoding="utf-8")


def test_finder_assets_are_the_approved_bytes():
    for name, sha in ASSETS.items():
        assert hashlib.sha256((MVP4 / "assets/images/finder-cta" / name).read_bytes()).hexdigest() == sha, name


def test_finder_cta_is_one_same_tab_link_without_nesting():
    js = read("assets/js/home-carousel.js")
    block = js[js.index("function finder()"):js.index("function mount()")]
    assert block.count("<a ") == 1 and "target=" not in block          # 링크 하나 · 같은 탭
    assert "<section class=\"hc-chat hc-finder\"" in block              # 바깥은 링크가 아닌 영역
    assert "P.designHref('chat','welcome')" in block
    assert "aria-hidden=\"true\"" in block                              # 장식 그림
    assert "'<a class=\"hc-chat\"" not in js                            # 옛 작은 링크는 없다


def test_finder_css_is_scoped_and_reduced_motion_stops():
    css = read("assets/css/home-carousel.css")
    part = css[css.index("approved AI finder CTA"):]
    for sel in re.findall(r"(?m)^([^@{}\n][^{}\n]*)\{", part):
        for one in sel.split(","):
            one = one.strip()
            if not one or one.endswith("%") or one in ("from", "to"):
                continue
            assert "hc-finder" in one, one                                 # 전역 body/main/h1/h2/button 없음
    assert "animation:hc-finder-pop-rise 6s infinite both" in part and "animation-delay:-3s" in part
    assert re.search(r"prefers-reduced-motion:reduce\)\{\.hc-finder-bubble\{animation:none", part)


def test_parts_rows_are_compact_and_open_one_at_a_time():
    css = read("assets/css/configuration-concept.css")
    assert ".cf-part summary{min-height:60px;padding-top:9px;padding-bottom:9px}" in css
    js = read("assets/js/configuration-concept.js")
    assert "'<details class=\"cf-part\"><summary>" in js                 # 처음엔 모두 닫힘(open 없음)
    assert "details.cf-part[open]" in js and "other.open = false" in js
    assert "pushState" not in js and "location.hash" not in js


def test_pages_load_new_versions():
    for page in ("index.html", "review-flows.html"):
        t = read(page)
        for a in ("home-carousel.css?v=20261020-edge1", "home-carousel.js?v=20261020-edge1",
                  "configuration-concept.css?v=20261020-acc1", "configuration-concept.js?v=20261020-buy1",
                  "core.js?v=20261020-logo3", "header-ui.js?v=20261020-logo2"):
            assert a in t, (page, a)
