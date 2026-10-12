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

function harness(handoffResponse){
  const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read('index.html'),{url:'https://qa.invalid/mvp3/#saved',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.TextEncoder=TextEncoder;
  Object.defineProperty(w,'crypto',{value:webcrypto});w.localStorage.setItem('popcorn-mvp3-guest-access-v1','a'.repeat(64));
  w.eval(read('live-model.js'));w.eval(read('api-client.js'));
  w.MVP3Api=w.MVP3Api.createClient({storage:w.localStorage,cryptoImpl:webcrypto,fetchImpl:async(url,options)=>{
    calls.push({url,method:options.method,key:options.headers['X-Access-Key']});
    const data=url.endsWith('/handoff')?handoffResponse:{ok:true,quotes:[{id:qid,product,state:talk,saved_at:'2026-10-11T00:00:00Z'}],has_more:false};
    return {ok:true,status:200,json:async()=>data,headers:{get:()=>null}};
  }});
  w.eval(read('live-flow.js'));
  const create=w.MVP3LiveFlow.createFlow;let flow;
  w.MVP3LiveFlow.createFlow=(...args)=>{flow=create(...args);return flow;};
  w.eval(read('live-photo.js'));w.eval(read('app.js'));
  return {doc:w.document,get flow(){return flow;},calls,errors,close:()=>dom.window.close()};
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
  }finally{h.close();}
});

test('before saving there is no purchase button',()=>{
  const app=read('app.js');
  assert.match(app,/saved&&state\.savedQuote&&!handoffDone\?button\(/);
});
