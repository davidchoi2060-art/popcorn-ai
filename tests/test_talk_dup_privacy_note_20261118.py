"""AI 답의 개인정보 주의 문장 중복 제거 -- 2026-11-18 개발 서버 실측, 사장님 승인 「넣어」.

서버 고정 안내(NOTE_PERSONAL)가 붙는 답에서 AI 가 스스로 쓴 같은 뜻 문장을 걷는다.
상품·견적 문장은 건드리지 않는다.
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://ci:ci@127.0.0.1:1/ci")

from api import talk_exceptions as TE  # noqa: E402

LF = chr(10)


def test_drops_the_ai_sentence_that_repeats_the_server_note():
    text = "골드 [12400F/16G/256GB/RTX3050] 1,194,500원을 추천드려요. 주민번호나 카드번호는 상담창에 남기지 않는 것이 좋습니다."
    assert TE.drop_own_privacy_warning(text) == "골드 [12400F/16G/256GB/RTX3050] 1,194,500원을 추천드려요."


def test_drops_across_paragraphs_and_keeps_the_rest():
    text = "이 구성은 게임에 충분해요." + LF * 2 + "개인정보는 적지 마세요." + LF * 2 + "궁금한 점 있으면 물어봐 주세요."
    out = TE.drop_own_privacy_warning(text)
    assert "개인정보" not in out
    assert out.startswith("이 구성은 게임에 충분해요.") and out.endswith("궁금한 점 있으면 물어봐 주세요.")


def test_keeps_product_and_unrelated_sentences():
    for text in ("카드 결제도 가능합니다. 비밀번호 설정은 윈도우에서 하세요.",
                 "RTX 5090 은 1000W 파워가 필요해요.",
                 "DDR5-5600 32GB 를 권해요. 1,644,300원입니다."):
        assert TE.drop_own_privacy_warning(text) == text


def test_never_returns_an_empty_answer():
    assert TE.drop_own_privacy_warning("주민번호는 적지 마세요.") == "주민번호는 적지 마세요."
    assert TE.drop_own_privacy_warning("") == ""


def test_personal_info_path_ends_with_one_server_note():
    src = open(TE.__file__, encoding="utf-8").read()
    assert "_add(drop_own_privacy_warning(out), NOTE_PERSONAL" in src


def test_agent_path_strips_when_notes_are_shown():
    from pathlib import Path
    src = (Path(TE.__file__).parent / "talk_agent.py").read_text(encoding="utf-8")
    assert "clean = TE.drop_own_privacy_warning(clean)" in src
