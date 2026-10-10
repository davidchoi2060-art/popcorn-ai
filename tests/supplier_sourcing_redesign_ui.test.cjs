const test=require('node:test');
const assert=require('node:assert/strict');
const {uiStage,replyEdited}=require('../mockups/shared/admin2/sourcing-new.js');
const p={quotes:[{quote_id:1,status:'회신',price:92000},{quote_id:2,status:'요청',price:null}]};
test('confirmation screen requires a still-valid replied quote; new requests remain a separate flow',()=>{
 assert.equal(uiStage({quotes:[]},{quote:null},'confirm'),'request');
 assert.equal(uiStage(p,{quote:null},'confirm'),'compare');
 assert.equal(uiStage(p,{quote:2},'confirm'),'compare');
 assert.equal(uiStage(p,{quote:1},'confirm'),'confirm');
 for(const changed of [{quote_id:1,status:'확정',price:92000},{quote_id:1,status:'회신',price:0},{quote_id:1,status:'회신',price:'not-a-price'}])assert.equal(uiStage({quotes:[changed]},{quote:1},'confirm'),'compare');
 assert.equal(uiStage(p,{quote:1},'request'),'compare');
});
test('reply leave guard treats price or memo edits as unsaved and handles server numeric/null values',()=>{
 const baseline={price:92000,memo:null};
 assert.equal(replyEdited({price:'92000',memo:''},baseline),false);
 assert.equal(replyEdited({price:'93000',memo:''},baseline),true);
 assert.equal(replyEdited({price:'92000',memo:'전화 회신'},baseline),true);
 assert.equal(replyEdited({price:'',memo:''},{price:null,memo:null}),false);
 assert.equal(replyEdited({price:'',memo:''},baseline),true);
});
