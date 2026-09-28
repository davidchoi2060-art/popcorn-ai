"""Source-bound component explanation drafts, separate from engine specs."""
import json
from pathlib import Path
from alembic import op
import sqlalchemy as sa

revision = "0116"
down_revision = "0115"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE product_explanations (
      source_product_code BIGINT PRIMARY KEY,
      product_code BIGINT REFERENCES products(product_code) ON DELETE SET NULL,
      content JSONB NOT NULL,
      source_snapshot JSONB NOT NULL,
      source_fingerprint VARCHAR(64) NOT NULL,
      status VARCHAR(12) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved','retired')),
      approved_by INTEGER REFERENCES admin_operators(operator_id),
      approved_at TIMESTAMPTZ,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CHECK (status <> 'approved' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL))
    )""")
    data = json.loads((Path(__file__).resolve().parents[1]/"data"/"part_explanations_20260928.json").read_text(encoding="utf-8"))
    conn = op.get_bind()
    for item in data["items"]:
        conn.execute(sa.text("""INSERT INTO product_explanations
          (source_product_code,product_code,content,source_snapshot,source_fingerprint)
          VALUES (:code,(SELECT product_code FROM products WHERE product_code=:code),
                  CAST(:content AS JSONB),CAST(:snapshot AS JSONB),:fingerprint)"""),
          dict(code=item["code"],content=json.dumps(item["content"],ensure_ascii=False),
               snapshot=json.dumps(item["snapshot"],ensure_ascii=False),fingerprint=item["fingerprint"]))


def downgrade():
    op.execute("DROP TABLE product_explanations")
