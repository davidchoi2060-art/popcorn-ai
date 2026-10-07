"""SOURCE only: immutable registered-photo evidence, no native content update."""
import re

from alembic import op
from sqlalchemy import text

revision = '0131'
down_revision = '0130'
branch_labels = None
depends_on = None

UPGRADE_SQL = r'''
DO $preflight$
DECLARE e_oid oid; a_oid oid; p_oid oid; code_col smallint; actor_col smallint;
        linked_col smallint; product_col smallint; native_actor_col smallint;
BEGIN
  e_oid:=to_regclass('__S__.product_explanations');
  a_oid:=to_regclass('__S__.admin_operators'); p_oid:=to_regclass('__S__.products');
  IF e_oid IS NULL OR a_oid IS NULL OR p_oid IS NULL
    OR to_regclass('__S__.part_explanation_approval_events') IS NULL THEN
    RAISE EXCEPTION 'Photo approval requires original catalogs and 0130 history';
  END IF;
  SELECT attnum INTO code_col FROM pg_catalog.pg_attribute WHERE attrelid=e_oid
    AND attname='source_product_code' AND atttypid='pg_catalog.int8'::regtype AND attnotnull AND attnum>0 AND NOT attisdropped;
  SELECT attnum INTO actor_col FROM pg_catalog.pg_attribute WHERE attrelid=a_oid
    AND attname='operator_id' AND atttypid='pg_catalog.int8'::regtype AND attnotnull AND attnum>0 AND NOT attisdropped;
  SELECT attnum INTO product_col FROM pg_catalog.pg_attribute WHERE attrelid=p_oid
    AND attname='product_code' AND atttypid='pg_catalog.int8'::regtype AND attnotnull AND attnum>0 AND NOT attisdropped;
  SELECT attnum INTO linked_col FROM pg_catalog.pg_attribute WHERE attrelid=e_oid
    AND attname='product_code' AND atttypid='pg_catalog.int8'::regtype AND NOT attnotnull AND attnum>0 AND NOT attisdropped;
  SELECT attnum INTO native_actor_col FROM pg_catalog.pg_attribute WHERE attrelid=e_oid
    AND attname='approved_by' AND atttypid='pg_catalog.int8'::regtype AND NOT attnotnull AND attnum>0 AND NOT attisdropped;
  IF code_col IS NULL OR actor_col IS NULL OR product_col IS NULL OR linked_col IS NULL OR native_actor_col IS NULL
    OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_constraint WHERE conrelid=e_oid AND contype='p' AND conkey=ARRAY[code_col]::smallint[])
    OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_constraint WHERE conrelid=a_oid AND contype='p' AND conkey=ARRAY[actor_col]::smallint[])
    OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_constraint WHERE conrelid=p_oid AND contype='p' AND conkey=ARRAY[product_col]::smallint[])
    OR (SELECT count(*) FROM pg_catalog.pg_constraint WHERE conrelid=e_oid AND contype='f' AND linked_col=ANY(conkey))<>1
    OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_constraint WHERE conrelid=e_oid AND contype='f'
      AND conkey=ARRAY[linked_col]::smallint[] AND confrelid=p_oid AND confkey=ARRAY[product_col]::smallint[]
      AND confdeltype='n' AND confupdtype='a' AND confmatchtype='s' AND convalidated AND NOT condeferrable AND NOT condeferred)
    OR (SELECT count(*) FROM pg_catalog.pg_constraint WHERE conrelid=e_oid AND contype='f' AND native_actor_col=ANY(conkey))<>1
    OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_constraint WHERE conrelid=e_oid AND contype='f'
      AND conkey=ARRAY[native_actor_col]::smallint[] AND confrelid=a_oid AND confkey=ARRAY[actor_col]::smallint[]
      AND confdeltype='a' AND confupdtype='a' AND confmatchtype='s' AND convalidated AND NOT condeferrable AND NOT condeferred) THEN
    RAISE EXCEPTION 'Photo approval original BIGINT PK/link/native actor FK shape differs';
  END IF;
END; $preflight$;

CREATE TABLE __S__.part_photo_approval_events (
  source_product_code BIGINT NOT NULL REFERENCES __S__.product_explanations(source_product_code) CHECK(source_product_code>0),
  event_seq BIGINT NOT NULL CHECK(event_seq>0),
  request_id UUID NOT NULL UNIQUE,
  request_digest VARCHAR(64) NOT NULL CHECK(request_digest ~ '^[a-f0-9]{64}$'),
  action TEXT NOT NULL CHECK(action IN ('approve','revoke')),
  operator_id BIGINT NOT NULL REFERENCES __S__.admin_operators(operator_id) CHECK(operator_id>0),
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  note TEXT NOT NULL CHECK(length(note) BETWEEN 1 AND 3000 AND octet_length(note)<=12000 AND length(btrim(note))>0),
  source_basis VARCHAR(64) NOT NULL CHECK(source_basis ~ '^[a-f0-9]{64}$'),
  approval_basis VARCHAR(64) NOT NULL CHECK(approval_basis ~ '^[a-f0-9]{64}$'),
  snapshot JSONB NOT NULL CHECK(jsonb_typeof(snapshot)='object'
    AND snapshot ?& ARRAY['version','scope','model','provenance']
    AND snapshot->>'version' IS NOT DISTINCT FROM 'part-photo-approval-v1'
    AND snapshot->>'scope' IS NOT DISTINCT FROM 'registered_product_photo'
    AND jsonb_typeof(snapshot->'model') IS NOT DISTINCT FROM 'object'
    AND jsonb_typeof(snapshot->'provenance') IS NOT DISTINCT FROM 'object'
    AND snapshot->'model' ?& ARRAY['source_product_code','product_code','source_snapshot','source_fingerprint',
      'product_name','spec_source_text','sale_status','image_url','image_asset']
    AND snapshot->'provenance' ?& ARRAY['source_product_code','product_code','basis','kind','source_reference','rights_reference']
    AND snapshot->'model'->'source_product_code' IS NOT DISTINCT FROM to_jsonb(source_product_code)
    AND snapshot->'provenance'->'source_product_code' IS NOT DISTINCT FROM to_jsonb(source_product_code)
    AND jsonb_typeof(snapshot->'model'->'product_code') IS NOT DISTINCT FROM 'number'
    AND snapshot->'provenance'->'product_code' IS NOT DISTINCT FROM snapshot->'model'->'product_code'
    AND snapshot->'provenance'->>'basis' IS NOT DISTINCT FROM source_basis
    AND snapshot->'provenance'->>'kind' IS NOT DISTINCT FROM 'registered_product_photo'
    AND jsonb_typeof(snapshot->'model'->'source_snapshot') IS NOT DISTINCT FROM 'object'
    AND jsonb_typeof(snapshot->'model'->'image_asset') IS NOT DISTINCT FROM 'object'),
  write_txid BIGINT NOT NULL DEFAULT txid_current() CHECK(write_txid>0),
  PRIMARY KEY(source_product_code,event_seq)
);

CREATE FUNCTION __S__.part_photo_approval_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $guard$
DECLARE e record; p record; previous record; actor_row record; model jsonb; asset jsonb; prefix text;
BEGIN
  IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Photo approval history is immutable'; END IF;
  PERFORM pg_advisory_xact_lock(hashtext('pc_configuration_copy'));
  SELECT * INTO e FROM __S__.product_explanations WHERE source_product_code=NEW.source_product_code FOR UPDATE;
  IF e.source_product_code IS NULL THEN RAISE EXCEPTION 'Photo source missing'; END IF;
  SELECT * INTO previous FROM __S__.part_photo_approval_events
    WHERE source_product_code=NEW.source_product_code ORDER BY event_seq DESC LIMIT 1;
  IF NEW.event_seq IS DISTINCT FROM coalesce(previous.event_seq,0)+1
    OR NEW.recorded_at IS DISTINCT FROM now() OR NEW.write_txid IS DISTINCT FROM txid_current() THEN
    RAISE EXCEPTION 'Photo approval sequence or caller transaction mismatch';
  END IF;
  SELECT * INTO p FROM __S__.products WHERE product_code=e.product_code FOR SHARE;
  SELECT role,status INTO actor_row FROM __S__.admin_operators WHERE operator_id=NEW.operator_id FOR SHARE;
  IF actor_row.role IS NULL OR actor_row.role NOT IN ('owner','operator') OR actor_row.status IS DISTINCT FROM '활성' THEN
    RAISE EXCEPTION 'Photo approval actor inactive';
  END IF;
  IF NEW.action='revoke' THEN
    IF previous.action IS DISTINCT FROM 'approve' OR NEW.snapshot IS DISTINCT FROM previous.snapshot
      OR NEW.source_basis IS DISTINCT FROM previous.source_basis OR NEW.approval_basis IS DISTINCT FROM previous.approval_basis THEN
      RAISE EXCEPTION 'Photo revoke requires latest exact approval';
    END IF;
    RETURN NEW;
  END IF;
  model:=NEW.snapshot->'model'; asset:=model->'image_asset';
  IF e.status NOT IN ('draft','approved') OR e.product_code IS NULL OR p.product_code IS NULL
    OR p.status IS DISTINCT FROM '판매중'
    OR model->'product_code' IS DISTINCT FROM to_jsonb(e.product_code)
    OR model->'source_snapshot' IS DISTINCT FROM e.source_snapshot
    OR model->>'source_fingerprint' IS DISTINCT FROM e.source_fingerprint
    OR model->>'product_name' IS DISTINCT FROM p.product_name OR model->>'spec_source_text' IS DISTINCT FROM p.spec_source_text
    OR model->>'sale_status' IS DISTINCT FROM p.status OR model->'image_url' IS DISTINCT FROM e.content->'image_url'
    OR asset IS DISTINCT FROM e.content->'image_asset'
    OR (e.source_fingerprint ~ '^[a-f0-9]{64}$') IS DISTINCT FROM true
    OR btrim(e.source_snapshot->>'name') IS DISTINCT FROM btrim(p.product_name)
    OR btrim(e.source_snapshot->>'spec') IS DISTINCT FROM btrim(p.spec_source_text)
    OR coalesce(length(btrim(p.product_name)),0)=0 OR coalesce(length(btrim(p.spec_source_text)),0)=0 THEN
    RAISE EXCEPTION 'Photo approval current model differs';
  END IF;
  prefix:='products/'||NEW.source_product_code::text||'/'||left(asset->>'sha256',16)||'/';
  IF asset->>'bucket' IS DISTINCT FROM 'popcorn-ai-product-media-045e861b'
    OR ((asset->>'sha256') ~ '^[a-f0-9]{64}$') IS DISTINCT FROM true
    OR ((asset->>'detail_sha256') ~ '^[a-f0-9]{64}$') IS DISTINCT FROM true
    OR asset->>'detail_key' IS DISTINCT FROM prefix||'detail.png'
    OR asset->>'thumbnail_key' IS DISTINCT FROM prefix||'thumb.webp'
    OR ((asset->>'original_key')=ANY(ARRAY[prefix||'original.jpg',prefix||'original.png',prefix||'original.webp',prefix||'original.gif'])) IS DISTINCT FROM true
    OR coalesce(length(asset->>'prepared_at'),0)=0
    OR ((NEW.snapshot->'provenance'->>'source_reference') ~ '^[A-Za-z][A-Za-z0-9_.+-]*:[^[:space:]]+$') IS DISTINCT FROM true
    OR lower(split_part(NEW.snapshot->'provenance'->>'source_reference',':',1)) IN ('http','https','data','javascript')
    OR length(NEW.snapshot->'provenance'->>'source_reference')>500
    OR ((NEW.snapshot->'provenance'->>'rights_reference') ~ '^workroom:[^[:space:]]+@v[1-9][0-9]*:[a-f0-9]{64}$') IS DISTINCT FROM true
    OR length(NEW.snapshot->'provenance'->>'rights_reference')>500 THEN
    RAISE EXCEPTION 'Photo approval registered asset or provenance differs';
  END IF;
  -- PostgreSQL does not fetch storage or reproduce Python's original digest.
  -- SERVER code verifies current bytes and canonical hashes; read_current must
  -- revalidate them. This trigger is structural source/TX protection only.
  RETURN NEW;
END; $guard$;
CREATE TRIGGER part_photo_approval_guard BEFORE INSERT OR UPDATE OR DELETE
  ON __S__.part_photo_approval_events FOR EACH ROW EXECUTE FUNCTION __S__.part_photo_approval_guard();
CREATE TRIGGER part_photo_approval_no_truncate BEFORE TRUNCATE
  ON __S__.part_photo_approval_events FOR EACH STATEMENT EXECUTE FUNCTION __S__.part_photo_approval_guard();
'''


def _schema(bind):
    value = bind.execute(text('SELECT current_schema()')).scalar_one()
    if type(value) is not str or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value):
        raise RuntimeError('Photo approval schema unavailable')
    return '"' + value + '"'


def upgrade():
    bind = op.get_bind()
    op.execute(UPGRADE_SQL.replace('__S__', _schema(bind)))


def downgrade():
    raise RuntimeError('Photo approval history must be preserved; explicit archival migration required')
