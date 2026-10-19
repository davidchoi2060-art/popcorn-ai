/* /mvp4 AI 슈퍼컴퓨터 상세 — 카테고리 공통 상세 틀 (v15/v15.1 승인 시안 · 카테고리 확장 2026-10-20).
 *
 * 화면 모양은 승인 v15/v15.1 그대로다. 내용은 상품별 데이터(GET /api/customer/supercomputers/{code})만 쓴다.
 *   - 사진·제조사 표지·사양표·연결(포트)·사용 환경·FAQ 는 그 상품의 표시 정보에 있을 때만 그린다.
 *     Dell 사진·DGX OS·ARM·포트·2TB/4TB FAQ 는 GB10 상품의 데이터다 — 다른 상품에 기본으로 나오지 않는다.
 *   - 값이 없으면 «확인 필요», 가격이 없으면 «가격 확인 필요», 판매 중지면 «판매 중지»로 그린다.
 *   - 같은 제품의 고정 모델(예: 2TB/4TB)은 모델 선택으로 보인다(부품 변경이 아니다). 모델·수량(1~10)만 고른다.
 *   - 문의로 id·quantity·intent(quote|adoption)를 넘긴다. 설치 상담을 업무형 패키지(package=business)로 바꾸지 않는다.
 *   - 상세·없는 상품·조회 실패 화면 모두 «AI 슈퍼컴퓨터 목록»으로 돌아가는 길을 둔다(목록의 필터·정렬·스크롤을 되살린다).
 */
