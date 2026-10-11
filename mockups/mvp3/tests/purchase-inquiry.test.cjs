'use strict';
// 최종 견적 -> 구매 상담 신청(api/mvp3_purchase_inquiry.py). CODE/MOCK fixture 로만 확인한다(실 DB·실 POST 없음).
// ① 단추를 누르면 서버가 준 주제·동의 문구로 칸이 열린다 ② 연락처·동의가 없으면 보내지 않는다
// ③ 보내면 보관 견적 번호와 상품 번호를 함께 한 번만 POST 하고 받은 신청 번호를 보여 준다
// ④ 서버가 422 로 거절하면 그 사유를 칸 안에 보여 주고 적던 값은 남는다.
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),{webcrypto}=require('node:crypto');
const {JSDOM,VirtualConsole}=require('jsdom');
const base=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(base,n),'utf8');
const qid='44444444-4444-4444-8444-444444444444';
const talk={usages:['사무용'],budget_won:1500000};
const product={product_code:113836,name:'CODE/MOCK 보관 PC',price:900000,price_src:'보관 시점 판매가',spec:{cpu:'CPU'},reasons:['이유'],over_budget:false};
const FORM={ok:true,topics:['여러 대 구매','할인','세금계산서·영수증','주문 희망','기타'],consent_text:'CODE/MOCK 동의 문구.'};
const tick=()=>new Promise(r=>setImmediate(r));
async function until(check){for(let n=0;n<400;n++){if(check())return;await tick();}throw Error('render did not settle');}

function harness(postReply){
  const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read('index.html'),{url:'https://qa.invalid/mvp3/#saved',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.TextEncoder=TextEncoder;
  Object.defineProperty(w,'crypto',{value:webcrypto});w.localStorage.setItem('popcorn-mvp3-guest-access-v1','a'.repeat(64));
  w.eval(read('live-model.js'));w.eval(read('api-client.js'));
  w.MVP3Api=w.MVP3Api.createClient({storage:w.localStorage,cryptoImpl:webcrypto,fetchImpl:async(url,options)=>{
    calls.push({url,method:options.method,body:options.body?JSON.parse(options.body):null});
    if(url==='/api/mvp3/purchase-inquiries/form')return {ok:true,status:200,json:async()=>FORM,headers:{get:()=>null}};
    if(url==='/api/mvp3/purchase-inquiries'){const r=postReply();return {ok:r.status===200,status:r.status,json:async()=>r.data,headers:{get:()=>null}};}
    return {ok:true,status:200,json:async()=>({ok:true,quotes:[{id:qid,product,state:talk,saved_at:'2026-10-11T00:00:00Z'}],has_more:false}),headers:{get:()=>null}};
  }});
  w.eval(read('live-flow.js'));
  const create=w.MVP3LiveFlow.createFlow;let flow;
  w.MVP3LiveFlow.createFlow=(...args)=>{flow=create(...args);return flow;};
  w.eval(read('live-photo.js'));w.eval(read('app.js'));
  return {w,doc:w.document,get flow(){return flow;},calls,errors,close:()=>dom.window.close()};
}
function fill(h,values){
  for(const [k,v] of Object.entries(values)){
    const e=h.doc.querySelector('[data-inquiry='+k+']');
    if(e.type==='checkbox')e.checked=v;else e.value=v;
    e.dispatchEvent(new h.w.Event('input',{bubbles:true}));
  }
}
async function openForm(h){
  await until(()=>h.doc.querySelector('[data-action=load]'));
  h.doc.querySelector('[data-action=load]').click();
  await until(()=>h.flow.state.screen==='final'&&h.doc.querySelector('[data-action=inquiry-open]'));
  h.doc.querySelector('[data-action=inquiry-open]').click();
  await until(()=>h.doc.querySelector('[data-action=inquiry-send]'));
}

test('opens with server topics, blocks without contact or consent, then posts once',async()=>{
  const h=harness(()=>({status:200,data:{ok:true,inquiry_no:'PI-1001',note:'CODE/MOCK 신청을 받았어요.'}}));
  try{
    await openForm(h);
    const opts=[...h.doc.querySelectorAll('[data-inquiry=topic] option')].map(o=>o.textContent);
    assert.deepEqual(opts.slice(1),FORM.topics);
    assert.match(h.doc.querySelector('.live-inquiry-consent').textContent,/CODE\/MOCK 동의 문구/);
    assert.match(h.doc.querySelector('[data-inquiry-form]').textContent,/주문이나 결제가 진행되지는 않아요/);

    fill(h,{topic:'여러 대 구매',name:'QA-구매자',message:'3대 견적'});
    h.doc.querySelector('[data-action=inquiry-send]').click();await tick();
    assert.match(h.doc.querySelector('.live-inquiry-error').textContent,/전화번호나 이메일/);
    fill(h,{phone:'010-1234-5678'});
    h.doc.querySelector('[data-action=inquiry-send]').click();await tick();
    assert.match(h.doc.querySelector('.live-inquiry-error').textContent,/동의/);
    assert.equal(h.calls.filter(c=>c.method==='POST').length,0,'nothing sent before the form is complete');
    assert.equal(h.doc.querySelector('[data-inquiry=name]').value,'QA-구매자','values survive re-render');

    fill(h,{consent:true});
    h.doc.querySelector('[data-action=inquiry-send]').click();
    await until(()=>h.flow.state.inquiry.done&&h.flow.state.phase===null);
    const posts=h.calls.filter(c=>c.method==='POST');
    assert.equal(posts.length,1);
    assert.deepEqual(posts[0].body,{topic:'여러 대 구매',consent:true,phone:'010-1234-5678',name:'QA-구매자',message:'3대 견적',quote_id:qid,product_code:113836});
    const done=h.doc.querySelector('[data-inquiry-done]');
    assert.match(done.textContent,/PI-1001/);
    assert.match(done.textContent,/주문과 결제는 아직 진행되지 않았어요/);
    assert.equal(h.doc.querySelector('[data-action=inquiry-send]'),null);
    assert.equal(h.doc.querySelector('[data-action=inquiry-open]'),null,'no second form after a sent inquiry');
    await new Promise(r=>setTimeout(r,50));
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('a 422 reason from the server is shown inside the form and the draft stays',async()=>{
  const h=harness(()=>({status:422,data:{detail:'이메일 형식을 확인해 주세요.'}}));
  try{
    await openForm(h);
    fill(h,{topic:'할인',email:'qa@example.com',consent:true});
    h.doc.querySelector('[data-action=inquiry-send]').click();
    await until(()=>h.flow.state.inquiry.error&&h.flow.state.phase===null);
    assert.equal(h.flow.state.inquiry.done,null);
    assert.match(h.doc.querySelector('.live-inquiry-error').textContent,/이메일 형식/);
    assert.equal(h.doc.querySelector('[data-inquiry=email]').value,'qa@example.com');
    assert.equal(h.doc.querySelector('[data-inquiry=consent]').checked,true);
  }finally{h.close();}
});

test('a reply without a valid inquiry number is not shown as accepted',async()=>{
  const h=harness(()=>({status:200,data:{ok:true,inquiry_no:'<b>x</b>'}}));
  try{
    await openForm(h);
    fill(h,{topic:'기타',phone:'01012345678',consent:true});
    h.doc.querySelector('[data-action=inquiry-send]').click();
    await until(()=>h.flow.state.inquiry.error&&h.flow.state.phase===null);
    assert.equal(h.flow.state.inquiry.done,null);
    assert.equal(h.doc.querySelector('[data-inquiry-done]'),null);
  }finally{h.close();}
});
