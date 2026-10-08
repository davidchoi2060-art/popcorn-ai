'use strict';
// 보관 견적 표시 기준: 금액·상품 기록은 보관 시점, 사진·부품 구성(public_configuration)은 응답의 현재 공개 상태.
// GET 불러오기(load)와 POST 보관(performSave) 두 경로를 CODE/MOCK fixture 로만 확인한다(실 DB·실 POST 없음).
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),{webcrypto}=require('node:crypto');
const {JSDOM,VirtualConsole}=require('jsdom');
const base=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(base,n),'utf8');
const NOTICE='AI 조립 예시 이미지 · 실제 출고 외형과 다를 수 있음';
const URL='/api/customer/products/113836/representative-image';
const BASIS='금액과 상품 기록은 보관 시점 기준입니다. 부품 구성과 사진은 조회 시점의 공개 상태를 따릅니다.';
const EMPTY_BOM='부품 구성 정보는 아직 연결되지 않았어요.';
const available={state:'available',kind:'ai_assembly_example',url:URL,notice:NOTICE};
const qid='22222222-2222-4222-8222-222222222222';
const talk={usages:['사무용'],budget_won:1500000};
function publicBom(code=113836){return {product_code:code,configuration_id:'CODE-MOCK-CONFIG',revision:1,offer_id:'P'+code,
  description:{title:'CODE/MOCK 부품 구성을 확인하세요',intro:'공개 등록 사양을 함께 확인하는 검사 구성입니다.',scene:null,benefits:[],checks:[],faq:[]},
  parts:[{ordinal:0,slot:'CPU',quantity:1,pseudo:false,name:'CODE/MOCK CPU',description:'등록 CPU 설명',specs:[{label:'등록 사양',value:'Fixture CPU'}]},
    {ordinal:1,slot:'GPU',quantity:1,pseudo:false,name:'CODE/MOCK GPU',description:'등록 GPU 설명',specs:[{label:'그래픽 메모리',value:'Fixture 8GB'}]}],
  price:{state:'unknown',amount:null,checked_at:null,observed_date:null,model:null},stock:{state:'unknown',checked_at:null},
  compatibility:{document_state:'unknown',public_summary:null,assembly_state:'unknown'},photo:{state:'unresolved',url:null},
  customer_conditions:Object.fromEntries(['os','keyboard','mouse','monitor','warranty'].map(k=>[k,{state:'unknown',detail:'',months:null,needs_reconfirmation:false,customer_statement:'구매 전에 확인해 주세요.'}]))};}
