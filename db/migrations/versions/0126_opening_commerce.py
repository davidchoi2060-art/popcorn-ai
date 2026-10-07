"""Commerce persistence SOURCE only. No legacy ownership/payment backfill.

Alembic owns the transaction. Technical stock tokens do not confirm sale stock.
Ordinary DML guards cannot protect disabled triggers, DDL or stale upward CSV
stock replacement. Those require the canonical stock adapter and route guards.
"""
import re

from alembic import op
from sqlalchemy import text

revision = '0126'
down_revision = '0125'
branch_labels = None
depends_on = None

UPGRADE_SQL = r'''
CREATE SEQUENCE __S__.commerce_stock_revision_seq AS BIGINT
  MINVALUE 1 MAXVALUE 9223372036854775807 CACHE 1 NO CYCLE;
ALTER TABLE __S__.products ADD COLUMN commerce_stock_revision BIGINT NOT NULL
  DEFAULT pg_catalog.nextval(E'__SEQ__'::pg_catalog.regclass)
  CHECK(commerce_stock_revision > 0);

CREATE TABLE __S__.commerce_owner_contexts (
  context_id UUID PRIMARY KEY,
  owner_scope VARCHAR(64) NOT NULL CHECK(owner_scope ~ '^[0-9a-f]{64}$'),
  owner_identity JSONB NOT NULL CHECK(jsonb_typeof(owner_identity)='object'),
  credential_hash VARCHAR(64) UNIQUE NOT NULL CHECK(credential_hash ~ '^[0-9a-f]{64}$'),
  expires_at BIGINT NOT NULL CHECK(expires_at >= 0),
  revoked_at BIGINT CHECK(revoked_at >= 0),
  created_at BIGINT NOT NULL CHECK(created_at >= 0)
);
CREATE TABLE __S__.commerce_order_details (
  order_id BIGINT PRIMARY KEY REFERENCES __S__.orders(order_id),
  context_id UUID NOT NULL REFERENCES __S__.commerce_owner_contexts(context_id),
  owner_scope VARCHAR(64) NOT NULL CHECK(owner_scope ~ '^[0-9a-f]{64}$'),
  owner_identity JSONB NOT NULL CHECK(jsonb_typeof(owner_identity)='object'),
  request_id UUID NOT NULL,
  request_basis VARCHAR(64) NOT NULL CHECK(request_basis ~ '^[0-9a-f]{64}$'),
  snapshot JSONB NOT NULL CHECK(jsonb_typeof(snapshot)='object'),
  policy_snapshot JSONB NOT NULL CHECK(jsonb_typeof(policy_snapshot)='object'),
  provider_binding JSONB CHECK(jsonb_typeof(provider_binding)='object'),
  states JSONB NOT NULL CHECK(jsonb_typeof(states)='object'),
  revision BIGINT NOT NULL CHECK(revision > 0),
  expires_at BIGINT NOT NULL CHECK(expires_at >= 0),
  write_txid BIGINT NOT NULL,
  UNIQUE(owner_scope,request_id)
);
CREATE INDEX commerce_orders_context_idx ON __S__.commerce_order_details(context_id,order_id);
CREATE TABLE __S__.commerce_payment_operations (
  operation_id UUID PRIMARY KEY,
  order_id BIGINT NOT NULL REFERENCES __S__.commerce_order_details(order_id),
  kind VARCHAR(10) NOT NULL CHECK(kind IN ('approve','cancel')),
  request_id UUID NOT NULL,
  request_basis VARCHAR(64) NOT NULL CHECK(request_basis ~ '^[0-9a-f]{64}$'),
  provider TEXT NOT NULL CHECK(length(provider)>0),
  provider_environment VARCHAR(4) NOT NULL CHECK(provider_environment IN ('test','live')),
  merchant_id TEXT NOT NULL CHECK(length(merchant_id)>0),
  original_operation_id UUID REFERENCES __S__.commerce_payment_operations(operation_id),
  state VARCHAR(12) NOT NULL CHECK(state IN ('prepared','processing','unknown','confirmed','declined','expired')),
  revision BIGINT NOT NULL CHECK(revision>0),
  operation JSONB NOT NULL CHECK(jsonb_typeof(operation)='object'),
  verification JSONB CHECK(jsonb_typeof(verification)='object'),
  provider_ref TEXT,
  write_txid BIGINT NOT NULL,
  CHECK(operation->>'state'=state AND (operation->>'revision')::bigint=revision),
  CHECK(operation->'spec'->>'operation_id'=operation_id::text),
  CHECK(operation->>'request_basis'=request_basis),
  CHECK((kind='approve' AND original_operation_id IS NULL) OR
        (kind='cancel' AND original_operation_id IS NOT NULL AND original_operation_id<>operation_id)),
  UNIQUE(order_id,kind,request_id)
);
CREATE UNIQUE INDEX commerce_active_financial_operation_unique
  ON __S__.commerce_payment_operations(order_id) WHERE state IN ('prepared','processing','unknown');
CREATE UNIQUE INDEX commerce_provider_result_unique ON __S__.commerce_payment_operations
  (provider,provider_environment,merchant_id,kind,provider_ref)
  WHERE state='confirmed' AND provider_ref IS NOT NULL;
CREATE TABLE __S__.commerce_payment_events (
  event_id BIGSERIAL PRIMARY KEY,
  operation_id UUID NOT NULL REFERENCES __S__.commerce_payment_operations(operation_id),
  provider TEXT NOT NULL,
  provider_environment VARCHAR(4) NOT NULL CHECK(provider_environment IN ('test','live')),
  merchant_id TEXT NOT NULL,
  event_key TEXT NOT NULL CHECK(length(event_key)>0),
  evidence_basis VARCHAR(64) NOT NULL CHECK(evidence_basis ~ '^[0-9a-f]{64}$'),
  verification JSONB NOT NULL CHECK(jsonb_typeof(verification)='object'),
  observed_at BIGINT NOT NULL CHECK(observed_at>=0),
  UNIQUE(provider,provider_environment,merchant_id,event_key)
);
ALTER TABLE __S__.payments ADD COLUMN commerce_operation_id UUID
  REFERENCES __S__.commerce_payment_operations(operation_id);
ALTER TABLE __S__.payments ADD COLUMN commerce_effect_key TEXT;
CREATE UNIQUE INDEX commerce_payment_operation_unique ON __S__.payments(commerce_operation_id)
  WHERE commerce_operation_id IS NOT NULL;
CREATE UNIQUE INDEX commerce_payment_effect_unique ON __S__.payments(commerce_effect_key)
  WHERE commerce_effect_key IS NOT NULL;
ALTER TABLE __S__.stock_movements ADD COLUMN commerce_operation_id UUID
  REFERENCES __S__.commerce_payment_operations(operation_id);
ALTER TABLE __S__.stock_movements ADD COLUMN commerce_effect_key TEXT;
CREATE UNIQUE INDEX commerce_stock_effect_unique ON __S__.stock_movements(commerce_effect_key)
  WHERE commerce_effect_key IS NOT NULL;
ALTER TABLE __S__.stock_reservations ADD COLUMN commerce_order_id BIGINT
  REFERENCES __S__.commerce_order_details(order_id);
ALTER TABLE __S__.stock_reservations ADD CONSTRAINT commerce_reservation_shape CHECK
  (commerce_order_id IS NULL OR (commerce_order_id=order_id AND qty>0 AND
    status IN ('held','protected','converted','released')));
CREATE UNIQUE INDEX commerce_reservation_product_unique
  ON __S__.stock_reservations(commerce_order_id,product_code) WHERE commerce_order_id IS NOT NULL;
CREATE INDEX commerce_reservation_active_idx ON __S__.stock_reservations(product_code,status,expires_at)
  WHERE commerce_order_id IS NOT NULL;

CREATE FUNCTION __S__.commerce_claimed(product bigint) RETURNS bigint
LANGUAGE sql VOLATILE SET search_path=pg_catalog AS $claim$
  SELECT COALESCE(sum(r.qty::bigint),0) FROM __S__.stock_reservations r
  WHERE r.product_code=product AND r.commerce_order_id IS NOT NULL
    AND (r.status='protected' OR (r.status='held' AND
         r.expires_at > (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')))
$claim$;
CREATE FUNCTION __S__.commerce_product_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $product$
BEGIN
  IF __S__.commerce_claimed(NEW.product_code)>0 AND
     COALESCE(NEW.stock_qty,0) < __S__.commerce_claimed(NEW.product_code) THEN
    RAISE EXCEPTION 'Commerce protected stock would be consumed';
  END IF;
  NEW.commerce_stock_revision := pg_catalog.nextval(E'__SEQ__'::pg_catalog.regclass);
  RETURN NEW;
END; $product$;
CREATE TRIGGER commerce_product_guard BEFORE INSERT OR UPDATE ON __S__.products
  FOR EACH ROW EXECUTE FUNCTION __S__.commerce_product_guard();

CREATE FUNCTION __S__.commerce_reservation_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $reservation$
DECLARE available bigint; claimed bigint; previous bigint:=0; wanted bigint:=0;
BEGIN
  IF TG_OP='DELETE' THEN
    IF OLD.commerce_order_id IS NOT NULL THEN
      RAISE EXCEPTION 'Commerce reservations must be preserved';
    END IF;
    RETURN OLD;
  END IF;
  IF TG_OP='UPDATE' AND OLD.commerce_order_id IS NOT NULL AND
    ROW(NEW.order_id,NEW.commerce_order_id,NEW.product_code,NEW.qty,NEW.expires_at)
    IS DISTINCT FROM ROW(OLD.order_id,OLD.commerce_order_id,OLD.product_code,OLD.qty,OLD.expires_at) THEN
    RAISE EXCEPTION 'Commerce reservation identity is immutable';
  END IF;
  IF NEW.commerce_order_id IS NULL THEN RETURN NEW; END IF;
  -- Writer already holds the complete sorted set. This also serializes ordinary
  -- direct reservation DML; arbitrary unsorted callers may deadlock and abort.
  SELECT COALESCE(p.stock_qty,0) INTO available FROM __S__.products p
    WHERE p.product_code=NEW.product_code FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Commerce reservation product missing'; END IF;
  claimed := __S__.commerce_claimed(NEW.product_code);
  IF TG_OP='UPDATE' AND (OLD.status='protected' OR
      (OLD.status='held' AND OLD.expires_at>(CURRENT_TIMESTAMP AT TIME ZONE 'UTC'))) THEN
    previous := OLD.qty;
  END IF;
  IF NEW.status='protected' OR (NEW.status='held' AND
      NEW.expires_at>(CURRENT_TIMESTAMP AT TIME ZONE 'UTC')) THEN wanted:=NEW.qty; END IF;
  IF available < claimed-previous+wanted THEN
    RAISE EXCEPTION 'Commerce reservation exceeds available stock';
  END IF;
  RETURN NEW;
END; $reservation$;
CREATE TRIGGER commerce_reservation_guard BEFORE INSERT OR UPDATE OR DELETE ON __S__.stock_reservations
  FOR EACH ROW EXECUTE FUNCTION __S__.commerce_reservation_guard();
CREATE FUNCTION __S__.commerce_reservation_revision() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $reserve_revision$
BEGIN
  IF NEW.commerce_order_id IS NOT NULL THEN
    -- The product BEFORE trigger allocates a fresh non-reusable token even for
    -- an unchanged quantity. Reserving/releasing therefore changes stock basis.
    UPDATE __S__.products SET commerce_stock_revision=commerce_stock_revision
      WHERE product_code=NEW.product_code;
  END IF;
  RETURN NEW;
END; $reserve_revision$;
CREATE TRIGGER commerce_reservation_revision AFTER INSERT OR UPDATE ON __S__.stock_reservations
  FOR EACH ROW EXECUTE FUNCTION __S__.commerce_reservation_revision();

CREATE FUNCTION __S__.commerce_history_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $history$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Commerce history must be preserved'; END IF;
  IF TG_TABLE_NAME='commerce_owner_contexts' THEN
    IF ROW(NEW.context_id,NEW.owner_scope,NEW.owner_identity,NEW.credential_hash,NEW.expires_at,NEW.created_at)
       IS DISTINCT FROM ROW(OLD.context_id,OLD.owner_scope,OLD.owner_identity,OLD.credential_hash,OLD.expires_at,OLD.created_at)
       OR OLD.revoked_at IS NOT NULL THEN RAISE EXCEPTION 'Commerce owner identity is immutable'; END IF;
  ELSIF TG_TABLE_NAME='commerce_order_details' THEN
    IF ROW(NEW.order_id,NEW.context_id,NEW.owner_scope,NEW.owner_identity,NEW.request_id,NEW.request_basis,
           NEW.snapshot,NEW.policy_snapshot,NEW.provider_binding,NEW.expires_at)
       IS DISTINCT FROM ROW(OLD.order_id,OLD.context_id,OLD.owner_scope,OLD.owner_identity,OLD.request_id,OLD.request_basis,
           OLD.snapshot,OLD.policy_snapshot,OLD.provider_binding,OLD.expires_at)
       OR NEW.revision<>OLD.revision+1 THEN RAISE EXCEPTION 'Commerce snapshot or revision changed'; END IF;
  ELSIF TG_TABLE_NAME='commerce_payment_operations' THEN
    IF ROW(NEW.operation_id,NEW.order_id,NEW.kind,NEW.request_id,NEW.request_basis,NEW.provider,
           NEW.provider_environment,NEW.merchant_id,NEW.original_operation_id,NEW.operation->'spec')
       IS DISTINCT FROM ROW(OLD.operation_id,OLD.order_id,OLD.kind,OLD.request_id,OLD.request_basis,OLD.provider,
           OLD.provider_environment,OLD.merchant_id,OLD.original_operation_id,OLD.operation->'spec')
       OR OLD.state IN ('confirmed','declined','expired') OR NEW.revision<>OLD.revision+1 THEN
      RAISE EXCEPTION 'Commerce operation identity or terminal result changed';
    END IF;
  ELSE RAISE EXCEPTION 'Commerce events are immutable';
  END IF;
  RETURN NEW;
END; $history$;
CREATE TRIGGER commerce_history_guard BEFORE UPDATE OR DELETE ON __S__.commerce_owner_contexts
  FOR EACH ROW EXECUTE FUNCTION __S__.commerce_history_guard();
CREATE TRIGGER commerce_history_guard BEFORE UPDATE OR DELETE ON __S__.commerce_order_details
  FOR EACH ROW EXECUTE FUNCTION __S__.commerce_history_guard();
CREATE TRIGGER commerce_history_guard BEFORE UPDATE OR DELETE ON __S__.commerce_payment_operations
  FOR EACH ROW EXECUTE FUNCTION __S__.commerce_history_guard();
CREATE TRIGGER commerce_history_guard BEFORE UPDATE OR DELETE ON __S__.commerce_payment_events
  FOR EACH ROW EXECUTE FUNCTION __S__.commerce_history_guard();

CREATE FUNCTION __S__.commerce_ledger_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $ledger$
DECLARE commercial boolean;
BEGIN
  IF TG_OP IN ('UPDATE','DELETE') THEN
    IF OLD.commerce_operation_id IS NOT NULL THEN RAISE EXCEPTION 'Commerce ledger is immutable'; END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  END IF;
  IF TG_TABLE_NAME='payments' THEN
    SELECT EXISTS(SELECT 1 FROM __S__.commerce_order_details WHERE order_id=NEW.order_id) INTO commercial;
    IF commercial AND (NEW.commerce_operation_id IS NULL OR NEW.commerce_effect_key IS NULL) THEN
      RAISE EXCEPTION 'Legacy payment writer cannot write commerce money';
    END IF;
    IF NEW.commerce_operation_id IS NOT NULL AND NOT EXISTS (
      SELECT 1 FROM __S__.commerce_payment_operations x WHERE x.operation_id=NEW.commerce_operation_id
      AND x.order_id=NEW.order_id AND NEW.pay_mode='own'
      AND NEW.commerce_effect_key=x.operation_id::text||'\:payment'
      AND ((x.kind='approve' AND NEW.status='승인' AND NEW.amount=(x.operation->'spec'->>'amount')::bigint)
        OR (x.kind='cancel' AND NEW.status='환불' AND NEW.amount=-(x.operation->'spec'->>'amount')::bigint))) THEN
      RAISE EXCEPTION 'Commerce payment scope mismatch';
    END IF;
  ELSIF (NEW.commerce_operation_id IS NULL) <> (NEW.commerce_effect_key IS NULL) THEN
    RAISE EXCEPTION 'Commerce stock effect identity required';
  END IF;
  RETURN NEW;
END; $ledger$;
CREATE TRIGGER commerce_ledger_guard BEFORE INSERT OR UPDATE OR DELETE ON __S__.payments
  FOR EACH ROW EXECUTE FUNCTION __S__.commerce_ledger_guard();
CREATE TRIGGER commerce_ledger_guard BEFORE INSERT OR UPDATE OR DELETE ON __S__.stock_movements
  FOR EACH ROW EXECUTE FUNCTION __S__.commerce_ledger_guard();
'''


