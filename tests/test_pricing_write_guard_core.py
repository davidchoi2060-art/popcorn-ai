"""Pure connection-shaped checks; never import application DB or open a socket."""
import ast
import importlib
from pathlib import Path
import subprocess
import sys
import unittest
from api.pricing_write_guard_core import lock_products, ProductScopeChanged

class Connection:
 def __init__(self,rows):self.rows=rows;self.calls=[];self.tx=object()
 def execute(self,sql,params):self.calls.append((str(sql),params));return self
 def scalars(self):return self
 def all(self):return self.rows
 def begin(self):raise AssertionError('caller owns transaction')
 def commit(self):raise AssertionError('caller owns transaction')
 def rollback(self):raise AssertionError('caller owns transaction')
class GuardTests(unittest.TestCase):
 def test_sorted_unique_one_fixed_SQL_array_binding(self):
  c=Connection([1,3,7]);original=[7,1,3,1];self.assertEqual(lock_products(c,original),(1,3,7));self.assertEqual(original,[7,1,3,1])
  self.assertEqual(c.calls,[('SELECT product_code FROM products WHERE product_code = ANY(:codes) ORDER BY product_code FOR UPDATE',{'codes':[1,3,7]})]);self.assertIs(type(c.calls[0][1]['codes']),list)
 def test_tuple_input_and_single_product(self):
  c=Connection([9]);self.assertEqual(lock_products(c,(9,9)),(9,));self.assertEqual(len(c.calls),1)
 def test_empty_no_SQL(self):
  for values in ([],()):
   c=Connection(None);self.assertEqual(lock_products(c,values),());self.assertEqual(c.calls,[])
 def test_native_positive_IDs_only_no_conversion(self):
  for values in ([True],[False],[0],[-1],['1'],[1.0],[None],None,{1},'1',(x for x in [1])):
   with self.subTest(kind=type(values).__name__):
    c=Connection([1])
    with self.assertRaises(ProductScopeChanged):lock_products(c,values)
    self.assertEqual(c.calls,[])
 def test_subclass_containers_and_IDs_denied(self):
  class ListSubclass(list):pass
  class IntSubclass(int):pass
  for values in (ListSubclass([1]),[IntSubclass(1)]):
   with self.assertRaises(ProductScopeChanged):lock_products(Connection([1]),values)
 def test_missing_extra_duplicate_wrong_order_or_type_denied(self):
  for rows in ([],[1],[1,2,3],[1,3,3],[3,1],[True,3],[1,'3'],[1,3.0],(1,3),None):
   with self.subTest(rows=rows),self.assertRaises(ProductScopeChanged):lock_products(Connection(rows),[3,1])
 def test_scope_failure_constant_no_values_in_message(self):
  with self.assertRaises(ProductScopeChanged) as caught:lock_products(Connection([]),[123456])
  self.assertEqual(str(caught.exception),'product_scope_changed')
 def test_DB_exception_is_same_object_no_retry(self):
  error=RuntimeError('synthetic DB failure')
  class Failing(Connection):
   def execute(self,*args):self.calls.append(args);raise error
  c=Failing([])
  with self.assertRaises(RuntimeError) as caught:lock_products(c,[1])
  self.assertIs(caught.exception,error);self.assertEqual(len(c.calls),1)
 def test_caller_transaction_identity_not_changed(self):
  c=Connection([2]);tx=c.tx;self.assertEqual(lock_products(c,[2]),(2,));self.assertIs(c.tx,tx)
 def test_lightweight_import_no_api_db_or_main(self):
  code='import sys;sys.path.insert(0,'+repr(str(Path(__file__).resolve().parents[1]))+');import api.pricing_write_guard_core;assert not any(n=="api.db" or n=="api.main" or n.startswith("psycopg") for n in sys.modules)'
  result=subprocess.run([sys.executable,'-I','-B','-c',code],capture_output=True,text=True,timeout=15);self.assertEqual(result.returncode,0,result.stderr)
if __name__=='__main__':unittest.main()
