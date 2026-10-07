'use strict';
// Executes the actual auth IIFE with mock fetch/storage and jsdom only.
// Reuses the existing test-only jsdom runtime; no real HTTP, browser identity,
// auth backend, DB, commerce owner credentials or production data is accessed.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {JSDOM}=require('jsdom');
const source=fs.readFileSync(path.join(__dirname,'..','auth.js'),'utf8');
const READY='회원 본인 확인 기능을 준비 중입니다. 현재 로그인·가입을 이용할 수 없습니다.';
const context=(id='101',revision='1',session='11111111-1111-4111-8111-111111111111')=>({member_id:id,session_context_id:session,principal_revision:revision});
const me=(id='101',overrides={},ctx={})=>({auth_version:2,phase:'authenticated',authenticated:true,
 member:{member_id:id,email:'member@example.test',nickname:'확인된 회원',via:'email',...overrides},auth_context:{...context(id),...ctx}});
const legacyMe=()=>({authenticated:true,member:{member_id:1,email:'member@example.test',nickname:'legacy',via:'email'}});
const signedOutV2=()=>({auth_version:2,phase:'signed-out',authenticated:false,member:null,auth_context:null});
const closedV2=()=>({...signedOutV2(),phase:'unavailable',reason:'auth_unavailable'});
const login=(id=1,overrides={})=>({state:'active',member:{id,email:'member@example.test',nickname:'확인된 회원',via:'email',...overrides}});
const out=()=>({authenticated:false,member:null});
const ready=()=>({authenticated:false,member:null,note:READY+' 상담·추천은 로그인 없이 이용할 수 있습니다.'});
const response=(body,status=200)=>({ok:status>=200&&status<300,status,json:async()=>body});
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
async function settle(){for(let i=0;i<6;i++)await new Promise(resolve=>setImmediate(resolve));}
function harness(t,initial=out(),options={}){
 const dom=new JSDOM('<!doctype html><html><body></body></html>',{url:'https://preview.test/'+(options.page||'main-landing.html'),runScripts:'outside-only'});
 const w=dom.window,calls=[],writes=[];
 if(options.Channel)w.BroadcastChannel=options.Channel;
 if(options.setup)options.setup(w);
 Object.defineProperty(w.document,'readyState',{value:'complete'});
 if(options.cached)w.localStorage.setItem('popcorn-member',JSON.stringify(options.cached));
 w.localStorage.setItem('popcorn-saved-quotes','keep-quote');w.localStorage.setItem('guest-owner-test','keep-owner');
 const originalSet=w.Storage.prototype.setItem;
 w.Storage.prototype.setItem=function(key,value){writes.push({key,value});return originalSet.call(this,key,value);};
 let responder=async()=>response(initial);
 w.fetch=(url,opts)=>{calls.push({url,opts});return responder(url,opts);};
 w.eval(source);
 t.after(()=>dom.window.close());
 const api=w.popcornAuth;
 return {w,api,calls,writes,setResponder(fn){responder=fn;},async start(){await settle();},
  open(after){api.open('login',after);return w.document.getElementById('pa-ov');},
  submit(){w.document.getElementById('pa-email').value='input@example.test';w.document.getElementById('pa-go').click();},
  cache(){return w.localStorage.getItem('popcorn-member');},fab(){return w.document.getElementById('pa-fab');},
  assertNoSuccess(callbacks=0){assert.equal(callbacks,0);assert.equal(api.member(),null);assert.equal(this.cache(),null);assert.equal(writes.filter(x=>x.key==='popcorn-member').length,0);assert.equal(this.fab()?.textContent.includes('마이페이지')||false,false);}
 };
}

test('stale localStorage never authenticates even before initial me resolves; independent keys stay intact',async t=>{
 const h=harness(t,out(),{cached:{nick:'old',email:'old@example.test',live:true}});
 assert.equal(h.api.member(),null);assert.equal(h.cache(),null);
 await h.start();h.assertNoSuccess();
 assert.equal(h.w.localStorage.getItem('popcorn-saved-quotes'),'keep-quote');assert.equal(h.w.localStorage.getItem('guest-owner-test'),'keep-owner');
});

test('structured auth_unavailable 503 displays safe preparation text, disables issuance, never succeeds',async t=>{
 const h=harness(t);await h.start();let callbacks=0;h.open(()=>callbacks++);
 h.setResponder(async()=>response({detail:{error:'auth_unavailable',detail:'<img src=x onerror=alert(1)>secret@example.test'}},503));
 h.submit();await settle();h.assertNoSuccess(callbacks);
 const ov=h.w.document.getElementById('pa-ov');assert.match(ov.textContent,/현재 로그인·가입을 이용할 수 없습니다/);
 assert.equal(ov.textContent.includes('[object Object]'),false);assert.equal(ov.textContent.includes('secret@example.test'),false);
 assert.equal(ov.querySelectorAll('img,script').length,0);assert.equal(ov.querySelector('#pa-go').disabled,true);
 assert.equal(ov.querySelector('#pa-email').disabled,true);
 ov.querySelector('[data-tab="join"]').click();assert.equal(ov.querySelector('#pa-go').textContent,'로그인·가입 준비 중');
});

