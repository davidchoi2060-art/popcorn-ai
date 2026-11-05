// Mounted GET-only regression for the physical-return read display (D2/D3).
// Runs the real commerce_orders template blocks and real shared JS in an installed
// headless Chrome/Edge against an injected fake fetch. No SSR, API, DB or network;
// the fake rejects every non-GET and any such attempt fails the group.
// No browser found: exits 2 as BLOCKED, never as PASS. Set CHROME_PATH to override.
const assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {pathToFileURL}=require('node:url');
const ROOT=path.join(__dirname,'..');
const GROUPS=['refresh_pending_hides_then_restores','refresh_pending_then_503_stays_unconfirmed','refresh_pending_then_401_closes_page','lookup_checking_keeps_current_evidence','confirmed_result_blocks_repeat_lookup','result_survives_current_failure_and_refresh','new_operation_and_case_can_lookup','failed_lookup_retries_same_operation','other_order_resets_selection','unchanged_denial_guard_and_404_contracts'];

function pageMain(){(async function(){
  const A='ORD-EXAMPLE-01',B='ORD-EXAMPLE-02',NOW=1791200100,HASH='a'.repeat(64),uid=n=>'00000000-0000-4000-8000-'+String(n).padStart(12,'0');
  const adminActions=()=>Object.fromEntries(['reconcile','cancel_payment','advance_fulfillment','return_stock'].map(k=>[k,{allowed:false,reason:'route_unavailable',expected_basis:null}]));
  const row=no=>({commerce_version:'commerce_v1',order_no:no,order_state:'접수',checkout_state:'unknown',payment_state:'unknown',allocation_state:'protected',refund_state:'none',total:'1000',currency:'KRW',expires_at:1791200000,lines:[{line_id:'line-'+no,name:'격리 예시',qty:2,unit_amount:'500'}],reason_codes:[],capabilities:{approve:false,cancel:false,partial_cancel:false,guest_checkout:false},checked_at:NOW,basis_state:'unconfirmed',basis_id:null,approved_amount:'0',refunded_amount:'0',refundable_amount:'0',provider_environment:'unknown',verification_state:'unknown',provider_checked_at:null,actions:adminActions()});
  const envelope=x=>({commerce_version:'commerce_v1',checked_at:NOW,context:{state:'confirmed',binding_id:'00000000-0000-4000-8000-0000000000aa'},...x});
  const shipping=no=>({version:'commerce_fulfillment_http_v1',state:'confirmed',order_no:no,order_state:'접수',checked_at:NOW,order_revision:2,expected_order_basis:null,shipments:[],actions:Object.fromEntries(['prepare_shipment','record_preparation_event','confirm_dispatch_ready','record_tracking','handoff','deliver'].map(a=>[a,{allowed:false,reason:'source_unconnected'}]))});
  const base=no=>no===A?100:200;
  const returnCase=(no,rid,collected)=>{const o=base(no)+(rid-11)*10,t=no===A?'A':'B',s=rid-10;return {return_id:rid,revision:2,lines:[{return_line_id:o+1,shipment_id:1,line_id:'RETLINE-'+t+s,claimed_qty:2,collected_qty:collected,received_qty:0,inspected_qty:0,resellable_qty:0,restoration_consumed_qty:0,restoration_remaining_qty:0,restoration_unresolved:false}],history:[{operation_id:uid(o+1),action:'create_case',actor_id:7,return_revision:1,order_revision:2,lines:[{return_line_id:o+1,qty:2}],occurred_at:null,reference:null,evidence:[]},{operation_id:uid(o+2),action:'record_collection',actor_id:7,return_revision:2,order_revision:3,lines:[{return_line_id:o+1,qty:1}],occurred_at:1791200000,reference:'REF-'+t+s,evidence:[]}]};};
  const returns=(no,collected=1)=>({version:'commerce_physical_return_storage_v1',state:'confirmed',order_no:no,checked_at:NOW,order_revision:3,expected_order_basis:HASH,expected_history_token:HASH,cases:[returnCase(no,11,collected),returnCase(no,12,1)],actions:{inspect:{allowed:false,reason:'source_unconnected'},restore:{allowed:false,reason:'source_unconnected'}}});
  const original=(no,id)=>{for(const c of returns(no).cases)for(const h of c.history)if(h.operation_id===id)return {version:'commerce_physical_return_storage_v1',state:'confirmed',pending_commit:false,pending:false,order_no:no,operation_id:id,action:h.action,return_id:c.return_id,order_revision:h.order_revision,return_revision:h.return_revision,lines:h.lines};return null;};
  const J=(body,status=200)=>({body,status}),DEFER={};
  const calls=[],violations=[];let routes=[];
  function dflt(url){const p=url.split('?')[0];let m;
    if(p==='/api/admin/auth/me')return J({authenticated:true,operator:{operator_id:7,role:'operator',status:'활성'}});
    if(p==='/api/admin/commerce/orders')return J(envelope({items:[row(A),row(B)],next_cursor:null}));
    if((m=p.match(/orders\/([^/]+)$/)))return J(envelope({item:row(m[1])}));
    if((m=p.match(/orders\/([^/]+)\/fulfillment$/)))return J(shipping(m[1]));
    if((m=p.match(/orders\/([^/]+)\/physical-returns$/)))return J(returns(m[1]));
    if((m=p.match(/orders\/([^/]+)\/physical-returns\/operations\/([^/]+)$/)))return J(original(m[1],m[2]));
    return J({detail:{code:'unavailable'}},503);}
  const respond=s=>new Response(JSON.stringify(s.body),{status:s.status,headers:{'content-type':'application/json'}});
  window.fetch=(url,opts={})=>{const c={url:String(url),method:opts.method||'GET',settled:false};calls.push(c);
    if(c.method!=='GET'){violations.push(c.method+' '+c.url);return Promise.reject(Error('GET_ONLY'));}
    return new Promise((res,rej)=>{c.res=s=>{c.settled=true;res(respond(s));};if(opts.signal)opts.signal.addEventListener('abort',()=>{if(!c.settled){c.settled=true;rej(new DOMException('aborted','AbortError'));}});
      let spec;for(const r of routes)if(r.re.test(c.url)){spec=r.fn(c);if(spec!==undefined)break;}
      if(spec===DEFER)return;c.res(spec||dflt(c.url));});};
  window.__start=async function(name){
    const root=document.getElementById('commerce-orders'),q=s=>root.querySelector(s),all=s=>[...root.querySelectorAll(s)];
    const tick=async(n=10)=>{for(let i=0;i<n;i++)await new Promise(r=>setTimeout(r,0));};
    const flows=()=>{const s=q('#aco-order-flows');return s?s.textContent:'';};
    const evidence=()=>{const s=all('#aco-order-flows .aco-flow-card').filter(x=>/현재 반품 조회 근거|같은 주문의 반품 건/.test(x.querySelector('h3')?.textContent||''));return s.length?s[0].textContent:null;};
    const route=(re,fn)=>{routes.unshift({re,fn});},clear=()=>{routes=[];};
    const count=re=>calls.filter(c=>re.test(c.url)).length,pending=re=>calls.filter(c=>re.test(c.url)&&!c.settled);
    const CUR=/\/physical-returns$/,OP=/\/physical-returns\/operations\//,DET=/\/orders\/ORD-[^/]+$/;
    const ctl=()=>root.commerceOrderFlows.returns;
    const open=async no=>{all('[data-order-index]').find(b=>b.textContent===no).click();await tick();q('[data-flow-tab="returns"]').click();await tick();};
    const pick=async(rid,op)=>{q('[data-return-case="'+rid+'"]').click();await tick();if(op){q('[data-return-operation="'+op+'"]').click();await tick();}};
    const lookup=async()=>{q('[data-flow-lookup]').click();await tick();};
    const refresh=async()=>{q('[data-return-refresh]').click();await tick();};
    const snap=()=>{const s=ctl().snapshot();return {status:s.status,caseId:s.caseId,hasCurrent:!!s.current,original:s.original&&s.original.operation_id,result:s.result&&s.result.operation_id,busy:s.busy};};
    const lookupDisabled=()=>q('[data-flow-lookup]').disabled;
    const pendingView=()=>{const e=evidence()||'';return {evidence:e,staleQty:/신청 \d+ · 회수 \d+/.test(e),staleLine:e.includes('RETLINE-A1'),staleHistory:e.includes('REF-A1'),staleTime:e.includes('조회 시각'),staleCases:e.includes('반품 #11'),notice:e.includes('조회 중'),state:snap()};};
    const G={
      async refresh_pending_hides_then_restores(){await open(A);await pick(11);route(CUR,()=>DEFER);await refresh();const during=pendingView();clear();pending(CUR).pop().res(J(returns(A,2)));await tick();const e=evidence();return {during,after:{selected:e.includes('선택 반품 #11'),qty:e.includes('신청 2 · 회수 2'),old:e.includes('회수 1'),state:snap()}};},
      async refresh_pending_then_503_stays_unconfirmed(){await open(A);await pick(11);route(CUR,()=>DEFER);await refresh();const during=pendingView();clear();pending(CUR).pop().res(J({detail:{code:'physical_return_unavailable'}},503));await tick();const e=evidence();return {during,after:{missing:e.includes('최신 반품 대상·수량 미확인'),failed:flows().includes('최신 반품 조회 실패'),saysEmpty:flows().includes('확인된 반품 없음'),state:snap()}};},
      async refresh_pending_then_401_closes_page(){await open(A);await pick(11);route(CUR,()=>DEFER);await refresh();const during=pendingView();clear();pending(CUR).pop().res(J({detail:{code:'x'}},401));await tick();return {during,after:{conn:q('#aco-connection').dataset.state,rows:all('[data-order-index]').length,leak:root.textContent.includes('RETLINE-A1')}};},
      async lookup_checking_keeps_current_evidence(){await open(A);await pick(11,uid(102));route(OP,()=>DEFER);await lookup();const e=evidence();const o={qty:e.includes('신청 2 · 회수 1'),status:snap().status,checking:flows().includes('같은 원 작업 조회 중')};clear();pending(OP).pop().res(J(original(A,uid(102))));await tick();o.done=snap();return o;},
      async confirmed_result_blocks_repeat_lookup(){await open(A);await pick(11,uid(102));await lookup();const first=count(OP);const o={first,state:snap(),confirmed:flows().includes('서버 저장 원결과 확인'),buttonDisabled:lookupDisabled()};route(OP,()=>J({detail:{code:'physical_return_result_unconfirmed'}},503));q('[data-flow-lookup]').click();await tick();const viaController=await ctl().lookup();await tick();o.viaController=viaController;o.extraGET=count(OP)-first;o.after=snap();o.conflict=flows().includes('원결과 확인 불가');o.guard=ctl().guard();clear();const before=count(DET);all('[data-order-index]').find(b=>b.textContent===B).click();await tick();o.navDetailGET=count(DET)-before;return o;},
      async result_survives_current_failure_and_refresh(){await open(A);await pick(11,uid(102));await lookup();route(CUR,()=>DEFER);await refresh();const o={duringResult:flows().includes('서버 저장 원결과 확인'),duringState:snap()};clear();pending(CUR).pop().res(J({detail:{code:'physical_return_unavailable'}},503));await tick();o.failed=snap();o.failedResult=flows().includes('서버 저장 원결과 확인');o.failedLookupDisabled=lookupDisabled();o.refreshEnabled=!q('[data-return-refresh]').disabled;const n=count(CUR);await refresh();o.refreshGET=count(CUR)-n;o.recovered=snap();return o;},
      async new_operation_and_case_can_lookup(){await open(A);await pick(11,uid(102));await lookup();const n=count(OP);q('[data-return-operation="'+uid(101)+'"]').click();await tick();const o={sameCase:{state:snap(),enabled:!lookupDisabled()}};await lookup();o.sameCase.GET=count(OP)-n;o.sameCase.after=snap();await pick(12);o.otherCase={state:snap(),disabledUntilChosen:lookupDisabled()};q('[data-return-operation="'+uid(111)+'"]').click();await tick();o.otherCase.enabled=!lookupDisabled();const m=count(OP);await lookup();o.otherCase.GET=count(OP)-m;o.otherCase.after=snap();return o;},
      async failed_lookup_retries_same_operation(){await open(A);await pick(11,uid(102));route(OP,()=>J({detail:{code:'physical_return_not_found'}},404));const n=count(OP);await lookup();const o={first:snap(),enabled:!lookupDisabled(),message:flows().includes('미실행 확정 아님')};await lookup();o.secondGET=count(OP)-n;o.second=snap();const d=count(DET);all('[data-order-index]').find(b=>b.textContent===B).click();await tick();o.navBlockedDetailGET=count(DET)-d;clear();await lookup();o.thirdGET=count(OP)-n;o.third=snap();o.nowDisabled=lookupDisabled();o.refreshEnabled=!q('[data-return-refresh]').disabled;return o;},
      async other_order_resets_selection(){await open(A);await pick(11,uid(102));await lookup();all('[data-order-index]').find(b=>b.textContent===B).click();await tick();q('[data-flow-tab="returns"]').click();await tick();const o={state:snap(),leak:['RETLINE-A1','REF-A1',uid(102)].filter(x=>root.textContent.includes(x)),disabledWithoutOriginal:lookupDisabled()};await pick(11,uid(202));o.enabled=!lookupDisabled();const n=count(OP);await lookup();o.GET=count(OP)-n;o.after=snap();return o;},
      async unchanged_denial_guard_and_404_contracts(){await open(A);await pick(11,uid(102));route(OP,()=>J({detail:{code:'physical_return_permission_required'}},403));await lookup();const o={denied:{conn:q('#aco-connection').dataset.state,rows:all('[data-order-index]').length}};clear();q('#aco-refresh').click();await tick();await open(A);route(CUR,()=>DEFER);await refresh();const d=count(DET);all('[data-order-index]').find(b=>b.textContent===B).click();await tick();o.busyGuard={detailGET:count(DET)-d,guard:ctl().guard()};clear();pending(CUR).pop().res(J({detail:{code:'physical_return_not_found'}},404));await tick();o.notFound={label:flows().includes('source_unconnected · main 등록/운영 연결 미확인'),status:snap().status,saysEmpty:flows().includes('확인된 반품 없음')};return o;},
    };
    let result;try{await tick(20);result=await G[name]();}catch(e){result={HARNESS_ERROR:String(e&&e.stack||e)};}
    const pre=document.createElement('pre');pre.id='RESULT';pre.textContent=encodeURIComponent(JSON.stringify({result,violations,methods:[...new Set(calls.map(c=>c.method))],calls:calls.length}));document.body.appendChild(pre);
  };
})();}

