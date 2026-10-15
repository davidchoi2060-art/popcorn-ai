'use strict';
// 2026-10-11 중헌 님 「제품을 선택하고 부품 변경하는 부분 — 아직 안 된다」.
// 상품 상세의 「부품 바꾸기」 -> 그 부품만 다른 판매 PC 선택지(api/mvp3_part_options) -> 고르면 그 PC 가
// 새 선택이 되고 금액이 바뀐다 -> 보관도 쇼핑몰 연결도 바뀐 상품번호로 간다. CODE/MOCK fixture 로만 확인한다.
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),{webcrypto}=require('node:crypto');
const {JSDOM,VirtualConsole}=require('jsdom');
const base=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(base,n),'utf8');
const tick=()=>new Promise(r=>setImmediate(r));
async function until(check){for(let n=0;n<400;n++){if(check())return;await tick();}throw Error('render did not settle');}
const qid='44444444-4444-4444-8444-444444444444';
const pc=(code,price,extra={})=>({product_code:code,name:'PC '+code,price,price_src:'현재 판매가',spec:{cpu:'i5-14400F',gpu:'RTX 5060 8GB',ram_gb:16,ssd_gb:500,vram_gb:8},reasons:['게임 FHD'],over_budget:false,...extra});
const talkState={usages:['게임'],budget_won:1500000,budget_bound:'이하',game:{names:['배그']}};
const reco={ok:true,assumed:[],anchor_code:12,wants:{},card_sets:[{kind:'sold',usage:'게임',usage_grid:'게임',items:[pc(12,1300000,{tag:'추천 구성',role:'recommended'})]}],talk_notes:[],choices:[]};
const swapped=pc(22,1350000,{tag:'고른 구성',role:'chosen',spec:{cpu:'i5-14400F',gpu:'RTX 5060 8GB',ram_gb:32,ssd_gb:500,vram_gb:8},
  swap:{slot:'ram',value:'32GB',price_diff:50000,also:[]}});
const bigger=pc(23,1500000,{tag:'고른 구성',role:'chosen',spec:{cpu:'i5-14400F',gpu:'RTX 5060 8GB',ram_gb:64,ssd_gb:2000,vram_gb:8},
  swap:{slot:'ram',value:'64GB',price_diff:200000,also:[{label:'저장장치',from:'500GB',to:'2TB'}]}});
const MALL='https://popcornpc.co.kr/shop/product_detail.html?pd_no=22';

