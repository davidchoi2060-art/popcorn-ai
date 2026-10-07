"""Selected original auth ContextVar/ASGI + actual writer, simulated SQL/TX only.

No real auth/main/db/environment/provider execution; existing audit guard and
session resolver AST fixture are installed before the HTTP module is imported.
"""
from copy import deepcopy
import ast
import json
from pathlib import Path
import re
import threading
import unittest
from unittest.mock import patch
from uuid import UUID

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from tests import test_admin_commerce_orders as auth_fixture
from tests.test_commerce_fulfillment_read import Connection as ReadConnection
from tests.test_commerce_fulfillment_read import Result, NO, TOKEN
from tests.test_commerce_fulfillment_writer import prep_request, shipping_request, policy
from tests import test_commerce_fulfillment_core as fixture
from api import commerce_contract as c
from api import commerce_owner as owner
from api import commerce_fulfillment_writer as writer
from api import commerce_fulfillment_http as h

POLICY = owner.OwnerPolicy('https://example.invalid', 900, True, True)
ADMIN = '/api/admin/commerce/orders/' + NO + '/fulfillment'
CUSTOMER = '/api/commerce/orders/' + NO + '/fulfillment'


class Connection(ReadConnection):
    def __init__(self, engine):
        super().__init__(); self.engine = engine
        self.data = deepcopy(engine.data); self.saved = deepcopy(self.data)
        self.txid = engine.next_txid; engine.next_txid += 1
        self.initial_txid = self.txid
        self.clock = engine.now; self.readonly = False
        self.fail_tag = engine.fail_tag; self.cas_tag = engine.cas_tag

    def execute(self, statement, params=None):
        sql = str(statement); p = params or {}
        tag = re.search(r'/\*(?:fulfillment_http|commerce_owner):(\w+)\*/', sql)
        if tag:
            name = tag[1]; self.trace.append((name, sql, deepcopy(p)))
            if self.engine.fail_tag == name: raise RuntimeError(fixture.PRIVATE)
            if name == 'readonly': self.readonly = True; result = Result()
            elif name == 'clock': result = Result(scalar=self.engine.now)
            elif name == 'session':
                row = self.engine.auth_engine.sessions.get(p['sid'])
                result = Result([{key: row[key] for key in ('operator_id','role','status','revoked','expired','idle')}] if row else [])
            elif name == 'ready': result = Result()
            elif name == 'lookup':
                row = self.engine.owner_context
                result = Result([row] if row and row['credential_hash'] == p['credential_hash'] else [])
            elif name == 'sources':
                result = Result([{key: row[key] for key in ('movement_id','product_code','qty_delta','operation_id','effect_key')}
                                 for row in self.data['movements']])
            else: raise AssertionError('unexpected HTTP SQL ' + name)
        else:
            if self.readonly and re.search(r'\b(?:INSERT|UPDATE|DELETE)\b|FOR UPDATE', sql):
                raise AssertionError('GET tried business write or lock')
            result = super().execute(statement, p)
            name = self.trace[-1][0]
        if self.engine.after_tag: self.engine.after_tag(self, name)
        return result

    def rollback(self):
        self.engine.lifecycle.append(('rollback_read', self.txid)); self.rollback_simulation()
        if self.engine.fail == 'rollback_read': raise RuntimeError(fixture.PRIVATE)


