/* Async consultation and saving state. A generation owns each pending response. */
(function(root){'use strict';
  const M=typeof module!=='undefined'?require('./live-model.js'):root.MVP3LiveModel;
  const JOURNAL_KEY='popcorn-mvp3-pending-save-v1';
  function validPending(record){
    const p=record?.payload;
    return M.object(record)&&record.version===1&&/^[a-f0-9]{64}$/.test(record.binding)&&M.object(p)
      &&Object.keys(p).sort().join(',')==='expected_price,product_code,request_id,state'
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
  function createFlow(api,options={}){
    const changed=options.onChange||(()=>{}), uuid=options.uuid||(()=>root.crypto.randomUUID());
    const state={screen:'welcome',talk:null,chatFlow:null,history:[],messages:[],groups:[],recommendation:null,
      selected:null,selectionState:null,savedQuote:null,quotes:[],hasMore:false,phase:null,error:null,retry:null,
      saveState:'idle',needsRefresh:false,lastText:'',missing:[],assumed:[],pendingSave:null,pendingProblem:''};
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
        selected:null,selectionState:null,savedQuote:null,quotes:[],hasMore:false,error:null,retry:null,saveState:'idle',needsRefresh:false,lastText:'',missing:[],assumed:[]});
      try{state.pendingSave=journal.read();state.pendingProblem='';if(state.pendingSave)state.saveState='uncertain';}
      catch{state.pendingProblem='이 탭의 보관 복구 기록을 확인할 수 없어 새 보관 요청을 보내지 않습니다. 내 견적은 확인할 수 있어요.';}
      message('안녕하세요! 즐기는 게임과 예산을 알려주시면 나에게 맞는 PC를 함께 찾아드릴게요.');emit();
    }
    async function recommendFor(op){
      state.phase='recommend';emit();
      const response=await api.recommend(state.talk,{signal:op.signal});
      if(!current(op))return;
      const parsed=M.recommendations(response);
      state.recommendation=parsed;state.groups=parsed.groups;state.assumed=parsed.assumed;state.missing=parsed.needs;
      state.selected=null;state.selectionState=null;state.savedQuote=null;state.saveState='idle';state.needsRefresh=false;state.screen='results';
      if(parsed.unsupported&&!parsed.groups.length)message('현재 추천 원천은 이 화면의 판매 중 PC 목록과 연결되지 않았어요. 상담 조건은 유지됩니다.');
    }
    async function submit(raw,{repeat=false}={}){
      const text=String(raw||'').trim();
      if(!text||text.length>300||state.phase)return false;
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
        state.history=state.history.slice(-6);state.missing=Array.isArray(response.missing)?response.missing:[];state.assumed=Array.isArray(response.assumed)?response.assumed:[];
        state.selected=null;state.selectionState=null;state.savedQuote=null;state.saveState='idle';state.groups=[];state.recommendation=null;state.needsRefresh=false;
        if(state.missing.length||response.pc_related===false||response.silent){state.screen='welcome';}
        else {await recommendFor(op);}
      }catch(error){
        if(current(op))fail(error,state.phase==='recommend'?{kind:'recommend'}:{kind:'talk',text});
      }finally{if(current(op)){state.phase=null;controller=null;emit();}}
      return true;
    }
    async function refresh(){
      if(!state.talk||state.phase)return;
      const op=begin('recommend');
      try{await recommendFor(op);}catch(error){if(current(op))fail(error,{kind:'recommend'});}
      finally{if(current(op)){state.phase=null;controller=null;emit();}}
    }
    function select(index){
      if(state.phase)return;
      const p=state.groups.flatMap(g=>g.products).find(p=>p.index===index);if(!p)return;
      cancel();state.selected=M.copy(p);state.selectionState=M.copy(state.talk);state.savedQuote=null;state.saveState='idle';state.needsRefresh=false;state.error=null;state.retry=null;state.screen='detail';emit();
    }
    function navigate(screen){
      if(['detail','final'].includes(screen)&&!state.selected)return;
      if(!['welcome','results','detail','final','saved'].includes(screen))return;
      cancel();state.screen=screen;state.error=null;state.retry=null;emit();
    }
    async function save(){
      if(state.phase||state.pendingSave||state.pendingProblem||!state.selected||!state.selectionState||state.needsRefresh||state.savedQuote||!Number.isInteger(state.selected.price))return;
      const selected=M.copy(state.selected),selectionState=M.copy(state.selectionState);
      const logical=JSON.stringify([selected.product_code,selected.price,selectionState]);
      if(!saveIds.has(logical))saveIds.set(logical,uuid());
      const payload={request_id:saveIds.get(logical),product_code:selected.product_code,expected_price:selected.price,state:selectionState};
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
      if(response?.ok!==true||!saved||saved.product.product_code!==record.payload.product_code||saved.product.price!==record.payload.expected_price)
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
      cancel();state.selected=M.copy(q.product);state.selectionState=M.copy(q.state);state.talk=M.copy(q.state);state.chatFlow=null;state.history=[];
      state.savedQuote=M.copy(q);state.saveState='saved';state.needsRefresh=false;state.error=null;state.retry=null;state.screen='final';
      message('이 브라우저에서 보관한 '+q.product.name+'을 불러왔어요. 표시 금액과 사양은 보관 시점 기준입니다.');emit();
    }
    async function retry(){
      if(state.phase||!state.retry||Date.now()<(state.error?.retryAt||0))return;
      const task=state.retry;
      if(task.kind==='talk')await submit(task.text,{repeat:true});
      else if(task.kind==='recommend')await refresh();
      else if(task.kind==='save')await save();
      else if(task.kind==='recover')await recover();
      else if(task.kind==='list')await list();
    }
    return {state,reset,submit,refresh,select,navigate,save,recover,list,load,retry,cancel,message,emit};
  }
  if(typeof module!=='undefined')module.exports={createFlow,JOURNAL_KEY,validPending};else root.MVP3LiveFlow={createFlow};
})(typeof window==='undefined'?globalThis:window);
