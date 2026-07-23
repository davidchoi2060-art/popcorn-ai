"""Add shipping_snap / session_id to orders.

ERD Ver 4.0 4th review (2026-07-24), S4 order slice.
- shipping_snap JSONB: recipient snapshot {name, phone, addr} (no storage existed).
- session_id: link order to consult_sessions (quote snapshot provenance). NULL allowed.

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE orders
          ADD COLUMN shipping_snap JSONB,
          ADD COLUMN session_id BIGINT REFERENCES consult_sessions(session_id)
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE orders
          DROP COLUMN shipping_snap,
          DROP COLUMN session_id
    """)
