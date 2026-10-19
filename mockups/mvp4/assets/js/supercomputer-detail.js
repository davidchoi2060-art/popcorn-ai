/* /mvp4 AI 슈퍼컴퓨터 상세 (v15 승인 시안 supercomputer-detail.js 를 실제 조회에 연결, 2026-10-19).
 *
 * 화면 모양은 시안 그대로다. 바꾼 것은 원천과 상태뿐이다.
 *   - 가격·판매 상태·용량은 GET /api/customer/supercomputers(live-supercomputer.js) 응답만 쓴다(시안의 10/19 관찰값을 쓰지 않는다).
 *   - 상태는 응답이 정한다 — 주소의 state= 로 오류·판매 확인·사진 누락 화면을 만들 수 없다(그 상태들은 시안 미리보기 전용).
 *     조회 실패 = «상품 정보를 불러오지 못했어요» · 판매 확인 필요(sale_state=check) = «판매 여부를 확인하고 있어요» · 사진 실패 = 대체 표시.
 *   - 두 모델은 고정 완제품이다. 부품 변경 없이 모델·수량(1~10)만 고르고, 문의로 id·quantity·intent 를 넘긴다.
 * 사진: 전체 모습(gb10-product.jpg)·전면/후면(Dell 제품 사진의 1600px WebP 파생본, 원본 PNG 보존). 출처·권리는 images/supercomputer/SOURCES.json.
 */
