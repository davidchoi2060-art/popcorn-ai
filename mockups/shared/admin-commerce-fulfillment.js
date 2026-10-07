/* Selected-order workflow state and fulfillment view; no ambient endpoint authority. */
(function(factory){if(typeof module==='object'&&module.exports)module.exports=factory(require('./admin-commerce-fulfillment-transport.js'));else window.PopcornFulfillment=factory(window.PopcornFulfillmentTransport);})(function(contract){
  'use strict';
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const copy=x=>JSON.parse(JSON.stringify(x)),freeze=x=>{if(x&&typeof x==='object'){Object.values(x).forEach(freeze);Object.freeze(x);}return x;};
  function controller(options){
    const adapter=options.adapter,onChange=options.onChange||(()=>{}),newId=options.newId||(()=>crypto.randomUUID());
    if(!adapter||!['live','mock'].includes(adapter.mode)||typeof adapter.current!=='function')throw Error('explicit workflow adapter required');
    let epoch=0,abort=null,disposed=false,state={order:null,current:null,status:'idle',draft:{},dirty:false,busy:false,original:null,result:null,message:''};
    const emit=()=>onChange(snapshot()),snapshot=()=>copy({...state,mode:adapter.mode});
    function clear(){++epoch;if(abort)abort.abort();abort=null;state={order:null,current:null,status:'idle',draft:{},dirty:false,busy:false,original:null,result:null,message:''};}
    function deny(error){clear();state.status='denied';state.message='로그인 또는 처리 권한 확인 필요 · 이전 입력과 근거를 닫았습니다.';emit();if(options.onDeny)options.onDeny(error);}
    async function run(kind,input){
      const token=++epoch,no=state.order.order_no;abort=new AbortController();state.busy=true;state.message='';if(kind==='current')state.status='loading';emit();
      try{
        const value=await adapter[kind](no,...(kind==='current'?[]:[input]),abort.signal);
        if(disposed||token!==epoch)return false;
        if(kind==='current'){state.current=copy(value);state.status='ready';}
        else{if(!value||value.state!=='confirmed'||value.order_no!==no||value.operation_id!==state.original.operation_id||value.action!==state.original.action)throw Error('original result mismatch');state.result=copy(value);state.current=null;state.status='confirmed';state.dirty=false;}
        state.busy=false;emit();return true;
      }catch(error){
        if(disposed||token!==epoch)return false;
        if(error.denied){deny(error);return false;}
        state.busy=false;state.status=kind==='current'?(adapter.available===false?'unavailable':'error'):'unknown';state.message=kind==='current'?'최신 근거 조회 실패 · '+error.message:'결과 확인 필요 · 원 작업과 입력을 보존했습니다. '+error.message;emit();return false;
      }
    }
    const api={snapshot,connect(order){if(disposed)return Promise.resolve(false);if(state.order&&state.order.order_no===order.order_no)return Promise.resolve(true);clear();state.order=freeze(copy({order_no:order.order_no,order_state:order.order_state,lines:order.lines}));return run('current');},
      setDraft(key,value){if(disposed||!state.order||state.busy||state.status==='unknown')return false;state.draft[key]=String(value).slice(0,1000);state.dirty=true;return true;},
      guard(){return state.busy?'처리 중에는 주문과 화면을 이동할 수 없습니다.':state.status==='unknown'?'원결과가 미확정입니다. 원 작업 결과를 먼저 조회하세요.':state.dirty?'작성 중인 입력이 있습니다. 입력을 버린 뒤 이동할 수 있습니다.':null;},
      discard(){if(state.busy||state.status==='unknown')return false;state.draft={};state.dirty=false;emit();return true;},
      refresh(){if(!state.order||state.busy||state.status==='unknown'||state.dirty)return Promise.resolve(false);return run('current');},
      submit(input){
        if(disposed||options.readOnly||!state.order||state.busy||state.status==='unknown'||state.current===null)return Promise.resolve(false);
        const cap=state.current.actions&&state.current.actions[input.action];
        if(!cap||!cap.allowed||!contract.basis(state.current.expected_order_basis)||!contract.basis(state.current.expected_policy_basis))return Promise.resolve(false);
        try{
          const cmd=contract.command({...copy(input),operation_id:'00000000-0000-4000-8000-000000000000'});
          if(cmd.expected_order_basis!==state.current.expected_order_basis||cmd.expected_policy_basis!==state.current.expected_policy_basis||cmd.expected_order_revision!==state.current.order_revision)throw Error('stale basis');
          const ship=state.current.shipments.find(s=>s.shipment_id===cmd.shipment_id);
          if(cmd.action!=='prepare_shipment'&&(!ship||ship.revision!==cmd.expected_shipment_revision))throw Error('stale shipment');
          for(const line of cmd.lines){const limit=(ship?ship.lines:state.order.lines).find(l=>l.line_id===line.line_id);if(!limit||line.qty>limit.qty)throw Error('quantity exceeds selected scope');}
          if(cmd.action!=='prepare_shipment'&&(cmd.lines.length!==ship.lines.length||cmd.lines.some(l=>ship.lines.find(s=>s.line_id===l.line_id).qty!==l.qty)))throw Error('shipment line basis changed');
          if(cmd.quantities&&cmd.quantities.some(q=>q.observed_qty>cmd.lines.find(l=>l.line_id===q.line_id).qty))throw Error('observation quantity exceeds scope');
          cmd.operation_id=newId();if(!contract.uuid(cmd.operation_id))throw Error('operation UUID required');
          state.original=freeze(copy(cmd));state.result=null;return run('execute',state.original);
        }catch(error){state.message='입력 확인 필요 · '+error.message;emit();return Promise.resolve(false);}
      },
      lookup(){if(disposed||!state.order||!state.original||state.busy)return Promise.resolve(false);return run('lookup',state.original);},
      reset(){clear();emit();},dispose(){disposed=true;clear();emit();}
    };return Object.freeze(api);
  }
  const steps=[['prepare','배송 준비 생성','prepare_shipment','이번 배송의 상품과 수량을 확인합니다. 부분 배송을 주문 전량으로 채우지 않습니다.'],['assembly','조립 시작 · 완료','record_preparation_event','시작과 완료는 각각 기록합니다. 수행자와 근거는 같은 주문의 이력으로 확인합니다.'],['inspect','검수 합격 · 불합격','record_preparation_event','조립 완료만으로 검수 합격을 표시하지 않습니다.'],['ready','출고 준비 확인','confirm_dispatch_ready','준비 확인은 실제 인계와 구분합니다. 해당 배송의 최신 근거를 확인합니다.'],['tracking','실제 송장 저장','record_tracking','송장 저장만으로 실제 인계나 배송완료를 확정하지 않습니다.'],['handoff','실제 인계 · 출고','handoff','배송 책임·조건, 준비 결과와 해당 배송의 실제 인계 근거를 함께 확인합니다.'],['delivered','해당 배송 완료','deliver','선택 배송의 완료를 기록합니다. 다른 배송 건을 함께 완료하지 않습니다.']];
  function input(s,key,label,type='text',disabled=true){return '<label>'+esc(label)+'<input type="'+type+'" data-flow-input="'+key+'" value="'+esc(s.draft[key]||'')+'" '+(disabled?'disabled':'')+'></label>';}
  function operation(s){return '<section class="aco-flow-card aco-flow-operation" id="flow-operation"><h3>원결과 확인 · 같은 주문의 이력</h3><p role="status">'+esc(s.message||({idle:'미연결',loading:'조회 중',ready:'현재 조회 근거 확인',error:'조회 실패',unavailable:'처리 계약 미연결',unknown:'결과 확인 필요',confirmed:'원 작업 결과 확인',denied:'접근 권한 확인 필요'})[s.status])+'</p><dl><div><dt>원 작업</dt><dd>'+esc(s.original?s.original.operation_id:'미확인')+'</dd></div><div><dt>원결과</dt><dd>'+esc(s.result?(s.mode==='mock'?'MOCK · 격리 예시 확정':'서버 원결과 확인'):'미확인')+'</dd></div><div><dt>원 작업 대상</dt><dd>'+esc(s.original?s.original.action+' · '+s.original.lines.map(l=>l.line_id+' 수량 '+l.qty).join(' / '):'미확인')+'</dd></div><div><dt>확인 배송 · 상태</dt><dd>'+esc(s.result?'#'+s.result.shipment_id+' · '+s.result.shipment_state+' · 준비 '+(s.result.ready?'확인':'미확인'):'미확인')+'</dd></div><div><dt>원결과 수행자 · 근거</dt><dd>조회 계약 미연결</dd></div></dl><button type="button" data-flow-lookup '+(!s.original||s.busy?'disabled':'')+'>원결과 조회</button><p>결과가 미확정이면 원 작업 ID와 입력을 유지합니다. 새 작업을 자동 제출하지 않습니다.</p></section>';}
  function shipmentEvidence(s){if(!s.current)return '<p class="aco-flow-placeholder">최신 배송 건 · 수량 · 송장 조회 근거 미확인</p>';const ships=s.current.shipments;if(!ships.length)return '<p class="aco-flow-placeholder">확인된 배송 조회 결과 · 배송 건 없음</p>';return '<div class="aco-flow-shipments">'+ships.map(ship=>'<details><summary>배송 #'+ship.shipment_id+' · '+esc(ship.shipment_state)+' · 준비 '+(ship.ready?'확인':'미확인')+'</summary><p>대상 · '+ship.lines.map(l=>esc(l.line_id)+' 수량 '+l.qty).join(' / ')+'</p><p>배송사 · '+esc(ship.carrier||'미확인')+' / 송장 · '+esc(ship.tracking_no||'미확인')+'</p><p>송장 기록 · '+esc(ship.tracking_recorded_at??'미확인')+' / 실제 인계 · '+esc(ship.handed_off_at??'미확인')+' / 배송완료 · '+esc(ship.delivered_at??'미확인')+' (서버 Unix 시각)</p>'+(ship.history===null?'<p>사건 이력 조회 계약 미연결</p>':!ship.history.length?'<p>확인된 사건 이력 없음</p>':'<ol>'+ship.history.map(h=>'<li>작업 '+esc(h.operation_id)+' · '+esc(h.action)+' · '+esc(h.event_kind||'')+' · 결과 '+esc(h.outcome||'미확인')+'<br>서버 수행자 #'+h.actor_id+' · 발생 '+esc(h.occurred_at??'미확인')+' · 근거 '+esc(h.reference||'미확인')+'</li>').join('')+'</ol>')+'</details>').join('')+'</div>';}
  function view(s){
    const ready=s.current,enabled=!!ready&&contract.basis(ready.expected_policy_basis)&&contract.basis(ready.expected_order_basis)&&!s.busy&&s.status!=='unknown';
    const reason=a=>ready&&ready.actions[a]?ready.actions[a].reason||(!enabled?'policy_basis_unconnected':'처리 허용'):'조회 근거 미확인';
    return '<section class="aco-flow-policy"><h3>출고·배송 책임 · 처리 조건</h3><dl><div><dt>처리 책임·조건</dt><dd>정책 근거 미연결</dd></div><div><dt>실제 차단 사유</dt><dd>'+esc(reason('prepare_shipment'))+'</dd></div><div><dt>확인 담당·근거</dt><dd>조회 계약 미연결</dd></div></dl><p>환불 금액·상태만으로 출고나 실물 처리의 가능 여부를 정하지 않습니다.</p>'+ (s.mode==='mock'?'<strong>MOCK · 격리 예시 · 운영 처리 아님</strong>':'')+'</section><nav class="aco-flow-steps-nav" aria-label="출고·배송 단계">'+steps.map(([key,label])=>'<a href="#flow-'+key+'">'+label+'</a>').join('')+'<a href="#flow-operation">원결과·이력</a></nav><div class="aco-flow-steps">'+steps.map(([key,label,action,note],index)=>{
      const allow=enabled&&ready.actions[action].allowed;
      let fields='';
      if(key==='prepare')fields='<p class="aco-flow-placeholder">선택 배송 · 대상 수량 확인</p>'+s.order.lines.map(l=>input(s,key+':'+l.line_id,l.name+' · 주문 수량 '+l.qty,'number',!allow)).join('');
      else if(key==='ready')fields='<p class="aco-flow-placeholder">조립 완료 · 검수 결과 · 현재 정책 근거 미연결</p>';
      else if(key==='tracking')fields=input(s,key+':carrier','실제 배송사','text',!allow)+input(s,key+':tracking_no','실제 송장번호','text',!allow);
      else fields=input(s,key+':qty',key==='inspect'?'실제 검수 수량':key==='assembly'?'조립 확인 수량':'실제 발생 일시',key==='assembly'||key==='inspect'?'number':'datetime-local',!allow)+input(s,key+':reference','실제 확인 근거','text',!allow);
      const buttons=key==='assembly'?['조립 시작 기록','조립 완료 기록']:key==='inspect'?['합격 결과 기록','불합격 결과 기록']:[label];
      // Current read DTO cannot produce a safe command. A policy-capable UI needs a new reviewed read contract.
      return '<section class="aco-flow-card" id="flow-'+key+'" tabindex="-1"><h3>'+(index+1)+'. '+label+'</h3><div class="aco-flow-fields">'+fields+'</div><p>'+note+'</p><div class="aco-flow-buttons">'+buttons.map(b=>'<button type="button" disabled>'+b+' · 미연결</button>').join('')+'</div><small>처리 사유 · '+esc(reason(action))+'</small></section>';
    }).join('')+'</div>'+shipmentEvidence(s)+operation(s);
  }
  return Object.freeze({controller,view,operation,input,esc});
});
