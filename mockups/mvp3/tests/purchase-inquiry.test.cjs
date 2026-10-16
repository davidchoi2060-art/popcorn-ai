'use strict';
// 보관 견적 -> 상담 신청 접수(api/mvp3_quote_consult · 2026-10-16 두 구매 흐름). CODE/MOCK fixture 로만 확인한다(실 DB·실 POST 없음).
// 옛 최종 견적 화면의 「구매 상담 신청」 칸은 삭제됐다 -- 같은 약속을 보관 완료 화면 -> 상담 화면에서 지킨다.
// ① 「상담 내용 남기기」를 누르면 서버가 준 주제로 상담 화면이 열린다 ② 연락처·동의가 없으면 연락처를 보내지 않는다
// ③ 보관 견적 번호와 고른 주제를 함께 접수하고 받은 신청 번호를 보여 준다
// ④ 서버가 거절하면 같은 상담 화면에 실패를 말하고 적던 값은 남는다 ⑤ 신청 번호가 없는 응답은 접수로 보이지 않는다.
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),{webcrypto}=require('node:crypto');
const {JSDOM,VirtualConsole}=require('jsdom');
const base=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(base,n),'utf8');
const qid='44444444-4444-4444-8444-444444444444';
const talk={usages:['사무용'],budget_won:1500000};
const product={product_code:113836,name:'CODE/MOCK 보관 PC',price:900000,price_src:'보관 시점 판매가',spec:{cpu:'CPU'},reasons:['이유'],over_budget:false,ai_composed:true};
const FORM={ok:true,topics:['여러 대 구매','할인','세금계산서·영수증','주문 희망','기타'],consent_text:'CODE/MOCK 동의 문구.'};
const MASKED='010-****-0000';
const reply=(status,data)=>({ok:status===200,status,json:async()=>data,headers:{get:()=>null}});
const tick=()=>new Promise(r=>setImmediate(r));
async function until(check){for(let n=0;n<400;n++){if(check())return;await tick();}throw Error('render did not settle');}

