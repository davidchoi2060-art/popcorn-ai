(function(root,factory){'use strict';var lib=factory();if(typeof module==='object'&&module.exports)module.exports=lib;else{root.SalePriceNew=lib;lib.mount(root);}})(typeof window==='undefined'?globalThis:window,function(){
  'use strict';
  function savedBlockers(state){
    var blockers=[];
    state.records.forEach(function(r,code){
      if(r.unresolved||r.phase==='writing'||r.phase==='refreshing'||r.phase==='refresh_failed')
        blockers.push({code:code,phase:r.unresolved?'uncertain':r.phase});
    });
    return blockers;
  }
  function restoreBlockers(controller,blockers){
    blockers.forEach(function(x){
      if(!Number.isSafeInteger(x.code))return;
      var r=controller.record(x.code);
      if(x.phase==='writing'||x.phase==='uncertain'){
        r.phase='uncertain';r.unresolved=true;r.note='처리 결과 미확인';
      }else if(x.phase==='refresh_failed'||x.phase==='refreshing')r.phase='refresh_failed';
    });
  }
  // Client state only. This does not supply a server expected/version contract.
  function createController(io,changed){
    var s={summary:null,summaryError:'',summaryLoading:false,selected:null,generation:0,summaryGeneration:0,records:new Map(),pending:null,canWrite:false,filter:'all',query:'',armed:null};
    var armTimer=null;function disarm(){clearTimeout(armTimer);armTimer=null;s.armed=null;}function emit(){changed(s);}
    function record(code){if(!s.records.has(code))s.records.set(code,{detail:null,loading:false,error:'',phase:'ready',note:'',unresolved:false,permission:false,readGeneration:0});return s.records.get(code);}
    async function summary(){var g=++s.summaryGeneration;s.summaryLoading=true;s.summaryError='';emit();try{var data=await io.get('/api/admin/sale-price/summary');if(g!==s.summaryGeneration)return;s.summary=data;}catch(e){if(g===s.summaryGeneration)s.summaryError=e.message||'목록 조회 실패';}finally{if(g===s.summaryGeneration){s.summaryLoading=false;emit();}}}
    async function read(code){var r=record(code),generation=s.generation,g=++r.readGeneration;r.loading=true;r.error='';disarm();emit();try{var d=await io.get('/api/admin/sale-price/'+code);if(g!==r.readGeneration||generation!==s.generation||s.selected!==code)return;r.detail=d;r.error='';if(r.phase==='refreshing'||r.phase==='refresh_failed'){r.phase='ready';r.note='저장 완료 · 최신 상태 확인';}if(r.phase==='read_failed'||r.phase==='conflict')r.phase='ready';}catch(e){if(g!==r.readGeneration||generation!==s.generation||s.selected!==code)return;r.error=e.message||'상세 조회 실패';if(r.phase==='refreshing'||r.phase==='refresh_failed')r.phase='refresh_failed';else if(!r.unresolved&&r.phase!=='writing'){if(e.status===401||e.status===403){r.permission=true;r.phase='permission';r.note='권한 오류 · 로그인 및 운영자 권한을 확인하세요.';}else r.phase='read_failed';}}finally{if(g===r.readGeneration){r.loading=false;emit();}}}
    function select(code){s.generation++;s.selected=Number(code);disarm();emit();return read(s.selected);}
    function back(){s.generation++;s.selected=null;disarm();emit();}
    function allowed(r){return s.canWrite&&!s.pending&&r&&r.detail&&!r.loading&&!r.error&&!r.unresolved&&!r.permission&&r.phase==='ready';}
    async function write(action){var code=s.selected,r=record(code);if(!allowed(r))return false;var d=r.detail;if(action==='match'&&!d.mall.known)return false;if(action==='lock'&&d.locked)return false;
      if(action==='match'&&d.locked&&s.armed!==code){s.armed=code;armTimer=setTimeout(function(){s.armed=null;emit();},4000);if(armTimer.unref)armTimer.unref();emit();return false;}
      disarm();s.pending={code:code,action:action};r.phase='writing';r.note='저장 중';r.readGeneration++;emit();
      try{var result=await io.post('/api/admin/sale-price/'+code+'/'+action,action==='match'?{mall_price:d.mall.price}:{});r.phase='refreshing';r.note=result.note||'저장 완료';s.pending=null;emit();summary();if(s.selected===code)await read(code);}
      catch(e){s.pending=null;s.armed=null;if(!e.status||e.status>=500||e.uncertain){r.unresolved=true;r.phase='uncertain';r.note='처리 결과 미확인 · 자동 재시도하지 않습니다.';}else if(e.status===401||e.status===403){r.permission=true;r.phase='permission';r.note='권한 오류 · 로그인 및 운영자 권한을 확인하세요.';}else if(e.status===409){r.phase='conflict';r.error='최신 상태를 다시 확인하세요.';r.note=e.message;}else{r.phase='read_failed';r.error=e.message;r.note='요청이 거절되었습니다. 최신 상태를 확인하세요.';}emit();}
      return true;
    }
    return {state:s,summary:summary,select:select,back:back,read:function(){return s.selected===null?Promise.resolve():read(s.selected);},write:write,allowed:allowed,record:record,permission:function(value){s.canWrite=value;emit();},filter:function(value){s.filter=value;emit();},search:function(value){s.query=value;emit();}};
  }
  function mount(w){var doc=w.document;if(!doc||!doc.getElementById('saleNew'))return;var $=function(id){return doc.getElementById(id);};
    function esc(v){return String(v==null?'':v).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
    function name(v){return w.Admin2Text?w.Admin2Text.stripHtml(v):String(v||'').replace(/<[^>]*>/g,'');}
    function won(v){return v==null?'값 없음':Number(v).toLocaleString('ko-KR')+'원';}
    function date(v){if(!v)return '시각 미확인';var d=new Date(v);return isNaN(d)?'시각 미확인':d.toLocaleString('ko-KR',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});}
    function age(v){if(!v)return '관측 시각 미확인';var t=new Date(v).getTime();return Number.isFinite(t)?'관측 '+Math.max(0,Math.floor((Date.now()-t)/86400000))+'일 전':'관측 시각 미확인';}
    async function request(url,payload){var write=payload!==undefined,res;try{res=await w.fetch(url,{credentials:'same-origin',method:write?'POST':'GET',headers:write?{'Content-Type':'application/json'}:undefined,body:write?JSON.stringify(payload):undefined});}catch(e){throw e;}var data;try{data=await res.json();}catch(e){var invalid=new Error(write?'처리 응답을 확인하지 못했습니다.':'조회 응답 형식 오류');invalid.status=res.status;invalid.uncertain=write&&res.ok;throw invalid;}if(!res.ok){var error=new Error(typeof data.detail==='string'?data.detail:'요청 오류 '+res.status);error.status=res.status;throw error;}if(!data||typeof data!=='object'||(write&&data.ok!==true)||(!write&&url.endsWith('/summary')&&(!Array.isArray(data.queue)||!data.kpi||!data.kpi.alert||!data.kpi.locked||!data.kpi.unknown||!data.trust))||(!write&&!url.endsWith('/summary')&&(!data.mall||data.product_code!==Number(url.split('/').pop())||!Object.prototype.hasOwnProperty.call(data,'sale_price')||(data.sale_price!==null&&!Number.isInteger(data.sale_price))||typeof data.mall.known!=='boolean'||(data.mall.known&&!Number.isInteger(data.mall.price))||!Array.isArray(data.history)))){var err=new Error('응답 내용을 확인하지 못했습니다.');err.uncertain=write;throw err;}return data;}
    var c=createController({get:request,post:request},render);
    // Preserve unresolved writes across same-tab reloads; GET cannot settle POST ambiguity.
    try{restoreBlockers(c,JSON.parse(w.sessionStorage.getItem('sale-price-new-blockers')||'[]'));}catch(ignore){}

    function statusHtml(r){
      var phase=r.phase,title='',note='';
      if(phase==='writing')title='저장 중';
      else if(phase==='refreshing')title='저장 완료 · 최신 조회 중';
      else if(phase==='refresh_failed')title='저장 완료 · 최신 상태 조회 실패';
      else if(phase==='uncertain'){title='처리 결과 미확인';note='조회만으로 저장 성공을 판정하지 않습니다. 처리 근거 확인 전 추가 변경이 차단됩니다.';}
      else if(phase==='permission'){title='권한 오류';note='로그인 및 운영자 권한을 확인하세요.';}
      else if(phase==='conflict'){title='확인한 값이 변경됨';note='최신 상태를 다시 확인하세요.';}
      else if(r.error){title='상세 조회 실패';note=r.error;}
      else if(r.loading)title='최신 상태 조회 중';
      else if(r.note)title=r.note;
      if(!title)return '';
      var stale=r.detail&&(r.loading||r.error||phase!=='ready'||r.unresolved);
      return '<div class="sn-message sn-state-head '+(phase==='ready'&&!r.error?'success':phase==='writing'||phase==='refreshing'?'':'error')+'" role="status" aria-live="polite"><div><strong>'+esc(title)+'</strong>'+(stale?'<p>이전 조회값 · 최신 확인 필요</p>':'')+(note?'<p>'+esc(note)+'</p>':'')+'</div>'+(phase!=='writing'?'<button type="button" class="sn-btn" data-read '+(r.loading?'disabled':'')+'>다시 조회</button>':'')+'</div>';
    }
    function render(s){try{w.sessionStorage.setItem('sale-price-new-blockers',JSON.stringify(savedBlockers(s)));}catch(ignore){}$('saleNew').dataset.selected=String(s.selected!==null);$('snListStatus').textContent=s.summaryError||(s.summaryLoading?'목록 조회 중':'');var data=s.summary;
      if(data){var k=data.kpi;var tabs=[['all','전체 예외',data.queue.length],['alert','가격 차이',k.alert.value],['unknown','관측 미확인',k.unknown.value],['locked','잠금 예외',k.locked.value]];$('snFilters').innerHTML=tabs.map(function(t){return '<button type="button" class="sn-filter" data-filter="'+t[0]+'" aria-pressed="'+(s.filter===t[0])+'">'+t[1]+' '+esc(t[2])+'</button>';}).join('');var q=data.queue.filter(function(x){return (s.filter==='all'||x.kind===s.filter)&&(!s.query||(name(x.name)+' '+x.product_code).toLowerCase().includes(s.query.toLowerCase()));});$('snCount').textContent=q.length+'개 상품 · 차이 큰 순';$('snSample').textContent=data.trust.sample_note;$('snQueue').innerHTML=q.map(function(x){return '<button type="button" class="sn-card" data-code="'+x.product_code+'" aria-current="'+(s.selected===x.product_code)+'"><span class="sn-thumb">이미지 없음</span><span class="sn-card-body"><strong>'+esc(name(x.name))+'</strong><span class="sn-meta">상품코드 '+x.product_code+'</span><div class="sn-card-price">현재 판매가 <b>'+won(x.sale_price)+'</b></div><span class="sn-card-tags"><span class="sn-tag '+(x.locked||x.kind==='locked'?'lock':'diff')+'">'+esc(x.kind_label)+(x.diff!=null?' '+esc(x.diff_display):'')+'</span><span class="sn-tag">'+esc(age(x.observed_at))+'</span></span></span></button>';}).join('')||'<p class="sn-empty">조건에 맞는 예외 상품이 없습니다.</p>';}
      if(s.selected===null)return;var r=c.record(s.selected),d=r.detail;
      if(!d){$('snDetail').innerHTML=statusHtml(r)+'<h2>상품코드 '+s.selected+'</h2>';return;}
      var blocked=!c.allowed(r),known=d.mall.known,delta=known&&d.sale_price!=null?d.mall.price-d.sale_price:null;
      var matchLabel=s.armed===s.selected?'다시 누르면 잠금 해제 후 맞춥니다':'관측값으로 맞추기'+(d.locked?' · 잠금 해제':'');
      $('snDetail').innerHTML=statusHtml(r)+'<div class="sn-product"><div class="sn-thumb">이미지 없음</div><div class="sn-product-name"><h2 tabindex="-1">'+esc(name(d.name))+'</h2><p class="sn-meta">상품코드 '+d.product_code+' · '+esc(d.cat)+' · '+esc(d.data_origin_label)+'</p><span class="sn-tag '+(d.locked?'lock':'')+'">'+(d.locked?'판매가 잠김':'판매가 잠금 해제')+'</span><span class="sn-tag">'+esc(age(d.mall.observed_at))+'</span></div></div>'+
        '<div class="sn-prices"><article class="sn-price"><b>현재 판매가</b><strong>'+won(d.sale_price)+'</strong><p>상품에 저장된 값</p></article><article class="sn-price"><b>인계 시점 관측값</b><strong>'+(known?won(d.mall.price):'관측 미확인')+'</strong><p>인계 시점의 값</p></article><article class="sn-price difference"><b>차이</b><strong>'+(delta==null?'계산 불가':(delta>0?'+':'')+won(delta))+'</strong><p>'+(delta==null?'양쪽 가격 확인이 필요합니다.':delta>0?'관측값이 더 높습니다.':delta<0?'관측값이 더 낮습니다.':'가격이 같습니다.')+'</p></article></div><div class="sn-source"><div><b>관측 출처</b><br>'+esc(d.mall.handoff_no||'인계 기록 없음')+' · '+esc(date(d.mall.observed_at))+'</div><p>인계 저장 시점 기준 · 현재 몰 가격과 다를 수 있습니다. 8일·30일은 표시 기준입니다.</p></div>'+
        '<section class="sn-section"><h3>적용 전 확인</h3><p>맞추기: 아래 변화 적용 · 잠그기: 현재 값 유지</p><div class="sn-confirm"><div><b>가격</b><span>'+won(d.sale_price)+' → '+(known?won(d.mall.price):'관측 미확인')+'</span></div><div><b>잠금</b><span>'+(d.locked?'잠김 → 맞추면 해제':'해제 상태 유지')+'</span></div></div>'+(d.locked&&known?'<div class="sn-warning">맞추면 잠금이 풀립니다. 이후 자동 가격 경로가 값을 변경할 수 있습니다.</div>':'')+
        (!s.canWrite?'<p>운영자 권한 확인 후 변경할 수 있습니다.</p>':'')+'<div class="sn-actions"><button type="button" class="sn-btn sn-primary" data-write="match" '+(blocked||!known?'disabled':'')+'>'+matchLabel+'</button><button type="button" class="sn-btn" data-write="lock" '+(blocked||d.locked?'disabled':'')+'>'+(d.locked?'이미 잠긴 상태':'현재 판매가 잠그기')+'</button></div></section>'+
        '<section class="sn-section"><h3>가격 변경 이력</h3><p>잠금만 바뀐 활동은 가격 변경 이력과 별도입니다.</p><div class="sn-table-wrap"><table class="sn-table"><thead><tr><th>변경일</th><th>변경 전</th><th>변경 후</th><th>사유</th></tr></thead><tbody>'+((d.history||[]).map(function(h){return '<tr><td>'+esc(date(h.at))+'</td><td>'+won(h.old)+'</td><td>'+won(h.new)+'</td><td>'+esc(h.reason_label)+'</td></tr>';}).join('')||'<tr><td colspan="4">가격 변경 이력이 없습니다.</td></tr>')+'</tbody></table></div></section>';
    }
    $('snSearch').addEventListener('input',function(e){c.search(e.target.value);});$('snReload').onclick=c.summary;$('snBack').onclick=c.back;
    $('saleNew').addEventListener('click',function(e){var b=e.target.closest('button');if(!b||b.disabled)return;if(b.dataset.code){var code=Number(b.dataset.code);c.select(code).then(function(){if(c.state.selected===code){var heading=doc.querySelector("#snDetail h2");if(heading)heading.focus({preventScroll:true});}});}if(b.dataset.filter){c.filter(b.dataset.filter);var next=doc.querySelector('[data-filter="'+b.dataset.filter+'"]');if(next)next.focus();}if(b.hasAttribute('data-read'))c.read();if(b.dataset.write){c.write(b.dataset.write);var btn=doc.querySelector('[data-write="'+b.dataset.write+'"]');if(btn&&!btn.disabled)btn.focus();}});
    $('saleNew').addEventListener('keydown',function(e){if(e.key==='Escape'){c.back();$('snSearch').focus();}});
    if(w.Admin2Shell&&w.Admin2Shell.meReady)w.Admin2Shell.meReady.then(function(){c.permission(w.Admin2Shell.canWrite('operator'));});c.summary();w.salePriceController=c;
  }
  return {createController:createController,savedBlockers:savedBlockers,restoreBlockers:restoreBlockers,mount:mount};
});