for(const [name,responder] of [
 ['network rejection',()=>Promise.reject(new Error('raw secret@example.test'))],
 ['synchronous fetch throw',()=>{throw new Error('raw secret');}],
 ['invalid JSON',async()=>({ok:true,status:200,json:async()=>{throw new Error('raw parse');}})],
 ['missing response',async()=>null],
 ['malformed 200',async()=>response({member:{nickname:'fake',email:'fake@example.test'},created:true})],
 ['wrong status 201',async()=>response(login(),201)],
 ['raw 500 error',async()=>response({detail:'<script>raw secret@example.test</script>'},500)],
 ['array 200 body',async()=>response([login()])]
])test('login '+name+' never creates a mock member or calls success',async t=>{
 const h=harness(t);await h.start();let callbacks=0;h.open(()=>callbacks++);h.setResponder(responder);
 h.submit();await settle();h.assertNoSuccess(callbacks);
 const ov=h.w.document.getElementById('pa-ov');assert.ok(ov);assert.equal(ov.textContent.includes('raw'),false);
 assert.equal(ov.textContent.includes('secret@example.test'),false);assert.equal(ov.querySelectorAll('script,img').length,0);
 assert.equal(h.calls.filter(c=>c.url==='/api/auth/login').length,1);
});

test('known login input rejection gives plain text and keeps input retry without saving identity',async t=>{
 const h=harness(t);await h.start();h.open();h.setResponder(async()=>response({detail:'<b>raw</b>'},400));h.submit();await settle();
 h.assertNoSuccess();assert.match(h.w.document.getElementById('pa-err').textContent,/입력 정보를 확인/);
 assert.equal(h.w.document.getElementById('pa-go').disabled,false);
});

test('legacy active login receipt stays closed without inventing a v2 login/me success flow',async t=>{
 const h=harness(t);await h.start();let callbacks=0;h.open(()=>callbacks++);
 h.setResponder(async url=>response(url==='/api/auth/login'?login():ready()));
 h.submit();await settle();h.assertNoSuccess(callbacks);
 assert.equal(h.calls.filter(c=>c.url==='/api/auth/me').length,1);
});

test('mismatched member id in login/me cannot publish either identity',async t=>{
 const h=harness(t);await h.start();let callbacks=0;h.open(()=>callbacks++);
 h.setResponder(async url=>response(url==='/api/auth/login'?login(1):me(2)));
 h.submit();await settle();h.assertNoSuccess(callbacks);
});

test('strict v2 mock me alone exposes a defensive display copy without a login callback',async t=>{
 const h=harness(t,me());await h.start();assert.equal(h.api.member().live,true);
 const copy=h.api.member();copy.nick='mutated';assert.equal(h.api.member().nick,'확인된 회원');
 assert.match(h.fab().textContent,/마이페이지/);assert.equal(h.writes.filter(x=>x.key==='popcorn-member').length,1);
});

test('initial mefalse preparation clears stale MY cache and does not auto-open repeated expiry modals',async t=>{
 const h=harness(t,ready(),{page:'my-orders.html',cached:{email:'old@example.test',nick:'old'}});await h.start();
 h.api.expired();h.api.expired();await settle();h.assertNoSuccess();assert.equal(h.w.document.getElementById('pa-ov'),null);
 assert.equal(h.fab().textContent,'로그인·가입 준비 중');assert.equal(h.calls.length,1);
 h.open();assert.match(h.w.document.getElementById('pa-note').textContent,/로그인·가입을 이용할 수 없습니다/);
 assert.equal(h.w.document.body.textContent.includes('이메일 주소만'),false);assert.equal(h.w.document.body.textContent.includes('가입하고 시작하기'),false);
});

test('social preparation has no email shortcut and never starts a login request',async t=>{
 const h=harness(t,ready());await h.start();const ov=h.open();ov.querySelector('[data-social="카카오"]').click();
 assert.match(ov.querySelector('#pa-err').textContent,/로그인 없이/);assert.equal(ov.querySelector('#pa-err').textContent.includes('이메일로'),false);
 assert.equal(h.calls.filter(c=>c.url==='/api/auth/login').length,0);h.assertNoSuccess();
});

test('sync failure removes previously confirmed identity; primary retry only reads me',async t=>{
 const h=harness(t,me());await h.start();assert.ok(h.api.member());
 h.setResponder(()=>Promise.reject(new Error('raw network')));assert.equal(await h.api.sync(),null);
 assert.equal(h.api.member(),null);assert.equal(h.cache(),null);assert.equal(h.fab().textContent,'회원 상태 확인');
 const ov=h.open();assert.equal(ov.querySelector('#pa-go').textContent,'회원 상태 다시 확인');
 const count=h.calls.length;ov.querySelector('#pa-go').click();await settle();assert.equal(h.calls.length,count+1);
 assert.equal(h.calls.at(-1).url,'/api/auth/me');assert.equal(h.calls.filter(c=>c.url==='/api/auth/login').length,0);
});

