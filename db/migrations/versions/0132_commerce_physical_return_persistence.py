"""SOURCE only. Append physical return storage; preserve financial/shipping records.

No downgrade/backfill. Native PostgreSQL behavior must be verified separately.
"""
import re
from alembic import op
from sqlalchemy import text

revision = '0132'
down_revision = '0131'
branch_labels = None
depends_on = None

UPGRADE_SQL = r'''
CREATE TABLE __S__.commerce_return_cases (
 return_id BIGSERIAL PRIMARY KEY,
 order_id BIGINT NOT NULL REFERENCES __S__.commerce_order_details(order_id),
 revision BIGINT NOT NULL CHECK(revision>0), write_txid BIGINT NOT NULL CHECK(write_txid>0),
 UNIQUE(order_id,return_id)
);
CREATE TABLE __S__.commerce_return_lines (
 return_line_id BIGSERIAL PRIMARY KEY, order_id BIGINT NOT NULL, return_id BIGINT NOT NULL,
 shipment_id BIGINT NOT NULL, line_id TEXT NOT NULL CHECK(length(line_id)>0),
 sale_movement_id BIGINT NOT NULL REFERENCES __S__.stock_movements(movement_id),
 product_code BIGINT NOT NULL REFERENCES __S__.products(product_code),
 claimed_qty INTEGER NOT NULL CHECK(claimed_qty>0),
 collected_qty INTEGER NOT NULL DEFAULT 0, received_qty INTEGER NOT NULL DEFAULT 0,
 inspected_qty INTEGER NOT NULL DEFAULT 0, resellable_qty INTEGER NOT NULL DEFAULT 0,
 collection_evidence JSONB, receipt_evidence JSONB, inspection_evidence JSONB,
 UNIQUE(order_id,return_id,return_line_id), UNIQUE(return_id,shipment_id,line_id),
 FOREIGN KEY(order_id,return_id) REFERENCES __S__.commerce_return_cases(order_id,return_id),
 FOREIGN KEY(shipment_id,line_id) REFERENCES __S__.commerce_shipment_lines(shipment_id,line_id),
 CHECK(0<=resellable_qty AND resellable_qty<=inspected_qty AND inspected_qty<=received_qty
   AND received_qty<=collected_qty AND collected_qty<=claimed_qty),
 CHECK((collected_qty=0 AND collection_evidence IS NULL) OR
   (collected_qty>0 AND collection_evidence IS NOT NULL AND jsonb_typeof(collection_evidence)='object')),
 CHECK((received_qty=0 AND receipt_evidence IS NULL) OR
   (received_qty>0 AND receipt_evidence IS NOT NULL AND jsonb_typeof(receipt_evidence)='object')),
 CHECK((inspected_qty=0 AND inspection_evidence IS NULL) OR
   (inspected_qty>0 AND inspection_evidence IS NOT NULL AND jsonb_typeof(inspection_evidence)='object'))
);
CREATE TABLE __S__.commerce_return_operations (
 operation_id UUID PRIMARY KEY, order_id BIGINT NOT NULL, return_id BIGINT NOT NULL,
 contract TEXT NOT NULL, action TEXT NOT NULL,
 actor_id BIGINT NOT NULL REFERENCES __S__.admin_operators(operator_id) CHECK(actor_id>0),
 owner_scope VARCHAR(64) NOT NULL CHECK(owner_scope ~ '^[0-9a-f]{64}$'),
 wire_intent JSONB NOT NULL CHECK(jsonb_typeof(wire_intent)='object'),
 request_basis VARCHAR(64) NOT NULL CHECK(request_basis ~ '^[0-9a-f]{64}$'),
 request JSONB NOT NULL CHECK(jsonb_typeof(request)='object'),
 identity JSONB NOT NULL CHECK(jsonb_typeof(identity)='object'),
 state TEXT NOT NULL CHECK(state IN ('prepared','processing','unknown','applied')),
 revision BIGINT NOT NULL CHECK(revision>0), result JSONB, receipt JSONB,
 write_txid BIGINT NOT NULL CHECK(write_txid>0), UNIQUE(order_id,return_id,operation_id),
 FOREIGN KEY(order_id,return_id) REFERENCES __S__.commerce_return_cases(order_id,return_id),
 CHECK((contract='commerce_physical_return_intake_v1' AND action IN
   ('create_case','record_collection','record_receipt')) OR
   (contract='commerce_physical_return_plan_v1' AND action IN ('inspect','restore'))),
 CHECK((state='applied' AND result IS NOT NULL AND receipt IS NOT NULL
   AND jsonb_typeof(result)='object' AND jsonb_typeof(receipt)='object') OR
   (state<>'applied' AND result IS NULL AND receipt IS NULL)),
 CHECK(identity ?& ARRAY['contract','operation_id','actor_id','order_no','return_id','action','owner_scope','request_basis']),
 CHECK(wire_intent ?& ARRAY['operation_id','order_no','action','return_id','expected_order_basis',
   'expected_order_revision','expected_return_revision','expected_history_token','expected_policy_basis','lines']),
 CHECK(identity->>'operation_id' IS NOT DISTINCT FROM operation_id::text
   AND identity->>'contract' IS NOT DISTINCT FROM contract AND identity->>'action' IS NOT DISTINCT FROM action
   AND identity->>'owner_scope' IS NOT DISTINCT FROM owner_scope AND identity->>'request_basis' IS NOT DISTINCT FROM request_basis
   AND (identity->>'actor_id')::bigint IS NOT DISTINCT FROM actor_id
   AND (identity->>'return_id')::bigint IS NOT DISTINCT FROM return_id),
 CHECK(wire_intent->>'operation_id' IS NOT DISTINCT FROM operation_id::text
   AND wire_intent->>'action' IS NOT DISTINCT FROM action AND jsonb_typeof(wire_intent->'lines')='array'),
 CHECK((jsonb_typeof(identity->'actor_id')='number' AND jsonb_typeof(identity->'return_id')='number'
   AND (wire_intent->>'expected_order_revision')::bigint>0
   AND jsonb_typeof(request->'proofs')='object'
   AND ((action IN ('create_case','record_collection','record_receipt')
      AND request->'command' IS NOT DISTINCT FROM wire_intent AND request->>'request_basis' IS NOT DISTINCT FROM request_basis
      AND (request->>'actor_id')::bigint IS NOT DISTINCT FROM actor_id
      AND request->'observation'->>'state'='confirmed' AND request->'observation'->>'source'='operator_record'
      AND request->'observation'->>'action' IS NOT DISTINCT FROM action
      AND (request->'observation'->>'actor_id')::bigint IS NOT DISTINCT FROM actor_id
      AND jsonb_typeof(request->'source_lines')='array') OR
     (action IN ('inspect','restore') AND request->'core_request'->>'operation_id' IS NOT DISTINCT FROM operation_id::text
      AND request->'core_request'->>'action' IS NOT DISTINCT FROM action
      AND request->'core_request'->>'request_basis' IS NOT DISTINCT FROM request_basis
      AND request->'core_request'->'lines' IS NOT DISTINCT FROM wire_intent->'lines'
      AND (request->'core_request'->>'actor_id')::bigint IS NOT DISTINCT FROM actor_id))) IS TRUE),
 CHECK(state<>'applied' OR (result ?& ARRAY['action','return_id','order_revision','return_revision','lines','evidence_basis','core_result']
   AND receipt ?& ARRAY['operation_id','request_basis','result_basis','storage_basis','core_result_basis','commit_id','write_txid']
   AND result->>'action' IS NOT DISTINCT FROM action AND (result->>'return_id')::bigint IS NOT DISTINCT FROM return_id
   AND receipt->>'operation_id' IS NOT DISTINCT FROM operation_id::text
   AND receipt->>'request_basis' IS NOT DISTINCT FROM request_basis
   AND (receipt->>'write_txid')::bigint IS NOT DISTINCT FROM write_txid
   AND (result->>'order_revision')::bigint>0 AND (result->>'return_revision')::bigint>0
   AND (receipt->>'result_basis') ~ '^[0-9a-f]{64}$' AND (receipt->>'storage_basis') ~ '^[0-9a-f]{64}$'
   AND (result->>'evidence_basis') ~ '^[0-9a-f]{64}$' AND jsonb_typeof(result->'lines')='array'))
 ,CHECK((state<>'applied' OR ((result->>'order_revision')::bigint>0 AND (result->>'return_revision')::bigint>0
   AND jsonb_typeof(result->'order_revision')='number' AND jsonb_typeof(result->'return_revision')='number'
   AND (receipt->>'commit_id')::uuid IS NOT NULL AND (receipt->>'write_txid')::bigint=write_txid
   AND receipt->>'result_basis' IS NOT NULL AND receipt->>'storage_basis' IS NOT NULL
   AND result->>'evidence_basis' IS NOT NULL AND jsonb_array_length(result->'lines')>0)) IS TRUE)
);
CREATE UNIQUE INDEX commerce_return_active_target ON __S__.commerce_return_operations(order_id,return_id)
 WHERE state IN ('prepared','processing','unknown');
CREATE UNIQUE INDEX commerce_return_applied_revision ON __S__.commerce_return_operations
 (return_id,((result->>'return_revision')::bigint)) WHERE state='applied';
CREATE TABLE __S__.commerce_return_restoration_effects (
 effect_key TEXT PRIMARY KEY, physical_operation_id UUID NOT NULL,
 order_id BIGINT NOT NULL, return_id BIGINT NOT NULL, return_line_id BIGINT NOT NULL,
 sale_movement_id BIGINT NOT NULL REFERENCES __S__.stock_movements(movement_id),
 product_code BIGINT NOT NULL REFERENCES __S__.products(product_code),
 qty INTEGER NOT NULL CHECK(qty>0),
 inspection_basis VARCHAR(64) NOT NULL CHECK(inspection_basis ~ '^[0-9a-f]{64}$'),
 policy_basis VARCHAR(64) NOT NULL CHECK(policy_basis ~ '^[0-9a-f]{64}$'),
 state TEXT NOT NULL CHECK(state IN ('prepared','processing','unknown','applied')),
 movement_id BIGINT UNIQUE, receipt JSONB, write_txid BIGINT NOT NULL CHECK(write_txid>0),
 UNIQUE(physical_operation_id,return_line_id), UNIQUE(physical_operation_id,effect_key),
 FOREIGN KEY(order_id,return_id,return_line_id) REFERENCES __S__.commerce_return_lines(order_id,return_id,return_line_id),
 FOREIGN KEY(order_id,return_id,physical_operation_id) REFERENCES __S__.commerce_return_operations(order_id,return_id,operation_id)
   DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(movement_id) REFERENCES __S__.stock_movements(movement_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(effect_key=physical_operation_id::text||':return:'||return_line_id::text),
 CHECK((state='applied' AND movement_id IS NOT NULL AND receipt IS NOT NULL AND jsonb_typeof(receipt)='object')
   OR (state<>'applied' AND movement_id IS NULL AND receipt IS NULL))
);
ALTER TABLE __S__.stock_movements ADD COLUMN physical_return_operation_id UUID,
 ADD COLUMN physical_return_effect_key TEXT,
 ADD CONSTRAINT commerce_return_stock_namespace CHECK
   ((physical_return_operation_id IS NULL AND physical_return_effect_key IS NULL) OR
    (physical_return_operation_id IS NOT NULL AND physical_return_effect_key IS NOT NULL
     AND commerce_operation_id IS NULL AND commerce_effect_key IS NULL AND movement_type='return'
     AND qty_delta>0 AND ref_kind='order' AND ref_id IS NOT NULL)),
 ADD CONSTRAINT commerce_return_stock_effect FOREIGN KEY(physical_return_operation_id,physical_return_effect_key)
   REFERENCES __S__.commerce_return_restoration_effects(physical_operation_id,effect_key) DEFERRABLE INITIALLY DEFERRED;
CREATE UNIQUE INDEX commerce_return_stock_effect_unique ON __S__.stock_movements(physical_return_operation_id,physical_return_effect_key)
 WHERE physical_return_operation_id IS NOT NULL;

CREATE FUNCTION __S__.commerce_return_uuid_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $uuid$
BEGIN
 PERFORM pg_advisory_xact_lock(hashtext(NEW.operation_id::text),2);
 IF (TG_TABLE_NAME<>'commerce_payment_operations' AND EXISTS
   (SELECT 1 FROM __S__.commerce_payment_operations WHERE operation_id=NEW.operation_id)) OR
   (TG_TABLE_NAME<>'commerce_physical_operations' AND EXISTS
   (SELECT 1 FROM __S__.commerce_physical_operations WHERE operation_id=NEW.operation_id)) OR
   (TG_TABLE_NAME<>'commerce_return_operations' AND EXISTS
   (SELECT 1 FROM __S__.commerce_return_operations WHERE operation_id=NEW.operation_id)) THEN
   RAISE EXCEPTION 'Financial shipping and return UUIDs are independent';
 END IF;
 RETURN NEW;
END; $uuid$;
CREATE TRIGGER commerce_return_uuid_guard BEFORE INSERT ON __S__.commerce_payment_operations
 FOR EACH ROW EXECUTE FUNCTION __S__.commerce_return_uuid_guard();
CREATE TRIGGER commerce_return_uuid_guard BEFORE INSERT ON __S__.commerce_physical_operations
 FOR EACH ROW EXECUTE FUNCTION __S__.commerce_return_uuid_guard();
CREATE TRIGGER commerce_return_uuid_guard BEFORE INSERT ON __S__.commerce_return_operations
 FOR EACH ROW EXECUTE FUNCTION __S__.commerce_return_uuid_guard();

CREATE FUNCTION __S__.commerce_return_scope_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $scope$
DECLARE detail RECORD; cargo RECORD; sale RECORD; claimed BIGINT;
BEGIN
 -- Whole product set, ascending, then order, then return: same writer order.
 PERFORM p.product_code FROM __S__.products p JOIN __S__.commerce_order_details d ON d.order_id=NEW.order_id
   WHERE p.product_code IN (SELECT (j->>'product_code')::bigint FROM jsonb_array_elements(d.snapshot->'lines') j)
   ORDER BY p.product_code FOR UPDATE OF p;
 PERFORM 1 FROM __S__.orders WHERE order_id=NEW.order_id FOR UPDATE;
 SELECT * INTO STRICT detail FROM __S__.commerce_order_details WHERE order_id=NEW.order_id FOR UPDATE;
 IF TG_TABLE_NAME='commerce_return_cases' THEN
   IF NEW.write_txid<>txid_current() THEN RAISE EXCEPTION 'Current return transaction required'; END IF;
 ELSE
   PERFORM 1 FROM __S__.commerce_return_cases WHERE return_id=NEW.return_id AND order_id=NEW.order_id FOR UPDATE;
 END IF;
 IF TG_TABLE_NAME='commerce_return_lines' THEN
   SELECT * INTO STRICT cargo FROM __S__.commerce_shipment_lines WHERE shipment_id=NEW.shipment_id AND line_id=NEW.line_id;
   SELECT * INTO STRICT sale FROM __S__.stock_movements WHERE movement_id=NEW.sale_movement_id;
   IF cargo.order_id<>NEW.order_id OR cargo.sale_movement_id<>NEW.sale_movement_id OR cargo.product_code<>NEW.product_code
     OR sale.product_code<>NEW.product_code OR sale.movement_type<>'own_sale' OR sale.qty_delta>=0
     OR sale.ref_kind<>'order' OR sale.ref_id<>NEW.order_id OR sale.commerce_operation_id IS NULL THEN
     RAISE EXCEPTION 'Return must bind original committed own sale and shipment cargo';
   END IF;
   SELECT COALESCE(sum(claimed_qty),0) INTO claimed FROM __S__.commerce_return_lines
     WHERE shipment_id=NEW.shipment_id AND line_id=NEW.line_id AND return_line_id<>NEW.return_line_id;
   IF claimed+NEW.claimed_qty>cargo.qty THEN RAISE EXCEPTION 'Return claims exceed cargo'; END IF;
 ELSIF TG_TABLE_NAME='commerce_return_operations' THEN
   IF NEW.write_txid<>txid_current() OR NEW.owner_scope<>detail.owner_scope OR
     NEW.identity->>'order_no' IS DISTINCT FROM (SELECT order_no FROM __S__.orders WHERE order_id=NEW.order_id)
     OR NEW.wire_intent->>'order_no' IS DISTINCT FROM NEW.identity->>'order_no' THEN
     RAISE EXCEPTION 'Return operation scope changed';
   END IF;
 END IF;
 RETURN NEW;
END; $scope$;
CREATE TRIGGER commerce_return_case_scope BEFORE INSERT OR UPDATE ON __S__.commerce_return_cases
 FOR EACH ROW EXECUTE FUNCTION __S__.commerce_return_scope_guard();
CREATE TRIGGER commerce_return_line_scope BEFORE INSERT OR UPDATE ON __S__.commerce_return_lines
 FOR EACH ROW EXECUTE FUNCTION __S__.commerce_return_scope_guard();
CREATE TRIGGER commerce_return_operation_scope BEFORE INSERT ON __S__.commerce_return_operations
 FOR EACH ROW EXECUTE FUNCTION __S__.commerce_return_scope_guard();

CREATE FUNCTION __S__.commerce_return_history_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $history$
BEGIN
 IF TG_OP IN ('DELETE','TRUNCATE') THEN RAISE EXCEPTION 'Return history must be preserved'; END IF;
 IF TG_TABLE_NAME='commerce_return_cases' THEN
   IF (NEW.order_id,NEW.return_id) IS DISTINCT FROM (OLD.order_id,OLD.return_id) OR NEW.revision<>OLD.revision+1
     OR NEW.write_txid<>txid_current() THEN RAISE EXCEPTION 'Return identity/revision immutable'; END IF;
 ELSIF TG_TABLE_NAME='commerce_return_lines' THEN
   IF (NEW.order_id,NEW.return_id,NEW.return_line_id,NEW.shipment_id,NEW.line_id,NEW.sale_movement_id,NEW.product_code,NEW.claimed_qty)
     IS DISTINCT FROM (OLD.order_id,OLD.return_id,OLD.return_line_id,OLD.shipment_id,OLD.line_id,OLD.sale_movement_id,OLD.product_code,OLD.claimed_qty)
     OR NEW.collected_qty<OLD.collected_qty OR NEW.received_qty<OLD.received_qty OR NEW.inspected_qty<OLD.inspected_qty THEN
     RAISE EXCEPTION 'Return line identity and observations cannot decrease';
   END IF;
   IF EXISTS(SELECT 1 FROM __S__.commerce_return_restoration_effects WHERE return_line_id=OLD.return_line_id)
     AND NEW IS DISTINCT FROM OLD THEN RAISE EXCEPTION 'Restoration inspection/history frozen'; END IF;
 ELSE RAISE EXCEPTION 'Return operation/effect history immutable';
 END IF;
 RETURN NEW;
END; $history$;
CREATE TRIGGER commerce_return_case_history BEFORE UPDATE OR DELETE ON __S__.commerce_return_cases
 FOR EACH ROW EXECUTE FUNCTION __S__.commerce_return_history_guard();
CREATE TRIGGER commerce_return_line_history BEFORE UPDATE OR DELETE ON __S__.commerce_return_lines
 FOR EACH ROW EXECUTE FUNCTION __S__.commerce_return_history_guard();
CREATE TRIGGER commerce_return_operation_history BEFORE UPDATE OR DELETE ON __S__.commerce_return_operations
 FOR EACH ROW EXECUTE FUNCTION __S__.commerce_return_history_guard();
CREATE TRIGGER commerce_return_effect_history BEFORE UPDATE OR DELETE ON __S__.commerce_return_restoration_effects
 FOR EACH ROW EXECUTE FUNCTION __S__.commerce_return_history_guard();
CREATE TRIGGER commerce_return_case_truncate BEFORE TRUNCATE ON __S__.commerce_return_cases
 FOR EACH STATEMENT EXECUTE FUNCTION __S__.commerce_return_history_guard();
CREATE TRIGGER commerce_return_line_truncate BEFORE TRUNCATE ON __S__.commerce_return_lines
 FOR EACH STATEMENT EXECUTE FUNCTION __S__.commerce_return_history_guard();
CREATE TRIGGER commerce_return_operation_truncate BEFORE TRUNCATE ON __S__.commerce_return_operations
 FOR EACH STATEMENT EXECUTE FUNCTION __S__.commerce_return_history_guard();
CREATE TRIGGER commerce_return_effect_truncate BEFORE TRUNCATE ON __S__.commerce_return_restoration_effects
 FOR EACH STATEMENT EXECUTE FUNCTION __S__.commerce_return_history_guard();
CREATE FUNCTION __S__.commerce_return_stock_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $stock$
BEGIN
 IF TG_OP<>'INSERT' AND OLD.physical_return_operation_id IS NOT NULL THEN
   RAISE EXCEPTION 'Physical return stock ledger immutable';
 END IF;
 IF TG_OP='UPDATE' AND (NEW.physical_return_operation_id,NEW.physical_return_effect_key)
   IS DISTINCT FROM (OLD.physical_return_operation_id,OLD.physical_return_effect_key) THEN
   RAISE EXCEPTION 'Stock ledger cannot acquire return identity';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END; $stock$;
CREATE TRIGGER commerce_return_stock_guard BEFORE INSERT OR UPDATE OR DELETE ON __S__.stock_movements
 FOR EACH ROW EXECUTE FUNCTION __S__.commerce_return_stock_guard();

CREATE FUNCTION __S__.commerce_return_final_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $final$
DECLARE oid BIGINT; bad BOOLEAN;
BEGIN
 IF TG_TABLE_NAME='stock_movements' THEN
   IF NEW.physical_return_operation_id IS NULL THEN RETURN NEW; END IF;
   oid:=NEW.ref_id;
 ELSE oid:=NEW.order_id;
 END IF;
 -- All states consume quantities, including prepared/processing/unknown.
 SELECT EXISTS(SELECT 1 FROM __S__.commerce_return_restoration_effects e
   JOIN __S__.commerce_return_lines l USING(return_line_id)
   JOIN __S__.commerce_return_operations x ON x.operation_id=e.physical_operation_id
   LEFT JOIN __S__.stock_movements m ON m.movement_id=e.movement_id
   WHERE e.order_id=oid AND (x.action<>'restore' OR e.state<>x.state OR e.return_id<>x.return_id
     OR e.sale_movement_id<>l.sale_movement_id OR e.product_code<>l.product_code
     OR e.inspection_basis IS DISTINCT FROM l.inspection_evidence->>'basis'
     OR e.policy_basis IS DISTINCT FROM x.wire_intent->>'expected_policy_basis'
     OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(x.wire_intent->'lines') j
       WHERE (j->>'return_line_id')::bigint=e.return_line_id AND (j->>'qty')::integer=e.qty)
     OR (e.state='applied' AND (m.movement_id IS NULL OR m.physical_return_operation_id IS DISTINCT FROM e.physical_operation_id
       OR m.physical_return_effect_key IS DISTINCT FROM e.effect_key OR m.product_code<>e.product_code
       OR m.qty_delta<>e.qty OR m.movement_type<>'return' OR m.ref_kind<>'order' OR m.ref_id<>oid
       OR (e.receipt->>'write_txid')::bigint IS DISTINCT FROM e.write_txid)))) INTO bad;
 IF bad THEN RAISE EXCEPTION 'Return final stock/effect binding mismatch'; END IF;
 IF EXISTS(SELECT 1 FROM __S__.commerce_return_restoration_effects e
   JOIN __S__.commerce_return_lines l USING(return_line_id) WHERE e.order_id=oid
   GROUP BY e.return_line_id,l.resellable_qty HAVING sum(e.qty)>l.resellable_qty) OR
   EXISTS(SELECT 1 FROM __S__.commerce_return_restoration_effects e JOIN __S__.stock_movements m
     ON m.movement_id=e.sale_movement_id WHERE e.order_id=oid GROUP BY e.sale_movement_id,m.qty_delta
     HAVING sum(e.qty)>-m.qty_delta) THEN RAISE EXCEPTION 'Return final remaining quantity exceeded'; END IF;
 IF EXISTS(SELECT 1 FROM __S__.commerce_return_operations x CROSS JOIN LATERAL
   jsonb_array_elements(x.wire_intent->'lines') j WHERE x.order_id=oid AND x.action='restore'
   AND NOT EXISTS(SELECT 1 FROM __S__.commerce_return_restoration_effects e
     WHERE e.physical_operation_id=x.operation_id AND e.return_line_id=(j->>'return_line_id')::bigint)) THEN
   RAISE EXCEPTION 'Return effect history incomplete'; END IF;
 IF EXISTS(SELECT 1 FROM __S__.commerce_return_cases r WHERE r.order_id=oid AND
   (r.revision<>(SELECT count(*) FROM __S__.commerce_return_operations x WHERE x.return_id=r.return_id AND x.state='applied')
    OR NOT EXISTS(SELECT 1 FROM __S__.commerce_return_operations x WHERE x.return_id=r.return_id AND x.action='create_case'
      AND x.state='applied' AND (x.result->>'return_revision')::bigint=1)
    OR NOT EXISTS(SELECT 1 FROM __S__.commerce_return_operations x WHERE x.return_id=r.return_id AND x.state='applied'
      AND (x.result->>'return_revision')::bigint=r.revision AND x.write_txid=r.write_txid))) THEN
   RAISE EXCEPTION 'Return final revision history incomplete'; END IF;
 IF EXISTS(SELECT 1 FROM __S__.commerce_return_operations x WHERE x.order_id=oid AND x.state='applied'
   AND ((x.result->>'return_revision')::bigint<>CASE WHEN x.action='create_case' THEN 1
       ELSE (x.wire_intent->>'expected_return_revision')::bigint+1 END
     OR (x.result->>'order_revision')::bigint<>(x.wire_intent->>'expected_order_revision')::bigint+1
     OR (x.result->>'order_revision')::bigint>(SELECT revision FROM __S__.commerce_order_details WHERE order_id=oid))) THEN
   RAISE EXCEPTION 'Return final order revision mismatch'; END IF;
 IF EXISTS(SELECT 1 FROM __S__.commerce_return_lines l CROSS JOIN LATERAL
   (VALUES ('record_collection',l.collection_evidence,l.collected_qty),
     ('record_receipt',l.receipt_evidence,l.received_qty),('inspect',l.inspection_evidence,l.inspected_qty))
     stage(action,proof,qty)
   LEFT JOIN LATERAL (SELECT x.request->'proofs'->l.return_line_id::text AS proof,j->>'qty' AS qty
     FROM __S__.commerce_return_operations x CROSS JOIN LATERAL jsonb_array_elements(x.result->'lines') j
     WHERE x.return_id=l.return_id AND x.state='applied' AND x.action=stage.action
       AND (j->>'return_line_id')::bigint=l.return_line_id
     ORDER BY (x.result->>'return_revision')::bigint DESC LIMIT 1) latest ON TRUE
   WHERE l.order_id=oid AND (stage.proof IS DISTINCT FROM latest.proof OR
     (stage.qty>0 AND (latest.qty::integer IS DISTINCT FROM stage.qty
       OR stage.proof->>'state' IS DISTINCT FROM 'confirmed'
       OR stage.proof->>'source' IS DISTINCT FROM CASE WHEN stage.action='inspect' THEN 'server_inspection' ELSE 'operator_record' END
       OR stage.proof->>'kind' IS DISTINCT FROM CASE stage.action WHEN 'inspect' THEN 'inspect'
         WHEN 'record_collection' THEN 'collect' ELSE 'receive' END
       OR (stage.proof->>'return_id')::bigint IS DISTINCT FROM l.return_id
       OR (stage.proof->>'return_line_id')::bigint IS DISTINCT FROM l.return_line_id
       OR (stage.proof->>'shipment_id')::bigint IS DISTINCT FROM l.shipment_id
       OR (stage.proof->>'sale_movement_id')::bigint IS DISTINCT FROM l.sale_movement_id)))) THEN
   RAISE EXCEPTION 'Return latest observation must bind immutable operation'; END IF;
 RETURN NEW;
END; $final$;
CREATE CONSTRAINT TRIGGER commerce_return_case_final AFTER INSERT OR UPDATE ON __S__.commerce_return_cases
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION __S__.commerce_return_final_guard();
CREATE CONSTRAINT TRIGGER commerce_return_line_final AFTER INSERT OR UPDATE ON __S__.commerce_return_lines
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION __S__.commerce_return_final_guard();
CREATE CONSTRAINT TRIGGER commerce_return_operation_final AFTER INSERT ON __S__.commerce_return_operations
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION __S__.commerce_return_final_guard();
CREATE CONSTRAINT TRIGGER commerce_return_effect_final AFTER INSERT ON __S__.commerce_return_restoration_effects
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION __S__.commerce_return_final_guard();
CREATE CONSTRAINT TRIGGER commerce_return_stock_final AFTER INSERT ON __S__.stock_movements
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION __S__.commerce_return_final_guard();
'''


