"""Actual review writers/undo with SQL-shaped mocks; no live PG verification."""
import ast
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from fastapi import HTTPException
from tests.test_review_write_lock_order import Database, routes, review, _LOCK_PRODUCTS_SQL


def freshness_baseline(tree):
    """Remove only approved capture metadata, preflight and reverse iteration."""
    tree=deepcopy(tree)
    helpers={'_review_undo_entries','_review_undo_entry_ids','_review_undo_product_fields',
             '_capture_review_undo_after','_validate_review_undo_after'}
    overlay=[]
    for node in tree.body:
        if isinstance(node,ast.FunctionDef) and node.name in helpers:overlay.append(deepcopy(node))
    tree.body=[n for n in tree.body if not (isinstance(n,ast.FunctionDef) and n.name in helpers)
               and not (isinstance(n,ast.Import) and [a.name for a in n.names]==['json'])]
    class Metadata(ast.NodeTransformer):
        def visit_Assign(self,node):
            if (any(isinstance(t,ast.Name) and t.id=='undo_after' or
                    isinstance(t,ast.Subscript) and isinstance(t.value,ast.Name) and t.value.id=='detail'
                    and isinstance(t.slice,ast.Constant) and t.slice.value=='undo_after' for t in node.targets)):
                overlay.append(deepcopy(node));return None
            return self.generic_visit(node)
        def visit_Dict(self,node):
            keep=[]
            for i,key in enumerate(node.keys):
                if isinstance(key,ast.Constant) and key.value=='undo_after':
                    overlay.append(ast.Expr(value=deepcopy(node.values[i])))
                else:keep.append(i)
            node.keys=[node.keys[i] for i in keep];node.values=[node.values[i] for i in keep]
            return self.generic_visit(node)
    for n in tree.body:
        if isinstance(n,ast.FunctionDef) and n.name in (
                'auto_approve_market_price','process_review','bulk_confirm','bulk_reject_zero_price'):
            Metadata().visit(n)
    undo=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='undo')
    body=next(n for n in undo.body if isinstance(n,ast.With)).body
    def assigns(n,name):return isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in n.targets)
    index=next(i for i,n in enumerate(body) if assigns(n,'entries'))
    overlay.append(deepcopy(body[index]))
    body[index:index+1]=ast.parse('''if log["action"] in ("review_bulk_confirm", "review_bulk_reject"):
    entries = detail["items"]
else:
    entries = [detail] + [
        {"mode": detail.get("mode"), "field": detail.get("field"),
         "review_id": a["review_id"], "before": a["before"]}
        for a in (detail.get("also") or [])]''').body
    start=next(i for i,n in enumerate(body) if assigns(n,'ids'))
    end=next(i for i,n in enumerate(body) if assigns(n,'locked'))
    overlay.extend(deepcopy(body[start:end]))
    body[start:end]=ast.parse('candidates = _review_candidates(conn, [e["review_id"] for e in entries], undo=True)').body
    index=next(i for i,n in enumerate(body) if isinstance(n,ast.For) and isinstance(n.iter,ast.Call)
               and isinstance(n.iter.func,ast.Name) and n.iter.func.id=='reversed')
    overlay.append(deepcopy(body[index-1]));overlay.append(ast.Expr(value=deepcopy(body[index].iter)))
    del body[index-1]
    loop=body[index-1]
    if ast.dump(loop.iter)!=ast.dump(ast.parse('reversed(entries)',mode='eval').body):
        raise AssertionError('only reverse entry iteration may change')
    loop.iter=ast.Name(id='entries',ctx=ast.Load())
    return tree,ast.Module(body=overlay,type_ignores=[])


