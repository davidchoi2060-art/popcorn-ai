/* /mvp4 견적·보관·내 견적·상담 신청 — 실제 서버 처리 (2026-10-19).
 *
 * design-checkout.js 의 화면 모양(ds-* 클래스·문구)을 쓰되, 상태는 서버 응답이 정한다.
 *   견적 보관   POST /api/mvp3/saved-quotes        (request_id 로 멱등 — 응답이 없으면 같은 요청을 다시 확인한다)
 *   연락처      GET/PUT /api/mvp3/contact          (처음 보관할 때만 전화번호 필수 · 다른 견적은 재사용)
 *   내 견적     GET /api/mvp3/saved-quotes?limit=20
 *   상담 신청   POST /api/mvp3/purchase-inquiries/from-quote (보관 견적) · POST /api/mvp3/purchase-inquiries (상품·일반 문의)
 * 보관은 상담 신청이 아니다 — 보관만 한 고객에게 먼저 연락하지 않는다. 동의 문구·보유 기간은 서버가 준 문장만 쓴다.
 * 이 브라우저의 견적 접근 키는 mvp3 와 같은 키를 쓴다(같은 브라우저의 내 견적이 한 목록이 된다).
 */
(function () {
  'use strict';
  var P = window.PAI, h = P.h;
  var KEY = 'popcorn-mvp3-guest-access-v1', KEY_RE = /^[A-Za-z0-9_-]{32,128}$/;
  var NO_CONTACT_FIRST = '상담을 신청하기 전에는 먼저 연락드리지 않아요.';

  // ── 서버 요청 ──────────────────────────────────────────────────────────
  function accessKey() {
    try {
      var k = window.localStorage.getItem(KEY);
      if (k && KEY_RE.test(k)) return k;
      var b = new Uint8Array(32); window.crypto.getRandomValues(b);
      k = Array.from(b, function (x) { return x.toString(16).padStart(2, '0'); }).join('');
      window.localStorage.setItem(KEY, k);
      return window.localStorage.getItem(KEY) === k ? k : null;
    } catch (e) { return null; }
  }
  function call(method, path, body, withKey) {
    var headers = { Accept: 'application/json', 'X-Popcorn-Surface': 'mvp4' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (withKey) { var k = accessKey(); if (!k) return Promise.reject(err('storage', 0, '이 브라우저에 견적 보관 키를 저장할 수 없어요. 브라우저 설정을 확인해 주세요.')); headers['X-Access-Key'] = k; }
    var ctrl = new AbortController(), timer = setTimeout(function () { ctrl.abort(); }, 30000);
    return fetch(path, { method: method, credentials: 'same-origin', cache: 'no-store', headers: headers, body: body === undefined ? undefined : JSON.stringify(body), signal: ctrl.signal })
      .then(function (r) {
        clearTimeout(timer);
        return r.json().catch(function () { return null; }).then(function (data) {
          if (r.ok && data && data.ok === true) return data;
          var d = data && data.detail, sentence = typeof d === 'string' ? d : d && typeof d.detail === 'string' ? d.detail : '';
          var code = d && typeof d === 'object' && typeof d.error === 'string' ? d.error : '';
          throw err(r.status >= 500 ? 'unknown' : code || 'http', r.status, sentence, d);
        });
      }, function () { clearTimeout(timer); throw err('unknown', 0, ''); });
  }
  function err(kind, status, message, detail) { var e = new Error(message || kind); e.kind = kind; e.status = status; e.detail = detail; e.sentence = message; return e; }
  var primed = null;
  function prime() { if (!primed) primed = call('GET', '/api/mvp3/saved-quotes?limit=1', undefined, true).catch(function (e) { primed = null; throw e; }); return primed; }
  function uuid() { if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID(); var b = new Uint8Array(16); window.crypto.getRandomValues(b); b[6] = b[6] & 15 | 64; b[8] = b[8] & 63 | 128; var x = Array.from(b, function (v) { return v.toString(16).padStart(2, '0'); }).join(''); return x.slice(0, 8) + '-' + x.slice(8, 12) + '-' + x.slice(12, 16) + '-' + x.slice(16, 20) + '-' + x.slice(20); }
  function message(e, fallback) {
    if (e.status === 429) return '요청이 잠시 많아요. 잠시 후 다시 시도해 주세요.';
    if (e.status === 403) return '이 브라우저의 견적 보관 기록에 접근할 수 없어요. 견적을 보관했던 브라우저에서 확인해 주세요.';
    if (e.sentence && e.sentence.length <= 200) return e.sentence;
    return fallback;
  }

  // ── 화면 조각 (design-checkout 과 같은 모양) ──────────────────────────
  function steps(active) { return '<nav class="ds-step" aria-label="견적 단계">' + ['상품 선택', '구성 확인', '견적 보관', '구매 상담'].map(function (t, i) { return (i ? P.icon('caret-right') : '') + (i === active ? '<b aria-current="step">' : '<span>') + t + (i === active ? '</b>' : '</span>'); }).join('') + '</nav>'; }
  function link(t, s, p, style, extra) { var q = p ? { id: p.id } : {}; Object.keys(extra || {}).forEach(function (k) { q[k] = extra[k]; }); return P.designLink(t, s, 'normal', q, style); }
  function sets(n) { n = parseInt(n, 10); return n >= 1 && n <= 10 ? n : 1; }
  function aside(p, n, extra) {
    var total = typeof p.price === 'number' && p.price > 0 ? P.money(p.price * n) : '가격 확인 필요';
    return '<aside class="ds-panel ds-sticky">' + P.designProductSummary(p) + '<div class="ds-price-line"><span>PC 본체 1대</span><b>' + h(P.catalogMoney(p)) + '</b></div><div class="ds-price-line"><span>수량</span><b>' + n + '대</b></div><div class="ds-price-line"><span>배송·추가 서비스</span><span>상담 시 확인</span></div><div class="ds-price-line total"><b>PC 금액</b><strong>' + h(total) + '</strong></div>' + (p.priceBasis ? '<p class="ds-muted">' + h(p.priceBasis) + '</p>' : '') + (extra || '') + '</aside>';
  }
  function loading(title, copy) { return '<div role="status" aria-busy="true"><h2>' + h(title) + '</h2><p class="ds-muted">' + h(copy) + '</p><div class="ds-skeleton"></div><div class="ds-skeleton"></div></div>'; }
  // 견적·보관 전에 확인할 것 — 판매 여부·가격·공개 구성. 없으면 문의로 안내한다(지어내지 않는다).
  function issue(p) {
    if (!p) return '상품을 다시 선택해 주세요.';
    if (p.isSelling !== true) return '현재 판매 여부를 확인해야 합니다.';
    if (!(typeof p.price === 'number' && p.price > 0)) return '현재 상품 가격을 확인해야 합니다.';
    if (p.liveDetail === 'error') return '상품 구성 정보를 지금 불러오지 못했어요. 잠시 후 다시 확인해 주세요.';
    if (!Array.isArray(p.specs) || !p.specs.length) return '이 상품의 정확한 부품 구성표를 확인해야 합니다.';
    return '';
  }
  function blocked(p) { return P.designNotice('상품 정보를 먼저 확인해 주세요', issue(p), 'bad') + P.designProductSummary(p) + '<div class="ds-actions">' + link('상품 상세 보기', 'product', p, 'btn-outline') + P.designLink('AI에게 질문하기', 'chat', 'product', { id: p.id }, 'btn-outline') + link('상품·구성 문의', 'consult', p) + '</div>'; }
  function mallLink(p, label) { return p.mallUrl ? '<a class="btn btn-outline" href="' + h(p.mallUrl) + '" target="_blank" rel="noopener">' + h(label || '팝콘PC에서 상품 보기') + ' <span aria-hidden="true">↗</span></a>' : ''; }
  function qp(ctx, k) { return ctx.query && typeof ctx.query.get === 'function' ? ctx.query.get(k) : null; }
  function current(ctx) { var id = ctx.productId || qp(ctx, 'id'); return id ? P.getCatalogProduct(id) : null; }

  // ── 견적 확인 ────────────────────────────────────────────────────────
  P.designScreens.quote = function (ctx) {
    var p = current(ctx), n = sets(qp(ctx, 'sets')), body;
    if (!p) body = P.designEmpty('아직 선택한 PC가 없어요', '상품을 고르거나 AI와 대화한 뒤 견적을 이어가세요.');
    else if (issue(p)) body = '<section class="ds-panel">' + blocked(p) + '</section>';
    else body = '<div class="ds-two-col"><div><section class="ds-panel"><h2>선택한 PC</h2>' + P.designProductSummary(p) + P.designSpecTable(p) + '<div class="ds-actions">' + link('상품 상세', 'product', p, 'btn-outline') + link('구성 살펴보기', 'options', p, 'btn-outline') + '</div></section>' + P.designNotice('견적 보관과 구매 상담은 별개예요', '견적만 보관한 경우에는 먼저 연락하지 않습니다. 상담을 원할 때 별도로 신청해 주세요.') + '</div>' +
      aside(p, n, '<label class="ds-sets"><span>같은 구성 대수</span><select data-ds-sets>' + [1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(function (k) { return '<option value="' + k + '"' + (k === n ? ' selected' : '') + '>' + k + '대</option>'; }).join('') + '</select></label><p class="ds-muted">금액은 한 대 기준 가격 × 대수예요.</p><div class="ds-actions">' + link('이 견적 보관하기', 'save', p, 'btn-primary', n > 1 ? { sets: n } : {}) + mallLink(p) + '</div><p class="ds-muted">보관한 견적에서 구매 상담을 신청할 수 있습니다.</p>') + '</div>';
    return { html: P.designWrap('내 PC 견적', '상품과 구성을 확인하고, 필요할 때 다시 찾아보세요.', steps(1) + body), mount: function () {
      var s = document.querySelector('[data-ds-sets]'); if (s) s.addEventListener('change', function () { location.replace(P.designHref('quote', 'normal', { id: p.id, sets: s.value > 1 ? s.value : '' })); });
    } };
  };

  // ── 구성 살펴보기: 쇼핑몰 완제품의 부품 변경은 팝콘PC 옵션으로 ────────────
  P.designScreens.options = function (ctx) {
    var p = current(ctx), body;
    if (!p) return { html: P.designWrap('구성 확인', '선택한 상품을 확인해 주세요.', P.designEmpty('선택한 PC를 찾을 수 없어요', '상품 목록에서 다시 선택해 주세요.')) };
    if (issue(p)) body = blocked(p);
    else body = '<h2>기본 구성</h2>' + P.designSpecTable(p) + '<h2 style="margin-top:28px">부품 변경</h2>' + P.designNotice('팝콘PC에서 부품을 변경해 주세요', '이 상품의 부품은 팝콘PC 상품 페이지에서 옵션으로 바꿀 수 있어요. 선택한 옵션에 따라 금액이 달라져요.') + '<div class="ds-actions">' + link('기본 구성으로 견적 보기', 'quote', p) + mallLink(p, '팝콘PC에서 부품 변경하기') + P.designLink('원하는 사양을 AI에게 말하기', 'chat', 'product', { id: p.id }, 'btn-outline') + '</div>';
    return { html: P.designWrap('원하는 구성으로 살펴보세요', '원래 PC와 변경할 내용을 구분해서 확인합니다.', steps(1) + '<div class="ds-two-col"><section class="ds-panel">' + body + '</section>' + aside(p, 1, P.designLink('이 PC에 대해 AI에게 질문', 'chat', 'product', { id: p.id }, 'btn-outline')) + '</div>') };
  };

  // ── 연락처 칸 ────────────────────────────────────────────────────────
  function contactFields(c) {
    return '<label for="ds-phone">전화번호 <span class="ds-muted">필수</span></label><input id="ds-phone" name="phone" type="tel" inputmode="tel" autocomplete="tel" maxlength="20" placeholder="010-1234-5678" required>' +
      '<label for="ds-name">이름 <span class="ds-muted">선택</span></label><input id="ds-name" name="name" maxlength="30" autocomplete="name">' +
      '<label for="ds-email">이메일 <span class="ds-muted">선택</span></label><input id="ds-email" name="email" type="email" maxlength="120" autocomplete="email">' +
      '<label class="ds-consent"><input type="checkbox" name="consent" required><span>' + h(c && c.consent_text || '개인정보 수집·이용에 동의합니다.') + '</span></label>';
  }
  function readContact(f) { var v = function (n) { var el = f.querySelector('[name=' + n + ']'); return el ? el.value.trim() : ''; }; var c = f.querySelector('[name=consent]'); return { phone: v('phone') || null, name: v('name') || null, email: v('email') || null, consent: !!(c && c.checked) }; }

  // ── 견적 보관 ────────────────────────────────────────────────────────
  P.designScreens.save = function (ctx) {
    var p = current(ctx), n = sets(qp(ctx, 'sets'));
    if (!p) return { html: P.designWrap('견적 보관', '보관할 PC를 확인해 주세요.', P.designEmpty('보관할 PC를 찾을 수 없어요', '상품 목록에서 다시 선택해 주세요.')) };
    if (issue(p)) return { html: P.designWrap('견적 보관', '보관하기 전에 상품을 확인해 주세요.', steps(2) + '<section class="ds-panel">' + blocked(p) + '</section>') };
    var req = { id: uuid(), expected: p.price, phase: 'idle', contact: null };
    return { html: P.designWrap('견적 보관', '이 견적을 보관해 두고 필요할 때 다시 확인하세요.', steps(2) + '<div class="ds-two-col"><section class="ds-panel" id="ds-save-panel">' + loading('보관 준비를 하고 있어요', '이 브라우저의 보관 연결과 연락처를 확인합니다.') + '</section>' + aside(p, n, '') + '</div>'), mount: function () {
      var panel = document.getElementById('ds-save-panel');
      function show(html, focus) { panel.innerHTML = html; if (focus) { panel.tabIndex = -1; panel.focus(); } }
      function form(note) {
        var c = req.contact, reuse = c && c.has_contact && !req.changeContact;
        show((note || '') + '<form id="ds-contact-form" class="ds-form" novalidate><p id="ds-form-errors" class="ds-form-error" role="alert" tabindex="-1" hidden></p><fieldset class="ds-form-fields">' +
          (reuse ? '<div class="ds-notice" role="status"><div><strong>등록된 연락처로 보관해요</strong><p>' + h(c.masked_phone || '') + (c.name ? ' · ' + h(c.name) : '') + '</p><button class="btn btn-outline" type="button" data-ds-contact-change>연락처 바꾸기</button></div></div>'
            : '<p class="ds-muted">처음 보관할 때 한 번만 전화번호를 받아요. 이 브라우저의 다른 견적은 같은 연락처를 씁니다.</p>' + contactFields(c)) +
          '<p class="ds-muted">' + NO_CONTACT_FIRST + ' 이 단계는 견적 보관입니다. 상담을 신청한 것은 아닙니다.</p><a class="ds-muted" href="support.html#privacy">개인정보 처리방침 보기</a></fieldset>' +
          '<div class="ds-actions"><button class="btn btn-primary" type="submit">' + (reuse ? '기존 연락처로 견적 보관' : '견적 보관하기') + P.icon('arrow-right') + '</button></div></form>', !!note);
        var f = document.getElementById('ds-contact-form');
        var ch = f.querySelector('[data-ds-contact-change]'); if (ch) ch.addEventListener('click', function () { req.changeContact = true; form(); });
        f.addEventListener('submit', function (e) { e.preventDefault(); submit(reuse ? null : readContact(f), f); });
      }
      function fieldError(f, text) { var el = f.querySelector('#ds-form-errors'); el.textContent = text; el.hidden = false; el.focus(); }
      function submit(contact, f) {
        if (contact) {
          if (!contact.phone) return fieldError(f, '전화번호를 입력해 주세요.');
          if (!/^0\d{1,2}-?\d{3,4}-?\d{4}$/.test(contact.phone.replace(/\s+/g, ''))) return fieldError(f, '전화번호 형식을 확인해 주세요. 예: 010-1234-5678');
          if (!contact.consent) return fieldError(f, '개인정보 수집·이용에 동의해 주세요.');
        }
        req.body = { request_id: req.id, product_code: Number(p.id), expected_price: req.expected, state: {}, sets: n, purpose: 'keep' };
        if (contact) req.body.contact = contact;
        send();
      }
      function send() {
        req.phase = 'submitting';
        show(loading('견적을 보관하고 있어요', '같은 요청을 두 번 보관하지 않도록 결과를 확인합니다.'));
        call('POST', '/api/mvp3/saved-quotes', req.body, true).then(done, failed);
      }
      function done(res) {
        req.phase = 'done';
        var q = res.quote || {}, qp2 = q.product || {}, c = res.contact || {}, changed = qp2.price_check && qp2.price_check.status === 'changed';
        show(P.designNotice('견적을 보관했어요', NO_CONTACT_FIRST + ' 상담이 필요하면 아래에서 신청해 주세요.') +
          (changed ? P.designNotice('보관하는 동안 쇼핑몰 가격이 바뀌었어요', '바뀐 가격으로 보관했어요. 보관한 금액을 확인해 주세요.', 'bad') : '') +
          '<div class="ds-price-line"><span>보관한 PC 금액</span><b>' + h(typeof qp2.price === 'number' ? P.money(qp2.price) : '확인 필요') + (n > 1 ? ' × ' + n + '대' : '') + '</b></div>' +
          (c.masked_phone ? '<div class="ds-price-line"><span>연락처</span><span>' + h(c.masked_phone) + '</span></div>' : '') +
          '<div class="ds-actions">' + P.designLink('내 견적 보기', 'saved', 'normal', {}, 'btn-outline') + P.designLink('이 견적으로 구매 상담 신청', 'consult', 'normal', { quote: q.id }, 'btn-primary') + '</div>', true);
      }
      function failed(e) {
        if (e.kind === 'unknown') {
          // 응답을 받지 못했다 — 보관됐는지 모른다. 같은 request_id 로만 다시 확인한다(두 번 보관되지 않는다).
          req.phase = 'unknown';
          show(P.designNotice('보관 결과를 확인하지 못했어요', '연결이 끊겨 보관 여부를 아직 몰라요. 아래 버튼은 같은 요청을 다시 확인하므로 두 번 보관되지 않아요.', 'bad') + '<div class="ds-actions"><button class="btn btn-primary" type="button" data-ds-check>보관 결과 확인</button>' + P.designLink('내 견적 보기', 'saved', 'normal', {}, 'btn-outline') + '</div>', true);
          panel.querySelector('[data-ds-check]').addEventListener('click', send);
          return;
        }
        req.phase = 'failed'; req.id = uuid();   // 확정 실패 — 고친 내용은 새 요청이다
        if (e.kind === 'contact_required') { req.contact = { has_contact: false, consent_text: e.detail && e.detail.consent_text }; req.changeContact = true; return form(P.designNotice('연락처를 등록해 주세요', '견적을 보관하려면 전화번호와 동의가 필요해요.', 'bad')); }
        if (e.status === 409 && /가격/.test(e.sentence || '')) {
          return P.live.loadCatalog().then(function () { var fresh = P.getCatalogProduct(p.id); if (fresh) { p = fresh; req.expected = fresh.price; } form(P.designNotice('보관 전에 가격을 다시 확인해 주세요', '현재 금액이 처음 확인한 견적과 달라졌어요. 오른쪽 금액을 확인한 뒤 다시 보관해 주세요.', 'bad')); });
        }
        form(P.designNotice('견적을 보관하지 못했어요', message(e, '입력 내용과 연결 상태를 확인한 뒤 다시 시도해 주세요.'), 'bad'));
      }
      prime().then(function () { return call('GET', '/api/mvp3/contact', undefined, true); }).then(function (c) { req.contact = c; form(); }, function (e) {
        show(P.designNotice('보관 준비를 하지 못했어요', message(e, '연결 상태를 확인한 뒤 다시 시도해 주세요. 기존 연락처가 없다고 확인된 것은 아닙니다.'), 'bad') + '<div class="ds-actions"><button class="btn btn-primary" type="button" data-ds-retry>다시 확인</button></div>');
        panel.querySelector('[data-ds-retry]').addEventListener('click', function () { location.reload(); });
      });
    } };
  };

  // ── 내 견적 ──────────────────────────────────────────────────────────
  P.designScreens.saved = function () {
    return { html: P.designWrap('내 견적', '보관한 PC를 다시 살펴보고 다음 단계를 이어가세요.', '<div id="ds-saved">' + loading('보관한 견적을 불러오고 있어요', '견적을 보관한 브라우저인지 확인합니다.') + '</div>'), mount: function () {
      var box = document.getElementById('ds-saved');
      call('GET', '/api/mvp3/saved-quotes?limit=20', undefined, true).then(function (res) {
        var quotes = Array.isArray(res.quotes) ? res.quotes : [];
        if (!quotes.length) { box.innerHTML = P.designEmpty('보관한 견적이 없어요', '마음에 드는 PC를 골라 견적을 보관해보세요.'); return; }
        box.innerHTML = P.designNotice('내 속도에 맞게 결정하세요', '견적을 보관했다고 상담을 신청한 것은 아닙니다. 상담이 필요하면 견적마다 별도로 신청해 주세요.') + quotes.map(function (q) {
          var s = q.product || {}, live = P.getCatalogProduct(String(s.product_code)), n = sets(s.sets);
          var status = !live ? P.designNotice('현재 판매 여부를 확인할 수 없어요', '보관 당시 견적은 남아 있습니다. 대체 PC를 살펴보거나 상담을 신청해 주세요.', 'bad') : live.price !== s.price && !(s.build) ? P.designNotice('보관 이후 가격이 달라졌어요', '보관한 금액과 현재 금액을 나누어 확인해 주세요.', 'bad') : '';
          return '<section class="ds-panel" style="margin-top:16px">' + status + '<small class="ds-muted">' + h(q.saved_at ? new Date(q.saved_at).toLocaleString('ko-KR') + ' 보관' : '') + '</small><h2>' + h(s.name || '보관한 PC') + '</h2>' +
            '<div class="ds-price-line"><span>보관한 PC 금액</span><b>' + h(typeof s.price === 'number' ? P.money(s.price) : '확인 필요') + (n > 1 ? ' × ' + n + '대' : '') + '</b></div>' +
            (live ? '<div class="ds-price-line"><span>현재 금액</span><span>' + h(P.catalogMoney(live)) + '</span></div>' : '') +
            '<div class="ds-actions">' + (live ? P.designLink('현재 상품 확인', 'product', 'normal', { id: live.id }, 'btn-outline') + P.designLink('AI와 이어서 대화', 'chat', 'product', { id: live.id }, 'btn-outline') : P.designLink('PC 둘러보기', 'catalog', 'normal', {}, 'btn-outline')) + P.designLink('구매 상담 신청', 'consult', 'normal', { quote: q.id }, 'btn-primary') + '</div></section>';
        }).join('');
      }, function (e) {
        box.innerHTML = P.designNotice('내 견적을 불러오지 못했어요', message(e, '보관한 견적이 삭제된 것은 아닙니다. 잠시 후 다시 확인해 주세요.'), 'bad') + '<div class="ds-actions"><button class="btn btn-primary" type="button" data-ds-retry>다시 확인</button></div>';
        box.querySelector('[data-ds-retry]').addEventListener('click', function () { location.reload(); });
      });
    } };
  };

  // ── 구매 상담 신청 ───────────────────────────────────────────────────
  P.designScreens.consult = function (ctx) {
    var quoteId = qp(ctx, 'quote'), p = current(ctx);
    var validQuote = quoteId && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(quoteId);
    return { html: P.designWrap(validQuote ? '구매 상담 신청' : '상품·구매 문의', validQuote ? '보관한 견적으로 구매 상담을 신청합니다.' : '궁금한 점을 남기면 신청 순서대로 연락드려요.', steps(3) + '<div class="ds-two-col"><section class="ds-panel" id="ds-consult">' + loading('신청 양식을 준비하고 있어요', '상담 주제와 동의 문구를 확인합니다.') + '</section>' + (p ? aside(p, 1, '') : '<aside class="ds-panel">' + P.designNotice('상담은 신청한 분께만 연락해요', '신청 순서대로 연락드리겠습니다.') + '</aside>') + '</div>'), mount: function () {
      var box = document.getElementById('ds-consult'), meta = null, contact = null, quote = null;
      function show(html, focus) { box.innerHTML = html; if (focus) { box.tabIndex = -1; box.focus(); } }
      function success(no, masked, already) {
        show(P.designNotice(already ? '이미 접수된 상담이에요' : '상담 신청을 접수했어요', '상담 신청 순서대로 연락드리겠습니다.') + '<div class="ds-price-line"><span>접수 번호</span><b>' + h(no) + '</b></div>' + (masked ? '<div class="ds-price-line"><span>연락처</span><span>' + h(masked) + '</span></div>' : '') + '<div class="ds-actions">' + P.designLink('내 견적 보기', 'saved', 'normal', {}, 'btn-outline') + P.designLink('PC 둘러보기', 'catalog', 'normal', {}, 'btn-outline') + '</div>', true);
      }
      function topics() { return '<label for="ds-topic">상담 주제</label><select id="ds-topic" name="topic">' + (meta.topics || []).map(function (t) { return '<option>' + h(t) + '</option>'; }).join('') + '</select><label for="ds-message">궁금한 점 <span class="ds-muted">선택</span></label><textarea id="ds-message" name="message" maxlength="500" placeholder="사용할 프로그램이나 원하는 구성 변경을 알려주세요."></textarea>'; }
      // 상담할 견적을 먼저 보인다(상품명·금액·견적번호) — 그다음 연락처·접수 단추(모바일도 같은 읽기 순서).
      function quoteSummary() {
        if (!quote) return P.designNotice('이 브라우저에서 보관한 견적을 찾지 못했어요', '내 견적에서 상담할 견적을 다시 골라 주세요. 그래도 신청은 할 수 있어요.', 'bad');
        var s = quote.product || {}, n = sets(s.sets);
        return '<section class="ds-quote-summary" aria-labelledby="ds-quote-title"><p class="eyebrow">상담할 견적</p><h2 id="ds-quote-title">' + h(s.name || '보관한 PC') + '</h2><div class="ds-price-line"><span>보관한 PC 금액</span><b>' + h(typeof s.price === 'number' ? P.money(s.price) : '확인 필요') + (n > 1 ? ' × ' + n + '대' : '') + '</b></div><div class="ds-price-line"><span>견적 번호</span><span>' + h(String(quote.id).slice(0, 8).toUpperCase()) + '</span></div></section>';
      }
      function quoteForm(note) {
        var has = contact && contact.has_contact;
        show((note || '') + quoteSummary() + '<form id="ds-consult-form" class="ds-form" novalidate><p id="ds-form-errors" class="ds-form-error" role="alert" tabindex="-1" hidden></p><fieldset class="ds-form-fields">' + topics() +
          (has ? '<div class="ds-notice" role="status"><div><strong>등록된 연락처로 연락드려요</strong><p>' + h(contact.masked_phone || '') + '</p></div></div>' : '<p class="ds-muted">상담 연락을 받을 전화번호를 등록해 주세요.</p>' + contactFields(contact)) +
          '</fieldset><div class="ds-actions"><button class="btn btn-primary" type="submit">구매 상담 신청' + P.icon('arrow-right') + '</button></div></form>', !!note);
        var f = document.getElementById('ds-consult-form');
        f.addEventListener('submit', function (e) {
          e.preventDefault();
          var body = { quote_id: quoteId, topic: f.topic.value, message: f.message.value.trim() || null };
          var step = has ? Promise.resolve() : (function () { var c = readContact(f); if (!c.phone || !c.consent) { var el = f.querySelector('#ds-form-errors'); el.textContent = '전화번호와 동의를 확인해 주세요.'; el.hidden = false; el.focus(); return null; } return call('PUT', '/api/mvp3/contact', c, true).then(function (r) { contact = r; }); }());
          if (!step) return;
          show(loading('상담 신청을 접수하고 있어요', '접수 번호를 확인합니다.'));
          step.then(function () { return call('POST', '/api/mvp3/purchase-inquiries/from-quote', body, true); }).then(function (r) { success(r.inquiry_no, r.masked_phone, r.already); }, function (e2) {
            if (e2.kind === 'unknown') {
              // 같은 견적의 상담은 하나뿐이라 다시 보내도 같은 접수 번호가 돌아온다(already).
              show(P.designNotice('접수 결과를 확인하지 못했어요', '연결이 끊겨 접수 여부를 아직 몰라요. 아래 버튼은 같은 견적의 접수를 다시 확인하므로 두 번 접수되지 않아요.', 'bad') + '<div class="ds-actions"><button class="btn btn-primary" type="button" data-ds-check>접수 결과 확인</button></div>', true);
              box.querySelector('[data-ds-check]').addEventListener('click', function () { show(loading('접수 결과를 확인하고 있어요', '')); call('POST', '/api/mvp3/purchase-inquiries/from-quote', body, true).then(function (r) { success(r.inquiry_no, r.masked_phone, r.already); }, function (e3) { quoteForm(P.designNotice('상담 신청을 접수하지 못했어요', message(e3, '잠시 후 다시 시도해 주세요.'), 'bad')); }); });
              return;
            }
            if (e2.kind === 'contact_required') { contact = { has_contact: false, consent_text: contact && contact.consent_text }; return quoteForm(P.designNotice('연락처를 등록해 주세요', '상담 연락을 받을 전화번호가 필요해요.', 'bad')); }
            quoteForm(P.designNotice('상담 신청을 접수하지 못했어요', message(e2, '입력 내용과 연결 상태를 확인한 뒤 다시 시도해 주세요.'), 'bad'));
          });
        });
      }
      function unknownGeneral(body) {
        show(P.designNotice('접수 결과를 확인하지 못했어요', '연결이 끊겨 접수 여부를 아직 몰라요. 아래 버튼은 같은 신청의 접수 여부만 확인하므로 두 번 접수되지 않아요.', 'bad') + '<div class="ds-actions"><button class="btn btn-primary" type="button" data-ds-check>접수 결과 확인</button><a class="btn btn-outline" href="support.html">고객지원</a></div>', true);
        box.querySelector('[data-ds-check]').addEventListener('click', function () {
          show(loading('접수 결과를 확인하고 있어요', '같은 신청의 접수 여부만 확인합니다.'));
          call('GET', '/api/mvp3/purchase-inquiries/by-key/' + encodeURIComponent(body.client_key)).then(function (r) {
            if (r.found) success(r.inquiry_no, null, false);
            else generalForm(P.designNotice('신청이 접수되지 않았어요', '이 신청은 접수되지 않은 것으로 확인됐어요. 내용을 확인한 뒤 다시 보내 주세요.', 'bad'));
          }, function () { unknownGeneral(body); });
        });
      }
      function generalForm(note) {
        show((note || '') + '<form id="ds-consult-form" class="ds-form" novalidate><p id="ds-form-errors" class="ds-form-error" role="alert" tabindex="-1" hidden></p><fieldset class="ds-form-fields">' + topics() +
          '<label for="ds-name">이름 <span class="ds-muted">선택</span></label><input id="ds-name" name="name" maxlength="30" autocomplete="name"><label for="ds-phone">전화번호</label><input id="ds-phone" name="phone" type="tel" maxlength="20" placeholder="010-1234-5678" autocomplete="tel"><label for="ds-email">이메일</label><input id="ds-email" name="email" type="email" maxlength="120" autocomplete="email"><p class="ds-muted">전화번호나 이메일 중 하나는 적어 주세요.</p>' +
          '<label class="ds-consent"><input type="checkbox" name="consent" required><span>' + h(meta.consent_text || '') + '</span></label></fieldset><div class="ds-actions"><button class="btn btn-primary" type="submit">' + (p ? '상품 문의 신청' : '구매 상담 신청') + P.icon('arrow-right') + '</button></div></form>', !!note);
        var f = document.getElementById('ds-consult-form');
        if (p) f.message.value = '상품번호 ' + p.id + '의 구성과 구매를 상담하고 싶어요.';
        f.addEventListener('submit', function (e) {
          e.preventDefault();
          var c = readContact(f), el = f.querySelector('#ds-form-errors');
          if (!c.phone && !c.email) { el.textContent = '전화번호나 이메일 중 하나는 적어 주세요.'; el.hidden = false; el.focus(); return; }
          if (!c.consent) { el.textContent = '개인정보 수집에 동의해 주세요.'; el.hidden = false; el.focus(); return; }
          // 같은 신청은 한 번만 접수된다(client_key, 0163). 응답을 못 받으면 같은 키로만 결과를 확인한다.
          var body = { topic: f.topic.value, name: c.name, phone: c.phone, email: c.email, message: f.message.value.trim() || null, consent: true, client_key: 'pi-' + uuid() };
          if (p && Number.isSafeInteger(Number(p.id))) body.product_code = Number(p.id);
          show(loading('상담 신청을 접수하고 있어요', '접수 번호를 확인합니다.'));
          call('POST', '/api/mvp3/purchase-inquiries', body, false).then(function (r) { success(r.inquiry_no, null, false); }, function (e2) {
            if (e2.kind === 'unknown') return unknownGeneral(body);
            generalForm(P.designNotice('상담 신청을 접수하지 못했어요', message(e2, '입력 내용과 연결 상태를 확인한 뒤 다시 시도해 주세요.'), 'bad'));
          });
        });
      }
      var form = call('GET', '/api/mvp3/purchase-inquiries/form').then(function (m) { meta = m; });
      (validQuote ? form.then(prime).then(function () { return Promise.all([call('GET', '/api/mvp3/contact', undefined, true), call('GET', '/api/mvp3/saved-quotes?limit=20', undefined, true)]); }).then(function (r) { contact = r[0]; quote = (r[1].quotes || []).find(function (x) { return x.id === quoteId; }) || null; quoteForm(); }) : form.then(function () { generalForm(); })).catch(function (e) {
        show(P.designNotice('신청 양식을 불러오지 못했어요', message(e, '연결 상태를 확인한 뒤 다시 시도해 주세요.'), 'bad') + '<div class="ds-actions"><button class="btn btn-primary" type="button" data-ds-retry>다시 확인</button></div>');
        box.querySelector('[data-ds-retry]').addEventListener('click', function () { location.reload(); });
      });
    } };
  };

}());
