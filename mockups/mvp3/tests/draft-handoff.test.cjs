'use strict';
// 처음 화면(index.html) <-> 대화 화면(talk.html) 사이 보내지 않은 입력 문장 인계(코덱스 #148 검수 P2).
// 같은 탭 sessionStorage 에만 잠깐 두고, 받는 화면이 한 번 읽고 지운다. 주소에는 싣지 않고 자동으로 보내지 않는다.
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),{webcrypto}=require('node:crypto');
const {JSDOM,VirtualConsole}=require('jsdom');
const base=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(base,n),'utf8');
const LF=require('../live-flow.js');
const tick=()=>new Promise(r=>setImmediate(r));
function storage(){const map=new Map();return {map,getItem:k=>map.get(k)??null,setItem:(k,v)=>map.set(k,String(v)),removeItem:k=>map.delete(k),key:i=>[...map.keys()][i]??null,get length(){return map.size;}};}

function page(file,ss,hash=''){
  const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read(file),{url:'https://qa.invalid/mvp3/'+file+hash,runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;w.scrollTo=()=>{};w.TextEncoder=TextEncoder;w.matchMedia=()=>({matches:false,addEventListener(){}});
  Object.defineProperty(w,'crypto',{value:webcrypto});Object.defineProperty(w,'sessionStorage',{value:ss});
  w.localStorage.setItem('popcorn-mvp3-guest-access-v1','a'.repeat(64));
  w.eval(read('live-model.js'));w.eval(read('api-client.js'));
  w.MVP3Api=w.MVP3Api.createClient({storage:w.localStorage,cryptoImpl:webcrypto,fetchImpl:async(url,options)=>{
    calls.push({url,body:options.body||null});return {ok:true,status:200,json:async()=>({ok:true,quotes:[],has_more:false}),headers:{get:()=>null}};}});
  w.eval(read('live-flow.js'));w.eval(read('live-photo.js'));w.eval(read(file==='talk.html'?'talk.js':'app.js'));
  const input=w.document.querySelector(file==='talk.html'?'#tk-input':'#request');
  return {w,input,calls,errors,
    type(text){input.value=text;input.dispatchEvent(new w.Event('input',{bubbles:true}));},
    leave(){w.dispatchEvent(new w.Event('pagehide'));},
    close(){w.close();}};
}

test('unsent draft typed on the first screen appears in the talk input, unsent and not in any URL',async()=>{
  const ss=storage(),a=page('index.html',ss,'#welcome');
  try{
    a.type('영상 편집용으로 알아보는 중인데 150만원 안쪽이면');a.leave();
    assert.ok(ss.getItem(LF.DRAFT_KEY));
    assert.doesNotMatch(a.w.location.href,/영상|%EC/);
    assert.deepEqual(a.errors,[]);
  }finally{a.close();}
  const b=page('talk.html',ss);
  try{
    await tick();
    assert.equal(b.input.value,'영상 편집용으로 알아보는 중인데 150만원 안쪽이면');
    assert.equal(ss.getItem(LF.DRAFT_KEY),null,'consumed once');
    assert.equal(b.calls.filter(c=>c.url==='/api/talk/parse').length,0,'never auto-sent');
    assert.deepEqual(b.errors,[]);
  }finally{b.close();}
});

test('unsent draft typed on the talk screen comes back to the first screen as an edited draft',async()=>{
  const ss=storage(),b=page('talk.html',ss);
  try{b.type('게임도 조금 하는데 조용한 PC');b.leave();assert.deepEqual(b.errors,[]);}finally{b.close();}
  const a=page('index.html',ss,'#welcome');
  try{
    await tick();
    assert.equal(a.input.value,'게임도 조금 하는데 조용한 PC');
    assert.equal(ss.getItem(LF.DRAFT_KEY),null);
    assert.equal(a.calls.filter(c=>c.url==='/api/talk/parse').length,0);
    assert.deepEqual(a.errors,[]);
  }finally{a.close();}
});

test('generated first-screen guide text is not handed over; an emptied input clears a stale handoff',async()=>{
  const ss=storage(),a=page('index.html',ss,'#purpose');
  try{
    a.w.document.querySelector('[data-usage="game"]').click();
    assert.ok(a.input.value.trim(),'gateway generated a guide sentence');a.leave();
    assert.equal(ss.getItem(LF.DRAFT_KEY),null,'auto-generated text is not the customer draft');
  }finally{a.close();}
  ss.setItem(LF.DRAFT_KEY,JSON.stringify({version:1,saved_at:Date.now(),text:'옛 문장'}));
  const b=page('talk.html',ss);
  try{
    assert.equal(b.input.value,'옛 문장');b.input.value='';b.leave();
    assert.equal(ss.getItem(LF.DRAFT_KEY),null,'sent or cleared input does not resurrect the old draft');
  }finally{b.close();}
});

test('handoff store: expires, masks card numbers, survives blocked storage',()=>{
  const ss=storage(),h=LF.createDraftHandoff({sessionStorage:ss}),t0=1_000_000;
  assert.equal(h.put('카드 1234-5678-1234-5678 로 결제할게요',t0),true);
  assert.doesNotMatch(ss.getItem(LF.DRAFT_KEY),/1234-5678/);
  assert.match(h.take(t0+1000),/\[가림\]/);
  assert.equal(h.take(t0+1000),'','read once');
  h.put('조금 뒤',t0);assert.equal(h.take(t0+LF.DRAFT_TTL_MS+1),'','expired');
  assert.ok(LF.DRAFT_TTL_MS<=15*60*1000,'short expiry');
  const blocked=LF.createDraftHandoff({sessionStorage:null});
  assert.equal(blocked.put('x'),false);assert.equal(blocked.take(),'');
  ss.setItem(LF.DRAFT_KEY,'{broken');assert.equal(h.take(),'');
});