def upgrade():
    op.execute('SELECT pg_catalog.pg_advisory_xact_lock(1347375171,1)')
    schema = op.get_bind().execute(text('SELECT current_schema()')).scalar_one()
    if type(schema) is not str or not schema:
        raise RuntimeError('Commerce requires the current application schema')
    quoted = '"' + schema.replace('"', '""') + '"'
    for table in ('products', 'orders', 'payments', 'stock_reservations', 'stock_movements'):
        found = op.get_bind().execute(text('''SELECT c.relkind FROM pg_catalog.pg_class c
          JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname=:schema AND c.relname=:table'''), dict(schema=schema, table=table)).scalar_one()
        if found != 'r':
            raise RuntimeError('Commerce requires ordinary existing tables')
    sequence = (quoted + '.commerce_stock_revision_seq').replace("'", "''").replace('\\', '\\\\')
    # One transaction; tokens are technical initialization, no ownership, money,
    # quantities or provider environment are inferred for any historical row.
    replacements = {'__S__': quoted, '__SEQ__': sequence}
    for name in ('claim','product','reservation','reserve_revision','history','ledger'):
        tag = '$commerce_' + name + '$'
        while tag in schema:
            tag = tag[:-1] + '_$'
        replacements['$' + name + '$'] = tag
    pattern = '|'.join(re.escape(marker) for marker in replacements)
    op.execute(re.sub(pattern, lambda match: replacements[match[0]], UPGRADE_SQL))


def downgrade():
    # Even empty commerce tables may have issued basis tokens. Never dispose and
    # recreate them, which could validate an old preview (ABA).
    raise RuntimeError('Commerce records and basis tokens must be preserved')
