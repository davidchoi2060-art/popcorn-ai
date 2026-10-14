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
      messages:(state.messages||[]).slice(-CONVERSATION_MAX_MESSAGES).filter(m=>m&&['user','ai'].includes(m.who)).map(m=>({who:m.who,text:text(m.text)})),
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
  function createFlow(api,options={}){
    const changed=options.onChange||(()=>{}), uuid=options.uuid||(()=>root.crypto.randomUUID());
    // keepCurrent: 2차 대화 화면(talk.html). 고객이 고른 구성(지금 견적)은 새 조건·새 추천이 와도 지우지 않고,
    // 고객이 다른 구성을 고를 때만 바뀐다(코덱스 1816 보강3 §5). 1차 화면은 지금처럼 새 조건에서 비운다.
    const keepCurrent=options.keepCurrent===true;let proposalSeq=0;
    const state={screen:'welcome',talk:null,chatFlow:null,history:[],messages:[],groups:[],recommendation:null,
      selected:null,selectionState:null,selectionWants:null,selectionQuery:null,lastQuery:null,savedQuote:null,quotes:[],hasMore:false,phase:null,error:null,retry:null,
      saveState:'idle',needsRefresh:false,lastText:'',missing:[],assumed:[],pendingSave:null,pendingProblem:'',handoff:null,
      wants:null,choices:[],anchorCode:null,pendingText:'',inquiry:emptyInquiry(),parts:emptyParts(),build:emptyBuild(),selectedContext:null,handoffOffer:false,restoredCurrent:null,restoredShown:false,proposals:[]};
    let generation=0,controller=null,pendingProduct=null;const saveIds=new Map(),journal=createJournal(options),conversation=createConversationStore(options);
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
    function reset({restore=false}={}){
      cancel();Object.assign(state,{restoredCurrent:null,restoredShown:false,proposals:[],screen:'welcome',talk:null,chatFlow:null,history:[],messages:[],groups:[],recommendation:null,
        selected:null,selectionState:null,selectionWants:null,selectionQuery:null,lastQuery:null,savedQuote:null,quotes:[],hasMore:false,error:null,retry:null,saveState:'idle',needsRefresh:false,lastText:'',missing:[],assumed:[],handoff:null,
        wants:null,choices:[],anchorCode:null,pendingText:'',inquiry:emptyInquiry(),parts:emptyParts(),build:emptyBuild(),selectedContext:null,handoffOffer:false});
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
      const response=await api.recommend(state.talk,{signal:op.signal},{wants:state.wants,anchor_code:state.anchorCode,...extra});
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
      state.proposals=[...state.proposals,{id:++proposalSeq,at:state.messages.length,groups:parsed.groups,talk:M.copy(state.talk)}].slice(-10);
      state.history=state.history.slice(-6);
      if(!keepCurrent){state.selected=null;state.selectionState=null;state.selectionWants=null;state.selectionQuery=null;state.savedQuote=null;state.saveState='idle';state.needsRefresh=false;}
      state.screen='results';
      if(parsed.unsupported&&!parsed.groups.length)message('현재 추천 원천은 이 화면의 판매 중 PC 목록과 연결되지 않았어요. 상담 조건은 유지됩니다.');
    }
    async function submit(raw,{repeat=false,entry=null}={}){
      const text=String(raw||'').trim();
      if(!text||text.length>MAX_TEXT||state.phase)return false;
      const previous=state.history.slice(-6),previousTalk=state.talk,op=begin('talk');
      state.lastText=text;if(!repeat)message(text,'user');emit();
      // 새 조건으로 다시 찾다가 실패하면 보던 견적으로 되돌린다(코덱스 PR136 검수 「추천 실패 때 이전 추천 복원」).
      let prior=null;
      try{
        // entry: 대화 화면 시작 단추로 시작한 문장이면 그 단추 키(서버가 로그로만 센다).
        const payload={text,state:state.talk,chat_flow:state.chatFlow,history:previous};if(entry)payload.entry=entry;
        const response=await api.parse(payload,{signal:op.signal});
        if(!current(op))return false;
        if(!M.object(response)||response.ok!==true||!M.object(response.state))throw new Error('상담 응답 형식을 확인할 수 없어요.');
        // 잡담·범위 밖 질문이 조건을 바꾸지 않았으면 보던 견적을 지우지 않는다(코덱스 1816 「앞서 말한 조건과 보던 견적을 잃지 않기」).
        const keep=!!state.recommendation&&(response.pc_related===false||!!response.fallback)&&JSON.stringify(response.state)===JSON.stringify(state.talk);
        state.talk=M.copy(response.state);state.chatFlow=M.object(response.chat_flow)?M.copy(response.chat_flow):null;
        state.history.push({role:'user',text:text.slice(0,1000)});
        const answer=M.text(response.answer),reply=M.text(response.reply);
        if(!response.silent){
          // 답을 먼저 충분히 하고, PC 이야기는 같은 말풍선 끝에 짧게 붙인다(코덱스 1816 보강2).
          message([answer.trim(),reply.trim()].filter(Boolean).join('\n\n'),'ai');
          if(answer.trim())state.history.push({role:'assistant',text:answer.slice(0,300)});
          if(reply.trim())state.history.push({role:'assistant',text:reply.slice(0,300)});
        }
        // 예외 입력(이상한 말·사람 상담 요청·AI 가 못 읽은 말)에는 서버가 사람 상담 길을 연다(api/talk_exceptions).
        if(response.handoff_offer===true)state.handoffOffer=true;
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
      if(!p){const r=M.recommendations(await api.recommend(M.copy(basis),{signal:op.signal},{...(M.object(wants)?{wants:M.copy(wants)}:{}),...(q||{})}));if(!current(op))return undefined;p=pick(r.groups);}
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
    async function save(){
      if(state.phase||state.pendingSave||state.pendingProblem||!state.selected||!state.selectionState||state.needsRefresh||state.savedQuote||!Number.isInteger(state.selected.price))return;
      const selected=M.copy(state.selected),selectionState=M.copy(state.selectionState);
      const changes=changesOf(selected);
      const sets=Number.isSafeInteger(selected.sets)&&selected.sets>1?selected.sets:1;
      const logical=JSON.stringify([selected.product_code,selected.price,selectionState,changes].concat(sets>1?[sets]:[]));
      if(!saveIds.has(logical))saveIds.set(logical,uuid());
      const payload={request_id:saveIds.get(logical),product_code:selected.product_code,expected_price:selected.price,state:selectionState};
      if(changes.length)payload.changes=changes;
      if(sets>1)payload.sets=sets;
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
      if(error?.status===409){
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
      const response=await api.saveQuote(M.copy(record.payload),{signal:op.signal,existingKeyOnly:true});
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
      state.savedQuote=saved;state.saveState='saved';state.selected=saved.product;state.selectionState=saved.state;state.selectionWants=null;state.screen='final';
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
      const o=data.options.find(x=>x.product_code===code);if(!o)return;
      const before=state.selected;
      state.selectedContext=state.selectedContext||(state.groups||[]).find(g=>Number.isInteger(before.index)&&g.products.some(x=>x.index===before.index&&x.product_code===before.product_code))||null;
      const next=M.copy(o);delete next.swap;next.swap_from={product_code:before.product_code,slot:data.slot};state.build=emptyBuild();
      state.selected=next;state.savedQuote=null;state.saveState='idle';state.needsRefresh=false;state.handoff=null;
      state.inquiry=emptyInquiry();state.parts=emptyParts();state.error=null;state.retry=null;
      const d=o.swap.price_diff,diff=d===0?'지금과 같은 금액':(d>0?'+':'-')+Math.abs(d).toLocaleString('ko-KR')+'원';
      message(data.label+'를 '+o.swap.value+'로 바꿨어요. 이 구성으로 판매 중인 PC로 옮겨서 금액은 '+o.price.toLocaleString('ko-KR')+'원('+diff+')이에요.'+
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
      const o=data.options.find(x=>x.product_code===code);if(!o)return;
      const changes=changesOf(state.selected).filter(c=>c.ordinal!==data.ordinal);
      const was=state.selected.build?.changes.find(c=>c.ordinal===data.ordinal),original=was?.before.product_code;
      // 수량을 바꿔 둔 줄은 제품을 바꿔도 그 수량을 지킨다.
      const quantity=was&&was.quantity!==was.base_quantity?{quantity:was.quantity}:{};
      if(code!==original||quantity.quantity)changes.push({ordinal:data.ordinal,product_code:code,...quantity});
      const won=n=>n.toLocaleString('ko-KR')+'원';
      return applyBuild(changes,q=>(data.label||'부품')+' 부품을 「'+o.name+'」 제품으로 바꿨어요. 호환 규칙을 다시 확인했고, 금액은 '+won(q.total)+'이에요(기본 구성 '+won(q.base_price)+
        (q.total===q.base_price?'과 같아요).':(q.total>q.base_price?' + ':' - ')+won(Math.abs(q.total-q.base_price))+').'));
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
    function resetBuild(){
      if(state.phase||!state.selected?.build)return;
      return applyBuild([],q=>'바꾼 부품을 모두 되돌렸어요. 기본 구성 금액 '+q.total.toLocaleString('ko-KR')+'원이에요.');
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
    }
    return {state,reset,submit,refresh,resume,reprice,explore,select,navigate,save,recover,list,load,retry,cancel,message,emit,handoff,openInquiry,closeInquiry,inquiryDraft,inquire,openParts,closeParts,swapPart,openBuild,closeBuild,pickBuild,resetBuild,setBuildQuantity,setSets};
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
  if(typeof module!=='undefined')module.exports={createFlow,GREETING,JOURNAL_KEY,validPending,inquiryProblem,CONVERSATION_KEY,conversationSnapshot,validConversation,DRAFT_KEY,DRAFT_TTL_MS,createDraftHandoff,handoffAndOpen};else root.MVP3LiveFlow={createFlow,GREETING,createDraftHandoff,handoffAndOpen};
})(typeof window==='undefined'?globalThis:window);
