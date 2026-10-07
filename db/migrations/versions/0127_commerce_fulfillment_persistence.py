"""SOURCE only: physical shipment records; no financial/stock effects or backfill."""
from alembic import op
from sqlalchemy import text
import re

revision = '0127'
down_revision = '0126'
branch_labels = None
depends_on = None

UPGRADE_SQL = r'''
CREATE TABLE __S__.commerce_shipments (
  shipment_id BIGSERIAL PRIMARY KEY,
  order_id BIGINT NOT NULL REFERENCES __S__.commerce_order_details(order_id),
  revision BIGINT NOT NULL CHECK(revision>0),
  state TEXT NOT NULL CHECK(state IN ('준비','배송중','완료')),
  line_basis VARCHAR(64) NOT NULL CHECK(line_basis ~ '^[0-9a-f]{64}$'),
  carrier TEXT, tracking_no TEXT,
  tracking_evidence JSONB, handoff_evidence JSONB, delivery_evidence JSONB,
  readiness JSONB, readiness_operation_id UUID,
  write_txid BIGINT NOT NULL CHECK(write_txid>0),
  UNIQUE(order_id,shipment_id),
  CHECK((readiness IS NULL)=(readiness_operation_id IS NULL)),
  CHECK(readiness IS NULL OR jsonb_typeof(readiness)='object'),
  CHECK(tracking_evidence IS NULL OR jsonb_typeof(tracking_evidence)='object'),
  CHECK(handoff_evidence IS NULL OR jsonb_typeof(handoff_evidence)='object'),
  CHECK(delivery_evidence IS NULL OR jsonb_typeof(delivery_evidence)='object'),
  CHECK((state='준비' AND handoff_evidence IS NULL AND delivery_evidence IS NULL)
    OR (state='배송중' AND tracking_evidence IS NOT NULL AND handoff_evidence IS NOT NULL AND delivery_evidence IS NULL)
    OR (state='완료' AND tracking_evidence IS NOT NULL AND handoff_evidence IS NOT NULL AND delivery_evidence IS NOT NULL))
);
CREATE TABLE __S__.commerce_shipment_lines (
  order_id BIGINT NOT NULL,
  shipment_id BIGINT NOT NULL,
  line_id TEXT NOT NULL CHECK(length(line_id)>0),
  product_code BIGINT NOT NULL REFERENCES __S__.products(product_code),
  qty INTEGER NOT NULL CHECK(qty>0),
  sale_movement_id BIGINT NOT NULL REFERENCES __S__.stock_movements(movement_id),
  PRIMARY KEY(shipment_id,line_id),
  UNIQUE(shipment_id,sale_movement_id),
  FOREIGN KEY(order_id,shipment_id) REFERENCES __S__.commerce_shipments(order_id,shipment_id)
);
CREATE INDEX commerce_shipment_order_lines ON __S__.commerce_shipment_lines(order_id,line_id);
CREATE TABLE __S__.commerce_physical_operations (
  operation_id UUID PRIMARY KEY,
  order_id BIGINT NOT NULL REFERENCES __S__.commerce_order_details(order_id),
  shipment_id BIGINT NOT NULL,
  contract TEXT NOT NULL CHECK(contract IN ('commerce_fulfillment_preparation_v1','commerce_manual_fulfillment_v1')),
  action TEXT NOT NULL,
  actor_id BIGINT NOT NULL REFERENCES __S__.admin_operators(operator_id) CHECK(actor_id>0),
  owner_scope VARCHAR(64) NOT NULL CHECK(owner_scope ~ '^[0-9a-f]{64}$'),
  request_basis VARCHAR(64) NOT NULL CHECK(request_basis ~ '^[0-9a-f]{64}$'),
  request JSONB NOT NULL CHECK(jsonb_typeof(request)='object'),
  identity JSONB NOT NULL CHECK(jsonb_typeof(identity)='object'),
  state TEXT NOT NULL CHECK(state IN ('prepared','processing','unknown','applied')),
  revision BIGINT NOT NULL CHECK(revision>0),
  result JSONB, receipt JSONB,
  write_txid BIGINT NOT NULL CHECK(write_txid>0),
  UNIQUE(order_id,operation_id),
  FOREIGN KEY(order_id,shipment_id) REFERENCES __S__.commerce_shipments(order_id,shipment_id),
  CHECK((contract='commerce_fulfillment_preparation_v1' AND action IN
    ('prepare_shipment','record_preparation_event','confirm_dispatch_ready')) OR
    (contract='commerce_manual_fulfillment_v1' AND action IN ('record_tracking','handoff','deliver'))),
  CHECK((state='applied' AND jsonb_typeof(result)='object' AND jsonb_typeof(receipt)='object') OR
    (state<>'applied' AND result IS NULL AND receipt IS NULL)),
  CHECK(identity ?& ARRAY['contract','operation_id','actor_id','order_no','owner_scope','action','request_basis']),
  CHECK(request ?& ARRAY['operation_id','actor_id','order_no','action','request_basis','expected_order_revision','lines']),
  CHECK(state<>'applied' OR (result ?& ARRAY['action','shipment_id','order_revision','shipment_revision','order_state',
      'shipment_state','ready','evidence_basis','readiness_basis','core_result']
    AND receipt ?& ARRAY['operation_id','request_basis','result_basis','commit_id','write_txid']
    AND jsonb_typeof(result->'ready')='boolean')),
  CHECK(identity->>'operation_id' IS NOT DISTINCT FROM operation_id::text
    AND identity->>'contract' IS NOT DISTINCT FROM contract AND identity->>'action' IS NOT DISTINCT FROM action
    AND identity->>'owner_scope' IS NOT DISTINCT FROM owner_scope AND identity->>'request_basis' IS NOT DISTINCT FROM request_basis
    AND jsonb_typeof(identity->'actor_id')='number' AND (identity->>'actor_id')::bigint IS NOT DISTINCT FROM actor_id),
  CHECK(request->>'operation_id' IS NOT DISTINCT FROM operation_id::text AND request->>'action' IS NOT DISTINCT FROM action
    AND request->>'request_basis' IS NOT DISTINCT FROM request_basis AND jsonb_typeof(request->'actor_id')='number'
    AND (request->>'actor_id')::bigint IS NOT DISTINCT FROM actor_id),
  CHECK(state<>'applied' OR (jsonb_typeof(result->'shipment_id')='number'
    AND (result->>'shipment_id') ~ '^[1-9][0-9]*$' AND jsonb_typeof(result->'order_revision')='number'
    AND (result->>'order_revision') ~ '^[1-9][0-9]*$' AND jsonb_typeof(result->'shipment_revision')='number'
    AND (result->>'shipment_revision') ~ '^[1-9][0-9]*$'
    AND result->>'evidence_basis' IS NOT NULL AND (result->>'evidence_basis') ~ '^[0-9a-f]{64}$'
    AND receipt->>'result_basis' IS NOT NULL AND (receipt->>'result_basis') ~ '^[0-9a-f]{64}$'
    AND receipt->>'commit_id' IS NOT NULL
    AND jsonb_typeof(receipt->'write_txid')='number' AND (receipt->>'write_txid') ~ '^[1-9][0-9]*$'))
);
CREATE UNIQUE INDEX commerce_physical_active_target ON __S__.commerce_physical_operations(order_id,shipment_id)
  WHERE state IN ('prepared','processing','unknown');
CREATE INDEX commerce_physical_order_history ON __S__.commerce_physical_operations(order_id,operation_id);
ALTER TABLE __S__.commerce_shipments ADD CONSTRAINT commerce_shipment_readiness_operation
  FOREIGN KEY(order_id,readiness_operation_id) REFERENCES __S__.commerce_physical_operations(order_id,operation_id);

CREATE FUNCTION __S__.commerce_physical_uuid_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $uuid$
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext(NEW.operation_id::text),2);
  IF (TG_TABLE_NAME='commerce_physical_operations' AND EXISTS(SELECT 1 FROM __S__.commerce_payment_operations WHERE operation_id=NEW.operation_id))
    OR (TG_TABLE_NAME='commerce_payment_operations' AND EXISTS(SELECT 1 FROM __S__.commerce_physical_operations WHERE operation_id=NEW.operation_id)) THEN
    RAISE EXCEPTION 'Physical and financial UUIDs are independent';
  END IF;
  RETURN NEW;
END; $uuid$;
CREATE TRIGGER commerce_physical_uuid_guard BEFORE INSERT ON __S__.commerce_physical_operations
  FOR EACH ROW EXECUTE FUNCTION __S__.commerce_physical_uuid_guard();
CREATE TRIGGER commerce_physical_uuid_guard BEFORE INSERT ON __S__.commerce_payment_operations
  FOR EACH ROW EXECUTE FUNCTION __S__.commerce_physical_uuid_guard();

CREATE FUNCTION __S__.commerce_physical_scope_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $scope$
DECLARE d record; m record; original_line record; total bigint;
BEGIN
  SELECT x.order_id,x.owner_scope,o.order_no,x.snapshot INTO d FROM __S__.commerce_order_details x
    JOIN __S__.orders o USING(order_id) WHERE x.order_id=NEW.order_id FOR UPDATE OF x,o;
  IF NOT FOUND THEN RAISE EXCEPTION 'Physical commerce order missing'; END IF;
  IF TG_TABLE_NAME='commerce_shipment_lines' THEN
    SELECT v.*,p.kind,p.state,p.order_id AS operation_order INTO m FROM __S__.stock_movements v
      JOIN __S__.commerce_payment_operations p ON p.operation_id=v.commerce_operation_id
      WHERE v.movement_id=NEW.sale_movement_id;
    IF NOT FOUND OR m.movement_type<>'own_sale' OR m.qty_delta>=0 OR m.product_code<>NEW.product_code
      OR m.ref_kind<>'order' OR m.ref_id<>NEW.order_id OR m.operation_order<>NEW.order_id
      OR m.kind<>'approve' OR m.state<>'confirmed'
      OR m.commerce_effect_key<>m.commerce_operation_id::text||':allocate:'||NEW.line_id THEN
      RAISE EXCEPTION 'Physical original sale scope mismatch';
    END IF;
    SELECT l.* INTO original_line FROM jsonb_to_recordset(d.snapshot->'lines')
      AS l(line_id text,product_code bigint,qty integer) WHERE l.line_id=NEW.line_id;
    IF NOT FOUND OR original_line.product_code<>NEW.product_code OR original_line.qty<>-m.qty_delta THEN
      RAISE EXCEPTION 'Physical snapshot line mismatch';
    END IF;
    SELECT COALESCE(sum(qty::bigint),0) INTO total FROM __S__.commerce_shipment_lines
      WHERE order_id=NEW.order_id AND line_id=NEW.line_id;
    IF total+NEW.qty>original_line.qty THEN RAISE EXCEPTION 'Physical shipment allocation exceeded'; END IF;
  ELSIF TG_TABLE_NAME='commerce_physical_operations' THEN
    IF NEW.owner_scope IS DISTINCT FROM d.owner_scope OR NEW.request->>'order_no' IS DISTINCT FROM d.order_no
      OR NEW.identity->>'order_no' IS DISTINCT FROM d.order_no
      OR NEW.write_txid<>txid_current() OR EXISTS(SELECT 1 FROM __S__.commerce_payment_operations WHERE operation_id=NEW.operation_id) THEN
      RAISE EXCEPTION 'Physical operation identity mismatch';
    END IF;
    IF NEW.state='applied' AND ((NEW.result->>'shipment_id')::bigint IS DISTINCT FROM NEW.shipment_id
      OR NEW.result->>'action' IS DISTINCT FROM NEW.action OR NEW.receipt->>'operation_id' IS DISTINCT FROM NEW.operation_id::text
      OR NEW.receipt->>'request_basis' IS DISTINCT FROM NEW.request_basis
      OR (NEW.receipt->>'write_txid')::bigint IS DISTINCT FROM NEW.write_txid) THEN
      RAISE EXCEPTION 'Physical result reference mismatch';
    END IF;
  ELSIF TG_TABLE_NAME='commerce_shipments' THEN
    IF NEW.write_txid<>txid_current() THEN RAISE EXCEPTION 'Physical caller transaction mismatch'; END IF;
    IF TG_OP='INSERT' AND (NEW.revision<>1 OR NEW.state<>'준비' OR NEW.readiness IS NOT NULL
      OR NEW.tracking_evidence IS NOT NULL) THEN RAISE EXCEPTION 'Physical shipment must start prepared'; END IF;
    IF TG_OP='UPDATE' AND NOT EXISTS(SELECT 1 FROM __S__.commerce_physical_operations p
      WHERE p.order_id=NEW.order_id AND p.shipment_id=NEW.shipment_id AND p.state='applied'
        AND p.write_txid=txid_current() AND (p.result->>'shipment_revision')::bigint=NEW.revision
        AND p.result->>'shipment_state'=NEW.state) THEN RAISE EXCEPTION 'Physical shipment result missing'; END IF;
    IF NEW.readiness IS NOT NULL AND NOT EXISTS(SELECT 1 FROM __S__.commerce_physical_operations p
      WHERE p.order_id=NEW.order_id AND p.shipment_id=NEW.shipment_id AND p.operation_id=NEW.readiness_operation_id
        AND p.action='confirm_dispatch_ready' AND p.state='applied'
        AND p.result->>'readiness_basis'=NEW.readiness->>'basis'
        AND NEW.readiness->>'line_basis'=NEW.line_basis) THEN RAISE EXCEPTION 'Physical readiness scope mismatch'; END IF;
  END IF;
  RETURN NEW;
END; $scope$;

CREATE FUNCTION __S__.commerce_physical_history_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $history$
BEGIN
  IF TG_OP='DELETE' OR TG_TABLE_NAME='commerce_shipment_lines' THEN
    RAISE EXCEPTION 'Physical records and allocation keys must be preserved';
  ELSIF TG_TABLE_NAME='commerce_physical_operations' THEN
    IF ROW(NEW.operation_id,NEW.order_id,NEW.shipment_id,NEW.contract,NEW.action,NEW.actor_id,NEW.owner_scope,
      NEW.request_basis,NEW.request,NEW.identity) IS DISTINCT FROM
      ROW(OLD.operation_id,OLD.order_id,OLD.shipment_id,OLD.contract,OLD.action,OLD.actor_id,OLD.owner_scope,
      OLD.request_basis,OLD.request,OLD.identity) OR OLD.state='applied' OR NEW.revision<>OLD.revision+1 THEN
      RAISE EXCEPTION 'Physical request evidence or terminal result changed'; END IF;
  ELSIF ROW(NEW.shipment_id,NEW.order_id,NEW.line_basis) IS DISTINCT FROM ROW(OLD.shipment_id,OLD.order_id,OLD.line_basis)
    OR NEW.revision<>OLD.revision+1 OR OLD.state='완료'
    OR (OLD.tracking_evidence IS NOT NULL AND NEW.tracking_evidence IS DISTINCT FROM OLD.tracking_evidence)
    OR (OLD.handoff_evidence IS NOT NULL AND NEW.handoff_evidence IS DISTINCT FROM OLD.handoff_evidence)
    OR (OLD.delivery_evidence IS NOT NULL AND NEW.delivery_evidence IS DISTINCT FROM OLD.delivery_evidence) THEN
    RAISE EXCEPTION 'Physical shipment identity evidence or revision changed';
  END IF;
  RETURN NEW;
END; $history$;
CREATE TRIGGER commerce_physical_scope_guard BEFORE INSERT OR UPDATE ON __S__.commerce_shipments
  FOR EACH ROW EXECUTE FUNCTION __S__.commerce_physical_scope_guard();
CREATE TRIGGER commerce_physical_scope_guard BEFORE INSERT ON __S__.commerce_shipment_lines
  FOR EACH ROW EXECUTE FUNCTION __S__.commerce_physical_scope_guard();
CREATE TRIGGER commerce_physical_scope_guard BEFORE INSERT OR UPDATE ON __S__.commerce_physical_operations
  FOR EACH ROW EXECUTE FUNCTION __S__.commerce_physical_scope_guard();
CREATE TRIGGER commerce_physical_history_guard BEFORE UPDATE OR DELETE ON __S__.commerce_shipments
  FOR EACH ROW EXECUTE FUNCTION __S__.commerce_physical_history_guard();
CREATE TRIGGER commerce_physical_history_guard BEFORE UPDATE OR DELETE ON __S__.commerce_shipment_lines
  FOR EACH ROW EXECUTE FUNCTION __S__.commerce_physical_history_guard();
CREATE TRIGGER commerce_physical_history_guard BEFORE UPDATE OR DELETE ON __S__.commerce_physical_operations
  FOR EACH ROW EXECUTE FUNCTION __S__.commerce_physical_history_guard();
'''


def upgrade():
    op.execute('SELECT pg_catalog.pg_advisory_xact_lock(1347375171,1)')
    schema=op.get_bind().execute(text('SELECT current_schema()')).scalar_one()
    if type(schema) is not str or not schema: raise RuntimeError('Physical commerce requires current schema')
    for table in ('orders','products','stock_movements','refunds','admin_operators','commerce_order_details','commerce_payment_operations'):
        kind=op.get_bind().execute(text('''SELECT c.relkind FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname=:schema AND c.relname=:table'''),dict(schema=schema,table=table)).scalar_one()
        if kind!='r': raise RuntimeError('Physical commerce requires ordinary existing tables')
    replacements={'__S__':'"'+schema.replace('"','""')+'"'}
    for name in ('scope','history','uuid'):
        tag='$physical_'+name+'$'
        while tag in schema: tag=tag[:-1]+'_$'
        replacements['$'+name+'$']=tag
    op.execute(re.sub('|'.join(re.escape(marker) for marker in replacements),lambda match:replacements[match[0]],UPGRADE_SQL))


def downgrade():
    raise RuntimeError('Physical records, operation IDs and evidence must be preserved')
