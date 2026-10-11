"""견적 상담 기록 — 상담 한 건에 처리 상태와 메모를 남긴다 (2026-10-11 품질관리 · 개편 16번).

「견적 상담 기록」(ADM-ORD-010)은 읽기 전용이라 관리자가 상담을 보고 «확인했다 · 연락했다»를
남길 곳이 없었다(관리자 결과 F8). 상담 원장(consult_sessions)은 재현성 소명 근거라 건드리지
않고, 처리 기록만 따로 둔다.

  · 상담 한 건에 한 행. 저장할 때 생긴다 — 행이 없으면 «대기»로 본다. 시드 행은 없다.
  · 행을 지우지 않는다. 기존 표·데이터는 바꾸지 않는다.
"""
from alembic import op

revision = '0152'
down_revision = '0151'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE consult_session_notes (
      session_id BIGINT PRIMARY KEY REFERENCES consult_sessions(session_id),
      status VARCHAR(8) NOT NULL DEFAULT '대기' CHECK (status IN ('대기','처리 중','완료')),
      memo VARCHAR(1000),
      updated_by BIGINT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now())''')


def downgrade():
    op.execute('''DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM consult_session_notes) THEN
        RAISE EXCEPTION '0152 downgrade refused: consult_session_notes has rows';
      END IF; END $$''')
    op.execute('DROP TABLE consult_session_notes')
