'use strict';
// 2026-10-12 사장님 결정: 대화 화면은 「AI 설명 -> 예산 안내 -> 카드 -> 더 싼 PC / 더 높은 사양 / 조건 바꾸기」 순서.
// 카드 검수 C1(예산 안내가 카드 아래) · C2(「아래에서 골라 주세요」인데 단추 없음). CODE/MOCK fixture 만 쓴다.
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),{webcrypto}=require('node:crypto');
const {JSDOM,VirtualConsole}=require('jsdom');
const base=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(base,n),'utf8');
const tick=()=>new Promise(r=>setImmediate(r));
async function until(check){for(let n=0;n<400;n++){if(check())return;await tick();}throw Error('render did not settle');}
const pc=(code,price,extra={})=>({product_code:code,name:'PC '+code,price,price_src:'현재 판매가',spec:{cpu:'CPU',gpu:'GPU',ram_gb:16,ssd_gb:512},reasons:['게임 쾌적 — FHD 게임'],tag:'추천 구성',...extra});
const t150={usages:['게임'],budget_won:1500000,budget_bound:'이하'};
const OVER='150만원 안에는 맞는 PC가 없어요. 가장 가까운 PC는 예산보다 124,400원 높아요.';
const ASK='더 싼 PC나 더 높은 사양도 보여 드릴까요? 아래에서 골라 주세요.';
const first={ok:true,assumed:[],needs:[],anchor_code:11,card_sets:[{kind:'sold',usage:'게임',items:[pc(11,1624400)]}],talk_notes:[OVER,ASK],
  choices:[{id:'cheaper',label:'더 싼 PC 볼래요',enabled:true},{id:'better',label:'더 높은 사양 볼래요',enabled:true},{id:'change',label:'조건 바꿀게요',enabled:true}]};
const second={ok:true,assumed:[],needs:[],anchor_code:21,card_sets:[{kind:'sold',usage:'게임',items:[pc(21,1300000)]}],talk_notes:['지금 보신 추천 구성보다 싼 PC를 보여 드려요.'],
  choices:[{id:'cheaper',label:'더 싼 PC 볼래요',enabled:false},{id:'better',label:'더 높은 사양 볼래요',enabled:true},{id:'change',label:'조건 바꿀게요',enabled:true}]};
