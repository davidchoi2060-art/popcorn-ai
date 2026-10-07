/* Read-only commerce_v1 renderer. The separate authorized adapter supplies DTOs.
 * No endpoints, network, storage, operational actions or example data here. */
(function(factory){
  if(typeof module==='object'&&module.exports)module.exports=factory();
  else{const ui=factory();window.PopcornCommerceOrders=ui;const root=document.getElementById('commerce-orders');if(root)ui.mount(root);}
})(function(){
  'use strict';
  const labels={
    checkout_state:{draft:'주문서 준비',processing:'결제 처리 중',unknown:'결과 확인 필요',paid:'결제 완료',expired:'주문서 만료',cancelled:'주문서 취소'},
    payment_state:{unpaid:'미결제',prepared:'결제 준비',processing:'결제 처리 중',unknown:'결과 확인 필요',confirmed:'승인 확정',declined:'승인 거절'},
    allocation_state:{unreserved:'예약 없음',held:'재고 예약',protected:'예약 보호',allocated:'배정 완료',blocked:'배정 확인 필요',released:'예약 해제'},
    refund_state:{none:'환불 없음',requested:'요청 접수',processing:'환불 처리 중',unknown:'결과 확인 필요',partial:'일부 환불',refunded:'자금 환불 완료'}
  };
  const orderStates=['접수','결제완료','조립중','출고','배송중','완료','취소'];
  const capabilityKeys=['approve','cancel','partial_cancel','guest_checkout'];
  const esc=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const object=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
  const text=value=>typeof value==='string'&&value.trim().length>0;
  function decimal(value){return typeof value==='string'&&/^(0|[1-9][0-9]{0,18})$/.test(value)&&(value.length<19||value<='9223372036854775807');}
  function money(value){return decimal(value)?value.replace(/\B(?=(\d{3})+(?!\d))/g,',')+'원':'금액 확인 필요';}
  const adminActions=['reconcile','cancel_payment','advance_fulfillment','return_stock'];
  function adminProject(row){
    const base=project(row),stamp=v=>Number.isSafeInteger(v)&&v>=0;
    if(!stamp(row.checked_at)||!['unconfirmed','confirmed','stale'].includes(row.basis_state)||!(row.basis_id===null||typeof row.basis_id==='string'&&/^[0-9a-f]{64}$/.test(row.basis_id)))throw Error('admin basis');
    if(row.basis_state==='confirmed'&&row.basis_id===null||row.basis_state==='unconfirmed'&&row.basis_id!==null)throw Error('admin basis');
    for(const key of ['approved_amount','refunded_amount','refundable_amount'])if(!decimal(row[key]))throw Error('admin amount');
    const approved=BigInt(row.approved_amount),refunded=BigInt(row.refunded_amount);
    if(refunded>approved||approved>BigInt(base.total)||BigInt(row.refundable_amount)!==approved-refunded||(base.payment_state==='confirmed'?approved!==BigInt(base.total):approved!==0n))throw Error('admin balance');
    if(!['unknown','test','live'].includes(row.provider_environment)||!['unknown','pending','confirmed','failed'].includes(row.verification_state)||!(row.provider_checked_at===null||stamp(row.provider_checked_at)&&row.provider_checked_at<=row.checked_at))throw Error('admin provider');
    if(row.verification_state==='confirmed'&&(row.provider_environment==='unknown'||row.provider_checked_at===null))throw Error('admin provider');
    if(!object(row.actions))throw Error('admin actions');
    const actions={};
    for(const key of adminActions){const a=row.actions[key];if(!object(a)||typeof a.allowed!=='boolean'||!(a.reason===null||text(a.reason))||!(a.expected_basis===null||typeof a.expected_basis==='string'&&/^[0-9a-f]{64}$/.test(a.expected_basis))||a.allowed&&(a.reason!==null||row.basis_state!=='confirmed'||a.expected_basis!==row.basis_id)||!a.allowed&&a.reason===null)throw Error('admin actions');actions[key]={allowed:a.allowed,reason:a.reason,expected_basis:a.expected_basis};}
    return {...base,checked_at:row.checked_at,basis_state:row.basis_state,basis_id:row.basis_id,approved_amount:row.approved_amount,refunded_amount:row.refunded_amount,refundable_amount:row.refundable_amount,provider_environment:row.provider_environment,verification_state:row.verification_state,provider_checked_at:row.provider_checked_at,actions};
  }
  function project(row){
    if(!object(row)||row.commerce_version!=='commerce_v1'||!text(row.order_no)||!orderStates.includes(row.order_state)||row.currency!=='KRW'||!decimal(row.total)||!Number.isSafeInteger(row.expires_at)||row.expires_at<0)throw Error('contract');
    for(const key of Object.keys(labels))if(typeof row[key]!=='string'||!Object.hasOwn(labels[key],row[key]))throw Error('state');
    if(!Array.isArray(row.lines)||!row.lines.length||!Array.isArray(row.reason_codes)||row.reason_codes.some(v=>!text(v))||new Set(row.reason_codes).size!==row.reason_codes.length||!object(row.capabilities)||capabilityKeys.some(k=>typeof row.capabilities[k]!=='boolean'))throw Error('contract');
    if((row.checkout_state==='paid'||row.allocation_state==='allocated'||['결제완료','조립중','출고','배송중','완료'].includes(row.order_state))&&row.payment_state!=='confirmed')throw Error('inconsistent');
    if(['결제완료','조립중','출고','배송중'].includes(row.order_state)&&row.allocation_state!=='allocated')throw Error('inconsistent');
    const lines=row.lines.map(l=>{if(!object(l)||!text(l.line_id)||!text(l.name)||!Number.isInteger(l.qty)||l.qty<1||l.qty>2147483647||!decimal(l.unit_amount))throw Error('line');return {line_id:l.line_id,name:l.name,qty:l.qty,unit_amount:l.unit_amount};});
    // Detach the public allowlist. Owner, PII, tokens, URLs and admin hints disappear.
    return {commerce_version:'commerce_v1',order_no:row.order_no,order_state:row.order_state,checkout_state:row.checkout_state,payment_state:row.payment_state,allocation_state:row.allocation_state,refund_state:row.refund_state,total:row.total,currency:'KRW',expires_at:row.expires_at,lines,reason_codes:[...row.reason_codes]};
  }
  function categories(row){const out=[];if(['prepared','processing','unknown','declined'].includes(row.payment_state))out.push('payment');if(['held','protected','blocked','allocated'].includes(row.allocation_state)&&!['완료','취소'].includes(row.order_state))out.push('fulfillment');if(row.refund_state!=='none')out.push('refund');return out;}
  function priority(row){return row.payment_state==='unknown'?0:row.refund_state==='unknown'?1:row.allocation_state==='blocked'?2:['processing','requested'].includes(row.refund_state)?3:4;}
  function reasons(row){return row.reason_codes.length?'<ul class="aco-reasons">'+row.reason_codes.map(code=>'<li>사유 코드 · '+esc(code)+'</li>').join('')+'</ul>':'<p class="aco-meta">추가 사유 코드 없음 · 운영 작업 사유 미연결</p>';}
  function foldedReasons(row){return row.reason_codes.length?'<details class="aco-reason-details"><summary>확인 사유 · 원 코드 '+row.reason_codes.length+'개</summary>'+reasons(row)+'</details>':reasons(row);}
  function evidenceTime(value){
    if(!Number.isSafeInteger(value)||value<0)return '미확인';
    const date=new Date(value*1000);if(!Number.isFinite(date.getTime()))return '미확인';
    try{return new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(date)+' (한국시간)';}catch{return '미확인';}
  }
  function paymentEvidence(row){
    // Only selected, validated admin detail carries these fields. A list DTO
    // deliberately has none; it must never supply an invented zero or PG time.
    const ready=Object.hasOwn(row,'checked_at'),queryTime=ready?evidenceTime(row.checked_at):'미확인';
    const providerTime=ready?evidenceTime(row.provider_checked_at):'미확인';
    const payment=labels.payment_state[row.payment_state],refund=labels.refund_state[row.refund_state];
    const heading=ready?payment+(row.refund_state==='none'?'':' · '+refund)+' · 비교 판정 미연결':'상세 원장 근거 미연결';
    const reason=ready?'조회된 내부 결제 상태는 '+payment+'입니다. 환불 자금 상태는 '+refund+'입니다. 원장과 PG의 비교 판정·PG 원문·참조가 연결되지 않아 금액 일치나 대사 성공을 판정할 수 없습니다.':'목록에서 확인한 결제 상태는 '+payment+'입니다. 상세 원장 금액과 확인 시각은 아직 연결되지 않았습니다. 목록 값으로 결제 비교 판정을 하지 않습니다.';
    const next=!ready?'선택한 주문의 상세 조회를 확인하세요. 근거가 연결되기 전에는 재결제나 수동 성공 처리를 하지 않습니다.':row.payment_state==='unknown'||row.payment_state==='processing'?'서버의 결제 결과 확인 작업이 연결되기 전에는 재결제나 수동 성공 처리를 하지 않습니다.':row.refund_state!=='none'?'환불 자금 상태와 실물 회수는 별도로 확인해야 합니다. 현재 조회만 가능하며 환불·재고 복원 처리는 연결되지 않았습니다.':'확인된 내부 상태를 기준으로 조회하세요. PG 비교와 운영 처리 작업은 연결되지 않았으므로 수동 성공 처리나 금액 정정을 하지 않습니다.';
    const verification=ready?({unknown:'검증 상태 미확인',pending:'검증 대기',confirmed:'서버 검증 확정',failed:'서버 검증 실패'})[row.verification_state]:'미연결';
    const evidenceRows=[['서버 주문 총액',money(row.total),queryTime],['내부 승인액',ready?money(row.approved_amount):'미확인',queryTime],['내부 환불액',ready?money(row.refunded_amount):'미확인',queryTime],['내부 환불가능액',ready?money(row.refundable_amount):'미확인',queryTime],['PG 근거',verification,providerTime]];
    return '<section class="aco-payment-evidence" aria-label="결제 결과 확인과 원장 근거"><div class="aco-evidence-banner"><span aria-hidden="true">!</span><strong>'+esc(heading)+'</strong></div><div class="aco-evidence-explain"><div><h4>이유</h4><p>'+esc(reason)+'</p></div><div><h4>안전한 다음 조치</h4><p>'+esc(next)+'</p></div></div><details class="aco-ledger-details"><summary>결제 결과 확인 · 원장 근거</summary><table class="aco-evidence aco-payment-table"><thead><tr><th scope="col">항목</th><th scope="col">값</th><th scope="col">근거 확인 시각</th></tr></thead><tbody>'+evidenceRows.map(([name,value,time],index)=>'<tr><th scope="row">'+esc(name)+'</th><td>'+esc(value)+'</td>'+(index===0?'<td rowspan="4"><span class="aco-evidence-time-label">주문 조회 시각</span><time>'+esc(time)+'</time></td>':index===4?'<td><span class="aco-evidence-time-label">PG 검증 시각</span><time>'+esc(time)+'</time></td>':'')+'</tr>').join('')+'</tbody></table></details><p class="aco-evidence-boundary">금액은 내부 원장 값이며 처리 권한을 뜻하지 않습니다. PG 금액·비교 판정·원문·참조·사건 이력은 미연결입니다.</p><p class="aco-evidence-info">PG 정산·은행 입금 근거 미연결</p></section>';
  }
  function detailHTML(row){
    const axes=[['주문서','checkout_state'],['결제','payment_state'],['재고 배정','allocation_state'],['환불 자금','refund_state']];
    return '<div class="aco-detail-scroll"><strong class="aco-order-no">'+esc(row.order_no)+'</strong><p class="aco-meta">주문 상태 · '+esc(row.order_state)+'<br>주문 생성시각 · 미확인 / 실행 환경 · 미확인</p>'+
      '<div class="aco-status-grid">'+axes.map(([name,key])=>'<div><small>'+name+'</small><strong>'+labels[key][row[key]]+'</strong></div>').join('')+'</div>'+
      '<h3>상품 구성</h3><ul class="aco-lines">'+row.lines.map(l=>'<li><div><strong>'+esc(l.name)+'</strong><small>수량 '+l.qty+' · 단가 '+money(l.unit_amount)+'</small></div></li>').join('')+'</ul><div class="aco-total"><span>서버 주문 총액</span><strong class="aco-money">'+money(row.total)+'</strong></div><small>배송비·추가 비용 내역 미확인</small>'+
      '<div class="aco-detail-reasons">'+foldedReasons(row)+'</div>'+
      paymentEvidence(row)+
      '<section id="aco-order-flows" class="aco-order-flows" aria-label="출고와 실물반품"></section>'+
      '<section id="aco-support" class="aco-support" aria-label="고객 문의와 지원 기록"></section>'+
      '<p class="aco-note">운영 작업 권한과 처리 연결을 확인해야 합니다. 결제 승인과 재고 배정은 서로 다른 상태입니다.</p>'+
      '<h3>취소·환불 요청과 처리 기록</h3><p class="aco-meta">환불 자금 · '+labels.refund_state[row.refund_state]+'<br>실물 회수 · 미확인 / 사건 이력 · 미연결</p></div>'+
      '<div class="aco-actions"><button type="button" disabled>결제 상태 다시 확인 · 미연결</button><button type="button" disabled>조립·검수·출고 · 미연결</button><button type="button" disabled>취소·환불 처리 · 미연결</button></div>';
  }
  function mount(root,options={}){
    const $=id=>root.querySelector('#'+id);
    let rows=[],selected=null,filter='all',query='',state='disconnected',generation=0,selection=0,detailToken=null,detail=null,detailState='idle';
    const detailListeners=new Set(),detailGuards=new Set();let renderSerial=0,detailSnapshot=null;
    const allowNavigation=()=>[...detailGuards].every(guard=>guard());
    function navigationEvent(e){const b=e.target.closest('button');if(b&&(b.dataset.orderIndex!==undefined||b.dataset.filter||['aco-back','aco-refresh','aco-prev','aco-next'].includes(b.id))&&!allowNavigation()){e.preventDefault();e.stopImmediatePropagation();}}
    function searchGuard(e){if(!allowNavigation()){e.preventDefault();e.stopImmediatePropagation();$('aco-search').value=query;}}
    const messages={disconnected:'주문 조회가 연결되지 않았습니다.',loading:'주문 조회 중 · 이전 결과를 닫았습니다.',error:'주문 조회에 실패했습니다. 최신 주문 상태를 확인할 수 없습니다.',invalid:'주문 응답 계약 확인 필요 · 최신 결과를 표시할 수 없습니다.',denied:'로그인 또는 조회 권한 확인이 필요합니다. 주문 정보를 닫았습니다.',ready:'현재 페이지 주문 조회 결과 · 처리 기능은 미연결입니다.'};
    function invalidateDetail(){++selection;detailToken=null;detail=null;detailState='idle';}
    function render(){
      $('aco-connection').textContent=messages[state];$('aco-connection').dataset.state=state;
      $('aco-search').disabled=state!=='ready';root.querySelectorAll('[data-filter]').forEach(b=>{b.disabled=state!=='ready';b.setAttribute('aria-pressed',String(b.dataset.filter===filter));});
      const visible=rows.map((row,index)=>({row,index})).filter(({row})=>row.order_no.includes(query)&&(filter==='all'||categories(row).includes(filter))).sort((a,b)=>priority(a.row)-priority(b.row)||a.index-b.index);
      if(!visible.some(({row})=>row.order_no===selected)){if(selected!==null)invalidateDetail();selected=null;root.classList.remove('show-detail');}
      $('aco-rows').innerHTML=state!=='ready'?'<p class="aco-empty">'+(state==='disconnected'?'주문 조회 연결 필요':state==='loading'?'불러오는 중':state==='invalid'?'응답 확인 필요':'조회 실패')+'</p>':!visible.length?'<p class="aco-empty">'+(rows.length?'현재 조건에 맞는 주문 없음':'조회 결과 주문 없음')+'</p>':'<table><thead><tr><th scope="col">주문번호 · 주문 상태</th><th scope="col">결제·배정·환불 확인 사유</th></tr></thead><tbody>'+visible.map(({row,index})=>'<tr class="aco-row" aria-selected="'+String(row.order_no===selected)+'"><td><button type="button" class="aco-open" data-order-index="'+index+'">'+esc(row.order_no)+'</button><small>'+esc(row.order_state)+'</small><small>생성시각 미확인</small></td><td>'+(priority(row)<4?'<span class="aco-priority">확인 필요</span>':'')+'<small>결제 · '+labels.payment_state[row.payment_state]+'<br>배정 · '+labels.allocation_state[row.allocation_state]+'<br>환불 · '+labels.refund_state[row.refund_state]+'</small>'+foldedReasons(row)+'</td></tr>').join('')+'</tbody></table>';
      $('aco-count').textContent=state==='ready'?'제공된 조회 결과 '+rows.length+'건 · 현재 표시 '+visible.length+'건 / 전체 주문 건수 미확인':'전체 주문 건수 미확인';
      const current=rows.find(row=>row.order_no===selected);$('aco-detail-title').textContent=current?'주문 상세 · '+current.order_no:'주문 상세';$('aco-detail').innerHTML=current?(detailState==='loading'?'<p class="aco-empty">선택한 주문 상세 조회 중 · 이전 원장 근거를 닫았습니다.</p>':detailState==='error'||detailState==='invalid'?'<p class="aco-empty">선택한 주문 상세를 확인할 수 없습니다. '+(detailState==='invalid'?'응답 계약 확인 필요':'최신 원장 근거 조회 실패')+' · 주문을 다시 선택하세요.</p>':detailHTML(detail||current)):'<p class="aco-empty">'+(state==='ready'?'목록에서 주문 선택':'최신 주문 상세를 확인할 수 없습니다.')+'</p>';
      detailSnapshot=Object.freeze({orderNo:current?selected:null,connection:state,detailState,generation,selection,renderSerial:++renderSerial});
      for(const listener of detailListeners){try{listener(detailSnapshot);}catch{ /* A consumer cannot break order rendering. */ }}
    }
    function clear(next){state=next;rows=[];selected=null;invalidateDetail();root.classList.remove('show-detail');render();}
    $('aco-search').addEventListener('input',()=>{query=$('aco-search').value.slice(0,100);render();});
    function focusList(){const index=rows.findIndex(row=>row.order_no===selected);const button=Number.isSafeInteger(index)&&index>=0?root.querySelector('[data-order-index="'+index+'"]'):null;(button||$('aco-search')).focus();}
    root.addEventListener('click',e=>{const b=e.target.closest('button');if(!b||b.disabled||state!=='ready')return;if(b.dataset.filter){if(!['all','payment','fulfillment','refund'].includes(b.dataset.filter))return;filter=b.dataset.filter;render();}else if(b.dataset.orderIndex!==undefined){if(!/^(0|[1-9]\d*)$/.test(b.dataset.orderIndex))return;const index=Number(b.dataset.orderIndex);if(!Number.isSafeInteger(index)||!rows[index])return;const row=rows[index];if(!row.order_no.includes(query)||(filter!=='all'&&!categories(row).includes(filter)))return;invalidateDetail();selected=row.order_no;root.classList.add('show-detail');render();$('aco-detail-title').focus();if(typeof options.onSelect==='function')options.onSelect(row.order_no);}else if(b.id==='aco-back'){root.classList.remove('show-detail');focusList();detailSnapshot=Object.freeze({orderNo:null,connection:state,detailState:'idle',generation,selection,renderSerial:++renderSerial});for(const listener of detailListeners){try{listener(detailSnapshot);}catch{}}}});
    // The authorized adapter calls begin, then receive/fail with that token.
    // Delayed results cannot overwrite newer loads; connection loss clears evidence.
    const controller={setOnSelect(callback){if(typeof callback!=='function')throw Error('selection callback');options={...options,onSelect:callback};},begin(){const token=++generation;clear('loading');return token;},receive(token,input){if(token!==generation)return false;try{if(!Array.isArray(input))throw Error('list');const fresh=input.map(project);if(new Set(fresh.map(r=>r.order_no)).size!==fresh.length)throw Error('duplicate');rows=fresh;state='ready';selected=null;invalidateDetail();render();return true;}catch{clear('invalid');return false;}},fail(token){if(token!==generation)return false;clear('error');return true;},disconnect(){++generation;clear('disconnected');},deny(){++generation;query='';filter='all';$('aco-search').value='';clear('denied');},
      registerDetailGuard(guard){if(typeof guard!=='function')throw Error('detail guard');if(!detailGuards.size){root.addEventListener('click',navigationEvent,true);$('aco-search').addEventListener('input',searchGuard,true);}detailGuards.add(guard);return ()=>{detailGuards.delete(guard);if(!detailGuards.size){root.removeEventListener('click',navigationEvent,true);$('aco-search').removeEventListener('input',searchGuard,true);}};},
      selectedFlowOrder(meta){return meta===detailSnapshot&&meta.orderNo===selected&&detailState==='ready'&&detail?Object.freeze({order_no:detail.order_no,order_state:detail.order_state,lines:Object.freeze(detail.lines.map(l=>Object.freeze({...l})))}):null;},
      subscribeDetail(listener){if(typeof listener!=='function')throw Error('detail listener');detailListeners.add(listener);if(detailSnapshot){try{listener(detailSnapshot);}catch{}}return ()=>detailListeners.delete(listener);},
      beginDetail(orderNo){if(state!=='ready'||selected!==orderNo)return null;detailToken=Object.freeze({generation,selection,orderNo});detail=null;detailState='loading';render();return detailToken;},
      isDetailCurrent(token){return token!==null&&token===detailToken&&token.generation===generation&&token.selection===selection&&token.orderNo===selected&&state==='ready';},
      receiveDetail(token,input){if(!controller.isDetailCurrent(token))return false;try{if(input.order_no!==token.orderNo)throw Error('detail identity');detail=adminProject(input);detailState='ready';render();return true;}catch{detail=null;detailState='invalid';render();return false;}},
      failDetail(token){if(!controller.isDetailCurrent(token))return false;detail=null;detailState='error';render();return true;}};
    root.commerceOrders=controller;render();return controller;
  }
  return Object.freeze({mount,project,adminProject,money});
});
