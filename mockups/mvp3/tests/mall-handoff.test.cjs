'use strict';
// 보관 견적 -> 팝콘PC 쇼핑몰 인계(api/mvp3_handoff.py). CODE/MOCK fixture 로만 확인한다(실 DB·실 POST 없음).
// 2026-10-16 P2-1: 옛 최종 화면(「쇼핑몰 구매」 단추)은 없어졌다. 「내 견적」에서 연 완제품 보관 견적도 같은 상품 상세를 그리고,
// 오른쪽 칸의 「팝콘PC에서 상품 보기」 한 번으로 ① 그 견적 번호로 인계를 한 번만 POST 하고 ② 성공한 뒤에만 미리 연 새 창을 쇼핑몰로 보내며
// ③ 서버가 준 쇼핑몰 가격이 다르면 이동 안내 화면이 그 차이를 말한다. 실패하면 창 없이 오른쪽 칸 안에서 말한다.
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),{webcrypto}=require('node:crypto');
const {JSDOM,VirtualConsole}=require('jsdom');
const base=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(base,n),'utf8');
const qid='33333333-3333-4333-8333-333333333333';
const talk={usages:['사무용'],budget_won:1500000};
const configuration={product_code:113836,configuration_id:'P10',revision:1,offer_id:'P113836',
  description:{title:'검증 PC',intro:'근거 설명',scene:null,benefits:[],checks:[],faq:[]},
  parts:[{ordinal:0,slot:'CPU',quantity:1,pseudo:false,name:'CPU A',description:'역할',specs:[{label:'소켓',value:'AM5'}]},
    {ordinal:3,slot:'GPU',quantity:1,pseudo:false,name:'원래',description:'역할',specs:[]}],
  price:{state:'unknown',amount:null,checked_at:null,observed_date:null,model:null},stock:{state:'unknown',checked_at:null},
  compatibility:{document_state:'pass',public_summary:null,assembly_state:'unknown'},photo:{state:'unresolved',url:null},
  customer_conditions:Object.fromEntries(['os','keyboard','mouse','monitor','warranty'].map(k=>[k,{state:'unknown',detail:'',months:null,needs_reconfirmation:false,customer_statement:'구매 전에 확인해 주세요.'}]))};
const product={product_code:113836,name:'CODE/MOCK 보관 PC',price:900000,price_src:'보관 시점 판매가',spec:{cpu:'CPU'},reasons:['이유'],over_budget:false,public_configuration:configuration};
const MALL='https://popcornpc.co.kr/shop/product_detail.html?pd_no=113836';
const tick=()=>new Promise(r=>setImmediate(r));
async function until(check){for(let n=0;n<400;n++){if(check())return;await tick();}throw Error('render did not settle');}
const text=e=>e.textContent.replace(/\s+/g,' ').trim();

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
// 「내 견적」 -> 보관 견적 열기 -> (final 이지만) 완제품 상세 -> 오른쪽 칸 「팝콘PC에서 상품 보기」.
async function openSavedAndView(h){
  await until(()=>h.doc.querySelector('[data-action=load]'));
  h.doc.querySelector('[data-action=load]').click();
  await until(()=>h.flow.state.screen==='final'&&h.doc.querySelector('.tf-detail aside.tf-side [data-action=mall-view]'));
  const main=h.doc.querySelector('aside.tf-side [data-action=mall-view]');
  assert.equal(main.disabled,false,'보관 견적이 있으면 주소를 몰라도 이동할 수 있다');
  assert.equal(h.doc.querySelector('[data-action=handoff]'),null,'옛 「쇼핑몰 구매」 단추는 없다');
  main.click();
  assert.equal(h.doc.querySelector('[data-mall-dialog]'),null,'「상품 보기」는 안내창 없이 바로 간다');
  await until(()=>h.flow.state.phase===null&&['moved','failed'].includes(h.flow.state.mall.step));
}

