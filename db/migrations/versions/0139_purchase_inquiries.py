"""구매 상담 신청 — 고객이 연락처를 남기고 관리자가 처리한다 (2026-10-11 품질관리 · R4·F12·M4).

지금 고객 화면(mvp3)의 고객은 익명이다. 대량 구매·할인·세금계산서·주문 희망처럼 AI 가
답할 수 없는 문의를 받아도 관리자가 다시 연락할 방법이 없었다.

  고객이 남기는 것   주제 · 연락처(전화 또는 이메일 중 하나 이상) · 이름(선택) · 내용 ·
                     개인정보 수집 동의 시각. 보관 견적이 있으면 그 견적을 잇는다
  관리자가 남기는 것 상태(대기 · 처리 중 · 완료) · 담당자 · 메모

연락처는 개인정보다 — `purge_at`(신청 후 180일)을 둔다. 지우는 작업 자체는 아직 없다.
"""
from alembic import op

revision = '0139'
down_revision = '0138'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE purchase_inquiries (
      inquiry_id BIGSERIAL PRIMARY KEY,
      inquiry_no VARCHAR(16) NOT NULL UNIQUE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      user_id BIGINT REFERENCES users(user_id),
      quote_id UUID REFERENCES mvp3_saved_recommendations(quote_id),
      product_code BIGINT,
      topic VARCHAR(16) NOT NULL CHECK(topic IN ('여러 대 구매','할인','세금계산서·영수증','주문 희망','기타')),
      contact_name VARCHAR(30),
      contact_phone VARCHAR(20),
      contact_email VARCHAR(120),
      message TEXT CHECK(message IS NULL OR length(message) <= 500),
      consent_at TIMESTAMPTZ NOT NULL,
      status VARCHAR(8) NOT NULL DEFAULT '대기' CHECK(status IN ('대기','처리 중','완료')),
      assignee_id BIGINT,
      memo TEXT CHECK(memo IS NULL OR length(memo) <= 1000),
      updated_by BIGINT,
      updated_at TIMESTAMPTZ,
      data_origin VARCHAR(8) NOT NULL DEFAULT 'real',
      purge_at TIMESTAMPTZ NOT NULL,
      CHECK(contact_phone IS NOT NULL OR contact_email IS NOT NULL))''')
    op.execute('CREATE INDEX purchase_inquiries_status_idx ON purchase_inquiries(status, created_at DESC)')
    op.execute('CREATE INDEX purchase_inquiries_user_idx ON purchase_inquiries(user_id, created_at DESC)')


def downgrade():
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM purchase_inquiries LIMIT 1)
      THEN RAISE EXCEPTION 'Customer purchase inquiries must be preserved'; END IF; END $$""")
    op.execute('DROP TABLE purchase_inquiries')
