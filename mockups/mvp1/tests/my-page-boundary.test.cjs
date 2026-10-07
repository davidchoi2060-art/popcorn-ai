'use strict';
// Actual C6 IIFE with mock-only fetch/storage. Accepted C3 is a read dependency,
// evaluated only for integration cases; no C1/C3/C4/C5 suite or live server runs.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {JSDOM}=require('jsdom');
const html=fs.readFileSync(path.join(__dirname,'..','my-page.html'),'utf8');
const inline=[...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)].filter(m=>!/\bsrc\s*=/.test(m[1])&&m[2].trim());
assert.equal(inline.length,1);const source=inline[0][2];
const c3File=process.env.POPCORN_C3_AUTH_SOURCE||'D:/WORK/PopcornAI/outputs/customer-auth-c3-code-20261007/frozen/mockups/shared/auth.js';
const c3Bytes=fs.readFileSync(c3File);
assert.equal(crypto.createHash('sha256').update(c3Bytes).digest('hex'),'f2d6afab2bb9068e885142e3a8c54442ec94b0d826870cb12574baedf8773406','read accepted C3 only');
const NAME='PRIVATE-CURRENT-NAME',EMAIL='private-current@example.test';
const context=(id='101',revision='1',session='11111111-1111-4111-8111-111111111111')=>({member_id:id,session_context_id:session,principal_revision:revision});
const authState=(epoch=1,id='101',ctx={})=>({epoch,phase:'authenticated',
 member:{member_id:id,nickname:'AUTH-DISPLAY-CACHE',email:null,via:'kakao'},auth_context:{...context(id),...ctx}});