// 보관 시점 기록: 가격 900,000원·SAVED CPU. 현재 추천 응답은 950,000원·CURRENT CPU 로 다르게 둔다.
const savedProduct={product_code:113836,name:'CODE/MOCK 보관 PC',price:900000,price_src:'보관 시점 판매가',spec:{cpu:'SAVED CPU'},reasons:['보관 이유'],over_budget:false,stock:0};
const currentProduct={...savedProduct,name:'CODE/MOCK 현재 PC',price:950000,spec:{cpu:'CURRENT CPU'},reasons:['현재 이유']};
const withdrawn=[[{state:'unavailable',url:URL},null],[undefined,undefined]];
const tick=()=>new Promise(r=>setImmediate(r));
async function until(check){for(let n=0;n<80;n++){if(check())return;await tick();}throw Error('render did not settle');}
function harness({hash='saved',quoteProduct=savedProduct,recommendItem=currentProduct,postProduct=null}={}){
  const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read('index.html'),{url:'https://qa.invalid/mvp3/#'+hash,runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.TextEncoder=TextEncoder;
  Object.defineProperty(w,'crypto',{value:webcrypto});w.localStorage.setItem('popcorn-mvp3-guest-access-v1','a'.repeat(64));
  w.eval(read('live-model.js'));w.eval(read('api-client.js'));
  const quote={id:qid,product:quoteProduct,state:talk,saved_at:'2026-10-08T00:00:00Z'};
  w.MVP3Api=w.MVP3Api.createClient({storage:w.localStorage,cryptoImpl:webcrypto,fetchImpl:async(url,options)=>{
    const body=options.body?JSON.parse(options.body):null;calls.push({url,method:options.method,body});
    let data;
    if(url==='/api/talk/parse')data={ok:true,state:talk,history:[],missing:[]};
    else if(url==='/api/grid/recommend')data={ok:true,card_sets:[{kind:'sold',usage:'사무용',items:[recommendItem]}]};
    else if(options.method==='POST'&&url==='/api/mvp3/saved-quotes')data={ok:true,quote:{id:qid,product:{...postProduct,product_code:body.product_code,price:body.expected_price},state:body.state,saved_at:'2026-10-08T01:00:00Z'}};
    else data={ok:true,quotes:hash==='saved'?[quote]:[],has_more:false};
    return {ok:true,status:200,json:async()=>data,headers:{get:()=>null}};
  }});w.eval(read('live-flow.js'));
  const create=w.MVP3LiveFlow.createFlow;let flow;
  w.MVP3LiveFlow.createFlow=(...args)=>{flow=create(...args);return flow;};
  w.eval(read('app.js'));
  return {w,doc:w.document,get flow(){return flow;},calls,errors,quote,click:s=>w.document.querySelector(s).click(),
    // 렌더 뒤 남은 타이머가 닫힌 문서를 만지지 않게 한 박자 기다린 뒤 닫는다.
    close:async()=>{await new Promise(r=>setTimeout(r,50));dom.window.close();}};
}
function finalView(h){return h.doc.querySelector('#view');}
function assertSavedBasis(h,{photo,bom}){
  const view=finalView(h),text=view.textContent;
  assert.equal(h.flow.state.screen,'final');assert.ok(h.flow.state.savedQuote);
  assert.ok(text.includes(BASIS),'saved/current basis notice');
  assert.match(text,/900,000원/);assert.doesNotMatch(text,/950,000원/);
  assert.equal(h.flow.state.selected.spec.cpu,'SAVED CPU');
  const img=view.querySelector('[data-product-image]');
  if(photo){assert.equal(img.getAttribute('src'),URL);assert.equal(view.querySelector('figcaption').textContent,NOTICE);}
  else{assert.equal(img,null);assert.match(text,/이미지 준비 중/);}
  if(bom){assert.ok(view.querySelector('.public-bom'),'public BOM section');assert.ok(!text.includes(EMPTY_BOM));assert.match(text,/CODE\/MOCK GPU/);}
  else{assert.ok(text.includes(EMPTY_BOM));assert.equal(view.querySelector('.public-bom'),null);assert.doesNotMatch(text,/CODE\/MOCK GPU/);}
  assert.deepEqual(h.errors,[]);
}
async function loadSaved(h){await until(()=>h.doc.querySelector('[data-action=load]'));h.click('[data-action=load]');await until(()=>h.flow.state.screen==='final');}
async function saveCurrent(h){
  await h.flow.submit('CODE/MOCK 사무용');await until(()=>h.doc.querySelector('[data-action=detail]'));
  h.click('[data-action=detail]');h.click('[data-action=final]');assert.equal(h.flow.state.screen,'final');
  h.click('[data-action=save]');await until(()=>h.flow.state.saveState==='saved'&&h.flow.phase!=='save'&&h.flow.state.phase===null);
}

test('saved-basis GET load: saved price/spec with current photo and public BOM plus basis notice',async()=>{
  const h=harness({quoteProduct:{...savedProduct,photo:available,public_configuration:publicBom()}});try{
    await loadSaved(h);assertSavedBasis(h,{photo:true,bom:true});
    assert.equal(h.flow.state.messages.at(-1).text,'이 브라우저에서 보관한 '+savedProduct.name+'을 불러왔어요. '+BASIS);
    assert.ok(h.calls.every(c=>c.method==='GET'));
  }finally{await h.close();}
});
test('saved-basis GET load: photo unavailable and public_configuration null/withdrawn fall back to 이미지 준비 중 and no BOM',async()=>{
  for(const [photo,configuration] of withdrawn){
    const h=harness({quoteProduct:{...savedProduct,photo,public_configuration:configuration}});try{
      await loadSaved(h);assertSavedBasis(h,{photo:false,bom:false});assert.ok(h.calls.every(c=>c.method==='GET'));
    }finally{await h.close();}
  }
});
test('saved-basis POST performSave: returned saved.product photo and BOM drive the final view with basis notice',async()=>{
  const h=harness({hash:'welcome',recommendItem:{...currentProduct,price:900000,photo:available,public_configuration:publicBom()},
    postProduct:{...savedProduct,photo:available,public_configuration:publicBom()}});try{
    await saveCurrent(h);assertSavedBasis(h,{photo:true,bom:true});
    const post=h.calls.filter(c=>c.method==='POST'&&c.url==='/api/mvp3/saved-quotes');assert.equal(post.length,1);assert.equal(post[0].body.expected_price,900000);
  }finally{await h.close();}
});
test('saved-basis POST performSave: unavailable photo and null/withdrawn BOM in saved.product override the recommendation view',async()=>{
  for(const [photo,configuration] of withdrawn){
    const h=harness({hash:'welcome',recommendItem:{...currentProduct,price:900000,photo:available,public_configuration:publicBom()},
      postProduct:{...savedProduct,photo,public_configuration:configuration}});try{
      await saveCurrent(h);assertSavedBasis(h,{photo:false,bom:false});
      assert.equal(h.calls.filter(c=>c.method==='POST'&&c.url==='/api/mvp3/saved-quotes').length,1);
    }finally{await h.close();}
  }
});
