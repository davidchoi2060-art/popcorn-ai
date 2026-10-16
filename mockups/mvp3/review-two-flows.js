/* 두 구매 흐름 검수용 예시 화면(2026-10-16 코덱스 독립 재검수 P2 요청 「실고객정보 없이 검수 가능한 안전한 경로나 fixture」).
   review-two-flows.html 에서만 읽는다. 서버에 아무것도 보내지 않는다 -- fetch 를 이 파일의 예시 응답으로 바꾸고,
   새 창(window.open)은 실제로 열지 않으며, 브라우저 보관함도 이 탭 메모리로만 쓴다(같은 주소의 실제 보관 기록을 건드리지 않는다).
   금액·번호·이름은 전부 예시다. 실제 연락처를 넣지 말 것 -- 자동 입력은 010-0000-0000(존재하지 않는 예시 번호)만 쓴다.

   주소 매개변수
     case    ai(기본) | mall | mall-nourl | mall-fail     상품 종류와 몰 연결 결과
     has     1                                           연락처가 이미 등록된 고객(다음 견적 보관 · 승인 08)
     save    fail | unknown                              fail = 확정 실패 422(승인 14 · 다시 보관하기) · unknown = 응답 불명 503(복구 안내)
     consult fail | already                              상담 접수 실패(승인 15) · 이미 접수된 견적
     close   cancel | x | esc                            step=pick(맞춤 후보 패널)·step=ask(완제품 안내창, 승인 04) 뒤 그 방법으로 닫는다
     step    detail(기본) | open | pick | change | keep | kept | consult | done | ask | moved
             open = 쿨러 후보 패널을 연 채(승인 06) · pick = 후보를 임시로 고른 채(적용 전) · change = 쿨러를 바꿔 적용한 상세 · ask = 완제품 「변경」 안내창(승인 02)
     w       390 처럼 숫자를 주면 화면 폭 안내만 붙인다(실제 폭은 브라우저 창으로 맞춘다) */
