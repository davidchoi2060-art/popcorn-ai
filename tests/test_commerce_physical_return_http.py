"""Actual auth AST/ASGI + frozen return reader/storage fixtures, SQL/TX doubles.

No actual api.auth/main/db execution, PG/network/provider/production env.
"""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from uuid import UUID
import ast
import asyncio
import json
import re
import threading
import unittest

from tests import test_admin_commerce_orders as auth_fixture
from tests import test_commerce_physical_return_persistence as storage_fixture
from tests.test_commerce_physical_return_persistence import Connection as StoredConnection
from tests.test_commerce_fulfillment_writer import Result
from tests import test_commerce_physical_return_core as fixture
from fastapi import FastAPI
from fastapi.testclient import TestClient
from api import commerce_physical_return_http as h
from api import commerce_contract as c

NO = 'fixture-order'
PATH = '/api/admin/commerce/orders/' + NO + '/physical-returns'


class Connection(StoredConnection):
    def __init__(self, engine):
        super().__init__(); self.engine=engine
        self.data=deepcopy(engine.data); self.saved=deepcopy(self.data)
        self.txid=engine.next_txid; engine.next_txid+=1; self.initial_txid=self.txid
        self.clock=engine.now; self.readonly=False; self.fail_tag=engine.fail_tag

    def execute(self, statement, params=None):
        sql=str(statement); p=params or {}
        tag=re.search(r'/\*physical_return_http:(\w+)\*/',sql)
        if tag:
            name=tag[1]; self.trace.append((name,sql,deepcopy(p)))
            if self.engine.fail_tag==name: raise RuntimeError(fixture.PRIVATE)
            if name=='readonly': self.readonly=True; result=Result()
            elif name=='clock': result=Result(scalar=self.engine.now)
            elif name=='session':
                row=self.engine.auth_engine.sessions.get(p['sid'])
                rows=[{k:row[k] for k in ('operator_id','role','status','revoked','expired','idle')}] if row else []
                if self.engine.session_hook: rows=self.engine.session_hook(rows)
                result=Result(rows)
            else: raise AssertionError('unexpected HTTP SQL '+name)
        else:
            if self.readonly and re.search(r'\b(?:INSERT|UPDATE|DELETE)\b|FOR UPDATE',sql):
                raise AssertionError('GET attempted business mutation/lock')
            result=super().execute(statement,p); name=self.trace[-1][0]
        if self.engine.after_tag: self.engine.after_tag(self,name)
        return result

    def rollback(self):
        self.engine.lifecycle.append(('rollback_read',self.initial_txid)); self.rollback_simulation()
        if self.engine.fail=='rollback': raise RuntimeError(fixture.PRIVATE)


class Context:
    def __init__(self,engine): self.engine=engine
    def __enter__(self):
        self.conn=Connection(self.engine); self.engine.connections.append(self.conn)
        self.engine.lifecycle.append(('open_read',self.conn.initial_txid)); return self.conn
    def __exit__(self,*args):
        self.engine.lifecycle.append(('close_read',self.conn.initial_txid))
        if self.engine.fail=='close': raise RuntimeError(fixture.PRIVATE)


class Engine:
    def __init__(self,auth_engine):
        seed=StoredConnection(); self.data=deepcopy(seed.data); self.auth_engine=auth_engine
        self.now=100; self.next_txid=1000; self.connections=[]; self.lifecycle=[]
        self.fail=self.fail_tag=self.after_tag=self.session_hook=None
    def connect(self):
        if self.fail=='connect': raise RuntimeError(fixture.PRIVATE)
        return Context(self)
    def begin(self): raise AssertionError('read HTTP must never begin write/commit')


