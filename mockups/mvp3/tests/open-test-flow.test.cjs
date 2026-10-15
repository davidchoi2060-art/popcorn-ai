'use strict';
// 2026-10-15 오픈테스트(고객10명) 결함 회귀. CODE/MOCK fixture 만 쓴다.
//   C04-F01 · C07-F03  첫 답변 뒤 추천 조회가 API 재시작 중 nginx 502 HTML 을 받아 「서버 응답을 확인할 수 없어요」로 끝났다.
//   C06-F05            기존 상담이 있는 #start 에서 「새 PC 고르기」 클릭이 이동하지 않았다(다시 그릴 때 카드가 바뀌어 클릭이 사라짐).
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),{webcrypto}=require('node:crypto');
const {JSDOM,VirtualConsole}=require('jsdom');
const A=require('../api-client.js'),{createFlow}=require('../live-flow.js');
const base=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(base,n),'utf8');
const talk={usages:['게임'],budget_won:1900000,budget_bound:'이하'};
const product={product_code:101,name:'CODE/MOCK PC',price:1800000,spec:{cpu:'MOCK CPU'}};
const reco={ok:true,card_sets:[{kind:'sold',usage:'게임',items:[product]}],needs:[],assumed:[]};
const parsed={ok:true,state:talk,chat_flow:null,missing:[],assumed:[],answer:'P1 을 권해요.',reply:'',agent:true,pc_related:true};
function storage(){const map=new Map();return {getItem:k=>map.get(k)??null,setItem:(k,v)=>map.set(k,v),removeItem:k=>map.delete(k)};}
const json=(data,status=200)=>({ok:status<400,status,headers:{get:()=>null},json:async()=>data});
// nginx 가 API 재시작 중에 내는 502 화면(본문이 HTML 이라 JSON 으로 읽히지 않는다).
const nginx502=()=>({ok:false,status:502,headers:{get:()=>null},json:async()=>{throw new SyntaxError('Unexpected token <');}});
function flowWith(recommendReplies,options={}){
  const calls=[];
  const api=A.createClient({storage:storage(),cryptoImpl:webcrypto,fetchImpl:async(url,init)=>{
    calls.push(url);if(url==='/api/talk/parse')return json(parsed);
    if(url==='/api/grid/recommend'){const r=recommendReplies.shift();return r?r():json(reco);}
    return json({ok:true,quotes:[],has_more:false});
  }});
  const flow=createFlow(api,{uuid:()=>'11111111-1111-4111-8111-111111111111',sessionStorage:storage(),keepCurrent:true,retryDelays:[0,0],...options});
  flow.reset();return {flow,calls,recommends:()=>calls.filter(u=>u==='/api/grid/recommend').length};
}

test('C04/C07: a proxy 502 (non-JSON) is a transient gateway error, not an invalid response',async()=>{
  const c=A.createClient({storage:storage(),cryptoImpl:webcrypto,fetchImpl:async()=>nginx502()});
  await assert.rejects(c.recommend(talk,{}),e=>e.code==='gateway_error'&&e.status===502&&!/응답을 확인할 수 없어요/.test(e.message));
  // 정상 상태코드인데 JSON 이 아니면 여전히 응답 형식 문제다.
  const bad=A.createClient({storage:storage(),cryptoImpl:webcrypto,fetchImpl:async()=>({ok:true,status:200,headers:{get:()=>null},json:async()=>{throw Error('x');}})});
  await assert.rejects(bad.recommend(talk,{}),e=>e.code==='invalid_response');
});

test('C04/C07: the answer-then-cards turn retries a transient recommend failure and shows the cards',async()=>{
  const h=flowWith([nginx502]);
  await h.flow.submit('1440p 고사양 게임 190만원');
  assert.equal(h.recommends(),2);
  assert.equal(h.flow.state.error,null);
  assert.equal(h.flow.state.recommendation.groups[0].products[0].product_code,101);
  assert.equal(h.flow.state.screen,'results');
});

