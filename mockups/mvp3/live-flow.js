/* Async consultation and saving state. A generation owns each pending response. */
(function(root){'use strict';
  const M=typeof module!=='undefined'?require('./live-model.js'):root.MVP3LiveModel;
  const JOURNAL_KEY='popcorn-mvp3-pending-save-v1';
  // 상담 한 번에 읽는 글자 수 -- 서버 api/talk.py MAX_TEXT_LEN 과 같다. 넘는 글은 서버가 앞부분만 읽고 알린다.
  const MAX_TEXT=1000;
  function validPending(record){
    const p=record?.payload;
    return M.object(record)&&record.version===1&&/^[a-f0-9]{64}$/.test(record.binding)&&M.object(p)
      &&['expected_price,product_code,request_id,state','changes,expected_price,product_code,request_id,state'].includes(Object.keys(p).sort().join(','))
      &&(p.changes===undefined||Array.isArray(p.changes)&&p.changes.length>0&&p.changes.length<=8&&p.changes.every(c=>M.object(c)&&Object.keys(c).sort().join(',')==='ordinal,product_code'&&Number.isSafeInteger(c.ordinal)&&c.ordinal>=0&&Number.isSafeInteger(c.product_code)&&c.product_code>0))
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
  // 구매 상담 신청 칸의 상태. 서버가 준 주제·동의 문구만 쓰고, 받은 신청 번호만 보여 준다.
  function emptyInquiry(){return {open:false,meta:null,draft:{topic:'',name:'',phone:'',email:'',message:'',consent:false},done:null,error:''};}
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
  function changesOf(p){return (p?.build?.changes||[]).map(c=>({ordinal:c.ordinal,product_code:c.after.product_code}));}
  function createFlow(api,options={}){
    const changed=options.onChange||(()=>{}), uuid=options.uuid||(()=>root.crypto.randomUUID());
    const state={screen:'welcome',talk:null,chatFlow:null,history:[],messages:[],groups:[],recommendation:null,
      selected:null,selectionState:null,savedQuote:null,quotes:[],hasMore:false,phase:null,error:null,retry:null,
      saveState:'idle',needsRefresh:false,lastText:'',missing:[],assumed:[],pendingSave:null,pendingProblem:'',handoff:null,
      wants:null,choices:[],anchorCode:null,pendingText:'',inquiry:emptyInquiry(),parts:emptyParts(),build:emptyBuild(),selectedContext:null,handoffOffer:false};
    let generation=0,controller=null,pendingProduct=null;const saveIds=new Map(),journal=createJournal(options);
    function emit(){changed(state);}
    function cancel(){if(state.phase==='save')state.saveState=state.pendingSave?'uncertain':'idle';generation++;controller?.abort();controller=null;state.phase=null;}
    function begin(phase){cancel();controller=new AbortController();state.phase=phase;state.error=null;state.retry=null;emit();return {id:generation,signal:controller.signal};}
    function current(op){return op.id===generation&&!op.signal.aborted;}
    function message(text,who='ai',extra={}){if(typeof text==='string'&&text.trim())state.messages.push({text,who,...extra});}
    function fail(error,retry){
      state.error={message:error?.message||'요청을 처리하지 못했어요.',status:error?.status||0,code:error?.code||'invalid_response',
        retryAfter:error?.retryAfter||0,retryAt:Date.now()+(error?.retryAfter||0)*1000};
      state.retry=retry;
    }
    function reset(){
      cancel();Object.assign(state,{screen:'welcome',talk:null,chatFlow:null,history:[],messages:[],groups:[],recommendation:null,
        selected:null,selectionState:null,savedQuote:null,quotes:[],hasMore:false,error:null,retry:null,saveState:'idle',needsRefresh:false,lastText:'',missing:[],assumed:[],handoff:null,
        wants:null,choices:[],anchorCode:null,pendingText:'',inquiry:emptyInquiry(),parts:emptyParts(),build:emptyBuild(),selectedContext:null,handoffOffer:false});
      try{state.pendingSave=journal.read();state.pendingProblem='';if(state.pendingSave)state.saveState='uncertain';}
      catch{state.pendingProblem='이 탭의 보관 복구 기록을 확인할 수 없어 새 보관 요청을 보내지 않습니다. 내 견적은 확인할 수 있어요.';}
      message('안녕하세요! 즐기는 게임과 예산을 알려주시면 나에게 맞는 PC를 함께 찾아드릴게요.');emit();
    }
    async function recommendFor(op,extra={}){
      state.phase='recommend';emit();
      const response=await api.recommend(state.talk,{signal:op.signal},{wants:state.wants,anchor_code:state.anchorCode,...extra});
      if(!current(op))return;
      if(extra.text!==undefined)state.pendingText='';
      const parsed=M.recommendations(response);
      state.recommendation=parsed;state.groups=parsed.groups;state.assumed=parsed.assumed;state.missing=parsed.needs;
      state.wants=parsed.wants;state.choices=parsed.choices;state.anchorCode=parsed.anchorCode;
      // What the server could and could not do with the request, then the follow-up question.
      for(const note of parsed.talkNotes){message(note);state.history.push({role:'assistant',text:note.slice(0,300)});}
      state.history=state.history.slice(-6);
      state.selected=null;state.selectionState=null;state.savedQuote=null;state.saveState='idle';state.needsRefresh=false;state.screen='results';
      if(parsed.unsupported&&!parsed.groups.length)message('현재 추천 원천은 이 화면의 판매 중 PC 목록과 연결되지 않았어요. 상담 조건은 유지됩니다.');
    }
    async function submit(raw,{repeat=false}={}){
      const text=String(raw||'').trim();
      if(!text||text.length>MAX_TEXT||state.phase)return false;
      const previous=state.history.slice(-6),op=begin('talk');
      state.lastText=text;if(!repeat)message(text,'user');emit();
      try{
        const response=await api.parse({text,state:state.talk,chat_flow:state.chatFlow,history:previous},{signal:op.signal});
        if(!current(op))return false;
        if(!M.object(response)||response.ok!==true||!M.object(response.state))throw new Error('상담 응답 형식을 확인할 수 없어요.');
        state.talk=M.copy(response.state);state.chatFlow=M.object(response.chat_flow)?M.copy(response.chat_flow):null;
        state.history.push({role:'user',text});
        const answer=M.text(response.answer),reply=M.text(response.reply);
        if(!response.silent){
          if(answer.trim()){message(answer,'ai');state.history.push({role:'assistant',text:answer.slice(0,300)});}
          if(reply.trim()){message(reply);state.history.push({role:'assistant',text:reply.slice(0,300)});}
        }
        // 예외 입력(이상한 말·사람 상담 요청·AI 가 못 읽은 말)에는 서버가 사람 상담 길을 연다(api/talk_exceptions).
        if(response.handoff_offer===true)state.handoffOffer=true;
        state.history=state.history.slice(-6);state.missing=Array.isArray(response.missing)?response.missing:[];state.assumed=Array.isArray(response.assumed)?response.assumed:[];
        state.selected=null;state.selectionState=null;state.savedQuote=null;state.saveState='idle';state.groups=[];state.recommendation=null;state.needsRefresh=false;
        // Sentences said while the server was still asking (e.g. 「램 64GB」 before the usage)
        // ride along until a recommendation actually reads them.
        state.pendingText=(state.pendingText?state.pendingText+' / '+text:text).slice(-300);
        if(state.missing.length||response.pc_related===false||response.silent||response.fallback){state.screen='welcome';}
        else {await recommendFor(op,{text:state.pendingText});}
      }catch(error){
        if(current(op)){fail(error,state.phase==='recommend'?{kind:'recommend'}:{kind:'talk',text});state.handoffOffer=true;}
      }finally{if(current(op)){state.phase=null;controller=null;emit();}}
      return true;
    }
    async function refresh(){
      if(!state.talk||state.phase)return;
      const op=begin('recommend');
      try{await recommendFor(op);}catch(error){if(current(op))fail(error,{kind:'recommend'});}
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
      cancel();state.inquiry=emptyInquiry();state.parts=emptyParts();state.build=emptyBuild();state.selectedContext=null;state.selected=M.copy(p);state.selectionState=M.copy(state.talk);state.savedQuote=null;state.saveState='idle';state.needsRefresh=false;state.error=null;state.retry=null;state.screen='detail';emit();
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
      const logical=JSON.stringify([selected.product_code,selected.price,selectionState,changes]);
      if(!saveIds.has(logical))saveIds.set(logical,uuid());
      const payload={request_id:saveIds.get(logical),product_code:selected.product_code,expected_price:selected.price,state:selectionState};
      if(changes.length)payload.changes=changes;
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
        fail(error,{kind:'recommend'});
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
      state.savedQuote=saved;state.saveState='saved';state.selected=saved.product;state.selectionState=saved.state;state.talk=M.copy(saved.state);state.screen='final';
    }
    async function recover(){
      if(state.phase||!state.pendingSave)return;
      const record=M.copy(state.pendingSave),op=begin('save');
      state.selected=pendingProduct||M.product({product_code:record.payload.product_code,name:'보관 요청한 PC · 상품번호 '+record.payload.product_code,price:record.payload.expected_price});
      state.selectionState=M.copy(record.payload.state);state.savedQuote=null;state.screen='final';state.saveState='saving';emit();
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
          delta:Array.isArray(r.changes)?r.changes.reduce((n,c)=>n+(Number.isSafeInteger(c?.delta)?c.delta:0),0):0};
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
    async function openInquiry(){
      if(state.phase)return;
      state.inquiry.open=true;state.inquiry.error='';
      // 상품을 고르기 전(상담 중) 사람 상담: 주제 「기타」와 마지막 문장을 미리 채운다 -- 고객이 고칠 수 있다.
      if(!state.selected&&!state.inquiry.draft.topic&&!state.inquiry.draft.message){state.inquiry.draft.topic='기타';state.inquiry.draft.message=String(state.lastText||'').slice(0,500);}
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
      const next=M.copy(o);delete next.swap;state.build=emptyBuild();
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
      const original=state.selected.build?.changes.find(c=>c.ordinal===data.ordinal)?.before.product_code;
      if(code!==original)changes.push({ordinal:data.ordinal,product_code:code});
      const won=n=>n.toLocaleString('ko-KR')+'원';
      return applyBuild(changes,q=>(data.label||'부품')+' 부품을 「'+o.name+'」 제품으로 바꿨어요. 호환 규칙을 다시 확인했고, 금액은 '+won(q.total)+'이에요(기본 구성 '+won(q.base_price)+
        (q.total===q.base_price?'과 같아요).':(q.total>q.base_price?' + ':' - ')+won(Math.abs(q.total-q.base_price))+').'));
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
    function load(id){
      if(state.phase)return;
      const q=state.quotes.find(q=>q.id===id);if(!q)return;
      cancel();state.inquiry=emptyInquiry();state.parts=emptyParts();state.build=emptyBuild();state.selectedContext=null;state.selected=M.copy(q.product);state.selectionState=M.copy(q.state);state.talk=M.copy(q.state);state.chatFlow=null;state.history=[];
      state.savedQuote=M.copy(q);state.saveState='saved';state.needsRefresh=false;state.error=null;state.retry=null;state.screen='final';
      message('이 브라우저에서 보관한 '+q.product.name+'을 불러왔어요. 금액과 상품 기록은 보관 시점 기준입니다. 부품 구성과 사진은 조회 시점의 공개 상태를 따릅니다.');emit();
    }
    async function retry(){
      if(state.phase||!state.retry||Date.now()<(state.error?.retryAt||0))return;
      const task=state.retry;
      if(task.kind==='talk')await submit(task.text,{repeat:true});
      else if(task.kind==='recommend')await refresh();
      else if(task.kind==='save')await save();
      else if(task.kind==='recover')await recover();
      else if(task.kind==='list')await list();
      else if(task.kind==='handoff')await handoff();
    }
    return {state,reset,submit,refresh,explore,select,navigate,save,recover,list,load,retry,cancel,message,emit,handoff,openInquiry,closeInquiry,inquiryDraft,inquire,openParts,closeParts,swapPart,openBuild,closeBuild,pickBuild,resetBuild};
  }
  if(typeof module!=='undefined')module.exports={createFlow,JOURNAL_KEY,validPending,inquiryProblem};else root.MVP3LiveFlow={createFlow};
})(typeof window==='undefined'?globalThis:window);
