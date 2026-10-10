'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),{webcrypto,createHash}=require('node:crypto');
const {JSDOM,VirtualConsole}=require('jsdom');
const BASE=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(BASE,n),'utf8');
const ID='11111111-1111-4111-8111-111111111111',QID='22222222-2222-4222-8222-222222222222';
const KEY='popcorn-mvp3-guest-access-v1',JOURNAL='popcorn-mvp3-pending-save-v1',ACCESS='a'.repeat(64);
const binding=createHash('sha256').update(ACCESS).digest('hex');
const talk={usages:['게임'],budget_won:1000000,budget_bound:'이하'};
const product={product_code:101,name:'CODE/MOCK PC',price:900000,spec:{cpu:'MOCK CPU'}};
const quote={id:QID,product,state:talk,saved_at:'2026-10-07T00:00:00Z'};
const pending={version:1,binding,payload:{request_id:ID,product_code:101,expected_price:900000,state:talk}};
const empty={ok:true,quotes:[],has_more:false},parsed={ok:true,state:talk,chat_flow:{step:'mock'},missing:[],assumed:[]};
const recommendation={ok:true,card_sets:[{kind:'sold',usage:'게임',items:[product]}],needs:[],assumed:[]};
const copy=v=>JSON.parse(JSON.stringify(v)),tick=()=>new Promise(r=>setImmediate(r));
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
async function until(check){for(let i=0;i<80;i++){if(check())return;await tick();}throw Error('probe did not settle');}
function standard(url){return url==='/api/talk/parse'?parsed:url==='/api/grid/recommend'?recommendation:empty;}
const active=[];
function harness({hash='#welcome',respond=standard,journal=null}={}){
  const disposed=deferred(),calls=[],errors=[];
  const vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read('index.html'),{url:'http://qa.invalid/'+hash,runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.TextEncoder=TextEncoder;
  Object.defineProperty(w,'crypto',{value:webcrypto});
  w.localStorage.setItem(KEY,ACCESS);if(journal)w.sessionStorage.setItem(JOURNAL,journal);
  w.eval(read('live-model.js'));w.eval(read('api-client.js'));
  w.MVP3Api=w.MVP3Api.createClient({storage:w.localStorage,cryptoImpl:webcrypto,fetchImpl:async(url,options)=>{
    const call={url,method:options.method,body:options.body?JSON.parse(options.body):null,signal:options.signal,headers:options.headers};calls.push(call);
    const result=await Promise.race([Promise.resolve().then(()=>respond(url,call)),disposed.promise]);
    return {ok:result.httpStatus?result.httpStatus<400:true,status:result.httpStatus||200,headers:{get:name=>result.headers?.[name]??null},json:async()=>{if(result.badJson)throw Error('mock invalid JSON');return result.data||result;}};
  }});
  w.eval(read('live-flow.js'));let flow;
  const factory=w.MVP3LiveFlow.createFlow;
  w.MVP3LiveFlow.createFlow=(api,options)=>flow=factory(api,{...options,uuid:()=>ID});
  w.eval(read('app.js'));
  const h={dom,w,flow,calls,errors,input:w.document.querySelector('#request'),
    click(action){const button=w.document.querySelector('[data-action="'+action+'"]');assert.ok(button,'actual rendered action '+action);button.click();},
    postCount(){return calls.filter(c=>c.method==='POST').length;},
    pop(hash){w.history.replaceState({screen:hash.slice(1)},'',hash);w.dispatchEvent(new w.PopStateEvent('popstate',{state:w.history.state}));},
    journal(){return w.sessionStorage.getItem(JOURNAL);},
    close(){flow.cancel();disposed.resolve(empty);w.close();}};
  active.push(h);return h;
}
test.afterEach(async()=>{for(const h of active.splice(0)){assert.deepEqual(h.errors,[]);h.close();}await tick();});
function edit(h,text){h.input.value=text;h.input.dispatchEvent(new h.w.Event('input',{bubbles:true}));}
function choose(h,usage){h.w.document.querySelector('[data-usage="'+usage+'"]').click();}
function budget(h,n){const e=h.w.document.querySelector('#gateway-budget');e.value=n;e.dispatchEvent(new h.w.Event('change',{bubbles:true}));}
function surface(h){return h.w.document.body.dataset.surface;}
function send(h){h.w.document.querySelector('#chat-form').requestSubmit();}
async function traverse(h,method){await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('history traversal timeout')),1500);h.w.addEventListener('popstate',()=>{clearTimeout(timer);resolve();},{once:true});h.w.history[method]();});}
test('generic entry shows approved two choices; direct is empty; no API until explicit send',()=>{
  const h=harness({hash:''});assert.equal(surface(h),'gateway');assert.match(h.w.document.querySelector('#gateway-root').textContent,/어디서부터/);assert.equal(h.calls.length,0);const n=h.w.history.length;h.click('gateway');assert.equal(h.w.history.length,n);h.click('gateway-direct');assert.equal(surface(h),'consultation');assert.equal(h.input.value,'');assert.equal(h.calls.length,0);assert.equal(h.w.document.activeElement,h.input);
});
test('unknown usage and unset budget generate editable draft without requests; won budget is parsed only on explicit send',async()=>{
  const h=harness({hash:''});h.click('gateway-use');choose(h,'unknown');budget(h,'');h.click('gateway-begin');assert.equal(h.input.value,'어떤 PC가 좋을지 함께 정하고 싶어요.');assert.equal(h.calls.length,0);h.click('gateway-use');choose(h,'edit');budget(h,'150');h.click('gateway-begin');assert.match(h.input.value,/영상 편집.*150만원 이하/);assert.equal(h.calls.length,0);send(h);await until(()=>h.flow.state.phase===null);assert.deepEqual(Object.keys(h.calls[0].body).sort(),['chat_flow','history','state','text']);assert.equal(h.calls[0].body.state,null);assert.deepEqual(h.calls[1].body,{state:talk});
});
test('manual text and manual deletion survive modes conditions and choices; only explicit rebuild replaces text',async()=>{
  const h=harness();edit(h,'수동 문장');h.click('gateway');h.click('gateway-use');choose(h,'game');budget(h,'200');h.click('gateway-begin');assert.equal(h.input.value,'수동 문장');h.click('gateway');h.click('gateway-direct');assert.equal(h.input.value,'수동 문장');
  await h.flow.submit('기존 실제 상담');h.click('conditions');assert.equal(h.input.value,'수동 문장');edit(h,'');h.click('gateway-use');choose(h,'office');h.click('gateway-begin');assert.equal(h.input.value,'');h.click('gateway-rebuild');assert.match(h.input.value,/문서 작업.*200만원/);
});
test('same document actual Back Forward never cancels pending parse or serializes raw text journal key',async()=>{
  const raw=JSON.stringify(pending),d=deferred(),h=harness({hash:'',journal:raw,respond:url=>url==='/api/talk/parse'?d.promise:recommendation});h.click('gateway-direct');edit(h,'한글 초안');send(h);const signal=h.calls[0].signal;h.click('gateway');h.click('gateway-use');const before=copy(h.flow.state),n=h.w.history.length;
  await traverse(h,'back');assert.equal(surface(h),'gateway');await traverse(h,'back');assert.equal(surface(h),'consultation');await traverse(h,'forward');await traverse(h,'forward');assert.equal(surface(h),'usage');assert.equal(h.w.history.length,n);assert.equal(signal.aborted,false);assert.deepEqual(copy(h.flow.state),before);assert.equal(h.input.value,'한글 초안');assert.equal(h.journal(),raw);assert.equal(h.calls.length,1);assert.deepEqual(Object.keys(h.w.history.state).sort(),['screen','surface','ui_epoch']);assert.equal(JSON.stringify(h.w.history.state).includes('한글'),false);assert.equal(h.w.location.href.includes('한글'),false);d.resolve(parsed);await until(()=>h.flow.state.phase===null);assert.equal(h.flow.state.screen,'results');assert.equal(surface(h),'usage');
});
test('direct welcome initial entry becomes a UI return anchor; Back during parse never invokes cancel',async()=>{
  const d=deferred(),h=harness({respond:url=>url==='/api/talk/parse'?d.promise:recommendation});edit(h,'직접유입 요청');send(h);const signal=h.calls[0].signal;h.click('gateway');await traverse(h,'back');assert.equal(surface(h),'consultation');assert.equal(h.input.disabled,true);assert.equal(signal.aborted,false);assert.equal(h.flow.state.phase,'talk');assert.equal(h.calls.length,1);d.resolve(parsed);await until(()=>h.flow.state.phase===null);assert.equal(h.flow.state.screen,'results');assert.equal(h.calls.length,2);
});
test('async result while usage remains open replaces metadata; old UI screen never rolls back latest products',async()=>{
  const d=deferred(),h=harness({hash:'',respond:url=>url==='/api/talk/parse'?d.promise:recommendation});h.click('gateway-direct');edit(h,'진행조건');send(h);h.click('gateway');h.click('gateway-use');const n=h.w.history.length;d.resolve(parsed);await until(()=>h.flow.state.phase===null);assert.equal(surface(h),'usage');assert.equal(h.flow.state.screen,'results');assert.equal(h.w.history.length,n);assert.equal(h.w.history.state.screen,'results');const before=copy(h.flow.state);await traverse(h,'back');assert.equal(surface(h),'gateway');assert.deepEqual(copy(h.flow.state),before);await traverse(h,'forward');assert.equal(surface(h),'usage');h.click('gateway-begin');assert.equal(h.flow.state.screen,'results');assert.match(h.w.document.querySelector('#view').textContent,/CODE\/MOCK PC/);assert.equal(h.calls.length,2);
});
test('recommendation selection conversation and pending journal survive UI-only transitions',async()=>{
  const h=harness({journal:JSON.stringify(pending)});await h.flow.submit('기존상담');h.flow.select(0);edit(h,'다음 조건');const before=copy(h.flow.state),raw=h.journal(),n=h.calls.length;h.click('gateway');h.click('gateway-use');choose(h,'office');budget(h,'250');h.click('gateway-begin');assert.deepEqual(copy(h.flow.state),before);assert.equal(h.journal(),raw);assert.equal(h.calls.length,n);assert.equal(h.input.value,'다음 조건');
});
test('IME Enter and Shift Enter do not submit; plain Enter and busy guard use existing contract',async()=>{
  const d=deferred(),h=harness({respond:()=>d.promise});edit(h,'한글 요청');for(const opts of [{isComposing:true},{shiftKey:true}]){h.input.dispatchEvent(new h.w.KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true,...opts}));assert.equal(h.calls.length,0);}const enter=()=>h.input.dispatchEvent(new h.w.KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));enter();assert.equal(h.calls.length,1);assert.equal(h.input.disabled,true);enter();assert.equal(h.calls.length,1);d.resolve({...parsed,missing:['budget']});await until(()=>h.flow.state.phase===null);assert.equal(h.input.value,'');
});
test('empty and >300 input never dispatch; failed submit retains draft across UI modes then explicit retry',async()=>{
  let count=0;const h=harness({respond:url=>url==='/api/talk/parse'?(++count===1?{httpStatus:503,data:{detail:{error:'down',secret:'NOT_PUBLIC'}}}:parsed):recommendation});for(const text of ['','   ','x'.repeat(301)]){edit(h,text);send(h);assert.equal(h.calls.length,0);}edit(h,'실패 후 문장');send(h);await until(()=>h.flow.state.phase===null);assert.equal(h.input.value,'실패 후 문장');assert.ok(h.w.document.querySelector('[role="alert"]'));assert.equal(h.w.document.body.textContent.includes('NOT_PUBLIC'),false);h.click('gateway');h.click('gateway-direct');assert.equal(h.input.value,'실패 후 문장');assert.equal(h.calls.length,1);h.click('retry');await until(()=>h.flow.state.phase===null&&h.flow.state.screen==='results');assert.equal(count,2);assert.equal(h.flow.state.messages.filter(m=>m.who==='user').length,1);
});
test('429 retry deadline remains disabled across UI surface and explicit recovery never duplicates message',async()=>{
  let n=0;const h=harness({respond:()=>++n===1?{httpStatus:429,headers:{'Retry-After':'3'},data:{detail:{error:'rate'}}}:{...parsed,missing:['budget']}});edit(h,'요청');send(h);await until(()=>h.flow.state.phase===null);h.click('gateway');h.click('gateway-direct');assert.equal(h.w.document.querySelector('[data-action="retry"]').disabled,true);h.click('retry');await tick();assert.equal(n,1);const original=h.w.Date.now;h.w.Date.now=()=>h.flow.state.error?.retryAt+1||original();h.flow.emit();h.click('retry');await until(()=>h.flow.state.phase===null);h.w.Date.now=original;assert.equal(n,2);assert.equal(h.flow.state.messages.filter(m=>m.who==='user').length,1);
});
test('recommend loading and failure preserve validated talk; retry calls only grid',async()=>{
  const d=deferred();let n=0;const h=harness({respond:url=>url==='/api/talk/parse'?parsed:(++n===1?d.promise:recommendation)});edit(h,'추천 조건');send(h);await until(()=>h.flow.state.phase==='recommend');const signal=h.calls[1].signal;h.click('gateway');d.resolve({httpStatus:502,data:{detail:{error:'grid_down'}}});await until(()=>h.flow.state.phase===null);assert.equal(signal.aborted,false);h.click('gateway-direct');assert.equal(h.input.value,'추천 조건');assert.equal(h.flow.state.retry.kind,'recommend');h.click('retry');await until(()=>h.flow.state.phase===null&&h.flow.state.screen==='results');assert.equal(h.calls.filter(c=>c.url==='/api/talk/parse').length,1);assert.equal(n,2);assert.deepEqual(copy(h.flow.state.talk),talk);
});
test('fresh saved GET coalesces duplicate clicks/pop; unknown reload is not confirmed by GET',async()=>{
  const raw=JSON.stringify(pending),d=deferred(),h=harness({hash:'#saved',journal:raw,respond:()=>d.promise});assert.equal(h.calls.length,1);assert.equal(h.calls[0].method,'GET');h.click('saved');h.pop('#saved');assert.equal(h.calls.length,1);assert.equal(h.calls[0].signal.aborted,false);d.resolve({ok:true,quotes:[quote]});await until(()=>h.flow.state.phase===null);assert.equal(h.flow.state.saveState,'uncertain');assert.equal(h.flow.state.savedQuote,null);assert.equal(h.journal(),raw);assert.equal(h.postCount(),0);const reload=harness({hash:'#saved',journal:raw});await until(()=>reload.flow.state.phase===null);assert.equal(reload.input.value,'');assert.equal(reload.journal(),raw);assert.equal(reload.postCount(),0);
});
test('fresh impossible/foreign routes never infer products or resurrect old UI epoch',()=>{
  for(const hash of ['#detail','#final','#results','#unknown']){const h=harness({hash});assert.equal(h.w.location.hash,'#welcome');assert.equal(h.flow.state.selected,null);assert.equal(h.calls.length,0);}const h=harness();edit(h,'현재문장');h.w.history.replaceState({screen:'welcome',surface:'usage',ui_epoch:'foreign-doc'},'','#welcome');h.w.dispatchEvent(new h.w.PopStateEvent('popstate',{state:h.w.history.state}));assert.equal(surface(h),'consultation');assert.equal(h.input.value,'현재문장');assert.equal(h.calls.length,0);
});
test('actual screen Back Forward maintains existing saved GET and abort behavior without loops',async()=>{
  const h=harness();h.click('saved');await until(()=>h.flow.state.phase===null);assert.equal(h.calls.length,1);h.click('back');const n=h.w.history.length;await traverse(h,'back');await until(()=>h.flow.state.phase===null);assert.equal(h.flow.state.screen,'saved');assert.equal(h.calls.length,2);assert.equal(h.w.history.length,n);await traverse(h,'forward');assert.equal(h.flow.state.screen,'welcome');assert.equal(h.w.history.length,n);
});
test('save in flight remains alive across UI-only changes, unknown journal survives late network failure',async()=>{
  const d=deferred(),h=harness({respond:(url,c)=>url==='/api/mvp3/saved-quotes'&&c.method==='POST'?d.promise:standard(url)});await h.flow.submit('조건');h.flow.select(0);h.flow.navigate('final');h.click('save');await until(()=>h.calls.some(c=>c.url==='/api/mvp3/saved-quotes'&&c.method==='POST'));const call=h.calls.find(c=>c.url==='/api/mvp3/saved-quotes'&&c.method==='POST'),raw=h.journal();h.click('gateway');h.click('gateway-use');assert.equal(call.signal.aborted,false);assert.equal(h.journal(),raw);d.reject(Error('mock network'));await until(()=>h.flow.state.phase===null);assert.equal(h.flow.state.saveState,'uncertain');assert.equal(h.journal(),raw);h.click('gateway-begin');assert.equal(h.flow.state.screen,'final');assert.equal(h.journal(),raw);assert.equal(h.calls.filter(c=>c.url==='/api/mvp3/saved-quotes'&&c.method==='POST').length,1);assert.deepEqual(Object.keys(call.body).sort(),['expected_price','product_code','request_id','state']);
});
test('unknown explicit recover uses exact same UUID payload binding; owner change and 409 keep existing policies',async()=>{
  const raw=JSON.stringify(pending),h=harness({journal:raw,respond:(url,c)=>c.method==='POST'?{ok:true,quote}:empty});h.click('gateway');h.click('gateway-direct');assert.equal(h.postCount(),0);h.click('recover');await until(()=>h.flow.state.phase===null);assert.deepEqual(h.calls.find(c=>c.method==='POST').body,pending.payload);assert.equal(h.journal(),null);assert.equal(h.flow.state.saveState,'saved');
  const owner=harness({journal:raw});owner.w.localStorage.setItem(KEY,'b'.repeat(64));owner.click('recover');await until(()=>owner.flow.state.phase===null);assert.equal(owner.postCount(),0);assert.equal(owner.journal(),raw);assert.equal(owner.flow.state.error.code,'owner_changed');
  const conflict=harness({journal:raw,respond:(url,c)=>c.method==='POST'?{httpStatus:409,data:{detail:{error:'price_changed'}}}:empty});conflict.click('recover');await until(()=>conflict.flow.state.phase===null);assert.equal(conflict.flow.state.needsRefresh,true);assert.equal(conflict.flow.state.saveState,'failed');assert.equal(conflict.journal(),null);
});
test('saved empty/failure/loading are distinct and actual retry is GET only',async()=>{
  let n=0;const d=deferred(),h=harness({hash:'#saved',respond:()=>++n===1?d.promise:empty});assert.match(h.w.document.querySelector('#view').textContent,/불러오는 중/);assert.doesNotMatch(h.w.document.querySelector('#view').textContent,/보관된 견적이 없어요/);d.resolve({httpStatus:503,data:{detail:{error:'unavailable'}}});await until(()=>h.flow.state.phase===null);assert.ok(h.w.document.querySelector('[role="alert"]'));assert.doesNotMatch(h.w.document.querySelector('#view').textContent,/보관된 견적이 없어요/);h.click('retry');await until(()=>h.flow.state.phase===null);assert.match(h.w.document.querySelector('#view').textContent,/보관된 견적이 없어요/);assert.equal(n,2);assert.equal(h.postCount(),0);
});
test('server missing/silent/non-PC guards and new reset remain explicit; product link never invents data',async()=>{
  for(const guard of [{missing:['budget']},{silent:true},{pc_related:false}]){const h=harness({respond:()=>({...parsed,...guard})});edit(h,'요청');send(h);await until(()=>h.flow.state.phase===null);assert.equal(h.calls.length,1);assert.equal(h.flow.state.screen,'welcome');}
  const h=harness({hash:''});h.click('gateway-products');assert.equal(h.calls.length,0);assert.equal(surface(h),'consultation');await h.flow.submit('조건');h.click('gateway');h.click('gateway-products');assert.equal(h.flow.state.screen,'results');assert.equal(h.calls.length,2);h.click('new');assert.equal(h.flow.state.talk,null);assert.equal(h.input.value,'');assert.equal(h.flow.state.selected,null);assert.equal(surface(h),'consultation');
});
test('consultation never shows removed source labels or web notice, including old stored messages',async()=>{
  const removed=['저희 자료에 없는 내용이라 잠깐 찾아볼게요. 조금만 기다려 주세요.','우리 자료','저희가 정리해 둔 자료예요.','찾아본 자료','저희 자료엔 없어서 방금 찾아봤어요 - 위키백과, 방금 기준이에요.'];
  const reply={...parsed,missing:['budget'],answer:'게임 설명입니다.',sources:[{kind:'own',label:removed[2]},{kind:'web',label:removed[4],url:'https://ko.wikipedia.org/wiki/x'}],answer_notice:removed[0]};
  const h=harness({respond:()=>reply});await h.flow.submit('게임 알려줘');
  h.flow.state.messages.push({text:'예전 답변',who:'ai',sources:reply.sources,notice:removed[0]});await h.flow.submit('다시');
  const box=h.w.document.querySelector('#messages');assert.match(box.textContent,/게임 설명입니다\./);assert.match(box.textContent,/예전 답변/);
  for(const phrase of removed)assert.ok(!box.textContent.includes(phrase),phrase);
  assert.equal(box.querySelectorAll('.message-sources,.answer-notice,a[href*="wikipedia"]').length,0);
});
test('quick replies follow what the consultation asks: usage question gets usage choices, game question gets games',async()=>{
  const chips=h=>[...h.w.document.querySelectorAll('#suggestions button')].map(b=>b.dataset.text);
  const usage={ok:true,state:{usages:[]},missing:['usages'],assumed:[],reply:'어떤 용도로 쓰실 PC인가요?'};
  const grade={ok:true,state:{usages:['게임'],budget_won:1000000},missing:['game.grade'],assumed:[],reply:'어떤 게임을 하실 예정인가요?'};
  const a=harness({respond:url=>url==='/api/talk/parse'?usage:empty});await a.flow.submit('최저가 PC');await until(()=>a.flow.state.phase===null);
  assert.deepEqual(chips(a),['게임용이에요','영상 편집용이에요','사무용이에요']);
  const b=harness({respond:url=>url==='/api/talk/parse'?grade:empty});await b.flow.submit('게임 100만원');await until(()=>b.flow.state.phase===null);
  assert.deepEqual(chips(b),['배그를 해요','롤을 해요','배그와 롤 둘 다 해요']);
  const c=harness();assert.ok(chips(c).includes('QHD로 해줘요'));
});
