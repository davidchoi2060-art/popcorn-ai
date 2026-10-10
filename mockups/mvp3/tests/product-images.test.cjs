'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),{webcrypto}=require('node:crypto');
const {JSDOM,VirtualConsole}=require('jsdom');
const base=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(base,n),'utf8');
const NOTICE='AI 조립 예시 이미지 · 실제 출고 외형과 다를 수 있음';
const URL='/api/customer/products/113836/representative-image';
const available={state:'available',kind:'ai_assembly_example',url:URL,notice:NOTICE};
const product={product_code:113836,name:'CODE/MOCK <PC>',price:900000,price_src:'현재 판매가',spec:{cpu:'CPU'},reasons:['사무용'],over_budget:false,stock:0,image_url:'https://untrusted.invalid/case.png'};
const qid='22222222-2222-4222-8222-222222222222';
const clone=v=>JSON.parse(JSON.stringify(v));
const tick=()=>new Promise(r=>setImmediate(r));
async function until(check){for(let n=0;n<50;n++){if(check())return;await tick();}throw Error('render did not settle');}
function harness({saved=false,item={...product,photo:available},groups=null,quoteItem=item,talkState={usages:['사무용'],budget_won:1500000}}={}){
  const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read('index.html'),{url:'https://qa.invalid/mvp3/#'+(saved?'saved':'welcome'),runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.TextEncoder=TextEncoder;
  Object.defineProperty(w,'crypto',{value:webcrypto});w.localStorage.setItem('popcorn-mvp3-guest-access-v1','a'.repeat(64));
  w.eval(read('live-model.js'));w.eval(read('api-client.js'));
  const response={ok:true,card_sets:groups||[{kind:'sold',usage:'사무용',items:[item]}]};
  const quote={id:qid,product:quoteItem,state:{usages:['사무용']},saved_at:'2026-10-08T00:00:00Z'};
  const before=clone(w.MVP3LiveModel.recommendations(response)),original=clone(response);
  w.MVP3Api=w.MVP3Api.createClient({storage:w.localStorage,cryptoImpl:webcrypto,fetchImpl:async(url,options)=>{
    calls.push({url,method:options.method});
    const data=url==='/api/talk/parse'?{ok:true,state:talkState,history:[],missing:[]}:url==='/api/grid/recommend'?response:{ok:true,quotes:[quote],has_more:false};
    return {ok:true,status:200,json:async()=>data,headers:{get:()=>null}};
  }});w.eval(read('live-flow.js'));
  const create=w.MVP3LiveFlow.createFlow;let flow;
  w.MVP3LiveFlow.createFlow=(...args)=>{flow=create(...args);return flow;};
  w.eval(read('app.js'));
  return {dom,w,flow,calls,errors,response,original,before,quote,click:s=>w.document.querySelector(s).click(),close:()=>dom.window.close()};
}
async function recommend(h){const input=h.w.document.querySelector('#request');input.value='CODE/MOCK 사무용';input.dispatchEvent(new h.w.Event('input',{bubbles:true}));h.w.document.querySelector('#chat-form').dispatchEvent(new h.w.Event('submit',{bubbles:true,cancelable:true}));await until(()=>h.w.document.querySelector('.live-product-card'));}
function business(result){const out=clone(result);for(const g of out.groups)for(const p of g.products)delete p.photo;return out;}

test('generated-media: exact server route and canonical AI notice survive normalization, card and detail',async()=>{
  assert.ok(fs.readFileSync(path.resolve(base,'../../api/pc_media.py'),'utf8').includes("NOTICE='"+NOTICE+"'"));
  for(const url of [URL,'https://qa.invalid'+URL]){
    const h=harness({item:{...product,photo:{...available,url,job_id:'private',bucket:'private'}}});try{
      await recommend(h);const img=h.w.document.querySelector('[data-product-image]');assert.equal(img.getAttribute('src'),url);assert.equal(img.alt,'CODE/MOCK <PC> · AI 조립 예시');
      assert.equal(h.w.document.querySelector('figcaption').textContent,NOTICE);assert.equal(h.w.document.querySelector('figcaption').hidden,false);
      const normalized=h.w.MVP3LiveModel.recommendations(h.response);assert.deepEqual(business(normalized),h.before);assert.deepEqual(Object.keys(normalized.groups[0].products[0].photo).sort(),['kind','notice','state','url']);
      h.click('[data-action=detail]');assert.equal(h.w.document.querySelector('[data-product-image]').getAttribute('src'),url);assert.equal(h.calls.length,2);assert.deepEqual(h.errors,[]);
      assert.equal(h.w.document.querySelector('[src*="product-images"]'),null);assert.deepEqual(h.response,h.original);
    }finally{h.close();}
  }
});
test('generated-media: missing/unavailable/temporary states request no image and preserve the product',async()=>{
  for(const [photo,label] of [[undefined,'정보 없음'],[null,'정보 없음'],[{state:'unavailable',url:URL},'정보 없음'],[{state:'temporarily_unavailable',url:URL},'이미지를 불러오지 못했습니다']]){
    const h=harness({item:{...product,photo}});try{await recommend(h);assert.equal(h.w.document.querySelector('[data-product-image]'),null);assert.equal(h.w.document.querySelector('.live-product-image-status').textContent,label);assert.match(h.w.document.querySelector('.live-product-card').textContent,/900,000원/);assert.deepEqual(business(h.w.MVP3LiveModel.recommendations(h.response)),h.before);assert.equal(h.calls.length,2);}finally{h.close();}
  }
});
test('generated-media: external, executable, wrong-SKU, admin, cloud, CASE, query and noncanonical URLs are rejected',async()=>{
  const bad=[null,42,'https://external.invalid'+URL,'javascript:alert(1)','data:image/png;base64,AA','//qa.invalid'+URL,'/api/customer/products/113835/representative-image','/api/admin/pc-configurations/1/media','https://storage.googleapis.com/bucket/representative.png','/api/product-images/129551/detail',URL+'?v=1',URL+'#a','/mvp3/..'+URL,'/api/customer/products/0113836/representative-image','https://user@qa.invalid'+URL,'https://qa.invalid:444'+URL];
  for(const url of bad){const h=harness({item:{...product,photo:{...available,url}}});try{await recommend(h);assert.equal(h.w.document.querySelector('[data-product-image]'),null,String(url));assert.equal(h.w.document.querySelector('.live-product-image-status').textContent,'정보 없음');assert.equal(h.calls.length,2);}finally{h.close();}}
});
test('generated-media: original-photo kind, invalid state, altered/missing notice and unsafe code do not claim an AI image',async()=>{
  for(const item of [{...product,photo:{...available,kind:'registered_product_photo'}},{...product,photo:{...available,state:'unknown'}},{...product,photo:{...available,notice:''}},{...product,photo:{...available,notice:'실제 조립 사진'}},{...product,product_code:Number.MAX_SAFE_INTEGER+1,photo:available}]){
    const h=harness({item});try{await recommend(h);assert.equal(h.w.document.querySelector('[data-product-image]'),null);assert.equal(h.w.document.querySelector('figcaption'),null);assert.match(h.w.document.querySelector('.live-product-card').textContent,/정보 없음/);}finally{h.close();}
  }
});
test('generated-media: img error retains AI notice, price, spec, selection and API call count; unrelated icon is unaffected',async()=>{
  const h=harness();try{await recommend(h);const card=h.w.document.querySelector('.live-product-card'),img=card.querySelector('[data-product-image]');
    const price=card.querySelector('.price').textContent,spec=card.querySelector('.live-card-spec').textContent,calls=clone(h.calls);
    img.dispatchEvent(new h.w.Event('error'));assert.equal(img.hidden,true);assert.equal(card.querySelector('[data-product-image-status]').hidden,false);assert.equal(card.querySelector('[data-product-image-status]').textContent,'이미지를 불러오지 못했습니다');assert.equal(card.querySelector('figcaption').textContent,NOTICE);assert.equal(card.querySelector('figcaption').hidden,false);
    assert.equal(card.querySelector('.price').textContent,price);assert.equal(card.querySelector('.live-card-spec').textContent,spec);assert.deepEqual(h.calls,calls);
    const icon=h.w.document.querySelector('.brand-mark');icon.dispatchEvent(new h.w.Event('error'));assert.equal(icon.hidden,false);
    h.click('[data-action=detail]');assert.equal(h.w.document.querySelector('[data-product-image]').getAttribute('src'),URL);assert.match(h.w.document.querySelector('.live-summary').textContent,/900,000원/);
    const detail=h.w.document.querySelector('[data-product-image]');detail.dispatchEvent(new h.w.Event('load'));assert.equal(detail.parentElement.dataset.imageState,'loaded');assert.equal(detail.parentElement.querySelector('[data-product-image-status]').hidden,true);assert.equal(detail.parentElement.querySelector('figcaption').hidden,false);assert.deepEqual(h.calls,calls);
  }finally{h.close();}
});
test('generated-media: saved quote consumes only its own photo and retains saved price/date without original-photo wording',async()=>{
  for(const photo of [available,undefined,{state:'temporarily_unavailable',url:null}]){
    const h=harness({saved:true,quoteItem:{...product,photo}});try{await until(()=>h.w.document.querySelector('[data-action=load]'));const card=h.w.document.querySelector('.live-product-card');assert.match(card.textContent,/900,000원/);h.click('[data-action=load]');const summary=h.w.document.querySelector('.live-summary');assert.ok(summary.textContent.includes("금액과 상품 기록은 보관 시점 기준입니다. 부품 구성과 사진은 조회 시점의 공개 상태를 따릅니다."));assert.equal(h.flow.state.messages.at(-1).text,"이 브라우저에서 보관한 "+h.quote.product.name+"을 불러왔어요. 금액과 상품 기록은 보관 시점 기준입니다. 부품 구성과 사진은 조회 시점의 공개 상태를 따릅니다.");assert.doesNotMatch(summary.textContent,/현재 등록본|실제 조립 사진/);assert.equal(!!summary.querySelector('[data-product-image]'),photo===available);if(photo===available)assert.equal(summary.querySelector('figcaption').textContent,NOTICE);assert.ok(h.calls.every(c=>c.method==='GET'));assert.equal(h.w.MVP3LiveModel.quote(h.quote).saved_at,h.quote.saved_at);}finally{h.close();}
  }
});
test('generated-media: invalid products and unsupported groups do not shift photo binding or change recommendation eligibility',async()=>{
  const second={...product,product_code:113835,name:'Second PC',photo:{state:'temporarily_unavailable',url:null}};
  const groups=[{kind:'estimate',items:[product]},{kind:'sold',usage:'사무용',items:[{product_code:113800,photo:available},{...product,photo:available},second]}];
  const h=harness({groups});try{await recommend(h);const normalized=h.w.MVP3LiveModel.recommendations(h.response);assert.deepEqual(business(normalized),h.before);assert.equal(normalized.groups[0].products[0].photo.url,URL);assert.equal(normalized.groups[0].products[1].photo.state,'temporarily_unavailable');assert.equal(h.w.document.querySelectorAll('.live-product-card').length,2);assert.equal(h.w.document.querySelectorAll('[data-product-image]').length,1);assert.equal(normalized.unsupported,true);}finally{h.close();}
});

// Integration-only fixtures. These describe CODE/MOCK data, not current offers or inventory.
function publicBom(code=113836){return {product_code:code,configuration_id:'CODE-MOCK-CONFIG',revision:1,offer_id:'P'+code,
  description:{title:'CODE/MOCK 부품 구성을 확인하세요',intro:'공개 등록 사양을 함께 확인하는 검사 구성입니다.',scene:null,benefits:[],checks:[],faq:[]},
  parts:[{ordinal:0,slot:'CPU',quantity:1,pseudo:false,name:'CODE/MOCK CPU',description:'등록 CPU 설명',specs:[{label:'등록 사양',value:'Fixture CPU'}]},
    {ordinal:1,slot:'GPU',quantity:1,pseudo:false,name:'CODE/MOCK GPU',description:'등록 GPU 설명',specs:[{label:'그래픽 메모리',value:'Fixture 8GB'}]}],
  price:{state:'unknown',amount:null,checked_at:null,observed_date:null,model:null},stock:{state:'unknown',checked_at:null},
  compatibility:{document_state:'unknown',public_summary:null,assembly_state:'unknown'},photo:{state:'unresolved',url:null},
  customer_conditions:Object.fromEntries(['os','keyboard','mouse','monitor','warranty'].map(k=>[k,{state:'unknown',detail:'',months:null,needs_reconfirmation:false,customer_statement:'구매 전에 확인해 주세요.'}]))};}
const gameContext={game_name:'CODE/MOCK 게임',why_this_pc:'같은 게임 문맥의 안내',caution:'실제 게임 성능 측정값 아님',source:{kind:'game_customer_copy',fields:['why_this_pc'],url:null}};

test('approved-ui: zero/one/two sold results preserve cardinality, ordering and supplied prices',async()=>{
  for(const count of [0,1,2]){
    const items=[{...product,name:'CODE/MOCK A',price:820000,photo:available},{...product,product_code:113835,name:'CODE/MOCK B',price:930000,photo:{state:'unavailable'},tag:'예산 안 최고 수준'}].slice(0,count);
    const h=harness({groups:[{kind:'sold',usage:'CODE/MOCK',items}]});try{
      await h.flow.submit('CODE/MOCK 결과 수 검사');assert.equal(h.flow.state.screen,'results');
      const cards=[...h.w.document.querySelectorAll('.live-product-card')];assert.equal(cards.length,count);
      assert.deepEqual(clone(h.flow.state.groups[0].products.map(p=>p.product_code)),items.map(p=>p.product_code));
      cards.forEach((card,n)=>{assert.match(card.textContent,new RegExp(items[n].price.toLocaleString('ko-KR')+'원'));assert.equal(card.querySelector('[data-action=detail]').dataset.id,String(n));});
      if(count===0){assert.match(h.w.document.querySelector('#view').textContent,/추천 상품이 없어요/);assert.equal(h.w.document.querySelector('[data-action=detail]'),null);}
      if(count===2){assert.match(cards[1].querySelector('.live-price-difference').textContent,/110,000원 높아요/);assert.equal(cards[0].querySelector('.live-price-difference'),null);}
      assert.equal(h.calls.length,2);assert.deepEqual(h.errors,[]);
    }finally{h.close();}
  }
});
test('approved-ui: selected BOM, photo, game context and native GPU disclosure survive rerender and final confirmation',async()=>{
  const item={...product,name:'CODE/MOCK 게임 PC',reasons:['고객 추천 이유 하나','고객 추천 이유 둘'],photo:available,public_configuration:publicBom()};
  const talkState={usages:['게임'],budget_won:1500000,game:{names:['CODE/MOCK 게임'],resolution:'1080p'}};
  const h=harness({item,talkState,groups:[{kind:'sold',usage_grid:'게임',usage:'게임',game_context:gameContext,items:[item]}]});try{
    await h.flow.submit('CODE/MOCK 같은 문맥');h.click('[data-action=detail]');
    const doc=h.w.document;assert.equal(doc.querySelectorAll('tr[data-part^="bom-"]').length,2);assert.match(doc.querySelector('#view').textContent,/같은 게임 문맥의 안내/);
    assert.deepEqual(clone(h.flow.state.selectionState),talkState);assert.match(doc.querySelector('#view').textContent,/고객 추천 이유 하나/);assert.match(doc.querySelector('#view').textContent,/고객 추천 이유 둘/);
    const selected=clone(h.flow.state.selected),calls=clone(h.calls);doc.querySelector('details[data-detail="bom-1"]').open=true;h.flow.emit();
    assert.equal(doc.querySelector('details[data-detail="bom-1"]').open,true);assert.match(doc.querySelector('tr[data-part="bom-1"]').textContent,/Fixture 8GB/);
    assert.ok([...doc.querySelectorAll('.public-bom [data-action=unavailable]')].every(b=>b.disabled));assert.equal(doc.querySelectorAll('.public-bom .final-part-price').length,2);
    assert.ok([...doc.querySelectorAll('.public-bom .final-part-price')].every(e=>e.textContent==='미확인'));assert.match(doc.querySelector('.public-bom-photo').textContent,/정보 없음/);
    doc.querySelector('[data-product-image]').dispatchEvent(new h.w.Event('error'));assert.equal(doc.querySelector('figcaption').textContent,NOTICE);assert.equal(doc.querySelector('[data-product-image-status]').hidden,false);
    assert.deepEqual(clone(h.flow.state.selected),selected);assert.deepEqual(h.calls,calls);assert.match(doc.querySelector('#actions').textContent,/900,000원/);
    h.click('[data-action=final]');assert.equal(h.flow.state.screen,'final');assert.ok(doc.querySelector('.public-bom-information .live-explanation'));assert.equal(doc.querySelector('.public-bom-information').open,false);
    assert.equal(doc.querySelector('[data-product-image]').getAttribute('src'),URL);assert.deepEqual(h.calls,calls);assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});
test('approved-ui: same SKU in another usage and a loaded saved quote cannot inherit the prior game context',async()=>{
  const item={...product,photo:available,public_configuration:publicBom()};
  const h=harness({item,groups:[{kind:'sold',usage_grid:'게임',game_context:gameContext,items:[item]},{kind:'sold',usage_grid:'영상 편집',items:[item]}]});try{
    await h.flow.submit('CODE/MOCK 재선택');h.flow.select(0);assert.match(h.w.document.querySelector('#view').textContent,/같은 게임 문맥의 안내/);
    h.flow.navigate('results');h.flow.select(1);assert.doesNotMatch(h.w.document.querySelector('#view').textContent,/같은 게임 문맥의 안내/);
    h.flow.select(0);await h.flow.list();h.flow.load(qid);assert.equal(h.flow.state.screen,'final');assert.doesNotMatch(h.w.document.querySelector('#view').textContent,/같은 게임 문맥의 안내/);
    assert.match(h.w.document.querySelector('.live-summary').textContent,/보관 시점/);assert.equal(h.w.document.querySelectorAll('tr[data-part^="bom-"]').length,2);
    assert.equal(h.w.document.querySelector('figcaption').textContent,NOTICE);h.flow.reset();assert.equal(h.flow.state.selected,null);assert.equal(h.flow.state.groups.length,0);
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});
test('approved-ui: missing/rejected BOM preserves the complete-product fallback and valid photo binding',async()=>{
  for(const configuration of [undefined,{...publicBom(),product_code:113835}]){
    const h=harness({item:{...product,photo:available,public_configuration:configuration}});try{
      await recommend(h);h.click('[data-action=detail]');assert.equal(h.w.document.querySelectorAll('tr[data-part^="bom-"]').length,0);assert.ok(h.w.document.querySelector('tr[data-part=pc]'));
      assert.equal(h.w.document.querySelector('[data-product-image]').getAttribute('src'),URL);assert.match(h.w.document.querySelector('#actions').textContent,/900,000원/);
      h.click('[data-action=final]');assert.ok(h.w.document.querySelector('details[data-detail=spec] .live-explanation'));assert.equal(h.w.document.querySelector('details[data-detail=spec]').open,false);assert.equal(h.calls.length,2);
    }finally{h.close();}
  }
});
test('approved-ui: absent/different price basis and unknown prices do not create a comparison amount',async()=>{
  for(const second of [{...product,price_src:'다른 기준'},{...product,price:null},{...product,price_src:''}]){
    const h=harness({groups:[{kind:'sold',items:[{...product,photo:available},{...second,product_code:113835,photo:{state:'unavailable'}}]}]});try{
      await recommend(h);assert.equal(h.w.document.querySelector('.live-price-difference'),null);assert.equal(h.w.document.querySelectorAll('.live-product-card').length,2);
      if(second.price===null)assert.match(h.w.document.querySelectorAll('.live-product-card')[1].textContent,/금액 미확인/);assert.equal(h.calls.length,2);
    }finally{h.close();}
  }
});

test('every deployed landing start CTA invokes approved MVP3 destination in the real handler',()=>{
  const dom=new JSDOM(read('../mvp1/main-landing.html'),{runScripts:'outside-only'});try{
    const source=Array.from(dom.window.document.scripts).find(s=>s.textContent.includes('window.location.href')&&s.textContent.includes('[data-cta="start"]'))?.textContent;assert.ok(source);
    const location={href:''};new Function('document','window','setTimeout',source)(dom.window.document,{location},()=>{});
    dom.window.document.dispatchEvent(new dom.window.Event('DOMContentLoaded'));
    const starts=dom.window.document.querySelectorAll('[data-cta="start"]');assert.ok(starts.length>=5);
    for(const start of starts){location.href='';start.click();assert.equal(location.href,'/mvp3/');}
  }finally{dom.window.close();}
});
