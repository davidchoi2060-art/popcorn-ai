"""Capture only: no Alembic database/native PostgreSQL execution."""
import importlib.util
from pathlib import Path
from unittest.mock import patch
import unittest
from tests.test_commerce_migration import Capture


class ReturnMigrationTests(unittest.TestCase):
    def setUp(self):
        path=Path(__file__).resolve().parents[1]/'db/migrations/versions/0132_commerce_physical_return_persistence.py'
        spec=importlib.util.spec_from_file_location('return_storage_source',path)
        self.module=importlib.util.module_from_spec(spec); spec.loader.exec_module(self.module)
    def captured(self,**kwargs):
        capture=Capture(**kwargs)
        with patch.object(self.module,'op',capture): self.module.upgrade()
        return capture,'\n'.join(v[0] for v in capture.sql)
    def test_revision_and_preservation(self):
        self.assertEqual((self.module.revision,self.module.down_revision),('0132','0131'))
        with self.assertRaisesRegex(RuntimeError,'preserved'): self.module.downgrade()
    def test_preflight_native_existing_tables_fail_closed(self):
        capture,_=self.captured(); self.assertIn('pg_advisory_xact_lock(1347375171,1)',capture.sql[0][0])
        self.assertEqual(len([p for _,p in capture.sql if p]),9)
        for kwargs in (dict(schema=''),dict(kind='v'),dict(kind='p')):
            with self.assertRaises(RuntimeError): self.captured(**kwargs)
    def test_schema_quoting_dollar_collision_no_security_privilege_or_backfill(self):
        schema='a"\'__S__$return_uuid$'; _,sql=self.captured(schema=schema)
        self.assertIn('CREATE TABLE "'+schema.replace('"','""')+'".commerce_return_cases',sql)
        self.assertIn('AS $return_uuid_$',sql)
        for text in ('SECURITY DEFINER','GRANT ','UPDATE orders SET','UPDATE payments SET','DROP TABLE','CREATE OR REPLACE'):
            self.assertNotIn(text,sql)
    def test_three_namespaces_same_advisory_lock_and_existing_guards_untouched(self):
        _,sql=self.captured()
        self.assertIn('pg_advisory_xact_lock(hashtext(NEW.operation_id::text),2)',sql)
        for table in ('commerce_payment_operations','commerce_physical_operations','commerce_return_operations'):
            self.assertIn('commerce_return_uuid_guard BEFORE INSERT ON "public".'+table,sql)
        self.assertNotIn('CREATE FUNCTION "public".commerce_physical_uuid_guard',sql)
    def test_fk_cycle_is_deferred_and_pair_namespace_mixing_rejected(self):
        _,sql=self.captured(); self.assertGreaterEqual(sql.count('DEFERRABLE INITIALLY DEFERRED'),8)
        for text in ('commerce_return_stock_namespace','commerce_operation_id IS NULL AND commerce_effect_key IS NULL',
                     'commerce_return_stock_effect_unique','UNIQUE(physical_operation_id,return_line_id)',
                     'FOREIGN KEY(order_id,return_id,return_line_id)','qty_delta>0'):
            self.assertIn(text,sql)
    def test_final_guard_whole_history_qty_unknown_and_ledger_bindings(self):
        _,sql=self.captured()
        for text in ('sum(e.qty)>l.resellable_qty','sum(e.qty)>-m.qty_delta','Return effect history incomplete',
                     'Return final revision history incomplete','m.physical_return_effect_key IS DISTINCT FROM e.effect_key',
                     'e.policy_basis IS DISTINCT FROM x.wire_intent','Return final order revision mismatch',
                     'Return latest observation must bind immutable operation'):
            self.assertIn(text,sql)
        caps=sql[sql.index('-- All states consume'):sql.index('Return final remaining quantity exceeded')]
        self.assertNotIn("WHERE state='applied'",caps)
    def test_histories_immutable_whole_product_order_lock_and_observation_limits(self):
        _,sql=self.captured()
        for text in ('ORDER BY p.product_code FOR UPDATE OF p','Return history must be preserved',
                     'Return operation/effect history immutable','Physical return stock ledger immutable',
                     'NEW.revision<>OLD.revision+1','received_qty<=collected_qty','collected_qty<=claimed_qty',
                     'Return claims exceed cargo','Restoration inspection/history frozen'):
            self.assertIn(text,sql)

    def test_truncate_exact_four_statement_guards_not_row_or_constraint(self):
        import re
        _,sql=self.captured()
        matches=re.findall(r'CREATE (CONSTRAINT )?TRIGGER (\w+) BEFORE TRUNCATE ON "public"\.(\w+)\s+FOR EACH (ROW|STATEMENT) EXECUTE FUNCTION "public"\.(\w+)\(\);',sql)
        self.assertEqual(len(matches),4)
        self.assertEqual({(table,mode,function) for constraint,name,table,mode,function in matches},
            {(table,'STATEMENT','commerce_return_history_guard') for table in
             ('commerce_return_cases','commerce_return_lines','commerce_return_operations','commerce_return_restoration_effects')})
        self.assertTrue(all(constraint=='' for constraint,name,table,mode,function in matches))
        self.assertEqual(len({name for constraint,name,table,mode,function in matches}),4)
    def test_truncate_and_delete_raise_before_any_old_new_dereference(self):
        import re
        _,sql=self.captured()
        function=sql[sql.index('CREATE FUNCTION "public".commerce_return_history_guard()'):sql.index('CREATE TRIGGER commerce_return_case_history')]
        body=function[function.index('BEGIN'):]
        self.assertRegex(body,r"BEGIN\s+IF TG_OP IN \('DELETE','TRUNCATE'\) THEN RAISE EXCEPTION 'Return history must be preserved'; END IF;")
        rejection=body.index("RAISE EXCEPTION 'Return history must be preserved'")
        self.assertGreater(body.index('NEW.'),rejection)
        self.assertGreater(body.index('OLD.'),rejection)
        for name in ('case','line','operation','effect'):
            self.assertIn('CREATE TRIGGER commerce_return_'+name+'_history BEFORE UPDATE OR DELETE',sql)
    def test_truncate_guard_schema_quote_history_dollar_collision_no_privilege_change(self):
        schema='a"__S__$return_history$'
        _,sql=self.captured(schema=schema); quoted='"'+schema.replace('"','""')+'"'
        self.assertIn('AS $return_history_$',sql)
        for name,table in (('case','commerce_return_cases'),('line','commerce_return_lines'),
                           ('operation','commerce_return_operations'),('effect','commerce_return_restoration_effects')):
            self.assertIn('CREATE TRIGGER commerce_return_'+name+'_truncate BEFORE TRUNCATE ON '+quoted+'.'+table+
                '\n FOR EACH STATEMENT EXECUTE FUNCTION '+quoted+'.commerce_return_history_guard();',sql)
        for forbidden in ('GRANT ','REVOKE ','SECURITY DEFINER','DISABLE TRIGGER','OWNER TO','CREATE OR REPLACE'):
            self.assertNotIn(forbidden,sql)



    def test_truncate_inverse_preserves_entire_original_ddl(self):
        import hashlib
        sql=self.module.UPGRADE_SQL
        new="IF TG_OP IN ('DELETE','TRUNCATE') THEN RAISE EXCEPTION 'Return history must be preserved'; END IF;"
        old="IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Return history must be preserved'; END IF;"
        self.assertEqual(sql.count(new),1); sql=sql.replace(new,old,1)
        for name,table in (('case','commerce_return_cases'),('line','commerce_return_lines'),
                           ('operation','commerce_return_operations'),('effect','commerce_return_restoration_effects')):
            added='CREATE TRIGGER commerce_return_'+name+'_truncate BEFORE TRUNCATE ON __S__.'+table+\
                '\n FOR EACH STATEMENT EXECUTE FUNCTION __S__.commerce_return_history_guard();\n'
            self.assertEqual(sql.count(added),1); sql=sql.replace(added,'',1)
        self.assertEqual(hashlib.sha256(sql.encode()).hexdigest(),'a0ef6454de1078688a52d6adb12b1dc68feca50a56fe5873b675731f2e8eb348')


if __name__=='__main__': unittest.main()
