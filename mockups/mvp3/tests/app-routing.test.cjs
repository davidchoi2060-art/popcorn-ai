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
// 틱 수만 세면 Web Crypto(접근 키 해시)처럼 스레드 풀에서 끝나는 일이 앞 테스트 부하에 따라 늦어 가끔 실패한다 -- 2초까지 기다린다.
async function until(check){const end=Date.now()+2000;for(let i=0;i<80||Date.now()<end;i++){if(check())return;await tick();}throw Error('probe did not settle');}
function standard(url){return url==='/api/talk/parse'?parsed:url==='/api/grid/recommend'?recommendation:url==='/api/mvp3/contact'?{ok:true,has_contact:true,masked_phone:'010-****-5678',name:null,consent_text:'동의 문구'}:empty;}
const active=[];
function harness({hash='#welcome',respond=standard,journal=null,fromTalk=false,mobile=false}={}){
  const disposed=deferred(),calls=[],errors=[];
  const vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read('index.html'),{url:'http://qa.invalid/'+hash,runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window,media={matches:mobile,listener:null,addEventListener(type,fn){if(type==='change')this.listener=fn;}};w.matchMedia=()=>media;w.scrollTo=()=>{};w.TextEncoder=TextEncoder;
  Object.defineProperty(w,'crypto',{value:webcrypto});
  w.localStorage.setItem(KEY,ACCESS);if(journal)w.sessionStorage.setItem(JOURNAL,journal);if(fromTalk)w.sessionStorage.setItem('popcorn-mvp3-from-talk-v1',JSON.stringify({focus:'parts'}));
  w.eval(read('live-model.js'));w.eval(read('api-client.js'));
  w.MVP3Api=w.MVP3Api.createClient({storage:w.localStorage,cryptoImpl:webcrypto,fetchImpl:async(url,options)=>{
    const call={url,method:options.method,body:options.body?JSON.parse(options.body):null,signal:options.signal,headers:options.headers};calls.push(call);
    const result=await Promise.race([Promise.resolve().then(()=>respond(url,call)),disposed.promise]);
    return {ok:result.httpStatus?result.httpStatus<400:true,status:result.httpStatus||200,headers:{get:name=>result.headers?.[name]??null},json:async()=>{if(result.badJson)throw Error('mock invalid JSON');return result.data||result;}};
  }});
  w.eval(read('live-flow.js'));let flow;
  const factory=w.MVP3LiveFlow.createFlow;
  w.MVP3LiveFlow.createFlow=(api,options)=>flow=factory(api,{...options,uuid:()=>ID});
  w.eval(read('live-photo.js'));w.eval(read('app.js'));
  const h={dom,w,flow,calls,errors,input:w.document.querySelector('#request'),
    setMobile(value){media.matches=value;media.listener?.();},
    click(action){const button=w.document.querySelector('[data-action="'+action+'"]');assert.ok(button,'actual rendered action '+action);button.click();},
    postCount(){return calls.filter(c=>c.method==='POST').length;},
    pop(hash){w.history.replaceState({screen:hash.slice(1)},'',hash);w.dispatchEvent(new w.PopStateEvent('popstate',{state:w.history.state}));},
    journal(){return w.sessionStorage.getItem(JOURNAL);},
    close(){flow.cancel();disposed.resolve(empty);w.close();}};
  active.push(h);return h;
}
test.afterEach(async()=>{for(const h of active.splice(0)){assert.deepEqual(h.errors,[]);h.close();}await tick();});
test('the real welcome-card loader and app pass only their displayed identities to the consultation',async()=>{
  const h=harness(),pcs=[{configuration_id:'A-03',title:'사무 PC',price:1000000},{configuration_id:'A-01',title:'게임 PC',price:null},{configuration_id:'A-02',title:'다른 PC',price:900000},{configuration_id:'A-04',title:'숨겨진 네 번째 PC',price:800000}];
  h.w.fetch=async()=>({ok:true,json:async()=>({ok:true,items:pcs})});
  h.w.eval(read('welcome-pcs.js'));
  await until(()=>h.w.document.querySelectorAll('.welcome-pc').length===3);
  edit(h,'세 번째 PC를 설명해 주세요');send(h);
  await until(()=>h.calls.some(c=>c.url==='/api/talk/parse'));
  const context=h.calls.find(c=>c.url==='/api/talk/parse').body.display_context;
  assert.deepEqual(copy(context),{screen:'welcome',cards:[{configuration_id:'A-03'},{configuration_id:'A-01'},{configuration_id:'A-02'}],selected:null,source:'new_pcs'});
});
function edit(h,text){h.input.value=text;h.input.dispatchEvent(new h.w.Event('input',{bubbles:true}));}
function choose(h,usage){h.w.document.querySelector('[data-usage="'+usage+'"]').click();}
function budget(h,n){const e=h.w.document.querySelector('#gateway-budget');e.value=n;e.dispatchEvent(new h.w.Event('change',{bubbles:true}));}
function surface(h){return h.w.document.body.dataset.surface;}
function send(h){h.w.document.querySelector('#chat-form').requestSubmit();}
async function traverse(h,method){await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('history traversal timeout')),1500);h.w.addEventListener('popstate',()=>{clearTimeout(timer);resolve();},{once:true});h.w.history[method]();});}
// 2026-10-16 중헌 님: 첫 화면은 하나다. 빈 주소와 옛 입구 주소(#start · #purpose)는 모두 상담 첫 화면(#welcome)으로 연다.
test('every entry opens the single consultation screen; no start gateway; no API until explicit send',()=>{
  for(const hash of ['','#start','#purpose','#welcome']){
    const h=harness({hash});const d=h.w.document;assert.equal(surface(h),'consultation');assert.equal(h.w.location.hash,'#welcome');assert.equal(h.flow.state.screen,'welcome');
    assert.equal(d.querySelector('#gateway-root'),null);assert.equal(d.querySelector('.gateway-route-toolbar'),null);assert.equal(d.querySelector('[data-action^="gateway"]'),null);
    assert.equal(d.querySelector('.workspace').hidden,false);assert.match(d.querySelector('#view').textContent,/어떤 PC가 필요한지 들려주세요/);assert.equal(h.calls.length,0);
  }
  const h=harness({hash:''});const n=h.w.history.length;h.click('home');assert.equal(h.w.history.length,n);assert.equal(h.flow.state.screen,'welcome');h.click('new');assert.equal(surface(h),'consultation');assert.equal(h.input.value,'');assert.equal(h.calls.length,0);
});
test('manual text and manual deletion survive the conditions shortcut',async()=>{
  const h=harness();edit(h,'수동 문장');await h.flow.submit('기존 실제 상담');h.click('conditions');assert.equal(h.input.value,'수동 문장');edit(h,'');h.click('conditions');assert.equal(h.input.value,'');
});
test('pending parse is never cancelled by the brand link and never serializes raw text into history',async()=>{
  const raw=JSON.stringify(pending),d=deferred(),h=harness({hash:'',journal:raw,respond:url=>url==='/api/talk/parse'?d.promise:recommendation});h.click('new');edit(h,'한글 초안');send(h);const signal=h.calls[0].signal;h.click('home');const before=copy(h.flow.state);
  assert.equal(signal.aborted,false);assert.deepEqual(copy(h.flow.state),before);assert.equal(h.input.value,'한글 초안');assert.equal(h.journal(),raw);assert.equal(h.calls.length,1);assert.deepEqual(Object.keys(h.w.history.state).sort(),['screen']);assert.equal(JSON.stringify(h.w.history.state).includes('한글'),false);assert.equal(h.w.location.href.includes('한글'),false);d.resolve(parsed);await until(()=>h.flow.state.phase===null);assert.equal(h.flow.state.screen,'results');
});
test('brand link during parse never invokes cancel',async()=>{
  const d=deferred(),h=harness({respond:url=>url==='/api/talk/parse'?d.promise:recommendation});edit(h,'직접유입 요청');send(h);const signal=h.calls[0].signal;h.click('home');assert.equal(surface(h),'consultation');assert.equal(h.input.disabled,true);assert.equal(signal.aborted,false);assert.equal(h.flow.state.phase,'talk');assert.equal(h.calls.length,1);d.resolve(parsed);await until(()=>h.flow.state.phase===null);assert.equal(h.flow.state.screen,'results');assert.equal(h.calls.length,2);
});
test('recommendation selection conversation and pending journal survive UI-only transitions',async()=>{
  const h=harness({journal:JSON.stringify(pending)});await h.flow.submit('기존상담');h.flow.select(0);edit(h,'다음 조건');const before=copy(h.flow.state),raw=h.journal(),n=h.calls.length;h.click('conditions');assert.deepEqual(copy(h.flow.state),before);assert.equal(h.journal(),raw);assert.equal(h.calls.length,n);assert.equal(h.input.value,'다음 조건');
});
test('IME Enter and Shift Enter do not submit; plain Enter and busy guard use existing contract',async()=>{
  const d=deferred(),h=harness({respond:()=>d.promise});edit(h,'한글 요청');for(const opts of [{isComposing:true},{shiftKey:true}]){h.input.dispatchEvent(new h.w.KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true,...opts}));assert.equal(h.calls.length,0);}const enter=()=>h.input.dispatchEvent(new h.w.KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));enter();assert.equal(h.calls.length,1);assert.equal(h.input.disabled,true);enter();assert.equal(h.calls.length,1);d.resolve({...parsed,missing:['budget']});await until(()=>h.flow.state.phase===null);assert.equal(h.input.value,'');
});
test('empty and >20000 input never dispatch; failed submit retains draft across UI modes then explicit retry',async()=>{
  let count=0;const h=harness({respond:url=>url==='/api/talk/parse'?(++count===1?{httpStatus:503,data:{detail:{error:'down',secret:'NOT_PUBLIC'}}}:parsed):recommendation});for(const text of ['','   ','x'.repeat(20001)]){edit(h,text);send(h);assert.equal(h.calls.length,0);}edit(h,'실패 후 문장');send(h);await until(()=>h.flow.state.phase===null);assert.equal(h.input.value,'실패 후 문장');assert.ok(h.w.document.querySelector('[role="alert"]'));assert.equal(h.w.document.body.textContent.includes('NOT_PUBLIC'),false);assert.equal(h.input.value,'실패 후 문장');assert.equal(h.calls.length,1);h.click('retry');await until(()=>h.flow.state.phase===null&&h.flow.state.screen==='results');assert.equal(count,2);assert.equal(h.flow.state.messages.filter(m=>m.who==='user').length,1);
});
test('429 retry deadline remains disabled across UI surface and explicit recovery never duplicates message',async()=>{
  let n=0;const h=harness({respond:()=>++n===1?{httpStatus:429,headers:{'Retry-After':'3'},data:{detail:{error:'rate'}}}:{...parsed,missing:['budget']}});edit(h,'요청');send(h);await until(()=>h.flow.state.phase===null);assert.equal(h.w.document.querySelector('[data-action="retry"]').disabled,true);h.click('retry');await tick();assert.equal(n,1);const original=h.w.Date.now;h.w.Date.now=()=>h.flow.state.error?.retryAt+1||original();h.flow.emit();h.click('retry');await until(()=>h.flow.state.phase===null);h.w.Date.now=original;assert.equal(n,2);assert.equal(h.flow.state.messages.filter(m=>m.who==='user').length,1);
});
test('recommend loading and failure preserve validated talk; retry calls only grid',async()=>{
  const d=deferred();let n=0;const h=harness({respond:url=>url==='/api/talk/parse'?parsed:(++n===1?d.promise:recommendation)});edit(h,'추천 조건');send(h);await until(()=>h.flow.state.phase==='recommend');const signal=h.calls[1].signal;h.click('home');d.resolve({httpStatus:502,data:{detail:{error:'grid_down'}}});await until(()=>h.flow.state.phase===null);assert.equal(signal.aborted,false);assert.equal(h.input.value,'추천 조건');assert.equal(h.flow.state.retry.kind,'recommend');h.click('retry');await until(()=>h.flow.state.phase===null&&h.flow.state.screen==='results');assert.equal(h.calls.filter(c=>c.url==='/api/talk/parse').length,1);assert.equal(n,2);assert.deepEqual(copy(h.flow.state.talk),talk);
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
  // 견적 보관은 팝콘AI 맞춤 구성(ai_composed)의 상세에서 바로 한다 -- 「선택한 구성 확인」(final) 단계는 없고, 보관은 창이 아니라 보관 화면이다.
  const ai={...recommendation,card_sets:[{...recommendation.card_sets[0],items:[{...product,ai_composed:true}]}]};
  const d=deferred(),h=harness({respond:(url,c)=>url==='/api/mvp3/saved-quotes'&&c.method==='POST'?d.promise:url==='/api/grid/recommend'?ai:standard(url)});await h.flow.submit('조건');h.flow.select(0);assert.equal(h.w.document.querySelector('[data-action="final"]'),null);h.click('save');await until(()=>h.w.document.querySelector('section[data-keep-page] [data-kact=submit]'));assert.equal(h.w.document.querySelector('[data-keep-dialog]'),null);h.w.document.querySelector('section[data-keep-page] [data-kact=submit]').click();await until(()=>h.calls.some(c=>c.url==='/api/mvp3/saved-quotes'&&c.method==='POST'));const call=h.calls.find(c=>c.url==='/api/mvp3/saved-quotes'&&c.method==='POST'),raw=h.journal();h.click('home');assert.equal(call.signal.aborted,false);assert.equal(h.journal(),raw);d.reject(Error('mock network'));await until(()=>h.flow.state.phase===null);assert.equal(h.flow.state.saveState,'uncertain');assert.equal(h.journal(),raw);assert.equal(h.flow.state.screen,'detail');assert.ok(h.w.document.querySelector('#recovery, [data-action="recover"]'),'unknown save keeps the explicit recovery path');assert.equal(h.journal(),raw);assert.equal(h.calls.filter(c=>c.url==='/api/mvp3/saved-quotes'&&c.method==='POST').length,1);assert.deepEqual(Object.keys(call.body).sort(),['expected_price','product_code','request_id','state']);
});
test('unknown explicit recover uses exact same UUID payload binding; owner change and 409 keep existing policies',async()=>{
  const raw=JSON.stringify(pending),h=harness({journal:raw,respond:(url,c)=>c.method==='POST'?{ok:true,quote}:empty});h.click('new');assert.equal(h.postCount(),0);h.click('recover');await until(()=>h.flow.state.phase===null);assert.deepEqual(h.calls.find(c=>c.method==='POST').body,pending.payload);assert.equal(h.journal(),null);assert.equal(h.flow.state.saveState,'saved');
  const owner=harness({journal:raw});owner.w.localStorage.setItem(KEY,'b'.repeat(64));owner.click('recover');await until(()=>owner.flow.state.phase===null);assert.equal(owner.postCount(),0);assert.equal(owner.journal(),raw);assert.equal(owner.flow.state.error.code,'owner_changed');
  const conflict=harness({journal:raw,respond:(url,c)=>c.method==='POST'?{httpStatus:409,data:{detail:{error:'price_changed'}}}:empty});conflict.click('recover');await until(()=>conflict.flow.state.phase===null);assert.equal(conflict.flow.state.needsRefresh,true);assert.equal(conflict.flow.state.saveState,'failed');assert.equal(conflict.journal(),null);
});
test('saved empty/failure/loading are distinct and actual retry is GET only',async()=>{
  let n=0;const d=deferred(),h=harness({hash:'#saved',respond:()=>++n===1?d.promise:empty});assert.match(h.w.document.querySelector('#view').textContent,/불러오는 중/);assert.doesNotMatch(h.w.document.querySelector('#view').textContent,/보관된 견적이 없어요/);d.resolve({httpStatus:503,data:{detail:{error:'unavailable'}}});await until(()=>h.flow.state.phase===null);assert.ok(h.w.document.querySelector('[role="alert"]'));assert.doesNotMatch(h.w.document.querySelector('#view').textContent,/보관된 견적이 없어요/);h.click('retry');await until(()=>h.flow.state.phase===null);assert.match(h.w.document.querySelector('#view').textContent,/보관된 견적이 없어요/);assert.equal(n,2);assert.equal(h.postCount(),0);
});
test('server missing/silent/non-PC guards and new reset remain explicit; product link never invents data',async()=>{
  for(const guard of [{missing:['budget']},{silent:true},{pc_related:false}]){const h=harness({respond:()=>({...parsed,...guard})});edit(h,'요청');send(h);await until(()=>h.flow.state.phase===null);assert.equal(h.calls.length,1);assert.equal(h.flow.state.screen,'welcome');}
  const h=harness({hash:''});h.click('home');assert.equal(h.calls.length,0);assert.equal(surface(h),'consultation');await h.flow.submit('조건');assert.equal(h.flow.state.screen,'results');h.click('home');assert.equal(h.flow.state.screen,'welcome');assert.ok(h.flow.state.recommendation,'the brand link keeps the recommendation');assert.equal(h.calls.length,2);h.click('new');assert.equal(h.flow.state.talk,null);assert.equal(h.input.value,'');assert.equal(h.flow.state.selected,null);assert.equal(surface(h),'consultation');
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
// 첫 화면 「새로 구성된 PC」: welcome-pcs.js 가 준 목록만 그리고, 도착하면 첫 화면을 다시 그린다. 상세·추천 화면에는 싣지 않는다.
test('the welcome screen shows the curated PC list only when welcome-pcs provides one',async()=>{
  const h=harness({hash:''}),d=h.w.document;assert.equal(d.querySelector('.welcome-pcs'),null);
  h.w.MVP3WelcomePcs={html:()=>'<section class="welcome-pcs"><a class="welcome-pc" href="new-pcs.html#c1">맞춘 PC</a></section>'};
  h.w.dispatchEvent(new h.w.Event('mvp3:welcome-pcs'));assert.equal(d.querySelector('#view .welcome-pcs a').getAttribute('href'),'new-pcs.html#c1');assert.equal(h.calls.length,0);
  await h.flow.submit('조건');assert.equal(h.flow.state.screen,'results');assert.equal(d.querySelector('.welcome-pcs'),null);
});

test('mobile curated PCs precede the same collapsed consultation DOM and can be expanded',()=>{
  const h=harness({mobile:true}),d=h.w.document,input=h.input;
  h.w.MVP3WelcomePcs={html:()=>'<section class="welcome-pcs"><h2 tabindex="-1">새로 구성된 PC</h2><a href="new-pcs.html#c1">구성 보기</a></section>'};
  h.w.dispatchEvent(new h.w.Event('mvp3:welcome-pcs'));
  assert.equal(d.querySelector('.workspace').firstElementChild,d.querySelector('.content'));
  assert.equal(d.querySelector('#chat-body').hidden,true);assert.equal(d.querySelector('#chat-toggle').getAttribute('aria-expanded'),'false');
  assert.equal(d.querySelector('.welcome-card'),null);assert.equal(d.querySelector('#request'),input);
  d.querySelector('#chat-toggle').click();assert.equal(d.querySelector('#chat-body').hidden,false);
  assert.equal(d.querySelector('#chat-toggle').getAttribute('aria-expanded'),'true');assert.equal(h.calls.length,0);
});

test('product arrival and responsive moves preserve the typed consultation, selection and focus',()=>{
  const h=harness({mobile:true}),d=h.w.document,input=h.input;
  edit(h,'입력 중인 조건과 예산');input.focus();input.setSelectionRange(3,7,'backward');
  h.w.MVP3WelcomePcs={html:()=>'<section class="welcome-pcs"><h2 tabindex="-1">새로 구성된 PC</h2></section>'};
  h.w.dispatchEvent(new h.w.Event('mvp3:welcome-pcs'));
  for(const small of [false,true,false,true]){
    h.setMobile(small);assert.equal(d.querySelector('#request'),input);assert.equal(input.value,'입력 중인 조건과 예산');
    assert.equal(d.activeElement,input);assert.equal(input.selectionStart,3);assert.equal(input.selectionEnd,7);assert.equal(input.selectionDirection,'backward');
    assert.equal(d.querySelector('#chat-body').hidden,false);
    assert.equal(d.querySelector('.workspace').firstElementChild,d.querySelector(small?'.content':'.chat'));
  }
  assert.equal(h.calls.length,0);
});

test('a mobile home without public PCs keeps the consultation and its original guidance',()=>{
  const h=harness({mobile:true}),d=h.w.document;
  assert.equal(d.querySelector('.workspace').firstElementChild,d.querySelector('.chat'));
  assert.equal(d.querySelector('#chat-body').hidden,false);assert.ok(d.querySelector('.welcome-card'));
  h.w.MVP3WelcomePcs={html:()=>''};h.w.dispatchEvent(new h.w.Event('mvp3:welcome-pcs'));
  assert.equal(d.body.classList.contains('has-welcome-pcs'),false);assert.equal(h.calls.length,0);
});
test('first question header hides once the customer has spoken (2026-10-12 owner report)',async()=>{
  const h=harness(),intro=h.w.document.querySelector('#chat-body .chat-intro');assert.equal(intro.hidden,false);
  await h.flow.submit('게임용 PC 추천해줘');await until(()=>h.flow.state.phase===null);assert.equal(intro.hidden,true);
});
test('detail opened from the talk screen hides the old consultation panel; direct entry keeps it (2026-10-12 card review)',()=>{
  const css=read('styles.css');assert.match(css,/body\[data-from-talk="1"\] \.workspace>\.chat\{display:none\}/);
  assert.match(css,/@media\(max-width:760px\)\{body \.topbar\{flex-wrap:wrap\}body \.topbar nav\{flex-wrap:wrap;max-width:100%\}body \.topbar nav>\*\{white-space:nowrap\}\}/);
  const a=harness({fromTalk:true});assert.equal(a.w.document.body.dataset.fromTalk,'1');assert.equal(a.w.document.querySelector('#back-to-talk').hidden,false);
  const b=harness();assert.equal(b.w.document.body.dataset.fromTalk,undefined);assert.equal(b.w.document.querySelector('#back-to-talk').hidden,true);
});
