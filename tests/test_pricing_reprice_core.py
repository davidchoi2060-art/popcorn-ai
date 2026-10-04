"""No-connect tests for the same repricing core used by the legacy adapter.

SQL/scripted responses do not establish PostgreSQL writer concurrency safety.
"""
import ast
import copy
import inspect
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from api.pricing_reprice_core import reprice
from api.pricing import sale_from_purchase

PRODUCT_SQL=('SELECT purchase_price, sale_price, locked_fields FROM products'
             ' WHERE product_code=:pc FOR UPDATE')
PSP_SQL=('SELECT cost_price, supply_state, supplier_id FROM product_supplier_prices'
         ' WHERE product_code=:pc')
PURCHASE_UPDATE='UPDATE products SET purchase_price=:v, updated_at=now() WHERE product_code=:pc'
SALE_UPDATE='UPDATE products SET sale_price=:v, updated_at=now() WHERE product_code=:pc'
PURCHASE_HISTORY=('INSERT INTO product_price_history'
 ' (product_code, field, old_price, new_price, reason, ref_id, changed_by, supplier_id)'
 " VALUES (:pc, 'purchase', :o, :n, :r, :ref, :op, :sid)")
SALE_HISTORY=('INSERT INTO product_price_history (product_code, field, old_price, new_price, reason, ref_id, changed_by)'
 " VALUES (:pc, 'sale', :o, :n, :r, :ref, :op)")

class Result:
    def __init__(self,value): self.value=value
    def mappings(self): return self
    def one(self): return self.value
    def all(self): return self.value

class ScriptedConnection:
    def __init__(self,product,rows):
        self.product=product;self.rows=rows;self.calls=[];self.fail_query=None
    def execute(self,query,parameters):
        q=str(query);self.calls.append((q,dict(parameters)))
        if self.fail_query==q: raise RuntimeError('SQL failure sentinel')
        if q==PRODUCT_SQL:return Result(self.product)
        if q==PSP_SQL:return Result(self.rows)
        if q not in (PURCHASE_UPDATE,SALE_UPDATE,PURCHASE_HISTORY,SALE_HISTORY):
            raise AssertionError('unregistered SQL')
        return Result(None)
    def begin(self): raise AssertionError('caller owns transaction')
    def commit(self): raise AssertionError('caller owns transaction')
    def rollback(self): raise AssertionError('caller owns transaction')

