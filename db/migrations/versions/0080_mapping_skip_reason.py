# -*- coding: utf-8 -*-
"""매핑 스킵 사유를 DB에 남긴다 — games/ai_workloads.mapping_skip_reason

■ 왜
  admin_game_matrix.py의 unjudgeable_reason이 "원천에 rec_gpu 없음" 하나만
  말하고 있었다(rec_gpu is None만 검사) — 실제로는 배치(game_cell_mapper.py)가
  이미 세 가지 사유를 구분해서 계산하고 있는데(rec_gpu_missing·
  rec_gpu_parse_failed·zero_matching_cells) DB에 안 남겨서 화면이 못 썼다.
  2026-09-09 실측(--dry SUMMARY_JSON): 게임 8종 미매핑 중 3종은 원천에 값
  자체가 없고(rec_gpu_missing), 5종은 값은 있는데 서열표에 없는 초구형 카드라
  파싱이 실패한다(rec_gpu_parse_failed). 화면은 이 둘을 구분해서 보여줘야
  운영자가 "데이터를 보강해야 하나" vs "서열표를 확장해야 하나"를 가를 수 있다.

■ 사람이 읽는 문구 — 단일 원천은 이 파일(games_matrix_reasons.py)뿐이다
  배치(tools/game_cell_mapper.py)와 화면 API(api/admin_game_matrix.py)가
  같은 사전을 참조한다 — 문구를 두 곳에 따로 적지 않는다(§단일 원천).

Revision ID: 0080
Revises: 0079
"""
import sqlalchemy as sa
from alembic import op

revision = "0080"
down_revision = "0079"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("games", sa.Column("mapping_skip_reason", sa.Text(), nullable=True))
    op.add_column("ai_workloads", sa.Column("mapping_skip_reason", sa.Text(), nullable=True))
    print("[0080] games/ai_workloads.mapping_skip_reason 컬럼 추가 완료"
          " (값 채움은 다음 배치 실행에서 이뤄진다 — tools/game_cell_mapper.py)")


def downgrade() -> None:
    op.drop_column("games", "mapping_skip_reason")
    op.drop_column("ai_workloads", "mapping_skip_reason")
