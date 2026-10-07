"""SOURCE only: checked INTEGER widening and immutable internal approval history."""
import re

from alembic import op
from sqlalchemy import text

revision = '0130'
down_revision = '0129'
branch_labels = None
depends_on = None

UPGRADE_SQL = r'''
DO $preflight$
DECLARE e_oid oid; a_oid oid; e_col smallint; a_col smallint; source_col smallint;
        e_type oid; a_type oid; source_type oid; nullable boolean; has_default boolean;
BEGIN
  e_oid:=to_regclass('__S__.product_explanations');
  a_oid:=to_regclass('__S__.admin_operators');
  IF e_oid IS NULL OR a_oid IS NULL THEN RAISE EXCEPTION 'Part approval catalogs unavailable'; END IF;
  SELECT attnum,atttypid,NOT attnotnull,atthasdef INTO e_col,e_type,nullable,has_default
    FROM pg_catalog.pg_attribute WHERE attrelid=e_oid AND attname='approved_by' AND attnum>0 AND NOT attisdropped;
  SELECT attnum,atttypid INTO a_col,a_type FROM pg_catalog.pg_attribute
    WHERE attrelid=a_oid AND attname='operator_id' AND attnum>0 AND NOT attisdropped;
  SELECT attnum,atttypid INTO source_col,source_type FROM pg_catalog.pg_attribute
    WHERE attrelid=e_oid AND attname='source_product_code' AND attnum>0 AND NOT attisdropped;
  IF e_col IS NULL OR e_type IS DISTINCT FROM 'pg_catalog.int4'::regtype
    OR nullable IS DISTINCT FROM true OR has_default IS DISTINCT FROM false
    OR a_col IS NULL OR a_type IS DISTINCT FROM 'pg_catalog.int8'::regtype
    OR source_col IS NULL OR source_type IS DISTINCT FROM 'pg_catalog.int8'::regtype
    OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_constraint WHERE conrelid=a_oid AND contype='p'
      AND conkey=ARRAY[a_col]::smallint[])
    OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_constraint WHERE conrelid=e_oid AND contype='p'
      AND conkey=ARRAY[source_col]::smallint[])
    OR (SELECT count(*) FROM pg_catalog.pg_constraint WHERE conrelid=e_oid AND contype='f'
      AND e_col=ANY(conkey))<>1
    OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_constraint WHERE conrelid=e_oid AND contype='f'
      AND conkey=ARRAY[e_col]::smallint[] AND confrelid=a_oid AND confkey=ARRAY[a_col]::smallint[]
      AND confupdtype='a' AND confdeltype='a' AND confmatchtype='s' AND convalidated
      AND NOT condeferrable AND NOT condeferred) THEN
    RAISE EXCEPTION 'Part approval original INTEGER column, FK or BIGINT PK differs';
  END IF;
END; $preflight$;
ALTER TABLE __S__.product_explanations ALTER COLUMN approved_by TYPE BIGINT USING approved_by::bigint;

CREATE TABLE __S__.part_explanation_approval_events (
  source_product_code BIGINT NOT NULL REFERENCES __S__.product_explanations(source_product_code) CHECK(source_product_code>0),
  event_seq BIGINT NOT NULL CHECK(event_seq>0),
  request_id UUID NOT NULL UNIQUE,
  request_digest VARCHAR(64) NOT NULL CHECK(request_digest ~ '^[a-f0-9]{64}$'),
  action TEXT NOT NULL CHECK(action IN ('approve','revoke')),
  operator_id BIGINT NOT NULL REFERENCES __S__.admin_operators(operator_id) CHECK(operator_id>0),
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  note TEXT NOT NULL CHECK(length(note) BETWEEN 1 AND 3000 AND octet_length(note)<=12000 AND length(btrim(note))>0),
  approval_basis VARCHAR(64) NOT NULL CHECK(approval_basis ~ '^[a-f0-9]{64}$'),
  snapshot JSONB NOT NULL CHECK(jsonb_typeof(snapshot)='object'
    AND snapshot ?& ARRAY['source_product_code','product_code','content','source_snapshot','source_fingerprint',
      'status','approved_by','approved_at','updated_at','product_name','spec_source_text','sale_status','sale_price']
    AND snapshot->'source_product_code' IS NOT DISTINCT FROM to_jsonb(source_product_code)
    AND snapshot->>'status' IS NOT DISTINCT FROM 'approved'
    AND jsonb_typeof(snapshot->'product_code') IS NOT DISTINCT FROM 'number'
    AND jsonb_typeof(snapshot->'approved_by') IS NOT DISTINCT FROM 'number'
    AND jsonb_typeof(snapshot->'approved_at') IS NOT DISTINCT FROM 'string'),
  metadata_reset BOOLEAN NOT NULL CHECK(action='revoke' OR NOT metadata_reset),
  write_txid BIGINT NOT NULL DEFAULT txid_current() CHECK(write_txid>0),
  PRIMARY KEY(source_product_code,event_seq)
);

CREATE FUNCTION __S__.part_explanation_approval_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $guard$
DECLARE e record; p record; previous record; actor_row record;
BEGIN
  IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Part approval history is immutable'; END IF;
  PERFORM pg_advisory_xact_lock(hashtext('pc_configuration_copy'));
  SELECT * INTO e FROM __S__.product_explanations WHERE source_product_code=NEW.source_product_code FOR UPDATE;
  IF e.source_product_code IS NULL THEN RAISE EXCEPTION 'Part approval source missing'; END IF;
  SELECT * INTO previous FROM __S__.part_explanation_approval_events
    WHERE source_product_code=NEW.source_product_code ORDER BY event_seq DESC LIMIT 1;
  IF NEW.event_seq IS DISTINCT FROM coalesce(previous.event_seq,0)+1
    OR NEW.recorded_at IS DISTINCT FROM now() OR NEW.write_txid IS DISTINCT FROM txid_current() THEN
    RAISE EXCEPTION 'Part approval sequence or transaction mismatch';
  END IF;
  SELECT * INTO p FROM __S__.products WHERE product_code=e.product_code FOR SHARE;
  SELECT role,status INTO actor_row FROM __S__.admin_operators WHERE operator_id=NEW.operator_id FOR SHARE;
  IF actor_row.role IS NULL OR actor_row.role NOT IN ('owner','operator') OR actor_row.status IS DISTINCT FROM '활성' THEN
    RAISE EXCEPTION 'Part approval actor inactive';
  END IF;
  IF NEW.action='approve' THEN
    IF e.product_code IS NULL OR p.product_code IS NULL OR p.status IS DISTINCT FROM '판매중'
      OR e.status IS DISTINCT FROM 'approved' OR e.approved_by IS DISTINCT FROM NEW.operator_id
      OR e.approved_at IS DISTINCT FROM NEW.recorded_at OR e.updated_at IS DISTINCT FROM NEW.recorded_at
      OR NEW.snapshot->'product_code' IS DISTINCT FROM to_jsonb(e.product_code)
      OR NEW.snapshot->'content' IS DISTINCT FROM e.content
      OR NEW.snapshot->'source_snapshot' IS DISTINCT FROM e.source_snapshot
      OR NEW.snapshot->>'source_fingerprint' IS DISTINCT FROM e.source_fingerprint
      OR NEW.snapshot->'approved_by' IS DISTINCT FROM to_jsonb(e.approved_by)
      OR (NEW.snapshot->>'approved_at')::timestamptz IS DISTINCT FROM e.approved_at
      OR (NEW.snapshot->>'updated_at')::timestamptz IS DISTINCT FROM e.updated_at
      OR NEW.snapshot->>'product_name' IS DISTINCT FROM p.product_name
      OR NEW.snapshot->>'spec_source_text' IS DISTINCT FROM p.spec_source_text
      OR NEW.snapshot->>'sale_status' IS DISTINCT FROM p.status
      OR NEW.snapshot->>'sale_price' IS DISTINCT FROM p.sale_price::text THEN
      RAISE EXCEPTION 'Part approval current source mismatch';
    END IF;
  ELSE
    IF previous.action IS DISTINCT FROM 'approve' OR NEW.snapshot IS DISTINCT FROM previous.snapshot
      OR NEW.approval_basis IS DISTINCT FROM previous.approval_basis THEN
      RAISE EXCEPTION 'Part revoke requires latest exact approval';
    END IF;
    IF NEW.metadata_reset THEN
      IF e.status IS DISTINCT FROM 'draft' OR e.approved_by IS NOT NULL OR e.approved_at IS NOT NULL
        OR e.updated_at IS DISTINCT FROM NEW.recorded_at THEN
        RAISE EXCEPTION 'Part revoke native reset mismatch';
      END IF;
    ELSIF e.status='approved' AND e.approved_by=(previous.snapshot->>'approved_by')::bigint
      AND e.approved_at=(previous.snapshot->>'approved_at')::timestamptz THEN
      RAISE EXCEPTION 'Part revoke must reset its own native metadata';
    END IF;
  END IF;
  RETURN NEW;
END; $guard$;
CREATE TRIGGER part_explanation_approval_guard BEFORE INSERT OR UPDATE OR DELETE
  ON __S__.part_explanation_approval_events FOR EACH ROW EXECUTE FUNCTION __S__.part_explanation_approval_guard();
CREATE TRIGGER part_explanation_approval_no_truncate BEFORE TRUNCATE
  ON __S__.part_explanation_approval_events FOR EACH STATEMENT EXECUTE FUNCTION __S__.part_explanation_approval_guard();

-- A pending native approval cannot be committed without its exact event in the
-- same TX. Ordinary draft edits remain allowed; this is not a consumer gate.
CREATE FUNCTION __S__.part_explanation_metadata_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $complete$
DECLARE changed boolean;
BEGIN
  IF NEW.status='approved' THEN
    IF TG_OP='INSERT' THEN changed:=true;
    ELSE changed:=OLD.status IS DISTINCT FROM NEW.status OR OLD.approved_by IS DISTINCT FROM NEW.approved_by
      OR OLD.approved_at IS DISTINCT FROM NEW.approved_at;
    END IF;
    IF changed AND NOT EXISTS(SELECT 1 FROM __S__.part_explanation_approval_events x
      WHERE x.source_product_code=NEW.source_product_code AND x.action='approve' AND x.write_txid=txid_current()
      AND x.operator_id=NEW.approved_by AND x.recorded_at=NEW.approved_at
      AND x.snapshot->'content' IS NOT DISTINCT FROM NEW.content
      AND x.snapshot->'source_snapshot' IS NOT DISTINCT FROM NEW.source_snapshot
      AND x.snapshot->>'source_fingerprint' IS NOT DISTINCT FROM NEW.source_fingerprint
      AND x.snapshot->'product_code' IS NOT DISTINCT FROM to_jsonb(NEW.product_code)
      AND (x.snapshot->>'updated_at')::timestamptz IS NOT DISTINCT FROM NEW.updated_at) THEN
      RAISE EXCEPTION 'Part native approval requires same-transaction immutable event';
    END IF;
  END IF;
  RETURN NULL;
END; $complete$;
CREATE CONSTRAINT TRIGGER part_explanation_metadata_complete AFTER INSERT OR UPDATE ON __S__.product_explanations
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION __S__.part_explanation_metadata_guard();
'''


def _schema(bind):
    value = bind.execute(text('SELECT current_schema()')).scalar_one()
    if type(value) is not str or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value):
        raise RuntimeError('Part approval schema unavailable')
    return '"' + value + '"'


def upgrade():
    bind = op.get_bind()
    op.execute(UPGRADE_SQL.replace('__S__', _schema(bind)))


def downgrade():
    raise RuntimeError('Part approval history and BIGINT actor compatibility must be preserved; explicit archival migration required')
