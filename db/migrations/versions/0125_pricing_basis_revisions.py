"""Pricing basis tokens for ordinary row DML; source only, not yet applied.

Sequences may have gaps, but CACHE 1/NO CYCLE avoids reserved-block reversal.
No protection for disabled triggers, sequence reset, TRUNCATE/DDL, population
phantoms or arbitrary transactions that take product locks before policy locks.
Downgrade refuses to discard tokens: reapplication could validate old previews.
"""
import re

from alembic import op
from sqlalchemy import text

revision = "0125"
down_revision = "0124"
branch_labels = None
depends_on = None


def upgrade():
    # Alembic owns the transaction. Take policy before any table/product lock.
    op.execute("SELECT pg_catalog.pg_advisory_xact_lock(1347375171,1)")
    schema = op.get_bind().execute(text("SELECT current_schema()")).scalar_one()
    if type(schema) is not str or not schema:
        raise RuntimeError("Pricing basis migration requires the current application schema")
    quoted = '"' + schema.replace('"', '""') + '"'
    literal = schema.replace("\\", "\\\\").replace("'", "''")
    sequence = (quoted + '.pricing_basis_revision_seq').replace("\\", "\\\\").replace("'", "''")
    sql = r'''DO $verify$
    DECLARE name text;
    BEGIN
      FOREACH name IN ARRAY ARRAY['products','pricing_settings','categories','category_margin_policies'] LOOP
        IF pg_catalog.to_regclass(name) IS DISTINCT FROM
           pg_catalog.to_regclass(pg_catalog.format('%I.%I', E'__SCHEMA_LITERAL__', name)) THEN
          RAISE EXCEPTION 'Pricing basis tables must resolve in the current application schema';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_class c
           JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
           WHERE n.nspname=E'__SCHEMA_LITERAL__' AND c.relname=name AND c.relkind='r') THEN
          RAISE EXCEPTION 'Pricing basis requires existing ordinary tables';
        END IF;
      END LOOP;
    END; $verify$;

    LOCK TABLE __SCHEMA__.pricing_settings, __SCHEMA__.categories,
      __SCHEMA__.category_margin_policies, __SCHEMA__.products IN ACCESS EXCLUSIVE MODE;
    CREATE SEQUENCE __SCHEMA__.pricing_basis_revision_seq AS BIGINT
      INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START WITH 1 CACHE 1 NO CYCLE;
    ALTER TABLE __SCHEMA__.products ADD COLUMN pricing_basis_revision BIGINT;
    UPDATE __SCHEMA__.products SET pricing_basis_revision =
      pg_catalog.nextval(E'__SEQUENCE__'::pg_catalog.regclass);
    ALTER TABLE __SCHEMA__.products ALTER COLUMN pricing_basis_revision SET NOT NULL;
    ALTER TABLE __SCHEMA__.products ADD CONSTRAINT products_pricing_basis_revision_positive
      CHECK (pricing_basis_revision > 0);

    CREATE TABLE __SCHEMA__.pricing_basis_policy_revision (
      singleton SMALLINT PRIMARY KEY CHECK (singleton = 1),
      revision BIGINT NOT NULL CHECK (revision > 0)
    );
    INSERT INTO __SCHEMA__.pricing_basis_policy_revision(singleton,revision) VALUES (1,1);

    CREATE FUNCTION __SCHEMA__.pricing_basis_product_revision() RETURNS trigger
      LANGUAGE plpgsql SET search_path = pg_catalog AS $product$
    BEGIN
      IF TG_OP = 'INSERT' THEN
        NEW.pricing_basis_revision := pg_catalog.nextval(E'__SEQUENCE__'::pg_catalog.regclass);
      ELSIF TG_OP = 'UPDATE' THEN
        IF OLD.pricing_basis_revision IS NULL OR OLD.pricing_basis_revision <= 0 THEN
          RAISE EXCEPTION 'Missing or invalid product pricing basis revision';
        END IF;
        IF ROW(OLD.product_code,OLD.product_name,OLD.part_type,OLD.purchase_price,OLD.sale_price,
               OLD.status,OLD.stock_qty,OLD.locked_fields,OLD.category_id) IS DISTINCT FROM
           ROW(NEW.product_code,NEW.product_name,NEW.part_type,NEW.purchase_price,NEW.sale_price,
               NEW.status,NEW.stock_qty,NEW.locked_fields,NEW.category_id) THEN
          NEW.pricing_basis_revision := pg_catalog.nextval(E'__SEQUENCE__'::pg_catalog.regclass);
        ELSE
          NEW.pricing_basis_revision := OLD.pricing_basis_revision;
        END IF;
      ELSE
        RAISE EXCEPTION 'Unexpected pricing basis product trigger operation';
      END IF;
      RETURN NEW;
    END; $product$;
    CREATE TRIGGER pricing_basis_product_revision
      BEFORE INSERT OR UPDATE ON __SCHEMA__.products
      FOR EACH ROW EXECUTE FUNCTION __SCHEMA__.pricing_basis_product_revision();

    CREATE FUNCTION __SCHEMA__.pricing_basis_policy_guard() RETURNS trigger
      LANGUAGE plpgsql SET search_path = pg_catalog AS $guard$
    BEGIN
      PERFORM pg_catalog.pg_advisory_xact_lock(1347375171,1);
      IF (SELECT count(*) FROM __SCHEMA__.pricing_basis_policy_revision) <> 1
         OR NOT EXISTS (SELECT 1 FROM __SCHEMA__.pricing_basis_policy_revision
                        WHERE singleton=1 AND revision IS NOT NULL AND revision>0) THEN
        RAISE EXCEPTION 'Missing or invalid pricing basis policy revision';
      END IF;
      RETURN NULL;
    END; $guard$;

    CREATE FUNCTION __SCHEMA__.pricing_basis_policy_bump() RETURNS trigger
      LANGUAGE plpgsql SET search_path = pg_catalog AS $policy$
    DECLARE changed boolean; token bigint;
    BEGIN
      IF TG_TABLE_SCHEMA <> E'__SCHEMA_LITERAL__'
         OR TG_TABLE_NAME NOT IN ('pricing_settings','categories','category_margin_policies') THEN
        RAISE EXCEPTION 'Unexpected pricing basis policy schema';
      END IF;
      IF TG_OP IN ('INSERT','DELETE') THEN
        changed := true;
      ELSIF TG_OP = 'UPDATE' THEN
        CASE TG_TABLE_NAME
          WHEN 'pricing_settings' THEN
            changed := ROW(OLD.setting_id,OLD.card_fee_rate,OLD.margin_rate,OLD.effective_from)
              IS DISTINCT FROM ROW(NEW.setting_id,NEW.card_fee_rate,NEW.margin_rate,NEW.effective_from);
          WHEN 'categories' THEN
            changed := ROW(OLD.category_id,OLD.parent_id)
              IS DISTINCT FROM ROW(NEW.category_id,NEW.parent_id);
          WHEN 'category_margin_policies' THEN
            changed := ROW(OLD.category_id,OLD.margin_rate)
              IS DISTINCT FROM ROW(NEW.category_id,NEW.margin_rate);
          ELSE RAISE EXCEPTION 'Unexpected pricing basis policy table';
        END CASE;
      ELSE
        RAISE EXCEPTION 'Unexpected pricing basis policy trigger operation';
      END IF;
      IF changed THEN
        UPDATE __SCHEMA__.pricing_basis_policy_revision SET revision = revision + 1
          WHERE singleton = 1 AND revision > 0 RETURNING revision INTO token;
        IF NOT FOUND OR token IS NULL OR token <= 0 THEN
          RAISE EXCEPTION 'Missing or invalid pricing basis policy revision';
        END IF;
      END IF;
      RETURN NULL;
    END; $policy$;
'''
    # Identifiers/literals are quoted separately; no SECURITY DEFINER or grants.
    replacements = {'__SEQUENCE__': sequence, '__SCHEMA_LITERAL__': literal, '__SCHEMA__': quoted}
    for name in ('verify', 'product', 'guard', 'policy'):
        tag = '$pricing_basis_' + name + '$'
        while tag in schema:
            tag = tag[:-1] + '_$'
        replacements['$' + name + '$'] = tag
    pattern = '|'.join(re.escape(marker) for marker in replacements)
    sql = re.sub(pattern, lambda match: replacements[match[0]], sql)
    op.execute(sql)
    for table in ("pricing_settings", "categories", "category_margin_policies"):
        op.execute(f"CREATE TRIGGER pricing_basis_policy_guard BEFORE INSERT OR UPDATE OR DELETE ON {quoted}.{table} "
                   f"FOR EACH STATEMENT EXECUTE FUNCTION {quoted}.pricing_basis_policy_guard()")
        op.execute(f"CREATE TRIGGER pricing_basis_policy_bump AFTER INSERT OR UPDATE OR DELETE ON {quoted}.{table} "
                   f"FOR EACH ROW EXECUTE FUNCTION {quoted}.pricing_basis_policy_bump()")


def downgrade():
    raise RuntimeError("Pricing basis revisions must be preserved; token disposal and reinitialization could permit ABA")
