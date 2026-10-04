"""Selected real review routes and business helpers; mocks are not PG evidence."""
import ast
import json
import re
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from api.pricing_write_guard_core import lock_products, ProductScopeChanged, _LOCK_PRODUCTS_SQL


def routes():
    path=Path(__file__).resolve().parents[1]/'api/admin_reviews.py'
    functions={'_review_candidates','_lock_review_scope','_lock_waiting_review','process_review',
        'bulk_confirm','bulk_reject_zero_price','auto_approve_market_price','undo',
        '_approve','_approve_product_field','_revert_one','_parse_price','_default_reject_reason',
        'product_price_max','market_auto_approve_decision'}
    constants={'FIELD_CAST','PRODUCT_FIELD_CAST','PRODUCT_PRICE_MIN','PRODUCT_PRICE_MAX_SYSTEM',
        'PRODUCT_PRICE_MAX_HIGH','PRODUCT_PRICE_MAX_STANDARD','_PRICE_TIER_BY_PART_TYPE',
        'MARKET_AUTO_APPROVE_PCT','ZERO_PRICE_REASON'}
    nodes=[]
    for node in ast.parse(path.read_text(encoding='utf-8')).body:
        if isinstance(node,ast.FunctionDef) and (node.name in functions or node.name.startswith('_review_undo_')
                or node.name in ('_capture_review_undo_after','_validate_review_undo_after')):
            node.decorator_list=[];nodes.append(node)
        elif isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in constants for t in node.targets):nodes.append(node)
    env=dict(json=json,text=text,HTTPException=HTTPException,DBAPIError=DBAPIError,lock_products=lock_products,
        ProductScopeChanged=ProductScopeChanged,ProcessBody=object,current_operator_id=lambda:21,
        required_fields=lambda pt:['length_mm'])
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),env)
    return env


class Result:
    def __init__(self,rows=()):self.rows=deepcopy(list(rows))
    def mappings(self):return self
    def scalars(self):return self
    def all(self):return deepcopy(self.rows)
    def first(self):return deepcopy(self.rows[0]) if self.rows else None
    def one(self):
        if len(self.rows)!=1:raise AssertionError('one row expected')
        return self.first()
    def scalar(self):return self.first()


def review(rid,pc,field='market_price',status='대기',origin='10000',suggested='10200'):
    return {'review_id':rid,'product_code':pc,'field_name':field,'review_status':status,
        'origin_value':origin,'suggested_value':suggested,'review_type':'low_confidence','detail':'original'}


def native_json(value):
    """Mock JSONB text, preserving numeric scale and timestamp text without coercion."""
    if isinstance(value,Decimal):return str(value)
    if isinstance(value,datetime):return json.dumps(value.isoformat())
    if type(value) is dict:
        return '{'+', '.join(json.dumps(k)+': '+native_json(v) for k,v in sorted(value.items()))+'}'
    if type(value) is list:return '['+', '.join(native_json(v) for v in value)+']'
    return json.dumps(value,ensure_ascii=False)


def append_lock(product,field):
    locks=product['locked_fields']
    if locks is not None and field not in locks:locks.append(field)


def cast_spec(field,value):
    if value is None:return None
    if field=='size_inch':return Decimal(str(value)).quantize(Decimal('.1'),rounding=ROUND_HALF_UP)
    if field in ('socket_list','form_factor_list'):return json.loads(value) if type(value) is str else deepcopy(value)
    if field in ('length_mm','rated_watt','capacity_gb','tdp_watt'):return int(value)
    return str(value)


class Database:
    def __init__(self):
        self.reviews={9:review(9,102),3:review(3,101)}
        self.products={pc:{'market_price':10000,'part_type':'GPU','locked_fields':[],
            'review_required_yn':True,'ai_candidate_yn':False} for pc in (101,102)}
        self.specs={pc:{'length_mm':240,'verified_yn':False} for pc in (101,102)}
        self.source_log=None;self.logs=[];self.writes=[];self.calls=[]
        self.product_locks=set();self.review_locks=set()
        self.after_product_lock=None;self.after_review_lock=None;self.after_log_lock=None
        self.guard_error=None;self.log_error=None;self.undo_query_error=None;self.snapshot_error=None;self.commits=self.rollbacks=0
        self.tx_serial=0
    def begin(self):return Transaction(self)
    def log(self,conn,action,target,detail,**kw):
        self.logs.append((action,target,deepcopy(detail),kw))
        if self.log_error:raise self.log_error
        return 91


class Transaction:
    def __init__(self,d):self.d=d
    def __enter__(self):
        self.d.tx_serial+=1
        self.c=Connection(self.d);return self.c
    def __exit__(self,typ,value,trace):
        if typ:
            self.d.rollbacks+=1
            self.d.products,self.d.reviews,self.d.specs,self.d.writes,self.d.logs=deepcopy(self.c.snapshot)
        else:self.d.commits+=1
        return False


