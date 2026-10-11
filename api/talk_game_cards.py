"""게임 카드 자료 -- 2차 대화 중심 상담 화면의 바닥(2026-10-11).

사장님이 2차(대화 중심 화면 개편)를 «진행»으로 정했고, 코덱스 기획(1816)이 「말풍선 아래
실제 게임 카드 2~3개」를 제안했다. 화면은 기획이 온 뒤에 만든다. 여기는 그 카드에 넣을
«우리가 실제로 아는 것»만 돌려주는 읽기 전용 조회다.

■ 지어내지 않는다
  - 값은 `api/talk_answer` 의 게임 사실(GameFacts -- games · 인기 스냅샷 · 부하 등급 ·
    검수 통과 문구)에서만 온다. 없는 칸은 null 이다.
  - 소개 문구는 **검수를 통과한 것만**(`api/game_copy` 게이트 -- talk_answer 가 이미 거친다).
  - 인기는 **날짜와 출처를 함께** 준다. 출처는 고객용 이름이다(내부 키를 내보내지 않는다).
  - 게임 그림은 아직 원천이 없다(games 에 그림 칸이 없다 -- 2026-10-11 조사). `image.state`
    가 "none" 이면 화면은 그림 자리를 비운다. 그림을 지어내거나 다른 상품 사진을 쓰지 않는다.
  - 묶음 항목(`is_bucket`)과 운영에서 내린 게임(`is_active = false`)은 카드로 내지 않는다.

■ 부하 등급 말
  카드에는 `load.word`(가벼운 편 · 보통 · 무거운 편)를 싣는다. 말풍선에 서버가 꼬리를 붙이던
  방식은 사장님 「기존 AI와 대화하듯이」로 걷었지만(#136), 카드는 자료 칸이라 화면이 쓸지
  고른다. 근거는 game_grade_resolution_tiers 1080p 요구 티어(0091):
    L(경량 캐주얼) -> 가벼운 편 · E·A(1080p T1) -> 보통 · B·C·S(T2 이상) -> 무거운 편
"""
from fastapi import APIRouter, Query
from sqlalchemy import bindparam, text

from .db import engine
from . import talk_answer as TA
from . import talk_schema as TS

router = APIRouter(prefix="/api/talk", tags=["talk"])

MAX_CARDS = 5
LOAD_WORDS = {"L": "가벼운 편", "E": "보통", "A": "보통",
              "B": "무거운 편", "C": "무거운 편", "S": "무거운 편"}


def popularity(f: "TA.GameFacts") -> dict | None:
    """인기 한 칸 -- 날짜가 없으면 내지 않는다(언제 값인지 모르는 순위는 틀린 값이다)."""
    if not f.snapshot_date:
        return None
    label = TA.public_source_label(f.snapshot_source)
    if f.pcbang_rank:
        return {"kind": "pcbang", "rank": f.pcbang_rank, "share_pct": f.pcbang_share,
                "as_of": f.snapshot_date, "source": label, "line": f.popularity_line()}
    if f.steam_ccu:
        return {"kind": "steam", "ccu": int(f.steam_ccu),
                "as_of": f.snapshot_date, "source": label, "line": f.popularity_line()}
    return None


def card(f: "TA.GameFacts") -> dict:
    """GameFacts -> 카드 한 장. 고객에게 나가도 되는 칸만 담는다."""
    year = None
    if f.release_date and str(f.release_date)[:4].isdigit():
        year = int(str(f.release_date)[:4])
    word = LOAD_WORDS.get(f.grade or "")
    return {
        "name": f.name,
        "genre": f.genre,
        "vendor": f.vendor,
        "release_year": year,
        "summary": (f.copy_spec or "").strip() or None,
        "load": {"grade": f.grade, "word": word} if word else None,
        "popularity": popularity(f),
        "image": {"state": "none", "url": None},
    }


def _hidden(conn, names: list[str]) -> set[str]:
    """카드로 내지 않을 이름 -- 묶음 항목·운영에서 내린 게임."""
    if not names:
        return set()
    rows = conn.execute(text(
        "SELECT name FROM games WHERE name IN :names"
        "   AND (is_bucket IS TRUE OR is_active IS FALSE)"
    ).bindparams(bindparam("names", expanding=True)), {"names": names}).all()
    return {r[0] for r in rows}


def build_cards(conn, *, names: list[str] | None = None, genre: str | None = None,
                limit: int = 3) -> list[dict]:
    """이름이 있으면 그 게임들(말한 순서), 없으면 인기 순 -- 카드 목록."""
    limit = max(1, min(int(limit or 3), MAX_CARDS))
    vocab = TS.load_vocab(conn)
    if names:
        facts = TA.load_game_facts(conn, [n for n in names if n][:MAX_CARDS * 2], vocab)
        order = []
        for n in names:
            m = TS.match_game(n, vocab)
            if m and m not in order:
                order.append(m)
        facts.sort(key=lambda f: order.index(f.name) if f.name in order else len(order))
    else:
        top = TA.popular_games(conn, [genre] if genre else None, limit=limit * 2)
        ranked = [f.name for f in top]
        facts = TA.load_game_facts(conn, ranked, vocab) if ranked else []
        facts.sort(key=lambda f: ranked.index(f.name) if f.name in ranked else len(ranked))
    hidden = _hidden(conn, [f.name for f in facts])
    return [card(f) for f in facts if f.name not in hidden][:limit]


@router.get("/game-cards")
def game_cards(names: str | None = Query(None, max_length=300),
               genre: str | None = Query(None, max_length=30),
               limit: int = Query(3, ge=1, le=MAX_CARDS)):
    """게임 카드 자료(읽기 전용).

    names  쉼표로 나눈 게임 이름(별칭 가능 -- talk_schema.match_game). 목록 밖 이름은 빠진다.
    genre  names 가 없을 때 인기 게임을 그 장르로 좁힌다(정본 games.genre).
    응답   {ok, cards[{name, genre, vendor, release_year, summary, load{grade,word}|null,
                     popularity{kind, rank|ccu, share_pct?, as_of, source, line}|null,
                     image{state:"none", url:null}}], basis:"names"|"popular"}
    """
    wanted = [n.strip() for n in (names or "").split(",") if n.strip()]
    with engine.connect() as conn:
        cards = build_cards(conn, names=wanted or None, genre=(genre or "").strip() or None,
                            limit=limit)
    return {"ok": True, "cards": cards, "basis": "names" if wanted else "popular"}
