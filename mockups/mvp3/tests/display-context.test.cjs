'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {createFlow}=require('../live-flow.js');
async function sent(state,options={}){
  const calls=[],storage={getItem:()=>null,setItem(){},removeItem(){}};
  const flow=createFlow({parse:async p=>{calls.push(p);throw Error('isolated fixture');}},
    {sessionStorage:storage,...options});
  Object.assign(flow.state,state);await flow.submit('이 PC의 부품을 설명해 주세요');
  assert.equal(calls.length,1);return calls[0];
}
test('currently visible recommendation identifiers keep repeated card positions and contain no display claims',async()=>{
  const p=await sent({screen:'results',groups:[{products:[{product_code:7,name:'PRIVATE_TITLE',price:123},{product_code:7},{product_code:8},{product_code:9},{product_code:10},{product_code:'11'}]}],contact:{phone:'PRIVATE_PHONE'}});
  assert.deepEqual(p.display_context,{screen:'results',cards:[{product_code:7},{product_code:7},{product_code:8},{product_code:9},{product_code:10}],selected:null,source:'recommendation'});
  assert.doesNotMatch(JSON.stringify(p),/PRIVATE_TITLE|PRIVATE_PHONE|123/);
});
test('loaded saved quote retains an explicit selection even when conversation history is empty',async()=>{
  const p=await sent({screen:'final',history:[],selected:{product_code:12,name:'SAVED_PRIVATE',price:999},savedQuote:{product:{product_code:12},quote_id:'PRIVATE_QUOTE'}});
  assert.deepEqual(p.display_context,{screen:'final',cards:[],selected:{product_code:12},source:'saved_quote'});
  assert.deepEqual(p.history,[]);assert.doesNotMatch(JSON.stringify(p),/SAVED_PRIVATE|PRIVATE_QUOTE|999/);
});
test('current selection is separate from the real card order while changed parts are not sent as public facts',async()=>{
  const p=await sent({screen:'results',selected:{product_code:20,build:{changes:[{name:'PRIVATE_PART',price:1234}]}},groups:[{products:[{product_code:1},{product_code:2},{product_code:3}]}]}, {keepCurrent:true});
  assert.deepEqual(p.display_context,{screen:'results',cards:[{product_code:1},{product_code:2},{product_code:3}],selected:{product_code:20},source:'custom_build'});
  assert.doesNotMatch(JSON.stringify(p),/PRIVATE_PART|1234/);
});
test('hidden prior cards are not claimed as the visible welcome or saved list',async()=>{
  for(const screen of ['welcome','saved']){
    const p=await sent({screen,selected:{product_code:20},groups:[{products:[{product_code:1}]}]});
    assert.deepEqual(p.display_context,{screen,cards:[],selected:null,source:'recommendation'});
  }
});
test('invalid identifiers and a changed saved selection never claim the previous quote',async()=>{
  const p=await sent({screen:'detail',selected:{product_code:30},savedQuote:{product:{product_code:12}},groups:[{products:[{product_code:-1},{product_code:Number.MAX_SAFE_INTEGER+1}]}]});
  assert.deepEqual(p.display_context,{screen:'detail',cards:[],selected:{product_code:30},source:'recommendation'});
});
test('home curated cards carry identifiers only, in actual displayed order',async()=>{
  const p=await sent({screen:'welcome'},{getDisplayCards:()=>[{configuration_id:'A-03',title:'PRIVATE_TITLE',price:456},{configuration_id:'A-01'},{configuration_id:'A-03'},{configuration_id:'../../bad'}]});
  assert.deepEqual(p.display_context,{screen:'welcome',cards:[{configuration_id:'A-03'},{configuration_id:'A-01'},{configuration_id:'A-03'}],selected:null,source:'new_pcs'});
  assert.doesNotMatch(JSON.stringify(p),/PRIVATE_TITLE|456|\.\.\//);
});
test('mixed result cards keep their real group order, with at most six references',async()=>{
  const p=await sent({screen:'results',groups:[{products:[{product_code:1},{product_code:2}],custom:[{configuration_id:'A-01'}]},{products:[{product_code:3},{product_code:4}],custom:[{configuration_id:'A-02'},{configuration_id:'A-03'}]}]});
  assert.deepEqual(p.display_context.cards,[{product_code:1},{product_code:2},{configuration_id:'A-01'},{product_code:3},{product_code:4},{configuration_id:'A-02'}]);
  assert.equal(p.display_context.cards_truncated,true);
});
test('a repeated PC in different groups retains the third position instead of shifting the following card',async()=>{
  const p=await sent({screen:'results',groups:[{products:[{product_code:1},{product_code:2}]},{products:[{product_code:2},{product_code:3}]}]});
  assert.deepEqual(p.display_context.cards,[{product_code:1},{product_code:2},{product_code:2},{product_code:3}]);
  assert.equal(p.display_context.cards_truncated,undefined);
});
test('talk screen keeps sending the right-panel cards after a saved quote is loaded (2026-10-16 「오른쪽 화면에 뜬 세가지 PC」)',async()=>{
  const p=await sent({screen:'final',history:[],selected:{product_code:12},savedQuote:{product:{product_code:12}},groups:[{products:[{product_code:1},{product_code:2},{product_code:3}]}]},{keepCurrent:true});
  assert.deepEqual(p.display_context,{screen:'final',cards:[{product_code:1},{product_code:2},{product_code:3}],selected:{product_code:12},source:'saved_quote'});
});
test('talk screen restored after refresh names the PC it was showing',async()=>{
  const p=await sent({screen:'results',restoredCurrent:{product_code:44},groups:[{products:[{product_code:1}]}]},{keepCurrent:true});
  assert.deepEqual(p.display_context.selected,{product_code:44});
});
