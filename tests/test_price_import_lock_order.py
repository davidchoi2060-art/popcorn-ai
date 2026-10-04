"""Compile only owned route functions; actual api.db/main imports are forbidden.
Native-shaped fakes run the unchanged repricing core. Thread test proves the
log-lock protocol in a mock, not PostgreSQL or general deadlock freedom.
"""
import ast
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from sqlalchemy import text
from api.pricing_write_guard_core import lock_products, ProductScopeChanged, _LOCK_PRODUCTS_SQL
from api.pricing_reprice_core import reprice
from api.html_text import strip_html_display

SOURCE=Path(__file__).resolve().parents[1]/'api/admin_price_import.py'

def routes():
 tree=ast.parse(SOURCE.read_text(encoding='utf-8'));nodes=[]
 for n in tree.body:
  if isinstance(n,ast.FunctionDef) and n.name in ('apply_rows','undo','_settings','_reprice','_log','_match'):
   n.decorator_list=[];nodes.append(n)
 env={'text':text,'HTTPException':HTTPException,'json':json,'current_operator_id':lambda:21,
      'lock_products':lock_products,'ProductScopeChanged':ProductScopeChanged,
      '_reprice_core':reprice,'strip_html_display':strip_html_display,'ApplyBody':object}
 exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),'exec'),env)
 return env

class Result:
 def __init__(self,values):self.values=deepcopy(values)
 def mappings(self):return self
 def scalars(self):return self
 def all(self):return deepcopy(self.values)
 def first(self):return deepcopy(self.values[0]) if self.values else None
 def one(self):
  if len(self.values)!=1:raise RuntimeError('expected one')
  return deepcopy(self.values[0])
 def scalar(self):return self.values[0] if self.values else None

class Database:
 def __init__(self):
  self.file={'file_id':301,'supplier_id':11,'received_at':datetime(2000,1,1),'status':'대기'}
  self.products={101:{'purchase_price':12000,'sale_price':13000,'locked_fields':[]},102:{'purchase_price':16000,'sale_price':17000,'locked_fields':[]},103:{'purchase_price':18000,'sale_price':19000,'locked_fields':[]}}
  self.psp={(101,11):(12000,'불가'),(102,11):(16000,'불가'),(103,11):(18000,'불가')}
  self.maps={'a':102,'b':101};self.rows={1:{'row_id':1,'model_name':'a','danawa_code':None,'prices':{},'cost_price':14000,'supply_state':'가능','memo':None},2:{'row_id':2,'model_name':'b','danawa_code':None,'prices':{},'cost_price':10000,'supply_state':'가능','memo':None}}
  self.eligible={1,2};self.logs={};self.history=[];self.connections=[];self.events=[];self.commits=0;self.rollbacks=0
  self.after_product_lock=None;self.lock_guard=threading.Lock();self.pause_first=False;self.first_locked=threading.Event();self.second_entered=threading.Event();self.release_first=threading.Event();self.stale_context=None
 def begin(self):return Transaction(self)
 def snapshot(self):return deepcopy((self.file,self.products,self.psp,self.logs,self.history))
 def restore(self,value):self.file,self.products,self.psp,self.logs,self.history=deepcopy(value)

class Transaction:
 def __init__(self,db):self.db=db
 def __enter__(self):self.c=Connection(self.db);self.db.connections.append(self.c);return self.c
 def __exit__(self,typ,value,trace):
  if typ:
   if self.c.wrote:self.db.restore(self.c.snapshot)
   self.db.rollbacks+=1
  else:self.db.commits+=1
  if self.c.guard_held:self.db.lock_guard.release()
  self.c.closed=True;return False

