"""SOURCE only: append-only publication history; no GRANT or automatic erase."""
import re

from alembic import op
from sqlalchemy import text

revision = '0129'
down_revision = '0128'
branch_labels = None
depends_on = None

UPGRADE_SQL = r'''
CREATE TABLE __S__.pc_customer_publication_events (
  configuration_id TEXT NOT NULL REFERENCES __S__.pc_configurations(configuration_id),
  event_seq BIGINT NOT NULL CHECK(event_seq>0),
  request_id UUID NOT NULL UNIQUE,
  request_digest VARCHAR(64) NOT NULL CHECK(request_digest ~ '^[a-f0-9]{64}$'),
  action TEXT NOT NULL CHECK(action IN ('approve','revoke')),
  operator_id BIGINT NOT NULL REFERENCES __S__.admin_operators(operator_id) CHECK(operator_id>0),
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  note TEXT NOT NULL CHECK(length(note)<=2000 AND octet_length(note)<=8000
    AND (action<>'revoke' OR length(btrim(note))>0)),
  configuration_revision INTEGER NOT NULL CHECK(configuration_revision>0),
  review_basis VARCHAR(64) NOT NULL CHECK(review_basis ~ '^[a-f0-9]{64}$'),
  publication_basis VARCHAR(64) NOT NULL CHECK(publication_basis ~ '^[a-f0-9]{64}$'),
  evidence JSONB NOT NULL CHECK(jsonb_typeof(evidence)='object'
    AND evidence ?& ARRAY['version','source_policy_version','binding','configuration_digest',
      'review_basis','review_digest','terms_scope_basis','terms_digest','components']
    AND evidence->>'version' IS NOT DISTINCT FROM 'pc-customer-publication-v1'
    AND evidence->>'source_policy_version' IS NOT DISTINCT FROM 'pc-publication-source-v1'
    AND jsonb_typeof(evidence->'binding') IS NOT DISTINCT FROM 'object'
    AND jsonb_typeof(evidence->'components') IS NOT DISTINCT FROM 'array'
    AND evidence->'binding'->>'configuration_id' IS NOT DISTINCT FROM configuration_id
    AND evidence->'binding'->'revision' IS NOT DISTINCT FROM to_jsonb(configuration_revision)
    AND evidence->>'review_basis' IS NOT DISTINCT FROM review_basis),
  PRIMARY KEY(configuration_id,event_seq)
);

CREATE FUNCTION __S__.pc_customer_publication_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $guard$
DECLARE c record; previous record; operator_row record;
BEGIN
  IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Publication history is immutable'; END IF;
  -- Match existing review writer lock order; even direct inserts serialize.
  PERFORM pg_advisory_xact_lock(hashtext('pc_configuration_copy'));
  SELECT * INTO c FROM __S__.pc_configurations
    WHERE configuration_id=NEW.configuration_id FOR UPDATE;
  IF c.configuration_id IS NULL THEN RAISE EXCEPTION 'Publication configuration missing'; END IF;
  SELECT * INTO previous FROM __S__.pc_customer_publication_events
    WHERE configuration_id=NEW.configuration_id ORDER BY event_seq DESC LIMIT 1;
  IF NEW.event_seq IS DISTINCT FROM coalesce(previous.event_seq,0)+1 THEN
    RAISE EXCEPTION 'Publication sequence mismatch';
  END IF;
  SELECT role,status INTO operator_row FROM __S__.admin_operators
    WHERE operator_id=NEW.operator_id FOR SHARE;
  IF operator_row.role IS NULL OR operator_row.role NOT IN ('owner','operator')
    OR operator_row.status IS DISTINCT FROM '활성' OR NEW.recorded_at IS DISTINCT FROM now() THEN
    RAISE EXCEPTION 'Publication actor or time mismatch';
  END IF;
  IF NEW.action='approve' THEN
    IF c.status IS DISTINCT FROM 'approved' OR c.revision IS DISTINCT FROM NEW.configuration_revision
      OR c.content->'_review'->>'state' IS DISTINCT FROM 'approved'
      OR c.content->'_review'->>'basis' IS DISTINCT FROM NEW.review_basis
      OR NEW.evidence->'binding'->>'bom_fingerprint' IS DISTINCT FROM c.bom_fingerprint
      OR NEW.evidence->'binding'->>'content_hash' IS DISTINCT FROM c.content_hash
      OR NEW.evidence->'binding'->>'copy_hash' IS DISTINCT FROM c.copy_hash THEN
      RAISE EXCEPTION 'Publication current configuration mismatch';
    END IF;
  ELSE
    -- Preserve the original approval binding even if that source is now stale.
    IF previous.action IS DISTINCT FROM 'approve'
      OR NEW.configuration_revision IS DISTINCT FROM previous.configuration_revision
      OR NEW.review_basis IS DISTINCT FROM previous.review_basis
      OR NEW.publication_basis IS DISTINCT FROM previous.publication_basis
      OR NEW.evidence IS DISTINCT FROM previous.evidence THEN
      RAISE EXCEPTION 'Publication revoke binding mismatch';
    END IF;
  END IF;
  RETURN NEW;
END; $guard$;
CREATE TRIGGER pc_customer_publication_guard BEFORE INSERT OR UPDATE OR DELETE
  ON __S__.pc_customer_publication_events FOR EACH ROW
  EXECUTE FUNCTION __S__.pc_customer_publication_guard();
CREATE TRIGGER pc_customer_publication_no_truncate BEFORE TRUNCATE
  ON __S__.pc_customer_publication_events FOR EACH STATEMENT
  EXECUTE FUNCTION __S__.pc_customer_publication_guard();
'''


def _schema(bind):
    value = bind.execute(text('SELECT current_schema()')).scalar_one()
    if type(value) is not str or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value):
        raise RuntimeError('Publication schema unavailable')
    return '"' + value + '"'


def upgrade():
    bind = op.get_bind()
    op.execute(UPGRADE_SQL.replace('__S__', _schema(bind)))


def downgrade():
    raise RuntimeError('Publication history must be preserved; explicit archival migration required')
