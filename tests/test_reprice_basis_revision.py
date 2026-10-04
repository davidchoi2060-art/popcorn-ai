"""Migration SQL capture and helper SQL mocks; never execute PG/DDL.

The source-derived DML model checks the declared rules, not PostgreSQL trigger
execution, driver JSON behavior, lock timing or operational role permissions.
"""
import ast
from copy import deepcopy
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import re
from types import SimpleNamespace
import unittest

from sqlalchemy.exc import NoResultFound
from api.reprice_basis_snapshot import read_basis, InvalidRepriceBasisSnapshot, _RAW_FIELDS

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / 'db/migrations/versions/0125_pricing_basis_revisions.py'


def capture_upgrade(schema='public'):
    spec = importlib.util.spec_from_file_location('pricing_revision_source', MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    class Bind:
        def execute(self, sql):
            calls.append(('read', str(sql)))
            return SimpleNamespace(scalar_one=lambda: schema)
    module.op = SimpleNamespace(execute=lambda sql: calls.append(('sql', str(sql))), get_bind=lambda: Bind())
    module.upgrade()
    return module, calls


def payload():
    return {'products': [dict(product_code=9,product_name='상품',part_type='GPU',purchase_price=10000,
                sale_price=None,status='판매중',stock_qty=2,locked_fields=None,category_id=3,
                pricing_basis_revision=9007199254740993)],
            'settings': {'card_fee_rate':0.02585,'margin_rate':0.13},
            'nodes':[[1,None],[2,1],[3,2],[4,None]],'margins':[[1,0.2],[2,0.17]],
            'policy_tokens':[{'singleton':1,'revision':9007199254740995}]}


class Connection:
    def __init__(self, value=None, error=None):
        self.value = json.dumps(payload() if value is None else value,ensure_ascii=False)
        self.error = error
        self.calls = []
    def execute(self, sql):
        self.calls.append(str(sql))
        if self.error:
            raise self.error
        return SimpleNamespace(scalar_one=lambda: self.value)


class DeclaredDmlModel:
    """Offline model of field sets extracted from captured trigger SQL."""
    def __init__(self, sql):
        match = re.search(r'IF ROW\((OLD\.product_code.*?)\) IS DISTINCT FROM', sql, re.S)
        self.fields = re.findall(r'OLD\.(\w+)', match[1])
        self.policy_fields = {table: re.findall(r'OLD\.(\w+)', fields) for table, fields in
            re.findall(r"WHEN '(\w+)' THEN\s+changed := ROW\((.*?)\)\s+IS DISTINCT FROM", sql,re.S)}
        self.next_value = 1
        self.rows = {}
        self.policy_revision = 1
    def nextval(self):
        token=self.next_value;self.next_value+=1;return token
    def insert(self, row):
        row=deepcopy(row);row['pricing_basis_revision']=self.nextval()
        self.rows[row['product_code']]=row
        return row['pricing_basis_revision']
    def update(self, code, changes):
        old=self.rows[code];new=deepcopy(old);new.update(changes)
        new['pricing_basis_revision']=(self.nextval() if any(old[k]!=new[k] for k in self.fields)
                                      else old['pricing_basis_revision'])
        self.rows[code]=new
        return new['pricing_basis_revision']
    def upsert(self, row):
        # BEFORE INSERT consumes a value even when the conflict UPDATE is a noop.
        if row['product_code'] in self.rows:
            self.nextval();return self.update(row['product_code'], row)
        return self.insert(row)
    def policy(self, table, operation, before=None, after=None):
        if operation in ('INSERT','DELETE') or any(before[k]!=after[k] for k in self.policy_fields[table]):
            self.policy_revision+=1


class MigrationSourceTests(unittest.TestCase):
    def setUp(self):
        self.module,self.calls=capture_upgrade()
        self.sql='\n'.join(sql for kind,sql in self.calls if kind=='sql')
        self.model=DeclaredDmlModel(self.sql)

    def test_actual_upgrade_policy_first_table_locks_backfill_install_atomic_contract(self):
        self.assertEqual(self.module.revision,'0125');self.assertEqual(self.module.down_revision,'0124')
        self.assertEqual(self.calls[0],('sql','SELECT pg_catalog.pg_advisory_xact_lock(1347375171,1)'))
        self.assertEqual(self.calls[1],('read','SELECT current_schema()'))
        self.assertLess(self.sql.index('LOCK TABLE'),self.sql.index('CREATE SEQUENCE'))
        self.assertLess(self.sql.index('UPDATE "public".products'),self.sql.index('SET NOT NULL'))
        self.assertLess(self.sql.index('SET NOT NULL'),self.sql.index('CREATE TRIGGER pricing_basis_product_revision'))
        self.assertIn("c.relkind='r'",self.sql)
        self.assertIn('CACHE 1 NO CYCLE',self.sql)
        self.assertNotIn('SECURITY DEFINER',self.sql);self.assertNotIn('GRANT ',self.sql)
        self.assertNotIn('CASCADE',self.sql)
        self.assertNotRegex(self.sql,r'CREATE\s+(?:TABLE|SEQUENCE|FUNCTION|TRIGGER)\s+IF NOT EXISTS')
        self.assertNotIn('COMMIT',self.sql);self.assertNotIn('ROLLBACK',self.sql)

    def test_product_trigger_exact_raw9_all_updates_no_policy_lock_or_counter(self):
        self.assertEqual(tuple(self.model.fields),_RAW_FIELDS)
        segment=self.sql.split('AS $pricing_basis_product$')[1].split('$pricing_basis_product$')[0]
        self.assertIn("TG_OP = 'INSERT'",segment);self.assertIn("TG_OP = 'UPDATE'",segment)
        self.assertIn('NEW.pricing_basis_revision := OLD.pricing_basis_revision',segment)
        self.assertIn('OLD.pricing_basis_revision IS NULL OR OLD.pricing_basis_revision <= 0',segment)
        self.assertNotIn('advisory',segment);self.assertNotIn('policy_revision',segment)
        self.assertIn('BEFORE INSERT OR UPDATE ON "public".products',self.sql)
        self.assertNotIn('UPDATE OF',self.sql)

    def test_policy_fields_guards_counter_missing_overflow_and_cascade_rule_source(self):
        self.assertEqual(self.model.policy_fields,{
            'pricing_settings':['setting_id','card_fee_rate','margin_rate','effective_from'],
            'categories':['category_id','parent_id'],
            'category_margin_policies':['category_id','margin_rate']})
        self.assertEqual(self.sql.count('FOR EACH STATEMENT EXECUTE'),3)
        self.assertEqual(self.sql.count('FOR EACH ROW EXECUTE'),4)
        self.assertEqual(self.sql.count('BEFORE INSERT OR UPDATE OR DELETE'),3)
        self.assertEqual(self.sql.count('AFTER INSERT OR UPDATE OR DELETE'),3)
        self.assertIn('SET revision = revision + 1',self.sql)
        self.assertIn('WHERE singleton = 1 AND revision > 0 RETURNING revision INTO token',self.sql)
        self.assertIn('IF NOT FOUND OR token IS NULL OR token <= 0',self.sql)
        self.assertIn('IF changed THEN',self.sql)
        self.assertIn('CHECK (singleton = 1)',self.sql)
        self.assertIn('CHECK (revision > 0)',self.sql)
        self.assertIn('pricing_basis_policy_revision) <> 1',self.sql)
        self.assertNotIn('EXCEPTION WHEN',self.sql)
        fk=(ROOT/'db/migrations/versions/0030_category_margin_by_node.py').read_text(encoding='utf-8')
        self.assertIn('REFERENCES categories(category_id) ON DELETE CASCADE',fk)

    def test_schema_identifiers_literals_and_dollar_delimiters_are_escaped(self):
        schema="odd_'\"\\$pricing_basis_policy$__SCHEMA__"
        module,calls=capture_upgrade(schema)
        sql='\n'.join(value for kind,value in calls if kind=='sql')
        quoted='"'+schema.replace('"','""')+'"'
        self.assertIn('LOCK TABLE '+quoted+'.pricing_settings',sql)
        self.assertIn('AS $pricing_basis_policy_$',sql)
        self.assertIn("odd_''",sql)
        self.assertIn('SET search_path = pg_catalog',sql)
        self.assertNotIn('SECURITY DEFINER',sql)
        # Replacement markers inside the real schema are preserved, never re-expanded.
        self.assertIn(quoted+'.products',sql)

    def test_missing_schema_fails_after_only_policy_guard(self):
        with self.assertRaises(RuntimeError):capture_upgrade(None)

    def test_downgrade_never_discards_tokens_or_runs_sql(self):
        before=deepcopy(self.calls)
        with self.assertRaisesRegex(RuntimeError,'must be preserved'):self.module.downgrade()
        self.assertEqual(self.calls,before)

    def test_declared_noop_unrelated_metadata_and_incoming_revision_do_not_reset_token(self):
        row=payload()['products'][0];original=self.model.insert(row)
        self.assertEqual(self.model.update(9,{'sale_price':None,'pricing_basis_revision':1}),original)
        self.assertEqual(self.model.update(9,{'maker':'새 제조사','updated_at':'changed'}),original)
        self.assertEqual(self.model.update(9,{'review_required_yn':False}),original)

    def test_declared_each_raw_field_and_null_vs_empty_and_array_order_changes_token(self):
        values={'product_code':10,'product_name':'B','part_type':'CPU','purchase_price':11000,
                'sale_price':12000,'status':'품절','stock_qty':3,'locked_fields':[],'category_id':4}
        for field,value in values.items():
            with self.subTest(field=field):
                model=DeclaredDmlModel(self.sql);original=model.insert(payload()['products'][0])
                self.assertGreater(model.update(9,{field:value}),original)
        original=self.model.insert(payload()['products'][0])
        second=self.model.update(9,{'locked_fields':['sale_price','purchase_price']})
        self.assertGreater(second,original)
        self.assertGreater(self.model.update(9,{'locked_fields':['purchase_price','sale_price']}),second)

    def test_declared_two_writes_aba_keeps_new_token_and_rollback_restores_row_not_sequence(self):
        original=self.model.insert(payload()['products'][0]);before=deepcopy(self.model.rows)
        self.model.update(9,{'purchase_price':11000});last=self.model.update(9,{'purchase_price':10000})
        self.assertEqual(self.model.rows[9]['purchase_price'],10000);self.assertGreater(last,original)
        consumed=self.model.next_value
        self.model.rows=before
        self.assertEqual(self.model.rows[9]['pricing_basis_revision'],original)
        self.assertEqual(self.model.next_value,consumed)
        self.assertGreater(self.model.update(9,{'sale_price':10000}),last)

    def test_declared_upsert_noop_consumes_gap_and_delete_reinsert_gets_new_incarnation(self):
        row=payload()['products'][0];original=self.model.insert(row)
        self.assertEqual(self.model.upsert(row),original);self.assertEqual(self.model.next_value,3)
        changed=self.model.upsert(row|{'sale_price':11000});self.assertGreater(changed,original)
        del self.model.rows[9]
        self.assertGreater(self.model.insert(row),changed)

    def test_declared_global_margin_policy_aba_and_metadata_noops(self):
        for table,before,changes in (
            ('pricing_settings',dict(setting_id=1,card_fee_rate=0.02585,margin_rate=0.13,effective_from='A'),
             {'card_fee_rate':0.03,'margin_rate':0.2,'effective_from':'B','setting_id':2}),
            ('category_margin_policies',dict(category_id=1,margin_rate=0.13),
             {'category_id':2,'margin_rate':0.2})):
            for field,value in changes.items():
                with self.subTest(table=table,field=field):
                    model=DeclaredDmlModel(self.sql)
                    model.policy(table,'UPDATE',before,before|{'updated_at':'B'})
                    self.assertEqual(model.policy_revision,1)
                    model.policy(table,'UPDATE',before,before|{field:value})
                    model.policy(table,'UPDATE',before|{field:value},before)
                    self.assertEqual(model.policy_revision,3)

    def test_declared_policy_noop_history_event_ancestor_aba_and_cascade_multiple_bumps(self):
        m=self.model;category={'category_id':1,'parent_id':None,'name':'A'}
        m.policy('categories','UPDATE',category,category|{'name':'B'})
        self.assertEqual(m.policy_revision,1)
        m.policy('categories','UPDATE',category,category|{'parent_id':2})
        m.policy('categories','UPDATE',category|{'parent_id':2},category)
        self.assertEqual(m.policy_revision,3)
        m.policy('pricing_settings','INSERT',after={})
        m.policy('category_margin_policies','DELETE',before={})
        m.policy('categories','DELETE',before=category)
        self.assertEqual(m.policy_revision,6)
        before=m.policy_revision;m.policy('category_margin_policies','INSERT',after={})
        m.policy_revision=before;self.assertEqual(m.policy_revision,6)  # caller rollback model


class SnapshotTests(unittest.TestCase):
    def reject(self, mutate):
        data=payload();mutate(data);conn=Connection(data)
        with self.assertRaises(InvalidRepriceBasisSnapshot):read_basis(conn,'all')
        self.assertEqual(len(conn.calls),1)

    def test_one_real_helper_statement_all_sources_and_original_policy_resolution(self):
        conn=Connection();basis=read_basis(conn,'all')
        self.assertEqual(len(conn.calls),1);sql=conn.calls[0]
        for table in ('products p','pricing_settings','categories','category_margin_policies','pricing_basis_policy_revision'):
            self.assertIn(table,sql)
        self.assertIn('ORDER BY effective_from DESC LIMIT 1',sql)
        self.assertIn('ORDER BY p.product_code',sql)
        self.assertEqual(set(basis),{'rows','product_revisions','policy_revision','fee','margin','mmap'})
        self.assertEqual(set(basis['rows'][0]),set(_RAW_FIELDS))
        self.assertEqual(basis['fee'],0.02585);self.assertEqual(basis['margin'],0.13)
        self.assertEqual(basis['mmap'],{1:0.2,2:0.17,3:0.17,4:0.13})
        self.assertEqual(basis['product_revisions'],{9:9007199254740993})
        self.assertEqual(basis['policy_revision'],9007199254740995)
        self.assertNotIn('FOR UPDATE',sql);self.assertNotIn('advisory',sql)

    def test_scope_whitelist_bound_sql_no_user_fragments_or_db_calls_on_invalid(self):
        for scope in ('x',"all; DROP TABLE products",None,1,[],{}):
            conn=Connection()
            with self.assertRaises(InvalidRepriceBasisSnapshot):read_basis(conn,scope)
            self.assertEqual(conn.calls,[])
        for scope,condition in (('all','AND TRUE'),('selling',"AND p.status = '판매중'"),
                                ('live',"AND p.status = '판매중' AND p.stock_qty > 0")):
            conn=Connection();read_basis(conn,scope);self.assertIn(condition,conn.calls[0])

    def test_empty_products_and_tree_are_valid_but_missing_settings_preserves_original_failure(self):
        data=payload();data.update(products=[],nodes=[],margins=[])
        basis=read_basis(Connection(data),'all')
        self.assertEqual(basis['rows'],[]);self.assertEqual(basis['product_revisions'],{});self.assertEqual(basis['mmap'],{})
        data['settings']=None
        with self.assertRaises(NoResultFound):read_basis(Connection(data),'all')

    def test_exact_decimal_bigint_null_locks_and_order_round_trip(self):
        conn=Connection();conn.value=conn.value.replace('10000','10000.12345678901234567890123456789')
        basis=read_basis(conn,'all')
        self.assertEqual(basis['rows'][0]['purchase_price'],Decimal('10000.12345678901234567890123456789'))
        self.assertIsNone(basis['rows'][0]['sale_price']);self.assertIsNone(basis['rows'][0]['locked_fields'])
        data=payload();data['products'][0]['locked_fields']=['stock_qty','sale_price','stock_qty']
        data['products'][0]['category_id']=None;data['products'][0]['stock_qty']=None
        row=read_basis(Connection(data),'all')['rows'][0]
        self.assertEqual(row['locked_fields'],['stock_qty','sale_price','stock_qty'])
        self.assertIsNone(row['category_id']);self.assertIsNone(row['stock_qty'])
        data['products'][0]['locked_fields']=[]
        self.assertEqual(read_basis(Connection(data),'all')['rows'][0]['locked_fields'],[])

    def test_policy_counter_missing_duplicate_wrong_identity_or_type_fails_closed(self):
        for tokens in ([],[{'singleton':1,'revision':0}],[{'singleton':1,'revision':True}],
                       [{'singleton':1,'revision':1.0}],[{'singleton':2,'revision':1}],
                       [{'singleton':1,'revision':1},{'singleton':1,'revision':2}],
                       [{'singleton':1,'revision':9223372036854775808}],[{'singleton':1}]):
            with self.subTest(tokens=tokens):self.reject(lambda d:d.update(policy_tokens=tokens))

    def test_product_revision_missing_invalid_and_malformed_raw_fields(self):
        for value in (None,False,0,-1,1.0,'2',9223372036854775808):
            with self.subTest(value=value):self.reject(lambda d:d['products'][0].update(pricing_basis_revision=value))
        self.reject(lambda d:d['products'][0].pop('pricing_basis_revision'))
        for field,value in (('stock_qty',True),('category_id',False),('purchase_price',None),
                            ('purchase_price',0),('sale_price',True),('locked_fields',[1]),('product_name',1)):
            with self.subTest(field=field,value=value):self.reject(lambda d:d['products'][0].update({field:value}))

    def test_duplicate_unsorted_products_and_category_inputs_fail_closed(self):
        self.reject(lambda d:d['products'].append(deepcopy(d['products'][0])))
        self.reject(lambda d:d['products'].append(d['products'][0]|{'product_code':8}))
        self.reject(lambda d:d.update(nodes=[[2,None],[1,None]]))
        self.reject(lambda d:d.update(margins=[[1,0.1],[1,0.2]]))
        self.reject(lambda d:d.update(nodes=[[True,None]]))
        self.reject(lambda d:d.update(nodes=[[1,True]]))
        self.reject(lambda d:d.update(margins=[[1,None]]))

    def test_scope_row_mismatch_fails_closed(self):
        for scope,change in (('selling',{'status':'품절'}),('live',{'stock_qty':0}),('live',{'stock_qty':None})):
            data=payload();data['products'][0].update(change)
            with self.assertRaises(InvalidRepriceBasisSnapshot):read_basis(Connection(data),scope)

    def test_malformed_json_duplicate_keys_nonfinite_and_shape_fail_closed(self):
        for raw in (None,'{}','[]','{bad}',Connection().value.replace('10000','NaN'),
                    Connection().value.replace('"settings":','"settings":null,"settings":')):
            conn=Connection();conn.value=raw
            with self.assertRaises(InvalidRepriceBasisSnapshot):read_basis(conn,'all')
        self.reject(lambda d:d['settings'].update(card_fee_rate=True))
        self.reject(lambda d:d.update(products={}))
        self.reject(lambda d:d.update(extra=1))
        conn=Connection();conn.value=conn.value.replace('0.02585','1e99999')
        with self.assertRaises(InvalidRepriceBasisSnapshot):read_basis(conn,'all')

    def test_sql_and_scalar_errors_propagate_identical_without_tx_ownership(self):
        error=RuntimeError('SQL failure');conn=Connection(error=error)
        with self.assertRaises(RuntimeError) as caught:read_basis(conn,'all')
        self.assertIs(caught.exception,error);self.assertEqual(len(conn.calls),1)
        source=(ROOT/'api/reprice_basis_snapshot.py').read_text(encoding='utf-8')
        tree=ast.parse(source)
        imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        self.assertNotIn('db',imports);self.assertNotIn('main',imports)
        for n in ast.walk(tree):
            if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute):
                self.assertNotIn(n.func.attr,('connect','begin','commit','rollback'))

    def test_scalar_result_failure_propagates_and_category_cycle_or_orphan_keeps_original_fallback(self):
        error=RuntimeError('result conversion failure')
        class ScalarError(Connection):
            def execute(self,sql):
                self.calls.append(str(sql))
                def scalar_one():raise error
                return SimpleNamespace(scalar_one=scalar_one)
        conn=ScalarError()
        with self.assertRaises(RuntimeError) as caught:read_basis(conn,'all')
        self.assertIs(caught.exception,error);self.assertEqual(len(conn.calls),1)
        data=payload();data.update(nodes=[[1,2],[2,1],[3,99]],margins=[])
        self.assertEqual(read_basis(Connection(data),'all')['mmap'],{1:0.13,2:0.13,3:0.13})

    def test_revision_difference_for_identical_value_basis_and_population_limit(self):
        first=read_basis(Connection(),'all');data=payload()
        data['products'][0]['pricing_basis_revision']+=2
        second=read_basis(Connection(data),'all')
        self.assertEqual(first['rows'],second['rows']);self.assertNotEqual(first['product_revisions'],second['product_revisions'])
        data['products'][0]['pricing_basis_revision']-=2;data['policy_tokens'][0]['revision']+=2
        third=read_basis(Connection(data),'all')
        self.assertEqual(first['rows'],third['rows']);self.assertNotEqual(first['policy_revision'],third['policy_revision'])
        # A new row inserted and deleted between reads leaves no token in this row set.
        self.assertEqual(read_basis(Connection(),'all'),first)


if __name__ == '__main__':
    unittest.main()