class Connection:
 def __init__(self,db):self.db=db;self.calls=[];self.snapshot=db.snapshot();self.wrote=False;self.guard_held=False;self.closed=False
 def execute(self,statement,params=None):
  q=str(statement);params={} if params is None else params;d=self.db;self.calls.append((q,deepcopy(params)));d.events.append((threading.current_thread().name,q,deepcopy(params)))
  if q==_LOCK_PRODUCTS_SQL:
   result=[pc for pc in params['codes'] if pc in d.products]
   if d.after_product_lock:d.after_product_lock(d);d.after_product_lock=None
   return Result(result)
  if q.startswith('SELECT file_id, supplier_id, received_at, status FROM supplier_price_files'):return Result([d.file] if d.file else [])
  if q.startswith('SELECT supplier_id FROM supplier_price_files'):return Result([{'supplier_id':d.file['supplier_id']}] if d.file else [])
  if q.startswith('SELECT card_fee_rate, margin_rate'):return Result([(0.02,0.03)])
  if q.startswith('SELECT action, detail FROM admin_operator_activity_logs'):
   if 'FOR UPDATE' in q:
    if d.pause_first and threading.current_thread().name=='undo-second':d.second_entered.set()
    d.lock_guard.acquire();self.guard_held=True;self.snapshot=d.snapshot()
    if d.pause_first and threading.current_thread().name=='undo-first':
     d.first_locked.set()
     if not d.release_first.wait(3):raise AssertionError('mock barrier timeout')
   return Result([d.logs[params['id']]] if params['id'] in d.logs else [])
  if q.startswith('SELECT 1 FROM admin_operator_activity_logs'):
   return Result([(1,)] if any(log['action']=='price_import_undo' and str(log['detail']['ref_log_id'])==params['id'] for log in d.logs.values()) else [])
  if q.startswith('SELECT cost_price, supply_state FROM product_supplier_prices'):
   value=d.psp.get((params['pc'],params['s']));return Result([value] if value is not None else [])
  if q.startswith('SELECT purchase_price, sale_price'):
   prod=d.products[params['pc']];keys=('purchase_price','sale_price','locked_fields') if 'locked_fields' in q else ('purchase_price','sale_price');return Result([{k:prod[k] for k in keys}])
  if q.startswith('SELECT cost_price, supply_state, supplier_id'):
   return Result([(cost,state,sid) for (pc,sid),(cost,state) in d.psp.items() if pc==params['pc']])
  if q.startswith('SELECT product_code, COALESCE'):
   return Result([{'product_code':pc,'label':'<b>상품'+str(pc)+'</b>'} for pc in set(params['codes'])])
  self.wrote=True
  if q.startswith('INSERT INTO product_supplier_prices'):d.psp[(params['pc'],params['s'])]=(params['c'],params['st']);return Result([])
  if q.startswith('UPDATE product_supplier_prices'):d.psp[(params['pc'],params['s'])]=(params['c'],params['st']);return Result([])
  if q.startswith('DELETE FROM product_supplier_prices'):d.psp.pop((params['pc'],params['s']),None);return Result([])
  if q.startswith('UPDATE products SET purchase_price'):d.products[params['pc']]['purchase_price']=params['v'];return Result([])
  if q.startswith('UPDATE products SET sale_price'):d.products[params['pc']]['sale_price']=params['v'];return Result([])
  if q.startswith('INSERT INTO product_price_history'):d.history.append(deepcopy(params));return Result([])
  if q.startswith('UPDATE supplier_price_files SET status'):d.file['status']=params['s'];return Result([])
  if q.startswith('INSERT INTO admin_operator_activity_logs'):
   number=max(d.logs,default=0)+1;d.logs[number]={'action':params['a'],'detail':json.loads(params['d'])};return Result([number])
  raise AssertionError('unexpected SQL '+q)

