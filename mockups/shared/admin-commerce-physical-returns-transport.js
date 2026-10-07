/* Read-only HTTP factory contract. Main registration and operating DB remain unverified. */
(function(factory){if(typeof module==='object'&&module.exports)module.exports=factory();else window.PopcornPhysicalReturnsTransport=factory();})(function(){
  'use strict';
  const VERSION='commerce_physical_return_storage_v1',actions=['create_case','record_collection','record_receipt','inspect','restore'];
  const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x),integer=(x,min=0,max=Number.MAX_SAFE_INTEGER)=>Number.isSafeInteger(x)&&x>=min&&x<=max;
  const text=x=>typeof x==='string'&&x.trim().length>0,order=x=>typeof x==='string'&&/^[A-Za-z0-9][A-Za-z0-9_-]{0,19}$/.test(x),uuid=x=>typeof x==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(x),basis=x=>typeof x==='string'&&/^[a-f0-9]{64}$/.test(x);
  const copy=x=>JSON.parse(JSON.stringify(x)),fail=()=>{throw Error('physical_return_contract_invalid');};
  function fields(x,keys){if(!object(x)||Object.keys(x).sort().join('|')!==keys.split(' ').sort().join('|'))fail();}
  function quantities(x){if(!Array.isArray(x)||!x.length)fail();let last=0;for(const l of x){fields(l,'return_line_id qty');if(!integer(l.return_line_id,1)||l.return_line_id<=last||!integer(l.qty,1,2147483647))fail();last=l.return_line_id;}return x;}
  function current(x,no){
    fields(x,'version state order_no checked_at order_revision expected_order_basis expected_history_token cases actions');
    if(x.version!==VERSION||x.state!=='confirmed'||x.order_no!==no||!integer(x.checked_at)||!integer(x.order_revision,1)||!basis(x.expected_order_basis)||!basis(x.expected_history_token)||!Array.isArray(x.cases))fail();
    fields(x.actions,'inspect restore');for(const cap of Object.values(x.actions)){fields(cap,'allowed reason');if(cap.allowed!==false||cap.reason!=='source_unconnected')fail();}
    const cases=new Set(),lines=new Set(),operations=new Set();
    for(const c of x.cases){
      fields(c,'return_id revision lines history');if(!integer(c.return_id,1)||cases.has(c.return_id)||!integer(c.revision,1)||!Array.isArray(c.lines)||!c.lines.length||!Array.isArray(c.history)||c.history.length!==c.revision)fail();cases.add(c.return_id);const own=new Set();
      for(const l of c.lines){
        fields(l,'return_line_id shipment_id line_id claimed_qty collected_qty received_qty inspected_qty resellable_qty restoration_consumed_qty restoration_remaining_qty restoration_unresolved');
        if(!integer(l.return_line_id,1)||lines.has(l.return_line_id)||!integer(l.shipment_id,1)||!text(l.line_id)||typeof l.restoration_unresolved!=='boolean')fail();lines.add(l.return_line_id);own.add(l.return_line_id);
        for(const k of ['claimed_qty','collected_qty','received_qty','inspected_qty','resellable_qty','restoration_consumed_qty','restoration_remaining_qty'])if(!integer(l[k],k==='claimed_qty'?1:0,2147483647))fail();
        if(!(l.resellable_qty<=l.inspected_qty&&l.inspected_qty<=l.received_qty&&l.received_qty<=l.collected_qty&&l.collected_qty<=l.claimed_qty)||l.restoration_consumed_qty+l.restoration_remaining_qty!==l.resellable_qty)fail();
      }
      c.history.forEach((h,i)=>{
        fields(h,'operation_id action actor_id return_revision order_revision lines occurred_at reference evidence');
        if(!uuid(h.operation_id)||operations.has(h.operation_id)||!actions.includes(h.action)||!integer(h.actor_id,1)||h.return_revision!==i+1||!integer(h.order_revision,1,x.order_revision)||!Array.isArray(h.evidence))fail();operations.add(h.operation_id);
        quantities(h.lines);if(h.lines.some(l=>!own.has(l.return_line_id)))fail();
        if(h.occurred_at===null? h.reference!==null:!integer(h.occurred_at,0,x.checked_at)||!text(h.reference))fail();
        const seen=new Set();for(const e of h.evidence){fields(e,'return_line_id kind actor_id occurred_at reference');if(!integer(e.return_line_id,1)||seen.has(e.return_line_id)||!h.lines.some(l=>l.return_line_id===e.return_line_id)||!['collect','receive','inspect'].includes(e.kind)||!integer(e.actor_id,1)||!integer(e.occurred_at,0,x.checked_at)||!text(e.reference))fail();seen.add(e.return_line_id);}
      });
    }return copy(x);
  }
  function identity(x){if(!object(x)||!uuid(x.operation_id)||!actions.includes(x.action)||!integer(x.return_id,1)||!integer(x.return_revision,1)||!integer(x.order_revision,1))fail();quantities(x.lines);return copy(x);}
  function result(x,no,original){
    const selected=identity(original);fields(x,'version state pending_commit pending order_no operation_id action return_id order_revision return_revision lines');
    if(x.version!==VERSION||x.state!=='confirmed'||x.pending!==false||x.pending_commit!==false||x.order_no!==no||x.operation_id!==selected.operation_id||x.action!==selected.action||x.return_id!==selected.return_id||x.return_revision!==selected.return_revision||x.order_revision!==selected.order_revision)fail();
    quantities(x.lines);if(x.lines.length!==selected.lines.length||x.lines.some((l,i)=>l.return_line_id!==selected.lines[i].return_line_id||l.qty!==selected.lines[i].qty))fail();return copy(x);
  }
  const unavailable=()=>Promise.reject(Error('physical_return_contract_unconnected'));
  const writeBlocked=()=>Promise.reject(Error('physical_return_readonly'));
  function create(options){
    if(!options||typeof options.fetch!=='function')return Object.freeze({mode:'live',available:false,current:unavailable,execute:writeBlocked,lookup:unavailable});
    async function request(no,suffix,signal){
      if(!order(no))fail();const r=await options.fetch('/api/admin/commerce/orders/'+encodeURIComponent(no)+'/physical-returns'+suffix,{method:'GET',credentials:'same-origin',cache:'no-store',redirect:'error',headers:{Accept:'application/json'},signal});
      if(r.status===401||r.status===403)throw Object.assign(Error('접근 권한 확인 필요'),{denied:true,status:r.status});
      if(!r.headers||!/^application\/json(?:\s*;|$)/i.test(r.headers.get('content-type')||''))throw Error('physical_return_JSON_required');
      const data=await r.json();if(!r.ok)throw Object.assign(Error(object(data)&&object(data.detail)&&text(data.detail.code)?data.detail.code:'physical_return_unavailable'),{status:r.status});return data;
    }
    return Object.freeze({mode:'live',available:true,current:async(no,signal)=>current(await request(no,'',signal),no),execute:writeBlocked,lookup:async(no,original,signal)=>{const selected=identity(original);return result(await request(no,'/operations/'+selected.operation_id,signal),no,selected);}});
  }
  // Explicit injection for isolated tests/previews, never an inferred production DTO.
  function createMock(callbacks){if(!callbacks||['current','execute','lookup'].some(k=>typeof callbacks[k]!=='function'))throw Error('explicit mock callbacks required');return Object.freeze({mode:'mock',available:true,...Object.fromEntries(['current','execute','lookup'].map(k=>[k,callbacks[k]]))});}
  return Object.freeze({create,createMock,current,result,identity});
});