function harness({options=[swapped,bigger],fail=false}={}){
  const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read('index.html'),{url:'https://qa.invalid/mvp3/#welcome',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.TextEncoder=TextEncoder;
  w.HTMLElement.prototype.scrollIntoView=function(){};
  const tabs=[];w.open=()=>{const t={opener:w,document:{title:''},location:{href:''},closed:false,close(){t.closed=true;}};tabs.push(t);return t;};
  Object.defineProperty(w,'crypto',{value:webcrypto});w.localStorage.setItem('popcorn-mvp3-guest-access-v1','a'.repeat(64));
  w.eval(read('live-model.js'));w.eval(read('api-client.js'));
  w.MVP3Api=w.MVP3Api.createClient({storage:w.localStorage,cryptoImpl:webcrypto,fetchImpl:async(url,init)=>{
    const body=init.body?JSON.parse(init.body):null;calls.push({url,method:init.method,body});
    if(url==='/api/mvp3/part-options'&&fail)return {ok:false,status:409,json:async()=>({detail:'x'}),headers:{get:()=>null}};
    const data=url==='/api/talk/parse'?{ok:true,state:talkState,history:[],missing:[]}:
      url==='/api/grid/recommend'?reco:
      url==='/api/mvp3/part-options'?{ok:true,slot:body.slot,label:'메모리',current:'16GB',base_code:body.product_code,base_price:1300000,options}:
      url==='/api/mvp3/saved-quotes'&&init.method==='POST'?{ok:true,quote:{id:qid,product:{...swapped,swap:undefined},state:talkState,saved_at:'2026-10-11T00:00:00Z'}}:
      url.endsWith('/handoff')?{ok:true,handoff_no:'HO-3001',quote_id:qid,product_code:22,name:'PC 22',price_quoted:1350000,price_mall:1350000,mall_status:'확인됨',mall_url:MALL}:
      {ok:true,quotes:[],has_more:false};
    return {ok:true,status:200,json:async()=>data,headers:{get:()=>null}};
  }});w.eval(read('live-flow.js'));
  const create=w.MVP3LiveFlow.createFlow;let flow;
  w.MVP3LiveFlow.createFlow=(...args)=>{flow=create(...args);return flow;};
  w.eval(read('live-photo.js'));w.eval(read('app.js'));
  return {w,d:w.document,get flow(){return flow;},errors,calls,tabs,close:()=>dom.window.close()};
}
const text=e=>e.textContent.replace(/\s+/g,' ').trim();
async function toDetail(h){
  const d=h.d,input=d.querySelector('#request');input.value='배그 150만원';input.dispatchEvent(new h.w.Event('input',{bubbles:true}));
  d.querySelector('#chat-form').dispatchEvent(new h.w.Event('submit',{bubbles:true,cancelable:true}));
  await until(()=>d.querySelector('.live-product-card [data-action=detail]'));
  d.querySelector('.live-product-card [data-action=detail]').click();
  await until(()=>h.flow.state.screen==='detail'&&d.querySelector('#part-change'));
}

test('detail shows four working part buttons instead of disabled ones',async()=>{
  const h=harness();try{await toDetail(h);const d=h.d;
    assert.deepEqual([...d.querySelectorAll('#part-change [data-action=part-options]')].map(b=>[b.dataset.slot,b.disabled]),
      [['cpu',false],['gpu',false],['ram',false],['ssd',false]]);
    assert.equal(d.querySelector('[data-action=unavailable]')?.textContent.includes('구성 변경 요청')??false,false);
    assert.equal(text(d.querySelector('#actions [data-action=part-focus]')),'부품 바꾸기');
    assert.ok(!text(d.body).includes('부품별 옵션 변경'));
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('ram options come from the server and swapping changes product, price and what is saved and bought',async()=>{
  const h=harness();try{await toDetail(h);const d=h.d;
    d.querySelector('#part-change [data-slot=ram]').click();
    await until(()=>d.querySelector('.part-option'));
    const req=h.calls.find(c=>c.url==='/api/mvp3/part-options');
    assert.deepEqual(req.body,{state:talkState,product_code:12,slot:'ram'});
    assert.equal(text(d.querySelector('.part-options-head h4')),'메모리 바꾸기 · 지금 16GB');
    const rows=[...d.querySelectorAll('.part-option')];
    assert.deepEqual(rows.map(r=>text(r.querySelector('strong'))),['32GB','64GB']);
    assert.ok(text(rows[0]).includes('+50,000원')&&text(rows[0]).includes('추가'));
    assert.ok(!text(rows[0]).includes('1,350,000원')&&!text(rows[1]).includes('1,500,000원'),'후보 옆에 PC 금액·단품 금액을 쓰지 않는다');
    assert.ok(text(rows[1]).includes('저장장치도 함께 바뀌어요: 500GB에서 2TB로'));
    rows[0].querySelector('[data-action=part-swap]').click();
    await until(()=>h.flow.state.selected.product_code===22);
    assert.equal(h.flow.state.selected.price,1350000);
    assert.equal(d.querySelector('.part-option'),null);
    assert.ok(text(d.querySelector('#actions')).includes('1,350,000원'));
    assert.ok(text([...d.querySelectorAll('.message.ai')].at(-1)).startsWith('메모리를 32GB로 바꿨어요. 이 구성으로 판매 중인 PC로 옮겼어요. 기본 부품 대비 차액은 +50,000원이고, PC 총액은 1,350,000원이에요.'));
    d.querySelector('#actions [data-action=final]').click();
    await until(()=>h.flow.state.screen==='final'&&d.querySelector('[data-action=save]'));
    d.querySelector('[data-action=save]').click();
    await until(()=>h.flow.state.saveState==='saved'&&d.querySelector('[data-action=handoff]'));
    const save=h.calls.find(c=>c.url==='/api/mvp3/saved-quotes'&&c.method==='POST');
    assert.equal(save.body.product_code,22);assert.equal(save.body.expected_price,1350000);assert.deepEqual(save.body.state,talkState);
    d.querySelector('[data-action=handoff]').click();
    await until(()=>d.querySelector('.live-handoff'));
    assert.ok(h.calls.some(c=>c.url==='/api/mvp3/saved-quotes/'+qid+'/handoff'));
    assert.equal(d.querySelector('.live-handoff a').getAttribute('href'),MALL);
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('no option and server refusal are said plainly, nothing is swapped',async()=>{
  for(const [opts,fail,expect] of [[[],false,'지금 판매 중인 PC 중에는 메모리만 다른 구성이 없어요.'],[[swapped],true,'상품 가격이나 추천 조건이 달라졌어요.']]){
    const h=harness({options:opts,fail});try{await toDetail(h);const d=h.d;
      d.querySelector('#part-change [data-slot=ram]').click();
      await until(()=>h.flow.state.phase===null&&d.querySelector('.part-options'));
      assert.ok(text(d.querySelector('.part-options')).includes(expect),text(d.querySelector('.part-options')));
      assert.equal(h.flow.state.selected.product_code,12);
      assert.deepEqual(h.errors,[]);
    }finally{h.close();}
  }
});

test('zero diff says 추가 금액 없음, a negative diff says 감소, a missing diff is shown but cannot be picked (2026-10-15)',async()=>{
  const zero=pc(24,1300000,{tag:'고른 구성',role:'chosen',swap:{slot:'ram',value:'16GB 다른 제품',price_diff:0,also:[]}});
  const minus=pc(25,1270000,{tag:'고른 구성',role:'chosen',swap:{slot:'ram',value:'8GB',price_diff:-30000,also:[]}});
  const none=pc(26,1300000,{tag:'고른 구성',role:'chosen',swap:{slot:'ram',value:'미확인 메모리',price_diff:null,also:[]}});
  const h=harness({options:[zero,minus,none]});try{await toDetail(h);const d=h.d;
    d.querySelector('#part-change [data-slot=ram]').click();
    await until(()=>d.querySelector('.part-option'));
    const row=code=>d.querySelector('[data-part-option="'+code+'"]');
    assert.ok(text(row(24)).includes('추가 금액 없음')&&!text(row(24)).includes('0원')&&!text(row(24)).includes('같은 금액'));
    assert.ok(text(row(25)).includes('\u221230,000원')&&text(row(25)).includes('감소')&&!text(row(25)).includes('1,270,000원'));
    assert.ok(text(row(26)).includes('차액 확인 필요'));
    assert.equal(row(26).querySelector('[data-action=part-swap]'),null,'차액 없는 후보는 선택 단추가 없다');
    assert.ok(row(24).querySelector('[data-action=part-swap]')&&row(25).querySelector('[data-action=part-swap]'));
    assert.ok(text(d.querySelector('.part-options')).includes('단품 금액 표시 없음'));
    assert.doesNotMatch(text(d.body),/조립·기타|가격 확인 중/);
    h.flow.swapPart(26);await tick();assert.equal(h.flow.state.selected.product_code,12,'흐름도 차액 없는 후보를 거부한다');
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});
test('an option with a broken price is dropped, not shown with an invented amount',async()=>{
  const h=harness({options:[{...swapped,price:null},{...bigger,swap:{...bigger.swap,price_diff:'200000'}},swapped]});try{await toDetail(h);const d=h.d;
    d.querySelector('#part-change [data-slot=ram]').click();
    await until(()=>d.querySelector('.part-option'));
    // 상품 금액이 깨진 후보는 버리고, 차액만 깨진 후보는 「차액 확인 필요」로 남기되 고를 수 없다.
    assert.deepEqual([...d.querySelectorAll('.part-option')].map(r=>Number(r.dataset.partOption)),[23,22]);
    assert.ok(text(d.querySelector('[data-part-option="23"]')).includes('차액 확인 필요'));assert.equal(d.querySelector('[data-part-option="23"] [data-action=part-swap]'),null);
  }finally{h.close();}
});
