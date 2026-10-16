'use strict';
// 2026-10-16 사장님: 쇼핑몰에서 파는 PC 는 우리 화면에서 부품을 바꾸지 않는다 -- 「변경」은 팝콘PC 이관 안내창으로 간다.
// 고객 문구 점검(C06 C14 C15 C16 C17 C18)도 같은 화면이라 여기서 함께 지킨다. CODE/MOCK fixture.
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
const MALL='https://popcornpc.co.kr/shop/product_detail.html?pd_no=12';
const pc={product_code:12,mall_url:MALL,name:'PC 12',price:1300000,price_src:'현재 판매가',spec:{cpu:'CPU A',ram_gb:32},reasons:['게임 FHD'],over_budget:false,tag:'추천 구성',role:'recommended',public_configuration:configuration};
const talkState={usages:['게임'],budget_won:1500000,budget_bound:'이하'};
const reco={ok:true,assumed:[],anchor_code:12,wants:{},card_sets:[{kind:'sold',usage:'게임',usage_grid:'게임',items:[pc]}],talk_notes:[],choices:[]};
const change={ordinal:1,slot:'RAM',label:'메모리',quantity:2,before:{product_code:501,name:'램 16GB',price:60000},after:{product_code:502,name:'램 32GB',price:110000},delta:100000};
const options={ok:true,base_code:12,ordinal:1,slot:'RAM',label:'메모리',quantity:2,current:{product_code:501,name:'램 16GB',price:60000},total:1300000,checked:4,untested:1,
  note:'호환 규칙을 모두 통과한 판매 중 부품만 보여 드려요.',
  options:[{product_code:503,name:'램 8GB',price:30000,price_diff:-60000,total:1240000},{product_code:502,name:'램 32GB',price:110000,price_diff:100000,total:1400000}]};


