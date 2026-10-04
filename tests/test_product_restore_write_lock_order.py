"""Selected actual route AST with native-shaped mocks; no PG concurrency claim."""
import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest
from fastapi import HTTPException
from sqlalchemy import text
from api.pricing_write_guard_core import lock_products, ProductScopeChanged, _LOCK_PRODUCTS_SQL

ROUTES = ('undo_product_edit', 'undo_spec_edit', 'undo_part_type', 'merge_product',
          'undo_merge', 'bulk_status', 'bulk_status_undo')


def routes():
    source = Path(__file__).resolve().parents[1] / 'api/admin_products.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    class LocalImports(ast.NodeTransformer):
        def visit_ImportFrom(self, node): return None
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in (*ROUTES, '_lock_restore_products', '_pool_count'):
            node.decorator_list = []
            nodes.append(LocalImports().visit(node))
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in
                ('EDITABLE', 'PRICE_HISTORY_FIELD', 'STATUS_OK', 'MAX_BULK') for t in node.targets):
            nodes.append(node)
    env = dict(text=text, HTTPException=HTTPException, lock_products=lock_products,
               ProductScopeChanged=ProductScopeChanged, MergeBody=object, BulkStatusBody=object,
               BulkUndoBody=object, _s=lambda v: v, current_operator_id=lambda: 21,
               SF=SimpleNamespace(field_cast=lambda: {'length_mm': 'integer'}))
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(source), 'exec'), env)
    return env


class Result:
    def __init__(self, rows=(), rowcount=0): self.rows = deepcopy(list(rows)); self.rowcount = rowcount
    def mappings(self): return self
    def scalars(self): return self
    def all(self): return deepcopy(self.rows)
    def first(self): return deepcopy(self.rows[0]) if self.rows else None
    def scalar_one(self):
        if len(self.rows) != 1: raise AssertionError('one expected')
        return self.first()


class Database:
    def __init__(self):
        self.products = {pc: {'product_code': pc, 'sku': str(pc), 'product_name': 'P'+str(pc),
            'part_type': 'GPU', 'status': '판매중', 'stock_qty': qty,
            'locked_fields': []} for pc, qty in ((101, 8), (102, 3))}
        self.source_log = None
        self.undo_exists = False
        self.suppliers = [{'supplier_id': 11, 'cost_price': 12000, 'supply_state': '가능'}]
        self.calls = []; self.logs = []; self.writes = []
        self.after_product_lock = None; self.after_log_lock = None
        self.error = None; self.log_error = None
        self.commits = self.rollbacks = 0; self.authorizations = 0
    def begin(self): return Transaction(self)
    def authorize(self): self.authorizations += 1
    def log(self, conn, action, target, detail, **kwargs):
        self.logs.append((action, target, deepcopy(detail), kwargs))
        if self.log_error: raise self.log_error
        return 91


class Transaction:
    def __init__(self, db): self.db = db
    def __enter__(self): self.conn = Connection(self.db); return self.conn
    def __exit__(self, typ, value, trace):
        if typ:
            self.db.rollbacks += 1
            self.db.products, self.db.writes, self.db.logs = deepcopy(self.conn.snapshot)
        else: self.db.commits += 1
        return False


