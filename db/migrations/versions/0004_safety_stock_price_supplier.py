"""Add products.safety_stock / product_price_history.supplier_id.

ERD Ver 4.0 5th review (2026-07-26), slice 33 — 원천 부재 해소 2건.
- safety_stock INTEGER (nullable): 안전재고 기준. 이 수량 미달이면 입고 대기에 합류하고
  매입 견적 자동 등록 대상이 된다. NULL = 기준 미설정(판정 대상 아님).
  근거: 사용자 확정 2026-07-14 "안전재고 개념 유지" — 그동안 화면 연출로만 존재했다
  (stock-inbound 안전재고 미달 배지·sourcing 자동 등록 문구).
- supplier_id BIGINT (nullable, FK suppliers): 매입가 이력의 출처 공급처.
  field='purchase'일 때만 채운다. 판매가 이력은 공급처 무관이므로 NULL 유지.
  근거: ADM-PRC-030 가격 이력이 "공급처별 매입가 2선"을 그리려 했으나 원장에 공급처
  구분이 없어 판매가·매입가 2선으로 축소했던 한계(슬라이스 27) 해소.

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE products
          ADD COLUMN safety_stock INTEGER;

        ALTER TABLE product_price_history
          ADD COLUMN supplier_id BIGINT REFERENCES suppliers(supplier_id);

        CREATE INDEX idx_price_history_supplier
          ON product_price_history (product_code, supplier_id, changed_at DESC)
          WHERE supplier_id IS NOT NULL;
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS idx_price_history_supplier;
        ALTER TABLE product_price_history DROP COLUMN IF EXISTS supplier_id;
        ALTER TABLE products DROP COLUMN IF EXISTS safety_stock;
    """)