function storage(){const map=new Map();return {getItem:k=>map.get(k)??null,setItem:(k,v)=>map.set(k,v),removeItem:k=>map.delete(k),key:i=>[...map.keys()][i]??null,get length(){return map.size;}};}
function harness(){
  const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read('talk.html'),{url:'https://qa.invalid/mvp3/talk.html',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;w.scrollTo=()=>{};w.TextEncoder=TextEncoder;
  Object.defineProperty(w,'crypto',{value:webcrypto});Object.defineProperty(w,'sessionStorage',{value:storage()});
  w.localStorage.setItem('popcorn-mvp3-guest-access-v1','a'.repeat(64));
  w.eval(read('live-model.js'));w.eval(read('api-client.js'));
  let recos=0;
  w.MVP3Api=w.MVP3Api.createClient({storage:w.localStorage,cryptoImpl:webcrypto,fetchImpl:async(url,init)=>{
    const body=init.body?JSON.parse(init.body):null;calls.push({url,body});
    const data=url==='/api/talk/parse'?{ok:true,state:/120만/.test(body.text)?{...t150,budget_won:1200000}:t150,missing:[],reply:'게임용 PC를 찾아볼게요.',pc_related:true}
      :url==='/api/grid/recommend'?(recos++?second:first):{ok:true,quotes:[],has_more:false};
    return {ok:true,status:200,json:async()=>data,headers:{get:()=>null}};
  }});
  w.eval(read('live-flow.js'));w.eval(read('live-photo.js'));w.eval(read('talk.js'));
  const doc=w.document;
  const idle=()=>until(()=>!doc.querySelector('#tk-status').textContent&&!doc.querySelector('#tk-send').disabled);
  async function say(text){doc.querySelector('#tk-input').value=text;doc.querySelector('#tk-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await idle();}
  return {w,doc,calls,errors,say,idle,close:()=>dom.window.close()};
}
// 대화 칸의 차례: 말풍선·카드·단추를 위에서부터 이름으로 적는다.
function order(doc){
  return [...doc.querySelector('#tk-log').children].map(e=>e.classList.contains('tk-cards')?(e.classList.contains('is-past')?'past-cards':'cards'):
    e.classList.contains('tk-msg')?(e.classList.contains('is-user')?'user':'ai:'+e.textContent):e.className);
}

test('AI answer and budget guidance come above the cards, the next-choice buttons right under them',async()=>{
  const h=harness();
  try{
    await h.say('배그 150만원');
    assert.deepEqual(order(h.doc),['user','ai:게임용 PC를 찾아볼게요.','ai:'+OVER,'ai:'+ASK,'cards']);
    const cards=h.doc.querySelector('.tk-cards:not(.is-past)');
    const list=cards.querySelector('.tk-card-list'),next=cards.querySelector('.tk-next');
    assert.ok(next,'buttons the 「아래에서 골라 주세요」 sentence talks about');
    assert.ok(list.compareDocumentPosition(next)&h.w.Node.DOCUMENT_POSITION_FOLLOWING,'buttons sit under the cards');
    assert.deepEqual([...next.querySelectorAll('button')].map(b=>b.textContent),['더 싼 PC','더 높은 사양','조건 바꾸기']);
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('cheaper asks nothing new: same conditions, recommend only, then the next cards',async()=>{
  const h=harness();
  try{
    await h.say('배그 150만원');
    const parses=h.calls.filter(c=>c.url==='/api/talk/parse').length;
    h.doc.querySelector('.tk-next [data-dir=cheaper]').click();await h.idle();
    assert.equal(h.calls.filter(c=>c.url==='/api/talk/parse').length,parses,'no AI parse, no new question');
    const last=h.calls.at(-1);assert.equal(last.url,'/api/grid/recommend');assert.equal(last.body.nav,'cheaper');assert.deepEqual(last.body.state,t150);
    assert.deepEqual(order(h.doc).slice(-4),['past-cards','user','ai:지금 보신 추천 구성보다 싼 PC를 보여 드려요.','cards']);
    // 지난 카드에는 단추가 없고, 서버가 꺼 둔 방향(더 싼 PC 없음)은 내지 않는다.
    assert.equal(h.doc.querySelectorAll('.tk-next').length,1);
    assert.deepEqual([...h.doc.querySelectorAll('.tk-next button')].map(b=>b.textContent),['더 높은 사양','조건 바꾸기']);
  }finally{h.close();}
});

test('change conditions opens budget and usage fields filled with the current conditions',async()=>{
  const h=harness();
  try{
    await h.say('배그 150만원');
    h.doc.querySelector('.tk-next [data-action=cond-open]').click();
    const form=h.doc.querySelector('[data-cond-form]');assert.ok(form);
    assert.equal(form.querySelector('[data-cond=budget]').value,'150');assert.equal(form.querySelector('[data-cond=usage]').value,'게임');
    // 아무것도 안 바꾸고 보내면 보내지 않는다.
    form.dispatchEvent(new h.w.Event('submit',{bubbles:true,cancelable:true}));
    assert.match(h.doc.querySelector('#tk-status').textContent,/바꿀 예산이나 용도/);
    form.querySelector('[data-cond=budget]').value='120';
    form.dispatchEvent(new h.w.Event('submit',{bubbles:true,cancelable:true}));await h.idle();
    const parse=h.calls.filter(c=>c.url==='/api/talk/parse').at(-1);
    assert.equal(parse.body.text,'예산은 120만원으로 바꿀게요.');
    assert.equal(h.calls.at(-1).url,'/api/grid/recommend');assert.equal(h.calls.at(-1).body.state.budget_won,1200000);
    assert.equal(h.doc.querySelector('[data-cond-form]'),null,'fields close once sent');
  }finally{h.close();}
});
