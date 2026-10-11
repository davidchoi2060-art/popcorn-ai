'use strict';
// 2026-10-11 상담 주고받기: 세 장(알뜰 · 추천 · 더 높은 사양), 카드 뒤 빠른 선택, 서버가 한 말.
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),{webcrypto}=require('node:crypto');
const {JSDOM,VirtualConsole}=require('jsdom');
const base=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(base,n),'utf8');
const tick=()=>new Promise(r=>setImmediate(r));
async function until(check){for(let n=0;n<80;n++){if(check())return;await tick();}throw Error('render did not settle');}
const pc=(code,price,extra={})=>({product_code:code,name:'PC '+code,price,price_src:'현재 판매가',spec:{cpu:'i5-14400F',gpu:'RTX 5060 8GB',ram_gb:16,ssd_gb:512,vram_gb:8},reasons:['게임 FHD'],over_budget:false,...extra});
const talkState={usages:['게임'],budget_won:2300000,budget_bound:'이하',game:{names:['배그']}};
const first={ok:true,assumed:[],anchor_code:12,wants:{},card_sets:[{kind:'sold',usage:'게임',usage_grid:'게임',items:[
  pc(11,1300000,{tag:'알뜰 구성',role:'value'}),pc(12,1585100,{tag:'추천 구성',role:'recommended'}),pc(13,2046500,{tag:'더 높은 사양',role:'premium'})]}],
  talk_notes:['더 싼 PC나 더 높은 사양도 보여 드릴까요? 아래에서 골라 주세요.'],
  choices:[{id:'cheaper',label:'더 싼 PC 볼래요',enabled:true},{id:'better',label:'더 높은 사양 볼래요',enabled:false},{id:'change',label:'조건 바꿀게요',enabled:true}]};
const cheaper={...first,anchor_code:21,card_sets:[{kind:'sold',usage:'게임',usage_grid:'게임',items:[pc(21,1300000,{tag:'추천 구성',role:'recommended'})]}],
  talk_notes:['지금 보신 추천 구성보다 싼 PC를 보여 드려요.'],choices:[]};
function harness(){
  const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read('index.html'),{url:'https://qa.invalid/mvp3/#welcome',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.TextEncoder=TextEncoder;
  Object.defineProperty(w,'crypto',{value:webcrypto});w.localStorage.setItem('popcorn-mvp3-guest-access-v1','a'.repeat(64));
  w.eval(read('live-model.js'));w.eval(read('api-client.js'));
  let recommends=0;
  w.MVP3Api=w.MVP3Api.createClient({storage:w.localStorage,cryptoImpl:webcrypto,fetchImpl:async(url,init)=>{
    calls.push({url,body:init.body?JSON.parse(init.body):null});
    const data=url==='/api/talk/parse'?{ok:true,state:talkState,history:[],missing:[]}:url==='/api/grid/recommend'?(recommends++?cheaper:first):{ok:true,quotes:[],has_more:false};
    return {ok:true,status:200,json:async()=>data,headers:{get:()=>null}};
  }});w.eval(read('live-flow.js'));w.eval(read('live-photo.js'));w.eval(read('app.js'));
  return {w,errors,calls,close:()=>dom.window.close()};
}
async function ask(h,text){const d=h.w.document,input=d.querySelector('#request');input.value=text;input.dispatchEvent(new h.w.Event('input',{bubbles:true}));d.querySelector('#chat-form').dispatchEvent(new h.w.Event('submit',{bubbles:true,cancelable:true}));await until(()=>d.querySelector('.live-product-card'));}
const text=e=>e.textContent.replace(/\s+/g,' ').trim();

test('three cards, follow-up question in chat, and only the enabled quick choices',async()=>{
  const h=harness();try{await ask(h,'배그 230만원');const d=h.w.document;
    assert.equal(d.querySelectorAll('.live-product-card').length,3);assert.ok(d.querySelector('.quote-cards.has-three'));
    assert.equal(text(d.querySelector('.results-subtitle')),'싼 구성부터 더 높은 사양까지 세 가지를 비교해 보세요.');
    assert.deepEqual([...d.querySelectorAll('.live-product-card .pill')].map(text),['알뜰 구성','추천 구성','더 높은 사양']);
    assert.equal(d.querySelectorAll('.live-product-card .pill.strong').length,1);
    assert.deepEqual([...d.querySelectorAll('.live-price-difference')].map(text),['알뜰 구성보다 285,100원 높아요.','추천 구성보다 461,400원 높아요.']);
    assert.deepEqual([...d.querySelectorAll('.explore-choices button')].map(text),['더 싼 PC 볼래요','조건 바꿀게요']);
    assert.deepEqual([...d.querySelectorAll('#suggestions button')].map(text),['더 싼 PC 볼래요','조건 바꿀게요']);
    assert.equal(text([...d.querySelectorAll('.message.ai')].at(-1)),first.talk_notes[0]);
    assert.deepEqual(h.calls[1].body,{state:talkState,text:'배그 230만원'});
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});
test('quick choice asks for cheaper than the card being looked at, without the AI parse',async()=>{
  const h=harness();try{await ask(h,'배그 230만원');const d=h.w.document;
    d.querySelector('.explore-choices [data-dir=cheaper]').click();
    await until(()=>d.querySelectorAll('.live-product-card').length===1);
    assert.equal(h.calls.filter(c=>c.url==='/api/talk/parse').length,1);
    assert.deepEqual(h.calls.at(-1).body,{state:talkState,wants:{},nav:'cheaper',anchor_code:12});
    const lines=[...d.querySelectorAll('.message')].map(text);
    assert.deepEqual(lines.slice(-2),['더 싼 PC 볼래요',cheaper.talk_notes[0]]);
    assert.equal(d.querySelector('.explore-choices'),null);
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});
