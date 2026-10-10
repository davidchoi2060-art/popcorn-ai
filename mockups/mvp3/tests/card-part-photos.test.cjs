'use strict';
// Results cards show approved part photos up front; parts without one are left out.
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),{webcrypto}=require('node:crypto');
const {JSDOM,VirtualConsole}=require('jsdom');
const base=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(base,n),'utf8');
const M=require('../live-model.js');
const tick=()=>new Promise(r=>setImmediate(r));
async function until(check){for(let n=0;n<50;n++){if(check())return;await tick();}throw Error('render did not settle');}
const pc=(code,price,extra={})=>({product_code:code,name:'PC '+code,price,price_src:'현재 판매가',spec:{cpu:'i5-12400',gpu:'RTX 3050 6GB',ram_gb:16,ssd_gb:512,vram_gb:6},reasons:['게임 캐주얼 — 롤','업그레이드 안내'],over_budget:false,...extra});
function harness({items,talkState={usages:['게임'],budget_won:1500000,game:{names:['배그','롤']}},assumed=['game.resolution=1080p'],groups=null}){
  const errors=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read('index.html'),{url:'https://qa.invalid/mvp3/#welcome',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.TextEncoder=TextEncoder;
  Object.defineProperty(w,'crypto',{value:webcrypto});w.localStorage.setItem('popcorn-mvp3-guest-access-v1','a'.repeat(64));
  w.eval(read('live-model.js'));w.eval(read('api-client.js'));
  const response={ok:true,assumed,card_sets:groups||[{kind:'sold',usage:'게임',usage_grid:'게임',items}]};
  w.MVP3Api=w.MVP3Api.createClient({storage:w.localStorage,cryptoImpl:webcrypto,fetchImpl:async url=>{
    const data=url==='/api/talk/parse'?{ok:true,state:talkState,history:[],missing:[]}:url==='/api/grid/recommend'?response:{ok:true,quotes:[],has_more:false};
    return {ok:true,status:200,json:async()=>data,headers:{get:()=>null}};
  }});w.eval(read('live-flow.js'));w.eval(read('app.js'));
  return {w,errors,close:()=>dom.window.close()};
}
async function recommend(h){const d=h.w.document,input=d.querySelector('#request');input.value='배그 롤 150만원';input.dispatchEvent(new h.w.Event('input',{bubbles:true}));d.querySelector('#chat-form').dispatchEvent(new h.w.Event('submit',{bubbles:true,cancelable:true}));await until(()=>d.querySelector('.live-product-card'));}
const text=e=>e.textContent.replace(/\s+/g,' ').trim();
function fixture(photos){return {product_code:99413,configuration_id:'P10',revision:1,offer_id:'P99413',
  description:{title:'검증 PC',intro:'근거 설명',scene:null,benefits:[],checks:[],faq:[]},
  parts:[{ordinal:0,slot:'CPU',quantity:1,pseudo:false,name:'CPU 이름',description:'역할',specs:[],photo:photos[0]},
    {ordinal:1,slot:'MB',quantity:1,pseudo:false,name:'MB 이름',description:'역할',specs:[],photo:photos[1]},
    {ordinal:8,slot:'SERVICE',quantity:1,pseudo:true,name:null,description:null,specs:[],photo:photos[2]}],
  price:{state:'unknown',amount:null,checked_at:null,observed_date:null,model:null},stock:{state:'unknown',checked_at:null},
  compatibility:{document_state:'pass',public_summary:null,assembly_state:'unknown'},photo:{state:'unresolved',url:null},
  customer_conditions:Object.fromEntries(['os','keyboard','mouse','monitor','warranty'].map(k=>[k,{state:'unknown',detail:'',months:null,needs_reconfirmation:false,customer_statement:'구매 전에 확인해 주세요.'}]))};}
const ok=code=>({state:'approved',url:'/api/product-images/'+code+'/detail'}),none={state:'none',url:null};
const cfg=(code,photos)=>{const f=fixture(photos);f.product_code=code;f.offer_id='P'+code;f.parts[1].slot='GPU';return f;};

test('cardPartPhotos: approved real parts only, in ordinal order, with Korean slot labels',()=>{
  const p=M.product(pc(99413,900000,{public_configuration:cfg(99413,[ok(11),ok(12),ok(13)])}));
  assert.deepEqual(M.cardPartPhotos(p),[{ordinal:0,label:'CPU',name:'CPU 이름',url:'/api/product-images/11/detail'},{ordinal:1,label:'그래픽카드',name:'MB 이름',url:'/api/product-images/12/detail'}]);
  assert.deepEqual(M.cardPartPhotos(M.product(pc(99413,900000,{public_configuration:cfg(99413,[none,none,none])}))),[]);
  assert.deepEqual(M.cardPartPhotos(M.product(pc(1,900000))),[]);
  assert.deepEqual(M.cardPartPhotos(null),[]);
});
test('results card renders approved thumbnails without placeholders; a card without photos has no strip',async()=>{
  const h=harness({items:[pc(93454,1199600,{tag:'알뜰 구성',role:'value'}),pc(99413,1268900,{tag:'추천 구성',role:'recommended',public_configuration:cfg(99413,[ok(11),none,none])})]});
  try{
    await recommend(h);const d=h.w.document,cards=[...d.querySelectorAll('.live-product-card')];
    assert.equal(cards.length,2);
    assert.equal(cards[0].querySelector('.card-part-photos'),null);
    const imgs=[...cards[1].querySelectorAll('.card-part-photos img')];
    assert.deepEqual(imgs.map(i=>i.getAttribute('src')),['/api/product-images/11/detail']);
    assert.equal(imgs[0].alt,'CPU 이름 부품 사진');
    assert.equal(text(cards[1].querySelector('.card-part-photos figcaption')),'CPU');
    assert.doesNotMatch(cards[1].textContent,/부품 사진 미확인/);
    imgs[0].dispatchEvent(new h.w.Event('error'));
    assert.equal(imgs[0].closest('li').hidden,true);
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});
