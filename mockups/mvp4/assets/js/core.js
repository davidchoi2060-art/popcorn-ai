(function () {
  'use strict';

  var allowedPages = ['index', 'home', 'pc-finder', 'pcs', 'pc-detail', 'ai-packages', 'ai-detail', 'ai-consult', 'ai-result', 'peripherals', 'mall-handoff', 'support', 'bridge'];
  var PAI = window.PAI || {};
  PAI.pages = PAI.pages || {};
  PAI.data = window.POPCORN_DATA || { products: [], packages: {} };
  PAI.config = window.POPCORN_CONFIG || {};
  PAI.qs = new URLSearchParams(window.location.search);
  PAI.h = function (value) {
    return String(value === undefined || value === null ? '' : value).replace(/[&<>"']/g, function (character) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character];
    });
  };
  PAI.href = function (page, params) {
    var name = String(page || 'index').replace(/\.html$/, '');
    if (allowedPages.indexOf(name) < 0) name = 'index';
    if (name === 'home') name = 'index';
    var query = new URLSearchParams();
    Object.keys(params || {}).forEach(function (key) {
      var value = params[key];
      if (value !== undefined && value !== null && value !== '') query.set(key, String(value));
    });
    return name + '.html' + (query.toString() ? '?' + query.toString() : '');
  };
  PAI.image = function (file) { return 'assets/images/' + String(file || '').replace(/^\/+/, ''); };
  PAI.icon = function (name, cls) {
    var safeName = /^[a-z0-9-]+$/.test(String(name)) ? name : 'question';
    return '<img class="icon' + (cls ? ' ' + PAI.h(cls) : '') + '" src="assets/icons/' + safeName + '.svg" alt="" aria-hidden="true" width="24" height="24">';
  };
  PAI.money = function (value) {
    return typeof value === 'number' && Number.isFinite(value) ? new Intl.NumberFormat('ko-KR').format(value) + '원' : '구성 확인';
  };

  // 헤더는 2026-10-20 대표 승인 가로형 로고(심볼+워드마크 한 장)를 쓴다. 글자가 그림 안에 있어 별도 「팝콘AI」 글자는 헤더에서만 뺀다.
  // 푸터·파비콘은 기존 logo.png 그대로.
  function brand(where) {
    if (where === 'header') return '<a class="site-brand site-brand-logo" href="' + PAI.href('index') + '" aria-label="팝콘AI 처음 화면">' +
      '<img class="brand-logo" src="' + PAI.image('brand/popcornai-header-logo-v2.png') + '" alt="" width="420" height="153" decoding="async"></a>';
    return '<a class="site-brand" href="' + PAI.href('index') + '" aria-label="팝콘AI 처음 화면">' +
      '<img src="' + PAI.image('logo.png') + '" alt="" width="42" height="42"><span>팝콘AI</span></a>';
  }

  function navigation(className) {
    var links = [
      ['PC 쇼핑', PAI.href('pcs'), 'pcs'],
      ['AI 패키지', PAI.href('ai-packages'), 'ai'],
      ['AI로 PC 찾기', PAI.href('pc-finder'), 'recommend'],
      ['고객지원', PAI.href('support'), 'support']
    ];
    return '<nav class="' + className + '" aria-label="주요 메뉴">' + links.map(function (link) {
      return '<a data-nav="' + link[2] + '" href="' + link[1] + '">' + link[0] + '</a>';
    }).join('') + '</nav>';
  }

  PAI.shell = function (content) {
    return '<a class="skip-link" href="#main-content">본문으로 건너뛰기</a>' +
      '<header class="site-header"><div class="container header-inner">' + brand('header') + navigation('desktop-nav') +
      '<div class="header-actions"><button class="icon-button" type="button" data-open-dialog="site-search" aria-label="상품 검색" aria-haspopup="dialog" aria-controls="site-search">' + PAI.icon('magnifying-glass') + '</button>' +
      '<a class="saved-link" href="' + PAI.href('bridge', { target: 'saved' }) + '">' + PAI.icon('clipboard-text') + '<span>내 견적</span></a>' +
      '<button class="icon-button menu-button" type="button" data-open-dialog="site-menu" aria-label="전체 메뉴 열기" aria-haspopup="dialog" aria-controls="site-menu">' + PAI.icon('list') + '</button></div></div></header>' +
      '<main id="main-content" class="page-main" tabindex="-1">' + content + '</main>' +
      '<footer class="site-footer"><div class="container footer-inner"><div class="footer-brand-row">' + brand() +
      '<nav class="footer-links" aria-label="정책 및 지원"><a href="' + PAI.href('support') + '#terms">이용약관</a><a href="' + PAI.href('support') + '#privacy">개인정보처리방침</a><a href="' + PAI.href('support') + '#sales-policy">쇼핑몰 운영정책</a><a href="' + PAI.href('support') + '">고객지원</a></nav></div>' +
      '<p class="footer-caption">좋은 PC에서, 쓸모 있는 AI까지.</p></div></footer>' +
      '<dialog class="site-dialog search-dialog" id="site-search" aria-labelledby="search-dialog-title"><div class="dialog-content"><div class="dialog-heading"><h2 id="search-dialog-title">어떤 PC를 찾으세요?</h2><button class="icon-button" type="button" data-close-dialog aria-label="검색 닫기">' + PAI.icon('x') + '</button></div>' +
      '<form class="search-form" action="pcs.html" method="get" data-search-form><label class="visually-hidden" for="site-search-input">상품명 또는 용도</label><div class="search-input-row">' + PAI.icon('magnifying-glass') + '<input id="site-search-input" name="q" type="search" placeholder="상품명, 부품명, 용도로 찾아보세요" autocomplete="off" maxlength="120" aria-describedby="search-error"><button class="btn btn-primary" type="submit">검색</button></div><p class="error" id="search-error" hidden>검색어를 입력해 주세요.</p></form>' +
      '<div class="search-suggestions"><span>이런 PC를 찾으시나요?</span><a class="chip" href="' + PAI.href('pcs', { purpose: 'gaming' }) + '">게이밍 PC</a><a class="chip" href="' + PAI.href('pcs', { purpose: 'office' }) + '">사무용 PC</a><a class="chip" href="' + PAI.href('pcs', { form: 'mini' }) + '">미니 PC</a></div></div></dialog>' +
      '<dialog class="site-dialog menu-dialog" id="site-menu" aria-labelledby="menu-dialog-title"><div class="dialog-content"><div class="dialog-heading"><h2 id="menu-dialog-title">팝콘AI 메뉴</h2><button class="icon-button" type="button" data-close-dialog aria-label="전체 메뉴 닫기">' + PAI.icon('x') + '</button></div>' + navigation('mobile-nav') +
      '<div class="menu-secondary"><a href="' + PAI.href('bridge', { target: 'custom' }) + '">' + PAI.icon('file-text') + '맞춤 견적' + PAI.icon('caret-right') + '</a><a href="' + PAI.href('bridge', { target: 'saved' }) + '">' + PAI.icon('clipboard-text') + '내 견적' + PAI.icon('caret-right') + '</a></div></div></dialog>';
  };

  PAI.bindShell = function () {
    var triggers = document.querySelectorAll('[data-open-dialog]');
    var page = document.body.dataset.page || 'home';
    var section = page.indexOf('ai-') === 0 ? 'ai' : (['pcs', 'pc-detail', 'peripherals', 'mall-handoff'].indexOf(page) >= 0 ? 'pcs' : page);
    if (page === 'pc-finder' || (page === 'bridge' && PAI.qs.get('target') === 'recommend')) section = 'recommend';
    document.querySelectorAll('[data-nav]').forEach(function (link) {
      if (link.dataset.nav === section) link.setAttribute('aria-current', 'page');
    });
    function closeDialog(dialog) {
      if (typeof dialog.close === 'function') dialog.close();
      else {
        dialog.removeAttribute('open');
        document.documentElement.classList.remove('dialog-is-open');
        if (dialog.returnFocus) dialog.returnFocus.focus();
      }
    }
    triggers.forEach(function (trigger) {
      trigger.addEventListener('click', function () {
        var dialog = document.getElementById(trigger.dataset.openDialog);
        if (!dialog || dialog.open) return;
        dialog.returnFocus = trigger;
        if (typeof dialog.showModal === 'function') dialog.showModal();
        else dialog.setAttribute('open', '');
        document.documentElement.classList.add('dialog-is-open');
        var focusTarget = dialog.querySelector('input') || dialog.querySelector('button,a');
        if (focusTarget) focusTarget.focus();
      });
    });
    document.querySelectorAll('.site-dialog').forEach(function (dialog) {
      dialog.querySelectorAll('[data-close-dialog]').forEach(function (button) {
        button.addEventListener('click', function () { closeDialog(dialog); });
      });
      dialog.addEventListener('click', function (event) {
        if (event.target === dialog) closeDialog(dialog);
      });
      dialog.addEventListener('close', function () {
        document.documentElement.classList.remove('dialog-is-open');
        if (dialog.returnFocus && document.contains(dialog.returnFocus)) dialog.returnFocus.focus();
      });
      dialog.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && typeof dialog.close !== 'function') closeDialog(dialog);
      });
    });
    document.querySelectorAll('[data-start-finder]').forEach(function (link) {
      link.addEventListener('click', function (event) {
        event.preventDefault();
        try {
          PAI.finderEntry.start({text:'',productId:link.dataset.finderProduct || null,
            source:link.dataset.finderProduct ? 'product' : 'category',purpose:link.dataset.finderPurpose || ''});
        } catch (error) {
          var notice=link.parentElement.querySelector('.finder-entry-error');
          if (!notice) {notice=document.createElement('p');notice.className='finder-entry-error error';notice.setAttribute('role','alert');link.parentElement.appendChild(notice);}
          notice.textContent='선택한 내용을 이어가지 못했어요. 브라우저 설정을 확인한 뒤 다시 시도해 주세요.';
        }
      });
    });
    var search = document.querySelector('[data-search-form]');
    if (search) {
      search.addEventListener('submit', function (event) {
        event.preventDefault();
        var input = search.querySelector('[name=q]');
        var query = input.value.trim();
        var error = document.getElementById('search-error');
        if (!query) {
          input.setAttribute('aria-invalid', 'true');
          error.hidden = false;
          input.focus();
          return;
        }
        input.removeAttribute('aria-invalid');
        error.hidden = true;
        window.location.href = PAI.href('pcs', { q: query });
      });
    }
  };
  window.PAI = PAI;
}());