class RepriceCoreTests(unittest.TestCase):
    def run_case(self,purchase=1000,sale=1000,locks=None,rows=((9000,'가능',7),),
                 restore=None,fee=0,margin=0):
        product={'purchase_price':purchase,'sale_price':sale,'locked_fields':locks}
        snapshot=copy.deepcopy((product,rows,restore));c=ScriptedConnection(product,rows)
        events=[]
        def actor(): events.append(len(c.calls));return 40+len(events)
        result=reprice(c,123,fee,margin,'price_import_undo',88,restore,operator_id=actor)
        self.assertEqual((product,rows,restore),snapshot)
        self.assertEqual(c.calls[:2],[(PRODUCT_SQL,{'pc':123}),(PSP_SQL,{'pc':123})])
        return result,c,events

    def test_two_changes_exact_sql_actor_timing_and_history(self):
        result,c,events=self.run_case()
        self.assertEqual(result,{'purchase_changed':True,'sale_changed':True,'sale_locked':False})
        self.assertEqual(events,[3,5])
        self.assertEqual(c.calls[2:],[(PURCHASE_UPDATE,{'v':9000,'pc':123}),
          (PURCHASE_HISTORY,{'pc':123,'o':1000,'n':9000,'r':'price_import_undo','ref':88,'op':41,'sid':7}),
          (SALE_UPDATE,{'v':9000,'pc':123}),
          (SALE_HISTORY,{'pc':123,'o':1000,'n':9000,'r':'price_import_undo','ref':88,'op':42})])

    def test_available_supplier_priority_over_cheaper_unavailable(self):
        _,c,_=self.run_case(rows=((100,'불가',1),(9000,'가능',7),(8000,'가능',9)))
        self.assertEqual(c.calls[2][1]['v'],8000);self.assertEqual(c.calls[3][1]['sid'],9)

    def test_available_lowest_cost_tie_uses_lowest_supplier(self):
        _,c,_=self.run_case(rows=((9000,'가능',9),(9000,'가능',3),(9000,'가능',7)))
        self.assertEqual(c.calls[3][1]['sid'],3)

    def test_no_available_falls_back_to_all_lowest_and_supplier_tie(self):
        _,c,_=self.run_case(rows=((8000,'불가',9),(9000,'대기',1),(8000,'중단',3)))
        self.assertEqual(c.calls[2][1]['v'],8000);self.assertEqual(c.calls[3][1]['sid'],3)

    def test_no_psp_no_restore_returns_exact_noop_before_actor(self):
        r,c,events=self.run_case(rows=())
        self.assertEqual(r,dict(purchase_changed=False,sale_changed=False,sale_locked=False))
        self.assertEqual(len(c.calls),2);self.assertEqual(events,[])

    def test_no_psp_restore_uses_original_nonformula_sale_and_null_supplier(self):
        _,c,_=self.run_case(rows=(),restore={'purchase':7000,'sale':7777,'extra':['keep']})
        self.assertEqual(c.calls[2][1]['v'],7000);self.assertIsNone(c.calls[3][1]['sid'])
        self.assertEqual(c.calls[4][1]['v'],7777)

    def test_restore_matching_purchase_uses_snapshot_sale(self):
        _,c,_=self.run_case(restore={'purchase':9000,'sale':7777})
        self.assertEqual(c.calls[4][1]['v'],7777)

    def test_restore_crossed_purchase_keeps_formula(self):
        _,c,_=self.run_case(restore={'purchase':7000,'sale':7777},fee=.025,margin=.1)
        self.assertEqual(c.calls[4][1]['v'],sale_from_purchase(9000,.025,.1))

    def test_locked_sale_preserves_price_and_no_sale_history(self):
        r,c,events=self.run_case(locks=['sale_price','spec'],restore={'purchase':9000,'sale':7777})
        self.assertEqual(r,dict(purchase_changed=True,sale_changed=False,sale_locked=True))
        self.assertEqual([q for q,p in c.calls],[PRODUCT_SQL,PSP_SQL,PURCHASE_UPDATE,PURCHASE_HISTORY])
        self.assertEqual(events,[3])

    def test_locked_matching_sale_is_not_reported_skipped(self):
        r,c,events=self.run_case(purchase=9000,sale=9000,locks=['sale_price'])
        self.assertFalse(r['sale_locked']);self.assertEqual(len(c.calls),2);self.assertEqual(events,[])

    def test_sale_only_transition_actor_once(self):
        r,c,events=self.run_case(purchase=9000)
        self.assertEqual(r,dict(purchase_changed=False,sale_changed=True,sale_locked=False))
        self.assertEqual(c.calls[2][0],SALE_UPDATE);self.assertEqual(c.calls[3][0],SALE_HISTORY)
        self.assertEqual(events,[3])

    def test_purchase_only_transition_actor_once(self):
        r,c,events=self.run_case(sale=9000)
        self.assertEqual(r,dict(purchase_changed=True,sale_changed=False,sale_locked=False))
        self.assertEqual(events,[3]);self.assertEqual(len(c.calls),4)

    def test_nullable_original_and_restore_prices_preserved(self):
        r,c,_=self.run_case(purchase=None,sale=None,rows=(),restore={'purchase':None,'sale':None})
        self.assertFalse(r['purchase_changed']);self.assertFalse(r['sale_changed']);self.assertEqual(len(c.calls),2)
        r,c,_=self.run_case(rows=(),restore={'purchase':None,'sale':None})
        self.assertIsNone(c.calls[2][1]['v']);self.assertIsNone(c.calls[4][1]['v'])

    def test_sql_exception_identity_propagates_without_actor_or_tx(self):
        c=ScriptedConnection({'purchase_price':1000,'sale_price':1000,'locked_fields':None},[(9000,'가능',7)])
        c.fail_query=PURCHASE_UPDATE;actor=Mock()
        with self.assertRaisesRegex(RuntimeError,'SQL failure sentinel'):
            reprice(c,123,0,0,'sourcing',88,operator_id=actor)
        actor.assert_not_called();self.assertEqual(len(c.calls),3)

    def test_actor_exception_after_update_propagates_before_history(self):
        c=ScriptedConnection({'purchase_price':1000,'sale_price':1000,'locked_fields':None},[(9000,'가능',7)])
        failure=RuntimeError('actor lookup sentinel');actor=Mock(side_effect=failure)
        with self.assertRaises(RuntimeError) as got:reprice(c,123,0,0,'sourcing',88,operator_id=actor)
        self.assertIs(got.exception,failure);self.assertEqual(len(c.calls),3);actor.assert_called_once_with()

    def test_existing_mixed_null_cost_typeerror_is_not_silently_normalized(self):
        c=ScriptedConnection({'purchase_price':1000,'sale_price':1000,'locked_fields':None},[(None,'가능',7),(9000,'가능',8)])
        actor=Mock()
        with self.assertRaises(TypeError):reprice(c,123,0,0,'sourcing',88,operator_id=actor)
        actor.assert_not_called();self.assertEqual(len(c.calls),2)

    def test_missing_restore_sale_error_preserves_original_lookup_order(self):
        c=ScriptedConnection({'purchase_price':1000,'sale_price':1000,'locked_fields':None},[])
        actor=Mock(return_value=41)
        with self.assertRaises(KeyError):reprice(c,123,0,0,'undo',88,{'purchase':7000},operator_id=actor)
        self.assertEqual([q for q,p in c.calls],[PRODUCT_SQL,PSP_SQL,PURCHASE_UPDATE,PURCHASE_HISTORY]);actor.assert_called_once_with()