for(const [name,data] of [
 ['truthy string authenticated',{...me(),authenticated:'true'}],
 ['missing false member',{authenticated:false}],
 ['false with identity',{...me(),phase:'signed-out',authenticated:false}],
 ['HTML identity',me('101',{nickname:'<img src=x onerror=alert(1)>'})],
 ['unsafe numeric id',me(Number.MAX_SAFE_INTEGER+1)],
 ['HTML email',me('101',{email:'<script>@example.test'})],
 ['object false note',{authenticated:false,member:null,note:{error:'raw'}}]
])test('me rejects '+name+' without authentication or HTML/raw identity exposure',async t=>{
 const h=harness(t,data,{cached:{nick:'old',email:'old@example.test'}});await h.start();h.assertNoSuccess();h.open();
 assert.equal(h.w.document.body.querySelectorAll('img,script').length,0);assert.equal(h.w.document.body.textContent.includes('onerror'),false);
});

test('closed login modal cannot restore a late identity or call its callback',async t=>{
 const h=harness(t);await h.start();const late=deferred();let callbacks=0;h.open(()=>callbacks++);
 h.setResponder(()=>late.promise);h.submit();await settle();h.w.document.getElementById('pa-x').click();
 late.resolve(response(login()));await settle();h.assertNoSuccess(callbacks);
 assert.equal(h.calls.filter(c=>c.url==='/api/auth/me').length,1);
});

test('replacement modal invalidates the old login and callback',async t=>{
 const h=harness(t);await h.start();const late=deferred();let callbacks=0;h.open(()=>callbacks++);
 h.setResponder(()=>late.promise);h.submit();await settle();const newer=h.open(()=>callbacks++);
 late.resolve(response(login()));await settle();h.assertNoSuccess(callbacks);
 assert.equal(h.w.document.getElementById('pa-ov'),newer);
});

test('expiry invalidates a genuinely pending me after a modal closes',async t=>{
 const h=harness(t);await h.start();const late=deferred();h.open();
 h.setResponder(()=>late.promise);const pending=h.api.sync();await settle();
 h.w.document.getElementById('pa-x').click();h.api.expired();late.resolve(response(me()));
 assert.equal(await pending,null);h.assertNoSuccess();
});

test('latest sync wins; late previously authenticated response cannot override mefalse',async t=>{
 const h=harness(t);await h.start();const old=deferred(),newer=deferred();let n=0;
 h.setResponder(()=>n++===0?old.promise:newer.promise);const first=h.api.sync(),second=h.api.sync();await settle();
 newer.resolve(response(ready()));assert.equal(await second,false);old.resolve(response(me()));assert.equal(await first,null);
 h.assertNoSuccess();assert.equal(h.fab().textContent,'로그인·가입 준비 중');
});

test('new sync invalidates pending login rather than invoking its closed generation callback',async t=>{
 const h=harness(t);await h.start();const old=deferred();let callbacks=0;h.open(()=>callbacks++);
 h.setResponder(url=>url==='/api/auth/login'?old.promise:Promise.resolve(response(ready())));
 h.submit();await settle();assert.equal(await h.api.sync(),false);old.resolve(response(login()));await settle();h.assertNoSuccess(callbacks);
});

test('logout preserves POST and local clear, blocks sync/login while pending, cannot restore old me',async t=>{
 const h=harness(t,me());await h.start();const old=deferred(),logout=deferred();
 h.setResponder(url=>url==='/api/auth/logout'?logout.promise:old.promise);
 const syncing=h.api.sync();await settle();const leaving=h.api.logout();await settle();
 assert.equal(h.api.member(),null);assert.equal(h.cache(),null);assert.equal(await h.api.sync(),null);
 h.open();h.submit();old.resolve(response(me()));assert.equal(await syncing,null);logout.resolve(response({ok:true}));await leaving;
 assert.equal(h.api.member(),null);assert.equal(h.cache(),null);
 const calls=h.calls.filter(c=>c.url==='/api/auth/logout');assert.equal(calls.length,1);assert.equal(calls[0].opts.method,'POST');
 assert.equal(h.calls.filter(c=>c.url==='/api/auth/login').length,0);assert.equal(h.w.document.getElementById('pa-toast').textContent,'로그아웃했습니다');
 assert.equal(h.w.localStorage.getItem('guest-owner-test'),'keep-owner');
});

test('logout invalidates pending login and its success callback even when that response arrives later',async t=>{
 const h=harness(t);await h.start();const old=deferred();let callbacks=0;h.open(()=>callbacks++);
 h.setResponder(url=>url==='/api/auth/login'?old.promise:Promise.resolve(response({ok:true})));
 h.submit();await settle();await h.api.logout();old.resolve(response(login()));await settle();h.assertNoSuccess(callbacks);
});