class Connection:
    def __init__(self, db): self.db = db; self.refresh_snapshot()
    def refresh_snapshot(self): self.snapshot = deepcopy((self.db.products, self.db.writes, self.db.logs))
    def execute(self, statement, params=None):
        q = str(statement); p = params or {}; d = self.db
        d.calls.append((q, deepcopy(p)))
        if q == _LOCK_PRODUCTS_SQL:
            if d.error: raise d.error
            if d.after_product_lock:
                callback = d.after_product_lock; d.after_product_lock = None; callback(d)
            self.refresh_snapshot()
            return Result([pc for pc in p['codes'] if pc in d.products])
        if q.startswith(('SELECT action, detail FROM admin_operator_activity_logs',
                         'SELECT detail, action FROM admin_operator_activity_logs')):
            if d.after_log_lock:
                callback = d.after_log_lock; d.after_log_lock = None; callback(d)
            self.refresh_snapshot()
            return Result([d.source_log] if d.source_log else [])
        if q.startswith('SELECT 1 FROM admin_operator_activity_logs'):
            return Result([(1,)] if d.undo_exists else [])
        if q.startswith('SELECT product_code, sku, product_name'):
            return Result([d.products[p['pc']]] if p['pc'] in d.products else [])
        if q.startswith('SELECT product_code, status, locked_fields'):
            return Result([d.products[pc] for pc in sorted(d.products) if pc in p['c']])
        if q.startswith('SELECT stock_qty FROM products'):
            return Result([d.products[p['p']]['stock_qty']])
        if q.startswith('SELECT ') and q.endswith(' FROM products WHERE product_code=:pc'):
            return Result([d.products[p['pc']]] if p['pc'] in d.products else [])
        if q.startswith('SELECT sp.supplier_id'): return Result(d.suppliers)
        if q.startswith('SELECT count(*) FROM v_recommendation_candidates'):
            return Result([sum(r['status'] == '판매중' and r['stock_qty'] > 0 for r in d.products.values())])
        if q.startswith(('INSERT ', 'UPDATE ', 'DELETE ')):
            d.writes.append((q, deepcopy(p)))
            if q.startswith('UPDATE products SET status = :s'):
                for pc in p.get('c', [p.get('pc')]): d.products[pc]['status'] = p['s']
            return Result(rowcount=2 if q.startswith('UPDATE product_reviews') else 0)
        raise AssertionError('unexpected SQL ' + q)


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(); self.env = routes()
        self.env.update(engine=self.db, _log=self.db.log, _bulk_operator=self.db.authorize,
                        _ref_counts=lambda conn, pc: {'orders': 2})
    def original_log(self, action, detail): self.db.source_log = {'action': action, 'detail': detail}
    def run_undo(self, route, detail=None):
        default = {'product_code': 102, 'sku': '102', 'changes': {'sale_price': {'from': None, 'to': 13000},
            'stock_qty': {'from': 3, 'to': 7}}, 'before': {'locked_fields': [], 'category_group': 'core'}, 'from': 'GPU'}
        if route == 'undo_spec_edit': default['changes'] = {'length_mm': {'from': 240, 'to': 300}}
        if route == 'undo_merge': default = {'dup': 102, 'into': 101, 'moved_stock': 3,
            'moved_suppliers': [11], 'before': {'status': '판매중'}, 'dup_sku': '102'}
        if route == 'bulk_status_undo': default = {'before': [{'pc': 102, 'st': '품절'}, {'pc': 101, 'st': '판매중'}]}
        action = {'undo_product_edit': 'product_edit', 'undo_spec_edit': 'spec_edit',
            'undo_part_type': 'part_type_change', 'undo_merge': 'product_merge',
            'bulk_status_undo': '상품 상태 일괄 변경'}[route]
        if route == 'undo_product_edit' and detail is None:
            default['locked'] = False
            self.db.products[102].update(sale_price=13000, stock_qty=7)
        self.original_log(action, default if detail is None else detail)
        return self.env[route](SimpleNamespace(log_id=70) if route == 'bulk_status_undo' else 70)
    def merge(self, dup=102, into=101, preview=False):
        return self.env['merge_product'](dup, SimpleNamespace(into=into, preview=preview))
    def bulk(self, codes=(102, 101), status='품절'):
        return self.env['bulk_status'](SimpleNamespace(product_codes=list(codes), status=status))
    def guards(self): return [(i,p['codes']) for i,(q,p) in enumerate(self.db.calls) if q == _LOCK_PRODUCTS_SQL]
    def assert_no_write_http(self, fn, status, detail=None):
        with self.assertRaises(HTTPException) as caught: fn()
        self.assertEqual(caught.exception.status_code, status)
        if detail: self.assertEqual(caught.exception.detail, detail)
        self.assertEqual(self.db.writes, []); self.assertEqual(self.db.logs, [])
        self.assertFalse(any(q.startswith(('UPDATE ', 'INSERT ', 'DELETE ')) for q,p in self.db.calls))
    def test_merge_both_request_directions_lock_complete_asc_before_children(self):
        for dup, into in ((102,101),(101,102)):
            self.setUp(); out=self.merge(dup,into); guard=self.guards()
            self.assertEqual([p for i,p in guard], [[101,102]])
            self.assertEqual(sum('FOR UPDATE' in q for q,p in self.db.calls),1)
            self.assertLess(guard[0][0], next(i for i,(q,p) in enumerate(self.db.calls) if 'product_supplier_prices' in q))
            self.assertEqual(out['undo_id'],91); self.assertEqual(out['reviews_closed'],2)
            stocks=[p for q,p in self.db.writes if q.startswith('INSERT INTO stock_movements')]
            qty=self.db.products[dup]['stock_qty']; self.assertEqual([p['q'] for p in stocks],[-qty,qty])
            self.assertEqual(self.db.logs[0][2]['moved_suppliers'],[11])
    def test_merge_preview_still_locks_and_rereads_current_stock_status(self):
        self.db.after_product_lock=lambda d:d.products[102].update(stock_qty=9,part_type='CPU')
        out=self.merge(preview=True);self.assertTrue(out['preview']);self.assertEqual(out['impact']['move_stock'],9)
        self.assertFalse(out['impact']['part_type_same']);self.assertEqual(self.guards()[0][1],[101,102])
        self.assertEqual(self.db.writes,[]);self.assertEqual(self.db.logs,[])
    def test_merge_current_already_deleted_409_before_write(self):
        self.db.after_product_lock=lambda d:d.products[102].update(status='삭제대기')
        self.assert_no_write_http(self.merge,409,'이미 정리된 상품입니다')
    def test_merge_same_product400_initial_missing404_and_wait_loss409(self):
        self.assert_no_write_http(lambda:self.merge(101,101),400);self.assertEqual(self.db.calls,[])
        self.setUp();self.db.products.pop(102);self.assert_no_write_http(self.merge,404);self.assertEqual(self.guards(),[])
        self.setUp();self.db.after_product_lock=lambda d:d.products.pop(102);self.assert_no_write_http(self.merge,409)
    def test_all_undo_original_log_lock_precedes_duplicate_and_one_complete_product_guard(self):
        for route in ('undo_product_edit','undo_spec_edit','undo_part_type','undo_merge','bulk_status_undo'):
            self.setUp();self.run_undo(route);self.assertIn('FOR UPDATE',self.db.calls[0][0])
            guard=self.guards();self.assertEqual(len(guard),1)
            self.assertEqual(guard[0][1],[101,102] if route in ('undo_merge','bulk_status_undo') else [102])
            duplicate=next(i for i,(q,p) in enumerate(self.db.calls) if q.startswith('SELECT 1 FROM admin_operator_activity_logs'))
            self.assertLess(duplicate,guard[0][0])
            child=next(i for i,(q,p) in enumerate(self.db.calls) if q.startswith(('UPDATE ','INSERT ','DELETE ')))
            self.assertLess(guard[0][0],child)
    def test_duplicate_visible_after_original_log_wait_all_undo409_without_guard_write(self):
        details={'undo_product_edit':'이미 되돌린 수정입니다','undo_spec_edit':'이미 되돌린 입력입니다',
            'undo_part_type':'이미 되돌린 변경입니다','undo_merge':'이미 되돌린 편입입니다','bulk_status_undo':'이미 되돌린 기록입니다'}
        for route,detail in details.items():
            self.setUp();self.db.after_log_lock=lambda d:setattr(d,'undo_exists',True)
            self.assert_no_write_http(lambda:self.run_undo(route),409,detail);self.assertEqual(self.guards(),[])
            self.assertIn('FOR UPDATE',self.db.calls[0][0])
    def test_undo_missing_products_all409_no_children(self):
        for route in ('undo_product_edit','undo_spec_edit','undo_part_type','undo_merge','bulk_status_undo'):
            self.setUp();self.db.after_product_lock=lambda d:d.products.pop(102)
            self.assert_no_write_http(lambda:self.run_undo(route),409)
    def test_undo_merge_qty_zero_still_both_locks_before_PSP_and_status(self):
        out=self.run_undo('undo_merge',{'dup':102,'into':101,'moved_stock':0,'moved_suppliers':[11]})
        self.assertEqual(self.guards()[0][1],[101,102]);self.assertEqual(out,{'ok':True,'restored':102})
        self.assertFalse(any('stock_movements' in q for q,p in self.db.calls))
        self.assertTrue(any(q.startswith('UPDATE product_supplier_prices') for q,p in self.db.calls))
    def test_undo_merge_current_stock_insufficient409_before_write(self):
        self.db.after_product_lock=lambda d:d.products[101].update(stock_qty=2)
        self.assert_no_write_http(lambda:self.run_undo('undo_merge'),409,
            '원본 재고가 편입분보다 적습니다 — 이후 판매·조정이 있었습니다')
    def test_undo_merge_reverse_stock_and_supplier_order_unchanged_no_late_lock(self):
        self.run_undo('undo_merge');self.assertEqual(sum('FOR UPDATE' in q for q,p in self.db.calls),2)
        stocks=[p for q,p in self.db.writes if q.startswith('INSERT INTO stock_movements')]
        self.assertEqual([(p['pc'],p['q'],p['ri']) for p in stocks],[(101,-3,102),(102,3,101)])
        psp=[p for q,p in self.db.writes if q.startswith('UPDATE product_supplier_prices')]
        self.assertEqual(psp,[{'p':102,'k':101,'s':11}]);self.assertEqual(self.db.logs[0][0],'product_merge_undo')
    def test_spec_product_guard_before_spec_write_and_gate_restoration(self):
        out=self.run_undo('undo_spec_edit');self.assertEqual(out,{'ok':True,'restored':1})
        self.assertTrue(self.db.writes[0][0].startswith('UPDATE product_specs'))
        self.assertEqual(self.db.writes[0][1],{'pc':102,'length_mm':240})
        self.assertEqual(self.db.writes[1][1],{'lf':'[]','rr':True,'ac':False,'pc':102})
    def test_part_type_restore_product_spec_review_payload_unchanged(self):
        out=self.run_undo('undo_part_type');self.assertEqual(out,{'ok':True,'restored':'GPU'})
        self.assertEqual([q.split()[1] for q,p in self.db.writes],['products','product_specs','FROM'])
        self.assertEqual(self.db.writes[-1][1],{'pc':102,'wait':'대기','pat':'분류 변경(%'})
    def test_product_restore_null_price_and_stock_ledger_keep_original_log_to_price(self):
        out=self.run_undo('undo_product_edit');self.assertEqual(out,{'ok':True,'restored':2})
        history=[p for q,p in self.db.writes if q.startswith('INSERT INTO product_price_history')]
        self.assertEqual(history,[{'pc':102,'f':'sale','old':13000,'new':None,'ref':70,'op':21}])
        stocks=[p for q,p in self.db.writes if q.startswith('INSERT INTO stock_movements')]
        self.assertEqual(stocks,[{'pc':102,'q':-4,'ref':70}])
    def test_product_no_editable_changes400_no_product_lock(self):
        self.assert_no_write_http(lambda:self.run_undo('undo_product_edit',{'product_code':102,'changes':{'bad':{'from':1}}}),400)
        self.assertEqual(self.guards(),[])
    def product_edit_detail(self, locked=False):
        return {'product_code':102, 'sku':'102', 'changes':{
            'stock_qty':{'from':7,'to':10}, 'sale_price':{'from':None,'to':13000}},
            'before':{'locked_fields':['maker']}, 'locked':locked}
    def product_edit_current(self, locked=False):
        self.db.products[102].update(stock_qty=10,sale_price=13000,
            locked_fields=['maker','stock_qty','sale_price'] if locked else ['maker'])
    def test_product_edit_post_lock_stock_price_or_other_lock_drift409_no_writes(self):
        for change in ({'stock_qty':15},{'sale_price':17000},
                       {'locked_fields':['maker','status']}):
            self.setUp();self.product_edit_current()
            self.db.after_product_lock=lambda d,c=change:d.products[102].update(c)
            self.assert_no_write_http(lambda:self.run_undo('undo_product_edit',self.product_edit_detail()),409)
            self.assertEqual((self.db.commits,self.db.rollbacks),(0,1))
            reads=[i for i,(q,p) in enumerate(self.db.calls) if q.startswith('SELECT stock_qty, sale_price, locked_fields')]
            self.assertEqual(len(reads),1);self.assertLess(self.guards()[0][0],reads[0])
    def test_product_edit_all_fields_preflight_last_field_drift_no_partial_restore(self):
        self.product_edit_current();self.db.products[102]['sale_price']=17000
        self.assert_no_write_http(lambda:self.run_undo('undo_product_edit',self.product_edit_detail()),409)
        self.assertEqual(self.db.products[102]['stock_qty'],10)
    def test_product_edit_valid_false_true_locks_null_restore_actor_history_and_delta(self):
        for locked in (False,True):
            self.setUp();self.product_edit_current(locked)
            result=self.run_undo('undo_product_edit',self.product_edit_detail(locked))
            self.assertEqual(result,{'ok':True,'restored':2})
            update=next(p for q,p in self.db.writes if q.startswith('UPDATE products'))
            self.assertEqual(update['stock_qty'],7);self.assertIsNone(update['sale_price'])
            self.assertEqual(update['lf'],'["maker"]')
            stock=[p for q,p in self.db.writes if q.startswith('INSERT INTO stock_movements')]
            self.assertEqual(stock,[{'pc':102,'q':-3,'ref':70}])
            history=[p for q,p in self.db.writes if q.startswith('INSERT INTO product_price_history')]
            self.assertEqual(history,[{'pc':102,'f':'sale','old':13000,'new':None,'ref':70,'op':21}])
            self.assertEqual((self.db.commits,self.db.rollbacks),(1,0))
    def test_product_edit_null_to_is_present_valid_evidence(self):
        self.product_edit_current();self.db.products[102]['sale_price']=None
        detail=self.product_edit_detail();detail['changes']['sale_price']={'from':13000,'to':None}
        self.run_undo('undo_product_edit',detail)
        history=next(p for q,p in self.db.writes if q.startswith('INSERT INTO product_price_history'))
        self.assertIsNone(history['old']);self.assertEqual(history['new'],13000)
    def test_product_edit_missing_or_malformed_evidence409_not_inferred(self):
        for mutation in ('to','from','locked','locked_type','before','before_locks',
                         'locks_type','lock_item','change_type','changes_type','price_bool','price_text','unknown'):
            self.setUp();self.product_edit_current();d=self.product_edit_detail()
            if mutation in ('to','from'):d['changes']['sale_price'].pop(mutation)
            elif mutation=='locked':d.pop('locked')
            elif mutation=='locked_type':d['locked']=0
            elif mutation=='before':d.pop('before')
            elif mutation=='before_locks':d['before'].pop('locked_fields')
            elif mutation=='locks_type':d['before']['locked_fields']=None
            elif mutation=='lock_item':d['before']['locked_fields']=[True]
            elif mutation=='change_type':d['changes']['sale_price']=[]
            elif mutation=='changes_type':d['changes']=[]
            elif mutation=='price_bool':d['changes']['sale_price']['from']=True
            elif mutation=='price_text':d['changes']['sale_price']['from']='13000'
            elif mutation=='unknown':d['changes']['unknown']={'from':1,'to':2}
            self.assert_no_write_http(lambda:self.run_undo('undo_product_edit',d),409)
    def test_product_edit_lock_order_is_preserved_and_reordered_current_refused(self):
        self.product_edit_current(True);self.db.products[102]['locked_fields']=['sale_price','maker','stock_qty']
        self.assert_no_write_http(lambda:self.run_undo('undo_product_edit',self.product_edit_detail(True)),409)
    def test_product_edit_alias_column_and_existing_lock_not_appended_twice(self):
        self.db.products[102].update(product_name='new',locked_fields=['status','product_name'])
        d={'product_code':102,'changes':{'name':{'from':'old','to':'new'}},
           'before':{'locked_fields':['status','product_name']},'locked':True}
        self.run_undo('undo_product_edit',d)
        read=next(q for q,p in self.db.calls if q.startswith('SELECT product_name, locked_fields'))
        self.assertNotIn('SELECT name,',read)
        update=next(p for q,p in self.db.writes if q.startswith('UPDATE products'))
        self.assertEqual(update['name'],'old');self.assertEqual(update['lf'],'["status", "product_name"]')
    def test_bulk_dedup_missing_skip_and_current_locked_status(self):
        def changed(d):d.products[102].update(locked_fields=['status']);d.products[101].update(status='단종')
        self.db.after_product_lock=changed;out=self.bulk((102,101,999,102))
        self.assertEqual((out['changed'],out['locked'],out['missing'],out['dropped']),(1,1,1,0))
        self.assertEqual(self.guards()[0][1],[101,102]);self.assertEqual(self.db.logs[0][2]['before'],[{'pc':101,'st':'단종'}])
        self.assertIn('없는 상품 1건',out['verdict']);self.assertEqual(self.db.authorizations,1)
    def test_bulk_cap_after_dedup_and_missing_skip_policy(self):
        self.env['MAX_BULK']=2;out=self.bulk((102,999,102,101))
        self.assertEqual((out['changed'],out['missing'],out['dropped']),(1,1,1));self.assertEqual(self.guards()[0][1],[102])
        self.assertEqual(self.db.logs[0][2]['before'],[{'pc':102,'st':'판매중'}])
    def test_bulk_wait_disappearance_or_new_requested_product409_no_write(self):
        for callback in (lambda d:d.products.pop(102),lambda d:d.products.update({999:dict(d.products[101],product_code=999)})):
            self.setUp();self.db.after_product_lock=callback;self.assert_no_write_http(lambda:self.bulk((102,101,999)),409)
    def test_bulk_current_values_no_targets400_no_pool_or_write(self):
        self.db.after_product_lock=lambda d:[r.update(status='품절') for r in d.products.values()]
        self.assert_no_write_http(self.bulk,400);self.assertFalse(any('v_recommendation_candidates' in q for q,p in self.db.calls))
    def test_bulk_invalid_status_empty_and_initial_all_missing_policy(self):
        for fn,status in ((lambda:self.bulk(status='bad'),400),(lambda:self.bulk(()),400),(lambda:self.bulk((999,)),404)):
            self.setUp();self.assert_no_write_http(fn,status);self.assertEqual(self.guards(),[])
    def test_bulk_undo_full_asc_locks_preserves_original_before_order_and_return(self):
        out=self.run_undo('bulk_status_undo');self.assertEqual(self.guards()[0][1],[101,102])
        self.assertEqual([p['pc'] for q,p in self.db.writes],[102,101]);self.assertEqual(out['restored'],2)
        self.assertEqual(self.db.authorizations,1)
    def test_guard_SQL_failure_propagates_identical_exception_without_retry_write(self):
        for route in (*ROUTES,):
            self.setUp();err=RuntimeError('mock guard failure');self.db.error=err
            with self.assertRaises(RuntimeError) as caught:
                if route=='merge_product':self.merge()
                elif route=='bulk_status':self.bulk()
                else:self.run_undo(route)
            self.assertIs(caught.exception,err);self.assertEqual(len(self.guards()),1)
            self.assertEqual(self.db.writes,[]);self.assertEqual(self.db.logs,[])
            self.assertEqual((self.db.commits,self.db.rollbacks),(0,1))
    def test_log_failure_caller_rollback_keeps_original_payload_and_propagates(self):
        for route in ROUTES:
            self.setUp()
            if route == 'undo_product_edit':self.db.products[102].update(sale_price=13000, stock_qty=7)
            before=deepcopy(self.db.products);err=RuntimeError('mock log failure');self.db.log_error=err
            with self.assertRaises(RuntimeError) as caught:
                if route=='merge_product':self.merge()
                elif route=='bulk_status':self.bulk()
                else:self.run_undo(route)
            self.assertIs(caught.exception,err);self.assertEqual(self.db.products,before)
            self.assertEqual(self.db.writes,[]);self.assertEqual(self.db.logs,[])
            self.assertEqual((self.db.commits,self.db.rollbacks),(0,1))
    def test_invalid_log_product_scope409_and_empty_bulkundo400_without_write(self):
        for pc in (None, True, -1, '102'):
            self.setUp();self.assert_no_write_http(lambda:self.run_undo('undo_part_type',
                {'product_code':pc,'before':{},'from':'GPU'}),409)
        self.setUp();self.assert_no_write_http(lambda:self.run_undo('bulk_status_undo',{'before':[]}),400)
        self.assertEqual(self.guards(),[])
    def test_selected_AST_never_imports_operational_db_main_or_admin_orders(self):
        import sys
        self.assertFalse(any(name in sys.modules for name in ('api.db','api.main','api.admin_orders')))
        for route in ROUTES:
            self.setUp()
            if route=='merge_product':self.merge()
            elif route=='bulk_status':self.bulk()
            else:self.run_undo(route)
        self.assertFalse(any(name in sys.modules for name in ('api.db','api.main','api.admin_orders')))
    def test_wrong_original_action_allundo404_without_guard_write(self):
        for route in ('undo_product_edit','undo_spec_edit','undo_part_type','undo_merge','bulk_status_undo'):
            self.setUp();self.db.after_log_lock=lambda d:d.source_log.update(action='other')
            self.assert_no_write_http(lambda:self.run_undo(route),404);self.assertEqual(self.guards(),[])


if __name__=='__main__': unittest.main()
