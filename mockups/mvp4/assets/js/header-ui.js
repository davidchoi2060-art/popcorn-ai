(function () {
  'use strict';
  var P = window.PAI;
  if (!P || P.headerUi) return;
  var originalShell = P.shell, originalBind = P.bindShell, h = P.h, icon = P.icon;
  var categories = [
    ['게이밍 PC', '게이밍 PC', 'game-controller', '좋아하는 게임에 맞게'],
    ['사무용 PC', '사무·업무용', 'monitor', '매일의 업무를 가볍게'],
    ['작업용 PC', '디자인·영상', 'video-camera', '디자인부터 영상 편집까지'],
    ['미니 PC', '미니 PC', 'computer-tower', '작은 공간에 필요한 성능'],
    ['고성능 PC', 'AI·고성능 PC', 'cpu', '큰 작업을 위한 구성'],
    // AI 전용 장비 카테고리(2026-10-20) — PC 목록 필터가 아니라 전용 목록(supercomputers.html)으로 간다.
    ['AI 슈퍼컴퓨터', null, 'cpu', 'AI 전용 장비', 'supercomputers.html', 'supercomputers'],
    ['주변기기', null, 'headset', '모니터와 주변기기']
  ];
  function route(screen, params) {
    var state = screen === 'chat' ? 'welcome' : 'normal';
    if (typeof P.designHref === 'function') return P.designHref(screen, state, params || {});
    // /mvp4 운영: design-common 이 없는 화면(AI 패키지·상담·지원)도 실제 라우터로 간다(검토용 경로를 내지 않는다).
    var q = new URLSearchParams(screen && screen !== 'home' ? { screen: screen } : {});
    if (screen === 'chat' && state && state !== 'welcome') q.set('state', state);
    Object.keys(params || {}).forEach(function (key) { if (params[key] !== null && params[key] !== undefined && params[key] !== '') q.set(key, params[key]); });
    var s = q.toString();
    return './' + (s ? '?' + s : '');
  }
  function catHref(c) { return c[4] || (c[1] ? catalog(c[1]) : 'peripherals.html'); }
  function catalog(category) { return route('catalog', category ? { category: category } : {}) + (category ? '#catalog-products' : ''); }
  function menuButton(className, text) {
    return '<button class="' + className + '" type="button" data-open-dialog="site-menu" aria-label="전체 카테고리 열기" aria-haspopup="dialog" aria-controls="site-menu">' + icon('list') + '<span>' + text + '</span></button>';
  }
  function navLink(label, href, current, className) {
    return '<a class="' + (className || '') + '" href="' + h(href) + '"' + (current ? ' data-nh-nav="' + h(current) + '"' : '') + '>' + label + '</a>';
  }
  function header(brand) {
    return '<header class="site-header nh-header"><div class="container nh-top">' + brand +
      '<form class="nh-search" data-nh-search role="search" action="./" method="get"><label class="visually-hidden" for="nh-search-input">상품명, CPU 또는 그래픽카드 검색</label><div class="nh-search-field"><input id="nh-search-input" name="q" type="search" placeholder="상품명, CPU, 그래픽카드 검색" autocomplete="off" maxlength="120" aria-describedby="nh-search-error"><button type="submit" aria-label="상품 검색">' + icon('magnifying-glass') + '</button></div><p class="nh-search-error" id="nh-search-error" role="alert" hidden>검색어를 입력해 주세요.</p></form>' +
      '<div class="nh-tools"><a class="nh-tool" href="' + h(route('saved')) + '" data-nh-nav="saved">' + icon('clipboard-text') + '<span>내 견적</span></a><a class="nh-tool nh-support-tool" href="support.html" data-nh-nav="support">' + icon('headset') + '<span>고객지원</span></a>' + menuButton('nh-mobile-menu', '전체 메뉴') + '</div></div>' +
      '<div class="nh-menu-bar"><nav class="container nh-service-nav" aria-label="주요 메뉴"><div class="nh-primary-links">' +
      // 순서(2026-10-20 대표 확정): PC 쇼핑 → AI 패키지 → AI 슈퍼컴퓨터 → AI로 PC 찾기
      navLink('PC 쇼핑', catalog(), 'catalog', 'nh-primary-link') + navLink('AI 패키지', 'ai-packages.html', 'ai', 'nh-primary-link') + navLink('AI 슈퍼컴퓨터', 'supercomputers.html', 'supercomputers', 'nh-primary-link') +
      navLink(icon('chat-circle') + '<span>AI로 PC 찾기</span>', route('chat'), 'chat', 'nh-primary-link nh-primary-ai') + '</div>' +
      '<div class="nh-purpose-group">' + menuButton('nh-category-button nh-category-compact', '전체 카테고리') +
      '<div class="nh-purpose-tabs" role="group" aria-label="용도별 PC와 주변기기">' + categories.map(function (c) {
        return navLink(c[0], catHref(c), c[5] || c[1] || 'peripherals', 'nh-purpose-tab');
      }).join('') + '</div></div></nav></div></header>';

  }
  function menu() {
    return '<dialog class="site-dialog menu-dialog nh-menu" id="site-menu" aria-labelledby="menu-dialog-title"><div class="nh-menu-content"><div class="nh-menu-heading"><div><p>POPCORN AI</p><h2 id="menu-dialog-title">어떤 PC를 찾으세요?</h2></div><button class="icon-button" type="button" data-close-dialog aria-label="전체 카테고리 닫기">' + icon('x') + '</button></div>' +
      '<div class="nh-menu-layout"><section class="nh-menu-pcs" aria-labelledby="nh-pc-menu-title"><div class="nh-group-heading"><h3 id="nh-pc-menu-title">PC 쇼핑</h3><a href="' + h(catalog()) + '">전체 PC 보기 ' + icon('arrow-right') + '</a></div><div class="nh-category-grid">' + categories.map(function (c) { return '<a href="' + h(catHref(c)) + '"><span class="nh-category-icon">' + icon(c[2]) + '</span><span><strong>' + h(c[0]) + '</strong><small>' + h(c[3]) + '</small></span>' + icon('caret-right') + '</a>'; }).join('') + '</div><a class="nh-menu-finder" href="' + h(route('chat')) + '">' + icon('chat-circle') + '<span><strong>AI로 PC 찾기</strong><small>용도와 예산을 말하면, 함께 찾아드려요.</small></span>' + icon('arrow-right') + '</a></section>' +
      '<section class="nh-menu-ai" aria-labelledby="nh-ai-menu-title"><div class="nh-group-heading"><h3 id="nh-ai-menu-title">AI 패키지</h3><a href="ai-packages.html">비교하기 ' + icon('arrow-right') + '</a></div><p class="nh-group-copy">내 일에 필요한 AI를 PC와 함께.</p><div class="nh-package-list">' + [['basic', '기본형', '내 자료 AI 비서', 'file-text-duotone'], ['business', '업무형', '업무형 로컬 AI', 'users-three-duotone'], ['advanced', '고급형', '전문 제작 AI', 'code-duotone']].map(function (p) { return '<a href="ai-detail.html?package=' + p[0] + '">' + icon(p[3]) + '<span><small>' + p[1] + '</small><strong>' + p[2] + '</strong></span>' + icon('caret-right') + '</a>'; }).join('') + '</div><a class="nh-consult-link" href="ai-consult.html?package=business&amp;intent=adoption">AI 도입 상담 ' + icon('arrow-right') + '</a></section></div>' +
      '<nav class="nh-menu-support" aria-label="견적 및 고객지원"><a href="' + h(route('saved')) + '">' + icon('clipboard-text') + '내 견적</a><a href="' + h(route('compare')) + '">' + icon('squares-four') + 'PC 비교</a><a href="support.html">' + icon('headset') + '고객지원</a><a href="support.html#sales-policy">' + icon('package') + '배송 · A/S 안내</a></nav></div></dialog>';
  }
  function syncSelection(category) {
    var page = document.body.dataset.page || 'home';
    // AI 슈퍼컴퓨터 상세·문의는 PC 상세 화면 틀(data-page=pc-detail)을 쓰지만 메뉴에서는 AI 슈퍼컴퓨터로 표시한다.
    if (/\/supercomputer(-inquiry)?\.html$/.test(location.pathname)) page = 'supercomputers';
    var active = page === 'pcs' ? category || 'catalog' : page.indexOf('ai-') === 0 ? 'ai' : page === 'pc-finder' ? 'chat' : page;
    var pcSection = page === 'pcs' || page === 'peripherals' || page === 'pc-detail';
    document.querySelectorAll('[data-nh-nav]').forEach(function (link) {
      var primary = !!link.closest('.nh-primary-links');
      var selected = primary ? (link.dataset.nhNav === 'catalog' && pcSection) || link.dataset.nhNav === active : link.dataset.nhNav === active;
      link.removeAttribute('aria-current');
      if (selected) link.setAttribute('aria-current', primary && pcSection ? 'true' : 'page');
    });
    window.requestAnimationFrame(function () {
      var selectedTab = document.querySelector('.nh-purpose-tabs [aria-current]');
      if (!selectedTab) return;
      var tabs = selectedTab.parentElement;
      if (tabs.scrollWidth > tabs.clientWidth) tabs.scrollLeft += selectedTab.getBoundingClientRect().left - tabs.getBoundingClientRect().left - (tabs.clientWidth - selectedTab.offsetWidth) / 2;
    });
  }
  function bindCategoryNavigation() {
    var form = document.querySelector('[data-dp-filter-form]');
    // Keep real links for new tabs and for pages without a mounted catalogue.
    document.querySelectorAll('a[href]').forEach(function (link) {
      var url = new URL(link.href, document.baseURI);
      if (url.origin !== location.origin || url.searchParams.get('screen') !== 'catalog' || !url.searchParams.has('category')) return;
      link.dataset.nhCategory = url.searchParams.get('category');
      url.hash = 'catalog-products'; link.href = url.href;
    });
    if (!form || form.dataset.nhCategoryBound) return;
    form.dataset.nhCategoryBound = 'true'; form.id = 'catalog-products'; form.tabIndex = -1;
    function alignSearch(focus, smooth) {
      window.requestAnimationFrame(function () {
        var scope = form.closest('[data-dp-catalog]');
        // Short/empty result sets must also have room to align the search row.
        if (scope) scope.style.minHeight = Math.ceil(form.getBoundingClientRect().top - scope.getBoundingClientRect().top + window.innerHeight) + 'px';
        if (focus) form.focus({ preventScroll: true });
        window.scrollTo({ top: Math.max(0, window.scrollY + form.getBoundingClientRect().top), behavior: smooth && !window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'smooth' : 'instant' });
      });
    }
    function filterUrl() {
      var url = new URL(location.href);
      ['q', 'category', 'sort'].forEach(function (name) {
        var value = form.elements[name].value;
        if (value && !(name === 'sort' && value === 'default')) url.searchParams.set(name, value);
        else url.searchParams.delete(name);
      });
      url.searchParams.delete('purpose');
      url.searchParams.delete('sale');   // 판매 상태 칸은 뺐다(2026-10-21 대표 — 목록은 판매중만 나온다)
      return url;
    }
    var restoring = false;
    function syncFilters() {
      syncSelection(form.elements.category.value);
      if (!restoring) history.replaceState(history.state, '', filterUrl());
    }
    form.addEventListener('input', syncFilters);
    form.addEventListener('change', syncFilters);
    form.addEventListener('submit', syncFilters);
    // Reset buttons can also live in an empty-results panel.
    form.closest('[data-dp-catalog]').addEventListener('click', function (event) {
      if (event.target.closest('[data-dp-reset]')) window.queueMicrotask(syncFilters);
    });
    document.addEventListener('click', function (event) {
      var link = event.target.closest('a[data-nh-category]');
      if (!link || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || link.target === '_blank') return;
      var value = link.dataset.nhCategory;
      if (!Array.from(form.elements.category.options).some(function (option) { return option.value === value; })) return;
      event.preventDefault();
      var previous = form.elements.category.value;
      history.replaceState(history.state, '', filterUrl());
      form.elements.category.value = value;
      var next = filterUrl(); next.hash = 'catalog-products';
      if (previous !== value) history.pushState(history.state, '', next);
      else history.replaceState(history.state, '', next);
      form.elements.category.dispatchEvent(new Event('change', { bubbles: true }));
      var dialog = link.closest('dialog[open]');
      if (dialog) {
        var nativeClose = typeof dialog.close === 'function';
        if (nativeClose) dialog.addEventListener('close', function () { alignSearch(true, true); }, { once: true });
        var close = dialog.querySelector('[data-close-dialog]');
        if (close) close.click();
        if (!nativeClose) alignSearch(true, true);
      } else alignSearch(true, true);
    });
    window.addEventListener('popstate', function () {
      var q = new URLSearchParams(location.search);
      restoring = true;
      form.elements.q.value = q.get('q') || '';
      form.elements.category.value = q.get('category') || q.get('purpose') || '';
      form.elements.sort.value = q.get('sort') || 'default';
      form.elements.category.dispatchEvent(new Event('change', { bubbles: true }));
      restoring = false;
      alignSearch(false, false);
    });
    if (location.hash === '#catalog-products') alignSearch(false, false);
  }
  P.headerUi = { route: route };
  P.shell = function (content) {
    var html = originalShell.call(P, content);
    var existing = html.match(/<header class="site-header">[\s\S]*?<\/header>/);
    if (!existing) return html;
    // 클래스가 더 붙거나 순서가 바뀌어도 브랜드 링크를 찾는다(2026-10-20 로고 교체 때 정확한 문자열 매칭이 깨져 헤더 변환이 통째로 빠졌다).
    var brand = existing[0].match(/<a\b[^>]*\bclass="(?:[^"]*\s)?site-brand(?:\s[^"]*)?"[\s\S]*?<\/a>/);
    if (!brand) return html;
    return html.replace(existing[0], header(brand[0])).replace(/<dialog class="site-dialog menu-dialog" id="site-menu"[\s\S]*?<\/dialog>/, menu());
  };
  P.bindShell = function () {
    originalBind.call(P);
    document.querySelectorAll('[data-nh-search]').forEach(function (form) {
      var input = form.querySelector('input[name="q"]'), error = form.querySelector('.nh-search-error');
      var initial = P.qs && P.qs.get('q');
      if (initial) input.value = initial.slice(0, 120);
      form.addEventListener('submit', function (event) {
        event.preventDefault();
        var term = input.value.trim();
        if (!term) { input.setAttribute('aria-invalid', 'true'); error.hidden = false; input.focus(); return; }
        input.removeAttribute('aria-invalid'); error.hidden = true;
        window.location.href = route('catalog', { q: term });
      });
      input.addEventListener('input', function () { if (input.value.trim()) { input.removeAttribute('aria-invalid'); error.hidden = true; } });
    });
    syncSelection(new URLSearchParams(location.search).get('category'));
    bindCategoryNavigation();
  };
}());