test('failed logout still clears local state but does not claim server logout success',async t=>{
 const h=harness(t,me());await h.start();h.setResponder(()=>Promise.reject(new Error('raw failure')));await h.api.logout();
 assert.equal(h.api.member(),null);assert.equal(h.cache(),null);assert.match(h.w.document.getElementById('pa-toast').textContent,/서버 로그아웃 상태는 확인하지 못했습니다/);
});

// Historical 32+16 evidence is preserved separately. Positive me fixtures now use accepted C1 v2.
// Existing keyboard/UI invariants remain; obsolete post-login me cases use genuine pending requests.
function keyboard(h,key,shiftKey=false){
 const event=new h.w.KeyboardEvent('keydown',{key,shiftKey,bubbles:true,cancelable:true});
 h.w.document.activeElement.dispatchEvent(event);return event;
}
function pageButton(h,id){const b=h.w.document.createElement('button');b.id=id;b.textContent=id;h.w.document.body.appendChild(b);return b;}

test('prepared dialog initially focuses its first enabled control and exposes dialog semantics',async t=>{
 const h=harness(t,ready());await h.start();const ov=h.open(),dialog=ov.querySelector('#pa-dialog');
 assert.equal(h.w.document.activeElement.id,'pa-x');assert.equal(dialog.getAttribute('role'),'dialog');
 assert.equal(dialog.getAttribute('aria-modal'),'true');assert.equal(dialog.getAttribute('aria-describedby'),'pa-note');
 assert.equal(ov.querySelector('#pa-email').disabled,true);assert.equal(ov.querySelector('#pa-go').disabled,true);h.assertNoSuccess();
});

test('Tab and ShiftTab wrap prepared dialog without reaching disabled inputs or background controls',async t=>{
 const h=harness(t,ready());await h.start();const background=pageButton(h,'background'),ov=h.open();
 const close=ov.querySelector('#pa-x'),last=ov.querySelector('[data-social="네이버"]');
 assert.equal(keyboard(h,'Tab',true).defaultPrevented,true);assert.equal(h.w.document.activeElement,last);
 assert.equal(keyboard(h,'Tab').defaultPrevented,true);assert.equal(h.w.document.activeElement,close);
 keyboard(h,'Tab');assert.equal(h.w.document.activeElement,ov.querySelector('[data-tab="login"]'));
 keyboard(h,'Tab');assert.equal(h.w.document.activeElement,ov.querySelector('[data-tab="join"]'));
 background.focus();keyboard(h,'Tab');assert.equal(h.w.document.activeElement,close);
 background.focus();keyboard(h,'Tab',true);assert.equal(h.w.document.activeElement,last);
});

test('normal login and join focus enabled inputs; Tab skips hidden nickname in login',async t=>{
 const h=harness(t);await h.start();let ov=h.open();assert.equal(h.w.document.activeElement.id,'pa-email');
 keyboard(h,'Tab',true);assert.equal(h.w.document.activeElement,ov.querySelector('[data-social="네이버"]'));
 keyboard(h,'Tab');assert.equal(h.w.document.activeElement.id,'pa-email');
 keyboard(h,'Tab');assert.equal(h.w.document.activeElement.id,'pa-go');
 h.api.open('join');ov=h.w.document.getElementById('pa-ov');assert.equal(h.w.document.activeElement.id,'pa-nick');
 keyboard(h,'Tab');assert.equal(h.w.document.activeElement.id,'pa-email');
});

test('Tab excludes controls hidden by parents, visibility, opacity and aria disabled',async t=>{
 const h=harness(t);await h.start();const ov=h.open();
 ov.querySelector('#pa-email').parentElement.hidden=true;
 ov.querySelector('[data-tab="join"]').style.visibility='hidden';
 ov.querySelector('[data-social="네이버"]').style.opacity='0';
 ov.querySelector('[data-social="카카오"]').setAttribute('aria-disabled','true');
 ov.querySelector('#pa-x').focus();keyboard(h,'Tab');assert.equal(h.w.document.activeElement,ov.querySelector('[data-tab="login"]'));
 keyboard(h,'Tab');assert.equal(h.w.document.activeElement.id,'pa-x');
});

test('Escape closes and restores a genuine valid opener; keyboard listener is removed',async t=>{
 const h=harness(t,ready());await h.start();const opener=pageButton(h,'open-login');opener.focus();h.open();
 assert.equal(keyboard(h,'Escape').defaultPrevented,true);assert.equal(h.w.document.getElementById('pa-ov'),null);
 assert.equal(h.w.document.activeElement,opener);assert.equal(keyboard(h,'Tab').defaultPrevented,false);
});

for(const [name,invalidate] of [
 ['removed',b=>b.remove()],['disabled',b=>{b.disabled=true;}],['hidden',b=>{b.hidden=true;}],
 ['aria disabled',b=>b.setAttribute('aria-disabled','true')],['transparent',b=>{b.style.opacity='0';}]
])test('closing never restores focus to an opener that is '+name,async t=>{
 const h=harness(t,ready());await h.start();const opener=pageButton(h,'old-open'),other=pageButton(h,'other-control');
 opener.focus();const ov=h.open();invalidate(opener);other.focus();ov.querySelector('#pa-x').click();
 assert.equal(h.w.document.getElementById('pa-ov'),null);assert.equal(h.w.document.activeElement,other);
});