const closed=(phase='unavailable',epoch=1)=>({epoch,phase,member:null,auth_context:null});
const profile=(s=authState(),extra={})=>({auth_version:2,auth_context:{...s.auth_context},profile:{member_id:s.member.member_id,nickname:NAME,email:EMAIL,...extra}});
const me=(s=authState())=>({auth_version:2,phase:'authenticated',authenticated:true,member:{...s.member},auth_context:{...s.auth_context}});
const clone=v=>JSON.parse(JSON.stringify(v));
const response=(body,status=200,extra={})=>({ok:status===200,status,redirected:false,type:'basic',url:'https://preview.test/api/my/profile',
 headers:{get:name=>name.toLowerCase()==='cache-control'?'no-store':null},json:async()=>body,...extra});
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
async function settle(){for(let i=0;i<8;i++)await new Promise(r=>setImmediate(r));}
function harness(t,{state=closed(),responder=()=>response(profile()),integration=false,Channel,legacy=false}={}){
 const dom=new JSDOM(html,{url:'https://preview.test/mvp1/my-page.html',runScripts:'outside-only'}),w=dom.window;
 Object.defineProperty(w.document,'readyState',{value:'complete'});
 if(Channel)w.BroadcastChannel=Channel;
 const calls=[],aborts=[],authCalls=[],storageCalls=[];
 w.localStorage.setItem('popcorn-member',JSON.stringify({nick:NAME,email:EMAIL,live:true}));
 w.localStorage.setItem('popcorn-saved-quotes','keep-quote');w.localStorage.setItem('guest-owner-test','keep-owner');
 for(const method of ['getItem','setItem','removeItem']){
  const original=w.Storage.prototype[method];
  w.Storage.prototype[method]=function(...args){storageCalls.push({method,key:args[0],value:args[1]});return original.apply(this,args);};
 }
 let respond=responder,s=clone(state),subscribers=new Set(),syncResponder=null;
 w.fetch=(url,options)=>{calls.push({url,options});options?.signal?.addEventListener('abort',()=>aborts.push(url));return respond(url,options);};
 const emit=value=>{s=clone(value);for(const listener of [...subscribers])listener(clone(s));};
 const stub={getSnapshot(){return clone(s);},subscribe(fn){authCalls.push('subscribe');subscribers.add(fn);fn(clone(s));let active=true;
  return ()=>{if(!active)return;active=false;authCalls.push('unsubscribe');subscribers.delete(fn);};},
  member(){authCalls.push('member');throw new Error('C6 must not consume cached member');},
  sync(){authCalls.push('sync');const epoch=s.epoch+1;emit(closed('checking',epoch));
   return syncResponder?syncResponder(epoch):Promise.resolve().then(()=>{emit(closed('unavailable',epoch));return false;});},
  expired(){authCalls.push('expired');emit(closed('error',s.epoch+1));},
  logout(){authCalls.push('logout');return Promise.resolve(null);},open(){authCalls.push('open');},toast(){authCalls.push('toast');}};
 w.popcornAuth=legacy?{member:stub.member,sync:stub.sync}:stub;
 if(integration)w.eval(c3Bytes.toString('utf8'));
 w.eval(source);t.after(()=>w.close());
 return {w,calls,aborts,authCalls,storageCalls,emit,setStateSilently(value){s=clone(value);},
  setResponder(fn){respond=fn;},setSync(fn){syncResponder=fn;},subscriberCount(){return subscribers.size;},
  title(){return w.document.getElementById('member-status-title').textContent;},retry(){return w.document.getElementById('member-retry');},
  event(name,persisted=false){w.dispatchEvent(new w.PageTransitionEvent(name,{persisted}));},
  noIdentity(){const body=w.document.body.textContent;for(const marker of [NAME,EMAIL,'AUTH-DISPLAY-CACHE','PRIVATE-ORDER-ROW','MALL-2201','OTHER-NAME'])assert.equal(body.includes(marker),false,marker);
   assert.equal(w.document.getElementById('my-avatar').textContent.includes(NAME),false);},
  otherFeaturesClosed(){const body=w.document.body.textContent;
   assert.equal(body.includes('아직 주문 내역이 없습니다'),false);assert.equal(body.includes('아직 등록한 후기가 없습니다'),false);
   assert.equal(body.includes('연결 완료'),false);assert.match(w.document.getElementById('orders-box').textContent,/조회하지 않았/);
   assert.match(w.document.getElementById('reviews-box').textContent,/조회하지 않았/);
   assert.match(w.document.getElementById('map-pill').textContent,/확인 전/);
   const privateButtons=[...w.document.querySelectorAll('main button')].filter(b=>b.id!=='member-retry');
   assert.equal(privateButtons.length,8);assert.ok(privateButtons.every(b=>b.disabled));assert.equal(w.document.getElementById('my-logout').disabled,true);
   assert.ok([...w.document.querySelectorAll('main a')].every(a=>!a.hasAttribute('href')&&a.getAttribute('aria-disabled')==='true'));
   assert.ok(calls.every(c=>['/api/my/profile',...(integration?['/api/auth/me']:[])].includes(c.url)));
   assert.ok(calls.every(c=>c.options?.method==='GET'||(integration&&c.url==='/api/auth/me'&&!c.options?.method)));
   assert.equal(authCalls.includes('member'),false);assert.equal(authCalls.includes('logout'),false);
  }
 };
}
test('initial shared checking never reads cache or opens profile, account, map, review or orders',async t=>{
 const h=harness(t,{state:closed('checking')});h.noIdentity();assert.match(h.title(),/확인 중/);await settle();
 assert.equal(h.calls.length,0);h.otherFeaturesClosed();assert.deepEqual(h.storageCalls,[]);assert.deepEqual(h.authCalls,['subscribe']);
});
for(const [phase,title] of [['signed-out',/로그인이 필요/],['unavailable',/준비 중/],['error',/확인하지 못/]])
 test('shared '+phase+' leaves all private panels unqueried',async t=>{
  const h=harness(t,{state:closed(phase)});await settle();h.noIdentity();h.otherFeaturesClosed();assert.equal(h.calls.length,0);assert.match(h.title(),title);
 });