test('saved quote: 팝콘PC에서 상품 보기 posts the handoff once with the quote id and the moved page tells the mall price change',async()=>{
  const h=harness({ok:true,handoff_no:'HO-2001',quote_id:qid,product_code:113836,name:product.name,
    price_quoted:900000,price_mall:910000,mall_status:'가격변동',mall_url:MALL});
  try{
    await openSavedAndView(h);
    assert.equal(h.flow.state.mall.step,'moved');
    const posts=h.calls.filter(c=>c.method==='POST');
    assert.equal(posts.length,1,'이미 보관된 견적이라 보관을 다시 보내지 않고 인계만 한 번');
    assert.equal(posts[0].url,'/api/mvp3/saved-quotes/'+qid+'/handoff');
    assert.match(posts[0].key,/^[a]{64}$/);
    const view=h.doc.querySelector('#view'),moved=view.querySelector('.tf-moved[data-mall-state=moved]');
    assert.ok(moved,'이동 안내 화면');
    const link=moved.querySelector('a[data-mall-reopen]');
    assert.equal(link.getAttribute('href'),MALL);assert.equal(link.getAttribute('target'),'_blank');assert.match(text(link),/상품 페이지 다시 보기/);
    assert.match(text(moved),/연결 번호 ?HO-2001/);
    const warn=[...moved.querySelectorAll('.warn-text')].map(text).join(' ');
    assert.match(warn,/910,000원/);assert.match(warn,/900,000원/);
    assert.equal(view.querySelector('[data-action=handoff]'),null);
    assert.match(text(moved),/주문이나 결제가 완료된 상태는 아니에요\./);
    // 한 번 누르면 쇼핑몰까지 간다 -- 미리 연 새 창이 쇼핑몰 주소로 간다(다시 누를 필요 없음).
    assert.equal(h.tabs.length,1);assert.equal(h.tabs[0].location.href,MALL);assert.equal(h.tabs[0].opener,null);assert.equal(h.tabs[0].closed,false);
    await new Promise(r=>setTimeout(r,50));
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('a handoff response without a safe mall link is rejected, not shown',async()=>{
  const h=harness({ok:true,handoff_no:'HO-2002',quote_id:qid,price_quoted:900000,price_mall:900000,mall_status:'확인됨',mall_url:'javascript:alert(1)'});
  try{
    await openSavedAndView(h);
    assert.equal(h.flow.state.mall.step,'failed');
    assert.equal(h.flow.state.handoff,null);
    assert.equal(h.doc.querySelector('.tf-moved'),null);
    assert.equal(h.doc.querySelector('[data-mall-reopen]'),null);
    assert.ok(!h.doc.querySelector('#view').innerHTML.includes('javascript:'),'unsafe link never reaches the page');
    assert.ok(h.doc.querySelector('aside.tf-side [data-mall-state=failed]'));
    assert.equal(h.tabs[0].closed,true,'the blank tab opened for the mall is closed when the link is refused');
    assert.equal(h.tabs[0].location.href,'');
  }finally{h.close();}
});

// 2026-10-12 끝까지 검수 O4: 연결이 502 로 실패하면 단추 바로 아래에 말한다(화면 맨 위 오류 칸은 모바일에서 3,700px 위였다).
test('a failed handoff is told right under the purchase button and the blank tab is closed',async()=>{
  const h=harness({ok:false,detail:'잠시 후 다시 시도해 주세요.'},{status:502});
  try{
    await openSavedAndView(h);
    const view=h.doc.querySelector('#view'),side=view.querySelector('aside.tf-side'),note=side.querySelector('[data-mall-state=failed]');
    assert.ok(note,'error sits in the same summary column as the button');assert.equal(note.getAttribute('role'),'alert');
    const main=side.querySelector('.tf-main[data-action=mall-view]');
    assert.ok(main.compareDocumentPosition(note)&h.doc.defaultView.Node.DOCUMENT_POSITION_FOLLOWING,'the note comes after the main button');
    assert.match(text(note),/상품 페이지를 열지 못했어요\./);assert.match(text(note),/현재 구성은 그대로예요\. 잠시 후 다시 시도해 주세요\./);
    assert.equal(view.querySelector('.live-error'),null,'not repeated at the top of the screen');
    assert.equal(h.doc.querySelector('[data-mall-dialog]'),null,'no dialog');
    const again=note.querySelector('[data-action=mall-view]:not([disabled])');assert.ok(again,'다시 연결하기 tries again');assert.equal(text(again),'다시 연결하기');
    assert.equal(h.doc.activeElement,again,'focus moves to the retry button');
    assert.equal(h.tabs[0].closed,true);
    again.click();await until(()=>h.flow.state.phase===null&&h.flow.state.mall.step==='failed'&&h.tabs.length===2);
    assert.equal(h.calls.filter(c=>c.method==='POST').length,2,'retry is one more handoff POST, never a new save');
    assert.equal(h.tabs[1].closed,true);
  }finally{h.close();}
});

test('when the browser blocks the new tab the mall link stays on the screen',async()=>{
  const h=harness({ok:true,handoff_no:'HO-2003',quote_id:qid,product_code:113836,name:product.name,
    price_quoted:900000,price_mall:900000,mall_status:'확인됨',mall_url:MALL},{popup:false});
  try{
    await openSavedAndView(h);
    const moved=h.doc.querySelector('.tf-moved[data-mall-state=moved]');assert.ok(moved);
    assert.match(text(moved),/새 창이 열리지 않았어요/);
    assert.equal(moved.querySelector('a[data-mall-reopen]').getAttribute('href'),MALL);
    assert.match(text(moved),/기본 구성 900,000원/);
    assert.equal(moved.querySelectorAll('.warn-text').length,0,'same price: no price warning');
    assert.equal(h.calls.filter(c=>c.url.endsWith('/handoff')).length,1);
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
    await until(()=>h.doc.querySelector('aside.tf-side [data-action=mall-view]'));
    // 이동 전 상세: 보관 견적 금액(바꾼 구성)과 「팝콘PC 상품 페이지는 기본 구성 기준」을 함께 말한다.
    const side=text(h.doc.querySelector('aside.tf-side'));
    assert.match(side,/1,576,200원/);assert.match(side,/팝콘PC 상품 페이지는 기본 구성 기준이에요\./);
    h.doc.querySelector('aside.tf-side [data-action=mall-view]').click();
    await until(()=>h.flow.state.phase===null&&h.flow.state.mall.step==='moved');
    const t=text(h.doc.querySelector('.tf-moved'));
    assert.doesNotMatch(t,/쇼핑몰 가격도|같아요/);
    assert.match(t,/기본 구성 1,624,400원/);assert.match(t,/바꾼 부품 1개는 연결 번호로 기록해 두었어요\./);
    assert.doesNotMatch(t,/48,200원|차액/);assert.match(t,/주문이나 결제가 완료된 상태는 아니에요/);
  }finally{h.close();}
});

// 옛 최종 화면(renderFinal: 「최종 견적 확인」·견적 저장·「쇼핑몰 구매」 단추·priceCheckPanel·handoffPanel)은 지워졌다.
// 이동 단추는 상세 오른쪽 칸의 「팝콘PC에서 상품 보기」 하나다.
test('the old final page and its 쇼핑몰 구매 button are gone; the mall move lives only in the detail summary',()=>{
  const app=read('app.js');
  assert.doesNotMatch(app,/function renderFinal\b|최종 견적 확인|function priceCheckPanel\b|function handoffPanel\b/);
  assert.doesNotMatch(app,/button\([^)]*'handoff'/,'no button issues data-action=handoff');
  assert.doesNotMatch(app,/saved&&state\.savedQuote&&!handoffDone\?button\(/);
  assert.match(app,/button\(\(moving\?'이동하는 중…':'팝콘PC에서 상품 보기'\)/);
});

// 구성표가 없는 완제품(옛 상세 .dt-detail)도 연결 실패를 화면에 남긴다 — 예전엔 v2 오른쪽 칸만 실패를 그려 조용히 아무 일도 없었다.
test('legacy mall detail without a configuration table shows the handoff failure in its aside',async()=>{
  const legacy={...product,public_configuration:undefined};
  const h=harness({ok:false,product:legacy,detail:'잠시 후 다시 시도해 주세요.'},{status:502});
  try{
    await until(()=>h.doc.querySelector('[data-action=load]'));
    h.doc.querySelector('[data-action=load]').click();
    await until(()=>h.flow.state.screen==='final'&&h.doc.querySelector('.dt-detail'));
    assert.equal(h.doc.querySelector('.tf-detail'),null,'구성표가 없으면 옛 상세');
    assert.equal(h.doc.querySelector('.dt-detail [data-action=back]'),null,'옛 상세에도 「이전 화면」 단추는 없다');
    h.doc.querySelector('#actions [data-action=mall-view]').click();
    await until(()=>h.doc.querySelector('.dt-detail [data-mall-state=failed]'));
    const alert=h.doc.querySelector('.dt-detail [data-mall-state=failed]');
    assert.equal(alert.getAttribute('role'),'alert');
    assert.match(text(alert),/상품 페이지를 열지 못했어요\./);
    assert.ok(alert.querySelector('[data-action=mall-view]'),'다시 연결하기');
    assert.equal(h.calls.filter(c=>c.url.endsWith('/handoff')).length,1);
    assert.ok(h.tabs.every(t=>t.closed),'미리 연 창은 닫는다');
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});