test('replacement modal preserves original opener without a focus bounce and removes each listener',async t=>{
 const h=harness(t);await h.start();const opener=pageButton(h,'original-open');opener.focus();
 let restored=0;const originalFocus=opener.focus.bind(opener);opener.focus=(...args)=>{restored++;return originalFocus(...args);};
 const d=h.w.document,add=d.addEventListener.bind(d),remove=d.removeEventListener.bind(d),added=[],removed=[];
 d.addEventListener=(type,fn,opts)=>{if(type==='keydown')added.push(fn);return add(type,fn,opts);};
 d.removeEventListener=(type,fn,opts)=>{if(type==='keydown')removed.push(fn);return remove(type,fn,opts);};
 const first=h.open();h.api.open('join');const second=d.getElementById('pa-ov');
 assert.notEqual(first,second);assert.equal(restored,0);assert.equal(added.length,2);assert.equal(removed.length,1);assert.equal(removed[0],added[0]);
 first.querySelector('#pa-x').click();assert.equal(d.getElementById('pa-ov'),second);
 keyboard(h,'Escape');assert.equal(restored,1);assert.equal(d.activeElement,opener);assert.equal(removed.length,2);assert.equal(removed[1],added[1]);
});

test('empty enabled control set focuses dialog rather than escaping to background',async t=>{
 const h=harness(t,ready());await h.start();const ov=h.open();ov.querySelectorAll('button,input').forEach(el=>{el.disabled=true;});
 keyboard(h,'Tab');assert.equal(h.w.document.activeElement,ov.querySelector('#pa-dialog'));
 keyboard(h,'Tab',true);assert.equal(h.w.document.activeElement,ov.querySelector('#pa-dialog'));
 keyboard(h,'Escape');assert.equal(h.w.document.getElementById('pa-ov'),null);
});

test('pending phase moves focus off disabled input; a current 503 never steals another modal control focus',async t=>{
 const h=harness(t);await h.start();const late=deferred(),ov=h.open();h.setResponder(()=>late.promise);
 h.submit();assert.equal(h.w.document.activeElement.id,'pa-x');
 const tab=ov.querySelector('[data-tab="join"]');tab.focus();
 late.resolve(response({detail:{error:'auth_unavailable'}},503));await settle();
 assert.equal(h.w.document.activeElement,tab);assert.equal(ov.querySelector('#pa-go').disabled,true);h.assertNoSuccess();
});

test('Escape during login restores opener and late login cannot steal subsequent page focus',async t=>{
 const h=harness(t);await h.start();const opener=pageButton(h,'start-login'),other=pageButton(h,'next-action'),late=deferred();let callbacks=0;
 opener.focus();h.open(()=>callbacks++);h.setResponder(()=>late.promise);h.submit();await settle();keyboard(h,'Escape');
 assert.equal(h.w.document.activeElement,opener);other.focus();late.resolve(response(login()));await settle();
 assert.equal(h.w.document.activeElement,other);h.assertNoSuccess(callbacks);assert.equal(keyboard(h,'Tab').defaultPrevented,false);
});

test('expiry of a pending me cannot restore focus or identity after a newer modal opens',async t=>{
 const h=harness(t);await h.start();const late=deferred();h.open();h.setResponder(()=>late.promise);
 const pending=h.api.sync();await settle();keyboard(h,'Escape');h.api.expired();
 const newer=h.open(),focused=h.w.document.activeElement;late.resolve(response(me()));assert.equal(await pending,null);await settle();
 assert.equal(h.w.document.getElementById('pa-ov'),newer);assert.equal(h.w.document.activeElement,focused);h.assertNoSuccess();
});