class PriceImportTests(unittest.TestCase):
 def setUp(self):
  self.db=Database();self.env=routes();self.env['engine']=self.db
  def ctx(conn,sid):return {'maps':dict(self.db.maps),'danawa':{},'products':deepcopy(self.db.stale_context or self.db.products)}
  def diff(conn,file,context):
   pending={}
   for rid,row in self.db.rows.items():
    pc=self.env['_match'](row,context);existing=self.db.psp.get((pc,file['supplier_id']))
    if rid in self.db.eligible and pc is not None and existing!=(row['cost_price'],row['supply_state']):pending[rid]=deepcopy(row)
   return {'pending':pending}
  self.env['_ctx']=ctx;self.env['_file_diff']=diff
 def apply(self,ids=(2,1)):return self.env['apply_rows'](301,SimpleNamespace(row_ids=list(ids)))
 def undo(self,log_id):return self.env['undo'](log_id)
 def mutations(self):return [q for _t,q,_p in self.db.events if q.startswith(('INSERT ','UPDATE ','DELETE '))]
 def test_apply_whole_ascending_scope_before_file_and_PSP(self):
  out=self.apply();calls=self.db.connections[0].calls;lock=next(i for i,(q,p) in enumerate(calls) if q==_LOCK_PRODUCTS_SQL);filelock=next(i for i,(q,p) in enumerate(calls) if 'supplier_price_files' in q and 'FOR UPDATE' in q);psp=next(i for i,(q,p) in enumerate(calls) if 'product_supplier_prices' in q and 'FOR UPDATE' in q)
  self.assertEqual(calls[lock][1],{'codes':[101,102]});self.assertLess(lock,filelock);self.assertLess(filelock,psp)
  self.assertEqual(out,{'applied':2,'price_changed':2,'sale_locked_skipped':0,'undo_id':1,'file_status':'반영 완료'})
  self.assertEqual([it['row_id'] for it in self.db.logs[1]['detail']['items']],[1,2]);self.assertEqual(len(self.db.history),4)
 def test_missing_product_rejects_before_file_or_write(self):
  del self.db.products[102]
  with self.assertRaises(HTTPException) as caught:self.apply()
  self.assertEqual(caught.exception.status_code,409);self.assertEqual(self.mutations(),[]);self.assertFalse(any('supplier_price_files' in q and 'FOR UPDATE' in q for _t,q,_p in self.db.events))
 def test_scope_swap_with_same_set_rejects_no_late_lock(self):
  self.db.after_product_lock=lambda db:db.maps.update({'a':101,'b':102})
  with self.assertRaises(HTTPException) as caught:self.apply()
  self.assertEqual(caught.exception.status_code,409);self.assertEqual(self.mutations(),[]);self.assertEqual(sum(q==_LOCK_PRODUCTS_SQL for _t,q,_p in self.db.events),1)
 def test_expanded_mapping_rejects_without_new_product_lock(self):
  self.db.after_product_lock=lambda db:db.maps.update({'a':103})
  with self.assertRaises(HTTPException) as caught:self.apply()
  self.assertEqual(caught.exception.status_code,409);self.assertEqual(self.mutations(),[]);self.assertEqual([p['codes'] for _t,q,p in self.db.events if q==_LOCK_PRODUCTS_SQL],[[101,102]])
 def test_selected_row_value_or_eligibility_drift_rejects(self):
  for change in (lambda db:db.rows[1].update(cost_price=13000),lambda db:db.eligible.remove(1)):
   self.setUp();self.db.after_product_lock=change
   with self.assertRaises(HTTPException) as caught:self.apply()
   self.assertEqual(caught.exception.status_code,409);self.assertEqual(self.mutations(),[])
 def test_file_supplier_drift_rejects(self):
  self.db.after_product_lock=lambda db:db.file.update(supplier_id=12)
  with self.assertRaises(HTTPException) as caught:self.apply()
  self.assertEqual(caught.exception.status_code,409);self.assertEqual(self.mutations(),[])
 def test_existing_initial_missing_complete_empty_bad_row_policy(self):
  for change,ids,status in ((lambda db:setattr(db,'file',None),(1,),404),(lambda db:db.file.update(status='반영 완료'),(1,),409),(lambda db:None,(),400),(lambda db:None,(99,),400)):
   self.setUp();change(self.db)
   with self.assertRaises(HTTPException) as caught:self.apply(ids)
   self.assertEqual(caught.exception.status_code,status);self.assertEqual(self.mutations(),[])
 def test_current_product_before_not_cached_ctx(self):
  self.db.stale_context=deepcopy(self.db.products);self.db.after_product_lock=lambda db:db.products[101].update(purchase_price=21000,sale_price=23000)
  self.apply();items=self.db.logs[1]['detail']['items'];self.assertEqual(next(i for i in items if i['product_code']==101)['product_before'],{'purchase':21000,'sale':23000})
 def test_same_product_multiple_rows_keep_order_and_current_before(self):
  self.db.maps['a']=101;out=self.apply();items=self.db.logs[1]['detail']['items'];self.assertEqual([it['row_id'] for it in items],[1,2]);self.assertEqual(out['applied'],2);self.assertEqual(items[0]['product_before'],{'purchase':12000,'sale':13000});self.assertEqual(items[1]['product_before'],{'purchase':14000,'sale':15000})
  self.assertEqual([p['codes'] for _t,q,p in self.db.events if q==_LOCK_PRODUCTS_SQL],[[101]])
 def test_duplicate_input_rows_policy_preserved_not_deduplicated(self):
  out=self.apply((2,2));self.assertEqual(out['applied'],2);self.assertEqual([it['row_id'] for it in self.db.logs[1]['detail']['items']],[2,2]);self.assertEqual([p['codes'] for _t,q,p in self.db.events if q==_LOCK_PRODUCTS_SQL],[[101]])
 def test_sale_locked_policy_and_log_before_preserved(self):
  self.db.products[101]['locked_fields']=['sale_price'];out=self.apply((2,));self.assertEqual(out['sale_locked_skipped'],1);self.assertEqual(self.db.products[101]['sale_price'],13000);self.assertEqual(len(self.db.history),1)
 def test_exception_after_PSP_write_propagates_same_and_caller_rolls_back(self):
  old=self.db.snapshot();error=RuntimeError('synthetic core failure')
  def fail(*args,**kwargs):raise error
  self.env['_reprice_core']=fail
  with self.assertRaises(RuntimeError) as caught:self.apply()
  self.assertIs(caught.exception,error);self.assertEqual(self.db.snapshot(),old);self.assertEqual(self.db.rollbacks,1);self.assertEqual(self.db.commits,0)
 def test_undo_exception_after_first_restore_propagates_and_rolls_back(self):
  self.apply();old=self.db.snapshot();commits=self.db.commits;error=RuntimeError('synthetic undo failure')
  def fail(*args,**kwargs):raise error
  self.env['_reprice_core']=fail
  with self.assertRaises(RuntimeError) as caught:self.undo(1)
  self.assertIs(caught.exception,error);self.assertEqual(self.db.snapshot(),old);self.assertEqual(self.db.rollbacks,1);self.assertEqual(self.db.commits,commits)
 def test_post_lock_missing_complete_file_preserves_error_policy(self):
  for change,status in ((lambda db:setattr(db,'file',None),404),(lambda db:db.file.update(status='반영 완료'),409)):
   self.setUp()
   self.db.after_product_lock=change
   with self.assertRaises(HTTPException) as caught:self.apply()
   self.assertEqual(caught.exception.status_code,status);self.assertEqual(self.mutations(),[])
 def test_undo_log_guard_products_file_PSP_full_scan_then_restore(self):
  out=self.apply();before=len(self.db.events);result=self.undo(out['undo_id']);calls=self.db.connections[-1].calls
  self.assertIn('FOR UPDATE',calls[0][0]);locks=[i for i,(q,p) in enumerate(calls) if q==_LOCK_PRODUCTS_SQL];self.assertEqual(len(locks),1);self.assertEqual(calls[locks[0]][1],{'codes':[101,102]})
  filelock=next(i for i,(q,p) in enumerate(calls) if 'supplier_price_files' in q);psplocks=[i for i,(q,p) in enumerate(calls) if 'product_supplier_prices' in q and 'FOR UPDATE' in q];firstwrite=next(i for i,(q,p) in enumerate(calls) if q.startswith(('UPDATE ','DELETE ','INSERT ')))
  self.assertLess(locks[0],filelock);self.assertTrue(all(filelock<i<firstwrite for i in psplocks));self.assertEqual(len(psplocks),2);self.assertEqual(result,{'ok':True,'restored':2});self.assertEqual(self.db.products[101]['purchase_price'],12000);self.assertEqual(self.db.products[101]['sale_price'],13000)
 def test_undo_conflicts_list_all_before_any_mutation(self):
  self.apply();self.db.psp[(101,11)]=(9999,'가능');self.db.psp[(102,11)]=(9998,'가능');before=len(self.mutations())
  with self.assertRaises(HTTPException) as caught:self.undo(1)
  self.assertEqual(caught.exception.status_code,409);self.assertIn('101(',caught.exception.detail);self.assertIn('102(',caught.exception.detail);self.assertNotIn('<b>',caught.exception.detail);self.assertEqual(len(self.mutations()),before)
 def test_undo_missing_product_rejects_before_file_child_write(self):
  self.apply();del self.db.products[102];before=len(self.mutations())
  with self.assertRaises(HTTPException) as caught:self.undo(1)
  self.assertEqual(caught.exception.status_code,409);self.assertEqual(len(self.mutations()),before)
 def test_undo_first_PSP_delete_restore_zero_supplier_path_unchanged(self):
  del self.db.psp[(101,11)];self.apply((2,));self.assertIsNone(self.db.logs[1]['detail']['items'][0]['psp_before']);self.undo(1);self.assertNotIn((101,11),self.db.psp);self.assertEqual(self.db.products[101]['sale_price'],13000)
 def test_undo_twice_guard_409_before_product_lock(self):
  self.apply();self.undo(1)
  with self.assertRaises(HTTPException) as caught:self.undo(1)
  self.assertEqual(caught.exception.status_code,409);self.assertFalse(any(q==_LOCK_PRODUCTS_SQL for q,p in self.db.connections[-1].calls))
 def test_concurrent_same_undo_log_guard_prevents_duplicate_restore(self):
  self.apply();self.db.pause_first=True;values=[];errors=[];done=threading.Event()
  def run(first):
   try:values.append(self.undo(1))
   except BaseException as exc:errors.append(exc)
   finally:
    if not first:done.set()
  first=threading.Thread(target=run,args=(True,),name='undo-first');second=threading.Thread(target=run,args=(False,),name='undo-second');first.start();self.assertTrue(self.db.first_locked.wait(2));second.start();self.assertTrue(self.db.second_entered.wait(2));self.assertFalse(done.is_set());self.db.release_first.set();first.join(3);second.join(3)
  self.assertFalse(first.is_alive());self.assertFalse(second.is_alive());self.assertEqual(values,[{'ok':True,'restored':2}]);self.assertEqual(len(errors),1);self.assertIsInstance(errors[0],HTTPException);self.assertEqual(errors[0].status_code,409);self.assertEqual(sum(log['action']=='price_import_undo' for log in self.db.logs.values()),1)
 def test_owned_route_extraction_never_imported_db_or_main(self):
  self.assertNotIn('api.db',sys.modules);self.assertNotIn('api.main',sys.modules)
if __name__=='__main__':unittest.main()
