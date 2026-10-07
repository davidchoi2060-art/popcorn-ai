/* GET-only admin envelope adapter. Cursor history is memory-only transport state. */
(function(factory){
  if(typeof module==='object'&&module.exports)module.exports=factory(require('./admin-commerce-orders.js'));
  else{const adapter=factory(window.PopcornCommerceOrders);window.PopcornCommerceOrdersTransport=adapter;const root=document.getElementById('commerce-orders');if(root)adapter.mount(root,{fetch:window.fetch.bind(window)}).refresh();}
})(function(ui){
  'use strict';
  const orderNumber=value=>typeof value==='string'&&/^[A-Za-z0-9][A-Za-z0-9_-]{0,19}$/.test(value);
  const cursor=value=>value===null||typeof value==='string'&&/^[A-Za-z0-9_-]{1,256}$/.test(value);
  function envelope(value,kind,orderNo){
    if(value===null||typeof value!=='object'||Array.isArray(value)||value.commerce_version!=='commerce_v1'||!Number.isSafeInteger(value.checked_at)||value.checked_at<0||!value.context||value.context.state!=='confirmed'||typeof value.context.binding_id!=='string'||!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value.context.binding_id))throw Error('envelope');
    function item(row){
      const safe=ui.adminProject(row);
      if(!orderNumber(safe.order_no)||safe.checked_at!==value.checked_at)throw Error('identity or clock');
      // project deliberately excludes capabilities. Copy only the four validated
      // booleans needed by the compatible row validator; never enable actions.
      return {...safe,capabilities:{approve:row.capabilities.approve,cancel:row.capabilities.cancel,partial_cancel:row.capabilities.partial_cancel,guest_checkout:row.capabilities.guest_checkout}};
    }
    if(kind==='list'){
      if(!Array.isArray(value.items)||value.items.length>20||!cursor(value.next_cursor))throw Error('list');
      const items=value.items.map(item);
      if(new Set(items.map(row=>row.order_no)).size!==items.length)throw Error('duplicate');
      return {items,nextCursor:value.next_cursor};
    }
    if(kind!=='detail'||!orderNumber(orderNo)||!value.item||value.item.order_no!==orderNo)throw Error('detail');
    return {item:item(value.item)};
  }
  function mount(root,options){
    if(!options||typeof options.fetch!=='function')throw Error('GET transport required');
    const controller=root.commerceOrders||ui.mount(root),$=id=>root.querySelector('#'+id);
    let epoch=0,listGeneration=0,detailGeneration=0,history=[null],page=0,nextCursor=null,pending=false,ready=false;
    let requestedCursor=null,requestedPage=0,listAbort=null,detailAbort=null;
    const activeList=(e,g)=>e===epoch&&g===listGeneration;
    const activeDetail=(e,g,token)=>e===epoch&&g===detailGeneration&&controller.isDetailCurrent(token);
    function controls(){
      $('aco-refresh').disabled=pending;$('aco-refresh').textContent=pending?'조회 중':'다시 조회';
      $('aco-prev').disabled=pending||!ready||page===0;$('aco-next').disabled=pending||!ready||nextCursor===null;
    }
    function cancelDetail(){++detailGeneration;if(detailAbort)detailAbort.abort();detailAbort=null;}
    function deny(){
      ++epoch;++listGeneration;cancelDetail();if(listAbort)listAbort.abort();listAbort=null;
      history=[null];page=0;nextCursor=null;requestedCursor=null;requestedPage=0;pending=false;ready=false;
      controller.deny();controls();
    }
    async function read(path,signal){
      const response=await options.fetch(path,{method:'GET',credentials:'same-origin',cache:'no-store',redirect:'error',headers:{Accept:'application/json'},signal});
      return response;
    }
    function jsonResponse(response){
      if(!response.ok||!response.headers||!/^application\/json(?:\s*;|$)/i.test(response.headers.get('content-type')||''))throw Error('GET response');
      return response.json();
    }
    async function load(value,index,reset=false){
      if(!cursor(value))throw Error('cursor');
      if(reset){history=[null];page=0;value=null;index=0;}
      ++listGeneration;cancelDetail();if(listAbort)listAbort.abort();listAbort=new AbortController();
      const e=epoch,g=listGeneration,token=controller.begin(),signal=listAbort.signal;
      requestedCursor=value;requestedPage=index;nextCursor=null;pending=true;ready=false;controls();
      try{
        const response=await read('/api/admin/commerce/orders?limit=20'+(value===null?'':'&cursor='+encodeURIComponent(value)),signal);
        if(!activeList(e,g))return false;
        if(response.status===401||response.status===403){deny();return false;}
        const data=await jsonResponse(response);if(!activeList(e,g))return false;
        const result=envelope(data,'list');
        if(result.nextCursor!==null&&result.nextCursor===value)throw Error('cursor did not advance');
        if(!controller.receive(token,result.items))throw Error('renderer contract');
        history=history.slice(0,index+1);history[index]=value;page=index;nextCursor=result.nextCursor;ready=true;pending=false;controls();return true;
      }catch{if(!activeList(e,g))return false;controller.fail(token);pending=false;ready=false;nextCursor=null;controls();return false;}
    }
    async function select(orderNo){
      cancelDetail();const token=controller.beginDetail(orderNo);if(token===null)return false;
      detailAbort=new AbortController();const e=epoch,g=detailGeneration,signal=detailAbort.signal;
      try{
        if(!orderNumber(orderNo))throw Error('order number');
        const response=await read('/api/admin/commerce/orders/'+encodeURIComponent(orderNo),signal);
        if(!activeDetail(e,g,token))return false;
        if(response.status===401||response.status===403){deny();return false;}
        const data=await jsonResponse(response);if(!activeDetail(e,g,token))return false;
        return controller.receiveDetail(token,envelope(data,'detail',orderNo).item);
      }catch{if(!activeDetail(e,g,token))return false;controller.failDetail(token);return false;}
    }
    const adapter={refresh:()=>load(null,0,true),retry:()=>load(requestedCursor,requestedPage),
      next:()=>pending||!ready||nextCursor===null?Promise.resolve(false):load(nextCursor,page+1),
      previous:()=>pending||!ready||page===0?Promise.resolve(false):load(history[page-1],page-1),
      dispose(){++epoch;++listGeneration;cancelDetail();if(listAbort)listAbort.abort();history=[null];nextCursor=null;requestedCursor=null;requestedPage=0;page=0;ready=false;pending=false;controller.disconnect();controls();}};
    controller.setOnSelect(select);
    $('aco-refresh').addEventListener('click',()=>{if(!pending)(ready?adapter.refresh():adapter.retry());});
    $('aco-prev').addEventListener('click',()=>adapter.previous());$('aco-next').addEventListener('click',()=>adapter.next());
    root.commerceOrdersTransport=adapter;controls();return adapter;
  }
  return Object.freeze({mount,envelope});
});
