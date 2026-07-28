"""사양 항목 추가 — cpu_gpu (내장그래픽).

관리자 화면(ADM-PRD-050)에서 만든 항목이다. 화면이 DDL을 실행했지만, 이력이 없으면
서버를 새로 세우거나 백업에서 복구할 때 이 컬럼이 사라진다. 그래서 같은 변경을
마이그레이션으로도 남긴다.

  · 적용 부품: CPU
  · 필수 사양: (없음)
  · 엔진 사용: 아니오 — 표시용

**이 파일은 손으로 썼다.** 원래 화면이 자동으로 남기는데, 2026-07-28 운영자가
베타 서버에서 이 항목을 만들 때 파일 쓰기가 실패했다(배포 서버의 앱 계정은 리포 폴더에
쓸 수 없다). ①컬럼 ②메타 ③작업기록은 이미 커밋된 뒤라 **변경은 살아 있는데 이력만
없는 상태**로 하루를 보냈고, 운영자 화면에는 500이 떴다. 빈 DB 관통 검증에서
사양 항목이 29 대 28로 갈려 발견했다(2026-07-29).

같은 일이 반복되지 않게 `admin_spec_fields`를 함께 고쳤다 — 파일을 못 써도 요청을
실패로 만들지 않고, 이력이 없다는 사실을 목록 화면이 계속 표시한다(`unrecorded`).

Revision ID: 0020
Revises: 0019
"""
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE product_specs ADD COLUMN IF NOT EXISTS cpu_gpu BOOLEAN")
    op.execute("""
        INSERT INTO spec_field_defs
          (field_key, label, data_type, unit, part_types, required_for,
           is_engine, is_custom, in_ingest, sort_order, note)
        VALUES ('cpu_gpu', '내장그래픽', 'BOOLEAN', NULL,
                '["CPU"]'::jsonb, '[]'::jsonb,
                false, true, false,
                (SELECT COALESCE(MAX(sort_order), 0) + 10 FROM spec_field_defs),
                '화면에서 추가')
        ON CONFLICT (field_key) DO NOTHING
    """)


def downgrade() -> None:
    # 컬럼을 지우면 값이 함께 사라진다 — 메타만 지우고 컬럼은 남긴다.
    op.execute("DELETE FROM spec_field_defs WHERE field_key = 'cpu_gpu'")
