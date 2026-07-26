"""관리자 인증 — admin_operators 확장 + admin_sessions.

ERD Ver 4.0 5th review §3.9 (2026-07-26), slice 37. 사용자 확정 설계:
소셜(구글) 신원 + **승인 게이트**, 자체 비밀번호는 저장하지 않는다
(우리가 갖지 않은 정보는 유출될 수 없다 — 자체 비밀번호를 더하면 이 이득이 사라진다).

status 어휘: 대기 / 활성 / 정지. 기존 'active' 행은 '활성'으로 이행한다.
role 어휘(2026-07-14 확정): viewer / operator / owner.
세션은 삭제하지 않고 revoked_at을 기록한다(감사).

Revision ID: 0007
Revises: 0006
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE admin_operators
          ADD COLUMN provider      VARCHAR(20),
          ADD COLUMN provider_uid  VARCHAR(120),
          ADD COLUMN phone         VARCHAR(30),
          ADD COLUMN duty          VARCHAR(100),
          ADD COLUMN approved_by   BIGINT REFERENCES admin_operators(operator_id),
          ADD COLUMN approved_at   TIMESTAMP,
          ADD COLUMN last_login_at TIMESTAMP;

        -- 기존 시드 운영자를 새 어휘로 이행(그동안 모든 쓰기의 주체였던 계정)
        UPDATE admin_operators SET status = '활성' WHERE status = 'active';

        CREATE UNIQUE INDEX idx_operators_provider
          ON admin_operators (provider, provider_uid)
          WHERE provider IS NOT NULL AND provider_uid IS NOT NULL;

        CREATE TABLE admin_sessions (
          session_id   VARCHAR(64) PRIMARY KEY,
          operator_id  BIGINT NOT NULL REFERENCES admin_operators(operator_id),
          created_at   TIMESTAMP NOT NULL DEFAULT now(),
          last_seen_at TIMESTAMP NOT NULL DEFAULT now(),
          expires_at   TIMESTAMP NOT NULL,
          revoked_at   TIMESTAMP,
          user_agent   VARCHAR(300)
        );

        CREATE INDEX idx_sessions_operator ON admin_sessions (operator_id, revoked_at);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS admin_sessions;
        DROP INDEX IF EXISTS idx_operators_provider;
        ALTER TABLE admin_operators
          DROP COLUMN IF EXISTS last_login_at,
          DROP COLUMN IF EXISTS approved_at,
          DROP COLUMN IF EXISTS approved_by,
          DROP COLUMN IF EXISTS duty,
          DROP COLUMN IF EXISTS phone,
          DROP COLUMN IF EXISTS provider_uid,
          DROP COLUMN IF EXISTS provider;
    """)
