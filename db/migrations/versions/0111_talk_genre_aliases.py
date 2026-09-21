# -*- coding: utf-8 -*-
"""팝콘톡 장르 별칭 — 고객이 쓰는 말 -> `games.genre` 정본 값.

사장님이 직접 보신 증상의 한 조각: 고객이 「슈팅게임」이라고 말했는데 우리 DB 의
장르 값은 `FPS` · `협동슈팅` · `익스트랙션FPS` · `액션TPS` 라, 글자로는 한 곳도
안 맞았다. 그래서 「슈팅게임」이 **장르로 인식되지 않았고**, 좁혀짐 판정이 `wide` 에
머물러 그 장르의 우리 게임을 꺼내 오지 못했다.

■ 왜 표인가 — **코드에 박지 않는다**
  이 저장소의 규약은 「어휘의 정본은 DB」다(`usage_floors` · `spec_tiers` ·
  `game_load_grades` 전부 표에서 온다). 장르 별칭만 코드에 박으면
  ① `games.genre` 가 늘어난 날 코드가 옛 어휘로 말하고
  ② 회귀의 「어휘 단일 원천」 검사와 결이 어긋난다.
  운영자가 표에 한 줄 넣으면 **다음 요청부터** 반영되는 자리로 둔다.

■ 방향
  `alias`(고객 말) -> `genre`(games.genre 실값). 한 별칭이 여러 장르를 가리킨다
  (\"슈팅\" -> FPS · 협동슈팅 · 익스트랙션FPS · 액션TPS). 그래서 PK 가 (alias, genre) 다.

■ genre 값을 FK 로 걸지 않는다
  `games.genre` 는 자유 문자열 컬럼이고 장르 정본 표가 따로 없다(실측 2026-09-21:
  DISTINCT 33종). 여기서 FK 를 걸려면 장르 표를 새로 세워야 하는데, 그것은 이
  작업의 범위가 아니다(게임 분류 체계는 다른 담당의 자리다). 대신 **씨앗을 넣을 때
  실제 `games.genre` 값과 대조**하고, 안 맞는 행은 넣지 않는다 — 지어낸 장르로
  조회하면 언제나 0건이 나와 「자료 없음」이 조용히 늘어난다.
"""
from alembic import op
import sqlalchemy as sa

revision = "0111"
down_revision = "0110"
branch_labels = None
depends_on = None


# 별칭 씨앗 — 왼쪽은 고객이 실제로 쓰는 말, 오른쪽은 `games.genre` 에 **실재하는** 값.
# 실재 여부는 upgrade() 가 대조한다(없는 장르를 가리키는 행은 넣지 않는다).
_SEED: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("슈팅", ("FPS", "협동슈팅", "익스트랙션FPS", "액션TPS", "배틀로얄")),
    ("슈팅게임", ("FPS", "협동슈팅", "익스트랙션FPS", "액션TPS", "배틀로얄")),
    ("fps", ("FPS", "익스트랙션FPS")),
    ("총게임", ("FPS", "협동슈팅", "액션TPS")),
    ("총쏘는", ("FPS", "협동슈팅", "액션TPS")),
    ("배틀로얄", ("배틀로얄",)),
    ("배그류", ("배틀로얄",)),
    ("롤같은", ("MOBA",)),
    ("aos", ("MOBA",)),
    ("moba", ("MOBA",)),
    ("rpg", ("RPG", "액션RPG", "오픈월드RPG", "MMORPG")),
    ("알피지", ("RPG", "액션RPG", "오픈월드RPG", "MMORPG")),
    ("역할수행", ("RPG", "액션RPG", "오픈월드RPG")),
    ("엠엠오", ("MMORPG", "서바이벌MMO")),
    ("mmo", ("MMORPG", "서바이벌MMO")),
    ("온라인게임", ("MMORPG", "서바이벌MMO")),
    ("액션", ("액션", "액션RPG", "오픈월드액션", "액션TPS")),
    ("오픈월드", ("오픈월드액션", "오픈월드RPG", "샌드박스")),
    ("호러", ("호러", "협동호러", "비대칭호러")),
    ("공포", ("호러", "협동호러", "비대칭호러")),
    ("무서운", ("호러", "협동호러", "비대칭호러")),
    ("생존", ("서바이벌", "서바이벌MMO", "배틀로얄")),
    ("서바이벌", ("서바이벌", "서바이벌MMO")),
    ("레이싱", ("레이싱",)),
    ("자동차", ("레이싱",)),
    ("스포츠", ("스포츠",)),
    ("축구", ("스포츠",)),
    ("격투", ("대전격투",)),
    ("전략", ("전략시뮬", "RTS", "도시건설")),
    ("rts", ("RTS",)),
    ("시뮬", ("시뮬레이션", "전략시뮬", "경영시뮬", "공장시뮬", "농장시뮬", "라이프시뮬")),
    ("시뮬레이션", ("시뮬레이션", "전략시뮬", "경영시뮬", "공장시뮬", "농장시뮬")),
    ("경영", ("경영시뮬", "도시건설")),
    ("건설", ("도시건설", "공장시뮬")),
    ("농장", ("농장시뮬",)),
    ("인디", ("인디(통칭)",)),
    ("협동", ("협동슈팅", "협동호러", "협동등반", "협동어드벤처")),
    ("코옵", ("협동슈팅", "협동호러", "협동등반", "협동어드벤처")),
    ("샌드박스", ("샌드박스",)),
    ("메트로배니아", ("메트로배니아",)),
    ("어드벤처", ("협동어드벤처", "메트로배니아")),
)


def upgrade() -> None:
    op.create_table(
        "talk_genre_aliases",
        sa.Column("alias", sa.String(40), primary_key=True),
        sa.Column("genre", sa.String(40), primary_key=True),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.execute(
        "COMMENT ON TABLE talk_genre_aliases IS "
        "'고객이 쓰는 장르 말 -> games.genre 실값. 팝콘톡 답변 경로(api/talk_answer."
        "match_genres)가 읽는다. 한 별칭이 여러 장르를 가리키므로 PK 는 (alias, genre). "
        "alias 는 소문자로 저장하고 조회 시에도 소문자로 맞춘다(0110).'"
    )

    conn = op.get_bind()
    # ★ 실재하는 장르만 넣는다 — 지어낸 장르로 조회하면 언제나 0건이고,
    #   그 사실이 「자료 없음」으로 조용히 묻힌다.
    known = {g for (g,) in conn.execute(sa.text(
        "SELECT DISTINCT genre FROM games WHERE genre IS NOT NULL")).all() if g}
    rows = []
    for alias, genres in _SEED:
        for g in genres:
            if g in known:
                rows.append({"a": alias.lower(), "g": g})
    if rows:
        conn.execute(sa.text(
            "INSERT INTO talk_genre_aliases (alias, genre) VALUES (:a, :g)"
            " ON CONFLICT DO NOTHING"), rows)


def downgrade() -> None:
    op.drop_table("talk_genre_aliases")
