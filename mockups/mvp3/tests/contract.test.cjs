const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{webcrypto}=require('node:crypto');
const M=require('../live-model.js'),A=require('../api-client.js'),{createFlow,JOURNAL_KEY,validPending}=require('../live-flow.js');
const ID='11111111-1111-4111-8111-111111111111',QID='22222222-2222-4222-8222-222222222222',BIND='a'.repeat(64);
const talk={usages:['게임','영상 편집'],budget_won:1500000,budget_bound:'이하',game:{names:['검증용 게임'],resolution:'1440p'}};
const product={product_code:101,name:'검증용 PC',price:1430000,price_src:'등록 판매가',spec:{cpu:'검증용 CPU',gpu:'검증용 GPU',ram_gb:32,ssd_gb:1024,vram_gb:8,cpu_mt:999,gpu_idx:999},reasons:['조건에 맞는 등록 상품'],tag:'추천'};
const reco={ok:true,card_sets:[{kind:'sold',usage:'게임',items:[product,{...product,product_code:102,name:'대안 PC'}]},{kind:'sold',usage:'영상 편집',items:[]}],needs:[],assumed:[]};
const parsed={ok:true,state:talk,chat_flow:{step:2},answer:'게임 성능 조건 안내',reply:'해상도도 알려주세요.',sources:[{kind:'own',label:'게임 자료'},{kind:'web',label:'참고 페이지',url:'https://example.invalid/game'}],answer_notice:'예전 안내',pc_related:true,missing:[]};
const saved={ok:true,quote:{id:QID,product,state:talk,saved_at:'2026-10-03T09:00:00+00:00'}};
function storage(){const map=new Map();return {getItem:k=>map.get(k)??null,setItem:(k,v)=>map.set(k,v),removeItem:k=>map.delete(k),map};}
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function response(data,status=200,headers={}){return {ok:status>=200&&status<300,status,json:async()=>data,headers:{get:key=>headers[key]??null}};}
function client(fetchImpl,extra={}){return A.createClient({fetchImpl,storage:storage(),cryptoImpl:webcrypto,...extra});}
function harness(extra={},sessionStorage=storage()){
 const api={parse:async()=>parsed,recommend:async()=>reco,prepareSave:async()=>BIND,saveQuote:async()=>saved,listSaved:async()=>({ok:true,quotes:[],has_more:false}),...extra};
 const flow=createFlow(api,{uuid:()=>ID,sessionStorage});flow.reset();return {flow,api,sessionStorage};
}
async function selected(h){await h.flow.submit('예산 150만원으로 추천');h.flow.select(0);h.flow.navigate('final');return h;}
test('live HTML only loads live modules and same-origin connections',()=>{
 const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
 assert.match(html,/connect-src 'self'/);assert.match(html,/maxlength="300"/);assert.doesNotMatch(html,/src="(?:fixtures|model)\.js"|connect-src 'none'|auth\.js/);
 assert.doesNotMatch(fs.readFileSync(path.join(__dirname,'../app.js'),'utf8'),/MVP3Fixtures|MVP3Model|1490000|\.gpus|swap\/apply/);
});
test('object specs retain only public CPU GPU RAM SSD VRAM and exclude nested internal fields',()=>{
 const p=M.product(product);assert.deepEqual(p.spec,{cpu:'검증용 CPU',gpu:'검증용 GPU',ram_gb:32,ssd_gb:1024,vram_gb:8});
 assert.equal(JSON.stringify(p).includes('gpu_idx'),false);assert.equal(JSON.stringify(p).includes('cpu_mt'),false);
 assert.deepEqual(M.publicSpec({cpu:{name:'private'},gpu:'GPU',ssd_gb:-1,ram_gb:'32',nested:{email:'private'}}),{gpu:'GPU'});
 assert.deepEqual(M.specRows(p.spec)[2],['메모리','32GB']);assert.match(M.specText(p.spec),/저장장치 1024GB/);
});
test('string spec stays text; invalid price remains unknown rather than zero',()=>{
 assert.equal(M.product({...product,spec:'문자열 사양'}).spec,'문자열 사양');
 for(const price of [undefined,'1430000',NaN,-1])assert.equal(M.product({...product,price}).price,null);
 assert.equal(M.product({...product,price:0}).price,0);assert.equal(M.product({...product,product_code:0}),null);
});
test('multiple groups/products and empty groups retain order; unsupported grid is never invented',()=>{
 const data=M.recommendations(reco);assert.equal(data.groups.length,2);assert.deepEqual(data.groups[0].products.map(p=>p.index),[0,1]);assert.equal(data.groups[1].products.length,0);
 const grid=M.recommendations({ok:true,card_sets:[{kind:'game',cards:[{total:1}]}]});assert.equal(grid.unsupported,true);assert.deepEqual(grid.groups,[]);assert.throws(()=>M.recommendations({ok:true,cards:[]}));
});
test('source links reject executable URLs and credentials; label remains literal for escaped rendering',()=>{
 for(const url of ['javascript:alert(1)','data:text/html,x','https://secret:pw@example.invalid'])assert.equal(M.safeUrl(url),null);
 assert.deepEqual(M.sources([{kind:'internal',label:'private'},{kind:'web',label:'<img onerror=x>',url:'javascript:x'}]),[{kind:'web',label:'<img onerror=x>',url:null}]);
});
test('saved quote requires UUID, parseable ISO date and actual price',()=>{
 assert.ok(M.quote(saved.quote));for(const patch of [{id:'-'.repeat(36)},{saved_at:'not a date'},{product:{...product,price:null}}])assert.equal(M.quote({...saved.quote,...patch}),null);
});
test('same-origin parser preserves actual state/history; never sends guest key to LLM routes',async()=>{
 const requests=[],s=storage(),c=client(async(url,opts)=>{requests.push({url,opts});return response(parsed);},{storage:s});
 await c.parse({text:'요청',state:talk,history:[]});assert.equal(requests[0].url,'/api/talk/parse');assert.equal(requests[0].opts.credentials,'same-origin');assert.equal(requests[0].opts.headers['X-Access-Key'],undefined);assert.equal(s.map.size,0);
 assert.deepEqual(JSON.parse(requests[0].opts.body).state,talk);
 await assert.rejects(c.request('GET','https://example.invalid/api'));await assert.rejects(c.request('POST','/api/admin/quotes',{}));assert.equal(requests.length,1);
});
test('save GET prepares visitor cookie before POST; only key persists in localStorage',async()=>{
 const s=storage(),calls=[],c=client(async(url,opts)=>{calls.push({url,opts});return response(opts.method==='GET'?{ok:true,quotes:[]}:saved);},{storage:s});
 const binding=await c.prepareSave();assert.match(binding,/^[a-f0-9]{64}$/);await c.saveQuote({request_id:ID,product_code:101,expected_price:1430000,state:talk});
 assert.deepEqual(calls.map(x=>x.opts.method),['GET','POST']);assert.match(calls[0].url,/limit=1$/);assert.match(calls[0].opts.headers['X-Access-Key'],/^[a-f0-9]{64}$/);
 assert.equal(calls[0].opts.headers['X-Access-Key'],calls[1].opts.headers['X-Access-Key']);assert.deepEqual([...s.map.keys()],[A.KEY]);
});
test('reload reuses access-key fingerprint; losing or changing key prevents replay',async()=>{
 const s=storage(),c=client(async()=>response({ok:true,quotes:[]}),{storage:s}),binding=await c.prepareSave();
 const next=client(async()=>response(saved),{storage:s});assert.equal(await next.prepareSave({existingKeyOnly:true}),binding);
 s.removeItem(A.KEY);await assert.rejects(next.prepareSave({existingKeyOnly:true}),e=>e.code==='owner_changed');assert.equal(s.map.size,0);
});
test('blocked localStorage prevents save request while consultation works',async()=>{
 let count=0;const c=client(async()=>{count++;return response(parsed);},{storage:{getItem(){throw Error('blocked');}}});
 await assert.rejects(c.saveQuote({}),e=>e.code==='storage_unavailable');assert.equal(count,0);await c.parse({text:'hello'});assert.equal(count,1);
});
test('invalid preflight GET never primes POST',async()=>{
 const calls=[],c=client(async(url)=>{calls.push(url);return response({ok:false});});await assert.rejects(c.saveQuote({}),e=>e.code==='invalid_response');assert.equal(calls.length,1);
});
test('429 delay and409 safe messages do not leak server details',async()=>{
 const rate=client(async()=>response({detail:{error:'rate_limit',secret:'do-not-display'}},429,{'Retry-After':'3'}));await assert.rejects(rate.parse({}),e=>e.retryAfter===3&&!e.message.includes('do-not-display'));
 await assert.rejects(client(async()=>response({detail:'internal SQL'},409)).recommend(talk),e=>e.status===409&&!e.message.includes('SQL'));
});
test('bad JSON, network, timeout and caller abort remain distinct',async()=>{
 await assert.rejects(client(async()=>({ok:true,status:200,json:async()=>{throw Error('JSON');}})).parse({}),e=>e.code==='invalid_response');
 await assert.rejects(client(async()=>{throw Error('offline');}).parse({}),e=>e.code==='network');
 const stalled=client((url,{signal})=>new Promise((resolve,reject)=>{if(signal.aborted)reject(Error('aborted'));signal.addEventListener('abort',()=>reject(Error('aborted')));}));
 await assert.rejects(stalled.parse({}, {timeoutMs:10}),e=>e.code==='timeout');
 const controller=new AbortController(),request=stalled.parse({}, {signal:controller.signal});controller.abort();await assert.rejects(request,e=>e.code==='aborted');
});
test('answer/reply and history stay separate and sequential; sources and notice are not shown',async()=>{
 let last;const h=harness({parse:async payload=>{last=payload;return parsed;}});await h.flow.submit('첫 요청');assert.equal(last.history.length,0);
 assert.deepEqual(h.flow.state.messages.slice(-3).map(m=>m.text),['첫 요청',parsed.answer,parsed.reply]);assert.equal(h.flow.state.messages.at(-2).sources,undefined);assert.equal(h.flow.state.messages.at(-2).notice,undefined);assert.equal(h.flow.state.screen,'results');
 await h.flow.submit('두번째');assert.equal(last.history.length,3);assert.deepEqual(last.chat_flow,{step:2});assert.equal(h.flow.state.history.length,6);
});
test('missing/silent/non-PC answer does not fabricate recommendations',async()=>{
 for(const patch of [{missing:['budget_won']},{silent:true},{pc_related:false}]){let called=0;const h=harness({parse:async()=>({...parsed,...patch}),recommend:async()=>{called++;return reco;}});await h.flow.submit('요청');assert.equal(called,0);assert.equal(h.flow.state.screen,'welcome');assert.deepEqual(h.flow.state.groups,[]);if(patch.silent)assert.equal(h.flow.state.messages.length,2);}
});
test('duplicate input blocked; cancelled late response cannot overwrite reset consultation',async()=>{
 const first=deferred(),h=harness({parse:()=>first.promise});const request=h.flow.submit('처음');assert.equal(await h.flow.submit('중복'),false);assert.equal(h.flow.state.messages.length,2);
 h.flow.reset();first.resolve(parsed);await request;assert.equal(h.flow.state.screen,'welcome');assert.equal(h.flow.state.talk,null);assert.equal(h.flow.state.messages.length,1);
});
test('talk retry does not duplicate user history; recommend retry does not call LLM again',async()=>{
 let attempts=0,rec=0;const h=harness({parse:async()=>{if(!attempts++)throw new A.ApiError('offline');return parsed;},recommend:async()=>{if(!rec++)throw new A.ApiError('DB offline');return reco;}});
 await h.flow.submit('요청');assert.equal(h.flow.state.retry.kind,'talk');await h.flow.retry();assert.equal(h.flow.state.messages.filter(x=>x.who==='user').length,1);assert.equal(h.flow.state.retry.kind,'recommend');await h.flow.retry();assert.equal(attempts,2);assert.equal(h.flow.state.screen,'results');
});
test('minimal fixed request persists before POST and clears only after valid response',async()=>{
 const pending=deferred();let payload;const h=await selected(harness({saveQuote:async p=>{payload=p;assert.ok(h.sessionStorage.getItem(JOURNAL_KEY));return pending.promise;}}));
 const request=h.flow.save();await tick();assert.equal(h.flow.state.saveState,'saving');assert.equal(h.flow.state.savedQuote,null);assert.deepEqual(Object.keys(payload).sort(),['expected_price','product_code','request_id','state']);assert.equal(payload.request_id,ID);
 pending.resolve(saved);await request;assert.equal(h.flow.state.saveState,'saved');assert.equal(h.sessionStorage.getItem(JOURNAL_KEY),null);
});
test('save cancel/navigation becomes uncertain, preserves original product and ignores late response',async()=>{
 const pending=deferred(),h=await selected(harness({saveQuote:()=>pending.promise}));const request=h.flow.save();await tick();h.flow.navigate('detail');
 assert.equal(h.flow.state.saveState,'uncertain');assert.equal(h.flow.state.selected.name,product.name);assert.ok(h.flow.state.pendingSave);
 pending.resolve(saved);await request;assert.equal(h.flow.state.saveState,'uncertain');assert.equal(h.flow.state.savedQuote,null);assert.equal(h.flow.state.phase,null);
});
test('reload restores UUID and payload, never automatically POSTs; explicit recovery succeeds',async()=>{
 const session=storage(),pending=deferred(),h=await selected(harness({saveQuote:()=>pending.promise},session));const request=h.flow.save();await tick();h.flow.navigate('welcome');pending.resolve(saved);await request;
 let calls=0,payload;const next=harness({saveQuote:async p=>{calls++;payload=p;return saved;}},session);assert.equal(calls,0);assert.equal(next.flow.state.saveState,'uncertain');
 const original=JSON.parse(session.getItem(JOURNAL_KEY)).payload;await next.flow.recover();assert.deepEqual(payload,original);assert.equal(payload.request_id,ID);assert.equal(calls,1);assert.equal(next.flow.state.savedQuote.id,QID);
});
test('network uncertainty retries exact same request instead of generating new ID',async()=>{
 const ids=[];let calls=0;const h=await selected(harness({saveQuote:async p=>{ids.push(p.request_id);if(!calls++)throw new A.ApiError('lost response');return saved;}}));
 await h.flow.save();assert.equal(h.flow.state.saveState,'uncertain');await h.flow.retry();assert.deepEqual(ids,[ID,ID]);assert.equal(h.flow.state.saveState,'saved');
});
test('list success/reset cannot infer pending POST completed or discard its request',async()=>{
 const h=await selected(harness({saveQuote:async()=>{throw new A.ApiError('offline');},listSaved:async()=>({ok:true,quotes:[saved.quote]})}));
 await h.flow.save();await h.flow.list();assert.equal(h.flow.state.quotes.length,1);assert.ok(h.flow.state.pendingSave);h.flow.reset();assert.ok(h.flow.state.pendingSave);assert.equal(h.flow.state.saveState,'uncertain');
});
test('pending request prevents new save even after choosing another product',async()=>{
 let count=0;const h=await selected(harness({saveQuote:async()=>{count++;throw new A.ApiError('offline');}}));await h.flow.save();h.flow.select(1);await h.flow.save();assert.equal(count,1);assert.equal(h.flow.state.pendingSave.payload.product_code,101);
});
test('changed access-key binding never replays under different owner',async()=>{
 let posts=0;const h=await selected(harness({saveQuote:async()=>{posts++;throw new A.ApiError('offline');}}));await h.flow.save();h.api.prepareSave=async()=>'b'.repeat(64);
 await h.flow.recover();assert.equal(posts,1);assert.equal(h.flow.state.error.code,'owner_changed');assert.ok(h.flow.state.pendingSave);
});
test('blocked or corrupt session journal prevents POST; consultation can continue',async()=>{
 let posts=0;const session={getItem:()=>null,setItem(){throw Error('blocked');},removeItem(){}};
 const h=await selected(harness({saveQuote:async()=>{posts++;return saved;}},session));await h.flow.save();assert.equal(posts,0);assert.equal(h.flow.state.saveState,'failed');assert.equal(h.flow.state.error.code,'storage_unavailable');
 const s=storage();s.setItem(JOURNAL_KEY,'{invalid');const next=harness({},s);await next.flow.submit('요청');next.flow.select(0);await next.flow.save();assert.ok(next.flow.state.pendingProblem);
});
test('journal rejects changed keys, oversized state, invalid ID and product/history body',()=>{
 const record={version:1,binding:BIND,payload:{request_id:ID,product_code:101,expected_price:1430000,state:talk}};assert.equal(validPending(record),true);
 for(const patch of [{request_id:'invalid'},{product_code:'101'},{product:product},{history:['private']},{state:{too_long:'x'.repeat(20000)}}])assert.equal(validPending({...record,payload:{...record.payload,...patch}}),false);
});
test('409 prevents stale saving and requires a fresh recommendation',async()=>{
 const h=await selected(harness({saveQuote:async()=>{throw new A.ApiError('price changed',409);}}));await h.flow.save();
 assert.equal(h.flow.state.needsRefresh,true);assert.equal(h.flow.state.retry.kind,'recommend');assert.equal(h.flow.state.pendingSave,null);assert.equal(h.flow.state.savedQuote,null);
 await h.flow.retry();assert.equal(h.flow.state.needsRefresh,false);assert.equal(h.flow.state.selected,null);
});
test('malformed or mismatched save response stays uncertain with recoverable request',async()=>{
 for(const result of [{ok:true,quote:{...saved.quote,id:'invalid'}},{ok:true,quote:{...saved.quote,product:{...product,price:1}}}]){const h=await selected(harness({saveQuote:async()=>result}));await h.flow.save();assert.equal(h.flow.state.saveState,'uncertain');assert.equal(h.flow.state.savedQuote,null);assert.ok(h.flow.state.pendingSave);}
});
test('list failure stays error rather than empty successful result',async()=>{
 const h=harness({listSaved:async()=>({ok:true,quotes:[{id:'broken'}]})});await h.flow.list();assert.equal(h.flow.state.screen,'saved');assert.ok(h.flow.state.error);assert.equal(h.flow.state.retry.kind,'list');
});
test('rate-limited retry respects delay; overlong input never requests',async()=>{
 let calls=0;const h=harness({parse:async()=>{calls++;throw new A.ApiError('wait',429,'rate',30);}});
 assert.equal(await h.flow.submit('x'.repeat(301)),false);await h.flow.submit('request');await h.flow.retry();assert.equal(calls,1);assert.ok(h.flow.state.error.retryAt>Date.now());
});
