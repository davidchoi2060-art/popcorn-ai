"""PC video job metadata. Original video files remain outside the DB."""
from alembic import op
revision='0122'
down_revision='0121'
branch_labels=None
depends_on=None
def upgrade():
    op.execute('''CREATE TABLE pc_video_jobs (
      job_id UUID PRIMARY KEY, configuration_id TEXT NOT NULL REFERENCES pc_configurations(configuration_id),
      request_id UUID NOT NULL UNIQUE, image_job_id UUID NOT NULL REFERENCES pc_media_jobs(job_id),
      basis TEXT NOT NULL, snapshot JSONB NOT NULL, actor TEXT NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('running','ready','failed')),
      phase TEXT NOT NULL DEFAULT 'render', error TEXT, asset JSONB,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),updated_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    op.execute('CREATE INDEX pc_video_config ON pc_video_jobs(configuration_id,created_at DESC)')
def downgrade():op.drop_table('pc_video_jobs')
