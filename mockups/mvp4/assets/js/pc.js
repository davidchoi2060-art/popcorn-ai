(function () {
  'use strict';
  var P = window.PAI = window.PAI || {};
  P.pages = P.pages || {};
  function h(value) { return (P.hescape || P.h)(String(value == null ? '' : value)); }
  function icon(name) { return P.icon(name); }
  function href(page, params) { return P.href(page, params || {}); }
  function img(name) { return P.image(name); }
  function data() { return P.data || window.POPCORN_DATA || {}; }
  function config() { return P.config || window.POPCORN_CONFIG || {}; }
  function query() { return P.qs || new URLSearchParams(window.location.search); }
  function products() { return Array.isArray(data().products) ? data().products : []; }
  function findProduct(id) { return products().find(function (p) { return p.id === id; }); }
  function money(value) { return Number.isFinite(value) ? value.toLocaleString('ko-KR') + '원' : '구성 확인'; }
  function price(p) { return '<strong class="pc-price">' + money(p.price) + '</strong>'; }
  var options = {
    purpose: [['all', '전체'], ['gaming', '게임'], ['office', '사무'], ['creative', '디자인·작업']],
    form: [['all', '전체'], ['mini', '초소형'], ['mini-tower', '미니타워'], ['tower', '타워']],
    tier: [['all', '전체'], ['general', '일반'], ['high', '고성능']],
    work: [['all', '전체 작업'], ['video', '영상편집'], ['graphic', '그래픽'], ['3d', '3D']]
  };
  var labels = { purpose: '용도', form: '크기', tier: '성능 등급', work: '작업 종류' };
  var aliases = { '게임': 'gaming', '게이밍': 'gaming', '사무': 'office', '사무용': 'office', '디자인·작업': 'creative', '디자인': 'creative', '초소형': 'mini', '미니': 'mini', '미니타워': 'mini-tower', '타워': 'tower', '고성능': 'high', '일반': 'general' };
  function norm(value) { return aliases[value] || value; }
  function allowed(group, value) { return options[group].some(function (o) { return o[0] === value; }) ? value : 'all'; }
  function readState() {
    var q = query();
    return { q: q.get('q') || '', purpose: allowed('purpose', norm(q.get('purpose') || q.get('category') || 'all')), form: allowed('form', norm(q.get('form') || 'all')), tier: allowed('tier', norm(q.get('tier') || 'all')), work: allowed('work', q.get('work') || 'all'), sort: ['price-asc', 'price-desc'].indexOf(q.get('sort')) >= 0 ? q.get('sort') : 'default' };
  }
  function paramsOf(state) {
    var out = {};
    ['q', 'purpose', 'form', 'tier', 'work', 'sort'].forEach(function (key) { if (state[key] && state[key] !== 'all' && state[key] !== 'default') out[key] = state[key]; });
    return out;
  }
  function filterProducts(items, state) {
    var text = (state.q || '').trim().toLocaleLowerCase('ko-KR');
    var result = items.filter(function (p) {
      var matches = ['purpose', 'form', 'tier', 'work'].every(function (key) { return !state[key] || state[key] === 'all' || norm(p[key]) === state[key]; });
      var search = [p.name, p.summary, p.purpose, p.form, p.tier].concat((p.specs || []).map(function (s) { return s.label + ' ' + s.value; })).join(' ').toLocaleLowerCase('ko-KR');
      return matches && (!text || search.indexOf(text) >= 0);
    });
    if (state.sort === 'price-asc' || state.sort === 'price-desc') result.sort(function (a, b) {
      if (!Number.isFinite(a.price)) return Number.isFinite(b.price) ? 1 : 0;
      if (!Number.isFinite(b.price)) return -1;
      return state.sort === 'price-asc' ? a.price - b.price : b.price - a.price;
    });
    return result;
  }
  P.pcFilterProducts = filterProducts;
  function productCard(p, state) {
    var to = href('pc-detail', Object.assign({}, paramsOf(state), { id: p.id }));
    return '<a class="pc-product-card" href="' + h(to) + '" data-product-id="' + h(p.id) + '"><div class="pc-product-photo"><img src="' + h(img(p.image)) + '" alt="' + h(p.name) + ' 상품 이미지" loading="lazy"></div><div class="pc-product-copy"><h2>' + h(p.name) + '</h2><p>' + h(p.summary) + '</p><div class="pc-card-price">' + price(p) + '</div><span class="pc-btn pc-btn-blue">상품 자세히 보기 ' + icon('arrow-right') + '</span></div></a>';
  }
  function filterFields(prefix, state) {
    return ['purpose', 'form', 'tier'].map(function (group) {
      return '<fieldset class="pc-filter-group"><legend>' + labels[group] + '</legend>' + options[group].map(function (o) {
        return '<label><input type="radio" name="' + prefix + '-' + group + '" value="' + o[0] + '" data-pc-filter="' + group + '"' + (state[group] === o[0] ? ' checked' : '') + '><span>' + o[1] + '</span></label>';
      }).join('') + '</fieldset>';
    }).join('') + '<button type="button" class="pc-btn pc-btn-outline pc-reset" data-pc-reset>' + icon('arrow-counter-clockwise') + ' 필터 초기화</button>';
  }
  function crumbs(items) { return '<nav class="pc-breadcrumb" aria-label="현재 위치"><a href="' + h(href('home')) + '">홈</a>' + items.map(function (x) { return '<span aria-hidden="true">/</span>' + (x.href ? '<a href="' + h(x.href) + '">' + h(x.label) + '</a>' : '<span>' + h(x.label) + '</span>'); }).join('') + '</nav>'; }
  function recommendationBanner() {
    return '<section class="pc-help-banner"><div>' + icon('chat-circle') + '<div><h2>어떤 PC가 맞을지 고민되나요?</h2><p>용도와 예산에 맞는 구성을 살펴보세요.</p></div></div><a class="pc-btn pc-btn-dark" href="' + h(href('pc-finder')) + '">AI로 내 PC 찾기 ' + icon('arrow-right') + '</a></section>';
  }
  P.pages.pcs = function () {
    var state = readState();
    return { html: '<div class="pc-page pc-catalog">' + crumbs([{ label: 'PC 쇼핑' }]) + '<section class="pc-catalog-hero"><div><p class="pc-eyebrow">PC SHOPPING</p><h1>PC 둘러보기</h1><p>용도와 예산에 맞는 구성을 살펴보세요.</p></div><div class="pc-catalog-hero-pcs" aria-hidden="true"><img src="' + h(img('mini.png')) + '" alt=""><img src="' + h(img('gaming.webp')) + '" alt=""><img src="' + h(img('high.png')) + '" alt=""></div></section><div class="pc-catalog-body"><aside class="pc-sidebar" aria-label="상품 필터">' + filterFields('desk', state) + '</aside><section class="pc-catalog-results" aria-label="상품 목록"><div class="pc-catalog-toolbar"><div><h2>전체 PC <span class="pc-result-count" aria-live="polite"></span></h2></div><label class="pc-search">' + icon('magnifying-glass') + '<span class="pc-sr-only">상품명 또는 부품명 검색</span><input type="search" data-pc-search placeholder="상품명 · 부품명 검색" value="' + h(state.q) + '"></label><label class="pc-sort"><span class="pc-sr-only">상품 정렬</span><select data-pc-sort><option value="default">기본순</option><option value="price-asc">낮은 가격순</option><option value="price-desc">높은 가격순</option></select></label></div><div class="pc-mobile-filters"><button type="button" class="pc-btn pc-btn-outline" data-pc-open-filters>' + icon('funnel') + ' 필터</button><span data-pc-filter-summary></span></div><div class="pc-work-tabs" data-pc-work-tabs' + (state.purpose !== 'creative' ? ' hidden' : '') + ' aria-label="작업 종류">' + options.work.map(function (o) { return '<button type="button" data-pc-work="' + o[0] + '" aria-pressed="' + (state.work === o[0]) + '">' + o[1] + '</button>'; }).join('') + '</div><div class="pc-product-grid" data-pc-grid></div></section></div>' + recommendationBanner() + '<dialog class="pc-filter-dialog" aria-labelledby="pc-filter-title"><header><h2 id="pc-filter-title">상품 필터</h2><button type="button" class="pc-dialog-close" data-pc-close-filters aria-label="필터 닫기">' + icon('x') + '<span>닫기</span></button></header><div class="pc-filter-dialog-body">' + filterFields('mobile', state) + '</div><footer><button type="button" class="pc-btn pc-btn-dark" data-pc-close-filters><span data-pc-apply-count></span>개 상품 보기 ' + icon('arrow-right') + '</button></footer></dialog></div>', mount: function () {
      var root = document.querySelector('.pc-catalog'); if (!root) return;
      var dialog = root.querySelector('.pc-filter-dialog');
      function paint() {
        var list = filterProducts(products(), state);
        root.querySelector('[data-pc-grid]').innerHTML = list.length ? list.map(function (p) { return productCard(p, state); }).join('') : '<div class="pc-empty">' + icon('question') + '<h3>조건에 맞는 상품이 없어요.</h3><p>검색어나 필터를 바꿔 다시 살펴보세요.</p><button type="button" class="pc-btn pc-btn-dark" data-pc-reset>전체 상품 보기</button></div>';
        root.querySelector('.pc-result-count').textContent = list.length + '개';
        root.querySelector('[data-pc-apply-count]').textContent = list.length;
        root.querySelector('[data-pc-filter-summary]').textContent = ['purpose', 'form', 'tier'].map(function (key) { return options[key].find(function (o) { return o[0] === state[key]; })[1]; }).filter(function (v) { return v !== '전체'; }).join(' · ') || '전체 상품';
        root.querySelectorAll('[data-pc-filter]').forEach(function (input) { input.checked = state[input.dataset.pcFilter] === input.value; });
        root.querySelector('[data-pc-work-tabs]').hidden = state.purpose !== 'creative';
        root.querySelectorAll('[data-pc-work]').forEach(function (button) { button.setAttribute('aria-pressed', String(state.work === button.dataset.pcWork)); });
        root.querySelector('[data-pc-sort]').value = state.sort;
      }
      function syncUrl() { try { window.history.replaceState(null, '', href('pcs', paramsOf(state))); } catch (_) { /* file:// may restrict history rewriting. */ } }
      root.addEventListener('input', function (event) { if (event.target.matches('[data-pc-search]')) { state.q = event.target.value; paint(); syncUrl(); } });
      root.addEventListener('change', function (event) {
        var target = event.target;
        if (target.matches('[data-pc-filter]')) { state[target.dataset.pcFilter] = target.value; if (target.dataset.pcFilter === 'purpose' && target.value !== 'creative') state.work = 'all'; paint(); syncUrl(); }
        if (target.matches('[data-pc-sort]')) { state.sort = target.value; paint(); syncUrl(); }
      });
      root.addEventListener('click', function (event) {
        var target = event.target.closest('button'); if (!target) return;
        if (target.matches('[data-pc-reset]')) { state = { q: '', purpose: 'all', form: 'all', tier: 'all', work: 'all', sort: 'default' }; root.querySelector('[data-pc-search]').value = ''; paint(); syncUrl(); }
        if (target.matches('[data-pc-open-filters]')) dialog.showModal();
        if (target.matches('[data-pc-close-filters]')) dialog.close();
        if (target.matches('[data-pc-work]')) { state.work = target.dataset.pcWork; paint(); syncUrl(); }
      });
      dialog.addEventListener('click', function (event) { if (event.target === dialog) { var box = dialog.getBoundingClientRect(); if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close(); } });
      paint();
    } };
  };
  var sceneCopy = {
    gaming: ['내 게임과 모니터에 맞춰 확인하세요.', '사용할 게임과 모니터를 기준으로 필요한 구성을 살펴보세요.'],
    office: ['책상 위, 필요한 구성부터.', '문서 작업과 온라인 회의 등 사용할 업무에 맞춰 살펴보세요.'],
    mini: ['책상 위, 필요한 공간부터.', '설치할 공간과 연결할 기기를 확인하고 내 사용 환경에 맞춰 살펴보세요.'],
    creative: ['작업 환경에 맞춰, 구성을 확인하세요.', '사용하는 프로그램과 작업 내용을 기준으로 필요한 구성을 살펴보세요.']
  };
  function sceneFor(p) {
    var key = p.form === 'mini' || p.form === 'mini-tower' ? 'mini' : p.purpose;
    var copy = sceneCopy[key] || sceneCopy.creative;
    var scenes = data().scenes || {};
    var source = scenes[p.id] || scenes[key];
    if (!source) return '<section class="pc-scene pc-scene-copy-only"><div><h2>' + h(copy[0]) + '</h2><p>' + h(copy[1]) + '</p></div></section>';
    return '<section class="pc-scene"><div><h2>' + h(copy[0]) + '</h2><p>' + h(copy[1]) + '</p></div><figure><img src="' + h(img(source)) + '" alt="' + h(p.name) + ' 사용 환경" loading="lazy"></figure></section>';
  }
  function productChecks() {
    return '<section class="pc-purchase-section" id="pc-purchase"><h2>구매 전 확인하세요</h2><div class="pc-faq-grid"><details><summary>' + icon('monitor') + '<span>모니터·주변기기</span>' + icon('caret-down') + '</summary><p>본체 단품 구성입니다. 필요한 모니터와 주변기기는 별도로 선택하세요.</p></details><details><summary>' + icon('gear') + '<span>옵션 변경</span>' + icon('caret-down') + '</summary><p>바꾸고 싶은 부품을 AI와 이야기하고, 변경 가능한 구성과 금액을 확인하세요.</p></details><details><summary>' + icon('wrench') + '<span>배송·A/S</span>' + icon('caret-down') + '</summary><p>상품별 배송·보증·A/S 조건은 구매 상담에서 확인하세요.</p></details></div></section>';
  }
  function notFound(message) { return { html: '<section class="pc-page pc-empty pc-not-found">' + icon('question') + '<h1>' + h(message) + '</h1><p>목록에서 원하는 상품을 다시 선택해 주세요.</p><a class="pc-btn pc-btn-dark" href="' + h(href('pcs')) + '">상품 목록으로 돌아가기 ' + icon('arrow-right') + '</a></section>', mount: function () {} }; }
  P.pages['pc-detail'] = function () {
    var p = findProduct(query().get('id') || 'gaming'); if (!p) return notFound('상품을 찾지 못했어요.');
    var state = readState(), listHref = href('pcs', paramsOf(state));
    var finderHref = href('pc-finder');
    var title = p.form === 'mini' || p.form === 'mini-tower' ? '미니 PC' : p.purpose === 'gaming' ? '게이밍 PC' : p.purpose === 'office' ? '사무·업무용 PC' : '디자인·작업용 PC';
    var shortCopy = p.purpose === 'gaming' ? '좋아하는 게임, 나답게 즐기다.' : p.form === 'mini' || p.form === 'mini-tower' ? '작은 공간에 맞춰 살펴보세요.' : p.purpose === 'office' ? '매일의 업무를 위한 기본 구성.' : '사용할 프로그램과 작업에 맞춰.';
    var action = '<a class="pc-btn pc-btn-blue" href="' + h(finderHref) + '" data-start-finder data-finder-product="' + h(p.id) + '">이 PC로 AI와 상담하기 ' + icon('arrow-right') + '</a>';
    return { html: '<div class="pc-page pc-detail">' + crumbs([{ label: 'PC 쇼핑', href: listHref }, { label: title }]) + '<section class="pc-detail-hero" id="pc-intro"><figure class="pc-detail-gallery"><button type="button" class="pc-photo-zoom" data-pc-zoom aria-label="상품 이미지 크게 보기"><img src="' + h(img(p.image)) + '" alt="' + h(p.name) + ' 상품 이미지"></button></figure><div class="pc-detail-heading"><p class="pc-eyebrow">' + h(title) + '</p><h1>' + h(p.name) + '</h1><p class="pc-detail-tagline">' + h(shortCopy) + '</p><p class="pc-detail-summary">' + h(p.summary) + '</p><div class="pc-detail-price">' + price(p) + '</div><p class="pc-muted">본체 단품 · 모니터 별도</p>' + action + '<p class="pc-action-help">이 PC를 기준으로 용도와 필요한 구성을 함께 확인해보세요.</p><div class="pc-return-links"><a href="' + h(listHref) + '">다른 구성 보기 ' + icon('arrow-right') + '</a><a href="' + h(listHref) + '">목록으로 돌아가기 ' + icon('arrow-left') + '</a></div></div></section>' + sceneFor(p) + '<nav class="pc-section-tabs" aria-label="상품 상세 목차"><a href="#pc-intro">상품 소개</a><a href="#pc-specs">부품 구성</a><a href="#pc-purchase">구매 안내</a></nav><section class="pc-spec-section" id="pc-specs"><div><h2>한눈에 보는 기본 사양</h2><p>' + h(p.name) + '입니다.<br>세부 모델과 옵션은 AI 상담에서 함께 확인하세요.</p></div><table><caption class="pc-sr-only">' + h(p.name) + ' 기본 사양</caption><tbody>' + (p.specs || []).map(function (s) { return '<tr><th scope="row">' + h(s.label) + '</th><td>' + h(s.value) + '</td></tr>'; }).join('') + '</tbody></table></section>' + productChecks() + '<div class="pc-detail-bottom">' + action + '<span>원하는 용도에 맞는지 AI와 함께 확인하세요.</span></div><dialog class="pc-photo-dialog" aria-label="상품 이미지 크게 보기"><button type="button" class="pc-dialog-close" data-pc-photo-close aria-label="확대 이미지 닫기">' + icon('x') + '<span>닫기</span></button><img src="' + h(img(p.image)) + '" alt="' + h(p.name) + ' 상품 이미지 확대"></dialog></div>', mount: function () {
      var root = document.querySelector('.pc-detail'); if (!root) return;
      var dialog = root.querySelector('.pc-photo-dialog');
      root.querySelector('[data-pc-zoom]').addEventListener('click', function () { dialog.showModal(); });
      root.querySelector('[data-pc-photo-close]').addEventListener('click', function () { dialog.close(); });
    } };
  };
  function peripheralItems() {
    var assets = data().categoryAssets || {};
    return [{ id: 'monitor', name: '모니터', description: '화면 크기와 연결할 PC에 맞춰 살펴보세요.', image: assets.monitor || 'monitor.png' }, { id: 'peripherals', name: '주변기기', description: '키보드·마우스 등 필요한 제품을 살펴보세요.', image: assets.peripherals || 'peripherals.png' }];
  }
  P.pages.peripherals = function () {
    return { html: '<div class="pc-page pc-peripherals">' + crumbs([{ label: 'PC 쇼핑', href: href('pcs') }, { label: '모니터·주변기기' }]) + '<header class="pc-peripheral-heading"><p class="pc-eyebrow">MONITOR & ACCESSORIES</p><h1>모니터·주변기기</h1><p>내 PC와 사용 환경에 필요한 제품을 살펴보세요.</p></header><div class="pc-peripheral-grid">' + peripheralItems().map(function (item) { return '<article><img src="' + h(img(item.image)) + '" alt="' + h(item.name) + ' 상품 이미지"><div><h2>' + h(item.name) + '</h2><p>' + h(item.description) + '</p><a class="pc-btn pc-btn-dark" href="' + h(href('pc-finder')) + '" data-start-finder data-finder-purpose="' + h(item.name) + '">' + h(item.name) + ' AI에게 물어보기 ' + icon('arrow-right') + '</a></div></article>'; }).join('') + '</div><a class="pc-back-link" href="' + h(href('pcs')) + '">' + icon('arrow-left') + ' PC 목록으로 돌아가기</a></div>', mount: function () {} };
  };
  P.pcResolveMallLink = function () { return null; };
  P.pages['mall-handoff'] = function () {
    var p=findProduct(query().get('id'));
    if (p) return {html:'<section class="pc-page pc-empty"><h1>이 PC로 상담을 이어가세요.</h1><p>'+h(p.name)+'</p><a class="pc-btn pc-btn-dark" href="'+h(href('pc-finder'))+'" data-start-finder data-finder-product="'+h(p.id)+'">이 PC로 AI와 상담하기 '+icon('arrow-right')+'</a><a class="pc-back-link" href="'+h(href('pc-detail',{id:p.id}))+'">상품 상세 보기</a></section>',mount:function(){}};
    return {html:'<section class="pc-page pc-empty"><h1>필요한 PC와 주변기기를 함께 찾아보세요.</h1><a class="pc-btn pc-btn-dark" href="'+h(href('pc-finder'))+'">AI로 내 PC 찾기 '+icon('arrow-right')+'</a></section>',mount:function(){}};
  };
}());
