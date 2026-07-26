"""product_sourcing_quotes를 A-10 공급처 원장과 연결.

ERD Ver 4.0 5th review §3.9 (2026-07-26), slice 35.
- supplier_id FK: Ver 2.0의 vendor VARCHAR를 공급처 원장과 연결(vendor는 표시용으로 남긴다 —
  기존 행이 없어 마이그레이션 위험 0, 향후 외부 공급처 자유 입력 여지).
- replied_at: 회신 기록 시각(NULL = 회신 대기). 공급처 회신은 전화·메일로 오므로
  **운영자 대행 입력**이 실제 업무다(자동 수신 아님 — 정직).
- memo: 회신 조건(납기·수량 등).
status 어휘: 요청 / 회신 / 확정 / 취소.

대기 목록(안전재고 미달·재고 0)은 **저장하지 않고 파생**한다(products.safety_stock, 0004) —
별도 큐 테이블은 동기화 문제만 만든다. 저장하는 것은 운영자가 실제로 한 행위뿐.

Revision ID: 0006
Revises: 0005
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE product_sourcing_quotes
          ADD COLUMN supplier_id BIGINT REFERENCES suppliers(supplier_id),
          ADD COLUMN replied_at  TIMESTAMP,
          ADD COLUMN memo        VARCHAR(200);

        CREATE INDEX idx_sourcing_quotes_product
          ON product_sourcing_quotes (product_code, status);
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS idx_sourcing_quotes_product;
        ALTER TABLE product_sourcing_quotes
          DROP COLUMN IF EXISTS memo,
          DROP COLUMN IF EXISTS replied_at,
          DROP COLUMN IF EXISTS supplier_id;
    """)
