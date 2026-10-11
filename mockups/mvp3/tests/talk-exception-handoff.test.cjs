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

// 코덱스 1816 「물은 것에 먼저 답하고, 앞서 말한 조건과 보던 견적을 잃지 않기」
test('an off-topic question keeps the quote being viewed; a changed condition refreshes it',async()=>{
  const replies=[parsed({reply:'찾아볼게요.'}),
    parsed({pc_related:false,answer:'오늘은 따뜻한 국물 요리 어떠세요?',reply:'PC가 필요하시면 언제든 말씀해 주세요.'}),
    parsed({state:{...talk,budget_won:2000000},reply:'예산을 바꿔 다시 찾아볼게요.'})];
  let n=0;const h=harness(()=>replies[Math.min(n++,2)]);
  const recs=()=>h.calls.filter(c=>c.url==='/api/grid/recommend').length;
  try{
    await h.flow.submit('배그 150만원');
    await until(()=>h.flow.state.phase===null);
    assert.equal(recs(),1);assert.equal(h.flow.state.screen,'results');
    const before=h.flow.state.recommendation;
    await h.flow.submit('오늘 저녁 뭐 먹지?');
    await until(()=>h.flow.state.phase===null);
    assert.equal(recs(),1);
    assert.equal(h.flow.state.screen,'results');
    assert.equal(h.flow.state.recommendation,before);
    assert.ok(h.flow.state.messages.some(m=>/국물/.test(m.text)));
    await h.flow.submit('예산 200만원으로 바꿀게요');
    await until(()=>h.flow.state.phase===null);
    assert.equal(recs(),2);
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

// 코덱스 PR136 검수 남은 숙제: ① 새 조건으로 다시 찾다 실패하면 보던 견적으로 되돌린다
// ② 상세를 보던 중에도 사람 상담 길이 뜬다 ③ 그 칸은 구매 상담이 아닌 일반 상담 문구다
const product={product_code:113836,name:'CODE/MOCK PC',price:900000,price_src:'판매가',spec:{cpu:'CPU'},reasons:['이유'],over_budget:false};
const cards={status:200,data:{ok:true,card_sets:[{kind:'sold',usage:'게임',items:[product]}],needs:[],assumed:[]}};

test('a failed re-recommend restores the quote being viewed',async()=>{
  const replies=[parsed({reply:'찾아볼게요.'}),parsed({state:{...talk,budget_won:2000000},reply:'다시 찾아볼게요.'})];
  const recs=[cards,{status:502,data:{detail:'잠시 뒤 다시 시도해 주세요.'}}];
  let n=0,r=0;const h=harness(()=>replies[Math.min(n++,1)],()=>recs[Math.min(r++,1)]);
  try{
    await h.flow.submit('배그 150만원');
    await until(()=>h.flow.state.phase===null);
    const before=h.flow.state.recommendation;assert.ok(before);assert.equal(h.flow.state.groups.length>0,true);
    await h.flow.submit('예산 200만원으로 바꿀게요');
    await until(()=>h.flow.state.phase===null);
    assert.ok(h.flow.state.error);
    assert.equal(h.flow.state.retry.kind,'recommend');
    assert.equal(h.flow.state.recommendation,before);
    assert.equal(h.flow.state.screen,'results');
    assert.ok(h.doc.querySelector('[data-action=inquiry-open]'));
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('the detail screen also offers the human inquiry with general wording',async()=>{
  const replies=[parsed({reply:'찾아볼게요.'}),parsed({pc_related:false,handoff_offer:true,exceptions:['human']})];
  let n=0;const h=harness(()=>replies[Math.min(n++,1)],()=>cards);
  try{
    await h.flow.submit('배그 150만원');
    await until(()=>h.flow.state.phase===null);
    h.flow.select(h.flow.state.groups[0].products[0].index);
    await until(()=>h.flow.state.screen==='detail');
    assert.equal(h.doc.querySelector('[data-action=inquiry-open]'),null);
    await h.flow.submit('상담원 연결해 주세요');
    await until(()=>h.flow.state.phase===null&&h.doc.querySelector('[data-action=inquiry-open]'));
    assert.equal(h.flow.state.screen,'detail');
    assert.ok(h.flow.state.selected);
    h.doc.querySelector('[data-action=inquiry-open]').click();
    await until(()=>h.doc.querySelector('[data-action=inquiry-send]'));
    assert.equal(h.doc.querySelector('[data-inquiry-form] h3').textContent,'사람 상담 남기기');
    assert.equal(h.doc.querySelector('[data-inquiry=message]').value,'상담원 연결해 주세요');
    await until(()=>h.flow.state.phase===null);for(let i=0;i<50;i++)await tick();
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('the human inquiry before choosing a product uses general wording',async()=>{
  const h=harness(()=>parsed({handoff_offer:true,pc_related:false,exceptions:['human']}));
  try{
    await h.flow.submit('상담원 연결해 주세요');
    await until(()=>h.flow.state.phase===null&&h.doc.querySelector('[data-action=inquiry-open]'));
    h.doc.querySelector('[data-action=inquiry-open]').click();
    await until(()=>h.doc.querySelector('[data-action=inquiry-send]'));
    const form=h.doc.querySelector('[data-inquiry-form]');
    assert.equal(form.querySelector('h3').textContent,'사람 상담 남기기');
    assert.doesNotMatch(form.textContent,/세금계산서처럼/);
  }finally{h.close();}
});
