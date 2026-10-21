"""쓰던 PC 업그레이드 질문엔 새 PC 카드를 붙이지 않는다 (2026-10-21 외부 수정 요청서 2차 N1)."""
from api import talk_pc_advice as PA
from api import talk_tools as TT

UPGRADE = "지금 i5-9400F에 GTX 1660 쓰는데 그래픽카드만 RTX 5070으로 바꾸면 될까요? 파워는 500W예요."


def test_upgrade_only_detects_current_pc_swap():
    assert PA.upgrade_only(UPGRADE)
    assert PA.upgrade_only("쓰던 컴퓨터가 너무 느려요 램만 늘리면 될까요")


def test_not_upgrade_when_new_pc_wanted():
    assert not PA.upgrade_only("지금 쓰는 PC가 느려서 새 PC 추천해 주세요")
    assert not PA.upgrade_only("100만원 게임용 PC 견적 보여줘")
    assert not PA.upgrade_only("")


def test_find_pcs_returns_no_cards_for_upgrade():
    book = TT.FactBook(request_text=UPGRADE)
    r = TT.find_pcs({"usages": [], "games": [], "prefs": []}, book)
    assert r["status"] == "upgrade_only"
    assert not book.found and not book.shown


def test_psu_line_still_read():
    assert PA.psu_question(UPGRADE) == ("RTX 5070", 500)


def test_new_pc_search_still_finds():
    assert not PA.upgrade_only("지금 PC는 GTX1060인데 느려요. 기존 컴퓨터는 램 8GB라서 답답해요. 게임용 RTX 4060 PC 찾아요.")
