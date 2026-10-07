"""Capture migration SOURCE with a fake Alembic op. Never connect/apply DDL."""
import importlib.util
from pathlib import Path
from unittest.mock import patch
import unittest
import io

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.exc import InvalidRequestError


class Scalar:
    def __init__(self,value): self.value=value
    def scalar_one(self): return self.value


class Capture:
    def __init__(self,schema='public',kind='r'): self.schema,self.kind,self.sql=schema,kind,[]
    def get_bind(self): return self
    def execute(self,statement,params=None):
        clause=text(statement) if isinstance(statement,str) else statement
        compiled=clause.compile(dialect=DefaultDialect())
        compiled.construct_params(params)
        self.sql.append((str(compiled),params))
        return Scalar(self.schema if str(statement)=='SELECT current_schema()' else self.kind)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        p=Path(__file__).resolve().parents[1]/'db/migrations/versions/0126_opening_commerce.py'
        spec=importlib.util.spec_from_file_location('commerce_source_migration',p)
        self.module=importlib.util.module_from_spec(spec); spec.loader.exec_module(self.module)
    def captured(self,**kwargs):
        capture=Capture(**kwargs)
        with patch.object(self.module,'op',capture): self.module.upgrade()
        return capture,'\n'.join(x[0] for x in capture.sql)
    def test_revision_parent_source_only_and_downgrade_preserves_even_empty_tokens(self):
        self.assertEqual((self.module.revision,self.module.down_revision),('0126','0125'))
        with self.assertRaisesRegex(RuntimeError,'preserved'): self.module.downgrade()
    def test_required_ordinary_tables_are_checked_and_policy_lock_is_first(self):
        capture,sql=self.captured()
        self.assertIn('pg_advisory_xact_lock(1347375171,1)',capture.sql[0][0])
        self.assertEqual([p['table'] for s,p in capture.sql if p],['products','orders','payments','stock_reservations','stock_movements'])
        with self.assertRaises(RuntimeError): self.captured(kind='v')
        with self.assertRaises(RuntimeError): self.captured(schema='')
    def test_fresh_schema_quoting_literal_and_dollar_tags_are_independent(self):
        schema='odd"\'\\__SEQ__$commerce_product$'
        _,sql=self.captured(schema=schema)
        quoted='"'+schema.replace('"','""')+'"'
        self.assertIn('CREATE TABLE '+quoted+'.commerce_order_details',sql)
        self.assertIn('AS $commerce_product_$',sql)
        self.assertIn("E'"+(quoted+'.commerce_stock_revision_seq').replace("'","''").replace('\\','\\\\')+"'",sql)
    def test_guest_context_immutable_snapshot_operation_and_event_identities(self):
        _,sql=self.captured()
        for token in ('commerce_owner_contexts','credential_hash','owner_identity','UNIQUE(owner_scope,request_id)',
                      'UNIQUE(order_id,kind,request_id)','UNIQUE(provider,provider_environment,merchant_id,event_key)',
                      "OLD.state IN ('confirmed','declined','expired')",'NEW.snapshot','OLD.snapshot'):
            self.assertIn(token,sql)
        self.assertNotIn('SECURITY DEFINER',sql); self.assertNotIn('GRANT ',sql)
    def test_one_active_financial_operation_and_nullable_legacy_ledger_dedup(self):
        _,sql=self.captured()
        self.assertIn("WHERE state IN ('prepared','processing','unknown')",sql)
        for token in ('commerce_payment_operation_unique','commerce_stock_effect_unique','commerce_provider_result_unique',
                      'WHERE commerce_operation_id IS NOT NULL','Legacy payment writer cannot write commerce money'):
            self.assertIn(token,sql)
        self.assertNotIn("UPDATE orders SET",sql)
        self.assertNotIn("UPDATE payments SET",sql)
        self.assertNotIn('DROP TABLE',sql)
    def test_reservation_guard_serializes_product_and_protects_unknown_after_expiry(self):
        _,sql=self.captured()
        self.assertIn('WHERE p.product_code=NEW.product_code FOR UPDATE',sql)
        self.assertIn('available < claimed-previous+wanted',sql)
        self.assertIn("r.status='protected' OR (r.status='held' AND",sql)
        self.assertIn('BEFORE INSERT OR UPDATE OR DELETE ON "public".stock_reservations',sql)
        self.assertIn('BEFORE INSERT OR UPDATE ON "public".products',sql)
        self.assertIn('Commerce reservations must be preserved',sql)
    def test_reservation_changes_bump_non_reusable_basis_and_no_business_defaults(self):
        _,sql=self.captured()
        self.assertIn('CACHE 1 NO CYCLE',sql)
        self.assertIn('AFTER INSERT OR UPDATE ON "public".stock_reservations',sql)
        self.assertIn('commerce_stock_revision=commerce_stock_revision',sql)
        for token in ('interval \'1 day\'','30000','stock_inbound_holds','pg_ref LIKE','UPDATE members','UPDATE users'):
            self.assertNotIn(token,sql)


