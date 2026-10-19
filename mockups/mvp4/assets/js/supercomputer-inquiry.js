/* /mvp4 AI 슈퍼컴퓨터 견적 문의·AI 도입 상담 (v15 승인 시안 supercomputer-inquiry.js 를 실제 접수에 연결, 2026-10-19).
 *
 * 화면 모양은 시안 그대로다. 바꾼 것:
 *   - 상품·가격은 GET /api/customer/supercomputers(live-supercomputer.js). 시안의 관찰 가격을 쓰지 않는다.
 *   - 접수는 POST /api/mvp3/purchase-inquiries (fixed = 모델·수량·목적, 0165). «접수 완료»는 서버가 접수 번호를 준 뒤에만 그린다.
 *     시안의 미리보기 전용 성공 처리(미리보기 틀 안에서만 동작)는 싣지 않았다.
 *   - 같은 신청은 한 번만 접수된다(client_key, 0163). 버튼은 보내는 동안 잠긴다. 응답을 못 받으면 같은 키로 접수 여부만 확인한다.
 *   - 실패하면 입력은 그대로 두고 다시 보낼 수 있다. 가격·판매 상태가 바뀌었으면(409 price_changed) 바뀐 금액을 보여 주고 다시 확인받는다.
 *   - 연락 요청 확인(시안)과 개인정보 수집·이용 동의(서버가 주는 최신 문구, 보관 180일)는 둘 다 필수다.
 * 이 문의는 고객이 직접 연락을 요청하는 화면이다. 견적 보관은 연락 요청이 아니다 — 보관만 한 고객에게 먼저 연락하지 않는다.
 */
