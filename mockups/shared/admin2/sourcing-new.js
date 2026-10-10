(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else{root.SourcingNew=factory();root.SourcingNew.mount(root);}})(typeof window==='undefined'?globalThis:window,function(){'use strict';
const MODE='sourcing', API='/api/admin/sourcing';

  const JOURNAL = 'popcorn-e1-operation-journal-v1';
  const COPY = {
    uncertain: '처리 결과 미확인 · 처리 근거 확인 전 추가 변경이 차단됩니다. 자동 재시도하지 않습니다.',
    writing: '저장 중 · 응답을 기다리고 있습니다.',
    refreshing: '저장 완료 · 최신 상태 조회 중',
    refresh_failed: '저장 완료 · 최신 상태 조회 실패. 이전 조회값입니다.',
    outside: '현재 조회 목록에 없습니다. 정확한 상품 상태는 확인되지 않았습니다.',
    permission: '로그인 및 운영자 권한을 확인하세요.'
  };
  function integer(value) { return /^\d+$/.test(String(value)) && Number.isSafeInteger(Number(value)) && Number(value) >= 1; }
  function createController(io, saved) {
    const s = { selected: saved?.selected || null, query: saved?.query || {q:'',part:'',page:1,mode:'pending',hold:'exclude',kind:'all'},
      items:[], records:{}, drafts:saved?.drafts || {}, suppliers:[], list:null, loading:false, error:'', meta:[], metaError:'',
      canWrite:false, permissionReady:false, permission:false, generation:0, epoch:0, busy:null, history:null, historyPage:1, historyCode:null, historyLoading:false, historyError:'', historyGeneration:0, journalError:false };
    function journal() { try { const raw=io.storage?.getItem(JOURNAL); const data=raw?JSON.parse(raw):{}; if(!data || Array.isArray(data) || typeof data!=='object'||Object.values(data).some(j=>!j||!['sourcing','stock'].includes(j.mode)||!Number.isSafeInteger(j.code)||j.code<1||!['writing','uncertain','saved'].includes(j.phase)||(j.phase==='saved'&&(!j.result||j.result.action!==j.action||!validResult(j.action,j.result.data,j.mode)))))throw Error(); return data; }catch(e){s.journalError=true;return {};} }
    const restored=journal();
    Object.values(restored).forEach(j=>{ if(j && j.mode===MODE && Number.isSafeInteger(j.code)){
      s.records[j.code]={item:null, phase:j.phase==='saved'?'refresh_failed':'uncertain', unresolved:j.phase!=='saved', result:j.result||null, note:j.phase==='saved'?COPY.refresh_failed:COPY.uncertain, stale:true};
    }});
    function record(code) { return s.records[code] || (s.records[code]={item:null,phase:'ready',unresolved:false,result:null,note:'',stale:true}); }
    function draft(code) { return s.drafts[code] || (s.drafts[code]={qty:'',why:record(code).item?.why==='adjust'?'adjust':'inbound',suppliers:[],quote:null,replies:{},replyOpen:null,holdReason:''}); }
    function persist() { try{io.saveState?.({selected:s.selected,query:s.query,drafts:s.drafts});}catch(e){} }
    function emit(){persist();io.change?.(s);}
    function putJournal(code,value){try{if(!io.storage)throw Error('storage unavailable'); const all=journal();if(s.journalError)throw Error();const key=MODE+':'+code;if(value)all[key]=value;else delete all[key];io.storage.setItem(JOURNAL,JSON.stringify(all));return true;}catch(e){s.journalError=true;return false;}}
    function journalBlocked(code){return Object.values(journal()).some(j=>j.code===code&&j.mode!==MODE&&j.phase!=='saved');}
    function allowed(code){const r=record(code);return s.canWrite&&!s.permission&&!s.journalError&&!s.busy&&!s.loading&&!s.error&&!!r.item&&!r.stale&&!r.unresolved&&!journalBlocked(code)&&r.phase==='ready';}
    function listUrl(){const p=new URLSearchParams({page:String(s.query.page),size:'50'});if(MODE==='sourcing'){if(s.query.q)p.set('q',s.query.q);if(s.query.part)p.set('part_type',s.query.part);}
      else {p.set('hold',s.query.hold);p.set('kind',s.query.kind);if(s.query.mode==='catalog')p.set('catalog_q',s.query.q);else{if(s.query.q)p.set('q',s.query.q);if(s.query.part)p.set('part_type',s.query.part);}}return API+'?'+p;}
    async function load(){if(s.busy!==null)return;const gen=++s.generation, epoch=s.epoch, url=listUrl();s.loading=true;s.error='';Object.values(s.records).forEach(r=>r.stale=true);emit();
      if(MODE==='stock'&&s.query.mode==='catalog'&&!s.query.q.trim()){s.list=null;s.items=[];s.loading=false;emit();return;}
      try{const data=await io.get(url);if(gen!==s.generation||epoch!==s.epoch||url!==listUrl())return;
        if(!data || !Array.isArray(data.items) || !Number.isInteger(data.page) || !Number.isInteger(data.total) || !Number.isInteger(data.pages) || !Number.isInteger(data.size) || data.page<1 || data.size<1 || data.total<0 || data.pages<0 || (MODE==='stock'&&!Array.isArray(data.catalog)))throw Error('조회 응답 형식 오류');
        const rows=MODE==='stock'&&s.query.mode==='catalog'?data.catalog:data.items;
        if(rows.some(p=>!Number.isSafeInteger(p.product_code)||!Number.isFinite(p.stock)||(MODE==='sourcing'&&!Array.isArray(p.quotes))))throw Error('상품 조회 응답 형식 오류');
        s.list=data;s.items=rows;s.suppliers=data.suppliers||[];s.query.page=data.page;
        rows.forEach(item=>{const r=record(item.product_code);r.item=item;if(r.unresolved){r.stale=true;r.phase='uncertain';return;}r.stale=false;if(r.phase==='refreshing'||r.phase==='refresh_failed'){r.phase='ready';r.note='저장 응답 확인 · 최신 목록 조회 완료';putJournal(item.product_code,null);}const d=draft(item.product_code);if(MODE==='sourcing'&&!item.quotes.some(q=>q.quote_id===d.quote&&q.status==='회신'&&integer(q.price)))d.quote=null;});
        Object.entries(s.records).forEach(([code,r])=>{if(!rows.some(p=>p.product_code===Number(code))){r.stale=true;if(r.phase==='refreshing'||r.phase==='refresh_failed'){r.phase='refresh_failed';r.note=COPY.outside;}}});
      }catch(e){if(gen!==s.generation||epoch!==s.epoch)return;s.error=e.message||'목록 조회 실패';if(e.status===401||e.status===403)s.permission=true;Object.values(s.records).forEach(r=>{r.stale=true;if(r.phase==='refreshing'){r.phase='refresh_failed';r.note=COPY.refresh_failed;}});}
      if(gen===s.generation&&epoch===s.epoch){s.loading=false;emit();}
    }
    async function meta(){try{const data=await io.get('/api/admin/product-meta');if(!Array.isArray(data.used_parts))throw Error('분류 조회 응답 오류');s.meta=data.used_parts;}catch(e){s.metaError='분류 선택지 조회 실패';}emit();}
    function select(code){s.selected=code;draft(code);emit();if(MODE==='stock')history(code,1);}
    function back(){s.selected=null;emit();if(MODE==='stock')history(null,1);}
    async function filter(values){Object.assign(s.query,values);if(!('page' in values))s.query.page=1;emit();return load();}
    function edit(code,key,value){draft(code)[key]=value;persist();io.editChange?.(s,code);}
    function quote(code,id){const r=record(code);if(r.item?.quotes.some(q=>q.quote_id===id&&q.status==='회신'&&integer(q.price))){draft(code).quote=id;emit();}}
    function can(action,code,arg){if(MODE==='stock'&&action==='undo'){const r=record(code),h=s.history?.items?.find(h=>h.log_id===arg&&h.product_code===code);return s.canWrite&&!s.permission&&!s.journalError&&!s.busy&&!r.unresolved&&!journalBlocked(code)&&!s.historyLoading&&!s.historyError&&s.history?.can_write===true&&h?.undoable===true&&['ready','refresh_failed'].includes(r.phase);}if(!allowed(code))return false;const p=record(code).item,d=draft(code);
      if(MODE==='sourcing'){if(action==='request')return !p.quotes.length&&d.suppliers.length>0&&d.suppliers.every(id=>s.suppliers.some(x=>x.id===id));const q=p.quotes.find(x=>x.quote_id===(action==='confirm'?d.quote:arg));if(!q)return false;if(action==='confirm')return q.status==='회신'&&integer(q.price);if(action==='reply')return ['요청','회신'].includes(q.status)&&integer(d.replies[arg]?.price);return false;}
      if(action==='inbound')return integer(d.qty)&&['inbound','adjust'].includes(d.why)&&!p.hold&&!['단종','삭제대기'].includes(p.status);
      if(action==='hold')return s.query.mode!=='catalog'&&!p.hold&&!!d.holdReason.trim();
      if(action==='release')return !!p.hold;
      if(action==='undo'){const h=s.history?.items?.find(h=>h.log_id===arg&&h.product_code===code);return !s.historyLoading&&!s.historyError&&s.history?.can_write===true&&h?.undoable===true;}
      return false;
    }
    function operation(action,code,arg){const d=draft(code);if(MODE==='sourcing'){if(action==='request')return {path:API+'/request',body:{product_code:code,supplier_ids:[...new Set(d.suppliers)]}};if(action==='reply')return {path:API+'/quotes/'+arg+'/reply',body:{price:Number(d.replies[arg].price),memo:d.replies[arg].memo||null}};return {path:API+'/quotes/'+d.quote+'/confirm',body:undefined};}
      if(action==='inbound')return {path:API+'/'+code,body:{qty:Number(d.qty),why:d.why}};if(action==='hold')return {path:API+'/hold/'+code,body:{reason:d.holdReason.trim()}};if(action==='release')return {path:API+'/hold/'+code+'/release',body:undefined};return {path:API+'/undo/'+arg,body:undefined};}
    async function write(action,code,arg){if(!can(action,code,arg))return false;const op=operation(action,code,arg),r=record(code);const entry={mode:MODE,code,action,path:op.path,body:op.body,phase:'writing',at:new Date().toISOString()};
      if(!putJournal(code,entry)){r.note='처리 기록을 저장할 수 없어 전송하지 않습니다.';emit();return false;}
      s.busy=code;s.epoch++;s.generation++;s.historyGeneration++;s.historyLoading=false;s.loading=false;r.phase='writing';r.stale=true;r.note=COPY.writing;emit();
      try{const result=await io.post(op.path,op.body);if(!validResult(action,result))throw Error('저장 응답을 확인하지 못했습니다.');r.result={action,data:result,at:new Date().toISOString()};r.phase='refreshing';r.note=COPY.refreshing;r.unresolved=false;const stored=putJournal(code,{...entry,phase:'saved',result:r.result});
        if(!stored){r.phase='uncertain';r.unresolved=true;r.note=COPY.uncertain;}if(MODE==='stock'&&action==='inbound'){draft(code).qty='';}if(MODE==='sourcing'&&action==='reply')draft(code).replyOpen=null;
      }catch(e){if(e.status>=400&&e.status<500&&!e.uncertain){r.phase='conflict';r.note=e.message||'요청이 거절되었습니다. 최신 상태를 다시 확인하세요.';putJournal(code,null);if(e.status===401||e.status===403){s.permission=true;r.phase='permission';}}else{r.unresolved=true;r.phase='uncertain';r.note=COPY.uncertain;putJournal(code,{...entry,phase:'uncertain'});}}
      s.busy=null;emit();if(r.phase==='refreshing'){await load();if(MODE==='stock')await history(s.historyCode,s.historyPage);}return true;
    }
    async function history(code,page){if(MODE!=='stock')return;const gen=++s.historyGeneration,epoch=s.epoch;s.historyCode=code??null;s.historyPage=page||1;s.historyLoading=true;s.historyError='';emit();try{const data=await io.get(API+'/history?page='+s.historyPage+'&size=20'+(code==null?'':'&product_code='+code));if(gen!==s.historyGeneration||epoch!==s.epoch)return;if(!data||!Array.isArray(data.items)||data.product_code!==(code??null)||!Number.isInteger(data.page)||!Number.isInteger(data.pages)||!Number.isInteger(data.total)||data.items.some(h=>!Number.isSafeInteger(h.log_id)||h.log_id<1||!Number.isSafeInteger(h.product_code)||h.product_code<1||(code!=null&&h.product_code!==code)))throw Error('입고 이력 응답 형식 오류');s.history=data;if(data.can_write===false)s.canWrite=false;}catch(e){if(gen!==s.historyGeneration||epoch!==s.epoch)return;s.historyError=e.message||'입고 이력 조회 실패';}if(gen===s.historyGeneration&&epoch===s.epoch){s.historyLoading=false;emit();}}
    function acceptRead(code){const r=record(code);if(r.phase==='conflict'&&!r.unresolved&&!r.stale){r.phase='ready';r.note='최신 조회값을 확인했습니다.';emit();}}
    function permission(value){s.permissionReady=true;s.canWrite=!!value;emit();}
    return {state:s,record,draft,load,meta,select,back,filter,edit,quote,can,write,history,acceptRead,permission,allowed,journalBlocked};
  }
  function validResult(action,x,mode=MODE){if(!x||x.ok!==true)return false;if(mode==='sourcing'){if(!['request','reply','confirm'].includes(action))return false;if(action==='request')return Number.isSafeInteger(x.batch_id)&&Array.isArray(x.quotes);if(action==='reply')return integer(x.price);return ['purchase_before','purchase_after','sale_before','sale_after'].every(k=>k in x&&(x[k]===null||Number.isFinite(x[k])))&&(typeof x.sale_locked==='boolean')&&integer(x.price);}if(action==='inbound')return Number.isFinite(x.stock_before)&&Number.isFinite(x.stock_after)&&Number.isSafeInteger(x.undo_id)&&typeof x.pool_entered==='boolean';if(action==='undo')return Number.isFinite(x.stock_after);return ['hold','release'].includes(action)&&Number.isSafeInteger(x.hold_id);}
  function esc(x){return String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  function clean(w,x){return w.Admin2Text?w.Admin2Text.stripHtml(x):String(x??'').replace(/<[^>]*>/g,'');}
  function amount(x){return x==null?'미확인':Number(x).toLocaleString('ko-KR');}
  function won(x){return x==null?'미등록':amount(x)+'원';}
  function disabled(value){return value?'':' disabled';}
  async function request(w,url,body,method){let res;res=await w.fetch(url,{credentials:'same-origin',method,headers:body!==undefined?{'Content-Type':'application/json'}:undefined,body:body!==undefined?JSON.stringify(body):undefined});let data;try{data=await res.json();}catch(e){const err=Error(method==='POST'?'처리 응답을 확인하지 못했습니다.':'조회 응답 형식 오류');err.status=res.status;err.uncertain=method==='POST';throw err;}if(!res.ok){const err=Error(typeof data?.detail==='string'?data.detail:'요청 오류 '+res.status);err.status=res.status;throw err;}return data;}
  function status(c,code){const r=c.record(code),s=c.state;let note=r.note;if(r.unresolved)note=COPY.uncertain;else if(c.journalBlocked(code))note='이 상품의 다른 화면 처리 결과가 미확인입니다. 처리 근거 확인 전 추가 변경이 차단됩니다.';else if(s.journalError)note='처리 기록 저장소를 확인할 수 없습니다. 추가 변경이 차단됩니다.';else if(s.permission||!s.canWrite)note=COPY.permission;else if(r.stale&&!note)note=s.loading?'최신 상태 조회 중':r.item?'이전 조회값 · 최신 상태 확인 필요':'상품 상태 미확인';
    return (note?'<div class="e1-status '+(r.unresolved||r.phase==='permission'?'error':'')+'" role="status"><strong>'+esc(note)+'</strong>'+(r.stale&&r.item?'<p>이전 조회값 · 최신 상태 확인 필요</p>':'')+'<button type="button" data-action="reload"'+disabled(!s.busy&&!s.loading)+'>다시 조회</button>'+(r.phase==='conflict'&&!r.stale?'<button type="button" data-action="accept" data-code="'+code+'">최신 조회값 확인</button>':'')+'</div>':'');
  }
  function pager(data,action){if(!data)return '';const a=data.total?(data.page-1)*data.size+1:0,z=Math.min(data.page*data.size,data.total);return '<div class="e1-pager"><button type="button" data-action="'+action+'" data-page="'+(data.page-1)+'"'+disabled(data.page>1)+'>이전</button><span>검색 '+amount(data.total)+'건 중 '+amount(a)+'–'+amount(z)+'건</span><button type="button" data-action="'+action+'" data-page="'+(data.page+1)+'"'+disabled(data.page<data.pages)+'>다음</button></div>';}
  function resultHtml(c,code){const result=c.record(code).result;if(!result)return '';const x=result.data;let text='';if(MODE==='sourcing'){if(result.action==='confirm')text='<h3>가격 확정 응답 확인</h3><p>회신가 '+won(x.price)+' · 상품 매입가 '+won(x.purchase_before)+' → '+won(x.purchase_after)+'</p><p>판매가 '+won(x.sale_before)+' → '+won(x.sale_after)+(x.sale_locked?' · 잠금으로 유지':'')+'</p><p>재고는 늘지 않았습니다. 대기 조건은 다음 조회에 따라 표시합니다.</p><a href="/admin2/stock-inbound?admin=new&amp;product_code='+code+'">이 상품 재고 입고 보기</a>';else text='<h3>'+(result.action==='request'?'견적 요청 기록 완료':'회신 입력 완료')+'</h3><p>실제 연락·자동 회신 수신은 하지 않습니다.</p>';}else{if(result.action==='inbound')text='<h3>입고 응답 확인</h3><p>실제 재고 '+amount(x.stock_before)+' → '+amount(x.stock_after)+'</p><p>'+(x.pool_entered?'추천 후보 진입 확인':'추천 후보에 들어가지 않았습니다.')+'</p>';else if(result.action==='undo')text='<h3>되돌림 응답 확인</h3><p>재고 '+amount(x.stock_after)+' · 역방향 원장 기록</p>';else text='<h3>'+(result.action==='hold'?'보류 등록 응답 확인':'보류 해제 응답 확인')+'</h3><p>'+esc(x.note||'')+'</p>';}
    return '<section class="e1-result" aria-label="이 상품의 처리 응답">'+text+'</section>';}

  function uiStage(product, draft, requested) {
    const quotes = product?.quotes || [];
    if (!quotes.length) return 'request';
    const chosen = quotes.find(q => q.quote_id === draft?.quote && q.status === '회신' && integer(q.price));
    return requested === 'confirm' && chosen ? 'confirm' : 'compare';
  }
  function replyEdited(draft, baseline) {
    return String(draft?.price ?? '') !== String(baseline?.price ?? '') || String(draft?.memo ?? '') !== String(baseline?.memo ?? '');
  }
  function mount(w){const doc=w.document,root=doc.getElementById('sourcingNew');if(!root)return;const $=id=>doc.getElementById(id);let saved={},listScroll={root:0,window:0}, stage='compare', stageCode=null, replyLeave=false;try{saved=JSON.parse(w.sessionStorage.getItem('sourcing-new-state')||'{}');}catch(e){}
    const entryCode=Number(new URLSearchParams(w.location.search).get('product_code'));if(Number.isSafeInteger(entryCode)&&entryCode>0)saved.selected=entryCode;const c=createController({storage:w.sessionStorage,get:url=>request(w,url,undefined,'GET'),post:(url,body)=>request(w,url,body,'POST'),saveState:x=>w.sessionStorage.setItem('sourcing-new-state',JSON.stringify(x)),change:render,editChange:updateActions},saved);
    function updateActions(s,code){root.querySelectorAll('[data-write]').forEach(b=>b.disabled=!c.can(b.dataset.write,Number(b.dataset.code),Number(b.dataset.arg)));const d=c.draft(code),count=$('srcNewRequestCount');if(count)count.textContent=d.suppliers.length+'곳에 견적 요청 기록';}
    function render(s){
      const active=doc.activeElement,attrs=['data-qty','data-hold','data-why','data-reply','data-field','data-quote'];
      const focusAttrs=attrs.filter(a=>active?.hasAttribute(a)).map(a=>[a,active.getAttribute(a)]),selection=active?.selectionStart;
      const restoreFocus=()=>{if(!focusAttrs.length)return;const el=root.querySelector(focusAttrs.map(([a,v])=>'['+a+'="'+v+'"]').join(''));if(el&&!el.disabled){el.focus({preventScroll:true});if(selection!=null&&el.setSelectionRange)try{el.setSelectionRange(selection,selection);}catch(e){}}};
      root.dataset.selected=String(s.selected!==null);
      root.querySelectorAll('[data-action=reload]').forEach(b=>b.disabled=!!s.busy||s.loading);root.querySelectorAll('[data-action=back]').forEach(b=>b.disabled=!!s.busy);
      $('srcNewListStatus').textContent=s.error?'목록 조회 실패 · '+s.error:s.loading?'목록 조회 중':!s.canWrite?(s.permissionReady?COPY.permission:'운영자 권한 확인 중'):s.metaError;
      $('srcNewSearch').value=s.query.q;
      $('srcNewPart').innerHTML='<option value="">전체 부품 종류</option>'+s.meta.map(x=>'<option value="'+esc(x.part_type)+'">'+esc(x.label)+'</option>').join('');$('srcNewPart').value=s.query.part;
      $('srcNewList').innerHTML=s.items.map(p=>'<button class="src-new-item" type="button" data-action="select" data-code="'+p.product_code+'"><span><strong>'+esc(clean(w,p.name))+'</strong><small>'+p.product_code+' · '+esc(p.sku)+'</small></span><span>재고 '+amount(p.stock)+' / 안전 '+amount(p.safety_stock)+'</span><span>'+won(p.purchase)+'</span><span>'+esc(p.why)+' · '+({req:'요청 전',wait:'회신 대기',reply:'회신 비교'}[p.state]||'미확인')+'</span></button>').join('')||'<p class="e1-empty">'+(s.error?'이전 조회 목록을 확인하세요.':s.loading?'불러오는 중':'현재 검색 조건에 맞는 상품이 없습니다.')+'</p>';
      $('srcNewPager').innerHTML=pager(s.list,'page');
      if(s.selected===null)return;
      const code=s.selected,r=c.record(code),p=r.item,d=c.draft(code);
      if(!p){$('srcNewTask').innerHTML=status(c,code)+resultHtml(c,code)+'<p class="e1-empty">상품코드 '+code+' · 현재 조회 범위에서 상품을 확인할 수 없습니다. 목록 검색으로 다시 찾아주세요.</p>';return;}
      if(stageCode!==code){stageCode=code;stage='compare';replyLeave=false;}
      const qs=p.quotes||[],selected=qs.find(x=>x.quote_id===d.quote&&x.status==='회신'&&integer(x.price));
      stage=uiStage(p,d,stage);
      const stageButtons='<nav class="src-new-stage-nav" aria-label="견적 진행">'+[['request','1 요청 기록'],['compare','2 회신 비교'],['confirm','3 확정 전 확인']].map(([key,label])=>'<button type="button" data-action="stage" data-stage="'+key+'" aria-pressed="'+(stage===key)+'"'+(key==='request'&&qs.length||key!=='request'&&!qs.length||key==='confirm'&&!selected?' disabled':'')+'>'+label+'</button>').join('')+'</nav>';
      let requestSection=!qs.length?'<section class="e1-section"><h2>공급처 선택 · 요청 기록</h2><p>전화·메일로 연락한 요청을 기록합니다. 자동 전송은 하지 않습니다.</p>'+(s.suppliers.length?'<div class="src-new-suppliers">'+s.suppliers.map(x=>'<label><input type="checkbox" data-supplier="'+x.id+'"'+(d.suppliers.includes(x.id)?' checked':'')+disabled(c.allowed(code))+'><strong>'+esc(x.name)+'</strong> '+esc(x.brands||'')+'</label>').join('')+'</div><button class="e1-primary" data-write="request" data-code="'+code+'"'+disabled(c.can('request',code))+'><span id="srcNewRequestCount">'+d.suppliers.length+'곳에 견적 요청 기록</span></button>':'<p>활성 공급처가 없습니다. <a href="/admin2/suppliers?admin=new">공급처 관리</a>에서 등록하세요.</p>')+'</section>':'';
      if(p.last_fix&&!qs.length)requestSection='<details class="e1-section"><summary>새 견적 요청 기록</summary>'+requestSection+'</details>';
      const rows=qs.map(q=>{d.replies[q.quote_id]||(d.replies[q.quote_id]={price:q.price==null?'':String(q.price),memo:q.memo||''});return '<article class="src-new-quote '+(d.quote===q.quote_id?'selected':'')+'"><div class="src-new-quote-head"><label>'+(q.status==='회신'&&integer(q.price)?'<input type="radio" name="srcQuote" data-quote="'+q.quote_id+'"'+(d.quote===q.quote_id?' checked':'')+disabled(c.allowed(code))+'>':'')+'<strong>'+esc(q.supplier)+'</strong></label><strong class="src-new-price">'+(q.price==null?'회신 대기':won(q.price))+'</strong></div><div class="src-new-quote-meta"><span class="e1-tag">'+(q.price==null?'회신 대기':q.best?'최저 회신가':esc(q.status))+'</span></div><p>메모 · '+esc(q.memo||(q.price==null?'아직 회신가가 없습니다.':'없음'))+'</p><button class="src-new-reply-toggle" type="button" data-action="reply-toggle" data-arg="'+q.quote_id+'"'+disabled(c.allowed(code))+'>'+(q.price==null?'회신 입력':'회신 수정')+'</button></article>';}).join('');
      const compare=qs.length&&stage==='compare'?'<section class="src-new-compare"><h2 tabindex="-1">회신가 비교</h2><p>회신이 기록된 견적을 선택하세요.</p><div class="src-new-quotes">'+rows+'</div><div class="src-new-next"><span>'+(selected?esc(selected.supplier)+' · '+won(selected.price)+' 선택':'선택한 회신이 없습니다.')+'</span><button class="e1-primary" type="button" data-action="stage" data-stage="confirm"'+disabled(!!selected)+'>선택 견적 확인</button></div></section>':'';
      const confirm=qs.length&&stage==='confirm'?'<section class="src-new-confirm-review"><h2 tabindex="-1">확정 전 확인</h2><article><h3>'+esc(selected.supplier)+'</h3><dl><dt>선택 공급처 회신가</dt><dd>'+won(selected.price)+'</dd><dt>상품 매입가</dt><dd>현재 '+won(p.purchase)+' · 확정 후 재판정</dd><dt>판매가</dt><dd>잠금이면 유지, 잠금이 없으면 재산정</dd><dt>같은 배치 견적</dt><dd>나머지 요청·회신 견적 취소</dd><dt>재고</dt><dd>가격 확정으로 늘지 않음</dd></dl></article><p>상품 매입가는 선택한 공급처 회신가와 다를 수 있습니다. 최종 전·후 값은 확정 응답으로 확인합니다.</p><div class="src-new-next"><button type="button" data-action="stage" data-stage="compare">회신 비교로</button><button class="e1-primary" type="button" data-write="confirm" data-code="'+code+'"'+disabled(c.can('confirm',code))+' >선택 견적 가격 확정</button></div></section>':'';
      const replyQuote=qs.find(q=>q.quote_id===d.replyOpen);
      let dialog='';
      if(replyQuote){const reply=d.replies[replyQuote.quote_id];dialog='<dialog id="srcNewReplyDialog" aria-labelledby="srcNewReplyTitle"><h2 id="srcNewReplyTitle">'+esc(replyQuote.supplier)+' · 회신 '+(replyQuote.price==null?'입력':'수정')+'</h2><p>운영자가 공급처 회신을 대행 입력합니다.</p><div class="src-new-reply"><label>회신가(원)<input inputmode="numeric" data-reply="'+replyQuote.quote_id+'" data-field="price" value="'+esc(reply.price)+'"'+disabled(c.allowed(code))+'></label><label>메모<input maxlength="200" data-reply="'+replyQuote.quote_id+'" data-field="memo" value="'+esc(reply.memo)+'"'+disabled(c.allowed(code))+'></label></div><div class="src-new-next"><button type="button" data-action="reply-close"'+disabled(!s.busy)+'>취소</button><button class="e1-primary" type="button" data-write="reply" data-code="'+code+'" data-arg="'+replyQuote.quote_id+'"'+disabled(c.can('reply',code,replyQuote.quote_id))+'>회신 기록</button></div>'+(replyLeave?'<div class="e1-status"><p>저장하지 않은 입력이 있습니다.</p><button type="button" data-action="reply-keep">계속 입력</button><button type="button" data-action="reply-discard">입력 버리기</button></div>':'')+'</dialog>';}
      $('srcNewTask').innerHTML=status(c,code)+'<header class="src-new-product"><p>매입 견적 · 상품 '+code+' · SKU '+esc(p.sku)+'</p><h1 tabindex="-1">'+esc(clean(w,p.name))+'</h1><div>재고 <b>'+amount(p.stock)+'</b> / 안전재고 <b>'+amount(p.safety_stock)+'</b><span class="src-new-purchase"> · 상품 매입가 <b>'+won(p.purchase)+'</b></span></div></header>'+stageButtons+(p.last_fix?'<p class="e1-notice">최근 확정: '+esc(p.last_fix.supplier)+' · '+won(p.last_fix.price)+' · 가격 확정은 재고 입고가 아닙니다.</p><a href="/admin2/stock-inbound?admin=new&amp;product_code='+code+'">이 상품 재고 입고 보기</a>':'')+resultHtml(c,code)+requestSection+compare+confirm+dialog;
      updateActions(s,code);
      const modal=$('srcNewReplyDialog');if(modal){modal.addEventListener('cancel',e=>{e.preventDefault();closeReply();});modal.showModal();}
      restoreFocus();
    }
    function replyIsDirty(){const code=c.state.selected;if(code==null)return false;const d=c.draft(code),q=c.record(code).item?.quotes?.find(q=>q.quote_id===d.replyOpen);return !!q&&replyEdited(d.replies[q.quote_id],q);}
    function closeReply(){if(c.state.busy)return;if(replyIsDirty()){replyLeave=true;render(c.state);}else{c.edit(c.state.selected,'replyOpen',null);replyLeave=false;render(c.state);}}
    $('srcNewSearchForm').onsubmit=e=>{e.preventDefault();c.filter({q:$('srcNewSearch').value.trim()});};$('srcNewPart').onchange=e=>c.filter({part:e.target.value});
    root.addEventListener('change',e=>{if(e.target.dataset.quote)c.quote(c.state.selected,Number(e.target.dataset.quote));if(e.target.dataset.supplier){const d=c.draft(c.state.selected),id=Number(e.target.dataset.supplier);c.edit(c.state.selected,'suppliers',e.target.checked?[...new Set([...d.suppliers,id])]:d.suppliers.filter(x=>x!==id));}});
    root.addEventListener('input',e=>{if(e.target.dataset.reply){const d=c.draft(c.state.selected);d.replies[e.target.dataset.reply][e.target.dataset.field]=e.target.value;c.edit(c.state.selected,'replies',d.replies);}});
    root.addEventListener('click',e=>{
      const b=e.target.closest('button');if(!b||b.disabled)return;
      const code=Number(b.dataset.code)||c.state.selected,action=b.dataset.action;
      if(b.dataset.write)c.write(b.dataset.write,code,Number(b.dataset.arg));
      else if(action==='select'){rememberList();c.select(code);root.scrollTop=0;if(w.innerWidth<=760)w.scrollTo(0,0);$('srcNewTask').querySelector('h1')?.focus({preventScroll:true});}
      else if(action==='back')toList();
      else if(action==='reload')c.load();
      else if(action==='page')c.filter({page:Number(b.dataset.page)});
      else if(action==='stage'){stage=b.dataset.stage;render(c.state);$('srcNewTask').querySelector('h2')?.focus?.({preventScroll:true});}
      else if(action==='reply-toggle'){replyLeave=false;c.edit(code,'replyOpen',Number(b.dataset.arg));render(c.state);}
      else if(action==='reply-close')closeReply();
      else if(action==='reply-keep'){replyLeave=false;render(c.state);}
      else if(action==='reply-discard'){const d=c.draft(code),q=c.record(code).item?.quotes?.find(q=>q.quote_id===d.replyOpen);if(q){d.replies[q.quote_id]={price:q.price==null?'':String(q.price),memo:q.memo||''};c.edit(code,'replies',d.replies);}c.edit(code,'replyOpen',null);replyLeave=false;render(c.state);}
      else if(action==='accept')c.acceptRead(code);
    });
    function rememberList(){listScroll={root:root.scrollTop,window:w.scrollY};}root.addEventListener('scroll',()=>{if(c.state.selected===null)rememberList();});function toList(){const scroll=listScroll;c.back();root.scrollTop=scroll.root;w.scrollTo(0,scroll.window);$('srcNewSearch').focus({preventScroll:true});}root.addEventListener('keydown',e=>{if(e.key==='Escape'&&c.state.selected!==null&&!$('srcNewReplyDialog')?.open){toList();}});
    w.addEventListener('beforeunload',e=>{if(c.state.busy||replyIsDirty()){e.preventDefault();e.returnValue='';}});
    w.sourcingNewController=c;render(c.state);w.Admin2Shell?.meReady?.then(()=>c.permission(w.Admin2Shell.canWrite('operator')));c.meta();c.load();
  }

return {createController,integer,validResult,mount,JOURNAL,uiStage,replyEdited};
});