function harness(product=pc){
  const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read('index.html'),{url:'https://qa.invalid/mvp3/#welcome',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.TextEncoder=TextEncoder;
  w.HTMLElement.prototype.scrollIntoView=function(){};
  const tabs=[];w.open=()=>{const t={opener:{},closed:false,location:{href:''},document:{title:''},close(){t.closed=true;}};tabs.push(t);return t;};
  Object.defineProperty(w,'crypto',{value:webcrypto});w.localStorage.setItem('popcorn-mvp3-guest-access-v1','a'.repeat(64));
  w.eval(read('live-model.js'));w.eval(read('api-client.js'));
  const card={...reco,card_sets:[{kind:'sold',usage:'게임',usage_grid:'게임',items:[product]}]};
  w.MVP3Api=w.MVP3Api.createClient({storage:w.localStorage,cryptoImpl:webcrypto,fetchImpl:async(url,init)=>{
    const body=init.body?JSON.parse(init.body):null;calls.push({url,method:init.method,body});
    const data=url==='/api/talk/parse'?{ok:true,state:talkState,history:[],missing:[]}:
      url==='/api/grid/recommend'?card:
      url==='/api/mvp3/saved-quotes'&&init.method==='POST'?{ok:true,quote:{id:qid,product,state:talkState,saved_at:'2026-10-11T00:00:00Z'}}:
      url==='/api/mvp3/build/options'?{ok:true,base_code:12,ordinal:1,slot:'RAM',label:'메모리',quantity:2,current:{product_code:501,name:'램 16GB',price:60000},total:1300000,checked:1,untested:0,note:'',options:[{product_code:502,name:'램 32GB',price:110000,price_diff:100000,total:1400000}]}:
      url==='/api/mvp3/contact'?{ok:true,has_contact:true,masked_phone:'010-****-5678',name:null,consent_text:'동의 문구'}:
      url.endsWith('/handoff')?{ok:true,handoff_no:'HO-5001',quote_id:qid,product_code:12,name:'PC 12',price_quoted:1300000,price_mall:1300000,mall_status:'확인됨',mall_url:MALL,changes:[]}:
      url==='/api/mvp3/inquiry-form'||url.includes('purchase-inquiry/form')?{ok:true,topics:['기타'],consent_text:'동의'}:
      {ok:true,quotes:[],has_more:false};
    return {ok:true,status:200,json:async()=>data,headers:{get:()=>null}};
  }});w.eval(read('live-flow.js'));
  const create=w.MVP3LiveFlow.createFlow;let flow;
  w.MVP3LiveFlow.createFlow=(...args)=>{flow=create(...args);return flow;};
  w.eval(read('live-photo.js'));w.eval(read('app.js'));
  return {w,d:w.document,get flow(){return flow;},errors,calls,tabs,close:()=>dom.window.close()};
}
const text=e=>e.textContent.replace(/\s+/g,' ').trim();
async function toDetail(h){
  const d=h.d,input=d.querySelector('#request');input.value='게임 150만원';input.dispatchEvent(new h.w.Event('input',{bubbles:true}));
  d.querySelector('#chat-form').dispatchEvent(new h.w.Event('submit',{bubbles:true,cancelable:true}));
  await until(()=>d.querySelector('.live-product-card [data-action=detail]'));
  d.querySelector('.live-product-card [data-action=detail]').click();
  await until(()=>h.flow.state.screen==='detail'&&d.querySelector('.public-bom'));
}
const key=(h,k,extra={})=>h.d.dispatchEvent(new h.w.KeyboardEvent('keydown',{key:k,bubbles:true,cancelable:true,...extra}));
const NEG=/부품별 금액을 더해|단품 금액 표시 없음|부품 질문은 아직 지원|이 부품 질문하기/;

test('mall PC detail: 변경 opens the 팝콘PC 이동 dialog, never the picker; no part-options call; cancel keeps everything',async()=>{
  const h=harness();try{await toDetail(h);const d=h.d;
    const btns=[...d.querySelectorAll('[data-action=build-options]')];
    assert.deepEqual(btns.map(b=>b.dataset.ordinal),['0','1']);
    btns[1].focus();btns[1].click();
    const dlg=d.querySelector('[data-mall-dialog]');assert.ok(dlg,'안내창이 열린다');
    assert.equal(d.querySelector('.dv2-panel'),null,'부품 선택 패널은 열리지 않는다');
    assert.ok(!h.calls.some(c=>c.url==='/api/mvp3/build/options'),'후보 조회 요청이 없다');
    assert.equal(text(dlg.querySelector('h3')),'팝콘PC에서 부품을 변경해 주세요');
    assert.equal(text(dlg.querySelector('#mall-dlg-desc')),'이 상품의 부품은 팝콘PC 상품 페이지에서 옵션으로 바꿀 수 있어요. 선택한 옵션에 따라 금액이 달라져요. 팝콘PC로 이동할까요?');
    const go=dlg.querySelector('[data-action=mall-move]'),cancel=dlg.querySelector('[data-action=mall-dialog-close]');
    assert.equal(text(go),'팝콘PC로 이동');assert.equal(text(cancel),'취소');
    assert.equal(dlg.querySelector('[role=dialog]').getAttribute('aria-modal'),'true');
    assert.equal(d.activeElement.id,'mall-dlg-title');
    // 아직 아무것도 보내지 않았다 -- 이동을 누르기 전에는 인계 기록도 새 창도 없다.
    assert.ok(!h.calls.some(c=>c.url==='/api/mvp3/saved-quotes'||c.url.endsWith('/handoff')));
    assert.equal(h.tabs.length,0);
    // 초점은 안내창 안에서만 돈다.
    cancel.focus();key(h,'Tab');assert.equal(d.activeElement,go);
    key(h,'Tab',{shiftKey:true});assert.equal(d.activeElement,cancel);
    // Escape 로 닫고 눌렀던 단추로 돌아온다. 새 창·인계 요청은 없다.
    key(h,'Escape');assert.equal(d.querySelector('[data-mall-dialog]'),null);assert.equal(d.activeElement.dataset.action,'build-options');assert.equal(d.activeElement.dataset.ordinal,'1');
    // 취소도 같다.
    const b0=d.querySelector('[data-action=build-options][data-ordinal="0"]');b0.focus();b0.click();d.querySelector('[data-action=mall-dialog-close]').click();
    assert.equal(d.querySelector('[data-mall-dialog]'),null);assert.equal(d.activeElement.dataset.action,'build-options');assert.equal(d.activeElement.dataset.ordinal,'0');
    assert.equal(h.tabs.length,0);assert.ok(!h.calls.some(c=>c.url.endsWith('/handoff')||c.url==='/api/mvp3/saved-quotes'));
    assert.equal(h.flow.state.screen,'detail');assert.equal(h.flow.state.selected.build,null);
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('mall PC: 팝콘PC로 이동 records the handoff first, then moves the pre-opened tab to the mall page; the dialog turns into the after-move notice',async()=>{
  const h=harness();try{await toDetail(h);const d=h.d;
    d.querySelector('[data-action=build-options][data-ordinal="0"]').click();
    d.querySelector('[data-action=mall-move]').click();
    await until(()=>d.querySelector('[data-mall-state=moved]'));
    const post=h.calls.filter(c=>c.method==='POST'&&(c.url==='/api/mvp3/saved-quotes'||c.url.endsWith('/handoff')));
    assert.deepEqual(post.map(c=>c.url),['/api/mvp3/saved-quotes','/api/mvp3/saved-quotes/'+qid+'/handoff'],'보관 -> 인계 기록 순서, 각 한 번');
    assert.equal(post[0].body.purpose,'handoff');assert.equal(post[0].body.contact,undefined,'쇼핑몰 이동은 연락처를 받지 않는다');
    assert.equal(h.tabs.length,1);assert.equal(h.tabs[0].location.href,MALL);assert.equal(h.tabs[0].opener,null);
    const t=text(d.querySelector('[data-mall-dialog]'));
    assert.match(t,/팝콘PC에서 원하는 옵션을 선택해 주세요\./);assert.match(t,/HO-5001/);assert.match(t,/주문이나 결제가 완료된 상태는 아니에요/);
    assert.doesNotMatch(t,/주문이 접수|결제가 완료됐|주문 완료/);
    assert.equal(d.querySelector('[data-mall-reopen]').getAttribute('href'),MALL);
    assert.equal(h.flow.state.screen,'detail');
    d.querySelector('[data-action=mall-dialog-close]').click();assert.equal(d.querySelector('[data-mall-dialog]'),null);
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('mall PC detail has no 원래 부품으로, change list, 부품 변경 금액, 저장 wording or negative total explanations',async()=>{
  const h=harness();try{await toDetail(h);const d=h.d,all=text(d.querySelector('.dv2'));
    assert.equal(d.querySelector('[data-action=build-undo]'),null);assert.equal(d.querySelector('[data-action=build-reset]'),null);
    assert.doesNotMatch(all,/원래 부품으로|변경 내역|부품 변경 금액/);assert.doesNotMatch(all,NEG);
    assert.ok(d.querySelector('[data-mall-hint]'),'쇼핑몰 구성 한 줄 안내');
    const confirm=[...d.querySelectorAll('[data-action=final]')];
    assert.ok(confirm.length>=1);for(const b of confirm){assert.match(text(b),/선택한 구성 확인/);assert.doesNotMatch(text(b),/저장|보관/);}
    assert.equal(d.querySelector('#actions [data-action=final]').textContent.includes('저장'),false);
    assert.doesNotMatch(all,/미확인 *$|재확인 필요/);
    assert.match(all,/팝콘PC 상품 페이지에서 포함 여부 확인/);assert.match(all,/주문 전 팝콘PC에서 확인/);
    assert.equal(d.querySelectorAll('[data-action=unavailable]').length,0,'비활성 질문 단추가 없다');
  }finally{h.close();}
});

test('final screen: no disabled 변경 buttons, single 상세로 돌아가기 path, 견적 저장 only after the real save',async()=>{
  const h=harness();try{await toDetail(h);const d=h.d;
    d.querySelector('#actions [data-action=final]').click();await until(()=>h.flow.state.screen==='final');
    const v=text(d.querySelector('#view'));
    assert.equal(d.querySelectorAll('#view [data-action=unavailable],#view [data-action=build-options]').length,0);
    assert.doesNotMatch(v,NEG);assert.match(text(d.querySelector('.final-back')),/상세로 돌아가기/);
    assert.match(v,/저장 전/);assert.doesNotMatch(v,/저장됨|저장 완료/);
    const save=d.querySelector('[data-action=save]');assert.equal(text(save),'견적 저장');
    save.click();await until(()=>d.querySelector('[data-kact=submit]'));d.querySelector('[data-kact=submit]').click();await until(()=>h.flow.state.saveState==='saved');
    assert.match(text(d.querySelector('#view')),/서버에 저장됨/);assert.equal(text(d.querySelector('[data-action=save]')),'저장 완료');
  }finally{h.close();}
});

test('older saved mall quote with changes: read-only rows, no undo/reset, note that the mall gets the base configuration',async()=>{
  const built={...pc,price:1400000,build:{base_price:1300000,changes:[change],warnings:[]}};
  const h=harness(built);try{await toDetail(h);const d=h.d;
    const row=d.querySelector('[data-part="bom-1"]');
    assert.ok(text(row).includes('램 32GB')&&text(row).includes('변경됨')&&text(row).includes('+100,000원'));
    assert.equal(d.querySelector('[data-action=build-undo]'),null);assert.equal(d.querySelector('[data-action=build-reset]'),null);
    assert.match(text(d.querySelector('.dv2-side')),/쇼핑몰 상품 페이지는 기본 구성 기준/);
    row.querySelector('[data-action=build-options]').click();
    assert.ok(d.querySelector('[data-mall-dialog]'));assert.equal(d.querySelector('.dv2-panel'),null);
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('AI-composed product (server flag, no mall page) still opens the picker panel',async()=>{
  const own={...pc,ai_composed:true};delete own.mall_url;
  const h=harness(own);try{await toDetail(h);const d=h.d;
    d.querySelector('[data-action=build-options][data-ordinal="1"]').click();
    assert.equal(d.querySelector('[data-mall-dialog]'),null);
    await until(()=>d.querySelector('[data-build-option]'));
    assert.ok(d.querySelector('.dv2-panel'));
  }finally{h.close();}
});

test('C06: with real conditions and nothing picked at the gateway, the header shows the applied conditions, never 미정',async()=>{
  const h=harness();try{await toDetail(h);const d=h.d;
    d.querySelector('[data-action=gateway]').click();d.querySelector('[data-action=gateway-use]').click();d.querySelector('[data-action=gateway-begin]').click();
    const box=d.querySelector('[data-draft-context]');assert.ok(box);
    assert.equal(box.dataset.draftContext,'applied');assert.match(text(box),/현재 상담 조건.*게임/);
    assert.doesNotMatch(text(d.querySelector('#view')),/용도 미정|예산 미정/);
  }finally{h.close();}
});
