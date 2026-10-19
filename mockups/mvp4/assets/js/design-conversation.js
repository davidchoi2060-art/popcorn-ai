/* Design-only conversation and comparison states. Reads the supplied catalog
 * snapshot only. Never calls an API, changes a product, saves a quote, or submits
 * a consultation. Local delays advance the explicitly selected design state. */
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
    if (p.source && p.source.kind === 'historical') return '현재 판매 여부 확인 필요';
    if (p.isSelling !== true) return p.saleStatus === '품절' ? '품절 · 판매 여부 확인 필요' : '판매 여부 확인 필요';
    if (p.statusKey === 'oos' || p.stockQty === 0) return '재고·판매 상태 확인 필요';
    if (p.reviewRequired === true) return '상품 검수 필요';
    if (!(typeof p.price === 'number' && isFinite(p.price) && p.price > 0)) return '가격 확인 필요';
    if (p.bomStatus === 'mismatch') return '상품과 구성표 일치 여부 확인 필요';
    if (p.bomStatus === 'missing' || !p.configurationId || !Array.isArray(p.specs) || !p.specs.length) return '부품 구성표 확인 필요';
    return '';
  }
  function product(id) {
    if (id === null || id === undefined || id === '') return null;
    if (typeof P.getCatalogProduct === 'function') { try { return P.getCatalogProduct(String(id)) || null; } catch (error) { return null; } }
    return products().find(function (p) { return String(p.id) === String(id); }) || null;
  }
  function url(screen, state, values) { return typeof P.designHref === 'function' ? P.designHref(screen, state, values || {}) : '#'; }
  function money(p) { return p && typeof P.catalogMoney === 'function' ? P.catalogMoney(p) : '가격 확인 필요'; }
  function photograph(p, cls) {
    var source = p && typeof P.catalogImage === 'function' ? P.catalogImage(p) : null;
    return source ? '<img class="' + h(cls || '') + '" src="' + h(source) + '" alt="' + h(p.name) + '" loading="lazy">' : '<span class="dc-photo-placeholder">' + icon('computer-tower') + '<small>상품 사진 준비 중</small></span>';
  }
  function buttonLink(label, screen, state, values, style) { return '<a class="btn ' + (style || 'btn-outline') + '" href="' + h(url(screen, state, values)) + '">' + h(label) + icon('caret-right') + '</a>'; }
  function normalize(value) { return String(value || '').toLowerCase().replace(/[\s·:()_-]/g, ''); }
  function spec(p, row) {
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
      '<div class="dc-product-actions"><button type="button" class="btn btn-small ' + (selected ? 'btn-primary' : 'btn-outline') + '" data-dc-select="' + h(p.id) + '" aria-pressed="' + String(selected) + '">' + (selected ? '선택한 PC' : '이 PC 선택') + '</button><a href="' + h(url('product', 'normal', { id: p.id })) + '">상세 ' + icon('caret-right') + '</a></div></div></article>';
  }

  P.designScreens.chat = function (ctx) {
    ctx = ctx || {};
    var initial = CHAT_STATES.indexOf(ctx.state) >= 0 ? ctx.state : 'welcome';
    var suppliedQuestion = param(ctx, 'text');
    var question = typeof suppliedQuestion === 'string' ? suppliedQuestion : initial === 'welcome' ? '' : initial === 'product' ? '이 PC로 게임과 영상 편집을 할 수 있을까요?' : initial === 'budget-over' ? '예산은 100만 원이고, 게임과 영상 편집용 PC를 찾고 있어요.' : DEFAULT_QUESTION;
    var selectedId = ctx.productId || param(ctx, 'id');
    var selected = selectedId ? product(selectedId) : initial === 'product' ? recommendations()[0] || null : null;
    var draft = ['loading', 'error', 'offline', 'timeout', 'long-message'].indexOf(initial) >= 0 ? question : '';
    if (initial === 'long-message' && typeof suppliedQuestion !== 'string') draft = (DEFAULT_QUESTION + '.\n현재 사용하는 프로그램과 모니터 환경도 함께 살펴보고 싶어요.\n').repeat(180);
    var model = { state: initial, question: initial === 'long-message' ? '' : question, draft: draft, selected: selected, history: [], mobile: 'chat', notice: '', suppressReply: false, conditions: { purpose: initial === 'welcome' ? '' : '게임 · 영상 편집', budget: String(param(ctx, 'budget') || (initial === 'budget-over' ? '100만 원' : '')), environment: '' } };
    var timer = null, generation = 0, root = null;

    function candidates() {
      if (['results', 'budget-over', 'partial'].indexOf(model.state) < 0) return [];
      var items = recommendations();
      if (model.state === 'budget-over' && model.conditions.budget === '100만 원') items = items.filter(function (p) { return typeof p.price === 'number' && p.price > 1000000; });
      return items.slice(0, model.state === 'partial' ? 2 : 3);
    }
    function messages() {
      var result = model.history.slice();
      if (model.question) result.push({ role: 'user', text: model.question });
      var reply = model.suppressReply ? '' : replyFor(model.state);
      if (!model.suppressReply && model.state === 'product' && model.selected && purchaseIssue(model.selected)) reply = '선택한 상품은 ' + purchaseIssue(model.selected) + ' 상태예요. 필요한 작업이나 확인하고 싶은 내용을 알려 주세요.';
      if (reply) result.push({ role: 'assistant', text: reply });
      return result.map(function (m) { return '<article class="dc-message dc-message-' + m.role + '"><span>' + (m.role === 'user' ? '나' : '팝콘AI') + '</span><p>' + h(m.text) + '</p></article>'; }).join('');
    }
    function stateNotice() {
      if (model.suppressReply) return '';
      if (model.state === 'loading') return '<div class="dc-state-box dc-loading" role="status">' + icon('clock') + '<div><strong>조건과 구성을 살펴보고 있어요.</strong><p>조금만 기다려 주세요. 입력한 내용은 그대로 남아 있어요.</p><button type="button" data-dc-action="stop">기다리기 중단</button></div></div>';
      var errors = { error: ['답변을 불러오지 못했어요.', '입력한 내용을 유지했어요. 다시 보내거나 내용을 고칠 수 있어요.'], offline: ['연결 상태를 확인해 주세요.', '대화를 이어가지 못했어요. 연결을 확인한 뒤 다시 시도해 주세요.'], timeout: ['답변이 예상보다 오래 걸리고 있어요.', '응답을 확인하지 못했어요. 입력한 내용을 보관한 채 다시 시도할 수 있어요.'], 'long-message': ['내용을 조금 나누어 보내주세요.', '한 번에 10,000자까지 입력할 수 있어요. 원문은 입력창에 그대로 두었어요.'] };
      if (errors[model.state]) { var item = errors[model.state]; return '<div class="dc-state-box dc-error" role="alert">' + icon('warning-circle') + '<div><strong>' + h(item[0]) + '</strong><p>' + h(item[1]) + '</p>' + (model.state !== 'long-message' ? '<button type="button" data-dc-action="retry">' + icon('arrow-counter-clockwise') + '다시 시도</button>' : '') + '</div></div>'; }
      if (model.state === 'partial') return '<div class="dc-inline-actions"><button class="btn btn-small btn-outline" type="button" data-dc-action="retry">' + icon('arrow-counter-clockwise') + '상품 정보 다시 확인</button></div>';
      if (model.state === 'budget-over') return '<div class="dc-inline-actions"><button class="btn btn-small btn-primary" type="button" data-dc-action="expand-budget">예산 범위 넓혀서 보기</button><button class="btn btn-small btn-outline" type="button" data-dc-action="keep-budget">예산 유지하고 다시 찾기</button></div>';
      if (model.state === 'clarify') return '<div class="dc-inline-actions"><button class="dc-draft-chip" type="button" data-dc-draft="예산은 아직 정하지 않았어요.">예산은 아직 몰라요</button><button class="dc-draft-chip" type="button" data-dc-draft="어떤 사양이 필요한지 잘 모르겠어요.">사양을 잘 몰라요</button></div>';
      if (model.state === 'no-results') return '<div class="dc-inline-actions"><button class="btn btn-small btn-primary" type="button" data-dc-action="conditions">조건 다시 정하기</button>' + buttonLink('PC 둘러보기', 'catalog', 'normal', {}, 'btn-small btn-outline') + '</div>';
      return '';
    }
    function selection() {
      if (!model.selected) return empty('아직 선택한 PC가 없어요.', '상품의 구성을 비교하고 마음에 드는 PC를 골라보세요.');
      var p = model.selected;
      var blocked = purchaseIssue(p);
      return '<div class="dc-chosen"><div class="dc-chosen-top">' + photograph(p) + '<div><strong>' + h(p.name) + '</strong><p>' + h(money(p)) + '</p></div></div>' + (blocked ? '<p class="dc-unavailable-label" role="status">' + h(blocked) + '</p>' : '') + '<div class="dc-chosen-links">' + buttonLink('선택 PC 상세', 'product', 'normal', { id: p.id }, 'btn-small btn-outline') + (blocked ? buttonLink('상품·구성 문의', 'consult', 'normal', { id: p.id }, 'btn-small btn-outline') + '<button class="btn btn-small btn-primary" disabled>견적 전 확인 필요</button>' : buttonLink('부품 구성 살펴보기', 'options', 'normal', { id: p.id }, 'btn-small btn-outline') + buttonLink('선택 상품 견적 확인', 'quote', 'normal', { id: p.id }, 'btn-small btn-primary')) + '</div></div>';
    }
    function markup() {
      var cards = candidates(), isLoading = model.state === 'loading';
      return '<header class="dc-heading"><div><p class="eyebrow">AI PC FINDER</p><h1>내게 맞는 PC를 함께 찾아요.</h1></div><button type="button" class="dc-new" data-dc-action="new">' + icon('arrow-counter-clockwise') + '새 대화</button></header>' +
        '<div class="dc-tabs" role="tablist" aria-label="대화와 PC"><button type="button" role="tab" id="dc-tab-chat" aria-selected="' + (model.mobile === 'chat') + '" aria-controls="dc-chat-main" tabindex="' + (model.mobile === 'chat' ? '0' : '-1') + '" data-dc-tab="chat">' + icon('chat-circle') + '대화</button><button type="button" role="tab" id="dc-tab-products" aria-selected="' + (model.mobile === 'products') + '" aria-controls="dc-chat-side" tabindex="' + (model.mobile === 'products' ? '0' : '-1') + '" data-dc-tab="products">' + icon('computer-tower') + '추천 PC <span>' + cards.length + '</span></button></div>' +
        '<div class="dc-chat-layout" data-mobile="' + model.mobile + '"><section class="dc-chat-main" id="dc-chat-main" aria-label="대화"><div class="dc-chat-log" role="log" aria-live="polite">' +
        (model.state === 'welcome' ? '<div class="dc-welcome"><span class="dc-welcome-mark">' + icon('chat-circle') + '</span><h2>어떤 PC가 필요하세요?</h2><p>게임, 작업, 일상까지.<br>하고 싶은 일부터 편하게 이야기해 주세요.</p><div class="dc-welcome-prompts"><button type="button" data-dc-draft="게임용 PC를 찾고 있어요.">' + icon('game-controller') + '게임용 PC</button><button type="button" data-dc-draft="영상 편집에 사용할 PC가 필요해요.">' + icon('video-camera') + '영상 편집용</button><button type="button" data-dc-draft="업무에 쓸 PC가 필요해요.">' + icon('monitor') + '사무·업무용</button></div></div>' : messages()) +
        stateNotice() + (model.notice ? '<p class="dc-local-notice" role="status">' + h(model.notice) + '</p>' : '') + '</div>' +
        '<form class="dc-composer" data-dc-form><label class="visually-hidden" for="dc-question">PC에 대해 질문하기</label><textarea id="dc-question" rows="3" placeholder="용도와 예산을 편하게 알려주세요."' + (isLoading ? ' readonly' : '') + '>' + h(model.draft) + '</textarea><div><small><span data-dc-count>' + model.draft.length.toLocaleString('ko-KR') + '</span> / 10,000자 · Shift+Enter 줄바꿈</small><button class="btn btn-primary" type="submit"' + (isLoading ? ' disabled' : '') + '>보내기' + icon('paper-plane-tilt') + '</button></div></form><p class="dc-chat-note">모르는 사양은 비워 두셔도 괜찮아요. 구매 전 상세 구성과 가격을 확인해 주세요.</p></section>' +
        '<aside class="dc-chat-side' + (model.selected ? ' has-selected' : '') + '" id="dc-chat-side" aria-label="추천 조건과 PC"><section class="dc-side-panel"><h2>' + icon('clipboard-text') + '내 추천 조건</h2><div class="dc-conditions">' + [['purpose', '용도', '어떤 작업을 하시나요?'], ['budget', '예산', '아직 정하지 않아도 괜찮아요'], ['environment', '사용 환경', '모니터나 프로그램 등']].map(function (f) { return '<label><span>' + f[1] + '</span><input data-dc-condition="' + f[0] + '" value="' + h(model.conditions[f[0]]) + '" placeholder="' + h(f[2]) + '" maxlength="200"' + (isLoading ? ' disabled' : '') + '></label>'; }).join('') + '</div></section>' +
        '<section class="dc-side-panel dc-selected-panel"><h2>' + icon('check-circle') + '선택한 PC</h2>' + selection() + '</section>' +
        '<section class="dc-candidates"><div class="dc-candidates-heading"><h2>살펴볼 PC</h2>' + (cards.length > 1 ? '<a href="' + h(url('compare', 'normal', { ids: cards.map(function (p) { return p.id; }).join(',') })) + '">비교하기 ' + icon('caret-right') + '</a>' : '') + '</div>' +
        (cards.length ? cards.map(function (p) { return card(p, !!model.selected && String(model.selected.id) === String(p.id)); }).join('') : empty(isLoading ? '구성을 살펴보고 있어요.' : '아직 보여드릴 PC가 없어요.', isLoading ? '확인하는 동안 대화를 계속 읽을 수 있어요.' : '원하는 조건을 알려주거나 상품을 먼저 둘러보세요.', isLoading ? '' : buttonLink('PC 둘러보기', 'catalog', 'normal', {}, 'btn-small btn-outline'))) + '</section></aside></div>';
    }
    function render() { if (root) root.innerHTML = markup(); }
    function stop() { generation++; if (timer !== null) { window.clearTimeout(timer); timer = null; } }
    function send(retry) {
      var text = retry ? model.draft || model.question : model.draft;
      if (!text.trim()) { model.notice = '찾고 싶은 PC나 궁금한 내용을 적어주세요.'; render(); root.querySelector('textarea').focus(); return; }
      if (text.length > MAX_TEXT) { model.state = 'long-message'; model.draft = text; model.notice = ''; render(); return; }
      if (model.state === 'loading') return;
      var oldReply = model.suppressReply ? '' : replyFor(model.state);
      if (!retry && model.question && oldReply) { model.history.push({ role: 'user', text: model.question }, { role: 'assistant', text: oldReply }); }
      model.question = text; model.draft = text; model.state = 'loading'; model.notice = ''; model.suppressReply = false; render();
      stop(); var turn = generation;
      timer = window.setTimeout(function () { if (turn !== generation) return; timer = null; model.state = recommendations().length ? 'results' : 'no-results'; model.draft = ''; render(); }, 1000);
    }
    return { html: '<section class="container dc-chat" data-dc-chat>' + markup() + '</section>', mount: function () {
      root = document.querySelector('[data-dc-chat]'); if (!root || root.dataset.mounted) return; root.dataset.mounted = 'true';
      // The home form's one-purpose handoff. Never enumerate/clear other keys.
      // Apply before removing so an unavailable storage write cannot erase text.
      try {
        var carried = window.sessionStorage.getItem('pai-design-question');
        if (typeof carried === 'string') {
          model.question = carried; model.draft = carried;
          if (carried.length > MAX_TEXT) model.state = 'long-message';
          try { window.sessionStorage.removeItem('pai-design-question'); } catch (ignoreRemove) { /* The original draft remains in both locations. */ }
          render();
        }
      } catch (ignoreStorage) { /* No fallback text is recovered from unrelated stores or URLs. */ }
      root.addEventListener('input', function (event) {
        if (event.target.id === 'dc-question') { model.draft = event.target.value; var count = root.querySelector('[data-dc-count]'); if (count) count.textContent = model.draft.length.toLocaleString('ko-KR'); }
        if (event.target.dataset.dcCondition) model.conditions[event.target.dataset.dcCondition] = event.target.value;
      });
      root.addEventListener('submit', function (event) { if (!event.target.matches('[data-dc-form]')) return; event.preventDefault(); send(false); });
      root.addEventListener('keydown', function (event) {
        if (event.target.id === 'dc-question' && event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229 && window.matchMedia('(min-width: 801px)').matches) { event.preventDefault(); send(false); }
        if (event.target.hasAttribute('data-dc-tab') && ['ArrowLeft', 'ArrowRight', 'Home', 'End'].indexOf(event.key) >= 0) { event.preventDefault(); model.mobile = event.key === 'Home' ? 'chat' : event.key === 'End' ? 'products' : model.mobile === 'chat' ? 'products' : 'chat'; render(); root.querySelector('[data-dc-tab="' + model.mobile + '"]').focus(); }
      });
      root.addEventListener('click', function (event) {
        var node = event.target.closest('button'); if (!node || node.disabled) return;
        if (node.hasAttribute('data-dc-tab')) { model.mobile = node.dataset.dcTab; render(); return; }
        if (node.hasAttribute('data-dc-draft')) { model.draft = model.draft ? model.draft + '\n' + node.dataset.dcDraft : node.dataset.dcDraft; render(); root.querySelector('textarea').focus(); return; }
        if (node.hasAttribute('data-dc-select')) { var p = product(node.dataset.dcSelect); if (p) { model.selected = p; model.notice = p.name + '을 선택했어요. 상세 구성과 견적을 이어서 확인해보세요.'; render(); } return; }
        var action = node.dataset.dcAction;
        if (action === 'new') { stop(); model.state = 'welcome'; model.question = ''; model.draft = ''; model.selected = null; model.history = []; model.notice = ''; model.suppressReply = false; model.conditions = { purpose: '', budget: '', environment: '' }; model.mobile = 'chat'; render(); }
        if (action === 'stop') { stop(); model.state = 'clarify'; model.suppressReply = true; model.notice = '기다리기를 중단했어요. 입력한 내용은 그대로 남아 있어요.'; render(); }
        if (action === 'retry') send(true);
        if (action === 'expand-budget') { model.conditions.budget = '예산 조정 가능'; model.state = recommendations().length ? 'results' : 'no-results'; model.suppressReply = false; render(); }
        if (action === 'keep-budget' || action === 'conditions') { model.state = 'clarify'; model.mobile = 'products'; model.suppressReply = false; model.notice = action === 'keep-budget' ? '예산은 유지하고 꼭 필요한 작업부터 다시 살펴볼게요.' : ''; render(); root.querySelector('[data-dc-condition="budget"]').focus(); }
      });
      window.addEventListener('pagehide', stop, { once: true });
    } };
  };

  P.designScreens.compare = function (ctx) {
    ctx = ctx || {};
    var state = COMPARE_STATES.indexOf(ctx.state) >= 0 ? ctx.state : 'normal';
    var rawIds = param(ctx, 'ids'), seen = Object.create(null);
    var chosen = rawIds !== null && rawIds !== undefined ? String(rawIds).split(',').slice(0, 3).map(product).filter(Boolean) : recommendations().slice(0, 3);
    chosen = chosen.filter(function (p) { var id = String(p.id); if (seen[id]) return false; seen[id] = true; return true; });
    if (state === 'empty') chosen = [];
    if (state === 'one') chosen = chosen.slice(0, 1);
    var unavailableId = state === 'unavailable' && chosen.length ? String(chosen[0].id) : null;
    var differences = false, mobileIndex = 0, root = null;
    function visibleRows() { return ROWS.filter(function (row) { return !differences || chosen.length < 2 || new Set(chosen.map(function (p) { return normalize(spec(p, row)); })).size > 1; }); }
    function actions(p) { return '<div class="dc-compare-actions">' + buttonLink('상품 상세', 'product', 'normal', { id: p.id }, 'btn-small btn-outline') + (String(p.id) === unavailableId || purchaseIssue(p) ? '<button class="btn btn-small btn-primary" disabled>견적 전 확인 필요</button>' + buttonLink('상품·구성 문의', 'consult', 'normal', { id: p.id }, 'btn-small btn-outline') : buttonLink('선택 상품 견적 확인', 'quote', 'normal', { id: p.id }, 'btn-small btn-primary')) + '</div>'; }
    function productHead(p) { var note = purchaseIssue(p) || (String(p.id) === unavailableId ? '구매 가능 여부 확인 중' : ''); return '<div class="dc-compare-product">' + photograph(p) + '<h2>' + h(p.name) + '</h2>' + (note ? '<p class="dc-unavailable-label">' + h(note) + '</p>' : '') + '<button class="dc-compare-remove" type="button" data-dc-remove="' + h(p.id) + '" aria-label="' + h(p.name) + ' 비교에서 제거">' + icon('x') + '제거</button></div>'; }
    function markup() {
      var rows = visibleRows();
      var content = '';
      if (!chosen.length) content = empty('비교할 PC를 골라주세요.', '최대 세 대까지 구성과 가격을 나란히 살펴볼 수 있어요.', buttonLink('PC 둘러보기', 'catalog', 'normal', {}, 'btn-primary'));
      else {
        content = (chosen.length === 1 ? '<div class="dc-compare-notice">' + icon('info') + '<p>PC를 한 대 더 고르면 서로 다른 구성을 비교할 수 있어요.</p>' + buttonLink('PC 더 고르기', 'catalog', 'normal', { ids: chosen.map(function(p){return p.id;}).join(',') }, 'btn-small btn-outline') + '</div>' : '') +
          (chosen.some(function (p) { return purchaseIssue(p) || String(p.id) === unavailableId; }) ? '<div class="dc-compare-notice dc-compare-warning">' + icon('warning-circle') + '<p>일부 상품은 판매 상태나 구성표 확인이 필요해요. 상품명 요약은 부품 구성표와 별도로 표시하며, 견적 진행은 확인 뒤에 이어갑니다.</p></div>' : '') +
          '<div class="dc-compare-table-wrap"><table class="dc-compare-table"><caption class="visually-hidden">선택한 PC의 CPU, 그래픽카드, 메모리, 저장장치와 가격 비교</caption><thead><tr><th scope="col">비교 항목</th>' + chosen.map(function (p) { return '<th scope="col">' + productHead(p) + '</th>'; }).join('') + '</tr></thead><tbody>' + rows.map(function (row) { return '<tr><th scope="row">' + h(row.label) + '</th>' + chosen.map(function (p) { return '<td' + (row.key === 'price' ? ' class="dc-compare-price"' : '') + '>' + h(spec(p, row)) + '</td>'; }).join('') + '</tr>'; }).join('') + (rows.length ? '' : '<tr><td colspan="' + (chosen.length + 1) + '" class="dc-no-difference">확인된 항목에서 서로 다른 정보가 없어요.</td></tr>') + '</tbody><tfoot><tr><th scope="row">선택</th>' + chosen.map(function (p) { return '<td>' + actions(p) + '</td>'; }).join('') + '</tr></tfoot></table></div>' +
          '<div class="dc-compare-mobile"><nav class="dc-slide-nav" aria-label="비교할 PC 전환"><button type="button" class="icon-button" data-dc-slide="previous" aria-label="이전 PC"' + (mobileIndex === 0 ? ' disabled' : '') + '>' + icon('arrow-left') + '</button><span aria-live="polite">' + (mobileIndex + 1) + ' / ' + chosen.length + '</span><button type="button" class="icon-button" data-dc-slide="next" aria-label="다음 PC"' + (mobileIndex === chosen.length - 1 ? ' disabled' : '') + '>' + icon('arrow-right') + '</button></nav><article class="dc-compare-mobile-card">' + productHead(chosen[mobileIndex]) + '<dl>' + rows.map(function (row) { return '<div><dt>' + h(row.label) + '</dt><dd>' + h(spec(chosen[mobileIndex], row)) + '</dd></div>'; }).join('') + '</dl>' + (rows.length ? '' : '<p class="dc-no-difference">확인된 항목에서 서로 다른 정보가 없어요.</p>') + actions(chosen[mobileIndex]) + '</article></div>';
      }
      return '<header class="dc-heading"><div><p class="eyebrow">COMPARE PCs</p><h1>내게 맞는 구성을 비교해보세요.</h1><p>확인된 사양과 가격을 한눈에 살펴보세요.</p></div>' + buttonLink('PC 더 고르기', 'catalog', 'normal', { ids: chosen.map(function(p){return p.id;}).join(',') }, 'btn-outline') + '</header><div class="dc-compare-toolbar"><span>선택한 PC <strong>' + chosen.length + '</strong> / 3</span><label><input type="checkbox" data-dc-differences' + (differences ? ' checked' : '') + (chosen.length < 2 ? ' disabled' : '') + '>차이만 보기</label></div>' + content + '<p class="dc-compare-footnote">세부 옵션과 구매 가능 여부는 상품 상세에서 확인해 주세요.</p>';
    }
    function render() { mobileIndex = Math.max(0, Math.min(mobileIndex, chosen.length - 1)); if (root) root.innerHTML = markup(); }
    return { html: '<section class="container dc-compare" data-dc-compare>' + markup() + '</section>', mount: function () {
      root = document.querySelector('[data-dc-compare]'); if (!root || root.dataset.mounted) return; root.dataset.mounted = 'true';
      root.addEventListener('change', function (event) { if (event.target.hasAttribute('data-dc-differences')) { differences = event.target.checked; render(); root.querySelector('[data-dc-differences]').focus(); } });
      root.addEventListener('click', function (event) {
        var node = event.target.closest('button'); if (!node || node.disabled) return;
        if (node.hasAttribute('data-dc-remove')) { chosen = chosen.filter(function (p) { return String(p.id) !== node.dataset.dcRemove; }); if (chosen.length < 2) differences = false; render(); }
        if (node.hasAttribute('data-dc-slide')) { mobileIndex += node.dataset.dcSlide === 'next' ? 1 : -1; render(); var next = root.querySelector('[data-dc-slide="' + node.dataset.dcSlide + '"]'); if (next && !next.disabled) next.focus(); }
      });
    } };
  };
}());
