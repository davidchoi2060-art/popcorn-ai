(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const states = {none:'미연결',requested:'요청 기록',mapped:'연결 ID 기록'};
  const viaLabels = {email:'이메일',kakao:'카카오',naver:'네이버',google:'구글'};
  const viaLabel = raw => viaLabels[raw] || '미분류 · ' + (raw || '빈값');
  const statusLabel = raw => raw === 'active' ? '이용 가능' : (raw || '상태 미확인') + ' · 이용 불가';
  const fmt = (value, short=false) => value ? (short ? PT.short(value) : PT.full(value)) : '기록 없음';
  const pill = (m, includeVia=false) => `<span class="mm-pill ${esc(m.map_state)}">${esc(states[m.map_state] || '상태 미확인')}${includeVia&&m.via_code!=='email'?' · '+esc(viaLabel(m.via_code)):''}</span>`;
  const url = new URL(location.href);
  const state = {items:[],total:0,page:1,size:20,sort:'joined_desc',q:'',via:null,status:null,map:'',
                 selected:null,member:null,mode:null,notes:{},ready:false,detailReady:false,busy:false,
                 operator:null,listSeq:0,detailSeq:0,undo:null,listMessage:'',detailMessage:'',view:'list',filtersOpen:false,listScroll:{page:0,panel:0}};
  let listController, detailController, toastTimer;
  function restore() {
    const p = Number(url.searchParams.get('page'));
    if(Number.isInteger(p) && p > 0 && p <= 10000000) state.page=p;
    const size=Number(url.searchParams.get('page_size')); if([10,20,50].includes(size))state.size=size;
    const sort=url.searchParams.get('sort'); if(['joined_desc','id_asc','activity_desc'].includes(sort))state.sort=sort;
    const map=url.searchParams.get('map_state'); if(['none','requested','mapped'].includes(map))state.map=map;
    for(const key of ['via','status']) if(url.searchParams.has(key)&&url.searchParams.get(key).length<=20)state[key]=url.searchParams.get(key);
    const id=Number(url.searchParams.get('member')); if(Number.isSafeInteger(id)&&id>0){state.selected=id;state.view='detail';}
    $('pageSize').value=String(state.size);$('sort').value=state.sort;$('map').value=state.map;
  }
  function persist() {
    const next=new URL(location.href);next.searchParams.delete('q');next.searchParams.set('admin','new');
    for(const [k,v] of [['page',state.page],['page_size',state.size],['sort',state.sort],['map_state',state.map],['via',state.via],['status',state.status],['member',state.selected]]){
      const absent=(k==='via'||k==='status')?v===null:(v===null||v==='');
      if(absent)next.searchParams.delete(k);else next.searchParams.set(k,String(v));
    }
    history.replaceState(null,'',next);
  }
  const mobile = () => matchMedia('(max-width:1000px)').matches;
  function originLabel(raw) {
    if(typeof raw!=='string'||!raw.trim())return '미확인';
    return raw==='real'?'일반(real)':raw==='demo'?'데모(demo)':'기타('+raw+')';
  }
  function originNote(raw) {
    if(raw==='real')return mobile()?'기본 분류 · 고객 확인과 별도입니다.':'기본 저장 분류이며 실제 고객 확인을 뜻하지 않습니다.';
    if(raw==='demo')return 'DB에 저장된 데모 분류입니다. 실제 고객 확인과 별도입니다.';
    return typeof raw!=='string'||!raw.trim()?'저장 분류 기록이 없습니다. 실제 고객 여부는 미확인입니다.':'DB에 저장된 원문 분류입니다. 실제 고객 확인과 별도입니다.';
  }
  function statusHTML(m) {return '<span class="mm-status '+(m.status==='active'?'active':'inactive')+'"><span class="mm-dot" aria-hidden="true"></span>'+esc(statusLabel(m.status))+'</span>';}
  function syncFilters() {
    $('filterFields').hidden=mobile()&&!state.filtersOpen;
    $('filterToggle').setAttribute('aria-expanded',String(!mobile()||state.filtersOpen));
    const count=[state.via!==null,state.status!==null,!!state.map].filter(Boolean).length;
    $('filterLabel').textContent=state.filtersOpen?'필터 접기':'필터 · '+(count?count+'개 적용':'전체');
  }
  function applyView() {$('membersWorkspace').dataset.view=state.view;syncFilters();}
  function backToList() {
    if(state.busy)return;
    state.view='list';applyView();
    requestAnimationFrame(()=>{$('membersWorkspace').scrollTop=state.listScroll.panel;window.scrollTo({top:state.listScroll.page,behavior:'auto'});$('rows').querySelector('[data-member="'+state.selected+'"]')?.focus({preventScroll:true});});
  }
  function bindBack() {$('detail').querySelectorAll('[data-back]').forEach(button=>button.onclick=backToList);}
  function canWrite() { return !!state.operator && ['operator','owner'].includes(state.operator.role); }
  function toast(msg) {$('toast').textContent=msg;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,6500);}
  function pageMessage(msg) {$('pageMessage').textContent=msg||'';$('pageMessage').hidden=!msg;}
  function reason(e) {
    if(e.status===401)return '세션 만료 또는 로그인 필요 · 다시 로그인 후 새로고침';
    if(e.status===403)return '권한 부족 · 현재 권한으로 처리 불가';
    if(e.status===404)return '회원 없음 · 목록을 다시 확인해 주세요';
    if(!e.status)return '네트워크 또는 응답 데이터 확인 실패';
    return e.message || '네트워크 응답 확인 불가';
  }
  async function request(path, options={}) {
    const response=await fetch(path,{credentials:'same-origin',...options});
    let data;try{data=await response.json();}catch{throw Object.assign(new Error('응답 형식 확인 실패'),{status:response.status});}
    if(!response.ok){const detail=data.detail;throw Object.assign(new Error(typeof detail==='string'?detail:'요청 처리 실패'),{status:response.status});}
    return data;
  }
  function modeText() {
    $('memberMode').textContent=state.mode==='own'?'자체 가입 모드':state.mode==='mall'?'쇼핑몰 회원 연동 모드':state.mode?'회원 모드 · '+state.mode:'운영 모드 확인 불가';
    $('modeNote').textContent=state.mode==='own'?'미연결도 자체 이용 가능':'요청 기록과 외부 계정 검증은 별도';
  }
  function options(id, values, current, label, all) {
    $(id).innerHTML=`<option value="">${all}</option>`+values.map(v=>`<option value="${esc(JSON.stringify(v))}">${esc(label(v))}</option>`).join('');
    if(current!==null){if(!values.includes(current))$(id).insertAdjacentHTML('beforeend',`<option value="${esc(JSON.stringify(current))}">${esc(label(current))}</option>`);$(id).value=JSON.stringify(current);}
  }
  function renderList(message=null) {
    if(message!==null)state.listMessage=message;
    const ready=state.ready;
    $('resultCount').textContent=ready?'검색 결과 '+state.total+'명':'회원 목록 조회 상태';
    $('rows').innerHTML=ready?state.items.map(m=>'<li data-id="'+m.id+'"><button class="mm-row-button" type="button" data-member="'+m.id+'" aria-current="'+(m.id===state.selected)+'" aria-label="'+esc((m.name||'이름 없음')+' · 회원번호 '+m.id+' 상세')+'"><span class="mm-row-main"><span class="mm-row-heading"><span class="mm-member-id">#'+m.id+'</span><span class="mm-member-name">'+esc(m.name||'이름 없음')+'</span></span><span class="mm-member-email">'+esc(m.email||'이메일 없음')+'</span><span class="mm-row-states">'+statusHTML(m)+'<span class="mm-origin">'+esc(originLabel(m.data_origin))+'</span>'+pill(m,true)+'</span></span><img class="mm-row-chevron" src="/shared/icons/admin/chevron-right.svg" alt=""></button></li>').join(''):'';
    $('listMessage').hidden=ready&&state.items.length>0;
    $('listMessage').textContent=ready?(state.total?'이 페이지의 회원 없음':'검색 결과 없음 · 검색어 또는 필터 조정'):state.listMessage||'회원 목록 조회 중';
    $('pageRange').textContent=ready?(state.total?'전체 '+state.total+'명 중 '+((state.page-1)*state.size+1)+'–'+((state.page-1)*state.size+state.items.length)+'명':'검색 결과 0명'):'건수 확인 불가';
    const pages=Math.max(1,Math.ceil(state.total/state.size));
    $('pageLabel').textContent=ready?state.page+' / '+pages:'—';
    $('prev').disabled=!ready||state.busy||state.page===1;$('next').disabled=!ready||state.busy||state.page>=pages;
    $('rows').querySelectorAll('[data-member]').forEach(button=>{
      button.disabled=state.busy;
      button.onclick=()=>{
        if(state.busy)return;
        state.listScroll={page:window.scrollY,panel:$('membersWorkspace').scrollTop};
        state.selected=Number(button.dataset.member);state.view='detail';applyView();persist();renderList();
        if(mobile()){$('membersWorkspace').scrollTop=0;window.scrollTo({top:0,behavior:'auto'});}
        loadDetail().then(ok=>{if(ok)$('detail').querySelector('h2')?.focus({preventScroll:true});});
      };
    });
    syncFilters();
  }
  function renderDetail(message=null) {
    if(message!==null)state.detailMessage=message;
    const m=state.member;
    const back='<button class="mm-btn mm-back" type="button" data-back '+(state.busy?'disabled':'')+'><img class="mm-icon mm-back-icon" src="/shared/icons/admin/chevron-right.svg" alt="">목록으로</button>';
    if(!m||!state.detailReady){
      $('detail').innerHTML=back+'<div class="mm-empty"><p>'+esc(state.detailMessage||(state.selected?'회원 상세 조회 중':'회원 선택 후 상세 확인'))+'</p>'+(state.detailMessage&&state.selected?'<button type="button" class="mm-btn mm-detail-retry" id="detailRetry">상세 다시 조회</button>':'')+'</div>';
      bindBack();if($('detailRetry'))$('detailRetry').onclick=()=>loadDetail();return;
    }
    let connection='';
    if(m.map_state==='requested')connection='<p><strong>연결 요청 기록 '+esc(fmt(m.requested_at))+'</strong></p><p>외부 전달 여부와 실제 계정 연결은 별도 확인이 필요합니다.</p>';
    if(m.map_state==='mapped')connection='<p><strong>연결 ID '+esc(m.mall_id)+'</strong></p><p>DB에 연결 ID가 기록되어 있습니다. 실제 쇼핑몰 계정 검증·동기화 여부는 미확인입니다.</p>';
    const mode=state.mode==='own'?'자체 가입 모드 · 미연결도 이용 가능':'요청 기록과 실제 외부 계정 검증은 별도입니다.';
    const ownUndo=state.undo&&state.undo.member===m.id&&state.undo.requested_at===m.requested_at&&m.map_state==='requested';
    const allowed=canWrite(),blocked=state.busy||!state.ready||!allowed;
    const base=[['회원번호','#'+m.id],['이메일',m.email||'이메일 없음'],['가입 경로',viaLabel(m.via_code)+' · 저장값 기준'],['가입 시각',fmt(m.joined)],['마지막 로그인',fmt(m.last_login_at)],['방문자 연결',m.visitor_linked?'연결 있음 · 회원번호와 다른 식별자':'연결 기록 없음']];
    const metrics=[['자체 주문 기록',m.orders],['회원 귀속 상담',m.consults],['후기 기록',m.reviews],['관심 부품',m.favs],['가격 알림 설정',m.alerts]];
    const scopes=['via','consults','orders','reviews','alerts','last'].map(key=>state.notes[key]).filter(Boolean);
    const scopeDetails='<details class="mm-scopes"><summary>집계 기준 보기</summary><ul>'+scopes.map(v=>'<li>'+esc(v)+'</li>').join('')+'</ul></details>';
    $('detail').innerHTML=back+
      '<div class="mm-profile-banner"><header class="mm-profile-head"><div class="mm-profile-identity"><span class="mm-profile-id">#'+m.id+'</span><div><span class="mm-eyebrow">선택한 회원 · #'+m.id+'</span><h2 tabindex="-1">'+esc(m.name||'이름 없음')+'</h2><p class="mm-email">'+esc(m.email||'이메일 없음')+'</p></div></div><p class="mm-selected-note">회원이 선택되었습니다.<br>다른 회원을 선택하면 정보가 변경됩니다.</p></header><div class="mm-judgement"><section><h3>회원 상태</h3><div class="mm-status-value">'+statusHTML(m)+'</div><p>'+esc(m.status==='active'?'현재 계정으로 정상 이용할 수 있습니다.':'현재 계정 상태로 이용이 제한됩니다.')+'</p></section><section><h3>저장 분류</h3><div class="mm-origin-value">'+esc(originLabel(m.data_origin))+'</div><p>'+esc(originNote(m.data_origin))+'</p></section></div></div>'+
      '<div class="mm-profile-body"><section class="mm-records"><h3>회원 기본 기록</h3><dl class="mm-definition">'+base.map(([k,v])=>'<dt>'+k+'</dt><dd>'+esc(v)+'</dd>').join('')+'</dl><p class="mm-callout">'+esc('가입 경로는 저장값 · OAuth 인증 증거와 별도입니다.')+'</p></section>'+
      '<section class="mm-connection"><div class="mm-connection-row"><h3>쇼핑몰 연결</h3>'+pill(m)+'</div><div class="mm-connection-description">'+connection+'<p>'+mode+'</p></div><p class="mm-callout mm-delivery-note">요청 기록은 DB 저장 · 외부 전달 미확인</p><div class="mm-detail-action">'+(m.map_state==='none'?'<button class="mm-btn mm-primary" type="button" id="requestBtn" '+(blocked?'disabled':'')+'>연결 요청 기록</button>':'')+(ownUndo?'<button class="mm-btn" type="button" id="undoBtn" '+(blocked?'disabled':'')+'>이번 요청 되돌리기</button>':'')+'</div>'+(!allowed?'<p class="mm-muted mm-permission">조회 권한 · 요청 기록과 되돌리기 권한 없음</p>':'')+'</section></div>'+
      '<section class="mm-ledger"><div class="mm-ledger-counts"><div class="mm-ledger-head"><h3>원장 기록 수</h3><p>실구매·발송 성공 수와 별도입니다.</p></div><div class="mm-metrics">'+metrics.map(([k,v])=>'<div class="mm-metric"><span>'+k+'</span><b>'+esc(v)+'</b></div>').join('')+'</div></div><div class="mm-recent-record"><div class="mm-recent"><h3>최근 기록</h3><span class="mm-recent-value">'+esc(fmt(m.last))+'</span></div><p class="mm-recent-note">'+esc(state.notes.last||'')+'</p></div>'+scopeDetails+'</section>'+back;
    bindBack();
    if($('requestBtn'))$('requestBtn').onclick=()=>{if(blocked)return;$('confirmTitle').textContent=(m.name||'이름 없음')+' · #'+m.id+' 요청 기록';$('confirmMode').textContent=$('memberMode').textContent;$('confirm').showModal();};
    if($('undoBtn'))$('undoBtn').onclick=()=>write('undo');
  }
  async function loadDetail() {
    const seq=++state.detailSeq;detailController?.abort();detailController=new AbortController();
    state.detailReady=false;state.member=null;state.detailMessage='';renderDetail();
    if(!state.selected)return true;
    const id=state.selected;
    try{const data=await request(`/api/admin/members/${id}`,{signal:detailController.signal});
      if(seq!==state.detailSeq||id!==state.selected)return false;
      state.member=data.member;state.mode=data.member_mode;state.notes=data.metric_notes;state.detailReady=true;modeText();renderDetail();return true;
    }catch(e){if(e.name==='AbortError'||seq!==state.detailSeq)return false;renderDetail(reason(e));return false;}
  }
  async function loadList(keepSelection=true, correcting=false) {
    const seq=++state.listSeq;listController?.abort();listController=new AbortController();
    detailController?.abort();++state.detailSeq;state.ready=false;state.detailReady=false;state.listMessage='';state.detailMessage='';state.mode=null;modeText();renderList();renderDetail();
    const params=new URLSearchParams({q:state.q,page:String(state.page),page_size:String(state.size),sort:state.sort,map_state:state.map});
    for(const key of ['via','status'])if(state[key]!==null)params.set(key,state[key]);
    try{const data=await request('/api/admin/members/search?'+params,{signal:listController.signal});
      if(seq!==state.listSeq)return false;
      if(data.total>0&&state.page>Math.ceil(data.total/state.size)&&!correcting){state.page=Math.ceil(data.total/state.size);persist();return loadList(keepSelection,true);}
      state.items=data.items;state.total=data.total;state.mode=data.member_mode;state.ready=true;
      options('via',data.available_filters.via,state.via,viaLabel,'전체 경로');options('status',data.available_filters.status,state.status,statusLabel,'전체 상태');
      if(!keepSelection||state.selected===null)state.selected=state.items[0]?.id??null;
      if(!state.selected){state.view='list';applyView();}
      modeText();persist();renderList();return await loadDetail();
    }catch(e){if(e.name==='AbortError'||seq!==state.listSeq)return false;state.ready=false;state.detailReady=false;renderList(reason(e));renderDetail('목록 조회 실패 · 최신 회원 상태 확인 불가');return false;}
  }
  function busy(value) {
    state.busy=value;
    $('filterForm').querySelectorAll('input,select,button').forEach(el=>el.disabled=value);
    for(const id of ['reload','sort','pageSize','saveRequest'])$(id).disabled=value;
    $('confirm').querySelectorAll('.mm-cancel').forEach(el=>el.disabled=value);
    renderList();renderDetail();
  }
  async function write(kind) {
    if(state.busy||!canWrite()||!state.ready||!state.detailReady)return;
    const id=state.selected, action=state.undo;
    if(kind==='undo'&&(!action||action.member!==id))return;
    busy(true);pageMessage('');let committed=false;
    try{
      const data=await request(kind==='request'?`/api/admin/members/${id}/map-request`:`/api/admin/members/map-request/undo/${action.log}`,{method:'POST'});
      committed=true;
      state.undo=kind==='request'?{member:id,log:data.undo_id,requested_at:data.requested_at}:null;
      if($('confirm').open)$('confirm').close();
      const refreshed=await loadList(true);
      const msg=kind==='request'?'연결 요청 기록 완료 · 실제 발송 여부 미확인':'이번 연결 요청 기록 해제 완료';
      if(!refreshed)pageMessage(msg+' · 저장 성공, 최신 상태 확인 실패 · 새로고침 필요');else toast(msg);
    }catch(e){
      if($('confirm').open)$('confirm').close();
      const msg=e.status?reason(e):'저장 응답 확인 불가 · 처리되었을 수 있으므로 새로고침 후 상태 확인';
      pageMessage((committed?'저장 성공, 후속 확인 실패 · ':'')+msg);
      await loadList(true);
    }finally{busy(false);if(committed&&state.detailReady)$('detail').querySelector('h2')?.focus({preventScroll:true});}
  }
  $('saveRequest').onclick=()=>write('request');
  $('confirm').addEventListener('cancel',e=>{if(state.busy)e.preventDefault();});
  $('filterForm').onsubmit=e=>{e.preventDefault();if(state.busy)return;state.q=$('q').value.trim();state.via=$('via').value?JSON.parse($('via').value):null;state.status=$('status').value?JSON.parse($('status').value):null;state.map=$('map').value;state.page=1;pageMessage('');loadList(false);};
  for(const id of ['via','map','status'])$(id).onchange=()=>$('filterForm').requestSubmit();
  for(const id of ['sort','pageSize'])$(id).onchange=()=>{state.sort=$('sort').value;state.size=Number($('pageSize').value);state.page=1;loadList(false);};
  $('reset').onclick=()=>{if(state.busy)return;state.q='';state.via=null;state.status=null;state.map='';state.page=1;$('q').value='';$('map').value='';pageMessage('');loadList(false);};
  $('prev').onclick=()=>{if(state.busy||state.page===1)return;state.page--;loadList(false);};
  $('next').onclick=()=>{if(state.busy)return;state.page++;loadList(false);};
  $('reload').onclick=()=>{if(state.busy)return;pageMessage('');loadList(true);};
  $('displayTimezone').textContent='표시 시각: '+Intl.DateTimeFormat().resolvedOptions().timeZone;
  $('filterToggle').onclick=()=>{if(state.busy)return;state.filtersOpen=!state.filtersOpen;syncFilters();};
  matchMedia('(max-width:1000px)').addEventListener('change',applyView);
  restore();applyView();
  if(window.Admin2Shell)Admin2Shell.meReady.then(op=>{state.operator=op;renderDetail();});
  loadList(true);
})();