class Context:
    def __init__(self, engine, write): self.engine, self.write = engine, write
    def __enter__(self):
        self.conn = Connection(self.engine); self.engine.connections.append(self.conn)
        self.engine.lifecycle.append(('begin' if self.write else 'open_read', self.conn.txid))
        if not self.write and self.engine.read_hook: self.engine.read_hook(self.conn)
        return self.conn
    def __exit__(self, typ, value, tb):
        try:
            if self.write:
                if typ is not None:
                    self.engine.lifecycle.append(('rollback_write', self.conn.txid)); self.conn.rollback_simulation()
                else:
                    if self.conn.aborted: raise RuntimeError(fixture.PRIVATE)
                    if self.engine.fail == 'commit_before':
                        self.conn.rollback_simulation(); self.engine.lifecycle.append(('rollback_write', self.conn.txid))
                        raise RuntimeError(fixture.PRIVATE)
                    self.engine.data = deepcopy(self.conn.data)
                    self.engine.lifecycle.append(('commit', self.conn.txid))
                    if self.engine.fail == 'commit_after': raise RuntimeError(fixture.PRIVATE)
        finally:
            name = 'close_write' if self.write else 'close_read'
            self.engine.lifecycle.append((name, self.conn.initial_txid))
            if self.engine.fail == name: raise RuntimeError(fixture.PRIVATE)


class Engine:
    def __init__(self, auth_engine):
        seed = ReadConnection(); self.data = deepcopy(seed.data)
        self.owner_context = deepcopy(seed.owner_context); self.auth_engine = auth_engine
        self.connections = []; self.lifecycle = []; self.next_txid = 100; self.now = 100
        self.fail = self.fail_tag = self.cas_tag = self.after_tag = self.read_hook = None
        self.serial = 500
    def begin(self):
        if self.fail == 'begin': raise RuntimeError(fixture.PRIVATE)
        return Context(self, True)
    def connect(self):
        if self.fail == 'connect': raise RuntimeError(fixture.PRIVATE)
        return Context(self, False)


