"""지금 가진 PC 설명은 첫 마디만이 아니라 전부 조건에서 뺀다(2026-10-12 카드 검수 · 개발 서버 재현).

쉼표로 늘어놓은 사양(「지금 PC는 i5-9400F, GTX1660, 램 16GB예요」)과 바로 다음 문장의 사양 나열이
「말씀하신 GTX 1660 · 메모리 16GB 조건」으로 읽혔다. 「~로 바꾸고 싶어요」처럼 원하는 사양은 남긴다.
"""
from types import SimpleNamespace

from api.talk_rules import drop_current_pc, unsupported_conditions


def _state():
    return SimpleNamespace(prefs=[], budget=None, purpose=None, game=None)


def _conds(text):
    return unsupported_conditions(text, _state(), _all=True)


def test_comma_list_of_current_specs_is_not_a_condition():
    text = "지금 PC는 i5-9400F, GTX1660, 램 16GB예요. 150만원으로 추천해 주세요."
    assert drop_current_pc(text).strip() == "150만원으로 추천해 주세요."


def test_spec_only_sentence_after_current_pc_is_not_a_condition():
    text = "지금 쓰는 PC가 너무 느려요. i5-9400F, GTX1660, 램 16GB예요. 150만원으로 추천해 주세요."
    out = drop_current_pc(text)
    assert "1660" not in out and "16GB" not in out
    assert "150만원" in out


def test_desired_spec_after_current_specs_is_kept():
    text = "지금 PC는 i5-9400F, GTX1660, 램 16GB예요. 램 32GB로 바꾸고 싶어요."
    out = drop_current_pc(text)
    assert "1660" not in out and "16GB" not in out
    assert "32GB로 바꾸고 싶어요" in out
    conds = _conds(text)
    assert "메모리 32GB" in conds
    assert not any("1660" in c for c in conds)


def test_wanted_part_in_the_comma_list_is_kept():
    out = drop_current_pc("지금 PC는 GTX1060, RTX4070 넣고 싶어요")
    assert "1060" not in out and "RTX4070 넣고 싶어요" in out


def test_current_spec_ending_without_period_is_dropped():
    out = drop_current_pc("지금 PC는 GTX1060이에요 RTX4070 넣고 싶어요")
    assert "1060" not in out and "RTX4070" in out


def test_part_to_add_to_current_pc_is_kept():
    text = "지금 쓰는 컴퓨터에 RTX 4070을 달고 싶어요."
    assert drop_current_pc(text) == text


def test_every_current_pc_mention_is_dropped():
    text = "지금 PC는 GTX1060인데 느려요. 기존 컴퓨터는 램 8GB라서 답답해요. 게임용 RTX 4060 PC 찾아요."
    conds = _conds(text)
    assert not any("1060" in c or "8GB" in c for c in conds)
    assert any("4060" in c for c in conds)


def test_text_without_current_pc_is_unchanged():
    text = "배그용 RTX 4060 PC 150만원, 램 32GB"
    assert drop_current_pc(text) == text