(function () {
  'use strict';
  var P = window.PAI, h = P.h, icon = P.icon;
  var products = {}, phase = 'loading';
  var ids = ['129615', '129614'], app = document.getElementById('app');
  var query = new URLSearchParams(window.location.search);
  var id = query.has('id') ? query.get('id') : '129615';
  var state = 'normal';
  function quantity(value) { return /^\d+$/.test(String(value || '')) && Number(value) >= 1 && Number(value) <= 10 ? Number(value) : 1; }
  var q = quantity(query.get('quantity'));
  function money(value) { return Number.isFinite(value) && value > 0 ? P.money(value) : '가격 확인 필요'; }
  function product() { return ids.indexOf(String(id)) >= 0 ? products[id] || null : null; }
  function price(p) { return p && typeof p.price === 'number' && Number.isFinite(p.price) && p.price > 0 ? p.price : null; }
  function storage(p) { return p && p.storage ? String(p.storage) : '저장공간 확인'; }
  function route(intent) { return 'supercomputer-inquiry.html?' + new URLSearchParams({ id: id, quantity: String(q), intent: intent }).toString(); }
  function retry() { return 'supercomputer.html?' + new URLSearchParams({ id: id, quantity: String(q) }).toString(); }
  function crumb() { return '<nav class="sc-breadcrumb" aria-label="현재 위치"><a href="index.html">홈</a>' + icon('caret-right') + '<a href="index.html#home-supercomputer">AI 슈퍼컴퓨터</a>' + icon('caret-right') + '<span aria-current="page">Dell GB10</span></nav>'; }
  function empty(notFound) {
    return '<div class="container sc-page">' + crumb() + '<section class="sc-empty"><span class="sc-empty-icon">' + icon(notFound ? 'package' : 'warning-circle') + '</span><p class="sc-eyebrow">AI SUPERCOMPUTER</p><h1>' + (notFound ? '선택한 상품을 찾을 수 없어요.' : '상품 정보를 불러오지 못했어요.') + '</h1><p>' + (notFound ? '상품 목록에서 원하시는 모델을 다시 선택해 주세요.' : '잠시 후 다시 확인해 주세요.') + '</p><div class="sc-empty-actions">' + (!notFound ? '<a class="btn btn-primary" href="' + h(retry()) + '">다시 불러오기</a>' : '') + '<a class="btn btn-outline" href="index.html#home-supercomputer">AI 슈퍼컴퓨터 보기 ' + icon('arrow-right') + '</a></div></section></div>';
  }
  function choices(p) {
    return '<fieldset class="sc-models"><legend>완제품 모델 선택</legend><div class="sc-model-options">' + ids.map(function (key) {
      var item = products[key];
      if (!item) return '';
      return '<label class="sc-model-option' + (key === id ? ' is-selected' : '') + '"><input type="radio" name="gb10-model" value="' + h(key) + '"' + (key === id ? ' checked' : '') + '><span><strong>' + h(storage(item)) + '</strong><small>128GB 통합 메모리</small></span><span class="sc-radio-mark" aria-hidden="true">' + icon('check') + '</span></label>';
    }).join('') + '</div><p>선택한 모델의 사양으로 제공됩니다.</p></fieldset>';
  }
  var views = [
    ['assets/images/supercomputer/gb10-product.jpg', '전체 모습', 'Dell Pro Max GB10 본체'],
    ['assets/images/supercomputer/gb10-front-1600.webp', '전면', 'Dell Pro Max GB10 전면'],
    ['assets/images/supercomputer/gb10-rear-1600.webp', '후면·연결 단자', 'Dell Pro Max GB10 후면 연결 단자']
  ];
  function galleryThumbs() {
    return '<div class="sc-gallery-thumbs" role="group" aria-label="제품 사진 선택">' + views.map(function (v, index) { return '<button type="button" data-sc-view="' + index + '" aria-pressed="' + (index === 0 ? 'true' : 'false') + '" aria-label="' + h(v[1]) + ' 사진 보기"><img src="' + h(v[0]) + '" alt="" width="80" height="45"><span>' + h(v[1]) + '</span></button>'; }).join('') + '</div>';
  }
  function connections() {
    return '<section class="sc-section sc-connectivity" aria-labelledby="sc-connect-title"><div class="sc-connect-copy"><span class="sc-eyebrow">CONNECT YOUR WORKFLOW</span><h2 id="sc-connect-title">연결까지, 한눈에.</h2><p>제품 뒷면의 실제 연결 단자를 확인하세요.</p><div class="sc-connect-labels"><span>10GbE</span><span>ConnectX-7</span></div></div><figure><img src="assets/images/supercomputer/gb10-rear-1600.webp" alt="Dell GB10 후면, 네트워크 및 연결 단자" width="1600" height="562" loading="lazy"><figcaption>Dell GB10 후면</figcaption></figure></section>';
  }
  function hero(p) {
    var unavailable = p.saleState !== 'on_sale';
    var image = typeof p.image === 'string' && /^(assets\/|https:\/\/)/.test(p.image) ? p.image : '';
    return '<section class="sc-product-hero" aria-labelledby="sc-title"><div class="sc-gallery"><div class="sc-gallery-top"><span class="sc-soft-label">AI 전용 장비</span><span>DELL</span></div><div class="sc-product-photo">' + (image ? '<img src="' + h(image) + '" alt="Dell Pro Max GB10 본체" width="640" height="640" fetchpriority="high" data-sc-product-image>' : '<div class="sc-image-fallback">' + icon('package') + '<span>제품 이미지를 준비하고 있어요.</span></div>') + '</div>' + galleryThumbs() + '<div class="sc-gallery-caption"><span>작은 공간에서 시작하는</span><strong>나만의 AI 개발 환경.</strong></div></div><div class="sc-product-info"><div class="sc-product-meta"><span class="sc-eyebrow">DESKTOP AI SUPERCOMPUTER</span><span class="sc-product-id">상품번호 ' + h(p.id) + '</span></div><h1 id="sc-title">Dell Pro Max GB10</h1><p class="sc-lead">AI 모델 실행·개발을 위한 완제품.</p><div class="sc-facts"><div>' + icon('cpu') + '<span>AI 프로세서</span><strong>NVIDIA GB10</strong></div><div>' + icon('memory') + '<span>통합 메모리</span><strong>128GB</strong></div><div>' + icon('hard-drive') + '<span>SSD</span><strong>' + h(storage(p)) + '</strong></div><div>' + icon('code') + '<span>운영체제</span><strong>DGX OS</strong></div></div>' + choices(p) + '<div class="sc-purchase"><div class="sc-unit-price"><span>판매가 <small>1대 기준</small></span><strong>' + h(money(price(p))) + '</strong></div><div class="sc-quantity-row"><label id="sc-quantity-label">수량</label><div class="sc-quantity" role="group" aria-labelledby="sc-quantity-label"><button type="button" data-sc-minus aria-label="수량 한 대 줄이기"' + (q <= 1 ? ' disabled' : '') + '>−</button><output data-sc-quantity aria-live="polite">' + q + '<span>대</span></output><button type="button" data-sc-plus aria-label="수량 한 대 늘리기"' + (q >= 10 ? ' disabled' : '') + '>+</button></div></div><div class="sc-total-row"><span>상품 합계</span><strong data-sc-total>' + h(money(price(p) === null ? null : price(p) * q)) + '</strong></div>' + (unavailable ? '<div class="sc-availability" role="status">' + icon('warning-circle') + '<div><strong>현재 판매 여부를 확인하고 있어요.</strong><p>문의하시면 공급 일정과 구매 가능 여부를 안내해 드립니다.</p></div></div>' : '') + '<div class="sc-actions"><a class="btn btn-primary" data-sc-action="quote" href="' + h(route('quote')) + '">' + (unavailable ? '장비 입고 문의' : '장비 견적 문의') + icon('arrow-right') + '</a><a class="btn sc-adoption" data-sc-action="adoption" href="' + h(route('adoption')) + '">' + icon('chat-circle') + 'AI 설치 상담</a></div><p class="sc-price-caption">가격·공급 일정은 문의 시 확인합니다. AI 설치·교육은 별도 상담하며, 지원 가능 여부를 먼저 검토합니다.</p></div></div></section>';
  }
  function details(p) {
    var rows = [
      ['제품명', 'Dell Pro Max GB10'], ['AI 프로세서', 'NVIDIA GB10 Grace Blackwell'], ['CPU', '20코어 ARM 기반 CPU'], ['메모리', '128GB LPDDR5x 통합 메모리'], ['저장장치', 'M.2 NVMe SSD ' + storage(p)], ['운영체제', 'NVIDIA DGX OS · Ubuntu 기반 Linux'], ['네트워크', '10GbE · NVIDIA ConnectX-7'], ['판매 구성', '선택한 사양의 완제품']
    ];
    return '<nav class="sc-section-nav" aria-label="상품 상세 메뉴"><a href="#sc-usecases">활용 분야</a><a href="#sc-specs">제품 사양</a><a href="#sc-environment">사용 환경</a><a href="#sc-faq">자주 묻는 질문</a></nav><section class="sc-usecases sc-section" id="sc-usecases"><div class="sc-section-heading"><span class="sc-eyebrow">YOUR AI, ON YOUR DESK</span><h2>AI를 직접 다루는 분을 위해.</h2></div><div class="sc-usecase-grid"><article><span class="sc-usecase-icon">' + icon('code') + '</span><span class="sc-usecase-number">01</span><h3>로컬 AI 실행</h3><p>내 장비에서 AI 모델을 실행하고 활용 환경을 살펴보세요.</p></article><article><span class="sc-usecase-icon">' + icon('cpu') + '</span><span class="sc-usecase-number">02</span><h3>AI 개발·실험</h3><p>모델과 개발 도구를 연결해 새로운 아이디어를 구현하세요.</p></article><article><span class="sc-usecase-icon">' + icon('file-text') + '</span><span class="sc-usecase-number">03</span><h3>업무 AI 도입 검토</h3><p>문서 검색과 지식 활용에 필요한 설치 환경을 함께 검토하세요.</p></article></div></section><section class="sc-section" id="sc-specs"><div class="sc-section-heading"><span class="sc-eyebrow">SPECIFICATIONS</span><h2>사양을 한눈에.</h2></div><details class="sc-spec-panel" open><summary><span>' + icon('cpu') + '<strong>' + h(storage(p)) + ' 모델 제품 사양</strong></span><span class="sc-detail-caret">접기·펼치기 ' + icon('caret-down') + '</span></summary><dl class="sc-spec-table">' + rows.map(function (r) { return '<div><dt>' + h(r[0]) + '</dt><dd>' + h(r[1]) + '</dd></div>'; }).join('') + '</dl></details></section>' + connections() + '<section class="sc-section sc-environment" id="sc-environment"><div class="sc-environment-copy"><span class="sc-eyebrow">BUILT FOR LOCAL AI</span><h2>사용할 프로그램부터<br>함께 확인해요.</h2><p>DGX OS와 ARM 기반으로 작동하는 AI 전용 환경입니다. 사용하려는 모델과 프로그램의 지원 여부를 먼저 확인해 주세요.</p><div class="sc-os-chips"><span>Linux</span><span>ARM</span><span>NVIDIA DGX OS</span></div></div><div class="sc-service-scope"><div><span class="sc-scope-icon">' + icon('package') + '</span><h3>하드웨어 구매</h3><p>선택한 GB10 완제품의 가격, 공급 일정과 보증 조건을 안내합니다.</p></div><div><span class="sc-scope-icon">' + icon('chat-circle') + '</span><h3>업무용 AI 설치도 필요하신가요?</h3><p>장비 구매와 별도로, 필요한 기능·설치·교육 범위와 지원 가능 여부를 상담에서 확인합니다.</p></div><a class="sc-inline-link" data-sc-action="adoption" href="' + h(route('adoption')) + '">업무용 AI 설치 상담하기 ' + icon('arrow-right') + '</a></div></section><section class="sc-section sc-faq" id="sc-faq"><div class="sc-section-heading"><span class="sc-eyebrow">QUESTIONS & ANSWERS</span><h2>궁금한 점을 확인하세요.</h2></div><details><summary>2TB와 4TB는 어떻게 선택하나요?' + icon('caret-down') + '</summary><p>저장공간이 다른 두 완제품 모델입니다. 위에서 원하는 모델을 선택하면 해당 상품의 가격과 사양을 확인할 수 있습니다.</p></details><details><summary>Windows 프로그램도 사용할 수 있나요?' + icon('caret-down') + '</summary><p>이 제품은 Ubuntu 기반 DGX OS를 사용합니다. 일반 Windows 프로그램의 실행을 전제로 구매하지 마시고, 필요한 프로그램이 Linux와 ARM 환경을 지원하는지 먼저 확인해 주세요.</p></details><details><summary>사내 문서 검색도 바로 제공되나요?' + icon('caret-down') + '</summary><p>제품 구매는 하드웨어 기준입니다. 업무형 로컬 AI 패키지가 기본 포함되는 것은 아닙니다. 문서 검색 등 필요한 기능, 데이터 연결, 설치·교육 범위와 지원 가능 여부는 별도 상담에서 확인합니다.</p></details><details><summary>어떤 AI 모델까지 사용할 수 있나요?' + icon('caret-down') + '</summary><p>모델 종류와 정밀도, 문맥 길이, 동시 사용 인원에 따라 실행 조건과 응답 성능이 달라집니다. 도입 상담에 사용하려는 모델과 업무를 알려주시면 검토 범위를 안내합니다.</p></details><details><summary>배송과 보증 조건은 어디서 확인하나요?' + icon('caret-down') + '</summary><p>실제 공급 일정, 국내 공급 모델과 보증 조건은 견적 문의에서 확인할 수 있습니다.</p></details></section><a class="sc-back-link" href="index.html#home-supercomputer">' + icon('arrow-left') + '다른 AI 슈퍼컴퓨터 모델 보기</a>';
  }
  function sticky(p) {
    return '<aside class="sc-mobile-purchase" aria-label="상품 견적 바로가기"><div><span>상품 합계 · <b data-sc-mobile-quantity>' + q + '</b>대</span><strong data-sc-total>' + h(money(price(p) === null ? null : price(p) * q)) + '</strong></div><a class="btn btn-primary" data-sc-action="quote" href="' + h(route('quote')) + '">' + (p.saleState !== 'on_sale' ? '장비 입고 문의' : '장비 견적 문의') + icon('arrow-right') + '</a></aside>';
  }
  function loading() {
    return '<div class="container sc-page">' + crumb() + '<section class="sc-empty" aria-busy="true"><span class="sc-empty-icon">' + icon('cpu') + '</span><p class="sc-eyebrow">AI SUPERCOMPUTER</p><h1>상품 정보를 불러오고 있어요.</h1><p>현재 가격과 판매 상태를 확인합니다.</p></section></div>';
  }
  function render(focusModel) {
    if (phase === 'loading') { app.innerHTML = P.shell(loading()); P.bindShell(); return; }
    var p = phase === 'ready' ? product() : null;
    var fail = !p;
    app.innerHTML = P.shell(fail ? empty(phase === 'ready') : '<div class="container sc-page">' + crumb() + hero(p) + details(p) + '</div>' + sticky(p));
    document.body.classList.toggle('sc-has-mobile-purchase', !fail);
    document.title = (p ? 'Dell Pro Max GB10 · ' + storage(p) : 'AI 슈퍼컴퓨터') + ' | 팝콘AI';
    P.bindShell();
    if (fail) return;
    app.querySelectorAll('[name="gb10-model"]').forEach(function (input) {
      input.addEventListener('change', function () {
        id = input.value; state = 'normal';
        var url = new URL(window.location.href); url.searchParams.set('id', id); url.searchParams.set('quantity', q); url.searchParams.delete('state');
        window.history.pushState(null, '', url.href);
        render(true);
      });
    });
    app.querySelectorAll('[data-sc-view]').forEach(function (button) {
      button.addEventListener('click', function () {
        var view = views[Number(button.dataset.scView)];
        if (!view) return;
        app.querySelector('.sc-product-photo').innerHTML = '<img src="' + h(view[0]) + '" alt="' + h(view[2]) + '" width="640" height="640" data-sc-product-image>';
        app.querySelectorAll('[data-sc-view]').forEach(function (item) { item.setAttribute('aria-pressed', item === button ? 'true' : 'false'); });
      });
    });
    app.querySelector('[data-sc-minus]').addEventListener('click', function () { changeQuantity(q - 1); });
    app.querySelector('[data-sc-plus]').addEventListener('click', function () { changeQuantity(q + 1); });
    if (focusModel) { var selected = app.querySelector('[name="gb10-model"]:checked'); if (selected) selected.focus({ preventScroll: true }); }
  }
  function changeQuantity(next) {
    q = Math.min(10, Math.max(1, next)); var p = product();
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
  window.addEventListener('popstate', function () { query = new URLSearchParams(window.location.search); id = query.has('id') ? query.get('id') : '129615'; state = 'normal'; q = quantity(query.get('quantity')); render(false); });
  function start() {
    phase = 'loading'; render(false);
    P.gb10.load(true).then(function (data) { products = data.products; phase = 'ready'; render(false); },
      function () { phase = 'error'; render(false); });
  }
  start();
}());
