"""Distinguish provider generation from existing-image registration.

SOURCE/CODE-MOCK candidate only. No DB or storage execution was verified.
JSON shape is evidence metadata, not proof of bytes, rights or currentness.
"""
import re
from alembic import op
from sqlalchemy import text

revision = '0134'
down_revision = '0133'
branch_labels = None
depends_on = None

# Explicit v1 shape. Original source history and present registration binding
# are disjoint; actual actor/created_at remain the existing job columns.
PROVENANCE_SHAPE = {
    'version': 'pc-media-existing-import-v1',
    'original': {
        'source_sku': 'P<original SKU>', 'original_revision': 'positive JSON integer',
        'original_ref': 'exact original archive reference',
        'original_sha256': 'lowercase hex64', 'manifest_sha256': 'lowercase hex64',
        'qa_references': 'nonempty array of nonempty references',
        'reused_from': 'source SKU or JSON null',
        'reuse_exception_reference': 'reference or JSON null',
        'ssd_facts_reference': 'reference or JSON null',
        'generation_model': None, 'generation_actor': None,
        'generation_time': None, 'original_visual_basis': None,
    },
    'current_binding': {
        'sku': 'P<current SKU>', 'offer_id': 'current offer reference',
        'configuration_id': 'exact job configuration_id',
        'revision': 'positive JSON integer', 'case_product_code': 'positive JSON integer',
        'visual_basis': 'exact current job visual_basis',
        'review_basis': 'exact current job review_basis',
    },
}

UPGRADE_SQL = r'''
CREATE FUNCTION __S__.pc_media_import_provenance_valid(
 p jsonb, configuration text, visual text, review text
) RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $shape$
DECLARE original jsonb; current_binding jsonb; item jsonb; name text;
BEGIN
 IF (jsonb_typeof(p)='object'
     AND p ?& ARRAY['version','original','current_binding']
     AND p->>'version'='pc-media-existing-import-v1'
     AND jsonb_typeof(p->'version')='string'
     AND jsonb_typeof(p->'original')='object'
     AND jsonb_typeof(p->'current_binding')='object') IS DISTINCT FROM TRUE THEN
   RETURN false;
 END IF;
 original:=p->'original'; current_binding:=p->'current_binding';
 IF (original ?& ARRAY['source_sku','original_revision','original_ref','original_sha256',
       'manifest_sha256','qa_references','reused_from','reuse_exception_reference',
       'ssd_facts_reference','generation_model','generation_actor','generation_time','original_visual_basis']
     AND jsonb_typeof(original->'source_sku')='string'
     AND original->>'source_sku' ~ '^P[1-9][0-9]*$'
     AND jsonb_typeof(original->'original_revision')='number'
     AND original->>'original_revision' ~ '^[1-9][0-9]*$'
     AND jsonb_typeof(original->'original_ref')='string'
     AND length(btrim(original->>'original_ref'))>0
     AND jsonb_typeof(original->'original_sha256')='string'
     AND original->>'original_sha256' ~ '^[a-f0-9]{64}$'
     AND jsonb_typeof(original->'manifest_sha256')='string'
     AND original->>'manifest_sha256' ~ '^[a-f0-9]{64}$'
     AND jsonb_typeof(original->'qa_references')='array'
     AND original->'generation_model' IS NOT DISTINCT FROM 'null'::jsonb
     AND original->'generation_actor' IS NOT DISTINCT FROM 'null'::jsonb
     AND original->'generation_time' IS NOT DISTINCT FROM 'null'::jsonb
     AND original->'original_visual_basis' IS NOT DISTINCT FROM 'null'::jsonb
     AND current_binding ?& ARRAY['sku','offer_id','configuration_id','revision',
       'case_product_code','visual_basis','review_basis']
     AND jsonb_typeof(current_binding->'sku')='string'
     AND current_binding->>'sku' ~ '^P[1-9][0-9]*$'
     AND jsonb_typeof(current_binding->'offer_id')='string'
     AND length(btrim(current_binding->>'offer_id'))>0
     AND jsonb_typeof(current_binding->'revision')='number'
     AND current_binding->>'revision' ~ '^[1-9][0-9]*$'
     AND jsonb_typeof(current_binding->'case_product_code')='number'
     AND current_binding->>'case_product_code' ~ '^[1-9][0-9]*$'
     AND jsonb_typeof(current_binding->'configuration_id')='string'
     AND current_binding->'configuration_id' IS NOT DISTINCT FROM to_jsonb(configuration)
     AND jsonb_typeof(current_binding->'visual_basis')='string'
     AND current_binding->'visual_basis' IS NOT DISTINCT FROM to_jsonb(visual)
     AND jsonb_typeof(current_binding->'review_basis')='string'
     AND current_binding->'review_basis' IS NOT DISTINCT FROM to_jsonb(review)
 ) IS DISTINCT FROM TRUE THEN RETURN false; END IF;
 -- Array expansion happens only after the explicit array-type check above.
 IF jsonb_array_length(original->'qa_references')=0 THEN RETURN false; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(original->'qa_references') LOOP
   IF (jsonb_typeof(item)='string' AND length(btrim(item #>> '{}'))>0)
       IS DISTINCT FROM TRUE THEN RETURN false; END IF;
 END LOOP;
 FOR name IN SELECT unnest(ARRAY['reuse_exception_reference','ssd_facts_reference']) LOOP
   item:=original->name;
   IF (item='null'::jsonb OR (jsonb_typeof(item)='string' AND length(btrim(item #>> '{}'))>0))
       IS DISTINCT FROM TRUE THEN RETURN false; END IF;
 END LOOP;
 IF (original->'reused_from'='null'::jsonb OR
     (jsonb_typeof(original->'reused_from')='string' AND original->>'reused_from' ~ '^P[1-9][0-9]*$'))
     IS DISTINCT FROM TRUE THEN RETURN false; END IF;
 IF original->'reused_from'<>'null'::jsonb
     AND original->'reuse_exception_reference'='null'::jsonb THEN RETURN false; END IF;
 RETURN true;
END; $shape$;

ALTER TABLE __S__.pc_media_jobs
 ADD COLUMN origin_kind TEXT NOT NULL DEFAULT 'generated',
 ADD COLUMN import_provenance JSONB,
 ALTER COLUMN model DROP NOT NULL;

ALTER TABLE __S__.pc_media_jobs ADD CONSTRAINT pc_media_jobs_origin_provenance_check
 CHECK ((
   (origin_kind='generated' AND model IS NOT NULL AND import_provenance IS NULL)
   OR
   (origin_kind='existing_import' AND model IS NULL AND import_provenance IS NOT NULL
    AND __S__.pc_media_import_provenance_valid(import_provenance,configuration_id,visual_basis,review_basis))
 ) IS TRUE);
'''

