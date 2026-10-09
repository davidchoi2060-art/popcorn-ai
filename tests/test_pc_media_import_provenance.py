"""SQL capture/three-valued CHECK fixtures, NOT PostgreSQL execution tests."""
import ast
import copy
import importlib.util
from pathlib import Path
import re
import sys
import types
import unittest
from unittest.mock import patch

FILE = Path(__file__).resolve().parents[1] / 'db/migrations/versions/0134_pc_media_import_provenance.py'


def deny_live(event, args):
    if event in ('socket.connect','socket.getaddrinfo','subprocess.Popen','os.system'):
        raise AssertionError('Schema fixture live IO forbidden')
    if event == 'import' and args and args[0].split('.')[0] in ('psycopg','psycopg2','pg8000'):
        raise AssertionError('Schema fixture driver forbidden')


sys.addaudithook(deny_live)


class CheckExpression:
    """Evaluate captured outer CHECK with SQL TRUE/FALSE/UNKNOWN semantics.

    Only this migration's boolean grammar is supported. PL/pgSQL JSON shape
    is a supplied fixture result, not executed or claimed verified here.
    """
    def __init__(self, expression, row, shape=True):
        expression = re.sub(r'__S__\.pc_media_import_provenance_valid\([^)]*\)', 'shape', expression)
        self.tokens = re.findall(r"'[^']*'|[A-Za-z_][A-Za-z_0-9]*|[()=]",expression)
        self.pos=0;self.row=row;self.shape=shape

    def take(self):
        item=self.tokens[self.pos];self.pos+=1;return item

    def accept(self,value):
        if self.pos<len(self.tokens) and self.tokens[self.pos]==value:
            self.pos+=1;return True
        return False

    def value(self):
        token=self.take()
        return token[1:-1] if token.startswith("'") else self.row[token]

    def atom(self):
        if self.accept('('):
            value=self.expression();assert self.take()==')'
        elif self.accept('shape'):
            value=self.shape
        else:
            left=self.value()
            if self.accept('='):
                right=self.value();value=None if left is None or right is None else left==right
            else:
                assert self.take()=='IS'
                negate=self.accept('NOT')
                if self.accept('NULL'):
                    value=left is None
                else:
                    assert self.take()=='DISTINCT';assert self.take()=='FROM'
                    right=self.value();value=left!=right
                if negate:value=not value
        if self.accept('IS'):
            assert self.take()=='TRUE';value=value is True
        return value

    def conjunction(self):
        value=self.atom()
        while self.accept('AND'):
            other=self.atom()
            value=False if value is False or other is False else None if value is None or other is None else True
        return value

    def expression(self):
        value=self.conjunction()
        while self.accept('OR'):
            other=self.conjunction()
            value=True if value is True or other is True else None if value is None or other is None else False
        return value

    def evaluate(self):
        value=self.expression();assert self.pos==len(self.tokens);return value


class FakeBind:
    def __init__(self, schema='fixture'):
        self.schema=schema;self.reads=[]
    def execute(self,sql):
        self.reads.append(sql);return self
    def scalar_one(self):return self.schema


class CaptureOp:
    def __init__(self,rows=(),schema='fixture'):
        self.bind=FakeBind(schema);self.rows=rows;self.sql=[]
    def get_bind(self):return self.bind
    def execute(self,sql):
        self.sql.append(sql)
        if 'DO $preserve$' in sql:
            expression=sql.split('WHERE ',1)[1].split(') THEN',1)[0]
            if any(CheckExpression(expression,row).evaluate() is True for row in self.rows):
                raise RuntimeError('mock downgrade refused; native PG unverified')


def load(op):
    alembic=types.ModuleType('alembic');alembic.op=op
    sqlalchemy=types.ModuleType('sqlalchemy');sqlalchemy.text=lambda value:value
    spec=importlib.util.spec_from_file_location('pc_media_import_0134_fixture',FILE)
    module=importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules,{'alembic':alembic,'sqlalchemy':sqlalchemy}):
        spec.loader.exec_module(module)
    return module


