// 코덱스 PR138 검수 보완(2026-10-11): 새로고침 뒤 보던 견적을 다시 열기 · 일반/구매 문의 성격 구분 · 보관 전 가림 순서.
const test=require('node:test'),assert=require('node:assert/strict');
const {createFlow,CONVERSATION_KEY,conversationSnapshot}=require('../live-flow.js');
const ID='11111111-1111-4111-8111-111111111111';
const talk={usages:['게임'],budget_won:1500000,budget_bound:'이하'};
const product={product_code:101,name:'검증용 PC',price:1430000,price_src:'등록 판매가',spec:{cpu:'CPU',gpu:'GPU',ram_gb:32,ssd_gb:1024},reasons:['조건에 맞는 등록 상품'],tag:'추천'};
const reco={ok:true,card_sets:[{kind:'sold',usage:'게임',items:[product,{...product,product_code:102,name:'대안 PC'}]}],needs:[],assumed:[]};
const parsed={ok:true,state:talk,chat_flow:{step:2},answer:'',reply:'찾아볼게요.',pc_related:true,missing:[]};
const change={ordinal:1,slot:'RAM',label:'메모리',quantity:1,before:{product_code:501,name:'램 16GB',price:60000},after:{product_code:502,name:'램 32GB',price:110000},delta:50000};
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
  assert.deepEqual(stored(ss),{product_code:101,changes:[]});
});
test('resume re-applies changed parts through the server quote',async()=>{
  const ss=storage();seed(ss,{product_code:101,changes:[{ordinal:1,product_code:502}]});let asked=null;
  const f=make({buildQuote:async(s,code,changes)=>{asked={code,changes};return {ok:true,base_code:101,base_price:1430000,total:1480000,changes:[change]};}},ss);
  f.reset({restore:true});await f.resume();
  assert.deepEqual(asked,{code:101,changes:[{ordinal:1,product_code:502}]});
  assert.equal(f.state.selected.price,1480000);assert.match(f.state.messages.at(-1).text,/바꿨던 부품도 다시 적용/);
  assert.deepEqual(stored(ss),{product_code:101,changes:[{ordinal:1,product_code:502}]});
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
  assert.match(f.state.messages.at(-1).text,/상품번호 999.*추천에 없어요/);
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
  assert.match(app,/state\.restoredCurrent&&state\.talk\)void flow\.resume\(\)/);
});