test('legacy shared auth without snapshot/subscribe stays unavailable without its own me fallback',async t=>{
 const h=harness(t,{legacy:true});await settle();h.noIdentity();h.otherFeaturesClosed();assert.match(h.title(),/준비 중/);
 assert.deepEqual(h.calls,[]);assert.deepEqual(h.authCalls,[]);assert.deepEqual(h.storageCalls,[]);
});
test('confirmed shared snapshot starts fixed profile GET but never renders snapshot display fields',async t=>{
 const late=deferred(),h=harness(t,{state:authState(),responder:()=>late.promise});
 h.noIdentity();assert.match(h.title(),/확인 중/);assert.equal(h.calls.length,0);await settle();
 assert.equal(h.calls.length,1);h.noIdentity();const opt=h.calls[0].options;
 assert.equal(opt.method,'GET');assert.equal(opt.credentials,'same-origin');assert.equal(opt.cache,'no-store');assert.equal(opt.redirect,'error');
 assert.deepEqual(clone(opt.headers),{'X-Popcorn-Auth-Context':context().session_context_id});assert.equal(opt.body,undefined);assert.ok(opt.signal);
 late.resolve(response(profile()));await settle();assert.equal(h.w.document.getElementById('my-nick').textContent,NAME);
 assert.equal(h.w.document.getElementById('my-identity-note').textContent,EMAIL);h.otherFeaturesClosed();assert.deepEqual(h.storageCalls,[]);
});
test('profile success uses current server nickname even when shared display nickname differs; null email stays null',async t=>{
 const h=harness(t,{state:authState(),responder:()=>response(profile(authState(),{email:null}))});await settle();
 assert.equal(h.w.document.getElementById('my-nick').textContent,NAME);
 assert.match(h.w.document.getElementById('my-identity-note').textContent,/提供|제공되지/);
 assert.equal(h.w.document.body.textContent.includes('AUTH-DISPLAY-CACHE'),false);h.otherFeaturesClosed();
});
test('large decimal member and revision are compared as strings without Number conversion',async t=>{
 const s=authState(1,'9223372036854775807',{principal_revision:'9223372036854775807'});
 const h=harness(t,{state:s,responder:()=>response(profile(s))});await settle();assert.equal(h.w.document.getElementById('my-nick').textContent,NAME);h.otherFeaturesClosed();
});
for(const [name,mutate] of [
 ['different member',d=>{d.profile.member_id='102';}],['different context owner',d=>{d.auth_context.member_id='102';}],
 ['different session',d=>{d.auth_context.session_context_id='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';}],
 ['different revision',d=>{d.auth_context.principal_revision='2';}],
 ['numeric ID',d=>{d.profile.member_id=101;}],['numeric revision',d=>{d.auth_context.principal_revision=1;}],
 ['alias nick',d=>{d.profile.nick=d.profile.nickname;delete d.profile.nickname;}],
 ['HTML nickname',d=>{d.profile.nickname='<img src=x onerror=alert(1)>'; }],
 ['control nickname',d=>{d.profile.nickname='bad\nname';}],['invalid email',d=>{d.profile.email='not-email';}],
 ['extra profile data',d=>{d.profile.mall_id='MALL-2201';}],['extra secret',d=>{d.cookie='PRIVATE-ORDER-ROW';}],
 ['unknown version',d=>{d.auth_version=3;}],['null context',d=>{d.auth_context=null;}],
 ['null profile',d=>{d.profile=null;}],['me instead of profile',d=>{delete d.profile;d.authenticated=true;d.member=authState().member;}]
])test('otherwise valid profile rejects '+name+' and invalidates shared identity',async t=>{
 const d=profile();mutate(d);const h=harness(t,{state:authState(),responder:()=>response(d)});await settle();
 h.noIdentity();h.otherFeaturesClosed();assert.equal(h.authCalls.filter(c=>c==='expired').length,1);
 assert.equal(h.w.document.querySelectorAll('main img[src="x"],main script').length,0);
});
for(const [name,change] of [
 ['unsafe epoch',s=>{s.epoch=Number.MAX_SAFE_INTEGER+1;}],['missing context',s=>{s.auth_context=null;}],
 ['alias snapshot nick',s=>{s.member.nick=s.member.nickname;delete s.member.nickname;}],
 ['numeric member',s=>{s.member.member_id=101;}],['context mismatch',s=>{s.auth_context.member_id='102';}],
 ['truthy phase',s=>{s.phase=true;}]
])test('malformed shared '+name+' never starts private GET',async t=>{
 const s=authState();change(s);const h=harness(t,{state:s});await settle();h.noIdentity();h.otherFeaturesClosed();assert.equal(h.calls.length,0);assert.match(h.title(),/확인하지 못/);
});
for(const status of [401,409])test('HTTP '+status+' wipes and expires shared state without parsing a late or hostile error body',async t=>{
 let parses=0;const h=harness(t,{state:authState(),responder:()=>response(null,status,{json:()=>{parses++;return new Promise(()=>{});}})});
 await settle();h.noIdentity();h.otherFeaturesClosed();assert.equal(parses,0);assert.equal(h.authCalls.filter(x=>x==='expired').length,1);
});
test('typed profile readiness503 remains unqueried elsewhere, safe to retry, with no fake login recovery',async t=>{
 const h=harness(t,{state:authState(),responder:()=>response({detail:{code:'auth_unavailable',message:EMAIL}},503)});await settle();
 h.noIdentity();h.otherFeaturesClosed();assert.match(h.title(),/조회 준비 중/);assert.equal(h.retry().hidden,false);assert.equal(h.authCalls.includes('expired'),false);
});
for(const [name,responder] of [
 ['network rejection',()=>Promise.reject(new Error(EMAIL))],
 ['synchronous throw',()=>{throw new Error(EMAIL);}],
 ['late JSON rejection',()=>response(null,200,{json:()=>Promise.reject(new Error(EMAIL))})],
 ['unknown503',()=>response({detail:{code:EMAIL}},503)],
 ['missing response',()=>null],['unexpected201',()=>response(profile(),201)],
 ['redirected',()=>response(profile(),200,{redirected:true})],['opaque',()=>response(profile(),200,{type:'opaque'})],
 ['foreign origin',()=>response(profile(),200,{url:'https://other.test/api/my/profile'})],
 ['account path',()=>response(profile(),200,{url:'https://preview.test/api/my/account'})],
 ['query URL',()=>response(profile(),200,{url:'https://preview.test/api/my/profile?member_id=101'})],
 ['missing cache header',()=>response(profile(),200,{headers:null})],
 ['cacheable response',()=>response(profile(),200,{headers:{get:()=> 'private,max-age=60'}})]
])test('profile '+name+' shows public retry error and never raw private data',async t=>{
 const h=harness(t,{state:authState(),responder});await settle();h.noIdentity();h.otherFeaturesClosed();assert.match(h.title(),/확인하지 못/);assert.equal(h.retry().hidden,false);
});
test('status401 without no-store still invalidates but cannot restore cached profile',async t=>{
 const h=harness(t,{state:authState(),responder:()=>response(profile(),401,{headers:null})});await settle();h.noIdentity();
 assert.ok(h.authCalls.includes('expired'));h.otherFeaturesClosed();
});
test('duplicate immutable authenticated notification deduplicates profile reads',async t=>{
 const h=harness(t,{state:authState()});await settle();h.emit(authState());await settle();assert.equal(h.calls.length,1);
 assert.equal(h.w.document.getElementById('my-nick').textContent,NAME);
});
test('auth begin wipes all profile fields and Abort synchronously before the next fetch or await',async t=>{
 const h=harness(t,{state:authState()});await settle();const late=deferred();
 h.setResponder(()=>late.promise);h.emit(authState(2));await settle();assert.equal(h.calls.length,2);
 h.emit(closed('checking',3));h.noIdentity();assert.equal(h.aborts.length,1);assert.match(h.title(),/확인 중/);
 let parses=0;late.resolve(response(profile(authState(2)),200,{json:async()=>{parses++;return profile(authState(2));}}));await settle();
 assert.equal(parses,0);h.noIdentity();h.otherFeaturesClosed();
});
test('A-B-A re-login rejects old response even when member ID matches again',async t=>{
 const old=deferred(),a1=authState(1),b=authState(2,'102',{principal_revision:'2'}),a2=authState(3,'101',{principal_revision:'3',session_context_id:'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'});
 const h=harness(t,{state:a1,responder:()=>old.promise});await settle();
 h.setResponder(()=>response(profile(b,{nickname:'B-NAME'})));h.emit(b);await settle();
 h.setResponder(()=>response(profile(a2,{nickname:'NEW-A-NAME'})));h.emit(a2);await settle();
 old.resolve(response(profile(a1)));await settle();assert.equal(h.w.document.getElementById('my-nick').textContent,'NEW-A-NAME');h.otherFeaturesClosed();
});
test('delayed response JSON and old failure cannot overwrite later signed-out or new profile',async t=>{
 const body=deferred(),h=harness(t,{state:authState(),responder:()=>response(null,200,{json:()=>body.promise})});await settle();
 h.emit(closed('signed-out',2));h.noIdentity();body.resolve(profile());await settle();h.noIdentity();assert.match(h.title(),/로그인이 필요/);
 const late=deferred();h.setResponder(()=>late.promise);h.emit(authState(3));await settle();
 const next=authState(4,'102');h.setResponder(()=>response(profile(next,{nickname:'NEW-B-NAME'})));h.emit(next);await settle();
 late.reject(new Error(EMAIL));await settle();assert.equal(h.w.document.getElementById('my-nick').textContent,'NEW-B-NAME');h.otherFeaturesClosed();
});
test('response checks current snapshot even if a consumer misses an external notification',async t=>{
 const late=deferred(),h=harness(t,{state:authState(),responder:()=>late.promise});await settle();
 h.setStateSilently(authState(1,'102'));late.resolve(response(profile()));await settle();h.noIdentity();assert.match(h.title(),/확인하지 못/);
});
test('retry wipes, verifies shared auth first, deduplicates and retains its native keyboard focus',async t=>{
 const h=harness(t,{state:authState(),responder:()=>response(null,500)});await settle();const button=h.retry(),wait=deferred();
 h.setSync(epoch=>wait.promise.then(()=>{h.emit(authState(epoch));return true;}));
 h.setResponder(()=>response(profile(authState(2))));button.focus();button.click();button.click();
 h.noIdentity();assert.equal(h.w.document.activeElement,button);assert.equal(button.getAttribute('aria-disabled'),'true');
 assert.equal(h.authCalls.filter(x=>x==='sync').length,1);wait.resolve();await settle();
 assert.equal(h.calls.length,2);assert.equal(h.w.document.getElementById('my-nick').textContent,NAME);h.otherFeaturesClosed();
});
test('pagehide unsubscribes and cancels; pageshow attaches once and old response cannot repaint',async t=>{
 const late=deferred(),h=harness(t,{state:authState(),responder:()=>late.promise});await settle();
 h.event('pagehide',true);h.noIdentity();assert.equal(h.subscriberCount(),0);assert.equal(h.aborts.length,1);
 h.retry().click();h.emit(authState(2));await settle();assert.equal(h.calls.length,1);
 h.setStateSilently(closed('checking',3));h.event('pageshow',true);h.event('pageshow',true);assert.equal(h.subscriberCount(),1);
 h.setResponder(()=>response(profile(authState(3,'102'),{nickname:'NEW-PAGE-NAME'})));h.emit(authState(3,'102'));await settle();
 late.resolve(response(profile()));await settle();assert.equal(h.w.document.getElementById('my-nick').textContent,'NEW-PAGE-NAME');h.otherFeaturesClosed();
});
test('hidden page wipes immediately; resume waits for new shared auth verification',async t=>{
 const h=harness(t,{state:authState()});await settle();let value='visible';
 Object.defineProperty(h.w.document,'visibilityState',{get:()=>value,configurable:true});
 value='hidden';h.w.document.dispatchEvent(new h.w.Event('visibilitychange'));h.noIdentity();assert.equal(h.subscriberCount(),0);
 h.setStateSilently(closed('checking',2));value='visible';h.w.document.dispatchEvent(new h.w.Event('visibilitychange'));await settle();
 h.noIdentity();assert.equal(h.calls.length,1);h.setResponder(()=>response(profile(authState(2))));h.emit(authState(2));await settle();
 assert.equal(h.calls.length,2);assert.equal(h.w.document.getElementById('my-nick').textContent,NAME);
});
test('all legacy/settings/map/order controls remain disabled without POST or local success writes',async t=>{
 const h=harness(t,{state:authState()});await settle();
 for(const b of h.w.document.querySelectorAll('button:not(#member-retry)')){b.click();b.dispatchEvent(new h.w.MouseEvent('click',{bubbles:true}));}
 await settle();h.otherFeaturesClosed();assert.equal(h.calls.length,1);assert.deepEqual(h.storageCalls,[]);
 assert.equal(h.w.document.querySelector('header a.btnp').getAttribute('href'),'/mvp3/');
});
test('actual accepted C3 publishes v2 me then C6 profile, and expiry wipes synchronously',async t=>{
 const s=authState();const h=harness(t,{integration:true,responder:url=>url==='/api/auth/me'?response(me(s)):response(profile(s))});
 await settle();assert.equal(h.w.document.getElementById('my-nick').textContent,NAME);
 assert.deepEqual(h.calls.map(c=>c.url),['/api/auth/me','/api/my/profile']);
 h.w.popcornAuth.expired();h.noIdentity();h.otherFeaturesClosed();
 assert.equal(h.w.localStorage.getItem('popcorn-saved-quotes'),'keep-quote');assert.equal(h.w.localStorage.getItem('guest-owner-test'),'keep-owner');
});
test('actual C3 unavailable503 prevents C6 profile or private reads',async t=>{
 const h=harness(t,{integration:true,responder:()=>response({detail:{code:'auth_unavailable'}},503)});
 await settle();h.noIdentity();h.otherFeaturesClosed();assert.deepEqual(h.calls.map(c=>c.url),['/api/auth/me']);assert.match(h.title(),/準備|준비 중/);
});
test('actual accepted C3 cross-tab invalidation wipes a displayed C6 profile before fresh me',async t=>{
 const channels=[],messages=[];
 class Channel{constructor(name){this.name=name;this.closed=false;channels.push(this);}postMessage(data){
  messages.push(clone(data));for(const peer of channels)if(peer!==this&&!peer.closed&&peer.onmessage)queueMicrotask(()=>{if(!peer.closed)peer.onmessage({data:clone(data)});});
 }close(){this.closed=true;}}
 const a=harness(t,{integration:true,Channel,responder:url=>url==='/api/auth/me'?response(me()):response(profile())});
 const b=harness(t,{integration:true,Channel,responder:url=>url==='/api/auth/me'?response(me()):response(profile())});
 await settle();assert.equal(b.w.document.getElementById('my-nick').textContent,NAME);
 const fresh=deferred();b.setResponder(()=>fresh.promise);a.w.popcornAuth.expired();await Promise.resolve();b.noIdentity();await settle();
 assert.equal(b.calls.filter(c=>c.url==='/api/my/profile').length,1);
 fresh.resolve(response({auth_version:2,phase:'signed-out',authenticated:false,member:null,auth_context:null}));await settle();b.noIdentity();b.otherFeaturesClosed();
 assert.deepEqual(messages,[{type:'invalidate',auth_version:2}]);
});
