'use strict';
// LLM 상담(2026-10-14 중헌 님 「고객 상담을 LLM 중심으로 해」 · api/talk_agent.as_parse). CODE/MOCK fixture 만 쓴다.
// ① /parse 가 agent:true 로 카드 조건을 주면 그 조건 그대로(wants·문장 없이) /grid/recommend 를 묻고 엔진 안내 문장은 붙이지 않는다
// ② 설명만 한 턴(explain_only)은 추천을 부르지 않고 보던 견적을 둔다 ③ 「더 싸게」면 같은 방향으로 묻는다
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),{webcrypto}=require('node:crypto');
const {JSDOM,VirtualConsole}=require('jsdom');
const base=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(base,n),'utf8');
const FORM={ok:true,topics:['여러 대 구매','할인','세금계산서·영수증','주문 희망','기타'],consent_text:'CODE/MOCK 동의 문구.'};
const talk={usages:['게임'],budget_won:1500000};
const tick=()=>new Promise(r=>setImmediate(r));
async function until(check){for(let n=0;n<400;n++){if(check())return;await tick();}throw Error('render did not settle');}

function harness(parseReply,recommendReply=()=>({status:200,data:{ok:true,card_sets:[],needs:[],assumed:[]}})){
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
    if(url==='/api/grid/recommend'){const r=recommendReply();return reply(r.status||200,r.data);}
    return reply(200,{ok:true,quotes:[],has_more:false});
  }});
  w.eval(read('live-flow.js'));
  const create=w.MVP3LiveFlow.createFlow;let flow;
  w.MVP3LiveFlow.createFlow=(...args)=>{flow=create(...args);return flow;};
  w.eval(read('live-photo.js'));w.eval(read('app.js'));
  return {w,doc:w.document,get flow(){return flow;},calls,errors,close:()=>dom.window.close()};
}

const CARD={product_code:1001,name:'CODE/MOCK 게임 PC',price:1498000,kind:'sold',spec:{gpu:'RTX 5060'}};
const reco=()=>({data:{ok:true,card_sets:[{usage:'게임',kind:'sold',items:[CARD]}],needs:[],assumed:[],talk_notes:['엔진 안내 문장'],wants:{tier:'x'},anchor_code:1001}});
const agent=extra=>({data:{ok:true,agent:true,state:talk,missing:[],assumed:[],pc_related:true,answer:'',reply:'CODE/MOCK 게임 PC A가 맞아요.',explain_only:false,nav:null,...extra}});

test('agent turn re-asks the engine with the AI condition, without wants, text or engine notes',async()=>{
  const h=harness(()=>agent(),reco);
  try{
    await h.flow.submit('게임용 PC 150만원');
    await until(()=>h.flow.state.phase===null&&h.flow.state.recommendation);
    const recs=h.calls.filter(c=>c.url==='/api/grid/recommend');
    assert.equal(recs.length,1);
    assert.deepEqual(recs[0].body,{state:talk});
    assert.equal(h.calls.filter(c=>c.url==='/api/talk/answer').length,0);   // AI 답이 최종 -- 「카드 먼저」 설명 받기를 부르지 않는다
    const texts=h.flow.state.messages.map(m=>m.text);
    assert.ok(texts.includes('CODE/MOCK 게임 PC A가 맞아요.'));
    assert.ok(!texts.includes('엔진 안내 문장'));
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('explain_only agent turn calls no recommend and keeps the current recommendation',async()=>{
  let n=0;const h=harness(()=>++n===1?agent():agent({explain_only:true,reply:'램은 동시 작업에 영향을 줘요.'}),reco);
  try{
    await h.flow.submit('게임용 PC 150만원');
    await until(()=>h.flow.state.phase===null&&h.flow.state.recommendation);
    const before=h.flow.state.recommendation;
    await h.flow.submit('램이랑 SSD 차이가 뭐예요?');
    await until(()=>h.flow.state.phase===null);
    assert.equal(h.calls.filter(c=>c.url==='/api/grid/recommend').length,1);
    assert.equal(h.flow.state.recommendation,before);
  }finally{h.close();}
});

test('agent nav cheaper asks the same direction from the shown card',async()=>{
  let n=0;const h=harness(()=>++n===1?agent():agent({nav:'cheaper'}),reco);
  try{
    await h.flow.submit('게임용 PC 150만원');
    await until(()=>h.flow.state.phase===null&&h.flow.state.recommendation);
    await h.flow.submit('더 싼 거 있어요?');
    await until(()=>h.flow.state.phase===null&&h.calls.filter(c=>c.url==='/api/grid/recommend').length===2);
    assert.deepEqual(h.calls.filter(c=>c.url==='/api/grid/recommend')[1].body,{state:talk,nav:'cheaper',anchor_code:1001});
  }finally{h.close();}
});

test('agent turn with units sends wants.units so the screen compares one-PC budget (C10)',async()=>{
  const h=harness(()=>agent({wants:{units:12}}),reco);
  try{
    await h.flow.submit('사무용 PC 12대 총 960만원');
    await until(()=>h.flow.state.phase===null&&h.flow.state.recommendation);
    const recs=h.calls.filter(c=>c.url==='/api/grid/recommend');
    assert.deepEqual(recs[0].body,{state:talk,wants:{units:12}});
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('agent shown_note rides in the next turn history but is never shown on screen',async()=>{
  const NOTE='보여 드린 PC: 1. 「CODE/MOCK 게임 PC」 1,498,000원';
  let n=0;const h=harness(()=>++n===1?agent({shown_note:NOTE}):agent({explain_only:true,reply:'두 번째 PC는 없었어요.'}),reco);
  try{
    await h.flow.submit('게임용 PC 150만원');
    await until(()=>h.flow.state.phase===null&&h.flow.state.recommendation);
    await h.flow.submit('조금 전 두 번째 제품을 다시 보여주세요.');
    await until(()=>h.flow.state.phase===null);
    const parses=h.calls.filter(c=>c.url==='/api/talk/parse');
    assert.ok(parses[1].body.history.some(t=>t.role==='assistant'&&t.text===NOTE));
    assert.ok(!h.flow.state.messages.some(m=>String(m.text).includes('보여 드린 PC')));
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});