test('C04/C07: retries are bounded; a lasting outage is reported as a connection failure with retry',async()=>{
  const h=flowWith([nginx502,nginx502,nginx502]);
  await h.flow.submit('1440p 고사양 게임 190만원');
  assert.equal(h.recommends(),3);
  assert.equal(h.flow.state.retry.kind,'recommend');
  assert.equal(h.flow.state.error.code,'gateway_error');
  assert.doesNotMatch(h.flow.state.error.message,/응답을 확인할 수 없어요/);
});

test('C04/C07: a JSON error the server chose (502 grid_down) and 429 are not retried automatically',async()=>{
  for(const r of [()=>json({detail:{error:'grid_down'}},502),()=>json({detail:{error:'rate'}},429)]){
    const h=flowWith([r]);await h.flow.submit('게임 190만원');
    assert.equal(h.recommends(),1);assert.equal(h.flow.state.retry.kind,'recommend');
  }
});

test('C04/C07: a newer request during the retry pause stops the old retry',async()=>{
  const h=flowWith([nginx502],{retryDelays:[50]});
  const first=h.flow.submit('게임 190만원');
  await new Promise(r=>setTimeout(r,5));
  h.flow.cancel();await first;
  await new Promise(r=>setTimeout(r,80));
  assert.equal(h.recommends(),1);assert.equal(h.flow.state.error,null);
});

function gatewayHarness(){
  const errors=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read('index.html'),{url:'https://qa.invalid/mvp3/#start',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.TextEncoder=TextEncoder;
  Object.defineProperty(w,'crypto',{value:webcrypto});w.localStorage.setItem('popcorn-mvp3-guest-access-v1','a'.repeat(64));
  // 대화 화면에서 상담하고 돌아온 탭: 이 탭 보관에 본인 상담이 있다(「작성하던 상담 이어가기」가 보인다).
  w.sessionStorage.setItem('popcorn-mvp3-conversation-v1',JSON.stringify({version:1,saved_at:Date.now(),talk,chat_flow:null,
    history:[{role:'user',text:'게임 190만원'}],messages:[{who:'user',text:'게임 190만원'},{who:'ai',text:'P1 을 권해요.'}],current:null,shown:true}));
  w.eval(read('live-model.js'));w.eval(read('api-client.js'));
  w.MVP3Api=w.MVP3Api.createClient({storage:w.localStorage,cryptoImpl:webcrypto,fetchImpl:async()=>new Promise(()=>{})});
  w.eval(read('live-flow.js'));const create=w.MVP3LiveFlow.createFlow;let flow;
  w.MVP3LiveFlow.createFlow=(...args)=>{flow=create(...args);return flow;};
  w.eval(read('live-photo.js'));w.eval(read('app.js'));
  return {w,get flow(){return flow;},errors,close:()=>w.close()};
}

test('C06-F05: with an own consultation on #start, re-renders keep the start cards so a click still navigates',()=>{
  const h=gatewayHarness();
  try{
    const d=h.w.document,card=d.querySelector('[data-action="gateway-start"][data-start="new_pc"]');
    assert.ok(d.querySelector('[data-action="gateway-continue"]'),'own consultation is offered');
    // 진행 중인 일·초읽기로 render() 가 다시 돌아도 같은 단추가 남아야 누르는 사이 클릭이 사라지지 않는다.
    card.dispatchEvent(new h.w.MouseEvent('mousedown',{bubbles:true}));
    h.flow.emit();h.flow.emit();
    assert.equal(d.querySelector('[data-action="gateway-start"][data-start="new_pc"]'),card);
    assert.ok(card.isConnected);
    card.querySelector('h2').click();
    // jsdom 은 다른 문서로 이동하지 못한다 -- 이동을 시도했다는 기록으로 확인한다.
    assert.ok(h.errors.some(m=>/navigation/i.test(m)),'click attempted navigation to talk.html');
    // 내용이 바뀌면 다시 그린다(입력한 글은 그대로 남는다).
    const text=d.querySelector('#gateway-text');text.value='새 글';text.dispatchEvent(new h.w.Event('input',{bubbles:true}));h.flow.emit();
    assert.equal(d.querySelector('#gateway-text').value,'새 글');
  }finally{h.close();}
});