(function(){'use strict';
const q=new URLSearchParams(location.search),CASE=q.get('case')||'ai',STEP=q.get('step')||'detail';
const CLOSE=q.get('close')||'',AI=CASE==='ai',HAS=q.get('has')==='1',SAVE=q.get('save')||'ok',SAVE_FAIL=SAVE==='fail'||SAVE==='unknown',CONSULT=q.get('consult')||'ok';
// 이 탭 메모리 보관함 -- 같은 주소의 실제 보관 키·견적 기록과 섞이지 않게 한다.
function memStore(){const m=new Map();return {getItem:k=>m.has(k)?m.get(k):null,setItem:(k,v)=>{m.set(k,String(v));},removeItem:k=>{m.delete(k);},clear:()=>m.clear(),key:i=>[...m.keys()][i]??null,get length(){return m.size;}};}
for(const name of ['localStorage','sessionStorage'])try{Object.defineProperty(window,name,{value:memStore(),configurable:true});}catch{}
const QID='5a5a5a5a-1016-4001-8001-000000000001',SAMPLE_URL='https://example.com/popcornpc-sample-product';
const role=r=>'이 부품은 '+r+' 역할을 해요.';
const part=(ordinal,slot,name,extra={})=>({ordinal,slot,quantity:1,pseudo:false,name,description:role(slot),specs:[],...extra});
const parts=AI?[part(0,'CPU','인텔 코어 i5-12400'),{ordinal:1,slot:'GPU',quantity:1,pseudo:true,name:null,description:null,specs:[]},
  part(2,'RAM','삼성 DDR4 16GB (8GB × 2)'),part(3,'SSD','WD Blue SN5100 NVMe 500GB'),part(4,'MB','GIGABYTE H610M H V2 D4'),part(5,'COOLER','기본 쿨러'),part(6,'PSU','AONE TFX-500P KC 500W'),part(7,'CASE','DAVEN N1 MESH 화이트')]:
  [part(0,'CPU','인텔 코어 i5-12400F'),part(1,'GPU','PALIT 지포스 RTX 5060 DUAL OC 8GB'),part(2,'RAM','삼성 DDR4 16GB (8GB × 2)'),part(3,'SSD','WD Blue SN5100 NVMe 500GB'),
  part(4,'MB','GIGABYTE H610M H V2 D4'),part(5,'COOLER','JIUSHARK JF120R'),part(6,'PSU','마이크로닉스 COOLMAX ELITE II 600W'),part(7,'CASE','앱코 U30 마린 블랙')];
const CODE=AI?91001:98149,BASE=AI?891700:1627700;
const configuration={product_code:CODE,configuration_id:'R'+CODE,revision:1,offer_id:'P'+CODE,description:{title:null,intro:null,scene:null,benefits:[],checks:[],faq:[]},parts,
  price:{state:'unknown',amount:null,checked_at:null,observed_date:null,model:null},stock:{state:'unknown',checked_at:null},
  compatibility:{document_state:'pass',public_summary:null,assembly_state:'unknown'},photo:{state:'unresolved',url:null},
  customer_conditions:Object.fromEntries(['os','keyboard','mouse','monitor','warranty'].map(k=>[k,{state:'unknown',detail:'',months:null,needs_reconfirmation:false,customer_statement:'구매 전에 확인해 주세요.'}]))};
const product=AI?{ai_composed:true,product_code:CODE,name:'문서·인터넷 작업을 위한 나의 PC',price:BASE,price_src:'예시 금액',spec:{cpu:'i5-12400',ram_gb:16,ssd_gb:500,gpu:'UHD 730'},
    reasons:['문서 작업 · 인터넷 · 여러 창을 함께 사용'],over_budget:false,tag:'추천 구성',role:'recommended',public_configuration:configuration}:
  {product_code:CODE,name:'골드 인텔 게이밍 PC',price:BASE,price_src:'예시 금액',spec:{cpu:'i5-12400F',ram_gb:16,ssd_gb:500,gpu:'RTX 5060'},reasons:['FHD 게임을 편하게 즐기는 구성'],
    over_budget:false,tag:'추천 구성',role:'recommended',public_configuration:configuration,...(CASE==='mall-nourl'?{}:{mall_url:SAMPLE_URL})};
const talk={usages:[AI?'사무':'게임'],budget_won:AI?1000000:1700000,budget_bound:'이하'};
const change={ordinal:5,slot:'COOLER',label:'쿨러',quantity:1,before:{product_code:7001,name:'기본 쿨러',price:0},after:{product_code:7002,name:'3RSYS Socool RC750N PWM',price:17000},delta:17000};
const server={has:HAS,saved:null,inquiry:CONSULT==='already',topic:null};
const reply=(status,data)=>Promise.resolve(new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}}));
const slow=(ms,v)=>new Promise(r=>setTimeout(()=>r(v),ms));
window.fetch=async(url,init={})=>{
  const path=String(url),method=init.method||'GET',body=init.body?JSON.parse(init.body):null;
  await slow(120);
  if(path==='/api/talk/parse')return reply(200,{ok:true,state:talk,history:[],missing:[]});
  if(path==='/api/grid/recommend')return reply(200,{ok:true,assumed:[],anchor_code:CODE,wants:{},card_sets:[{kind:'sold',usage:talk.usages[0],usage_grid:talk.usages[0],items:[product]}],talk_notes:[],choices:[]});
  if(path==='/api/mvp3/build/options')return reply(200,{ok:true,base_code:CODE,ordinal:body.ordinal,slot:'COOLER',label:'쿨러',quantity:1,current:{product_code:7001,name:'기본 쿨러',price:0},total:BASE,checked:2,untested:0,
    note:'호환 규칙을 모두 통과한 판매 중 부품만 보여 드려요.',options:[{product_code:7002,name:'3RSYS Socool RC750N PWM',price:17000,price_diff:17000,total:BASE+17000}]});
  if(path==='/api/mvp3/build/quote'){const ch=(body.changes||[]).length;return reply(200,{ok:true,base_code:CODE,base_price:BASE,total:ch?BASE+17000:BASE,changes:ch?[change]:[],compat:{ok:true}});}
  if(path==='/api/mvp3/contact'&&method==='GET')return reply(200,{ok:true,has_contact:server.has,masked_phone:server.has?'010-****-0000':null,name:null,
    consent_text:'(예시) 견적 보관과 고객이 요청한 구매 상담 연락에 전화번호(필수)·이름·이메일(선택)을 씁니다. 실제 동의 문구는 서버가 줍니다.'});
  if(path==='/api/mvp3/contact'&&method==='PUT'){server.has=true;return reply(200,{ok:true,has_contact:true,masked_phone:'010-****-0000',name:null});}
  if(path.startsWith('/api/mvp3/saved-quotes')&&method==='GET')return reply(200,{ok:true,quotes:server.saved?[server.saved]:[],has_more:false});
  if(path==='/api/mvp3/saved-quotes'&&method==='POST'){
    if(body.purpose!=='handoff'){
      // fail = 서버가 보관하지 않고 돌려보냄(확정 실패 422 · 승인 14) / unknown = 응답 불명(503 · 복구 안내, 다시 보내지 않음)
      if(SAVE==='fail')return reply(422,{detail:'검수용 예시 · 보관하지 않았어요.'});
      if(SAVE==='unknown')return reply(503,{detail:'검수용 예시 · 응답 불명'});
      if(!body.contact&&!server.has)return reply(422,{detail:{error:'contact_required',contact_required:true,detail:'견적을 보관하려면 전화번호를 입력하고 개인정보 수집·이용에 동의해 주세요.'}});
      if(body.contact)server.has=true;
    }
    const price=body.expected_price,build=body.changes?.length?{base_price:BASE,changes:[change]}:undefined;
    server.saved={id:QID,product:{...product,price,...(build?{build}:{}),...(body.sets?{sets:body.sets}:{})},state:body.state,saved_at:new Date().toISOString()};
    return reply(200,{ok:true,quote:server.saved,contact:server.has?{has_contact:true,masked_phone:'010-****-0000',name:null}:{has_contact:false,masked_phone:null,name:null}});
  }
  if(path.endsWith('/handoff')){
    if(CASE==='mall-fail')return reply(502,{detail:'검수용 예시 · 연결 실패'});
    return reply(200,{ok:true,handoff_no:'HO-예시',quote_id:QID,product_code:CODE,name:product.name,price_quoted:BASE,price_mall:BASE,mall_status:'확인됨',mall_url:SAMPLE_URL,changes:[]});
  }
  if(path==='/api/mvp3/purchase-inquiries/form')return reply(200,{ok:true,topics:['여러 대 구매','할인','세금계산서·영수증','주문 희망','기타'],consent_text:'(예시) 일반 문의 동의'});
  if(path==='/api/mvp3/purchase-inquiries/from-quote'){
    if(CONSULT==='fail')return reply(503,{detail:'검수용 예시 · 접수 실패'});
    const already=server.inquiry;server.inquiry=true;
    return reply(200,{ok:true,already,inquiry_no:'PI-1016',quote_id:body.quote_id,masked_phone:'010-****-0000'});
  }
  return reply(404,{detail:'검수용 예시에 없는 요청'});
};
// 새 창은 열지 않는다(예시 주소로도 이동하지 않는다). 「팝콘PC로 이동」이 성공했는지는 화면의 이동 뒤 안내로 확인한다.
window.open=()=>{const t={opener:{},closed:false,location:{href:''},document:{title:''},close(){t.closed=true;}};return t;};
const banner=()=>{const b=document.createElement('p');b.className='review-banner';b.setAttribute('role','note');b.textContent='검수용 예시 화면 · 서버에 저장·접수되지 않아요 · 금액·번호는 예시';document.body.prepend(b);};
const wait=async(fn,n=200)=>{for(let i=0;i<n;i++){const v=fn();if(v)return v;await slow(30);}throw new Error('검수 예시: 화면이 기대한 상태로 오지 않았어요');};
const $=s=>document.querySelector(s),click=s=>$(s).click();
function fill(name,value){const e=$('[data-keep-page] [data-keep='+name+']');if(!e)return;if(e.type==='checkbox')e.checked=value;else e.value=value;e.dispatchEvent(new Event('input',{bubbles:true}));}
async function drive(){
  banner();
  const input=await wait(()=>$('#request'));
  if(location.hash!=='#welcome')location.hash='#welcome';
  input.value=AI?'문서 작업용 PC 100만원':'게임용 PC 170만원';input.dispatchEvent(new Event('input',{bubbles:true}));
  $('#chat-form').requestSubmit();
  (await wait(()=>$('.live-product-card [data-action=detail]'))).click();
  await wait(()=>$('.tf-detail'));
  if(STEP==='detail')return;
  if(!AI){
    if(STEP==='ask'){click('[data-action=build-options][data-ordinal="1"]');
      // 승인 04(취소 뒤): close=cancel|x|esc 로 안내창을 닫는다 -- 상세·금액은 그대로, 초점은 누른 「변경」으로 돌아간다
      if(CLOSE){await wait(()=>$('[data-mall-dialog]'));
        if(CLOSE==='cancel')click('[data-mall-dialog] [data-action=mall-dialog-close]:not(.mall-dlg-x)');
        else if(CLOSE==='x')click('[data-mall-dialog] .mall-dlg-x');
        else if(CLOSE==='esc')$('[data-mall-dialog]').dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));}
      return;}
    if(STEP==='moved'){click('[data-action=mall-view]');await wait(()=>$('[data-mall-state=moved],[data-mall-state=failed]'));}
    return;
  }
  click('[data-action=build-options][data-ordinal="5"]');
  const radio=await wait(()=>$('[data-dv2-radio][value="7002"]'));
  if(STEP==='open')return;   // 승인 06: 후보 패널을 연 채(아직 아무것도 고르지 않음)
  radio.checked=true;radio.dispatchEvent(new Event('change',{bubbles:true}));
  if(STEP==='pick'){         // 후보를 임시로 골랐지만 적용 전 -- 표·금액은 원 구성 그대로
    if(CLOSE==='cancel')click('.dv2-panel .dv2-cancel');
    else if(CLOSE==='x')click('.dv2-panel .dv2-x');
    else if(CLOSE==='esc')document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
    return;
  }
  click('[data-dv2-apply]');await wait(()=>$('[data-pc-total-move]'));
  if(STEP==='change')return;
  click('[data-action=save]');await wait(()=>$('[data-keep-page]'));
  if(STEP==='keep')return;
  if(!HAS){fill('phone','010-0000-0000');fill('consent',true);}
  click('[data-keep-page] [data-kact=submit]');
  await wait(()=>$('.tf-kept')||$('[data-keep-retry]')||(SAVE==='unknown'&&!$('[data-keep-page]')&&$('.live-recovery [data-action=recover]')));
  if(STEP==='kept'||SAVE_FAIL)return;
  if(STEP==='consult'){click('[data-action=consult-note]');await wait(()=>$('.tf-consult select'));return;}
  if(STEP==='done'){click('[data-action=consult-send]');await wait(()=>$('.tf-done')||$('.tf-consult .tf-alert')||$('[data-consult-done]'));}
}
document.addEventListener('DOMContentLoaded',()=>{void drive().catch(e=>{const p=document.createElement('p');p.className='review-banner is-error';p.textContent=e.message;document.body.prepend(p);});});
})();
