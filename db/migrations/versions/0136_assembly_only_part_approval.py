"""Assembly-only parts (no retail product row) can carry explanation/photo approval.

Owner decision 2026-10-10: spec values are not a publication gate; missing data is
shown as unknown. 127201/127203 are BOM-only parts with product_code NULL and
content.availability_scope='assembly_only', so the 0130/0131 snapshot CHECKs and
guards that required a retail product blocked every PC that uses them.

Only the retail-product link is relaxed, and only for assembly_only rows. Photo
rights/provenance, immutability, sequence, actor and same-TX native checks stay.
"""
import re

from alembic import op
from sqlalchemy import text

revision = '0136'
down_revision = '0135'
branch_labels = None
depends_on = None

UPGRADE_SQL = r'''
DO $swap$
DECLARE name text;
BEGIN
  FOR name IN SELECT conname FROM pg_catalog.pg_constraint
      WHERE conrelid='__S__.part_explanation_approval_events'::regclass AND contype='c'
        AND pg_catalog.pg_get_constraintdef(oid) LIKE '%snapshot%product_code%' LOOP
    EXECUTE format('ALTER TABLE __S__.part_explanation_approval_events DROP CONSTRAINT %I', name);
  END LOOP;
  FOR name IN SELECT conname FROM pg_catalog.pg_constraint
      WHERE conrelid='__S__.part_photo_approval_events'::regclass AND contype='c'
        AND pg_catalog.pg_get_constraintdef(oid) LIKE '%snapshot%product_code%' LOOP
    EXECUTE format('ALTER TABLE __S__.part_photo_approval_events DROP CONSTRAINT %I', name);
  END LOOP;
END; $swap$;

ALTER TABLE __S__.part_explanation_approval_events ADD CONSTRAINT part_explanation_approval_events_snapshot_check
  CHECK(jsonb_typeof(snapshot)='object'
    AND snapshot ?& ARRAY['source_product_code','product_code','content','source_snapshot','source_fingerprint',
      'status','approved_by','approved_at','updated_at','product_name','spec_source_text','sale_status','sale_price']
    AND snapshot->'source_product_code' IS NOT DISTINCT FROM to_jsonb(source_product_code)
    AND snapshot->>'status' IS NOT DISTINCT FROM 'approved'
    AND (jsonb_typeof(snapshot->'product_code') IS NOT DISTINCT FROM 'number'
      OR (jsonb_typeof(snapshot->'product_code') IS NOT DISTINCT FROM 'null'
        AND snapshot->'content'->>'availability_scope' IS NOT DISTINCT FROM 'assembly_only'))
    AND jsonb_typeof(snapshot->'approved_by') IS NOT DISTINCT FROM 'number'
    AND jsonb_typeof(snapshot->'approved_at') IS NOT DISTINCT FROM 'string');

ALTER TABLE __S__.part_photo_approval_events ADD CONSTRAINT part_photo_approval_events_snapshot_check
  CHECK(jsonb_typeof(snapshot)='object'
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
    AND jsonb_typeof(snapshot->'model'->'product_code') IN ('number','null')
    AND snapshot->'provenance'->'product_code' IS NOT DISTINCT FROM snapshot->'model'->'product_code'
    AND snapshot->'provenance'->>'basis' IS NOT DISTINCT FROM source_basis
    AND snapshot->'provenance'->>'kind' IS NOT DISTINCT FROM 'registered_product_photo'
    AND jsonb_typeof(snapshot->'model'->'source_snapshot') IS NOT DISTINCT FROM 'object'
    AND jsonb_typeof(snapshot->'model'->'image_asset') IS NOT DISTINCT FROM 'object');

CREATE OR REPLACE FUNCTION __S__.part_explanation_approval_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $guard$
DECLARE e record; p record; previous record; actor_row record; assembly boolean;
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
  assembly:=e.product_code IS NULL AND e.content->>'availability_scope' IS NOT DISTINCT FROM 'assembly_only';
  IF NEW.action='approve' THEN
    IF (NOT assembly AND (e.product_code IS NULL OR p.product_code IS NULL OR p.status IS DISTINCT FROM '판매중'))
      OR e.status IS DISTINCT FROM 'approved' OR e.approved_by IS DISTINCT FROM NEW.operator_id
      OR e.approved_at IS DISTINCT FROM NEW.recorded_at OR e.updated_at IS DISTINCT FROM NEW.recorded_at
      OR NEW.snapshot->'product_code' IS DISTINCT FROM coalesce(to_jsonb(e.product_code),'null'::jsonb)
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

CREATE OR REPLACE FUNCTION __S__.part_explanation_metadata_guard() RETURNS trigger
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
      AND x.snapshot->'product_code' IS NOT DISTINCT FROM coalesce(to_jsonb(NEW.product_code),'null'::jsonb)
      AND (x.snapshot->>'updated_at')::timestamptz IS NOT DISTINCT FROM NEW.updated_at) THEN
      RAISE EXCEPTION 'Part native approval requires same-transaction immutable event';
    END IF;
  END IF;
  RETURN NULL;
END; $complete$;

CREATE OR REPLACE FUNCTION __S__.part_photo_approval_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $guard$
DECLARE e record; p record; previous record; actor_row record; model jsonb; asset jsonb; prefix text; assembly boolean;
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
  assembly:=e.product_code IS NULL AND e.content->>'availability_scope' IS NOT DISTINCT FROM 'assembly_only';
  IF e.status NOT IN ('draft','approved')
    OR (NOT assembly AND (e.product_code IS NULL OR p.product_code IS NULL OR p.status IS DISTINCT FROM '판매중'))
    OR model->'product_code' IS DISTINCT FROM coalesce(to_jsonb(e.product_code),'null'::jsonb)
    OR model->'source_snapshot' IS DISTINCT FROM e.source_snapshot
    OR model->>'source_fingerprint' IS DISTINCT FROM e.source_fingerprint
    OR model->>'product_name' IS DISTINCT FROM p.product_name OR model->>'spec_source_text' IS DISTINCT FROM p.spec_source_text
    OR model->>'sale_status' IS DISTINCT FROM p.status OR model->'image_url' IS DISTINCT FROM e.content->'image_url'
    OR asset IS DISTINCT FROM e.content->'image_asset'
    OR (e.source_fingerprint ~ '^[a-f0-9]{64}$') IS DISTINCT FROM true
    OR (NOT assembly AND (btrim(e.source_snapshot->>'name') IS DISTINCT FROM btrim(p.product_name)
      OR btrim(e.source_snapshot->>'spec') IS DISTINCT FROM btrim(p.spec_source_text)
      OR coalesce(length(btrim(p.product_name)),0)=0 OR coalesce(length(btrim(p.spec_source_text)),0)=0)) THEN
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
  RETURN NEW;
END; $guard$;
'''


def _schema(bind):
    value = bind.execute(text('SELECT current_schema()')).scalar_one()
    if type(value) is not str or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value):
        raise RuntimeError('Assembly-only approval schema unavailable')
    return '"' + value + '"'


def upgrade():
    bind = op.get_bind()
    op.execute(UPGRADE_SQL.replace('__S__', _schema(bind)))


def downgrade():
    raise RuntimeError('Approval history may already hold assembly-only events; explicit archival migration required')
