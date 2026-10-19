"""구매 상담 신청의 화면 요청 키 — 같은 요청은 한 번만 접수하고, 응답을 못 받은 화면이 결과를 확인한다 (2026-10-19 /mvp4 v11).

`purchase_inquiries.client_key` — 화면이 신청마다 만든 키(/mvp4 AI 패키지 문의의 clientRequestKey). NULL 허용.
같은 방문자(user_id)·같은 키의 행은 하나뿐이다(부분 고유 색인). 키가 없는 기존 신청 경로는 그대로다.

  · 기존 행은 건드리지 않는다(NULL).
"""
from alembic import op

revision = '0163'
down_revision = '0162'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE purchase_inquiries ADD COLUMN client_key TEXT')
    op.execute("ALTER TABLE purchase_inquiries ADD CONSTRAINT purchase_inquiries_client_key_chk"
               " CHECK (client_key ~ '^[A-Za-z0-9_-]{6,64}$')")
    op.execute('CREATE UNIQUE INDEX purchase_inquiries_client_key_uq ON purchase_inquiries (user_id, client_key)'
               ' WHERE client_key IS NOT NULL')


def downgrade():
    op.execute('DROP INDEX IF EXISTS purchase_inquiries_client_key_uq')
    op.execute('ALTER TABLE purchase_inquiries DROP CONSTRAINT IF EXISTS purchase_inquiries_client_key_chk')
    op.execute('ALTER TABLE purchase_inquiries DROP COLUMN IF EXISTS client_key')
