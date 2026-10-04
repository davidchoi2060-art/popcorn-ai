"""Real catalog functions with mock transactions; no database or operational imports."""
import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, mock_open
import contextlib
import io
import json
import sys
import unittest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from api import catalog_ingest as ci
from api.pricing_write_guard_core import _LOCK_PRODUCTS_SQL


class Result:
    def __init__(self, rows=()): self.rows = deepcopy(list(rows))
    def all(self): return deepcopy(self.rows)
    def scalars(self): return self
    def scalar(self): return self.rows[0] if self.rows else None
    def scalar_one(self): return self.scalar()


def integrity(constraint='products_pkey', state='23505'):
    original = Exception('mock key error')
    original.sqlstate = state
    original.diag = SimpleNamespace(constraint_name=constraint)
    return IntegrityError('mock', {}, original)


def product(pc, stock=1, pp=100, sp=200):
    return dict(pc=pc, sku=str(pc), name='원본', maker=None, model=None, pt='CPU',
        grp='core_part', status='판매중', ai=False, rev=True, pp=pp, sp2=sp,
        mp=None, sup=None, dan=None, stock=stock, spec_text=None, origin='real',
        raw={'자체상품코드':str(pc), '임의원천':'원문'})


def plan(prods, db, specs=(), existing=None, owners=None):
    codes = {p['pc'] for p in prods}
    return dict(prods=prods, specs=list(specs), reviews=[], errors=[], row_total=len(prods),
        skipped={}, basis={'locked':{pc:tuple(sorted(db.products.get(pc, {}).get('locked', []))) for pc in codes},
                          'existing':existing or {}, 'dan_owner':owners or {}})


class Database:
    def __init__(self):
        self.products={101:{'stock':7, 'pp':100, 'sp2':200, 'locked':[]}}
        self.specs={101:{'socket':'AM5'}}; self.owners={}; self.calls=[]; self.writes=[]
        self.locks=(); self.required=None; self.after_lock=None; self.before_read=None; self.key_error=None; self.commits=0; self.rollbacks=0
    def begin(self): return Transaction(self)
    def connect(self): return Transaction(self, read=True)


class Transaction:
    def __init__(self, db, read=False): self.db=db; self.read=read
    def __enter__(self):
        self.snapshot=deepcopy((self.db.products, self.db.writes)); self.db.transaction=self
        return Connection(self.db)
    def __exit__(self, typ, value, tb):
        if typ:
            self.db.products,self.db.writes=deepcopy(self.snapshot); self.db.rollbacks+=1
        elif not self.read: self.db.commits+=1
        return False


class Connection:
    def __init__(self, db): self.db=db
    def execute(self, statement, params=None):
        q=str(statement); p=params or {}; d=self.db; d.calls.append((q,deepcopy(p)))
        if q==_LOCK_PRODUCTS_SQL:
            d.locks=tuple(sorted(pc for pc in p['codes'] if pc in d.products))
            if d.after_lock:
                d.after_lock(d)
                d.transaction.snapshot=deepcopy((d.products,d.writes))
            return Result(d.locks)
        if q.startswith('SELECT product_code FROM products'):
            found=tuple(sorted(pc for pc in p['c'] if pc in d.products))
            if d.required is None: d.required=found
            return Result(found)
        if q.startswith('SELECT product_code, locked_fields'):
            return Result((pc,d.products[pc]['locked']) for pc in p['c'] if pc in d.products)
        if q.startswith('SELECT product_code, stock_qty'):
            if d.before_read:
                d.before_read(d)
                d.transaction.snapshot=deepcopy((d.products,d.writes))
            return Result((pc,d.products[pc]['stock'],d.products[pc]['pp'],d.products[pc]['sp2'],
                           d.products[pc]['locked']) for pc in p['c'] if pc in d.products)
        if ' FROM product_specs WHERE' in q:
            columns=q.split(' FROM')[0].split(', ')[1:]
            return Result((pc,*(d.specs[pc].get(col) for col in columns)) for pc in p['c'] if pc in d.specs)
        if q.startswith('SELECT danawa_code'):
            return Result((dan,d.owners[dan]) for dan in p['d'] if dan in d.owners)
        if 'INSERT INTO csv_import_jobs' in q:
            self.assert_locked(); d.writes.append(('job',deepcopy(p))); return Result([91])
        if 'INSERT INTO products (' in q:
            self.assert_locked()
            if d.key_error: raise d.key_error
            for row in p:
                pc=row['pc']; before=d.products.get(pc)
                if before is not None and 'ON CONFLICT' not in q: raise integrity()
                if before is None:
                    d.products[pc]={'stock':row['stock'],'pp':row['pp'],'sp2':row['sp2'],'locked':[]}
                else:
                    before['stock']=row['stock']
                    for col,key in [('purchase_price','pp'),('sale_price','sp2')]:
                        if col not in before['locked'] and row[key] is not None: before[key]=row[key]
            d.writes.append(('products',deepcopy(p))); return Result()
        if q.lstrip().startswith('INSERT'):
            self.assert_locked(); d.writes.append((q,deepcopy(p))); return Result()
        if q.startswith('SELECT count'): return Result([1])
        raise AssertionError(q)
    def assert_locked(self):
        if self.db.required is None or not set(self.db.required).issubset(self.db.locks):
            raise AssertionError('write before complete product lock')


