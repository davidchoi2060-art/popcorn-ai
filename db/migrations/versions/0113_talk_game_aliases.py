# -*- coding: utf-8 -*-
"""팝콘톡 게임명 별칭 — 고객이 쓰는 줄임말 -> `games.name` 정본 값.

■ 왜 표인가 — 0111(talk_genre_aliases)과 같은 이유, **코드에 박지 않는다**
  이 저장소의 규약은 「어휘의 정본은 DB」다. 게임명 별칭만 코드에 박으면
  ① `games` 가 늘어난 날 코드가 옛 어휘로 말하고
  ② 회귀의 「어휘 단일 원천」 검사와 결이 어긋난다.
  운영자가 표에 한 줄 넣으면 **다음 요청부터** 반영되는 자리로 둔다.

■ 실측(2026-09-22) — `api/talk_schema.match_game`(345행)의 실패 지점 둘
  ① "롤" 은 `_norm_name()` 정규화 후 길이 1자라 **길이 검사(②, 2자 미만 컷)에서
     죽는다** — 포함 관계 비교(③)까지 가지도 못한다.
  ② "배그·옵치·던파·로아·마크" 는 길이는 통과하지만 정규화한 `games.name`
     과 **연속 부분문자열 관계가 아니라서** 포함 관계 비교에서 죽는다
     (예: "배그" 는 "배틀그라운드" 의 부분문자열이 아니다 — 자모가 안 이어진다).
  "발로·서든·메이플·디아·FC·오버워치" 는 이미 포함 관계로 맞는다 — 이 표에
  넣지 않는다(중복 경로는 유지보수 부담만 늘린다).

■ 방향과 FK
  `alias`(고객 말) -> `games.name`(games.name 실값, **FK**). 장르 별칭(0111)과
  달리 게임명은 `games.name` 이 `VARCHAR(60) NOT NULL UNIQUE`(0073)라 FK 를
  걸 수 있다 — 지어낸 게임을 가리키는 별칭은 제약이 막아 준다.

■ 씨앗은 여섯 쌍만
  롤/배그/옵치/던파/로아/마크 — 위 실측에서 실패가 확인된 것만 넣는다.
  피파·스타·와우는 후보로 거론됐으나 **가리킬 대상 게임이 `games` 에 실재하는지
  확인되지 않아 넣지 않는다**(지어낸 별칭은 FK 가 막겠지만, 애초에 근거 없는
  씨앗을 심지 않는다). 대상이 생기면 2차 후보로 다시 본다.

■ 소문자 저장(0111과 동일 관례)
  `.lower()` 로 저장한다 — 한글은 대소문자가 없어 영향이 없고, 영문 별칭이
  섞여도 조회 규약을 하나로 유지한다.

Revision ID: 0113
Revises: 0112
"""
from alembic import op
import sqlalchemy as sa

revision = "0113"
down_revision = "0112"
branch_labels = None
depends_on = None


# 별칭 씨앗 — 왼쪽은 고객이 실제로 쓰는 줄임말, 오른쪽은 `games.name` 에
# **실재하는** 값(0073 시드). 실재 여부는 upgrade() 가 대조한다 — 없는 게임을
# 가리키는 행은 넣지 않는다(건너뛴다, 조용히).
_SEED: tuple[tuple[str, str], ...] = (
    ("롤", "리그 오브 레전드"),
    ("배그", "배틀그라운드"),
    ("옵치", "오버워치2"),
    ("던파", "던전앤파이터"),
    ("로아", "로스트아크"),
    ("마크", "마인크래프트"),
)


def upgrade() -> None:
    op.create_table(
        "talk_game_aliases",
        sa.Column("alias", sa.String(40), primary_key=True),
        sa.Column("game_id", sa.Integer,
                   sa.ForeignKey("games.game_id", ondelete="CASCADE"), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.execute(
        "COMMENT ON TABLE talk_game_aliases IS "
        "'고객이 쓰는 게임 줄임말 -> games.name. 팝콘톡 답변 경로(api/talk_schema."
        "match_game)가 읽는다. 방향은 alias(고객 말) -> games.name. "
        "game_id 를 FK 로 걸어 지어낸 게임을 가리키는 별칭을 막는다.'"
    )

    conn = op.get_bind()
    # ★ 실재하는 게임만 넣는다 — 지어낸 이름을 가리키면 FK 위반으로 마이그레이션이
    #   실패하므로, 여기서 미리 걸러 **대상이 없는 별칭은 조용히 건너뛴다.**
    name_to_id = {n: i for i, n in conn.execute(sa.text(
        "SELECT game_id, name FROM games")).all()}
    rows = []
    for alias, name in _SEED:
        gid = name_to_id.get(name)
        if gid is not None:
            rows.append({"a": alias.lower(), "gid": gid})
    if rows:
        conn.execute(sa.text(
            "INSERT INTO talk_game_aliases (alias, game_id) VALUES (:a, :gid)"
            " ON CONFLICT DO NOTHING"), rows)


def downgrade() -> None:
    op.drop_table("talk_game_aliases")
