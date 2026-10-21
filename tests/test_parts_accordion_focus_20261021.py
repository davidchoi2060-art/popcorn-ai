"""상세 부품 아코디언 — 펼친 행으로 화면을 옮긴다 (2026-10-21 사장님 「해당 아코디언으로 포커스가 이동되도록」).

열린 행(머리+펼친 내용)이 화면 아래로 잘리면 그만큼만 올리고, 머리 행이 화면 위로 나가지 않게 한다.
위쪽 행이 닫혀 줄어든 높이 보정(2026-10-20)은 그대로 먼저 한다. 실제 화면 전후 수치는 PR 근거 자료에 있다.
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1] / "mockups/mvp4"


def part_handler():
    s = (ROOT / "assets/js/configuration-concept.js").read_text(encoding="utf-8")
    return s[s.index("if (!P.cfPartSingleOpen)"):s.index("P.configurationConceptV12 =")]


def test_open_row_is_revealed_without_pushing_header_off_screen():
    h = part_handler()
    shift, reveal = h.index("window.scrollBy({ top: shift"), h.index("window.scrollBy({ top: reveal")
    assert shift < reveal                                                   # 닫힘 보정 다음에 펼침 노출
    assert "rect.bottom + gap - view" in h and "Math.max(0, rect.top - gap)" in h   # 잘린 만큼, 머리는 위 여백까지만
    assert "if (rect.top < gap) reveal = rect.top - gap" in h


def test_focus_moves_to_the_opened_row_and_respects_reduced_motion():
    h = part_handler()
    assert "summary.focus({ preventScroll: true })" in h
    assert "prefers-reduced-motion: reduce" in h and "'smooth'" in h
    assert "scrollIntoView" not in h and "pushState" not in h and "location.hash" not in h


def test_pages_load_new_version():
    for page in ("index.html", "review-flows.html"):
        assert "configuration-concept.js?v=20261021-cb2" in (ROOT / page).read_text(encoding="utf-8")
