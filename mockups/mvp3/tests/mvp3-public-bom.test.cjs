'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const M=require('../live-model.js');
// CODE/MOCK DTO reconstructed from test_customer_sold_offer_read's CPU/MB fixture.
// SERVICE follows its pseudo test. SSD variants below test multiplicity, not actual inventory.
function fixture(){return {product_code:99413,configuration_id:'P10',revision:1,offer_id:'P99413',
  description:{title:'검증 PC',intro:'근거 설명',scene:null,benefits:[],checks:[],faq:[]},
  parts:[{ordinal:0,slot:'CPU',quantity:1,pseudo:false,name:'CPU',description:'실제 등록 역할 11',specs:[{label:'등록 사실',value:'AM4'}]},
    {ordinal:1,slot:'MB',quantity:1,pseudo:false,name:'MB',description:'실제 등록 역할 12',specs:[{label:'등록 사실',value:'AM4'}]},
    {ordinal:8,slot:'SERVICE',quantity:1,pseudo:true,name:null,description:null,specs:[]}],
  price:{state:'unknown',amount:null,checked_at:null,observed_date:null,model:null},stock:{state:'unknown',checked_at:null},
  compatibility:{document_state:'pass',public_summary:null,assembly_state:'unknown'},photo:{state:'unresolved',url:null},
  customer_conditions:Object.fromEntries(['os','keyboard','mouse','monitor','warranty'].map(k=>[k,{state:'unknown',detail:'',months:null,needs_reconfirmation:false,customer_statement:'구매 전에 확인해 주세요.'}]))};}
