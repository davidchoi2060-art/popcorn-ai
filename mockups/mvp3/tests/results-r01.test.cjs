'use strict';
// R01 results card: heading, condition chips, four-row spec, footer and emphasis.
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

test('cardSpecRows: four R01 rows from server fields only',()=>{
  assert.deepEqual(M.cardSpecRows({cpu:'i5-12400',gpu:'RTX 3050 6GB',ram_gb:16,ssd_gb:512,vram_gb:6}),[['CPU','i5-12400'],['GPU','RTX 3050 6GB'],['RAM','16GB'],['저장장치','512GB SSD']]);
  assert.deepEqual(M.cardSpecRows({gpu:'RTX 4060',vram_gb:8,ssd_gb:1024}),[['CPU','정보 없음'],['GPU','RTX 4060 · 8GB'],['RAM','정보 없음'],['저장장치','1TB SSD']]);
  assert.deepEqual(M.cardSpecRows({vram_gb:8,ssd_gb:2000}),[['CPU','정보 없음'],['GPU','8GB 그래픽카드'],['RAM','정보 없음'],['저장장치','2TB SSD']]);
  assert.deepEqual(M.cardSpecRows('문자열 사양'),[]);assert.deepEqual(M.cardSpecRows(null),[]);
  assert.deepEqual(M.cardSpecRows({cpu:'',gpu:null,ram_gb:null}),[['CPU','정보 없음'],['GPU','정보 없음'],['RAM','정보 없음'],['저장장치','정보 없음']]);
});
test('conditionChips: one chip per game, budget, usage; FHD only as a provisional assumption',()=>{
  const chips=M.conditionChips({usages:['게임'],budget_won:1500000,game:{names:['배그','롤']}},['game.resolution=1080p']);
  assert.deepEqual(chips.map(c=>c.label),['배그','롤','예산 1,500,000원','게임','FHD · 임시 기준']);
  assert.equal(chips.filter(c=>c.assumed).length,1);
  assert.deepEqual(M.conditionChips({game:{names:['롤'],resolution:'QHD'}},['game.resolution=1080p']).map(c=>c.label),['롤','QHD']);
  assert.deepEqual(M.conditionChips(null,[]),[]);
});
test('product role: server roles survive; legacy badges infer a role; unknown roles are dropped',()=>{
  for(const role of ['value','recommended','reference'])assert.equal(M.product(pc(1,1,{role,tag:'아무 문구'})).role,role);
  assert.equal(M.product(pc(1,1,{role:'<b>',tag:'추천 구성'})).role,'');
  for(const [tag,role] of [['추천 구성','recommended'],['예산 안 최고 수준','recommended'],['알뜰 구성','value'],['가장 저렴한 선택','value'],['예산을 넘는 최저가','reference'],['같은 수준 다른 구성',''],['한 단계 위',''],['','']])
    assert.equal(M.product(pc(1,1,{tag})).role,role,tag);
});
test('saved quote: role is kept through quote normalization; old snapshots without role still load',()=>{
  const q=product=>({id:'22222222-2222-4222-8222-222222222222',product,state:{usages:['게임']},saved_at:'2026-10-09T00:00:00Z'});
  assert.equal(M.quote(q(pc(41,1490000,{tag:'추천 구성',role:'recommended'}))).product.role,'recommended');
  const old=M.quote(q(pc(42,1199600,{tag:'예산 안 최고 수준'})));assert.equal(old.product.role,'recommended');assert.equal(old.product.price,1199600);
  assert.equal(M.quote(q(pc(43,1268900,{tag:'같은 수준 다른 구성'}))).product.role,'');
});
test('results: R01 heading, chips, four spec rows, single comparison line, footnote, no group heading or start toolbar',async()=>{
  const h=harness({items:[pc(11,1290000,{tag:'알뜰 구성',role:'value'}),pc(12,1490000,{tag:'추천 구성',role:'recommended'})]});try{await recommend(h);
    const d=h.w.document,cards=[...d.querySelectorAll('.live-product-card')];
    assert.equal(text(d.querySelector('.results-subtitle')),'예산 안에서 비교할 수 있는 두 가지 구성입니다.');
    assert.deepEqual([...d.querySelectorAll('.condition-chip')].map(text),['배그×','롤×','예산 1,500,000원×','게임×','FHD · 임시 기준']);
    assert.ok(d.querySelector('.condition-chip.is-assumed').title.includes('FHD(1080p)'));
    assert.equal(d.querySelector('.live-result-group>h3'),null);
    assert.equal(d.querySelector('.gateway-route-toolbar').hidden,true);
    assert.deepEqual([...cards[0].querySelectorAll('.live-card-spec dt')].map(text),['CPU','GPU','RAM','저장장치']);
    assert.equal(cards[0].querySelector('.live-reasons'),null);
    assert.equal(cards[0].querySelector('.live-price-difference'),null);
    assert.equal(text(cards[1].querySelector('.live-price-difference')),'알뜰 구성보다 200,000원 높아요.');
    assert.equal(d.querySelectorAll('.live-product-card .warn-text,.live-product-card .green').length,0);
    assert.equal(text(cards[0].querySelector('[data-action=detail]')),'구성 자세히 보기');assert.ok(cards[0].querySelector('[data-action=detail]').classList.contains('outline'));
    assert.equal(text(cards[1].querySelector('[data-action=detail]')),'추천 견적 자세히 보기');assert.ok(cards[1].querySelector('[data-action=detail]').classList.contains('primary'));
    assert.ok(cards[1].querySelector('.pill.strong'));assert.equal(cards[0].querySelector('.pill.strong'),null);
    assert.equal(text(d.querySelector('.results-note')),'해상도나 포함 품목을 바꾸면 견적이 달라질 수 있어요.');
    d.querySelector('.condition-chip[data-action=conditions]').click();assert.match(d.querySelector('#notice').textContent,/상담창/);
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});
test('results: older responses without role keep the "최고" emphasis; over-budget verdict is still shown',async()=>{
  const h=harness({items:[pc(21,1199600,{tag:'예산 안 최고 수준'}),pc(22,1600000,{tag:'같은 수준 다른 구성',over_budget:true})]});try{await recommend(h);
    const d=h.w.document,cards=[...d.querySelectorAll('.live-product-card')];
    assert.ok(cards[0].querySelector('.pill.strong'));assert.equal(text(cards[0].querySelector('[data-action=detail]')),'추천 견적 자세히 보기');
    assert.equal(text(cards[1].querySelector('[data-action=detail]')),'구성 자세히 보기');
    assert.equal(text(cards[1].querySelector('.warn-text')),'예산보다 100,000원 높아요');
    assert.equal(text(d.querySelector('.results-subtitle')),'비교할 수 있는 두 가지 구성입니다.');
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});
test('results: several usage groups keep their headings; one card has no subtitle',async()=>{
  const groups=[{kind:'sold',usage:'게임',items:[pc(31,900000)]},{kind:'sold',usage:'영상 편집',items:[pc(32,1000000)]}];
  const h=harness({groups});try{await recommend(h);const d=h.w.document;
    assert.deepEqual([...d.querySelectorAll('.live-result-group>h3')].map(text),['게임','영상 편집']);
    assert.equal(d.querySelector('.results-subtitle'),null);assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});
