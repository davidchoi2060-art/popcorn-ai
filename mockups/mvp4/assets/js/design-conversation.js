/* 대화·비교 화면. /mvp4 에서는 대화가 실제 상담 API(live-talk.js)를 부른다(2026-10-19).
 * 비교는 실제 목록(live-catalog.js)의 상품만 쓴다. 견적 보관·상담 접수는 이 파일이 하지 않는다. */
(function () {
  'use strict';
  var P = window.PAI;
  if (!P) return;
  P.designScreens = P.designScreens || {};
  var h = P.h, icon = P.icon, MAX_TEXT = 10000;
  var CHAT_STATES = ['welcome', 'product', 'loading', 'results', 'clarify', 'budget-over', 'no-results', 'partial', 'error', 'offline', 'timeout', 'long-message'];
  var DEFAULT_QUESTION = '게임과 영상 편집용 PC를 찾고 있어요';
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
  function url(screen, state, values) { return typeof P.designHref === 'function' ? P.designHref(screen, state, values || {}) : '#'; }
  function money(p) { return p && typeof P.catalogMoney === 'function' ? P.catalogMoney(p) : '가격 확인 필요'; }
  function photograph(p, cls) {
    var source = p && p.kind === 'ai_device' ? (typeof p.image === 'string' && /^(assets\/|\/api\/product-images\/)/.test(p.image) ? p.image : null) : p && typeof P.catalogImage === 'function' ? P.catalogImage(p) : null;
    return source ? '<img class="' + h(cls || '') + '" src="' + h(source) + '" alt="' + h(p.name) + '" loading="lazy">' : '<span class="dc-photo-placeholder">' + icon('computer-tower') + '<small>상품 사진 준비 중</small></span>';
  }
  // 2026-10-20 승인 「구매 경로 분리」 -- 선택·비교한 일반 완제품의 다음 행동은 그 상품의 팝콘PC몰 페이지다(견적 보관·상담 아님).
  function buyButton(p, unsure, cls) { if (p && p.kind === 'ai_device') return deviceBuy(p); return (P.mallBuyLink && P.mallBuyLink(p, cls || 'btn btn-small btn-primary', unsure ? '팝콘PC몰에서 상품 확인' : '팝콘PC몰에서 바로 구매')) || '<button class="btn btn-small btn-primary" disabled>팝콘PC몰 구매 링크 확인 필요</button>'; }
  function buttonLink(label, screen, state, values, style) { return '<a class="btn ' + (style || 'btn-outline') + '" href="' + h(url(screen, state, values)) + '">' + h(label) + icon('caret-right') + '</a>'; }
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
  // 추천 카드(2026-10-21 확정 1번 시안 01): 사진 · 이름 · 사양 · 가격 · 고른 이유 · 찜하기 · 자세히 보기. 「이 PC 선택」은 없다.
  function card(p, extra) {
    var href = url('product', 'normal', { id: p.id, from: 'chat' }), issue = purchaseIssue(p);
    return '<article class="dc-reco-card"><a class="dc-reco-photo" href="' + h(href) + '" tabindex="-1" aria-hidden="true">' + photograph(p) + '</a>' +
      '<div class="dc-reco-info"><h3><a href="' + h(href) + '">' + h(p.name) + '</a></h3><p class="dc-reco-spec">' + h(p.summary || '세부 구성은 상세에서 확인해 주세요.') + '</p><strong>' + h(money(p)) + '</strong>' +
      (extra && extra.reason ? '<p class="dc-reco-why">' + h(extra.reason) + '</p>' : '') + (extra && extra.overBudget ? '<p class="dc-unavailable-label">예산보다 높은 상품이에요.</p>' : '') + (issue ? '<p class="dc-unavailable-label">' + h(issue) + '</p>' : '') + '</div>' +
      '<div class="dc-reco-actions">' + (P.wishButton ? P.wishButton({ kind: 'pc', id: p.id, name: p.name, cls: 'dc-reco-wish' }) : '') + '<a class="btn btn-outline dc-reco-detail" href="' + h(href) + '">자세히 보기' + icon('caret-right') + '</a></div></article>';
  }

  P.designScreens.chat = function (ctx) {
    /* /mvp4 실제 상담(2026-10-19). 승인 화면의 배치·문구는 그대로 두고, 답과 추천 PC 만 서버(P.liveTalk)에서 받는다.
     * 고객이 쓰지 않은 질문을 대신 넣지 않는다. 실패하면 입력을 그대로 두고 그 사실을 알린다. */
    ctx = ctx || {};
    var entry = ['welcome', 'product', 'clarify'].indexOf(ctx.state) >= 0 ? ctx.state : 'welcome';
    var selectedId = ctx.productId || param(ctx, 'id');
    var selected = selectedId ? product(selectedId) : null;
    var model = { state: entry === 'product' && selected ? 'product' : 'welcome', question: '', draft: '', outgoing: null, selected: selected, log: [], ids: [], mobile: 'chat', notice: '', handoff: false,
      conditions: { purpose: '', budget: '', environment: '' }, dirty: {}, convo: { talk: null, chatFlow: null, history: [], pendingText: '' }, ask: [], editing: false };
    var controller = null, root = null, lastPick = null, A = P.chatAnswer;
    // 화면 왕복 보존(2026-10-21 검수 F1): 다른 화면(AI 슈퍼컴퓨터·내 견적·상세)을 다녀와도 대화·작성 중 질문·조건·비교·선택·스크롤이
    // 남는다. 이 탭(sessionStorage)에만 두고 서버로 보내지 않는다. 「새 대화」만 비운다.
    var KEEP = 'pai-finder-chat-v1', SAVED = ['state', 'question', 'draft', 'outgoing', 'log', 'ids', 'mobile', 'handoff', 'conditions', 'dirty', 'convo', 'ask'], restoredScroll = null;
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
      if (!Array.isArray(model.log)) model.log = []; if (!Array.isArray(model.ids)) model.ids = []; if (!Array.isArray(model.ask)) model.ask = [];
      // 상품에서 「AI와 이어서 대화」로 들어오면 그 상품을 고른 채 이어 간다. 아니면 고르던 상품을 그대로 둔다.
      if (!selected && snap.selected) model.selected = product(snap.selected);
      if (entry === 'product' && selected && !model.log.length) model.state = 'product';
      restoredScroll = snap.scroll || null;   // 이 값은 지우지 않는다 -- 보관된 화면이 한 번 더 그려져도 같은 위치로 돌아간다
    }());
    // 성능 비교의 「AI에게 차이 물어보기」(2026-10-21 시안 03): 비교한 상품을 입력창 위에 밝혀 두기만 한다.
    // 질문 대상(선택)을 덮어쓰지 않고, 입력 중인 문장을 바꾸지 않고, 보내지 않는다. 「차이 질문 넣기」를 눌러야 입력창에 붙는다.
    (function askFromCompare() {
      var raw = param(ctx, 'ask'); if (!raw) return;
      var list = String(raw).split(',').map(function (s) { var m = /^pc:(\d{1,18})$/.exec(s.trim()); return m ? m[1] : null; }).filter(Boolean).slice(0, 3);
      if (list.length >= 2) model.ask = list;
    }());
    function askProducts() { return (model.ask || []).map(product).filter(Boolean); }
    function candidates() { return model.ids.map(function (x) { return product(x.id); }).filter(Boolean).slice(0, 3); }
    function messages() {
      var list = model.log.slice();
      if (model.state === 'product' && model.selected && !list.length) list.push({ role: 'assistant', text: '이 PC의 구성과 필요한 작업을 함께 살펴볼게요. 하려는 작업이나 사용하는 프로그램을 알려 주세요.' });
      var opts = { pcHref: function (id) { return url('product', 'normal', { id: id, from: 'chat' }); }, issue: purchaseIssue, money: money };
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
    function conditionsLine() {
      var bits = [model.conditions.purpose, model.conditions.budget, model.conditions.environment].map(function (v) { return String(v || '').trim(); }).filter(Boolean);
      return bits.length ? bits.join(' · ') : '용도와 예산을 알려 주시면 여기에 정리돼요.';
    }
    // 고른 이유: 추천 응답이 준 이유가 있으면 그 문장, 없으면 이 대화의 용도에 대한 팝콘 기준표 수준(있을 때만).
    function reasonOf(x, p) {
      if (x && typeof x.reason === 'string' && x.reason.trim()) return x.reason.trim();
      var fit = p.fit || {}, purpose = String(model.conditions.purpose || '');
      var u = Object.keys(fit).find(function (k) { return purpose.indexOf(k) >= 0; });
      return u ? u + ' ' + fit[u] + ' 수준 · 팝콘 기준표(실측 아님)' : '';
    }
    // 입력창 위 작은 표시: 질문 대상(상품 상세 「이 PC에 대해 AI에게 질문하기」로만 정해진다)과 비교 상품.
    function composerChips() {
      var out = '';
      if (model.selected) out += '<div class="dc-target"><span>질문 대상: <b>' + h(model.selected.name) + '</b></span><button type="button" data-dc-unselect aria-label="질문 대상 ' + h(model.selected.name) + ' 해제">' + icon('x') + '</button></div>';
      var asks = askProducts();
      if (asks.length >= 2) out += '<div class="dc-target dc-target-ask"><span>비교한 상품: <b>' + h(asks.map(function (p) { return p.name; }).join(' · ')) + '</b></span><button type="button" class="dc-target-insert" data-dc-action="ask-insert">차이 질문 넣기</button><button type="button" data-dc-action="ask-clear" aria-label="비교한 상품 표시 닫기">' + icon('x') + '</button></div>';
      return out ? '<div class="dc-targets">' + out + '</div>' : '';
    }
    function side() {
      var cards = candidates(), isLoading = model.state === 'loading', n = P.wishCount ? P.wishCount() : 0;
      var list = cards.length ? '<div class="dc-reco-list">' + cards.map(function (p) { var x = model.ids.find(function (y) { return String(y.id) === String(p.id); }); return card(p, { reason: reasonOf(x, p), overBudget: x && x.overBudget }); }).join('') + '</div>'
        : empty(isLoading ? '구성을 살펴보고 있어요.' : '아직 보여드릴 PC가 없어요.', isLoading ? '확인하는 동안 대화를 계속 읽을 수 있어요.' : '원하는 조건을 알려주거나 상품을 먼저 둘러보세요.', isLoading ? '' : buttonLink('PC 둘러보기', 'catalog', 'normal', {}, 'btn-small btn-outline'));
      var edit = model.editing ? '<div class="dc-conditions" id="dc-conditions">' + [['purpose', '용도', '어떤 작업을 하시나요?'], ['budget', '예산', '아직 정하지 않아도 괜찮아요'], ['environment', '사용 환경', '모니터나 프로그램 등']].map(function (f) { return '<label><span>' + f[1] + '</span><input data-dc-condition="' + f[0] + '" value="' + h(model.conditions[f[0]]) + '" placeholder="' + h(f[2]) + '" maxlength="200"' + (isLoading ? ' disabled' : '') + '></label>'; }).join('') + '<p>고친 조건은 다음 질문을 보낼 때 함께 전해요.</p></div>' : '';
      return '<section class="dc-reco" aria-labelledby="dc-reco-title"><header class="dc-reco-head"><div><h2 id="dc-reco-title">추천 PC</h2><p>' + h(conditionsLine()) + '</p></div><button type="button" class="btn btn-outline dc-reco-edit" data-dc-action="edit-conditions" aria-expanded="' + model.editing + '" aria-controls="dc-conditions">' + icon('funnel') + '조건 수정</button></header>' + edit + list +
        '<a class="dc-reco-cta" href="' + h(P.wishHref ? P.wishHref({ from: 'chat' }) : url('compare', 'normal')) + '" data-wish-has' + (n ? '' : ' hidden') + '><span><b>찜목록에서 <i data-wish-count>' + n + '</i>개 살펴보기</b>' + icon('arrow-right') + '</span><small>찜목록에서 골라 비교할 수 있어요.</small></a></section>';
    }
    function markup() {
      var cards = candidates(), isLoading = model.state === 'loading';
      return '<header class="dc-heading"><div><h1>내게 맞는 <em>PC를 함께</em> 찾아요.</h1><p class="dc-lede">추천 PC를 살펴보고, 마음에 드는 상품을 찜해보세요.</p></div><div class="dc-heading-actions">' + (P.wishLink ? P.wishLink({ params: { from: 'chat' }, cls: 'dc-wish-link' }) : '') + '<button type="button" class="dc-new" data-dc-action="new">' + icon('arrow-counter-clockwise') + '새 대화</button></div></header>' +
        '<div class="dc-tabs" role="tablist" aria-label="대화와 PC"><button type="button" role="tab" id="dc-tab-chat" aria-selected="' + (model.mobile === 'chat') + '" aria-controls="dc-chat-main" tabindex="' + (model.mobile === 'chat' ? '0' : '-1') + '" data-dc-tab="chat">' + icon('chat-circle') + '대화</button><button type="button" role="tab" id="dc-tab-products" aria-selected="' + (model.mobile === 'products') + '" aria-controls="dc-chat-side" tabindex="' + (model.mobile === 'products' ? '0' : '-1') + '" data-dc-tab="products">' + icon('computer-tower') + '추천 PC <span>' + cards.length + '</span></button></div>' +
        '<div class="dc-chat-layout" data-mobile="' + model.mobile + '"><section class="dc-chat-main' + (model.state === 'welcome' && !model.log.length ? ' is-welcome' : '') + '" id="dc-chat-main" aria-label="대화"><div class="dc-chat-log" role="log" aria-live="polite">' +
        (model.state === 'welcome' && !model.log.length ? '<div class="dc-welcome"><span class="dc-welcome-mark">' + icon('chat-circle') + '</span><h2>어떤 PC가 필요하세요?</h2><p>게임, 작업, 일상까지.<br>하고 싶은 일부터 편하게 이야기해 주세요.</p><div class="dc-welcome-prompts"><button type="button" data-dc-draft="게임용 PC를 찾고 있어요.">' + icon('game-controller') + '<b>게임용 PC</b><small class="dc-prompt-hint">이 용도로 질문하기</small></button><button type="button" data-dc-draft="영상 편집에 사용할 PC가 필요해요.">' + icon('video-camera') + '<b>영상편집용 PC</b><small class="dc-prompt-hint">이 용도로 질문하기</small></button><button type="button" data-dc-draft="업무에 쓸 PC가 필요해요.">' + icon('monitor') + '<b>사무·업무용 PC</b><small class="dc-prompt-hint">이 용도로 질문하기</small></button></div><img class="dc-welcome-art" src="assets/images/pc-finder-core-v3.webp" width="618" height="496" alt="" aria-hidden="true" loading="lazy" decoding="async"></div>' : messages()) +
        stateNotice() + (model.notice ? '<p class="dc-local-notice" role="status">' + h(model.notice) + '</p>' : '') + '</div>' +
        '<form class="dc-composer" data-dc-form>' + composerChips() + '<label class="visually-hidden" for="dc-question">PC에 대해 질문하기</label><textarea id="dc-question" rows="3" placeholder="' + (model.log.length ? '더 궁금한 점을 물어보세요.' : '용도와 예산을 편하게 알려주세요.') + '"' + (isLoading ? ' readonly' : '') + '>' + h(model.draft) + '</textarea><div><small><span data-dc-count>' + model.draft.length.toLocaleString('ko-KR') + '</span> / 10,000자 · Shift+Enter 줄바꿈</small><button class="btn btn-primary" type="submit"' + (isLoading ? ' disabled' : '') + '>보내기' + icon('paper-plane-tilt') + '</button></div></form><p class="dc-chat-note">모르는 사양은 비워 두셔도 괜찮아요. 구매 전 상세 구성과 가격을 확인해 주세요.</p></section>' +
        '<aside class="dc-chat-side" id="dc-chat-side" aria-label="추천 PC">' + side() + '</aside></div>';
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
      var shown = candidates(); askProducts().forEach(function (p) { if (!shown.some(function (c) { return String(c.id) === String(p.id); })) shown.push(p); });
      var cards = shown.map(function (p) { return { product_code: Number(p.id) }; }).filter(function (c) { return Number.isSafeInteger(c.product_code) && c.product_code > 0; });
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
      if (model.selected && P.live && P.live.loadDetail && model.selected.liveDetail === 'pending') P.live.loadDetail(model.selected.id).then(render);
      // 메인 입력의 원문 한 번 전달(앞뒤 공백·줄바꿈·기호 그대로). 고객이 이미 「AI로 PC 찾기」를 눌렀으니 바로 보낸다.
      var carried = null;
      try { carried = window.sessionStorage.getItem('pai-design-question'); if (typeof carried === 'string') { try { window.sessionStorage.removeItem('pai-design-question'); } catch (ignoreRemove) { /* 원문은 아래에서 쓴다 */ } } } catch (ignoreStorage) { carried = null; }
      if (param(ctx, 'ask') && window.history && window.history.replaceState) { try { var u0 = new URL(window.location.href); u0.searchParams.delete('ask'); window.history.replaceState(window.history.state, '', u0.href); } catch (ignoreAsk) { /* 주소 정리만 빠진다 */ } }
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
        // 질문 대상 해제: 질문 대상만 비운다 — 대화·입력 중인 문장·추천 조건·찜목록·내 견적은 그대로다.
        if (node.hasAttribute('data-dc-unselect')) { var was = model.selected; model.selected = null; model.notice = was ? '질문 대상(' + was.name + ')을 해제했어요.' : ''; render(); var ta0 = root.querySelector('#dc-question'); if (ta0 && ta0.getClientRects().length) ta0.focus({ preventScroll: true }); return; }
        if (node.hasAttribute('data-dc-tab')) { model.mobile = node.dataset.dcTab; render(); return; }
        if (node.hasAttribute('data-dc-draft')) { model.draft = model.draft ? model.draft + '\n' + node.dataset.dcDraft : node.dataset.dcDraft; render(); root.querySelector('textarea').focus(); return; }
        var action = node.dataset.dcAction;
        if (action === 'new') { stop(); restoredScroll = null; model.state = 'welcome'; model.question = ''; model.draft = ''; model.outgoing = null; model.selected = null; model.log = []; model.ids = []; model.notice = ''; model.handoff = false; model.conditions = { purpose: '', budget: '', environment: '' }; model.dirty = {}; model.convo = { talk: null, chatFlow: null, history: [], pendingText: '' }; model.ask = []; model.editing = false; lastPick = null; model.mobile = 'chat'; render(); }
        if (action === 'retry') send(true);
        if (action === 'conditions') { model.state = 'clarify'; model.mobile = 'products'; model.editing = true; render(); var b = root.querySelector('[data-dc-condition="budget"]'); if (b) b.focus(); }
        if (action === 'edit-conditions') { model.editing = !model.editing; render(); var e1 = root.querySelector(model.editing ? '[data-dc-condition="purpose"]' : '[data-dc-action="edit-conditions"]'); if (e1) e1.focus(); }
        if (action === 'ask-clear') { model.ask = []; render(); var ta1 = root.querySelector('#dc-question'); if (ta1) ta1.focus(); }
        if (action === 'ask-insert') {
          var asks = askProducts();
          if (asks.length >= 2) { var line = asks.map(function (p) { return p.name + '(상품번호 ' + p.id + ')'; }).join('와 ') + '의 차이를 알려 주세요.'; model.draft = model.draft ? model.draft + '\n' + line : line; model.ask = []; render(); var ta2 = root.querySelector('#dc-question'); if (ta2) { ta2.focus(); ta2.setSelectionRange(ta2.value.length, ta2.value.length); } }
        }
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

// 찜목록·성능 비교 화면(wishlist-compare.js)이 같은 상품 판정·사진·구매 버튼을 쓴다 — 두 벌 두지 않는다.
  P.dcHelpers = { product: product, purchaseIssue: purchaseIssue, photograph: photograph, money: money, deviceOf: deviceOf, deviceIssue: deviceIssue, buyButton: buyButton };
}());