class AdapterAndImportTests(unittest.TestCase):
    def adapter(self):
        # Execute only the checked-in adapter AST to avoid importing operating
        # db/auth modules; this is an offline wiring check, not an HTTP/PG test.
        tree=ast.parse((ROOT/'api/admin_price_import.py').read_text(encoding='utf-8'))
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_reprice')
        imported=next(n for n in tree.body if isinstance(n,ast.ImportFrom) and n.module=='pricing_reprice_core')
        self.assertEqual([(n.name,n.asname) for n in imported.names],[('reprice','_reprice_core')])
        self.assertEqual(len(node.body),2);self.assertIsInstance(node.body[1],ast.Return)
        actor=Mock(return_value=37);scope={'_reprice_core':reprice,'current_operator_id':actor}
        module=ast.Module(body=[node],type_ignores=[]);exec(compile(module,'checked-in-adapter','exec'),scope)
        return scope['_reprice'],actor

    def test_actual_adapter_function_routes_to_real_core_with_lazy_actor(self):
        adapter,actor=self.adapter();c=ScriptedConnection({'purchase_price':1000,'sale_price':1000,'locked_fields':None},[(9000,'가능',7)])
        self.assertEqual(tuple(inspect.signature(adapter).parameters),('conn','pc','fee','margin','reason','ref_id','restore'))
        self.assertEqual(adapter(c,123,0,0,'sourcing',88),dict(purchase_changed=True,sale_changed=True,sale_locked=False))
        self.assertEqual(actor.call_count,2);self.assertEqual(c.calls[3][1]['op'],37);self.assertEqual(c.calls[5][1]['op'],37)

    def test_adapter_does_not_eagerly_lookup_actor_on_noop(self):
        adapter,actor=self.adapter();c=ScriptedConnection({'purchase_price':None,'sale_price':None,'locked_fields':None},[])
        adapter(c,123,0,0,'sourcing',88);actor.assert_not_called()

    def test_fresh_core_import_blocks_operating_dependencies_and_network(self):
        code="""import sys,socket,importlib.abc
sys.path.insert(0,ROOT)
class Forbidden(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname in ('api.db','api.main','api.auth','api.admin_price_import','api.admin_sourcing','api.admin_products') or fullname.startswith(('psycopg','dotenv')):
   raise AssertionError('operating dependency forbidden')
sys.meta_path.insert(0,Forbidden())
class ForbiddenSocket(socket.socket):
 def __new__(cls,*a,**k): raise AssertionError('network forbidden')
socket.socket=ForbiddenSocket
import api.pricing_reprice_core as core
assert callable(core.reprice)
assert not any(n in sys.modules for n in ('api.db','api.main','api.auth','api.admin_price_import'))
""".replace('ROOT',repr(str(ROOT)))
        p=subprocess.run([sys.executable,'-I','-B','-c',code],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)

if __name__=='__main__': unittest.main()
