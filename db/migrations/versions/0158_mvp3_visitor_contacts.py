"""방문자 연락처 -- 견적을 처음 보관할 때 한 번만 받는 전화번호 (2026-10-16 대표 지시).

고객이 견적을 보관할 때 전화번호(필수)·이름·이메일(선택)을 받아 방문자 한 명에 한 줄 둔다.
다음 견적은 이 줄을 재사용한다(견적마다 연락처를 복제하지 않는다). 견적 보관만으로는 상담 신청이
생기지 않는다 -- `purchase_inquiries` 는 고객이 「상담 신청 접수」를 누를 때만 이 줄을 복사해 만든다.

  · `contact_phone` 은 NULL 을 허용하되 CHECK 로 「비운 줄(`contact_purged_at`)」만 예외로 둔다
    (일일 지우기 작업이 값만 비우고 줄은 남긴다 -- `api/retention_purge.py`).
  · 기존 행은 건드리지 않는다. 새 표 하나뿐이다.
"""
from alembic import op

revision = '0158'
down_revision = '0157'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE mvp3_visitor_contacts (
      user_id BIGINT PRIMARY KEY REFERENCES users(user_id),
      contact_phone VARCHAR(20),
      contact_name VARCHAR(30),
      contact_email VARCHAR(120),
      consent_at TIMESTAMPTZ NOT NULL,
      consent_text TEXT NOT NULL,
      data_origin VARCHAR(8) NOT NULL DEFAULT 'real',
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      purge_at TIMESTAMPTZ NOT NULL,
      contact_purged_at TIMESTAMPTZ,
      CHECK(contact_phone IS NOT NULL OR contact_purged_at IS NOT NULL))''')
    op.execute('CREATE INDEX mvp3_visitor_contacts_purge_idx ON mvp3_visitor_contacts(purge_at)')


def downgrade():
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM mvp3_visitor_contacts LIMIT 1)
      THEN RAISE EXCEPTION 'Visitor contacts must be preserved'; END IF; END $$""")
    op.execute('DROP TABLE mvp3_visitor_contacts')