class ReviewUndoFreshnessTests(unittest.TestCase):
    def test_only_authorized_overlay_changes_accepted_business_ast(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'api/admin_reviews.py').read_text(encoding='utf-8'))
        baseline,overlay=freshness_baseline(tree)
        # Accepted B source + immutable C diff reconstructs SHA 1e6bb835...;
        # adding the accepted permanent duplicate guard yields this full AST.
        self.assertEqual(hashlib.sha256(ast.dump(baseline).encode()).hexdigest(),
                         'ece04e41a2a46cc17c6763fc268c37b9f62a1560a9bbc5aa89b3afc58a9723da')
        self.assertEqual(hashlib.sha256(ast.dump(overlay).encode()).hexdigest(),
                         'e5294b9d825ad158bbf577b9ba338bec52b1ca3e2a51ed8ec9e1cf18e9692b30')

    def setUp(self):
        self.db=Database();self.env=routes();self.env.update(engine=self.db,_log=self.db.log)

    def process(self,rid=9,value='11000',also=(),action='manual',reason=None):
        return self.env['process_review'](rid,SimpleNamespace(action=action,value=value,also=list(also),reason=reason))

    def original(self,index=-1):
        action,target,detail,kwargs=self.db.logs[index]
        return {'action':action,'detail':deepcopy(detail)}

    def undo(self,original=None,log_id=70):
        self.db.source_log=deepcopy(original if original is not None else self.original())
        return self.env['undo'](log_id)

    def reject_no_new_writes(self,original,log_id=70,status=409):
        before=deepcopy((self.db.products,self.db.reviews,self.db.specs,self.db.writes,self.db.logs))
        start=len(self.db.calls)
        with self.assertRaises(HTTPException) as caught:self.undo(original,log_id)
        self.assertEqual(caught.exception.status_code,status)
        self.assertEqual((self.db.products,self.db.reviews,self.db.specs,self.db.writes,self.db.logs),before)
        calls=self.db.calls[start:]
        self.assertFalse(any(q.lstrip().startswith(('UPDATE ','INSERT ','DELETE ')) for q,p in calls))
        return caught.exception,calls

    def test_first_old_market_undo_rejects_different_review_later_approval(self):
        self.db.reviews[3]['product_code']=102
        self.process();old=self.original();self.process(3,'12000')
        error,calls=self.reject_no_new_writes(old)
        self.assertIn('다른 변경',error.detail);self.assertEqual(self.db.products[102]['market_price'],12000)
        self.assertFalse(any(a=='review_undo' for a,t,d,k in self.db.logs))

    def test_first_old_spec_undo_rejects_later_same_field_approval(self):
        for rid in (3,9):self.db.reviews[rid].update(product_code=102,field_name='length_mm')
        self.process(value='300');old=self.original();self.process(3,'350')
        self.reject_no_new_writes(old);self.assertEqual(self.db.specs[102]['length_mm'],350)

    def test_prices_specs_flags_and_other_locks_all_restore_regions_are_preflighted(self):
        for target,change in (
                ('product',{'locked_fields':['market_price','maker']}),
                ('product',{'review_required_yn':True}),('product',{'ai_candidate_yn':False}),
                ('spec',{'length_mm':350}),('spec',{'verified_yn':False})):
            self.setUp();self.db.reviews[9]['field_name']='length_mm';self.process(value='300');old=self.original()
            if target=='product':
                if 'locked_fields' in change:change={'locked_fields':['specs.length_mm','maker']}
                self.db.products[102].update(change)
            else:self.db.specs[102].update(change)
            self.reject_no_new_writes(old)

    def test_review_generation_detail_status_and_original_binding_drift_reject(self):
        for change in ({'reviewed_at':datetime(2026,10,4)+timedelta(seconds=1)},
                       {'reviewed_by':22},{'detail':'later detail'}, {'review_status':'수정'},
                       {'product_code':101},{'field_name':'length_mm'}):
            self.setUp();self.process(action='origin');old=self.original();self.db.reviews[9].update(change)
            self.reject_no_new_writes(old)

    def test_last_review_drift_rejects_before_any_partial_restore(self):
        self.process(also=(3,));old=self.original();self.db.reviews[9]['detail']='later'
        error,calls=self.reject_no_new_writes(old)
        self.assertEqual(self.db.products[101]['market_price'],11000)
        self.assertEqual(self.db.products[102]['market_price'],11000)
        self.assertTrue(any(q.startswith('SELECT review_id, product_code, field_name,') for q,p in calls))

    def test_same_product_bulk_different_values_reverse_stack_restores_original_and_history(self):
        self.db.reviews[3].update(product_code=102,origin_value='11000')
        self.db.reviews[9]['origin_value']='12000'
        before=deepcopy(self.db.products);self.env['bulk_confirm']();old=self.original()
        after=old['detail']['undo_after']
        self.assertEqual(len(after['products']),1)
        self.assertEqual(json.loads(after['products'][0]['state'])['market_price'],12000)
        hstart=len(self.db.writes);result=self.undo(old)
        self.assertEqual(result,{'ok':True,'restored':2});self.assertEqual(self.db.products,before)
        history=[p for q,p in self.db.writes[hstart:] if q.startswith('INSERT INTO product_price_history')]
        self.assertEqual([(p['o'],p['n'],p['ref'],p['op']) for p in history],[(12000,11000,9,21),(11000,10000,3,21)])

    def test_same_product_also_same_value_final_snapshot_not_intermediate_and_original_locks_restore(self):
        self.db.reviews[3]['product_code']=102;before=deepcopy(self.db.products)
        self.process(also=(3,));old=self.original()
        self.assertEqual(len(old['detail']['undo_after']['products']),1)
        start=len(self.db.calls);self.undo(old)
        self.assertEqual(self.db.products,before)
        restored=[p['rid'] for q,p in self.db.calls[start:] if "review_status='대기'" in q]
        self.assertEqual(restored,[3,9])

    def test_same_product_different_spec_fields_reverse_shared_gate_and_lock_chain(self):
        self.db.reviews[3].update(product_code=102,field_name='socket',origin_value='AM5')
        self.db.reviews[9].update(field_name='length_mm',origin_value='300')
        self.db.specs[102]['socket']='AM4'
        before=deepcopy((self.db.products,self.db.specs));self.env['bulk_confirm']();old=self.original()
        self.assertEqual(len(old['detail']['undo_after']['products']),1)
        self.undo(old);self.assertEqual((self.db.products,self.db.specs),before)

    def test_all_five_actual_writer_paths_first_undo_original_response_and_second_duplicate(self):
        for kind,count in (('primary',1),('also',2),('bulk',2),('auto',1),('reject',1),('reject_bulk',2)):
            self.setUp();products=deepcopy(self.db.products)
            if kind=='primary':self.process()
            elif kind=='also':self.process(also=(3,))
            elif kind=='bulk':self.env['bulk_confirm']()
            elif kind=='auto':self.env['auto_approve_market_price'](9)
            elif kind=='reject':self.process(action='reject',reason='hold')
            else:
                for r in self.db.reviews.values():r['suggested_value']='0'
                self.env['bulk_reject_zero_price']()
            old=self.original();self.assertEqual(old['detail']['undo_after']['version'],'review_undo_after_v1')
            self.assertEqual(self.undo(old),{'ok':True,'restored':count})
            self.assertEqual(self.db.products,products)
            self.assertEqual(self.db.logs[-1],('review_undo','70',{'ref_log_id':70,'count':count},{}))
            error,calls=self.reject_no_new_writes(old)
            self.assertEqual(error.detail,'이미 대기 상태입니다');self.assertEqual(len(calls),2)

    def test_native_json_text_preserves_numeric_scale_json_arrays_and_timestamps(self):
        for field,value,before in (('size_inch','27.04',Decimal('24.0')),
                                   ('socket_list','["AM4", "AM5"]',['AM4'])):
            self.setUp();self.db.reviews[9]['field_name']=field;self.db.specs[102][field]=before
            self.process(value=value);old=self.original();state=old['detail']['undo_after']['products'][0]['state']
            if field=='size_inch':
                self.assertIn('27.0',state);self.assertNotIn('"27.0"',state)
            else:self.assertEqual(json.loads(state)['specs.socket_list'],['AM4','AM5'])
            review_state=old['detail']['undo_after']['reviews'][0]['state']
            self.assertIn('2026-10-04T00:00:00.000001',review_state)
            self.undo(old);self.assertEqual(self.db.specs[102][field],before)

    def test_null_product_value_and_null_vs_empty_full_locks_are_not_conflated(self):
        for locks in (None,[]):
            self.setUp();self.db.products[102].update(market_price=None,locked_fields=deepcopy(locks))
            self.process();old=self.original();self.undo(old)
            self.assertIsNone(self.db.products[102]['market_price']);self.assertEqual(self.db.products[102]['locked_fields'],locks)
        self.setUp();self.db.products[102]['locked_fields']=None;self.process();old=self.original()
        self.db.products[102]['locked_fields']=[];self.reject_no_new_writes(old)

    def test_missing_after_legacy_and_malformed_snapshot_or_entries_fail_closed(self):
        self.process();valid=self.original()
        for mutation in ('missing','version','reviews','products','state','review_id','product_code','fields','before','items'):
            old=deepcopy(valid);after=old['detail']['undo_after']
            if mutation=='missing':old['detail'].pop('undo_after')
            elif mutation=='version':after['version']='old'
            elif mutation in ('reviews','products'):after[mutation]=[]
            elif mutation=='state':after['products'][0]['state']='not json'
            elif mutation=='review_id':after['reviews'][0]['review_id']=True
            elif mutation=='product_code':after['reviews'][0]['product_code']=True
            elif mutation=='fields':after['products'][0]['fields']=['unsafe_column']
            elif mutation=='before':old['detail']['before'].pop('product_value')
            elif mutation=='items':old={'action':'review_bulk_confirm','detail':{}}
            self.reject_no_new_writes(old)

    def test_original_waiting_error_wins_even_legacy_after_missing(self):
        self.process();old=self.original();old['detail'].pop('undo_after');self.db.reviews[9]['review_status']='대기'
        error,calls=self.reject_no_new_writes(old)
        self.assertEqual(error.detail,'이미 대기 상태입니다')

    def test_spec_row_absent_before_is_not_claimed_to_be_deleted_by_legacy_business_restore(self):
        self.db.reviews[9]['field_name']='length_mm';self.db.specs.pop(102)
        self.process(value='300');old=self.original()
        self.assertTrue(json.loads(old['detail']['undo_after']['products'][0]['state'])['specs_exists'])
        self.undo(old);self.assertIn(102,self.db.specs)
        self.assertIsNone(self.db.specs[102]['length_mm']);self.assertFalse(self.db.specs[102]['verified_yn'])

    def test_capture_or_preflight_failure_and_restore_log_failure_propagate_with_caller_rollback(self):
        self.db.snapshot_error=RuntimeError('capture failed');before=deepcopy((self.db.products,self.db.reviews,self.db.specs))
        with self.assertRaises(RuntimeError) as caught:self.process()
        self.assertIs(caught.exception,self.db.snapshot_error)
        self.assertEqual((self.db.products,self.db.reviews,self.db.specs),before);self.assertEqual(self.db.writes,[])
        for stage in ('preflight','log'):
            self.setUp();self.process();old=self.original();before=deepcopy((self.db.products,self.db.reviews,self.db.specs,self.db.writes,self.db.logs))
            error=RuntimeError(stage)
            if stage=='preflight':self.db.snapshot_error=error
            else:self.db.log_error=error
            with self.assertRaises(RuntimeError) as caught:self.undo(old)
            self.assertIs(caught.exception,error);self.assertEqual((self.db.products,self.db.reviews,self.db.specs,self.db.writes,self.db.logs),before)
            self.assertEqual(self.db.rollbacks,1)


if __name__ == '__main__':unittest.main()