class MediaProvenanceFixtures(unittest.TestCase):
    def setUp(self):
        self.op=CaptureOp();self.m=load(self.op)
        self.check=self.m.UPGRADE_SQL.split(' CHECK ',1)[1].strip().removesuffix(';')

    def valid(self,origin,model,provenance,shape=True):
        return CheckExpression(self.check,dict(origin_kind=origin,model=model,import_provenance=provenance),shape).evaluate()

    def test_exact_chain_and_mock_upgrade(self):
        self.assertEqual((self.m.revision,self.m.down_revision),('0134','0133'))
        self.m.upgrade()
        self.assertEqual(self.op.bind.reads,['SELECT current_schema()'])
        self.assertEqual(len(self.op.sql),1)
        self.assertNotIn('__S__',self.op.sql[0])
        self.assertIn('"fixture".pc_media_jobs',self.op.sql[0])

    def test_generated_requires_model_and_no_provenance(self):
        self.assertIs(self.valid('generated','original-model',None),True)
        self.assertIs(self.valid('generated','',None),True)  # Preserve original NOT NULL semantics.
        for model,prov in ((None,None),('x',{}),('x','json-null'),(None,{})):
            with self.subTest(model=model,prov=prov):self.assertIs(self.valid('generated',model,prov),False)

    def test_import_requires_null_model_and_valid_provenance(self):
        self.assertIs(self.valid('existing_import',None,{}),True)
        for model,prov,shape in (('provider',{},True),(None,None,True),(None,{},False),(None,{},None)):
            with self.subTest(model=model,prov=prov,shape=shape):
                self.assertIs(self.valid('existing_import',model,prov,shape),False)

    def test_sql_unknown_does_not_escape_check(self):
        for origin in (None,'other','Generated',''):
            for model in (None,'model'):
                for prov in (None,{}):
                    with self.subTest(origin=origin,model=model,prov=prov):
                        self.assertIs(self.valid(origin,model,prov,None),False)
        self.assertTrue(self.check.endswith('IS TRUE)'))

    def test_missing_json_and_json_null_are_distinguished_in_source_guards(self):
        sql=self.m.UPGRADE_SQL
        self.assertGreaterEqual(sql.count('IS DISTINCT FROM TRUE'),5)
        for key in ('generation_model','generation_actor','generation_time','original_visual_basis'):
            self.assertIn("original->'"+key+"' IS NOT DISTINCT FROM 'null'::jsonb",sql)
            self.assertIn(key,self.m.PROVENANCE_SHAPE['original'])
        self.assertIn("p ?& ARRAY['version','original','current_binding']",sql)
        self.assertIn("jsonb_typeof(p->'original')='object'",sql)

    def test_declared_shape_preserves_unknown_generation_metadata(self):
        original=self.m.PROVENANCE_SHAPE['original']
        for key in ('generation_model','generation_time','generation_actor','original_visual_basis'):
            self.assertIsNone(original[key])
        self.assertIn('original_sha256',original);self.assertIn('manifest_sha256',original)
        self.assertIn('original_revision',original);self.assertIn('source_sku',original)

    def test_original_vs_current_binding_not_rewritten(self):
        sql=self.m.UPGRADE_SQL
        for key,arg in (('configuration_id','configuration'),('visual_basis','visual'),('review_basis','review')):
            self.assertIn("current_binding->'"+key+"' IS NOT DISTINCT FROM to_jsonb("+arg+")",sql)
        self.assertNotIn("original->'original_visual_basis' IS NOT DISTINCT FROM to_jsonb",sql)
        self.assertIn("current_binding->>'revision' ~ '^[1-9][0-9]*$'",sql)
        self.assertIn("original->>'original_revision' ~ '^[1-9][0-9]*$'",sql)

    def test_hash_type_and_full_lowercase_hash_contract(self):
        sql=self.m.UPGRADE_SQL
        for key in ('original_sha256','manifest_sha256'):
            self.assertIn("jsonb_typeof(original->'"+key+"')='string'",sql)
            self.assertIn("original->>'"+key+"' ~ '^[a-f0-9]{64}$'",sql)
        for bad in ('abc','A'*64,'a'*63,'a'*65):
            self.assertIsNone(re.fullmatch('[a-f0-9]{64}',bad))

    def test_qa_exception_and_ssd_reference_guards_present(self):
        sql=self.m.UPGRADE_SQL
        self.assertIn("jsonb_typeof(original->'qa_references')='array'",sql)
        self.assertIn("jsonb_array_length(original->'qa_references')=0",sql)
        self.assertIn("jsonb_typeof(item)='string' AND length(btrim(item #>> '{}'))>0",sql)
        for key in ('reuse_exception_reference','ssd_facts_reference','reused_from'):
            self.assertIn(key,self.m.PROVENANCE_SHAPE['original'])
        self.assertIn("original->'reuse_exception_reference'='null'::jsonb THEN RETURN false",sql)

    def test_existing_rows_are_additive_only(self):
        sql=self.m.UPGRADE_SQL
        self.assertIn("ADD COLUMN origin_kind TEXT NOT NULL DEFAULT 'generated'",sql)
        self.assertIn('ALTER COLUMN model DROP NOT NULL',sql)
        # Source contract: no DML/backfill overwrites any original job value.
        self.assertNotRegex(sql,r'(?i)\b(UPDATE|DELETE|INSERT|TRUNCATE)\b')
        for field in ('actor','created_at','updated_at','snapshot','asset','selected','status','request_id','staged_png'):
            self.assertNotRegex(sql,r'(?i)ALTER COLUMN\s+'+field+r'\b')

    def test_existing_job_values_preserved_in_expected_overlay(self):
        old=dict(model='original-provider',actor='old-operator',created_at='old-time',status='ready',
            asset={'sha':'old'},selected=True,visual_basis='old-visual',review_basis='old-review',request_id='old-request')
        old_copy=copy.deepcopy(old);overlay=copy.deepcopy(old);overlay.update(origin_kind='generated',import_provenance=None)
        self.assertEqual({k:overlay[k] for k in old},old_copy)
        self.assertIs(self.valid(overlay['origin_kind'],overlay['model'],overlay['import_provenance']),True)

    def test_existing_status_selected_unique_request_and_fk_not_touched(self):
        sql=self.m.UPGRADE_SQL+self.m.DOWNGRADE_SQL
        for token in ('DROP TABLE','DROP INDEX','pc_media_selected','request_id','REFERENCES','status IN'):
            self.assertNotIn(token,sql)

    def test_downgrade_refuses_import_and_invalid_states_without_mutation(self):
        for row in (dict(origin_kind='existing_import',model=None,import_provenance={}),
            dict(origin_kind='generated',model='x',import_provenance={}),
            dict(origin_kind='generated',model=None,import_provenance=None),
            dict(origin_kind=None,model='x',import_provenance=None)):
            with self.subTest(row=row):
                before=copy.deepcopy(row);op=CaptureOp((row,));m=load(op)
                with self.assertRaisesRegex(RuntimeError,'mock downgrade refused'):m.downgrade()
                self.assertEqual(row,before)

    def test_downgrade_generated_only_guard_and_lock_order(self):
        op=CaptureOp((dict(origin_kind='generated',model='x',import_provenance=None),));m=load(op);m.downgrade()
        sql=op.sql[0]
        self.assertLess(sql.index('LOCK TABLE'),sql.index('IF EXISTS'))
        self.assertLess(sql.index('RAISE EXCEPTION'),sql.index('DROP CONSTRAINT'))
        self.assertIn('ALTER COLUMN model SET NOT NULL',sql)
        self.assertNotRegex(sql,r'(?i)\b(DELETE|UPDATE|TRUNCATE)\b')

    def test_schema_injection_or_unknown_schema_closed(self):
        for value in (None,True,'public;DROP TABLE x','x.y',''):
            op=CaptureOp(schema=value);m=load(op)
            with self.subTest(value=value),self.assertRaises(RuntimeError):m.upgrade()
            self.assertEqual(op.sql,[])

    def test_no_engine_storage_or_commit_in_migration(self):
        tree=ast.parse(FILE.read_text(encoding='utf-8'))
        calls=[n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)]
        for method in ('commit','connect','begin','upload','delete_blob'):self.assertNotIn(method,calls)
        self.assertNotIn('create_engine',FILE.read_text(encoding='utf-8'))


if __name__=='__main__':unittest.main()
