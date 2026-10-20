"""2026-10-20 대표 승인 헤더 로고 -- 헤더만 바꾸고 푸터·파비콘·logo.png 는 그대로."""
import hashlib, json, pathlib, re

ROOT = pathlib.Path(__file__).resolve().parents[1] / "mockups" / "mvp4"
BRAND = ROOT / "assets" / "images" / "brand"


def test_master_is_untouched_copy():
    prov = json.loads((BRAND / "popcornai-header-logo.provenance.json").read_text(encoding="utf-8"))
    master = (BRAND / "popcornai-header-logo-approved.png").read_bytes()
    assert hashlib.sha256(master).hexdigest() == "67a588ee7cb9ed612168b65cf7396b07e849d7582501de62c34a2cf98823fa51"
    assert len(master) == 664684
    assert hashlib.sha256((BRAND / "popcornai-header-logo.png").read_bytes()).hexdigest() == prov["sha256"]


def test_header_uses_logo_footer_keeps_old():
    js = (ROOT / "assets" / "js" / "core.js").read_text(encoding="utf-8")
    assert "brand('header')" in js
    assert "brand/popcornai-header-logo.png" in js and 'width="420" height="153"' in js
    assert 'aria-label="팝콘AI 처음 화면"' in js
    # 푸터 쪽 brand() 는 logo.png + 「팝콘AI」 글자를 유지한다
    assert "PAI.image('logo.png')" in js and "<span>팝콘AI</span>" in js


def test_css_keeps_ratio():
    css = (ROOT / "assets" / "css" / "header-ui.css").read_text(encoding="utf-8")
    assert "aspect-ratio:420/153" in css and "object-fit:contain" in css and "width:auto" in css


def test_pages_bumped():
    for p in ROOT.glob("*.html"):
        t = p.read_text(encoding="utf-8")
        if "assets/js/core.js" in t:
            assert "core.js?v=20261020-logo1" in t, p.name
        if "assets/css/header-ui.css" in t:
            assert "header-ui.css?v=20261020-logo1" in t, p.name
