'use strict';
// 보관 견적 -> 팝콘PC 쇼핑몰 인계(api/mvp3_handoff.py). CODE/MOCK fixture 로만 확인한다(실 DB·실 POST 없음).
// ① 보관 전에는 구매 단추가 없다 ② 보관 견적에서 누르면 그 견적 번호로 한 번만 POST 한다
// ③ 서버가 준 쇼핑몰 가격이 다르면 화면이 그 차이를 말하고, 쇼핑몰 링크를 연다.
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),{webcrypto}=require('node:crypto');
const {JSDOM,VirtualConsole}=require('jsdom');
const base=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(base,n),'utf8');
const qid='33333333-3333-4333-8333-333333333333';
const talk={usages:['사무용'],budget_won:1500000};
const product={product_code:113836,name:'CODE/MOCK 보관 PC',price:900000,price_src:'보관 시점 판매가',spec:{cpu:'CPU'},reasons:['이유'],over_budget:false};
const MALL='https://popcornpc.co.kr/shop/product_detail.html?pd_no=113836';
const tick=()=>new Promise(r=>setImmediate(r));
async function until(check){for(let n=0;n<400;n++){if(check())return;await tick();}throw Error('render did not settle');}

// 새 창: 누른 순간 빈 창을 열고, 연결이 끝나면 그 창을 쇼핑몰로 보낸다(2026-10-12 중헌 님 고객단 6번). popup:false 면 브라우저가 막은 경우.
function fakeTabs(popup=true){
  const tabs=[];
  const open=()=>{if(!popup)return null;const t={opener:{},closed:false,location:{href:''},document:{title:''},close(){t.closed=true;}};tabs.push(t);return t;};
  return {tabs,open};
}
function harness(handoffResponse,{popup=true,status=200}={}){
  const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read('index.html'),{url:'https://qa.invalid/mvp3/#saved',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.TextEncoder=TextEncoder;
  const tabs=fakeTabs(popup);w.open=tabs.open;
  Object.defineProperty(w,'crypto',{value:webcrypto});w.localStorage.setItem('popcorn-mvp3-guest-access-v1','a'.repeat(64));
  w.eval(read('live-model.js'));w.eval(read('api-client.js'));
  w.MVP3Api=w.MVP3Api.createClient({storage:w.localStorage,cryptoImpl:webcrypto,fetchImpl:async(url,options)=>{
    calls.push({url,method:options.method,key:options.headers['X-Access-Key']});
    const handoff=url.endsWith('/handoff');
    const data=handoff?handoffResponse:{ok:true,quotes:[{id:qid,product:handoffResponse?.product||product,state:talk,saved_at:'2026-10-11T00:00:00Z'}],has_more:false};
    const code=handoff?status:200;
    return {ok:code<400,status:code,json:async()=>data,headers:{get:()=>null}};
  }});
  w.eval(read('live-flow.js'));
  const create=w.MVP3LiveFlow.createFlow;let flow;
  w.MVP3LiveFlow.createFlow=(...args)=>{flow=create(...args);return flow;};
  w.eval(read('live-photo.js'));w.eval(read('app.js'));
  return {doc:w.document,get flow(){return flow;},calls,errors,tabs:tabs.tabs,close:()=>dom.window.close()};
}

test('saved quote shows the mall purchase button and posts once with the quote id',async()=>{
  const h=harness({ok:true,handoff_no:'HO-2001',quote_id:qid,product_code:113836,name:product.name,
    price_quoted:900000,price_mall:910000,mall_status:'가격변동',mall_url:MALL});
  try{
    await until(()=>h.doc.querySelector('[data-action=load]'));
    h.doc.querySelector('[data-action=load]').click();
    await until(()=>h.flow.state.screen==='final'&&h.doc.querySelector('[data-action=handoff]'));
    h.doc.querySelector('[data-action=handoff]').click();
    await until(()=>h.flow.state.handoff&&h.flow.state.phase===null);
    const posts=h.calls.filter(c=>c.method==='POST');
    assert.equal(posts.length,1);
    assert.equal(posts[0].url,'/api/mvp3/saved-quotes/'+qid+'/handoff');
    assert.match(posts[0].key,/^[a]{64}$/);
    const view=h.doc.querySelector('#view'),link=view.querySelector('.live-handoff a');
    assert.equal(link.getAttribute('href'),MALL);
    assert.equal(link.getAttribute('target'),'_blank');
    assert.match(view.textContent,/910,000원/);
    assert.match(view.textContent,/900,000원/);
    assert.equal(view.querySelector('[data-action=handoff]'),null,'button replaced by the result');
    // 2026-10-12 사장님 「클릭했더니 없어져 버리고」: 단추 자리에 쇼핑몰 링크가 남는다.
    const kept=view.querySelector('.final-buttons a.final-mall-link');
    assert.equal(kept.getAttribute('href'),MALL);assert.equal(kept.getAttribute('target'),'_blank');
    assert.ok(view.querySelector('.final-next .live-handoff'),'handoff result sits in the full-width next-step row');
    // 한 번 누르면 쇼핑몰까지 간다 -- 미리 연 새 창이 쇼핑몰 주소로 간다(다시 누를 필요 없음).
    assert.equal(h.tabs.length,1);assert.equal(h.tabs[0].location.href,MALL);assert.equal(h.tabs[0].opener,null);assert.equal(h.tabs[0].closed,false);
    await new Promise(r=>setTimeout(r,50));
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('a handoff response without a safe mall link is rejected, not shown',async()=>{
  const h=harness({ok:true,handoff_no:'HO-2002',quote_id:qid,price_quoted:900000,price_mall:900000,mall_status:'확인됨',mall_url:'javascript:alert(1)'});
  try{
    await until(()=>h.doc.querySelector('[data-action=load]'));
    h.doc.querySelector('[data-action=load]').click();
    await until(()=>h.doc.querySelector('[data-action=handoff]'));
    h.doc.querySelector('[data-action=handoff]').click();
    await until(()=>h.flow.state.error&&h.flow.state.phase===null);
    assert.equal(h.flow.state.handoff,null);
    assert.equal(h.doc.querySelector('.live-handoff'),null);
    assert.equal(h.flow.state.retry.kind,'handoff');
    assert.equal(h.tabs[0].closed,true,'the blank tab opened for the mall is closed when the link is refused');
  }finally{h.close();}
});

// 2026-10-12 끝까지 검수 O4: 연결이 502 로 실패하면 단추 바로 아래에 말한다(화면 맨 위 오류 칸은 모바일에서 3,700px 위였다).
test('a failed handoff is told right under the purchase button and the blank tab is closed',async()=>{
  const h=harness({ok:false,detail:'잠시 후 다시 시도해 주세요.'},{status:502});
  try{
    await until(()=>h.doc.querySelector('[data-action=load]'));
    h.doc.querySelector('[data-action=load]').click();
    await until(()=>h.doc.querySelector('[data-action=handoff]'));
    h.doc.querySelector('[data-action=handoff]').click();
    await until(()=>h.flow.state.error&&h.flow.state.phase===null);
    const view=h.doc.querySelector('#view'),note=view.querySelector('.final-handoff-error');
    assert.ok(note,'error sits next to the buttons');assert.equal(note.getAttribute('role'),'alert');
    assert.ok(note.previousElementSibling.classList.contains('final-buttons'));
    assert.match(note.textContent,/쇼핑몰 연결을 준비하지 못했어요/);
    assert.equal(view.querySelector('.live-error'),null,'not repeated at the top of the screen');
    assert.ok(view.querySelector('.final-buttons [data-action=handoff]:not([disabled])'),'the same button tries again');
    assert.equal(h.tabs[0].closed,true);
  }finally{h.close();}
});

test('when the browser blocks the new tab the mall link stays on the screen',async()=>{
  const h=harness({ok:true,handoff_no:'HO-2003',quote_id:qid,product_code:113836,name:product.name,
    price_quoted:900000,price_mall:900000,mall_status:'확인됨',mall_url:MALL},{popup:false});
  try{
    await until(()=>h.doc.querySelector('[data-action=load]'));
    h.doc.querySelector('[data-action=load]').click();
    await until(()=>h.doc.querySelector('[data-action=handoff]'));
    h.doc.querySelector('[data-action=handoff]').click();
    await until(()=>h.flow.state.handoff&&h.flow.state.phase===null);
    assert.equal(h.doc.querySelector('.final-buttons a.final-mall-link').getAttribute('href'),MALL);
    assert.match(h.doc.querySelector('.live-handoff').textContent,/쇼핑몰 가격도 900,000원으로 같아요/);
  }finally{h.close();}
});

// 2026-10-12 끝까지 검수 O3: 부품을 바꾼 견적(1,576,200원)에 「쇼핑몰 가격도 1,624,400원으로 같아요」라고 했다.
test('a changed-part quote says the mall page is the base build and gives the quote total',async()=>{
  const build={base_price:1624400,changes:[{ordinal:3,slot:'GPU',label:'그래픽카드',quantity:1,before:{product_code:1,name:'원래',price:500000},after:{product_code:2,name:'바꾼',price:451800},delta:-48200}]};
  const built={...product,price:1576200,build};
  const h=harness({ok:true,handoff_no:'HO-2004',quote_id:qid,product_code:113836,name:product.name,
    price_quoted:1624400,price_mall:1624400,mall_status:'확인됨',mall_url:MALL,changes:[{delta:-48200}],product:built});
  try{
    await until(()=>h.doc.querySelector('[data-action=load]'));
    h.doc.querySelector('[data-action=load]').click();
    await until(()=>h.doc.querySelector('[data-action=handoff]'));
    h.doc.querySelector('[data-action=handoff]').click();
    await until(()=>h.flow.state.handoff&&h.flow.state.phase===null);
    const t=h.doc.querySelector('.live-handoff').textContent;
    assert.doesNotMatch(t,/쇼핑몰 가격도/);
    assert.match(t,/기본 구성 1,624,400원 \u2192 바꾼 구성 1,576,200원/);assert.doesNotMatch(t,/48,200원|차액/);assert.match(t,/주문·결제는 아직 진행되지 않았어요/);
  }finally{h.close();}
});

test('before saving there is no purchase button',()=>{
  const app=read('app.js');
  assert.match(app,/saved&&state\.savedQuote&&!handoffDone\?button\(/);
});