def upgrade():
    op.execute('SELECT pg_catalog.pg_advisory_xact_lock(1347375171,1)')
    schema = op.get_bind().execute(text('SELECT current_schema()')).scalar_one()
    if type(schema) is not str or not schema: raise RuntimeError('Return storage requires current schema')
    for table in ('orders', 'products', 'stock_movements', 'admin_operators', 'commerce_order_details',
                  'commerce_payment_operations', 'commerce_shipments', 'commerce_shipment_lines', 'commerce_physical_operations'):
        kind = op.get_bind().execute(text('''SELECT c.relkind FROM pg_catalog.pg_class c
          JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:schema AND c.relname=:table'''),
          dict(schema=schema, table=table)).scalar_one()
        if kind != 'r': raise RuntimeError('Return storage requires ordinary existing tables')
    replacements = {'__S__': '"' + schema.replace('"', '""') + '"'}
    for name in ('uuid', 'scope', 'history', 'stock', 'final'):
        tag = '$return_' + name + '$'
        while tag in schema: tag = tag[:-1] + '_$'
        replacements['$' + name + '$'] = tag
    op.execute(re.sub('|'.join(re.escape(marker) for marker in replacements),
                      lambda match: replacements[match[0]], UPGRADE_SQL))


def downgrade():
    raise RuntimeError('Return cases, UUIDs, evidence and stock ledgers must be preserved')
