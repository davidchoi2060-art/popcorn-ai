'use strict';
// 상담 예외 입력 -> 사람 상담 길(2026-10-11 「무조건 차단하면 안 된다」). CODE/MOCK fixture 만 쓴다.
// ① 서버가 handoff_offer 를 주면 상품을 고르기 전에도 「사람 상담 남기기」가 뜬다
// ② 열면 주제 「기타」와 마지막 문장이 미리 채워지고, 보내면 상품 번호 없이 한 번 POST 한다
// ③ AI 응답을 못 읽은 턴(fallback)은 추천을 부르지 않는다 ④ 상담 실패 뒤에도 사람 상담 길이 열린다
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),{webcrypto}=require('node:crypto');
const {JSDOM,VirtualConsole}=require('jsdom');
const base=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(base,n),'utf8');
const FORM={ok:true,topics:['여러 대 구매','할인','세금계산서·영수증','주문 희망','기타'],consent_text:'CODE/MOCK 동의 문구.'};
const talk={usages:['게임'],budget_won:1500000};
const tick=()=>new Promise(r=>setImmediate(r));
async function until(check){for(let n=0;n<400;n++){if(check())return;await tick();}throw Error('render did not settle');}

function harness(parseReply){
  const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read('index.html'),{url:'https://qa.invalid/mvp3/#welcome',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.TextEncoder=TextEncoder;
  Object.defineProperty(w,'crypto',{value:webcrypto});w.localStorage.setItem('popcorn-mvp3-guest-access-v1','a'.repeat(64));
  w.eval(read('live-model.js'));w.eval(read('api-client.js'));
  const reply=(status,data)=>({ok:status<400,status,json:async()=>data,headers:{get:()=>null}});
  w.MVP3Api=w.MVP3Api.createClient({storage:w.localStorage,cryptoImpl:webcrypto,fetchImpl:async(url,options)=>{
    calls.push({url,method:options.method,body:options.body?JSON.parse(options.body):null});
    if(url==='/api/talk/parse'){const r=parseReply();return reply(r.status||200,r.data);}
    if(url==='/api/mvp3/purchase-inquiries/form')return reply(200,FORM);
    if(url==='/api/mvp3/purchase-inquiries')return reply(200,{ok:true,inquiry_no:'PI-2001',note:'CODE/MOCK 신청을 받았어요.'});
    if(url==='/api/grid/recommend')return reply(200,{ok:true,card_sets:[],needs:[],assumed:[]});
    return reply(200,{ok:true,quotes:[],has_more:false});
  }});
  w.eval(read('live-flow.js'));
  const create=w.MVP3LiveFlow.createFlow;let flow;
  w.MVP3LiveFlow.createFlow=(...args)=>{flow=create(...args);return flow;};
  w.eval(read('app.js'));
  return {w,doc:w.document,get flow(){return flow;},calls,errors,close:()=>dom.window.close()};
}
const parsed=extra=>({data:{ok:true,state:talk,missing:[],assumed:[],reply:'사람 상담을 원하시면 아래 「사람 상담 남기기」에 연락처를 남겨 주세요.',...extra}});

test('handoff_offer shows a human inquiry before any product is chosen and posts without product',async()=>{
  const h=harness(()=>parsed({handoff_offer:true,pc_related:false,exceptions:['human']}));
  try{
    await h.flow.submit('상담원 연결해 주세요');
    await until(()=>h.flow.state.phase===null&&h.doc.querySelector('[data-action=inquiry-open]'));
    assert.equal(h.flow.state.selected,null);
    assert.equal(h.calls.filter(c=>c.url==='/api/grid/recommend').length,0);
    h.doc.querySelector('[data-action=inquiry-open]').click();
    await until(()=>h.doc.querySelector('[data-action=inquiry-send]'));
    assert.equal(h.doc.querySelector('[data-inquiry=topic]').value,'기타');
    assert.equal(h.doc.querySelector('[data-inquiry=message]').value,'상담원 연결해 주세요');
    const set=(k,v)=>{const e=h.doc.querySelector('[data-inquiry='+k+']');if(e.type==='checkbox')e.checked=v;else e.value=v;e.dispatchEvent(new h.w.Event('input',{bubbles:true}));};
    set('phone','010-1234-5678');set('consent',true);
    h.doc.querySelector('[data-action=inquiry-send]').click();
    await until(()=>h.flow.state.inquiry.done);
    const posts=h.calls.filter(c=>c.url==='/api/mvp3/purchase-inquiries'&&c.method==='POST');
    assert.equal(posts.length,1);
    assert.deepEqual(posts[0].body,{topic:'기타',consent:true,phone:'010-1234-5678',message:'상담원 연결해 주세요'});
    assert.match(h.doc.querySelector('[data-inquiry-done]').textContent,/PI-2001/);
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('ai_unreadable fallback keeps conditions and does not call recommend',async()=>{
  const h=harness(()=>parsed({fallback:'ai_unreadable',handoff_offer:true,reply:'방금 말씀을 제가 잘 정리하지 못했어요.'}));
  try{
    await h.flow.submit('뭐라뭐라');
    await until(()=>h.flow.state.phase===null);
    assert.equal(h.flow.state.screen,'welcome');
    assert.equal(h.calls.filter(c=>c.url==='/api/grid/recommend').length,0);
    assert.ok(h.doc.querySelector('[data-action=inquiry-open]'));
  }finally{h.close();}
});

test('a failed consultation also opens the human inquiry path',async()=>{
  const h=harness(()=>({status:502,data:{detail:'AI 상담 응답을 처리하지 못했습니다.'}}));
  try{
    await h.flow.submit('배그 150');
    await until(()=>h.flow.state.phase===null);
    assert.ok(h.flow.state.error);
    assert.ok(h.doc.querySelector('[data-action=inquiry-open]'));
  }finally{h.close();}
});

test('plain answers do not show the human inquiry button',async()=>{
  const h=harness(()=>parsed({missing:['usages'],reply:'어떤 용도로 쓰세요?'}));
  try{
    await h.flow.submit('컴퓨터 사고 싶어요');
    await until(()=>h.flow.state.phase===null);
    assert.equal(h.doc.querySelector('[data-action=inquiry-open]'),null);
  }finally{h.close();}
});
