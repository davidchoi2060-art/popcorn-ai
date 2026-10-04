"""Immutable reprice outcomes in the same transaction as price/history/log writes."""
from alembic import op

revision = '0124'
down_revision = '0123'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE admin_operation_receipts (
      environment UUID NOT NULL,
      operation_id UUID NOT NULL,
      receipt_id UUID NOT NULL UNIQUE,
      actor_id BIGINT NOT NULL REFERENCES admin_operators(operator_id)
        CHECK(actor_id BETWEEN 1 AND 9007199254740991),
      action TEXT NOT NULL CHECK(action='reprice_apply'),
      contract_version TEXT NOT NULL CHECK(contract_version='admin_operation_v1'),
      canonical_version TEXT NOT NULL CHECK(canonical_version='reprice_request_v1'),
      scope TEXT NOT NULL CHECK(scope IN ('live','selling','all')),
      request_fingerprint VARCHAR(64) NOT NULL CHECK(request_fingerprint ~ '^[0-9a-f]{64}$'),
      state TEXT NOT NULL CHECK(state IN ('applied','rejected')),
      result JSONB NOT NULL CHECK(jsonb_typeof(result)='object'),
      response_body JSONB NOT NULL CHECK(jsonb_typeof(response_body)='object'),
      original_http_status INT NOT NULL,
      log_id BIGINT REFERENCES admin_operator_activity_logs(log_id),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY(environment,operation_id),
      CHECK ((state='rejected' AND log_id IS NULL AND result='{}'::jsonb
              AND original_http_status IN (400,409)
              AND response_body ? 'detail'
              AND jsonb_typeof(response_body->'detail')='string'
              AND response_body - 'detail' = '{}'::jsonb)
          OR (state='applied' AND log_id IS NOT NULL AND log_id > 0
              AND original_http_status=200
              AND result ?& ARRAY['log_id','changed','up','down','locked','dropped']
              AND result - ARRAY['log_id','changed','up','down','locked','dropped'] = '{}'::jsonb
              AND jsonb_typeof(result->'log_id')='number' AND result->>'log_id' ~ '^[0-9]+$'
              AND jsonb_typeof(result->'changed')='number' AND result->>'changed' ~ '^[0-9]+$'
              AND jsonb_typeof(result->'up')='number' AND result->>'up' ~ '^[0-9]+$'
              AND jsonb_typeof(result->'down')='number' AND result->>'down' ~ '^[0-9]+$'
              AND jsonb_typeof(result->'locked')='number' AND result->>'locked' ~ '^[0-9]+$'
              AND jsonb_typeof(result->'dropped')='number' AND result->>'dropped' ~ '^[0-9]+$'
              AND (result->>'log_id')::numeric=log_id
              AND response_body ? 'verdict' AND jsonb_typeof(response_body->'verdict')='string'
              AND response_body - 'verdict' = result)))''')
    op.execute("""CREATE UNIQUE INDEX admin_operation_receipts_applied_log_uq
      ON admin_operation_receipts(environment,log_id) WHERE state='applied'""")
    op.execute("""CREATE FUNCTION admin_operation_receipts_immutable() RETURNS trigger
      LANGUAGE plpgsql AS $$ BEGIN
        RAISE EXCEPTION 'Admin operation receipts are immutable';
      END $$""")
    op.execute("""CREATE TRIGGER admin_operation_receipts_no_change
      BEFORE UPDATE OR DELETE ON admin_operation_receipts
      FOR EACH ROW EXECUTE FUNCTION admin_operation_receipts_immutable()""")


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM admin_operation_receipts LIMIT 1)
      THEN RAISE EXCEPTION 'Admin operation receipts must be preserved'; END IF;
      END $$""")
    op.execute('DROP TABLE admin_operation_receipts')
    op.execute('DROP FUNCTION admin_operation_receipts_immutable()')