class Connection:
    def __init__(self,d):self.d=d;self.refresh()
    def refresh(self):self.snapshot=deepcopy((self.d.products,self.d.reviews,self.d.specs,self.d.writes,self.d.logs))
    def execute(self,statement,params=None):
        q=str(statement);p=params or {};d=self.d;d.calls.append((q,deepcopy(p)))
        if q=='SELECT mock_new_review':return Result([9])
        if q==_LOCK_PRODUCTS_SQL:
            if d.guard_error:raise d.guard_error
            if d.after_product_lock:
                fn=d.after_product_lock;d.after_product_lock=None;fn(d)
            self.refresh();codes=[pc for pc in p['codes'] if pc in d.products];d.product_locks.update(codes);return Result(codes)
        if q.startswith('SELECT action, detail FROM admin_operator_activity_logs'):
            if d.after_log_lock:
                fn=d.after_log_lock;d.after_log_lock=None;fn(d)
            self.refresh();return Result([d.source_log] if d.source_log else [])
        if q.startswith('SELECT 1 FROM admin_operator_activity_logs'):
            if d.undo_query_error:raise d.undo_query_error
            if "action='review_undo'" not in q or "detail->>'ref_log_id'=:id" not in q:
                raise AssertionError('undo must match action and exact original log ID')
            return Result([(1,)] if any(action=='review_undo' and str(detail.get('ref_log_id'))==p['id']
                for action,target,detail,kw in d.logs) else [])
        if q.startswith('SELECT review_id, product_code, field_name,'):
            if d.snapshot_error:raise d.snapshot_error
            return Result([{'review_id':rid,'product_code':d.reviews[rid]['product_code'],
                'field_name':d.reviews[rid]['field_name'],'state':native_json({k:d.reviews[rid].get(k)
                    for k in ('review_status','reviewed_by','reviewed_at','detail')})}
                for rid in sorted(p['ids']) if rid in d.reviews])
        if q.startswith('SELECT jsonb_build_object('):
            if d.snapshot_error:raise d.snapshot_error
            if p['pc'] not in d.products:return Result([])
            fields=re.findall(r"'([^']+)'",q);state={};spec=d.specs.get(p['pc'])
            for field in fields:
                state[field]=(spec is not None if field=='specs_exists' else
                    (spec or {}).get(field[6:]) if field.startswith('specs.') else d.products[p['pc']].get(field))
            return Result([{'state':native_json(state)}])
        if q.startswith('SELECT * FROM product_reviews WHERE review_id='):
            if 'FOR UPDATE' in q:
                if d.after_review_lock:
                    fn=d.after_review_lock;d.after_review_lock=None;fn(d)
                self.refresh();d.review_locks.add(p['rid'])
            return Result([d.reviews[p['rid']]] if p['rid'] in d.reviews else [])
        if q.startswith('SELECT * FROM product_reviews WHERE '):
            rows=[r for rid,r in sorted(d.reviews.items()) if r['review_status']=='대기' and
                (r['review_type']=='low_confidence' if 'review_type=' in q else r['field_name']=='market_price')]
            return Result(rows)
        if q.startswith('SELECT market_price, part_type FROM products'):return Result([d.products[p['pc']]])
        if q.startswith('SELECT market_price AS v, locked_fields, part_type FROM products'):
            self.assert_product(p['pc']);row=d.products[p['pc']];return Result([dict(row,v=row['market_price'])])
        if q.startswith('SELECT market_price AS v FROM products'):
            self.assert_product(p['pc']);return Result([d.products[p['pc']]['market_price']])
        if q.startswith('SELECT part_type, review_required_yn'):
            self.assert_product(p['pc']);return Result([d.products[p['pc']]])
        if q.startswith('SELECT to_jsonb(ps) AS specs'):
            self.assert_product(p['pc']);return Result([{'specs':d.specs[p['pc']]}] if p['pc'] in d.specs else [])
        if q.startswith('SELECT to_jsonb(ps) AS s'):return Result([d.specs.get(p['pc'])])
        if q.startswith('SELECT COUNT(*) FROM product_reviews'):
            return Result([sum(r['product_code']==p['pc'] and r['review_status'] in ('대기','검수중') and r['review_id']!=p['rid'] for r in d.reviews.values())])
        if q.lstrip().startswith(('INSERT ','UPDATE ','DELETE ')):
            if 'pc' in p:self.assert_product(p['pc'])
            if 'rid' in p:
                if p['rid'] not in d.review_locks:raise AssertionError('review not already locked')
            d.writes.append((q,deepcopy(p)))
            if q.startswith('UPDATE products SET market_price'):
                d.products[p['pc']]['market_price']=int(p['v']) if p['v'] is not None else None
                if 'CASE WHEN' in q:append_lock(d.products[p['pc']],p['lf'])
                else:d.products[p['pc']]['locked_fields']=json.loads(p['lf'])
            if q.startswith('UPDATE products SET review_required_yn=false'):
                d.products[p['pc']].update(review_required_yn=False,ai_candidate_yn=True)
                append_lock(d.products[p['pc']],p['lf'])
            elif q.startswith('UPDATE products SET review_required_yn=:rr'):
                d.products[p['pc']].update(review_required_yn=p['rr'],ai_candidate_yn=p['ac'],locked_fields=json.loads(p['lf']))
            elif q.startswith('UPDATE products SET locked_fields = CASE'):
                append_lock(d.products[p['pc']],p['lf'])
            if q.startswith('UPDATE product_reviews SET review_status'):
                d.reviews[p['rid']]['review_status']=p.get('st','대기' if "review_status='대기'" in q else '보류')
                d.reviews[p['rid']]['reviewed_by']=p.get('op')
                d.reviews[p['rid']]['reviewed_at']=(None if "review_status='대기'" in q else
                    datetime(2026,10,4)+timedelta(microseconds=d.tx_serial))
                if 'rs' in p and (p['rs'] is not None):
                    d.reviews[p['rid']]['detail']=(d.reviews[p['rid']]['detail'] or '')+' [반려 사유: '+p['rs']+']'
            if q.startswith('UPDATE product_reviews SET detail='):d.reviews[p['rid']]['detail']=p['d']
            if q.lstrip().startswith('INSERT INTO product_specs'):
                field=re.search(r'product_code, part_type, (\w+)\)',q).group(1)
                d.specs.setdefault(p['pc'],{'verified_yn':False})[field]=cast_spec(field,p['v'])
            if q.lstrip().startswith('UPDATE product_specs SET verified_yn=true'):
                d.specs[p['pc']]['verified_yn']=True
            elif q.lstrip().startswith('UPDATE product_specs SET'):
                field=re.search(r'UPDATE product_specs SET (\w+)',q).group(1)
                d.specs[p['pc']][field]=cast_spec(field,p['v']);d.specs[p['pc']]['verified_yn']=p['vy']
            return Result()
        raise AssertionError('unexpected SQL '+q)
    def assert_product(self,pc):
        if pc not in self.d.product_locks:raise AssertionError('late product lock/write without full guard')


