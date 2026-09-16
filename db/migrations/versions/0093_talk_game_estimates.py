# -*- coding: utf-8 -*-
"""talk_game_estimates — 팝콘톡 AI 가 「목록 밖 게임」의 부하 등급을 추정한 기록.

■ 왜 필요한가 — 2026-09-16 사장님 확정 정책 ②(docs/design/talk-grid-guide-redesign-
  2026-09-16.md §6): 우리 `games`·`game_grade_assignments` 목록에 없는 게임을 고객이
  말하면, AI 가 game_load_grades 설명으로 등급을 추정하고(grade_src="ai_estimate")
  서버는 그 등급으로 **바로 카드를 낸다**(화면에 「AI 추정」 배지). 추정을 흘려보내지
  않고 이 표에 모아 두면 사람이 나중에 확정해 `games`·`game_grade_assignments` 에
  편입할 수 있다(관리자 화면은 §11 미정 — 지금은 쌓이기만 한다).

■ 언제 한 행이 생기나 — `POST /api/grid/recommend`(api/grid_public.py)가
  state.game.grade_src == "ai_estimate" 인 상태로 게임 카드를 **낸 시점**에 한 행.
  INSERT 실패는 카드 응답을 버리지 않고 서버 로그로만 남긴다(api/llm.py 의
  cost_logged 판단과 같은 결 — 이미 낸 답을 기록 실패 때문에 버리지 않는다).

■ 원장 규약 — 삭제하지 않는다. 사람이 확정하면 `resolved_game_id`(→games) +
  `resolved_at` 을 채우는 상태 전이로 편입을 표시한다. 미확정 행만 빠르게 찾도록
  `resolved_game_id IS NULL` 부분 인덱스를 둔다.

■ 컬럼
  game_name_raw   고객이 말한 게임명 원문 중 대표 하나(state.game.names[0]). NOT NULL —
                  이름 없이 "대작 다"(names 빈 배열)로 추정한 경우엔 빈 문자열 '' 로
                  넣는다(NULL 이 아니라 "이름을 말하지 않았다"는 사실 자체가 값이다).
  names_all       state.game.names 전체(jsonb) — 원문을 잃지 않는다.
  grade           추정 등급. FK → game_load_grades(grade) — 어휘 밖 등급은 DB 가 막는다.
  evidence        AI 판단 근거 문장(있으면). grid_public 은 parse 응답의 evidence 를 받지
                  않으므로 지금은 NULL 로 들어간다 — 화면이 넘겨주는 날 채워진다.
  visitor_key     고객 식별(있으면). 세션·원장을 쓰지 않는 grid_public 이라 지금은 NULL.

Revision ID: 0093
Revises: 0092
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0093"
down_revision = "0092"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "talk_game_estimates",
        sa.Column("estimate_id", sa.Integer, primary_key=True),
        sa.Column("game_name_raw", sa.Text, nullable=False),
        sa.Column("names_all", postgresql.JSONB, nullable=True),
        sa.Column("grade", sa.Text, sa.ForeignKey("game_load_grades.grade"), nullable=False),
        sa.Column("evidence", sa.Text, nullable=True),
        sa.Column("visitor_key", sa.Text, nullable=True),
        sa.Column("resolved_game_id", sa.Integer, sa.ForeignKey("games.game_id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_talk_game_estimates_game_name_raw", "talk_game_estimates",
                    ["game_name_raw"])
    op.create_index(
        "ix_talk_game_estimates_unresolved", "talk_game_estimates",
        ["resolved_game_id"],
        postgresql_where=sa.text("resolved_game_id IS NULL"),
    )
    op.execute(
        "COMMENT ON TABLE talk_game_estimates IS "
        "'팝콘톡 AI 가 목록 밖 게임의 부하 등급을 추정한 기록(원장, 삭제 없음). "
        "사람이 확정하면 resolved_game_id/resolved_at 으로 편입 표시 — 설계 "
        "talk-grid-guide-redesign-2026-09-16 §6 ②'"
    )


def downgrade() -> None:
    op.drop_index("ix_talk_game_estimates_unresolved", table_name="talk_game_estimates")
    op.drop_index("ix_talk_game_estimates_game_name_raw", table_name="talk_game_estimates")
    op.drop_table("talk_game_estimates")
