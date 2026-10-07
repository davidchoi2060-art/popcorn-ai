// Isolated operation/state regressions. Actual source DOM/layout is verified separately.
const assert=require('node:assert/strict');
const transport=require('../mockups/shared/admin-commerce-fulfillment-transport.js');
const flow=require('../mockups/shared/admin-commerce-fulfillment.js');
const returns=require('../mockups/shared/admin-commerce-physical-returns-transport.js');
const returnUI=require('../mockups/shared/admin-commerce-physical-returns.js');
const {harness,fixtureOrders}=require('./admin_commerce_orders_ui.cjs');
const ID='00000000-0000-4000-8000-000000000001',HASH='a'.repeat(64),order={order_no:'ORD-EXAMPLE-01',order_state:'접수',lines:[{line_id:'line-1',name:'격리 예시',qty:2}]};
const native=()=>({version:'commerce_fulfillment_http_v1',state:'confirmed',order_no:order.order_no,order_state:'접수',checked_at:1,order_revision:1,expected_order_basis:null,shipments:[],actions:Object.fromEntries(transport.actions.map(a=>[a,{allowed:false,reason:'source_unconnected'}]))});
const granted=()=>({...transport.current(native(),order.order_no),expected_order_basis:HASH,expected_policy_basis:HASH,actions:Object.fromEntries(transport.actions.map(a=>[a,{allowed:true,reason:null}]))});
const command=()=>({action:'prepare_shipment',expected_order_basis:HASH,expected_policy_basis:HASH,expected_order_revision:1,expected_order_state:'접수',shipment_id:null,expected_shipment_revision:null,lines:[{line_id:'line-1',qty:1}]});
const result=original=>({version:'commerce_fulfillment_http_v1',state:'confirmed',order_no:order.order_no,checked_at:2,operation_id:original.operation_id,request_basis:HASH,action:original.action,shipment_id:1,order_revision:2,shipment_revision:1,order_state:'접수',shipment_state:'준비',ready:false});
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const response=(data,status=200)=>({ok:status<400,status,headers:{get:()=> 'application/json'},json:async()=>data});
let groups=0;async function check(name,fn){await fn();groups++;console.log('PASS '+name);}
(async()=>{
 await check('exact current allowlist removes actor and fake policy, native missing policy keeps all writes blocked',async()=>{
   let posts=0;const dto={...native(),actor:{secret:'PRIVATE'},expected_policy_basis:HASH};const projected=transport.current(dto,order.order_no);assert.equal(projected.expected_policy_basis,null);assert(!JSON.stringify(projected).includes('PRIVATE'));
   const c=flow.controller({adapter:{mode:'live',current:async()=>projected,execute:async()=>posts++},newId:()=>ID});await c.connect(order);assert.equal(await c.submit(command()),false);assert.equal(posts,0);
   const html=flow.view(c.snapshot());for(const text of ['배송 준비 생성','조립 시작 · 완료','검수 합격 · 불합격','출고 준비 확인','실제 송장 저장','실제 인계 · 출고','해당 배송 완료','source_unconnected'])assert(html.includes(text));assert(!html.includes('MOCK'));
 });
 await check('fixed GET/POST/operation GET and exact original result reject wrong order, UUID, nonJSON and preserve backend code',async()=>{
   const calls=[],cmd={...command(),operation_id:ID},adapter=transport.create({fetch:async(url,options)=>{calls.push({url,options});return response(options.method==='POST'||url.includes('/operations/')?result(cmd):native());}});
   await adapter.current(order.order_no);await adapter.execute(order.order_no,cmd);await adapter.lookup(order.order_no,cmd);
   assert.deepEqual(calls.map(c=>c.options.method),['GET','POST','GET']);assert.equal(calls[2].url,'/api/admin/commerce/orders/'+order.order_no+'/fulfillment/operations/'+ID);
   for(const c of calls){assert.equal(c.options.credentials,'same-origin');assert.equal(c.options.cache,'no-store');assert.equal(c.options.redirect,'error');}assert.deepEqual(JSON.parse(calls[1].options.body),cmd);
   assert.throws(()=>transport.receipt({...result(cmd),operation_id:'bad'},order.order_no,cmd));assert.throws(()=>transport.receipt({...result(cmd),order_no:'OTHER'},order.order_no,cmd));
   await assert.rejects(transport.create({fetch:async()=>response({detail:{code:'physical_result_unconfirmed'}},503)}).current(order.order_no),/physical_result_unconfirmed/);
   await assert.rejects(transport.create({fetch:async()=>({...response(native()),headers:{get:()=> 'text/html'}})}).current(order.order_no),/JSON/);
 });
 await check('partial quantities validate before allocating UUID; mutable caller fields never alter original',async()=>{
   let ids=0,posted;const pending=deferred();const c=flow.controller({adapter:{mode:'mock',current:async()=>granted(),execute:async(no,cmd)=>{posted=cmd;return pending.promise;}},newId:()=>{ids++;return ID;}});await c.connect(order);
   for(const qty of [0,3,1.5,'1',true])assert.equal(await c.submit({...command(),lines:[{line_id:'line-1',qty}]}),false);assert.equal(ids,0);
   const input=command(),job=c.submit(input);input.lines[0].qty=2;assert.equal(ids,1);assert.equal(posted.lines[0].qty,1);assert(Object.isFrozen(posted.lines[0]));assert(c.guard().includes('처리 중'));assert.equal(await c.submit(command()),false);pending.resolve(result(posted));await job;assert.equal(c.snapshot().result.operation_id,ID);assert.equal(c.snapshot().current,null);assert.equal(await c.submit(command()),false);
 });
 await check('unknown preserves drafts and original; explicit original lookup only, 404 never unlocks new POST',async()=>{
   let posts=0,lookups=0,ids=0;const c=flow.controller({adapter:{mode:'mock',current:async()=>granted(),execute:async()=>{posts++;throw Error('network');},lookup:async(no,original)=>{lookups++;assert.equal(original.operation_id,ID);if(lookups===1)throw Object.assign(Error('not found'),{status:404});return result(original);}},newId:()=>{ids++;return ID;}});
   await c.connect(order);c.setDraft('prepare:line-1','1');await c.submit(command());assert.equal(c.snapshot().status,'unknown');assert.equal(c.snapshot().draft['prepare:line-1'],'1');assert.equal(c.discard(),false);assert.equal(await c.submit(command()),false);assert.equal(await c.refresh(),false);assert.equal(await c.lookup(),false);assert.equal(c.snapshot().status,'unknown');assert.equal(await c.lookup(),true);assert.equal(posts,1);assert.equal(ids,1);assert.equal(lookups,2);
 });
 await check('confirmed original receipt survives newer current-read failure; MOCK result remains visibly isolated',async()=>{
   let reads=0;const c=flow.controller({adapter:{mode:'mock',current:async()=>{if(++reads>1)throw Error('read failure');return granted();},execute:async(no,cmd)=>result(cmd)},newId:()=>ID});await c.connect(order);await c.submit(command());await c.refresh();assert.equal(c.snapshot().status,'error');assert.equal(c.snapshot().result.operation_id,ID);assert(flow.operation(c.snapshot()).includes('MOCK · 격리 예시 확정'));
 });
 await check('selection, reset, denial and dispose cancel late old success/error and wipe RAM',async()=>{
   for(const finish of ['success','denied']){const late=deferred();let denied=0;const c=flow.controller({adapter:{mode:'mock',current:async()=>granted(),execute:async()=>late.promise},newId:()=>ID,onDeny:()=>denied++});await c.connect(order);c.setDraft('qty','1');const job=c.submit(command());c.reset();await c.connect({...order,order_no:'OTHER'});if(finish==='success')late.resolve(result({...command(),operation_id:ID}));else late.reject(Object.assign(Error('denied'),{denied:true}));await job;assert.equal(c.snapshot().order.order_no,'OTHER');assert.equal(c.snapshot().original,null);assert.equal(denied,0);c.dispose();assert.equal(c.snapshot().order,null);assert.equal(await c.connect(order),false);}
   const c=flow.controller({adapter:{mode:'live',current:async()=>{throw Object.assign(Error('denied'),{denied:true});}},onDeny:()=>{}});await c.connect(order);assert.equal(c.snapshot().status,'denied');assert.equal(c.snapshot().order,null);
 });
 await check('physical-return default never fetches or invents success; structural steps and financial boundaries remain separate',async()=>{
   const adapter=returns.create();assert.equal(adapter.available,false);await assert.rejects(adapter.current(order.order_no),/unconnected/);const c=returnUI.controller({adapter});await c.connect(order);assert.equal(c.snapshot().status,'unavailable');const html=returnUI.view(c.snapshot());for(const text of ['반품 접수 확인','실제 회수','실물 입고','검수 · 판매 가능 수량','별도 재고복원','검수 저장만으로 재고가 늘지 않습니다','현금 환불을 실행하지 않습니다','source_unconnected'])assert(html.includes(text));assert.throws(()=>returns.createMock({}),/explicit/);
 });
 await check('selected order seam rejects stale metadata and PII without changing original subscriber metadata',()=>{
   const h=harness(),rows=fixtureOrders();let meta;h.controller.subscribeDetail(s=>meta=s);h.load(rows);h.select(0);assert.equal(h.controller.selectedFlowOrder(meta),null);const token=h.controller.beginDetail(rows[0].order_no);const detail={...rows[0],checked_at:1,basis_state:'unconfirmed',basis_id:null,approved_amount:'0',refunded_amount:'0',refundable_amount:'0',provider_environment:'unknown',verification_state:'unknown',provider_checked_at:null,actions:Object.fromEntries(['reconcile','cancel_payment','advance_fulfillment','return_stock'].map(a=>[a,{allowed:false,reason:'unconnected',expected_basis:null}])),private:'PRIVATE'};h.controller.receiveDetail(token,detail);const selected=h.controller.selectedFlowOrder(meta);assert(Object.isFrozen(selected.lines[0]));assert(!JSON.stringify(selected).includes('PRIVATE'));const old=meta;h.select(1);assert.equal(h.controller.selectedFlowOrder(old),null);
 });
 await check('server shipment/history allowlist validates actor, quantity and original identity without private fallback',()=>{
   const dto=native();dto.shipments=[{shipment_id:1,shipment_state:'준비',revision:1,ready:false,lines:[{line_id:'line-1',qty:1}],carrier:null,tracking_no:null,tracking_recorded_at:null,handed_off_at:null,delivered_at:null,history:[{operation_id:ID,action:'prepare_shipment',shipment_revision:1,order_revision:1,actor_id:7,event_kind:null,quantities:null,outcome:null,occurred_at:null,reference:null,ready:false,private:'PRIVATE'}]}];
   const safe=transport.current(dto,order.order_no);assert.equal(safe.shipments[0].history[0].actor_id,7);assert(!JSON.stringify(safe).includes('PRIVATE'));dto.shipments[0].history[0].actor_id='7';assert.throws(()=>transport.current(dto,order.order_no),/history/);
 });
 await check('registered dirty/busy navigation gate intercepts row, filter, back, paging, refresh and search before target handlers',()=>{
   const h=harness(),rows=fixtureOrders();h.load(rows);h.select(0);let capture,search,blocked=true,calls=0;
   h.root.addEventListener=(type,fn,useCapture)=>{assert.equal(useCapture,true);capture=fn;};h.root.removeEventListener=()=>{};
   h.element('aco-search').addEventListener=(type,fn,useCapture)=>{assert.equal(useCapture,true);search=fn;};h.element('aco-search').removeEventListener=()=>{};
   const stop=h.controller.registerDetailGuard(()=>{calls++;return !blocked;});
   for(const button of [{dataset:{orderIndex:'1'}},{dataset:{filter:'all'}},...['aco-back','aco-refresh','aco-prev','aco-next'].map(id=>({id,dataset:{}}))]){let stopped=false,prevented=false;capture({target:{closest:()=>button},preventDefault(){prevented=true;},stopImmediatePropagation(){stopped=true;}});assert(stopped&&prevented);}
   h.element('aco-search').value='other';let stopped=false;search({preventDefault(){},stopImmediatePropagation(){stopped=true;}});assert(stopped);assert.equal(h.element('aco-search').value,'');blocked=false;capture({target:{closest:()=>({id:'aco-refresh',dataset:{}})},preventDefault(){throw Error('should pass');},stopImmediatePropagation(){throw Error('should pass');}});assert.equal(calls,8);stop();
 });
 // Explicit isolated fixtures for the server's READONLY contract; never operating evidence.
 const clone=x=>JSON.parse(JSON.stringify(x)),ID2='00000000-0000-4000-8000-000000000002';
 const returnCurrent=()=>({version:'commerce_physical_return_storage_v1',state:'confirmed',order_no:order.order_no,checked_at:10,order_revision:3,expected_order_basis:HASH,expected_history_token:HASH,cases:[1,2].map((rid,i)=>({return_id:rid,revision:1,lines:[{return_line_id:rid,shipment_id:1,line_id:'line-1',claimed_qty:2,collected_qty:0,received_qty:0,inspected_qty:0,resellable_qty:0,restoration_consumed_qty:0,restoration_remaining_qty:0,restoration_unresolved:false}],history:[{operation_id:i?ID2:ID,action:'create_case',actor_id:7,return_revision:1,order_revision:i+2,lines:[{return_line_id:rid,qty:2}],occurred_at:null,reference:null,evidence:[]}]})),actions:{inspect:{allowed:false,reason:'source_unconnected'},restore:{allowed:false,reason:'source_unconnected'}}});
 const returnOriginal=(dto=returnCurrent(),index=0)=>({...dto.cases[index].history[0],return_id:dto.cases[index].return_id});
 const returnResult=(selected=returnOriginal())=>({version:'commerce_physical_return_storage_v1',state:'confirmed',pending_commit:false,pending:false,order_no:order.order_no,operation_id:selected.operation_id,action:selected.action,return_id:selected.return_id,order_revision:selected.order_revision,return_revision:selected.return_revision,lines:clone(selected.lines)});
 const returnAdapter=(extra={})=>returns.createMock({current:async()=>returnCurrent(),lookup:async(no,id)=>returnResult(id),execute:async()=>{throw Error('must never write');},...extra});
 await check('returns exact readonly GET options and original scope; execute cannot fetch',async()=>{
   const calls=[],adapter=returns.create({fetch:async(url,opts)=>{calls.push({url,opts});return response(url.includes('/operations/')?returnResult():returnCurrent());}});
   await adapter.current(order.order_no);await adapter.lookup(order.order_no,returnOriginal());await assert.rejects(adapter.execute(),/readonly/);
   assert.deepEqual(calls.map(c=>c.opts.method),['GET','GET']);assert.equal(calls[0].url,'/api/admin/commerce/orders/'+order.order_no+'/physical-returns');assert.equal(calls[1].url,calls[0].url+'/operations/'+ID);
   for(const c of calls){assert.equal(c.opts.credentials,'same-origin');assert.equal(c.opts.cache,'no-store');assert.equal(c.opts.redirect,'error');assert(!Object.hasOwn(c.opts,'body'));}
   await assert.rejects(adapter.current('../bad'),/invalid/);assert.equal(calls.length,2);
 });
 await check('returns current rejects partial, extra, duplicate, inconsistent, unsafe and granted DTOs; empty differs from missing',()=>{
   const good=returnCurrent();assert.equal(returns.current(good,order.order_no).cases[0].lines[0].collected_qty,0);const empty={...good,cases:[]};assert.equal(returns.current(empty,order.order_no).cases.length,0);
   const mutate=[d=>delete d.cases,d=>d.private='PRIVATE',d=>d.order_no='OTHER',d=>d.cases[1].return_id=1,d=>d.cases[1].lines[0].return_line_id=1,d=>d.cases[0].lines[0].collected_qty='0',d=>d.cases[0].lines[0].received_qty=1,d=>d.cases[0].lines[0].restoration_remaining_qty=1,d=>d.cases[0].lines[0].restoration_unresolved=0,d=>d.cases[0].revision=Number.MAX_SAFE_INTEGER+1,d=>d.cases[0].history[0].return_revision=2,d=>d.cases[0].history[0].actor_id='7',d=>d.cases[0].history[0].lines[0].return_line_id=2,d=>d.cases[1].history[0].operation_id=ID,d=>d.actions.inspect.allowed=true,d=>d.cases[0].history[0].reference='false time',d=>d.cases[0].history[0].evidence=[{return_line_id:2,kind:'inspect',actor_id:7,occurred_at:1,reference:'x'}]];
   for(const change of mutate){const d=clone(good);change(d);assert.throws(()=>returns.current(d,order.order_no),/invalid/);}
 });
 await check('returns original result binds case UUID action revisions and lines without shipping or pending success',()=>{
   const selected=returnOriginal(),good=returnResult();assert.equal(returns.result(good,order.order_no,selected).return_id,1);
   for(const [key,value] of [['order_no','OTHER'],['operation_id',ID2],['action','restore'],['return_id',2],['return_revision',2],['order_revision',3],['pending',true],['pending_commit',true],['shipment_state','완료']])assert.throws(()=>returns.result({...good,[key]:value},order.order_no,selected),/invalid/);
   assert.throws(()=>returns.result({...good,lines:[{return_line_id:1,qty:1}]},order.order_no,selected),/invalid/);
 });
 await check('returns case selection stays distinct for same order line; writes draft and storage are absent',async()=>{
   const c=returnUI.controller({adapter:returnAdapter()});await c.connect(order);assert.equal(c.snapshot().caseId,null);assert(c.selectCase(1));assert(c.selectOperation(ID));assert.equal(c.snapshot().original.return_id,1);assert(!c.selectOperation(ID2));assert(c.selectCase(2));assert.equal(c.snapshot().original,null);assert(c.selectOperation(ID2));assert.equal(c.snapshot().original.lines[0].return_line_id,2);assert.equal(c.setDraft('qty','1'),false);assert.equal(await c.submit(command()),false);await c.lookup();assert.equal(c.snapshot().result.return_id,2);c.reset();assert.equal(c.snapshot().result,null);assert.equal(c.snapshot().caseId,null);
 });
 await check('returns operation404 is unknown with immutable identity and no new operation; same lookup can resolve',async()=>{
   let calls=0;const c=returnUI.controller({adapter:returnAdapter({lookup:async(no,id)=>{if(++calls===1)throw Object.assign(Error('physical_return_not_found'),{status:404});return returnResult(id);}})});await c.connect(order);c.selectCase(1);c.selectOperation(ID);assert.equal(await c.lookup(),false);assert.equal(c.snapshot().status,'unknown');assert.equal(c.snapshot().original.operation_id,ID);assert(c.snapshot().message.includes('미실행 확정 아님'));assert.equal(c.selectCase(2),false);assert.equal(await c.refresh(),false);assert.equal(c.discard(),false);assert.equal(await c.submit(command()),false);assert.equal(await c.lookup(),true);assert.equal(calls,2);
 });
 await check('returns confirmed result survives current failure; current404 cannot become empty or stock zero',async()=>{
   let reads=0;const c=returnUI.controller({adapter:returnAdapter({current:async()=>{if(++reads>1)throw Object.assign(Error('not registered'),{status:404});return returnCurrent();}})});await c.connect(order);c.selectCase(1);c.selectOperation(ID);await c.lookup();await c.refresh();assert.equal(c.snapshot().status,'unavailable');assert.equal(c.snapshot().current,null);assert.equal(c.snapshot().result.operation_id,ID);const html=returnUI.view(c.snapshot());assert(html.includes('main 등록/운영 연결 미확인'));assert(!html.includes('확인된 반품 없음'));assert(html.includes('MOCK · 격리 예시 확정'));
 });
 await check('returns old current success error or denial cannot affect new order; active401 clears all RAM',async()=>{
   for(const finish of ['success','error','denied']){const late=deferred();let reads=0,denied=0;const c=returnUI.controller({adapter:returnAdapter({current:async(no)=>++reads===1?late.promise:{...returnCurrent(),order_no:no}}),onDeny:()=>denied++});const old=c.connect(order);await c.connect({...order,order_no:'OTHER'});finish==='success'?late.resolve(returnCurrent()):late.reject(Object.assign(Error(finish),finish==='denied'?{denied:true}:{}));await old;assert.equal(c.snapshot().order.order_no,'OTHER');assert.equal(c.snapshot().status,'ready');assert.equal(denied,0);c.dispose();assert.equal(c.snapshot().current,null);}
   let denied=0;const c=returnUI.controller({adapter:returnAdapter({lookup:async()=>{throw Object.assign(Error('401'),{denied:true});}}),onDeny:()=>denied++});await c.connect(order);c.selectCase(1);c.selectOperation(ID);await c.lookup();assert.equal(denied,1);for(const k of ['order','current','original','result','caseId'])assert.equal(c.snapshot()[k],null);
 });
 await check('returns late lookup success and401 ignored after case switch; dispose blocks late result and reconnect',async()=>{
   for(const finish of ['success','denied']){const late=deferred();let denied=0;const c=returnUI.controller({adapter:returnAdapter({lookup:async()=>late.promise}),onDeny:()=>denied++});await c.connect(order);c.selectCase(1);c.selectOperation(ID);const job=c.lookup();assert(c.selectCase(2));finish==='success'?late.resolve(returnResult()):late.reject(Object.assign(Error('401'),{denied:true}));await job;assert.equal(c.snapshot().caseId,2);assert.equal(c.snapshot().result,null);assert.equal(denied,0);}
   const late=deferred(),c=returnUI.controller({adapter:returnAdapter({current:async()=>late.promise})});const job=c.connect(order);c.dispose();late.resolve(returnCurrent());await job;assert.equal(c.snapshot().order,null);assert.equal(await c.connect(order),false);
 });
 await check('returns escaping history and null times keep approved steps disabled; no actor query or restore timestamp synthesis',async()=>{
   const d=returnCurrent();d.cases[0].history[0].action='restore';d.cases[0].history[0].evidence=[{return_line_id:1,kind:'inspect',actor_id:7,occurred_at:1,reference:'<script>PRIVATE</script>'}];const c=returnUI.controller({adapter:returnAdapter({current:async()=>d})});await c.connect(order);c.selectCase(1);const html=returnUI.view(c.snapshot());assert(!html.includes('<script>'));assert(html.includes('&lt;script&gt;'));assert(html.includes('발생 미확인'));assert.equal((html.match(/<button type="button" disabled>/g)||[]).length,5);assert(html.includes('조회 전용 · 모든 쓰기 비활성'));assert(!html.includes('shipment_state'));
 });
 await check('returns HTTP active denial precedes body; nonJSON and503 preserve failure without fake success',async()=>{
   for(const status of [401,403])await assert.rejects(returns.create({fetch:async()=>({...response({},status),json:()=>{throw Error('must not parse');}})}).current(order.order_no),e=>e.denied===true&&e.status===status);
   await assert.rejects(returns.create({fetch:async()=>({...response(returnCurrent()),headers:{get:()=> 'text/html'}})}).current(order.order_no),/JSON/);
   await assert.rejects(returns.create({fetch:async()=>response({detail:{code:'physical_return_unavailable'}},503)}).current(order.order_no),e=>e.status===503&&e.message==='physical_return_unavailable');
 });
 console.log(groups+' order-flow regression groups passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