const clone=x=>JSON.parse(JSON.stringify(x));
function render(configuration,finalOnly=false,source){
  const p=M.product({product_code:99413,name:'CODE/MOCK 검증 PC',price:900000,spec:{cpu:'CPU'},reasons:['추천 근거'],public_configuration:configuration});
  const app=source||fs.readFileSync(path.join(__dirname,'../app.js'),'utf8');
  // Execute the actual render declarations; no startup, network or state-machine substitute.
  const start=app.indexOf('function publicBomDetails('),end=app.indexOf('function finalConditions(');
  const code=app.slice(start<0?app.indexOf('function productDetails('):start,end);
  return vm.runInNewContext(code+'\nproductDetails('+finalOnly+')',{M,state:{selected:p,selectedContext:null,selectionState:{usages:['게임']},talk:{}},
    esc:v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
    uiIcon:(name,cls='')=>'<img class="ui-icon '+cls+'" src="assets/icons/'+name+'.svg" alt="">',
    button:(label,action,cls='',data='')=>'<button type="button" class="'+cls+'" data-action="'+action+'" '+data+'>'+label+'</button>',
    money:v=>Number.isInteger(v)?v.toLocaleString('ko-KR')+'원':'금액 미확인'});
}
test('valid sold-offer binding accepts configuration identity different from offer; sorts without mutation',()=>{
  const f=fixture();f.parts.reverse();const before=clone(f),out=M.publicConfiguration(f,99413);
  assert.equal(out.configuration_id,'P10');assert.deepEqual(out.parts.map(p=>p.ordinal),[0,1,8]);assert.deepEqual(f,before);
});
test('missing, wrong selected product/offer, unsafe revision, duplicate ordinal and invalid quantity fail closed',()=>{
  assert.equal(M.publicConfiguration(null,99413),null);assert.equal(M.publicConfiguration(fixture(),101),null);
  for(const change of [f=>f.offer_id='P10',f=>f.revision=0,f=>f.revision='1',f=>f.revision=Number.MAX_SAFE_INTEGER+1,f=>f.revision=true,
    f=>f.parts[1].ordinal=0,f=>f.parts[0].quantity=0,f=>f.parts[0].quantity=1.5,f=>f.parts[0].specs=null,
    f=>f.photo.url='https://example.invalid/fake.png',f=>f.parts[2].name='가짜 조립',f=>f.parts=[],f=>f.description.faq=null]){
    const f=fixture();change(f);assert.equal(M.publicConfiguration(f,99413),null);
  }
});
test('public projection strips private fields deeply and is detached from its input',()=>{
  const f=fixture();f.source_basis='SECRET';f.parts[0].unit_price=100;f.parts[0].source_code='SECRET';f.parts[0].specs[0].operator_id=1;
  f.description.faq=[{question:'질문',answer:'답변',approved_by:1}];f.customer_conditions.os.private='SECRET';
  const out=M.publicConfiguration(f,99413);assert.doesNotMatch(JSON.stringify(out),/SECRET|unit_price|operator_id|approved_by|private/);
  f.parts[0].specs[0].value='changed';f.description.faq[0].answer='changed';assert.equal(out.parts[0].specs[0].value,'AM4');assert.equal(out.description.faq[0].answer,'답변');
});
test('needs_reconfirmation keeps null price; no frontend latest-revision proof is invented',()=>{
  const f=fixture();f.price.state='needs_reconfirmation';f.revision=2;assert.equal(M.publicConfiguration(f,99413).price.amount,null);
  assert.equal(M.publicConfiguration(f,99413).revision,2);
});
test('optional product seam survives recommendation and saved quote normalization without new requests',()=>{
  const p={product_code:99413,name:'검증 PC',price:900000,public_configuration:fixture()};
  const recommendation=M.recommendations({ok:true,card_sets:[{kind:'sold',items:[p]}]});
  const selected=recommendation.groups[0].products[0];assert.equal(selected.public_configuration.parts.length,3);
  const saved=M.quote({id:'11111111-1111-4111-8111-111111111111',product:p,state:{usages:['게임']},saved_at:'2026-10-06T00:00:00Z'});
  assert.deepEqual(saved.product.public_configuration,selected.public_configuration);p.public_configuration.parts[0].name='mutated';assert.equal(selected.public_configuration.parts[0].name,'CPU');
  assert.equal(M.product({product_code:99413,name:'PC',price:900000}).public_configuration,null);
});
test('pseudo and multiple SSD rows use ordinal keys and quantities without guessed price/photo',()=>{
  const f=fixture();f.parts.push(...[2,3].map(ordinal=>({...clone(f.parts[0]),ordinal,slot:'SSD',quantity:ordinal,name:'SSD'})));
  const html=render(f);assert.equal((html.match(/<tr data-part="bom-/g)||[]).length,5);
  assert.match(html,/data-detail="bom-2"/);assert.match(html,/data-detail="bom-3"/);assert.match(html,/수량 3/);assert.match(html,/서비스/);
  assert.equal((html.match(/class="final-part-price">미확인/g)||[]).length,5);assert.match(html,/900,000원/);
  assert.doesNotMatch(html,/100원|fake\.png|<img[^>]+(?:merchant|photo)/);assert.match(html,/disabled aria-describedby="bom-unavailable-/);
});
test('missing spec values and parts without specs read 정보 없음 (2026-10-10 owner decision)',()=>{
  const f=fixture();f.parts[0].specs=[{label:'소켓',value:'LGA1851'},{label:'기본 전력',value:'  '}];f.parts[1].specs=[];
  const html=render(f);assert.match(html,/<dt>소켓<\/dt><dd>LGA1851<\/dd>/);assert.match(html,/<dt>기본 전력<\/dt><dd>정보 없음<\/dd>/);
  assert.match(html,/<div class="public-bom-specs"><p>정보 없음<\/p><\/div>/);assert.doesNotMatch(html,/등록 사양 미확인/);
});
test('part text/specs are escaped and cannot insert executable markup',()=>{
  const f=fixture();f.parts[0].name='<img src=x onerror=alert(1)>';f.parts[0].description='<script>alert(1)</script>';f.parts[0].specs=[{label:'<svg>',value:'" onclick="bad'}];
  const html=render(f);assert.match(html,/&lt;script&gt;/);assert.match(html,/&lt;svg&gt;/);assert.match(html,/&quot; onclick=&quot;bad/);assert.doesNotMatch(html,/<script>|<img src=x|<svg>/);
});
test('absent and rejected public BOM keep identical legacy markup; final recommendations remain collapsible',()=>{
  assert.equal(render(null),render(undefined));const wrong=fixture();wrong.product_code=101;assert.equal(render(wrong),render(null));
  const current=fs.readFileSync(path.join(__dirname,'../app.js'),'utf8');
  const legacy=current.replace(/  const configuration=M\.publicConfiguration\(p\.public_configuration,p\.product_code\);\r?\n  if\(configuration\)return publicBomDetails\(configuration,p,information,finalOnly\);\r?\n/,'');
  for(const final of [false,true])assert.equal(render(null,final),render(null,final,legacy));
  const detail=render(fixture()),final=render(fixture(),true);assert.match(detail,/<\/section><section class="live-explanation">/);
  assert.match(final,/<details class="public-bom-information" data-detail="spec">/);assert.ok(final.indexOf('추천 근거')>final.indexOf('public-bom-information'));
});
// Whole-app DOM regression uses the existing jsdom test runtime (via NODE_PATH).
async function wholeApp(configuration){
  const {JSDOM}=require('jsdom'),read=name=>fs.readFileSync(path.join(__dirname,'../'+name),'utf8');
  const dom=new JSDOM(read('index.html'),{url:'http://qa.invalid/mvp3/#welcome',runScripts:'outside-only',pretendToBeVisual:true}),w=dom.window;
  const calls={parse:0,recommend:0,network:0,save:0};
  w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.TextEncoder=TextEncoder;
  w.fetch=()=>{calls.network++;throw Error('Network forbidden');};
  w.eval(read('live-model.js'));
  w.MVP3Api={parse:async()=>{calls.parse++;return {ok:true,state:{usages:['게임'],budget_won:1000000},missing:[]};},
    recommend:async()=>{calls.recommend++;return {ok:true,card_sets:[{kind:'sold',items:[{product_code:99413,name:'검증 PC',price:900000,reasons:['추천 근거'],public_configuration:configuration}]}],needs:[],assumed:[]};},
    save:async()=>{calls.save++;throw Error('Save forbidden');}};
  w.eval(read('live-flow.js'));const factory=w.MVP3LiveFlow.createFlow;let flow;
  w.MVP3LiveFlow.createFlow=(...args)=>{flow=factory(...args);return flow;};
  try{w.eval(read('app.js'));await flow.submit('CODE/MOCK 부품 슬롯 회귀');return {dom,flow,calls};}
  catch(error){dom.window.close();throw error;}
}
for(const slot of ['__proto__','constructor','toString','CPU','CUSTOM_SERVICE']){
  test('whole app/model/flow renders accepted slot '+slot+' in detail and final',async()=>{
    const f=fixture();f.parts[0].slot=slot;assert.equal(M.publicConfiguration(f,99413).parts[0].slot,slot);
    const h=await wholeApp(f);
    try{
      assert.equal(h.flow.state.error,null);assert.equal(h.flow.state.screen,'results');
      h.flow.select(0);
      for(const screen of ['detail','final']){
        if(screen==='final')h.flow.navigate('final');
        const doc=h.dom.window.document;assert.equal(doc.body.dataset.screen,screen);
        assert.equal(doc.querySelectorAll('tr[data-part^="bom-"]').length,3);
        const row=doc.querySelector('tr[data-part="bom-0"]');assert.ok(row.querySelector('h4').textContent.includes(slot));
        assert.equal(row.querySelector('.final-part-price').textContent,'미확인');
        const details=row.querySelector('details');details.open=true;h.flow.emit();
        assert.equal(doc.querySelector('details[data-detail="bom-0"]').open,true);
        assert.match(doc.querySelector('.public-bom-role').textContent,slot==='CPU'?/프로그램의 명령/:/등록된 사양과 설명/);
        assert.match(doc.querySelector('.final-summary-price').textContent,/900,000원/);
        const explanation=doc.querySelector('.live-explanation');assert.ok(explanation);
        assert.equal(!!explanation.closest('details.public-bom-information'),screen==='final');
      }
      assert.deepEqual(h.calls,{parse:1,recommend:1,network:0,save:0});
    }finally{h.dom.window.close();}
  });
}
module.exports={fixture,render};