class ReturnHTTPTests(unittest.TestCase):
    def setUp(self):
        self.auth=auth_fixture.auth; self.auth_engine=auth_fixture.AuthEngine()
        for token,actor,role in (('session-7',7,'operator'),('session-8',8,'owner'),('session-viewer',9,'viewer')):
            self.auth_engine.seed(token,actor,role)
        self.auth.engine=self.auth_engine; self.auth._device_trust_ready=None
        self.engine=Engine(self.auth_engine)
        self.app=FastAPI(); self.app.include_router(h.create_router())
        self.app.middleware('http')(self.auth.auth_middleware)
        self.app.middleware('http')(h.physical_return_no_store)
        self.client=TestClient(self.app,base_url='https://example.invalid'); self.addCleanup(self.client.close)
        for key,value in (('get_engine',self.engine),('get_auth',self.auth)):
            p=patch.object(h,key,return_value=value); p.start(); self.addCleanup(p.stop)

    def get(self,path=PATH,token='session-7',**kwargs):
        return self.client.get(path,headers={'Cookie':self.auth.COOKIE+'='+token},**kwargs)
    def check(self,response,status=200):
        self.assertEqual(response.status_code,status,response.text)
        self.assertEqual(response.headers.get('cache-control'),'no-store')
        payload=response.json(); serialized=json.dumps(payload)
        denied={'owner_identity','owner_scope','provider_binding','provider_ref','request_basis','core_result',
                'receipt','write_txid','read_txid','sale_movement_id','product_code'}
        def fields(value):
            if type(value) is dict:
                self.assertFalse(denied.intersection(value),value)
                for item in value.values(): fields(item)
            elif type(value) is list:
                for item in value: fields(item)
        fields(payload)
        for token in ('session-7','session-8','session-viewer'): self.assertNotIn(token,serialized)
        if status!=200: self.assertNotIn(fixture.PRIVATE,serialized)
        return payload
    def seed(self,through='restore'):
        # Real five-stage helpers invoke storage writer/core. Seed then COMMIT in
        # the limited simulator; HTTP GET sees a separate snapshot/transaction.
        helper=storage_fixture.PersistenceTests(); helper.conn=StoredConnection(); helper.ship()
        commands=[]; cmd=helper.command(); rid=helper.commit(cmd)['return_id']; commands.append(cmd)
        if through!='create_case':
            for action in ('record_collection','record_receipt','inspect','restore'):
                cmd=helper.command(action,rid); helper.commit(cmd); commands.append(cmd)
                if action==through: break
        self.engine.data=deepcopy(helper.conn.data); self.engine.now=helper.conn.clock+10
        return rid,commands

    def test_current_exact_reader_dto_and_empty_is_confirmed_not_unconnected_success(self):
        value=self.check(self.get(token='session-viewer'))
        self.assertEqual(set(value),set(h.CURRENT)); self.assertEqual(value['cases'],[])
        self.assertEqual(value['actions'],{a:dict(allowed=False,reason='source_unconnected') for a in ('inspect','restore')})
        self.assertEqual(value['version'],'commerce_physical_return_storage_v1')
    def test_current_full_history_quantities_evidence_only_allowlist(self):
        rid,commands=self.seed(); value=self.check(self.get())
        case=value['cases'][0]; self.assertEqual(case['return_id'],rid); self.assertEqual(case['revision'],5)
        self.assertEqual([v['operation_id'] for v in case['history']],[v['operation_id'] for v in commands])
        self.assertEqual(set(case['lines'][0]),set(h.LINE)); self.assertEqual(set(case['history'][0]),set(h.HISTORY))
        self.assertTrue(all(v['restoration_remaining_qty']==0 for v in case['lines']))
        self.assertIsNone(case['history'][-1]['occurred_at']); self.assertEqual(case['history'][-1]['evidence'][0]['kind'],'inspect')
        self.assertEqual(case['history'][1]['reference'],fixture.PRIVATE) # Authenticated historical admin field only.
    def test_result_all_five_exact_stored_uuid_no_replan_and_no_private_history(self):
        rid,commands=self.seed(); before=deepcopy(self.engine.data)
        with patch.object(h.reader.core,'plan_physical_return',side_effect=AssertionError('replan forbidden')):
            for cmd in commands:
                value=self.check(self.get(PATH+'/operations/'+cmd['operation_id']))
                self.assertEqual(set(value),set(h.RESULT)); self.assertEqual(value['return_id'],rid)
                self.assertFalse(value['pending']); self.assertFalse(value['pending_commit'])
                self.assertNotIn(fixture.PRIVATE,json.dumps(value))
        self.assertEqual(before,self.engine.data)
        self.assertFalse(any(tag=='return_snapshot' for conn in self.engine.connections for tag,_,_ in conn.trace))
    def test_current_readonly_single_snapshot_no_locks_commits_and_close_before_response(self):
        self.seed(); before=deepcopy(self.engine.data); self.check(self.get())
        conn=self.engine.connections[-1]; self.assertTrue(conn.readonly)
        self.assertEqual([tag for tag,_,_ in conn.trace].count('return_snapshot'),1)
        self.assertFalse(any(re.search(r'\b(?:INSERT|UPDATE|DELETE)\b|FOR UPDATE',sql) for _,sql,_ in conn.trace))
        self.assertEqual(self.engine.lifecycle,[('open_read',1000),('rollback_read',1000),('close_read',1000)])
        self.assertEqual(self.engine.data,before)
    def test_current_basis_and_token_across_read_transactions_are_stable(self):
        self.seed('record_receipt'); first=self.check(self.get()); second=self.check(self.get())
        self.assertEqual(first['expected_history_token'],second['expected_history_token'])
        self.assertEqual(first['expected_order_basis'],second['expected_order_basis'])
        self.assertNotEqual(self.engine.connections[-1].initial_txid,self.engine.connections[-2].initial_txid)
    def test_absent_session_and_cookie_never_open_business_connection(self):
        self.check(self.client.get(PATH),401); self.check(self.get(token='missing'),401)
        self.assertEqual(self.engine.connections,[])
    def test_viewer_can_current_but_original_result_requires_exact_actor_and_action_role(self):
        _,commands=self.seed(); path=PATH+'/operations/'+commands[0]['operation_id']
        self.check(self.get(token='session-viewer'))
        self.check(self.get(path,token='session-viewer'),403); self.check(self.get(path,token='session-8'),403)
        self.check(self.get(path))
    def test_suspended_or_invalid_role_denied(self):
        self.auth_engine.sessions['session-7']['status']='정지'; self.check(self.get(),401)
        self.auth_engine.sessions['session-7']['status']='활성'; self.auth_engine.sessions['session-7']['role']='invalid'
        response=self.get(); self.assertIn(response.status_code,(401,403)); self.check(response,response.status_code)
    def test_https_required_and_customer_route_not_created(self):
        self.check(self.get('http://example.invalid'+PATH),503)
        self.assertEqual(self.client.get('/api/commerce/orders/'+NO+'/physical-returns').status_code,404)
        self.assertEqual(self.engine.connections,[])
    def test_unknown_and_duplicate_queries_all_rejected_without_connection(self):
        for suffix in ('?return_id=20','?expected_binding_id=x','?x=1&x=2','?operation_id=x','?action=read'):
            with self.subTest(suffix=suffix): self.check(self.get(PATH+suffix),422)
        self.assertEqual(self.engine.connections,[])
    def test_get_body_rejected_before_connection(self):
        response=self.client.request('GET',PATH,headers={'Cookie':self.auth.COOKIE+'=session-7'},content=b'{}')
        self.check(response,422); self.assertEqual(self.engine.connections,[])
    def test_invalid_order_and_uuid_rejected(self):
        for path in (PATH.replace(NO,'bad.order'),PATH.replace(NO,'A'*21),PATH+'/operations/not-a-uuid'):
            self.check(self.get(path),422)
        self.assertEqual(self.engine.connections,[])
    def test_post_put_delete_head_not_supported_and_no_store(self):
        for method in ('POST','PUT','DELETE','HEAD'):
            response=self.client.request(method,PATH,headers={'Cookie':self.auth.COOKIE+'=session-7'},json={})
            self.assertEqual(response.status_code,405); self.assertEqual(response.headers.get('cache-control'),'no-store')
        self.assertEqual(self.engine.connections,[])
    def test_missing_order_and_missing_uuid_do_not_promote_success(self):
        self.check(self.get(PATH.replace(NO,'missing-order')),404)
        self.check(self.get(PATH+'/operations/'+str(UUID(int=9000))),404)
    def test_foreign_order_or_changed_owner_cannot_read_uuid(self):
        _,commands=self.seed(); cmd=commands[0]
        original=self.engine.data['orders'][NO]
        self.engine.data['orders']['other-order']=dict(original,order_id=2,order_no='other-order')
        self.engine.data['details'][2]=deepcopy(self.engine.data['details'][1])
        self.check(self.get(PATH.replace(NO,'other-order')+'/operations/'+cmd['operation_id']),404)
        self.engine.data['details'][1]['owner_scope']='f'*64
        self.check(self.get(PATH+'/operations/'+cmd['operation_id']),404)
    def test_unknown_stored_state_not_confirmed_result(self):
        _,commands=self.seed('create_case'); op=self.engine.data['return_ops'][commands[0]['operation_id']]
        op.update(state='unknown',result=None,receipt=None)
        value=self.check(self.get(PATH+'/operations/'+commands[0]['operation_id']),503)
        self.assertEqual(value['detail']['code'],'physical_return_result_unconfirmed')
    def test_corrupt_stored_receipt_or_same_write_read_txid_fails_closed(self):
        _,commands=self.seed('create_case'); path=PATH+'/operations/'+commands[0]['operation_id']
        record=self.engine.data['return_ops'][commands[0]['operation_id']]; original=deepcopy(record)
        record['receipt']['storage_basis']='f'*64; self.check(self.get(path),503)
        self.engine.data['return_ops'][commands[0]['operation_id']]=original
        self.engine.next_txid=original['write_txid']; self.check(self.get(path),503)
    def test_current_scope_corruption_and_sql_failure_not_empty_success(self):
        self.seed(); self.engine.data['return_lines'][51]['sale_movement_id']=999
        self.check(self.get(),503)
        self.engine.fail_tag='return_snapshot'; self.check(self.get(),503)
    def test_session_revoked_expired_idle_after_snapshot_discards_payload(self):
        self.seed()
        for field in ('revoked','expired','idle'):
            self.auth_engine.sessions['session-7'].update(revoked=False,expired=False,idle=False)
            def change(conn,tag):
                if tag=='return_snapshot': self.auth_engine.sessions['session-7'][field]=True
            self.engine.after_tag=change; self.check(self.get(),401)
        self.assertTrue(all(('close_read',conn.initial_txid) in self.engine.lifecycle for conn in self.engine.connections))
    def test_late_role_change_discards_result(self):
        self.seed()
        def change(conn,tag):
            if tag=='return_snapshot': self.auth_engine.sessions['session-7']['role']='owner'
        self.engine.after_tag=change; self.check(self.get(),403)
    def test_session_cardinality_or_native_boolean_mismatch_unready(self):
        for hook in (lambda rows:rows+rows,lambda rows:[dict(rows[0],revoked=0)]):
            self.engine.session_hook=hook; self.check(self.get(),503)
    def test_tx_change_during_snapshot_no_false_success(self):
        def change(conn,tag):
            if tag=='return_snapshot': conn.txid+=1
        self.engine.after_tag=change; self.check(self.get(),503)
    def test_connect_rollback_close_failures_are_redacted_without_retry(self):
        for mode in ('connect','rollback','close'):
            self.engine.fail=mode; before=len(self.engine.connections); self.check(self.get(),503)
            self.assertEqual(len(self.engine.connections)-before,0 if mode=='connect' else 1)
    def test_result_rollback_close_failure_does_not_publish_confirmed(self):
        _,commands=self.seed(); path=PATH+'/operations/'+commands[0]['operation_id']
        for mode in ('rollback','close'):
            self.engine.fail=mode; self.check(self.get(path),503)
    def test_extra_current_nested_private_field_or_result_private_field_rejected(self):
        self.seed(); actual=h.reader.read_current
        def leak(*args,**kwargs):
            value=actual(*args,**kwargs); value['cases'][0]['history'][0]['receipt']={'raw':fixture.PRIVATE}; return value
        with patch.object(h.reader,'read_current',side_effect=leak): self.check(self.get(),503)
        _,commands=self.seed(); actual_result=h.reader.read_result
        def result_leak(*args,**kwargs): value=actual_result(*args,**kwargs); value['owner_scope']='f'*64; return value
        with patch.object(h.reader,'read_result',side_effect=result_leak): self.check(self.get(PATH+'/operations/'+commands[0]['operation_id']),503)
    def test_pending_or_wrong_identity_result_projection_rejected(self):
        _,commands=self.seed(); path=PATH+'/operations/'+commands[0]['operation_id']; actual=h.reader.read_result
        for change in (dict(pending=True),dict(pending_commit=True),dict(order_no='other-order'),dict(operation_id=str(UUID(int=9000))),
                       dict(return_id=999),dict(order_revision=999),dict(return_revision=999),dict(lines=[])):
            def corrupt(*args,**kwargs): return actual(*args,**kwargs)|change
            with patch.object(h.reader,'read_result',side_effect=corrupt): self.check(self.get(path),503)
    def test_contextvars_parallel_requests_do_not_share_actor(self):
        _,commands=self.seed(); path=PATH+'/operations/'+commands[0]['operation_id']; results=[]
        def request(token): results.append((token,self.get(path,token=token).status_code))
        threads=[threading.Thread(target=request,args=(token,)) for token in ('session-7','session-8')]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertCountEqual(results,[('session-7',200),('session-8',403)])
    def test_disconnected_before_or_after_read_never_publishes_success(self):
        for values in ((True,),(False,True)):
            with patch.object(h.Request,'is_disconnected',side_effect=values): self.check(self.get(),503)
    def test_no_store_outside_auth_and_unhandled_route_exception(self):
        self.check(self.client.get(PATH),401)
        # Inspect exception redaction directly without an alternate route/app.
        request=h.Request({'type':'http','method':'GET','path':'/api/admin/commerce/orders/broken/physical-returns','headers':[],'query_string':b''})
        async def fail(request): raise RuntimeError(fixture.PRIVATE)
        response=asyncio.run(h.physical_return_no_store(request,fail)); self.assertEqual(response.status_code,503)
        self.assertNotIn(fixture.PRIVATE,response.body.decode())
        other=h.Request({'type':'http','method':'GET','path':'/outside','headers':[],'query_string':b''})
        with self.assertRaises(RuntimeError): asyncio.run(h.physical_return_no_store(other,fail))
    def test_factory_only_exact_get2_and_no_mutating_or_policy_callers(self):
        routes=h.create_router().routes
        self.assertEqual([(r.path,r.methods) for r in routes],[(PATH.replace(NO,'{order_no}'),{'GET'}),
            (PATH.replace(NO,'{order_no}')+'/operations/{operation_id}',{'GET'})])
        source=Path(h.__file__).read_text(encoding='utf-8'); tree=ast.parse(source)
        self.assertFalse(hasattr(h,'router')); self.assertNotIn('get_policy',source); self.assertNotIn('get_origin',source)
        for node in ast.walk(tree):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
                self.assertNotIn(node.func.attr,('commit','begin','begin_nested','execute_return','create_case','record_receipt','record_collection'))
        self.assertNotRegex(source,r'from .*main import|from .*physical_return_writer import')


if __name__=='__main__': unittest.main()
