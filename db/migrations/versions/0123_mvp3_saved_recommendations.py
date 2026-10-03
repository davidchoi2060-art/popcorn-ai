"""Guest-owned public recommendation snapshots, separate from confirmed quote ledgers."""
from alembic import op

revision = '0123'
down_revision = '0122'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE mvp3_saved_recommendations (
      quote_id UUID PRIMARY KEY,
      user_id BIGINT NOT NULL REFERENCES users(user_id),
      owner_key_hash VARCHAR(64) NOT NULL CHECK(length(owner_key_hash)=64),
      request_id UUID NOT NULL,
      request_basis VARCHAR(64) NOT NULL CHECK(length(request_basis)=64),
      product_snapshot JSONB NOT NULL CHECK(jsonb_typeof(product_snapshot)='object'),
      talk_state JSONB NOT NULL CHECK(jsonb_typeof(talk_state)='object'),
      saved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(user_id,owner_key_hash,request_id))''')
    op.execute('CREATE INDEX mvp3_saved_owner_time_idx ON mvp3_saved_recommendations(user_id,owner_key_hash,saved_at DESC,quote_id DESC)')


def downgrade():
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM mvp3_saved_recommendations LIMIT 1)
      THEN RAISE EXCEPTION 'Saved customer recommendations must be preserved'; END IF; END $$""")
    op.execute('DROP TABLE mvp3_saved_recommendations')
