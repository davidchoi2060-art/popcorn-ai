"""구매 상담 신청에 「직접 고른 PC」 구성을 붙인다 (2026-10-16 중헌 님 — 고객이 부품을 직접 골라 담기).

고객이 `api/mvp3_free_build` 로 고른 구성은 몰 상품번호가 없는 부품 묶음이라 몰 장바구니에 넣지 않고,
「이 구성으로 구매 상담 신청」으로 받는다. 신청 순간 서버가 지금 판매가·호환으로 다시 계산한 구성을
`free_build` 에 남긴다(부품 · 수량 · 그때 판매가 · 조립비 · 총액). 관리자 「구매 상담 신청」이 그대로 읽는다.

  · 기존 행은 건드리지 않는다. NULL 허용 칸 하나뿐이다.
"""
from alembic import op

revision = '0159'
down_revision = '0158'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE purchase_inquiries ADD COLUMN free_build JSONB')


def downgrade():
    op.execute('ALTER TABLE purchase_inquiries DROP COLUMN IF EXISTS free_build')