class CompilerBoundaryTests(unittest.TestCase):
    def load(self,revision):
        folder=Path(__file__).resolve().parents[1]/'db/migrations/versions'
        path=next(folder.glob(revision+'_*.py'))
        spec=importlib.util.spec_from_file_location('compiler_migration_'+revision,path)
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        return module

    def test_capture_rejects_original_quoted_payment_missing_bind(self):
        capture=Capture()
        with self.assertRaisesRegex(InvalidRequestError,"bind parameter 'payment'"):
            capture.execute("SELECT ':payment'")
        self.assertEqual(capture.sql,[])

    def test_payment_escape_emits_identical_business_sql_without_bind(self):
        sql=self.load('0126').UPGRADE_SQL
        self.assertEqual(sql.count(r"'\:payment'"),1)
        original=sql.replace(r"'\:payment'","':payment'")
        compiled=text(sql).compile(dialect=DefaultDialect())
        self.assertEqual(compiled.params,{})
        self.assertEqual(compiled.construct_params(),{})
        self.assertEqual(str(compiled),original)
        old=text(original).compile(dialect=DefaultDialect())
        with self.assertRaisesRegex(InvalidRequestError,"bind parameter 'payment'"):
            old.construct_params()

    def test_actual_alembic_offline_string_conversion_preserves_payment_literal(self):
        sql=self.load('0126').UPGRADE_SQL
        buffer=io.StringIO()
        context=MigrationContext.configure(dialect=DefaultDialect(),opts={'as_sql':True,'output_buffer':buffer})
        Operations(context).execute(sql)
        self.assertEqual(buffer.getvalue(),sql.replace(r"'\:payment'","':payment'").strip()+';\n\n')

    def test_other_migration_compilers_preserve_original_sql_without_required_binds(self):
        for revision in ('0127','0128','0129'):
            with self.subTest(revision=revision):
                sql=self.load(revision).UPGRADE_SQL
                compiled=text(sql).compile(dialect=DefaultDialect())
                self.assertEqual(compiled.params,{})
                self.assertEqual(compiled.construct_params(),{})
                self.assertEqual(str(compiled),sql)
        self.assertIn("':allocate:'",self.load('0127').UPGRADE_SQL)

    def test_legitimate_preflight_parameters_remain_required_and_supplied(self):
        query=text('SELECT :schema, :table')
        values={'schema':'public','table':'products'}
        compiled=query.compile(dialect=DefaultDialect())
        self.assertEqual(compiled.construct_params(values),values)
        capture=Capture(); capture.execute(query,values)
        self.assertEqual(capture.sql,[(str(compiled),values)])
        with self.assertRaisesRegex(InvalidRequestError,"bind parameter 'table'"):
            capture.execute(query,{'schema':'public'})


if __name__=='__main__': unittest.main()
