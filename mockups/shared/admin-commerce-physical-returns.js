(function(factory){if(typeof module==='object'&&module.exports)module.exports=factory(require('./admin-commerce-fulfillment.js'),require('./admin-commerce-physical-returns-transport.js'));else window.PopcornPhysicalReturns=factory(window.PopcornFulfillment,window.PopcornPhysicalReturnsTransport);})(function(ui,contract){
  'use strict';
  const steps=[['claim','반품 접수 확인','원주문과 실제 인계된 상품의 반품 대상을 확인합니다. 출고 전 취소는 별도로 처리합니다.'],['collection','실제 회수','회수 요청과 실제 회수를 구분합니다. 실물 입고는 따로 확인합니다.'],['receipt','실물 입고','일부만 도착했다면 받은 수량만 확인합니다. 원주문 전량을 자동으로 채우지 않습니다.'],['inspect','검수 · 판매 가능 수량','입고됐다는 이유로 전량을 판매 가능으로 정하지 않습니다. 검수 저장만으로 재고가 늘지 않습니다.'],['restore','별도 재고복원','원판매 차감과 검수 근거, 이전 복원 결과를 함께 확인합니다. 재고복원은 현금 환불을 실행하지 않습니다.']];
  const copy=x=>JSON.parse(JSON.stringify(x)),freeze=x=>{if(x&&typeof x==='object'){Object.values(x).forEach(freeze);Object.freeze(x);}return x;};
  function controller(options){
    const adapter=options.adapter;if(!adapter||!['live','mock'].includes(adapter.mode)||typeof adapter.current!=='function'||typeof adapter.lookup!=='function')throw Error('explicit return read adapter required');
    let epoch=0,abort=null,disposed=false,state;
    const emit=()=>{if(options.onChange)options.onChange(snapshot());},snapshot=()=>copy({...state,mode:adapter.mode});
    function cancel(){++epoch;if(abort)abort.abort();abort=null;}
    function clear(){cancel();state={order:null,current:null,status:'idle',caseId:null,original:null,result:null,busy:false,draft:{},message:''};}clear();
    async function read(kind){
      const token=++epoch,no=state.order.order_no,selected=state.original&&freeze(copy(state.original));if(abort)abort.abort();abort=new AbortController();state.busy=true;state.message='';state.status=kind==='current'?'loading':'checking';emit();
      try{
        const raw=await (kind==='current'?adapter.current(no,abort.signal):adapter.lookup(no,selected,abort.signal));if(disposed||token!==epoch)return false;
        const value=kind==='current'?contract.current(raw,no):contract.result(raw,no,selected);
        if(kind==='current'){
          state.current=value;
          // Preserve an already selected immutable result independently of a fresh read.
          if(!value.cases.some(c=>c.return_id===state.caseId))state.caseId=null;
          state.status='ready';
        }else{state.result=value;state.status='confirmed';}
        state.busy=false;emit();return true;
      }catch(error){
        if(disposed||token!==epoch)return false;
        if(error.denied){clear();state.status='denied';state.message='접근 권한 확인 필요 · 주문과 반품 조회 근거를 닫았습니다.';emit();if(options.onDeny)options.onDeny(error);return false;}
        state.busy=false;
        if(kind==='current'){state.current=null;state.status=adapter.available===false||error.status===404?'unavailable':'error';state.message='최신 반품 조회 실패 · '+(state.status==='unavailable'?'source_unconnected · main 등록/운영 연결 미확인 · ':'')+error.message;}
        else{state.status='unknown';state.message='원결과 확인 불가 · 같은 반품·작업 ID를 보존했습니다. '+error.message+' · 미실행 확정 아님';}
        emit();return false;
      }
    }
    return Object.freeze({snapshot,connect(order){if(disposed)return Promise.resolve(false);clear();state.order=freeze(copy({order_no:order.order_no,lines:order.lines}));return read('current');},
      selectCase(id){if(disposed||state.status==='unknown'||!state.current||!state.current.cases.some(c=>c.return_id===id))return false;cancel();state.busy=false;state.caseId=id;state.original=null;state.result=null;state.status='ready';state.message='';emit();return true;},
      selectOperation(id){if(disposed||state.status==='unknown'||!state.current)return false;const c=state.current.cases.find(c=>c.return_id===state.caseId),h=c&&c.history.find(h=>h.operation_id===id);if(!h)return false;cancel();state.busy=false;state.original=freeze(contract.identity({...h,return_id:c.return_id}));state.result=null;state.status='ready';state.message='';emit();return true;},
      lookup(){return disposed||!state.order||!state.original||state.busy?Promise.resolve(false):read('lookup');},
      refresh(){return disposed||!state.order||state.busy||state.status==='unknown'?Promise.resolve(false):read('current');},
      guard(){return state.busy?'조회 중에는 주문과 화면을 이동할 수 없습니다.':state.status==='unknown'?'원결과가 미확정입니다. 같은 원 작업 결과를 먼저 조회하세요.':null;},
      setDraft(){return false;},submit(){return Promise.resolve(false);},discard(){return false;},reset(){clear();emit();},dispose(){disposed=true;clear();emit();}
    });
  }
  const stamp=x=>x===null?'미확인':ui.esc(x)+' (서버 Unix seconds)';
  function evidence(s){
    if(!s.current)return '<section class="aco-flow-card"><h3>현재 반품 조회 근거</h3><p>최신 반품 대상·수량 미확인</p></section>';
    if(!s.current.cases.length)return '<section class="aco-flow-card"><h3>현재 반품 조회 근거</h3><p>확인된 반품 없음</p></section>';
    const c=s.current.cases.find(c=>c.return_id===s.caseId);
    return '<section class="aco-flow-card"><h3>같은 주문의 반품 건</h3><p>조회 시각 · '+stamp(s.current.checked_at)+'</p><div class="aco-flow-buttons">'+s.current.cases.map(c=>'<button type="button" data-return-case="'+c.return_id+'" aria-pressed="'+(c.return_id===s.caseId)+'" '+(s.busy||s.status==='unknown'?'disabled':'')+'>반품 #'+c.return_id+' · revision '+c.revision+'</button>').join('')+'</div>'+(c?'<h4>선택 반품 #'+c.return_id+'</h4>'+c.lines.map(l=>'<p>반품행 #'+l.return_line_id+' · 배송 #'+l.shipment_id+' · 주문행 '+ui.esc(l.line_id)+'<br>신청 '+l.claimed_qty+' · 회수 '+l.collected_qty+' · 입고 '+l.received_qty+' · 검수 '+l.inspected_qty+' · 판매 가능 '+l.resellable_qty+'<br>복원 소비 '+l.restoration_consumed_qty+' · 남은 수량 '+l.restoration_remaining_qty+' · 복원 미결 '+(l.restoration_unresolved?'있음 · 처리 허용 아님':'없음')+'</p>').join('')+'<h4>저장 작업 이력</h4><ol>'+c.history.map(h=>'<li>'+ui.esc(h.action)+' · 반품 revision '+h.return_revision+' · 서버 수행자 #'+h.actor_id+'<br>작업 '+ui.esc(h.operation_id)+'<br>발생 '+stamp(h.occurred_at)+' · 근거 '+ui.esc(h.reference??'미확인')+'<br>'+h.lines.map(l=>'반품행 #'+l.return_line_id+' 수량 '+l.qty).join(' / ')+h.evidence.map(e=>'<p>근거 '+ui.esc(e.kind)+' · 반품행 #'+e.return_line_id+' · 서버 수행자 #'+e.actor_id+' · '+stamp(e.occurred_at)+' · '+ui.esc(e.reference)+'</p>').join('')+'<button type="button" data-return-operation="'+h.operation_id+'" '+(s.busy||s.status==='unknown'?'disabled':'')+'>이 원 작업 선택</button></li>').join('')+'</ol>':'<p>조회할 반품 건을 선택하세요.</p>')+'</section>';
  }
  function operation(s){return '<section class="aco-flow-card aco-flow-operation" id="flow-operation"><h3>원결과 확인 · 같은 반품의 이력</h3><p role="status">'+ui.esc(s.message||({idle:'미연결',loading:'조회 중',ready:'현재 반품 조회 근거 확인',checking:'같은 원 작업 조회 중',error:'최신 조회 실패',unavailable:'source_unconnected · main 등록/운영 연결 미확인',unknown:'원결과 확인 필요',confirmed:'저장 원결과 확인',denied:'접근 권한 확인 필요'})[s.status]||'미확인')+'</p><p>원 작업 · '+ui.esc(s.original?s.original.operation_id:'미확인')+'<br>원 대상 · '+ui.esc(s.original?'반품 #'+s.original.return_id+' · '+s.original.action:'미확인')+'</p>'+(s.result?'<p>'+(s.mode==='mock'?'MOCK · 격리 예시 확정':'서버 저장 원결과 확인')+' · 반품 #'+s.result.return_id+' · revision '+s.result.return_revision+'<br>'+s.result.lines.map(l=>'반품행 #'+l.return_line_id+' 수량 '+l.qty).join(' / ')+'</p>':'<p>원결과 · 미확인</p>')+'<button type="button" data-flow-lookup '+(!s.original||s.busy?'disabled':'')+'>같은 원결과 조회</button><button type="button" data-return-refresh '+(s.busy||s.status==='unknown'?'disabled':'')+'>현재 반품 다시 조회</button><p>원결과는 저장된 해당 작업의 결과입니다. 현재 전체 수량이나 금융환불 성공을 뜻하지 않습니다. 404도 미실행 확정이 아닙니다. 새 작업을 자동 제출하지 않습니다.</p></section>';}
  function view(s){return '<section class="aco-flow-policy"><h3>실물반품 책임 · 처리 조건</h3><dl><div><dt>처리 허용 여부</dt><dd>조회 전용 · 모든 쓰기 비활성</dd></div><div><dt>실제 차단 사유</dt><dd>source_unconnected · main 등록/운영 연결 미확인</dd></div><div><dt>확인 담당·근거</dt><dd>정책·관측·검수 producer 미연결</dd></div></dl><p>실물 회수, 검수, 재고복원과 환불 자금을 각각 확인합니다.</p>'+(s.mode==='mock'?'<strong>MOCK · 격리 예시 · 운영 처리 아님</strong>':'')+'</section><nav class="aco-flow-steps-nav" aria-label="실물반품 단계">'+steps.map(([key,label])=>'<a href="#flow-'+key+'">'+label+'</a>').join('')+'<a href="#flow-operation">원결과·이력</a></nav><div class="aco-flow-steps">'+steps.map(([key,label,note],i)=>'<section class="aco-flow-card" id="flow-'+key+'" tabindex="-1"><h3>'+(i+1)+'. '+label+'</h3>'+(key==='claim'?'<p class="aco-flow-placeholder">원주문 · 반품 대상 · 신청 수량은 아래 조회 근거에서 확인합니다.</p>':key==='restore'?'<p class="aco-flow-placeholder">입고 · 검수 · 판매 가능 · 이전 복원 · 복원 가능한 잔량은 아래 조회 근거에서 확인합니다.</p>'+ui.input(s,key+':qty','이번 복원 수량','number'):ui.input(s,key+':qty',key==='inspect'?'실제 검수 수량':'실제 '+(key==='collection'?'회수':'입고')+' 수량','number')+ui.input(s,key+':reference',key==='inspect'?'판매 가능 수량':'실제 발생 시각 · 근거',key==='inspect'?'number':'text'))+'<p>'+note+'</p><button type="button" disabled>'+label+' · 미연결</button></section>').join('')+'</div>'+evidence(s)+operation(s);}
  function mount(root,options={}){
    const orders=root.commerceOrders;if(!orders)throw Error('orders controller required');
    const fulfillment=ui.controller({adapter:options.fulfillment||window.PopcornFulfillmentTransport.create({fetch:window.fetch.bind(window)}),onChange:paint,onDeny:deny});
    const returns=controller({adapter:options.returns||contract.create({fetch:window.fetch.bind(window)}),onChange:paint,onDeny:deny});
    let active='fulfillment',context=null,slot=null,disposed=false,message='';
    function deny(){if(root.commerceOrdersTransport)root.commerceOrdersTransport.dispose();orders.deny();}
    function guard(){return fulfillment.guard()||returns.guard();}
    function paint(){if(disposed||!slot||!context)return;const s=(active==='fulfillment'?fulfillment:returns).snapshot();if(!s.order)return;
      const focused=slot.contains(document.activeElement)?document.activeElement:null;
      const focus=focused?{input:focused.dataset.flowInput,tab:focused.dataset.flowTab,id:focused.id,lookup:focused.hasAttribute('data-flow-lookup'),case:focused.dataset.returnCase,operation:focused.dataset.returnOperation,refresh:focused.hasAttribute('data-return-refresh')}:null;
      slot.innerHTML='<nav class="aco-flow-tabs" aria-label="주문 작업 영역"><button type="button" data-flow-tab="fulfillment" aria-pressed="'+(active==='fulfillment')+'">출고·배송</button><button type="button" data-flow-tab="returns" aria-pressed="'+(active==='returns')+'">실물반품</button><span>금융 취소·환불 · 미연결</span></nav>'+(message?'<p role="alert" class="aco-flow-guard">'+ui.esc(message)+' <button type="button" data-flow-discard '+(s.busy||s.status==='unknown'?'disabled':'')+'>입력 버리기</button></p>':'')+(active==='fulfillment'?ui.view(s):view(s));
      if(focus){const target=[...slot.querySelectorAll('[data-flow-input],[data-flow-tab],[id],[data-flow-lookup],[data-return-case],[data-return-operation],[data-return-refresh]')].find(el=>focus.input?el.dataset.flowInput===focus.input:focus.tab?el.dataset.flowTab===focus.tab:focus.id?el.id===focus.id:focus.case?el.dataset.returnCase===focus.case:focus.operation?el.dataset.returnOperation===focus.operation:focus.refresh?el.hasAttribute('data-return-refresh'):focus.lookup&&el.hasAttribute('data-flow-lookup'));if(target&&!target.disabled)target.focus({preventScroll:true});}
    }
    const unsubscribe=orders.subscribeDetail(meta=>{
      slot=root.querySelector('#aco-order-flows');
      const selectedOrder=orders.selectedFlowOrder(meta);
      if(meta.connection!=='ready'||meta.detailState!=='ready'||!selectedOrder){context=null;fulfillment.reset();returns.reset();if(slot)slot.innerHTML='';return;}
      const key=meta.generation+':'+meta.selection+':'+meta.orderNo;
      if(context&&context.key===key){paint();return;}
      // Controllers are replaced on context loss below; no retained input crosses orders.
      context=null;fulfillment.reset();returns.reset();context={key,order:selectedOrder};active='fulfillment';message='';fulfillment.connect(selectedOrder);returns.connect(selectedOrder);paint();
    });
    function click(e){const b=e.target.closest('button');if(!b||b.disabled||!slot||!slot.contains(b))return;
      if(b.dataset.flowTab){const blocked=guard();if(blocked){message=blocked;paint();return;}active=b.dataset.flowTab;message='';paint();}
      else if(b.hasAttribute('data-flow-discard')){fulfillment.discard();returns.discard();message='';paint();}
      else if(b.hasAttribute('data-flow-lookup'))(active==='fulfillment'?fulfillment:returns).lookup();
      else if(b.dataset.returnCase)returns.selectCase(Number(b.dataset.returnCase));
      else if(b.dataset.returnOperation)returns.selectOperation(b.dataset.returnOperation);
      else if(b.hasAttribute('data-return-refresh'))returns.refresh();
    }
    function input(e){if(slot&&slot.contains(e.target)&&e.target.dataset.flowInput)(active==='fulfillment'?fulfillment:returns).setDraft(e.target.dataset.flowInput,e.target.value);}
    root.addEventListener('click',click);root.addEventListener('input',input);
    function beforeUnload(e){if(guard()){e.preventDefault();e.returnValue='';}}
    window.addEventListener('beforeunload',beforeUnload);
    const removeGuard=orders.registerDetailGuard?orders.registerDetailGuard(()=>{const blocked=guard();if(blocked){message=blocked;paint();}return !blocked;}):()=>{};
    return Object.freeze({fulfillment,returns,dispose(){disposed=true;unsubscribe();removeGuard();root.removeEventListener('click',click);root.removeEventListener('input',input);window.removeEventListener('beforeunload',beforeUnload);fulfillment.dispose();returns.dispose();if(slot)slot.innerHTML='';}});
  }
  return Object.freeze({controller,view,mount});
});
