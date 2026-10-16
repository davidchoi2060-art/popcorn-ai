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
const pc={ai_composed:true,product_code:12,name:'PC 12',price:1300000,price_src:'현재 판매가',spec:{cpu:'CPU A',ram_gb:32},reasons:['게임 FHD'],over_budget:false,tag:'추천 구성',role:'recommended',public_configuration:configuration};
const talkState={usages:['게임'],budget_won:1500000,budget_bound:'이하'};
const reco={ok:true,assumed:[],anchor_code:12,wants:{},card_sets:[{kind:'sold',usage:'게임',usage_grid:'게임',items:[pc]}],talk_notes:[],choices:[]};
const change={ordinal:1,slot:'RAM',label:'메모리',quantity:2,before:{product_code:501,name:'램 16GB',price:60000},after:{product_code:502,name:'램 32GB',price:110000},delta:100000};
const options={ok:true,base_code:12,ordinal:1,slot:'RAM',label:'메모리',quantity:2,current:{product_code:501,name:'램 16GB',price:60000},total:1300000,checked:4,untested:1,
  note:'호환 규칙을 모두 통과한 판매 중 부품만 보여 드려요.',
  options:[{product_code:503,name:'램 8GB',price:30000,price_diff:-60000,total:1240000},{product_code:502,name:'램 32GB',price:110000,price_diff:100000,total:1400000}]};

