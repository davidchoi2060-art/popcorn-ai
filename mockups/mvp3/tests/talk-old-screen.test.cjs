'use strict';
// 대화 화면(talk.html) <-> 기존 상담 화면(index.html) 오가기. 사장님 원칙 「기존 상담 화면 기능을 뒤에서 잘 활용,
// 결국 거기로 모인다」. 두 화면은 같은 탭 보관(CONVERSATION_KEY)을 함께 쓰고, 주소에는 화면 이름만 싣는다.
// CODE/MOCK fixture 만 쓴다.
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),{webcrypto}=require('node:crypto');
const {JSDOM,VirtualConsole}=require('jsdom');
const base=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(base,n),'utf8');
const CONVERSATION_KEY='popcorn-mvp3-conversation-v1',FROM_TALK_KEY='popcorn-mvp3-from-talk-v1';
const tick=()=>new Promise(r=>setImmediate(r));
async function until(check){for(let n=0;n<400;n++){if(check())return;await tick();}throw Error('render did not settle');}
function storage(){const map=new Map();return {getItem:k=>map.get(k)??null,setItem:(k,v)=>map.set(k,v),removeItem:k=>map.delete(k),key:i=>[...map.keys()][i]??null,get length(){return map.size;}};}
const talkState={usages:['게임'],budget_won:1500000,budget_bound:'이하'};
const pc=(code,price,extra={})=>({product_code:code,name:'CODE/MOCK PC '+code,price,price_src:'현재 판매가',spec:{cpu:'CPU',gpu:'RTX 5060 8GB',ram_gb:16,ssd_gb:500,vram_gb:8},reasons:['CODE/MOCK 이유'],tag:'추천',...extra});
const reco={ok:true,assumed:[],needs:[],card_sets:[{kind:'sold',usage:'게임',items:[pc(12,1300000),pc(13,1400000)]}]};
// GPU 만 다른 판매 PC. 추천 목록에는 없다 -- 돌아갈 때 부품 바꾸기 선택지에서 다시 찾아야 한다.
const swapped=pc(22,1450000,{spec:{cpu:'CPU',gpu:'RTX 5070 12GB',ram_gb:16,ssd_gb:500,vram_gb:12},swap:{slot:'gpu',value:'RTX 5070 12GB',price_diff:150000,also:[]}});
function api(calls){
  return async(url,init)=>{
    const body=init.body?JSON.parse(init.body):null;calls.push({url,body});
    const data=url==='/api/talk/parse'?{ok:true,state:talkState,missing:[],reply:'조건에 맞는 PC를 찾아볼게요.',pc_related:true}:
      url==='/api/grid/recommend'?reco:
      url==='/api/mvp3/part-options'?{ok:true,slot:body.slot,label:'그래픽카드',current:'RTX 5060 8GB',base_code:body.product_code,base_price:1300000,options:[swapped]}:
      url==='/api/mvp3/purchase-inquiries/form'?{ok:true,topics:['기타'],consent_text:'CODE/MOCK'}:
      {ok:true,quotes:[],has_more:false};
    return {ok:true,status:200,json:async()=>data,headers:{get:()=>null}};
  };
}
// 다른 문서로 가는 이동(location.href)은 jsdom 이 지원하지 않아 그 알림만 걸러낸다.
const real=errors=>errors.filter(m=>!/navigation/i.test(m));
function page(file,url,ss){
  const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read(file),{url,runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.TextEncoder=TextEncoder;
  w.HTMLElement.prototype.scrollIntoView=function(){};
  Object.defineProperty(w,'crypto',{value:webcrypto});Object.defineProperty(w,'sessionStorage',{value:ss});
  w.localStorage.setItem('popcorn-mvp3-guest-access-v1','a'.repeat(64));
  w.eval(read('live-model.js'));w.eval(read('api-client.js'));
  w.MVP3Api=w.MVP3Api.createClient({storage:w.localStorage,cryptoImpl:webcrypto,fetchImpl:api(calls)});
  w.eval(read('live-flow.js'));
  const create=w.MVP3LiveFlow.createFlow;let flow;
  w.MVP3LiveFlow.createFlow=(...args)=>{flow=create(...args);return flow;};
  w.eval(read('live-photo.js'));w.eval(read(file==='talk.html'?'talk.js':'app.js'));
  return {w,d:w.document,get flow(){return flow;},errors,calls,close:()=>dom.window.close()};
}
const talkPage=ss=>page('talk.html','https://qa.invalid/mvp3/talk.html',ss);
const indexPage=(ss,hash)=>page('index.html','https://qa.invalid/mvp3/index.html'+hash,ss);
async function say(h,text){
  h.d.querySelector('#tk-input').value=text;h.d.querySelector('#tk-form').dispatchEvent(new h.w.Event('submit',{bubbles:true,cancelable:true}));
  await until(()=>!h.flow.state.phase&&h.flow.state.recommendation);
}
const oldLink=h=>h.d.querySelector('#tk-old').getAttribute('href');
const fromTalk=ss=>JSON.parse(ss.getItem(FROM_TALK_KEY));
const snapshot=ss=>JSON.parse(ss.getItem(CONVERSATION_KEY));

test('「기존 상담 화면」 lands on the screen that matches the state and carries nothing in the address',async()=>{
  const ss=storage(),h=talkPage(ss);
  try{
    await until(()=>h.d.querySelector('.tk-welcome'));
    assert.equal(oldLink(h),'index.html#welcome');
    await say(h,'배그 150만원 이하 게임용');
    assert.equal(oldLink(h),'index.html#results','conditions and a recommendation, nothing chosen yet');
    h.d.querySelector('[data-action=choose][data-index="0"]').click();await tick();
    assert.equal(oldLink(h),'index.html#detail','a chosen build opens the detail screen');
    assert.ok(!/배그|150|게임/.test(oldLink(h)),'customer text and conditions never ride in the URL');
    h.d.querySelector('#tk-old').click();
    assert.deepEqual(fromTalk(ss),{focus:null});
    assert.equal(snapshot(ss).current.product_code,12,'the chosen build travels in the shared tab snapshot');
    assert.deepEqual(real(h.errors),[]);
  }finally{h.close();}
});

test('「부품 바꾸기」 opens the old detail screen focused on the part change section',async()=>{
  const ss=storage(),t=talkPage(ss);
  try{
    await say(t,'배그 150만원 이하 게임용');t.d.querySelector('[data-action=choose][data-index="0"]').click();await tick();
    t.d.querySelector('[data-action=open-detail][data-focus=parts]').click();
    assert.deepEqual(fromTalk(ss),{focus:'parts'});
  }finally{t.close();}
  const h=indexPage(ss,'#detail');
  try{
    await until(()=>h.flow.state.screen==='detail'&&!h.flow.state.phase&&h.d.querySelector('#part-change'));
    assert.equal(h.flow.state.selected.product_code,12);
    assert.ok(h.d.activeElement?.closest('#part-change'),'focus is inside the part change section');
    assert.equal(h.d.activeElement.dataset.action,'part-options');
    assert.equal(ss.getItem(FROM_TALK_KEY),null,'the one-shot flag is consumed');
    assert.equal(h.d.querySelector('#back-to-talk').hidden,false);
    assert.deepEqual(real(h.errors),[]);
  }finally{h.close();}
});

test('conditions without a chosen build open the recommendation list on the old screen',async()=>{
  const ss=storage();
  ss.setItem(CONVERSATION_KEY,JSON.stringify({version:1,saved_at:Date.now(),talk:talkState,chat_flow:null,history:[],messages:[{who:'user',text:'배그 150만원'}],current:null}));
  ss.setItem(FROM_TALK_KEY,JSON.stringify({focus:null}));
  const h=indexPage(ss,'#results');
  try{
    await until(()=>h.flow.state.screen==='results'&&!h.flow.state.phase);
    assert.ok(h.calls.some(c=>c.url==='/api/grid/recommend'&&JSON.stringify(c.body.state)===JSON.stringify(talkState)));
    assert.ok([...h.d.querySelectorAll('.message.user')].some(m=>m.textContent.includes('배그 150만원')),'the conversation came along');
    assert.equal(h.w.location.hash,'#results');
    assert.deepEqual(real(h.errors),[]);
  }finally{h.close();}
});

test('「대화로 돌아가기」 shows only when the customer came from the talk screen',async()=>{
  const ss=storage(),plain=indexPage(ss,'#welcome');
  try{assert.equal(plain.d.querySelector('#back-to-talk').hidden,true);assert.deepEqual(real(plain.errors),[]);}finally{plain.close();}
  ss.setItem(FROM_TALK_KEY,JSON.stringify({focus:null}));
  const came=indexPage(ss,'#welcome');
  try{
    const link=came.d.querySelector('#back-to-talk');
    assert.equal(link.hidden,false);assert.equal(link.getAttribute('href'),'talk.html');assert.equal(link.textContent,'대화로 돌아가기');
    assert.deepEqual(real(came.errors),[]);
  }finally{came.close();}
  const later=indexPage(ss,'#welcome');
  try{assert.equal(later.d.querySelector('#back-to-talk').hidden,true,'a later plain visit does not show it');}finally{later.close();}
});

test('round trip keeps the conversation and the part swapped on the old screen',async()=>{
  const ss=storage(),t=talkPage(ss);
  try{
    await say(t,'배그 150만원 이하 게임용');t.d.querySelector('[data-action=choose][data-index="0"]').click();await tick();
    t.d.querySelector('[data-action=open-detail][data-focus=parts]').click();
  }finally{t.close();}
  const h=indexPage(ss,'#detail');
  try{
    await until(()=>h.flow.state.screen==='detail'&&!h.flow.state.phase&&h.d.querySelector('#part-change'));
    h.d.querySelector('#part-change [data-slot=gpu]').click();
    await until(()=>h.d.querySelector('[data-action=part-swap]'));
    h.d.querySelector('[data-action=part-swap]').click();
    await until(()=>h.flow.state.selected.product_code===22);
    assert.deepEqual(snapshot(ss).current.swap_from,{product_code:12,slot:'gpu'},'the swap is written into the shared snapshot');
    assert.equal(snapshot(ss).current.product_code,22);
    assert.deepEqual(real(h.errors),[]);
  }finally{h.close();}
  const back=talkPage(ss);
  try{
    await until(()=>back.flow.state.selected&&!back.flow.state.phase);
    assert.equal(back.flow.state.selected.product_code,22,'지금 견적 is the swapped PC');
    assert.equal(back.flow.state.selected.price,1450000);
    assert.ok(back.d.querySelector('#tk-now-body').textContent.includes('CODE/MOCK PC 22'));
    const log=back.d.querySelector('#tk-log').textContent;
    assert.ok(log.includes('배그 150만원 이하 게임용'),'the conversation is kept');
    assert.ok(log.includes('그래픽카드를 RTX 5070 12GB로 바꿨어요'),'the swap said on the old screen is part of the conversation');
    const lookup=back.calls.find(c=>c.url==='/api/mvp3/part-options');
    assert.deepEqual(lookup.body,{state:talkState,product_code:12,slot:'gpu'},'the swapped PC is found again from the server, not from storage');
    assert.equal(oldLink(back),'index.html#detail');
    assert.deepEqual(real(back.errors),[]);
  }finally{back.close();}
});
