/* Async consultation and saving state. A generation owns each pending response. */
(function(root){'use strict';
  const M=typeof module!=='undefined'?require('./live-model.js'):root.MVP3LiveModel;
  const JOURNAL_KEY='popcorn-mvp3-pending-save-v1';
  // 상담 한 번에 보낼 수 있는 글자 수. 서버는 긴 글을 막지 않고 앞 800자와 끝 200자를 읽은 뒤 그 사실을 알린다(api/talk.py _read_long).
  const MAX_TEXT=20000;
  // 같은 구성을 몇 대까지 한 번에 견적하나(api/mvp3_quantity.MAX_SETS 와 같은 값).
  const MAX_SETS=10;
  function validPending(record){
    const p=record?.payload;
    return M.object(record)&&record.version===1&&/^[a-f0-9]{64}$/.test(record.binding)&&M.object(p)
      &&['expected_price,product_code,request_id,state','changes,expected_price,product_code,request_id,state','expected_price,product_code,request_id,sets,state','changes,expected_price,product_code,request_id,sets,state'].includes(Object.keys(p).sort().join(','))
      &&(p.sets===undefined||Number.isSafeInteger(p.sets)&&p.sets>1&&p.sets<=MAX_SETS)
      &&(p.changes===undefined||Array.isArray(p.changes)&&p.changes.length>0&&p.changes.length<=8&&p.changes.every(c=>M.object(c)&&['ordinal,product_code','ordinal,product_code,quantity'].includes(Object.keys(c).sort().join(','))&&Number.isSafeInteger(c.ordinal)&&c.ordinal>=0&&Number.isSafeInteger(c.product_code)&&c.product_code>0
        &&(c.quantity===undefined||Number.isSafeInteger(c.quantity)&&c.quantity>=1&&c.quantity<=8)))
      &&M.uuid(p.request_id)&&Number.isInteger(p.product_code)&&p.product_code>0&&Number.isInteger(p.expected_price)&&p.expected_price>=0
      &&M.object(p.state)&&new TextEncoder().encode(JSON.stringify(p)).length<=16384;
  }
  function createJournal(options){
    let storage=options.sessionStorage,resolved=Object.prototype.hasOwnProperty.call(options,'sessionStorage');
    function target(){if(!resolved){storage=root.sessionStorage;resolved=true;}if(!storage)throw new Error('session storage');return storage;}
    return {
      read(){const raw=target().getItem(JOURNAL_KEY);if(!raw)return null;const record=JSON.parse(raw);if(!validPending(record))throw new Error('invalid journal');return record;},
      write(record){if(!validPending(record))throw new Error('invalid journal');const raw=JSON.stringify(record),s=target();s.setItem(JOURNAL_KEY,raw);if(s.getItem(JOURNAL_KEY)!==raw)throw new Error('storage');},
      clear(){target().removeItem(JOURNAL_KEY);}
    };
  }
  // 대화 상태 보관(2차 대화 중심 화면의 바닥 -- 2026-10-11). 새로고침해도 앞서 말한 조건과 대화,
  // 지금 보던 견적(상품 번호와 바꾼 부품)을 잃지 않게 이 탭(sessionStorage)에만 둔다. 가격·추천 카드는
  // 두지 않는다 -- 시간이 지나면 틀리므로 되살린 뒤 서버에 다시 묻는다(restoredCurrent).
  const CONVERSATION_KEY='popcorn-mvp3-conversation-v1',CONVERSATION_TTL_MS=6*3600*1000,CONVERSATION_MAX_BYTES=65536;
  const CONVERSATION_MAX_MESSAGES=60,CONVERSATION_MAX_TEXT=2000;
  // 카드번호·주민번호 모양의 숫자는 보관하기 전에 가린다(서버 api/talk_exceptions.mask_personal 과 같은 모양).
  // 가리는 것은 이 두 모양뿐이다 -- 전화번호·이메일·주소·이름은 가리지 않고, 보관은 이 탭 안 6시간이다.
  // 자르기 전에 가린다: 먼저 자르면 끝에 걸친 번호가 조각으로 남아 모양을 잃고 가려지지 않는다.
  function maskPersonal(t){return String(t).replace(/(?<!\d)\d{6}\s*-\s*[1-8]\d{6}(?!\d)/g,'[가림]').replace(/(?<!\d)\d{4}(?:[\s-]?\d{4}){3}(?!\d)/g,'[가림]');}
  // 보내지 않은 입력 문장의 화면 간 인계(코덱스 #148 검수 P2 -- 2026-10-11). 처음 화면 <-> 대화 화면은 문서를
  // 새로 열어 입력 칸이 비었다. 떠날 때 이 탭(sessionStorage)에만 잠깐 두고, 다음 화면이 한 번 읽고 바로 지운다.
  // 주소(URL)에는 절대 싣지 않고 자동으로 보내지도 않는다 -- 입력 칸에 다시 채워 고객이 고쳐 보낼 수 있게만 한다.
  const DRAFT_KEY='popcorn-mvp3-draft-handoff-v1',DRAFT_TTL_MS=10*60*1000;
  function createDraftHandoff(options={}){
    let storage=options.sessionStorage,resolved=Object.prototype.hasOwnProperty.call(options,'sessionStorage');
    function target(){if(!resolved){storage=root.sessionStorage;resolved=true;}if(!storage)throw new Error('session storage');return storage;}
    return {
      // 빈 문장이면 남아 있던 인계를 지운다(보낸 뒤 비운 칸이 옛 문장을 되살리지 않게).
      put(text,now=Date.now()){
        try{const t=maskPersonal(String(text||'')).slice(0,MAX_TEXT);
          if(!t.trim()){target().removeItem(DRAFT_KEY);return false;}
          target().setItem(DRAFT_KEY,JSON.stringify({version:1,saved_at:now,text:t}));return true;}catch{return false;}
      },
      take(now=Date.now()){
        try{const s=target(),raw=s.getItem(DRAFT_KEY);if(!raw)return '';s.removeItem(DRAFT_KEY);const r=JSON.parse(raw);
          return M.object(r)&&r.version===1&&Number.isFinite(r.saved_at)&&now-r.saved_at>=0&&now-r.saved_at<=DRAFT_TTL_MS
            &&typeof r.text==='string'&&r.text.trim()&&r.text.length<=MAX_TEXT?r.text:'';}catch{return '';}
      }
    };
  }
  function conversationSnapshot(state,now=Date.now()){
    const text=t=>maskPersonal(String(t||'')).slice(0,CONVERSATION_MAX_TEXT);
    const sel=state.selected;
    // 추천 조건(wants: 4K·램 하한 등 글에서 읽은 것)도 둔다 -- 없으면 옛 화면이 같은 조건의 추천을 다시 받지 못해
    // 대화 화면에서 고른 PC 를 찾지 못한다(2026-10-12 카드 검수: 4K 영상 PC 127317 이 사라짐).
    // shown: 이 대화에서 추천 카드를 이미 보여 줬는지. 카드는 보관하지 않으므로(값이 시간이 지나면 틀린다) 새로고침하면
    // 같은 조건으로 서버에 다시 묻는다 -- 없으면 「아래에서 골라 주세요」만 남고 고를 카드가 사라진다(2026-10-12 고객단 끝까지 검수 E16).
    return {version:1,saved_at:now,talk:M.object(state.talk)?M.copy(state.talk):null,...(M.object(state.wants)?{wants:M.copy(state.wants)}:{}),...(state.recommendation||state.restoredShown?{shown:true}:{}),
      chat_flow:M.object(state.chatFlow)?M.copy(state.chatFlow):null,
      history:(state.history||[]).slice(-6).filter(h=>h&&['user','assistant'].includes(h.role)).map(h=>({role:h.role,text:text(h.text)})),
      messages:(state.messages||[]).slice(-CONVERSATION_MAX_MESSAGES).filter(m=>m&&['user','ai'].includes(m.who)&&!m.pending).map(m=>({who:m.who,text:text(m.text)})),
      // 되살린 견적을 아직 다시 불러오기 전이면(selected 없음) 그 상품 번호를 지우지 않고 그대로 둔다.
      // 고를 때 조건(selection_state)도 함께 둔다 -- 그 뒤 조건을 바꿨으면 지금 조건의 추천에는 그 상품이 없을 수 있다.
      // 부품 바꾸기로 옮긴 PC 는 추천 목록에 없을 수 있어 어느 PC 의 어느 부품에서 옮겼는지(swap_from)도 둔다.
      current:sel&&Number.isInteger(sel.product_code)?{product_code:sel.product_code,changes:changesOf(sel),selection_state:M.object(state.selectionState)?M.copy(state.selectionState):null,...(M.object(state.selectionWants)?{selection_wants:M.copy(state.selectionWants)}:{}),...(validQuery(state.selectionQuery)?{selection_query:M.copy(state.selectionQuery)}:{}),...(validSwapFrom(sel.swap_from)?{swap_from:M.copy(sel.swap_from)}:{}),...(validSets(sel.sets)?{sets:sel.sets}:{})}
        :state.restoredCurrent?M.copy(state.restoredCurrent):null};
  }
  function validSets(n){return Number.isSafeInteger(n)&&n>1&&n<=MAX_SETS;}
  function validQuery(q){return M.object(q)&&['cheaper','better'].includes(q.nav)&&Number.isSafeInteger(q.anchor_code)&&q.anchor_code>0?{nav:q.nav,anchor_code:q.anchor_code}:null;}
  function validSwapFrom(x){return M.object(x)&&Number.isSafeInteger(x.product_code)&&x.product_code>0&&['cpu','gpu','ram','ssd'].includes(x.slot);}
  function validConversation(r,now=Date.now()){
    return M.object(r)&&r.version===1&&Number.isFinite(r.saved_at)&&now-r.saved_at>=0&&now-r.saved_at<=CONVERSATION_TTL_MS
      &&(r.talk===null||M.object(r.talk))&&(r.chat_flow===null||M.object(r.chat_flow))&&(r.wants===undefined||r.wants===null||M.object(r.wants))
      &&Array.isArray(r.history)&&r.history.length<=6&&r.history.every(h=>M.object(h)&&['user','assistant'].includes(h.role)&&typeof h.text==='string')
      &&Array.isArray(r.messages)&&r.messages.length<=CONVERSATION_MAX_MESSAGES&&r.messages.every(m=>M.object(m)&&['user','ai'].includes(m.who)&&typeof m.text==='string')
      &&(r.current===null||M.object(r.current)&&Number.isInteger(r.current.product_code)&&r.current.product_code>0&&Array.isArray(r.current.changes)
        &&(r.current.selection_state===undefined||r.current.selection_state===null||M.object(r.current.selection_state))
        &&(r.current.selection_wants===undefined||r.current.selection_wants===null||M.object(r.current.selection_wants))
        &&(r.current.selection_query===undefined||validQuery(r.current.selection_query)!==null)
        &&(r.current.swap_from===undefined||validSwapFrom(r.current.swap_from))&&(r.current.sets===undefined||validSets(r.current.sets)));
  }
  function createConversationStore(options){
    let storage=options.sessionStorage,resolved=Object.prototype.hasOwnProperty.call(options,'sessionStorage');
    function target(){if(!resolved){storage=root.sessionStorage;resolved=true;}if(!storage)throw new Error('session storage');return storage;}
    return {
      read(now=Date.now()){const raw=target().getItem(CONVERSATION_KEY);if(!raw)return null;const r=JSON.parse(raw);return validConversation(r,now)?r:null;},
      write(record){const raw=JSON.stringify(record);if(raw.length>CONVERSATION_MAX_BYTES)return false;target().setItem(CONVERSATION_KEY,raw);return true;},
      clear(){target().removeItem(CONVERSATION_KEY);}
    };
  }
  // 구매 상담 신청 칸의 상태. 서버가 준 주제·동의 문구만 쓰고, 받은 신청 번호만 보여 준다.
  function emptyInquiry(){return {open:false,human:false,meta:null,draft:{topic:'',name:'',phone:'',email:'',message:'',consent:false},done:null,error:''};}
  const PHONE_RE=/^0\d{1,2}-?\d{3,4}-?\d{4}$/, EMAIL_RE=/^[^@\s]{1,64}@[^@\s]{1,100}\.[^@\s]{2,}$/;
  function inquiryProblem(d,meta){
    if(!meta||!meta.topics.includes(d.topic))return '문의 주제를 골라 주세요.';
    const phone=String(d.phone||'').replace(/\s+/g,''),email=String(d.email||'').trim();
    if(!phone&&!email)return '전화번호나 이메일 중 하나는 적어 주세요.';
    if(phone&&!PHONE_RE.test(phone))return '전화번호 형식을 확인해 주세요. 예: 010-1234-5678';
    if(email&&!EMAIL_RE.test(email))return '이메일 형식을 확인해 주세요.';
    if(String(d.name||'').trim().length>30)return '이름은 30자 이내로 적어 주세요.';
    if(String(d.message||'').trim().length>500)return '문의 내용은 500자 이내로 적어 주세요.';
    if(d.consent!==true)return '연락처를 받으려면 개인정보 수집에 동의해 주세요.';
    return '';
  }
function inquiryHtml(q,{phase=null}={}){
  const state={phase};if(!q.open&&!q.done)return '';
  // 「사람 상담 남기기」 단추로 열었으면 구매 상담 문구 대신 일반 상담 문구를 쓴다(코덱스 PR136 검수 「신청 문구의 범위」).
  const button=(label,action,cls='',attrs='')=>'<button type="button" data-action="'+action+'" class="'+cls+'" '+attrs+'>'+label+'</button>';
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const human=!!q.human,title=human?'사람 상담 남기기':'구매 상담 신청';
  if(q.done)return '<section class="live-explanation live-inquiry" role="status" data-inquiry-done><h3>'+title+'</h3><p>'+esc(q.done.note)+'</p>'+
    '<p class="muted">신청 번호 '+esc(q.done.inquiry_no)+' · 주문과 결제는 아직 진행되지 않았어요.</p></section>';
  const busy=state.phase==='inquiry'||state.phase==='inquiry-form',d=q.draft;
  const err=q.error?'<p class="live-inquiry-error" role="alert" tabindex="-1">'+esc(q.error)+'</p>':'';
  if(!q.meta)return '<section class="live-explanation live-inquiry" data-inquiry-form><h3>'+title+'</h3>'+
    (busy?'<p class="muted">신청 양식을 불러오는 중이에요.</p>':err+button('다시 불러오기','inquiry-open','outline',human?'data-human="1"':''))+'</section>';
  const field=(name,label,input)=>'<label class="live-inquiry-field"><span>'+label+'</span>'+input+'</label>';
  const dis=busy?' disabled':'';
  return '<section class="live-explanation live-inquiry" data-inquiry-form><h3>'+title+'</h3>'+
    '<p class="muted">'+(human?'상담에서 바로 답하기 어려운 내용은 팝콘PC 담당자가 연락드려 안내해요.':'여러 대 구매 · 할인 · 세금계산서처럼 상담에서 정할 수 없는 내용은 팝콘PC 담당자가 연락드려 안내해요.')+' 이 신청으로 주문이나 결제가 진행되지는 않아요.</p>'+
    field('topic','문의 주제','<select data-inquiry="topic"'+dis+'><option value="">주제를 골라 주세요</option>'+q.meta.topics.map(t=>'<option'+(d.topic===t?' selected':'')+'>'+esc(t)+'</option>').join('')+'</select>')+
    field('name','이름 (선택)','<input data-inquiry="name" maxlength="30" autocomplete="name" value="'+esc(d.name)+'"'+dis+'>')+
    field('phone','전화번호','<input data-inquiry="phone" type="tel" maxlength="20" autocomplete="tel" placeholder="010-1234-5678" value="'+esc(d.phone)+'"'+dis+'>')+
    field('email','이메일','<input data-inquiry="email" type="email" maxlength="120" autocomplete="email" value="'+esc(d.email)+'"'+dis+'>')+
    '<p class="muted live-inquiry-hint">전화번호나 이메일 중 하나는 적어 주세요.</p>'+
    field('message','문의 내용 (선택)','<textarea data-inquiry="message" maxlength="500" rows="3"'+dis+'>'+esc(d.message)+'</textarea>')+
    '<label class="live-inquiry-consent"><input type="checkbox" data-inquiry="consent"'+(d.consent?' checked':'')+dis+'><span>'+esc(q.meta.consent_text)+' 동의합니다.</span></label>'+
    err+'<div class="live-inquiry-buttons">'+button('닫기','inquiry-close','outline',busy?'disabled':'')+
    button(state.phase==='inquiry'?'보내는 중…':'신청 보내기','inquiry-send','primary',busy?'disabled':'')+'</div></section>';
}
  // 견적 보관 창(연락처) · 상담 신청 접수 · 쇼핑몰 이동 안내창의 상태 (2026-10-16 두 구매 흐름).
  // 연락처는 처음 보관할 때 한 번만 받는다. 전체 번호는 화면이 서버에서 되받지 않는다 -- 가린 번호만 들고 있다.
  // draft 는 고객이 지금 적는 값이라 이 탭 메모리에만 있고, 대화 보관(conversationSnapshot)·보관 복구(journal)에 싣지 않는다.
  function emptyContact(){return {loaded:false,has:false,masked:'',name:'',consentText:''};}
  function emptyKeep(){return {open:false,purpose:'save',after:null,editing:false,busy:false,error:'',failed:false,code:'',draft:{phone:'',name:'',email:'',consent:false}};}
  function emptyConsult(){return {open:false,message:'',topic:'',done:null,showRows:false,error:''};}
  function emptyMall(){return {open:false,step:'ask',error:'',blocked:false};}
  function contactProblem(d){
    const phone=String(d.phone||'').replace(/\s+/g,''),email=String(d.email||'').trim();
    if(!phone)return '전화번호를 입력해 주세요.';
    if(!PHONE_RE.test(phone))return '전화번호 형식을 확인해 주세요. 예: 010-1234-5678';
    if(email&&!EMAIL_RE.test(email))return '이메일 형식을 확인해 주세요.';
    if(String(d.name||'').trim().length>30)return '이름은 30자 이내로 적어 주세요.';
    if(d.consent!==true)return '개인정보 수집·이용에 동의해 주세요.';
    return '';
  }
  function contactPayload(d){
    const out={phone:String(d.phone).replace(/\s+/g,''),consent:true},name=String(d.name||'').trim(),email=String(d.email||'').trim();
    if(name)out.name=name;if(email)out.email=email;return out;
  }
  // 부품 바꾸기 칸의 상태. 열린 부품(slot)과 서버가 준 선택지만 든다.
  function emptyParts(){return {slot:null,data:null,error:''};}
  // 부품 직접 바꾸기 칸(api/mvp3_build). 열린 구성표 줄(ordinal)과 서버가 준 선택지만 든다.
  // 바꾼 결과는 선택한 상품의 build(기준 판매가 · 바꾼 줄)와 price(서버가 다시 계산한 합계)에 둔다.
  function emptyBuild(){return {ordinal:null,data:null,error:''};}
  // 수량을 바꾼 줄(메모리·저장장치)은 그 수량도 함께 보낸다. 수량이 구성표 그대로면 예전과 같은 모양이다.
  function changesOf(p){return (p?.build?.changes||[]).map(c=>({ordinal:c.ordinal,product_code:c.after.product_code,
    ...(Number.isSafeInteger(c.base_quantity)&&c.quantity!==c.base_quantity?{quantity:c.quantity}:{})}));}
  // 첫 인사는 PC 상담으로 바로 들어간다(2026-10-11 사장님: 게임 탐색은 화면이 먼저 권하지 않는다).
  const GREETING='안녕하세요! 어떤 용도로 쓰실 PC인지와 예산을 알려주시면 맞는 PC를 함께 찾아드릴게요.';
  const ANSWER_WRITING='설명을 쓰고 있어요. 아래 추천부터 먼저 보여 드릴게요.';
  const ANSWER_MISSING='설명을 불러오지 못했어요. 아래 추천을 먼저 확인해 주세요.';
  // 화면 식별자만 보낸다. 제목·가격·부품·연락처는 요청 자료로 믿지 않고 서버가 공개 구성에서 다시 읽는다.
  function displayContext(state,keepCurrent,extraCards){
    const screen=['welcome','results','detail','final','saved'].includes(state.screen)?state.screen:'welcome';
    const selected=screen!=='saved'&&(keepCurrent||['detail','final'].includes(screen))?(state.selected||(keepCurrent?state.restoredCurrent:null)):null;
    const positive=n=>Number.isSafeInteger(n)&&n>0;
    const identity=p=>positive(p?.product_code)?{product_code:p.product_code}:
      typeof p?.configuration_id==='string'&&/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(p.configuration_id)?{configuration_id:p.configuration_id}:null;
    // 선택 견적을 추천 배열 앞에 끼우면 「세 번째 PC」의 순서가 바뀐다. 선택은 따로 보낸다.
    const currentSelection=identity(selected);
    // 대화 화면(keepCurrent)은 견적을 불러오거나 고른 뒤에도 오른쪽 카드가 그대로 보인다 -- 그 카드도 보낸다(2026-10-16 중헌 님 「오른쪽 화면에 뜬 세가지 PC는 뭐야?」).
    const shown=screen==='results'||(keepCurrent&&screen!=='saved')?(state.groups||[]).flatMap(g=>[...(Array.isArray(g.products)?g.products:[]),...(Array.isArray(g.custom)?g.custom:[])]):
      screen==='welcome'&&Array.isArray(extraCards)?extraCards:[];
    // 같은 PC가 여러 용도 그룹에 다시 나타나도 화면의 카드 순번은 그대로 둔다.
    const identities=shown.map(identity).filter(Boolean),cards=identities.slice(0,6);
    const source=currentSelection?.product_code&&state.savedQuote?.product?.product_code===currentSelection.product_code?'saved_quote':
      selected?.build?'custom_build':screen==='welcome'&&cards.some(c=>c.configuration_id)?'new_pcs':'recommendation';
    return {screen,cards,selected:currentSelection,source,...(identities.length>6?{cards_truncated:true}:{})};
  }
  function createFlow(api,options={}){
    const changed=options.onChange||(()=>{}), uuid=options.uuid||(()=>root.crypto.randomUUID());
    // keepCurrent: 2차 대화 화면(talk.html). 고객이 고른 구성(지금 견적)은 새 조건·새 추천이 와도 지우지 않고,
    // 고객이 다른 구성을 고를 때만 바뀐다(코덱스 1816 보강3 §5). 1차 화면은 지금처럼 새 조건에서 비운다.
    const keepCurrent=options.keepCurrent===true;let proposalSeq=0,answerSeq=0;
    const state={screen:'welcome',talk:null,chatFlow:null,history:[],messages:[],groups:[],recommendation:null,
      selected:null,selectionState:null,selectionWants:null,selectionQuery:null,lastQuery:null,savedQuote:null,quotes:[],hasMore:false,phase:null,error:null,retry:null,
      saveState:'idle',needsRefresh:false,lastText:'',missing:[],assumed:[],pendingSave:null,pendingProblem:'',handoff:null,
      wants:null,choices:[],anchorCode:null,pendingText:'',inquiry:emptyInquiry(),parts:emptyParts(),build:emptyBuild(),selectedContext:null,freeBuildOffer:null,handoffOffer:false,restoredCurrent:null,restoredShown:false,proposals:[],
      contact:emptyContact(),keep:emptyKeep(),consult:emptyConsult(),mall:emptyMall()};
    let generation=0,controller=null,pendingProduct=null,pendingContact=null,pendingPurpose='keep',stayOnScreen=false;const saveIds=new Map(),journal=createJournal(options),conversation=createConversationStore(options);
    // 화면을 그릴 때마다 대화 상태를 이 탭에 남긴다. 보관이 막혀 있어도 상담은 그대로 간다.
    function remember(){try{conversation.write(conversationSnapshot(state));}catch{}}
    function emit(){remember();changed(state);}
    function cancel(){if(state.phase==='save')state.saveState=state.pendingSave?'uncertain':'idle';generation++;controller?.abort();controller=null;state.phase=null;}
    function begin(phase){cancel();controller=new AbortController();state.phase=phase;state.error=null;state.retry=null;emit();return {id:generation,signal:controller.signal};}
    function current(op){return op.id===generation&&!op.signal.aborted;}
    function message(text,who='ai',extra={}){if(typeof text==='string'&&text.trim())state.messages.push({text,who,...extra});}
    // 상세 화면을 다녀오면 대화를 되살려 같은 견적을 다시 연다. 그때마다 같은 안내가 붙지 않게 바로 앞과 같은 말은 다시 넣지 않는다
    // (2026-10-12 카드 검수 X3: 고객이 말하지 않았는데 「새로고침 전에 보던…」이 왕복마다 쌓였다).
    function messageOnce(text){const last=state.messages[state.messages.length-1];if(!(last&&last.who==='ai'&&last.text===text))message(text);}
    function fail(error,retry){
      state.error={message:error?.message||'요청을 처리하지 못했어요.',status:error?.status||0,code:error?.code||'invalid_response',
        retryAfter:error?.retryAfter||0,retryAt:Date.now()+(error?.retryAfter||0)*1000};
      state.retry=retry;
    }
    // 추천 조회가 일시적 연결 실패(API 재시작 중 nginx 가 낸 5xx HTML)로 끝나면 같은 요청을 잠시 뒤 다시 묻는다.
    // 첫 답변이 이미 후보를 말했는데 카드 자리만 「새 추천을 불러오지 못했어요」가 되던 일(2026-10-15 오픈테스트 C04·C07)의
    // 원인으로 본다(실패 문구가 JSON 읽기 실패에서만 나온다) -- 고객이 다시 시도하지 않아도 화면을 다시 오가면 회복됐다. 서버가 JSON 으로 낸 오류(그 판단)와
    // 429·연결 끊김은 다시 묻지 않는다(그대로 알리고 「다시 시도」를 둔다). 기다리는 동안 이 요청이 밀려나면(새 문장·새 상담) 더 묻지 않는다.
    const TRANSIENT=new Set(['gateway_error']),RETRY_DELAYS=Array.isArray(options.retryDelays)?options.retryDelays:[1500,4000];
    function pause(ms,signal){return new Promise(resolve=>{if(signal.aborted)return resolve();const t=setTimeout(done,ms);function done(){clearTimeout(t);signal.removeEventListener('abort',done);resolve();}signal.addEventListener('abort',done,{once:true});});}
    async function recommendRetrying(op,...args){
      for(let i=0;;i++){
        try{return await api.recommend(...args);}
        catch(error){if(i>=RETRY_DELAYS.length||!TRANSIENT.has(error?.code)||!current(op))throw error;}
        await pause(RETRY_DELAYS[i],op.signal);
        if(!current(op))throw Object.assign(new Error('요청을 취소했어요.'),{code:'aborted'});
      }
    }
    function reset({restore=false}={}){
      cancel();Object.assign(state,{restoredCurrent:null,restoredShown:false,proposals:[],screen:'welcome',talk:null,chatFlow:null,history:[],messages:[],groups:[],recommendation:null,
        selected:null,selectionState:null,selectionWants:null,selectionQuery:null,lastQuery:null,savedQuote:null,quotes:[],hasMore:false,error:null,retry:null,saveState:'idle',needsRefresh:false,lastText:'',missing:[],assumed:[],handoff:null,
        wants:null,choices:[],anchorCode:null,pendingText:'',inquiry:emptyInquiry(),parts:emptyParts(),build:emptyBuild(),selectedContext:null,freeBuildOffer:null,handoffOffer:false,
        keep:emptyKeep(),consult:emptyConsult(),mall:emptyMall()});
      try{state.pendingSave=journal.read();state.pendingProblem='';if(state.pendingSave)state.saveState='uncertain';}
      catch{state.pendingProblem='이 탭의 보관 복구 기록을 확인할 수 없어 새 보관 요청을 보내지 않습니다. 내 견적은 확인할 수 있어요.';}
      message(GREETING);
      // restore: 처음 열 때만 이 탭에 남은 대화를 되살린다. 「새 상담」은 지운다.
      let saved=null;
      if(restore){try{saved=conversation.read();}catch{saved=null;}}
      else{try{conversation.clear();}catch{}}
      if(saved){
        state.talk=saved.talk;state.chatFlow=saved.chat_flow;state.history=saved.history;state.wants=M.object(saved.wants)?saved.wants:null;
        if(saved.messages.length)state.messages=saved.messages;
        state.restoredCurrent=saved.current;state.restoredShown=saved.shown===true;
      }
      emit();
    }
    async function recommendFor(op,extra={},{notes=true}={}){
      state.phase='recommend';emit();
      const sentAnchor=state.anchorCode;
      const response=await recommendRetrying(op,state.talk,{signal:op.signal},{wants:state.wants,anchor_code:state.anchorCode,...extra});
      if(!current(op))return;
      // 「더 싸게·더 높은 사양」으로 받은 카드는 같은 방향·기준 카드로 물어야 다시 나온다 -- 고를 때 함께 기억한다
      // (2026-10-13 사장님: 대화 화면 「더 높은 사양」 카드의 상세 보기가 상세 대신 다른 추천 목록으로 갔다).
      state.lastQuery=validQuery({nav:extra.nav,anchor_code:sentAnchor});
      if(extra.text!==undefined)state.pendingText='';
      const parsed=M.recommendations(response);
      state.recommendation=parsed;state.groups=parsed.groups;state.assumed=parsed.assumed;state.missing=parsed.needs;
      state.wants=parsed.wants;state.choices=parsed.choices;state.anchorCode=parsed.anchorCode;
      // What the server could and could not do with the request, then the follow-up question.
      // 되살린 대화를 다시 열 때(notes=false)는 같은 안내·다음 질문이 이미 대화에 있다 -- 다시 붙이지 않는다
      // (2026-10-12 카드 검수 X3: 「더 싼 PC나 더 높은 사양도…」가 상세 왕복마다 1→3→5개로 쌓였다).
      for(const note of notes?parsed.talkNotes:[]){message(note);state.history.push({role:'assistant',text:note.slice(0,300)});}
      // 이 추천이 어느 말 뒤에 나왔는지 남긴다. 대화 화면은 그 말풍선 아래에 카드를 붙이고, 지난 제안은
      // 그때 값 그대로 「이전 제안」으로 둔다 -- 새 추천으로 덮지 않는다(코덱스 1816 보강3 §2).
      // 안내(예산·못 맞춘 조건·되묻기) 다음에 남긴다: AI 설명 -> 예산 안내 -> 카드 -> 다음 선택 단추 순서
      // (2026-10-12 사장님 결정 · 카드 검수 C1 「예산 안내가 카드 아래 말풍선으로 붙음」).
      state.proposals=[...state.proposals,{id:++proposalSeq,at:state.messages.length,groups:parsed.groups,talk:M.copy(state.talk),wants:M.object(parsed.wants)?M.copy(parsed.wants):null}].slice(-10);
      state.history=state.history.slice(-6);
      if(!keepCurrent){state.selected=null;state.selectionState=null;state.selectionWants=null;state.selectionQuery=null;state.savedQuote=null;state.saveState='idle';state.needsRefresh=false;}
      state.screen='results';
      if(parsed.unsupported&&!parsed.groups.length)message('현재 추천 원천은 이 화면의 판매 중 PC 목록과 연결되지 않았어요. 상담 조건은 유지됩니다.');
    }
    // AI 가 고른 PC 가 조건으로 다시 받은 카드에 없으면(부품 바꾸기로 옮긴 PC·화면에서 고른 PC) 그 PC 를 맨 앞 묶음으로 그린다.
    // 말과 카드가 달랐다(2026-10-16 「가장 비싼 GPU로 바꿔줘」 -- 설명은 RTX 5070 Ti PC, 카드는 150만원 추천). 값은 서버가 준 것만 쓴다.
    function agentCards(list){
      if(!Array.isArray(list)||!list.length)return;
      const have=new Set((state.groups||[]).flatMap(g=>(g.products||[]).map(p=>p.product_code)));
      if(list.every(c=>have.has(c?.product_code)))return;
      let picked;try{picked=M.recommendations({ok:true,card_sets:[{kind:'sold',usage:'상담에서 고른 PC',items:list}]}).groups[0];}catch{return;}
      if(!picked||!picked.products.length)return;
      const codes=new Set(picked.products.map(p=>p.product_code));
      const rest=(state.groups||[]).map(g=>({...g,products:(g.products||[]).filter(p=>!codes.has(p.product_code))})).filter(g=>g.products.length||(g.custom||[]).length);
      let index=0;state.groups=[picked,...rest].map(g=>({...g,products:g.products.map(p=>({...p,index:index++}))}));
      if(state.recommendation)state.recommendation={...state.recommendation,groups:state.groups};
      const last=state.proposals[state.proposals.length-1];if(last)last.groups=state.groups;
    }
    async function submit(raw,{repeat=false,entry=null}={}){
      const text=String(raw||'').trim();
      if(!text||text.length>MAX_TEXT||state.phase)return false;
      const previous=state.history.slice(-6),previousTalk=state.talk,op=begin('talk');
      state.freeBuildOffer=null;state.lastText=text;if(!repeat)message(text,'user');emit();
      // 새 조건으로 다시 찾다가 실패하면 보던 견적으로 되돌린다(코덱스 PR136 검수 「추천 실패 때 이전 추천 복원」).
      let prior=null;
      try{
        // entry: 대화 화면 시작 단추로 시작한 문장이면 그 단추 키(서버가 로그로만 센다).
        // defer_answer: 「카드 먼저」(2026-10-14) -- 서버가 설명을 기다리지 않고 답한다. 설명은 fillAnswer 가 따로 받아 채운다.
        const shown=state.screen==='welcome'&&typeof options.getDisplayCards==='function'?options.getDisplayCards():[];
        const payload={text,state:state.talk,chat_flow:state.chatFlow,history:previous,defer_answer:true,display_context:displayContext(state,keepCurrent,shown)};if(entry)payload.entry=entry;
        const response=await api.parse(payload,{signal:op.signal});
        if(!current(op))return false;
        if(!M.object(response)||response.ok!==true||!M.object(response.state))throw new Error('상담 응답 형식을 확인할 수 없어요.');
        // 잡담·범위 밖 질문이 조건을 바꾸지 않았으면 보던 견적을 지우지 않는다(코덱스 1816 「앞서 말한 조건과 보던 견적을 잃지 않기」).
        const keep=!!state.recommendation&&(response.pc_related===false||!!response.fallback)&&JSON.stringify(response.state)===JSON.stringify(state.talk);
        state.talk=M.copy(response.state);state.chatFlow=M.object(response.chat_flow)?M.copy(response.chat_flow):null;
        state.history.push({role:'user',text:text.slice(0,1000)});
        const answer=M.text(response.answer),reply=M.text(response.reply);
        const pendingAnswer=typeof response.answer_pending==='string'?response.answer_pending:'';
        if(pendingAnswer)fillAnswer(pendingAnswer,response);
        else if(!response.silent){
          // 답을 먼저 충분히 하고, PC 이야기는 같은 말풍선 끝에 짧게 붙인다(코덱스 1816 보강2).
          message([answer.trim(),reply.trim()].filter(Boolean).join('\n\n'),'ai');
          if(answer.trim())state.history.push({role:'assistant',text:answer.slice(0,300)});
          if(reply.trim())state.history.push({role:'assistant',text:reply.slice(0,300)});
        }
        const actionEntry=typeof module!=='undefined'?require('./free-build-entry.js'):root.MVP3FreeBuildEntry;
        if(actionEntry?.validAction(response.action,text)){state.freeBuildOffer=M.copy(response.action);return true;}
        // 예외 입력(이상한 말·사람 상담 요청·AI 가 못 읽은 말)에는 서버가 사람 상담 길을 연다(api/talk_exceptions).
        if(response.handoff_offer===true)state.handoffOffer=true;
        // 상담원이 고른 PC 목록은 다음 턴 기록에만 싣는다 -- 「조금 전 두 번째 제품」을 가리킬 수 있게(코덱스 v2 Q42). 화면에는 보이지 않는다.
        if(response.agent===true&&typeof response.shown_note==='string'&&response.shown_note.trim())state.history.push({role:'assistant',text:response.shown_note.slice(0,300)});
        state.history=state.history.slice(-6);
        // 「차이만 설명해 주세요 · 추천은 필요 없어요」면 설명으로 끝낸다 -- 추천 카드를 부르지 않고 보던 것도 그대로 둔다
        // (2026-10-12 카드 검수 X2: 설명 뒤에 카드 3장이 나왔다).
        if(keep||response.explain_only===true)return true;
        // 조건이 바뀌었으면 새로고침 전 견적은 더 이상 지금 조건의 견적이 아니다.
        // 대화 화면(keepCurrent)은 고를 때 조건을 함께 보관하므로 조건이 바뀌어도 그 견적을 버리지 않는다.
        if(!keepCurrent&&JSON.stringify(response.state)!==JSON.stringify(previousTalk))state.restoredCurrent=null;
        state.missing=Array.isArray(response.missing)?response.missing:[];state.assumed=Array.isArray(response.assumed)?response.assumed:[];
        if(state.recommendation)prior={screen:state.screen,recommendation:state.recommendation,groups:state.groups,selected:state.selected,selectionState:state.selectionState,
          savedQuote:state.savedQuote,saveState:state.saveState,needsRefresh:state.needsRefresh,wants:state.wants,choices:state.choices,anchorCode:state.anchorCode};
        if(!keepCurrent){state.selected=null;state.selectionState=null;state.selectionWants=null;state.selectionQuery=null;state.savedQuote=null;state.saveState='idle';state.needsRefresh=false;}
        state.groups=[];state.recommendation=null;
        // Sentences said while the server was still asking (e.g. 「램 64GB」 before the usage)
        // ride along until a recommendation actually reads them.
        state.pendingText=(state.pendingText?state.pendingText+' / '+text:text).slice(-300);
        if(state.missing.length||response.pc_related===false||response.silent||response.fallback){state.screen='welcome';}
        // LLM 상담(response.agent, api/talk_agent.as_parse · 2026-10-14 중헌 님): AI 가 엔진에 넘긴 조건 그대로 카드를
        // 다시 묻는다 -- wants·문장은 보내지 않았고, 「더 싸게/더 좋게」면 같은 방향이다(A-02 같은 엔진·같은 순서).
        // 엔진 안내 문장은 AI 설명과 겹치므로 붙이지 않는다.
        // 여러 대 구매(response.wants.units, 코덱스 C10)는 그대로 실어 화면이 한 대 예산으로 견주게 한다.
        else if(response.agent===true){state.pendingText='';await recommendFor(op,{wants:M.object(response.wants)?M.copy(response.wants):null,...(['cheaper','better'].includes(response.nav)?{nav:response.nav}:{})},{notes:false});if(current(op))agentCards(response.agent_cards);}
        else {await recommendFor(op,{text:state.pendingText});}
      }catch(error){
        if(current(op)){
          const inRecommend=state.phase==='recommend';
          fail(error,inRecommend?{kind:'recommend'}:{kind:'talk',text});state.handoffOffer=true;
          if(inRecommend&&prior)Object.assign(state,prior);
        }
      }finally{if(current(op)){state.phase=null;controller=null;emit();}}
      return true;
    }
    // 「카드 먼저」(2026-10-14 사장님 「그렇게 해」): 설명 AI 가 7~9초 걸려, 서버는 질문 읽기가 끝나면 먼저 답하고
    // (answer_pending 표) 설명은 따로 쓴다. 말풍선에는 «설명을 쓰는 중» 한 줄을 두고 카드를 먼저 부른다. 설명이 오면
    // 같은 말풍선을 설명 + 서버 마무리 문장으로 바꾼다 -- 말풍선 순서(설명 위, 카드 아래)는 그대로다.
    // 설명을 못 받으면(서버가 표를 모름·시간 초과·연결 실패) 첫 응답의 문장으로 둔다. 문장도 없으면 그 사실을 한 줄로 밝힌다.
    function fillAnswer(token,first){
      const seq=++answerSeq,msg={text:ANSWER_WRITING,who:'ai',pending:true};state.messages.push(msg);
      const shown=r=>[M.text(r.answer).trim(),M.text(r.reply).trim()].filter(Boolean).join('\n\n');
      const settle=(text,final)=>{
        if(!state.messages.includes(msg))return;     // 새 상담으로 지웠다
        msg.text=text||ANSWER_MISSING;delete msg.pending;
        if(!final||seq!==answerSeq)return;          // 그새 다음 문장을 보냈으면 대화 기록·조건은 그 문장이 정한다
        const a=M.text(final.answer),r=M.text(final.reply);
        if(a.trim())state.history.push({role:'assistant',text:a.slice(0,300)});
        if(r.trim())state.history.push({role:'assistant',text:r.slice(0,300)});
        state.history=state.history.slice(-6);
        if(M.object(final.chat_flow))state.chatFlow=M.copy(final.chat_flow);
        if(final.handoff_offer===true)state.handoffOffer=true;
        // 설명까지 보고 조건이 달라졌으면(드물다) 카드를 그 조건으로 다시 받는다.
        const missing=Array.isArray(final.missing)?final.missing:[];
        if(M.object(final.state)&&!state.phase&&(JSON.stringify(final.state)!==JSON.stringify(state.talk)||JSON.stringify(missing)!==JSON.stringify(state.missing))){
          state.talk=M.copy(final.state);state.missing=missing;
          if(!missing.length&&final.pc_related!==false&&final.explain_only!==true)refresh({notes:false});
        }
      };
      api.answer({token}).then(final=>{
        if(!M.object(final)||final.ok!==true)throw new Error('answer');
        settle(shown(final),final);
      },()=>settle(shown({reply:first.reply}),null)).finally(emit);
    }
    // notes=false: 되살린 대화에 카드만 다시 붙인다(같은 안내·다음 질문은 이미 대화에 있다).
    async function refresh({notes=true}={}){
      if(!state.talk||state.phase)return;
      const op=begin('recommend');
      try{await recommendFor(op,{},{notes});state.restoredShown=false;}catch(error){if(current(op))fail(error,{kind:'recommend'});}
      finally{if(current(op)){state.phase=null;controller=null;emit();}}
    }
    // 고른 상품을 고를 때 조건(basis)으로 서버에 다시 묻는다. 지금 조건이 고를 때와 같으면 방금 받은 추천에서
    // 찾고(fresh 가 아닐 때), 아니면 고를 때 조건으로 한 번 더 묻는다 -- 조건을 바꾼 뒤에도 지금 견적이
    // 사라지지 않게(코덱스 PR142·143 검수 1). 없으면 null, 이 요청이 밀려났으면 undefined.
    async function findProduct(op,code,basis,{fresh=false,wants=null,query=null}={}){
      const pick=groups=>groups.flatMap(g=>g.products).find(x=>x.product_code===code)||null;
      let p=!fresh&&JSON.stringify(basis)===JSON.stringify(state.talk)?pick(state.groups):null;
      // 고를 때 추천 조건(wants)도 함께 보낸다 -- 빼면 서버가 다른 PC 를 추천해 고른 PC 를 못 찾는다.
      const q=validQuery(query);
      if(!p){const r=M.recommendations(await recommendRetrying(op,M.copy(basis),{signal:op.signal},{...(M.object(wants)?{wants:M.copy(wants)}:{}),...(q||{})}));if(!current(op))return undefined;p=pick(r.groups);}
      return p&&M.copy(p);
    }
    // 바꿨던 부품을 서버 계산으로 다시 적용한다. 못 하면 기본 구성으로 두고 그 사실을 note 로 돌려준다.
    // strict(가격 재확인)면 기본·일부 적용 구성으로 바꾸지 않고 던진다 -- 고객이 고른 부품 구성은 그대로 두고
    // 다시 시도하게 한다. 다른 구성은 고객이 따로 고른다(코덱스 PR147 검수 1).
    async function reapply(op,p,basis,changes,{strict=false}={}){
      if(!changes.length)return {product:p,note:''};
      const keep=()=>Object.assign(new Error('바꿨던 부품을 지금 금액으로 다시 계산하지 못해 고른 구성을 그대로 두었어요. 잠시 뒤 다시 확인하거나, 부품 구성에서 다른 부품으로 바꿔 주세요.'),{code:'build_unavailable'});
      let q;
      try{q=M.buildQuote(await api.buildQuote(M.copy(basis),p.product_code,M.copy(changes),{signal:op.signal}),p.product_code);}
      catch(error){
        if(!current(op))return null;
        if(strict)throw keep();
        return {product:p,note:' 바꿨던 부품은 다시 적용하지 못해 기본 구성으로 보여 드려요. 부품 구성에서 다시 바꿀 수 있어요.'};
      }
      if(!current(op))return null;
      if(strict&&q.changes.length<changes.length)throw keep();
      return {product:{...p,price:q.total,build:q.changes.length?{base_price:q.base_price,changes:q.changes,warnings:q.warnings}:null},
        note:q.changes.length<changes.length?' 바꿨던 부품 중 일부는 지금 다시 적용할 수 없어 기본 구성으로 두었어요.':' 바꿨던 부품도 다시 적용했어요.'};
    }
    // 새로고침 전에 보던 견적을 다시 연다. 가격·구성은 보관하지 않았으므로 고를 때 조건으로 서버에 다시 묻고,
    // 같은 상품 번호가 있으면 그것을 고른 뒤 바꿨던 부품을 서버 계산으로 다시 적용한다.
    // 없거나 실패하면 지어내지 않고 그 사실을 말한다. 실패하면 상품 번호는 남겨 다시 시도할 수 있게 한다.
    // arrived = 대화 화면에서 「상세 보기」로 넘어왔다(새로고침이 아니다) -- 안내 문구만 다르다(2026-10-13 사장님:
    // 넘어왔는데 「새로고침 전에 보던 …을 다시 불러왔어요」라고 했다).
    async function resume({arrived=false}={}){
      const want=state.restoredCurrent;
      if(state.phase||!want||!state.talk)return;
      const basis=M.object(want.selection_state)?want.selection_state:state.talk,op=begin('recommend');
      // 최신 조건 추천이 실패해도 고를 때 조건으로 고른 견적은 따로 복원한다(코덱스 PR147 검수 2).
      // 최신 조건 실패는 복원 뒤 「새 추천을 불러오지 못했어요」로 따로 알린다.
      let latest=null;
      try{
        try{await recommendFor(op,{},{notes:false});}catch(error){if(!current(op))return;if(error?.name==='AbortError')throw error;latest=error;}
        if(!current(op))return;
        const wantWants=M.object(want.selection_wants)?want.selection_wants:null;
        const wantQuery=validQuery(want.selection_query);
        let p=await findProduct(op,want.product_code,basis,{fresh:!!latest,wants:wantWants,query:wantQuery});
        if(p===undefined||!current(op))return;
        // 부품 바꾸기로 옮긴 PC 는 추천 목록에 없을 수 있다. 옮기기 전 PC 의 같은 부품 선택지에서 서버에 다시 찾는다.
        if(!p&&validSwapFrom(want.swap_from)){
          // 실패하면 바깥에서 「다시 불러오기」로 남긴다(상품 번호는 지우지 않는다).
          const r=await api.partOptions(M.copy(basis),want.swap_from.product_code,want.swap_from.slot,{signal:op.signal});
          if(!current(op))return;
          const o=M.partOptions(r,want.swap_from.slot,want.swap_from.product_code).options.find(x=>x.product_code===want.product_code);
          if(o){p=M.copy(o);delete p.swap;p.swap_from=M.copy(want.swap_from);}
        }else if(p&&validSwapFrom(want.swap_from)){
          // 이번엔 일반 추천에서 찾았어도 어디서 옮겼는지는 남긴다 -- 다음 왕복에서 추천에서 빠지면 그 부품 선택지로
          // 다시 찾는다(코덱스 PR158 검수 v1 신규 후보).
          p={...p,swap_from:M.copy(want.swap_from)};
        }
        if(!p){state.restoredCurrent=null;messageOnce((arrived?'고르신 PC(상품번호 ':'새로고침 전에 보던 PC(상품번호 ')+want.product_code+')는 지금 판매 중인 추천에서 찾지 못했어요. 판매가 끝났거나 조건에 맞는 상품이 바뀌었을 수 있어요. 아래 추천에서 다시 골라 주세요.');return;}
        const r=await reapply(op,p,basis,want.changes);
        if(!r||!current(op))return;
        state.selected=validSets(want.sets)?{...r.product,sets:want.sets}:r.product;state.selectionState=M.copy(basis);state.selectionWants=wantWants&&M.copy(wantWants);state.selectionQuery=wantQuery;state.selectedContext=null;state.screen='detail';
        state.restoredCurrent=null;messageOnce((arrived?'고르신 '+p.name+' 구성의 상세예요.':'새로고침 전에 보던 '+p.name+'을 다시 불러왔어요.')+' 금액은 지금 다시 확인한 값이에요.'+r.note);
        if(latest)fail(latest,{kind:'recommend'});
      }catch(error){if(current(op))fail(error,{kind:'resume'});}
      finally{if(current(op)){state.phase=null;controller=null;emit();}}
    }
    // 저장하는 사이 금액이 바뀌어(409) 막힌 견적을 지금 금액으로 다시 확인한다(코덱스 PR142·143 검수 3).
    // 잠금만 풀어 예전 금액을 다시 보내지 않는다 -- 서버에 다시 물은 금액으로 바꾼 뒤, 저장은 고객이 다시 누른다.
    async function reprice(){
      const p=state.selected,basis=state.selectionState;
      if(state.phase||!p||!M.object(basis)||!state.needsRefresh)return;
      const before=p.price,op=begin('reprice');
      try{
        const found=await findProduct(op,p.product_code,basis,{fresh:true,wants:state.selectionWants,query:state.selectionQuery});
        if(found===undefined||!current(op))return;
        if(!found){message('「'+p.name+'」은 지금 판매 중인 추천에서 찾지 못했어요. 판매가 끝났거나 조건에 맞는 상품이 바뀌었을 수 있어요. 다른 구성을 골라 주세요.');return;}
        const r=await reapply(op,found,basis,changesOf(p),{strict:true});
        if(!r||!current(op))return;
        const won=n=>Number.isInteger(n)?n.toLocaleString('ko-KR')+'원':'금액 미확인';
        state.selected={...r.product,index:p.index};state.needsRefresh=false;state.saveState='idle';state.savedQuote=null;state.handoff=null;
        message('금액을 지금 기준으로 다시 확인했어요. '+(before===r.product.price?'금액은 '+won(before)+'으로 같아요.':won(before)+'에서 '+won(r.product.price)+'으로 바뀌었어요.')+
          ' 이 금액으로 저장하려면 「견적 저장」을 다시 눌러 주세요.'+r.note);
      }catch(error){if(current(op))fail(error,{kind:'reprice'});}
      finally{if(current(op)){state.phase=null;controller=null;emit();}}
    }
    // Quick choice after the cards: cheaper / better than the card being looked at.
    // Same recommend call with a direction; no AI parse, the conditions stay as they are.
    async function explore(direction,label){
      if(state.phase||!state.talk||!state.recommendation||!['cheaper','better'].includes(direction))return;
      const op=begin('recommend');
      if(label){message(label,'user');state.history.push({role:'user',text:label});}
      try{await recommendFor(op,{nav:direction});}
      catch(error){if(current(op))fail(error,{kind:'recommend'});}
      finally{if(current(op)){state.phase=null;controller=null;emit();}}
    }
    function select(index){
      if(state.phase)return;
      const p=state.groups.flatMap(g=>g.products).find(p=>p.index===index);if(!p)return;
      cancel();state.restoredCurrent=null;state.inquiry=emptyInquiry();state.parts=emptyParts();state.build=emptyBuild();state.selectedContext=null;state.selected=M.copy(p);state.selectionState=M.copy(state.talk);state.selectionWants=M.object(state.wants)?M.copy(state.wants):null;state.selectionQuery=state.lastQuery&&M.copy(state.lastQuery);state.savedQuote=null;state.saveState='idle';state.needsRefresh=false;state.error=null;state.retry=null;state.screen='detail';emit();
    }
    function navigate(screen){
      if(['detail','final'].includes(screen)&&!state.selected)return;
      if(!['welcome','results','detail','final','saved'].includes(screen))return;
      cancel();state.parts=emptyParts();state.build=emptyBuild();state.screen=screen;state.error=null;state.retry=null;emit();
    }
    async function save({contact=null,purpose='keep',stay=false}={}){
      if(state.phase||state.pendingSave||state.pendingProblem||!state.selected||!state.selectionState||state.needsRefresh||state.savedQuote||!Number.isInteger(state.selected.price))return;
      const selected=M.copy(state.selected),selectionState=M.copy(state.selectionState);
      const changes=changesOf(selected);
      const sets=Number.isSafeInteger(selected.sets)&&selected.sets>1?selected.sets:1;
      const logical=JSON.stringify([selected.product_code,selected.price,selectionState,changes].concat(sets>1?[sets]:[]));
      if(!saveIds.has(logical))saveIds.set(logical,uuid());
      const payload={request_id:saveIds.get(logical),product_code:selected.product_code,expected_price:selected.price,state:selectionState};
      if(changes.length)payload.changes=changes;
      if(sets>1)payload.sets=sets;
      pendingContact=purpose==='keep'?contact:null;pendingPurpose=purpose;stayOnScreen=stay;
      const op=begin('save');state.saveState='saving';emit();
      try{
        const binding=await api.prepareSave();if(!current(op))return;
        const record={version:1,payload,binding};
        try{journal.write(record);}catch{throw Object.assign(new Error('새로고침 후 동일 요청을 복구할 수 없어 보관 요청을 보내지 않았어요. 브라우저 설정을 확인해주세요.'),{code:'storage_unavailable'});}
        state.pendingSave=record;pendingProduct=selected;
        await performSave(op,record);
      }catch(error){
        if(current(op))saveFailure(error);
      }finally{if(current(op)){state.phase=null;controller=null;emit();}}
    }
    function saveFailure(error){
      if(error?.status===422){
        // 서버가 보관하지 않고 돌려보낸 요청(연락처 없음·형식 오류)이다 -- 저장 결과가 불명한 것이 아니므로 보관 복구 기록을 지운다.
        state.saveState='failed';
        try{journal.clear();state.pendingSave=null;pendingProduct=null;}catch{state.pendingProblem='이 탭의 이전 보관 복구 기록을 정리하지 못했어요. 내 견적을 확인해주세요.';}
        fail(error,{kind:'save'});
      }else if(error?.status===409){
        state.needsRefresh=true;state.saveState='failed';
        try{journal.clear();state.pendingSave=null;pendingProduct=null;}catch{state.pendingProblem='이 탭의 이전 보관 복구 기록을 정리하지 못했어요. 내 견적을 확인해주세요.';}
        // 대화 화면은 지금 견적을 그대로 두고 그 상품의 지금 금액만 다시 확인한다(reprice).
        fail(error,{kind:keepCurrent?'reprice':'recommend'});
      }else{
        state.saveState=state.pendingSave?'uncertain':'failed';
        fail(error,state.pendingSave?{kind:'recover'}:{kind:'save'});
      }
    }
    async function performSave(op,record){
      // 연락처·보관 목적은 보관 복구 기록(journal)에 싣지 않는다 -- 이 탭 메모리에서만 보낸다.
      const body=M.copy(record.payload);
      if(pendingContact)body.contact=pendingContact;
      if(pendingPurpose==='handoff')body.purpose='handoff';
      const response=await api.saveQuote(body,{signal:op.signal,existingKeyOnly:true});
      if(!current(op))return;
      const saved=M.quote(response?.quote);
      // 보관하는 순간 서버가 쇼핑몰 현재가와 비교한다(api/mall_price_live). 바뀌었으면 쇼핑몰 가격으로
      // 보관하고 그 사실(보던 가격 = 요청 가격, 쇼핑몰 가격 = 보관 가격)을 함께 돌려준다. 그 경우만 다른 가격을 받는다.
      // 서버가 쇼핑몰 가격으로 고쳐 보관했을 때만 다른 가격을 받는다. 부품을 바꾼 견적은 기준 PC 만
      // 비교하므로 «바뀐 차액만큼 옮겨졌는가»로 확인한다(api/mvp3_saved_quotes).
      const check=saved?.price_check,repriced=check?.status==='changed'&&Number.isSafeInteger(check.diff)
        &&check.mall-check.quoted===check.diff&&saved?.product.price===record.payload.expected_price+check.diff;
      if(response?.ok!==true||!saved||saved.product.product_code!==record.payload.product_code||(saved.product.price!==record.payload.expected_price&&!repriced))
        throw new Error('서버 보관 응답을 확인할 수 없어요.');
      try{journal.clear();state.pendingSave=null;state.pendingProblem='';pendingProduct=null;}
      catch{state.pendingProblem='보관은 완료됐지만 이 탭의 복구 기록을 정리하지 못했어요. 같은 요청 외에 새 보관을 보내지 않습니다.';}
      pendingContact=null;
      if(M.object(response.contact)&&response.contact.has_contact===true&&typeof response.contact.masked_phone==='string')
        state.contact={loaded:true,has:true,masked:response.contact.masked_phone,name:M.text(response.contact.name),consentText:state.contact.consentText};
      state.savedQuote=saved;state.saveState='saved';state.selected=saved.product;state.selectionState=saved.state;state.selectionWants=null;
      if(!stayOnScreen)state.screen='final';stayOnScreen=false;
      // 대화 화면은 앞선 조건의 견적을 저장해도 지금 상담 조건을 덮지 않는다(코덱스 PR142·143 검수 2).
      if(!keepCurrent)state.talk=M.copy(saved.state);
    }
    async function recover(){
      if(state.phase||!state.pendingSave)return;
      const record=M.copy(state.pendingSave),op=begin('save');
      state.selected=pendingProduct||M.product({product_code:record.payload.product_code,name:'보관 요청한 PC · 상품번호 '+record.payload.product_code,price:record.payload.expected_price});
      state.selectionState=M.copy(record.payload.state);state.selectionWants=null;state.savedQuote=null;state.screen='final';state.saveState='saving';emit();
      try{
        const binding=await api.prepareSave({existingKeyOnly:true});if(!current(op))return;
        if(binding!==record.binding)throw Object.assign(new Error('이전 보관 요청과 브라우저 접근 키가 달라 요청을 유지합니다. 기존 키 없이는 이전 보관 결과를 확인할 수 없어요.'),{code:'owner_changed'});
        await performSave(op,record);
      }catch(error){if(current(op))saveFailure(error);}
      finally{if(current(op)){state.phase=null;controller=null;emit();}}
    }
    // Saved quote -> mall handoff (api/mvp3_handoff.py). The server re-reads the saved
    // record and rechecks the mall price; the screen only shows what it returns.
    async function handoff(){
      const q=state.savedQuote;
      if(state.phase||!q||!M.uuid(q.id))return;
      if(state.handoff?.quote_id===q.id)return;
      const op=begin('handoff');
      try{
        const r=await api.handoff(q.id,{signal:op.signal});
        if(!current(op))return;
        const url=M.safeUrl(r?.mall_url);
        if(r?.ok!==true||!url||r.quote_id!==q.id||!Number.isInteger(r.price_quoted))throw new Error('쇼핑몰 연결 응답을 확인할 수 없어요.');
        state.handoff={quote_id:q.id,handoff_no:M.text(r.handoff_no),mall_url:url,status:M.text(r.mall_status),
          price_quoted:r.price_quoted,price_mall:Number.isInteger(r.price_mall)?r.price_mall:null,
          changes:Array.isArray(r.changes)?r.changes.filter(c=>M.object(c)&&Number.isSafeInteger(c.delta)).length:0,
          delta:Array.isArray(r.changes)?r.changes.reduce((n,c)=>n+(Number.isSafeInteger(c?.delta)?c.delta:0),0):0,
          sets:Number.isSafeInteger(r.sets)&&r.sets>1&&r.sets<=MAX_SETS?r.sets:1};
        // 서버가 보관 견적도 쇼핑몰 가격으로 고쳤다(api/mvp3_handoff). 화면의 보관 가격도 같은 값으로 맞춘다.
        // 부품을 바꾼 견적이면 쇼핑몰 가격은 기준 PC 값이라 바꾼 부품 차액을 더한다.
        if(state.handoff.status==='가격변동'&&state.handoff.price_mall!==null){
          const price=state.handoff.price_mall+state.handoff.delta;
          q.product={...q.product,price};
          if(state.selected?.product_code===q.product.product_code)state.selected={...state.selected,price};
        }
      }catch(error){if(current(op))fail(error,{kind:'handoff'});}
      finally{if(current(op)){state.phase=null;controller=null;emit();}}
    }

    // ===== 연락처 · 견적 보관 창 · 상담 신청 접수 (2026-10-16 두 구매 흐름) =====
    // 견적 보관(저장)과 상담 신청 접수는 다른 상태다. 보관만으로는 신청이 생기지 않고, 상담사가 먼저 연락하지도 않는다.
    // quiet: 보관 견적서를 다시 열 때 등록 연락처(가린 번호)만 조용히 읽는다 -- 실패해도 화면 위 오류 칸을 띄우지 않는다.
    async function loadContact({quiet=false}={}){
      if(state.phase)return false;
      if(quiet){
        try{const r=await api.contact({});
          if(r?.ok===true&&typeof r.has_contact==='boolean'&&(!r.has_contact||typeof r.masked_phone==='string')){
            state.contact={loaded:true,has:r.has_contact,masked:r.has_contact?r.masked_phone:'',name:M.text(r.name),consentText:M.text(r.consent_text)};emit();return true;}
        }catch{}
        return false;
      }
      const op=begin('contact');
      try{
        const r=await api.contact({signal:op.signal});
        if(!current(op))return false;
        if(r?.ok!==true||typeof r.has_contact!=='boolean'||(r.has_contact&&typeof r.masked_phone!=='string'))throw new Error('연락처 확인 응답을 확인할 수 없어요.');
        state.contact={loaded:true,has:r.has_contact,masked:r.has_contact?r.masked_phone:'',name:M.text(r.name),consentText:M.text(r.consent_text)};
        return true;
      }catch(error){if(current(op))fail(error,{kind:'keep'});return false;}
      finally{if(current(op)){state.phase=null;controller=null;emit();}}
    }
    // 견적 보관 단추: 연락처가 있는지 먼저 서버에 묻고 보관 창을 연다(처음이면 입력, 이미 있으면 가린 번호 확인).
    async function openKeep(){
      if(state.phase||state.pendingProblem||!state.selected||!state.selectionState||state.needsRefresh||state.savedQuote||!Number.isInteger(state.selected.price))return;
      if(!state.pendingSave&&!await loadContact())return;
      state.keep={...emptyKeep(),open:true,purpose:'save'};emit();
    }
    async function openContactChange(){
      if(state.phase||state.keep.open)return;
      if(!state.contact.loaded&&!await loadContact())return;
      state.keep={...emptyKeep(),open:true,purpose:'contact',editing:true};emit();
    }
    function closeKeep(){if(state.keep.busy)return;state.keep=emptyKeep();emit();}
    function keepDraft(values){
      const d=state.keep.draft;
      for(const k of ['phone','name','email'])if(typeof values?.[k]==='string')d[k]=values[k];
      if(typeof values?.consent==='boolean')d.consent=values.consent;
    }
    // 「연락처 변경」을 누른 때만 입력 칸을 연다. 취소하면 이전 번호를 그대로 쓴다.
    function keepEditing(on){
      if(!state.keep.open||state.keep.busy||state.keep.purpose!=='save'||!state.contact.has)return;
      state.keep.editing=on===true;state.keep.error='';if(!on)state.keep.draft={phone:'',name:'',email:'',consent:false};emit();
    }
    async function submitKeep(values){
      const k=state.keep;if(!k.open||k.busy||state.phase)return;
      keepDraft(values);
      const inputs=k.purpose==='contact'||!state.contact.has||k.editing;
      let contact=null;
      if(inputs){const problem=contactProblem(k.draft);if(problem){k.error=problem;k.failed=false;emit();return;}contact=contactPayload(k.draft);}
      k.busy=true;k.error='';k.failed=false;emit();
      if(k.purpose==='save'){
        if(state.pendingSave)await recover();else await save({contact});
        k.busy=false;
        if(state.saveState==='saved'){state.keep=emptyKeep();emit();return;}
        if(state.needsRefresh){state.keep=emptyKeep();emit();return;}   // 금액이 바뀐 것은 화면 위 안내가 말한다
        // 응답을 받지 못했다(5xx·네트워크): 보관됐는지 모른다. 「다시 보관하기」로 새로 보내지 않고 보관 화면을 닫는다 --
        // 화면 위 복구 안내(이전 보관 요청 확인)가 같은 요청 번호로만 결과를 확인한다(중복 보관 방지).
        if(state.saveState==='uncertain'){state.keep=emptyKeep();emit();return;}
        // 서버가 연락처가 없다고 돌려보냈거나(기한 만료) 보관하지 못했다 -- 이유는 보관 창 안에서 말한다.
        const err=state.error;state.error=null;state.retry=null;
        if(err?.code==='contact_required'){state.contact={...state.contact,has:false,masked:''};k.editing=false;}
        k.error=err?.message||'견적을 보관하지 못했어요.';k.failed=true;k.code=err?.code||'';emit();return;
      }
      const ok=await putContact(contact);
      k.busy=false;
      if(!ok){k.failed=true;emit();return;}
      const after=k.after;state.keep=emptyKeep();emit();
      if(after==='consult')await consult();
    }
    async function putContact(contact){
      const op=begin('contact-save');
      try{
        const r=await api.saveContact(contact,{signal:op.signal});
        if(!current(op))return false;
        if(r?.ok!==true||r.has_contact!==true||typeof r.masked_phone!=='string')throw new Error('연락처 저장 응답을 확인할 수 없어요.');
        state.contact={loaded:true,has:true,masked:r.masked_phone,name:M.text(r.name),consentText:state.contact.consentText};
        return true;
      }catch(error){if(current(op)){state.keep.error=error?.message||'연락처를 저장하지 못했어요.';}return false;}
      finally{if(current(op)){state.phase=null;controller=null;}}
    }
    // 「상담 내용 남기기 (선택)」: 상담 주제 선택지는 서버(구매 상담 신청 양식)가 준 것만 쓴다. 못 읽으면 주제 없이 보내고
    // 서버가 기본값(주문 희망)으로 접수한다.
    async function consultToggle(open,message){
      state.consult.open=open===true;state.consult.error='';if(typeof message==='string')state.consult.message=message.slice(0,500);emit();
      if(state.consult.open){topicsAsked=false;await loadConsultTopics();}
    }
    // 상담 주제 선택지(구매 상담 신청 양식). 한 번만 묻는다 -- 못 읽으면 주제 없이 보내고 서버가 「주문 희망」으로 접수한다.
    let topicsAsked=false;
    async function loadConsultTopics(){
      if(state.inquiry.meta||topicsAsked)return;topicsAsked=true;
      try{const r=await api.inquiryForm({});
        if(r?.ok===true&&Array.isArray(r.topics)&&r.topics.length&&r.topics.every(t=>typeof t==='string')&&typeof r.consent_text==='string'){
          state.inquiry.meta={topics:r.topics.slice(0,10),consent_text:r.consent_text};emit();}
      }catch{}
    }
    function consultTopic(topic){if(typeof topic==='string'&&(state.inquiry.meta?.topics||[]).includes(topic))state.consult.topic=topic;}
    function consultDraft(message){if(typeof message==='string')state.consult.message=message.slice(0,500);}
    function consultRows(show){state.consult.showRows=show===true;emit();}
    // 보관 견적 + 등록 연락처로 상담 신청 접수(api/mvp3_quote_consult). 같은 견적은 서버가 한 건만 만든다.
    async function consult(){
      const q=state.savedQuote;
      if(state.phase||!q||!M.uuid(q.id)||state.consult.done?.quote_id===q.id)return;
      const text=state.consult.message.trim(),topic=(state.inquiry.meta?.topics||[]).includes(state.consult.topic)?state.consult.topic:null;
      const op=begin('consult');state.consult.error='';
      try{
        const r=await api.consultFromQuote(q.id,text||null,{signal:op.signal},topic);
        if(!current(op))return;
        if(r?.ok!==true||typeof r.inquiry_no!=='string'||!/^PI-\d{1,12}$/.test(r.inquiry_no)||r.quote_id!==q.id||typeof r.masked_phone!=='string')
          throw new Error('상담 신청 접수 결과를 확인할 수 없어요.');
        state.consult.done={quote_id:q.id,inquiry_no:r.inquiry_no,masked_phone:r.masked_phone,already:r.already===true};
        state.consult.showRows=r.already!==true;state.consult.open=false;
        state.contact={...state.contact,loaded:true,has:true,masked:r.masked_phone};
      }catch(error){
        if(!current(op))return;
        if(error?.code==='contact_required'){
          // 연락처가 없다(기한이 지났거나 보관만 한 견적). 연락처를 먼저 받고 이어서 접수한다.
          state.contact={...state.contact,has:false,masked:''};
          state.keep={...emptyKeep(),open:true,purpose:'contact',after:'consult',editing:true};
        }else state.consult.error=error?.message||'상담 신청을 접수하지 못했어요.';
      }
      finally{if(current(op)){state.phase=null;controller=null;emit();}}
    }
    // 쇼핑몰 완제품: 「팝콘PC로 이동」 -- 견적을 조용히 보관해(연락처 없이, 목적 handoff) 인계 기록을 만들고 성공한 뒤에만 이동한다.
    // 인계 기록은 견적 하나에 한 건이라(api/mvp3_handoff) 다시 눌러도 번호가 늘지 않는다.
    function openMall(){if(state.mall.open)return;state.mall={...emptyMall(),open:true};emit();}
    function closeMall(){if(state.mall.step==='moving')return;state.mall=emptyMall();emit();}
    async function mallHandoff(){
      const fail_=message=>{state.mall={...state.mall,step:'failed',error:message};state.error=null;state.retry=null;return false;};
      if(!state.selected||!state.selectionState)return fail_('상품 정보를 확인하지 못했어요.');
      if(!state.savedQuote){
        await save({purpose:'handoff',stay:true});
        if(!state.savedQuote)return fail_(state.error?.message||(state.needsRefresh?'상품 금액이 바뀌었어요. 지금 금액을 다시 확인해 주세요.':'상품 정보를 확인하지 못했어요.'));
      }
      await handoff();
      const h=state.handoff,q=state.savedQuote;
      if(!(h&&q&&h.quote_id===q.id&&h.mall_url))return fail_(state.error?.message||'쇼핑몰 연결 응답을 확인할 수 없어요.');
      return true;
    }
    async function openInquiry({human=false}={}){
      if(state.phase)return;
      // 어느 단추로 열었는지가 신청의 성격을 정한다(일반 상담 / 구매 상담). 닫았다 다른 단추로 열면 그 성격을 따른다.
      // 성격이 바뀌면 앞서 미리 채운 주제·내용은 비운다. 연락처는 고객이 적은 것이라 둔다.
      if(!state.inquiry.done){if(state.inquiry.human!==human){state.inquiry.draft.topic='';state.inquiry.draft.message='';}state.inquiry.human=human;}
      state.inquiry.open=true;state.inquiry.error='';
      // 상품을 고르기 전(상담 중) 사람 상담: 주제 「기타」와 마지막 문장을 미리 채운다 -- 고객이 고칠 수 있다.
      if((!state.selected||human)&&!state.inquiry.draft.topic&&!state.inquiry.draft.message){state.inquiry.draft.topic='기타';state.inquiry.draft.message=String(state.lastText||'').slice(0,500);}
      if(state.inquiry.meta){emit();return;}
      const op=begin('inquiry-form');
      try{
        const r=await api.inquiryForm({signal:op.signal});
        if(!current(op))return;
        if(r?.ok!==true||!Array.isArray(r.topics)||!r.topics.length||r.topics.some(t=>typeof t!=='string')||typeof r.consent_text!=='string')
          throw new Error('구매 상담 신청 양식을 불러오지 못했어요.');
        state.inquiry.meta={topics:r.topics.slice(0,10),consent_text:r.consent_text};
      }catch(error){if(current(op))state.inquiry.error=error?.message||'구매 상담 신청 양식을 불러오지 못했어요.';}
      finally{if(current(op)){state.phase=null;controller=null;emit();}}
    }
    function closeInquiry(){if(state.phase==='inquiry')return;state.inquiry.open=false;state.inquiry.error='';emit();}
    function inquiryDraft(values){
      const d=state.inquiry.draft;
      for(const k of ['topic','name','phone','email','message'])if(typeof values?.[k]==='string')d[k]=values[k];
      if(typeof values?.consent==='boolean')d.consent=values.consent;
    }
    async function inquire(values){
      if(state.phase||!state.inquiry.open||state.inquiry.done)return;
      inquiryDraft(values);
      const d=state.inquiry.draft,problem=inquiryProblem(d,state.inquiry.meta);
      if(problem){state.inquiry.error=problem;emit();return;}
      const payload={topic:d.topic,consent:true};
      const phone=d.phone.replace(/\s+/g,''),email=d.email.trim(),name=d.name.trim(),text=d.message.trim();
      if(phone)payload.phone=phone;if(email)payload.email=email;if(name)payload.name=name;if(text)payload.message=text;
      if(state.savedQuote&&M.uuid(state.savedQuote.id))payload.quote_id=state.savedQuote.id;
      if(Number.isInteger(state.selected?.product_code)&&state.selected.product_code>0)payload.product_code=state.selected.product_code;
      const op=begin('inquiry');state.inquiry.error='';
      try{
        const r=await api.inquiry(payload,{signal:op.signal});
        if(!current(op))return;
        if(r?.ok!==true||typeof r.inquiry_no!=='string'||!/^PI-\d{1,12}$/.test(r.inquiry_no))throw new Error('구매 상담 신청 결과를 확인할 수 없어요.');
        state.inquiry.done={inquiry_no:r.inquiry_no,note:M.text(r.note)};
        state.inquiry.draft={topic:'',name:'',phone:'',email:'',message:'',consent:false};
      }catch(error){if(current(op))state.inquiry.error=error?.message||'구매 상담 신청을 보내지 못했어요.';}
      finally{if(current(op)){state.phase=null;controller=null;emit();}}
    }
    // 부품 바꾸기(api/mvp3_part_options): 고른 PC 에서 그 부품만 다른 판매 PC 들을 받아 온다.
    // 고르면 그 판매 PC 가 새 선택이 된다 — 금액은 그 상품의 판매가이고, 보관·쇼핑몰 연결도 그 상품번호로 간다.
    async function openParts(slot){
      if(state.phase||!state.selected||!state.selectionState||state.screen!=='detail')return;
      if(state.parts.slot===slot&&state.parts.data){state.parts=emptyParts();emit();return;}
      state.parts={slot,data:null,error:''};
      const base=state.selected.product_code,op=begin('parts');
      try{
        const r=await api.partOptions(M.copy(state.selectionState),base,slot,{signal:op.signal});
        if(!current(op))return;
        state.parts.data=M.partOptions(r,slot,base);
      }catch(error){if(current(op))state.parts.error=error?.message||'부품 선택지를 불러오지 못했어요.';}
      finally{if(current(op)){state.phase=null;controller=null;emit();}}
    }
    function closeParts(){if(state.phase==='parts')cancel();state.parts=emptyParts();emit();}
    function swapPart(code){
      const data=state.parts.data;
      if(state.phase||!data||!state.selected)return;
      const o=data.options.find(x=>x.product_code===code);if(!o||!Number.isSafeInteger(o.swap.price_diff))return;
      const before=state.selected;
      state.selectedContext=state.selectedContext||(state.groups||[]).find(g=>Number.isInteger(before.index)&&g.products.some(x=>x.index===before.index&&x.product_code===before.product_code))||null;
      const next=M.copy(o);delete next.swap;next.swap_from={product_code:before.product_code,slot:data.slot};state.build=emptyBuild();
      state.selected=next;state.savedQuote=null;state.saveState='idle';state.needsRefresh=false;state.handoff=null;
      state.inquiry=emptyInquiry();state.parts=emptyParts();state.error=null;state.retry=null;
      const d=o.swap.price_diff,diff=!Number.isSafeInteger(d)?'차액 확인 필요':d===0?'추가 금액 없음':(d>0?'+':'\u2212')+Math.abs(d).toLocaleString('ko-KR')+'원';
      message(data.label+'를 '+o.swap.value+'로 바꿨어요. 이 구성으로 판매 중인 PC로 옮겼어요. 기본 부품 대비 차액은 '+diff+'이고, PC 총액은 '+o.price.toLocaleString('ko-KR')+'원이에요.'+
        o.swap.also.map(x=>' '+x.label+'도 '+x.from+'에서 '+x.to+'로 함께 바뀌어요.').join('')+' 파워·케이스 같은 나머지 부품은 부품 구성에서 확인해 주세요.');
      emit();
    }
    // 부품 직접 바꾸기(api/mvp3_build): 공개된 구성표의 한 줄을 호환되는 판매 부품으로 바꾼다.
    // 상품번호는 그대로이고, 금액은 서버가 「PC 판매가 + 부품 가격 차이」로 다시 계산한 값만 쓴다.
    async function openBuild(ordinal){
      if(state.phase||!state.selected||!state.selectionState||state.screen!=='detail'||!Number.isSafeInteger(ordinal))return;
      if(state.build.ordinal===ordinal&&(state.build.data||state.build.error)){state.build=emptyBuild();emit();return;}
      state.parts=emptyParts();state.build={ordinal,data:null,error:''};
      const base=state.selected.product_code,op=begin('build');
      try{
        const r=await api.buildOptions(M.copy(state.selectionState),base,changesOf(state.selected),ordinal,{signal:op.signal});
        if(!current(op))return;
        state.build.data=M.buildOptions(r,base,ordinal);
      }catch(error){if(current(op))state.build.error=error?.message||'바꿀 부품을 불러오지 못했어요.';}
      finally{if(current(op)){state.phase=null;controller=null;emit();}}
    }
    function closeBuild(){if(state.phase==='build')cancel();state.build=emptyBuild();emit();}
    async function applyBuild(changes,say){
      const p=state.selected,base=p.product_code,op=begin('build');
      try{
        const q=M.buildQuote(await api.buildQuote(M.copy(state.selectionState),base,changes,{signal:op.signal}),base);
        if(!current(op))return;
        state.selected={...p,price:q.total,build:q.changes.length?{base_price:q.base_price,changes:q.changes,warnings:q.warnings}:null};
        state.savedQuote=null;state.saveState='idle';state.needsRefresh=false;state.handoff=null;state.inquiry=emptyInquiry();state.build=emptyBuild();
        message(say(q)+(q.changes.length&&q.warnings.length?' '+q.warnings.join(' '):''));
      }catch(error){if(current(op))state.build.error=error?.message||'부품을 바꾸지 못했어요.';}
      finally{if(current(op)){state.phase=null;controller=null;emit();}}
    }
    function pickBuild(code){
      const data=state.build.data;
      if(state.phase||!data||!state.selected)return;
      const was=state.selected.build?.changes.find(c=>c.ordinal===data.ordinal),original=was?.before.product_code;
      let o=data.options.find(x=>x.product_code===code);
      // 기본 부품으로 되돌리는 선택(상세 v2 「기본 부품으로」): 후보 목록에 없어도 서버가 준 변경 줄의 before 가 근거다.
      if(!o&&was&&code===original)o={product_code:code,name:was.before.name,price_diff:0};
      if(!o||!Number.isSafeInteger(o.price_diff))return;
      const changes=changesOf(state.selected).filter(c=>c.ordinal!==data.ordinal);
      // 수량을 바꿔 둔 줄은 제품을 바꿔도 그 수량을 지킨다.
      const quantity=was&&was.quantity!==was.base_quantity?{quantity:was.quantity}:{};
      if(code!==original||quantity.quantity)changes.push({ordinal:data.ordinal,product_code:code,...quantity});
      const won=n=>n.toLocaleString('ko-KR')+'원';
      return applyBuild(changes,q=>(data.label||'부품')+' 부품을 「'+o.name+'」 제품으로 바꿨어요. 호환 규칙을 다시 확인했어요. 기본 구성 '+won(q.base_price)+' \u2192 바꾼 구성 '+won(q.total)+'이에요.');
    }
    // 메모리·저장장치 수량(api/mvp3_quantity). 범위는 서버가 준 것만 쓰고, 금액·메인보드 조건은 서버가 다시 확인한다.
    function setBuildQuantity(n){
      const data=state.build.data,q=data?.quantity;
      if(state.phase||!q||!state.selected||!data.current||!Number.isSafeInteger(n)||n<q.min||n>q.max||n===q.current)return;
      const was=state.selected.build?.changes.find(c=>c.ordinal===data.ordinal);
      const base=was?was.base_quantity:q.current,original=was?was.before.product_code:data.current.product_code;
      const changes=changesOf(state.selected).filter(c=>c.ordinal!==data.ordinal);
      if(data.current.product_code!==original||n!==base)changes.push({ordinal:data.ordinal,product_code:data.current.product_code,...(n!==base?{quantity:n}:{})});
      return applyBuild(changes,r=>(data.label||'부품')+' 수량을 '+n+'개로 바꿨어요. 금액은 '+r.total.toLocaleString('ko-KR')+'원이에요(한 대 기준).');
    }
    // 같은 구성 여러 대. 금액(price)은 한 대 값 그대로, 대수만 상품에 둔다 -- 보관·쇼핑몰 연결에서 서버가 다시 곱한다.
    function setSets(n){
      const p=state.selected;
      if(state.phase||!p||state.screen!=='detail'||!Number.isSafeInteger(n)||n<1||n>MAX_SETS||n===(p.sets||1))return;
      const next={...p};if(n>1)next.sets=n;else delete next.sets;
      state.selected=next;state.savedQuote=null;state.saveState='idle';state.needsRefresh=false;state.handoff=null;emit();
    }
    // 패널이 닫힌 채 실행한 되돌리기가 실패하면 오류를 둘 자리가 없다 -- 그 줄의 패널을 오류 상태로 열어 사유를 보인다(조용히 삼키지 않는다).
    function surfaceBuildError(ordinal){
      if(state.build.ordinal===null&&state.build.error){const message=state.build.error;state.build={ordinal,data:null,error:message};emit();}
    }
    async function resetBuild(){
      if(state.phase||!state.selected?.build)return;
      const first=state.selected.build.changes[0].ordinal;state.build=emptyBuild();
      await applyBuild([],q=>'바꾼 부품을 모두 되돌렸어요. 기본 구성 PC 총액 '+q.total.toLocaleString('ko-KR')+'원이에요.');
      surfaceBuildError(first);
    }
    // 한 줄만 원래 부품으로(상세 v2 줄의 「기본 부품으로」). 나머지 변경과 수량은 그대로 두고 서버가 금액을 다시 계산한다.
    async function undoBuild(ordinal){
      const c=state.selected?.build?.changes.find(x=>x.ordinal===ordinal);
      if(state.phase||!c)return;
      const changes=changesOf(state.selected).filter(x=>x.ordinal!==ordinal);state.build=emptyBuild();
      await applyBuild(changes,q=>c.label+' 부품을 원래 부품 「'+c.before.name+'」으로 되돌렸어요. 바꾼 구성 PC 총액은 '+q.total.toLocaleString('ko-KR')+'원이에요(한 대 기준).');
      surfaceBuildError(ordinal);
    }
    async function list(){
      const op=begin('list');state.screen='saved';emit();
      try{
        const response=await api.listSaved({signal:op.signal});
        if(!current(op))return;
        if(response?.ok!==true||!Array.isArray(response.quotes))throw new Error('보관 목록을 확인할 수 없어요.');
        const quotes=response.quotes.map(M.quote);
        if(quotes.some(x=>!x))throw new Error('보관 목록의 형식을 확인할 수 없어요.');
        state.quotes=quotes;state.hasMore=response.has_more===true;
      }catch(error){if(current(op))fail(error,{kind:'list'});}
      finally{if(current(op)){state.phase=null;controller=null;emit();}}
    }
    // 보관 견적을 열어도 같은 상담이다(대화가 남는다). 잡담 횟수는 새로 세되, 이미 PC 상담을 권했거나
    // 고객이 거절한 사실은 이어 준다 -- 열자마자 다시 권하지 않게(코덱스 #145 검수 3). 「새 상담」만 지운다.
    function offerFlags(flow){
      const f=M.object(flow)?flow:{},keep={};
      if(f.pc_offered===true)keep.pc_offered=true;
      if(f.pc_declined===true)keep.pc_declined=true;
      return Object.keys(keep).length?keep:null;
    }
    function load(id){
      if(state.phase)return;
      const q=state.quotes.find(q=>q.id===id);if(!q)return;
      cancel();state.inquiry=emptyInquiry();state.parts=emptyParts();state.build=emptyBuild();state.selectedContext=null;state.selected=M.copy(q.product);state.selectionState=M.copy(q.state);state.selectionWants=null;state.talk=M.copy(q.state);state.chatFlow=offerFlags(state.chatFlow);state.history=[];
      state.keep=emptyKeep();state.mall=emptyMall();state.consult={...emptyConsult(),done:state.consult.done};
      state.savedQuote=M.copy(q);state.saveState='saved';state.needsRefresh=false;state.error=null;state.retry=null;state.screen='final';
      message('이 브라우저에서 보관한 '+q.product.name+'을 불러왔어요. 금액과 상품 기록은 보관 시점 기준입니다. 부품 구성과 사진은 조회 시점의 공개 상태를 따릅니다.');emit();
    }
    async function retry(){
      if(state.phase||!state.retry||Date.now()<(state.error?.retryAt||0))return;
      const task=state.retry;
      if(task.kind==='talk')await submit(task.text,{repeat:true});
      else if(task.kind==='recommend')await refresh();
      else if(task.kind==='resume')await resume();
      else if(task.kind==='reprice')await reprice();
      else if(task.kind==='save')await save();
      else if(task.kind==='recover')await recover();
      else if(task.kind==='list')await list();
      else if(task.kind==='handoff')await handoff();
      else if(task.kind==='keep')await openKeep();
    }
    return {state,reset,submit,refresh,resume,reprice,explore,select,navigate,save,recover,list,load,retry,cancel,message,emit,handoff,openInquiry,closeInquiry,inquiryDraft,inquire,loadContact,openKeep,openContactChange,closeKeep,keepDraft,keepEditing,submitKeep,consultToggle,loadConsultTopics,consultTopic,consultDraft,consultRows,consult,openMall,closeMall,mallHandoff,openParts,closeParts,swapPart,openBuild,closeBuild,pickBuild,resetBuild,undoBuild,setBuildQuantity,setSets};
  }
  // 「쇼핑몰에서 구매 이어가기」 한 번으로 쇼핑몰까지 간다(2026-10-12 중헌 님 고객단 6번: 연결 번호가 생긴 뒤 같은 단추를
  // 한 번 더 눌러야 쇼핑몰이 열렸다). 연결 번호는 그대로 만든다 -- 인계 기록(관리자 「인계 기록」·유입 성과)과 쇼핑몰 가격
  // 재확인, 부품을 바꾼 견적의 차액 기록이 이 번호에 걸린다(api/mvp3_handoff). 고객에게는 화면에 남겨 두기만 한다.
  // 새 창은 누른 순간에 열어 둔다 -- 서버 응답을 기다린 뒤 열면 브라우저가 팝업으로 막는다. 연결에 실패하면 그 창을 닫고,
  // 창이 막혔으면(open 이 null) 화면에 남는 「쇼핑몰 상품 페이지 열기」 링크로 간다.
  async function handoffAndOpen(flow,win){
    let tab=null;
    try{tab=win.open('','_blank');}catch{tab=null;}
    try{if(tab)tab.document.title='팝콘PC 쇼핑몰로 연결하는 중';}catch{}
    await flow.handoff();
    const h=flow.state.handoff,q=flow.state.savedQuote;
    const ok=!!(h&&q&&h.quote_id===q.id&&h.mall_url);
    if(!tab)return ok;
    if(!ok){try{tab.close();}catch{}return false;}
    try{tab.opener=null;tab.location.href=h.mall_url;}catch{try{tab.close();}catch{}return false;}
    return true;
  }
  // ===== 견적 보관 창 · 보관 견적서의 상담 신청 접수 칸 (2026-10-16 두 구매 흐름) =====
  // index(app.js)와 대화 화면(talk.js)이 같은 조각을 쓴다 -- 두 화면에 따로 그리면 한쪽만 고쳐진다.
  // 문구 정본: 대표 전달 「화면별-문구-정본.csv」. 번호·금액은 서버가 준 값만 쓴다(가린 번호 · 신청 번호 · 보관 견적 번호는 견적 id 에서 앞 8자리).
  // page:true(index) -- 보관 창을 띄우지 않고 화면(app.js)이 pageHtml() 을 상세 자리에 그린다(승인 시안 07·08 「견적 보관」 화면).
  // 대화 화면(talk.js)은 지금처럼 창으로 쓴다.
  function createKeepUi(flow,doc,opts={}){
    const page=opts.page===true;
    const state=flow.state,esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const money=v=>Number.isInteger(v)?v.toLocaleString('ko-KR')+'원':'금액 미확인';
    const quoteNo=id=>'Q-'+String(id||'').slice(0,8).toUpperCase();
    let el=null,sig='',opener=null;
    const ORDER_LINE='상담 신청 순서대로 연락드리겠습니다.',NO_CALL='상담을 신청하기 전에는 먼저 연락드리지 않아요.';
    function summary(){
      const p=state.selected;if(!p)return '';
      const sets=Number.isSafeInteger(p.sets)&&p.sets>1?p.sets:1,note=M.changedPartsNote?M.changedPartsNote(p.build):'';
      return '<div class="keep-sum"><strong>'+esc(p.name)+'</strong>'+(note?'<small>'+esc(note)+'</small>':'')+
        '<span class="keep-sum-price">'+money(p.price)+'<small> · '+sets+'대'+(sets>1&&Number.isInteger(p.price)?' · 합계 '+money(p.price*sets):'')+'</small></span></div>';
    }
    function inputs(k,tag='h4'){
      const d=k.draft,dis=k.busy?' disabled':'';
      return '<'+tag+'>연락받을 정보</'+tag+'>'+
        '<label class="keep-field"><span>전화번호 <em>필수</em></span><input data-keep="phone" type="tel" maxlength="20" autocomplete="tel" inputmode="tel" placeholder="010-1234-5678" value="'+esc(d.phone)+'"'+dis+'></label>'+
        '<p class="keep-note">'+NO_CALL+'</p>'+
        '<div class="keep-two"><label class="keep-field"><span>이름 <em>선택</em></span><input data-keep="name" maxlength="30" autocomplete="name" placeholder="이름을 입력해 주세요" value="'+esc(d.name)+'"'+dis+'></label>'+
        '<label class="keep-field"><span>이메일 <em>선택</em></span><input data-keep="email" type="email" maxlength="120" autocomplete="email" placeholder="example@email.com" value="'+esc(d.email)+'"'+dis+'></label></div>'+
        '<label class="keep-consent"><input type="checkbox" data-keep="consent"'+(d.consent?' checked':'')+dis+'><span>개인정보 수집·이용 동의 (필수)</span></label>'+
        '<details class="keep-consent-text"><summary>동의 내용 보기</summary><p>'+esc(state.contact.consentText||'동의 내용을 불러오지 못했어요. 닫았다가 다시 열어 주세요.')+'</p></details>';
    }
    function dialogHtml(){
      const k=state.keep,has=state.contact.has,showInputs=k.purpose==='contact'||!has||k.editing,dis=k.busy?' disabled':'';
      const consultFirst=k.purpose==='contact'&&k.after==='consult',contactOnly=k.purpose==='contact'&&!consultFirst;
      const title=consultFirst?'연락처 등록':contactOnly?'연락처 변경':'견적 보관';
      const sub=consultFirst?'상담 신청을 접수하려면 전화번호가 필요해요.':contactOnly?'바꾼 연락처는 앞으로 보관하거나 신청하는 견적에 쓰여요. 이미 보관한 견적은 그대로예요.':
        (!has?'전화번호는 처음 보관할 때 한 번만 입력해 주세요.':'등록한 연락처로 새 견적을 보관해요.');
      let body='';
      if(k.purpose==='save')body+=summary();
      if(k.purpose==='save'&&has){
        body+='<div class="keep-reg"><span>등록된 연락처</span><strong>'+esc(state.contact.masked)+'</strong>'+
          (k.editing?'<button type="button" class="keep-link" data-kact="edit-cancel"'+dis+'>연락처 변경 취소</button>':'<button type="button" class="keep-link" data-kact="edit"'+dis+'>연락처 변경</button>')+'</div>';
        if(!k.editing)body+='<p class="keep-note">이 연락처로 견적을 보관해요.</p><p class="keep-note keep-nocall">'+NO_CALL+'</p>';
      }
      if(showInputs)body+=inputs(k);
      let err='';
      if(k.error)err=k.failed?'<div class="keep-error" role="alert" tabindex="-1"><strong>'+(k.purpose==='save'?'견적을 보관하지 못했어요.':'연락처를 저장하지 못했어요.')+'</strong><p>'+(k.purpose==='save'?'선택한 부품과 금액은 그대로예요. ':'')+esc(k.error)+'</p></div>':
        '<p class="keep-error" role="alert" tabindex="-1">'+esc(k.error)+'</p>';
      const go=k.busy?'처리하는 중…':k.purpose==='save'?(k.failed?'다시 보관하기':'견적 보관'):consultFirst?'등록하고 상담 신청 접수':'연락처 저장';
      return '<div class="mall-dlg-card keep-dlg-card" role="dialog" aria-modal="true" aria-labelledby="keep-title"><h3 id="keep-title" tabindex="-1">'+title+'</h3><p class="keep-sub">'+sub+'</p>'+
        body+err+'<div class="keep-actions"><button type="button" class="primary" data-kact="submit"'+dis+'>'+go+'</button>'+
        '<button type="button" class="outline" data-kact="cancel"'+dis+'>취소</button></div>'+
        (k.purpose==='save'&&!has?'<p class="keep-foot">구매 상담 신청은 보관 후 진행할 수 있어요.</p>':'')+'</div>';
    }
    // 보관 화면(page). steps·summary 는 화면이 그려 준다(견적 진행 단계 · 구성 요약).
    function pageHtml({steps='',summary:sum=''}={}){
      const k=state.keep,has=state.contact.has,showInputs=k.purpose==='contact'||!has||k.editing,dis=k.busy?' disabled':'';
      const consultFirst=k.purpose==='contact'&&k.after==='consult',contactOnly=k.purpose==='contact'&&!consultFirst;
      const title=consultFirst?'연락처 등록':contactOnly?'연락처 변경':'견적 보관';
      const sub=consultFirst?'상담 신청을 접수하려면 전화번호가 필요해요.':contactOnly?'바꾼 연락처는 앞으로 보관하거나 신청하는 견적에 쓰여요. 이미 보관한 견적은 그대로예요.':
        (!has?'전화번호는 처음 보관할 때 한 번만 입력해 주세요.':'등록한 연락처로 새 견적을 보관해요.');
      let body='';
      if(k.purpose==='save')body+=sum||summary();
      if(k.purpose==='save'&&has){
        body+='<div class="keep-reg tf-reg"><span>등록된 연락처</span><strong>'+esc(state.contact.masked)+'</strong>'+
          (k.editing?'<button type="button" class="keep-link" data-kact="edit-cancel"'+dis+'>연락처 변경 취소</button>':'<button type="button" class="keep-link" data-kact="edit"'+dis+'>연락처 변경</button>')+'</div>';
        if(!k.editing)body+='<p class="keep-note">이 연락처로 견적을 보관해요.</p><p class="keep-note keep-nocall">'+NO_CALL+'</p>';
      }
      let err='';
      if(k.error)err=k.failed?'<div class="keep-error" role="alert" tabindex="-1"><strong>'+(k.purpose==='save'?'견적을 보관하지 못했어요.':'연락처를 저장하지 못했어요.')+'</strong><p>'+(k.purpose==='save'?'선택한 부품과 금액은 그대로예요. ':'')+esc(k.error)+'</p></div>':
        '<p class="keep-error" role="alert" tabindex="-1">'+esc(k.error)+'</p>';
      const go=k.busy?'처리하는 중…':k.purpose==='save'?(k.failed?'다시 보관하기':'견적 보관'):consultFirst?'등록하고 상담 신청 접수':'연락처 저장';
      return '<section class="tf-page tf-keep" data-keep-page>'+steps+'<p class="tf-eyebrow">'+(k.purpose==='save'?'내 견적':'연락처')+'</p><h2 id="keep-title" tabindex="-1">'+title+'</h2><p class="tf-sub">'+sub+'</p>'+
        body+(showInputs?'<div class="tf-keep-form">'+inputs(k,'h3')+'</div>':'')+'<div class="tf-keep-actions">'+err+
        '<button type="button" class="primary tf-wide" data-kact="submit"'+dis+'>'+go+'</button>'+
        (k.purpose==='save'&&!has?'<p class="keep-foot">구매 상담 신청은 보관 후 진행할 수 있어요.</p>':'')+
        '<button type="button" class="tf-textbtn" data-kact="cancel"'+dis+'>취소</button></div></section>';
    }
    function valuesIn(root){
      const out={};for(const e of root.querySelectorAll('[data-keep]'))out[e.dataset.keep]=e.type==='checkbox'?e.checked:e.value;return out;
    }
    if(page){
      // 보관 화면의 단추·입력. 상세의 「다시 보관하기」([data-keep-retry])는 적어 둔 값 그대로 다시 보낸다.
      doc.addEventListener('click',e=>{
        const b=e.target.closest?.('[data-kact]');if(!b||b.disabled||!b.closest('[data-keep-page],[data-keep-retry]'))return;
        e.preventDefault();const root=doc.querySelector('[data-keep-page]'),vals=root?valuesIn(root):{},a=b.dataset.kact;
        if(a==='cancel')flow.closeKeep();else if(a==='edit')flow.keepEditing(true);else if(a==='edit-cancel')flow.keepEditing(false);
        else if(a==='submit')void flow.submitKeep(vals);
      });
      const sink=e=>{const root=e.target.closest?.('[data-keep-page]');if(root&&e.target.dataset?.keep)flow.keepDraft(valuesIn(root));};
      doc.addEventListener('input',sink);doc.addEventListener('change',sink);
      doc.addEventListener('keydown',e=>{const root=e.target.closest?.('[data-keep-page]');if(root&&e.key==='Enter'&&e.target.matches('input:not([type=checkbox])')){e.preventDefault();void flow.submitKeep(valuesIn(root));}});
    }
    function values(){
      const out={};for(const e of el.querySelectorAll('[data-keep]'))out[e.dataset.keep]=e.type==='checkbox'?e.checked:e.value;return out;
    }
    function focusables(){return [...el.querySelectorAll('input:not([disabled]),button:not([disabled]),summary,[tabindex="-1"]:not(h3)')].filter(x=>x.tabIndex>=0);}
    function onKey(e){
      if(!el)return;
      if(e.key==='Escape'){e.preventDefault();e.stopPropagation();flow.closeKeep();return;}
      if(e.key!=='Tab')return;
      const items=focusables();if(!items.length)return;
      const first=items[0],last=items[items.length-1],now=doc.activeElement;
      if(!el.contains(now)){e.preventDefault();first.focus();}
      else if(e.shiftKey&&now===first){e.preventDefault();last.focus();}
      else if(!e.shiftKey&&now===last){e.preventDefault();first.focus();}
    }
    function close(){
      if(!el)return;el.remove();el=null;sig='';doc.removeEventListener('keydown',onKey,true);
      const target=opener&&opener.isConnected?opener:doc.querySelector('[data-action=save],[data-action=contact-change]');
      opener=null;target?.focus?.({preventScroll:true});
    }
    // 화면을 다시 그릴 때마다 부른다. 보관 창 상태가 바뀐 때만 창을 다시 만든다(적는 중에는 건드리지 않는다).
    function sync(){
      if(page)return;
      const k=state.keep;
      if(!k.open){close();return;}
      const next=JSON.stringify([k.purpose,k.after,k.editing,k.busy,k.error,k.failed,state.contact.has,state.contact.masked,state.contact.consentText,state.selected?.product_code,state.selected?.price]);
      if(el&&next===sig)return;
      const fresh=!el;
      if(fresh){opener=doc.activeElement&&doc.activeElement!==doc.body?doc.activeElement:null;
        el=doc.createElement('div');el.className='mall-dlg keep-dlg';el.dataset.keepDialog='';
        el.addEventListener('click',e=>{
          if(e.target===el){flow.closeKeep();return;}
          const b=e.target.closest('[data-kact]');if(!b||b.disabled)return;
          const a=b.dataset.kact;
          if(a==='cancel')flow.closeKeep();else if(a==='edit')flow.keepEditing(true);else if(a==='edit-cancel')flow.keepEditing(false);
          else if(a==='submit')void flow.submitKeep(values());
        });
        const sink=()=>flow.keepDraft(values());el.addEventListener('input',sink);el.addEventListener('change',sink);
        el.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.matches('input:not([type=checkbox])')){e.preventDefault();void flow.submitKeep(values());}});
        doc.body.append(el);doc.addEventListener('keydown',onKey,true);}
      else flow.keepDraft(values());
      sig=next;el.innerHTML=dialogHtml();
      const target=fresh?el.querySelector('#keep-title'):(el.querySelector('.keep-error')||el.querySelector('input:not([disabled])')||el.querySelector('#keep-title'));
      target?.focus({preventScroll:true});
    }
    // 보관 견적서 아래 칸: 보관 완료 · 연락처 · 상담 신청 접수 · 접수 결과.
    function doneRows(c){
      return '<dl class="consult-rows"><div><dt>상담 신청 번호</dt><dd>'+esc(c.inquiry_no)+'</dd></div><div><dt>함께 보낸 견적</dt><dd>'+esc(quoteNo(c.quote_id))+'</dd></div>'+
        '<div><dt>연락받을 전화번호</dt><dd>'+esc(c.masked_phone)+'</dd></div></dl>';
    }
    function panelHtml(){
      const q=state.savedQuote;if(!q||state.saveState!=='saved')return '';
      const c=state.consult,done=c.done&&c.done.quote_id===q.id?c.done:null,busy=!!state.phase;
      const reg=state.contact.has?'<div class="keep-reg"><span>등록된 연락처</span><strong>'+esc(state.contact.masked)+'</strong>'+
        '<button type="button" class="keep-link" data-action="contact-change"'+(busy?' disabled':'')+'>연락처 변경</button></div>':'';
      let consult;
      if(done){
        consult='<section class="consult-done" role="status" data-consult-done="'+(done.already?'already':'new')+'"><h4>'+(done.already?'이미 상담 신청이 접수된 견적이에요':'상담 신청이 접수됐어요')+'</h4>'+
          '<p class="consult-order">'+ORDER_LINE+'</p>'+
          (done.already&&!c.showRows?'<button type="button" class="outline" data-action="consult-rows" data-show="1">상담 접수 내역 보기</button>':doneRows(done))+
          '<p class="muted">주문·결제는 아직 진행되지 않았어요.</p></section>';
      }else{
        const note=c.open?'<div class="consult-note"><p class="consult-topic"><span>상담 주제</span><strong>주문 희망</strong></p>'+
          '<label class="keep-field"><span>상담할 내용 <em>선택</em></span><textarea data-consult-message maxlength="500" rows="3" placeholder="궁금한 점이나 연락받기 편한 때를 적어 주세요."'+(busy?' disabled':'')+'>'+esc(c.message)+'</textarea></label>'+
          '<small class="consult-count">'+c.message.length+' / 500자</small></div>':'';
        consult='<section class="consult-ask" data-consult-ask><h4>필요할 때 상담을 신청해 주세요.</h4><p>보관한 견적과 등록한 전화번호로 상담을 접수해요.</p>'+note+
          (c.error?'<div class="keep-error" role="alert"><strong>상담 신청을 접수하지 못했어요.</strong><p>보관한 견적과 입력한 내용은 그대로예요. '+esc(c.error)+' 다시 신청해 주세요.</p></div>':'')+
          '<div class="consult-buttons"><button type="button" class="primary" data-action="consult-send"'+(busy?' disabled':'')+'>'+(state.phase==='consult'?'접수하는 중…':'상담 신청 접수')+'</button>'+
          '<button type="button" class="keep-link" data-action="consult-note"'+(busy?' disabled':'')+'>'+(c.open?'상담할 내용 닫기':'상담할 내용 남기기 (선택)')+'</button></div>'+
          '<p class="keep-note">상담 신청만 접수돼요. 주문·결제는 진행되지 않아요.</p></section>';
      }
      return '<section class="live-explanation keep-done" data-keep-done><h3>견적을 보관했어요</h3><p class="muted">선택한 부품과 금액을 다시 볼 수 있어요.</p>'+
        '<p class="keep-qno"><span>보관 견적</span><strong>'+esc(quoteNo(q.id))+'</strong></p>'+reg+'<p class="keep-note keep-nocall">'+NO_CALL+'</p>'+consult+'</section>';
    }
    // 화면의 data-action 을 처리하면 true.
    function handle(action,b){
      switch(action){
        case 'save':void flow.openKeep();return true;
        case 'contact-change':void flow.openContactChange();return true;
        case 'consult-send':{const t=doc.querySelector('[data-consult-message]');if(t)flow.consultDraft(t.value);void flow.consult();return true;}
        case 'consult-note':{const t=doc.querySelector('[data-consult-message]');flow.consultToggle(!state.consult.open,t?t.value:undefined);return true;}
        case 'consult-rows':flow.consultRows(true);return true;
        default:return false;
      }
    }
    doc.addEventListener('input',e=>{if(e.target?.matches?.('[data-consult-message]')){flow.consultDraft(e.target.value);const n=doc.querySelector('.consult-count');if(n)n.textContent=e.target.value.length+' / 500자';}});
    return {sync,panelHtml,pageHtml,handle,quoteNo,close,NO_CALL,ORDER_LINE,doneRows};
  }
  // 쇼핑몰 완제품 「팝콘PC로 이동」(2026-10-16 두 구매 흐름). 새 창은 누른 순간에 열어 둔다(서버 응답 뒤에 열면 팝업으로 막힌다).
  // 인계 기록이 성공한 뒤에만 그 창을 쇼핑몰 주소로 옮긴다. 실패하면 창을 닫고 이동 완료 화면을 보이지 않는다.
  // 창이 막혔으면(open 이 null) 안내창의 「상품 페이지 다시 보기」 링크가 같은 주소를 연다 -- 인계 번호를 다시 만들지 않는다.
  async function moveToMall(flow,win){
    const s=flow.state;
    if(s.phase||s.mall.step==='moving')return false;
    let tab=null;
    try{tab=win.open('','_blank');}catch{tab=null;}
    try{if(tab)tab.document.title='팝콘PC로 이동하는 중';}catch{}
    s.mall={...s.mall,open:true,step:'moving',error:'',blocked:false};flow.emit();
    const ok=await flow.mallHandoff();
    if(!ok){try{tab?.close();}catch{}flow.emit();return false;}
    let moved=false;
    if(tab){try{tab.opener=null;tab.location.href=s.handoff.mall_url;moved=true;}catch{try{tab.close();}catch{}}}
    s.mall={...s.mall,step:'moved',error:'',blocked:!moved};flow.emit();
    return true;
  }
  if(typeof module!=='undefined')module.exports={moveToMall,createKeepUi,createFlow,GREETING,JOURNAL_KEY,validPending,inquiryProblem,inquiryHtml,CONVERSATION_KEY,conversationSnapshot,validConversation,DRAFT_KEY,DRAFT_TTL_MS,createDraftHandoff,handoffAndOpen};else root.MVP3LiveFlow={moveToMall,createKeepUi,createFlow,GREETING,inquiryProblem,inquiryHtml,createDraftHandoff,handoffAndOpen};
})(typeof window==='undefined'?globalThis:window);