DOWNGRADE_SQL = r'''
LOCK TABLE __S__.pc_media_jobs IN ACCESS EXCLUSIVE MODE;
DO $preserve$
BEGIN
 IF EXISTS(SELECT 1 FROM __S__.pc_media_jobs
     WHERE origin_kind IS DISTINCT FROM 'generated'
       OR import_provenance IS NOT NULL OR model IS NULL) THEN
   RAISE EXCEPTION 'Existing image import provenance must be preserved; downgrade refused';
 END IF;
END; $preserve$;
ALTER TABLE __S__.pc_media_jobs DROP CONSTRAINT pc_media_jobs_origin_provenance_check;
ALTER TABLE __S__.pc_media_jobs ALTER COLUMN model SET NOT NULL;
ALTER TABLE __S__.pc_media_jobs DROP COLUMN import_provenance, DROP COLUMN origin_kind;
DROP FUNCTION __S__.pc_media_import_provenance_valid(jsonb,text,text,text);
'''


def _schema(bind):
    value = bind.execute(text('SELECT current_schema()')).scalar_one()
    if type(value) is not str or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value):
        raise RuntimeError('PC media schema unavailable')
    return '"' + value + '"'


def upgrade():
    # Caller-owned Alembic transaction: no engine, commit or registration here.
    bind = op.get_bind()
    op.execute(UPGRADE_SQL.replace('__S__', _schema(bind)))


def downgrade():
    # Lock + guard + DDL must remain in the caller's single transaction.
    bind = op.get_bind()
    op.execute(DOWNGRADE_SQL.replace('__S__', _schema(bind)))