(function () {
  'use strict';
  var P = window.PAI, h = P.h, icon = P.icon, qs = new URLSearchParams(location.search);
  var TOPIC = { quote: 'AI 슈퍼컴퓨터 견적', adoption: 'AI 도입 상담' };
  var id = qs.has('id') ? qs.get('id') : '129615';
  var product = null, meta = null;
  var rawQuantity = Number(qs.get('quantity') || 1);
  var quantity = Number.isInteger(rawQuantity) ? Math.min(10, Math.max(1, rawQuantity)) : 1;
  var intent = qs.get('intent') === 'adoption' ? 'adoption' : 'quote';
  // loading | load-error | form | sending | success | error | unknown
  var phase = 'loading', notice = '', receipt = null, clientKey = null, seenPrice = null;
  var draft = { method: 'phone', phone: '', email: '', name: '', purpose: '', message: '', contactRequested: false, consent: false };
  var errors = {};
  var app = document.getElementById('app');
  function noun() { return intent === 'adoption' ? 'GB10 AI 설치 상담' : 'AI 전용 장비 견적 문의'; }
  function detailUrl() { return 'supercomputer.html?id=' + encodeURIComponent(id) + '&quantity=' + quantity; }
  function money(value) { return typeof value === 'number' && isFinite(value) && value > 0 ? P.money(value) : '금액 확인 필요'; }
  function total() { return product && typeof product.price === 'number' ? product.price * quantity : null; }
  function key() {
    if (clientKey) return clientKey;
    var b = new Uint8Array(16); window.crypto.getRandomValues(b);
    clientKey = 'sc-' + Array.from(b, function (x) { return x.toString(16).padStart(2, '0'); }).join('');
    return clientKey;
  }
  function call(method, path, body) {
    var headers = { Accept: 'application/json', 'X-Popcorn-Surface': 'mvp4' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    var ctrl = new AbortController(), timer = setTimeout(function () { ctrl.abort(); }, 30000);
    return fetch(path, { method: method, credentials: 'same-origin', cache: 'no-store', headers: headers, body: body === undefined ? undefined : JSON.stringify(body), signal: ctrl.signal })
      .then(function (r) {
        clearTimeout(timer);
        return r.json().catch(function () { return null; }).then(function (data) {
          if (r.ok && data && data.ok === true) return data;
          var d = data && data.detail, e = new Error('http');
          e.status = r.status; e.unknown = r.status >= 500;
          e.code = d && typeof d === 'object' && typeof d.error === 'string' ? d.error : '';
          e.sentence = typeof d === 'string' ? d : d && typeof d.detail === 'string' ? d.detail : '';
          throw e;
        });
      }, function () { clearTimeout(timer); var e = new Error('network'); e.unknown = true; throw e; });
  }
  function crumb() {
    return '<nav class="breadcrumb" aria-label="현재 위치"><a href="index.html">홈</a>' + icon('caret-right') + '<a href="' + h(detailUrl()) + '">AI 슈퍼컴퓨터</a>' + icon('caret-right') + '<span>' + noun() + '</span></nav>';
  }
  function summary() {
    var p = product;
    return '<aside class="sci-summary"><div class="sci-product-visual"><img src="' + h(p.image) + '" alt="Dell Pro Max GB10 제품"></div>' +
      '<div class="sci-summary-body"><span class="eyebrow">선택한 완제품</span><h2>' + h(p.name) + '</h2><p class="sci-model">128GB · SSD ' + h(p.storage || '확인 필요') + '</p>' +
      '<dl><div><dt>상품번호</dt><dd>' + h(p.id) + '</dd></div><div><dt>상품 금액</dt><dd>' + money(p.price) + '</dd></div><div><dt>수량</dt><dd>' + quantity + '대</dd></div>' +
      '<div class="sci-total"><dt>하드웨어 합계</dt><dd>' + money(total()) + '</dd></div></dl>' +
      (p.saleState !== 'on_sale' ? '<p class="sci-note">현재 판매 여부를 확인하고 있어요. 문의하시면 공급 일정과 구매 가능 여부를 안내해 드립니다.</p>' : '') +
      '<p class="sci-note">장비 구매와 별도로, AI 설치·교육 범위와 지원 가능 여부를 상담에서 확인합니다.</p><a class="sci-back" href="' + h(detailUrl()) + '">선택한 상품 다시 보기 ' + icon('arrow-right') + '</a></div></aside>';
  }
  function errorFor(k) { return '<p class="sci-error" id="sci-' + k + '-error"' + (errors[k] ? '' : ' hidden') + '>' + h(errors[k] || '') + '</p>'; }
  function form() {
    var phone = draft.method === 'phone', sending = phase === 'sending';
    return '<div class="sci-heading"><span class="eyebrow">AI SUPERCOMPUTER</span><h1>' + noun() + '</h1><p>' + (intent === 'adoption' ? '사용할 모델·프로그램과 필요한 설치 범위를 알려주세요.' : '선택한 제품의 구매 조건을 함께 확인해 보세요.') + '</p></div>' +
      '<div class="sci-layout"><form class="sci-form" novalidate' + (sending ? ' aria-busy="true"' : '') + '>' +
      (Object.keys(errors).length ? '<div class="sci-error-summary" role="alert">' + (errors.contact ? '연락처' : '') + (errors.contact && (errors.consent || errors.privacy) ? '와 ' : '') + (errors.consent || errors.privacy ? '확인란' : '') + '을 확인해 주세요.</div>' : '') +
      (notice ? '<div class="sci-error-summary" role="alert">' + h(notice) + '</div>' : '') +
      '<section class="sci-section"><header><span>01</span><h2>어디로 안내드릴까요?</h2></header>' +
      '<fieldset class="sci-contact-method"><legend>연락받을 방법 <b>필수</b></legend><div class="sci-methods">' +
      '<label><input type="radio" name="method" value="phone"' + (phone ? ' checked' : '') + '>' + icon('phone') + '전화</label>' +
      '<label><input type="radio" name="method" value="email"' + (!phone ? ' checked' : '') + '>' + icon('envelope') + '이메일</label></div></fieldset>' +
      '<div class="sci-field"><label for="sci-contact">' + (phone ? '전화번호' : '이메일 주소') + ' <b>필수</b></label><input id="sci-contact" name="contact" type="' + (phone ? 'tel' : 'email') + '" inputmode="' + (phone ? 'tel' : 'email') + '" autocomplete="' + (phone ? 'tel' : 'email') + '" maxlength="' + (phone ? 20 : 120) + '" value="' + h(draft[draft.method]) + '" placeholder="' + (phone ? '010-0000-0000' : 'name@company.com') + '" aria-invalid="' + !!errors.contact + '" aria-describedby="sci-contact-error">' + errorFor('contact') + '</div>' +
      '<div class="sci-field"><label for="sci-name">이름 <small>선택</small></label><input id="sci-name" name="name" autocomplete="name" maxlength="30" value="' + h(draft.name) + '" placeholder="성함을 알려주세요"></div></section>' +
      '<section class="sci-section"><header><span>02</span><h2>어떤 도움이 필요하세요?</h2></header><div class="sci-field"><label for="sci-purpose">활용 목적 <small>선택</small></label><select id="sci-purpose" name="purpose"><option value="">선택해 주세요</option>' +
      [['local-llm', '로컬 AI 모델 실행'], ['documents', '사내 문서 검색·업무 활용'], ['development', 'AI 개발·연구'], ['other', '그 밖의 용도·아직 미정']].map(function (o) { return '<option value="' + o[0] + '"' + (draft.purpose === o[0] ? ' selected' : '') + '>' + o[1] + '</option>'; }).join('') +
      '</select></div><div class="sci-field"><label for="sci-message">문의 내용 <small>선택</small></label><textarea id="sci-message" name="message" rows="4" maxlength="500" placeholder="필요한 수량, 활용할 업무 또는 궁금한 점을 남겨주세요.">' + h(draft.message) + '</textarea></div></section>' +
      '<div class="sci-consent"><label><input type="checkbox" name="contactRequested"' + (draft.contactRequested ? ' checked' : '') + ' aria-invalid="' + !!errors.consent + '" aria-describedby="sci-consent-error"><span>이 문의에 대한 안내를 받기 위해 연락을 요청합니다. <b>필수</b></span></label>' + errorFor('consent') + '<p>요청한 문의에 대해 선택한 방법으로 연락드립니다.</p></div>' +
      '<div class="sci-consent"><label><input type="checkbox" name="consent"' + (draft.consent ? ' checked' : '') + ' aria-invalid="' + !!errors.privacy + '" aria-describedby="sci-privacy-error"><span>' + h(meta.consent_text) + ' <b>필수</b></span></label>' + errorFor('privacy') + '</div>' +
      '<button class="btn btn-primary sci-submit" type="submit"' + (sending ? ' disabled' : '') + '>' + (sending ? '접수하고 있어요…' : (intent === 'adoption' ? 'AI 설치 상담 신청하기' : '장비 견적 문의 보내기') + icon('arrow-right')) + '</button><p class="sci-submit-note">문의 내용과 선택한 상품을 함께 확인합니다.</p></form>' + summary() + '</div>';
  }
  function result() {
    var success = phase === 'success', unknown = phase === 'unknown';
    return '<section class="sci-result" aria-live="polite"><div class="sci-result-icon ' + (success ? 'is-success' : 'is-error') + '">' + icon(success ? 'check-circle' : 'warning-circle') + '</div>' +
      '<span class="eyebrow">' + (success ? '접수 완료' : unknown ? '접수 확인 필요' : '접수 미완료') + '</span><h1 id="sci-result-title" tabindex="-1">' + (success ? '문의가 접수되었습니다.' : unknown ? '접수 결과를 확인하지 못했어요.' : '문의를 접수하지 못했어요.') + '</h1><p>' +
      (success ? '요청 내용을 확인한 뒤 선택한 방법으로 안내드립니다.' : unknown ? '연결이 끊겨 접수 여부를 아직 몰라요. 아래 버튼은 같은 문의의 접수 여부만 확인하므로 두 번 접수되지 않아요.' : h(notice || '입력한 내용은 유지되어 있어요. 내용을 확인한 뒤 다시 시도해 주세요.')) + '</p>' +
      '<dl class="sci-result-summary">' + (success && receipt ? '<div><dt>접수 번호</dt><dd>' + h(receipt) + '</dd></div>' : '') + '<div><dt>문의 유형</dt><dd>' + noun() + '</dd></div><div><dt>선택한 상품</dt><dd>' + h(product.name) + ' · ' + h(product.storage || '') + '</dd></div><div><dt>수량</dt><dd>' + quantity + '대</dd></div><div><dt>하드웨어 합계</dt><dd>' + money(total()) + '</dd></div></dl>' +
      '<div class="sci-result-actions">' + (unknown ? '<button type="button" class="btn btn-primary" data-sci-check>접수 결과 확인 ' + icon('arrow-right') + '</button>' : '') + (!success && !unknown ? '<button type="button" class="btn btn-primary" data-sci-edit>입력 내용 다시 확인 ' + icon('arrow-right') + '</button>' : '') + '<a href="' + h(detailUrl()) + '" class="btn ' + (success ? 'btn-primary' : 'btn-outline') + '">상품 상세로 돌아가기</a></div>' +
      (success ? '<div class="sci-next"><span>' + icon('file-text') + '문의 내용 확인</span><span>' + icon('chat-circle') + '구매·도입 범위 안내</span></div>' : '') + '</section>';
  }
  function collect() {
    var f = document.querySelector('.sci-form'); if (!f) return;
    var fd = new FormData(f);
    ['name', 'purpose', 'message'].forEach(function (k) { draft[k] = String(fd.get(k) || ''); });
    draft[draft.method] = String(fd.get('contact') || ''); draft.contactRequested = fd.has('contactRequested'); draft.consent = fd.has('consent');
  }
  function validate() {
    errors = {}; var value = draft[draft.method].trim();
    // 서버 규칙(api/mvp3_contact PHONE_RE · EMAIL_RE)과 같은 모양만 받는다.
    var valid = draft.method === 'email' ? /^[^@\s]{1,64}@[^@\s]{1,100}\.[^@\s]{2,}$/.test(value) : /^0\d{1,2}-?\d{3,4}-?\d{4}$/.test(value.replace(/\s+/g, ''));
    if (!valid) errors.contact = draft.method === 'email' ? '올바른 이메일 주소를 입력해 주세요.' : '연락받을 전화번호를 확인해 주세요. 예: 010-1234-5678';
    if (!draft.contactRequested) errors.consent = '연락을 원하시면 요청 확인란을 선택해 주세요.';
    if (!draft.consent) errors.privacy = '개인정보 수집·이용에 동의해 주세요.';
    return Object.keys(errors).length === 0;
  }
  function body() {
    var b = { topic: TOPIC[intent], name: draft.name.trim() || null, phone: null, email: null, message: draft.message.trim() || null,
      consent: true, product_code: Number(product.id), client_key: key(),
      fixed: { intent: intent, quantity: quantity, purpose: draft.purpose || null, seen_unit_price: seenPrice } };
    b[draft.method] = draft[draft.method].trim();
    return b;
  }
  function submit() {
    phase = 'sending'; notice = ''; render(false);
    call('POST', '/api/mvp3/purchase-inquiries', body()).then(function (r) {
      receipt = r.inquiry_no; clientKey = null; phase = 'success'; render(true);
    }, function (e) {
      if (e.unknown) { phase = 'unknown'; render(true); return; }
      if (e.code === 'price_changed' || e.code === 'product_missing') {
        // 바뀐 가격·판매 상태를 다시 읽어 보여 주고, 고객이 확인한 뒤 다시 보낸다(입력은 그대로).
        return P.gb10.load(true).then(function (data) { product = data.products[id] || null; seenPrice = product ? product.price : null; }, function () {})
          .then(function () { notice = e.sentence || '상품 가격이나 판매 상태가 바뀌었어요. 바뀐 내용을 확인한 뒤 다시 보내 주세요.'; phase = product ? 'form' : 'load-error'; render(true); });
      }
      notice = e.status === 429 ? '요청이 잠시 많아요. 잠시 후 다시 시도해 주세요.' : e.sentence && e.sentence.length <= 200 ? e.sentence : '입력한 내용은 유지되어 있어요. 내용을 확인한 뒤 다시 시도해 주세요.';
      phase = 'error'; render(true);
    });
  }
  function render(focus) {
    var content;
    if (phase === 'loading') content = '<section class="sci-result" aria-busy="true"><h1>문의 화면을 준비하고 있어요.</h1><p>선택한 상품의 현재 가격과 판매 상태를 확인합니다.</p></section>';
    else if (phase === 'load-error') content = '<section class="sci-result"><div class="sci-result-icon is-error">' + icon('warning-circle') + '</div><h1>' + (product === null && notice === 'missing' ? '선택한 상품을 찾을 수 없어요.' : '문의 화면을 불러오지 못했어요.') + '</h1><p>' + (notice === 'missing' ? '상품을 다시 선택한 뒤 문의해 주세요.' : '연결 상태를 확인한 뒤 다시 시도해 주세요.') + '</p><div class="sci-result-actions">' + (notice === 'missing' ? '' : '<button type="button" class="btn btn-primary" data-sci-reload>다시 불러오기</button>') + '<a class="btn btn-outline" href="index.html#home-supercomputer">AI 슈퍼컴퓨터 보기</a></div></section>';
    else content = crumb() + (phase === 'form' || phase === 'sending' ? form() : result());
    app.innerHTML = P.shell('<div class="container sci-page">' + content + '</div>');
    P.bindShell(); document.title = noun() + ' | 팝콘AI';
    var f = document.querySelector('.sci-form');
    if (f) {
      f.addEventListener('input', collect);
      f.addEventListener('change', function (event) {
        if (event.target.name === 'method') { collect(); draft.method = event.target.value; errors = {}; render(false); document.getElementById('sci-contact').focus({ preventScroll: true }); } else collect();
      });
      f.addEventListener('submit', function (event) {
        event.preventDefault();
        if (phase === 'sending') return;            // 보내는 중에는 다시 보내지 않는다
        collect(); notice = '';
        if (!validate()) { render(false); var invalid = document.querySelector('.sci-form [aria-invalid="true"]'); if (invalid) invalid.focus(); return; }
        submit();
      });
    }
    var edit = document.querySelector('[data-sci-edit]');
    if (edit) edit.addEventListener('click', function () { phase = 'form'; render(true); });
    var check = document.querySelector('[data-sci-check]');
    if (check) check.addEventListener('click', function () {
      check.disabled = true;
      call('GET', '/api/mvp3/purchase-inquiries/by-key/' + encodeURIComponent(key())).then(function (r) {
        if (r.found) { receipt = r.inquiry_no; clientKey = null; phase = 'success'; }
        else { notice = '이 문의는 접수되지 않은 것으로 확인됐어요. 입력한 내용은 그대로 있으니 확인한 뒤 다시 보내 주세요.'; phase = 'error'; }
        render(true);
      }, function () { phase = 'unknown'; render(true); });
    });
    var reload = document.querySelector('[data-sci-reload]');
    if (reload) reload.addEventListener('click', start);
    if (focus) { var target = document.getElementById('sci-result-title') || document.getElementById('sci-contact'); if (target) target.focus(); document.querySelector('.sci-page').scrollIntoView({ block: 'start' }); }
  }
  app.addEventListener('error', function (event) {
    var img = event.target;
    if (img && img.matches && img.matches('.sci-product-visual img')) img.parentNode.innerHTML = '<span class="sci-image-fallback">' + icon('cpu') + '제품 이미지</span>';
  }, true);
  function start() {
    phase = 'loading'; notice = ''; render(false);
    // 동의 문구는 서버가 준다(보관 기간 포함). 이 호출이 방문자 연결도 맺어, 응답을 못 받았을 때 접수 여부를 확인할 수 있다.
    Promise.all([P.gb10.load(true), call('GET', '/api/mvp3/purchase-inquiries/form')]).then(function (r) {
      meta = r[1]; product = r[0].products[id] || null;
      if (!product || P.gb10.ids.indexOf(id) < 0) { product = null; notice = 'missing'; phase = 'load-error'; render(false); return; }
      seenPrice = product.price; phase = 'form'; render(false);
    }, function () { phase = 'load-error'; render(false); });
  }
  start();
}());
