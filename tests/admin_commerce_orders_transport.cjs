// Actual adapter + actual renderer, deferred GET mocks; no auth/DB/provider IO.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const ui=require('../mockups/shared/admin-commerce-orders.js');
const transport=require('../mockups/shared/admin-commerce-orders-transport.js');
const {fixtureOrders,harness}=require('./admin_commerce_orders_ui.cjs');
const clone=x=>JSON.parse(JSON.stringify(x));
function adminRows(){return fixtureOrders().map(row=>({...row,checked_at:1791200000,basis_state:'unconfirmed',basis_id:null,approved_amount:row.payment_state==='confirmed'?row.total:'0',refunded_amount:'0',refundable_amount:row.payment_state==='confirmed'?row.total:'0',provider_environment:'unknown',verification_state:'unknown',provider_checked_at:null,actions:Object.fromEntries(['reconcile','cancel_payment','advance_fulfillment','return_stock'].map(key=>[key,{allowed:false,reason:'route_unavailable',expected_basis:null}]))}));}
function envelope(items=adminRows(),next=null){return {commerce_version:'commerce_v1',checked_at:1791200000,context:{state:'confirmed',binding_id:'11111111-1111-4111-8111-111111111111'},items,next_cursor:next};}
function detail(item=adminRows()[0]){const result=envelope();delete result.items;delete result.next_cursor;result.item=item;return result;}
function response(payload,status=200,type='application/json'){return {ok:status>=200&&status<300,status,headers:{get:()=>type},json:async()=>payload};}
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function setup(){
  const h=harness(),calls=[];
  const adapter=transport.mount(h.root,{fetch:(url,options)=>{const gate=deferred();calls.push({url,options,gate});return gate.promise;}});
  async function load(payload=envelope()){const job=adapter.refresh();calls.at(-1).gate.resolve(response(payload));assert.equal(await job,true);}
  return {...h,adapter,calls,load};
}
async function run(){let count=0;const check=async(name,fn)=>{await fn();++count;console.log('PASS '+name);};
await check('fixed same-origin GET options and list envelope provide real rows without PII',async()=>{
  const h=setup(),data=envelope();data.owner='PRIVATE';data.items[0].shipping={address:'PRIVATE'};data.items[0].provider_merchant='PRIVATE';
  await h.load(data);const call=h.calls[0];assert.equal(call.url,'/api/admin/commerce/orders?limit=20');
  assert.equal(call.options.method,'GET');assert.equal(call.options.credentials,'same-origin');assert.equal(call.options.cache,'no-store');assert.equal(call.options.redirect,'error');assert.deepEqual(call.options.headers,{Accept:'application/json'});assert(!Object.hasOwn(call.options,'body'));
  h.select(0);assert.equal(h.calls[1].url,'/api/admin/commerce/orders/ORD-EXAMPLE-01');
  h.calls[1].gate.resolve(response(detail(data.items[0])));await settle();assert(!h.element('aco-detail').innerHTML.includes('PRIVATE'));
});
await check('malformed envelope version/context/clock/cursor/amount/action/provider fails closed',async()=>{
  const bad=[];
  for(const edit of [v=>v.commerce_version='v2',v=>v.context.state='unconfirmed',v=>v.context.binding_id='not-a-uuid',v=>v.checked_at='1791200000',v=>v.next_cursor='?url=foreign',v=>delete v.next_cursor,v=>v.items={},v=>v.items[0].checked_at++,v=>v.items[0].approved_amount=0,v=>v.items[0].refunded_amount='1',v=>v.items[0].refundable_amount='01',v=>v.items[0].actions.reconcile.allowed=true,v=>v.items[0].provider_checked_at=v.checked_at+1,v=>{v.items[0].verification_state='confirmed';},v=>v.items.push(clone(v.items[0]))]){const value=envelope();edit(value);bad.push(value);}
  for(const value of bad){const h=setup(),job=h.adapter.refresh();h.calls[0].gate.resolve(response(value));assert.equal(await job,false);assert.match(h.element('aco-rows').innerHTML,/조회 실패/);assert(!h.element('aco-detail').innerHTML.includes('승인 확정'));assert(h.element('aco-next').disabled);}
});
await check('exact large balances stay strings and zero, missing or malformed metadata never fabricates evidence',async()=>{
  const row=adminRows()[0];row.payment_state='confirmed';row.checkout_state='paid';row.allocation_state='allocated';row.order_state='결제완료';row.approved_amount=row.total;row.refunded_amount='1';row.refundable_amount='9007199254740992';
  const projected=transport.envelope(detail(row),'detail',row.order_no).item;assert.equal(projected.refundable_amount,'9007199254740992');assert.equal(ui.adminProject(projected).approved_amount,'9007199254740993');
  for(const key of ['approved_amount','refunded_amount','refundable_amount','basis_state','actions','provider_environment','checked_at']){const missing=clone(row);delete missing[key];assert.throws(()=>transport.envelope(detail(missing),'detail',row.order_no));}
  assert.equal(ui.adminProject(adminRows()[1]).refundable_amount,'0');
});
await check('latest list wins; stale 401/403 or rejected old load cannot erase new scope',async()=>{
  for(const status of [401,403,503]){const h=setup(),old=h.adapter.refresh(),fresh=h.adapter.refresh();h.calls[1].gate.resolve(response(envelope()));assert.equal(await fresh,true);h.calls[0].gate.resolve(response({},status));assert.equal(await old,false);assert(h.element('aco-rows').innerHTML.includes('ORD-EXAMPLE-01'));assert.equal(h.calls[0].options.signal.aborted,true);}
  const h=setup(),old=h.adapter.refresh(),fresh=h.adapter.refresh();h.calls[1].gate.resolve(response(envelope()));await fresh;h.calls[0].gate.reject(Error('old network'));await old;assert(h.element('aco-rows').innerHTML.includes('ORD-EXAMPLE'));
});
await check('delayed JSON decoding is also generation checked for lists and detail selection',async()=>{
  const h=setup(),decode=deferred(),old=h.adapter.refresh();h.calls[0].gate.resolve({...response(null),json:()=>decode.promise});await settle();await h.load();decode.resolve(envelope([]));assert.equal(await old,false);assert(h.element('aco-rows').innerHTML.includes('ORD-EXAMPLE'));
  h.select(0);const detailDecode=deferred();h.calls.at(-1).gate.resolve({...response(null),json:()=>detailDecode.promise});await settle();h.select(1);h.calls.at(-1).gate.resolve(response(detail(adminRows()[1])));await settle();detailDecode.resolve(detail());await settle();assert(h.element('aco-detail').innerHTML.includes('ORD-EXAMPLE-02'));assert(!h.element('aco-detail').innerHTML.includes('ORD-EXAMPLE-01'));
});
await check('A to B detail race rejects old success/auth/network errors and never refocuses asynchronously',async()=>{
  for(const outcome of ['success','auth','network']){const h=setup();await h.load();h.select(0);const old=h.calls.at(-1);h.select(1);const fresh=h.calls.at(-1);fresh.gate.resolve(response(detail(adminRows()[1])));await settle();
    if(outcome==='success')old.gate.resolve(response(detail()));else if(outcome==='auth')old.gate.resolve(response({},403));else old.gate.reject(Error('old detail'));
    await settle();assert(h.element('aco-detail').innerHTML.includes('ORD-EXAMPLE-02'));assert(!h.element('aco-detail').innerHTML.includes('ORD-EXAMPLE-01'));assert.deepEqual(h.root.focusCalls,['aco-detail-title','aco-detail-title']);assert(old.options.signal.aborted);
    h.click({id:'aco-back',dataset:{},disabled:false});assert.equal(h.root.focused,'order-1');assert(!h.classes.has('show-detail'));
  }
});
await check('current list or detail 401/403 wipes rows/detail/selection/cursor then retry starts first page',async()=>{
  for(const route of ['list','detail'])for(const status of [401,403]){const h=setup();await h.load(envelope(adminRows(),'opaqueCursor'));h.select(1);h.calls.at(-1).gate.resolve(response(detail(adminRows()[1])));await settle();
    let job;if(route==='list'){job=h.adapter.next();}else{h.select(0);}
    h.calls.at(-1).gate.resolve(response({private:'PRIVATE'},status));if(job)await job;await settle();
    assert(!h.element('aco-rows').innerHTML.includes('ORD-EXAMPLE'));assert(!h.element('aco-detail').innerHTML.includes('승인 확정'));assert.match(h.element('aco-connection').textContent,/권한 확인/);assert(h.element('aco-prev').disabled&&h.element('aco-next').disabled);assert(!h.classes.has('show-detail'));
    const retry=h.adapter.retry();assert.equal(h.calls.at(-1).url,'/api/admin/commerce/orders?limit=20');h.calls.at(-1).gate.resolve(response(envelope([])));assert.equal(await retry,true);
  }
});
await check('refresh while detail pending prevents old 401 or success from clearing or repopulating page',async()=>{
  for(const status of [200,401]){const h=setup();await h.load();h.select(0);const old=h.calls.at(-1);await h.load(envelope([]));old.gate.resolve(response(status===200?detail():{},status));await settle();assert.match(h.element('aco-rows').innerHTML,/조회 결과 주문 없음/);assert(!h.element('aco-detail').innerHTML.includes('ORD-EXAMPLE'));}
});
await check('next previous re-fetch opaque cursors; refresh resets first page and no global total is invented',async()=>{
  const h=setup();await h.load(envelope(adminRows(),'opaque_A'));assert(h.element('aco-prev').disabled);assert(!h.element('aco-next').disabled);
  const next=h.adapter.next();assert.equal(h.calls.at(-1).url,'/api/admin/commerce/orders?limit=20&cursor=opaque_A');assert(h.element('aco-next').disabled&&h.element('aco-prev').disabled);h.calls.at(-1).gate.resolve(response(envelope([adminRows()[1]],'opaque_B')));await next;
  const previous=h.adapter.previous();assert.equal(h.calls.at(-1).url,'/api/admin/commerce/orders?limit=20');h.calls.at(-1).gate.resolve(response(envelope(adminRows(),'opaque_A')));await previous;assert(h.element('aco-prev').disabled);
  const refresh=h.adapter.refresh();assert.equal(h.calls.at(-1).url,'/api/admin/commerce/orders?limit=20');h.calls.at(-1).gate.resolve(response(envelope([],null)));await refresh;assert(h.element('aco-next').disabled);assert.match(h.element('aco-count').textContent,/전체 주문 건수 미확인/);
});
await check('network/non-JSON/503 errors clear earlier rows and are never empty success or cached fallback',async()=>{
  for(const kind of ['network','nonjson','503']){const h=setup();await h.load();const job=h.adapter.refresh();assert(!h.element('aco-rows').innerHTML.includes('ORD-EXAMPLE'));if(kind==='network')h.calls.at(-1).gate.reject(Error('PRIVATE'));else h.calls.at(-1).gate.resolve(response(envelope(),kind==='503'?503:200,kind==='nonjson'?'text/html':'application/json'));assert.equal(await job,false);assert.match(h.element('aco-rows').innerHTML,/조회 실패/);assert(!h.element('aco-rows').innerHTML.includes('주문 없음'));assert(!h.element('aco-connection').textContent.includes('PRIVATE'));}
});
await check('wrong/null/malformed selected detail clears evidence without turning current list into success-empty',async()=>{
  for(const value of [detail(adminRows()[1]),detail(null),detail({...adminRows()[0],total:'-1'})]){const h=setup();await h.load();h.select(0);h.calls.at(-1).gate.resolve(response(value));await settle();assert.match(h.element('aco-detail').innerHTML,/상세를 확인할 수 없습니다/);assert(!h.element('aco-detail').innerHTML.includes('자금 환불 완료'));assert(h.element('aco-rows').innerHTML.includes('ORD-EXAMPLE'));}
});
await check('filter-invalidated detail auth is stale and cannot wipe visible current list',async()=>{
  const h=setup();await h.load();h.select(0);const old=h.calls.at(-1);h.filter('refund');old.gate.resolve(response({},401));await settle();assert(h.element('aco-rows').innerHTML.includes('ORD-EXAMPLE-02'));assert(!h.element('aco-connection').textContent.includes('권한 확인'));
});
await check('allowed admin capabilities still leave every business action disabled and hide private extras',async()=>{
  const row=adminRows()[1];row.total='10';row.approved_amount='10';row.refundable_amount='10';row.basis_state='confirmed';row.basis_id='a'.repeat(64);row.provider_environment='test';row.provider_checked_at=row.checked_at;row.verification_state='confirmed';
  for(const action of Object.values(row.actions)){action.allowed=true;action.reason=null;action.expected_basis=row.basis_id;}
  row.owner_key='PRIVATE';row.raw_proof={secret:'PRIVATE'};row.provider_merchant='PRIVATE';const safe=transport.envelope(detail(row),'detail',row.order_no).item;assert(!JSON.stringify(safe).includes('PRIVATE'));
  const h=setup();await h.load(envelope([row]));h.select(0);h.calls.at(-1).gate.resolve(response(detail(row)));await settle();assert.equal((h.element('aco-detail').innerHTML.match(/<button type="button" disabled>/g)||[]).length,3);assert.match(h.element('aco-detail').innerHTML,/실물 회수 · 미확인/);
});
await check('dispose invalidates in-flight responses and buttons and transport uses no persistence or cursor decoding',async()=>{
  const h=setup(),job=h.adapter.refresh();h.adapter.dispose();h.calls[0].gate.resolve(response(envelope()));assert.equal(await job,false);assert.match(h.element('aco-rows').innerHTML,/연결 필요/);assert(h.element('aco-next').disabled);
  const source=fs.readFileSync(path.join(__dirname,'../mockups/shared/admin-commerce-orders-transport.js'),'utf8');assert(!/localStorage|sessionStorage|pushState|replaceState|atob\(|btoa\(|XMLHttpRequest|POST|provider_merchant|owner_key/.test(source));
});
console.log(count+' commerce transport regression groups passed');}
module.exports={adminRows,envelope,detail,response};if(require.main===module)run().catch(error=>{console.error(error);process.exitCode=1;});
