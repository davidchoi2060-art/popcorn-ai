'use strict';
// 2026-10-11 중헌 님 「부품들도 개별 제품으로 … 자유롭게 변경하되, 호환성 체크는 해야 함」(부품 상품화 3단계).
// 공개된 구성표의 줄 「변경」 -> 호환되는 판매 부품(api/mvp3_build) -> 고르면 같은 PC 에서 그 줄만 바뀌고
// 금액은 서버가 다시 계산한 값 -> 보관은 바꾼 줄과 그 금액으로, 쇼핑몰 연결은 기본 구성임을 말한다. CODE/MOCK fixture.
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),{webcrypto}=require('node:crypto');
const {JSDOM,VirtualConsole}=require('jsdom');
const base=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(base,n),'utf8');
const tick=()=>new Promise(r=>setImmediate(r));
async function until(check){for(let n=0;n<400;n++){if(check())return;await tick();}throw Error('render did not settle');}
const qid='55555555-5555-4555-8555-555555555555';
const configuration={product_code:12,configuration_id:'P10',revision:1,offer_id:'P12',
  description:{title:'검증 PC',intro:'근거 설명',scene:null,benefits:[],checks:[],faq:[]},
  parts:[{ordinal:0,slot:'CPU',quantity:1,pseudo:false,name:'CPU A',description:'역할',specs:[{label:'소켓',value:'AM5'}]},
    {ordinal:1,slot:'RAM',quantity:2,pseudo:false,name:'램 16GB',description:'역할',specs:[]},
    {ordinal:8,slot:'SERVICE',quantity:1,pseudo:true,name:null,description:null,specs:[]}],
  price:{state:'unknown',amount:null,checked_at:null,observed_date:null,model:null},stock:{state:'unknown',checked_at:null},
  compatibility:{document_state:'pass',public_summary:null,assembly_state:'unknown'},photo:{state:'unresolved',url:null},
  customer_conditions:Object.fromEntries(['os','keyboard','mouse','monitor','warranty'].map(k=>[k,{state:'unknown',detail:'',months:null,needs_reconfirmation:false,customer_statement:'구매 전에 확인해 주세요.'}]))};
const pc={product_code:12,name:'PC 12',price:1300000,price_src:'현재 판매가',spec:{cpu:'CPU A',ram_gb:32},reasons:['게임 FHD'],over_budget:false,tag:'추천 구성',role:'recommended',public_configuration:configuration};
const talkState={usages:['게임'],budget_won:1500000,budget_bound:'이하'};
const reco={ok:true,assumed:[],anchor_code:12,wants:{},card_sets:[{kind:'sold',usage:'게임',usage_grid:'게임',items:[pc]}],talk_notes:[],choices:[]};
const change={ordinal:1,slot:'RAM',label:'메모리',quantity:2,before:{product_code:501,name:'램 16GB',price:60000},after:{product_code:502,name:'램 32GB',price:110000},delta:100000};
const options={ok:true,base_code:12,ordinal:1,slot:'RAM',label:'메모리',quantity:2,current:{product_code:501,name:'램 16GB',price:60000},total:1300000,checked:4,untested:1,
  note:'호환 규칙을 모두 통과한 판매 중 부품만 보여 드려요.',
  options:[{product_code:503,name:'램 8GB',price:30000,price_diff:-60000,total:1240000},{product_code:502,name:'램 32GB',price:110000,price_diff:100000,total:1400000}]};

