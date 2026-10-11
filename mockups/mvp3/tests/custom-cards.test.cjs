'use strict';
// 2026-10-11 부품 상품화 5단계: 운영자 신규 조립PC 가 추천 결과에 「새로 나온 PC」 카드로 함께 나온다.
// 몰 카드와 섞지 않고, 용도 적합도는 서버 판정(정보 없음 포함)을 그대로 적고, 「새로 나온 PC」 화면으로 보낸다.
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),{webcrypto}=require('node:crypto');
const {JSDOM,VirtualConsole}=require('jsdom');
const base=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(base,n),'utf8');
const tick=()=>new Promise(r=>setImmediate(r));
async function until(check){for(let n=0;n<400;n++){if(check())return;await tick();}throw Error('render did not settle');}
const qid='55555555-5555-4555-8555-555555555555';
const configuration={product_code:12,configuration_id:'P10',revision:1,offer_id:'P12',
  description:{title:'검증 PC',intro:'근거 설명',scene:null,benefits:[],checks:[],faq:[]},
  parts:[{ordinal:0,slot:'CPU',quantity:1,pseudo:false,name:'CPU A',description:'역할',specs:[{label:'소켓',value:'AM5'}]},
    {ordinal:1,slot:'RAM',quantity:2,pseudo:false,name:'램 16GB',description:'역할',specs:[]},
    {ordinal:8,slot:'SERVICE',quantity:1,pseudo:true,name:null,description:null,specs:[]}],
  price:{state:'unknown',amount:null,checked_at:null,observed_date:null,model:null},stock:{state:'unknown',checked_at:null},
  compatibility:{document_state:'pass',public_summary:null,assembly_state:'unknown'},photo:{state:'unresolved',url:null},
  customer_conditions:Object.fromEntries(['os','keyboard','mouse','monitor','warranty'].map(k=>[k,{state:'unknown',detail:'',months:null,needs_reconfirmation:false,customer_statement:'구매 전에 확인해 주세요.'}]))};
const pc={product_code:12,name:'PC 12',price:1300000,price_src:'현재 판매가',spec:{cpu:'CPU A',ram_gb:32},reasons:['게임 FHD'],over_budget:false,tag:'추천 구성',role:'recommended',public_configuration:configuration};
const talkState={usages:['게임'],budget_won:1500000,budget_bound:'이하'};
const custom=[{configuration_id:'A0123456789ABCDEF',title:'새 게임 PC',price:1290000,price_note:'부품 판매가 합계 + 조립비',fit:'fit',level:'FHD',level_text:'게임 FHD',
  parts:[{slot_label:'CPU',name:'라이젠5 7500F',quantity:1},{slot_label:'메모리',name:'DDR5 16GB',quantity:2}],url:'new-pcs.html#A0123456789ABCDEF'},
  {configuration_id:'A00000000000000FF',title:'정보 없는 PC',price:990000,price_note:'부품 판매가 합계 + 조립비',fit:'unknown',level:null,level_text:'정보 없음',parts:[],url:'javascript:alert(1)'},
  {configuration_id:'bad',title:'형식 오류',price:1}];
const reco={ok:true,assumed:[],anchor_code:12,wants:{},card_sets:[{kind:'sold',usage:'게임',usage_grid:'게임',items:[pc],custom_items:custom}],talk_notes:[],choices:[]};
const change={ordinal:1,slot:'RAM',label:'메모리',quantity:2,before:{product_code:501,name:'램 16GB',price:60000},after:{product_code:502,name:'램 32GB',price:110000},delta:100000};
const options={ok:true,base_code:12,ordinal:1,slot:'RAM',label:'메모리',quantity:2,current:{product_code:501,name:'램 16GB',price:60000},total:1300000,checked:4,untested:1,
  note:'호환 규칙을 모두 통과한 판매 중 부품만 보여 드려요.',
  options:[{product_code:503,name:'램 8GB',price:30000,price_diff:-60000,total:1240000},{product_code:502,name:'램 32GB',price:110000,price_diff:100000,total:1400000}]};

function harness(){
  const errors=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read('index.html'),{url:'https://qa.invalid/mvp3/#welcome',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.TextEncoder=TextEncoder;
  w.HTMLElement.prototype.scrollIntoView=function(){};
  Object.defineProperty(w,'crypto',{value:webcrypto});w.localStorage.setItem('popcorn-mvp3-guest-access-v1','a'.repeat(64));
  w.eval(read('live-model.js'));w.eval(read('api-client.js'));
  w.MVP3Api=w.MVP3Api.createClient({storage:w.localStorage,cryptoImpl:webcrypto,fetchImpl:async url=>{
    const data=url==='/api/talk/parse'?{ok:true,state:talkState,history:[],missing:[]}:url==='/api/grid/recommend'?reco:{ok:true,quotes:[],has_more:false};
    return {ok:true,status:200,json:async()=>data,headers:{get:()=>null}};}});
  w.eval(read('live-flow.js'));w.eval(read('app.js'));
  return {w,d:w.document,errors,close:()=>dom.window.close()};
}
const text=e=>e.textContent.replace(/\s+/g,' ').trim();

test('new PCs show beside the mall cards with server fit, price and a link to the new-PC page',async()=>{
  const h=harness();try{const d=h.d,input=d.querySelector('#request');input.value='게임 150만원';input.dispatchEvent(new h.w.Event('input',{bubbles:true}));
    d.querySelector('#chat-form').dispatchEvent(new h.w.Event('submit',{bubbles:true,cancelable:true}));
    await until(()=>d.querySelector('[data-custom-pc]'));
    assert.equal(d.querySelectorAll('.live-product-card:not(.custom-pc-card)').length,1);
    const cards=[...d.querySelectorAll('[data-custom-pc]')];
    assert.equal(cards.length,2);
    assert.ok(text(cards[0]).includes('1,290,000원')&&text(cards[0]).includes('용도 적합도: 게임 FHD')&&text(cards[0]).includes('DDR5 16GB × 2'));
    assert.equal(cards[0].querySelector('a').getAttribute('href'),'new-pcs.html#A0123456789ABCDEF');
    assert.ok(text(cards[1]).includes('용도 적합도: 정보 없음'));
    assert.equal(cards[1].querySelector('a').getAttribute('href'),'new-pcs.html#A00000000000000FF');
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('the model drops malformed new-PC entries and keeps mall cards unchanged',()=>{
  const h=harness();try{const g=h.w.MVP3LiveModel.recommendations(reco).groups[0];
    assert.equal(g.custom.length,2);assert.equal(g.products.length,1);assert.equal(g.products[0].product_code,12);
    assert.equal(h.w.MVP3LiveModel.recommendations({ok:true,card_sets:[{kind:'sold',items:[pc]}]}).groups[0].custom.length,0);
  }finally{h.close();}
});
