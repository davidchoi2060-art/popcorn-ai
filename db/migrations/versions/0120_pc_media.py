"""Persistent PC representative image jobs; no BOM or review mutation."""
from alembic import op
revision='0120'
down_revision='0119'
branch_labels=None
depends_on=None

def upgrade():
    op.execute("""CREATE TABLE pc_media_jobs (
      job_id UUID PRIMARY KEY, configuration_id TEXT NOT NULL REFERENCES pc_configurations(configuration_id),
      request_id UUID NOT NULL UNIQUE, visual_basis TEXT NOT NULL, review_basis TEXT NOT NULL,
      snapshot JSONB NOT NULL, model TEXT NOT NULL, actor TEXT NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('running','ready','failed')),
      phase TEXT NOT NULL DEFAULT 'generation', error TEXT, asset JSONB,
      selected BOOLEAN NOT NULL DEFAULT false,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
    op.execute("CREATE UNIQUE INDEX pc_media_selected ON pc_media_jobs(configuration_id) WHERE selected")
    op.execute('CREATE INDEX pc_media_config ON pc_media_jobs(configuration_id,created_at DESC)')

def downgrade():
    op.drop_table('pc_media_jobs')
