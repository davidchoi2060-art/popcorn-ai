// 코덱스 PR138 검수 보완(2026-10-11): 새로고침 뒤 보던 견적을 다시 열기 · 일반/구매 문의 성격 구분 · 보관 전 가림 순서.
const test=require('node:test'),assert=require('node:assert/strict');
const {createFlow,CONVERSATION_KEY,conversationSnapshot}=require('../live-flow.js');
const ID='11111111-1111-4111-8111-111111111111';
const talk={usages:['게임'],budget_won:1500000,budget_bound:'이하'};
const product={product_code:101,name:'검증용 PC',price:1430000,price_src:'등록 판매가',spec:{cpu:'CPU',gpu:'GPU',ram_gb:32,ssd_gb:1024},reasons:['조건에 맞는 등록 상품'],tag:'추천'};
const reco={ok:true,card_sets:[{kind:'sold',usage:'게임',items:[product,{...product,product_code:102,name:'대안 PC'}]}],needs:[],assumed:[]};
const parsed={ok:true,state:talk,chat_flow:{step:2},answer:'',reply:'찾아볼게요.',pc_related:true,missing:[]};
const change={ordinal:1,slot:'RAM',label:'메모리',quantity:1,base_quantity:1,before:{product_code:501,name:'램 16GB',price:60000},after:{product_code:502,name:'램 32GB',price:110000},delta:50000};
function storage(){const map=new Map();return {getItem:k=>map.get(k)??null,setItem:(k,v)=>map.set(k,v),removeItem:k=>map.delete(k),map};}
const tick=()=>new Promise(r=>setImmediate(r));
function make(api,ss){const flow=createFlow({parse:async()=>parsed,recommend:async()=>reco,inquiryForm:async()=>({ok:true,topics:['기타','여러 대 구매'],consent_text:'동의'}),...api},{uuid:()=>ID,sessionStorage:ss});return flow;}
function seed(ss,current){ss.setItem(CONVERSATION_KEY,JSON.stringify({version:1,saved_at:Date.now(),talk,chat_flow:null,history:[],messages:[{who:'user',text:'150만원 게임용'}],current}));}
const stored=ss=>JSON.parse(ss.getItem(CONVERSATION_KEY)).current;

