/* 대화·비교 화면. /mvp4 에서는 대화가 실제 상담 API(live-talk.js)를 부른다(2026-10-19).
 * 비교는 실제 목록(live-catalog.js)의 상품만 쓴다. 견적 보관·상담 접수는 이 파일이 하지 않는다. */
(function () {
  'use strict';
  var P = window.PAI;
  if (!P) return;
  P.designScreens = P.designScreens || {};
  var h = P.h, icon = P.icon, MAX_TEXT = 10000;
  var CHAT_STATES = ['welcome', 'product', 'loading', 'results', 'clarify', 'budget-over', 'no-results', 'partial', 'error', 'offline', 'timeout', 'long-message'];
  var COMPARE_STATES = ['normal', 'one', 'empty', 'unavailable'];
  var DEFAULT_QUESTION = '게임과 영상 편집용 PC를 찾고 있어요';
  var ROWS = [
    { key: 'cpu', label: 'CPU', aliases: ['cpu', '프로세서'] },
    { key: 'gpu', label: '그래픽카드', aliases: ['gpu', '그래픽카드', '그래픽'] },
    { key: 'ram', label: '메모리', aliases: ['ram', '메모리'] },
    { key: 'ssd', label: '저장장치', aliases: ['ssd', '저장장치', '스토리지'] },
    { key: 'price', label: '가격', aliases: [] }
  ];
  function param(ctx, key) { var q = ctx && ctx.query; return q && typeof q.get === 'function' ? q.get(key) : q && q[key] !== undefined ? q[key] : null; }
  function products() { return (Array.isArray(P.catalogProducts) ? P.catalogProducts : []).filter(function (p) { return p && p.id !== undefined && typeof p.name === 'string'; }); }
  function recommendations() { return products().filter(function (p) { return p.isSelling === true && p.recommendable === true && p.reviewRequired !== true && typeof p.price === 'number' && isFinite(p.price) && p.price > 0; }); }
  function purchaseIssue(p) {
    if (!p) return '상품 확인 필요';
    if (p.kind === 'ai_device') return deviceIssue(p);
    if (p.source && p.source.kind === 'historical') return '현재 판매 여부 확인 필요';
    if (p.isSelling !== true) return p.saleStatus === '품절' ? '품절 · 판매 여부 확인 필요' : '판매 여부 확인 필요';
    if (p.statusKey === 'oos' || p.stockQty === 0) return '재고·판매 상태 확인 필요';
    if (p.reviewRequired === true) return '상품 검수 필요';
    if (!(typeof p.price === 'number' && isFinite(p.price) && p.price > 0)) return '가격 확인 필요';
    // 구성표 확인은 구매를 막는 조건이 아니다(2026-10-20 대표 -- 상품 상세 pending() 과 같은 기준). 구성은 상세에서 확인한다.
    return '';
  }
  function product(id) {
    if (id === null || id === undefined || id === '') return null;
    if (typeof P.getCatalogProduct === 'function') { try { return P.getCatalogProduct(String(id)) || null; } catch (error) { return null; } }
    return products().find(function (p) { return String(p.id) === String(id); }) || null;
  }
  // AI 장비(AI 슈퍼컴퓨터 카테고리) — 2026-10-21 구매 1번 승인으로 관심·비교상품에 함께 담는다.
  // 상품번호로 서버 상세를 읽은 값만 쓴다(이름·배열로 정하지 않는다). 사양 칸은 장비 사양 그대로이고,
  // 장비 메모리를 그래픽카드 전용 메모리와 같은 숫자로 놓지 않는다(같은 기준이 아니라고 칸에 적는다).
  function deviceOf(d) {
    return d ? { kind: 'ai_device', id: String(d.id), name: d.name + (d.modelLabel && d.models && d.models.length > 1 && d.name.indexOf(d.modelLabel) < 0 ? ' · ' + d.modelLabel : ''), modelLabel: d.modelLabel, price: d.price, saleState: d.saleState,
      processor: d.processor, accelerator: d.accelerator, memory: d.memory, storage: d.storage, image: d.image, mallUrl: d.mallUrl } : null;
  }
  function deviceIssue(d) { return d.saleState === 'stopped' ? '판매 중지' : d.saleState !== 'on_sale' ? '가격 확인 필요' : ''; }
  function deviceHref(d) { return 'supercomputer.html?id=' + encodeURIComponent(d.id); }
  function deviceBuy(d) { return d.saleState === 'stopped' ? '<button class="btn btn-small btn-primary" disabled>판매 중지</button>' : (P.mallBuyAnchor && P.mallBuyAnchor({ id: d.id, url: d.mallUrl, name: d.name, price: d.saleState === 'on_sale' ? d.price : null, image: d.image, cls: 'btn btn-small btn-primary', label: '팝콘PC몰에서 바로 구매' })) || '<button class="btn btn-small btn-primary" disabled>팝콘PC몰 구매 링크 확인 필요</button>'; }
  function deviceSpec(d, row) {
    if (row.key === 'price') return d.saleState === 'stopped' ? '판매 중지' : typeof d.price === 'number' && d.price > 0 ? P.money(d.price) : '가격 확인 필요';
    if (row.key === 'cpu') return d.processor || '정보 확인 필요';
    if (row.key === 'gpu') return d.accelerator ? d.accelerator + ' (AI 가속기)' : '정보 확인 필요';
    if (row.key === 'ram') return d.memory ? d.memory + ' (장비 메모리 · 그래픽카드 전용 메모리와 같은 기준 아님)' : '정보 확인 필요';
    if (row.key === 'ssd') return d.storage || '정보 확인 필요';
    return '정보 확인 필요';
  }
  function url(screen, state, values) { return typeof P.designHref === 'function' ? P.designHref(screen, state, values || {}) : '#'; }
  function money(p) { return p && typeof P.catalogMoney === 'function' ? P.catalogMoney(p) : '가격 확인 필요'; }
  function photograph(p, cls) {
    var source = p && p.kind === 'ai_device' ? (typeof p.image === 'string' && /^(assets\/|\/api\/product-images\/)/.test(p.image) ? p.image : null) : p && typeof P.catalogImage === 'function' ? P.catalogImage(p) : null;
    return source ? '<img class="' + h(cls || '') + '" src="' + h(source) + '" alt="' + h(p.name) + '" loading="lazy">' : '<span class="dc-photo-placeholder">' + icon('computer-tower') + '<small>상품 사진 준비 중</small></span>';
  }
  // 2026-10-20 승인 「구매 경로 분리」 -- 선택·비교한 일반 완제품의 다음 행동은 그 상품의 팝콘PC몰 페이지다(견적 보관·상담 아님).
  function buyButton(p, unsure, cls) { if (p && p.kind === 'ai_device') return deviceBuy(p); return (P.mallBuyLink && P.mallBuyLink(p, cls || 'btn btn-small btn-primary', unsure ? '팝콘PC몰에서 상품 확인' : '팝콘PC몰에서 바로 구매')) || '<button class="btn btn-small btn-primary" disabled>팝콘PC몰 구매 링크 확인 필요</button>'; }
  function buttonLink(label, screen, state, values, style) { return '<a class="btn ' + (style || 'btn-outline') + '" href="' + h(url(screen, state, values)) + '">' + h(label) + icon('caret-right') + '</a>'; }
  function normalize(value) { return String(value || '').toLowerCase().replace(/[\s·:()_-]/g, ''); }
  function spec(p, row) {
    if (p && p.kind === 'ai_device') return deviceSpec(p, row);
    if (row.key === 'price') return money(p);
    if (p.bomStatus === 'mismatch') return '상품과 구성표 일치 확인 필요';
    var list = Array.isArray(p.specs) ? p.specs : [];
    var item = list.find(function (s) { var label = normalize(s.label); return row.aliases.some(function (a) { return label === normalize(a); }); });
    if (!item && row.key === 'ssd') item = list.find(function (s) { return /ssd|저장장치/.test(normalize(s.label)); });
    if (item && item.value !== undefined && String(item.value).trim()) return String(item.value) + (item.basis === 'registered-spec-source-text' ? ' (등록 모델 · 판매 구성 확인 필요)' : '');
    var summary = (Array.isArray(p.summarySpecs) ? p.summarySpecs : []).find(function (s) { return row.aliases.some(function (a) { return normalize(s.label) === normalize(a); }); });
    return summary && summary.value ? String(summary.value) + ' (상품명 요약)' : '정보 확인 필요';
  }
  function shortSpecs(p) { if (p.bomStatus === 'mismatch') return '상품과 구성표 일치 확인 필요'; var exact = Array.isArray(p.specs) && p.specs.length; var rows = exact ? p.specs : p.summarySpecs || []; return (exact ? (p.source && p.source.bomBasis === 'registered-admin-spec-source-text' ? '등록 모델 · 판매 구성 확인 필요 · ' : '') : rows.length ? '상품명 요약 · ' : '') + rows.filter(function (s) { return s.label && s.value; }).slice(0, 2).map(function (s) { return h(s.label) + ' ' + h(s.value); }).join(' · '); }
  function empty(label, description, action) { return '<div class="dc-empty">' + icon('computer-tower') + '<h3>' + h(label) + '</h3><p>' + h(description) + '</p>' + (action || '') + '</div>'; }
  function replyFor(state) {
    return {
      product: '이 PC의 구성과 필요한 작업을 함께 살펴볼게요. 사용하는 프로그램이나 모니터 환경을 알려주셔도 좋아요.',
      results: '아래 상품을 함께 살펴보세요. 부품 구성이나 변경 가능 여부가 아직 확인되지 않은 상품은 상세 화면에서 확인할 수 있어요.',
      clarify: '생각한 예산이 있나요? 아직 정하지 않았다면 괜찮아요. 자주 하는 작업이나 사용하는 프로그램부터 알려주세요.',
      'budget-over': '예산 범위를 넓혀서도 살펴볼까요? 예산을 유지한 채 중요한 조건부터 다시 정할 수도 있어요.',
      'no-results': '지금 조건으로 보여드릴 PC가 없어요. 예산이나 용도 중 바꿀 수 있는 조건부터 다시 살펴볼까요?',
      partial: '일부 상품 정보를 확인하지 못했어요. 확인할 수 있는 구성을 먼저 살펴보고, 나머지는 다시 확인할 수 있어요.'
    }[state] || '';
  }
  function card(p, selected) {
    return '<article class="dc-product-card' + (selected ? ' is-selected' : '') + '"><a class="dc-product-photo" href="' + h(url('product', 'normal', { id: p.id })) + '">' + photograph(p) + '</a>' +
      '<div class="dc-product-content"><h3><a href="' + h(url('product', 'normal', { id: p.id })) + '">' + h(p.name) + '</a></h3><p>' + (shortSpecs(p) || h(p.summary || '세부 구성을 확인해 주세요.')) + '</p><strong>' + h(money(p)) + '</strong>' +
      '<div class="dc-product-actions"><button type="button" class="btn btn-small ' + (selected ? 'btn-primary' : 'btn-outline') + '" data-dc-select="' + h(p.id) + '" aria-pressed="' + String(selected) + '">' + (selected ? '선택한 PC' : '이 PC 선택') + '</button><a href="' + h(url('product', 'normal', { id: p.id })) + '">상세 ' + icon('caret-right') + '</a>' + (P.mallBuyLink ? P.mallBuyLink(p, 'dc-mall-buy', '팝콘PC몰에서 바로 구매') : '') + '</div></div></article>';
  }

  P.designScreens.chat = function (ctx) {
    /* /mvp4 실제 상담(2026-10-19). 승인 화면의 배치·문구는 그대로 두고, 답과 추천 PC 만 서버(P.liveTalk)에서 받는다.
     * 고객이 쓰지 않은 질문을 대신 넣지 않는다. 실패하면 입력을 그대로 두고 그 사실을 알린다. */
    ctx = ctx || {};
    var entry = ['welcome', 'product', 'clarify'].indexOf(ctx.state) >= 0 ? ctx.state : 'welcome';
    var selectedId = ctx.productId || param(ctx, 'id');
    var selected = selectedId ? product(selectedId) : null;
    var model = { state: entry === 'product' && selected ? 'product' : 'welcome', question: '', draft: '', outgoing: null, selected: selected, log: [], ids: [], mobile: 'chat', notice: '', handoff: false,
      conditions: { purpose: '', budget: '', environment: '' }, dirty: {}, convo: { talk: null, chatFlow: null, history: [], pendingText: '' }, compare: [] };
    var controller = null, root = null, lastPick = null, A = P.chatAnswer;
    var COMPARE_MAX = 3;
    // 화면 왕복 보존(2026-10-21 검수 F1): 다른 화면(AI 슈퍼컴퓨터·내 견적·상세)을 다녀와도 대화·작성 중 질문·조건·비교·선택·스크롤이
    // 남는다. 이 탭(sessionStorage)에만 두고 서버로 보내지 않는다. 「새 대화」만 비운다.
    var KEEP = 'pai-finder-chat-v1', SAVED = ['state', 'question', 'draft', 'outgoing', 'log', 'ids', 'mobile', 'handoff', 'conditions', 'dirty', 'convo', 'compare'], restoredScroll = null;
    function remember(scroll) {
      try {
        var snap = { v: 1, selected: model.selected ? String(model.selected.id) : null };
        SAVED.forEach(function (k) { snap[k] = model[k]; });
        if (snap.state === 'loading') { snap.state = 'error'; snap.draft = model.question; }   // 떠나며 끊긴 질문은 입력창에 돌려 둔다
        if (scroll) { var lg = root && root.querySelector('.dc-chat-log'); snap.scroll = { page: window.scrollY || 0, log: lg ? lg.scrollTop : 0 }; }
        else snap.scroll = restoredScroll;   // 떠날 때 잰 위치는 다음에 떠날 때까지 둔다(화면이 다시 그려져도)
        window.sessionStorage.setItem(KEEP, JSON.stringify(snap));
      } catch (ignoreKeep) { /* 저장소를 못 쓰면 보존만 빠진다 */ }
    }
    (function restore() {
      var snap = null;
      try { snap = JSON.parse(window.sessionStorage.getItem(KEEP) || 'null'); } catch (ignoreRestore) { snap = null; }
      if (!snap || snap.v !== 1) return;
      SAVED.forEach(function (k) { if (snap[k] !== undefined && snap[k] !== null) model[k] = snap[k]; });
      if (CHAT_STATES.indexOf(model.state) < 0 || model.state === 'loading') model.state = 'welcome';
      if (!Array.isArray(model.log)) model.log = []; if (!Array.isArray(model.ids)) model.ids = []; if (!Array.isArray(model.compare)) model.compare = [];
      // 상품에서 「AI와 이어서 대화」로 들어오면 그 상품을 고른 채 이어 간다. 아니면 고르던 상품을 그대로 둔다.
      if (!selected && snap.selected) model.selected = product(snap.selected);
      if (entry === 'product' && selected && !model.log.length) model.state = 'product';
      restoredScroll = snap.scroll || null;   // 이 값은 지우지 않는다 -- 보관된 화면이 한 번 더 그려져도 같은 위치로 돌아간다
    }());
    function candidates() { return model.ids.map(function (x) { return product(x.id); }).filter(Boolean).slice(0, 3); }
    function messages() {
      var list = model.log.slice();
      if (model.state === 'product' && model.selected && !list.length) list.push({ role: 'assistant', text: '이 PC의 구성과 필요한 작업을 함께 살펴볼게요. 하려는 작업이나 사용하는 프로그램을 알려 주세요.' });
      var opts = { pcHref: function (id) { return url('product', 'normal', { id: id }); }, issue: purchaseIssue, money: money, inCompare: inCompare };
      return list.map(function (m) { return '<article class="dc-message dc-message-' + m.role + '"><span>' + (m.role === 'user' ? '나' : '팝콘AI') + '</span>' + (m.answer && A ? A.render(m, opts) : '<p>' + h(m.text) + '</p>') + '</article>'; }).join('');
    }
    function stateNotice() {
      // 응답 대기(2026-10-20 대표 「마지막 시안을 작게 해서 애니메이션」): 실제 요청 중에만 그려지고 답·오류·중단이면 다시 그려지며 사라진다.
      if (model.state === 'loading') return '<div class="dc-state-box dc-loading dc-wait" role="status">' + (P.chatWaitArt ? P.chatWaitArt() : icon('clock')) + '<div><strong>AI가 답변을 준비하고 있어요.</strong><p>조금만 기다려 주세요.</p></div></div>';
      var errors = { error: ['답변을 불러오지 못했어요.', '입력한 내용을 유지했어요. 다시 보내거나 내용을 고칠 수 있어요.'], offline: ['연결 상태를 확인해 주세요.', '대화를 이어가지 못했어요. 연결을 확인한 뒤 다시 시도해 주세요.'], timeout: ['답변이 예상보다 오래 걸리고 있어요.', '응답을 확인하지 못했어요. 입력한 내용을 보관한 채 다시 시도할 수 있어요.'], 'rate-limit': ['요청이 잠시 많아요.', '잠시 후 다시 보내 주세요. 입력한 내용은 그대로 남아 있어요.'], 'long-message': ['내용을 조금 나누어 보내주세요.', '한 번에 10,000자까지 입력할 수 있어요. 원문은 입력창에 그대로 두었어요.'] };
      if (errors[model.state]) { var item = errors[model.state]; return '<div class="dc-state-box dc-error" role="alert">' + icon('warning-circle') + '<div><strong>' + h(item[0]) + '</strong><p>' + h(item[1]) + '</p>' + (model.state !== 'long-message' ? '<button type="button" data-dc-action="retry">' + icon('arrow-counter-clockwise') + '다시 시도</button>' : '') + '</div></div>'; }
      if (model.state === 'clarify') return '<div class="dc-inline-actions"><button class="dc-draft-chip" type="button" data-dc-draft="예산은 아직 정하지 않았어요.">예산은 아직 몰라요</button><button class="dc-draft-chip" type="button" data-dc-draft="어떤 사양이 필요한지 잘 모르겠어요.">사양을 잘 몰라요</button></div>';
      if (model.state === 'no-results') return '<div class="dc-inline-actions"><button class="btn btn-small btn-primary" type="button" data-dc-action="conditions">조건 다시 정하기</button>' + buttonLink('PC 둘러보기', 'catalog', 'normal', {}, 'btn-small btn-outline') + '</div>';
      // 일반 완제품은 상품 상담으로 넘기지 않는다(2026-10-20 구매 경로 분리) -- 사람 상담은 상품 없는 일반 문의로, 선택 PC 는 몰 구매로.
      if (model.handoff) return '<div class="dc-inline-actions">' + (model.selected ? buyButton(model.selected, false) : '') + buttonLink('사람 상담 신청하기', 'consult', 'normal', {}, 'btn-small btn-outline') + '</div>';
      return '';
    }
    function selection() {
      if (!model.selected) return empty('아직 선택한 PC가 없어요.', '상품의 구성을 비교하고 마음에 드는 PC를 골라보세요.');
      var p = model.selected, blocked = purchaseIssue(p);
      return '<div class="dc-chosen"><div class="dc-chosen-head"><small>선택한 PC</small><button type="button" class="dc-chosen-clear" data-dc-unselect aria-label="' + h(p.name) + ' 선택 해제">' + icon('x') + '선택 해제</button></div><div class="dc-chosen-top">' + photograph(p) + '<div><strong>' + h(p.name) + '</strong><p>' + h(money(p)) + '</p></div></div>' + (blocked ? '<p class="dc-unavailable-label" role="status">' + h(blocked) + '</p>' : '') + '<div class="dc-chosen-links">' + buttonLink('선택 PC 상세', 'product', 'normal', { id: p.id }, 'btn-small btn-outline') + buyButton(p, !!blocked) + '</div></div>';
    }
    function kindOf(k) { return k === 'ai_device' ? 'ai_device' : 'pc'; }
    function inCompare(id, kind) { kind = kindOf(kind); return model.compare.some(function (c) { return c.id === String(id) && c.kind === kind; }); }
    // 관심·비교상품(2026-10-20 대표 승인): 답변 카드의 「비교에 담기」가 여기에 쌓인다. 저장하지 않는다(새 대화·새로고침이면 비운다).
    function compareTray() {
      var items = model.compare.map(function (c) { var p = c.kind === 'ai_device' ? c.device : product(c.id); return p ? { c: c, p: p } : null; }).filter(Boolean);
      var pcs = items.filter(function (x) { return x.c.kind === 'pc'; }).map(function (x) { return x.p.id; }), devs = items.filter(function (x) { return x.c.kind === 'ai_device'; }).map(function (x) { return x.p.id; });
      return '<section class="dc-side-panel pa-interest" aria-label="관심·비교상품"><h2>' + icon('list') + '관심·비교상품 <span data-pa-count>' + items.length + '</span></h2>' +
        (items.length ? '<ul>' + items.map(function (x) {
          var dev = x.c.kind === 'ai_device', href = dev ? deviceHref(x.p) : url('product', 'normal', { id: x.p.id });
          return '<li><div><a href="' + h(href) + '" target="_blank" rel="noopener">' + (dev ? '<span class="pa-kind">AI 장비</span>' : '') + h(x.p.name) + '</a><small>상품번호 ' + h(x.p.id) + '</small></div><button type="button" class="pa-copy pa-remove" data-pa-remove="' + h(x.p.id) + '" data-pa-kind="' + x.c.kind + '" aria-label="' + h(x.p.name) + ' 비교에서 빼기">비교에서 빼기</button></li>';
        }).join('') + '</ul>' : '<p class="pa-interest-empty">추천 답변이나 AI 슈퍼컴퓨터 상세에서 비교할 상품을 담아보세요. 대화와 입력 중인 문장은 그대로예요.</p>') +
        (items.length >= 2 ? '<a class="pa-open-compare" href="' + h(url('compare', 'normal', { ids: pcs.join(','), ai: devs.join(',') })) + '" target="_blank" rel="noopener">선택 상품 비교하기 ↗</a>' : '') + '</section>';
    }
    // 코발트 추천 패널(2026-10-21 대표 승인 1번): 지금 고른 PC, 없으면 서버가 준 첫 추천 PC 하나를 크게 보인다.
    // 구매 · 선택 · 비교는 서로 다른 버튼이고 각자 기존 동작(몰 안내창 · data-dc-select/unselect · data-pa-add)을 그대로 쓴다.
    function featured() {
      var list = candidates(), p = model.selected || list[0];
      if (!p) return '';
      var picked = !!model.selected && String(model.selected.id) === String(p.id), issue = purchaseIssue(p), added = inCompare(p.id, 'pc');
      var detail = url('product', 'normal', { id: p.id });
      return '<section class="dc-feature" aria-labelledby="dc-feature-title"><header class="dc-feature-head"><h2 id="dc-feature-title">' + icon('check-circle') + (picked ? '선택한 PC' : 'AI 추천 PC') + '</h2><small>구매 시 가격 확인</small></header>' +
        '<div class="dc-feature-body"><a class="dc-feature-photo" href="' + h(detail) + '">' + photograph(p) + '</a><div class="dc-feature-info"><h3><a href="' + h(detail) + '">' + h(p.name) + '</a></h3><p>' + (shortSpecs(p) || h(p.summary || '세부 구성을 확인해 주세요.')) + '</p><strong>' + h(money(p)) + '</strong>' +
        (issue ? '<p class="dc-unavailable-label" role="status">' + h(issue) + '</p>' : '') + '</div></div>' +
        '<div class="dc-feature-actions">' + buyButton(p, !!issue, 'btn btn-primary dc-feature-buy') +
        '<div class="dc-feature-pair">' + (picked ? '<button type="button" class="btn btn-outline" data-dc-unselect aria-label="' + h(p.name) + ' 선택 해제">' + icon('x') + '선택 해제</button>' : '<button type="button" class="btn btn-outline" data-dc-select="' + h(p.id) + '" aria-pressed="false">' + icon('check-circle') + '이 PC 선택</button>') +
        '<button type="button" class="btn btn-outline" data-pa-add="' + h(p.id) + '" data-pa-kind="pc" aria-pressed="' + added + '" aria-label="' + h(p.name) + (added ? ' 비교에서 빼기' : ' 비교에 담기') + '">' + icon('arrows-left-right') + (added ? '비교에서 빼기' : '비교에 담기') + '</button></div>' +
        '<a class="dc-feature-detail" href="' + h(detail) + '">' + icon('clipboard-text') + '상품 상세' + icon('caret-right') + '</a><p class="dc-feature-note">부품 가격 변동으로 최종 금액이 달라질 수 있어요.</p></div>' +
        '<dl class="dc-feature-summary"><div><dt>선택한 PC</dt><dd>' + h(model.selected ? model.selected.name : '없음') + '</dd></div><div><dt>비교</dt><dd>' + model.compare.length + '</dd></div></dl></section>';
    }
    function markup() {
      var cards = candidates(), isLoading = model.state === 'loading';
      return '<header class="dc-heading"><div><p class="eyebrow">AI PC FINDER</p><h1>내게 맞는 <em>PC를 함께</em> 찾아요.</h1><p class="dc-lede">AI가 용도와 예산에 맞춰, 딱 맞는 PC를 찾아드려요.</p></div><button type="button" class="dc-new" data-dc-action="new">' + icon('arrow-counter-clockwise') + '새 대화</button></header>' +
        '<div class="dc-tabs" role="tablist" aria-label="대화와 PC"><button type="button" role="tab" id="dc-tab-chat" aria-selected="' + (model.mobile === 'chat') + '" aria-controls="dc-chat-main" tabindex="' + (model.mobile === 'chat' ? '0' : '-1') + '" data-dc-tab="chat">' + icon('chat-circle') + '대화</button><button type="button" role="tab" id="dc-tab-products" aria-selected="' + (model.mobile === 'products') + '" aria-controls="dc-chat-side" tabindex="' + (model.mobile === 'products' ? '0' : '-1') + '" data-dc-tab="products">' + icon('computer-tower') + '추천 PC <span>' + cards.length + '</span></button></div>' +
        '<div class="dc-chat-layout" data-mobile="' + model.mobile + '"><section class="dc-chat-main" id="dc-chat-main" aria-label="대화"><div class="dc-chat-log" role="log" aria-live="polite">' +
        (model.state === 'welcome' && !model.log.length ? '<div class="dc-welcome"><span class="dc-welcome-mark">' + icon('chat-circle') + '</span><h2>어떤 PC가 필요하세요?</h2><p>게임, 작업, 일상까지.<br>하고 싶은 일부터 편하게 이야기해 주세요.</p><div class="dc-welcome-prompts"><button type="button" data-dc-draft="게임용 PC를 찾고 있어요.">' + icon('game-controller') + '<b>게임용 PC</b><small class="dc-prompt-hint">질문에 담기 +</small></button><button type="button" data-dc-draft="영상 편집에 사용할 PC가 필요해요.">' + icon('video-camera') + '<b>영상 편집용</b><small class="dc-prompt-hint">질문에 담기 +</small></button><button type="button" data-dc-draft="업무에 쓸 PC가 필요해요.">' + icon('monitor') + '<b>사무·업무용</b><small class="dc-prompt-hint">질문에 담기 +</small></button></div><img class="dc-welcome-art" src="assets/images/pc-finder-core-v3.webp" width="618" height="496" alt="" aria-hidden="true" loading="lazy" decoding="async"></div>' : messages()) +
        stateNotice() + (model.notice ? '<p class="dc-local-notice" role="status">' + h(model.notice) + '</p>' : '') + '</div>' +
        '<form class="dc-composer" data-dc-form><label class="visually-hidden" for="dc-question">PC에 대해 질문하기</label><textarea id="dc-question" rows="3" placeholder="용도와 예산을 편하게 알려주세요."' + (isLoading ? ' readonly' : '') + '>' + h(model.draft) + '</textarea><div><small><span data-dc-count>' + model.draft.length.toLocaleString('ko-KR') + '</span> / 10,000자 · Shift+Enter 줄바꿈</small><button class="btn btn-primary" type="submit"' + (isLoading ? ' disabled' : '') + '>보내기' + icon('paper-plane-tilt') + '</button></div></form><p class="dc-chat-note">모르는 사양은 비워 두셔도 괜찮아요. 구매 전 상세 구성과 가격을 확인해 주세요.</p></section>' +
        '<aside class="dc-chat-side' + (model.selected ? ' has-selected' : '') + '" id="dc-chat-side" aria-label="추천 조건과 PC">' + featured() + '<section class="dc-side-panel"><h2>' + icon('clipboard-text') + '내 추천 조건</h2><div class="dc-conditions">' + [['purpose', '용도', '어떤 작업을 하시나요?'], ['budget', '예산', '아직 정하지 않아도 괜찮아요'], ['environment', '사용 환경', '모니터나 프로그램 등']].map(function (f) { return '<label><span>' + f[1] + '</span><input data-dc-condition="' + f[0] + '" value="' + h(model.conditions[f[0]]) + '" placeholder="' + h(f[2]) + '" maxlength="200"' + (isLoading ? ' disabled' : '') + '></label>'; }).join('') + '</div></section>' +
        '<section class="dc-side-panel dc-selected-panel"><h2>' + icon('check-circle') + '선택한 PC</h2>' + selection() + '</section>' + compareTray() +
        '<section class="dc-candidates"><div class="dc-candidates-heading"><h2>살펴볼 PC</h2>' + (cards.length > 1 ? '<a href="' + h(url('compare', 'normal', { ids: cards.map(function (p) { return p.id; }).join(',') })) + '">비교하기 ' + icon('caret-right') + '</a>' : '') + '</div>' +
        (cards.length ? cards.map(function (p) { return card(p, !!model.selected && String(model.selected.id) === String(p.id)); }).join('') : empty(isLoading ? '구성을 살펴보고 있어요.' : '아직 보여드릴 PC가 없어요.', isLoading ? '확인하는 동안 대화를 계속 읽을 수 있어요.' : '원하는 조건을 알려주거나 상품을 먼저 둘러보세요.', isLoading ? '' : buttonLink('PC 둘러보기', 'catalog', 'normal', {}, 'btn-small btn-outline'))) + '</section></aside></div>';
    }
    // 화면을 통째로 다시 그리면 대화 기록 스크롤이 맨 위(첫 질문)로 돌아간다. 새 질문을 보냈을 때만 그 질문을 위에 맞추고, 그 밖에는 읽던 위치를 그대로 둔다.
    function render() {
      if (!root) return;
      var old = root.querySelector('.dc-chat-log'), keep = old ? { top: old.scrollTop, users: old.querySelectorAll('.dc-message-user').length } : null;
      root.innerHTML = markup();
      remember(false);
      var log = root.querySelector('.dc-chat-log');
      if (!log || !keep) return;
      var users = log.querySelectorAll('.dc-message-user'), last = users[users.length - 1];
      if (users.length > keep.users && last) log.scrollTop = Math.max(0, last.getBoundingClientRect().top - log.getBoundingClientRect().top + log.scrollTop - 12);
      else log.scrollTop = keep.top;
    }
    function stop() { if (controller) { var c = controller; controller = null; c.abort(); } }
    // 화면이 보여 주는 PC 를 서버가 읽을 수 있게 상품번호만 보낸다(가격·이름은 보내지 않는다).
    function displayContext() {
      var cards = candidates().map(function (p) { return { product_code: Number(p.id) }; }).filter(function (c) { return Number.isSafeInteger(c.product_code) && c.product_code > 0; });
      var sel = model.selected && Number.isSafeInteger(Number(model.selected.id)) ? { product_code: Number(model.selected.id) } : null;
      // 답변 본문이 소개한 PC 묶음(최근 3개, 오래된 것 -> 최근 것). 「위 N번째」는 마지막 묶음, 「오른쪽 N번째」는 cards 를 본다.
      var sets = model.log.filter(function (m) { return m.answer && m.answer.setId && m.answer.set.length; }).slice(-3).map(function (m) {
        return { set_id: m.answer.setId, cards: m.answer.set.map(function (x) { return { product_code: x.product_code }; }) };
      });
      if (!cards.length && !sel && !sets.length) return null;
      var out = { screen: sel && !cards.length ? 'detail' : 'results', source: 'catalog', cards: cards.slice(0, 6) };
      if (sel) out.selected = sel;
      if (sets.length) out.answer_sets = sets;
      return out;
    }
    // 고객이 조건 칸에 직접 적은 것만 덧붙인다(원문은 그대로 앞에 둔다).
    function withConditions(text) {
      var extra = [['purpose', '용도'], ['budget', '예산'], ['environment', '사용 환경']].filter(function (f) { return model.dirty[f[0]] && String(model.conditions[f[0]] || '').trim(); }).map(function (f) { return f[1] + ': ' + String(model.conditions[f[0]]).trim(); });
      model.dirty = {};
      return extra.length ? text + '\n(' + extra.join(' / ') + ')' : text;
    }
    function syncConditions() {
      var t = model.convo.talk || {};
      if (Array.isArray(t.usages) && t.usages.length && !model.dirty.purpose) model.conditions.purpose = t.usages.join(' · ');
      var b = P.liveTalk.budgetText(t); if (b && !model.dirty.budget) model.conditions.budget = b;
    }
    function entryOf(turn) { return model.log.find(function (m) { return m.answer && m.answer.turnId === turn; }) || null; }
    function setCopy(entry, status, fallback) {
      entry.answer.copy = { status: status, fallback: fallback || '' }; render();
      var ta = fallback && root.querySelector('[data-pa-fallback="' + entry.answer.turnId + '"]');
      if (ta) { try { ta.focus({ preventScroll: true }); } catch (e) { ta.focus(); } ta.select(); }
    }
    // 복사: 본문 글자만. 클립보드가 받아 준 뒤에만 「복사했어요」. 막히면 고를 수 있는 글로 내민다.
    function copy(node) {
      var entry = entryOf(node.dataset.paTurn), kind = node.dataset.paCopy, text = '';
      if (!entry || !A) return;
      if (kind === 'all') text = A.strip(entry.answer.raw).trim();
      else if (kind === 'line') text = (entry.sentences || [])[Number(node.dataset.paI)] || '';
      else {
        var box = root.querySelector('[data-pa-answer="' + entry.answer.turnId + '"]');
        text = A.selectionText(window.getSelection(), box) || (lastPick && lastPick.turn === entry.answer.turnId ? lastPick.text : '');
        if (!text) { setCopy(entry, '복사할 문장을 먼저 길게 눌러 선택해 주세요.'); return; }
      }
      if (!text) return;
      A.writeClipboard(text).then(function (ok) {
        if (!entryOf(entry.answer.turnId)) return;
        if (ok) setCopy(entry, kind === 'all' ? '답변 전체를 복사했어요.' : '문장을 복사했어요.');
        else setCopy(entry, '자동 복사가 되지 않았어요. 아래 글을 길게 눌러 선택해 복사해 주세요.', text);
      });
    }
    // 비교에 담기·빼기: 예산·용도·대화는 건드리지 않는다. 담은 순서는 답변의 순번을 바꾸지 않는다(묶음은 답변이 들고 있다).
    // 비교에서 빼기는 그 상품만 목록에서 뺀다 — 대화·추천 이력·입력 중인 문장·선택한 PC·내 견적은 그대로다.
    // 같은 상품(종류+번호)은 한 번만 담긴다. 세 대가 차 있으면 다른 상품을 빼지 않고 안내만 한다.
    function addDevice(id, turn, quiet) {
      var have = P.aiDevices && P.aiDevices.data && Array.isArray(P.aiDevices.data.items) ? P.aiDevices.data.items.find(function (d) { return String(d.id) === String(id); }) : null;
      var got = have ? Promise.resolve(have) : P.aiDevices ? P.aiDevices.detail(id) : Promise.reject(new Error('no source'));
      return got.then(function (d) {
        if (inCompare(id, 'ai_device')) return '이미 비교에 담긴 상품이에요.';
        if (model.compare.length >= COMPARE_MAX) return '비교는 세 대까지 담을 수 있어요. 하나를 뺀 뒤 담아 주세요.';
        model.compare.push({ id: String(d.id), kind: 'ai_device', turn: turn || null, device: deviceOf(d) });
        return 'AI 장비를 비교에 담았어요. 지금 ' + model.compare.length + '대';
      }, function () { return quiet ? '' : '지금 확인할 수 없는 AI 장비라 담지 못했어요.'; });
    }
    function toggleCompare(id, turn, kind) {
      id = String(id); kind = kindOf(kind); var entry = turn ? entryOf(turn) : null, msg;
      function done(text) { if (entry) entry.answer.copy = { status: text, fallback: '' }; else if (text) model.notice = text; render(); }
      if (inCompare(id, kind)) { model.compare = model.compare.filter(function (c) { return !(c.id === id && c.kind === kind); }); return done('비교에서 뺐어요. 다시 담을 수 있어요.'); }
      if (kind === 'ai_device') { addDevice(id, turn).then(done); return; }
      var p = product(id);
      if (!p) msg = '지금 목록에서 확인할 수 없는 상품이라 담지 못했어요.';
      else if (model.compare.length >= COMPARE_MAX) msg = '비교는 세 대까지 담을 수 있어요. 하나를 뺀 뒤 담아 주세요.';
      else { model.compare.push({ id: id, kind: 'pc', turn: turn || null }); msg = '비교에 담았어요. 지금 ' + model.compare.length + '대' + (window.matchMedia('(max-width: 800px)').matches ? ' · 추천 PC 탭에서 볼 수 있어요.' : ' · 오른쪽 관심·비교상품에서 볼 수 있어요.'); }
      done(msg);
    }
    // 다른 화면(AI 슈퍼컴퓨터 상세·업무별 PC 칸)의 「AI로 비교하기」가 넘긴 상품을 받는다. 질문을 보내지 않는다.
    function takeCarried(list) {
      var chain = Promise.resolve(), notes = [];
      (list || []).forEach(function (x) {
        chain = chain.then(function () {
          if (inCompare(x.id, x.kind)) { notes.push('이미 비교에 담긴 상품이 있어요.'); return; }
          if (x.kind === 'ai_device') return addDevice(x.id, null, false).then(function (t) { if (t) notes.push(t); });
          var p = product(x.id);
          if (!p) notes.push('지금 목록에서 확인할 수 없는 상품이 있어 담지 못했어요.');
          else if (model.compare.length >= COMPARE_MAX) notes.push('비교는 세 대까지 담을 수 있어요. 하나를 뺀 뒤 담아 주세요.');
          else { model.compare.push({ id: String(x.id), kind: 'pc', turn: null }); notes.push('비교에 담았어요. 지금 ' + model.compare.length + '대'); }
        });
      });
      chain.then(function () { if (notes.length) { model.notice = notes[notes.length - 1]; render(); } });
    }
    function send(retry) {
      var text = retry ? model.question : model.draft;
      if (!text || !text.trim()) { model.notice = '찾고 싶은 PC나 궁금한 내용을 적어주세요.'; render(); var ta = root.querySelector('textarea'); if (ta) ta.focus(); return; }
      if (text.length > MAX_TEXT) { model.state = 'long-message'; model.draft = text; model.notice = ''; render(); return; }
      if (model.state === 'loading') return;
      var outgoing = retry && model.outgoing ? model.outgoing : withConditions(text);
      model.question = text; model.outgoing = outgoing; model.draft = text; model.notice = ''; model.handoff = false;
      if (!retry) model.log.push({ role: 'user', text: text });
      model.state = 'loading'; render();
      stop(); controller = typeof AbortController === 'function' ? new AbortController() : null; var mine = controller;
      P.liveTalk.send(model.convo, outgoing, displayContext(), mine ? mine.signal : undefined).then(function (res) {
        if (mine !== controller) return; controller = null;
        var built = res.reply && A ? A.build(res.reply, res.agentCards, res.products) : null;
        if (res.reply) model.log.push({ role: 'assistant', text: A ? A.strip(res.reply) : res.reply, answer: built });
        // 오른쪽 카드도 이 답변의 묶음 순서를 따른다(본문 1·2·3번 = 오른쪽 1·2·3번).
        if (res.products && built && built.set.length) { var byId = Object.create(null); res.products.forEach(function (x) { byId[x.id] = x; }); res.products = built.set.map(function (x) { return byId[String(x.product_code)]; }).filter(Boolean); }
        if (typeof res.commit === 'function') res.commit();   // 그린 답만 다음 질문의 이력이 된다
        model.handoff = res.handoff; syncConditions();
        if (res.products) { model.ids = res.products; model.state = res.products.length ? 'results' : 'no-results'; }
        else model.state = res.missing.length ? 'clarify' : model.ids.length ? 'results' : model.selected ? 'product' : 'clarify';
        model.draft = ''; model.outgoing = null; render();
      }, function (err) {
        if (err && err.kind === 'aborted') return;
        if (mine !== controller) return; controller = null;
        model.state = err && err.kind === 'timeout' ? 'timeout' : err && err.kind === 'offline' ? 'offline' : err && err.kind === 'rate_limited' ? 'rate-limit' : 'error';
        model.draft = text; render();
      });
    }
    return { html: '<section class="container dc-chat" data-dc-chat>' + markup() + '</section>', mount: function () {
      root = document.querySelector('[data-dc-chat]'); if (!root || root.dataset.mounted) return; root.dataset.mounted = 'true';
      if (P.compareCarry) { takeCarried(P.compareCarry.take()); P.compareCarry.listen(takeCarried); }
      if (model.selected && P.live && P.live.loadDetail && model.selected.liveDetail === 'pending') P.live.loadDetail(model.selected.id).then(render);
      // 메인 입력의 원문 한 번 전달(앞뒤 공백·줄바꿈·기호 그대로). 고객이 이미 「AI로 PC 찾기」를 눌렀으니 바로 보낸다.
      var carried = null;
      try { carried = window.sessionStorage.getItem('pai-design-question'); if (typeof carried === 'string') { try { window.sessionStorage.removeItem('pai-design-question'); } catch (ignoreRemove) { /* 원문은 아래에서 쓴다 */ } } } catch (ignoreStorage) { carried = null; }
      if (typeof carried === 'string' && carried.length) { model.draft = carried; if (carried.length > MAX_TEXT) { model.state = 'long-message'; render(); } else send(false); }
      root.addEventListener('input', function (event) {
        if (event.target.id === 'dc-question') { model.draft = event.target.value; var count = root.querySelector('[data-dc-count]'); if (count) count.textContent = model.draft.length.toLocaleString('ko-KR'); }
        if (event.target.dataset.dcCondition) { model.conditions[event.target.dataset.dcCondition] = event.target.value; model.dirty[event.target.dataset.dcCondition] = true; }
        remember(false);
      });
      root.addEventListener('submit', function (event) { if (!event.target.matches('[data-dc-form]')) return; event.preventDefault(); send(false); });
      root.addEventListener('keydown', function (event) {
        if (event.target.id === 'dc-question' && event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229 && window.matchMedia('(min-width: 801px)').matches) { event.preventDefault(); send(false); }
        if (event.target.hasAttribute('data-dc-tab') && ['ArrowLeft', 'ArrowRight', 'Home', 'End'].indexOf(event.key) >= 0) { event.preventDefault(); model.mobile = event.key === 'Home' ? 'chat' : event.key === 'End' ? 'products' : model.mobile === 'chat' ? 'products' : 'chat'; render(); root.querySelector('[data-dc-tab="' + model.mobile + '"]').focus(); }
      });
      root.addEventListener('click', function (event) {
        var node = event.target.closest('button'); if (!node || node.disabled) return;
        if (node.hasAttribute('data-pa-copy')) { copy(node); return; }
        if (node.hasAttribute('data-pa-add')) { toggleCompare(node.dataset.paAdd, node.dataset.paTurn, node.dataset.paKind); return; }
        if (node.hasAttribute('data-pa-remove')) { toggleCompare(node.dataset.paRemove, null, node.dataset.paKind); return; }
        // 선택 해제: 지금 고른 PC만 비운다 — 대화·입력 중인 문장·추천 조건·비교 목록·내 견적은 그대로다.
        if (node.hasAttribute('data-dc-unselect')) { var was = model.selected; model.selected = null; model.notice = was ? was.name + ' 선택을 해제했어요. 다른 PC를 다시 고를 수 있어요.' : ''; render(); var back = [root.querySelector('[data-dc-select="' + (was ? was.id : '') + '"]'), root.querySelector('#dc-question'), root.querySelector('.dc-selected-panel h2')].filter(function (n) { return n && n.getClientRects().length; })[0];   // 모바일 탭에서는 입력창이 숨어 있어 선택 영역 제목으로 돌린다
          if (back) { if (back.tagName === 'H2') back.setAttribute('tabindex', '-1'); back.focus({ preventScroll: true }); } return; }
        if (node.hasAttribute('data-dc-tab')) { model.mobile = node.dataset.dcTab; render(); return; }
        if (node.hasAttribute('data-dc-draft')) { model.draft = model.draft ? model.draft + '\n' + node.dataset.dcDraft : node.dataset.dcDraft; render(); root.querySelector('textarea').focus(); return; }
        if (node.hasAttribute('data-dc-select')) { var p = product(node.dataset.dcSelect); if (p) { model.selected = p; model.notice = p.name + '을 선택했어요. 상세 구성과 견적을 이어서 확인해보세요.'; render(); if (p.liveDetail === 'pending' && P.live) P.live.loadDetail(p.id).then(render); } return; }
        var action = node.dataset.dcAction;
        if (action === 'new') { stop(); restoredScroll = null; model.state = 'welcome'; model.question = ''; model.draft = ''; model.outgoing = null; model.selected = null; model.log = []; model.ids = []; model.notice = ''; model.handoff = false; model.conditions = { purpose: '', budget: '', environment: '' }; model.dirty = {}; model.convo = { talk: null, chatFlow: null, history: [], pendingText: '' }; model.compare = []; lastPick = null; model.mobile = 'chat'; render(); }
        if (action === 'retry') send(true);
        if (action === 'conditions') { model.state = 'clarify'; model.mobile = 'products'; render(); var b = root.querySelector('[data-dc-condition="budget"]'); if (b) b.focus(); }
      });
      // 모바일은 「선택한 문장 복사」를 누르는 순간 선택이 풀린다 -- 답변 안에서 마지막으로 고른 글을 기억해 둔다.
      document.addEventListener('selectionchange', function () {
        if (!A || !root) return;
        var sel = window.getSelection(), node = sel && sel.anchorNode, el = node && (node.nodeType === 1 ? node : node.parentElement), box = el && el.closest ? el.closest('[data-pa-answer]') : null;
        if (box && root.contains(box)) { var t = A.selectionText(sel, box); if (t) lastPick = { turn: box.dataset.paAnswer, text: t }; }
      });
      window.addEventListener('pagehide', function () { remember(true); stop(); });
      document.addEventListener('click', function (event) { if (root && root.isConnected && event.target.closest && event.target.closest('a[href]')) remember(true); }, true);
      if (restoredScroll) { var rs = restoredScroll; window.requestAnimationFrame(function () { var lg = root.querySelector('.dc-chat-log'); if (lg) lg.scrollTop = rs.log || 0; window.scrollTo(0, rs.page || 0); }); }
    } };
  };

P.designScreens.compare = function (ctx) {
    ctx = ctx || {};
    var state = COMPARE_STATES.indexOf(ctx.state) >= 0 ? ctx.state : 'normal';
    var rawIds = param(ctx, 'ids'), seen = Object.create(null);
    var chosen = rawIds !== null && rawIds !== undefined ? String(rawIds).split(',').slice(0, 3).map(product).filter(Boolean) : recommendations().slice(0, 3);
    chosen = chosen.filter(function (p) { var id = String(p.id); if (seen[id]) return false; seen[id] = true; return true; });
    // AI 장비(ai=상품번호,…): 서버 상세를 읽은 뒤 열에 더한다(세 대 한도 안에서). 못 읽으면 열을 만들지 않고 알린다.
    var rawAi = param(ctx, 'ai');
    if (rawAi && (rawIds === null || rawIds === undefined)) chosen = [];   // AI 장비만 고른 비교에 추천 PC를 끼워 넣지 않는다
    var aiIds = rawAi ? String(rawAi).split(',').filter(function (x) { return /^\d{1,18}$/.test(x); }).slice(0, 3) : [], aiMissing = 0;
    function isDev(p) { return p && p.kind === 'ai_device'; }
    if (state === 'empty') chosen = [];
    if (state === 'one') chosen = chosen.slice(0, 1);
    var unavailableId = state === 'unavailable' && chosen.length ? String(chosen[0].id) : null;
    var differences = false, mobileIndex = 0, root = null;
    function visibleRows() { return ROWS.filter(function (row) { return !differences || chosen.length < 2 || new Set(chosen.map(function (p) { return normalize(spec(p, row)); })).size > 1; }); }
    function actions(p) { if (isDev(p)) return '<div class="dc-compare-actions"><a class="btn btn-small btn-outline" href="' + h(deviceHref(p)) + '">상품 상세' + icon('caret-right') + '</a>' + deviceBuy(p) + '</div>'; return '<div class="dc-compare-actions">' + buttonLink('상품 상세', 'product', 'normal', { id: p.id }, 'btn-small btn-outline') + buyButton(p, String(p.id) === unavailableId || !!purchaseIssue(p)) + '</div>'; }
    function productHead(p) { var note = isDev(p) ? deviceIssue(p) : purchaseIssue(p) || (String(p.id) === unavailableId ? '구매 가능 여부 확인 중' : ''); return '<div class="dc-compare-product">' + photograph(p) + '<h2>' + h(p.name) + '</h2>' + (note ? '<p class="dc-unavailable-label">' + h(note) + '</p>' : '') + (isDev(p) ? '<span class="pa-kind">AI 장비</span>' : '') + '<button class="dc-compare-remove" type="button" data-dc-remove="' + h(p.id) + '" data-dc-kind="' + (isDev(p) ? 'ai_device' : 'pc') + '" aria-label="' + h(p.name) + ' 비교에서 빼기">' + icon('x') + '제거</button></div>'; }
    function markup() {
      var rows = visibleRows();
      var content = '';
      if (aiMissing) content += '<div class="dc-compare-notice dc-compare-warning">' + icon('warning-circle') + '<p>확인할 수 없는 AI 장비 ' + aiMissing + '대는 비교에서 뺐어요.</p></div>';
      if (!chosen.length) content += empty('비교할 PC를 골라주세요.', '최대 세 대까지 구성과 가격을 나란히 살펴볼 수 있어요.', buttonLink('PC 둘러보기', 'catalog', 'normal', {}, 'btn-primary'));
      else {
        content += (chosen.length === 1 ? '<div class="dc-compare-notice">' + icon('info') + '<p>PC를 한 대 더 고르면 서로 다른 구성을 비교할 수 있어요.</p>' + buttonLink('PC 더 고르기', 'catalog', 'normal', { ids: chosen.map(function(p){return p.id;}).join(',') }, 'btn-small btn-outline') + '</div>' : '') +
          (chosen.some(function (p) { return purchaseIssue(p) || String(p.id) === unavailableId; }) ? '<div class="dc-compare-notice dc-compare-warning">' + icon('warning-circle') + '<p>일부 상품은 판매 상태나 구성표 확인이 필요해요. 상품명 요약은 부품 구성표와 별도로 표시하며, 견적 진행은 확인 뒤에 이어갑니다.</p></div>' : '') +
          '<div class="dc-compare-table-wrap"><table class="dc-compare-table"><caption class="visually-hidden">선택한 PC의 CPU, 그래픽카드, 메모리, 저장장치와 가격 비교</caption><thead><tr><th scope="col">비교 항목</th>' + chosen.map(function (p) { return '<th scope="col">' + productHead(p) + '</th>'; }).join('') + '</tr></thead><tbody>' + rows.map(function (row) { return '<tr><th scope="row">' + h(row.label) + '</th>' + chosen.map(function (p) { return '<td' + (row.key === 'price' ? ' class="dc-compare-price"' : '') + '>' + h(spec(p, row)) + '</td>'; }).join('') + '</tr>'; }).join('') + (rows.length ? '' : '<tr><td colspan="' + (chosen.length + 1) + '" class="dc-no-difference">확인된 항목에서 서로 다른 정보가 없어요.</td></tr>') + '</tbody><tfoot><tr><th scope="row">선택</th>' + chosen.map(function (p) { return '<td>' + actions(p) + '</td>'; }).join('') + '</tr></tfoot></table></div>' +
          '<div class="dc-compare-mobile"><nav class="dc-slide-nav" aria-label="비교할 PC 전환"><button type="button" class="icon-button" data-dc-slide="previous" aria-label="이전 PC"' + (mobileIndex === 0 ? ' disabled' : '') + '>' + icon('arrow-left') + '</button><span aria-live="polite">' + (mobileIndex + 1) + ' / ' + chosen.length + '</span><button type="button" class="icon-button" data-dc-slide="next" aria-label="다음 PC"' + (mobileIndex === chosen.length - 1 ? ' disabled' : '') + '>' + icon('arrow-right') + '</button></nav><article class="dc-compare-mobile-card">' + productHead(chosen[mobileIndex]) + '<dl>' + rows.map(function (row) { return '<div><dt>' + h(row.label) + '</dt><dd>' + h(spec(chosen[mobileIndex], row)) + '</dd></div>'; }).join('') + '</dl>' + (rows.length ? '' : '<p class="dc-no-difference">확인된 항목에서 서로 다른 정보가 없어요.</p>') + actions(chosen[mobileIndex]) + '</article></div>';
      }
      return '<header class="dc-heading"><div><p class="eyebrow">COMPARE PCs</p><h1>내게 맞는 구성을 비교해보세요.</h1><p>확인된 사양과 가격을 한눈에 살펴보세요.</p></div>' + buttonLink('PC 더 고르기', 'catalog', 'normal', { ids: chosen.map(function(p){return p.id;}).join(',') }, 'btn-outline') + '</header><div class="dc-compare-toolbar"><span>선택한 PC <strong>' + chosen.length + '</strong> / 3</span><label><input type="checkbox" data-dc-differences' + (differences ? ' checked' : '') + (chosen.length < 2 ? ' disabled' : '') + '>차이만 보기</label></div>' + content + '<p class="dc-compare-footnote">세부 옵션과 구매 가능 여부는 상품 상세에서 확인해 주세요.</p>';
    }
    // 여기서 뺀 상품은 AI로 PC 찾기 대화의 관심·비교상품에서도 뺀다(2026-10-21 검수 F3 -- 같은 비교 목록이다).
    function forget(id, kind) {
      try {
        var snap = JSON.parse(window.sessionStorage.getItem('pai-finder-chat-v1') || 'null');
        if (!snap || !Array.isArray(snap.compare)) return;
        snap.compare = snap.compare.filter(function (c) { return !(String(c.id) === String(id) && (c.kind === 'ai_device' ? 'ai_device' : 'pc') === kind); });
        window.sessionStorage.setItem('pai-finder-chat-v1', JSON.stringify(snap));
      } catch (ignoreForget) { /* 저장소를 못 쓰면 이 화면만 바뀐다 */ }
    }
    function render() { mobileIndex = Math.max(0, Math.min(mobileIndex, chosen.length - 1)); if (root) root.innerHTML = markup(); }
    return { html: '<section class="container dc-compare" data-dc-compare>' + markup() + '</section>', mount: function () {
      root = document.querySelector('[data-dc-compare]'); if (!root || root.dataset.mounted) return; root.dataset.mounted = 'true';
      if (aiIds.length && P.aiDevices) Promise.all(aiIds.map(function (x) { return P.aiDevices.detail(x).then(deviceOf, function () { aiMissing += 1; return null; }); })).then(function (list) {
        list.forEach(function (d) { if (d && chosen.length < 3 && !chosen.some(function (c) { return isDev(c) && c.id === d.id; })) chosen.push(d); });
        render();
      });
      root.addEventListener('change', function (event) { if (event.target.hasAttribute('data-dc-differences')) { differences = event.target.checked; render(); root.querySelector('[data-dc-differences]').focus(); } });
      root.addEventListener('click', function (event) {
        var node = event.target.closest('button'); if (!node || node.disabled) return;
        if (node.hasAttribute('data-dc-remove')) { chosen = chosen.filter(function (p) { return !(String(p.id) === node.dataset.dcRemove && (isDev(p) ? 'ai_device' : 'pc') === (node.dataset.dcKind || 'pc')); }); if (chosen.length < 2) differences = false; forget(node.dataset.dcRemove, node.dataset.dcKind || 'pc'); render(); }
        if (node.hasAttribute('data-dc-slide')) { mobileIndex += node.dataset.dcSlide === 'next' ? 1 : -1; render(); var next = root.querySelector('[data-dc-slide="' + node.dataset.dcSlide + '"]'); if (next && !next.disabled) next.focus(); }
      });
    } };
  };
}());
