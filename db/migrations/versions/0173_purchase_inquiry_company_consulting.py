"""30인 이하 기업 AI 업무개선 컨설팅 상담 주제 (2026-10-21 /mvp4 대표 승인, 주제 추가는 같은 날 대표 「바로 하라」).

`purchase_inquiries.topic` 에 「기업 AI 업무개선 컨설팅」을 더한다. 지금까지 AI 패키지 상담은 모두 「기타」로 저장돼
개인 업무 AI 도입 상담과 기업 컨설팅을 서버에서 구분할 수 없었다. 일반 상담 화면의 주제 목록(api TOPICS)은 그대로다.

  · 기존 행은 건드리지 않는다.
  · downgrade 는 새 주제 행이 하나라도 있으면 거부한다(주제 CHECK 를 되돌릴 수 없다).
"""
from alembic import op

revision = '0173'
down_revision = '0172'
branch_labels = None
depends_on = None

OLD = "('여러 대 구매','할인','세금계산서·영수증','주문 희망','기타','AI 슈퍼컴퓨터 견적','AI 도입 상담')"
NEW = "('여러 대 구매','할인','세금계산서·영수증','주문 희망','기타','AI 슈퍼컴퓨터 견적','AI 도입 상담','기업 AI 업무개선 컨설팅')"


def upgrade():
    op.execute('ALTER TABLE purchase_inquiries DROP CONSTRAINT IF EXISTS purchase_inquiries_topic_check')
    op.execute('ALTER TABLE purchase_inquiries ADD CONSTRAINT purchase_inquiries_topic_check CHECK (topic IN %s)' % NEW)


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM purchase_inquiries WHERE topic = '기업 AI 업무개선 컨설팅')
      THEN RAISE EXCEPTION 'company consulting inquiries must be preserved'; END IF; END $$""")
    op.execute('ALTER TABLE purchase_inquiries DROP CONSTRAINT IF EXISTS purchase_inquiries_topic_check')
    op.execute('ALTER TABLE purchase_inquiries ADD CONSTRAINT purchase_inquiries_topic_check CHECK (topic IN %s)' % OLD)