test('a second refresh before reopening keeps the product number',()=>{
  const ss=storage();seed(ss,{product_code:101,changes:[]});
  const a=make({},ss);a.reset({restore:true});assert.deepEqual(stored(ss),{product_code:101,changes:[]});
  const b=make({},ss);b.reset({restore:true});assert.deepEqual(b.state.restoredCurrent,{product_code:101,changes:[]});
});
test('resume asks the server again and reopens the same product at today\'s price',async()=>{
  const ss=storage();seed(ss,{product_code:101,changes:[]});
  const f=make({recommend:async()=>({...reco,card_sets:[{kind:'sold',usage:'게임',items:[{...product,price:1390000}]}]})},ss);
  f.reset({restore:true});await f.resume();
  assert.equal(f.state.screen,'detail');assert.equal(f.state.selected.product_code,101);assert.equal(f.state.selected.price,1390000);
  assert.equal(f.state.restoredCurrent,null);assert.match(f.state.messages.at(-1).text,/지금 다시 확인한 값/);
  assert.deepEqual(stored(ss),{product_code:101,changes:[],selection_state:talk});
});
test('resume re-applies changed parts through the server quote',async()=>{
  const ss=storage();seed(ss,{product_code:101,changes:[{ordinal:1,product_code:502}]});let asked=null;
  const f=make({buildQuote:async(s,code,changes)=>{asked={code,changes};return {ok:true,base_code:101,base_price:1430000,total:1480000,changes:[change]};}},ss);
  f.reset({restore:true});await f.resume();
  assert.deepEqual(asked,{code:101,changes:[{ordinal:1,product_code:502}]});
  assert.equal(f.state.selected.price,1480000);assert.match(f.state.messages.at(-1).text,/바꿨던 부품도 다시 적용/);
  assert.deepEqual(stored(ss),{product_code:101,changes:[{ordinal:1,product_code:502}],selection_state:talk});
});
test('if parts cannot be re-applied it shows the base build and says so',async()=>{
  const ss=storage();seed(ss,{product_code:101,changes:[{ordinal:1,product_code:502}]});
  const f=make({buildQuote:async()=>{throw new Error('down');}},ss);
  f.reset({restore:true});await f.resume();
  assert.equal(f.state.selected.price,1430000);assert.ok(!f.state.selected.build);
  assert.match(f.state.messages.at(-1).text,/기본 구성으로 보여 드려요/);
});
test('a product no longer recommended is not invented',async()=>{
  const ss=storage();seed(ss,{product_code:999,changes:[]});
  const f=make({},ss);f.reset({restore:true});await f.resume();
  assert.equal(f.state.selected,null);assert.equal(f.state.screen,'results');assert.equal(f.state.restoredCurrent,null);
  assert.match(f.state.messages.at(-1).text,/상품번호 999.*찾지 못했어요/);
});
test('a failed re-query keeps the product number for retry',async()=>{
  const ss=storage();seed(ss,{product_code:101,changes:[]});let fail=true;
  const f=make({recommend:async()=>{if(fail)throw Object.assign(new Error('잠시 후'),{status:503});return reco;}},ss);
  f.reset({restore:true});await f.resume();
  assert.deepEqual(f.state.restoredCurrent,{product_code:101,changes:[]});assert.equal(f.state.retry.kind,'resume');
  assert.deepEqual(stored(ss),{product_code:101,changes:[]});
  fail=false;await f.retry();assert.equal(f.state.selected.product_code,101);
});
test('new conditions drop the old product number',async()=>{
  const ss=storage();seed(ss,{product_code:101,changes:[]});
  const f=make({parse:async()=>({...parsed,state:{...talk,budget_won:900000},missing:['usage']})},ss);
  f.reset({restore:true});await f.submit('90만원으로 바꿀게요');
  assert.equal(f.state.restoredCurrent,null);assert.equal(stored(ss),null);
});
test('masking runs before trimming so a number cut at the edge is not left as a fragment',()=>{
  const long='가'.repeat(1990)+' 1234-5678-9012-3456';
  const rec=conversationSnapshot({history:[],messages:[{who:'user',text:long}],selected:null,restoredCurrent:null});
  assert.equal(rec.messages[0].text.includes('1234'),false);assert.ok(rec.messages[0].text.length<=2000);
});
test('the inquiry follows the button it was opened with',async()=>{
  const f=make({},storage());f.reset();
  await f.openInquiry({human:true});assert.equal(f.state.inquiry.human,true);assert.equal(f.state.inquiry.draft.topic,'기타');
  f.closeInquiry();await f.openInquiry();assert.equal(f.state.inquiry.human,false);
  f.closeInquiry();await f.openInquiry({human:true});assert.equal(f.state.inquiry.human,true);
});
test('the retry button keeps the general inquiry wording',()=>{
  const app=require('node:fs').readFileSync(require('node:path').join(__dirname,'../app.js'),'utf8');
  assert.match(app,/button\('다시 불러오기','inquiry-open','outline',human\?'data-human="1"':''\)/);
  assert.match(app,/state\.restoredCurrent&&state\.talk\)\{restoring=true;void flow\.resume\(\{arrived:!!arrival\}\)/);
});

// 코덱스 PR142·143 검수 보완(2026-10-11): 대화 화면(keepCurrent)에서 조건을 바꾼 뒤에도 지금 견적을 지킨다.
const talk100={...talk,budget_won:1000000};
const other={...product,product_code:301,name:'100만원 PC',price:990000};
const reco100={...reco,card_sets:[{kind:'sold',usage:'게임',items:[other]}]};
const BIND='a'.repeat(64),QID='22222222-2222-4222-8222-222222222222';
function keep(api,ss){return createFlow({parse:async()=>parsed,recommend:async s=>s.budget_won===1000000?reco100:reco,prepareSave:async()=>BIND,
  saveQuote:async p=>({ok:true,quote:{id:QID,product:{...product,price:p.expected_price},state:p.state,saved_at:'2026-10-11T09:00:00+00:00'}}),...api},{uuid:()=>ID,sessionStorage:ss,keepCurrent:true});}
