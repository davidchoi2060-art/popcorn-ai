'use strict';
// 2026-10-16 두 구매 흐름(대표 지시 + Claude 디자인 시안 v1). CODE/MOCK fixture 로만 확인한다(실 DB·실 요청 없음).
//  ① 쇼핑몰 완제품: 「팝콘PC로 이동」= 인계 기록 한 번 -> 성공한 뒤에만 새 창. 주소 없음·인계 실패·팝업 차단은 이동 완료를 보이지 않는다.
//  ② 견적 보관: 처음에는 전화번호(필수)+동의, 다음 견적은 등록 연락처 재사용, 연락처 변경은 누른 때만.
//  ③ 보관 견적서의 「상담 신청 접수」: 보관과 다른 상태. 접수 성공 뒤에만 신청 번호·견적 번호·가린 번호를 보이고, 같은 견적은 새 신청을 만들지 않는다.
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),{webcrypto}=require('node:crypto');
const {JSDOM,VirtualConsole}=require('jsdom');
const base=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(base,n),'utf8');
const tick=()=>new Promise(r=>setImmediate(r));
async function until(check){for(let n=0;n<600;n++){if(check())return;await tick();}throw Error('render did not settle');}
const qid='55555555-5555-4555-8555-555555555555';
const MALL='https://popcornpc.co.kr/shop/product_detail.html?pd_no=12';
const configuration={product_code:12,configuration_id:'P10',revision:1,offer_id:'P12',
  description:{title:'검증 PC',intro:'근거 설명',scene:null,benefits:[],checks:[],faq:[]},
  parts:[{ordinal:0,slot:'CPU',quantity:1,pseudo:false,name:'CPU A',description:'역할',specs:[{label:'소켓',value:'AM5'}]},
    {ordinal:1,slot:'RAM',quantity:2,pseudo:false,name:'램 16GB',description:'역할',specs:[]},
    {ordinal:8,slot:'SERVICE',quantity:1,pseudo:true,name:null,description:null,specs:[]}],
  price:{state:'unknown',amount:null,checked_at:null,observed_date:null,model:null},stock:{state:'unknown',checked_at:null},
  compatibility:{document_state:'pass',public_summary:null,assembly_state:'unknown'},photo:{state:'unresolved',url:null},
  customer_conditions:Object.fromEntries(['os','keyboard','mouse','monitor','warranty'].map(k=>[k,{state:'unknown',detail:'',months:null,needs_reconfirmation:false,customer_statement:'구매 전에 확인해 주세요.'}]))};
