/* Exact, same-origin fulfillment adapter. No policy, actor, stock or proof producer. */
(function(factory){if(typeof module==='object'&&module.exports)module.exports=factory();else window.PopcornFulfillmentTransport=factory();})(function(){
  'use strict';
  const VERSION='commerce_fulfillment_http_v1',actions=['prepare_shipment','record_preparation_event','confirm_dispatch_ready','record_tracking','handoff','deliver'];
  const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x),integer=x=>Number.isSafeInteger(x)&&x>=1,stamp=x=>Number.isSafeInteger(x)&&x>=0;
  const text=x=>typeof x==='string'&&x.trim().length>0,order=x=>typeof x==='string'&&/^[A-Za-z0-9][A-Za-z0-9_-]{0,19}$/.test(x),basis=x=>typeof x==='string'&&/^[a-f0-9]{64}$/.test(x),uuid=x=>typeof x==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(x);
  const clone=x=>JSON.parse(JSON.stringify(x));
  function fields(x,keys){if(!object(x)||Object.keys(x).sort().join('|')!==[...keys].sort().join('|'))throw Error('command fields');}
  function lines(x){if(!Array.isArray(x)||!x.length||x.length>100||new Set(x.map(r=>r.line_id)).size!==x.length)throw Error('lines');return x.map(r=>{fields(r,['line_id','qty']);if(!text(r.line_id)||!integer(r.qty)||r.qty>2147483647)throw Error('quantity');return {line_id:r.line_id,qty:r.qty};});}
  function command(x){
    const common=['operation_id','action','expected_order_basis','expected_order_revision','expected_policy_basis','shipment_id','expected_shipment_revision','lines'];
    if(!object(x)||!actions.includes(x.action))throw Error('action');
    const preparation=actions.indexOf(x.action)<3,extra=preparation?['expected_order_state']:[];
    if(x.action==='record_preparation_event')extra.push('event_kind','quantities','outcome','observation');
    else if(x.action==='confirm_dispatch_ready')extra.push('prerequisites','observation');
    else if(!preparation)extra.push('carrier','tracking_no','observation');
    fields(x,common.concat(extra));
    if(!uuid(x.operation_id)||!basis(x.expected_order_basis)||!basis(x.expected_policy_basis)||!integer(x.expected_order_revision))throw Error('basis');
    if(x.action==='prepare_shipment'){if(x.shipment_id!==null||x.expected_shipment_revision!==null)throw Error('new shipment');}
    else if(!integer(x.shipment_id)||!integer(x.expected_shipment_revision))throw Error('shipment');
    if(preparation&&!['접수','결제완료','조립중','출고','배송중','완료','취소'].includes(x.expected_order_state))throw Error('order state');
    const result={...clone(x),lines:lines(x.lines)};
    if(x.action!=='prepare_shipment'){fields(x.observation,['occurred_at','reference']);if(!stamp(x.observation.occurred_at)||!text(x.observation.reference))throw Error('observation');}
    if(x.action==='record_preparation_event'){
      if(!['assembly_started','assembly_completed','inspection_recorded'].includes(x.event_kind)||!(x.event_kind==='inspection_recorded'?['accepted','rejected']:['recorded']).includes(x.outcome))throw Error('event');
      if(!Array.isArray(x.quantities)||x.quantities.length!==result.lines.length)throw Error('quantities');
      const ids=new Set();for(const q of x.quantities){fields(q,['line_id','observed_qty']);if(!result.lines.some(r=>r.line_id===q.line_id)||ids.has(q.line_id)||!integer(q.observed_qty)||q.observed_qty>2147483647)throw Error('quantity scope');ids.add(q.line_id);}
    }
    // Prerequisite proof references belong to the backend. Never synthesize them.
    if(x.action==='confirm_dispatch_ready'){
      if(!Array.isArray(x.prerequisites))throw Error('prerequisites');const seen=new Set();
      for(const ref of x.prerequisites){fields(ref,['operation_id','evidence_basis']);if(!uuid(ref.operation_id)||!basis(ref.evidence_basis)||seen.has(ref.operation_id))throw Error('prerequisite reference');seen.add(ref.operation_id);}
    }
    if(!preparation&&(!text(x.carrier)||!text(x.tracking_no)))throw Error('tracking');
    return result;
  }
  function current(x,no){
    if(!object(x)||x.version!==VERSION||x.state!=='confirmed'||x.order_no!==no||!stamp(x.checked_at)||!integer(x.order_revision)||!['접수','결제완료','조립중','출고','배송중','완료','취소'].includes(x.order_state)||!(x.expected_order_basis===null||basis(x.expected_order_basis))||!Array.isArray(x.shipments)||!object(x.actions))throw Error('current contract');
    const ships=x.shipments.map(s=>{
      if(!object(s)||!integer(s.shipment_id)||!integer(s.revision)||!['준비','배송중','완료'].includes(s.shipment_state)||typeof s.ready!=='boolean'||!(s.carrier===null||text(s.carrier))||!(s.tracking_no===null||text(s.tracking_no)))throw Error('shipment contract');
      for(const key of ['tracking_recorded_at','handed_off_at','delivered_at'])if(!(s[key]===null||stamp(s[key])))throw Error('shipment time');
      let history=null;if(Object.hasOwn(s,'history')){
        if(!Array.isArray(s.history))throw Error('history');history=s.history.map(h=>{
          if(!object(h)||!uuid(h.operation_id)||!actions.includes(h.action)||!integer(h.shipment_revision)||!integer(h.order_revision)||!integer(h.actor_id)||typeof h.ready!=='boolean'||!(h.occurred_at===null||stamp(h.occurred_at))||!(h.reference===null||text(h.reference))||!(h.event_kind===null||['assembly_started','assembly_completed','inspection_recorded'].includes(h.event_kind))||!(h.outcome===null||['recorded','accepted','rejected'].includes(h.outcome)))throw Error('history contract');
          if(h.quantities!==null&&(!Array.isArray(h.quantities)||h.quantities.some(q=>!object(q)||!text(q.line_id)||!integer(q.observed_qty))))throw Error('history quantities');
          return Object.fromEntries(['operation_id','action','shipment_revision','order_revision','actor_id','event_kind','quantities','outcome','occurred_at','reference','ready'].map(k=>[k,clone(h[k])]));
        });
      }
      return {shipment_id:s.shipment_id,revision:s.revision,shipment_state:s.shipment_state,ready:s.ready,lines:lines(s.lines),carrier:s.carrier,tracking_no:s.tracking_no,tracking_recorded_at:s.tracking_recorded_at,handed_off_at:s.handed_off_at,delivered_at:s.delivered_at,history};
    });
    if(new Set(ships.map(s=>s.shipment_id)).size!==ships.length)throw Error('duplicate shipment');
    const safeActions={};for(const a of actions){const cap=x.actions[a];if(!object(cap)||typeof cap.allowed!=='boolean'||!(cap.reason===null||text(cap.reason))||!cap.allowed&&cap.reason===null)throw Error('capability');safeActions[a]={allowed:cap.allowed,reason:cap.reason};}
    // Current HTTP DTO has no actionable policy basis or prerequisite producer.
    return {version:VERSION,state:x.state,order_no:no,order_state:x.order_state,checked_at:x.checked_at,order_revision:x.order_revision,expected_order_basis:x.expected_order_basis,expected_policy_basis:null,prerequisites:null,shipments:ships,actions:safeActions,history:null};
  }
  function receipt(x,no,original){
    if(!object(x)||x.version!==VERSION||x.state!=='confirmed'||x.order_no!==no||x.operation_id!==original.operation_id||x.action!==original.action||!basis(x.request_basis)||!stamp(x.checked_at)||!integer(x.shipment_id)||!integer(x.order_revision)||!integer(x.shipment_revision)||typeof x.ready!=='boolean'||!['준비','배송중','완료'].includes(x.shipment_state)||!['접수','결제완료','조립중','출고','배송중','완료','취소'].includes(x.order_state)||original.shipment_id!==null&&original.shipment_id!==x.shipment_id)throw Error('original result mismatch');
    return Object.fromEntries(['version','state','order_no','checked_at','operation_id','request_basis','action','shipment_id','order_revision','shipment_revision','order_state','shipment_state','ready'].map(k=>[k,x[k]]));
  }
  function create(options){
    if(!options||typeof options.fetch!=='function')throw Error('fetch required');
    async function request(no,suffix,body,signal){
      if(!order(no))throw Error('order identity');
      const response=await options.fetch('/api/admin/commerce/orders/'+encodeURIComponent(no)+'/fulfillment'+suffix,{method:body?'POST':'GET',credentials:'same-origin',cache:'no-store',redirect:'error',headers:body?{Accept:'application/json','Content-Type':'application/json'}:{Accept:'application/json'},signal,...(body?{body:JSON.stringify(body)}:{})});
      if(response.status===401||response.status===403){const error=Error('접근 권한 확인 필요');error.denied=true;throw error;}
      if(!response.headers||!/^application\/json(?:\s*;|$)/i.test(response.headers.get('content-type')||''))throw Error('JSON response required');
      const data=await response.json();if(!response.ok){const error=Error(object(data)&&object(data.detail)&&text(data.detail.code)?data.detail.code:'fulfillment_unavailable');error.status=response.status;throw error;}return data;
    }
    return Object.freeze({mode:'live',current:async(no,signal)=>current(await request(no,'',null,signal),no),execute:async(no,input,signal)=>{const cmd=command(input);return receipt(await request(no,'',cmd,signal),no,cmd);},lookup:async(no,original,signal)=>{if(!uuid(original.operation_id))throw Error('operation identity');return receipt(await request(no,'/operations/'+encodeURIComponent(original.operation_id),null,signal),no,original);}});
  }
  return Object.freeze({create,current,receipt,command,actions:Object.freeze(actions),order,uuid,basis});
});
