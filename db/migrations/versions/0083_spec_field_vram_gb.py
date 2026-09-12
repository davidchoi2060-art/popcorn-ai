"""사양 항목 추가 — vram_gb (VRAM 용량).

관리자 화면(ADM-PRD-050)에서 만든 항목이다. 화면이 DDL을 실행했지만, 이력이 없으면
서버를 새로 세우거나 백업에서 복구할 때 이 컬럼이 사라진다. 그래서 같은 변경을
마이그레이션으로도 남긴다.

  · 적용 부품: GPU
  · 필수 사양: (없음)
  · 엔진 사용: 예 — 추천 뷰에 포함

Revision ID: 0083
Revises: 0082
"""
from alembic import op

revision = "0083"
down_revision = "0082"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE product_specs ADD COLUMN IF NOT EXISTS vram_gb INTEGER")
    op.execute("""
        INSERT INTO spec_field_defs
          (field_key, label, data_type, unit, part_types, required_for,
           is_engine, is_custom, in_ingest, sort_order, note)
        VALUES ('vram_gb', 'VRAM 용량', 'INTEGER',
                'GB',
                '["GPU"]'::jsonb, '[]'::jsonb,
                true, true, false,
                (SELECT COALESCE(MAX(sort_order), 0) + 10 FROM spec_field_defs),
                '화면에서 추가')
        ON CONFLICT (field_key) DO NOTHING
    """)


def downgrade() -> None:
    # 컬럼을 지우면 값이 함께 사라진다 — 메타만 지우고 컬럼은 남긴다.
    op.execute("DELETE FROM spec_field_defs WHERE field_key = 'vram_gb'")
