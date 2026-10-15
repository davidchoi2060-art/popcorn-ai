'use strict';
// 2차 대화 화면(talk.html · 코덱스 1816 보강3). CODE/MOCK fixture 만 쓴다.
// 지금 견적은 고객이 고른 구성이다 -- 새 조건·새 추천·잡담·추천 실패가 와도 지우지 않는다.
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),{webcrypto}=require('node:crypto');
const {JSDOM,VirtualConsole}=require('jsdom');
const base=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(base,n),'utf8');
const FORM={ok:true,topics:['여러 대 구매','기타'],consent_text:'CODE/MOCK 동의 문구.'};
const t150={usages:['게임'],budget_won:1500000,budget_bound:'이하'},t100={usages:['게임'],budget_won:1000000,budget_bound:'이하'};
const pc=(code,name,price)=>({product_code:code,name,price,price_src:'현재 판매가',spec:{cpu:'CPU',gpu:'GPU',ram_gb:16,ssd_gb:512},reasons:['CODE/MOCK 이유'],tag:'추천'});
const reco=items=>({ok:true,card_sets:[{kind:'sold',usage:'게임',items}],needs:[],assumed:[]});
const tick=()=>new Promise(r=>setImmediate(r));
async function until(check){for(let n=0;n<400;n++){if(check())return;await tick();}throw Error('render did not settle');}
function storage(){const map=new Map();return {getItem:k=>map.get(k)??null,setItem:(k,v)=>map.set(k,v),removeItem:k=>map.delete(k),key:i=>[...map.keys()][i]??null,get length(){return map.size;}};}

