"""Capture new Alembic SOURCE only; no SQL parser, native schema or DDL proof."""
from pathlib import Path
from unittest.mock import patch
import importlib.util
import unittest

from tests.test_commerce_migration import Capture


class FulfillmentMigrationTests(unittest.TestCase):
    def setUp(self):
        path=Path(__file__).resolve().parents[1]/'db/migrations/versions/0127_commerce_fulfillment_persistence.py'
        spec=importlib.util.spec_from_file_location('physical_migration_source',path)
        self.module=importlib.util.module_from_spec(spec); spec.loader.exec_module(self.module)
    def capture(self,**kwargs):
        recorder=Capture(**kwargs)
        with patch.object(self.module,'op',recorder): self.module.upgrade()
        return recorder,'\n'.join(sql for sql,_ in recorder.sql)

    def test_chain_and_reverse_operation_preserve_original_keys_even_if_empty(self):
        self.assertEqual((self.module.revision,self.module.down_revision),('0127','0126'))
        with self.assertRaisesRegex(RuntimeError,'preserved'): self.module.downgrade()
        _,sql=self.capture(); self.assertNotIn('DROP ',sql)
        self.assertNotIn('DELETE FROM',sql); self.assertNotIn('UPDATE orders',sql)

    def test_ordinary_existing_source_tables_checked_and_schema_dollar_quoting_safe(self):
        recorder,sql=self.capture(schema='odd"\'\\$physical_scope$__S__')
        self.assertIn('pg_advisory_xact_lock(1347375171,1)',recorder.sql[0][0])
        self.assertEqual([params['table'] for _,params in recorder.sql if params],
            ['orders','products','stock_movements','refunds','admin_operators','commerce_order_details','commerce_payment_operations'])
        self.assertIn('"odd""\'\\$physical_scope$__S__".commerce_shipments',sql)
        self.assertIn('AS $physical_scope_$',sql)
        with self.assertRaises(RuntimeError): self.capture(kind='v')
        with self.assertRaises(RuntimeError): self.capture(schema='')

    def test_physical_uuid_namespace_is_separate_from_financial_fk_in_both_insert_directions(self):
        _,sql=self.capture()
        operations=sql.split('CREATE TABLE "public".commerce_physical_operations (',1)[1].split('CREATE UNIQUE INDEX',1)[0]
        self.assertNotIn('REFERENCES "public".commerce_payment_operations',operations)
        self.assertIn('operation_id UUID PRIMARY KEY',operations)
        self.assertIn('FOREIGN KEY(order_id,shipment_id)',operations)
        self.assertIn('BEFORE INSERT ON "public".commerce_payment_operations',sql)
        self.assertIn('BEFORE INSERT ON "public".commerce_physical_operations',sql)
        self.assertIn('pg_advisory_xact_lock(hashtext(NEW.operation_id::text),2)',sql)

    def test_whole_order_line_caps_link_to_real_sale_snapshot_and_preserve_prepared_unknown_claims(self):
        _,sql=self.capture()
        for token in ('REFERENCES "public".stock_movements(movement_id)',"m.movement_type<>'own_sale'",
                      'm.operation_order<>NEW.order_id',"':allocate:'||NEW.line_id",'d.snapshot',
                      'WHERE order_id=NEW.order_id AND line_id=NEW.line_id','total+NEW.qty>original_line.qty',
                      "WHERE state IN ('prepared','processing','unknown')",'FOR UPDATE OF x,o'):
            self.assertIn(token,sql)
        cap=sql.split('SELECT COALESCE(sum(qty::bigint),0)',1)[1].split('ELSIF',1)[0]
        self.assertNotIn("state='",cap); self.assertNotIn('LIMIT',cap)

    def test_immutable_request_evidence_result_and_line_identity_revision_guards_exist(self):
        _,sql=self.capture()
        for token in ('NEW.request,NEW.identity','OLD.request,OLD.identity',"OLD.state='applied'",
                      'NEW.revision<>OLD.revision+1',"TG_TABLE_NAME='commerce_shipment_lines'",
                      'NEW.line_basis','OLD.line_basis','NEW.tracking_evidence IS DISTINCT FROM OLD.tracking_evidence',
                      'Physical readiness scope mismatch','Physical records and allocation keys must be preserved',
                      'NEW.write_txid<>txid_current()',"jsonb_typeof(result->'ready')='boolean'"):
            self.assertIn(token,sql)
        self.assertIn('FOREIGN KEY(order_id,readiness_operation_id)',sql)
        # SQL CHECK treats UNKNOWN as passing: digest presence must therefore
        # be explicit rather than relying only on a regex over nullable text.
        self.assertIn("receipt->>'result_basis' IS NOT NULL",sql)
        self.assertIn("result->>'evidence_basis' IS NOT NULL",sql)
        self.assertIn('IS NOT DISTINCT FROM operation_id::text',sql)

    def test_source_creates_only_minimal_three_tables_no_money_stock_or_invented_business_defaults(self):
        _,sql=self.capture()
        self.assertEqual(sql.count('CREATE TABLE '),3)
        for token in ('UPDATE products','INSERT INTO payments','INSERT INTO stock_movements','UPDATE stock_reservations',
                      'GRANT ','SECURITY DEFINER','30000',"interval '1 day'",'CJ대한통운','ALTER TABLE "public".stock_movements'):
            self.assertNotIn(token,sql)
        for action in ('prepare_shipment','record_preparation_event','confirm_dispatch_ready','record_tracking','handoff','deliver'):
            self.assertIn("'"+action+"'",sql)


if __name__=='__main__': unittest.main()