(function () {
  'use strict';
  var P = window.PAI, h = P.h, icon = P.icon, D = P.aiDevices;
  var app = document.getElementById('app'), phase = 'loading', product = null;
  var query = new URLSearchParams(window.location.search);
  var id = query.get('id') || '';
  function quantity(value) { return /^\d+$/.test(String(value || '')) && Number(value) >= 1 && Number(value) <= 10 ? Number(value) : 1; }
  var q = quantity(query.get('quantity'));
  function money(value) { return Number.isFinite(value) && value > 0 ? P.money(value) : '가격 확인 필요'; }
  function price(p) { return p && p.saleState === 'on_sale' && typeof p.price === 'number' && p.price > 0 ? p.price : null; }
  function val(v) { return v || '확인 필요'; }
  function d(p) { return p.detail || {}; }
  function route(intent) { return 'supercomputer-inquiry.html?' + new URLSearchParams({ id: id, quantity: String(q), intent: intent }).toString(); }
  function retry() { return 'supercomputer.html?' + new URLSearchParams({ id: id, quantity: String(q) }).toString(); }
  // 목록으로 돌아갈 때는 목록이 남긴 주소(필터·정렬)를 쓴다. 없으면 목록 첫 화면.
  function listUrl() { try { var u = sessionStorage.getItem('pai-sc-list-url'); if (u && /^supercomputers\.html(\?[^#]*)?$/.test(u)) return u; } catch (e) { /* 저장소를 못 쓰면 첫 화면 */ } return D.listUrl; }
  function crumb(name) { return '<nav class="sc-breadcrumb" aria-label="현재 위치"><a href="index.html">홈</a>' + icon('caret-right') + '<a href="' + h(listUrl()) + '">AI 슈퍼컴퓨터</a>' + icon('caret-right') + '<span aria-current="page">' + h(name || '상품 정보') + '</span></nav>'; }
  function backLink() { return '<a class="btn btn-outline" href="' + h(listUrl()) + '">AI 슈퍼컴퓨터 목록 ' + icon('arrow-right') + '</a>'; }
  function empty(notFound) {
    return '<div class="container sc-page">' + crumb() + '<section class="sc-empty"><span class="sc-empty-icon">' + icon(notFound ? 'package' : 'warning-circle') + '</span><p class="sc-eyebrow">AI 슈퍼컴퓨터</p><h1>' + (notFound ? '선택한 상품을 찾을 수 없어요.' : '상품 정보를 불러오지 못했어요.') + '</h1><p>' + (notFound ? '판매가 끝났거나 목록에서 빠진 상품일 수 있어요. AI 슈퍼컴퓨터 목록에서 다른 제품을 확인해 주세요.' : '잠시 후 다시 확인해 주세요.') + '</p><div class="sc-empty-actions">' + (!notFound ? '<a class="btn btn-primary" href="' + h(retry()) + '">다시 불러오기</a>' : '') + backLink() + '</div></section></div>';
  }
  function choices(p) {
    var models = (p.models || []).filter(function (m) { return m.label; });
    if (models.length < 2) return '';
    return '<fieldset class="sc-models"><legend>완제품 모델 선택</legend><div class="sc-model-options">' + models.map(function (m) {
      return '<label class="sc-model-option' + (m.id === id ? ' is-selected' : '') + '"><input type="radio" name="sc-model" value="' + h(m.id) + '"' + (m.id === id ? ' checked' : '') + '><span><strong>' + h(m.label) + '</strong>' + (d(p).model_note ? '<small>' + h(d(p).model_note) + '</small>' : '') + '</span><span class="sc-radio-mark" aria-hidden="true">' + icon('check') + '</span></label>';
    }).join('') + '</div><p>선택한 모델의 사양으로 제공됩니다.</p></fieldset>';
  }
  function galleryThumbs(p) {
    if (p.images.length < 2) return '';
    return '<div class="sc-gallery-thumbs" role="group" aria-label="제품 사진 선택">' + p.images.map(function (v, index) { var label = v.label || '사진 ' + (index + 1); return '<button type="button" data-sc-view="' + index + '" aria-pressed="' + (index === 0 ? 'true' : 'false') + '" aria-label="' + h(label) + ' 사진 보기"><img src="' + h(v.src) + '" alt="" width="80" height="45"><span>' + h(label) + '</span></button>'; }).join('') + '</div>';
  }
  function connections(p) {
    var c = d(p).connectivity;
    if (!c || !c.image || typeof c.image.src !== 'string') return '';
    return '<section class="sc-section sc-connectivity" aria-labelledby="sc-connect-title"><div class="sc-connect-copy"><span class="sc-eyebrow">CONNECT YOUR WORKFLOW</span><h2 id="sc-connect-title">' + h(c.title || '연결 단자') + '</h2>' + (c.text ? '<p>' + h(c.text) + '</p>' : '') + (Array.isArray(c.labels) && c.labels.length ? '<div class="sc-connect-labels">' + c.labels.map(function (x) { return '<span>' + h(x) + '</span>'; }).join('') + '</div>' : '') + '</div><figure><img src="' + h(c.image.src) + '" alt="' + h(c.image.alt || '') + '" width="' + h(c.image.width || 1600) + '" height="' + h(c.image.height || 900) + '" loading="lazy">' + (c.image.caption ? '<figcaption>' + h(c.image.caption) + '</figcaption>' : '') + '</figure></section>';
  }
  // 상품 데이터가 정한 핵심 사양 네 칸(아이콘·이름·값). 없으면 공통 네 칸(가속기/프로세서·메모리·저장장치·OS)을 «확인 필요»와 함께.
  var ICONS = ['cpu', 'memory', 'hard-drive', 'code', 'package', 'monitor'];
  function facts(p) {
    var f = Array.isArray(d(p).facts) ? d(p).facts.filter(function (x) { return Array.isArray(x) && x.length === 3 && ICONS.indexOf(x[0]) >= 0; }) : [];
    return f.length ? f : D.specs(p);
  }
  function hero(p) {
    var unavailable = p.saleState !== 'on_sale', stopped = p.saleState === 'stopped', info = d(p);
    var main = p.images[0];
    var caption = Array.isArray(info.gallery_caption) && info.gallery_caption.length === 2 ? '<div class="sc-gallery-caption"><span>' + h(info.gallery_caption[0]) + '</span><strong>' + h(info.gallery_caption[1]) + '</strong></div>' : '';
    var brand = info.brand_label || (p.maker ? String(p.maker).toUpperCase() : '');
    return '<section class="sc-product-hero" aria-labelledby="sc-title"><div class="sc-gallery"><div class="sc-gallery-top"><span class="sc-soft-label">AI 전용 장비</span>' + (brand ? '<span>' + h(brand) + '</span>' : '') + '</div><div class="sc-product-photo">' + (main ? '<img src="' + h(main.src) + '" alt="' + h(main.alt || p.name) + '" width="640" height="640" fetchpriority="high" data-sc-product-image>' : '<div class="sc-image-fallback">' + icon('package') + '<span>제품 이미지를 준비하고 있어요.</span></div>') + '</div>' + galleryThumbs(p) + caption + '</div>' +
      '<div class="sc-product-info"><div class="sc-product-meta"><span class="sc-eyebrow">' + h(info.eyebrow || 'AI 슈퍼컴퓨터') + '</span><span class="sc-product-id">상품번호 ' + h(p.id) + '</span></div><h1 id="sc-title">' + h(p.name) + '</h1>' + (info.lead ? '<p class="sc-lead">' + h(info.lead) + '</p>' : '') +
      '<div class="sc-facts">' + facts(p).map(function (s) { return '<div>' + icon(s[0]) + '<span>' + h(s[1]) + '</span><strong>' + h(val(s[2])) + '</strong></div>'; }).join('') + '</div>' + choices(p) +
      '<div class="sc-purchase"><div class="sc-unit-price"><span>판매가 <small>1대 기준</small></span><strong>' + h(stopped ? '판매 중지' : money(price(p))) + '</strong></div><div class="sc-quantity-row"><label id="sc-quantity-label">수량</label><div class="sc-quantity" role="group" aria-labelledby="sc-quantity-label"><button type="button" data-sc-minus aria-label="수량 한 대 줄이기"' + (q <= 1 ? ' disabled' : '') + '>−</button><output data-sc-quantity aria-live="polite">' + q + '<span>대</span></output><button type="button" data-sc-plus aria-label="수량 한 대 늘리기"' + (q >= 10 ? ' disabled' : '') + '>+</button></div></div><div class="sc-total-row"><span>상품 합계</span><strong data-sc-total>' + h(money(price(p) === null ? null : price(p) * q)) + '</strong></div>' +
      (unavailable ? '<div class="sc-availability" role="status">' + icon('warning-circle') + '<div><strong>' + (stopped ? '현재 판매가 중지된 상품이에요.' : '현재 판매 여부를 확인하고 있어요.') + '</strong><p>문의하시면 공급 일정과 구매 가능 여부를 안내해 드립니다.</p></div></div>' : '') +
      '<div class="sc-actions"><a class="btn btn-primary" data-sc-action="quote" href="' + h(route('quote')) + '">' + (unavailable ? '장비 입고 문의' : '장비 견적 문의') + icon('arrow-right') + '</a><a class="btn sc-adoption" data-sc-action="adoption" href="' + h(route('adoption')) + '">' + icon('chat-circle') + 'AI 설치 상담</a></div><p class="sc-price-caption">가격·공급 일정은 문의 시 확인합니다. AI 설치·교육은 별도 상담하며, 지원 가능 여부를 먼저 검토합니다.</p></div></div></section>';
  }
  var GENERIC_FAQ = [
    ['사내 문서 검색도 바로 제공되나요?', '제품 구매는 하드웨어 기준입니다. 업무형 로컬 AI 패키지가 기본 포함되는 것은 아닙니다. 문서 검색 등 필요한 기능, 데이터 연결, 설치·교육 범위와 지원 가능 여부는 별도 상담에서 확인합니다.'],
    ['어떤 AI 모델까지 사용할 수 있나요?', '모델 종류와 정밀도, 문맥 길이, 동시 사용 인원에 따라 실행 조건과 응답 성능이 달라집니다. 도입 상담에 사용하려는 모델과 업무를 알려주시면 검토 범위를 안내합니다.'],
    ['배송과 보증 조건은 어디서 확인하나요?', '실제 공급 일정, 국내 공급 모델과 보증 조건은 견적 문의에서 확인할 수 있습니다.']
  ];
  function specRows(p) {
    var rows = Array.isArray(d(p).spec_rows) ? d(p).spec_rows.filter(function (r) { return Array.isArray(r) && r.length === 2; }) : [];
    if (rows.length) return rows;
    return [['제품명', p.name], ['제조사', val(p.maker)], ['모델명', val(p.modelName)], ['AI 가속기', val(p.accelerator)], ['프로세서', val(p.processor)], ['메모리', val(p.memory)], ['저장장치', val(p.storage)], ['운영체제', val(p.os)], ['아키텍처', val(p.architecture)], ['판매 구성', '선택한 사양의 완제품']];
  }
  function scope() {
    return '<div class="sc-service-scope"><div><span class="sc-scope-icon">' + icon('package') + '</span><h3>하드웨어 구매</h3><p>선택한 완제품의 가격, 공급 일정과 보증 조건을 안내합니다.</p></div><div><span class="sc-scope-icon">' + icon('chat-circle') + '</span><h3>업무용 AI 설치도 필요하신가요?</h3><p>장비 구매와 별도로, 필요한 기능·설치·교육 범위와 지원 가능 여부를 상담에서 확인합니다.</p></div><a class="sc-inline-link" data-sc-action="adoption" href="' + h(route('adoption')) + '">업무용 AI 설치 상담하기 ' + icon('arrow-right') + '</a></div>';
  }
  function details(p) {
    var info = d(p), env = info.environment, model = p.models && p.models.length > 1 && p.modelLabel ? p.modelLabel + ' 모델 ' : '';
    var faq = Array.isArray(info.faq) && info.faq.length ? info.faq : GENERIC_FAQ;
    var envHtml = env && env.text ? '<div class="sc-environment-copy"><span class="sc-eyebrow">BUILT FOR LOCAL AI</span><h2>' + (Array.isArray(env.title) ? env.title.map(h).join('<br>') : h(env.title || '사용 환경')) + '</h2><p>' + h(env.text) + '</p>' + (Array.isArray(env.chips) && env.chips.length ? '<div class="sc-os-chips">' + env.chips.map(function (c) { return '<span>' + h(c) + '</span>'; }).join('') + '</div>' : '') + '</div>'
      : '<div class="sc-environment-copy"><span class="sc-eyebrow">BEFORE YOU BUY</span><h2>사용할 프로그램부터<br>함께 확인해요.</h2><p>운영체제·아키텍처와 사용하려는 모델·프로그램의 지원 여부는 문의에서 먼저 확인해 주세요.</p></div>';
    return '<nav class="sc-section-nav" aria-label="상품 상세 메뉴"><a href="#sc-usecases">활용 분야</a><a href="#sc-specs">제품 사양</a><a href="#sc-environment">사용 환경</a><a href="#sc-faq">자주 묻는 질문</a></nav>' +
      '<section class="sc-usecases sc-section" id="sc-usecases"><div class="sc-section-heading"><span class="sc-eyebrow">YOUR AI, ON YOUR DESK</span><h2>AI를 직접 다루는 분을 위해.</h2></div><div class="sc-usecase-grid"><article><span class="sc-usecase-icon">' + icon('code') + '</span><span class="sc-usecase-number">01</span><h3>로컬 AI 실행</h3><p>내 장비에서 AI 모델을 실행하고 활용 환경을 살펴보세요.</p></article><article><span class="sc-usecase-icon">' + icon('cpu') + '</span><span class="sc-usecase-number">02</span><h3>AI 개발·실험</h3><p>모델과 개발 도구를 연결해 새로운 아이디어를 구현하세요.</p></article><article><span class="sc-usecase-icon">' + icon('file-text') + '</span><span class="sc-usecase-number">03</span><h3>업무 AI 도입 검토</h3><p>문서 검색과 지식 활용에 필요한 설치 환경을 함께 검토하세요.</p></article></div></section>' +
      '<section class="sc-section" id="sc-specs"><div class="sc-section-heading"><span class="sc-eyebrow">SPECIFICATIONS</span><h2>사양을 한눈에.</h2></div><details class="sc-spec-panel" open><summary><span>' + icon('cpu') + '<strong>' + h(model) + '제품 사양</strong></span><span class="sc-detail-caret">접기·펼치기 ' + icon('caret-down') + '</span></summary><dl class="sc-spec-table">' + specRows(p).map(function (r) { return '<div><dt>' + h(r[0]) + '</dt><dd>' + h(r[1]) + '</dd></div>'; }).join('') + '</dl></details></section>' +
      connections(p) +
      '<section class="sc-section sc-environment" id="sc-environment">' + envHtml + scope() + '</section>' +
      '<section class="sc-section sc-faq" id="sc-faq"><div class="sc-section-heading"><span class="sc-eyebrow">QUESTIONS & ANSWERS</span><h2>궁금한 점을 확인하세요.</h2></div>' + faq.map(function (f) { return '<details><summary>' + h(f[0]) + icon('caret-down') + '</summary><p>' + h(f[1]) + '</p></details>'; }).join('') + '</section>' +
      '<a class="sc-back-link" href="' + h(listUrl()) + '">' + icon('arrow-left') + '다른 AI 슈퍼컴퓨터 보기</a>';
  }
  function sticky(p) {
    return '<aside class="sc-mobile-purchase" aria-label="상품 견적 바로가기"><div><span>상품 합계 · <b data-sc-mobile-quantity>' + q + '</b>대</span><strong data-sc-total>' + h(money(price(p) === null ? null : price(p) * q)) + '</strong></div><a class="btn btn-primary" data-sc-action="quote" href="' + h(route('quote')) + '">' + (p.saleState !== 'on_sale' ? '장비 입고 문의' : '장비 견적 문의') + icon('arrow-right') + '</a></aside>';
  }
  function loading() {
    return '<div class="container sc-page">' + crumb() + '<section class="sc-empty" aria-busy="true"><span class="sc-empty-icon">' + icon('cpu') + '</span><p class="sc-eyebrow">AI 슈퍼컴퓨터</p><h1>상품 정보를 불러오고 있어요.</h1><p>현재 가격과 판매 상태를 확인합니다.</p></section></div>';
  }
  function render(focusModel) {
    if (phase === 'loading') { app.innerHTML = P.shell(loading()); P.bindShell(); return; }
    var p = phase === 'ready' ? product : null;
    var fail = !p;
    app.innerHTML = P.shell(fail ? empty(phase === 'missing') : '<div class="container sc-page">' + crumb(p.name) + hero(p) + details(p) + '</div>' + sticky(p));
    document.body.classList.toggle('sc-has-mobile-purchase', !fail);
    document.title = (p ? p.name + (p.modelLabel && p.models.length > 1 ? ' · ' + p.modelLabel : '') : 'AI 슈퍼컴퓨터') + ' | 팝콘AI';
    P.bindShell();
    if (fail) return;
    app.querySelectorAll('[name="sc-model"]').forEach(function (input) {
      input.addEventListener('change', function () {
        id = input.value;
        var url = new URL(window.location.href); url.searchParams.set('id', id); url.searchParams.set('quantity', q);
        window.history.pushState(null, '', url.href);
        load(true);
      });
    });
    app.querySelectorAll('[data-sc-view]').forEach(function (button) {
      button.addEventListener('click', function () {
        var view = p.images[Number(button.dataset.scView)];
        if (!view) return;
        app.querySelector('.sc-product-photo').innerHTML = '<img src="' + h(view.src) + '" alt="' + h(view.alt || p.name) + '" width="640" height="640" data-sc-product-image>';
        app.querySelectorAll('[data-sc-view]').forEach(function (item) { item.setAttribute('aria-pressed', item === button ? 'true' : 'false'); });
      });
    });
    app.querySelector('[data-sc-minus]').addEventListener('click', function () { changeQuantity(q - 1); });
    app.querySelector('[data-sc-plus]').addEventListener('click', function () { changeQuantity(q + 1); });
    if (focusModel) { var selected = app.querySelector('[name="sc-model"]:checked'); if (selected) selected.focus({ preventScroll: true }); }
  }
  function changeQuantity(next) {
    q = Math.min(10, Math.max(1, next)); var p = product;
    app.querySelector('[data-sc-quantity]').innerHTML = q + '<span>대</span>';
    app.querySelector('[data-sc-mobile-quantity]').textContent = q;
    app.querySelector('[data-sc-minus]').disabled = q <= 1;
    app.querySelector('[data-sc-plus]').disabled = q >= 10;
    app.querySelectorAll('[data-sc-total]').forEach(function (node) { node.textContent = money(price(p) === null ? null : price(p) * q); });
    app.querySelectorAll('[data-sc-action]').forEach(function (a) { a.href = route(a.dataset.scAction); });
    var url = new URL(window.location.href); url.searchParams.set('quantity', q); window.history.replaceState(null, '', url.href);
  }
  app.addEventListener('error', function (event) {
    var img = event.target;
    if (img && img.matches && img.matches('[data-sc-product-image]')) img.parentElement.innerHTML = '<div class="sc-image-fallback">' + icon('package') + '<span>제품 이미지를 불러오지 못했어요.</span></div>';
  }, true);
  // 모델을 바꿀 때는 화면을 비우지 않고 새 상품을 읽은 뒤 그린다.
  function load(keep) {
    if (!keep) { phase = 'loading'; render(false); }
    D.detail(id).then(function (p) { product = p; phase = 'ready'; render(!!keep); if (!keep && toHash()) [150, 600].forEach(function (ms) { setTimeout(toHash, ms); }); },
      function (e) { product = null; phase = e && e.status === 404 ? 'missing' : 'error'; render(false); });
  }
  // F05(2026-10-20): 상세 메뉴(#sc-specs 등)를 누르면 브라우저가 popstate 를 낸다 — 같은 상품·같은 수량이면 다시 읽거나
  // 다시 그리지 않고 그 구획으로만 옮긴다(선택한 사진·모델·수량 유지). 상품이나 수량이 바뀐 이력 이동만 다시 읽는다.
  // 고정 머리글 아래로 구획 제목이 오게 직접 계산한다(브라우저 기본 앵커 이동·scroll-padding 차이에 기대지 않는다).
  function scrollToSection(target) {
    var head = document.querySelector('.site-header'), cover = 0;
    if (head) { var hr = head.getBoundingClientRect(), pos = getComputedStyle(head).position; if (pos === 'sticky' || pos === 'fixed') cover = Math.max(0, hr.bottom); }
    window.scrollTo(0, Math.max(0, target.getBoundingClientRect().top + window.scrollY - cover - 16));
  }
  function toHash() {
    var target = location.hash && location.hash.length > 1 ? document.getElementById(decodeURIComponent(location.hash.slice(1))) : null;
    if (target) scrollToSection(target);
    return !!target;
  }
  window.addEventListener('popstate', function () {
    var next = new URLSearchParams(window.location.search), nextId = next.get('id') || '', nextQ = quantity(next.get('quantity'));
    if (product && nextId === id && nextQ === q) { toHash(); return; }
    query = next; id = nextId; q = nextQ; load(false);
  });
  app.addEventListener('click', function (e) {
    var a = e.target.closest('.sc-section-nav a, a[href^="#sc-"]');
    if (!a) return;
    var target = document.getElementById(a.getAttribute('href').slice(1));
    if (!target) return;
    e.preventDefault();
    history.pushState(null, '', location.pathname + location.search + a.getAttribute('href'));
    scrollToSection(target);
  });
  load(false);
}());