function harness(script,ss=storage(),url='https://qa.invalid/mvp3/talk.html'){
  const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read('talk.html'),{url,runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;w.scrollTo=()=>{};w.TextEncoder=TextEncoder;
  Object.defineProperty(w,'crypto',{value:webcrypto});Object.defineProperty(w,'sessionStorage',{value:ss});
  w.localStorage.setItem('popcorn-mvp3-guest-access-v1','a'.repeat(64));
  w.eval(read('live-model.js'));w.eval(read('api-client.js'));
  const reply=(status,data)=>({ok:status<400,status,json:async()=>data,headers:{get:()=>null}});
  w.MVP3Api=w.MVP3Api.createClient({storage:w.localStorage,cryptoImpl:webcrypto,fetchImpl:async(url,options)=>{
    const body=options.body?JSON.parse(options.body):null;calls.push({url,body});
    if(url==='/api/mvp3/purchase-inquiries/form')return reply(200,FORM);
    const r=script(url,body);return reply(r.status||200,r.data);
  }});
  w.eval(read('live-flow.js'));w.eval(read('live-photo.js'));w.eval(read('talk.js'));
  const doc=w.document;
  async function say(text){doc.querySelector('#tk-input').value=text;doc.querySelector('#tk-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));
    await until(()=>!doc.querySelector('#tk-status').textContent&&!doc.querySelector('#tk-send').disabled);}
  return {w,doc,calls,errors,ss,say,click:s=>doc.querySelector(s).click(),text:s=>doc.querySelector(s)?.textContent||'',close:()=>dom.window.close()};
}
// 첫 문장 150만원 -> 추천 A·B, 둘째 문장 100만원 -> 추천 C. 잡담은 조건을 바꾸지 않는다.
function scripted({failSecond=false}={}){
  let parses=0,recos=0;
  return (url,body)=>{
    if(url==='/api/talk/parse'){parses++;
      if(/심심/.test(body.text))return {data:{ok:true,state:body.state,pc_related:false,missing:[],reply:'심심할 땐 산책도 좋아요.'}};
      return {data:{ok:true,state:/100만/.test(body.text)?t100:t150,missing:[],reply:'조건에 맞는 PC를 찾아볼게요.',pc_related:true}};}
    if(url==='/api/grid/recommend'){recos++;
      if(recos===2&&failSecond)return {status:503,data:{ok:false,detail:'잠시 후 다시 시도해 주세요.'}};
      return {data:recos===1?reco([pc(101,'CODE/MOCK A',1450000),pc(102,'CODE/MOCK B',1390000)]):reco([pc(201,'CODE/MOCK C',990000)])};}
    return {data:{ok:true,quotes:[],has_more:false}};
  };
}

test('first screen offers three starters that fill the input without sending',async()=>{
  const h=harness(scripted());
  try{
    await until(()=>h.doc.querySelector('.tk-welcome'));
    assert.match(h.text('.tk-welcome h1'),/어떤 PC가 필요하세요/);
    const labels=[...h.doc.querySelectorAll('[data-action=starter]')].map(b=>b.textContent);
    assert.deepEqual(labels,['새 PC 찾기','쓰던 PC 업그레이드','부품·구성 물어보기']);
    assert.match(h.text('#tk-now-body'),/구성을 선택하면 여기에 모아둘게요/);
    h.click('[data-action=starter][data-entry=upgrade]');
    assert.equal(h.doc.querySelector('#tk-input').value,'지금 쓰는 PC에서 불편한 점을 상담하고 싶어요.');
    h.click('[data-action=starter][data-entry=new_pc]');
    assert.equal(h.doc.querySelector('#tk-input').value,'새 PC를 찾고 있어요.','another starter replaces an untouched draft');
    await tick();assert.equal(h.calls.length,0);assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});
test('a starter keeps what the customer already typed and its key rides the first send only',async()=>{
  const h=harness(scripted());
  try{
    await until(()=>h.doc.querySelector('.tk-welcome'));
    const box=h.doc.querySelector('#tk-input');box.value='영상 편집용으로';
    h.click('[data-action=starter][data-entry=new_pc]');
    assert.equal(box.value,'영상 편집용으로 새 PC를 찾고 있어요.');
    h.doc.querySelector('#tk-form').dispatchEvent(new h.w.Event('submit',{bubbles:true,cancelable:true}));
    await until(()=>h.calls.some(c=>c.url==='/api/talk/parse'));
    const first=h.calls.find(c=>c.url==='/api/talk/parse');
    assert.equal(first.body.entry,'new_pc');assert.equal(first.body.text,'영상 편집용으로 새 PC를 찾고 있어요.');
    await until(()=>!h.doc.querySelector('#tk-send').disabled&&h.doc.querySelectorAll('.tk-msg.is-ai').length>0);
    assert.ok(h.doc.querySelector('#tk-starters').hidden,'starters go away once the conversation starts');
    assert.ok(!h.doc.querySelector('.tk-chat').classList.contains('is-fresh'));
    await h.say('150만원 게임용');
    await until(()=>h.calls.filter(c=>c.url==='/api/talk/parse').length===2);
    assert.equal(h.calls.filter(c=>c.url==='/api/talk/parse')[1].body.entry,undefined);
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});
test('arriving from a landing path fills that draft once and clears the address',async()=>{
  const h=harness(scripted(),storage(),'https://qa.invalid/mvp3/talk.html?start=upgrade');
  try{
    await until(()=>h.doc.querySelector('.tk-welcome'));
    assert.equal(h.doc.querySelector('#tk-input').value,'지금 쓰는 PC에서 불편한 점을 상담하고 싶어요.');
    assert.equal(h.w.location.search,'');
    h.doc.querySelector('#tk-form').dispatchEvent(new h.w.Event('submit',{bubbles:true,cancelable:true}));
    await until(()=>h.calls.some(c=>c.url==='/api/talk/parse'));
    assert.equal(h.calls.find(c=>c.url==='/api/talk/parse').body.entry,'upgrade');
    await until(()=>!h.doc.querySelector('#tk-send').disabled&&h.doc.querySelectorAll('.tk-msg.is-ai').length>0);
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});
test('a sentence typed on the landing chat box is sent once on arrival without a button key',async()=>{
  const ss=storage();ss.setItem('popcorn-mvp3-first-message-v1',JSON.stringify({text:'지금 쓰는 PC가 느려요',at:Date.now()}));
  const h=harness(scripted(),ss);
  try{
    await until(()=>h.calls.some(c=>c.url==='/api/talk/parse'));
    const first=h.calls.find(c=>c.url==='/api/talk/parse');
    assert.equal(first.body.text,'지금 쓰는 PC가 느려요');assert.equal(first.body.entry,undefined);
    assert.equal(ss.getItem('popcorn-mvp3-first-message-v1'),null,'taken once');
    await until(()=>!h.doc.querySelector('#tk-send').disabled&&h.doc.querySelectorAll('.tk-msg.is-ai').length>0);
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});
// 2026-10-12 중헌 님 고객단 1·2번: 홈으로 돌아와 다른 상담을 고르거나 채팅창에 새로 적으면 지난 대화·조건·지금 견적을 비우고 시작한다.
test('a landing path after an earlier talk starts a fresh consultation',async()=>{
  const ss=storage();const a=harness(scripted(),ss);
  try{await a.say('150만원 게임용');a.doc.querySelector('[data-action=choose][data-index="1"]').click();await tick();}finally{a.close();}
  const b=harness(scripted(),ss,'https://qa.invalid/mvp3/talk.html?start=parts');
  try{
    await until(()=>b.doc.querySelector('.tk-welcome'));
    assert.equal(b.doc.querySelector('#tk-input').value,'PC 부품이나 구성에서 궁금한 점이 있어요.');
    assert.doesNotMatch(b.text('#tk-log'),/150만원 게임용/);
    assert.match(b.text('#tk-now-body'),/구성을 선택하면 여기에 모아둘게요/);
    assert.doesNotMatch(b.text('#tk-now-body'),/지금 조건/);
    await tick();assert.deepEqual(b.calls.map(c=>c.url),[],'the earlier quote is not reopened');
    b.doc.querySelector('#tk-form').dispatchEvent(new b.w.Event('submit',{bubbles:true,cancelable:true}));
    await until(()=>b.calls.some(c=>c.url==='/api/talk/parse'));
    const sent=b.calls.find(c=>c.url==='/api/talk/parse').body;
    assert.equal(sent.state,null);assert.deepEqual(sent.history,[]);
    await until(()=>!b.doc.querySelector('#tk-send').disabled&&b.doc.querySelector('.tk-card'));
    assert.deepEqual(b.errors,[]);
  }finally{b.close();}
});
test('a sentence typed on the landing chat box after an earlier talk starts fresh too',async()=>{
  const ss=storage();const a=harness(scripted(),ss);
  try{await a.say('150만원 게임용');}finally{a.close();}
  ss.setItem('popcorn-mvp3-first-message-v1',JSON.stringify({text:'사무용 컴퓨터요',at:Date.now()}));
  const b=harness(scripted(),ss);
  try{
    await until(()=>b.calls.some(c=>c.url==='/api/talk/parse'));
    const sent=b.calls.find(c=>c.url==='/api/talk/parse').body;
    assert.equal(sent.text,'사무용 컴퓨터요');assert.equal(sent.state,null);assert.deepEqual(sent.history,[]);
    await until(()=>!b.doc.querySelector('#tk-send').disabled&&b.doc.querySelector('.tk-card'));
    assert.doesNotMatch(b.text('#tk-log'),/150만원 게임용/);
  }finally{b.close();}
});
test('opening the talk page without a landing start keeps the earlier talk',async()=>{
  const ss=storage();const a=harness(scripted(),ss);
  try{await a.say('150만원 게임용');}finally{a.close();}
  const b=harness(scripted(),ss);
  // 되살린 대화가 추천 카드까지 다시 불러온 뒤 닫는다(#229 -- 새로고침해도 카드가 남는다).
  try{await until(()=>/150만원 게임용/.test(b.text('#tk-log'))&&b.doc.querySelector('.tk-card')&&!b.doc.querySelector('#tk-send').disabled);await tick();}finally{b.close();}
});
test('an old landing sentence is dropped instead of being sent later',async()=>{
  const ss=storage();ss.setItem('popcorn-mvp3-first-message-v1',JSON.stringify({text:'예전 글',at:Date.now()-3600000}));
  const h=harness(scripted(),ss);
  try{await until(()=>h.doc.querySelector('.tk-welcome'));await tick();assert.equal(h.calls.filter(c=>c.url==='/api/talk/parse').length,0);assert.equal(ss.getItem('popcorn-mvp3-first-message-v1'),null);}finally{h.close();}
});
test('the top label shows the consultation path the server chose',async()=>{
  const h=harness((url,body)=>url==='/api/talk/parse'?{data:{ok:true,state:{usages:[],budget_won:null},missing:[],reply:'어떤 작업에서 느린가요?',answer:'',pc_related:true,chat_flow:{smalltalk_turns:0,pc_offered:false,pc_declined:false,entry:'upgrade',entry_asked:false}}}:{data:{ok:true,quotes:[],has_more:false}});
  try{
    assert.equal(h.text('.demo-label'),'PC 상담');
    await h.say('지금 쓰는 PC가 느려요');
    await until(()=>/업그레이드/.test(h.text('.demo-label')));
    assert.equal(h.text('.demo-label'),'PC 상담 · 쓰던 PC 업그레이드');
  }finally{h.close();}
});
test('a new consultation drops the earlier starter key and path label',async()=>{
  const h=harness((url,body)=>url==='/api/talk/parse'?{data:{ok:true,state:{usages:[],budget_won:null},missing:[],reply:'어떤 작업에서 느린가요?',answer:'',pc_related:true,chat_flow:body.entry?{smalltalk_turns:0,pc_offered:false,pc_declined:false,entry:body.entry,entry_asked:false}:null}}:{data:{ok:true,quotes:[],has_more:false}});
  try{
    let asked=0;h.w.confirm=()=>{asked++;return false;};
    await until(()=>h.doc.querySelector('.tk-welcome'));
    // 단추만 고르고 보내지 않은 채 새 상담 -> 다음 첫 문장에 옛 갈래가 실리지 않는다.
    h.click('[data-action=starter][data-entry=upgrade]');
    h.click('[data-action=new]');
    await h.say('지금 쓰는 PC가 느려요');
    assert.equal(h.calls.filter(c=>c.url==='/api/talk/parse')[0].body.entry,undefined);
    // 단추로 시작해 갈래가 잡힌 뒤 새 상담 -> 상단 표시가 돌아오고 다음 문장에도 갈래가 없다.
    h.click('[data-action=new]');
    h.click('[data-action=starter][data-entry=upgrade]');
    await h.say(h.doc.querySelector('#tk-input').value);
    assert.equal(h.calls.filter(c=>c.url==='/api/talk/parse')[1].body.entry,'upgrade');
    assert.equal(h.text('.demo-label'),'PC 상담 · 쓰던 PC 업그레이드');
    h.click('[data-action=new]');
    assert.equal(h.text('.demo-label'),'PC 상담');
    await h.say('새 PC를 알아보고 있어요');
    const third=h.calls.filter(c=>c.url==='/api/talk/parse')[2];
    assert.equal(third.body.entry,undefined);assert.equal(third.body.chat_flow,null);
    assert.equal(h.text('.demo-label'),'PC 상담');
    // 대화를 나눈 뒤에도 「새 상담」은 확인 창 없이 바로 비운다(2026-10-15 중헌 님).
    h.click('[data-action=new]');
    assert.equal(asked,0);
    assert.ok(!h.text('#tk-log').includes('새 PC를 알아보고 있어요'));
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});
test('an unknown landing path key is ignored',async()=>{
  const h=harness(scripted(),storage(),'https://qa.invalid/mvp3/talk.html?start=game');
  try{await until(()=>h.doc.querySelector('.tk-welcome'));assert.equal(h.doc.querySelector('#tk-input').value,'');assert.deepEqual(h.errors,[]);}finally{h.close();}
});
test('cards sit under the answer and choosing one fills the quote panel',async()=>{
  const h=harness(scripted());
  try{
    await h.say('150만원 게임용');
    const cards=h.doc.querySelectorAll('.tk-cards:not(.is-past) .tk-card');assert.equal(cards.length,2);
    assert.ok(h.doc.querySelector('.tk-msg.is-ai + .tk-cards'),'cards follow an AI bubble');
    h.doc.querySelector('[data-action=choose][data-index="1"]').click();
    await until(()=>/CODE\/MOCK B/.test(h.text('#tk-now-body')));
    assert.match(h.text('#tk-now-body'),/지금 선택한 구성/);assert.match(h.text('#tk-now-body'),/1,390,000원/);assert.match(h.text('#tk-now-body'),/아직 저장하지 않았어요/);
    assert.match(h.text('#tk-log'),/「CODE\/MOCK B」 구성을 지금 견적으로 골랐어요/);
    assert.equal(JSON.parse(h.ss.getItem('popcorn-mvp3-conversation-v1')).current.product_code,102);
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});
test('new conditions add a new proposal but keep the chosen quote until the customer picks again',async()=>{
  const h=harness(scripted());
  try{
    await h.say('150만원 게임용');h.doc.querySelector('[data-action=choose][data-index="0"]').click();await tick();
    await h.say('100만원으로 바꿀게요');
    assert.match(h.text('#tk-now-body'),/CODE\/MOCK A/);assert.match(h.text('#tk-now-body'),/지금 조건 · 게임 · 예산 1,000,000원/);
    assert.match(h.text('#tk-now-body'),/예산보다 450,000원 높아요/);
    const past=h.doc.querySelector('.tk-cards.is-past');assert.ok(past);assert.match(past.textContent,/이전 제안/);
    assert.equal(past.querySelector('[data-action=choose]'),null);
    assert.equal(h.doc.querySelectorAll('.tk-cards:not(.is-past) .tk-card').length,1);
    h.doc.querySelector('.tk-cards:not(.is-past) [data-action=choose]').click();
    await until(()=>/CODE\/MOCK C/.test(h.text('#tk-now-body')));
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});
test('small talk and a failed new recommendation leave the chosen quote in place',async()=>{
  const h=harness(scripted({failSecond:true}));
  try{
    await h.say('150만원 게임용');h.doc.querySelector('[data-action=choose][data-index="0"]').click();await tick();
    await h.say('심심해');assert.match(h.text('#tk-now-body'),/CODE\/MOCK A/);assert.match(h.text('#tk-log'),/산책/);
    await h.say('100만원으로 바꿀게요');
    assert.match(h.text('.tk-msg.is-error'),/새 추천을 불러오지 못했어요\. 앞서 고른 견적은 유지할게요\./);
    assert.match(h.text('#tk-now-body'),/CODE\/MOCK A/);
    assert.ok(h.doc.querySelector('.tk-msg.is-error [data-action=inquiry-open][data-human="1"]'));
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});
test('general and purchase inquiries use their own titles',async()=>{
  const h=harness(scripted());
  try{
    await h.say('150만원 게임용');h.doc.querySelector('[data-action=choose][data-index="0"]').click();await tick();
    assert.match(h.text('.tk-phone'),/상담사가 전화로 구성을 함께 살펴봐요/);
    h.click('.tk-ask [data-action=inquiry-open][data-human="1"]');await until(()=>h.doc.querySelector('[data-inquiry=topic]'));
    assert.equal(h.text('.tk-inquiry h3'),'전문가에게 문의하기');
    h.click('[data-action=inquiry-close]');await tick();
    h.click('.tk-ask [data-action=inquiry-open]:not([data-human])');await until(()=>h.doc.querySelector('[data-inquiry=topic]'));
    assert.equal(h.text('.tk-inquiry h3'),'구매 조건 문의');assert.match(h.text('.tk-inquiry'),/세금계산서/);
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});
test('a refresh reopens the chosen quote by asking the server again',async()=>{
  const ss=storage();const a=harness(scripted(),ss);
  try{await a.say('150만원 게임용');a.doc.querySelector('[data-action=choose][data-index="1"]').click();await tick();}finally{a.close();}
  const b=harness((url,body)=>url==='/api/grid/recommend'?{data:reco([pc(101,'CODE/MOCK A',1450000),pc(102,'CODE/MOCK B',1370000)])}:{data:{ok:true}},ss);
  try{
    await until(()=>/CODE\/MOCK B/.test(b.text('#tk-now-body')));
    assert.match(b.text('#tk-now-body'),/1,370,000원/);assert.match(b.text('#tk-now-body'),/새로고침 전 저장 여부는 내 견적에서/);
    assert.match(b.text('#tk-log'),/150만원 게임용/);assert.match(b.text('#tk-log'),/금액은 지금 다시 확인한 값/);
    assert.deepEqual(b.calls.map(c=>c.url),['/api/grid/recommend']);assert.deepEqual(b.errors,[]);
  }finally{b.close();}
});
// 코덱스 PR142·143 검수 보완(2026-10-11).
test('a price change on save keeps the quote and offers a fresh price check before saving again',async()=>{
  const base=scripted();let reprices=0,posts=[];
  const h=harness((url,body)=>{
    if(url==='/api/mvp3/saved-quotes'&&body){posts.push(body.expected_price);
      if(body.expected_price===1450000)return {status:409,data:{detail:{error:'price_changed'}}};
      return {data:{ok:true,quote:{id:'22222222-2222-4222-8222-222222222222',product:pc(101,'CODE/MOCK A',body.expected_price),state:body.state,saved_at:'2026-10-11T09:00:00+00:00'}}};}
    if(url==='/api/grid/recommend'&&reprices++>=1)return {data:reco([pc(101,'CODE/MOCK A',1470000)])};
    return base(url,body);
  });
  try{
    await h.say('150만원 게임용');h.doc.querySelector('[data-action=choose][data-index="0"]').click();await tick();
    h.click('[data-action=save]');await until(()=>h.doc.querySelector('[data-action=reprice]'));
    assert.match(h.text('.tk-msg.is-error'),/금액이 바뀌어 저장하지 못했어요/);assert.match(h.text('#tk-now-body'),/CODE\/MOCK A/);
    assert.equal(h.doc.querySelector('[data-action=save]'),null,'old price cannot be resent');
    h.click('[data-action=reprice]');await until(()=>h.doc.querySelector('[data-action=save]')&&!h.doc.querySelector('[data-action=save]').disabled);
    assert.match(h.text('#tk-now-body'),/1,470,000원/);assert.match(h.text('#tk-log'),/1,450,000원에서 1,470,000원으로/);
    assert.deepEqual(posts,[1450000]);
    h.click('[data-action=save]');await until(()=>/견적을 저장했어요/.test(h.text('#tk-now-body')));
    assert.deepEqual(posts,[1450000,1470000]);assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});
test('on a narrow screen an inquiry button opens the folded quote panel and moves focus to the form',async()=>{
  const h=harness(scripted({failSecond:true}));
  try{
    await h.say('150만원 게임용');h.doc.querySelector('[data-action=choose][data-index="0"]').click();await tick();
    await h.say('100만원으로 바꿀게요');
    assert.equal(h.doc.querySelector('#tk-now').classList.contains('is-open'),false);
    h.click('.tk-msg.is-error [data-action=inquiry-open]');
    await until(()=>h.doc.querySelector('[data-inquiry=topic]'));await tick();
    assert.equal(h.doc.querySelector('#tk-now').classList.contains('is-open'),true);
    assert.equal(h.doc.querySelector('[data-action=toggle-now]').getAttribute('aria-expanded'),'true');
    assert.equal(h.doc.activeElement,h.doc.querySelector('[data-inquiry=topic]'));
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});
test('opening details of another card asks before replacing the chosen quote',async()=>{
  const h=harness(scripted());
  try{
    await h.say('150만원 게임용');h.doc.querySelector('[data-action=choose][data-index="0"]').click();await tick();
    let asked='';h.w.confirm=m=>{asked=m;return false;};
    h.doc.querySelector('[data-action=detail][data-index="1"]').click();await tick();
    assert.match(asked,/지금 견적이 「CODE\/MOCK B」 구성으로 바뀌어요/);assert.match(h.text('#tk-now-body'),/CODE\/MOCK A/);
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('cards over the budget come with the server reason above them',async()=>{
  const h=harness((url,body)=>url==='/api/talk/parse'?{data:{ok:true,state:{usages:['사무용'],budget_won:500000,budget_bound:'이하'},missing:[],reply:'사무용 50만원으로 볼게요.',pc_related:true}}
    :url==='/api/grid/recommend'?{data:{ok:true,card_sets:[{kind:'sold',usage:'사무용',empty_reason:'예산 안 상품 없음',empty_note:'이 작업은 595,700원부터 가능합니다.',
      items:[pc(301,'CODE/MOCK D',595700)]}],needs:[],assumed:[]}}:{data:{ok:true,quotes:[],has_more:false}});
  try{
    await h.say('사무용 50만원');
    assert.equal(h.text('.tk-cards .tk-group-note'),'이 작업은 595,700원부터 가능합니다.');
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('a budget far below the cheapest PC shows only the server line, no cards',async()=>{
  const note='이 작업은 4,800,000원부터 가능합니다. 예산을 조금 올리시면 보여 드릴게요.';
  const h=harness((url,body)=>url==='/api/talk/parse'?{data:{ok:true,state:{usages:['영상 편집'],budget_won:100000,budget_bound:'이하'},missing:[],reply:'영상 편집 10만원으로 볼게요.',pc_related:true}}
    :url==='/api/grid/recommend'?{data:{ok:true,card_sets:[{kind:'sold',usage:'영상 편집',empty_reason:'예산이 너무 낮음',empty_note:note,items:[]}],needs:[],assumed:[]}}
    :{data:{ok:true,quotes:[],has_more:false}});
  try{
    await h.say('영상 편집 10만원');
    assert.equal(h.text('.tk-cards.is-empty .tk-group-note'),note);
    assert.equal(h.doc.querySelectorAll('.tk-card-list li').length,0);
    assert.doesNotMatch(h.text('.tk-cards.is-empty'),/찾지 못했어요/);
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

// 2026-10-12 카드 검수 X1: SSD 를 1TB 로 바꿔도 지금 견적 사양은 「저장장치 500GB SSD」, 쇼핑몰 연결은 기본 구성 안내 없이 열렸다.
test('the current quote shows the changed part instead of the base spec and says the name is the base build',async()=>{
  const ss=storage();
  ss.setItem('popcorn-mvp3-conversation-v1',JSON.stringify({version:1,saved_at:Date.now(),talk:t150,chat_flow:null,history:[],messages:[{who:'user',text:'150만원 게임용'}],
    current:{product_code:101,changes:[{ordinal:1,product_code:502}],selection_state:t150}}));
  const ssd={ordinal:1,slot:'SSD',label:'저장장치',quantity:1,before:{product_code:501,name:'SSD 512GB',price:50000},after:{product_code:502,name:'PNY CS900 1TB',price:100000},delta:50000};
  const h=harness((url)=>url==='/api/grid/recommend'?{data:reco([pc(101,'CODE/MOCK A',1450000)])}
    :url==='/api/mvp3/build/quote'?{data:{ok:true,base_code:101,base_price:1450000,total:1500000,changes:[ssd]}}:{data:{ok:true,quotes:[],has_more:false}},ss);
  try{
    await until(()=>h.text('#tk-now-body .tk-price').includes('1,500,000원'));
    const body=h.text('#tk-now-body');
    assert.match(body,/상품 이름은 기본 구성 기준이에요\. 바꾼 부품: 저장장치 PNY CS900 1TB/);
    assert.match(body,/저장장치PNY CS900 1TB \(바꾼 부품\)/);
    assert.ok(!body.includes('512GB SSD'));
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

// 2026-10-12 카드 검수 X2: 「차이만 설명해 주세요 · 아직 추천은 필요 없어요」에도 설명 뒤 카드 3장이 나왔다.
test('an explain-only answer does not call the recommendation',async()=>{
  const h=harness((url,body)=>url==='/api/talk/parse'?{data:{ok:true,state:t150,missing:[],pc_related:true,explain_only:true,
      answer:'16GB는 문서·게임에, 32GB는 영상 편집에 여유가 있어요.',reply:''}}
    :url==='/api/grid/recommend'?{data:reco([pc(101,'CODE/MOCK A',1450000)])}:{data:{ok:true,quotes:[],has_more:false}});
  try{
    await h.say('RAM 16GB랑 32GB 차이만 설명해 주세요. 아직 PC 추천은 필요 없어요.');
    assert.ok(!h.calls.some(c=>c.url==='/api/grid/recommend'));
    assert.match(h.text('#tk-log'),/32GB는 영상 편집에 여유/);
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

// 2026-10-12 사장님 결정 「크게」: 카드 맨 위에 작업 수준(용도 수준 / 작업)을 크게 둔다 -- 사양표 아래 작은 줄이 아니다.
test('card shows the work level big at the top, and no product name over the photo',async()=>{
  const fit={...pc(301,'CODE/MOCK 영상',3230400),reasons:['영상편집 쾌적 — 4K 편집']};
  const h=harness((url)=>url==='/api/talk/parse'?{data:{ok:true,state:t150,missing:[],reply:'찾아볼게요.',pc_related:true}}
    :url==='/api/grid/recommend'?{data:reco([fit])}:{data:{ok:true,quotes:[],has_more:false}});
  try{
    await h.say('4K 영상 편집');
    const card=h.doc.querySelector('.tk-card'),line=card.querySelector('.tk-fit');
    assert.equal(line.querySelector('strong').textContent,'영상편집 쾌적');assert.equal(line.querySelector('span').textContent,'4K 편집');
    assert.ok(line.compareDocumentPosition(card.querySelector('.tk-price'))&h.w.Node.DOCUMENT_POSITION_FOLLOWING,'before the price');
    // 2026-10-12 중헌 님 고객단 4번: 사진 위 상품명은 아래 사양과 겹쳐 뺐다.
    assert.equal(card.querySelector('h4'),null);assert.doesNotMatch(card.textContent,/CODE\/MOCK 영상/);
    assert.equal(card.querySelectorAll('.tk-reason').length,0,'not repeated as a small line');
  }finally{h.close();}
});

// 2026-10-15 코덱스 오픈테스트 C10-F01: 12대 총 960만원에서 892,800원 카드가 「예산보다 8,707,200원 낮아요」였다.
// 서버가 읽은 대수(wants.units)가 있으면 한 대 예산(총예산 ÷ 대수)으로 견주고, 대수를 모르면 견주지 않는다.
test('bulk purchase: cards compare one unit to the per-unit budget, never to the total',async()=>{
  const t960={usages:['사무용'],budget_won:9600000,budget_bound:'이하'};
  let units=12;
  const h=harness((url)=>{
    if(url==='/api/talk/parse')return {data:{ok:true,state:t960,missing:[],reply:'찾아볼게요.',pc_related:true}};
    if(url==='/api/grid/recommend')return {data:{...reco([pc(301,'CODE/MOCK 사무 A',595700),pc(302,'CODE/MOCK 사무 B',892800)]),wants:{units}}};
    return {data:{ok:true,quotes:[],has_more:false}};
  });
  const gaps=()=>[...h.doc.querySelectorAll('.tk-cards:not(.is-past) .tk-card')].map(c=>[...c.querySelectorAll('p')].find(p=>/예산/.test(p.textContent)));
  try{
    await h.say('사무용 PC 12대, 총 960만원');
    await until(()=>h.doc.querySelectorAll('.tk-cards:not(.is-past) .tk-card').length===2);
    let [a,b]=gaps();
    assert.equal(a.textContent,'12대 기준 한 대 예산 800,000원보다 204,300원 낮아요');
    assert.equal(b.textContent,'12대 기준 한 대 예산 800,000원보다 92,800원 높아요');
    assert.equal(b.className,'warn-text');
    assert.doesNotMatch(h.text('.tk-cards'),/8,707,200/);
    units=15;await h.say('15대로 늘었어요');
    await until(()=>/15대 기준/.test(h.text('.tk-cards:not(.is-past)')));
    [a,b]=gaps();
    assert.equal(a.textContent,'15대 기준 한 대 예산 640,000원보다 44,300원 낮아요');
    assert.equal(b.textContent,'15대 기준 한 대 예산 640,000원보다 252,800원 높아요');
    units=0;await h.say('여러 대 살 거예요');
    await until(()=>/견주지 않았어요/.test(h.text('.tk-cards:not(.is-past)')));
    assert.doesNotMatch(h.text('.tk-cards:not(.is-past)'),/예산보다/);
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});