const pc={product_code:12,mall_url:MALL,name:'PC 12',price:1300000,price_src:'현재 판매가',spec:{cpu:'CPU A',ram_gb:32},reasons:['게임 FHD'],over_budget:false,tag:'추천 구성',role:'recommended',public_configuration:configuration};
const talkState={usages:['게임'],budget_won:1500000,budget_bound:'이하'};
const text=e=>e.innerHTML.replace(/<[^>]*>/g,' ').replace(/&[a-z#0-9]+;/g,' ').replace(/\s+/g,' ').trim();
const reply=(status,data)=>({ok:status<400,status,json:async()=>data,headers:{get:()=>null}});
const key=(h,k,extra={})=>h.d.dispatchEvent(new h.w.KeyboardEvent('keydown',{key:k,bubbles:true,cancelable:true,...extra}));

// opts: product · has(연락처 등록 여부) · popup · handoff('ok'|'fail') · saveFail · consult('ok'|'already'|'fail'|'need_contact')
function harness(opts={}){
  const o={product:pc,has:false,popup:true,handoff:'ok',saveFail:0,consult:'ok',...opts};
  const errors=[],calls=[],tabs=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read('index.html'),{url:'https://qa.invalid/mvp3/#welcome',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.TextEncoder=TextEncoder;
  w.HTMLElement.prototype.scrollIntoView=function(){};
  w.open=()=>{if(!o.popup)return null;const t={opener:{},closed:false,location:{href:''},document:{title:''},close(){t.closed=true;}};tabs.push(t);return t;};
  Object.defineProperty(w,'crypto',{value:webcrypto});w.localStorage.setItem('popcorn-mvp3-guest-access-v1','a'.repeat(64));
  w.eval(read('live-model.js'));w.eval(read('api-client.js'));
  const reco={ok:true,assumed:[],anchor_code:12,wants:{},card_sets:[{kind:'sold',usage:'게임',usage_grid:'게임',items:[o.product]}],talk_notes:[],choices:[]};
  const server={has:o.has,phone:null,inquiries:new Map(),saved:null,sets:0};
  w.MVP3Api=w.MVP3Api.createClient({storage:w.localStorage,cryptoImpl:webcrypto,fetchImpl:async(url,init)=>{
    const body=init.body?JSON.parse(init.body):null;calls.push({url,method:init.method,body,key:init.headers['X-Access-Key']});
    if(url==='/api/talk/parse')return reply(200,{ok:true,state:talkState,history:[],missing:[]});
    if(url==='/api/grid/recommend')return reply(200,reco);
    if(url==='/api/mvp3/contact'&&init.method==='GET')return reply(200,{ok:true,has_contact:server.has,masked_phone:server.has?'010-****-5678':null,name:null,consent_text:'서버 동의 문구'});
    if(url==='/api/mvp3/contact'&&init.method==='PUT'){server.has=true;server.phone=body.phone;return reply(200,{ok:true,has_contact:true,masked_phone:'010-****-9999',name:null});}
    if(url==='/api/mvp3/saved-quotes'&&init.method==='POST'){
      if(server.saveFail>0||o.saveFail>server.sets++&&false)return reply(500,{detail:'x'});
      if(o.saveFail&&server.sets<=o.saveFail)return reply(503,{detail:'서버 점검 중'});
      if(body.purpose!=='handoff'){
        if(!body.contact&&!server.has)return reply(422,{detail:{error:'contact_required',contact_required:true,detail:'견적을 보관하려면 전화번호를 입력하고 개인정보 수집·이용에 동의해 주세요.',consent_text:'서버 동의 문구'}});
        if(body.contact){server.has=true;server.phone=body.contact.phone;}
      }
      server.saved=qid;
      return reply(200,{ok:true,quote:{id:qid,product:{...o.product,price:body.expected_price},state:body.state,saved_at:'2026-10-16T00:00:00Z'},
        contact:server.has?{has_contact:true,masked_phone:body.contact?'010-****-5678':'010-****-5678',name:null}:{has_contact:false,masked_phone:null,name:null}});
    }
    if(url.endsWith('/handoff')){
      if(o.handoff==='fail')return reply(502,{detail:'bad gateway'});
      return reply(200,{ok:true,handoff_no:'HO-5001',quote_id:qid,product_code:12,name:'PC 12',price_quoted:1300000,price_mall:1300000,mall_status:'확인됨',mall_url:MALL,changes:[]});
    }
    if(url==='/api/mvp3/purchase-inquiries/from-quote'){
      if(o.consult==='fail')return reply(503,{detail:'서버 점검 중'});
      if(o.consult==='need_contact'&&!server.has)return reply(409,{detail:{error:'contact_required',contact_required:true,detail:'상담 신청을 접수하려면 연락처가 필요해요. 연락처를 먼저 등록해 주세요.'}});
      const already=server.inquiries.has(body.quote_id)||o.consult==='already';
      if(!already)server.inquiries.set(body.quote_id,'PI-1001');
      return reply(200,{ok:true,already,inquiry_no:'PI-1001',quote_id:body.quote_id,masked_phone:'010-****-5678'});
    }
    if(url==='/api/mvp3/purchase-inquiries/form')return reply(200,{ok:true,topics:['기타'],consent_text:'일반 문의 동의'});
    return reply(200,{ok:true,quotes:[],has_more:false});
  }});
  w.eval(read('live-flow.js'));
  const create=w.MVP3LiveFlow.createFlow;let flow;
  w.MVP3LiveFlow.createFlow=(...args)=>{flow=create(...args);return flow;};
  w.eval(read('live-photo.js'));w.eval(read('app.js'));
  return {w,d:w.document,get flow(){return flow;},errors,calls,tabs,server,close:()=>dom.window.close(),
    posts:u=>calls.filter(c=>c.method==='POST'&&(typeof u==='string'?c.url===u:u.test(c.url))),
    puts:()=>calls.filter(c=>c.method==='PUT')};
}
async function toDetail(h){
  const d=h.d,input=d.querySelector('#request');input.value='게임 150만원';input.dispatchEvent(new h.w.Event('input',{bubbles:true}));
  d.querySelector('#chat-form').dispatchEvent(new h.w.Event('submit',{bubbles:true,cancelable:true}));
  await until(()=>d.querySelector('.live-product-card [data-action=detail]'));
  d.querySelector('.live-product-card [data-action=detail]').click();
  await until(()=>h.flow.state.screen==='detail'&&d.querySelector('.public-bom'));
}
async function toFinal(h){await toDetail(h);h.d.querySelector('#actions [data-action=final]').click();await until(()=>h.flow.state.screen==='final');}
const keepDlg=h=>h.d.querySelector('[data-keep-dialog]');
async function openKeep(h){h.d.querySelector('[data-action=save]').click();await until(()=>keepDlg(h));}
const fill=(h,name,value)=>{const e=keepDlg(h).querySelector('[data-keep='+name+']');if(e.type==='checkbox')e.checked=value;else e.value=value;e.dispatchEvent(new h.w.Event('input',{bubbles:true}));};
const submitKeep=h=>keepDlg(h).querySelector('[data-kact=submit]').click();
// 쓰기 요청(POST·PUT)이 한 건도 없었는지 -- 읽기(GET)와 상담·추천 조회는 센다.
const WRITES=/^\/api\/mvp3\/(saved-quotes|purchase-inquiries\/from-quote)/;   // POST 만 센다(PUT 은 h.puts())

// ===== ① 쇼핑몰 완제품 =====
test('mall PC 이동: tab is opened on the click, the handoff is recorded once, and only after it succeeds the tab goes to the mall URL',async()=>{
  const h=harness();try{await toDetail(h);const d=h.d;
    d.querySelector('[data-action=build-options][data-ordinal="1"]').click();
    d.querySelector('[data-action=mall-move]').click();
    // 누른 순간 새 창은 이미 열려 있고, 서버 응답 전에는 아직 주소가 없다(팝업 차단을 피한다).
    assert.equal(h.tabs.length,1);assert.equal(h.tabs[0].location.href,'');
    await until(()=>d.querySelector('[data-mall-state=moved]'));
    assert.equal(h.tabs[0].location.href,MALL);assert.equal(h.posts(/\/handoff$/).length,1);
    assert.deepEqual(h.posts(WRITES).map(c=>c.url),['/api/mvp3/saved-quotes','/api/mvp3/saved-quotes/'+qid+'/handoff']);
    assert.equal(h.posts('/api/mvp3/saved-quotes')[0].body.purpose,'handoff');
    assert.equal(h.posts(/purchase-inquiries/).length,0,'이동은 상담 신청이 아니다');
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('mall PC 이동: popup blocked shows the same URL as a link and never issues a second handoff',async()=>{
  const h=harness({popup:false});try{await toDetail(h);const d=h.d;
    d.querySelector('[data-action=build-options][data-ordinal="0"]').click();d.querySelector('[data-action=mall-move]').click();
    await until(()=>d.querySelector('[data-mall-state=moved]'));
    assert.match(text(d.querySelector('[data-mall-dialog]')),/새 창이 열리지 않았어요/);
    const again=d.querySelector('[data-mall-reopen]');assert.equal(again.getAttribute('href'),MALL);assert.equal(again.getAttribute('target'),'_blank');
    assert.equal(h.posts(/\/handoff$/).length,1);
    assert.match(text(d.querySelector('[data-mall-dialog]')),/HO-5001/);
  }finally{h.close();}
});

test('mall PC 이동: a failed handoff closes the pre-opened tab, shows no completion, and 다시 연결하기 reuses the flow',async()=>{
  const h=harness({handoff:'fail'});try{await toDetail(h);const d=h.d;
    d.querySelector('[data-action=build-options][data-ordinal="0"]').click();d.querySelector('[data-action=mall-move]').click();
    await until(()=>d.querySelector('[data-mall-state=failed]'));
    const t=text(d.querySelector('[data-mall-dialog]'));
    assert.match(t,/상품 페이지를 열지 못했어요\./);assert.match(t,/현재 구성은 그대로예요\. 잠시 후 다시 시도해 주세요\./);
    assert.doesNotMatch(t,/HO-|원하는 옵션을 선택해 주세요/);
    assert.equal(h.tabs.length,1);assert.equal(h.tabs[0].closed,true);assert.equal(h.tabs[0].location.href,'');
    assert.equal(h.flow.state.error,null,'detail screen carries no stray error panel');
    assert.equal(text(d.querySelector('[data-action=mall-move]')),'다시 연결하기');
    assert.equal(h.posts('/api/mvp3/saved-quotes').length,1,'save is not repeated');
  }finally{h.close();}
});

test('mall PC with no verified URL: 변경 explains it cannot connect and never records a handoff or opens a tab',async()=>{
  const nourl={...pc};delete nourl.mall_url;
  const h=harness({product:nourl});try{await toDetail(h);const d=h.d;
    d.querySelector('[data-action=build-options][data-ordinal="0"]').click();
    const t=text(d.querySelector('[data-mall-dialog]'));
    assert.match(t,/상품 페이지를 확인하고 있어요\./);assert.match(t,/지금은 연결할 수 없어요\. 상품 주소를 확인한 뒤 다시 안내해 드릴게요\./);
    assert.equal(d.querySelector('[data-action=mall-move]'),null,'이동 단추가 없다');
    assert.equal(d.querySelector('.dv2-panel'),null,'AI 부품 선택으로 바뀌지 않는다');
    assert.equal(h.tabs.length,0);assert.equal(h.posts(WRITES).length,0);
  }finally{h.close();}
});

// ===== ② 견적 보관과 연락처 =====
test('first 견적 저장: asks for phone (required) + consent, shows the no-call line and sends nothing until both are given',async()=>{
  const h=harness({has:false});try{await toFinal(h);const d=h.d;await openKeep(h);
    const t=text(keepDlg(h));
    assert.match(t,/견적 보관/);assert.match(t,/전화번호는 처음 보관할 때 한 번만 입력해 주세요\./);assert.match(t,/상담을 신청하기 전에는 먼저 연락드리지 않아요\./);
    assert.match(t,/전화번호 필수/);assert.match(t,/이름 선택/);assert.match(t,/이메일 선택/);assert.match(t,/서버 동의 문구/);
    assert.equal(keepDlg(h).querySelector('[data-keep=consent]').checked,false,'동의는 미리 체크하지 않는다');
    assert.match(t,/PC 12/);assert.match(t,/1,300,000원/);
    submitKeep(h);assert.match(text(keepDlg(h)),/전화번호를 입력해 주세요/);
    fill(h,'phone','abc');submitKeep(h);assert.match(text(keepDlg(h)),/전화번호 형식을 확인해 주세요/);
    fill(h,'phone','010-1234-5678');submitKeep(h);assert.match(text(keepDlg(h)),/개인정보 수집·이용에 동의해 주세요/);
    assert.equal(h.posts('/api/mvp3/saved-quotes').length,0,'입력만으로 보관을 보내지 않는다');
    assert.equal(h.flow.state.saveState,'idle');
    // 취소는 구성·화면을 그대로 둔다.
    keepDlg(h).querySelector('[data-kact=cancel]').click();assert.equal(keepDlg(h),null);
    assert.equal(h.flow.state.screen,'final');assert.equal(h.flow.state.selected.price,1300000);assert.equal(h.posts(WRITES).length,0);
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('first save with phone + consent: one POST carries the contact, success shows 견적을 보관했어요 + quote number + masked phone, nothing else is created',async()=>{
  const h=harness({has:false});try{await toFinal(h);const d=h.d;await openKeep(h);
    fill(h,'phone',' 010-1234-5678 ');fill(h,'consent',true);submitKeep(h);
    await until(()=>h.flow.state.saveState==='saved'&&!keepDlg(h));
    const posts=h.posts('/api/mvp3/saved-quotes');assert.equal(posts.length,1);
    assert.deepEqual(posts[0].body.contact,{phone:'010-1234-5678',consent:true},'빈 이름·이메일은 보내지 않는다');
    assert.equal(posts[0].body.purpose,undefined);
    const panel=text(d.querySelector('[data-keep-done]'));
    assert.match(panel,/견적을 보관했어요/);assert.match(panel,/보관 견적 Q-55555555/);assert.match(panel,/등록된 연락처 010-\*\*\*\*-5678/);
    assert.match(panel,/상담을 신청하기 전에는 먼저 연락드리지 않아요\./);assert.match(panel,/필요할 때 상담을 신청해 주세요\./);
    assert.doesNotMatch(panel,/010-1234-5678/,'전체 번호는 화면에 없다');
    assert.equal(h.posts(/purchase-inquiries/).length,0,'보관만으로 상담 신청이 생기지 않는다');
    // 전화번호는 보관 복구 기록(sessionStorage)에도 남지 않는다.
    for(let i=0;i<h.w.sessionStorage.length;i++)assert.ok(!String(h.w.sessionStorage.getItem(h.w.sessionStorage.key(i))).includes('010-1234-5678'));
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('second save reuses the registered contact: masked phone only, no inputs, no phone sent; 연락처 변경 opens inputs only when clicked and cancel keeps the old number',async()=>{
  const h=harness({has:true});try{await toFinal(h);const d=h.d;await openKeep(h);
    const t=text(keepDlg(h));
    assert.match(t,/등록한 연락처로 새 견적을 보관해요\./);assert.match(t,/등록된 연락처 010-\*\*\*\*-5678/);assert.match(t,/상담을 신청하기 전에는 먼저 연락드리지 않아요\./);
    assert.equal(keepDlg(h).querySelectorAll('[data-keep]').length,0,'전화번호·이름·이메일·동의를 다시 받지 않는다');
    keepDlg(h).querySelector('[data-kact=edit]').click();
    assert.equal(keepDlg(h).querySelectorAll('[data-keep]').length,4);
    keepDlg(h).querySelector('[data-kact=edit-cancel]').click();
    assert.equal(keepDlg(h).querySelectorAll('[data-keep]').length,0);assert.match(text(keepDlg(h)),/010-\*\*\*\*-5678/);
    submitKeep(h);await until(()=>h.flow.state.saveState==='saved'&&!keepDlg(h));
    const posts=h.posts('/api/mvp3/saved-quotes');assert.equal(posts.length,1);assert.equal(posts[0].body.contact,undefined);
    assert.equal(h.puts().length,0);
  }finally{h.close();}
});

test('changing the contact while saving sends the new contact together with the quote (the old number is kept until then)',async()=>{
  const h=harness({has:true});try{await toFinal(h);await openKeep(h);
    keepDlg(h).querySelector('[data-kact=edit]').click();
    fill(h,'phone','010-9999-0000');fill(h,'name','홍길동');fill(h,'email','a@b.co');fill(h,'consent',true);submitKeep(h);
    await until(()=>h.flow.state.saveState==='saved');
    assert.deepEqual(h.posts('/api/mvp3/saved-quotes')[0].body.contact,{phone:'010-9999-0000',consent:true,name:'홍길동',email:'a@b.co'});
  }finally{h.close();}
});

test('save failure (design 14): says it failed with the reason, keeps the configuration, shows no 보관했어요, and 다시 보관하기 retries',async()=>{
  const h=harness({has:true,saveFail:1});try{await toFinal(h);const d=h.d;await openKeep(h);
    submitKeep(h);await until(()=>keepDlg(h)?.querySelector('.keep-error'));
    const t=text(keepDlg(h));
    assert.match(t,/견적을 보관하지 못했어요\./);assert.match(t,/선택한 부품과 금액은 그대로예요\./);assert.match(t,/서버 점검 중|잠시 후 다시/);
    assert.equal(keepDlg(h).querySelector('.keep-error').getAttribute('role'),'alert');
    assert.equal(text(keepDlg(h).querySelector('[data-kact=submit]')),'다시 보관하기');
    assert.equal(d.querySelector('[data-keep-done]'),null);assert.notEqual(h.flow.state.saveState,'saved');
    assert.equal(h.flow.state.selected.price,1300000);
    submitKeep(h);await until(()=>h.flow.state.saveState==='saved'&&!keepDlg(h));
    assert.match(text(d.querySelector('[data-keep-done]')),/견적을 보관했어요/);
  }finally{h.close();}
});

// ===== ③ 상담 신청 접수 =====
async function savedFinal(h){await toFinal(h);await openKeep(h);if(keepDlg(h).querySelector('[data-keep=phone]')){fill(h,'phone','010-1234-5678');fill(h,'consent',true);}submitKeep(h);await until(()=>h.flow.state.saveState==='saved'&&!keepDlg(h));}

test('상담 신청 접수: one click sends the quote id, shows PI number + quote number + masked phone only after success; the button is gone so no second PI',async()=>{
  const h=harness({has:true});try{await savedFinal(h);const d=h.d;
    const btn=d.querySelector('[data-action=consult-send]');assert.equal(text(btn),'상담 신청 접수');
    btn.click();assert.equal(btn.disabled||h.flow.state.phase==='consult',true,'sending disables the button');
    await until(()=>d.querySelector('[data-consult-done]'));
    const calls=h.posts('/api/mvp3/purchase-inquiries/from-quote');assert.equal(calls.length,1);
    assert.deepEqual(calls[0].body,{quote_id:qid});assert.match(calls[0].key,/^a{64}$/);
    const t=text(d.querySelector('[data-consult-done]'));
    assert.match(t,/상담 신청이 접수됐어요/);assert.match(t,/상담 신청 순서대로 연락드리겠습니다\./);
    assert.match(t,/상담 신청 번호 PI-1001/);assert.match(t,/함께 보낸 견적 Q-55555555/);assert.match(t,/연락받을 전화번호 010-\*\*\*\*-5678/);
    assert.match(t,/주문·결제는 아직 진행되지 않았어요/);assert.doesNotMatch(t,/오늘|시간 내|당일/);
    assert.equal(d.querySelector('[data-action=consult-send]'),null);
    assert.equal(h.posts('/api/mvp3/purchase-inquiries').length,0,'일반 문의 경로를 쓰지 않는다');
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('상담 내용 남기기 (선택): the message goes along; the topic is fixed (주문 희망 is chosen by the server)',async()=>{
  const h=harness({has:true});try{await savedFinal(h);const d=h.d;
    d.querySelector('[data-action=consult-note]').click();
    const ta=d.querySelector('[data-consult-message]');ta.value='저녁에 연락 주세요';ta.dispatchEvent(new h.w.Event('input',{bubbles:true}));
    assert.match(text(d.querySelector('.consult-note')),/주문 희망/);assert.match(text(d.querySelector('.consult-count')),/10 \/ 500자/);
    d.querySelector('[data-action=consult-send]').click();await until(()=>d.querySelector('[data-consult-done]'));
    assert.deepEqual(h.posts('/api/mvp3/purchase-inquiries/from-quote')[0].body,{quote_id:qid,message:'저녁에 연락 주세요'});
  }finally{h.close();}
});

test('already submitted for this quote: shows no new PI, offers 상담 접수 내역 보기 and the same PI number',async()=>{
  const h=harness({has:true,consult:'already'});try{await savedFinal(h);const d=h.d;
    d.querySelector('[data-action=consult-send]').click();await until(()=>d.querySelector('[data-consult-done=already]'));
    const box=d.querySelector('[data-consult-done]');
    assert.match(text(box),/이미 상담 신청이 접수된 견적이에요/);assert.doesNotMatch(text(box),/PI-1001/);
    const open=box.querySelector('[data-action=consult-rows]');assert.equal(text(open),'상담 접수 내역 보기');open.click();
    assert.match(text(d.querySelector('[data-consult-done]')),/상담 신청 번호 PI-1001/);
    assert.equal(h.posts('/api/mvp3/purchase-inquiries/from-quote').length,1);
  }finally{h.close();}
});

test('접수 failure (design 15): says it failed, keeps the saved quote and the typed message, shows no completion, and the button can retry',async()=>{
  const h=harness({has:true,consult:'fail'});try{await savedFinal(h);const d=h.d;
    d.querySelector('[data-action=consult-note]').click();
    const ta=d.querySelector('[data-consult-message]');ta.value='내용';ta.dispatchEvent(new h.w.Event('input',{bubbles:true}));
    d.querySelector('[data-action=consult-send]').click();await until(()=>d.querySelector('[data-consult-ask] .keep-error'));
    const t=text(d.querySelector('[data-consult-ask]'));
    assert.match(t,/상담 신청을 접수하지 못했어요\./);assert.match(t,/보관한 견적과 입력한 내용은 그대로예요\./);assert.match(t,/다시 신청해 주세요\./);
    assert.equal(d.querySelector('[data-consult-done]'),null);assert.equal(d.querySelector('[data-consult-message]').value,'내용');
    assert.ok(d.querySelector('[data-action=consult-send]')&&!d.querySelector('[data-action=consult-send]').disabled);
    assert.equal(h.flow.state.saveState,'saved');
  }finally{h.close();}
});

test('a quote saved without a contact (mall 이동) asks for the contact first when 상담 신청 접수 is pressed, then continues',async()=>{
  const h=harness({has:false,consult:'need_contact'});try{await toDetail(h);const d=h.d;
    // 쇼핑몰 이동으로 연락처 없이 보관된 견적이 있다.
    d.querySelector('[data-action=build-options][data-ordinal="0"]').click();d.querySelector('[data-action=mall-move]').click();await until(()=>d.querySelector('[data-mall-state=moved]'));
    d.querySelector('[data-action=mall-dialog-close]').click();
    d.querySelector('#actions [data-action=final]').click();await until(()=>h.flow.state.screen==='final'&&d.querySelector('[data-action=consult-send]'));
    d.querySelector('[data-action=consult-send]').click();await until(()=>keepDlg(h));
    assert.match(text(keepDlg(h)),/연락처 등록/);assert.match(text(keepDlg(h)),/상담 신청을 접수하려면 전화번호가 필요해요\./);
    assert.equal(d.querySelector('[data-consult-done]'),null);
    fill(h,'phone','010-9999-0000');fill(h,'consent',true);submitKeep(h);
    await until(()=>d.querySelector('[data-consult-done]'));
    assert.equal(h.puts().length,1);assert.equal(h.posts('/api/mvp3/purchase-inquiries/from-quote').length,2,'first 409, then the retry after the contact is saved');
  }finally{h.close();}
});

test('connected API client: contact and from-quote use the access key; PUT is allowed only for /api/mvp3/contact',async()=>{
  const h=harness({has:true});try{await savedFinal(h);const d=h.d;
    d.querySelector('[data-action=consult-send]').click();await until(()=>d.querySelector('[data-consult-done]'));
    for(const c of h.calls.filter(c=>c.url.startsWith('/api/mvp3/contact')||c.url.endsWith('/from-quote')))assert.match(c.key,/^a{64}$/,c.url);
    await assert.rejects(()=>h.w.MVP3Api.request('PUT','/api/mvp3/saved-quotes',{}),e=>e.code==='unsupported');
    await assert.rejects(()=>h.w.MVP3Api.request('DELETE','/api/mvp3/contact'),e=>e.code==='unsupported');
  }finally{h.close();}
});
