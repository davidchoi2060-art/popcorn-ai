'use strict';
// 2겹 실시간 안전장치(api/mall_price_live): 보관하는 순간 쇼핑몰 현재가가 다르면 서버가 쇼핑몰 가격으로 보관하고
// price_check 로 그 사실을 돌려준다. 화면은 그 보관을 받아들이고 서버 문장을 그대로 보인다(CODE/MOCK fixture · 실 POST 없음).
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),{webcrypto}=require('node:crypto');
const {JSDOM,VirtualConsole}=require('jsdom');
const base=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(base,n),'utf8');
const qid='33333333-3333-4333-8333-333333333333';
const talk={usages:['사무용'],budget_won:1700000};
const item={product_code:98149,name:'CODE/MOCK 골드 PC',price:1585100,price_src:'판매가',spec:{cpu:'CPU'},reasons:['이유'],over_budget:false};
const CHANGED='쇼핑몰 현재 가격이 1,585,100원에서 1,624,400원으로 바뀌었습니다. 바뀐 가격으로 보관했습니다.';
const UNCHECKED='현재 가격 확인이 안 되어 쇼핑몰에서 최종 확인됩니다';
const tick=()=>new Promise(r=>setImmediate(r));
async function until(check){for(let n=0;n<80;n++){if(check())return;await tick();}throw Error('render did not settle');}
function harness(saved){
  const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read('index.html'),{url:'https://qa.invalid/mvp3/#welcome',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.TextEncoder=TextEncoder;
  Object.defineProperty(w,'crypto',{value:webcrypto});w.localStorage.setItem('popcorn-mvp3-guest-access-v1','a'.repeat(64));
  w.eval(read('live-model.js'));w.eval(read('api-client.js'));
  w.MVP3Api=w.MVP3Api.createClient({storage:w.localStorage,cryptoImpl:webcrypto,fetchImpl:async(url,options)=>{
    const body=options.body?JSON.parse(options.body):null;calls.push({url,method:options.method,body});
    let data;
    if(url==='/api/talk/parse')data={ok:true,state:talk,history:[],missing:[]};
    else if(url==='/api/grid/recommend')data={ok:true,card_sets:[{kind:'sold',usage:'사무용',items:[item]}]};
    else if(options.method==='POST'&&url==='/api/mvp3/saved-quotes')data={ok:true,quote:{id:qid,product:saved(body),state:body.state,saved_at:'2026-10-11T01:00:00Z'}};
    else data={ok:true,quotes:[],has_more:false};
    return {ok:true,status:200,json:async()=>data,headers:{get:()=>null}};
  }});w.eval(read('live-flow.js'));
  const create=w.MVP3LiveFlow.createFlow;let flow;
  w.MVP3LiveFlow.createFlow=(...args)=>{flow=create(...args);return flow;};
  w.eval(read('live-photo.js'));w.eval(read('app.js'));
  return {doc:w.document,get flow(){return flow;},calls,errors,click:s=>w.document.querySelector(s).click(),close:()=>dom.window.close()};
}
async function save(h){
  await h.flow.submit('CODE/MOCK 사무용');await until(()=>h.doc.querySelector('[data-action=detail]'));
  h.click('[data-action=detail]');h.click('[data-action=final]');h.click('[data-action=save]');
  await until(()=>h.flow.state.phase===null&&h.flow.state.saveState!=='saving');
}
async function run(saved,body){
  const h=harness(saved);let passed=false;
  try{await body(h);passed=true;}
  finally{await new Promise(r=>setTimeout(r,50));const errors=[...h.errors];h.close();if(passed)assert.deepEqual(errors,[]);}
}
const check=(status,mall,message)=>({status,quoted:1585100,mall,diff:mall===null?null:mall-1585100,saved:status==='changed',message,checked_at:'2026-10-11T01:00:00Z'});

test('changed mall price at save: saved at the mall price and the server sentence is shown',async()=>{
  await run(body=>({...item,price:1624400,price_check:check('changed',1624400,CHANGED)}),async h=>{
    await save(h);
    assert.equal(h.flow.state.saveState,'saved');
    assert.equal(h.flow.state.savedQuote.product.price,1624400);
    assert.equal(h.calls.find(c=>c.method==='POST'&&c.url==='/api/mvp3/saved-quotes').body.expected_price,1585100);
    const panel=h.doc.querySelector('.live-price-check');
    assert.ok(panel,'price notice shown');assert.equal(panel.dataset.priceCheck,'changed');
    assert.match(panel.textContent,/1,585,100원에서 1,624,400원으로/);
  });
});

test('unreadable mall price at save: saved at the card price with the final-check sentence',async()=>{
  await run(body=>({...item,price:body.expected_price,price_check:check('unchecked',null,UNCHECKED)}),async h=>{
    await save(h);
    assert.equal(h.flow.state.saveState,'saved');
    assert.equal(h.doc.querySelector('.live-price-check').textContent.includes(UNCHECKED),true);
  });
});

test('same mall price: no notice',async()=>{
  await run(body=>({...item,price:body.expected_price,price_check:check('same',1585100,null)}),async h=>{
    await save(h);
    assert.equal(h.flow.state.saveState,'saved');
    assert.equal(h.doc.querySelector('.live-price-check'),null);
  });
});

test('a different price without a matching server price check is still refused',async()=>{
  // 서버가 「바뀌었다」고 말하지 않았거나 보던 가격이 요청과 다르면 받지 않는다(조용한 가격 교체 차단).
  for(const saved of [body=>({...item,price:1624400}),
                      body=>({...item,price:1624400,price_check:{...check('changed',1624400,CHANGED),quoted:1500000}}),
                      body=>({...item,price:1700000,price_check:check('changed',1624400,CHANGED)})]){
    await run(saved,async h=>{await save(h);assert.notEqual(h.flow.state.saveState,'saved');assert.equal(h.flow.state.savedQuote,null);});
  }
});
