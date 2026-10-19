/* PC finder UI, with an explicitly supplied service adapter only.
 * No network, storage, live API calls, invented answers, or built-in recommendations.
 *
 * Optional entry adapter, consumed once at mount:
 *   PAI.finderEntry.consume() -> { text, productId, source, purpose? } | null
 * Only source=home with a nonblank text represents a previous send action and
 * causes one automatic attempt. Product/category entries merely fill the draft.
 * Direct query parameters never establish a selected product or a message.
 *
 * Optional async UI service contract (map to verified server contracts separately):
 *   PAI.sendPCMessage({ text, history:[{role,text}], selectedProductId, source,
 *                      conditions:{purpose,budget,environment} })
 *   -> Promise<{ reply:string, products?:Array<string|{id:string}>,
 *                 conditions?:{purpose?:string,budget?:string,environment?:string} }>
 * Product identifiers must resolve to PAI.data.products. Reply text is plain text.
 * The adapter owns verified product mapping, actual API calls, error reporting,
 * and server state. This UI contract is not the production /api/talk contract.
 */
(function () {
  'use strict';
  var P = window.PAI;
  if (!P) return;
  var h = P.h, icon = P.icon, MAX_TEXT = 20000, MAX_HISTORY = 12, REPLY_TIMEOUT = 45000;
  var CONDITION_KEYS = ['purpose', 'budget', 'environment'];
  var PROMPTS = [
    { icon: 'game-controller', label: '게임용 PC를 찾고 있어요', hint: '즐기는 게임부터 함께', text: '게임용 PC를 찾고 있어요.' },
    { icon: 'monitor', label: '업무용 PC가 필요해요', hint: '매일 하는 작업에 맞게', text: '업무용 PC가 필요해요.' },
    { icon: 'video-camera', label: '영상·디자인 작업을 해요', hint: '사용하는 프로그램부터', text: '영상 편집과 디자인 작업에 쓸 PC를 찾고 있어요.' }
  ];

  function plainObject(value) { return !!value && typeof value === 'object' && !Array.isArray(value); }
  function findProduct(id) {
    if (typeof id !== 'string' || !id) return null;
    return (Array.isArray(P.data.products) ? P.data.products : []).find(function (product) { return product.id === id; }) || null;
  }
  function cleanConditions(value, previous) {
    var result = Object.assign({ purpose: '', budget: '', environment: '' }, previous || {});
    if (!plainObject(value)) return result;
    CONDITION_KEYS.forEach(function (key) {
      if (typeof value[key] === 'string' && value[key].length <= 200) result[key] = value[key];
    });
    return result;
  }
  function productImage(product) {
    return typeof product.image === 'string' && /^[a-zA-Z0-9][a-zA-Z0-9._-]*\.(?:png|webp|jpe?g)$/i.test(product.image) ? P.image(product.image) : '';
  }
  function productCards(products) {
    if (!products.length) return '';
    return '<div class="finder-products">' + products.map(function (product) {
      var src = productImage(product);
      return '<article class="finder-product">' + (src ? '<img src="' + h(src) + '" alt="' + h(product.name) + '" loading="lazy">' : '') +
        '<h3>' + h(product.name) + '</h3><p>' + h(product.summary || '') + '</p>' +
        '<p class="finder-product-price">' + h(P.money(product.price)) + '</p>' +
        '<button class="btn btn-outline" type="button" data-finder-select="' + h(product.id) + '">이 PC 선택' + icon('caret-right') + '</button></article>';
    }).join('') + '</div>';
  }
  function validateReply(response) {
    if (!plainObject(response) || typeof response.reply !== 'string' || !response.reply.trim() || response.reply.length > MAX_TEXT) throw new Error('invalid_response');
    if (response.products !== undefined && !Array.isArray(response.products)) throw new Error('invalid_response');
    if (response.conditions !== undefined && !plainObject(response.conditions)) throw new Error('invalid_response');
    var seen = Object.create(null), products = [];
    (response.products || []).slice(0, 12).forEach(function (value) {
      var id = typeof value === 'string' ? value : plainObject(value) && value.id;
      var product = findProduct(id);
      if (product && !seen[product.id]) { seen[product.id] = true; products.push(product); }
    });
    return { reply: response.reply, products: products, conditions: response.conditions };
  }
  function requestReply(payload) {
    // A stalled connection must not lock the composer forever. Timeout does not
    // claim that a server did not receive the request, and never retries itself.
    return new Promise(function (resolve, reject) {
      var timer = window.setTimeout(function () { reject(new Error('reply_timeout')); }, REPLY_TIMEOUT);
      Promise.resolve().then(function () { return P.sendPCMessage(payload); }).then(function (response) {
        window.clearTimeout(timer); resolve(response);
      }, function (error) { window.clearTimeout(timer); reject(error); });
    });
  }

  P.pages['pc-finder'] = function () {
    var html = '<div class="container finder-wrap">' +
      '<div class="finder-topline"><nav class="breadcrumb" aria-label="현재 위치"><a href="index.html">홈</a>' + icon('caret-right') + '<span>내게 맞는 PC 찾기</span></nav>' +
      '<button class="finder-new" type="button" data-finder-new>' + icon('arrow-counter-clockwise') + '새 대화</button></div>' +
      '<div class="finder-mobile-tabs" role="tablist" aria-label="상담 화면"><button type="button" id="finder-tab-chat" role="tab" aria-selected="true" aria-controls="finder-conversation" data-finder-tab="chat">' + icon('chat-circle') + '대화</button>' +
      '<button type="button" id="finder-tab-selection" role="tab" aria-selected="false" aria-controls="finder-sidebar" tabindex="-1" data-finder-tab="selection">' + icon('computer-tower') + '선택 PC <span class="finder-mobile-count" data-finder-count>0</span></button></div>' +
      '<div class="finder-layout" data-finder-layout data-mobile-panel="chat">' +
      '<section class="finder-conversation" id="finder-conversation" aria-labelledby="finder-heading">' +
      '<div class="finder-intro"><div class="finder-kicker"><img src="' + P.image('logo.png') + '" alt=""><span>POPCORN AI</span></div>' +
      '<h1 id="finder-heading">어떤 PC가 필요하세요?</h1><p>하고 싶은 일과 예산을 편하게 알려주세요.<br>잘 모르는 사양은 함께 살펴보면 돼요.</p></div>' +
      '<div class="finder-prompts" aria-label="질문 시작하기">' + PROMPTS.map(function (prompt, index) { return '<button class="finder-prompt" type="button" data-finder-prompt="' + index + '">' + icon(prompt.icon) + '<span>' + h(prompt.label) + '<small>' + h(prompt.hint) + '</small></span></button>'; }).join('') + '</div>' +
      '<div class="finder-log" id="finder-log" role="log" aria-label="대화 내용" aria-live="polite" aria-relevant="additions text"></div>' +
      '<p class="finder-working" data-finder-working role="status" hidden>' + icon('clock') + '답변을 기다리고 있어요.</p>' +
      '<div class="finder-composer-wrap"><form class="finder-composer" data-finder-form>' +
      '<label class="visually-hidden" for="finder-message">원하는 PC에 대해 알려주세요</label>' +
      '<textarea id="finder-message" rows="3" maxlength="20000" placeholder="예: 150만 원 안팎으로 게임과 영상 편집에 쓸 PC를 찾고 있어요." aria-describedby="finder-input-hint finder-error-text"></textarea>' +
      '<div class="finder-composer-bottom"><p class="finder-composer-hint" id="finder-input-hint"><span class="finder-keyboard-hint">Enter로 보내기 · Shift+Enter로 줄바꿈</span><span data-finder-length></span></p>' +
      '<button class="finder-send" type="submit" data-finder-send>보내기' + icon('paper-plane-tilt') + '</button></div></form>' +
      '<div class="finder-status" data-finder-error role="alert" hidden>' + icon('warning-circle') + '<div class="finder-status-body"><p id="finder-error-text"></p><button class="finder-retry" type="button" data-finder-retry hidden>' + icon('arrow-counter-clockwise') + '다시 보내기</button></div></div>' +
      '<p class="finder-privacy">' + icon('info') + '<span>답변을 참고한 뒤 상품 상세에서 구성과 가격을 확인해 주세요.</span></p></div></section>' +
      '<aside class="finder-sidebar" id="finder-sidebar" aria-label="조건과 선택한 PC">' +
      '<section class="finder-sidecard"><div class="finder-sidecard-heading">' + icon('clipboard-text') + '<h2>함께 정할 조건</h2><small>선택 입력</small></div>' +
      '<div class="finder-conditions"><label class="finder-condition" for="finder-purpose"><span>사용 용도</span><input id="finder-purpose" data-finder-condition="purpose" maxlength="200" placeholder="게임, 사무, 영상 편집 등"></label>' +
      '<label class="finder-condition" for="finder-budget"><span>생각한 예산</span><input id="finder-budget" data-finder-condition="budget" maxlength="200" placeholder="예: 150만 원 안팎"></label>' +
      '<label class="finder-condition" for="finder-environment"><span>사용 환경</span><input id="finder-environment" data-finder-condition="environment" maxlength="200" placeholder="예: QHD 모니터 1대"></label>' +
      '<p class="finder-condition-note">아는 것만 적어주세요.<br>입력한 조건은 다음 질문과 함께 전달됩니다.</p></div></section>' +
      '<section class="finder-sidecard finder-choice-card"><div class="finder-sidecard-heading">' + icon('computer-tower') + '<h2>선택한 PC</h2></div><div data-finder-selected></div></section>' +
      '<p class="finder-selected-note" data-finder-selection-note role="status" hidden></p></aside></div></div>';

    return { html: html, mount: function () {
      var wrap = document.querySelector('.finder-wrap');
      if (!wrap || wrap.dataset.mounted === 'true') return;
      wrap.dataset.mounted = 'true';
      var input = wrap.querySelector('#finder-message'), log = wrap.querySelector('#finder-log');
      var state = { messages: [], history: [], selectedProduct: null, conditions: cleanConditions(null), source: 'finder', pending: false, generation: 0 };
      var errorBox = wrap.querySelector('[data-finder-error]'), errorText = wrap.querySelector('#finder-error-text');
      var retry = wrap.querySelector('[data-finder-retry]'), working = wrap.querySelector('[data-finder-working]');
      var conditionInputs = Array.prototype.slice.call(wrap.querySelectorAll('[data-finder-condition]'));

      function showError(message, canRetry) {
        errorText.textContent = message;
        errorBox.hidden = false;
        retry.hidden = !canRetry;
        input.setAttribute('aria-invalid', canRetry ? 'false' : 'true');
      }
      function clearError() {
        errorBox.hidden = true; errorText.textContent = ''; retry.hidden = true; input.removeAttribute('aria-invalid');
      }
      function updateCount() {
        wrap.querySelector('[data-finder-length]').textContent = input.value.length > 1000 ? ' ' + input.value.length.toLocaleString('ko-KR') + ' / 20,000자' : '';
      }
      function readConditions() {
        conditionInputs.forEach(function (field) { state.conditions[field.dataset.finderCondition] = field.value; });
        return Object.assign({}, state.conditions);
      }
      function renderConditions() { conditionInputs.forEach(function (field) { field.value = state.conditions[field.dataset.finderCondition] || ''; }); }
      function setPending(pending) {
        state.pending = pending; input.disabled = pending; working.hidden = !pending;
        wrap.querySelector('[data-finder-send]').disabled = pending;
        wrap.querySelector('[data-finder-new]').disabled = pending;
        retry.disabled = pending;
        conditionInputs.forEach(function (field) { field.disabled = pending; });
        wrap.querySelectorAll('[data-finder-prompt], [data-finder-select], [data-finder-unselect]').forEach(function (button) { button.disabled = pending; });
        log.setAttribute('aria-busy', String(pending));
      }
      function renderMessages() {
        log.innerHTML = state.messages.map(function (message) {
          var user = message.role === 'user';
          return '<article class="finder-message finder-message-' + (user ? 'user' : 'assistant') + '"><div class="finder-message-label">' +
            (user ? '나' : '<img src="' + P.image('logo.png') + '" alt="">팝콘AI') + '</div><p class="finder-message-body">' + h(message.text) + '</p>' +
            (user && message.status === 'failed' ? '<p class="finder-message-state">답변을 확인하지 못한 질문</p>' : '') +
            (!user ? productCards(message.products || []) : '') + '</article>';
        }).join('');
      }
      function renderSelected() {
        var selected = state.selectedProduct, area = wrap.querySelector('[data-finder-selected]');
        wrap.querySelector('#finder-sidebar').className = 'finder-sidebar' + (selected ? ' has-selection' : '');
        wrap.querySelector('[data-finder-count]').textContent = selected ? '1' : '0';
        if (!selected) {
          area.innerHTML = '<div class="finder-selected-empty"><strong>아직 고른 PC가 없어요.</strong><p>상품을 둘러보거나 대화에서<br>마음에 드는 PC를 골라보세요.</p><a class="finder-browse" href="' + h(P.href('pcs')) + '">PC 먼저 둘러보기' + icon('arrow-right') + '</a></div>';
          return;
        }
        var src = productImage(selected);
        area.innerHTML = '<div class="finder-selected"><div class="finder-selected-summary">' + (src ? '<div class="finder-selected-photo"><img src="' + h(src) + '" alt="' + h(selected.name) + '"></div>' : '') +
          '<div class="finder-selected-info"><h3>' + h(selected.name) + '</h3><p>' + h(selected.summary || '') + '</p><p class="finder-selected-price">' + h(P.money(selected.price)) + '</p></div></div>' +
          '<div class="finder-selected-links"><a class="btn btn-outline" href="' + h(P.href('pc-detail', { id: selected.id })) + '">상품 상세 보기' + icon('caret-right') + '</a>' +
          '<button class="finder-unselect" type="button" data-finder-unselect>선택 해제</button></div></div>';
      }
      function chooseTab(panel, focus) {
        var selected = panel === 'selection' ? 'selection' : 'chat';
        wrap.querySelector('[data-finder-layout]').dataset.mobilePanel = selected;
        wrap.querySelectorAll('[data-finder-tab]').forEach(function (button) {
          var active = button.dataset.finderTab === selected;
          button.setAttribute('aria-selected', String(active)); button.tabIndex = active ? 0 : -1;
          if (active && focus) button.focus();
        });
      }
      async function send() {
        if (state.pending) return;
        var text = input.value;
        if (!text.trim()) { showError('어떤 PC를 찾는지 한 줄만 적어주세요.', false); input.focus(); return; }
        if (text.length > MAX_TEXT) { showError('한 번에 20,000자까지 보낼 수 있어요. 내용을 나누어 주세요.', false); input.focus(); return; }
        clearError();
        // Missing adapter cannot send anything. Preserve the exact draft, with no bot message.
        if (typeof P.sendPCMessage !== 'function') {
          showError('지금은 대화에 연결할 수 없어요. 적어주신 내용은 그대로 남겨두었어요. 잠시 후 다시 보내주세요.', true);
          return;
        }
        var payload = { text: text, history: state.history.slice(-MAX_HISTORY).map(function (item) { return { role: item.role, text: item.text }; }),
          selectedProductId: state.selectedProduct ? state.selectedProduct.id : null, source: state.source, conditions: readConditions() };
        var previous = state.messages[state.messages.length - 1];
        var userMessage = previous && previous.role === 'user' && previous.status === 'failed' && previous.text === text ? previous : { role: 'user', text: text };
        if (userMessage !== previous) state.messages.push(userMessage);
        userMessage.status = 'pending';
        renderMessages(); setPending(true);
        var generation = ++state.generation;
        try {
          var result = validateReply(await requestReply(payload));
          if (generation !== state.generation) return;
          userMessage.status = 'sent';
          state.messages.push({ role: 'assistant', text: result.reply, products: result.products });
          state.history.push({ role: 'user', text: text }, { role: 'assistant', text: result.reply });
          state.history = state.history.slice(-MAX_HISTORY);
          state.conditions = cleanConditions(result.conditions, state.conditions);
          renderConditions();
          // Only a validated response permits clearing the sent draft.
          input.value = ''; updateCount(); clearError(); renderMessages();
        } catch (error) {
          if (generation !== state.generation) return;
          userMessage.status = 'failed';
          // Do not expose technical errors or server-provided markup to the customer.
          showError('답변을 확인하지 못했어요. 입력한 내용은 그대로 있으니 잠시 후 다시 보내주세요.', true);
          renderMessages();
        } finally {
          if (generation === state.generation) { setPending(false); }
        }
      }

      wrap.querySelector('[data-finder-form]').addEventListener('submit', function (event) { event.preventDefault(); void send(); });
      retry.addEventListener('click', function () { void send(); });
      input.addEventListener('input', function () { updateCount(); if (!errorBox.hidden) clearError(); });
      input.addEventListener('keydown', function (event) {
        // Mobile Enter remains a newline. Desktop has the stated send shortcut.
        if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && window.matchMedia('(min-width: 801px)').matches) { event.preventDefault(); void send(); }
      });
      wrap.addEventListener('click', function (event) {
        var button = event.target.closest('button');
        if (!button || button.disabled) return;
        if (button.hasAttribute('data-finder-tab')) { chooseTab(button.dataset.finderTab, false); return; }
        if (button.hasAttribute('data-finder-prompt')) {
          var prompt = PROMPTS[Number(button.dataset.finderPrompt)];
          if (!prompt) return;
          // Suggestions fill drafts only; do not erase a customer's unfinished wording.
          input.value = input.value.trim() ? input.value + '\n' + prompt.text : prompt.text;
          clearError(); updateCount(); input.focus(); return;
        }
        if (button.hasAttribute('data-finder-select')) {
          var product = findProduct(button.dataset.finderSelect);
          if (!product || state.pending) return;
          state.selectedProduct = product; renderSelected();
          var note = wrap.querySelector('[data-finder-selection-note]');
          note.textContent = product.name + '을 선택했어요. 다음 질문부터 이 PC를 함께 살펴봅니다.'; note.hidden = false;
          return;
        }
        if (button.hasAttribute('data-finder-unselect')) { state.selectedProduct = null; renderSelected(); wrap.querySelector('[data-finder-selection-note]').hidden = true; return; }
        if (button.hasAttribute('data-finder-new')) {
          state.generation++; state.messages = []; state.history = []; state.selectedProduct = null; state.conditions = cleanConditions(null); state.source = 'finder';
          input.value = ''; updateCount(); clearError(); renderMessages(); renderConditions(); renderSelected();
          wrap.querySelector('[data-finder-selection-note]').hidden = true; chooseTab('chat', false); input.focus();
        }
      });
      wrap.querySelector('[role="tablist"]').addEventListener('keydown', function (event) {
        if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].indexOf(event.key) < 0) return;
        event.preventDefault();
        var current = wrap.querySelector('[data-finder-layout]').dataset.mobilePanel;
        chooseTab(event.key === 'Home' ? 'chat' : event.key === 'End' ? 'selection' : current === 'chat' ? 'selection' : 'chat', true);
      });

      // No raw URL query or automatic query-to-product fallback.
      var entry = null;
      try { if (P.finderEntry && typeof P.finderEntry.consume === 'function') entry = P.finderEntry.consume(); } catch (error) { entry = null; }
      if (plainObject(entry)) {
        if (typeof entry.text === 'string') input.value = entry.text;
        state.selectedProduct = findProduct(entry.productId);
        if (['home', 'product', 'category', 'global', 'finder'].indexOf(entry.source) >= 0) state.source = entry.source;
        if (typeof entry.purpose === 'string' && entry.purpose.length <= 200) state.conditions.purpose = entry.purpose;
      }
      renderSelected(); renderConditions(); updateCount();
      if (state.source === 'home' && input.value.trim()) void send();
    } };
  };
}());