function harness(postReply,{hasContact=false}={}){
  const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read('index.html'),{url:'https://qa.invalid/mvp3/#saved',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.TextEncoder=TextEncoder;
  Object.defineProperty(w,'crypto',{value:webcrypto});w.localStorage.setItem('popcorn-mvp3-guest-access-v1','a'.repeat(64));
  w.eval(read('live-model.js'));w.eval(read('api-client.js'));
  let contact=hasContact;
  w.MVP3Api=w.MVP3Api.createClient({storage:w.localStorage,cryptoImpl:webcrypto,fetchImpl:async(url,options)=>{
    calls.push({url,method:options.method,body:options.body?JSON.parse(options.body):null});
    if(url==='/api/mvp3/purchase-inquiries/form')return reply(200,FORM);
    if(url==='/api/mvp3/contact'&&options.method==='GET')return reply(200,{ok:true,has_contact:contact,...(contact?{masked_phone:MASKED}:{}),consent_text:FORM.consent_text});
    if(url==='/api/mvp3/contact'&&options.method==='PUT'){contact=true;return reply(200,{ok:true,has_contact:true,masked_phone:MASKED});}
    if(url==='/api/mvp3/purchase-inquiries/from-quote'){const r=postReply();return reply(r.status,r.data);}
    return reply(200,{ok:true,quotes:[{id:qid,product,state:talk,saved_at:'2026-10-11T00:00:00Z'}],has_more:false});
  }});
  w.eval(read('live-flow.js'));
  const create=w.MVP3LiveFlow.createFlow;let flow;
  w.MVP3LiveFlow.createFlow=(...args)=>{flow=create(...args);return flow;};
  w.eval(read('live-photo.js'));w.eval(read('app.js'));
  return {w,doc:w.document,get flow(){return flow;},calls,errors,close:()=>dom.window.close()};
}
const posts=h=>h.calls.filter(c=>c.url==='/api/mvp3/purchase-inquiries/from-quote');
const puts=h=>h.calls.filter(c=>c.method==='PUT');
function fillKeep(h,values){
  for(const [k,v] of Object.entries(values)){
    const e=h.doc.querySelector('[data-keep-page] [data-keep='+k+']');
    if(e.type==='checkbox')e.checked=v;else e.value=v;
    e.dispatchEvent(new h.w.Event('input',{bubbles:true}));
  }
}
// 보관 견적을 열면 보관 완료 화면 -> 「상담 내용 남기기 (선택)」 -> 상담 화면(서버 주제).
async function openConsult(h){
  await until(()=>h.doc.querySelector('[data-action=load]'));
  h.doc.querySelector('[data-action=load]').click();
  await until(()=>h.flow.state.screen==='final'&&h.doc.querySelector('section.tf-kept[data-keep-done]')&&h.flow.state.contact.loaded);
  assert.equal(h.doc.querySelector('[data-action=inquiry-open]'),null,'옛 최종 견적의 구매 상담 신청 단추는 없다');
  assert.equal(h.doc.querySelector('[data-inquiry-form]'),null);
  assert.doesNotMatch(h.doc.querySelector('#view').textContent,/최종 견적 확인/);
  assert.match(h.doc.querySelector('.tf-kept').textContent,/상담을 신청하기 전에는 먼저 연락드리지 않아요\./);
  h.doc.querySelector('[data-action=consult-note]').click();
  await until(()=>h.doc.querySelector('section.tf-consult select[data-consult-topic]'));
}
function pickTopic(h,topic){const s=h.doc.querySelector('[data-consult-topic]');s.value=topic;s.dispatchEvent(new h.w.Event('change',{bubbles:true}));}
function typeMessage(h,text){const t=h.doc.querySelector('[data-consult-message]');t.value=text;t.dispatchEvent(new h.w.Event('input',{bubbles:true}));}

test('opens with server topics, blocks without contact or consent, then posts once',async()=>{
  let n=0;
  const h=harness(()=>++n===1?{status:422,data:{detail:{error:'contact_required',detail:'연락처를 먼저 등록해 주세요.'}}}:
    {status:200,data:{ok:true,inquiry_no:'PI-1001',quote_id:qid,masked_phone:MASKED}});
  try{
    await openConsult(h);
    const opts=[...h.doc.querySelectorAll('[data-consult-topic] option')].map(o=>o.textContent);
    assert.deepEqual(opts,FORM.topics,'상담 주제는 서버가 준 것만');
    assert.equal(h.doc.querySelector('[data-consult-topic]').value,'주문 희망','기본 주제는 주문 희망');
    assert.equal(h.doc.querySelector('.tf-consult h2').textContent,'상담할 내용을 남겨 주세요');
    pickTopic(h,'여러 대 구매');typeMessage(h,'3대 견적');

    // 등록 연락처가 없으면 서버가 contact_required 로 돌려보내고, 연락처 화면을 연다.
    h.doc.querySelector('[data-action=consult-send]').click();
    await until(()=>h.doc.querySelector('section[data-keep-page]')&&h.flow.state.phase===null);
    assert.equal(posts(h).length,1);assert.equal(h.flow.state.consult.done,null);
    assert.equal(h.doc.querySelector('#keep-title').textContent,'연락처 등록');
    assert.equal(h.doc.querySelector('[data-keep-dialog]'),null,'index 는 창이 아니라 화면');
    assert.match(h.doc.querySelector('.keep-consent-text').textContent,/CODE\/MOCK 동의 문구/);

    h.doc.querySelector('[data-keep-page] [data-kact=submit]').click();await tick();
    assert.match(h.doc.querySelector('[data-keep-page] .keep-error').textContent,/전화번호/);
    fillKeep(h,{phone:'010-0000-0000',name:'QA-구매자'});
    h.doc.querySelector('[data-keep-page] [data-kact=submit]').click();await tick();
    assert.match(h.doc.querySelector('[data-keep-page] .keep-error').textContent,/동의/);
    assert.equal(puts(h).length,0,'연락처·동의가 갖춰지기 전에는 보내지 않는다');
    assert.equal(posts(h).length,1,'다시 접수하지 않는다');
    assert.equal(h.doc.querySelector('[data-keep-page] [data-keep=name]').value,'QA-구매자','values survive re-render');

    fillKeep(h,{consent:true});
    h.doc.querySelector('[data-keep-page] [data-kact=submit]').click();
    await until(()=>h.flow.state.consult.done&&h.flow.state.phase===null);
    assert.equal(puts(h).length,1);
    assert.deepEqual(puts(h)[0].body,{phone:'010-0000-0000',consent:true,name:'QA-구매자'});
    assert.equal(posts(h).length,2);
    assert.deepEqual(posts(h)[1].body,{quote_id:qid,message:'3대 견적',topic:'여러 대 구매'});
    const done=h.doc.querySelector('section.tf-done[data-consult-done=new]');
    assert.ok(done);assert.match(done.textContent,/상담 신청이 접수됐어요/);assert.match(done.textContent,/PI-1001/);
    assert.match(done.querySelector('dl.consult-rows').textContent,/상담 신청 번호PI-1001함께 보낸 견적Q-44444444연락받을 전화번호010-\*\*\*\*-0000/);
    assert.match(done.textContent,/주문·결제는 아직 진행되지 않았어요/);
    assert.equal(h.doc.querySelector('[data-action=consult-send]'),null,'no second request after a sent inquiry');
    assert.equal(h.doc.querySelector('[data-action=inquiry-open]'),null);
    await new Promise(r=>setTimeout(r,50));
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('a 422 reason from the server is shown inside the form and the draft stays',async()=>{
  const h=harness(()=>({status:422,data:{detail:'CODE/MOCK 상담 내용을 확인해 주세요.'}}),{hasContact:true});
  try{
    await openConsult(h);
    assert.match(h.doc.querySelector('.tf-consult .tf-reg').textContent,/010-\*\*\*\*-0000/);
    pickTopic(h,'할인');typeMessage(h,'할인 문의');
    h.doc.querySelector('[data-action=consult-send]').click();
    await until(()=>h.flow.state.consult.error&&h.flow.state.phase===null);
    assert.equal(h.flow.state.consult.done,null);
    assert.equal(h.flow.state.consult.error,'CODE/MOCK 상담 내용을 확인해 주세요.','서버가 준 사유를 그대로 든다');
    assert.ok(h.doc.querySelector('section.tf-consult'),'같은 상담 화면에 남는다');
    assert.match(h.doc.querySelector('.tf-consult .tf-alert').textContent,/상담 신청을 접수하지 못했어요\./);
    assert.equal(h.doc.querySelector('[data-consult-message]').value,'할인 문의');
    assert.equal(h.doc.querySelector('[data-consult-topic]').value,'할인');
    assert.equal(h.doc.querySelector('[data-consult-done]'),null);
    assert.equal(posts(h).length,1);assert.deepEqual(posts(h)[0].body,{quote_id:qid,message:'할인 문의',topic:'할인'});
  }finally{h.close();}
});

test('a reply without a valid inquiry number is not shown as accepted',async()=>{
  const h=harness(()=>({status:200,data:{ok:true,inquiry_no:'<b>x</b>',quote_id:qid,masked_phone:MASKED}}),{hasContact:true});
  try{
    await until(()=>h.doc.querySelector('[data-action=load]'));
    h.doc.querySelector('[data-action=load]').click();
    await until(()=>h.doc.querySelector('section.tf-kept')&&h.flow.state.contact.loaded);
    // 「상담 신청 접수」로 바로 보내도 실패는 상담 화면에서 말한다.
    h.doc.querySelector('[data-action=consult-send]').click();
    await until(()=>h.flow.state.consult.error&&h.flow.state.phase===null);
    assert.equal(h.flow.state.consult.done,null);
    assert.equal(h.doc.querySelector('[data-consult-done]'),null);
    assert.equal(h.doc.querySelector('#view b'),null);
    assert.match(h.doc.querySelector('section.tf-consult .tf-alert').textContent,/상담 신청을 접수하지 못했어요\./);
    assert.deepEqual(posts(h)[0].body,{quote_id:qid},'주제를 고르지 않았으면 보내지 않는다');
  }finally{h.close();}
});