test('a quote chosen before a condition change survives a reload (selection basis is stored)',async()=>{
  const ss=storage();let next=talk;
  const f=keep({parse:async()=>({...parsed,state:next})},ss);f.reset();
  await f.submit('150만원 게임용');f.select(0);
  next=talk100;await f.submit('100만원으로 바꿀게요');
  assert.equal(f.state.selected.product_code,101);assert.deepEqual(f.state.talk,talk100);
  assert.deepEqual(stored(ss),{product_code:101,changes:[],selection_state:talk});
  const asked=[];const g=keep({recommend:async s=>{asked.push(s.budget_won);return s.budget_won===1000000?reco100:reco;}},ss);
  g.reset({restore:true});assert.deepEqual(g.state.restoredCurrent.selection_state,talk);
  await g.resume();
  assert.deepEqual(asked,[1000000,1500000]);
  assert.equal(g.state.selected.product_code,101);assert.deepEqual(g.state.selectionState,talk);assert.deepEqual(g.state.talk,talk100);
});
test('in the conversation screen a new condition does not drop a quote still waiting to reopen',async()=>{
  const ss=storage();seed(ss,{product_code:101,changes:[],selection_state:talk});
  const f=keep({parse:async()=>({...parsed,state:talk100})},ss);f.reset({restore:true});
  await f.submit('100만원으로 바꿀게요');
  assert.deepEqual(f.state.restoredCurrent,{product_code:101,changes:[],selection_state:talk});
});
test('saving a quote chosen under old conditions keeps the latest conversation conditions',async()=>{
  const ss=storage();let next=talk,sent=null;
  const f=keep({parse:async()=>({...parsed,state:next}),saveQuote:async p=>{sent=p;return {ok:true,quote:{id:QID,product,state:p.state,saved_at:'2026-10-11T09:00:00+00:00'}};}},ss);f.reset();
  await f.submit('150만원 게임용');f.select(0);next=talk100;await f.submit('100만원으로 바꿀게요');
  await f.save();
  assert.equal(f.state.saveState,'saved');assert.deepEqual(sent.state,talk);
  assert.deepEqual(f.state.talk,talk100);assert.deepEqual(f.state.selectionState,talk);
});
test('a 409 on save re-checks today\'s price for the same product and lets the customer save again',async()=>{
  const ss=storage();let price=1430000,saves=[];
  const f=keep({recommend:async()=>({...reco,card_sets:[{kind:'sold',usage:'게임',items:[{...product,price}]}]}),
    saveQuote:async p=>{saves.push(p.expected_price);if(p.expected_price!==price)throw Object.assign(new Error('금액이 바뀌었어요.'),{status:409});
      return {ok:true,quote:{id:QID,product:{...product,price},state:p.state,saved_at:'2026-10-11T09:00:00+00:00'}};}},ss);f.reset();
  await f.submit('150만원 게임용');f.select(0);
  price=1450000;await f.save();
  assert.equal(f.state.needsRefresh,true);assert.equal(f.state.retry.kind,'reprice');assert.equal(f.state.selected.product_code,101);
  await f.save();assert.deepEqual(saves,[1430000],'blocked save does not resend the old price');
  await f.retry();
  assert.equal(f.state.needsRefresh,false);assert.equal(f.state.selected.price,1450000);assert.equal(f.state.saveState,'idle');
  assert.match(f.state.messages.at(-1).text,/1,430,000원에서 1,450,000원으로/);assert.match(f.state.messages.at(-1).text,/다시 눌러/);
  assert.equal(f.state.savedQuote,null,'re-check alone does not save');
  await f.save();assert.deepEqual(saves,[1430000,1450000]);assert.equal(f.state.saveState,'saved');
});
test('the price re-check re-applies changed parts through the server',async()=>{
  const ss=storage();let asked=null;
  const f=keep({buildQuote:async(s,code,changes)=>{asked={code,changes};return {ok:true,base_code:101,base_price:1430000,total:1490000,changes:[change]};}},ss);f.reset();
  await f.submit('150만원 게임용');f.select(0);
  f.state.selected={...f.state.selected,price:1480000,build:{base_price:1430000,changes:[change],warnings:[]}};f.state.needsRefresh=true;
  await f.reprice();
  assert.deepEqual(asked,{code:101,changes:[{ordinal:1,product_code:502}]});assert.equal(f.state.selected.price,1490000);assert.equal(f.state.needsRefresh,false);
});
test('a product gone after a 409 is not invented and stays blocked',async()=>{
  const ss=storage();
  const f=keep({},ss);f.reset();await f.submit('150만원 게임용');f.select(0);
  f.state.needsRefresh=true;f.state.selected={...f.state.selected,product_code:999};
  await f.reprice();
  assert.equal(f.state.needsRefresh,true);assert.match(f.state.messages.at(-1).text,/찾지 못했어요/);
});
test('the first screen keeps its existing 409 path (fresh recommendation)',async()=>{
  const f=make({prepareSave:async()=>BIND,saveQuote:async()=>{throw Object.assign(new Error('x'),{status:409});}},storage());f.reset();
  await f.submit('150만원 게임용');f.select(0);await f.save();assert.equal(f.state.retry.kind,'recommend');
});
// 코덱스 #145 검수 보완(2026-10-11): 보관 견적을 열어도 이미 권했거나 거절한 사실은 이어진다.
test('opening a saved quote keeps the offer and refusal flags but restarts the small-talk count',()=>{
  const f=keep({},storage());f.reset();
  const q={id:QID,product,state:talk,saved_at:'2026-10-11T09:00:00+00:00'};
  f.state.quotes=[q];f.state.chatFlow={smalltalk_turns:2,pc_offered:true,pc_declined:true};f.load(QID);
  assert.deepEqual(f.state.chatFlow,{pc_offered:true,pc_declined:true});
  f.state.chatFlow={smalltalk_turns:2};f.load(QID);assert.equal(f.state.chatFlow,null);
});
// 코덱스 PR147 검수 보완(2026-10-11): 가격 재확인에서 부품 재계산이 실패하면 고른 구성을 바꾸지 않는다.
test('a failed parts re-calc during the price re-check keeps the chosen build and the lock',async()=>{
  const ss=storage();let mode='throw';const saves=[];
  const f=keep({buildQuote:async()=>{if(mode==='throw')throw Object.assign(new Error('잠시 후'),{status:503});
      if(mode==='partial')return {ok:true,base_code:101,base_price:1430000,total:1430000,changes:[]};
      return {ok:true,base_code:101,base_price:1430000,total:1490000,changes:[change]};},
    saveQuote:async p=>{saves.push(p);throw new Error('no');}},ss);f.reset();
  await f.submit('150만원 게임용');f.select(0);
  const chosen={...f.state.selected,price:1480000,build:{base_price:1430000,changes:[change],warnings:[]}};
  f.state.selected=JSON.parse(JSON.stringify(chosen));f.state.needsRefresh=true;
  for(const m of ['throw','partial']){
    mode=m;await f.reprice();
    assert.deepEqual(f.state.selected,chosen,m+': chosen build untouched');
    assert.equal(f.state.needsRefresh,true,m+': still locked');assert.equal(f.state.retry.kind,'reprice');
    assert.match(f.state.error.message,/고른 구성을 그대로 두었어요/);
    await f.save();assert.equal(saves.length,0,m+': no save while unresolved');
  }
  mode='ok';await f.retry();
  assert.equal(f.state.needsRefresh,false);assert.equal(f.state.selected.price,1490000);
  assert.deepEqual(f.state.selected.build.changes,[change]);
});
// 코덱스 PR147 검수 보완(2026-10-11): 최신 조건 조회가 실패해도 고를 때 조건으로 고른 견적은 복원한다.
test('a failed latest-condition lookup still restores the quote from its own conditions',async()=>{
  const ss=storage();seed(ss,{product_code:101,changes:[],selection_state:talk});
  const asked=[];
  const f=keep({recommend:async s=>{asked.push(s.budget_won);if(s.budget_won===1000000)throw Object.assign(new Error('잠시 후'),{status:503});return reco;}},ss);
  f.reset({restore:true});f.state.talk=talk100;
  await f.resume();
  assert.deepEqual(asked,[1000000,1500000]);
  assert.equal(f.state.selected.product_code,101);assert.deepEqual(f.state.selectionState,talk);assert.deepEqual(f.state.talk,talk100);
  assert.equal(f.state.restoredCurrent,null);
  assert.equal(f.state.retry.kind,'recommend','the latest-condition failure is reported on its own');
  assert.match(f.state.messages.at(-1).text,/다시 불러왔어요/);
});
// 2026-10-12 카드 검수: 대화 화면에서 4K 영상 PC(글에서 읽은 추천 조건 wants)를 고르고 「부품 바꾸기」로 옛 화면에
// 가면, 옛 화면이 wants 없이 추천을 다시 받아 다른 PC 만 보여 주고 고른 PC 를 못 찾았다.
const otherReco={...reco,card_sets:[{kind:'sold',usage:'영상',items:[{...product,product_code:202,name:'다른 PC'}]}]};
const uhdOnly=async(s,o,extra)=>extra&&extra.wants&&extra.wants.uhd===true?reco:otherReco;
test('resume sends the recommendation wants restored from the conversation and finds the chosen PC',async()=>{
  const ss=storage();ss.setItem(CONVERSATION_KEY,JSON.stringify({version:1,saved_at:Date.now(),talk,wants:{uhd:true},chat_flow:null,history:[],messages:[],current:{product_code:101,changes:[],selection_state:talk,selection_wants:{uhd:true}}}));
  const f=make({recommend:uhdOnly},ss);f.reset({restore:true});assert.deepEqual(f.state.wants,{uhd:true});await f.resume();
  assert.equal(f.state.screen,'detail');assert.equal(f.state.selected.product_code,101);
  assert.deepEqual(stored(ss),{product_code:101,changes:[],selection_state:talk,selection_wants:{uhd:true}});
});
test('the lookup for the chosen PC itself carries the wants it was chosen with',async()=>{
  const ss=storage();seed(ss,{product_code:101,changes:[],selection_state:talk,selection_wants:{uhd:true}});
  const f=make({recommend:uhdOnly},ss);f.reset({restore:true});await f.resume();
  assert.equal(f.state.selected.product_code,101);assert.doesNotMatch(f.state.messages.at(-1).text,/찾지 못했어요/);
});
test('selecting a card keeps the wants of that recommendation in the stored conversation',()=>{
  const ss=storage();const f=make({},ss);f.reset();
  f.state.talk=talk;f.state.wants={uhd:true,min_ram_gb:32};f.state.groups=[{products:[{...product,index:0}]}];f.select(0);
  const rec=JSON.parse(ss.getItem(CONVERSATION_KEY));assert.deepEqual(rec.wants,{uhd:true,min_ram_gb:32});
  assert.deepEqual(rec.current.selection_wants,{uhd:true,min_ram_gb:32});
});
// 2026-10-12 카드 검수 X3: 상세↔대화를 오갈 때마다 고객이 말하지 않았는데 같은 다음 질문과 「새로고침 전에 보던…」 안내가 쌓였다.
test('going back and forth between pages does not pile up the same follow-up question or notice',async()=>{
  const ss=storage();const ask='더 싼 PC나 더 높은 사양도 보여 드릴까요? 아래에서 골라 주세요.';
  ss.setItem(CONVERSATION_KEY,JSON.stringify({version:1,saved_at:Date.now(),talk,chat_flow:null,history:[],
    messages:[{who:'user',text:'150만원 게임용'},{who:'ai',text:ask}],current:{product_code:101,changes:[]}}));
  const api={recommend:async()=>({...reco,talk_notes:[ask],choices:[{id:'cheaper',label:'더 싼 PC',enabled:true}]})};
  for(let trip=0;trip<3;trip++){const f=make(api,ss);f.reset({restore:true});await f.resume();assert.equal(f.state.selected.product_code,101);}
  const texts=JSON.parse(ss.getItem(CONVERSATION_KEY)).messages.map(m=>m.text);
  assert.equal(texts.filter(t=>t===ask).length,1);
  assert.equal(texts.filter(t=>/새로고침 전에 보던/.test(t)).length,1);
  assert.equal(texts.filter(t=>t==='150만원 게임용').length,1);
});
