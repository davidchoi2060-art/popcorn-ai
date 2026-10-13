// 2026-10-13 사장님: 대화 화면에서 「더 높은 사양」을 눌러 받은 카드의 「상세 보기」가 상세 대신 다른 추천 목록으로 갔다.
// 상세 화면(index.html)은 고른 PC 를 같은 조건으로 서버에 다시 물어 찾는데, 「더 싸게·더 높은 사양」 방향과 기준 카드를
// 빼고 물어서 기본 추천만 돌아왔다(개발 서버 재현: 사무용 → 더 높은 사양 3번 → 2,198,900원 PC, 방향 없이는 못 찾음).
// 고를 때 마지막 방향·기준 카드를 함께 기억하고(selection_query), 다시 찾을 때 함께 보낸다.
const test=require('node:test'),assert=require('node:assert/strict');
const {createFlow,CONVERSATION_KEY,validConversation}=require('../live-flow.js');
const ID='11111111-1111-4111-8111-111111111111';
const talk={usages:['사무용']};
const pc=(code,price,tag)=>({product_code:code,name:'PC '+code,price,price_src:'등록 판매가',spec:{cpu:'CPU',gpu:'GPU',ram_gb:16,ssd_gb:500},reasons:['사무용 쾌적'],tag});
const base={ok:true,card_sets:[{kind:'sold',usage:'사무용',items:[pc(101,892800,'추천 구성'),pc(102,1471000,'더 높은 사양')]}],needs:[],assumed:[],anchor_code:101,choices:[]};
const higher={ok:true,card_sets:[{kind:'sold',usage:'사무용',items:[pc(201,1533000,'추천 구성'),pc(202,2198900,'더 높은 사양')]}],needs:[],assumed:[],anchor_code:201,choices:[]};
const parsed={ok:true,state:talk,chat_flow:{step:2},answer:'',reply:'',pc_related:true,missing:[]};
function storage(){const map=new Map();return {getItem:k=>map.get(k)??null,setItem:(k,v)=>map.set(k,v),removeItem:k=>map.delete(k)};}
// 서버 흉내: 「더 높은 사양」 + 기준 카드 101 이면 높은 카드, 아니면 기본 추천.
function server(calls){return async(state,opts,extra={})=>{calls.push(extra);return extra.nav==='better'&&extra.anchor_code===101?higher:base;};}
function make(ss,calls){return createFlow({parse:async()=>parsed,recommend:server(calls),inquiryForm:async()=>({ok:true,topics:['기타'],consent_text:'동의'})},{uuid:()=>ID,sessionStorage:ss});}

test('a card picked after 「더 높은 사양」 reopens in detail on the other screen',async()=>{
  const ss=storage(),calls=[];
  const talkScreen=make(ss,calls);talkScreen.reset({restore:false});
  await talkScreen.submit('사무용 컴퓨터 찾아요');
  await talkScreen.explore('better','더 높은 사양');
  const pick=talkScreen.state.groups.flatMap(g=>g.products).find(p=>p.product_code===202);
  talkScreen.select(pick.index);
  const saved=JSON.parse(ss.getItem(CONVERSATION_KEY));
  assert.deepEqual(saved.current.selection_query,{nav:'better',anchor_code:101});
  assert.ok(validConversation(saved));

  // 상세 화면(index.html)이 같은 탭 보관에서 이어받는다.
  const detailCalls=[],detail=make(ss,detailCalls);detail.reset({restore:true});await detail.resume({arrived:true});
  assert.equal(detail.state.screen,'detail');
  assert.equal(detail.state.selected.product_code,202);
  assert.ok(detailCalls.some(x=>x.nav==='better'&&x.anchor_code===101),'re-query carries the direction and anchor');
  // 넘어온 것이지 새로고침이 아니다 -- 「새로고침 전에 보던」이라고 하지 않는다(2026-10-13 사장님).
  const last=detail.state.messages.at(-1).text;
  assert.match(last,/^고르신 PC 202 구성의 상세예요\. 금액은 지금 다시 확인한 값이에요\./);
  assert.doesNotMatch(last,/새로고침/);
});

test('a real refresh still says it reopened the earlier build',async()=>{
  const ss=storage(),calls=[];
  const f=make(ss,calls);f.reset({restore:false});await f.submit('사무용 컴퓨터 찾아요');
  f.select(f.state.groups.flatMap(g=>g.products).find(p=>p.product_code===101).index);
  const again=make(ss,[]);again.reset({restore:true});await again.resume();
  assert.match(again.state.messages.at(-1).text,/^새로고침 전에 보던 PC 101을 다시 불러왔어요\./);
});

test('a plain recommendation keeps no direction',async()=>{
  const ss=storage(),calls=[];
  const f=make(ss,calls);f.reset({restore:false});await f.submit('사무용 컴퓨터 찾아요');
  const pick=f.state.groups.flatMap(g=>g.products).find(p=>p.product_code===102);f.select(pick.index);
  assert.equal(JSON.parse(ss.getItem(CONVERSATION_KEY)).current.selection_query,undefined);
});

test('a malformed stored direction is rejected, not sent',()=>{
  const rec={version:1,saved_at:Date.now(),talk,chat_flow:null,history:[],messages:[],current:{product_code:202,changes:[],selection_query:{nav:'sideways',anchor_code:101}}};
  assert.equal(validConversation(rec),false);
});
