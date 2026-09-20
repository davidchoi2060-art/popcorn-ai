# -*- coding: utf-8 -*-
"""0103: 고객용 게임 상세설명(game_customer_copy) + 기계 등급 제안(game_grade_suggestions)

사장님 지시(2026-09-19): "게임은 고객들이 가장 많이 물어보니까 상세하게 상세설명을
DB에 달아놓아야 하지 않을까?"

조사 산출물: D:/Hermes-Workspace/game_customer_copy.json (86종 전수) ·
             D:/Hermes-Workspace/game_customer_copy.md (샘플·등급제안표·스키마 제안)

■ 왜 games 에 컬럼을 붙이지 않고 표를 따로 두는가 (조사자 권고, 수용)

  games 는 지금 56컬럼이고 그 대부분은 **게임사 공지에서 받아 적은 사실**이다
  (min_gpu · rec_vram_gb · rec_spec_note_raw ...). 갱신 주기는 게임사 공지에 묶인다.

  반면 이 네 문장(spec_summary_ko · why_this_pc · upgrade_hint · caution)은
  **우리가 쓴 글**이다. 고객이 읽고, 우리가 검수하고, 말투가 어색하면 우리가 고친다.
  갱신 주기가 게임사 공지와 전혀 다르게 돈다. 한 표에 섞으면
    - 사양 재조사 로더가 문구를 덮어쓰거나(0097 때 실제로 48개 필드가 그렇게 덮였다)
    - 문구 검수 한 번에 games 의 updated 시각이 통째로 움직여 사양 갱신 이력이 흐려진다.
  그래서 나눈다. 1:1 이지만 «출처가 다르고 검수 주기가 다른 것»은 나누는 편이 맞다.

  reviewed_by 를 여기 두는 이유도 같다 — 사양에는 검수자 개념이 없고(공지가 정본),
  고객 문구에는 있다(사람이 읽고 통과시켜야 나간다).

■ 왜 제안 등급을 game_grade_assignments 에 넣지 않는가

  game_grade_assignments 는 **확정 배정**이다. 22행 중 21행이 is_confirmed=true 이고
  그 이력은 사장님 확정이다. 기계 제안을 같은 표에 넣으면 is_confirmed 한 칸으로만
  «사람이 정한 것»과 «기계가 추측한 것»이 갈리게 되고, 조회 한 번 잘못 짜면
  추측이 확정인 척 견적에 실린다.

  분리하면 그 사고가 구조적으로 불가능하다 — 견적 경로는 game_grade_assignments 만
  읽고, game_grade_suggestions 는 관리자 승인 화면만 읽는다.
  승인 흐름(제안 -> 확정)은 이 마이그레이션이 만들지 않는다. 사장님 승인이 먼저다.

■ 이 마이그레이션이 하지 않는 것
  - games 의 어떤 컬럼도 추가/수정/삭제하지 않는다
  - game_grade_assignments · game_load_grades 를 읽지도 쓰지도 않는다
    (suggested_grade 의 FK 만 game_load_grades.grade 를 가리킨다 — 어휘를 두 벌
     두지 않기 위해서다. 없는 등급 문자가 제안으로 들어오는 것을 DB가 막는다)
  - 행을 넣지 않는다. 적재는 tools/game_customer_copy_load.py 가 한다.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0103"
down_revision = "0102"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 고객용 문구 ────────────────────────────────────────────────────────────
    # game_id 를 PK 로 둔다 — 게임 하나에 «현행 문구»는 하나다. 개정 이력이 필요해지면
    # 그때 별도 이력표를 만든다(지금 없는 요구를 미리 만들지 않는다).
    op.create_table(
        "game_customer_copy",
        sa.Column("game_id", sa.Integer,
                  sa.ForeignKey("games.game_id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("spec_summary_ko", sa.Text, nullable=True,
                  comment="한 줄 요약 — '이 게임은 OO가 중요합니다'"),
        sa.Column("why_this_pc", sa.Text, nullable=True,
                  comment="2~3문장 — 병목·목표 fps·VRAM 을 숫자와 함께"),
        sa.Column("upgrade_hint", sa.Text, nullable=True,
                  comment="한 줄 — 다음에 무엇을 올리는가"),
        sa.Column("caution", sa.Text, nullable=True,
                  comment="함정·오해. 없을 수 있다(15종은 null)"),
        # 어떤 DB 컬럼을 근거로 이 문장을 썼는지. 나중에 그 컬럼이 바뀌면
        # 어떤 문구를 다시 봐야 하는지 이 칸 하나로 찾을 수 있다.
        sa.Column("source_fields", postgresql.JSONB, nullable=True,
                  comment="근거로 쓴 games/game_measured_fps 컬럼명 배열"),
        sa.Column("confidence", sa.String(20), nullable=True,
                  comment="높음 / 보통 / 낮음 — 근거의 두께"),
        # 아직 아무도 검수하지 않았다. 전부 null 로 들어간다 — 기계가 쓴 글에
        # 사람 이름을 미리 적어 두면 그게 가장 위험한 거짓말이다.
        sa.Column("reviewed_by", sa.String(60), nullable=True,
                  comment="사람 검수자. null = 미검수"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_url", sa.Text, nullable=True,
                  comment="문구가 특정 외부 출처에 기대는 경우만"),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        comment="고객에게 보여주는 게임 상세설명. games(사실)와 검수 주기가 다르다",
    )
    op.create_index("ix_game_customer_copy_confidence",
                    "game_customer_copy", ["confidence"])
    op.create_index("ix_game_customer_copy_unreviewed",
                    "game_customer_copy", ["game_id"],
                    postgresql_where=sa.text("reviewed_by IS NULL"))

    # ── 기계 등급 제안 ────────────────────────────────────────────────────────
    # suggested_grade 는 nullable 이다. 제안기가 «모르겠다»고 말할 수 있어야 한다
    # (7종이 그렇다). 억지로 한 글자를 채우면 그 순간 근거 없는 등급이 생긴다.
    op.create_table(
        "game_grade_suggestions",
        sa.Column("game_id", sa.Integer,
                  sa.ForeignKey("games.game_id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("suggested_grade", sa.String(1),
                  sa.ForeignKey("game_load_grades.grade"), nullable=True,
                  comment="null = 기계가 판정하지 못했다(사람이 정해야 한다)"),
        sa.Column("confidence", sa.String(40), nullable=True,
                  comment="높음 / 보통 / 사람 확인 필요"),
        sa.Column("reason", sa.Text, nullable=True,
                  comment="어떤 컬럼 값을 보고 그렇게 판정했는가 — 사람이 검증할 수 있게"),
        sa.Column("rule_version", sa.String(40), nullable=True,
                  comment="제안을 만든 규칙 버전(grade_rules)"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        comment=("기계가 만든 «제안» 등급. 확정 배정은 game_grade_assignments 다. "
                 "견적 경로는 이 표를 읽지 않는다 — 관리자 승인 화면 전용"),
    )
    op.create_index("ix_game_grade_suggestions_confidence",
                    "game_grade_suggestions", ["confidence"])


def downgrade() -> None:
    op.drop_index("ix_game_grade_suggestions_confidence",
                  table_name="game_grade_suggestions")
    op.drop_table("game_grade_suggestions")
    op.drop_index("ix_game_customer_copy_unreviewed",
                  table_name="game_customer_copy")
    op.drop_index("ix_game_customer_copy_confidence",
                  table_name="game_customer_copy")
    op.drop_table("game_customer_copy")
