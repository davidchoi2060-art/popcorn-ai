"""AI 슈퍼컴퓨터(고정 완제품) 문의 — 모델·수량·문의 목적을 신청에 남긴다 (2026-10-19 /mvp4 v15 대표 승인).

`purchase_inquiries.fixed_product` (JSONB, NULL 허용) — /mvp4 슈퍼컴퓨터 상세에서 온 신청만 채운다.
  {product_code, name, storage, intent(quote|adoption), quantity(1~10), purpose, unit_price, total, priced_at}
  금액은 서버가 신청 순간 products 판매가로 다시 센 값이다(화면 값을 믿지 않는다). 판매 확인이 필요한 상품은 NULL 금액.
주제(topic)에 「AI 슈퍼컴퓨터 견적」·「AI 도입 상담」 두 값을 더한다. 일반 상담 화면의 주제 목록(api TOPICS)은 그대로다.

  · 기존 행은 건드리지 않는다(NULL).
  · downgrade 는 새 주제 행이 하나라도 있으면 거부한다(주제 CHECK 를 되돌릴 수 없다).
"""
from alembic import op

revision = '0165'
down_revision = '0164'
branch_labels = None
depends_on = None

OLD = "('여러 대 구매','할인','세금계산서·영수증','주문 희망','기타')"
NEW = "('여러 대 구매','할인','세금계산서·영수증','주문 희망','기타','AI 슈퍼컴퓨터 견적','AI 도입 상담')"


def upgrade():
    op.execute('ALTER TABLE purchase_inquiries ADD COLUMN fixed_product JSONB')
    op.execute("ALTER TABLE purchase_inquiries ADD CONSTRAINT purchase_inquiries_fixed_product_chk"
               " CHECK (fixed_product IS NULL OR jsonb_typeof(fixed_product) = 'object')")
    op.execute('ALTER TABLE purchase_inquiries DROP CONSTRAINT IF EXISTS purchase_inquiries_topic_check')
    op.execute('ALTER TABLE purchase_inquiries ADD CONSTRAINT purchase_inquiries_topic_check CHECK (topic IN %s)' % NEW)


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM purchase_inquiries WHERE fixed_product IS NOT NULL
                    OR topic IN ('AI 슈퍼컴퓨터 견적','AI 도입 상담'))
      THEN RAISE EXCEPTION 'supercomputer inquiries must be preserved'; END IF; END $$""")
    op.execute('ALTER TABLE purchase_inquiries DROP CONSTRAINT IF EXISTS purchase_inquiries_topic_check')
    op.execute('ALTER TABLE purchase_inquiries ADD CONSTRAINT purchase_inquiries_topic_check CHECK (topic IN %s)' % OLD)
    op.execute('ALTER TABLE purchase_inquiries DROP CONSTRAINT IF EXISTS purchase_inquiries_fixed_product_chk')
    op.execute('ALTER TABLE purchase_inquiries DROP COLUMN IF EXISTS fixed_product')
