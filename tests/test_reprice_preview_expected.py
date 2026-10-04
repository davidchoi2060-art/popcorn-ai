"""Actual selected routes/Pydantic and actual template JS; offline mocks only."""
import ast
from copy import deepcopy
from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from api.reprice_preview_expected import canonical_basis, make_expected, InvalidPreviewBasis, _number
from tests.test_reprice_write_lock_order import (
    ROOT, Database, routes, product, u4_module_baseline, digest, _LOCK_PRODUCTS_SQL,
)


class PreviewExpectedTests(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        self.env = routes()
        self.env.update(engine=self.db, current_operator=self.db.operator,
                        current_operator_id=self.db.actor, _log=self.db.log)

    def preview(self, scope='all'):
        return self.env['preview'](scope)

    def body(self, preview):
        return self.env['ApplyBody'](scope=preview['scope'], expect_changed=preview['changed'],
                                     expected=preview['expected'], note=' old note ')

    def writes(self):
        return [q for q, _ in self.db.calls if q.startswith(('UPDATE ', 'INSERT ', 'DELETE '))
                and not q.startswith('INSERT INTO admin_operation_receipts')]

    def reject(self, body, status=409):
        with self.assertRaises(HTTPException) as caught:
            self.env['apply'](body)
        self.assertEqual(caught.exception.status_code, status)
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.db.histories, [])
        self.assertEqual(self.db.logs, [])

    def test_full_module_after_exact_u4_removal_equals_accepted_policy_c_source_ast(self):
        restored = u4_module_baseline(ast.parse((ROOT/'api/admin_reprice.py').read_text(encoding='utf-8')))
        self.assertEqual(digest(restored), '460a054c3c60178bf1838052f225f6eecf171672c09bf8e985e62b658ba49032')
        # All CSS, layout and non-script content remain byte-identical.
        template = (ROOT/'templates/admin/reprice.html.j2').read_bytes()
        self.assertEqual(hashlib.sha256(template.split(b'<script>')[0]).hexdigest(),
                         'e51e90a419d0688ec03cc21b4e02a41c32d097d916f9ec3f8e7901932008e2ce')

    def test_real_required_expected_model_http_validation_and_scope_boundary_no_tx(self):
        app = FastAPI()
        app.get('/preview')(self.env['preview'])
        app.post('/apply')(self.env['apply'])
        with TestClient(app) as client:
            preview = client.get('/preview?scope=all').json()
            valid = self.body(preview).model_dump()
            mutations = [
                lambda b: b.pop('expected'), lambda b: b.update(expected=None),
                lambda b: b.update(expected='bad'),
                lambda b: b['expected'].pop('fingerprint'),
                lambda b: b['expected'].update(version='v2'),
                lambda b: b['expected'].update(scope='invalid'),
                lambda b: b['expected'].update(fingerprint='a'*63),
                lambda b: b['expected'].update(fingerprint='a'*64+'\n'),
                lambda b: b['expected'].update(fingerprint='A'*64),
                lambda b: b['expected'].update(fingerprint=123),
                lambda b: b['expected'].update(extra=True),
            ]
            for mutate in mutations:
                body = deepcopy(valid); mutate(body)
                self.assertEqual(client.post('/apply', json=body).status_code, 422, body)
            mismatch = deepcopy(valid); mismatch['expected']['scope'] = 'live'
            self.assertEqual(client.post('/apply', json=mismatch).status_code, 409)
            self.assertEqual(self.db.begins, 0)
            self.assertEqual(self.writes(), [])
            response = client.post('/apply', json=valid)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['changed'], 4)
            self.assertEqual(self.db.calls[0][0], 'SELECT pg_catalog.pg_advisory_xact_lock_shared(:namespace,:key)')
            self.assertEqual((self.db.commits, self.db.rollbacks), (1, 0))

    def test_same_count_changes_in_every_raw_basis_field_reject_before_product_lock(self):
        mutations = {
            'product_code': 1000, 'product_name': 'renamed', 'part_type': 'CPU',
            'purchase_price': 10001, 'sale_price': 9001, 'status': '품절',
            'stock_qty': 8, 'locked_fields': ['name'], 'category_id': 44,
        }
        for field, value in mutations.items():
            self.setUp(); preview = self.preview(); body = self.body(preview)
            self.db.products[102][field] = value
            self.assertEqual(self.preview()['changed'], preview['changed'], field)
            self.reject(body)
            self.assertFalse(any(q == _LOCK_PRODUCTS_SQL for q, _ in self.db.calls), field)
            self.assertEqual(self.db.actor_calls, 0)

    def test_policy_same_count_price_and_small_rate_drift_are_bound_to_original_preview(self):
        for field, value in (('fee', .12), ('fee', .0201), ('margin', .15), ('margin', .0301)):
            self.setUp(); self.db.products.pop(105)
            preview = self.preview(); body = self.body(preview)
            setattr(self.db, field, value)
            self.assertEqual(self.preview()['changed'], preview['changed'])
            self.reject(body)
        self.setUp(); self.db.categories = [(7, None), (8, 7)]
        self.db.policies = [(7, .05)]; self.db.products[102]['category_id'] = 8
        preview = self.preview(); body = self.body(preview)
        self.db.policies = [(7, .15)]
        self.assertEqual(self.preview()['changed'], preview['changed'])
        self.reject(body)

    def test_unused_effective_margin_map_drift_conservatively_rejects_same_display_and_count(self):
        old = self.preview(); body = self.body(old)
        self.db.categories = [(44, None)]; self.db.policies = [(44, .5)]
        new = self.preview()
        self.assertEqual({k: v for k, v in old.items() if k != 'expected'},
                         {k: v for k, v in new.items() if k != 'expected'})
        self.reject(body)

    def test_not_displayed_example_and_cap_excluded_and_unchanged_rows_are_bound(self):
        for field, value in (('stock_qty', 8), ('product_name', 'outside examples')):
            self.setUp(); self.env['MAX_APPLY'] = 3
            self.db.products = {pc: product(pc, 9000) for pc in range(101, 131)}
            preview = self.preview(); body = self.body(preview)
            self.assertNotIn(130, [r['product_code'] for r in preview['examples']['up']])
            self.db.products[130][field] = value
            self.assertEqual(self.preview()['changed'], 30)
            self.reject(body)
            self.assertFalse(any(q == _LOCK_PRODUCTS_SQL for q, _ in self.db.calls))
        self.setUp(); preview = self.preview(); body = self.body(preview)
        self.db.products[105]['stock_qty'] = 8  # price already agrees, not a target
        self.reject(body)

    def test_post_lock_full_basis_drift_rejects_without_locking_extra_products(self):
        for mutate in (
            lambda d: d.products[104].update(stock_qty=8),
            lambda d: d.products[105].update(product_name='unchanged-price row'),
            lambda d: setattr(d, 'categories', [(44, None)]),
        ):
            self.setUp(); self.env['MAX_APPLY'] = 3
            preview = self.preview(); body = self.body(preview)
            self.db.after_lock = mutate
            self.reject(body)
            self.assertEqual([p['codes'] for q, p in self.db.calls if q == _LOCK_PRODUCTS_SQL], [[101, 102, 103]])
            self.assertEqual((self.db.commits, self.db.rollbacks), (1, 0))
            self.assertEqual(next(iter(self.db.receipts.values()))['state'],'rejected')

    def test_null_and_lock_list_shape_and_order_are_distinct_basis(self):
        for change in (
            lambda r: r.update(sale_price=None),
            lambda r: r.update(locked_fields=None),
            lambda r: r.update(locked_fields=['name']),
        ):
            preview = self.preview(); body = self.body(preview)
            change(self.db.products[102]); self.reject(body); self.setUp()
        self.db.products[102]['locked_fields'] = ['name', 'stock_qty']
        preview = self.preview(); body = self.body(preview)
        self.db.products[102]['locked_fields'].reverse()
        self.reject(body)

    def test_value_A_B_A_remains_same_expected_and_is_not_a_revision_proof(self):
        def v1_token():
            rows=[deepcopy(r) for _,r in sorted(self.db.products.items()) if r['purchase_price'] is not None and r['purchase_price']>0]
            return self.env['_preview_plan'](rows,'all',self.db.fee,self.db.margin,{})[1]
        old=v1_token()
        self.db.products[102]['purchase_price'] = 14000
        self.assertNotEqual(v1_token(),old)
        self.db.products[102]['purchase_price'] = 10000
        self.db.margin = .15; self.db.margin = .03
        self.assertEqual(v1_token(),old)
        self.assertEqual(old['version'],'reprice_basis_v1')
        body=self.env['ApplyBody'](scope='all',expect_changed=4,expected=old)
        self.reject(body)
        self.assertFalse(any(q == _LOCK_PRODUCTS_SQL for q,p in self.db.calls))

    def test_nonfinite_and_missing_or_malformed_raw_basis_fail_before_classification_or_writes(self):
        for value in (float('nan'), float('inf'), -float('inf'), Decimal('NaN'), Decimal('Infinity')):
            self.setUp(); self.db.fee = value
            with self.assertRaises(HTTPException) as caught: self.preview()
            self.assertEqual(caught.exception.status_code, 409)
            self.assertEqual(self.writes(), [])
        for mutate in (lambda r: r.pop('stock_qty'), lambda r: r.update(locked_fields=True),
                       lambda r: r.update(product_code=True), lambda r: r.update(purchase_price=True)):
            self.setUp(); mutate(self.db.products[102])
            with self.assertRaises(HTTPException) as caught: self.preview()
            self.assertEqual(caught.exception.status_code, 409)
            self.assertEqual(self.writes(), [])

    def test_explicit_numeric_normalization_without_rounding_or_decimal_context_dependence(self):
        for value in (12000, 12000.0, Decimal('12000.000')):
            self.assertEqual(_number(value), ['number', 0, '12', 3])
        for value in (0, -0.0, Decimal('-0.000')):
            self.assertEqual(_number(value), ['number', 0, '0', 0])
        with localcontext() as ctx:
            ctx.prec = 2
            self.assertEqual(_number(Decimal('123456789.1234000')), ['number', 0, '1234567891234', -4])
        self.assertNotEqual(_number(.0201), _number(.02))
        with self.assertRaises(InvalidPreviewBasis): _number(True)
        old = self.preview()['expected']
        for r in self.db.products.values():
            if r['purchase_price'] is not None: r['purchase_price'] = Decimal(str(r['purchase_price']))
        self.assertEqual(self.preview()['expected'], old)

    def test_object_map_key_order_stable_but_row_and_plan_order_not_normalized_away(self):
        rows = [product(1, 9000), product(2, 13000)]
        mmap = {7: .05, 8: .03}
        def token(rows, mmap):
            basis = canonical_basis(scope='all', rows=rows, fee=.02, margin=.03, mmap=mmap, max_apply=1)
            c = self.env['_classify'](rows, .02, .03, mmap)
            return make_expected(basis, c, scope='all', max_apply=1)
        a = token(rows, mmap)
        self.assertEqual(a, token([dict(reversed(list(r.items()))) for r in rows], {8: .03, 7: .05}))
        self.assertNotEqual(a, token(list(reversed(rows)), mmap))
        self.assertEqual(self.env['_classify'](rows, .02, .03)['up'][0]['product_code'], 1)
        self.assertEqual(self.env['_classify'](rows, .02, .03)['down'][0]['product_code'], 2)

    def test_actual_template_js_expected_payload_409_and_failed_late_preview_paths(self):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node required for actual template JS regression')
        script = (ROOT/'templates/admin/reprice.html.j2').read_text(encoding='utf-8').partition('<script>')[2].partition('</script>')[0]
        script = script.replace('{{ links_json | safe }}', '{}').replace('{{ rounds_json | safe }}', '[]')
        self.assertEqual(script.count('  boot();'), 1)
        script = script.replace('  boot();', '''window.__rp = {S:S, canExecute:canExecute, doPreview:doPreview,
doApply:doApply, checkOperation:checkOperation, journal:function(){return J;}, bind:bind, renderExecute:renderExecute};
renderAll = function () {};
  boot();''')
        harness = r'''
const vm = require('node:vm'), assert = require('node:assert/strict');
const source = SOURCE, journalSource = JOURNAL;
const completed = [];
function runtime() {
  const calls = [], nodes = {}, listeners = {}, timers = [];
  const ctx = {console, Promise, setTimeout:f=>timers.push(f), location:{reload(){}},
    window:{Admin2Shell:{canWrite:()=>true,meReady:Promise.resolve()},TextEncoder,crypto:require('node:crypto').webcrypto,sessionStorage:{getItem(k){return this[k]??null;},setItem(k,v){this[k]=v;}}},
    document:{readyState:'loading', addEventListener:(n,f)=>listeners[n]=f,
      getElementById:id=>nodes[id]||(nodes[id]={innerHTML:''})}};
  ctx.fetch=(url,init)=>new Promise((resolve,reject)=>calls.push({url,init,resolve,reject}));
  vm.runInNewContext(journalSource,ctx);
  vm.runInNewContext(source,ctx);
  return {r:ctx.window.__rp,calls,nodes,listeners,timers};
}
const flush = async()=>{for(let i=0;i<10;i++) await Promise.resolve();};
const serverContext={contract_version:'admin_operation_v1',canonical_version:'reprice_request_v1',actor_id:21,environment:'3c88fbc4-091a-44ea-bc0f-1192de0ca173',action:'reprice_apply'};
const postReady=async(t,index)=>{reply(t.calls[index],serverContext);for(let i=0;i<1000&&!t.calls[index+1];i++)await new Promise(setImmediate);assert.ok(t.calls[index+1]);return t.calls[index+1];};
const receipt=(call,state='applied')=>{const b=JSON.parse(call.init.body);return {...b.operation_context,operation_id:b.operation_id,target:{scope:b.scope},request_fingerprint:b.request_fingerprint,state,receipt_id:'8621c23b-5887-4abc-97ef-8268a5d1be21',result:state==='applied'?{log_id:81,changed:1,up:1,down:0,locked:0,dropped:0}:{}};};
const preview = scope=>({scope,changed:1,expected:{version:'reprice_basis_v2',scope,fingerprint:'a'.repeat(64)}});
const reply = (call,value,status=200)=>call.resolve({ok:status===200,status,clone(){return this;},json:()=>Promise.resolve(value)});
const scope = (t,value)=>t.listeners.change({target:{name:'rpScope',value}});
async function scenario(name,fn){await fn(); completed.push(name);}
(async()=>{
 await scenario('missing_expected_no_POST',async()=>{
   const t=runtime(); t.r.S.preview={scope:'live',changed:1}; t.r.doApply();
   assert.equal(t.r.canExecute(),false); assert.equal(t.calls.length,0);
 });
 await scenario('real_preview_exact_expected_POST_and_success',async()=>{
   const t=runtime(); t.r.doPreview(); assert.equal(t.r.canExecute(),false);
   reply(t.calls[0],preview('live')); await flush(); assert.equal(t.r.canExecute(),true);
   t.r.doApply(); const post=await postReady(t,1),sent=JSON.parse(post.init.body);
   assert.deepEqual(sent.expected,preview('live').expected); assert.equal(sent.expect_changed,1);
   assert.equal(t.r.canExecute(),false); t.r.doPreview(); assert.equal(t.calls.length,3);
    reply(post,{verdict:'done',operation_receipt:receipt(post)}); await flush();
   assert.equal(t.r.canExecute(),false); assert.equal(t.timers.length,1);
 });
 await scenario('409_invalidates_and_displays_then_requires_new_preview',async()=>{
   const t=runtime(); t.r.S.preview=preview('live'); t.r.doApply();
   const post=await postReady(t,0);reply(post,{detail:'basis changed'},409); await flush();
   assert.equal(t.r.S.preview,null); assert.equal(t.r.canExecute(),false);
   t.r.renderExecute(); assert.match(t.nodes.rpExecBody.innerHTML,/rp-safetybox/);
   t.r.doApply(); assert.equal(t.calls.length,2);
    t.r.doPreview(); reply(t.calls[2],preview('live')); await flush();
    assert.equal(t.r.canExecute(),false);
    t.r.checkOperation();reply(t.calls[3],serverContext);await flush();
    reply(t.calls[4],{operation_receipt:receipt(post,'rejected'),response:{detail:'basis changed'},original_http_status:409});await flush();
    assert.equal(t.r.S.preview,null);t.r.doPreview();reply(t.calls[5],preview('live'));await flush();
    assert.equal(t.r.canExecute(),true);
 });
 await scenario('failed_refresh_clears_old_preview',async()=>{
   const t=runtime(); t.r.S.preview=preview('live'); t.r.doPreview();
   assert.equal(t.r.S.preview,null); t.calls[0].reject(new Error('offline')); await flush();
   assert.equal(t.r.canExecute(),false); assert.equal(t.r.S.preview,null);
 });
 await scenario('scope_round_trip_does_not_reuse_preview',async()=>{
   const t=runtime(); t.r.S.preview=preview('live'); scope(t,'all'); scope(t,'live');
   assert.equal(t.r.S.preview,null); assert.equal(t.r.canExecute(),false);
 });
 await scenario('late_old_success_cannot_replace_new_preview',async()=>{
   const t=runtime(); t.r.doPreview(); scope(t,'all'); t.r.doPreview();
   reply(t.calls[1],preview('all')); await flush(); reply(t.calls[0],preview('live')); await flush();
   assert.equal(t.r.S.preview.scope,'all'); assert.equal(t.r.canExecute(),true);
 });
 await scenario('late_old_failure_cannot_clear_new_preview',async()=>{
   const t=runtime(); t.r.doPreview(); scope(t,'all'); t.r.doPreview();
   reply(t.calls[1],preview('all')); await flush(); t.calls[0].reject(new Error('late')); await flush();
   assert.equal(t.r.S.preview.scope,'all'); assert.equal(t.r.S.previewErr,null);
 });
 await scenario('late_round_trip_response_cannot_reenable_execution',async()=>{
   const t=runtime(); t.r.doPreview(); scope(t,'all'); scope(t,'live');
   reply(t.calls[0],preview('live')); await flush(); assert.equal(t.r.canExecute(),false);
 });
 await scenario('wrong_scope_or_malformed_expected_preview_rejected',async()=>{
   for(const p of [{scope:'live',changed:1},preview('all'),
      {...preview('live'),expected:{...preview('live').expected,fingerprint:'A'.repeat(64)}},
      {...preview('live'),expected:{...preview('live').expected,fingerprint:'a'.repeat(64)+'\n'}}]){
     const t=runtime(); t.r.doPreview(); reply(t.calls[0],p); await flush();
     assert.equal(t.r.S.preview,null); assert.equal(t.r.canExecute(),false); assert.ok(t.r.S.previewErr);
   }
 });
 await scenario('preview_busy_prevents_apply_and_duplicate_preview',async()=>{
   const t=runtime(); t.r.S.preview=preview('live'); t.r.doPreview(); t.r.doApply(); t.r.doPreview();
   assert.equal(t.calls.length,1); assert.equal(t.r.canExecute(),false);
 });
 await scenario('late_old_success_while_new_preview_busy_is_ignored',async()=>{
   const t=runtime(); t.r.doPreview(); scope(t,'all'); t.r.doPreview();
   reply(t.calls[0],preview('live')); await flush();
   assert.equal(t.r.S.previewBusy,true); assert.equal(t.r.S.preview,null);
   reply(t.calls[1],preview('all')); await flush(); assert.equal(t.r.canExecute(),true);
 });
 process.stdout.write(JSON.stringify({scenarios:completed.length,names:completed}));
})().catch(e=>{console.error(e);process.exitCode=1;});
'''.replace('SOURCE',json.dumps(script,ensure_ascii=True)).replace('JOURNAL',json.dumps((ROOT/'mockups/shared/admin2/reprice-operation-journal.js').read_text(encoding='utf-8'),ensure_ascii=True))
        result = subprocess.run([node, '-'], input=harness, capture_output=True, text=True,
                                encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['scenarios'], 11)


if __name__ == '__main__':
    unittest.main(verbosity=2)
