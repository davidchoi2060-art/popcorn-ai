(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const states = {none:'미연결',requested:'요청 기록',mapped:'연결 완료'};
  const viaLabels = {email:'이메일',kakao:'카카오',naver:'네이버',google:'구글'};
  const viaLabel = raw => viaLabels[raw] || '미분류 · ' + (raw || '빈값');
  const statusLabel = raw => raw === 'active' ? '이용 가능' : (raw || '상태 미확인') + ' · 이용 불가';
  const fmt = (value, short=false) => value ? (short ? PT.short(value) : PT.full(value)) : '기록 없음';
  const pill = m => `<span class="mm-pill ${esc(m.map_state)}">${esc(states[m.map_state] || '상태 미확인')}</span>`;
  const url = new URL(location.href);
  const state = {items:[],total:0,page:1,size:20,sort:'joined_desc',q:'',via:null,status:null,map:'',
                 selected:null,member:null,mode:null,notes:{},ready:false,detailReady:false,busy:false,
                 operator:null,listSeq:0,detailSeq:0,undo:null,listMessage:'',detailMessage:''};
  let listController, detailController, toastTimer;
  function restore() {
    const p = Number(url.searchParams.get('page'));
    if(Number.isInteger(p) && p > 0 && p <= 10000000) state.page=p;
    const size=Number(url.searchParams.get('page_size')); if([10,20,50].includes(size))state.size=size;
    const sort=url.searchParams.get('sort'); if(['joined_desc','id_asc','activity_desc'].includes(sort))state.sort=sort;
    const map=url.searchParams.get('map_state'); if(['none','requested','mapped'].includes(map))state.map=map;
    for(const key of ['via','status']) if(url.searchParams.has(key)&&url.searchParams.get(key).length<=20)state[key]=url.searchParams.get(key);
    const id=Number(url.searchParams.get('member')); if(Number.isSafeInteger(id)&&id>0)state.selected=id;
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
    $('modeNote').textContent=state.mode==='own'?'미연결 회원도 자체 서비스 이용 가능':'요청 기록과 외부 계정 검증은 별도';
  }
  function options(id, values, current, label, all) {
    $(id).innerHTML=`<option value="">${all}</option>`+values.map(v=>`<option value="${esc(JSON.stringify(v))}">${esc(label(v))}</option>`).join('');
    if(current!==null){if(!values.includes(current))$(id).insertAdjacentHTML('beforeend',`<option value="${esc(JSON.stringify(current))}">${esc(label(current))}</option>`);$(id).value=JSON.stringify(current);}
  }
  function renderList(message=null) {
    if(message!==null)state.listMessage=message;
    const ready=state.ready;
    $('resultCount').textContent=ready?`검색 결과 ${state.total}명`:'회원 목록 조회 상태';
    $('rows').innerHTML=ready?state.items.map(m=>`<tr data-id="${m.id}" aria-selected="${m.id===state.selected}"><td><button class="mm-row-button" type="button" data-member="${m.id}"><span class="mm-member-name">${esc(m.name || '이름 없음')}</span><span class="mm-member-meta">#${m.id} · ${esc(statusLabel(m.status))}<br>${esc(m.email || '이메일 없음')}</span></button></td><td>${esc(viaLabel(m.via_code))}</td><td>${pill(m)}</td><td class="mm-num">${m.orders}</td><td>${esc(fmt(m.last,true))}</td></tr>`).join(''):'';
    $('listMessage').hidden=ready&&state.items.length>0;
    $('listMessage').textContent=ready?(state.total?'이 페이지의 회원 없음':'검색 결과 없음 · 검색어 또는 필터 조정'):state.listMessage||'회원 목록 조회 중';
    $('pageRange').textContent=ready?(state.total?`전체 ${state.total}명 중 ${(state.page-1)*state.size+1}–${(state.page-1)*state.size+state.items.length}명`:'검색 결과 0명'):'건수 확인 불가';
    const pages=Math.max(1,Math.ceil(state.total/state.size));
    $('pageLabel').textContent=ready?`${state.page} / ${pages}`:'—';
    $('prev').disabled=!ready||state.busy||state.page===1;$('next').disabled=!ready||state.busy||state.page>=pages;
    $('rows').querySelectorAll('[data-member]').forEach(button=>{button.disabled=state.busy;button.onclick=()=>{if(state.busy)return;state.selected=Number(button.dataset.member);persist();renderList();loadDetail().then(ok=>{if(ok&&innerWidth<=1000)$('detail').scrollIntoView({block:'start',behavior:'smooth'});});};});
  }
  function renderDetail(message=null) {
    if(message!==null)state.detailMessage=message;
    const m=state.member;
    if(!m||!state.detailReady){$('detail').innerHTML=`<div class="mm-empty">${esc(state.detailMessage || (state.selected?'회원 상세 조회 중':'회원 선택 후 상세 확인'))}${state.detailMessage&&state.selected?'<br><button type="button" class="mm-btn mm-detail-retry" id="detailRetry">상세 다시 조회</button>':''}</div>`;if($('detailRetry'))$('detailRetry').onclick=()=>loadDetail();return;}
    let connection='연결 요청 기록 없음<br>자체 가입 모드에서 미연결은 처리 필수 상태가 아님';
    if(m.map_state==='requested')connection=`<strong>연결 요청 기록 ${esc(fmt(m.requested_at))}</strong><br>외부 전달 여부 미확인 · 이메일 발송 증거 없음<br>고객 동의 API 존재 · 현행 고객 안내 진입 경로 미확인`;
    if(m.map_state==='mapped')connection=`<strong>연결 ID ${esc(m.mall_id)}</strong><br>DB 원장에 연결 ID 존재<br>실제 쇼핑몰 계정 검증·동기화 정보 없음`;
    const ownUndo=state.undo&&state.undo.member===m.id&&state.undo.requested_at===m.requested_at&&m.map_state==='requested';
    const allowed=canWrite(), blocked=state.busy||!state.ready||!allowed;
    $('detail').innerHTML=`<button class="mm-btn mm-back" type="button" id="backToList">목록으로</button><div class="mm-detail-top"><div><span class="mm-eyebrow">선택한 회원 · #${m.id}</span><h2 tabindex="-1">${esc(m.name || '이름 없음')}</h2></div><span class="mm-pill">${esc(statusLabel(m.status))}</span></div><p class="mm-email">${esc(m.email || '이메일 없음')}</p><dl class="mm-definition"><dt>가입 경로</dt><dd>${esc(viaLabel(m.via_code))} · 저장값 기준</dd><dt>가입 시각</dt><dd>${esc(fmt(m.joined))}</dd><dt>마지막 로그인</dt><dd>${esc(fmt(m.last_login_at))}</dd><dt>방문자 연결</dt><dd>${m.visitor_linked?'연결 있음 · 회원번호와 다른 식별자':'연결 기록 없음'}</dd></dl><section class="mm-detail-section"><div class="mm-connection-row"><h3>쇼핑몰 계정 연결</h3>${pill(m)}</div><div class="mm-callout">${connection}</div><div class="mm-detail-action">${m.map_state==='none'?`<button class="mm-btn mm-primary" type="button" id="requestBtn" ${blocked?'disabled':''}>연결 요청 기록</button>`:''}${ownUndo?`<button class="mm-btn" type="button" id="undoBtn" ${blocked?'disabled':''}>이번 요청 되돌리기</button>`:''}</div>${!allowed?'<p class="mm-muted">조회 권한 · 요청 기록과 되돌리기 권한 없음</p>':''}</section><section class="mm-detail-section"><h3>실제 기록 지표 <span class="mm-muted">원장별 집계</span></h3><div class="mm-metrics">${[['자체 주문 기록',m.orders],['회원 귀속 상담',m.consults],['후기 기록',m.reviews],['관심 부품',m.favs],['가격 알림 설정',m.alerts]].map(([k,v])=>`<div class="mm-metric"><span>${k}</span><b>${v}</b></div>`).join('')}</div><p class="mm-metrics-note">${esc(state.notes.consults || '')}<br>${esc(state.notes.reviews || '')}<br>${esc(state.notes.alerts || '')}</p></section><section class="mm-detail-section"><h3>최근 기록 생성</h3><p class="mm-muted">${esc(fmt(m.last))}<br>${esc(state.notes.last || '')}</p></section>`;
    if($('backToList'))$('backToList').onclick=()=>{$('rows').querySelector(`[data-member="${m.id}"]`)?.focus();document.querySelector('.mm-list-panel').scrollIntoView({block:'start'});};
    if($('requestBtn'))$('requestBtn').onclick=()=>{if(blocked)return;$('confirmTitle').textContent=`${m.name || '이름 없음'} · #${m.id} 요청 기록`;$('confirmMode').textContent=$('memberMode').textContent;$('confirm').showModal();};
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
  restore();
  if(window.Admin2Shell)Admin2Shell.meReady.then(op=>{state.operator=op;renderDetail();});
  loadList(true);
})();
