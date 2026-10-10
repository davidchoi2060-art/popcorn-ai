"""Selected real registration function; caller rollback and exact constraint dispatch."""
import ast
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from api.catalog_ingest import is_product_key_conflict
from tests.test_catalog_ingest_write_lock_order import integrity, selected, Result


class Database:
    def __init__(self, error=None, fail_at='INSERT INTO products', mapping=44, categories=(7,)):
        self.error=error; self.fail_at=fail_at; self.mapping=mapping; self.categories=categories
        self.calls=[]; self.writes=[]; self.commits=0; self.rollbacks=0
    def begin(self): return self
    def __enter__(self): return self
    def __exit__(self, typ, value, tb):
        if typ: self.rollbacks+=1; self.writes=[]
        else: self.commits+=1
        return False
    def execute(self, statement, params=None):
        q=str(statement); self.calls.append((q,params))
        if q.startswith('SELECT 1 FROM suppliers'): return SimpleNamespace(first=lambda:(1,))
        if q.startswith('SELECT 1 FROM categories'):
            return SimpleNamespace(first=lambda:(1,) if params['c'] in self.categories else None)
        if q.startswith('SELECT sku'): return Result()
        if q.startswith('SELECT COALESCE(MAX'): return Result([12])
        if q.startswith(self.fail_at) and self.error: raise self.error
        if q.startswith('INSERT INTO supplier_product_map'):
            self.writes.append(q); return Result([self.mapping])
        if q.startswith('SELECT r.supply_state'): return SimpleNamespace(first=lambda:None)
        self.writes.append(q); return Result()


def register(db):
    def log(conn,*args,**kwargs): conn.writes.append('log')
    body=SimpleNamespace(part_type='CPU',part_label=None,name='테스트 상품',supplier_id=None,
        model_name=None,cost_price=None,danawa_code=None,confirm_similar=True,supplier=None,maker=None,
        category_id=None)
    env=dict(__name__='api.admin_products',__package__='api',PART_TYPE_LABELS={'CPU':'CPU'},RegisterBody=object,engine=db,text=text,
        HTTPException=HTTPException,IntegrityError=IntegrityError,is_product_key_conflict=is_product_key_conflict)
    fn=selected(Path(__file__).resolve().parents[1]/'api/admin_products.py','register_product',env)
    return fn,body,SimpleNamespace(_log=log)


class RegisterTests(unittest.TestCase):
    def call(self,db,body=None):
        fn,default,module=register(db)
        with patch.dict(sys.modules,{'api.admin_orders':module}): return fn(body or default)
    def test_exact_three_unique_constraints_conflict_after_rollback(self):
        for key in ['products_pkey','products_sku_key','idx_products_danawa']:
            db=Database(integrity(key))
            with self.assertRaises(HTTPException) as caught: self.call(db)
            self.assertEqual(caught.exception.status_code,409)
            self.assertEqual(db.rollbacks,1); self.assertEqual(db.commits,0)
            self.assertEqual(db.writes,[])
            self.assertEqual(sum(q.startswith('SELECT COALESCE(MAX') for q,p in db.calls),1)
    def test_other_constraint_fk_or_unknown_state_propagates_same_exception(self):
        for key,state in [('unrelated_unique','23505'),('products_pkey','23503'),('products_sku_key',None)]:
            error=integrity(key,state); db=Database(error)
            with self.assertRaises(IntegrityError) as caught: self.call(db)
            self.assertIs(caught.exception,error); self.assertEqual(db.rollbacks,1)
    def test_pgcode_legacy_driver_supported(self):
        error=integrity(); del error.orig.sqlstate; error.orig.pgcode='23505'
        self.assertTrue(is_product_key_conflict(error))
    def test_original_identity_and_parent_before_children(self):
        db=Database(); result=self.call(db)
        self.assertEqual((result['sku'],result['product_code']),('P-12',204812))
        self.assertEqual(db.commits,1)
        self.assertTrue(db.writes[0].startswith('INSERT INTO products'))
        self.assertTrue(db.writes[1].startswith('INSERT INTO product_specs'))
        self.assertFalse(any('FOR UPDATE' in q for q,p in db.calls))
        self.assertFalse(any('product_price_history' in q or 'product_supplier_prices' in q for q,p in db.calls))
    def test_category_is_saved_with_the_product(self):
        # 2026-10-10 전수 점검: 등록 화면의 필수 카테고리가 잠겨 등록을 끝낼 수 없었다.
        db=Database(); fn,body,module=register(db); body.category_id=7
        with patch.dict(sys.modules,{'api.admin_orders':module}): fn(body)
        params=next(p for q,p in db.calls if q.startswith('INSERT INTO products'))
        self.assertEqual(params['cat'],7)
        self.assertIn('category_id',next(q for q,p in db.calls if q.startswith('INSERT INTO products')))
    def test_unknown_category_rejected_before_any_write(self):
        db=Database(); fn,body,module=register(db); body.category_id=999
        with patch.dict(sys.modules,{'api.admin_orders':module}),self.assertRaises(HTTPException) as caught: fn(body)
        self.assertEqual(caught.exception.status_code,400); self.assertEqual(db.writes,[])
    def test_late_failure_rolls_back_parent_without_409_conversion(self):
        error=integrity('product_specs_product_code_fkey','23503')
        db=Database(error,fail_at='INSERT INTO product_specs')
        with self.assertRaises(IntegrityError) as caught: self.call(db)
        self.assertIs(caught.exception,error); self.assertEqual(db.writes,[]); self.assertEqual(db.rollbacks,1)
    def test_supplier_mapping_conflict_original_409_full_rollback(self):
        db=Database(mapping=None); fn,body,module=register(db)
        body.supplier_id=11;body.model_name='원모델';body.cost_price=100
        with patch.dict(sys.modules,{'api.admin_orders':module}),self.assertRaises(HTTPException) as caught: fn(body)
        self.assertEqual(caught.exception.status_code,409)
        self.assertEqual(caught.exception.detail,'이미 연결된 단가표 모델입니다')
        self.assertEqual(db.writes,[]);self.assertEqual(db.rollbacks,1)
    def test_supplier_success_preserves_no_initial_history(self):
        db=Database(); fn,body,module=register(db)
        body.supplier_id=11;body.model_name='원모델';body.cost_price=100
        with patch.dict(sys.modules,{'api.admin_orders':module}): result=fn(body)
        self.assertEqual(result,{'ok':True,'sku':'P-12','product_code':204812})
        self.assertTrue(any('product_supplier_prices' in q for q in db.writes))
        self.assertFalse(any('product_price_history' in q for q in db.writes))
        self.assertEqual(db.commits,1)


if __name__=='__main__': unittest.main()
