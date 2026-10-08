(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else {
    root.SaleReadiness = api;
    const start = () => api.mount(document, root);
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
  }
})(typeof window === 'undefined' ? globalThis : window, function () {
  'use strict';
  const states = ['needs_work', 'needs_check', 'basis_met', 'excluded'];
  const scopeOf = value => value === 'parts' ? 'parts' : 'configurations';
  const basisLabel = scope => scope === 'parts' ? '추천 근거 충족' : '등록 근거 충족';
  const stateLabel = (state, scope) => ({needs_work:'보완 필요', needs_check:'확인 필요', basis_met:basisLabel(scope), excluded:'조회 제외'})[state] || '확인 필요';
  const checkLabel = state => ({met:'근거 확인', blocked:'보완 필요', unknown:'확인 필요', na:'해당 없음'})[state] || '확인 필요';
  const linkPaths = new Set(['/admin2/products', '/admin2/reviews', '/admin2/spec-fill', '/admin2/spec-standard', '/admin2/spec-field-defs', '/admin2/candidate-pool', '/admin2/price-review', '/admin2/sale-price', '/admin2/stock-inbound', '/admin2/pc-workspace', '/admin2/pc-configurations', '/admin2/part-explanations', '/admin2/build-map', '/admin2/product-workspace']);
  const workspaceTabs = new Set(['parts', 'copy', 'review', 'sales']);
  const identityOf = value => typeof value === 'string' && value.length <= 200 && !/[\u0000-\u001f\u007f]/.test(value) ? value : '';
  const offsetOf = value => /^\d{1,7}$/.test(String(value)) && Number(value) <= 1000000 && Number(value) % 40 === 0 ? Number(value) : 0;
  const queryOf = value => String(value || '').replace(/[\u0000-\u001f\u007f]/g, '').trim().slice(0,100);

  function readNavigation(search) {
    const params = new URLSearchParams(search);
    return {scope:scopeOf(params.get('scope')), q:queryOf(params.get('q')),
      offset:offsetOf(params.get('offset')), selectedId:identityOf(params.get('selected')) || null};
  }

  function readinessHref(state) {
    const params = new URLSearchParams({scope:scopeOf(state.scope)});
    if (queryOf(state.q)) params.set('q',queryOf(state.q));
    if (offsetOf(state.offset)) params.set('offset',String(offsetOf(state.offset)));
    if (identityOf(state.selectedId)) params.set('selected',state.selectedId);
    return '/admin2/sale-readiness?' + params;
  }

  function safeHref(value, origin) {
    if (typeof value !== 'string' || !value.startsWith('/admin2/') || /[\\\s\u0000-\u001f]/.test(value)) return null;
    try {
      const url = new URL(value, origin);
      const rawPath = value.split(/[?#]/)[0];
      if (url.origin !== origin || url.username || url.password || url.hash || rawPath !== url.pathname || !linkPaths.has(url.pathname)) return null;
      if (new Set(url.searchParams.keys()).size !== Array.from(url.searchParams).length) return null;
      for (const [key, val] of url.searchParams) {
        if (key === 'admin' && val === 'new') continue;
        if (url.pathname === '/admin2/pc-workspace' && key === 'id' && val) continue;
        if (url.pathname === '/admin2/pc-workspace') {
          if (key === 'tab' && workspaceTabs.has(val)) continue;
          if (key === 'from' && val === 'sale-readiness') continue;
          if (url.searchParams.get('from') === 'sale-readiness') {
            if (key === 'sr_scope' && ['parts','configurations'].includes(val)) continue;
            if (key === 'sr_q' && val === queryOf(val)) continue;
            if (key === 'sr_offset' && String(offsetOf(val)) === val) continue;
            if (key === 'sr_selected' && val && identityOf(val) === val) continue;
          }
        }
        if (url.pathname === '/admin2/reviews' && ['keyword', 'part_type'].includes(key)) continue;
        if (url.pathname === '/admin2/products' && ['category_id', 'include_desc'].includes(key)) continue;
        return null;
      }
      return url.pathname + url.search;
    } catch (_) { return null; }
  }

  function resolutionHref(href, item, reason, state, origin) {
    const safe = safeHref(href, origin);
    if (!safe) return null;
    const url = new URL(safe, origin);
    if (state.scope === 'parts' && url.pathname === '/admin2/reviews') {
      url.searchParams.set('keyword',item.id);
    } else if (state.scope === 'configurations' && url.pathname === '/admin2/pc-workspace' && url.searchParams.get('id') === item.id) {
      const key = reason && reason.key || '';
      const tab = key === 'parts' ? 'parts' : key === 'description' ? 'copy' : key === 'sales_conditions' || key.startsWith('sales:') ? 'sales' : reason ? 'review' : 'copy';
      url.searchParams.set('tab',tab);
      url.searchParams.set('from','sale-readiness');
      url.searchParams.set('sr_scope',scopeOf(state.scope));
      url.searchParams.set('sr_q',queryOf(state.q));
      url.searchParams.set('sr_offset',String(offsetOf(state.offset)));
      url.searchParams.set('sr_selected',item.id);
    }
    return safeHref(url.pathname + url.search, origin);
  }

  function readItem(value) {
    if (!value || (typeof value.id !== 'string' && typeof value.id !== 'number') || !String(value.id) || typeof value.name !== 'string' || !states.includes(value.state) || !Array.isArray(value.reasons) || !Array.isArray(value.checks)) throw new Error('invalid item');
    const item = {
      id:String(value.id), name:value.name, code:typeof value.code === 'string' ? value.code : '', state:value.state,
      href:typeof value.href === 'string' ? value.href : '',
      reasons:value.reasons.map(reason => {
        if (!reason || typeof reason.label !== 'string' || !['blocker', 'unknown', 'info'].includes(reason.severity)) throw new Error('invalid reason');
        return {key:String(reason.key || ''), label:reason.label, detail:String(reason.detail || ''), href:typeof reason.href === 'string' ? reason.href : '', severity:reason.severity};
      }),
      checks:value.checks.map(check => {
        if (!check || typeof check.label !== 'string' || !['met', 'blocked', 'unknown', 'na'].includes(check.state)) throw new Error('invalid check');
        return {key:String(check.key || ''), label:check.label, state:check.state, detail:String(check.detail || '')};
      })
    };
    // An inconsistent response must never turn unverified evidence into a green result.
    if (item.state === 'basis_met' && (item.checks.some(c => ['blocked', 'unknown'].includes(c.state)) || item.reasons.some(r => r.severity !== 'info'))) throw new Error('inconsistent basis');
    return item;
  }

  function readPage(value, request) {
    if (!value || value.scope !== request.scope || !Array.isArray(value.items) || !value.counts || !Number.isInteger(value.total) || value.total < 0 || value.offset !== request.offset || value.limit !== request.limit) throw new Error('invalid page');
    const counts = {};
    for (const state of states) {
      if (!Number.isInteger(value.counts[state]) || value.counts[state] < 0) throw new Error('invalid counts');
      counts[state] = value.counts[state];
    }
    if (states.reduce((sum, key) => sum + counts[key], 0) !== value.total || value.items.length > request.limit) throw new Error('inconsistent counts');
    const items = value.items.map(readItem);
    if (new Set(items.map(item => item.id)).size !== items.length) throw new Error('duplicate identity');
    return {items, counts, total:value.total, note:typeof value.note === 'string' ? value.note : ''};
  }

  function errorMessage(error) {
    if (error && error.status === 401) return '로그인이 필요합니다. 로그인 후 다시 조회해 주세요.';
    if (error && error.status === 403) return '이 근거를 조회할 권한이 없습니다.';
    if (error && error.status === 404) return '선택한 제품을 찾을 수 없습니다. 목록을 다시 조회해 주세요.';
    return '근거를 불러오지 못했습니다. 다시 조회해 주세요.';
  }

  function createController(io, initial) {
    const state = {scope:scopeOf(initial && initial.scope), q:queryOf(initial && initial.q), offset:offsetOf(initial && initial.offset), limit:40, status:'idle', items:[], counts:null, total:null, note:'', error:'', selectedId:identityOf(initial && initial.selectedId) || null, detail:null, detailStatus:'idle'};
    let listGeneration = 0, detailGeneration = 0, timer = null;
    const publish = () => { if (io.change) io.change(state); };
    const cancelTimer = () => { if (timer !== null) (io.cancel || clearTimeout)(timer); timer = null; };
    function clearEvidence() {
      state.items = []; state.counts = null; state.total = null; state.note = ''; state.error = '';
      state.selectedId = null; state.detail = null; state.detailStatus = 'idle'; detailGeneration += 1;
    }
    async function select(identity) {
      const item = state.items.find(row => row.id === String(identity));
      if (state.status !== 'ready' || !item) return false;
      const ticket = ++detailGeneration, scope = state.scope, listTicket = listGeneration;
      state.selectedId = item.id; state.detail = null; state.detailStatus = 'loading'; publish();
      try {
        const data = await io.get('/api/admin/sale-readiness/' + scope + '/' + encodeURIComponent(item.id));
        if (ticket !== detailGeneration || listTicket !== listGeneration) return false;
        const detail = readItem(data);
        if (detail.id !== item.id) throw new Error('detail identity mismatch');
        state.detail = detail; state.detailStatus = 'ready'; publish(); return true;
      } catch (error) {
        if (ticket !== detailGeneration || listTicket !== listGeneration) return false;
        clearEvidence(); state.status = 'error'; state.error = errorMessage(error); publish(); return false;
      }
    }
    async function run(ticket, request, previousId) {
      try {
        const params = new URLSearchParams({scope:request.scope, q:request.q, offset:String(request.offset), limit:String(request.limit)});
        const raw = await io.get('/api/admin/sale-readiness?' + params);
        if (ticket !== listGeneration) return false;
        const page = readPage(raw, request);
        if (!page.items.length && page.total > 0 && request.offset > 0) {
          return load({offset:Math.floor((page.total - 1) / request.limit) * request.limit});
        }
        Object.assign(state, page, {status:'ready'}); publish();
        const selected = page.items.find(item => item.id === previousId) || page.items[0];
        if (selected) await select(selected.id);
        return ticket === listGeneration && state.status === 'ready';
      } catch (error) {
        if (ticket !== listGeneration) return false;
        clearEvidence(); state.status = 'error'; state.error = errorMessage(error); publish(); return false;
      }
    }
    function load(patch, debounce) {
      cancelTimer();
      const previousId = state.selectedId;
      Object.assign(state, patch || {});
      state.scope = scopeOf(state.scope); state.q = String(state.q).trim().slice(0,100);
      const ticket = ++listGeneration, request = {scope:state.scope, q:state.q, offset:state.offset, limit:state.limit};
      clearEvidence(); state.status = 'loading'; publish();
      if (debounce) {
        timer = (io.schedule || setTimeout)(() => { timer = null; void run(ticket, request, previousId); }, debounce);
        return Promise.resolve(false);
      }
      return run(ticket, request, previousId);
    }
    return {
      state, load:() => load(), select,
      search:(q, delay) => load({q, offset:0}, delay === undefined ? 300 : delay),
      setScope:scope => load({scope, offset:0}),
      page:direction => {
        if (state.status !== 'ready' || state.total === null) return Promise.resolve(false);
        const offset = state.offset + (direction > 0 ? state.limit : -state.limit);
        if (offset < 0 || offset >= state.total) return Promise.resolve(false);
        return load({offset});
      },
      dispose:() => { cancelTimer(); listGeneration += 1; detailGeneration += 1; }
    };
  }

  function mount(doc, win) {
    const page = doc.getElementById('saleReadiness');
    if (!page) return null;
    const byId = id => doc.getElementById(id);
    const element = (tag, className, text) => {
      const node = doc.createElement(tag);
      if (className) node.className = className;
      if (text !== undefined) node.textContent = text;
      return node;
    };
    // Existing Feather distribution; these SVGs come from the icon library, never hand-drawn.
    const iconSource = (name, stroke) => win.feather && win.feather.icons[name] ? 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(win.feather.icons[name].toSvg({stroke:stroke || '#403c35','stroke-width':1.8})) : '/shared/icons/admin/help-circle.svg';
    const icon = (name, stroke) => { const img = element('img'); img.src = iconSource(name,stroke); img.alt = ''; return img; };
    doc.querySelectorAll('.sr-page img[data-icon]').forEach(img => { const name = img.dataset.icon; img.src = iconSource(name,name === 'check' ? '#176242' : name === 'clock' ? '#80570b' : name === 'alert-circle' ? '#9e3d06' : '#403c35'); });
    const badge = (item, scope) => {
      const node = element('span', 'sr-badge', stateLabel(item.state, scope)); node.dataset.state = item.state; return node;
    };
    const link = (href, label, className) => {
      const safe = safeHref(href, win.location.origin);
      if (!safe) return null;
      const node = element('a', className, label); node.href = safe; return node;
    };
    let detailView = Boolean(readNavigation(win.location.search).selectedId), focusDetail = false;
    const controller = createController({
      get:async url => {
        const response = await win.fetch(url, {method:'GET', credentials:'same-origin', cache:'no-store', headers:{Accept:'application/json'}});
        if (!response.ok) { const error = new Error('request failed'); error.status = response.status; throw error; }
        return response.json();
      },
      change:render
    }, readNavigation(win.location.search));
    byId('srSearch').value = controller.state.q;

    function render(state) {
      if (state.status === 'ready' && win.history && win.history.replaceState) win.history.replaceState(null,'',readinessHref(state));
      byId('srBasisLabel').textContent = basisLabel(state.scope);
      [['srNeedsWork','needs_work'], ['srNeedsCheck','needs_check'], ['srBasisMet','basis_met']].forEach(([id,key]) => { byId(id).textContent = state.counts ? state.counts[key].toLocaleString('ko-KR') : '—'; });
      byId('srExcluded').textContent = '조회 제외 ' + (state.counts ? state.counts.excluded.toLocaleString('ko-KR') + '건' : '—');
      byId('srResult').textContent = state.status === 'ready' ? '검색 결과 전체 ' + state.total.toLocaleString('ko-KR') + '건' : state.status === 'error' ? '조회 실패' : '불러오는 중';
      byId('srListPanel').setAttribute('aria-busy', String(state.status === 'loading'));
      byId('srListPanel').setAttribute('aria-labelledby', state.scope === 'parts' ? 'srParts' : 'srConfigurations');
      doc.querySelectorAll('.sr-tabs button').forEach(button => { const active = button.dataset.scope === state.scope; button.setAttribute('aria-selected', String(active)); button.tabIndex = active ? 0 : -1; });
      byId('srNote').textContent = state.status === 'ready' && state.note ? state.note : '확인된 근거 기준이며 주문·결제 가능 여부와는 별도입니다.';
      const rows = byId('srRows'); rows.replaceChildren();
      state.items.forEach(item => {
        const li = element('li'), button = element('button', 'sr-row'); button.type = 'button'; button.dataset.identity = item.id;
        button.setAttribute('aria-pressed', String(item.id === state.selectedId));
        button.setAttribute('aria-label', item.name + ' · ' + stateLabel(item.state, state.scope) + (item.code ? ' · ' + item.code : ''));
        const name = element('span', 'sr-product'); name.append(element('strong', '', item.name));
        if (item.code) name.append(element('span', 'sr-code', item.code));
        button.append(name, badge(item, state.scope), element('span', 'sr-first-action', item.reasons[0] ? item.reasons[0].label : item.state === 'basis_met' ? '근거 상세 확인' : '상세 확인'));
        button.addEventListener('click', () => { detailView = true; focusDetail = true; void controller.select(item.id); });
        button.addEventListener('keydown', event => {
          if (!['ArrowDown','ArrowUp','Home','End'].includes(event.key)) return;
          event.preventDefault(); const buttons = Array.from(rows.querySelectorAll('button')); const index = buttons.indexOf(button);
          const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
          buttons[next].focus();
        }); li.append(button); rows.append(li);
      });
      const message = byId('srListMessage'); message.replaceChildren(); message.hidden = state.status === 'ready' && state.items.length > 0;
      if (!message.hidden) {
        message.append(element('p','',state.status === 'error' ? state.error : state.status === 'ready' ? '검색 결과가 없습니다. 검색어를 바꿔 주세요.' : '목록을 불러오는 중입니다.'));
        if (state.status === 'error') { const retry = element('button','sr-button','다시 조회'); retry.type = 'button'; retry.addEventListener('click', () => { detailView = false; void controller.load(); }); message.append(retry); }
      }
      byId('srRange').textContent = state.status === 'ready' ? (state.items.length ? (state.offset + 1) + '–' + (state.offset + state.items.length) + ' / ' + state.total.toLocaleString('ko-KR') + '건' : '0건') : '—';
      byId('srPrev').disabled = state.status !== 'ready' || state.offset === 0;
      byId('srNext').disabled = state.status !== 'ready' || state.offset + state.limit >= state.total;
      const detail = byId('srDetail'); detail.replaceChildren(); detail.setAttribute('aria-busy', String(state.detailStatus === 'loading'));
      const back = element('button','sr-button sr-back','목록으로'); back.type = 'button';
      back.addEventListener('click', () => { detailView = false; page.dataset.view = 'list'; const selected = Array.from(rows.querySelectorAll('button')).find(row => row.dataset.identity === state.selectedId); if (selected) selected.focus(); }); detail.append(back);
      page.dataset.view = detailView ? 'detail' : 'list';
      if (state.detailStatus !== 'ready' || !state.detail) {
        detail.append(element('div','sr-message', state.detailStatus === 'loading' ? '선택한 제품의 최신 근거를 확인하는 중입니다.' : state.status === 'error' ? state.error : '제품을 선택하면 최신 근거를 확인합니다.'));
        if (state.status === 'error') { detailView = false; page.dataset.view = 'list'; }
        return;
      }
      const item = state.detail, top = element('div','sr-detail-top'), titleGroup = element('div'), title = element('h2','',item.name); title.tabIndex = -1;
      titleGroup.append(title); if (item.code) titleGroup.append(element('span','sr-code',item.code)); top.append(titleGroup,badge(item,state.scope)); detail.append(top);
      detail.append(element('p','sr-detail-intro','확인된 근거 기준이며 주문·결제 가능 여부와는 별도입니다.'));
      const checks = element('ul','sr-checks'); checks.setAttribute('aria-label','판단 근거');
      const extraChecks = element('ul','sr-checks');
      item.checks.forEach((check,index) => {
        const li = element('li'), disclosure = element('details','sr-check'); disclosure.dataset.state = check.state;
        const line = element('summary','sr-check-line'); line.append(icon(check.state === 'met' ? 'check-circle' : check.state === 'blocked' ? 'alert-circle' : check.state === 'unknown' ? 'clock' : 'minus-circle',check.state === 'met' ? '#176242' : check.state === 'blocked' ? '#9e3d06' : check.state === 'unknown' ? '#80570b' : '#6f6a61'), element('strong','',check.label), element('span','sr-check-state',checkLabel(check.state)));
        const chevron = icon('chevron-down','#6f6a61'); chevron.className = 'sr-check-chevron'; line.append(chevron);
        disclosure.append(line,element('span','sr-check-detail',check.detail || '추가 설명이 없습니다.')); li.append(disclosure); (index < 4 ? checks : extraChecks).append(li);
      });
      if (item.checks.length > 4) {
        const rest = item.checks.slice(4), unknown = rest.filter(check => check.state === 'unknown').length, blocked = rest.filter(check => check.state === 'blocked').length;
        const li = element('li'), more = element('details','sr-extra-checks');
        more.append(element('summary','','추가 근거 ' + rest.length + '개' + (unknown ? ' · 확인 필요 ' + unknown + '개' : '') + (blocked ? ' · 보완 필요 ' + blocked + '개' : '')),extraChecks); li.append(more); checks.append(li);
      }
      if (item.checks.length) detail.append(checks);
      else detail.append(element('p','sr-detail-intro','세부 판단 근거가 없습니다. 기존 작업 화면에서 확인해 주세요.'));
      detail.append(element('h3','',item.reasons.length ? '지금 해결해야 할 작업' : '차단 이유'));
      if (item.reasons.length) {
        const reasons = element('ul','sr-reasons');
        const moreReasons = element('ul','sr-reasons');
        item.reasons.forEach((reason,index) => { const li = element('li','sr-reason'); li.dataset.severity = reason.severity; const copy = element('div'); copy.append(element('strong','',reason.label)); if (reason.detail) copy.append(element('p','',reason.detail)); li.append(copy); const action = link(resolutionHref(reason.href,item,reason,state,win.location.origin),'작업 화면 열기','sr-resolve'); if (action) { action.setAttribute('aria-label', reason.label + ' · 작업 화면 열기'); li.append(action); } (index < 2 ? reasons : moreReasons).append(li); }); detail.append(reasons);
        if (item.reasons.length > 2) { const more = element('details','sr-more'); more.append(element('summary','','추가 작업 ' + (item.reasons.length - 2) + '개 보기'),moreReasons); detail.append(more); }
      } else detail.append(element('p','sr-detail-intro','조회된 차단 이유가 없습니다. 확인된 근거의 범위는 위 항목을 참고해 주세요.'));
      const open = link(resolutionHref(item.href,item,null,state,win.location.origin), state.scope === 'parts' ? '부품 작업 화면 열기' : '구성 PC 작업실 열기', 'sr-open'); if (open) { open.append(icon('arrow-right','#176242')); detail.append(open); }
      if (focusDetail) { focusDetail = false; title.focus({preventScroll:true}); if (win.matchMedia('(max-width:600px)').matches) detail.scrollIntoView({block:'start'}); }
    }
    doc.querySelectorAll('.sr-tabs button').forEach(button => {
      button.addEventListener('click', () => { detailView = false; void controller.setScope(button.dataset.scope); });
      button.addEventListener('keydown', event => {
        if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
        event.preventDefault(); const target = event.key === 'Home' ? byId('srConfigurations') : event.key === 'End' ? byId('srParts') : button.dataset.scope === 'parts' ? byId('srConfigurations') : byId('srParts');
        target.click(); target.focus();
      });
    });
    byId('srSearch').addEventListener('input', event => { detailView = false; void controller.search(event.target.value); });
    byId('srSearchForm').addEventListener('submit', event => { event.preventDefault(); detailView = false; void controller.search(byId('srSearch').value,0); });
    byId('srRefresh').addEventListener('click', () => { detailView = false; void controller.load(); });
    byId('srPrev').addEventListener('click', () => { detailView = false; void controller.page(-1); });
    byId('srNext').addEventListener('click', () => { detailView = false; void controller.page(1); });
    win.addEventListener('pagehide', () => controller.dispose(), {once:true});
    void controller.load(); return controller;
  }
  return {basisLabel, stateLabel, checkLabel, safeHref, readNavigation, readinessHref, resolutionHref, readItem, readPage, createController, mount};
});