test('component styles remain installed once after modal close and never target unrelated layout',async t=>{
 const h=harness(t,ready());await h.start();h.open();keyboard(h,'Escape');h.open();
 assert.equal(h.w.document.querySelectorAll('#pa-legibility').length,1);
 const sheet=h.w.document.getElementById('pa-legibility').sheet;
 assert.ok(sheet.cssRules.length>0);
 for(const rule of sheet.cssRules)assert.ok(rule.selectorText.replace(/:is\([^)]*\)/g,':is').split(',').every(s=>/^#pa-(ov|fab|toast)\b/.test(s.trim())),rule.selectorText);
});


// C3 session boundary coverage. Every fetch is the harness mock, never operational auth.
function plain(v){return JSON.parse(JSON.stringify(v));}
function channelBus(){
 const instances=[],sent=[];
 class Channel{
  constructor(name){this.name=name;this.onmessage=null;this.closed=false;instances.push(this);}
  postMessage(data){sent.push(plain(data));for(const peer of instances){
   if(peer!==this&&!peer.closed&&peer.name===this.name&&peer.onmessage)peer.onmessage({data:plain(data)});
  }}
  close(){this.closed=true;}
 }
 return {Channel,instances,sent};
}
function storageSignal(h,key='popcorn-auth-invalidation-v2',value='invalidate-v2'){
 h.w.dispatchEvent(new h.w.StorageEvent('storage',{key,newValue:value}));
}
test('snapshot is frozen, has defensive nested C1 DTO copies and subscribe is synchronous/idempotent',async t=>{
 const h=harness(t,me('9007199254740993',{email:null,via:'kakao'}));let initial;
 const seen=[],stop=h.api.subscribe(s=>{seen.push(s);initial=s;});
 assert.equal(seen.length,1);assert.equal(initial.phase,'checking');assert.equal(initial.member,null);
 await h.start();const s=h.api.getSnapshot();assert.equal(s.phase,'authenticated');
 assert.equal(s.member.member_id,'9007199254740993');assert.equal(s.member.email,null);
 assert.ok(Object.isFrozen(s)&&Object.isFrozen(s.member)&&Object.isFrozen(s.auth_context));
 assert.throws(()=>{s.member.nickname='bad';},TypeError);assert.throws(()=>{s.auth_context.principal_revision='2';},TypeError);
 assert.notEqual(s,h.api.getSnapshot());assert.notEqual(s.member,h.api.getSnapshot().member);
 const count=seen.length;stop();stop();h.api.expired();assert.equal(seen.length,count);
 assert.throws(()=>h.api.subscribe(null),/listener/);
});
test('sync wipes and notifies before fetch or first await, then publishes current context',async t=>{
 const h=harness(t,me());await h.start();const events=[];h.api.subscribe(s=>events.push(plain(s)));
 const previous=h.api.getSnapshot().epoch,late=deferred();let inspected=false;
 h.setResponder(()=>{inspected=true;assert.equal(h.api.member(),null);assert.equal(h.cache(),null);
  assert.equal(events.at(-1).phase,'checking');assert.equal(events.at(-1).auth_context,null);return late.promise;});
 const pending=h.api.sync();assert.equal(inspected,false);assert.equal(h.api.member(),null);
 assert.equal(events.at(-1).epoch,previous+1);await settle();assert.equal(inspected,true);
 late.resolve(response(me('102',{}, {principal_revision:'2'})));assert.equal(await pending,true);
 assert.equal(h.api.getSnapshot().member.member_id,'102');
});
test('subscriber exception and unsubscribe during delivery cannot block other synchronous wipes',async t=>{
 const h=harness(t,me());await h.start();let b=0,c=0,stopB=()=>{};
 const stopA=h.api.subscribe(s=>{if(s.phase==='checking')stopB();throw new Error('consumer failure');});
 stopB=h.api.subscribe(()=>b++);h.api.subscribe(()=>c++);const beforeB=b,beforeC=c;
 h.setResponder(async()=>response(out()));const p=h.api.sync();
 assert.equal(b,beforeB);assert.equal(c,beforeC+1);await p;stopA();
});
test('reentrant subscriber invalidation never delivers stale authenticated state or returns true',async t=>{
 const h=harness(t);await h.start();const other=[];
 h.api.subscribe(s=>{if(s.phase==='authenticated')h.api.expired();});
 h.api.subscribe(s=>other.push(s.phase));h.setResponder(async()=>response(me()));
 assert.equal(await h.api.sync(),null);assert.equal(h.api.member(),null);assert.equal(other.includes('authenticated'),false);
 assert.equal(h.api.getSnapshot().phase,'error');
});
test('A-B-A and revision changes reject late same-member responses using local epochs',async t=>{
 const h=harness(t,me('101'));await h.start();const late=deferred();
 h.setResponder(()=>late.promise);const first=h.api.sync();await settle();
 h.setResponder(async()=>response(me('102',{}, {principal_revision:'2'})));assert.equal(await h.api.sync(),true);
 h.setResponder(async()=>response(me('101',{}, {principal_revision:'3',session_context_id:'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'})));
 assert.equal(await h.api.sync(),true);const current=h.api.getSnapshot();
 late.resolve(response(me('101')));assert.equal(await first,null);
 assert.deepEqual(plain(h.api.getSnapshot()),plain(current));assert.equal(current.auth_context.principal_revision,'3');
});
for(const id of ['1','9007199254740993','9223372036854775807'])test('canonical decimal ID accepted without numeric precision loss: '+id,async t=>{
 const h=harness(t,me(id));await h.start();assert.equal(h.api.getSnapshot().member.member_id,id);
});
for(const [name,mutate] of [
 ['numeric member ID',d=>{d.member.member_id=101;d.auth_context.member_id=101;}],
 ['leading zero',d=>{d.member.member_id='0101';d.auth_context.member_id='0101';}],
 ['zero',d=>{d.member.member_id='0';d.auth_context.member_id='0';}],
 ['negative',d=>{d.member.member_id='-1';d.auth_context.member_id='-1';}],
 ['overflow',d=>{d.member.member_id='9223372036854775808';d.auth_context.member_id='9223372036854775808';}],
 ['exponent',d=>{d.member.member_id='1e2';d.auth_context.member_id='1e2';}],
 ['surrounding whitespace',d=>{d.member.member_id=' 101';d.auth_context.member_id=' 101';}],
 ['context member mismatch',d=>{d.auth_context.member_id='102';}],
 ['missing context',d=>{delete d.auth_context;}],
 ['null context',d=>{d.auth_context=null;}],
 ['numeric revision',d=>{d.auth_context.principal_revision=1;}],
 ['zero revision',d=>{d.auth_context.principal_revision='0';}],
 ['leading-zero revision',d=>{d.auth_context.principal_revision='01';}],
 ['overflow revision',d=>{d.auth_context.principal_revision='9223372036854775808';}],
 ['uppercase UUID',d=>{d.auth_context.session_context_id='AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA';}],
 ['malformed UUID',d=>{d.auth_context.session_context_id='not-a-uuid';}],
 ['unknown via',d=>{d.member.via='dev';}],
 ['object via',d=>{d.member.via={value:'kakao'};}],
 ['numeric via',d=>{d.member.via=1;}],
 ['whitespace via',d=>{d.member.via=' kakao';}],
 ['unknown version',d=>{d.auth_version=3;}],
 ['truthy phase disagreement',d=>{d.phase='signed-out';}],
 ['extra top-level secret',d=>{d.token='test-only-secret';}],
 ['extra member secret',d=>{d.member.auth_subject='test-only-secret';}],
 ['extra context secret',d=>{d.auth_context.cookie='test-only-secret';}],
 ['empty nickname',d=>{d.member.nickname='';}],
 ['bad email',d=>{d.member.email='invalid';}]
])test('v2 me fails closed on '+name+' with all other fields otherwise valid',async t=>{
 const d=me();mutate(d);const h=harness(t,d);await h.start();h.assertNoSuccess();
 assert.equal(h.api.getSnapshot().phase,'error');assert.equal(h.api.getSnapshot().auth_context,null);
});
for(const via of ['kakao','naver','google','email'])test('accepted provider enum and null-email remain supported: '+via,async t=>{
 const h=harness(t,me('101',{via,email:null}));await h.start();assert.equal(h.api.getSnapshot().member.via,via);
});
for(const [name,d,phase] of [
 ['v2 signed out',signedOutV2(),'signed-out'],['v2 closed',closedV2(),'unavailable'],
 ['legacy authenticated',legacyMe(),'error'],['legacy closed',ready(),'unavailable'],
 ['extra closed field',{...closedV2(),cookie:'test-only-secret'},'error']
])test('closed/legacy boundary: '+name,async t=>{
 const h=harness(t,d);await h.start();h.assertNoSuccess();assert.equal(h.api.getSnapshot().phase,phase);
});
test('logout wipes synchronously; request remains POST/no-store and stores no context or secret',async t=>{
 const h=harness(t,me());await h.start();const before=h.api.getSnapshot().epoch,late=deferred(),seen=[];
 h.api.subscribe(s=>seen.push(plain(s)));h.setResponder(()=>{assert.equal(h.api.member(),null);return late.promise;});
 const pending=h.api.logout();assert.equal(h.api.getSnapshot().epoch,before+1);assert.equal(seen.at(-1).member,null);
 await settle();late.resolve(response({ok:true}));await pending;
 for(const c of h.calls){assert.equal(c.opts.cache,'no-store');assert.equal(c.opts.credentials,'same-origin');
  assert.ok(['/api/auth/me','/api/auth/login','/api/auth/logout'].includes(c.url));}
 const cacheWrites=h.writes.filter(x=>x.key==='popcorn-member');assert.equal(cacheWrites.length,1);
 assert.deepEqual(Object.keys(JSON.parse(cacheWrites[0].value)).sort(),['email','live','nick','via']);
 assert.equal(h.w.localStorage.getItem('popcorn-saved-quotes'),'keep-quote');
 assert.equal(h.w.localStorage.getItem('guest-owner-test'),'keep-owner');
});
test('login start, cancellation and expiry synchronously invalidate generations without callback authority',async t=>{
 const h=harness(t);await h.start();const seen=[];h.api.subscribe(s=>seen.push(plain(s)));
 const late=deferred();h.setResponder(()=>late.promise);let callbacks=0;h.open(()=>callbacks++);
 const before=h.api.getSnapshot().epoch;h.submit();assert.equal(seen.at(-1).epoch,before+1);assert.equal(seen.at(-1).member,null);
 h.w.document.getElementById('pa-x').click();assert.equal(seen.at(-1).epoch,before+2);
 h.api.expired();assert.equal(seen.at(-1).epoch,before+3);late.resolve(response(login()));await settle();h.assertNoSuccess(callbacks);
});
test('cross-tab invalidation contains no identity and triggers a single non-echoing fresh me',async t=>{
 const bus=channelBus(),a=harness(t,me(),{Channel:bus.Channel}),b=harness(t,me(),{Channel:bus.Channel});await a.start();await b.start();
 const late=deferred();b.setResponder(()=>late.promise);const count=b.calls.length;
 a.api.expired();assert.equal(b.api.member(),null);assert.equal(b.api.getSnapshot().phase,'checking');
 await settle();assert.equal(b.calls.length,count+1);assert.deepEqual(bus.sent,[{type:'invalidate',auth_version:2}]);
 late.resolve(response(signedOutV2()));await settle();assert.equal(b.api.getSnapshot().phase,'signed-out');assert.equal(bus.sent.length,1);
});
test('cross-tab rejects unexpected versions/fields and display-cache events cannot authorize a member',async t=>{
 const bus=channelBus(),h=harness(t,me(),{Channel:bus.Channel});await h.start();const before=h.api.getSnapshot();
 for(const data of [{type:'invalidate',auth_version:3},{type:'invalidate',auth_version:2,member:'101'},null,'invalidate'])
  bus.instances[0].onmessage({data});
 storageSignal(h,'popcorn-member',JSON.stringify({live:true}));storageSignal(h,undefined,'other');
 await settle();assert.deepEqual(plain(h.api.getSnapshot()),plain(before));assert.equal(h.calls.length,1);
});
test('storage fallback emits only an ephemeral constant and receiver wipes before refetch',async t=>{
 const h=harness(t,me());await h.start();h.api.expired();
 assert.deepEqual(h.writes.filter(x=>x.key==='popcorn-auth-invalidation-v2'),[{key:'popcorn-auth-invalidation-v2',value:'invalidate-v2'}]);
 assert.equal(h.w.localStorage.getItem('popcorn-auth-invalidation-v2'),null);
 const late=deferred();h.setResponder(()=>late.promise);storageSignal(h);
 assert.equal(h.api.member(),null);await settle();late.resolve(response(signedOutV2()));await settle();
 assert.equal(h.api.getSnapshot().phase,'signed-out');
 assert.equal(h.writes.filter(x=>x.key==='popcorn-auth-invalidation-v2').length,1);
});
test('channel/storage failures do not prevent local invalidation or expose errors',async t=>{
 class Broken{constructor(){throw new Error('test-only-secret');}}
 const h=harness(t,me(),{Channel:Broken});await h.start();
 h.w.Storage.prototype.setItem=()=>{throw new Error('test-only-secret');};
 h.api.expired();assert.equal(h.api.member(),null);assert.equal(h.cache(),null);
 assert.equal(h.w.document.body.textContent.includes('test-only-secret'),false);
});
test('remote invalidation during logout cannot resurrect the old epoch and refreshes after POST completion',async t=>{
 const bus=channelBus(),a=harness(t,me(),{Channel:bus.Channel}),b=harness(t,me(),{Channel:bus.Channel});await a.start();await b.start();
 const late=deferred();b.setResponder(url=>url==='/api/auth/logout'?late.promise:Promise.resolve(response(signedOutV2())));
 const leaving=b.api.logout();await settle();a.api.expired();assert.equal(b.api.member(),null);
 late.resolve(response({ok:true}));await leaving;assert.equal(b.api.getSnapshot().phase,'signed-out');
 assert.equal(b.calls.filter(c=>c.url==='/api/auth/logout').length,1);
});
test('pagehide closes channel and clears identity; bfcache restore reconnects and rejects old me',async t=>{
 const bus=channelBus(),h=harness(t,me(),{Channel:bus.Channel});await h.start();const late=deferred();
 h.setResponder(()=>late.promise);const old=h.api.sync();await settle();h.open();
 h.w.dispatchEvent(new h.w.PageTransitionEvent('pagehide',{persisted:true}));
 assert.equal(h.api.member(),null);assert.equal(h.w.document.getElementById('pa-ov'),null);assert.equal(bus.instances[0].closed,true);
 late.resolve(response(me()));assert.equal(await old,null);
 h.setResponder(async()=>response(me('102')));h.w.dispatchEvent(new h.w.PageTransitionEvent('pageshow',{persisted:true}));await settle();
 assert.equal(bus.instances.length,2);assert.equal(h.api.getSnapshot().member.member_id,'102');
});
test('hidden page wipes immediately; visible and window focus recheck, control focus does not',async t=>{
 const h=harness(t,me());await h.start();let visibility='visible';
 Object.defineProperty(h.w.document,'visibilityState',{get:()=>visibility,configurable:true});
 const old=deferred();h.setResponder(()=>old.promise);const pending=h.api.sync();await settle();
 visibility='hidden';h.w.document.dispatchEvent(new h.w.Event('visibilitychange'));assert.equal(h.api.member(),null);
 old.resolve(response(me()));assert.equal(await pending,null);const count=h.calls.length;
 h.setResponder(async()=>response(me('102')));visibility='visible';h.w.document.dispatchEvent(new h.w.Event('visibilitychange'));await settle();
 assert.equal(h.calls.length,count+1);assert.equal(h.api.getSnapshot().member.member_id,'102');
 pageButton(h,'focus-control').focus();await settle();assert.equal(h.calls.length,count+1);
 h.w.dispatchEvent(new h.w.Event('focus'));assert.equal(h.api.member(),null);await settle();assert.equal(h.calls.length,count+2);
});
