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

function harness(script,ss=storage()){
  const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read('talk.html'),{url:'https://qa.invalid/mvp3/talk.html',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
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
    h.click('.tk-ask [data-action=inquiry-open][data-human="1"]');await until(()=>h.doc.querySelector('[data-inquiry=topic]'));
    assert.equal(h.text('.tk-inquiry h3'),'사람에게 문의하기');
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
