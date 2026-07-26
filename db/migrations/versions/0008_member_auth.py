"""고객 인증 — members 확장 + member_sessions.

ERD Ver 4.0 6th review §3.11 (2026-07-26), slice 38.

관리자 인증(0007)과 **의도적으로 다른 3가지**:
  ① 승인 게이트 없음 — 첫 로그인이 가입이고 즉시 이용한다(고객을 기다리게 하면 이탈한다).
  ② 만료 = 절대 14일 · 유휴 없음(관리자는 8시간/30분) — 고객은 재방문 간격이 길고
     다루는 권한이 자기 데이터뿐이라 유휴 만료는 불편만 남긴다.
  ③ 권한 등급 없음 — 회원은 자기 데이터만 본다(경계는 member_id).

같은 원칙: **비밀번호를 저장하지 않는다.** joined_via가 이미 email/kakao/naver를 갖고
있어 provider 컬럼은 추가하지 않고 재사용한다(중복 원천 금지).

Revision ID: 0008
Revises: 0007
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE members
          ADD COLUMN provider_uid  VARCHAR(120),   -- 제공자 고유 ID — 이메일 변경에도 불변
          ADD COLUMN last_login_at TIMESTAMP;

        -- joined_via(email|kakao|naver|google)와 짝 — 같은 제공자에 같은 uid는 한 계정
        CREATE UNIQUE INDEX idx_members_provider
          ON members (joined_via, provider_uid)
          WHERE provider_uid IS NOT NULL;

        CREATE TABLE member_sessions (
          session_id   VARCHAR(64) PRIMARY KEY,
          member_id    BIGINT NOT NULL REFERENCES members(member_id),
          created_at   TIMESTAMP NOT NULL DEFAULT now(),
          last_seen_at TIMESTAMP NOT NULL DEFAULT now(),
          expires_at   TIMESTAMP NOT NULL,          -- 절대 만료(14일)
          revoked_at   TIMESTAMP,                   -- 로그아웃·탈퇴 — 삭제하지 않는다
          user_agent   VARCHAR(300)
        );

        CREATE INDEX idx_member_sessions_member ON member_sessions (member_id, revoked_at);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS member_sessions;
        DROP INDEX IF EXISTS idx_members_provider;
        ALTER TABLE members
          DROP COLUMN IF EXISTS last_login_at,
          DROP COLUMN IF EXISTS provider_uid;
    """)
