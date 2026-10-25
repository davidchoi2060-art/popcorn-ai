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
    assert "brand/popcornai-header-logo-final.png" in js and 'width="420" height="153"' in js
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
            assert "core.js?v=20261022-biz2" in t, p.name  # 2026-10-21 하단 회사정보·정책 링크
        if "assets/css/header-ui.css" in t:
            assert "header-ui.css?v=20261025-builder1" in t, p.name


def test_header_ui_finds_brand_with_extra_class():
    """PR #358 회귀: core.js 가 site-brand 에 클래스를 더 붙이자 header-ui.js 의 정확 문자열 매칭이 실패해
    최신 헤더(상시 검색·띠메뉴) 변환이 통째로 빠지고 옛 헤더가 운영에 나갔다. 클래스가 더 붙어도 찾아야 한다."""
    js = (ROOT / "assets" / "js" / "header-ui.js").read_text(encoding="utf-8")
    m = re.search(r"var brand = existing\[0\]\.match\(/(.+?)/\);", js)
    assert m, "brand matcher not found"
    pat = re.compile(m.group(1).replace("\\/", "/"))
    core = (ROOT / "assets" / "js" / "core.js").read_text(encoding="utf-8")
    assert "site-brand site-brand-logo" in core
    for html in ['<a class="site-brand site-brand-logo" href="x" aria-label="y"><img></a>',
                 '<a class="site-brand" href="x"><img><span>팝콘AI</span></a>',
                 '<a class="x site-brand" href="x"><img></a>']:
        assert pat.search(html), html
    assert not pat.search('<a class="site-brand-logo" href="x"><img></a>')


def test_header_logo_final_is_the_approved_original_bytes():
    """2026-10-20 대표 최종 확정 「이게 정말 최종 로고임.. 이 이미지만 바꿔줘」(v2 를 대체) -- 원본 바이트 그대로(재생성·크롭·배경 제거 없음)."""
    img = (BRAND / "popcornai-header-logo-final.png").read_bytes()
    assert len(img) == 204469
    assert hashlib.sha256(img).hexdigest() == "25e86af8131998955cc2bd42b43a56db9de5cd30d86079e849c2562286ceff40"
    prov = json.loads((BRAND / "popcornai-header-logo-final.provenance.json").read_text(encoding="utf-8"))
    assert prov["sha256"] == hashlib.sha256(img).hexdigest()