function harness({quoteFail=false,total=1400000,limit=null,optionData=options,product=pc,width=1440}={}){
  const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read('index.html'),{url:'https://qa.invalid/mvp3/#welcome',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;w.matchMedia=q=>({matches:width<=Number(q.match(/max-width:\s*(\d+)px/)?.[1]||0),addEventListener(){}});w.scrollTo=()=>{};w.TextEncoder=TextEncoder;
  w.HTMLElement.prototype.scrollIntoView=function(){};
  Object.defineProperty(w,'crypto',{value:webcrypto});w.localStorage.setItem('popcorn-mvp3-guest-access-v1','a'.repeat(64));
  w.eval(read('live-model.js'));w.eval(read('api-client.js'));
  w.MVP3Api=w.MVP3Api.createClient({storage:w.localStorage,cryptoImpl:webcrypto,fetchImpl:async(url,init)=>{
    const body=init.body?JSON.parse(init.body):null;calls.push({url,method:init.method,body});
    if(url==='/api/mvp3/build/quote'&&quoteFail)return {ok:false,status:409,json:async()=>({detail:'이 조합은 호환되지 않아요: CPU-보드 소켓'}),headers:{get:()=>null}};
    const changes=body?.changes||[];
    const data=url==='/api/talk/parse'?{ok:true,state:talkState,history:[],missing:[]}:
      url==='/api/grid/recommend'?{...reco,card_sets:[{...reco.card_sets[0],items:[product]}]}:
      url==='/api/mvp3/build/options'?(limit?{...optionData,quantity_limit:limit}:typeof optionData==='function'?optionData(body):optionData):
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
// 후보 임시 선택(라디오) -> 「선택한 부품 적용」. 적용 전에는 서버 재계산이 일어나지 않는다.
function pickOption(d,code){d.querySelector('input[name=dv2-pick][value="'+code+'"]').click();d.querySelector('[data-action=build-apply]').click();}
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
    assert.equal(d.querySelector('[data-part="bom-8"] [data-action=build-options]'),null,'서비스 줄에는 변경 단추가 없다');
    assert.match(text(d.querySelector('[data-part="bom-8"] .dv2-act')),/변경 불가/);
    assert.equal(d.querySelector('#part-change [data-action=part-options]'),null);
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('options come from the server; picking one recomputes on the server and changes only that row',async()=>{
  const h=harness();try{await toDetail(h);const d=h.d;
    d.querySelector('[data-action=build-options][data-ordinal="1"]').click();
    await until(()=>d.querySelector('[data-build-option]'));
    assert.deepEqual(h.calls.find(c=>c.url==='/api/mvp3/build/options').body,{state:talkState,product_code:12,changes:[],ordinal:1});
    const panel=text(d.querySelector('.dv2-panel'));
    assert.equal(text(d.querySelector('.dv2-panel-head h3')),'메모리 변경');
    assert.ok(panel.includes('사용할 부품을 골라 주세요.')&&panel.includes('기본 구성과 비교한 금액이에요.')&&panel.includes('적용 전에는 구성이 바뀌지 않아요.'));
    const rows=[...d.querySelectorAll('[data-build-option]')];
    assert.deepEqual(rows.map(r=>r.dataset.buildOption),['501','503','502']);
    assert.ok(text(rows[0]).includes('기본 메모리')&&text(rows[0]).includes('추가 금액 없음')&&text(rows[0]).includes('현재 선택'));
    assert.ok(text(rows[2]).includes('+100,000원')&&!text(rows[2]).includes('1,400,000원')&&!text(rows[2]).includes('110,000원'),'후보 옆에 단품·PC 금액이 없다');
    assert.ok(text(rows[1]).includes('−60,000원')&&!text(rows[1]).includes('1,240,000원'));
    const apply=d.querySelector('[data-action=build-apply]');
    assert.equal(apply.disabled,true,'같은 후보(현재 적용된 것)에는 적용할 수 없다');
    // 임시 선택은 본문·총액·변경 개수를 바꾸지 않는다.
    d.querySelector('input[name=dv2-pick][value="502"]').click();
    assert.equal(apply.disabled,false);assert.equal(h.flow.state.selected.price,1300000);assert.equal(h.flow.state.selected.build,null);
    assert.ok(!h.calls.some(c=>c.url==='/api/mvp3/build/quote'),'적용 전에는 서버 재계산 요청이 없다');
    assert.ok(text(d.querySelector('[data-dv2-total]')).includes('1,300,000원'));
    d.querySelector('input[name=dv2-pick][value="501"]').click();assert.equal(apply.disabled,true);
    d.querySelector('input[name=dv2-pick][value="502"]').click();apply.click();
    await until(()=>h.flow.state.selected.price===1400000);
    assert.deepEqual(h.calls.find(c=>c.url==='/api/mvp3/build/quote').body,{state:talkState,product_code:12,changes:[{ordinal:1,product_code:502}]});
    assert.equal(h.flow.state.selected.product_code,12);
    assert.equal(d.querySelector('.dv2-panel'),null,'적용이 성공하면 패널이 닫힌다');
    const row=d.querySelector('[data-part="bom-1"]');
    assert.ok(text(row).includes('램 32GB')&&text(row).includes('기본 구성: 램 16GB')&&text(row).includes('변경됨')&&text(row).includes('+100,000원'));
    assert.ok(!text(row).includes('110,000원')&&!text(row).includes('60,000원'),'바꾼 줄에도 부품 판매가가 없다');
    assert.ok(row.querySelector('[data-action=build-undo]'));
    // 2026-10-16 P2-1: 오른쪽 aside 「선택한 구성」 -- 「변경 내용 N개」 + 줄별 차액 + 기본 구성 금액.
    const side=text(d.querySelector('aside.tf-side'));
    assert.ok(side.includes('선택한 구성')&&side.includes('1,400,000원')&&side.includes('기본 구성 금액1,300,000원')&&side.includes('메모리 변경+100,000원'),side);
    assert.equal(text(d.querySelector('aside.tf-side [data-pc-total-move]')),'변경 내용 1개');
    assert.doesNotMatch(text(d.querySelector('.dv2-parts')),/조립·기타|부품 합계/);
    assert.equal(d.querySelector('.dv2-parts tfoot'),null);
    // 하단 액션바는 구성표 있는 상세에서 숨는다. 「선택한 구성 확인」·「이전 화면」은 없고 주 버튼은 aside 의 「견적 보관하기」다.
    assert.equal(d.querySelector('#actions').hidden,true);
    assert.equal(d.querySelector('[data-action=final]'),null);assert.equal(d.querySelector('[data-action=back]'),null);
    assert.equal(text(d.querySelector('aside.tf-side [data-action=save]')),'견적 보관하기');
    assert.ok(text(d.querySelector('aside.tf-side [data-dv2-total]')).includes('1,400,000원'));
    assert.equal(d.activeElement?.dataset?.ordinal,'1','닫으면 포커스가 연 변경 단추로 돌아온다');
    assert.ok(text([...d.querySelectorAll('.message.ai')].at(-1)).startsWith('메모리 부품을 「램 32GB」 제품으로 바꿨어요.'));
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('save sends the changed rows and the server total; the kept page names the changed part and the handoff keeps the server number',async()=>{
  const h=harness();try{await toDetail(h);const d=h.d;
    d.querySelector('[data-action=build-options][data-ordinal="1"]').click();
    await until(()=>d.querySelector('[data-build-option]'));
    pickOption(d,502);
    await until(()=>h.flow.state.selected.price===1400000);
    await h.flow.save();
    const save=h.calls.find(c=>c.url==='/api/mvp3/saved-quotes'&&c.method==='POST').body;
    assert.equal(save.expected_price,1400000);assert.deepEqual(save.changes,[{ordinal:1,product_code:502}]);
    assert.equal(h.flow.state.savedQuote.product.build.changes.length,1);
    // 2026-10-16 P2-1: 보관 뒤에는 옛 최종 화면(인계 칸 .live-handoff) 대신 보관 완료 화면이 바꾼 부품과 서버 금액을 말한다.
    await until(()=>d.querySelector('section.tf-kept[data-keep-done]'));
    const kept=d.querySelector('section.tf-kept[data-keep-done]');
    assert.ok(text(kept).includes('메모리 변경 · 램 32GB')&&text(kept.querySelector('.tf-card-price')).includes('1,400,000원'),text(kept));
    assert.equal(d.querySelector('.live-handoff'),null,'old handoff panel is gone');
    // 인계 기록은 서버가 준 연결 번호와 바꾼 부품을 그대로 싣는다. 맞춤 구성은 몰 이동 화면(.tf-moved)을 그리지 않는다.
    await h.flow.handoff();await until(()=>h.flow.state.handoff);
    assert.equal(h.flow.state.handoff.handoff_no,'HO-4001');assert.equal(h.flow.state.handoff.changes,1,'the changed part is recorded with the handoff number');
    assert.equal(h.calls.filter(c=>c.url.endsWith('/handoff')).length,1);
    assert.equal(d.querySelector('.tf-moved'),null);assert.ok(d.querySelector('section.tf-kept[data-keep-done]'));
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('a refused combination keeps the old price and says why; reset goes back to the base build',async()=>{
  const h=harness({quoteFail:true});try{await toDetail(h);const d=h.d;
    d.querySelector('[data-action=build-options][data-ordinal="1"]').click();
    await until(()=>d.querySelector('[data-build-option]'));
    pickOption(d,502);
    await until(()=>d.querySelector('.dv2-panel [role=alert]'));
    assert.equal(h.flow.state.selected.price,1300000);
    assert.ok(text(d.querySelector('.dv2-panel [role=alert]')).includes('호환되지 않아요'));
    assert.ok(d.querySelector('input[name=dv2-pick][value="502"]').checked,'실패해도 고르던 후보가 남는다');
  }finally{h.close();}
  const g=harness();try{await toDetail(g);const d=g.d;
    d.querySelector('[data-action=build-options][data-ordinal="1"]').click();
    await until(()=>d.querySelector('[data-build-option]'));
    pickOption(d,502);
    await until(()=>g.flow.state.selected.price===1400000);
    d.querySelector('[data-action=build-reset]').click();
    await until(()=>g.flow.state.selected.price===1300000);
    assert.equal(g.flow.state.selected.build,null);
    // 변경이 없으면 aside 에 「변경 내용」 칸과 「전체 원래 구성으로」가 없다.
    assert.equal(d.querySelector('aside.tf-side [data-pc-total-move]'),null);assert.equal(d.querySelector('[data-action=build-reset]'),null);
    assert.ok(text(d.querySelector('[data-dv2-total]')).includes('1,300,000원'));
  }finally{g.close();}
});

test('the summary judges the budget on the new total after a change (over-budget line only)',async()=>{
  const h=harness({total:1580300});try{await toDetail(h);const d=h.d;
    // 2026-10-16 P2-1: aside 의 예산 줄(.dv2-notes)은 예산을 넘을 때만 나온다(tfOver). 예산 안이면 줄이 없다.
    const line=()=>d.querySelector('aside.tf-side .dv2-notes p:last-child');
    assert.equal(line(),null,'within budget: no budget line in the aside');
    d.querySelector('[data-action=build-options][data-ordinal="1"]').click();
    await until(()=>d.querySelector('[data-build-option]'));
    pickOption(d,502);
    await until(()=>h.flow.state.selected.price===1580300);
    const box=text(d.querySelector('aside.tf-side'));
    assert.ok(box.includes('1,580,300원')&&box.includes('기본 구성 금액1,300,000원'),box);
    assert.ok(text(d.querySelector('.dv2-mchanges')).includes('기본 구성보다 280,300원 추가'),'the move is judged on the new server total');
    assert.equal(text(line()),'예산보다 80,300원 높아요');assert.ok(line().classList.contains('warn-text'));
    d.querySelector('[data-action=build-reset]').click();
    await until(()=>h.flow.state.selected.price===1300000);
    assert.equal(line(),null,'back within budget: the over-budget line is gone');
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

// 2026-10-12 카드 검수 X1: 부품을 바꾼 뒤에도 상세 제목 아래에 기본 구성 이름만 있었다.
test('after a part change the detail says the product name is the base build and names the changed part',async()=>{
  const h=harness();try{await toDetail(h);const d=h.d;
    d.querySelector('[data-action=build-options][data-ordinal="1"]').click();
    await until(()=>d.querySelector('[data-build-option]'));
    pickOption(d,502);
    await until(()=>h.flow.state.selected.price===1400000);
    // 상품 이름은 식별 정보로 두고, 바꾼 내용은 「변경 내역」에 구분해 적는다.
    assert.equal(text(d.querySelector('.dv2-name')),'PC 12');
    // 바꾼 내용은 머리의 「변경 내역」(.dv2-mchanges)과 aside 의 「변경 내용 N개」에 적는다.
    const head=text(d.querySelector('.dv2-mchanges'));assert.ok(head.includes('변경 내역 1개')&&head.includes('메모리 변경')&&head.includes('+100,000원'),head);
    const side=text(d.querySelector('aside.tf-side .tf-changes'));assert.ok(side.includes('변경 내용 1개')&&side.includes('메모리 변경')&&side.includes('+100,000원'),side);
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
    pickOption(d,502);
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

// 2026-10-15 코덱스 오픈테스트 C04-F04: 메모리를 16GB × 2 로 바꿔도 소개 글은 「시스템 메모리는 16GB」였고 짧은 RAM 줄에도
// 수량·합계가 없었다. 서버가 준 바꾼 뒤 합계(system_ram_gb)로 소개 문장·바꾼 부품 안내·사양 줄을 고친다.
test('memory change: intro, changed-part note and spec row use the server system memory total',()=>{
  const M=require('../live-model.js');
  const build={changes:[{slot:'RAM',label:'메모리',quantity:2,after:{name:'KLEVV DDR5-5600 (16GB)'},system_ram_gb:32}]};
  const intro='Ryzen 5 9600X와 RTX 5070 12GB를 중심으로 구성했습니다. 저장공간은 1TB SSD입니다. 시스템 메모리는 16GB입니다.';
  assert.equal(M.changedIntro(intro,build),'Ryzen 5 9600X와 RTX 5070 12GB를 중심으로 구성했습니다. 저장공간은 1TB SSD입니다. 바꾼 구성의 시스템 메모리는 총 32GB입니다.');
  assert.equal(M.changedPartsNote(build),'상품 이름은 기본 구성 기준이에요. 바꾼 부품: 메모리 KLEVV DDR5-5600 (16GB) × 2 · 바꾼 구성의 시스템 메모리 총 32GB');
  assert.deepEqual(M.changedSpecRows(M.cardSpecRows({cpu:'C',ram_gb:16,ssd_gb:1000}),build).find(r=>r[0]==='RAM'),['RAM','총 32GB · KLEVV DDR5-5600 (16GB) × 2 (바꾼 부품)']);
  // 서버가 합계를 모르면 지어내지 않는다 -- 소개 글은 그대로, 수량만 밝힌다.
  const unknown={changes:[{slot:'RAM',label:'메모리',quantity:2,after:{name:'램'}}]};
  assert.equal(M.changedIntro(intro,unknown),intro);
  assert.equal(M.changedPartsNote(unknown),'상품 이름은 기본 구성 기준이에요. 바꾼 부품: 메모리 램 × 2');
  const q=M.buildQuote({ok:true,base_code:1,base_price:10,total:20,changes:[{ordinal:1,slot:'RAM',delta:10,quantity:2,system_ram_gb:32,before:{product_code:1,name:'a',price:5},after:{product_code:2,name:'b',price:10}}]},1);
  assert.equal(q.changes[0].system_ram_gb,32);
});
test('budget basis: per-unit budget for several units, withheld when the count is unknown',()=>{
  const M=require('../live-model.js'),money=n=>n.toLocaleString('ko-KR')+'원',t={budget_won:9600000,budget_bound:'이하'};
  assert.equal(M.budgetGapText(892800,t,null,money),'예산보다 8,707,200원 낮아요');
  assert.equal(M.budgetGapText(892800,t,{units:12},money),'12대 기준 한 대 예산 800,000원보다 92,800원 높아요');
  assert.equal(M.budgetGapText(800000,t,{units:12},money),'12대 기준 한 대 예산 800,000원과 같아요');
  assert.equal(M.budgetGapText(892800,t,{units:0},money),'여러 대 구매 · 대수를 몰라 총예산과 한 대 가격은 견주지 않았어요');
  assert.equal(M.overUnitBudget(892800,t,{units:12}),true);
  assert.equal(M.overUnitBudget(892800,t,{units:0}),false);
  assert.equal(M.overUnitBudget(892800,t,{units:1}),false);
});

// ===== 상세 v2 (2026-10-16 통합안): 선택한 부품 표 + 오른쪽 변경 패널 =====
test('v2 detail: no part price, parts sum or 조립·기타 row; only the server total and diffs',async()=>{
  const h=harness();try{await toDetail(h);const d=h.d;
    const body=text(d.querySelector('.dv2'));
    assert.doesNotMatch(body,/조립·기타|조립 · 기타|부품 합계|60,000원|110,000원|30,000원/);
    assert.equal(d.querySelectorAll('.dv2-row .final-part-price').length,0);
    assert.equal(d.querySelectorAll('.dv2-parts tfoot').length,0);
    assert.ok(text(d.querySelector('[data-dv2-total]')).includes('1,300,000원'));
    assert.match(text(d.querySelector('aside.tf-side')),/최종 금액, 재고와 운영체제·보증 포함 여부는 구매 상담 때 확인해 주세요\./);
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});
test('v2 picker: a candidate without a server diff is shown as 차액 확인 필요 and cannot be chosen (never 0)',async()=>{
  options.options.push({product_code:504,name:'차액 없는 램',price:1,price_diff:null});
  const h=harness();try{await toDetail(h);const d=h.d;
    d.querySelector('[data-action=build-options][data-ordinal="1"]').click();
    await until(()=>d.querySelector('[data-build-option="504"]'));
    const row=d.querySelector('[data-build-option="504"]');
    assert.ok(text(row).includes('차액 확인 필요')&&text(row).includes('선택 불가')&&!text(row).includes('추가 금액 없음'));
    assert.equal(row.querySelector('input').disabled,true);
    d.querySelector('[data-action=build-apply]').click();
    assert.ok(!h.calls.some(c=>c.url==='/api/mvp3/build/quote'));
  }finally{options.options.pop();h.close();}
});
test('v2 picker: temporary choice never changes the body; apply is disabled when the choice equals the applied part; 기본 부품으로 is also temporary',async()=>{
  const h=harness();try{await toDetail(h);const d=h.d;
    d.querySelector('[data-action=build-options][data-ordinal="1"]').click();await until(()=>d.querySelector('[data-build-option]'));
    pickOption(d,502);await until(()=>h.flow.state.selected.price===1400000);
    d.querySelector('[data-action=build-options][data-ordinal="1"]').click();await until(()=>d.querySelector('[data-build-option]'));
    const apply=()=>d.querySelector('[data-action=build-apply]'),quotes=()=>h.calls.filter(c=>c.url==='/api/mvp3/build/quote').length;
    assert.equal(apply().disabled,true);assert.ok(text(d.querySelector('[data-build-option="502"]')).includes('현재 선택'));
    d.querySelector('[data-action=build-pick-base]').click();
    assert.equal(d.querySelector('input[value="501"]').checked,true);assert.equal(apply().disabled,false);
    assert.equal(h.flow.state.selected.price,1400000);assert.equal(quotes(),1,'적용 전에는 서버 재계산이 없다');
    assert.ok(text(d.querySelector('[data-part="bom-1"]')).includes('램 32GB'),'본문은 아직 그대로');
    apply().click();await until(()=>h.flow.state.selected.price===1300000);
    assert.equal(h.flow.state.selected.build,null);assert.equal(d.querySelector('.dv2-panel'),null);
    assert.deepEqual(h.calls.filter(c=>c.url==='/api/mvp3/build/quote').at(-1).body.changes,[]);
  }finally{h.close();}
});
test('v2 row 기본 부품으로 reverts one row; Escape and cancel keep applied changes and the PC count',async()=>{
  const h=harness();try{await toDetail(h);const d=h.d;
    d.querySelector('[data-sets] [data-action=sets][data-sets="2"]').click();await until(()=>d.querySelector('[data-sets-total]'));
    d.querySelector('[data-action=build-options][data-ordinal="1"]').click();await until(()=>d.querySelector('[data-build-option]'));
    pickOption(d,502);await until(()=>h.flow.state.selected.price===1400000);
    assert.equal(h.flow.state.selected.sets,2);
    d.querySelector('[data-action=build-options][data-ordinal="1"]').click();await until(()=>d.querySelector('[data-build-option]'));
    d.querySelector('input[value="503"]').click();
    d.dispatchEvent(new h.w.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
    assert.equal(d.querySelector('.dv2-panel'),null);assert.equal(h.flow.state.selected.price,1400000);assert.equal(h.flow.state.selected.sets,2);
    assert.ok(text(d.querySelector('[data-part="bom-1"]')).includes('램 32GB'));
    d.querySelector('[data-action=build-options][data-ordinal="1"]').click();await until(()=>d.querySelector('[data-build-option]'));
    assert.equal(d.querySelector('input[value="502"]').checked,true,'다시 열면 임시 선택이 아니라 적용된 부품이 선택돼 있다');
    d.querySelector('.dv2-cancel').click();assert.equal(d.querySelector('.dv2-panel'),null);
    assert.equal(text(d.querySelector('[data-part="bom-1"] [data-action=build-undo]')),'기본 부품으로');
    d.querySelector('[data-part="bom-1"] [data-action=build-undo]').click();await until(()=>h.flow.state.selected.price===1300000);
    assert.equal(h.flow.state.selected.sets,2,'대수는 되돌려도 그대로');assert.equal(h.flow.state.selected.build,null);
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

// 2026-10-17 승인06 잔여: 임시 선택은 적용 후 예상 PC 총액만 미리 보이고 실제 구성/보관 상태를 바꾸지 않는다.
const previewProduct={...pc,price:891700,public_configuration:{...configuration,parts:[configuration.parts[0],
  {...configuration.parts[1],slot:'COOLER',quantity:1,name:'기본 쿨러'}]}};
const previewOptions={...options,slot:'COOLER',label:'쿨러',quantity:1,total:891700,
  current:{product_code:501,name:'기본 쿨러',price:32999},
  options:[{product_code:502,name:'3RSYS Socool RC750N PWM',price:49999,price_diff:17000,total:908700}]};
const appliedSnapshot=h=>JSON.stringify({selected:h.flow.state.selected,savedQuote:h.flow.state.savedQuote,
  saveState:h.flow.state.saveState,pendingSave:h.flow.state.pendingSave,inquiry:h.flow.state.inquiry});
async function openPreview(h){h.d.querySelector('[data-action=build-options][data-ordinal="1"]').click();await until(()=>h.d.querySelector('[data-build-option="502"]'));}
for(const width of [1440,390,360])test('temporary preview at '+width+': current 891700 and expected 908700 stay separate, without changing parts/count/saved quote or making requests',async()=>{
  const h=harness({product:previewProduct,optionData:previewOptions,width});try{await toDetail(h);const d=h.d;
    h.flow.setSets(2);
    h.flow.state.savedQuote={id:qid,product:JSON.parse(JSON.stringify(h.flow.state.selected))};h.flow.state.saveState='saved';h.flow.emit();
    await openPreview(h);
    const box=d.querySelector('[data-dv2-preview]');assert.ok(box);assert.equal(box.hidden,true);
    const before=appliedSnapshot(h),calls=h.calls.length;
    d.querySelector('input[name=dv2-pick][value="502"]').click();
    assert.equal(box.hidden,false);assert.match(text(box),/선택 적용 후/);assert.match(text(box),/1대 기준/);
    assert.equal(text(box.querySelector('[data-dv2-preview-total]')),'908,700원');assert.match(text(box),/\+17,000원/);
    assert.equal(text(d.querySelector('[data-dv2-total]')),'891,700원');
    assert.match(text(d.querySelector('[data-part="bom-1"]')),/기본 쿨러/);
    assert.equal(h.flow.state.selected.sets,2);assert.equal(h.flow.state.selected.public_configuration.parts[1].quantity,1);
    assert.equal(appliedSnapshot(h),before);assert.equal(h.calls.length,calls,'radio selection calls no quote/save/PI/LLM endpoint');
    assert.doesNotMatch(text(d.querySelector('.dv2-panel')),/32,999원|49,999원/,'part prices stay private');
    d.querySelector('input[name=dv2-pick][value="501"]').click();assert.equal(box.hidden,true);assert.equal(text(box),'');
    assert.equal(appliedSnapshot(h),before);assert.equal(h.calls.length,calls);
    d.querySelector('input[name=dv2-pick][value="502"]').click();d.querySelector('.dv2-cancel').click();
    assert.equal(d.querySelector('[data-dv2-preview]'),null);assert.equal(appliedSnapshot(h),before);
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('preview uses validated server PC total for positive, zero and negative diffs; invalid/missing totals remain unknown',async()=>{
  for(const [delta,total,expected] of [[17000,908700,'908,700원'],[0,891700,'891,700원'],[-17000,874700,'874,700원'],
    [17000,null,null],[17000,'908700',null],[17000,-1,null],[17000,908701,null]]){
    const optionData={...previewOptions,options:[{...previewOptions.options[0],price_diff:delta,total}]};
    const h=harness({product:previewProduct,optionData});try{await toDetail(h);await openPreview(h);const before=appliedSnapshot(h),calls=h.calls.length;
      h.d.querySelector('input[value="502"]').click();const box=h.d.querySelector('[data-dv2-preview]');assert.ok(box);
      if(expected){assert.equal(text(box.querySelector('[data-dv2-preview-total]')),expected);assert.doesNotMatch(text(box),/금액 확인 중/);}
      else{assert.equal(box.querySelector('[data-dv2-preview-total]'),null);assert.match(text(box),/금액 확인 중/);}
      assert.equal(appliedSnapshot(h),before);assert.equal(h.calls.length,calls);assert.deepEqual(h.errors,[]);
    }finally{h.close();}
  }
});

test('malformed current response totals are refused; negative/inconsistent current totals cannot produce an estimate',async()=>{
  for(const currentTotal of [null,'891700',NaN,Number.MAX_SAFE_INTEGER+1,-1,891701]){
    const optionData={...previewOptions,total:currentTotal};
    const h=harness({product:previewProduct,optionData});try{await toDetail(h);const d=h.d;
      const before=appliedSnapshot(h);d.querySelector('[data-action=build-options][data-ordinal="1"]').click();
      if(!Number.isSafeInteger(currentTotal)){
        await until(()=>d.querySelector('.dv2-panel [role=alert]'));
        assert.equal(d.querySelector('[data-dv2-preview-total]'),null);assert.equal(d.querySelector('[data-build-option]'),null);
      }else{
        await until(()=>d.querySelector('[data-build-option="502"]'));d.querySelector('input[value="502"]').click();
        assert.equal(d.querySelector('[data-dv2-preview-total]'),null);assert.match(text(d.querySelector('[data-dv2-preview]')),/금액 확인 중/);
      }
      assert.equal(appliedSnapshot(h),before);assert.equal(h.calls.filter(c=>c.url==='/api/mvp3/build/quote').length,0);
      assert.deepEqual(h.errors,[]);
    }finally{h.close();}
  }
});

test('base-part preview uses its server candidate total with other changes/quantities; absent candidate totals are never guessed',async()=>{
  for(const [quantity,hasBaseOption,omitBaseQuantity] of [[2,true,false],[3,true,false],[2,false,false],[3,false,false],[3,false,true]]){
    const row={...change,base_quantity:2,quantity,delta:quantity===2?100000:160000};
    if(omitBaseQuantity)delete row.base_quantity;
    const cpu={...change,ordinal:0,slot:'CPU',label:'CPU',quantity:1,base_quantity:1,delta:100000,
      before:{product_code:601,name:'CPU A',price:100000},after:{product_code:602,name:'CPU B',price:200000}};
    const product={...pc,price:1300000+row.delta+cpu.delta,build:{base_price:1300000,changes:[row,cpu]}};
    const expectedTotal=1300000+cpu.delta+(quantity-2)*60000;
    const optionData={...options,total:product.price,current:row.after,options:hasBaseOption?[{
      ...row.before,price_diff:expectedTotal-product.price,total:expectedTotal}]:[]};
    const h=harness({product,optionData});try{await toDetail(h);const d=h.d;
      d.querySelector('[data-action=build-options][data-ordinal="1"]').click();await until(()=>d.querySelector('[data-action=build-pick-base]'));
      const before=appliedSnapshot(h),calls=h.calls.length;d.querySelector('[data-action=build-pick-base]').click();
      const box=d.querySelector('[data-dv2-preview]');assert.ok(box);assert.equal(box.hidden,false);
      if(hasBaseOption){assert.equal(text(box.querySelector('[data-dv2-preview-total]')),expectedTotal.toLocaleString('ko-KR')+'원');assert.match(text(box),/−100,000원/);}
      else{assert.equal(box.querySelector('[data-dv2-preview-total]'),null);assert.match(text(box),/금액 확인 중/);}
      assert.equal(appliedSnapshot(h),before);assert.equal(h.calls.length,calls);assert.deepEqual(h.errors,[]);
    }finally{h.close();}
  }
});

test('after a refused apply the estimate remains a preview, and only successful server quote changes the actual total',async()=>{
  for(const quoteFail of [true,false]){
    const h=harness({quoteFail});try{await toDetail(h);await openPreview(h);const d=h.d;
      d.querySelector('input[value="502"]').click();assert.equal(text(d.querySelector('[data-dv2-preview-total]')),'1,400,000원');
      d.querySelector('[data-action=build-apply]').click();await until(()=>!h.flow.state.phase);
      assert.equal(h.calls.filter(c=>c.url==='/api/mvp3/build/quote').length,1);
      assert.equal(h.flow.state.selected.price,quoteFail?1300000:1400000);
      if(quoteFail){assert.equal(text(d.querySelector('[data-dv2-total]')),'1,300,000원');assert.equal(text(d.querySelector('[data-dv2-preview-total]')),'1,400,000원');}
      else assert.equal(d.querySelector('[data-dv2-preview]'),null);
      assert.deepEqual(h.errors,[]);
    }finally{h.close();}
  }
});
