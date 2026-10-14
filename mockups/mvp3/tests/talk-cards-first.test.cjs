'use strict';
// 「카드 먼저」(2026-10-14 사장님 「그렇게 해」) -- 서버가 설명을 기다리지 않고 답하면(answer_pending) 카드를 먼저 부르고,
// 설명은 /api/talk/answer 로 받아 같은 말풍선에 채운다. 설명을 못 받으면 첫 응답 문장으로 둔다. CODE/MOCK fixture 만 쓴다.
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),{webcrypto}=require('node:crypto');
const {JSDOM,VirtualConsole}=require('jsdom');
const base=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(base,n),'utf8');
const talk={usages:['게임'],budget_won:1500000};
const tick=()=>new Promise(r=>setImmediate(r));
async function until(check){for(let n=0;n<400;n++){if(check())return;await tick();}throw Error('render did not settle');}

function harness(answerReply){
  const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read('index.html'),{url:'https://qa.invalid/mvp3/#welcome',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.TextEncoder=TextEncoder;
  Object.defineProperty(w,'crypto',{value:webcrypto});w.localStorage.setItem('popcorn-mvp3-guest-access-v1','a'.repeat(64));
  w.eval(read('live-model.js'));w.eval(read('api-client.js'));
  const reply=(status,data)=>({ok:status<400,status,json:async()=>data,headers:{get:()=>null}});
  w.MVP3Api=w.MVP3Api.createClient({storage:w.localStorage,cryptoImpl:webcrypto,fetchImpl:async(url,options)=>{
    calls.push({url,method:options.method,body:options.body?JSON.parse(options.body):null});
    if(url==='/api/talk/parse')return reply(200,{ok:true,state:talk,missing:[],assumed:[],answer:'',reply:'첫 응답 문장',answer_pending:'tok-1'});
    if(url==='/api/talk/answer'){const r=await answerReply();return reply(r.status||200,r.data);}
    if(url==='/api/grid/recommend')return reply(200,{ok:true,card_sets:[],needs:[],assumed:[]});
    return reply(200,{ok:true,quotes:[],has_more:false});
  }});
  w.eval(read('live-flow.js'));
  const create=w.MVP3LiveFlow.createFlow;let flow;
  w.MVP3LiveFlow.createFlow=(...args)=>{flow=create(...args);return flow;};
  w.eval(read('live-photo.js'));w.eval(read('app.js'));
  return {w,get flow(){return flow;},calls,errors,close:()=>dom.window.close()};
}
const lastAi=h=>h.flow.state.messages.filter(m=>m.who==='ai').pop();

test('cards are requested before the explanation arrives, then the explanation fills the same bubble',async()=>{
  let release;const gate=new Promise(r=>{release=r;});
  const h=harness(async()=>{await gate;return {data:{ok:true,state:talk,missing:[],answer:'게임용은 그래픽카드가 먼저예요.',reply:'FHD 기준으로 골랐어요.'}};});
  try{
    await h.flow.submit('게임용 150만원');
    await until(()=>h.flow.state.phase===null);
    assert.equal(h.calls.find(c=>c.url==='/api/talk/parse').body.defer_answer,true);
    assert.equal(h.calls.filter(c=>c.url==='/api/grid/recommend').length,1);   // 카드는 설명을 기다리지 않는다
    assert.match(lastAi(h).text,/설명을 쓰고 있어요/);
    assert.equal(lastAi(h).pending,true);
    const at=h.flow.state.messages.indexOf(lastAi(h));
    release();
    await until(()=>!lastAi(h).pending);
    assert.equal(lastAi(h).text,'게임용은 그래픽카드가 먼저예요.\n\nFHD 기준으로 골랐어요.');
    assert.equal(h.flow.state.messages.indexOf(lastAi(h)),at);                 // 말풍선 자리는 그대로(카드 위)
    assert.deepEqual(h.calls.find(c=>c.url==='/api/talk/answer').body,{token:'tok-1'});
    assert.ok(h.flow.state.history.some(x=>x.role==='assistant'&&/그래픽카드/.test(x.text)));
    assert.equal(h.calls.filter(c=>c.url==='/api/grid/recommend').length,1);   // 조건이 같으면 카드를 다시 부르지 않는다
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('when the explanation cannot be fetched the first reply stays',async()=>{
  const h=harness(async()=>({status:404,data:{detail:'answer not found'}}));
  try{
    await h.flow.submit('게임용 150만원');
    await until(()=>h.flow.state.phase===null&&!lastAi(h).pending);
    assert.equal(lastAi(h).text,'첫 응답 문장');
    assert.equal(h.flow.state.error,null);
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});
