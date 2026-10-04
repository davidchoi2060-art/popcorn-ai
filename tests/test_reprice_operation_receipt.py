"""Selected real caller/API/JS with offline mocks; no PG/auth/commit proof."""
import ast
from copy import deepcopy
import hashlib
import json
import os
import shutil
import subprocess
import unittest
from unittest.mock import patch
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException, Response
from fastapi.testclient import TestClient
from api.admin_operation_receipt_contract import validate_receipt
from tests.test_reprice_write_lock_order import (
    ROOT, Database, Connection, Transaction, routes, expected_snapshot, TEST_CONTEXT,
    TEST_ENVIRONMENT, POLICY_SHARED_SQL, POLICY_PARAMS, receipt_core as core, digest,
)


def lookup_router(db):
    tree = ast.parse((ROOT/'api/admin_operation_receipts.py').read_text(encoding='utf-8'))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
             or isinstance(n, ast.Assign)]
    def context(operator):
        with patch.object(core, 'configured_environment', return_value=TEST_ENVIRONMENT):
            return core.operation_context(operator)
    env = dict(APIRouter=APIRouter, HTTPException=HTTPException, Response=Response, UUID=UUID,
               engine=db, current_operator=db.operator, operation_context=context,
               lookup_operation=core.lookup_operation, operation_record=core.operation_record,
               ReceiptUnavailable=core.ReceiptUnavailable, OperationConflict=core.OperationConflict)
    exec(compile(ast.fix_missing_locations(ast.Module(nodes, [])), 'receipt-selected', 'exec'), env)
    return env


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        self.env = routes()
        self.env.update(engine=self.db, current_operator=self.db.operator,
                        current_operator_id=self.db.actor, _log=self.db.log)

    def body(self, **changes):
        fields = dict(scope='all', expect_changed=4, note=' 한글 😀\r\n"\\ ',
                      expected=expected_snapshot(self.db, self.env, 'all'))
        fields.update(changes)
        return self.env['ApplyBody'](**fields)

    def app(self):
        app = FastAPI()
        app.post('/api/admin/reprice/apply')(self.env['apply'])
        api = lookup_router(self.db)
        app.include_router(api['router'])
        return app, api

    def test_first_policy_then_operation_lookup_then_products_and_same_tx_final_insert(self):
        body = self.body()
        answer = self.env['apply'](body)
        calls = self.db.calls
        identity = answer['operation_receipt']
        self.assertEqual(calls[0], (POLICY_SHARED_SQL, POLICY_PARAMS))
        self.assertEqual(calls[1], (core.OPERATION_LOCK_SQL, core.operation_lock_params(identity)))
        self.assertEqual(calls[2], (core.LOOKUP_SQL, {'environment':TEST_ENVIRONMENT,
                                                    'operation_id':body.operation_id}))
        self.assertEqual(calls[-1][0], core.INSERT_SQL)
        self.assertNotIn('ON CONFLICT', core.INSERT_SQL)
        self.assertEqual(self.db.isolation_options, [{'isolation_level':'READ COMMITTED'}])
        self.assertEqual((self.db.begins,self.db.connects,self.db.commits,self.db.rollbacks),(1,0,1,0))
        self.assertEqual(identity['result'], {k:answer[k] for k in core.RESULT_FIELDS})
        self.assertEqual(self.db.logs[-1]['operator_id'], identity['actor_id'])
        self.assertEqual(len(self.db.receipts),1)
        self.assertNotIn('note', json.dumps(list(self.db.receipts.values())))

    def test_same_uuid_replays_original_receipt_before_any_price_or_expected_recalculation(self):
        body = self.body()
        original = self.env['apply'](body)
        self.db.fee = float('nan')  # Any reclassification would now fail.
        self.db.products[102]['sale_price'] = 77777
        before, start = self.db.state(), len(self.db.calls)
        self.assertEqual(self.env['apply'](body), original)
        self.assertEqual(self.db.state(), before)
        self.assertEqual(len(self.db.calls[start:]),3)
        self.assertEqual([q for q,_ in self.db.calls[start:]],
                         [POLICY_SHARED_SQL,core.OPERATION_LOCK_SQL,core.LOOKUP_SQL])
        self.assertEqual(len(self.db.receipts),1)

    def test_same_uuid_different_validated_payload_or_actor_is_generic409_before_business_reads(self):
        body = self.body()
        self.env['apply'](body)
        for changed in ('note','actor'):
            payload = body.model_dump()
            if changed == 'note':payload['note'] += 'different'
            else:
                payload['operation_context']['actor_id'] = 27
                self.env['current_operator'] = lambda:{'role':'owner','operator_id':27}
            payload['request_fingerprint'] = core.request_fingerprint(payload)
            request = self.env['ApplyModel'](**payload)
            before, start = self.db.state(), len(self.db.calls)
            with self.assertRaises(HTTPException) as got:self.env['apply'](request)
            self.assertEqual((got.exception.status_code,got.exception.detail),(409,'재산정 요청 정보가 다릅니다'))
            self.assertEqual(len(self.db.calls[start:]),3)
            self.assertEqual(self.db.state(),before)

    def test_operation_key_excludes_actor_action_and_payload_but_full_identity_comparison_does_not(self):
        identity = TEST_CONTEXT | {'operation_id':'22f71a0f-a9e0-4dce-a5e6-70e1c523be87',
                                   'target':{'scope':'all'},'request_fingerprint':'a'*64}
        key = core.operation_lock_params(identity)
        self.assertEqual(key['namespace'], int.from_bytes(b'POPR','big'))
        self.assertGreaterEqual(key['key'], -(2**31))
        self.assertLess(key['key'], 2**31)
        for changes in ({'actor_id':27},{'action':'other'},{'request_fingerprint':'b'*64}):
            self.assertEqual(core.operation_lock_params(identity|changes),key)
        self.assertNotEqual(core.operation_lock_params(identity|{'environment':'22f71a0f-a9e0-4dce-a5e6-70e1c523be87'}),key)

    def test_mock_winner_becomes_visible_after_operation_guard_before_any_price_read(self):
        body=self.body();winner=self.env['apply'](body)
        row=deepcopy(next(iter(self.db.receipts.values())))
        self.setUp()
        db=self.db
        class WaitedConnection(Connection):
            def execute(self,statement,params=None):
                result=super().execute(statement,params)
                if str(statement)==core.OPERATION_LOCK_SQL:
                    db.receipts[(row['environment'],row['operation_id'])]=deepcopy(row)
                    self.receipt_snapshot=deepcopy(db.receipts)  # External committed mock winner.
                return result
        class WaitedTransaction(Transaction):
            def __enter__(self):
                self.conn=WaitedConnection(db);return self.conn
        db.begin=lambda:WaitedTransaction(db,True)
        self.assertEqual(self.env['apply'](body),winner)
        self.assertEqual([q for q,_ in db.calls],
                         [POLICY_SHARED_SQL,core.OPERATION_LOCK_SQL,core.LOOKUP_SQL])
        self.assertEqual((db.histories,db.logs),([],[]))

    def test_full_rollback_removes_binding_same_uuid_changed_payload_is_not_permanently_fenced(self):
        # Explicitly preserve the documented limit; the browser never does this automatically.
        body=self.body()
        self.db.fail=lambda q,p:RuntimeError('rollback') if q==core.INSERT_SQL else None
        with self.assertRaises(RuntimeError):self.env['apply'](body)
        self.assertEqual(self.db.receipts,{})
        self.db.fail=None
        payload=body.model_dump();payload['note']='changed after complete rollback'
        payload['request_fingerprint']=core.request_fingerprint(payload)
        answer=self.env['apply'](self.env['ApplyModel'](**payload))
        self.assertEqual(answer['operation_receipt']['operation_id'],body.operation_id)
        self.assertNotEqual(answer['operation_receipt']['request_fingerprint'],body.request_fingerprint)

    def test_canonical_validated_semantics_ignore_json_key_order_and_operation_id_but_reject_surrogates(self):
        payload=self.body().model_dump()
        expected=core.request_fingerprint(payload)
        reversed_payload=dict(reversed(list(payload.items())))
        reversed_payload['expected']=dict(reversed(list(payload['expected'].items())))
        reversed_payload['operation_id']='22f71a0f-a9e0-4dce-a5e6-70e1c523be87'
        self.assertEqual(core.request_fingerprint(reversed_payload),expected)
        with self.assertRaises(core.OperationConflict):
            core.request_fingerprint(payload|{'note':'\ud800'})

    def test_expected_versions_are_closed_and_domain_separated_without_changing_request_v1(self):
        payload = self.body().model_dump()
        fingerprints = []
        for version in ('reprice_basis_v1', 'reprice_basis_v2'):
            candidate = payload | {'expected':payload['expected'] | {'version':version}}
            command = ['reprice_request_v1', 'reprice_apply', candidate['scope'],
                       str(candidate['expect_changed']),
                       [version,candidate['expected']['scope'],candidate['expected']['fingerprint']],
                       candidate['note']]
            golden = hashlib.sha256(json.dumps(command,ensure_ascii=False,
                                               separators=(',',':')).encode('utf-8')).hexdigest()
            fingerprints.append(core.request_fingerprint(candidate))
            self.assertEqual(fingerprints[-1],golden)
        self.assertNotEqual(*fingerprints)
        for version in ('reprice_basis_v3', '', None, True, 2, ['reprice_basis_v2']):
            with self.assertRaises(core.OperationConflict):
                core.request_fingerprint(payload | {'expected':payload['expected'] | {'version':version}})

    def test_new_legacy_v1_request_is_rejected_after_lookup_before_any_basis_or_business_read(self):
        body = self.body(expected=self.body().expected.model_dump() | {'version':'reprice_basis_v1'})
        before = self.db.state()
        with self.assertRaises(HTTPException) as got:self.env['apply'](body)
        self.assertEqual(got.exception.status_code,409)
        self.assertIn('새 미리보기',got.exception.detail)
        self.assertEqual([q for q,_ in self.db.calls],
                         [POLICY_SHARED_SQL,core.OPERATION_LOCK_SQL,core.LOOKUP_SQL,core.INSERT_SQL])
        self.assertEqual(self.db.state(),before)
        self.assertEqual((self.db.commits,self.db.rollbacks),(1,0))
        row = next(iter(self.db.receipts.values()))
        self.assertEqual((row['state'],row['result'],row['log_id']),('rejected',{},None))

    def test_committed_legacy_v1_replays_and_exact_get_recovers_without_basis_calculation(self):
        body = self.body(expected=self.body().expected.model_dump() | {'version':'reprice_basis_v1'})
        identity = TEST_CONTEXT | {'operation_id':body.operation_id,'target':{'scope':body.scope},
                                   'request_fingerprint':body.request_fingerprint}
        # Model a previously committed v1 event, using the actual receipt writer on a mock caller TX.
        original = {'verdict':'original v1 result','log_id':81,'changed':4,'up':1,
                    'down':3,'locked':1,'dropped':0}
        self.db.logs.append({'log_id':81,'operator_id':21,'action':'reprice_apply'})
        with self.db.begin() as conn:stored = core.store_operation(conn,identity,original)
        self.db.fee = float('nan')  # Any new classification/snapshot would fail.
        before,start = self.db.state(),len(self.db.calls)
        self.assertEqual(self.env['apply'](body),original | {'operation_receipt':stored['receipt']})
        self.assertEqual([q for q,_ in self.db.calls[start:]],
                         [POLICY_SHARED_SQL,core.OPERATION_LOCK_SQL,core.LOOKUP_SQL])
        app,_ = self.app()
        with TestClient(app) as client:
            start = len(self.db.calls)
            found = client.get('/api/admin/reprice/operations/'+body.operation_id)
            self.assertEqual(found.status_code,200)
            self.assertEqual(found.headers['cache-control'],'no-store')
            self.assertEqual(found.json(),{'operation_receipt':stored['receipt'],
                                           'response':original,'original_http_status':200})
            self.assertEqual([q for q,_ in self.db.calls[start:]],[core.OWN_LOOKUP_SQL])
        self.assertEqual(self.db.state(),before)
        self.assertEqual(len(self.db.receipts),1)
        changed = body.model_dump()
        changed['expected']['version'] = 'reprice_basis_v2'
        changed['request_fingerprint'] = core.request_fingerprint(changed)
        start = len(self.db.calls)
        with self.assertRaises(HTTPException) as got:self.env['apply'](self.env['ApplyModel'](**changed))
        self.assertEqual((got.exception.status_code,got.exception.detail),(409,'재산정 요청 정보가 다릅니다'))
        self.assertEqual(len(self.db.calls[start:]),3)
        self.assertEqual(self.db.state(),before)

    def test_strict_http_operation_fields_and_hash_assertions_never_begin_transaction(self):
        valid = self.body().model_dump()
        app,_ = self.app()
        mutations = [
            lambda b:b.pop('operation_id'), lambda b:b.pop('operation_context'),
            lambda b:b.pop('request_fingerprint'),lambda b:b.update(operation_id='invalid'),
            lambda b:b.update(expect_changed=True),lambda b:b.update(expect_changed='4'),
            lambda b:b.update(expect_changed=2**53),lambda b:b.update(note=23),
            lambda b:b['operation_context'].update(actor_id=True),
            lambda b:b['operation_context'].update(actor_id=0),
            lambda b:b['operation_context'].update(environment='untrusted'),
            lambda b:b['operation_context'].update(canonical_version='v2'),
            lambda b:b['operation_context'].update(extra=True),lambda b:b.update(extra=True),
        ]
        with TestClient(app) as client:
            for mutate in mutations:
                payload=deepcopy(valid);mutate(payload)
                self.assertEqual(client.post('/api/admin/reprice/apply',json=payload).status_code,422)
            bad=deepcopy(valid);bad['note']='different'
            self.assertEqual(client.post('/api/admin/reprice/apply',json=bad).status_code,409)
        self.assertEqual(self.db.begins,0)
        self.assertEqual(self.db.calls,[])

    def test_missing_malformed_environment_and_seed_fallback_actor_fail_closed_without_db(self):
        body = self.body()
        self.env['prepare_reprice_operation'] = core.prepare_reprice_operation
        for value in ('','not-a-uuid', TEST_ENVIRONMENT.upper()):
            with patch.dict(os.environ, {'ADMIN_OPERATION_ENVIRONMENT':value}):
                with self.assertRaises(HTTPException) as got:self.env['apply'](body)
                self.assertEqual(got.exception.status_code,503)
        self.env['current_operator'] = lambda:{'role':'owner'}
        with self.assertRaises(HTTPException) as got:self.env['apply'](body)
        self.assertEqual(got.exception.status_code,409)
        self.assertEqual(self.db.actor_calls,0)
        self.assertEqual(self.db.begins,0)

    def test_prewrite_rejected_is_committed_without_price_history_or_log_and_exact_get_confirms(self):
        body = self.body(expect_changed=3)
        app,_ = self.app()
        with TestClient(app) as client:
            response = client.post('/api/admin/reprice/apply',json=body.model_dump())
            self.assertEqual(response.status_code,409)
            row = next(iter(self.db.receipts.values()))
            self.assertEqual((row['state'],row['log_id'],row['result']),('rejected',None,{}))
            identity = TEST_CONTEXT|{'operation_id':body.operation_id,'target':{'scope':'all'},
                                     'request_fingerprint':body.request_fingerprint}
            self.assertEqual(validate_receipt(core.operation_record(row)['receipt'],expected=identity,
                                               transport_status=409)['state'],'unknown')
            result=client.get('/api/admin/reprice/operations/'+body.operation_id)
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.headers['cache-control'],'no-store')
            self.assertEqual(validate_receipt(result.json()['operation_receipt'],
                                               expected=identity)['state'],'rejected')
            before=len(self.db.calls)
            replay=client.post('/api/admin/reprice/apply',json=body.model_dump())
            self.assertEqual(replay.json(),response.json())
            self.assertEqual(replay.status_code,409)
            self.assertEqual(len(self.db.calls[before:]),3)
        self.assertEqual((self.db.commits,self.db.rollbacks),(2,0))
        self.assertEqual((self.db.histories,self.db.logs),([],[]))

    def test_every_sql_and_log_exception_including_http_types_rolls_back_without_rejected_receipt(self):
        # v2 combines settings/margins/products into one snapshot statement; fault both reads.
        sites = [('WITH scoped_products AS',1),('WITH scoped_products AS',2)] + [
            (prefix,1) for prefix in ('SELECT product_code FROM products','UPDATE products',
                                     'INSERT INTO product_price_history','LOG ',core.INSERT_SQL)]
        for prefix,occurrence in sites:
            for error in (RuntimeError('SQL failure'), HTTPException(409,'synthetic SQL failure')):
                self.setUp();body=self.body();before=self.db.state()
                hits = []
                def fail(q,p):
                    if q.lstrip().startswith(prefix):
                        hits.append(q)
                        if len(hits) == occurrence:return error
                self.db.fail=fail
                with self.assertRaises(type(error)) as got:self.env['apply'](body)
                self.assertIs(got.exception,error)
                self.assertEqual(len(hits),occurrence)
                self.assertEqual(self.db.state(),before,prefix)
                self.assertEqual(self.db.receipts,{},prefix)
                self.assertEqual((self.db.commits,self.db.rollbacks),(0,1),prefix)

    def test_unexpected_final_unique_failure_rolls_back_all_preceding_effects(self):
        body=self.body();before=self.db.state();error=RuntimeError('unique violation')
        self.db.fail=lambda q,p:error if q==core.INSERT_SQL else None
        with self.assertRaises(RuntimeError) as got:self.env['apply'](body)
        self.assertIs(got.exception,error)
        self.assertEqual(len([q for q,_ in self.db.calls if q.startswith('UPDATE products')]),4)
        self.assertEqual(self.db.state(),before)
        self.assertEqual(self.db.receipts,{})
        self.assertEqual((self.db.commits,self.db.rollbacks),(0,1))

    def test_commit_exception_returns_no_ack_and_lookup_absence_does_not_prove_rejection(self):
        body=self.body();db=self.db
        class FailCommit(Transaction):
            def __exit__(self, typ, value, trace):
                if typ:return super().__exit__(typ,value,trace)
                db.restore(self.conn.snapshot);db.receipts=deepcopy(self.conn.receipt_snapshot)
                db.rollbacks+=1
                raise RuntimeError('ambiguous commit transport failure')
        db.begin=lambda:FailCommit(db,True)
        with self.assertRaises(RuntimeError):self.env['apply'](body)
        api=lookup_router(db)
        with self.assertRaises(HTTPException) as got:api['receipt'](UUID(body.operation_id),Response())
        self.assertEqual(got.exception.status_code,404)
        identity=TEST_CONTEXT|{'operation_id':body.operation_id,'target':{'scope':'all'},
                               'request_fingerprint':body.request_fingerprint}
        self.assertEqual(validate_receipt(None,expected=identity,transport_status=404)['state'],'unknown')

    def test_postcommit_response_loss_exact_lookup_survives_changed_current_prices(self):
        body=self.body();original=self.env['apply'](body)  # Simulated transport discards this reply.
        self.db.products[102]['sale_price']=77777
        app,_=self.app()
        with TestClient(app) as client:
            context=client.get('/api/admin/reprice/operations/context')
            self.assertEqual(context.json(),TEST_CONTEXT)
            self.assertEqual(context.headers['cache-control'],'no-store')
            start=len(self.db.calls)
            found=client.get('/api/admin/reprice/operations/'+body.operation_id)
            self.assertEqual(found.status_code,200)
            self.assertEqual(found.json()['operation_receipt'],original['operation_receipt'])
            self.assertEqual(found.json()['response'],{k:original[k] for k in core.RESULT_FIELDS}|{'verdict':original['verdict']})
            self.assertEqual(self.db.calls[start:],[(
                core.OWN_LOOKUP_SQL,{'environment':TEST_ENVIRONMENT,'operation_id':body.operation_id,
                                     'actor_id':21,'action':'reprice_apply'})])

    def test_exact_lookup_actor_role_filter_and_errors_no_store_never_expose_foreign_receipt(self):
        body=self.body();self.env['apply'](body)
        api=lookup_router(self.db)
        api['current_operator']=lambda:{'role':'owner','operator_id':27}
        with self.assertRaises(HTTPException) as got:api['receipt'](UUID(body.operation_id),Response())
        self.assertEqual((got.exception.status_code,got.exception.headers['Cache-Control']),(404,'no-store'))
        api['current_operator']=lambda:{'role':'viewer','operator_id':21}
        before=len(self.db.calls)
        with self.assertRaises(HTTPException) as got:api['context'](Response())
        self.assertEqual(got.exception.status_code,403)
        self.assertEqual(len(self.db.calls),before)
        api['current_operator']=self.db.operator;api['operation_context']=core.operation_context
        with patch.dict(os.environ,{'ADMIN_OPERATION_ENVIRONMENT':''}):
            with self.assertRaises(HTTPException) as got:api['context'](Response())
            self.assertEqual((got.exception.status_code,got.exception.headers['Cache-Control']),(503,'no-store'))

    def test_receipt_remains_original_applied_event_after_undo_and_replay_never_redoes_business(self):
        body=self.body();first=self.env['apply'](body)
        self.env['undo'](type('Undo',(),{'log_id':first['log_id']})())
        before=self.db.state()
        self.assertEqual(self.env['apply'](body),first)
        self.assertEqual(self.db.state(),before)
        self.assertEqual(next(iter(self.db.receipts.values()))['state'],'applied')

    def test_reprice_scope_type_extension_preserves_typed_results_and_other_action_id_rules(self):
        answer=self.env['apply'](self.body());receipt=answer['operation_receipt']
        for key in core.RESULT_FIELDS:
            candidate=deepcopy(receipt);candidate['result'][key]=True
            self.assertEqual(validate_receipt(candidate,expected=receipt)['state'],'invalid',key)
        for target in ({'scope':21},{'scope':'unknown'},{'scope':'all','product_code':1}):
            candidate=deepcopy(receipt);candidate['target']=target
            self.assertEqual(validate_receipt(candidate,expected=receipt)['state'],'invalid')

    def test_migration_source_unique_keys_foreign_keys_append_only_and_populated_downgrade(self):
        tree=ast.parse((ROOT/'db/migrations/versions/0124_admin_operation_receipts.py').read_text(encoding='utf-8'))
        constants={n.targets[0].id:ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)}
        self.assertEqual((constants['revision'],constants['down_revision']),('0124','0123'))
        class SQLCapture:
            def __init__(self):self.calls=[]
            def execute(self,sql):self.calls.append(sql)
        op=SQLCapture();env={'op':op}
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef)]
        exec(compile(ast.Module(nodes,[]),'migration-source-only','exec'),env)
        env['upgrade']()
        self.assertEqual(len(op.calls),4)
        ddl=' '.join(op.calls)
        for needed in ('PRIMARY KEY(environment,operation_id)','receipt_id UUID NOT NULL UNIQUE',
                       'actor_id BIGINT','REFERENCES admin_operators(operator_id)',
                       'REFERENCES admin_operator_activity_logs(log_id)',
                       'BEFORE UPDATE OR DELETE','CREATE UNIQUE INDEX','log_id IS NULL',
                       "original_http_status IN (400,409)"):
            self.assertIn(needed,ddl)
        op.calls=[];env['downgrade']()
        self.assertIn('IF EXISTS (SELECT 1 FROM admin_operation_receipts',op.calls[0])
        self.assertIn('RAISE EXCEPTION',op.calls[0])
        self.assertEqual(op.calls[1:],
                         ['DROP TABLE admin_operation_receipts','DROP FUNCTION admin_operation_receipts_immutable()'])

    def test_actual_journal_and_template_unknown_reload_actor_storage_late_ack_and_canonical(self):
        node=shutil.which('node')
        self.assertIsNotNone(node)
        script=(ROOT/'templates/admin/reprice.html.j2').read_text(encoding='utf-8').partition('<script>')[2].partition('</script>')[0]
        script=script.replace('{{ links_json | safe }}','{}').replace('{{ rounds_json | safe }}','[]')
        script=script.replace('  boot();', """window.__rp={S:S,doApply:doApply,doPreview:doPreview,checkOperation:checkOperation,
canExecute:canExecute,confirmUndo:confirmUndo,renderExecute:renderExecute,journal:function(){return J;}};
renderAll=function(){};
  boot();""")
        notes=['',' 한글 😀\r\n"\\ ','\u2028\u2029','ends\n', '𝄞 / escape\b']
        vectors=[]
        for note in notes:
            payload={'scope':'all','expect_changed':20000,'expected':{'version':'reprice_basis_v1','scope':'all','fingerprint':'a'*64},'note':note}
            vectors.append({'payload':payload,'sha':core.request_fingerprint(payload)})
        v2_vectors=[]
        for vector in vectors:
            payload=deepcopy(vector['payload']);payload['expected']['version']='reprice_basis_v2'
            fingerprint=core.request_fingerprint(payload)
            self.assertNotEqual(fingerprint,vector['sha'])
            v2_vectors.append({'payload':payload,'sha':fingerprint})
        harness=r"""
const vm=require('node:vm'),assert=require('node:assert/strict'),crypto=require('node:crypto').webcrypto;
const journalSource=JOURNAL_SOURCE,source=TEMPLATE_SOURCE,vectors=VECTORS,v2Vectors=V2_VECTORS,done=[];
const owner={contract_version:'admin_operation_v1',canonical_version:'reprice_request_v1',actor_id:21,
 environment:'3c88fbc4-091a-44ea-bc0f-1192de0ca173',action:'reprice_apply'};
const preview=()=>({scope:'live',changed:1,expected:{version:'reprice_basis_v2',scope:'live',fingerprint:'a'.repeat(64)}});
function store(){const values={};return {values,getItem(k){if(this.failRead)throw Error('read failed');return values[k]??null;},
 setItem(k,v){if(this.failWrite)throw Error('write failed');values[k]=v;if(this.badReadback)this.failRead=true;}};}
function runtime(storage=store(),mode='normal'){
 const calls=[],listeners={},timers=[],nodes={},ids=[];
 const c={subtle:crypto.subtle,randomUUID(){if(mode==='uuid-failure')throw Error('UUID failed');
   const id=crypto.randomUUID();ids.push(id);return id;}};
 const w={TextEncoder,sessionStorage:storage,crypto:mode==='no-crypto'?null:c,
   Admin2Shell:{canWrite:()=>true,meReady:Promise.resolve()}};
 const ctx={window:w,Promise,console,location:{reload(){}},setTimeout:f=>timers.push(f),
  document:{getElementById:id=>nodes[id]||(nodes[id]={innerHTML:''}),addEventListener:(k,f)=>listeners[k]=f,
   createElement:()=>({}),head:{appendChild:s=>nodes.script=s}}};
 ctx.fetch=(url,init)=>new Promise((resolve,reject)=>calls.push({url,init,resolve,reject}));
 if(mode!=='script-loadfailure')vm.runInNewContext(journalSource,ctx);vm.runInNewContext(source,ctx);
 return {r:w.__rp,w,calls,listeners,timers,storage,ids,nodes};
}
const flush=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
const reply=(call,value,status=200)=>call.resolve({ok:status===200,status,clone(){return this;},json:()=>Promise.resolve(value)});
async function start(t){
 t.r.S.preview=preview();t.r.doApply();assert.equal(t.calls[0].url,'/api/admin/reprice/operations/context');
 reply(t.calls[0],owner);
 const end=Date.now()+2000;while(!t.calls[1]&&Date.now()<end)await new Promise(setImmediate);
 assert.ok(t.calls[1]);assert.equal(t.calls[1].init.method,'POST');
 return t.calls[1];
}
function proof(t,state='applied'){
 const id=t.r.journal().snapshot().identity;
 return {...id,state,receipt_id:'8621c23b-5887-4abc-97ef-8268a5d1be21',
  result:state==='applied'?{log_id:81,changed:1,up:1,down:0,locked:0,dropped:0}:{}};
}
async function scenario(name,f){await f();done.push(name);}
(async()=>{
 await scenario('journal_script_load_failure_blocks_all_writes',async()=>{
  const t=runtime(store(),'script-loadfailure');t.r.S.preview=preview();
  assert.equal(t.r.canExecute(),false);assert.equal(t.nodes.script.src,'/shared/admin2/reprice-operation-journal.js');
  t.nodes.script.onerror();t.r.doApply();t.r.confirmUndo(100);assert.equal(t.calls.length,0);
 });
 await scenario('canonical_python_js_goldens_and_invalid_unicode',async()=>{
  const t=runtime();
  for(const v of vectors)assert.equal(await t.w.RepriceOperationJournal.fingerprint(v.payload,t.w.crypto),v.sha);
  const bad={...vectors[0].payload,note:'\uD800'};
  await assert.rejects(()=>t.w.RepriceOperationJournal.fingerprint(bad,t.w.crypto));
  for(const expect_changed of [true,'1',NaN,9007199254740992])
    await assert.rejects(()=>t.w.RepriceOperationJournal.fingerprint({...vectors[0].payload,expect_changed},t.w.crypto));
 });
 await scenario('v2_python_js_five_goldens_keep_request_v1_and_distinguish_legacy',async()=>{
  const t=runtime();assert.equal(vectors.length,5);assert.equal(v2Vectors.length,5);
  for(let i=0;i<v2Vectors.length;i++){
   const v=v2Vectors[i],legacy=vectors[i];
   assert.equal(await t.w.RepriceOperationJournal.fingerprint(v.payload,t.w.crypto),v.sha);
   assert.notEqual(v.sha,legacy.sha);
   const canonical=JSON.parse(t.w.RepriceOperationJournal.canonical(v.payload));
   assert.equal(canonical[0],'reprice_request_v1');assert.equal(canonical[4][0],'reprice_basis_v2');
  }
  for(const version of ['reprice_basis_v3','',null,true,2,['reprice_basis_v2']])
   await assert.rejects(()=>t.w.RepriceOperationJournal.fingerprint(
    {...v2Vectors[0].payload,expected:{...v2Vectors[0].payload.expected,version}},t.w.crypto));
 });
 await scenario('new_execution_and_fresh_preview_require_v2',async()=>{
  const t=runtime(),legacy={...preview(),expected:{...preview().expected,version:'reprice_basis_v1'}};
  t.r.S.preview=legacy;assert.equal(t.r.canExecute(),false);t.r.doApply();
  assert.equal(t.calls.length,0);assert.equal(t.ids.length,0);
  t.r.doPreview();reply(t.calls[0],legacy);await flush();
  assert.equal(t.r.S.preview,null);assert.ok(t.r.S.previewErr);assert.equal(t.r.canExecute(),false);
  t.r.doApply();assert.equal(t.calls.length,1);assert.equal(t.ids.length,0);
  t.r.doPreview();reply(t.calls[1],preview());await flush();assert.equal(t.r.canExecute(),true);
 });
 await scenario('legacy_v1_unknown_reload_actual_DOM_exact_GET_keeps_identity_and_ack',async()=>{
  for(const state of ['applied','rejected']){
   const storage=store(),prior=runtime(storage);
   const payload={scope:'live',expect_changed:1,
    expected:{...preview().expected,version:'reprice_basis_v1'},note:'legacy'};
   await prior.r.journal().prepare(owner,payload,()=>true);
   const identity=prior.r.journal().snapshot().identity,receipt=proof(prior,state);
   assert.equal(identity.request_fingerprint,await prior.w.RepriceOperationJournal.fingerprint(payload,prior.w.crypto));
   const raw=JSON.stringify(storage.values),next=runtime(storage);
   assert.equal(JSON.stringify(next.r.journal().snapshot().identity),JSON.stringify(identity));
   assert.equal(next.r.journal().snapshot().phase,'uncertain');assert.equal(next.calls.length,0);
   assert.equal(Object.keys(storage.values).length,1);
   assert.ok(raw.includes('popcorn.admin.reprice.operation.v1'));assert.ok(!raw.includes('legacy'));
   next.r.S.preview=preview();next.r.doApply();next.r.confirmUndo(100);
   assert.equal(next.calls.length,0);assert.equal(next.ids.length,0);
   next.r.renderExecute();assert.match(next.nodes.rpExecBody.innerHTML,/data-action="check-operation"/);
   next.listeners.click({target:{closest:()=>({getAttribute:k=>k==='data-action'?'check-operation':null})}});
   reply(next.calls[0],owner);await flush();
   assert.equal(next.calls[1].url,'/api/admin/reprice/operations/'+identity.operation_id);
   assert.equal(next.calls[1].init.cache,'no-store');
   reply(next.calls[1],{operation_receipt:receipt,response:{verdict:'original'},original_http_status:state==='applied'?200:409});
   await flush();assert.equal(next.r.journal().snapshot().phase,state);
   assert.equal(JSON.stringify(next.r.journal().snapshot().identity),JSON.stringify(identity));
   const ack=JSON.stringify(next.r.journal().snapshot());
   next.r.journal().observe(null,401,identity);
   next.r.journal().observe({...receipt,state:state==='applied'?'rejected':'applied'},200,identity);
   assert.equal(JSON.stringify(next.r.journal().snapshot()),ack);
   const again=runtime(storage);assert.equal(again.r.journal().snapshot().phase,state);
   assert.equal(JSON.stringify(again.r.journal().snapshot().identity),JSON.stringify(identity));
   assert.equal(next.ids.length,0);assert.equal(again.ids.length,0);
   assert.equal(next.calls.filter(c=>c.init.method==='POST').length,0);
  }
 });
 await scenario('transport_loss_blocks_new_ids_preview_and_undo',async()=>{
  const t=runtime(),post=await start(t);post.reject(Error('lost response'));await flush();
  assert.equal(t.r.journal().snapshot().phase,'uncertain');assert.equal(t.r.canExecute(),false);
  t.r.S.preview=preview();t.r.doApply();t.r.confirmUndo(100);assert.equal(t.calls.length,2);assert.equal(t.ids.length,1);
  t.r.doPreview();reply(t.calls[2],preview());await flush();assert.equal(t.r.canExecute(),false);
 });
 await scenario('same_tab_reload_keeps_uuid_no_automatic_post',async()=>{
  const storage=store(),t=runtime(storage),post=await start(t),id=t.r.journal().snapshot().identity.operation_id;
  const next=runtime(storage);assert.equal(next.r.journal().snapshot().phase,'uncertain');
  assert.equal(next.r.journal().snapshot().identity.operation_id,id);assert.equal(next.calls.length,0);
  const raw=JSON.stringify(storage.values);assert.ok(!raw.includes('note'));assert.ok(!raw.includes('payload'));
  post.reject(Error('late'));await flush();assert.equal(next.calls.length,0);
 });
 await scenario('lookup404_then_exact200_recovers_original_event',async()=>{
  const t=runtime(),post=await start(t),receipt=proof(t);post.reject(Error('lost'));await flush();
  t.r.checkOperation();reply(t.calls[2],owner);await flush();reply(t.calls[3],{detail:'absent'},404);await flush();
  assert.equal(t.r.journal().snapshot().phase,'uncertain');assert.equal(t.r.canExecute(),false);
  t.r.checkOperation();reply(t.calls[4],owner);await flush();
  reply(t.calls[5],{operation_receipt:receipt,response:{verdict:'confirmed'},original_http_status:200});await flush();
  assert.equal(t.r.journal().snapshot().phase,'applied');assert.equal(t.timers.length,1);
  assert.equal(t.calls.filter(c=>c.init.method==='POST').length,1);
 });
 await scenario('actor_and_environment_change_keep_old_identity_and_block_lookup',async()=>{
  for(const context of [{...owner,actor_id:27},{...owner,environment:'22f71a0f-a9e0-4dce-a5e6-70e1c523be87'}]){
   const t=runtime(),post=await start(t),id=JSON.stringify(t.r.journal().snapshot().identity);
   post.reject(Error('lost'));await flush();t.r.checkOperation();reply(t.calls[2],context);await flush();
   assert.equal(t.calls.length,3);assert.equal(JSON.stringify(t.r.journal().snapshot().identity),id);
   assert.equal(t.r.journal().snapshot().phase,'uncertain');
  }
 });
 await scenario('storage_read_write_readback_failure_and_crypto_absence_send_no_post',async()=>{
  for(const mode of ['read','write','readback','no-crypto','uuid-failure']){
   const s=store();if(mode==='read')s.failRead=true;if(mode==='write')s.failWrite=true;if(mode==='readback')s.badReadback=true;
   const t=runtime(s,mode);t.r.S.preview=preview();const promise=t.r.doApply();
   if(t.calls[0])reply(t.calls[0],owner);if(promise)await promise;await flush();
   assert.equal(t.calls.filter(c=>c.init.method==='POST').length,0,mode);
   assert.equal(t.r.canExecute(),false,mode);
  }
 });
 await scenario('non200_with_receipt_and_ordinary_observation_cannot_confirm_rejection',async()=>{
  const t=runtime(),post=await start(t),rejected=proof(t,'rejected'),id=t.r.journal().snapshot().identity;
  t.r.journal().observe(rejected,409,id);assert.equal(t.r.journal().snapshot().phase,'uncertain');
  t.r.journal().observe(null,404,id);assert.equal(t.r.journal().snapshot().phase,'uncertain');
  post.reject(Error('lost'));await flush();t.r.S.preview=preview();assert.equal(t.r.canExecute(),false);
  t.r.journal().observe(rejected,200,id);assert.equal(t.r.journal().snapshot().phase,'rejected');
 });
 await scenario('every_identity_mismatch_and_typed_result_error_stays_unknown',async()=>{
  const t=runtime();await start(t);const good=proof(t),id=t.r.journal().snapshot().identity;
  for(const changes of [{operation_id:crypto.randomUUID()},{actor_id:27},{environment:crypto.randomUUID()},
   {action:'stock_inbound'},{canonical_version:'v2'},{contract_version:'v2'},{target:{scope:'all'}},
   {request_fingerprint:'b'.repeat(64)},{result:{...good.result,changed:true}}]){
    t.r.journal().observe({...good,...changes},200,id);assert.equal(t.r.journal().snapshot().phase,'uncertain');
  }
 });
 await scenario('first_matched_ack_preserved_on_permission_errors_and_late_conflicts',async()=>{
  const t=runtime();await start(t);const good=proof(t),id=t.r.journal().snapshot().identity,j=t.r.journal();
  j.observe(good,200,id);const saved=JSON.stringify(j.snapshot());
  j.observe(null,403,id);j.observe({...good,state:'rejected',result:{}},200,id);
  j.observe({...good,actor_id:27},200,id);assert.equal(JSON.stringify(j.snapshot()),saved);
  const after=runtime(t.storage);assert.equal(after.r.journal().snapshot().phase,'applied');
 });
 await scenario('matched_ack_storage_failure_keeps_ack_but_blocks_next_write',async()=>{
  const t=runtime();await start(t);const good=proof(t),id=t.r.journal().snapshot().identity;
  t.storage.failWrite=true;t.r.journal().observe(good,200,id);
  t.r.journal().observe(null,401,id);assert.equal(t.r.journal().snapshot().phase,'applied');
  assert.equal(t.r.journal().pending(),true);
 });
 await scenario('late_old_ack_cannot_resolve_new_operation',async()=>{
  const t=runtime();await start(t);const old=proof(t),id=t.r.journal().snapshot().identity,j=t.r.journal();
  j.observe(old,200,id);
  const body={scope:'live',expect_changed:1,expected:preview().expected,note:'new'};
  await j.prepare(owner,body,()=>true);
  assert.equal(j.observe(old,200,id),null);assert.equal(j.snapshot().phase,'writing');
 });
 await scenario('scope_change_before_context_reply_sends_no_operation',async()=>{
  const t=runtime();t.r.S.preview=preview();const p=t.r.doApply();
  t.listeners.change({target:{name:'rpScope',value:'all'}});reply(t.calls[0],owner);await p;
  assert.equal(t.calls.length,1);assert.equal(t.r.journal().snapshot(),null);
 });
 for(const branch of ['zero','mismatch','none']){
  await scenario('unknown_'+branch+'_actual_DOM_button_recovers_exact_receipt',async()=>{
   const t=runtime(),post=await start(t),receipt=proof(t),id=t.r.journal().snapshot().identity.operation_id;
   post.reject(Error('response lost after commit'));await flush();
   if(branch==='zero'){
    t.r.doPreview();const previewCall=t.calls[t.calls.length-1];
    reply(previewCall,{...preview(),changed:0});await flush();assert.equal(t.r.S.preview.changed,0);
   }else if(branch==='mismatch'){
    t.r.S.preview={...preview(),scope:'all',expected:{...preview().expected,scope:'all'}};
   }else t.r.S.preview=null;
   // Invoke the real render function and inspect its DOM output, despite other flow mocks.
   t.r.renderExecute();
   const html=t.nodes.rpExecBody.innerHTML;
   const button=(html.match(/<button\b[^>]*>/g)||[]).find(b=>b.includes('data-action="check-operation"'));
   assert.ok(button,branch+' must expose exact-GET recovery');assert.ok(!/\bdisabled\b/.test(button));
   assert.equal(t.r.journal().pending(),true);assert.equal(t.r.canExecute(),false);
   const requests=t.calls.length;t.r.doApply();t.r.confirmUndo(100);
   assert.equal(t.calls.length,requests);assert.equal(t.ids.length,1);
   assert.equal(t.r.journal().snapshot().identity.operation_id,id);
   // Follow the button's actual bound click handler, not an invented recovery path.
   t.listeners.click({target:{closest:()=>({getAttribute:k=>k==='data-action'?'check-operation':null})}});
   assert.equal(t.calls[requests].url,'/api/admin/reprice/operations/context');
   t.r.renderExecute();assert.match(t.nodes.rpExecBody.innerHTML,/data-action="check-operation" disabled/);
   reply(t.calls[requests],owner);await flush();
   assert.equal(t.calls[requests+1].url,'/api/admin/reprice/operations/'+id);
   assert.equal(t.calls[requests+1].init.cache,'no-store');
   reply(t.calls[requests+1],{operation_receipt:receipt,response:{verdict:'confirmed'},original_http_status:200});await flush();
   assert.equal(t.r.journal().snapshot().phase,'applied');assert.equal(t.r.journal().pending(),false);
   assert.equal(t.calls.filter(c=>c.init.method==='POST').length,1);assert.equal(t.ids.length,1);
   t.r.renderExecute();assert.ok(!t.nodes.rpExecBody.innerHTML.includes('data-action="check-operation"'));
  });
 }
 await scenario('separate_tab_and_deleted_storage_have_no_uuid_recovery_guarantee',async()=>{
  const t=runtime();await start(t);const other=runtime();assert.equal(other.r.journal().snapshot(),null);
  other.r.S.preview=preview();assert.equal(other.r.canExecute(),true);
 });
 process.stdout.write(JSON.stringify({count:done.length,names:done}));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        harness=harness.replace('JOURNAL_SOURCE',json.dumps((ROOT/'mockups/shared/admin2/reprice-operation-journal.js').read_text(encoding='utf-8'),ensure_ascii=True))
        harness=harness.replace('TEMPLATE_SOURCE',json.dumps(script,ensure_ascii=True))
        harness=harness.replace('V2_VECTORS',json.dumps(v2_vectors,ensure_ascii=True)).replace('VECTORS',json.dumps(vectors,ensure_ascii=True))
        result=subprocess.run([node,'-'],input=harness,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['count'],20)


if __name__ == '__main__':
    unittest.main(verbosity=2)
