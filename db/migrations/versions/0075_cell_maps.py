# -*- coding: utf-8 -*-
"""게임·AI 작업 ↔ 격자 칸 매핑 — game_cell_map·workload_cell_map (격자-6)

■ 배경 — `docs/design/game-quote-mapping-2026-09-07.md` §2(판정 3경로)·§5(작업 순서)
  "이 견적으로 이 게임이 되는가"에 화면이 답하려면 게임/AI 작업과 격자 칸을 미리
  이어 둬야 한다(실시간 계산은 하지 않는다 — §5 "계산 시점: 배치에서"). 이
  마이그레이션은 그 저장 구조만 만든다. 실제 판정 계산은 `tools/game_cell_mapper.py`.

■ 왜 `grid_quotes`처럼 원장(is_current + INSERT 이력)으로 두지 않았는가
  `grid_quotes`는 "이 칸이 언제·왜 이 구성이었나"를 나중에 되짚어야 하는 **견적
  이력**이다(0072 머리 주석) — 그래서 UPDATE 대신 INSERT하고 과거본을 남긴다.

  이 두 표는 다르다. **매핑은 파생값이다** — 게임 요구사양·`gpu_ladder` 서열·
  `grid_quotes`의 현재 칸 구성, 이 셋을 조합한 "지금 시점의 판정 결과"일 뿐이고
  그 자체로 사실을 기록하는 게 아니다. `grid_quotes`가 갱신되면(칸의 GPU가
  바뀌면) 어제의 판정은 **틀린 값**이 된다 — 원장으로 쌓아 두면 "어제는
  권장충족이었는데 오늘은 왜 빠졌나"를 묻는 대신, 갱신 전 판정이 화면에 계속
  남아 지어낸 사실을 말하게 된다(§화면 정직성 규약). 되짚어야 할 이력이 아니라
  **항상 최신 grid_quotes와 정합해야 하는 캐시**이므로, 배치가 돌 때마다
  TRUNCATE 후 재계산한다. 원장화가 필요해지는 시점(예: "이 게임이 예전엔 이
  칸에서도 됐었다"를 보여줘야 할 때)이 오면 별도 결정으로 연다 — 지금은
  요구되지 않은 이력을 미리 만들지 않는다.

■ 다대다인 이유
  게임 하나가 여러 칸을 만족할 수 있다(§2 "격자 칸 권장"은 "가장 싼 칸"을
  고르지만, 화면이 나중에 "이 게임 되는 다른 견적도 보기"를 보여주려면 원천에
  전부 있어야 한다). 그래서 PK를 (game_id, cell_id) 복합키로 둔다 — "가장 싼
  칸" 선택은 조회 시점에 이 표를 정렬해서 뽑는다(별도 컬럼으로 표시하지 않는다,
  grid_quotes의 total을 조인하면 항상 정확하다 — 단일 원천).

Revision ID: 0075
Revises: 0074
"""
import sqlalchemy as sa
from alembic import op

revision = "0075"
down_revision = "0074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "game_cell_map",
        sa.Column("game_id", sa.Integer,
                   sa.ForeignKey("games.game_id"), nullable=False),
        sa.Column("cell_id", sa.Integer,
                   sa.ForeignKey("grid_cells.cell_id"), nullable=False),
        sa.Column("match_level", sa.String(12), nullable=False),  # 권장충족/최소충족
        sa.Column("gpu_used", sa.String(40), nullable=False),     # 그 칸 견적 GPU의 gpu_ladder 정규형
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False,
                   server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("game_id", "cell_id", name="pk_game_cell_map"),
    )
    op.execute(
        "COMMENT ON TABLE game_cell_map IS "
        "'게임 x 격자칸 판정 결과(파생 캐시, 원장 아님) — 배치가 돌 때마다 TRUNCATE 후 "
        "재계산한다. tools/game_cell_mapper.py. docs/design/game-quote-mapping-2026-09-07.md §2'"
    )

    op.create_table(
        "workload_cell_map",
        sa.Column("workload_id", sa.Integer,
                   sa.ForeignKey("ai_workloads.workload_id"), nullable=False),
        sa.Column("cell_id", sa.Integer,
                   sa.ForeignKey("grid_cells.cell_id"), nullable=False),
        sa.Column("match_level", sa.String(12), nullable=False),  # 구동가능/권장구성
        sa.Column("gpu_used", sa.String(40), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False,
                   server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("workload_id", "cell_id", name="pk_workload_cell_map"),
    )
    op.execute(
        "COMMENT ON TABLE workload_cell_map IS "
        "'AI작업 x 격자칸 판정 결과(파생 캐시, 원장 아님) — 배치가 돌 때마다 TRUNCATE 후 "
        "재계산한다. tools/game_cell_mapper.py. docs/design/game-quote-mapping-2026-09-07.md §2'"
    )


def downgrade() -> None:
    op.drop_table("workload_cell_map")
    op.drop_table("game_cell_map")