class ReviewTests(unittest.TestCase):
    def setUp(self):self.d=Database();self.env=routes();self.env.update(engine=self.d,_log=self.d.log)
    def process(self,rid=9,action='suggested',also=(3,9,3),value='10300',reason=None):
        return self.env['process_review'](rid,SimpleNamespace(action=action,also=list(also),value=value,reason=reason))
    def auto(self):return self.env['auto_approve_market_price'](9)
    def bulk(self):return self.env['bulk_confirm']()
    def reject_bulk(self):return self.env['bulk_reject_zero_price']()
    def undo(self,entries=None):
        if entries is None:entries=[{'review_id':9,'mode':'reject','before':{'review_status':'대기','detail':'old9'}},
            {'review_id':3,'mode':'reject','before':{'review_status':'대기','detail':'old3'}}]
        # New-version synthetic fixture: capture reads are seed work, outside route call assertions.
        start=len(self.d.calls)
        unique=list({e['review_id']:e for e in entries}.values())
        after=(self.env['_capture_review_undo_after'](Connection(self.d),unique)
               if all(e['review_id'] in self.d.reviews for e in unique) else None)
        del self.d.calls[start:]
        self.d.source_log={'action':'review_bulk_reject','detail':{'items':entries,'undo_after':after}}
        return self.env['undo'](70)
    def processed(self):
        for r in self.d.reviews.values():r['review_status']='보류'
    def guards(self):return [(i,p['codes']) for i,(q,p) in enumerate(self.d.calls) if q==_LOCK_PRODUCTS_SQL]
    def reviewlocks(self):return [(i,p['rid']) for i,(q,p) in enumerate(self.d.calls) if q.startswith('SELECT * FROM product_reviews WHERE review_id=') and 'FOR UPDATE' in q]
    def no_write_http(self,fn,status,detail=None):
        with self.assertRaises(HTTPException) as caught:fn()
        self.assertEqual(caught.exception.status_code,status)
        if detail:self.assertEqual(caught.exception.detail,detail)
        self.assertEqual(self.d.writes,[]);self.assertEqual(self.d.logs,[])
        self.assertFalse(any(q.lstrip().startswith(('INSERT ','UPDATE ','DELETE ')) for q,p in self.d.calls))
    def test_primary_also_reverse_products_and_reviews_lock_asc_apply_original_order(self):
        out=self.process();self.assertEqual([p for i,p in self.guards()],[[101,102]])
        self.assertEqual([rid for i,rid in self.reviewlocks()],[3,9]);self.assertLess(self.guards()[0][0],self.reviewlocks()[0][0])
        self.assertEqual([p['rid'] for q,p in self.d.writes if q.startswith('UPDATE product_reviews SET review_status')],[9,3])
        self.assertEqual(out['applied'],2);self.assertEqual(out['pool_added'],0)
        self.assertEqual(self.d.logs[0][2]['also'][0]['review_id'],3)
    def test_reverse_request_direction_same_lock_sets(self):
        self.process(3,also=(9,));self.assertEqual([p for i,p in self.guards()],[[101,102]])
        self.assertEqual([rid for i,rid in self.reviewlocks()],[3,9])
        self.assertEqual([p['rid'] for q,p in self.d.writes if q.startswith('UPDATE product_reviews SET review_status')],[3,9])
    def test_reject_ignores_also_missing_and_reason_before_detail_preserved(self):
        out=self.process(action='reject',also=(999,),reason='customer reason')
        self.assertEqual([p for i,p in self.guards()],[[102]]);self.assertEqual([rid for i,rid in self.reviewlocks()],[9])
        self.assertEqual(out,{'ok':True,'undo_id':91,'pool_added':0});self.assertEqual(self.d.logs[0][2]['before']['detail'],'original')
        self.assertEqual(self.d.writes[0][1],{'op':21,'rid':9,'rs':'customer reason'})
    def test_primary_initial404_processed409_invalid_action400_and_no_value400(self):
        self.no_write_http(lambda:self.process(999),404)
        self.setUp();self.d.reviews[9]['review_status']='승인';self.no_write_http(lambda:self.process(also=(999,)),409,'이미 처리된 항목입니다')
        self.setUp();self.no_write_http(lambda:self.process(action='bad'),400);self.assertEqual(self.d.calls,[])
        self.setUp();self.d.reviews[9]['suggested_value']=None;self.no_write_http(lambda:self.process(also=(999,)),400,'확정할 값이 없습니다')
    def test_also_wrong_field_or_missing_fails_before_primary_write(self):
        self.d.reviews[3]['field_name']='length_mm';self.no_write_http(self.process,400)
        self.setUp();self.no_write_http(lambda:self.process(also=(999,)),404)
    def test_status_processed_while_product_waits_exact_handled409(self):
        self.d.after_product_lock=lambda d:d.reviews[3].update(review_status='승인')
        self.no_write_http(self.process,409,'이미 처리된 항목입니다')
    def test_rebinding_field_change_or_disappearance409_without_late_products_or_writes(self):
        for callback in (lambda d:d.reviews[3].update(product_code=999),lambda d:d.reviews[3].update(field_name='length_mm'),lambda d:d.reviews.pop(3)):
            self.setUp();self.d.after_product_lock=callback;self.no_write_http(self.process,409)
            self.assertEqual([p for i,p in self.guards()],[[101,102]])
    def test_missing_product_scope409_no_review_lock_write(self):
        self.d.after_product_lock=lambda d:d.products.pop(102);self.no_write_http(self.process,409);self.assertEqual(self.reviewlocks(),[])
    def test_bulk_ascending_review_order_skip_origin_none_and_actor_unchanged(self):
        self.d.reviews[9]['origin_value']=None;out=self.bulk()
        self.assertEqual((out['count'],out['skipped'],out['pool_added']),(1,1,0));self.assertEqual([rid for i,rid in self.reviewlocks()],[3,9])
        self.assertEqual([p for i,p in self.guards()],[[101,102]])
        self.assertEqual([p['op'] for q,p in self.d.writes if q.startswith('UPDATE product_reviews SET review_status')],[21])
    def test_bulk_new_candidate_removed_candidate_or_rebinding409_no_write(self):
        for fn in (lambda d:d.reviews.update({7:review(7,101)}),lambda d:d.reviews[3].update(review_status='승인'),lambda d:d.reviews[3].update(product_code=102)):
            self.setUp();self.d.after_product_lock=fn;self.no_write_http(self.bulk,409)
    def test_zero_bulk_skip_positive_bad_null_and_never_market_update(self):
        self.d.reviews={i:review(i,101,suggested=v) for i,v in enumerate(('0','-1','100','bad',None),1)}
        out=self.reject_bulk();self.assertEqual((out['count'],out['skipped']),(2,3))
        self.assertFalse(any('UPDATE products' in q for q,p in self.d.writes))
        self.assertEqual([p['rid'] for q,p in self.d.writes],[1,2]);self.assertTrue(all(p['op']==21 for q,p in self.d.writes))
        self.assertTrue(all(e['before']['detail']=='original' for e in self.d.logs[0][2]['items']))
    def test_zero_bulk_new_candidate_or_removed_scope409(self):
        for fn in (lambda d:d.reviews.update({7:review(7,101,suggested='0')}),lambda d:d.reviews[3].update(field_name='length_mm')):
            self.setUp();self.d.reviews[9]['suggested_value']='0';self.d.after_product_lock=fn;self.no_write_http(self.reject_bulk,409)
    def test_no_bulk_entries_original400(self):
        self.d.reviews={};self.no_write_http(self.bulk,400)
        self.setUp();self.no_write_http(self.reject_bulk,400)
    def test_auto_actual_decision_and_helper_system_null_actor_policy(self):
        out=self.auto();self.assertTrue(out['auto_approved']);self.assertFalse(out['left_to_human']);self.assertEqual(out['pct_change'],2.0)
        history=[p for q,p in self.d.writes if q.startswith('INSERT INTO product_price_history')]
        self.assertEqual(history,[{'pc':102,'o':10000,'n':10200,'ref':9,'op':None}])
        self.assertEqual(self.d.reviews[9]['reviewed_by'],None);self.assertEqual(self.d.logs[0][3],{'auto':True})
        self.assertEqual(self.d.logs[0][2]['threshold_pct'],5.0)
    def test_auto_processed_response_for_initial_or_wait_transition(self):
        for waiting in (False,True):
            self.setUp()
            if waiting:self.d.after_product_lock=lambda d:d.reviews[9].update(review_status='승인')
            else:self.d.reviews[9]['review_status']='승인'
            out=self.auto();self.assertEqual((out['auto_approved'],out['left_to_human']),(False,False))
            self.assertEqual(self.d.writes,[]);self.assertEqual(self.d.logs,[])
    def test_auto_scope409_not_swallowed_by_handled_exception(self):
        self.d.after_product_lock=lambda d:d.reviews[9].update(product_code=101)
        self.no_write_http(self.auto,409,'검수 대상 연결이 변경되었습니다 — 새로고침 후 다시 시도하세요')
    def test_auto_missing404_wrongfield400_and_human_null_bad_threshold(self):
        self.d.reviews.pop(9);self.no_write_http(self.auto,404)
        self.setUp();self.d.reviews[9]['field_name']='length_mm';self.no_write_http(self.auto,400)
        for value in (None,'bad','10500','0'):
            self.setUp();self.d.reviews[9]['suggested_value']=value;out=self.auto()
            self.assertFalse(out['auto_approved']);self.assertTrue(out['left_to_human']);self.assertEqual(self.d.writes,[])
    def test_auto_uses_current_product_price_after_guard_wait(self):
        self.d.after_product_lock=lambda d:d.products[102].update(market_price=20000)
        out=self.auto();self.assertEqual(out['old_value'],20000);self.assertFalse(out['auto_approved']);self.assertEqual(self.d.writes,[])
    def test_undo_log_first_then_all_products_reviews_sorted_original_entry_order(self):
        self.processed();out=self.undo();self.assertEqual(out,{'ok':True,'restored':2})
        self.assertIn('FOR UPDATE',self.d.calls[0][0]);self.assertEqual([p for i,p in self.guards()],[[101,102]])
        self.assertEqual([rid for i,rid in self.reviewlocks()],[3,9])
        self.assertEqual([p['rid'] for q,p in self.d.writes if "review_status='대기'" in q],[3,9])
        self.assertEqual([p['d'] for q,p in self.d.writes if q.startswith('UPDATE product_reviews SET detail')],['old3','old9'])
        self.assertIn("action='review_undo'",self.d.calls[1][0])
        self.assertEqual(self.d.calls[1][1],{'id':'70'})
        self.assertLess(1,self.guards()[0][0])
    def undo_source(self, item):
        action,target,detail,kw=item
        self.d.source_log={'action':action,'detail':deepcopy(detail)}
    def assert_duplicate_undo_no_new_mutation(self, log_id):
        state=deepcopy((self.d.products,self.d.reviews,self.d.specs,self.d.writes,self.d.logs))
        start=len(self.d.calls)
        with self.assertRaises(HTTPException) as caught:self.env['undo'](log_id)
        self.assertEqual((caught.exception.status_code,caught.exception.detail),(409,'이미 대기 상태입니다'))
        self.assertEqual((self.d.products,self.d.reviews,self.d.specs,self.d.writes,self.d.logs),state)
        calls=self.d.calls[start:];self.assertEqual(len(calls),2)
        self.assertIn('FOR UPDATE',calls[0][0]);self.assertIn("action='review_undo'",calls[1][0])
        self.assertFalse(any(q==_LOCK_PRODUCTS_SQL or q.startswith(('UPDATE ','INSERT ','DELETE ')) for q,p in calls))
    def test_undo_old_approve_after_reapproval409_preserves_latest_and_latest_undo_works(self):
        self.process(also=(),action='manual',value='11000');old=deepcopy(self.d.logs[-1])
        self.undo_source(old);self.assertEqual(self.env['undo'](70),{'ok':True,'restored':1})
        self.process(also=(),action='manual',value='12000');latest=deepcopy(self.d.logs[-1])
        self.undo_source(old);self.assert_duplicate_undo_no_new_mutation(70)
        self.assertEqual(self.d.products[102]['market_price'],12000)
        self.undo_source(latest);self.assertEqual(self.env['undo'](71),{'ok':True,'restored':1})
        self.assertEqual(self.d.products[102]['market_price'],10000)
        self.assertEqual(self.d.logs[-1][2],{'ref_log_id':71,'count':1})
    def test_duplicate_after_original_log_wait409_before_products_even_reapproved(self):
        self.processed()
        self.d.after_log_lock=lambda d:d.logs.append(('review_undo','70',{'ref_log_id':70},{}))
        self.d.source_log={'action':'review_process','detail':{}}
        with self.assertRaises(HTTPException) as caught:self.env['undo'](70)
        self.assertEqual((caught.exception.status_code,caught.exception.detail),(409,'이미 대기 상태입니다'))
        self.assertEqual(self.guards(),[]);self.assertEqual(self.reviewlocks(),[]);self.assertEqual(self.d.writes,[])
        self.assertEqual(len(self.d.logs),1);self.assertEqual((self.d.commits,self.d.rollbacks),(0,1))
    def test_permanent_duplicate_guard_all_original_actions_and_also_bulk_whole_scope(self):
        for action in ('review_process','review_bulk_confirm','review_auto_approve','review_bulk_reject'):
            self.setUp();self.processed()
            self.d.source_log={'action':action,'detail':{}}
            self.d.logs=[('review_undo','70',{'ref_log_id':70,'count':2},{})]
            self.assert_duplicate_undo_no_new_mutation(70)
    def test_first_undo_all_real_original_paths_and_same_undo409(self):
        for kind,count in (('also',2),('bulk',2),('auto',1),('reject',1),('reject_bulk',2)):
            self.setUp()
            if kind=='also':self.process()
            elif kind=='bulk':self.bulk()
            elif kind=='auto':self.auto()
            elif kind=='reject':self.process(action='reject',also=())
            else:
                for r in self.d.reviews.values():r['suggested_value']='0'
                self.reject_bulk()
            self.undo_source(self.d.logs[-1])
            result=self.env['undo'](70)
            self.assertEqual(result,{'ok':True,'restored':count})
            self.assertEqual(self.d.logs[-1],('review_undo','70',{'ref_log_id':70,'count':count},{}))
            self.assertEqual((self.d.commits,self.d.rollbacks),(2,0))
            self.assert_duplicate_undo_no_new_mutation(70)
            self.assertEqual((self.d.commits,self.d.rollbacks),(2,1))
    def test_duplicate_receipt_exact_ref_and_action_no_false_positive(self):
        for action,ref in (('other_action',70),('review_undo',7),('review_undo',701),('review_undo',None)):
            self.setUp();self.processed();self.d.logs=[(action,'x',{'ref_log_id':ref},{})]
            self.assertEqual(self.undo(),{'ok':True,'restored':2})
            self.assertEqual(self.d.logs[-1][0],'review_undo')
    def test_original_missing_or_wrong_action404_before_duplicate_query(self):
        for original in (None,{'action':'other','detail':{}}):
            self.setUp();self.d.source_log=original
            self.no_write_http(lambda:self.env['undo'](70),404,'되돌릴 작업 기록이 없습니다')
            self.assertEqual(len(self.d.calls),1);self.assertEqual(self.guards(),[])
    def test_duplicate_query_exception_propagates_caller_rollback_without_retry_or_guard(self):
        self.processed();error=RuntimeError('mock duplicate query failure');self.d.undo_query_error=error
        before=deepcopy((self.d.products,self.d.reviews,self.d.specs))
        with self.assertRaises(RuntimeError) as caught:self.undo()
        self.assertIs(caught.exception,error);self.assertEqual((self.d.products,self.d.reviews,self.d.specs),before)
        self.assertEqual((self.d.commits,self.d.rollbacks),(0,1));self.assertEqual(len(self.d.calls),2)
        self.assertEqual(self.guards(),[]);self.assertEqual(self.d.writes,[]);self.assertEqual(self.d.logs,[])
    def test_undo_waiting_after_log_wait_exact409_no_product_child_write(self):
        self.processed();self.d.after_log_lock=lambda d:d.reviews[3].update(review_status='대기')
        self.no_write_http(self.undo,409,'이미 대기 상태입니다')
    def test_undo_rebinding_or_status_drift_scope409_no_write(self):
        for fn in (lambda d:d.reviews[3].update(product_code=999),lambda d:d.reviews[3].update(review_status='승인')):
            self.setUp();self.processed();self.d.after_product_lock=fn;self.no_write_http(self.undo,409)
    def test_undo_old_reject_log_missing_detail_does_not_overwrite_original(self):
        self.processed();self.undo([{'review_id':9,'mode':'reject','before':{'review_status':'대기'}}])
        self.assertFalse(any(q.startswith('UPDATE product_reviews SET detail') for q,p in self.d.writes))
        self.assertEqual(self.d.reviews[9]['detail'],'original')
    def test_undo_repeated_same_entry_retains_original_waiting409_and_rollback(self):
        self.processed();entry={'review_id':9,'mode':'reject','before':{}}
        with self.assertRaises(HTTPException) as c:self.undo([entry,entry])
        self.assertEqual(c.exception.detail,'이미 대기 상태입니다');self.assertEqual(self.d.reviews[9]['review_status'],'보류')
        self.assertEqual(self.d.logs,[]);self.assertEqual((self.d.commits,self.d.rollbacks),(0,1))
    def test_spec_approval_product_guard_before_specs_and_original_gate_rule(self):
        self.d.reviews[9]['field_name']='length_mm';out=self.process(also=(),value='300',action='manual')
        self.assertEqual(out['pool_added'],1);self.assertEqual(self.d.specs[102]['length_mm'],300)
        self.assertLess(self.guards()[0][0],next(i for i,(q,p) in enumerate(self.d.calls) if 'FROM product_specs' in q))
    def test_actual_price_validation_400_remains(self):
        for value in ('','0','-1','bad'):
            self.setUp();self.no_write_http(lambda:self.process(also=(),value=value,action='manual'),400)
    def test_guard_SQL_failure_and_log_failure_propagate_caller_rollback_no_retry(self):
        for name in ('process','auto','bulk','reject_bulk','undo'):
            self.setUp();self.d.reviews[9]['suggested_value']='0' if name=='reject_bulk' else '10200'
            if name=='undo':self.processed()
            error=RuntimeError('mock guard failure');self.d.guard_error=error
            with self.assertRaises(RuntimeError) as c:getattr(self,name)()
            self.assertIs(c.exception,error);self.assertEqual(len(self.guards()),1);self.assertEqual(self.d.writes,[])
            self.assertEqual((self.d.commits,self.d.rollbacks),(0,1))
            self.setUp();self.d.reviews[9]['suggested_value']='0' if name=='reject_bulk' else '10200'
            if name=='undo':self.processed()
            prior=deepcopy((self.d.products,self.d.reviews));self.d.log_error=error
            with self.assertRaises(RuntimeError) as c:getattr(self,name)()
            self.assertIs(c.exception,error);self.assertEqual((self.d.products,self.d.reviews),prior)
            self.assertEqual(self.d.logs,[]);self.assertEqual((self.d.commits,self.d.rollbacks),(0,1))
    def test_scope_change_at_review_lock_boundary_no_write_or_late_product(self):
        self.d.after_review_lock=lambda d:d.reviews[9].update(product_code=999)
        self.no_write_http(self.process,409);self.assertEqual([p for i,p in self.guards()],[[101,102]])
    def test_same_product_distinct_reviews_guard_once_history_only_first_change(self):
        self.d.reviews[3]['product_code']=102;out=self.process()
        self.assertEqual([p for i,p in self.guards()],[[102]]);self.assertEqual(out['applied'],2)
        self.assertEqual(len([q for q,p in self.d.writes if q.startswith('INSERT INTO product_price_history')]),1)
    def test_undo_market_restore_actual_current_price_reverse_ledger_and_human_actor(self):
        self.processed();self.d.products[102]['market_price']=12000
        out=self.undo([{'review_id':9,'mode':'approve','field':'market_price',
            'before':{'product_value':10000,'locked_fields':[],'review_status':'대기'}}])
        self.assertEqual(out['restored'],1);self.assertEqual(self.d.products[102]['market_price'],10000)
        history=[p for q,p in self.d.writes if q.startswith('INSERT INTO product_price_history')]
        self.assertEqual(history,[{'pc':102,'o':12000,'n':10000,'ref':9,'op':21}])
        self.assertIsNone(self.d.reviews[9]['reviewed_by'])
    def test_undo_initial_missing_review_exact404_message_and_no_write(self):
        self.processed();self.d.reviews.pop(9)
        self.no_write_http(self.undo,404,'검수 항목이 없습니다: 9')
    def fallback(self):
        with self.d.begin() as conn:
            return self.env['_lock_waiting_review'](conn,9)
    def test_fallback_single_product_before_review_and_current_row_reread(self):
        self.d.after_product_lock=lambda d:d.reviews[9].update(suggested_value='11000')
        row=self.fallback();self.assertEqual(row['suggested_value'],'11000')
        self.assertEqual([p for i,p in self.guards()],[[102]])
        self.assertLess(self.guards()[0][0],self.reviewlocks()[0][0])
    def test_fallback_binding_or_field_drift409_no_writes(self):
        for fn in (lambda d:d.reviews[9].update(product_code=101),lambda d:d.reviews[9].update(field_name='length_mm')):
            self.setUp();self.d.after_product_lock=fn;self.no_write_http(self.fallback,409)
            self.assertEqual((self.d.commits,self.d.rollbacks),(0,1))
    def test_fallback_initial_missing404_waiting_transition_handled409(self):
        self.d.reviews.pop(9);self.no_write_http(self.fallback,404)
        self.setUp();self.d.after_product_lock=lambda d:d.reviews[9].update(review_status='승인')
        self.no_write_http(self.fallback,409,'이미 처리된 항목입니다')
    def test_fallback_guard_SQL_exception_identity_and_caller_rollback(self):
        error=RuntimeError('mock CLI guard failure');self.d.guard_error=error
        with self.assertRaises(RuntimeError) as c:self.fallback()
        self.assertIs(c.exception,error);self.assertEqual((self.d.commits,self.d.rollbacks),(0,1))
        self.assertEqual(self.reviewlocks(),[]);self.assertEqual(self.d.writes,[])
    def cli_env(self):
        return dict(self.env,engine=self.d,_log=self.d.log,print=lambda *a,**kw:None)
    def approval_cli_loop(self,passed):
        path=Path(__file__).resolve().parents[1]/'tools/approve_suggestions.py'
        main=next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='main')
        loop=next(n for n in main.body if isinstance(n,ast.For) and isinstance(n.iter,ast.Name) and n.iter.id=='passed')
        env=self.cli_env();env.update(passed=passed,done=0,failed=[],pool_added=0)
        exec(compile(ast.Module(body=[loop],type_ignores=[]),str(path),'exec'),env)
        return env['done'],env['failed'],env['pool_added']
    def mall_cli(self,approve=True):
        path=Path(__file__).resolve().parents[1]/'tools/mall_market_price_apply.py'
        node=next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='apply_one')
        class Imports(ast.NodeTransformer):
            def visit_ImportFrom(self,node):return None
        node=Imports().visit(node)
        env=self.cli_env();env.update(PRICE_INSERT_SQL=text('SELECT mock_new_review'),PRICE_REVIEW_TYPE='mock_type',
            DETAIL_TMPL='{v} {when}',OWNER_APPROVAL='original planned approval',
            auto_approve_market_price=lambda rid:{'auto_approved':False,'reason':'human'})
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),str(path),'exec'),env)
        return env['apply_one']({'pc':102,'new':10200},'fixed time',approve)
    def test_approve_suggestions_real_loop_fallback_actual_approve_and_per_item_partial_success(self):
        self.d.reviews[9]['field_name']='length_mm'
        done,failed,pool=self.approval_cli_loop([(9,'length_mm','300','GPU','P102',None),(999,'length_mm','300','GPU','missing',None)])
        self.assertEqual((done,len(failed),pool),(1,1,1));self.assertEqual((self.d.commits,self.d.rollbacks),(1,1))
        self.assertEqual(self.d.specs[102]['length_mm'],300);self.assertEqual(self.d.logs[0][2]['value'],'300')
        self.assertLess(self.guards()[0][0],self.reviewlocks()[0][0])
    def test_approve_suggestions_loop_does_not_replace_planned_value_policy(self):
        self.d.after_product_lock=lambda d:d.reviews[9].update(suggested_value='11111')
        done,failed,pool=self.approval_cli_loop([(9,'market_price','10200','GPU','P102',None)])
        self.assertEqual((done,failed,pool),(1,[],0));self.assertEqual(self.d.products[102]['market_price'],10200)
    def test_mall_actual_apply_one_fallback_actual_business_helper_auto_NULL_actor(self):
        out=self.mall_cli();self.assertEqual(out,('승인(첫 값)',True))
        self.assertEqual([p for i,p in self.guards()],[[102]])
        self.assertLess(self.guards()[0][0],self.reviewlocks()[0][0])
        self.assertEqual(self.d.reviews[9]['reviewed_by'],None)
        self.assertEqual([p['op'] for q,p in self.d.writes if q.startswith('INSERT INTO product_price_history')],[None])
        self.assertEqual(self.d.logs[0][3],{'auto':True})
    def test_mall_existing_catch_message_scope409_and_no_approval_writes(self):
        self.d.after_product_lock=lambda d:d.reviews[9].update(product_code=101)
        msg,applied=self.mall_cli();self.assertFalse(applied)
        self.assertEqual(msg,'승인 거부됨(검수 대상 연결이 변경되었습니다 — 새로고침 후 다시 시도하세요)')
        self.assertEqual(self.d.writes,[]);self.assertEqual(self.d.logs,[])
    def test_mall_without_approve_permission_stops_before_fallback(self):
        self.assertEqual(self.mall_cli(False),('검수 대기로 남김(human)',False));self.assertEqual(self.guards(),[])
        self.assertEqual(self.d.writes,[])
    def test_no_operational_imports(self):
        import sys
        self.assertFalse(any(n in sys.modules for n in ('api.db','api.main','api.admin_products')))


if __name__=='__main__':unittest.main()