function harness({quoteFail=false,total=1400000,limit=null}={}){
  const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read('index.html'),{url:'https://qa.invalid/mvp3/#welcome',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.TextEncoder=TextEncoder;
  w.HTMLElement.prototype.scrollIntoView=function(){};
  Object.defineProperty(w,'crypto',{value:webcrypto});w.localStorage.setItem('popcorn-mvp3-guest-access-v1','a'.repeat(64));
  w.eval(read('live-model.js'));w.eval(read('api-client.js'));
  w.MVP3Api=w.MVP3Api.createClient({storage:w.localStorage,cryptoImpl:webcrypto,fetchImpl:async(url,init)=>{
    const body=init.body?JSON.parse(init.body):null;calls.push({url,method:init.method,body});
    if(url==='/api/mvp3/build/quote'&&quoteFail)return {ok:false,status:409,json:async()=>({detail:'이 조합은 호환되지 않아요: CPU-보드 소켓'}),headers:{get:()=>null}};
    const changes=body?.changes||[];
    const data=url==='/api/talk/parse'?{ok:true,state:talkState,history:[],missing:[]}:
      url==='/api/grid/recommend'?reco:
      url==='/api/mvp3/build/options'?(limit?{...options,quantity_limit:limit}:options):
      url==='/api/mvp3/build/quote'&&changes[0]?.quantity?{ok:true,base_code:12,base_price:1300000,total:1300000+60000*(changes[0].quantity-2),compat:{ok:true},
        changes:[{...change,quantity:changes[0].quantity,base_quantity:2,after:change.before,delta:60000*(changes[0].quantity-2)}]}:
      url==='/api/mvp3/build/quote'?{ok:true,base_code:12,base_price:1300000,total:changes.length?total:1300000,changes:changes.length?[change]:[],compat:{ok:true}}:
      url==='/api/mvp3/saved-quotes'&&init.method==='POST'?{ok:true,quote:{id:qid,product:{...pc,price:1400000,build:{base_price:1300000,changes:[change]}},state:talkState,saved_at:'2026-10-11T00:00:00Z'}}:
      url.endsWith('/handoff')?{ok:true,handoff_no:'HO-4001',quote_id:qid,product_code:12,name:'PC 12',price_quoted:1300000,price_mall:1300000,mall_status:'확인됨',
        mall_url:'https://popcornpc.co.kr/shop/product_detail.html?pd_no=12',changes:[change]}:
      {ok:true,quotes:[],has_more:false};
    return {ok:true,status:200,json:async()=>data,headers:{get:()=>null}};
  }});w.eval(read('live-flow.js'));
  const create=w.MVP3LiveFlow.createFlow;let flow;
  w.MVP3LiveFlow.createFlow=(...args)=>{flow=create(...args);return flow;};
  w.eval(read('live-photo.js'));w.eval(read('app.js'));
  return {w,d:w.document,get flow(){return flow;},errors,calls,close:()=>dom.window.close()};
}
const text=e=>e.textContent.replace(/\s+/g,' ').trim();
async function toDetail(h){
  const d=h.d,input=d.querySelector('#request');input.value='게임 150만원';input.dispatchEvent(new h.w.Event('input',{bubbles:true}));
  d.querySelector('#chat-form').dispatchEvent(new h.w.Event('submit',{bubbles:true,cancelable:true}));
  await until(()=>d.querySelector('.live-product-card [data-action=detail]'));
  d.querySelector('.live-product-card [data-action=detail]').click();
  await until(()=>h.flow.state.screen==='detail'&&d.querySelector('.public-bom'));
}

test('every real BOM row has a working 변경; the service row does not; old other-PC buttons are gone',async()=>{
  const h=harness();try{await toDetail(h);const d=h.d;
    assert.deepEqual([...d.querySelectorAll('[data-action=build-options]')].map(b=>b.dataset.ordinal),['0','1']);
    assert.ok(d.querySelector('[data-part="bom-8"] [data-action=unavailable]').disabled);
    assert.equal(d.querySelector('#part-change [data-action=part-options]'),null);
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('options come from the server; picking one recomputes on the server and changes only that row',async()=>{
  const h=harness();try{await toDetail(h);const d=h.d;
    d.querySelector('[data-action=build-options][data-ordinal="1"]').click();
    await until(()=>d.querySelector('[data-build-option]'));
    assert.deepEqual(h.calls.find(c=>c.url==='/api/mvp3/build/options').body,{state:talkState,product_code:12,changes:[],ordinal:1});
    assert.equal(text(d.querySelector('.build-options-row h4')),'메모리 바꾸기 · 지금 램 16GB');
    assert.ok(text(d.querySelector('.build-options-row')).includes('확인하지 못한 부품 1개'));
    const rows=[...d.querySelectorAll('[data-build-option]')];
    assert.ok(text(rows[1]).includes('1,400,000원')&&text(rows[1]).includes('+100,000원'));
    rows[1].querySelector('[data-action=build-pick]').click();
    await until(()=>h.flow.state.selected.price===1400000);
    assert.deepEqual(h.calls.find(c=>c.url==='/api/mvp3/build/quote').body,{state:talkState,product_code:12,changes:[{ordinal:1,product_code:502}]});
    assert.equal(h.flow.state.selected.product_code,12);
    const row=d.querySelector('[data-part="bom-1"]');
    assert.ok(text(row).includes('램 32GB')&&text(row).includes('원래 부품: 램 16GB')&&text(row).includes('+100,000원'));
    assert.ok(text(d.querySelector('.public-bom tfoot')).replace(/\s/g,'').includes('기본구성금액1,300,000원'));
    assert.ok(text(d.querySelector('#actions')).includes('1,400,000원'));
    assert.ok(text([...d.querySelectorAll('.message.ai')].at(-1)).startsWith('메모리 부품을 「램 32GB」 제품으로 바꿨어요.'));
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('save sends the changed rows and the server total; handoff says the mall page is the base build',async()=>{
  const h=harness();try{await toDetail(h);const d=h.d;
    d.querySelector('[data-action=build-options][data-ordinal="1"]').click();
    await until(()=>d.querySelector('[data-build-option]'));
    d.querySelector('[data-build-option="502"] [data-action=build-pick]').click();
    await until(()=>h.flow.state.selected.price===1400000);
    await h.flow.save();
    const save=h.calls.find(c=>c.url==='/api/mvp3/saved-quotes'&&c.method==='POST').body;
    assert.equal(save.expected_price,1400000);assert.deepEqual(save.changes,[{ordinal:1,product_code:502}]);
    assert.equal(h.flow.state.savedQuote.product.build.changes.length,1);
    await h.flow.handoff();await until(()=>d.querySelector('.live-handoff'));
    assert.ok(text(d.querySelector('.live-handoff')).includes('쇼핑몰 상품 페이지는 기본 구성 기준이에요. 바꾼 부품 1개(차액 +100,000원)는 연결 번호 HO-4001로 기록해 두었어요.'));
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('a refused combination keeps the old price and says why; reset goes back to the base build',async()=>{
  const h=harness({quoteFail:true});try{await toDetail(h);const d=h.d;
    d.querySelector('[data-action=build-options][data-ordinal="1"]').click();
    await until(()=>d.querySelector('[data-build-option]'));
    d.querySelector('[data-build-option="502"] [data-action=build-pick]').click();
    await until(()=>d.querySelector('.build-options-row [role=alert]'));
    assert.equal(h.flow.state.selected.price,1300000);
    assert.ok(text(d.querySelector('.build-options-row')).includes('호환되지 않아요'));
  }finally{h.close();}
  const g=harness();try{await toDetail(g);const d=g.d;
    d.querySelector('[data-action=build-options][data-ordinal="1"]').click();
    await until(()=>d.querySelector('[data-build-option]'));
    d.querySelector('[data-build-option="502"] [data-action=build-pick]').click();
    await until(()=>g.flow.state.selected.price===1400000);
    d.querySelector('[data-action=build-reset]').click();
    await until(()=>g.flow.state.selected.price===1300000);
    assert.equal(g.flow.state.selected.build,null);
    assert.ok(text(d.querySelector('.public-bom tfoot')).replace(/\s/g,'').includes('상품참고금액1,300,000원'));
  }finally{g.close();}
});

test('the summary keeps the budget line after a change and judges it on the new total',async()=>{
  const h=harness({total:1580300});try{await toDetail(h);const d=h.d;
    const line=()=>d.querySelector('.final-summary-price p:last-child');
    assert.equal(text(line()),'예산보다 200,000원 낮아요');assert.ok(line().classList.contains('green'));
    d.querySelector('[data-action=build-options][data-ordinal="1"]').click();
    await until(()=>d.querySelector('[data-build-option]'));
    d.querySelector('[data-build-option="502"] [data-action=build-pick]').click();
    await until(()=>h.flow.state.selected.price===1580300);
    const box=text(d.querySelector('.final-summary-price'));
    assert.ok(box.includes('부품 1개를 바꾼 금액이에요 · 기본 구성 대비 +280,300원'),box);
    assert.equal(text(line()),'예산보다 80,300원 높아요');assert.ok(line().classList.contains('warn-text'));
    d.querySelector('[data-action=build-reset]').click();
    await until(()=>h.flow.state.selected.price===1300000);
    assert.equal(text(line()),'예산보다 200,000원 낮아요');assert.ok(line().classList.contains('green'));
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

// 2026-10-12 카드 검수 X1: 부품을 바꾼 뒤에도 상세 제목 아래에 기본 구성 이름만 있었다.
test('after a part change the detail says the product name is the base build and names the changed part',async()=>{
  const h=harness();try{await toDetail(h);const d=h.d;
    d.querySelector('[data-action=build-options][data-ordinal="1"]').click();
    await until(()=>d.querySelector('[data-build-option]'));
    d.querySelector('[data-build-option="502"] [data-action=build-pick]').click();
    await until(()=>h.flow.state.selected.price===1400000);
    assert.equal(text(d.querySelector('.live-summary [data-changed-parts]')),'상품 이름은 기본 구성 기준이에요. 바꾼 부품: 메모리 램 32GB');
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});
test('changed spec rows replace only the changed slots and drop the old GPU memory row',()=>{
  const M=require('../live-model.js'),spec={cpu:'i5-12400F',gpu:'RTX 5060',ram_gb:16,ssd_gb:500,vram_gb:8};
  const build={changes:[{slot:'SSD',label:'저장장치',after:{name:'PNY CS900 1TB'}},{slot:'GPU',label:'그래픽카드',after:{name:'RTX 5050'}}]};
  assert.deepEqual(M.changedSpecRows(M.specRows(spec),build),[['CPU','i5-12400F'],['GPU','RTX 5050 (바꾼 부품)'],['메모리','16GB'],['저장장치','PNY CS900 1TB (바꾼 부품)']]);
  assert.deepEqual(M.changedSpecRows(M.cardSpecRows(spec),null),M.cardSpecRows(spec));
  assert.equal(M.changedPartsNote(null),'');
});

// 2026-10-12 중헌 님 7번: 메모리·저장장치는 메인보드가 받는 만큼 수량을, 전체 구성은 여러 대로.
test('memory quantity goes up to the board limit the server gives; the server recomputes the price',async()=>{
  const h=harness({limit:{min:1,max:4,basis:'메인보드 메모리 슬롯 4개 · 최대 192GB 기준이에요.',known:true}});try{await toDetail(h);const d=h.d;
    d.querySelector('[data-action=build-options][data-ordinal="1"]').click();
    await until(()=>d.querySelector('[data-part-qty]'));
    assert.match(text(d.querySelector('[data-part-qty]')),/수량−2개\+메인보드 메모리 슬롯 4개 · 최대 192GB 기준이에요. 4개까지 고를 수 있어요./);
    d.querySelector('[data-action=build-qty][data-qty="3"]').click();
    await until(()=>h.flow.state.selected.price===1360000);
    const q=h.calls.filter(c=>c.url==='/api/mvp3/build/quote').at(-1);
    assert.deepEqual(q.body.changes,[{ordinal:1,product_code:501,quantity:3}]);
    assert.match(text(d.querySelector('[data-part="bom-1"]')),/수량 3/);
    d.querySelector('[data-action=build-options][data-ordinal="1"]').click();
    await until(()=>d.querySelector('[data-build-option]'));
    d.querySelector('[data-build-option="502"] [data-action=build-pick]').click();
    await until(()=>h.calls.filter(c=>c.url==='/api/mvp3/build/quote').length===2&&!h.flow.state.phase);await tick();
    assert.deepEqual(h.calls.filter(c=>c.url==='/api/mvp3/build/quote').at(-1).body.changes,[{ordinal:1,product_code:502,quantity:3}],'a picked part keeps the chosen quantity');
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('an unknown board keeps the plus button locked and says why',async()=>{
  const h=harness({limit:{min:1,max:2,basis:'메인보드 메모리 슬롯이나 메모리 용량 정보를 확인하지 못해 수량을 늘릴 수 없어요.',known:false}});try{await toDetail(h);const d=h.d;
    d.querySelector('[data-action=build-options][data-ordinal="1"]').click();
    await until(()=>d.querySelector('[data-part-qty]'));
    assert.ok(d.querySelector('[data-action=build-qty][data-qty="3"]').disabled);
    assert.ok(!d.querySelector('[data-action=build-qty][data-qty="1"]').disabled);
    assert.ok(d.querySelector('[data-part-qty] .warn-text'));
  }finally{h.close();}
});

test('the whole build can be quoted for several units; the save sends the unit price and the count',async()=>{
  const h=harness();try{await toDetail(h);const d=h.d;
    d.querySelector('[data-sets] [data-action=sets][data-sets="2"]').click();
    await until(()=>d.querySelector('[data-sets-total]'));
    assert.equal(text(d.querySelector('[data-sets-total]')),'같은 구성 2대 · 합계 2,600,000원');
    d.querySelector('[data-sets] [data-action=sets][data-sets="3"]').click();
    await until(()=>h.flow.state.selected.sets===3);
    h.flow.save();
    await until(()=>h.calls.some(c=>c.url==='/api/mvp3/saved-quotes'&&c.method==='POST'));
    const save=h.calls.find(c=>c.url==='/api/mvp3/saved-quotes'&&c.method==='POST');
    assert.equal(save.body.sets,3);assert.equal(save.body.expected_price,1300000);
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});