def selected(path, name, env):
    tree=ast.parse(Path(path).read_text(encoding='utf-8'))
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    node.decorator_list=[]
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),env)
    return env[name]


class CatalogTests(unittest.TestCase):
    def apply(self, db, value):
        with db.begin() as conn: return ci.apply_plan(conn,value,'원본.csv','real',31)
    def rows(self, db, table):
        return [row for q,p in db.writes if table in q for row in p]
    def test_whole_lock_before_job_and_actual_before_after_wait(self):
        db=Database(); db.products[102]={'stock':3,'pp':100,'sp2':200,'locked':[]}
        value=plan([product(102),product(101)],db)
        db.after_lock=lambda d:d.products[101].update(stock=9,pp=150)
        self.apply(db,value)
        self.assertEqual(db.locks,(101,102))
        queries=[q for q,p in db.calls]
        self.assertLess(queries.index(_LOCK_PRODUCTS_SQL),next(i for i,q in enumerate(queries) if 'INSERT' in q))
        self.assertLess(next(i for i,q in enumerate(queries) if 'stock_qty, purchase_price' in q),next(i for i,q in enumerate(queries) if 'INSERT' in q))
        self.assertEqual([r['pc'] for q,p in db.writes if q=='products' for r in p],[102,101])
        self.assertEqual([r['q'] for r in self.rows(db,'stock_movements')],[-2,-8])
        self.assertEqual(self.rows(db,'product_price_history')[0]['old'],150)
        self.assertEqual(self.rows(db,'product_imports')[0]['raw'],json.dumps(value['prods'][0]['raw'],ensure_ascii=False))
        self.assertEqual(db.commits,1)
    def test_locked_drift_both_spellings_refused_before_any_write(self):
        for field in ['socket','specs.socket']:
            with self.subTest(field=field):
                db=Database(); value=plan([product(101)],db)
                db.after_lock=lambda d:d.products[101]['locked'].append(field)
                with self.assertRaises(ci.CatalogConflict): self.apply(db,value)
                self.assertEqual(db.writes,[]); self.assertEqual(db.rollbacks,1)
    def test_required_spec_and_dan_owner_drift_refused(self):
        for kind in ['spec','owner']:
            db=Database(); value=plan([product(101)],db,existing={101:{'socket':'AM5'}},owners={'123':None})
            db.after_lock=(lambda d:d.specs[101].update(socket='LGA')) if kind=='spec' else (lambda d:d.owners.update({'123':999}))
            with self.assertRaises(ci.CatalogConflict): self.apply(db,value)
            self.assertEqual(db.writes,[])
    def test_scope_insert_or_delete_after_candidate_refused(self):
        for action in ['insert','delete']:
            db=Database(); value=plan([product(101),product(102)],db)
            db.after_lock=(lambda d:d.products.update({102:{'stock':0,'pp':None,'sp2':None,'locked':[]}})) if action=='insert' else (lambda d:d.products.pop(101))
            with self.assertRaises(ci.CatalogConflict): self.apply(db,value)
            self.assertEqual(db.writes,[])
    def test_unrelated_refs_not_compared(self):
        db=Database(); value=plan([product(101)],db,existing={101:{'socket':'AM5'}})
        db.after_lock=lambda d:(d.specs[101].update(capacity_gb=999),d.owners.update({'unrelated':909}))
        self.apply(db,value); self.assertEqual(db.commits,1)
    def test_duplicate_existing_sequential_stock_and_price_history(self):
        db=Database(); value=plan([product(101,1,150,250),product(101,0,None,300)],db)
        self.apply(db,value)
        self.assertEqual([r['q'] for r in self.rows(db,'stock_movements')],[-6,-1])
        self.assertEqual([(r['field'],r['old'],r['new']) for r in self.rows(db,'product_price_history')],
                         [('purchase',100,150),('sale',200,250),('sale',250,300)])
        self.assertEqual(db.products[101]['pp'],150)
    def test_duplicate_new_insert_then_update_initial_price_excluded(self):
        db=Database(); value=plan([product(102,1,10,20),product(102,0,15,30)],db)
        self.apply(db,value)
        inserts=[q for q,p in db.calls if 'INSERT INTO products (' in q]
        self.assertNotIn('ON CONFLICT',inserts[0]); self.assertIn('ON CONFLICT',inserts[1])
        self.assertEqual([r['q'] for r in self.rows(db,'stock_movements')],[1,-1])
        self.assertEqual([(r['old'],r['new']) for r in self.rows(db,'product_price_history')],[(10,15),(20,30)])
    def test_new_concurrent_unique_collision_rolls_back_job(self):
        for constraint in ['products_pkey','products_sku_key','idx_products_danawa']:
            db=Database(); db.key_error=integrity(constraint); value=plan([product(102)],db)
            with self.assertRaises(ci.CatalogConflict): self.apply(db,value)
            self.assertEqual(db.writes,[]); self.assertEqual(db.commits,0); self.assertEqual(db.rollbacks,1)
    def test_external_new_product_after_scope_check_before_before_read_not_adopted(self):
        db=Database(); value=plan([product(101),product(102,1,10,20)],db)
        external={'stock':42,'pp':777,'sp2':888,'locked':[]}
        db.before_read=lambda d:d.products.update({102:deepcopy(external)})
        with self.assertRaises(ci.CatalogConflict): self.apply(db,value)
        before_queries=[p for q,p in db.calls if q.startswith('SELECT product_code, stock_qty')]
        self.assertEqual(before_queries,[{'c':[101]}])
        writes=[(q,p) for q,p in db.calls if 'INSERT INTO products (' in q]
        self.assertEqual([r['pc'] for q,p in writes for r in p],[101,102])
        self.assertNotIn('ON CONFLICT',writes[-1][0])
        self.assertEqual(db.products[102],external)
        self.assertEqual(db.products[101]['stock'],7)
        self.assertEqual(db.writes,[])
        self.assertEqual((db.commits,db.rollbacks),(0,1))

    def test_other_integrity_propagates(self):
        db=Database(); db.key_error=integrity('other_key')
        with self.assertRaises(IntegrityError): self.apply(db,plan([product(101)],db))
        self.assertEqual(db.rollbacks,1)
    def test_batch500_and_original_order(self):
        db=Database(); prods=[product(101, i%2,100,200) for i in range(501)]
        self.apply(db,plan(prods,db))
        batches=[p for q,p in db.writes if q=='products']
        self.assertEqual(list(map(len,batches)),[500,1]); self.assertEqual(batches[0],prods[:500])
    def test_locked_prices_no_history_and_empty_price_coalesce(self):
        db=Database(); db.products[101]['locked']=['purchase_price','sale_price']
        self.apply(db,plan([product(101,1,900,999)],db))
        self.assertEqual(self.rows(db,'product_price_history'),[])
        self.assertEqual((db.products[101]['pp'],db.products[101]['sp2']),(100,200))
    def test_build_plan_basis_only_used_targets_fields_owners(self):
        refs={'gpu_ref':{},'locked':{101:['specs.socket'],999:['x']},
              'existing':{101:{'socket':'AM5','tdp_watt':65},999:{'socket':'other'}},
              'dan_owner':{'123':None,'unused':999}}
        row={k:'' for k in ci.MASTER_REQUIRED_COLS}; row.update({'자체상품코드':'101','상품명':'CPU','다나와No':'123'})
        with patch.object(ci,'map_part_type',return_value=('CPU','core_part',None)), patch.object(ci,'extract_specs',return_value=({'tdp_watt':65},{})), patch.object(ci,'_required_for',return_value=['socket','tdp_watt']):
            value=ci.build_plan([row],{}, {},refs,'real')
        self.assertEqual(value['basis'],{'locked':{101:('specs.socket',)},'existing':{101:{'socket':'AM5'}},'dan_owner':{'123':None}})
        self.assertIsNone(value['specs'][0]['socket'])
    def test_raw_errors_capped200_actor_and_spec_sql_preserved(self):
        db=Database(); value=plan([product(101)],db,specs=[{'pc':101,'pt':'CPU','socket':None,'sources':'{}'}])
        value['errors']=[(i,{'원본':str(i)},'원인') for i in range(205)]
        self.apply(db,value)
        errors=[p for q,p in db.writes if 'csv_import_errors' in q]
        self.assertEqual(len(errors),200)
        self.assertEqual(errors[-1]['r'],json.dumps({'원본':'199'},ensure_ascii=False))
        job=next(p for q,p in db.writes if q=='job')
        self.assertEqual((job['by'],job['er']),(31,205))
        sql=next(q for q,p in db.writes if 'INSERT INTO product_specs' in q)
        self.assertIn('COALESCE(EXCLUDED.socket, product_specs.socket)',sql)
        self.assertIn("|| COALESCE(EXCLUDED.spec_sources, '{}'::jsonb)",sql)
        self.assertIn('ELSE EXCLUDED.market_price END',ci.UPSERT_PRODUCTS_SQL)
    def test_new_duplicate_across_batch_boundary(self):
        db=Database(); prods=[product(102,1,10,20)]+[product(101) for _ in range(499)]+[product(102,0,15,30)]
        self.apply(db,plan(prods,db))
        rows=[r for r in self.rows(db,'stock_movements') if r['pc']==102]
        self.assertEqual([r['q'] for r in rows],[1,-1])
        rows=[r for r in self.rows(db,'product_price_history') if r['pc']==102]
        self.assertEqual([(r['old'],r['new']) for r in rows],[(10,15),(20,30)])
    def test_mock_imports_never_load_operational_db_or_main(self):
        self.assertNotIn('api.db',sys.modules)
        self.assertNotIn('api.main',sys.modules)

    def test_http_conflict_after_rollback_no_archive_or_delete(self):
        db=Database(); paths=SimpleNamespace(exists=lambda p:True)
        shutil=SimpleNamespace(copyfile=lambda *a:self.fail('archive on failure'))
        os=SimpleNamespace(path=paths,makedirs=lambda *a,**k:self.fail('mkdir on failure'),remove=lambda *a:self.fail('delete on failure'))
        def failed(*args,**kwargs): raise ci.CatalogConflict('drift')
        env=dict(Form=lambda *a,**k:None,io=SimpleNamespace(open=mock_open(read_data=json.dumps({'origin':'real','file_name':'x'}))),json=json,os=os,shutil=shutil,engine=db,
                 _stage_path=lambda *a:'unused', read_master=lambda b:[],load_eav=lambda *a:({},{}),read_refs=lambda c:{},build_plan=lambda *a:{'prods':[]},current_operator=lambda:{},apply_plan=failed,CatalogConflict=ci.CatalogConflict,HTTPException=HTTPException)
        fn=selected(Path(__file__).resolve().parents[1]/'api/admin_catalog_import.py','apply',env)
        with self.assertRaises(HTTPException) as caught: fn('stage',0)
        self.assertEqual(caught.exception.status_code,409); self.assertEqual(db.rollbacks,1)
    def test_cli_conflict_nonzero_after_rollback_and_dry_no_write(self):
        for dry in [False,True]:
            db=Database(); args=SimpleNamespace(origin='real',limit=0,dry=dry)
            parser=SimpleNamespace(add_argument=lambda *a,**k:None,parse_args=lambda:args)
            def failed(*args,**kwargs): raise ci.CatalogConflict('drift')
            env=dict(argparse=SimpleNamespace(ArgumentParser=lambda:parser),load_dotenv=lambda p:None,ROOT='mock',os=SimpleNamespace(path=SimpleNamespace(join=lambda *a:'mock',basename=lambda x:x),environ={'DATABASE_URL':'mock'}),create_engine=lambda u:db,load_eav=lambda *a:({},{}),_read=lambda p:b'',DB_PRODUCTS='p',DB_SPECS='s',MASTER='m',read_master=lambda b:[],build_plan=lambda *a:{},plan_summary=lambda p:{'ok':0,'spec_rows':0,'review':0,'skipped':0,'error':0},apply_plan=failed,CatalogConflict=ci.CatalogConflict,sys=sys)
            fn=selected(Path(__file__).resolve().parents[1]/'tools/catalog_import.py','main',env)
            with patch.object(ci,'read_refs',return_value={'gpu_ref':{},'locked':{}}),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()) as stderr:
                if dry: fn()
                else:
                    with self.assertRaises(SystemExit) as caught: fn()
                    self.assertEqual(caught.exception.code,1); self.assertIn('적재 실패',stderr.getvalue())
            self.assertEqual(db.rollbacks,0 if dry else 1); self.assertEqual(db.commits,0)


if __name__ == '__main__': unittest.main()
