"""Add compat_rules — 조립 호환 규칙을 엔진의 단일 원천으로.

ERD Ver 4.0 5th review §3.7 (2026-07-26), slice 34.
그동안 규칙은 recommend._slot_ok의 코드 상수로만 존재했고 화면은 그것을 읽어 표시했다.
이 마이그레이션과 함께 엔진이 이 테이블을 읽도록 리팩터링한다(테이블만 만들면 이중 원천).

계약: NULL 불통과 / ref_slot은 탐색 순서상 앞 / active=false는 미로드 /
      규칙 변경은 견적 결과를 바꾸므로 회귀 검증 대상.

Revision ID: 0005
Revises: 0004
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE compat_rules (
          rule_id     BIGSERIAL PRIMARY KEY,
          rule_key    VARCHAR(40) NOT NULL UNIQUE,
          slot        VARCHAR(20) NOT NULL,
          field       VARCHAR(40) NOT NULL,
          op          VARCHAR(4)  NOT NULL,
          ref_slot    VARCHAR(20) NOT NULL,
          ref_field   VARCHAR(40) NOT NULL,
          label       VARCHAR(100) NOT NULL,
          detail_fmt  VARCHAR(200),
          blocking    BOOLEAN NOT NULL DEFAULT true,
          active      BOOLEAN NOT NULL DEFAULT true,
          sort_order  INTEGER NOT NULL DEFAULT 0,
          updated_at  TIMESTAMP NOT NULL DEFAULT now()
        );

        CREATE INDEX idx_compat_rules_slot ON compat_rules (slot) WHERE active;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS compat_rules;")
