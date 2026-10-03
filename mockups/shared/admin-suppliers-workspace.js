/* Approved supplier NEW workspace. Production data only; no fallback fixture. */
(function () {
  'use strict';
  const root = document.getElementById('suppliers-workspace');
  if (!root) return;
  const el = id => root.querySelector('#' + id);
  const esc = value => String(value == null ? '—' : value).replace(/[&<>"']/g,
    c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const S = {canWrite:root.dataset.canWrite === 'true', page:1, size:20, q:'', status:'all',
    data:null, selected:null, profile:null, mode:'read', draft:null, baseline:null,
    error:'', duplicate:null, latest:null, impact:null, impactError:'', products:null,
    productsError:'', productsPage:1, busy:false, directorySeq:0, detailSeq:0};
  const base = '/api/admin/suppliers';
  function notice(text) { el('sw-message').textContent = text || ''; }
  function badge(status) { return '<span class="sw-badge ' + (status === '활성' ? 'sw-active' : '') + '">' + esc(status) + '</span>'; }
  function stamp(value) {
    if (!value) return '수집 시각 미확인';
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? '수집 시각 미확인' :
      d.toLocaleString('ko-KR', {timeZone:'Asia/Seoul'});
  }
  async function api(path, method, body) {
    const r = await fetch(path, {credentials:'same-origin', method:method || 'GET',
      headers:body ? {'Content-Type':'application/json'} : {}, body:body ? JSON.stringify(body) : undefined});
    let data;
    try { data = await r.json(); } catch (_) { data = {}; }
    if (!r.ok) {
      const d = data.detail;
      const err = new Error(r.status >= 500 ? '서버에서 요청을 처리하지 못했습니다. 다시 시도하세요.' :
        (d && typeof d === 'object' && !Array.isArray(d) ? d.message : typeof d === 'string' ? d :
          r.status === 422 ? '입력값을 확인하세요.' : '요청을 처리하지 못했습니다.'));
      err.status = r.status; err.detail = d;
      if (r.status === 401) err.message = '로그인이 필요합니다. 관리자 로그인 후 다시 조회하세요.';
      if (r.status === 403) {
        err.message = '권한이 부족합니다. 현재 계정의 조회·수정 권한을 확인하세요.';
        S.canWrite = false;
        if (el('sw-new')) el('sw-new').hidden = true;
      }
      throw err;
    }
    return data;
  }
  let disabledBefore = new Map();
  function busy(value) {
    S.busy = value; root.setAttribute('aria-busy', String(value));
    if (value) {
      disabledBefore = new Map();
      root.querySelectorAll('button,input,select').forEach(n => { disabledBefore.set(n, n.disabled); n.disabled = true; });
    } else {
      disabledBefore.forEach((state,n) => { if (root.contains(n)) n.disabled = state; });
      disabledBefore.clear();
    }
  }
  function readDraft() {
    if (!el('sw-form')) return;
    S.draft = {name:el('sw-name').value, platform:el('sw-platform').value, brands:el('sw-brands').value};
  }
  function formValues() {
    return {name:S.draft.name.trim(), platform:S.draft.platform.trim() || null, brands:S.draft.brands.trim() || null};
  }
  function edits() {
    const vals = formValues();
    return Object.fromEntries(Object.entries(vals).filter(([k]) =>
      S.draft[k] !== (S.baseline[k] == null ? '' : S.baseline[k])));
  }
  function dirty() {
    if (S.mode !== 'new' && S.mode !== 'edit') return false;
    readDraft();
    return S.mode === 'new' ? Object.values(S.draft).some(v => v.trim()) : Object.keys(edits()).length > 0;
  }
  function leaveForm() { return !dirty() || window.confirm('저장하지 않은 입력이 있습니다. 입력을 버리고 이동할까요?'); }
  function renderList() {
    const j = S.data;
    if (!j) return;
    const sum = j.summary;
    el('sw-summary').innerHTML = '<span>전체 <b>' + esc(sum.total) + '곳</b></span><span>활성 <b>' + esc(sum.active) +
      '곳</b></span><span>중지 <b>' + esc(sum.inactive) + '곳</b></span>';
    el('sw-count').textContent = '검색 결과 ' + j.total + '곳';
    el('sw-rows').innerHTML = j.items.map(it => '<button type="button" class="sw-row" data-action="select" data-id="' + esc(it.id) +
      '" aria-pressed="' + (it.id === S.selected) + '"><span class="sw-row-top"><strong>' + esc(it.name) + '</strong>' + badge(it.status) +
      '</span><span class="sw-muted"><span class="sw-brief">ID ' + esc(it.id) + '</span> · ' + esc(it.platform || '플랫폼 미등록') +
      '</span><span class="sw-row-bottom"><span>' + esc(it.brands || '브랜드 미등록') + '</span><span>연결 ' + esc(it.linked_products) + '개</span></span></button>').join('') ||
      '<div class="sw-empty">' + (sum.total === 0 ? '등록된 공급처가 없습니다.' : '조건에 맞는 공급처가 없습니다. 검색어나 상태를 바꿔보세요.') + '</div>';
    const start = (j.page - 1) * j.page_size;
    el('sw-range').textContent = j.total ? '검색 ' + j.total + '곳 중 ' + (start + 1) + '–' + (start + j.items.length) + '곳' : '검색 결과 0곳';
    el('sw-prev').disabled = S.busy || j.page <= 1;
    el('sw-next').disabled = S.busy || j.page * j.page_size >= j.total;
    root.querySelectorAll('.sw-row').forEach(n => { n.disabled = S.busy; });
  }
  async function directory() {
    const token = ++S.directorySeq;
    el('sw-rows').innerHTML = '<p class="sw-empty">조회 중…</p>';
    el('sw-prev').disabled = el('sw-next').disabled = true;
    el('sw-directory-error').hidden = true;
    try {
      const params = new URLSearchParams({q:S.q, status:S.status, page:S.page, page_size:S.size});
      const j = await api(base + '/directory?' + params);
      if (token !== S.directorySeq) return;
      if (!j.items.length && j.total > 0 && S.page > 1) {
        S.page = Math.max(1, Math.ceil(j.total / S.size)); return directory();
      }
      S.data = j; S.canWrite = root.dataset.canWrite === 'true' && !!j.can_write;
      if (el('sw-new')) el('sw-new').hidden = !S.canWrite;
      el('sw-state').innerHTML = '<option value="all">전체</option>' + j.states.map(s => '<option value="' + esc(s) + '">' + esc(s) + '</option>').join('');
      el('sw-state').value = S.status;
      el('sw-size').innerHTML = j.page_sizes.map(n => '<option value="' + n + '">' + n + '곳씩</option>').join('');
      el('sw-size').value = String(S.size);
      renderList();
      if (j.empty) notice(j.note);
      if (S.selected == null && S.mode === 'read' && j.items.length) await select(j.items[0].id);
      else if (S.mode === 'read' && S.profile) renderDetail();
    } catch (e) {
      if (token !== S.directorySeq) return;
      S.data = null;
      el('sw-summary').textContent = '공급처 현황을 확인하지 못했습니다.';
      el('sw-count').textContent = ''; el('sw-range').textContent = '';
      el('sw-rows').innerHTML = '<div class="sw-empty">목록을 불러오지 못했습니다.</div>';
      el('sw-directory-error').hidden = false;
      el('sw-directory-error').innerHTML = esc(e.message) + ' <button type="button" data-action="retry-directory">다시 조회</button>';
    }
  }
  async function select(id) {
    const token = ++S.detailSeq;
    S.selected = id; S.profile = null; S.mode = 'read'; S.error = ''; S.duplicate = null;
    S.products = null; S.productsError = ''; S.productsPage = 1;
    renderList(); el('sw-detail').innerHTML = '<p>상세 조회 중…</p>';
    try {
      const p = await api(base + '/' + id + '/profile');
      if (token !== S.detailSeq) return;
      S.profile = p; renderDetail(); await products(token);
    } catch (e) {
      if (token !== S.detailSeq) return;
      el('sw-detail').innerHTML = '<div class="sw-error" role="alert">' + esc(e.message) + '</div><button type="button" data-action="retry-detail">다시 조회</button>';
    }
  }
  function renderDetail() {
    if (S.mode === 'new' || S.mode === 'edit') { renderForm(); return; }
    if (S.mode === 'stop') { renderStop(); return; }
    if (!S.profile) return;
    const it = S.profile.item, c = S.profile.contact;
    const outside = S.data && !S.data.items.some(i => i.id === S.selected) ? '<p class="sw-muted">현재 목록 밖의 선택 공급처 · ID ' + esc(it.id) + '</p>' : '';
    const actions = S.canWrite && S.profile.can_write ? '<div class="sw-actions"><button type="button" data-action="edit">정보 수정</button><button type="button" class="' +
      (it.status === '활성' ? 'sw-danger' : '') + '" data-action="' + (it.status === '활성' ? 'stop' : 'revive') + '">' +
      (it.status === '활성' ? '중지 영향 확인' : '활성으로 되돌리기') + '</button></div>' : '<p class="sw-muted">조회 전용 권한입니다.</p>';
    const contact = c.name || c.phone || c.order_phone ? '<dl><dt>담당자</dt><dd>' + esc(c.name || '미등록') + '</dd><dt>대표 전화</dt><dd>' +
      esc(c.phone || '미등록') + '</dd><dt>발주 전화</dt><dd>' + esc(c.order_phone || '미등록') + '</dd></dl>' : '<p class="sw-muted">등록된 연락 정보가 없습니다.</p>';
    el('sw-detail').innerHTML = outside + '<div class="sw-detail-title"><div><span class="sw-muted sw-brief">공급처 상세 · ID ' + esc(it.id) + '</span><h2>' + esc(it.name) + '</h2></div>' + badge(it.status) +
      '</div><h3>기본 정보</h3><dl><dt>플랫폼</dt><dd>' + esc(it.platform || '미등록') + '</dd><dt>취급 브랜드</dt><dd>' + esc(it.brands || '미등록') + '</dd></dl>' + actions +
      '<hr><h3>연락 정보 <span class="sw-muted sw-brief">조회</span></h3>' + contact + '<p class="sw-muted">' +
      (c.source === 'mall_observation' ? '쇼핑몰 수집 기록 · ' : '출처 미확인 · ') + esc(stamp(c.fetched_at)) +
      '<br>저장된 정보입니다. 현재 연락 가능 여부를 확인한 것은 아닙니다.</p><hr><h3>상품·단가표 연결</h3><dl><dt>매입가 연결 상품</dt><dd>' + esc(it.linked_products) +
      '개</dd><dt>단가표 파일</dt><dd>' + esc(it.price_files) + '건</dd><dt>파서 프리셋</dt><dd>' + (it.preset_count ? '등록됨' : '없음') + '</dd></dl>' +
      (!it.preset_count ? '<div class="sw-callout sw-warning">파서 프리셋이 없어 단가표 자동 반영 준비가 필요합니다.</div>' : '') +
      '<h3>연결 상품</h3><div id="sw-products"></div><p class="sw-muted">이 화면에서는 상품 연결·가격·재고를 변경하지 않습니다.</p>';
    renderProducts();
  }
  async function products(token) {
    S.productsError = ''; S.products = null; renderProducts();
    const id = S.selected, page = S.productsPage;
    try {
      const data = await api(base + '/' + id + '/products?page=' + page + '&page_size=20');
      if (token !== S.detailSeq || id !== S.selected || page !== S.productsPage) return;
      S.products = data; renderProducts();
    } catch (e) {
      if (token !== S.detailSeq || id !== S.selected || page !== S.productsPage) return;
      S.productsError = e.message; renderProducts();
    }
  }
  function renderProducts() {
    const node = el('sw-products'); if (!node) return;
    if (S.productsError) { node.innerHTML = '<p class="sw-error" role="alert">' + esc(S.productsError) + '</p><button type="button" data-action="retry-products">다시 조회</button>'; return; }
    const j = S.products;
    if (!j) { node.textContent = '연결 상품 조회 중…'; return; }
    node.innerHTML = j.items.map(p => '<div class="sw-product"><span>' + esc(p.display_name) + '<br><span class="sw-muted"><span class="sw-brief">상품 ' + esc(p.product_code) + '</span> · ' + esc(p.sku || 'SKU 미등록') +
      '</span></span><span class="sw-muted">' + esc(p.supply_state || '상태 미등록') + '</span></div>').join('') || '<p class="sw-muted">연결된 상품이 없습니다.</p>';
    if (j.total) node.innerHTML += '<nav class="sw-pagination" aria-label="연결 상품 페이지"><button type="button" data-action="products-prev" ' + (j.page <= 1 ? 'disabled' : '') +
      '>이전</button><span>총 ' + j.total + '개 · ' + j.page + ' / ' + Math.ceil(j.total / j.page_size) + '</span><button type="button" data-action="products-next" ' +
      (j.page * j.page_size >= j.total ? 'disabled' : '') + '>다음</button></nav>';
  }
  function renderForm() {
    const editing = S.mode === 'edit';
    const duplicate = S.duplicate ? '<div class="sw-callout sw-warning">이미 있는 공급처입니다.<br><strong>' + esc(S.duplicate.name) + '</strong> · ID ' +
      esc(S.duplicate.supplier_id) + ' · ' + esc(S.duplicate.status) + '<p>같은 회사인지 먼저 확인하세요. 입력은 유지됩니다.</p><button type="button" data-action="duplicate">기존 공급처 상세 보기</button></div>' : '';
    const latest = S.latest ? '<div class="sw-callout"><strong>최신 기본 정보</strong><p>' + esc(S.latest.item.name) + ' · ' + esc(S.latest.item.platform || '플랫폼 미등록') +
      ' · ' + esc(S.latest.item.brands || '브랜드 미등록') + ' · ' + esc(S.latest.item.status) + '</p><button type="button" data-action="adopt-latest">최신값 기준으로 계속 수정</button></div>' : '';
    el('sw-detail').innerHTML = '<div class="sw-muted">' + (editing ? '공급처 수정 · ID ' + esc(S.selected) : '새 공급처') + '</div><h2>' + (editing ? '기본 정보 수정' : '공급처 등록') +
      '</h2><p class="sw-muted">' + (editing ? '연락 정보·상품 연결은 함께 변경하지 않습니다.' : '이름은 필수입니다. 새 공급처는 활성 상태로 등록합니다.') + '</p>' +
      '<form id="sw-form" class="sw-form"><label>공급처 이름 *<input id="sw-name" required maxlength="100" value="' + esc(S.draft.name) +
      '" autocomplete="off" placeholder="공급처 이름"><small>최대 100자 · 대소문자와 앞뒤 공백은 중복 판정에서 무시합니다.</small></label><label>플랫폼<input id="sw-platform" maxlength="50" value="' +
      esc(S.draft.platform) + '" placeholder="선택 입력"><small class="sw-brief">최대 50자</small></label><label>취급 브랜드<input id="sw-brands" maxlength="200" value="' + esc(S.draft.brands) +
      '" placeholder="선택 입력"><small class="sw-brief">최대 200자</small></label><div class="sw-error" id="sw-form-error" role="alert">' + esc(S.error || '') + '</div>' + duplicate + latest +
      (S.error && editing && !S.latest ? '<button type="button" data-action="compare">최신 정보와 비교</button>' : '') +
      '<div class="sw-actions"><button type="submit" class="sw-primary" ' + (!S.canWrite ? 'disabled' : '') + '>' + (editing ? '변경 저장' : '등록') +
      '</button><button type="button" data-action="cancel">취소</button></div></form>';
    el('sw-form').addEventListener('submit', save);
    el('sw-form').addEventListener('input', readDraft);
  }
  async function save(e) {
    e.preventDefault(); if (S.busy || !S.canWrite) return;
    readDraft(); const values = formValues();
    if (!values.name || values.name.length > 100 || (values.platform || '').length > 50 || (values.brands || '').length > 200) {
      S.error = !values.name ? '공급처 이름을 입력하세요' : '이름 100자 · 플랫폼 50자 · 브랜드 200자 이내로 입력하세요'; renderForm(); return;
    }
    const editing = S.mode === 'edit', id = S.selected;
    const payload = editing ? {expected:S.profile.edit_snapshot, supplier:edits()} : {...values, status:'활성'};
    S.error = ''; S.duplicate = null; busy(true);
    try {
      const r = await api(editing ? base + '/' + id + '/editor' : base, editing ? 'PATCH' : 'POST', payload);
      busy(false); S.mode = 'read'; S.draft = null; S.selected = r.id; S.profile = null;
      notice(r.note || '저장했습니다.'); await directory(); await select(r.id);
    } catch (err) {
      busy(false); S.error = err.message;
      if (err.detail && err.detail.error === 'duplicate_name') S.duplicate = err.detail;
      if (err.status === 409 && typeof err.detail === 'string') S.error += ' 입력한 이름으로 목록을 검색해 기존 공급처를 확인하세요.';
      renderForm();
    }
  }
  async function openStop() {
    const token = ++S.detailSeq, id = S.selected;
    S.mode = 'stop'; S.impact = null; S.impactError = ''; renderStop();
    try {
      const profile = await api(base + '/' + id + '/profile');
      if (token !== S.detailSeq || S.mode !== 'stop') return;
      S.profile = profile;
      if (profile.item.status !== '활성') { S.mode = 'read'; notice('이미 중지된 공급처입니다.'); renderDetail(); return; }
      const im = await api(base + '/' + id + '/impact');
      if (token !== S.detailSeq || S.mode !== 'stop') return;
      if (im.supplier_id !== id) throw new Error('공급처 대상을 확인하지 못했습니다.');
      S.impact = im; renderStop();
    } catch (e) { if (token === S.detailSeq && S.mode === 'stop') { S.impactError = e.message; renderStop(); } }
  }
  function renderStop() {
    const it = S.profile.item, im = S.impact;
    el('sw-detail').innerHTML = '<span class="sw-muted">상태 변경 · ID ' + esc(it.id) + '</span><h2>' + esc(it.name) + ' 중지 전 확인</h2><p class="sw-muted">삭제가 아닙니다. 기존 연결과 기록은 남습니다.</p>' +
      (S.impactError ? '<p class="sw-error" role="alert">' + esc(S.impactError) + '</p><button type="button" data-action="retry-impact">다시 조회</button>' : !im ? '<p>중지 영향 조회 중…</p>' :
        '<div class="sw-impact"><div><span>연결 상품</span><b>' + esc(im.linked_products) + '</b></div><div><span>단가표 파일</span><b>' + esc(im.price_files) +
        '</b></div><div><span>유일 연결 상품</span><b>' + esc(im.sole_source_products) + '</b></div></div><div class="sw-callout sw-warning">' + esc(im.sole_source_products) +
        '개 상품은 저장된 연결 기준으로 공급처가 이곳 한 곳뿐입니다. 다른 활성·구매 가능 공급처 유무와는 별도입니다.</div>') +
      '<div class="sw-callout">활성 공급처 선택 목록에서 제외됩니다.<br>기존 매입가·단가표·기록은 변경하지 않습니다. 중지 상태여도 일부 업무에서는 기존 공급처를 계속 참조할 수 있습니다.</div>' +
      '<div class="sw-actions"><button type="button" class="sw-danger" data-action="confirm-stop" ' + (!im || S.impactError || !S.canWrite ? 'disabled' : '') +
      '>중지로 변경</button><button type="button" data-action="cancel">취소</button></div>';
  }
  async function changeStatus(status) {
    if (S.busy || !S.canWrite || !S.profile || (status === '중지' && (!S.impact || S.impactError))) return;
    const id = S.selected, expected = S.profile.edit_snapshot; busy(true);
    try {
      const r = await api(base + '/' + id + '/editor', 'PATCH', {expected, supplier:{status}});
      busy(false); S.mode = 'read'; S.profile = null; notice(r.note); await directory(); await select(id);
    } catch (e) {
      busy(false); notice(e.message);
      if (S.mode === 'stop') { S.impactError = e.message; S.impact = null; renderStop(); }
      else renderDetail();
    }
  }
  root.addEventListener('click', async function (e) {
    const button = e.target.closest('button[data-action]'); if (!button || S.busy) return;
    const action = button.dataset.action;
    if (['select','new','duplicate','cancel'].includes(action) && !leaveForm()) return;
    if (action === 'select' || action === 'duplicate') {
      const id = action === 'select' ? Number(button.dataset.id) : S.duplicate.supplier_id;
      notice(''); await select(id);
    } else if (action === 'new' && S.canWrite) {
      ++S.detailSeq; S.mode = 'new'; S.draft = {name:'',platform:'',brands:''}; S.error = ''; S.duplicate = S.latest = null; notice(''); renderForm(); el('sw-name').focus();
    } else if (action === 'edit' && S.canWrite && S.profile) {
      S.mode = 'edit'; S.baseline = {...S.profile.edit_snapshot};
      S.draft = {name:S.baseline.name, platform:S.baseline.platform || '', brands:S.baseline.brands || ''}; S.error = ''; S.duplicate = S.latest = null; renderForm();
    } else if (action === 'cancel') {
      ++S.detailSeq; S.mode = 'read'; S.draft = null;
      if (S.selected != null) await select(S.selected); else el('sw-detail').innerHTML = '<h2>공급처를 선택하세요</h2>';
    } else if (action === 'prev' || action === 'next') {
      S.page += action === 'next' ? 1 : -1; await directory();
    } else if (action === 'retry-directory') await directory();
    else if (action === 'retry-detail') await select(S.selected);
    else if (action === 'stop' || action === 'retry-impact') { if (S.canWrite) await openStop(); }
    else if (action === 'confirm-stop') await changeStatus('중지');
    else if (action === 'revive') await changeStatus('활성');
    else if (action === 'retry-products' || action === 'products-prev' || action === 'products-next') {
      if (action === 'products-prev') S.productsPage--;
      if (action === 'products-next') S.productsPage++;
      await products(S.detailSeq);
    } else if (action === 'compare') {
      readDraft(); const id = S.selected, token = S.detailSeq;
      try { const latest = await api(base + '/' + id + '/profile'); if (token === S.detailSeq && S.mode === 'edit') { S.latest = latest; renderForm(); } }
      catch (err) { if (token === S.detailSeq && S.mode === 'edit') { S.error = err.message; renderForm(); } }
    } else if (action === 'adopt-latest' && S.latest) {
      readDraft(); const retained = edits();
      S.profile = S.latest; S.latest = null; S.baseline = {...S.profile.edit_snapshot};
      const merged = {...S.baseline, ...retained};
      S.draft = {name:merged.name,platform:merged.platform || '',brands:merged.brands || ''};
      S.error = ''; notice('최신 기본값을 반영했습니다. 수정한 입력은 유지되며 아직 저장하지 않았습니다.'); renderForm();
    }
  });
  el('sw-search-form').addEventListener('submit', e => {
    e.preventDefault(); if (S.busy) return;
    S.q = el('sw-search').value.trim(); S.status = el('sw-state').value; S.size = Number(el('sw-size').value); S.page = 1; directory();
  });
  ['sw-state','sw-size'].forEach(id => el(id).addEventListener('change', () => {
    if (S.busy) return;
    S.q = el('sw-search').value.trim(); S.status = el('sw-state').value; S.size = Number(el('sw-size').value); S.page = 1; directory();
  }));
  window.addEventListener('beforeunload', e => { if (S.busy || dirty()) { e.preventDefault(); e.returnValue = ''; } });
  directory();
})();
