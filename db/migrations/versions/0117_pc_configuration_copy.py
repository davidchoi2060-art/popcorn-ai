"""Versioned BOM copy and links to component explanation identities."""
from alembic import op

revision = '0117'
down_revision = '0116'
branch_labels = None
depends_on = None

def upgrade():
    op.execute('''CREATE TABLE pc_configurations (
      configuration_id TEXT PRIMARY KEY, bom_fingerprint VARCHAR(64) NOT NULL UNIQUE,
      content JSONB NOT NULL, content_hash VARCHAR(64) NOT NULL, copy_hash VARCHAR(64) NOT NULL,
      revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
      observed_date DATE NOT NULL,
      status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','review_required','approved','retired')),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    op.execute('''CREATE TABLE pc_configuration_parts (
      configuration_id TEXT NOT NULL REFERENCES pc_configurations(configuration_id),
      ordinal INTEGER NOT NULL, slot TEXT NOT NULL, source_code TEXT NOT NULL,
      explanation_code BIGINT REFERENCES product_explanations(source_product_code),
      quantity INTEGER NOT NULL CHECK(quantity > 0), pseudo BOOLEAN NOT NULL,
      selection_note TEXT NOT NULL, explanation_hash VARCHAR(64),
      PRIMARY KEY(configuration_id, ordinal),
      CHECK ((pseudo AND explanation_code IS NULL) OR
             (NOT pseudo AND explanation_code IS NOT NULL AND explanation_hash IS NOT NULL)))''')
    op.execute('CREATE INDEX pc_configuration_parts_explanation_idx ON pc_configuration_parts(explanation_code)')
    op.execute('''CREATE TABLE pc_configuration_offers (
      offer_id TEXT PRIMARY KEY, configuration_id TEXT NOT NULL REFERENCES pc_configurations(configuration_id),
      price_snapshot BIGINT NOT NULL CHECK(price_snapshot > 0), payload JSONB NOT NULL)''')
    op.execute('''CREATE TABLE pc_configuration_history (
      configuration_id TEXT NOT NULL REFERENCES pc_configurations(configuration_id),
      revision INTEGER NOT NULL, snapshot JSONB NOT NULL,
      archived_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(configuration_id,revision))''')

def downgrade():
    # Populated content must be explicitly archived, never erased by routine downgrade.
    op.execute("DO $$ BEGIN IF EXISTS(SELECT 1 FROM pc_configurations) THEN RAISE EXCEPTION 'Archive populated configuration data before downgrade'; END IF; END $$")
    for name in ['pc_configuration_history','pc_configuration_offers','pc_configuration_parts','pc_configurations']:
        op.execute(f'DROP TABLE {name}')
