'use strict';
// 2026-10-12 고객단 끝까지 검수: E16 대화 화면 새로고침 뒤 카드가 사라짐 · E15 대화에서 연 상세에서 「뒤로」가 빈 첫 화면.
// CODE/MOCK fixture 만 쓴다.
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),{webcrypto}=require('node:crypto');
const {JSDOM,VirtualConsole}=require('jsdom');
const base=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(base,n),'utf8');
const KEY='popcorn-mvp3-conversation-v1';
const t150={usages:['게임'],budget_won:1500000,budget_bound:'이하'};
const pc=(code,name,price)=>({product_code:code,name,price,price_src:'현재 판매가',spec:{cpu:'CPU',gpu:'GPU',ram_gb:16,ssd_gb:512},reasons:['CODE/MOCK 이유'],tag:'추천'});
const reco={ok:true,card_sets:[{kind:'sold',usage:'게임',items:[pc(101,'CODE/MOCK A',1450000),pc(102,'CODE/MOCK B',1390000)]}],needs:[],assumed:[]};
const tick=()=>new Promise(r=>setImmediate(r));
async function until(check){for(let n=0;n<400;n++){if(check())return;await tick();}throw Error('render did not settle');}
function storage(){const map=new Map();return {getItem:k=>map.get(k)??null,setItem:(k,v)=>map.set(k,v),removeItem:k=>map.delete(k),key:i=>[...map.keys()][i]??null,get length(){return map.size;}};}
function client(w,calls,script){
  const reply=(status,data)=>({ok:status<400,status,json:async()=>data,headers:{get:()=>null}});
  return w.MVP3Api.createClient({storage:w.localStorage,cryptoImpl:webcrypto,fetchImpl:async(url,options)=>{
    const body=options.body?JSON.parse(options.body):null;calls.push({url,body});const r=script(url,body);return reply(r.status||200,r.data);}});
}
const script=(url,body)=>url==='/api/talk/parse'?{data:{ok:true,state:t150,missing:[],reply:'조건에 맞는 PC를 찾아볼게요.',pc_related:true}}
  :url==='/api/grid/recommend'?{data:reco}:{data:{ok:true,quotes:[],has_more:false}};
function talkPage(ss){
  const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read('talk.html'),{url:'https://qa.invalid/mvp3/talk.html',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;w.scrollTo=()=>{};w.TextEncoder=TextEncoder;
  Object.defineProperty(w,'crypto',{value:webcrypto});Object.defineProperty(w,'sessionStorage',{value:ss});
  w.localStorage.setItem('popcorn-mvp3-guest-access-v1','a'.repeat(64));
  w.eval(read('live-model.js'));w.eval(read('api-client.js'));w.MVP3Api=client(w,calls,script);
  w.eval(read('live-flow.js'));w.eval(read('live-photo.js'));w.eval(read('talk.js'));
  const doc=w.document;
  const idle=()=>until(()=>!doc.querySelector('#tk-status').textContent&&!doc.querySelector('#tk-send').disabled);
  async function say(text){doc.querySelector('#tk-input').value=text;doc.querySelector('#tk-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await idle();}
  const cards=()=>doc.querySelectorAll('.tk-cards:not(.is-past) .tk-card').length;
  const bubbles=()=>[...doc.querySelectorAll('#tk-log .is-ai')].map(e=>e.textContent);
  return {w,doc,calls,errors,say,idle,cards,bubbles,close:()=>dom.window.close()};
}

test('reloading the chat while looking at cards brings the cards back without asking the AI again',async()=>{
  const ss=storage();
  const a=talkPage(ss);await a.say('배그 150만원');assert.equal(a.cards(),2);const before=a.bubbles();a.close();
  assert.equal(JSON.parse(ss.getItem(KEY)).shown,true);
  const b=talkPage(ss);await until(()=>b.cards()===2);await b.idle();
  assert.equal(b.calls.filter(c=>c.url==='/api/talk/parse').length,0,'no AI call on reload');
  assert.equal(b.calls.filter(c=>c.url==='/api/grid/recommend').length,1);
  assert.deepEqual(b.bubbles(),before,'the same notes are not added twice');
  assert.deepEqual(b.errors,[]);b.close();
});
test('a chat that never showed cards does not fetch cards on reload',async()=>{
  const ss=storage();
  ss.setItem(KEY,JSON.stringify({version:1,saved_at:Date.now(),talk:t150,chat_flow:null,history:[],messages:[{who:'user',text:'배그'}],current:null}));
  const b=talkPage(ss);for(let i=0;i<20;i++)await tick();
  assert.equal(b.calls.filter(c=>c.url==='/api/grid/recommend').length,0);assert.equal(b.cards(),0);b.close();
});

test('back from a detail opened from the chat goes back to the chat, not to an empty start screen',async()=>{
  const ss=storage();
  ss.setItem(KEY,JSON.stringify({version:1,saved_at:Date.now(),talk:t150,chat_flow:null,history:[],messages:[{who:'user',text:'배그 150만원'}],current:{product_code:101,changes:[],selection_state:t150},shown:true}));
  ss.setItem('popcorn-mvp3-from-talk-v1',JSON.stringify({focus:null}));
  const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read('index.html'),{url:'https://qa.invalid/mvp3/index.html#detail',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.TextEncoder=TextEncoder;
  Object.defineProperty(w,'crypto',{value:webcrypto});Object.defineProperty(w,'sessionStorage',{value:ss});
  w.localStorage.setItem('popcorn-mvp3-guest-access-v1','a'.repeat(64));
  w.eval(read('live-model.js'));w.eval(read('api-client.js'));w.MVP3Api=client(w,calls,script);
  w.eval(read('live-flow.js'));w.eval(read('live-photo.js'));
  const length=w.history.length;
  w.eval(read('app.js'));
  await until(()=>w.document.querySelector('#view .final-table'));for(let i=0;i<5;i++)await tick();
  assert.equal(w.location.hash,'#detail');
  assert.equal(w.history.length,length,'restoring the quote replaces the entry instead of adding #results/#detail');
  // 그 뒤 고객이 직접 옮겨 다니면 평소처럼 기록이 쌓인다.
  w.document.querySelector('[data-action="final"]').click();await until(()=>w.location.hash==='#final');
  assert.equal(w.history.length,length+1);
  assert.deepEqual(errors,[]);dom.window.close();
});
