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
    ['주변기기', null, 'headset', '모니터와 주변기기']
  ];
  function route(screen, params) {
    var state = screen === 'chat' ? 'welcome' : 'normal';
    if (typeof P.designHref === 'function') return P.designHref(screen, state, params || {});
    var q = new URLSearchParams({ screen: screen, state: state });
    Object.keys(params || {}).forEach(function (key) { if (params[key] !== null && params[key] !== undefined && params[key] !== '') q.set(key, params[key]); });
    if (P.qs && P.qs.get('dataset') && !q.has('dataset')) q.set('dataset', P.qs.get('dataset'));
    return 'design-only/design-screen.html?' + q.toString();
  }
  function catalog(category) { return route('catalog', category ? { category: category } : {}); }
  function menuButton(className, text) {
    return '<button class="' + className + '" type="button" data-open-dialog="site-menu" aria-label="전체 카테고리 열기" aria-haspopup="dialog" aria-controls="site-menu">' + icon('list') + '<span>' + text + '</span></button>';
  }
  function navLink(label, href, current, className) {
    return '<a class="' + (className || '') + '" href="' + h(href) + '"' + (current ? ' data-nh-nav="' + h(current) + '"' : '') + '>' + label + '</a>';
  }
  function header(brand) {
    return '<header class="site-header nh-header"><div class="container nh-top">' + brand +
      '<form class="nh-search" data-nh-search role="search" action="design-only/design-screen.html" method="get"><label class="visually-hidden" for="nh-search-input">상품명, CPU 또는 그래픽카드 검색</label><div class="nh-search-field"><input id="nh-search-input" name="q" type="search" placeholder="상품명, CPU, 그래픽카드 검색" autocomplete="off" maxlength="120" aria-describedby="nh-search-error"><button type="submit" aria-label="상품 검색">' + icon('magnifying-glass') + '</button></div><p class="nh-search-error" id="nh-search-error" role="alert" hidden>검색어를 입력해 주세요.</p></form>' +
      '<div class="nh-tools"><a class="nh-tool" href="' + h(route('saved')) + '" data-nh-nav="saved">' + icon('clipboard-text') + '<span>내 견적</span></a><a class="nh-tool nh-support-tool" href="support.html" data-nh-nav="support">' + icon('headset') + '<span>고객지원</span></a>' + menuButton('nh-mobile-menu', '전체 메뉴') + '</div></div>' +
      '<div class="nh-menu-bar"><nav class="container nh-desktop-nav" aria-label="주요 메뉴">' + menuButton('nh-category-button', '전체 카테고리') + '<div class="nh-main-links">' +
      navLink('PC 쇼핑', catalog(), 'catalog') + navLink('게이밍 PC', catalog('게이밍 PC'), '게이밍 PC') + navLink('사무용 PC', catalog('사무·업무용'), '사무·업무용') + navLink('작업용 PC', catalog('디자인·영상'), '디자인·영상') + navLink('미니 PC', catalog('미니 PC'), '미니 PC') + navLink('AI 패키지', 'ai-packages.html', 'ai') + '</div>' +
      navLink(icon('chat-circle') + '<span>AI로 PC 찾기</span>' + icon('arrow-right'), route('chat'), 'chat', 'nh-ai-entry') + '</nav>' +
      '<nav class="container nh-mobile-nav" aria-label="주요 메뉴">' + navLink('PC 쇼핑', catalog(), 'catalog') + navLink('AI 패키지', 'ai-packages.html', 'ai') + navLink(icon('chat-circle') + '<span>AI로 PC 찾기</span>', route('chat'), 'chat', 'nh-mobile-ai') + '</nav></div></header>';
  }
  function menu() {
    return '<dialog class="site-dialog menu-dialog nh-menu" id="site-menu" aria-labelledby="menu-dialog-title"><div class="nh-menu-content"><div class="nh-menu-heading"><div><p>POPCORN AI</p><h2 id="menu-dialog-title">어떤 PC를 찾으세요?</h2></div><button class="icon-button" type="button" data-close-dialog aria-label="전체 카테고리 닫기">' + icon('x') + '</button></div>' +
      '<div class="nh-menu-layout"><section class="nh-menu-pcs" aria-labelledby="nh-pc-menu-title"><div class="nh-group-heading"><h3 id="nh-pc-menu-title">PC 쇼핑</h3><a href="' + h(catalog()) + '">전체 PC 보기 ' + icon('arrow-right') + '</a></div><div class="nh-category-grid">' + categories.map(function (c) { return '<a href="' + h(c[1] ? catalog(c[1]) : 'peripherals.html') + '"><span class="nh-category-icon">' + icon(c[2]) + '</span><span><strong>' + h(c[0]) + '</strong><small>' + h(c[3]) + '</small></span>' + icon('caret-right') + '</a>'; }).join('') + '</div><a class="nh-menu-finder" href="' + h(route('chat')) + '">' + icon('chat-circle') + '<span><strong>AI로 PC 찾기</strong><small>용도와 예산을 말하면, 함께 찾아드려요.</small></span>' + icon('arrow-right') + '</a></section>' +
      '<section class="nh-menu-ai" aria-labelledby="nh-ai-menu-title"><div class="nh-group-heading"><h3 id="nh-ai-menu-title">AI 패키지</h3><a href="ai-packages.html">비교하기 ' + icon('arrow-right') + '</a></div><p class="nh-group-copy">내 일에 필요한 AI를 PC와 함께.</p><div class="nh-package-list">' + [['basic', '기본형', '내 자료 AI 비서', 'file-text-duotone'], ['business', '업무형', '업무형 로컬 AI', 'users-three-duotone'], ['advanced', '고급형', '전문 제작 AI', 'code-duotone']].map(function (p) { return '<a href="ai-detail.html?package=' + p[0] + '">' + icon(p[3]) + '<span><small>' + p[1] + '</small><strong>' + p[2] + '</strong></span>' + icon('caret-right') + '</a>'; }).join('') + '</div><a class="nh-consult-link" href="ai-consult.html?package=business&amp;intent=adoption">AI 도입 상담 ' + icon('arrow-right') + '</a></section></div>' +
      '<nav class="nh-menu-support" aria-label="견적 및 고객지원"><a href="' + h(route('saved')) + '">' + icon('clipboard-text') + '내 견적</a><a href="' + h(route('compare')) + '">' + icon('squares-four') + 'PC 비교</a><a href="support.html">' + icon('headset') + '고객지원</a><a href="support.html#sales-policy">' + icon('package') + '배송 · A/S 안내</a></nav></div></dialog>';
  }
  P.headerUi = { route: route };
  P.shell = function (content) {
    var html = originalShell.call(P, content);
    var existing = html.match(/<header class="site-header">[\s\S]*?<\/header>/);
    if (!existing) return html;
    var brand = existing[0].match(/<a class="site-brand"[\s\S]*?<\/a>/);
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
    var page = document.body.dataset.page || 'home', category = P.qs && P.qs.get('category');
    var active = page === 'pcs' ? category || 'catalog' : page.indexOf('ai-') === 0 ? 'ai' : page === 'pc-finder' ? 'chat' : page;
    document.querySelectorAll('[data-nh-nav]').forEach(function (link) {
      if (link.dataset.nhNav === active || (link.dataset.nhNav === 'catalog' && page === 'pcs' && link.closest('.nh-mobile-nav'))) link.setAttribute('aria-current', 'page');
    });
  };
}());
