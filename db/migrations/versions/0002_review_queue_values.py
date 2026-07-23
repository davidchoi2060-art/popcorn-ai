"""Add origin_value / suggested_value / confidence to product_reviews.

ERD Ver 4.0 3rd review (2026-07-23), ADM-PRD-020 slice.
First-class promotion of cross-validation gate outputs (ERD 7.2):
machine-readable inputs for the confirm action. Values must be castable
canonical strings ('272', 'DDR5') - no unit suffixes.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE product_reviews
          ADD COLUMN origin_value    VARCHAR(255),
          ADD COLUMN suggested_value VARCHAR(255),
          ADD COLUMN confidence      NUMERIC(4,2)
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE product_reviews
          DROP COLUMN origin_value,
          DROP COLUMN suggested_value,
          DROP COLUMN confidence
    """)