class FulfillmentHTTPTests(unittest.TestCase):
    def setUp(self):
        self.auth = auth_fixture.auth; self.auth_engine = auth_fixture.AuthEngine()
        self.auth_engine.seed('session-7', 7, 'operator')
        self.auth_engine.seed('session-8', 8, 'owner')
        self.auth_engine.seed('session-viewer', 9, 'viewer')
        self.auth.engine = self.auth_engine; self.auth._device_trust_ready = None
        self.engine = Engine(self.auth_engine)
        self.app = FastAPI(); self.app.include_router(h.create_router())
        self.app.middleware('http')(self.auth.auth_middleware)
        self.app.middleware('http')(h.fulfillment_no_store)
        self.client = TestClient(self.app, base_url=POLICY.origin); self.addCleanup(self.client.close)
        for key, value in (('get_engine', self.engine), ('get_auth', self.auth), ('get_origin', POLICY.origin)):
            p = patch.object(h, key, return_value=value); p.start(); self.addCleanup(p.stop)
        p = patch.object(h.owner_http, 'get_policy', return_value=POLICY); p.start(); self.addCleanup(p.stop)
        self.resolver = patch.object(h, 'get_policies', return_value=dict(preparation=policy(),fulfillment=fixture.inputs()['policy']))
        self.policy_mock = self.resolver.start(); self.addCleanup(self.resolver.stop)

    def headers(self, token='session-7', customer=False):
        return {'Cookie': (owner.COOKIE if customer else self.auth.COOKIE) + '=' + (TOKEN if customer else token),
                'Origin': POLICY.origin, 'Content-Type': 'application/json'}

    def request(self, cmd=None, *, path=ADMIN, token='session-7', customer=False, **kwargs):
        headers = self.headers(token, customer)
        headers.update(kwargs.pop('headers', {}))
        params = kwargs.pop('params', {'expected_binding_id':self.engine.owner_context['context_id']} if customer else {})
        if cmd is None:
            return self.client.get(path, headers=headers, params=params, **kwargs)
        return self.client.post(path, json=cmd, headers=headers, params=params, **kwargs)

    def checked(self, response, status=200):
        self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(response.headers.get('cache-control'), 'no-store')
        payload = response.json()
        residual = deepcopy(payload)
        private_values = (fixture.PRIVATE, TOKEN, 'session-7', 'owner_identity', 'provider_binding', 'actor_id', 'core_result')
        if status == 200 and response.request.method == 'GET' and response.request.url.path == ADMIN:
            fields = {'operation_id', 'action', 'shipment_revision', 'order_revision', 'actor_id',
                      'event_kind', 'quantities', 'outcome', 'occurred_at', 'reference', 'ready'}
            for ship in residual['shipments']:
                history = ship.pop('history')
                stored = sorted((op for op in self.engine.data['physical_ops'].values()
                                 if op['shipment_id'] == ship['shipment_id']),
                                key=lambda op: op['result']['shipment_revision'])
                self.assertEqual(len(history), len(stored))
                for entry, op in zip(history, stored):
                    self.assertEqual(set(entry), fields)
                    request, result = op['request'], op['result']
                    evidence = request.get('evidence')
                    self.assertIs(type(entry['actor_id']), int)
                    self.assertEqual(entry, dict(
                        operation_id=op['operation_id'], action=op['action'],
                        shipment_revision=result['shipment_revision'], order_revision=result['order_revision'],
                        actor_id=op['actor_id'], event_kind=request.get('event_kind'),
                        quantities=request.get('quantities'), outcome=request.get('outcome'),
                        occurred_at=evidence['occurred_at'] if evidence is not None else None,
                        reference=evidence['reference'] if evidence is not None else None, ready=result['ready']))
                    if entry['quantities'] is not None:
                        for metric in entry['quantities']:
                            self.assertEqual(set(metric), {'line_id', 'observed_qty'})
                    if entry['reference'] is not None:
                        self.assertIs(type(entry['reference']), str)
                    for private in (TOKEN, 'session-7', 'owner_identity', 'provider_binding', 'core_result'):
                        self.assertNotIn(private, json.dumps(entry))
                    safe_entry = {key: value for key, value in entry.items() if key not in ('actor_id', 'reference')}
                    encoded = json.dumps(safe_entry)
                    for private in private_values:
                        self.assertNotIn(private, encoded)
        encoded = json.dumps(residual)
        self.assertNotRegex(encoded, r'"(?:history|reference)"\s*:')
        for private in (fixture.PRIVATE, TOKEN, 'session-7', 'owner_identity', 'provider_binding', 'actor_id', 'core_result'):
            self.assertNotIn(private, encoded)
        return payload

    def make(self, action='prepare_shipment', sid=None, **changes):
        conn = ReadConnection(); conn.data = deepcopy(self.engine.data)
        conn.clock = self.engine.now; conn.serial = self.engine.serial
        if action == 'prepare_shipment': req = prep_request(conn)
        elif action == 'record_preparation_event':
            lines = [{key: row[key] for key in ('line_id','product_code','qty','sale_movement_id')}
                     for row in self.engine.data['cargo'] if row['shipment_id'] == sid]
            event = changes.pop('event', 'assembly_started')
            req = prep_request(conn, action, sid=sid, lines=lines, event=event,
                quantities=[dict(line_id=l['line_id'],observed_qty=l['qty']) for l in lines],
                outcome='accepted' if event == 'inspection_recorded' else 'recorded')
        elif action == 'confirm_dispatch_ready':
            refs = [dict(operation_id=op['operation_id'],evidence_basis=op['request']['evidence']['basis'])
                    for op in self.engine.data['physical_ops'].values() if op['action']=='record_preparation_event'
                    and op['request']['event_kind'] in ('assembly_completed','inspection_recorded')]
            req = prep_request(conn, action, sid=sid, refs=refs)
        else: req = shipping_request(conn, sid, action)
        self.engine.serial = conn.serial; self.engine.now = conn.clock
        return h.command(h.intent(req) | changes)

    def prepare(self):
        cmd = self.make(); data = self.checked(self.request(cmd))
        return data['shipment_id'], cmd

    def ready(self, sid):
        for event in ('assembly_started','assembly_completed','inspection_recorded'):
            self.checked(self.request(self.make('record_preparation_event',sid,event=event)))
        self.checked(self.request(self.make('confirm_dispatch_ready',sid)))

    def test_initial_real_writer_pending_then_distinct_read_tx_and_public_result(self):
        with patch.object(writer,'execute_preparation',wraps=writer.execute_preparation) as execute, patch.object(writer,'read_result',wraps=writer.read_result) as read:
            sid, cmd = self.prepare()
        execute.assert_called_once(); read.assert_called_once()
        self.assertEqual(len(self.engine.connections),2)
        first, second = self.engine.connections
        self.assertNotEqual(first.initial_txid,second.initial_txid)
        self.assertEqual(self.engine.lifecycle[-2:], [('rollback_read',second.initial_txid),('close_read',second.initial_txid)])
        record=self.engine.data['physical_ops'][cmd['operation_id']]
        self.assertEqual(record['actor_id'],7); self.assertEqual(record['shipment_id'],sid)
        self.assertIsNone(self.checked(self.request(customer=True,path=CUSTOMER))['shipments'][0]['handed_off_at'])

    def test_all_six_actions_and_exact_replays_never_recompute_current_business(self):
        commands=[]; cmd=self.make(); sid=self.checked(self.request(cmd))['shipment_id']; commands.append(cmd)
        for event in ('assembly_started','assembly_completed','inspection_recorded'):
            cmd=self.make('record_preparation_event',sid,event=event); data=self.checked(self.request(cmd)); commands.append(cmd)
            self.assertEqual(data['order_state'],'조립중')
        for action in ('confirm_dispatch_ready','record_tracking','handoff','deliver'):
            cmd=self.make(action,sid); data=self.checked(self.request(cmd)); commands.append(cmd)
        self.assertEqual(data['order_state'],'완료')
        before=deepcopy(self.engine.data)
        with patch.object(h,'get_policies',side_effect=AssertionError('no policy replan')), patch.object(h,'_new_request',side_effect=AssertionError('no source regeneration')), patch.object(writer,'_origin',side_effect=AssertionError('no financial replan')), patch.object(writer,'_observations',side_effect=AssertionError('no qty replan')):
            for cmd in commands:
                data=self.checked(self.request(cmd)); self.assertEqual(data['operation_id'],cmd['operation_id'])
        self.assertEqual(self.engine.data,before)
        self.assertEqual(len(self.engine.data['movements']),2)
        self.assertEqual(len(self.engine.data['payments']),1)

    def test_original_get_is_historical_result_current_get_is_current_state(self):
        sid, cmd=self.prepare(); self.ready(sid)
        self.checked(self.request(self.make('record_tracking',sid)))
        self.checked(self.request(self.make('handoff',sid)))
        with patch.object(h,'get_policies',side_effect=AssertionError('no source for old GET')):
            old=self.checked(self.request(path=ADMIN+'/operations/'+cmd['operation_id']))
        current=self.checked(self.request())
        self.assertEqual(old['order_state'],'결제완료'); self.assertFalse(old['ready'])
        self.assertEqual(current['order_state'],'배송중')
        self.assertTrue(all(not a['allowed'] for a in current['actions'].values()))

    def test_changed_intent_and_actor_never_rekey_or_add_effect(self):
        _,cmd=self.prepare(); before=deepcopy(self.engine.data)
        for field,value in (('expected_order_revision',99),('expected_policy_basis','a'*64),('lines',[dict(line_id='a',qty=1)])):
            self.checked(self.request(dict(cmd,**{field:value})),409)
        self.checked(self.request(cmd,token='session-8'),403)
        self.checked(self.request(path=ADMIN+'/operations/'+cmd['operation_id'],token='session-viewer'),403)
        self.assertEqual(self.engine.data,before)

    def test_native_contextvar_survives_threadpool_no_fallback_and_no_extra_resolver(self):
        threads=[]; original=h._session
        def observe(*args):
            threads.append((threading.get_ident(),self.auth.current_operator()['operator_id']))
            return original(*args)
        main=threading.get_ident()
        with patch.object(h,'_session',side_effect=observe), patch.object(self.auth,'resolve_session',wraps=self.auth.resolve_session) as resolve:
            self.prepare()
        self.assertEqual(resolve.call_count,1)
        self.assertTrue(threads); self.assertTrue(all(t != main and actor==7 for t,actor in threads))
        business_sql=' '.join(sql for conn in self.engine.connections for _,sql,_ in conn.trace)
        self.assertNotIn('UPDATE admin_sessions',business_sql)

    def test_early_original_auth_denials_and_invalid_methods_all_have_outer_no_store(self):
        self.checked(self.request(token='absent'),401)
        self.checked(self.request(self.make(),token='session-viewer'),403)
        self.assertEqual(self.engine.connections,[])
        for path,method in ((ADMIN,'delete'),(CUSTOMER,'post'),(CUSTOMER+'/operations/'+str(UUID(int=1)),'get')):
            response=getattr(self.client,method)(path,headers=self.headers())
            self.assertIn(response.status_code,(404,405)); self.assertEqual(response.headers['cache-control'],'no-store')

    def test_customer_owner_scope_before_any_physical_and_no_financial_queries(self):
        self.prepare(); self.engine.connections.clear()
        payload=self.checked(self.request(customer=True,path=CUSTOMER))
        self.assertEqual(len(payload['shipments']),1)
        conn=self.engine.connections[0]; tags=[tag for tag,_,_ in conn.trace]
        self.assertLess(tags.index('lookup'),tags.index('scope')); self.assertLess(tags.index('scope'),tags.index('snapshot'))
        self.assertFalse(any(tag in ('balance','order_bundle','physical_operation','sources') for tag in tags))
        self.engine.owner_context['context_id']=str(UUID(int=900)); self.engine.connections.clear()
        self.checked(self.request(customer=True,path=CUSTOMER),404)
        self.assertFalse(any(tag=='snapshot' for conn in self.engine.connections for tag,_,_ in conn.trace))

    def test_customer_expiry_revocation_binding_and_member_label_do_not_grant_access(self):
        original=deepcopy(self.engine.owner_context)
        for key,value,status in (('expires_at',100,401),('revoked_at',1,401)):
            self.engine.owner_context=deepcopy(original); self.engine.owner_context[key]=value
            self.checked(self.request(customer=True,path=CUSTOMER),status)
        self.engine.owner_context=deepcopy(original)
        self.checked(self.request(customer=True,path=CUSTOMER,params={'expected_binding_id':str(UUID(int=999))}),409)
        member=dict(kind='member',member_id=7,auth_subject='development-only')
        self.engine.owner_context.update(owner_identity=member,owner_scope=c.fingerprint(member))
        self.checked(self.request(customer=True,path=CUSTOMER),401)

    def test_live_session_db_probe_detects_role_status_expiry_revocation_and_bad_native_actor(self):
        for changes,status in ((dict(role='viewer'),403),(dict(status='정지'),403),(dict(revoked=True),401),(dict(expired=True),401),(dict(idle=True),401),(dict(operator_id=True),503)):
            old=deepcopy(self.auth_engine.sessions['session-7'])
            # Change after middleware has captured its original principal.
            self.engine.after_tag=lambda conn,tag,ch=changes: self.auth_engine.sessions['session-7'].update(ch) if tag=='clock' else None
            self.checked(self.request(),status)
            self.auth_engine.sessions['session-7']=old; self.engine.after_tag=None

    def test_auth_loss_after_insert_rolls_back_entire_business_tx(self):
        before=deepcopy(self.engine.data)
        self.engine.after_tag=lambda conn,tag: self.auth_engine.sessions['session-7'].update(revoked=True) if tag=='physical_order_event' else None
        self.checked(self.request(self.make()),401)
        self.assertEqual(self.engine.data,before)
        self.assertTrue(any(tag=='rollback_write' for tag,_ in self.engine.lifecycle))

    def test_auth_loss_after_commit_returns_denial_not_a_success_or_generic_unknown(self):
        self.engine.read_hook=lambda conn: self.auth_engine.sessions['session-7'].update(revoked=True)
        self.checked(self.request(self.make()),401)
        self.assertEqual(len(self.engine.data['physical_ops']),1)

    def test_commit_ack_or_write_close_unknown_preserves_original_uuid_get_recovery(self):
        for fail in ('commit_after','close_write'):
            with self.subTest(fail=fail):
                # Independent original fixture, no overwrite of failed run evidence.
                self.engine.data=deepcopy(ReadConnection().data); self.engine.fail=fail
                cmd=self.make(); self.checked(self.request(cmd),503)
                self.assertIn(cmd['operation_id'],self.engine.data['physical_ops'])
                self.engine.fail=None
                data=self.checked(self.request(path=ADMIN+'/operations/'+cmd['operation_id']))
                self.assertEqual(data['operation_id'],cmd['operation_id'])

    def test_precommit_failure_missing_uuid404_does_not_claim_not_executed(self):
        cmd=self.make(); self.engine.fail='commit_before'
        self.checked(self.request(cmd),503); self.engine.fail=None
        response=self.request(path=ADMIN+'/operations/'+cmd['operation_id']); data=self.checked(response,404)
        self.assertEqual(set(data),{'detail'}); self.assertNotIn('not_executed',response.text)
        self.assertEqual(self.engine.data['physical_ops'],{})

    def test_read_rollback_close_connect_failure_never_returns_data(self):
        self.prepare()
        for fail in ('rollback_read','close_read','connect'):
            self.engine.fail=fail; payload=self.checked(self.request(),503)
            self.assertEqual(set(payload),{'detail'})
        self.engine.fail=None

    def test_unavailable_table_pending_operation_actual_write_tx_and_tampered_receipt_fail_closed(self):
        _,cmd=self.prepare(); original=deepcopy(self.engine.data)
        self.engine.fail_tag='snapshot'; self.checked(self.request(),503); self.engine.fail_tag=None
        self.engine.data['physical_ops'][cmd['operation_id']]['state']='unknown'
        self.checked(self.request(),503); self.checked(self.request(path=ADMIN+'/operations/'+cmd['operation_id']),503)
        self.engine.data=deepcopy(original)
        self.engine.read_hook=lambda conn: setattr(conn,'txid',original['physical_ops'][cmd['operation_id']]['write_txid'])
        self.checked(self.request(path=ADMIN+'/operations/'+cmd['operation_id']),503); self.engine.read_hook=None
        self.engine.data['physical_ops'][cmd['operation_id']]['receipt']['result_basis']='a'*64
        self.checked(self.request(path=ADMIN+'/operations/'+cmd['operation_id']),503)

    def test_all_exception_late_cas_failures_restore_state_with_no_stock_effects(self):
        for tag in ('physical_insert_operation','physical_order_event'):
            self.engine.fail_tag=tag; before=deepcopy(self.engine.data)
            self.checked(self.request(self.make()),503); self.assertEqual(self.engine.data,before)
        self.engine.fail_tag=None; self.engine.cas_tag='update_order'
        before=deepcopy(self.engine.data); self.checked(self.request(self.make()),503)
        self.assertEqual(self.engine.data,before)

    def test_unconnected_policy_and_origin_never_create_operation(self):
        with patch.object(h,'get_origin',return_value=None): self.checked(self.request(self.make()),503)
        self.assertEqual(self.engine.connections,[])
        self.policy_mock.return_value=None
        self.checked(self.request(self.make()),503); self.assertEqual(self.engine.data['physical_ops'],{})

    def test_strict_duplicate_json_query_fields_native_values_and_stream_limit(self):
        cmd=self.make()
        for change in (dict(actor_id=7),dict(grant=True),dict(ready=True),dict(expected_order_revision=True),
                       dict(lines=[dict(line_id='a',qty=0)]),dict(lines=[dict(line_id='a',qty=1)]*2)):
            self.checked(self.request(dict(cmd,**change)),422)
        raw=json.dumps(cmd)[:-1]+',"action":"prepare_shipment"}'
        self.checked(self.client.post(ADMIN,content=raw,headers=self.headers()),422)
        self.checked(self.client.post(ADMIN,content=b' '* (h.MAX_REQUEST_BYTES+1),headers=self.headers()),422)
        self.checked(self.request(params=[('x','1'),('x','2')]),422)
        self.checked(self.request(customer=True,path=CUSTOMER,params={}),422)
        self.assertEqual(self.engine.connections,[])

    def test_csrf_tls_and_future_observation_are_rejected_without_fake_fact(self):
        self.checked(self.request(self.make(),headers={'Origin':'https://foreign.invalid'}),403)
        self.checked(self.request(self.make(),headers={'Sec-Fetch-Site':'cross-site'}),403)
        sid,_=self.prepare(); cmd=self.make('record_preparation_event',sid)
        cmd['observation']['occurred_at']=self.engine.now+1
        before=deepcopy(self.engine.data); self.checked(self.request(cmd),422); self.assertEqual(self.engine.data,before)
        with TestClient(self.app,base_url='http://example.invalid') as client:
            self.checked(client.get(ADMIN,headers=self.headers()),503)

    def test_current_final_owner_change_and_exception_outer_redaction(self):
        self.prepare(); lookups=[]
        def change(conn,tag):
            if tag=='lookup':
                lookups.append(tag)
                if len(lookups)==2:self.engine.owner_context['revoked_at']=1
        self.engine.after_tag=change
        self.checked(self.request(customer=True,path=CUSTOMER),401)
        self.engine.after_tag=None
        with patch.object(h,'_handle',side_effect=RuntimeError(fixture.PRIVATE)):
            self.checked(self.request(),503)

    def test_source_resolver_cannot_change_callers_transaction(self):
        def changed(conn,**kwargs):
            conn.txid+=1
            return dict(preparation=policy(),fulfillment=fixture.inputs()['policy'])
        with patch.object(h,'get_policies',side_effect=changed): self.checked(self.request(self.make()),503)
        self.assertEqual(self.engine.data['physical_ops'],{})

    def test_foreign_existing_uuid_blocks_before_new_policy_source(self):
        _,cmd=self.prepare()
        self.engine.data['physical_ops'][cmd['operation_id']]['order_id']=88
        before=deepcopy(self.engine.data)
        with patch.object(h,'get_policies',side_effect=AssertionError('foreign UUID must stop first')) as source:
            self.checked(self.request(cmd),409)
            self.checked(self.request(path=ADMIN+'/operations/'+cmd['operation_id']),404)
        source.assert_not_called(); self.assertEqual(self.engine.data,before)

    def test_final_same_binding_owner_identity_change_cannot_leak_prior_owner_data(self):
        self.prepare(); clocks=[]
        def change(conn,tag):
            if tag=='clock':
                clocks.append(tag)
                if len(clocks)==2:
                    identity=dict(self.engine.owner_context['owner_identity'],owner_hash='f'*64)
                    self.engine.owner_context.update(owner_identity=identity,owner_scope=c.fingerprint(identity))
        self.engine.after_tag=change
        self.checked(self.request(customer=True,path=CUSTOMER),409)

    def test_final_auth_probe_cannot_switch_read_transaction(self):
        self.prepare(); clocks=[]
        def change(conn,tag):
            if tag=='clock':
                clocks.append(tag)
                if len(clocks)==2:conn.txid+=1
        self.engine.after_tag=change
        self.checked(self.request(),503)

    def test_factory_has_no_global_router_or_import_time_registration(self):
        self.assertFalse(any(isinstance(v,APIRouter) for v in vars(h).values()))
        self.assertEqual(len(h.create_router().routes),4)
        source=Path(h.__file__).read_text(encoding='utf-8'); tree=ast.parse(source)
        self.assertFalse(any(isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) for n in tree.body))
        self.assertNotIn('include_router',source); self.assertNotIn('resolve_session(',source)
        self.assertNotIn('current_operator_id(',source); self.assertNotIn('UPDATE admin_sessions',source)

    def test_admin_current_history_allows_only_stored_actor_and_reference(self):
        cmd = self.make()
        sid = self.checked(self.request(cmd, token='session-8'))['shipment_id']
        self.checked(self.request(self.make('record_preparation_event', sid), token='session-8'))
        history = self.checked(self.request())['shipments'][0]['history']
        self.assertEqual([entry['actor_id'] for entry in history], [8, 8])
        self.assertIsNone(history[0]['reference']); self.assertIsNone(history[0]['occurred_at'])
        self.assertEqual(history[1]['reference'], fixture.PRIVATE)
        self.assertEqual(history[1]['event_kind'], 'assembly_started')
        self.assertEqual(history[0]['operation_id'], cmd['operation_id'])
        self.assertNotIn('history', self.checked(self.request(path=ADMIN+'/operations/'+cmd['operation_id'], token='session-8')))
        customer = self.checked(self.request(customer=True, path=CUSTOMER))
        self.assertTrue(all('history' not in ship for ship in customer['shipments']))

    def test_admin_current_history_guard_rejects_extra_fields_wrong_actor_and_reference(self):
        sid, _ = self.prepare(); self.ready(sid)
        current = self.checked(self.request())
        cases = [('actor_id', 99), ('reference', 'unrelated observation'), ('reference', None)]
        cases += [(field, 'hidden') for field in (
            'owner_identity', 'provider_binding', 'core_result', 'receipt', 'request', 'proof',
            'verification', 'request_basis', 'rules_basis', 'product_code', 'sale_movement_id')]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                tampered = deepcopy(current)
                tampered['shipments'][0]['history'][1][field] = value
                with patch.object(h.reader, 'read_current', return_value=tampered):
                    with self.assertRaises(AssertionError): self.checked(self.request())
        tampered = deepcopy(current)
        tampered['shipments'][0]['history'][1]['quantities'][0]['actor_id'] = 7
        with patch.object(h.reader, 'read_current', return_value=tampered):
            with self.assertRaises(AssertionError): self.checked(self.request())

    def test_history_exception_never_allows_actor_reference_in_other_locations_or_audiences(self):
        sid, cmd = self.prepare(); self.ready(sid)
        current = self.checked(self.request())
        for target, field, value in (
                ('root', 'actor_id', 7), ('shipment', 'actor_id', 7),
                ('root', 'reference', fixture.PRIVATE), ('shipment', 'reference', 'plain unexpected reference'),
                ('root', 'debug', dict(nested=dict(actor_id=7))),
                ('shipment', 'debug', dict(nested=dict(reference='plain unexpected reference')))):
            with self.subTest(target=target, field=field):
                tampered = deepcopy(current)
                place = tampered if target == 'root' else tampered['shipments'][0]
                place[field] = value
                with patch.object(h.reader, 'read_current', return_value=tampered):
                    with self.assertRaises(AssertionError): self.checked(self.request())
        customer = self.checked(self.request(customer=True, path=CUSTOMER))
        for field, value in (('history', []), ('history', current['shipments'][0]['history']),
                             ('actor_id', 7), ('reference', 'unexpected customer reference')):
            with self.subTest(audience='customer', field=field):
                tampered = deepcopy(customer); tampered['shipments'][0][field] = value
                with patch.object(h.reader, 'read_current', return_value=tampered):
                    with self.assertRaises(AssertionError): self.checked(self.request(customer=True, path=CUSTOMER))
        original = self.checked(self.request(path=ADMIN+'/operations/'+cmd['operation_id']))
        for field, value in (('actor_id', 7), ('reference', fixture.PRIVATE), ('history', [])):
            with self.subTest(audience='operation', field=field):
                with patch.object(h, '_result_payload', return_value=dict(original, **{field: value})):
                    with self.assertRaises(AssertionError):
                        self.checked(self.request(path=ADMIN+'/operations/'+cmd['operation_id']))


if __name__ == '__main__':
    unittest.main()