function buildPage(dir){
  const tpl=fs.readFileSync(path.join(ROOT,'templates/admin/commerce_orders.html.j2'),'utf8');
  const block=n=>{const m=tpl.match(new RegExp('\\{% block '+n+' %\\}([\\s\\S]*?)\\{% endblock %\\}'));assert(m,'template block '+n);return m[1];};
  const shared=pathToFileURL(path.join(ROOT,'mockups/shared')).href+'/';
  const local=s=>s.replaceAll('"/shared/','"'+shared);
  const file=path.join(dir,'page.html');
  fs.writeFileSync(file,'<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>T</title>'+local(block('head_extra'))+'</head><body>'+block('content')+'<script>('+pageMain.toString()+')();</script>'+local(block('foot_extra'))+'<script>window.__start(location.hash.slice(1));</script></body></html>');
  return pathToFileURL(file).href;
}
function browser(){
  const list=[process.env.CHROME_PATH,'C:/Program Files/Google/Chrome/Application/chrome.exe','C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','/usr/bin/google-chrome','/usr/bin/chromium','/usr/bin/chromium-browser'];
  return list.find(p=>p&&fs.existsSync(p));
}
function run(bin,url,profile,name){
  let dom='';
  try{dom=execFileSync(bin,['--headless=new','--disable-gpu','--no-first-run','--no-sandbox','--disable-extensions','--disable-sync','--disable-background-networking','--disable-component-update','--allow-file-access-from-files','--host-resolver-rules=MAP * ~NOTFOUND','--user-data-dir='+profile,'--window-size=1440,1000','--virtual-time-budget=20000','--dump-dom',url+'#'+name],{encoding:'utf8',maxBuffer:1<<26,timeout:90000,stdio:['ignore','pipe','ignore']});}catch(e){dom=e.stdout||'';}
  const m=dom.match(/<pre id="RESULT">([^<]*)<\/pre>/);
  if(!m)throw Error('no result from page: '+name);
  return JSON.parse(decodeURIComponent(m[1]));
}
const hidden=d=>{assert.equal(d.staleQty,false,'stale quantity shown while loading');assert.equal(d.staleLine,false,'stale line shown while loading');assert.equal(d.staleHistory,false,'stale history shown while loading');assert.equal(d.staleTime,false,'stale checked_at shown while loading');assert.equal(d.staleCases,false,'stale case shown while loading');assert.equal(d.notice,true,'loading notice');assert.equal(d.state.status,'loading');assert.equal(d.state.hasCurrent,true,'state.current kept while loading');assert.equal(d.state.caseId,11,'caseId kept while loading');};
const CHECKS={
  refresh_pending_hides_then_restores(r){hidden(r.during);assert.equal(r.after.selected,true);assert.equal(r.after.qty,true);assert.equal(r.after.old,false);assert.equal(r.after.state.status,'ready');},
  refresh_pending_then_503_stays_unconfirmed(r){hidden(r.during);assert.equal(r.after.missing,true);assert.equal(r.after.failed,true);assert.equal(r.after.saysEmpty,false);assert.equal(r.after.state.hasCurrent,false);},
  refresh_pending_then_401_closes_page(r){hidden(r.during);assert.equal(r.after.conn,'denied');assert.equal(r.after.rows,0);assert.equal(r.after.leak,false);},
  lookup_checking_keeps_current_evidence(r){assert.equal(r.status,'checking');assert.equal(r.qty,true);assert.equal(r.checking,true);assert.equal(r.done.status,'confirmed');},
  confirmed_result_blocks_repeat_lookup(r){assert.equal(r.first,1);assert.equal(r.confirmed,true);assert.equal(r.buttonDisabled,true,'lookup button disabled after confirmation');assert.equal(r.viaController,false,'controller refuses repeat lookup');assert.equal(r.extraGET,0,'no extra GET');assert.equal(r.after.status,'confirmed');assert.equal(r.conflict,false);assert.equal(r.guard,null);assert.equal(r.navDetailGET,1);},
  result_survives_current_failure_and_refresh(r){assert.equal(r.duringResult,true);assert.equal(r.failed.status,'error');assert.equal(r.failed.hasCurrent,false);assert.equal(r.failed.result,'00000000-0000-4000-8000-000000000102');assert.equal(r.failedResult,true);assert.equal(r.failedLookupDisabled,true,'lookup stays disabled with a confirmed result');assert.equal(r.refreshEnabled,true);assert.equal(r.refreshGET,1);assert.equal(r.recovered.status,'ready');assert.equal(r.recovered.result,'00000000-0000-4000-8000-000000000102');},
  new_operation_and_case_can_lookup(r){assert.equal(r.sameCase.state.result,null);assert.equal(r.sameCase.enabled,true);assert.equal(r.sameCase.GET,1);assert.equal(r.sameCase.after.result,'00000000-0000-4000-8000-000000000101');assert.equal(r.otherCase.state.original,null);assert.equal(r.otherCase.disabledUntilChosen,true);assert.equal(r.otherCase.enabled,true);assert.equal(r.otherCase.GET,1);assert.equal(r.otherCase.after.result,'00000000-0000-4000-8000-000000000111');},
  failed_lookup_retries_same_operation(r){assert.equal(r.first.status,'unknown');assert.equal(r.enabled,true);assert.equal(r.message,true);assert.equal(r.secondGET,2);assert.equal(r.second.status,'unknown');assert.equal(r.navBlockedDetailGET,0);assert.equal(r.thirdGET,3);assert.equal(r.third.status,'confirmed');assert.equal(r.nowDisabled,true,'lookup disabled once the retry confirms');assert.equal(r.refreshEnabled,true);},
  other_order_resets_selection(r){assert.equal(r.state.original,null);assert.equal(r.state.result,null);assert.equal(r.state.caseId,null);assert.deepEqual(r.leak,[]);assert.equal(r.disabledWithoutOriginal,true);assert.equal(r.enabled,true);assert.equal(r.GET,1);assert.equal(r.after.result,'00000000-0000-4000-8000-000000000202');},
  unchanged_denial_guard_and_404_contracts(r){assert.equal(r.denied.conn,'denied');assert.equal(r.denied.rows,0);assert.equal(r.busyGuard.detailGET,0);assert.match(r.busyGuard.guard,/조회 중/);assert.equal(r.notFound.label,true);assert.equal(r.notFound.status,'unavailable');assert.equal(r.notFound.saysEmpty,false);},
};
(function main(){
  const self=pageMain.toString();
  assert(!/\.(execute|submit)\(/.test(self),'page script must not call write paths');
  for(const f of ['admin-commerce-physical-returns.js','admin-commerce-physical-returns-transport.js'])assert(!/method\s*:\s*['"]POST/.test(fs.readFileSync(path.join(ROOT,'mockups/shared',f),'utf8')),f+' source must stay GET-only');
  const bin=browser();if(!bin){console.error('BLOCKED: no Chrome/Edge found; regression not executed');process.exitCode=2;return;}
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'return-read-display-'));let failed=0,reported=0;const only=process.argv.slice(2);
  try{const url=buildPage(dir);
    for(const name of GROUPS.filter(g=>!only.length||only.includes(g))){
      try{const out=run(bin,url,path.join(dir,'profile'),name);
        assert.deepEqual(out.violations,[],'non-GET attempted');assert.deepEqual(out.methods,['GET']);assert.equal(out.result.HARNESS_ERROR,undefined,out.result.HARNESS_ERROR);
        CHECKS[name](out.result);reported++;console.log('PASS '+name+' (GET '+out.calls+')');
      }catch(error){failed++;console.log('FAIL '+name+' :: '+String(error.message).split('\n')[0]);}
    }
  }finally{fs.rmSync(dir,{recursive:true,force:true});}
  console.log(reported+' passed, '+failed+' failed');if(failed)process.exitCode=1;
})();
