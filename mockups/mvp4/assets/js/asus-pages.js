/* ASUS AI PC 기획전: 서브메인(asus.html)과 상세 3종(asus-pc.html?model=). 제목·사양·가격·버튼은 전부 실제 HTML이다.
 * 모델 값은 서버 응답(A.load)만 쓴다. 불러오는 중·실패·빈 결과를 그대로 말하고, 금액을 더하거나 구성을 대신 고르지 않는다.
 * 상세 3종에는 금액과 내부 검토 상태를 표시하지 않는다(2026-11-06 사용자 지시). 목록·문의의 기획 검토가 표기는 그대로다. */
(function () {
  'use strict';
  var P = window.PAI, h = P.h, A = P.asus;

  function arrow() { return P.icon('arrow-right'); }

  function brandBar(backHref, backLabel) {
    return '<div class="az-brand"><div class="az-wrap az-brand-row">' +
      '<a class="az-logo-link" href="asus.html"><img src="' + A.image('logo-asus-white.png') + '" alt="ASUS" width="150" height="30"><span>ASUS 기획전</span></a>' +
      (backHref ? '<a class="az-back" href="' + h(backHref) + '">' + P.icon('arrow-left') + h(backLabel) + '</a>' : '<span class="az-brand-with">ASUS × 팝콘AI</span>') +
      '</div></div>';
  }

  function headline() {
    return '<span>ASUS의 강력한 성능,</span> <em>나의 AI 작업실.</em>';
  }

  function planBlock(m) {
    return '<div class="az-plan"><p class="az-plan-label">' + h(A.PLAN_LABEL) + '</p><p class="az-plan-value">' + h(A.planText(m)) + '</p><p class="az-plan-note">' + h(A.PLAN_NOTE) + '</p></div>';
  }

  function specRows(m) {
    return '<dl class="az-specs">' +
      row('CPU', m.cpu) + row('메모리', m.ram) + row('SSD', m.ssd) +
      row('케이스', m.caseName) + row('CPU 쿨러', m.coolerName) + '</dl>';
    function row(k, v) { return '<div><dt>' + h(k) + '</dt><dd>' + h(v) + '</dd></div>'; }
  }

  function card(m) {
    return '<article class="az-card az-tone-' + h(m.tone) + '" aria-labelledby="az-card-' + h(m.id) + '">' +
      '<h3 class="az-tag" id="az-card-' + h(m.id) + '"><a href="' + h(A.detailHref(m.id)) + '">' + h(m.name) + '</a></h3>' +
      '<figure class="az-card-photo"><a href="' + h(A.detailHref(m.id)) + '" tabindex="-1" aria-hidden="true"><img src="' + h(A.image(m.heroImage)) + '" alt="' + h(m.heroAlt) + '" width="800" height="800" loading="lazy" decoding="async"></a></figure>' +
      '<div class="az-card-body">' +
      '<p class="az-card-tagline">' + h(m.tagline) + '</p>' +
      '<p class="az-gpu"><span>그래픽카드</span><strong>' + h(m.gpu) + '</strong></p>' +
      '<p class="az-vram"><span>그래픽 메모리</span><strong>' + h(m.vram) + '</strong></p>' +
      specRows(m) + planBlock(m) +
      P.asusCart.html(m.id, m.name) +
      '<a class="az-card-detail" href="' + h(A.detailHref(m.id)) + '" aria-label="' + h(m.name) + ' 상품 정보 보기">상품 정보 보기' + arrow() + '</a>' +
      '</div></article>';
  }

  // 불러오는 중·실패·빈 결과 안내. 어느 경우에도 모델 값을 대신 그리지 않는다.
  function statusBox(kind, message) {
    return '<div class="az-load az-load-' + h(kind) + '" data-az-load="' + h(kind) + '"' + (kind === 'error' ? ' role="alert"' : ' role="status"') + '><p>' + h(message) + '</p>' +
      (kind === 'error' ? '<button class="az-btn az-btn-solid" type="button" data-az-retry>다시 시도</button>' : '') + '</div>';
  }

  // 응답을 받아 그리는 공통 흐름. 다시 시도가 겹치면 마지막 요청의 결과만 그린다.
  function loadInto(box, draw, force) {
    var token = (box.azToken || 0) + 1;
    box.azToken = token;
    box.innerHTML = statusBox('loading', A.LOADING);
    A.load(force).then(function () {
      if (box.azToken === token) draw();
    }, function () {
      if (box.azToken !== token) return;
      box.innerHTML = statusBox('error', A.LOAD_FAILED);
      box.querySelector('[data-az-retry]').addEventListener('click', function () { loadInto(box, draw, true); });
    });
  }

  function homePage() {
    var html = '<div class="az-page">' + brandBar() +
      '<section class="az-hero az-hero-main" aria-labelledby="az-title"><div class="az-wrap az-hero-grid">' +
      '<div class="az-hero-copy"><p class="az-with">ASUS × 팝콘AI</p><h1 id="az-title">' + headline() + '</h1>' +
      '<p class="az-lead">' + h(A.INTRO) + '</p><p class="az-lead-sub">하는 일에 맞춰 ASUS PC 3종을 비교해 보세요.</p>' +
      '<ul class="az-fields" aria-label="활용 분야">' + A.FIELDS.map(function (f) { return '<li>' + h(f) + '</li>'; }).join('') + '</ul>' +
      '<a class="az-btn az-btn-cyan" href="#az-products">3종 핵심 사양 비교하기' + arrow() + '</a>' +
      '<p class="az-hero-caption"><b>' + h(A.CASE_NAME) + '</b>' + h(A.BUILD_NOTE) + ' ' + h(A.LIGHT_NOTE) + '</p></div>' +
      '</div></section>' +

      '<section class="az-products" id="az-products" aria-labelledby="az-products-title"><div class="az-wrap">' +
      '<header class="az-head"><h2 id="az-products-title">어떤 일을 하시나요?</h2><p>필요한 성능과 구성을 비교해 보세요.</p></header>' +
      '<p class="az-terms">CPU(중앙처리장치) · GPU(그래픽카드) · RAM(메모리) · SSD(저장장치). 그래픽 메모리와 메모리는 서로 다른 항목입니다.</p>' +
      '<div id="az-cards-root"></div>' +
      '<div class="az-notice"><p>' + P.icon('info') + '<span><b>' + h(A.PLAN_LABEL) + '.</b> ' + h(A.TOTAL_NOTE) + '</span></p><p>' + P.icon('gear') + '<span>프로그램 설치와 사용 안내는 별도 문의해 주세요.</span></p></div>' +
      '</div></section>' +

      '<section class="az-process" aria-labelledby="az-process-title"><div class="az-wrap">' +
      '<h2 id="az-process-title">이렇게 진행합니다</h2><ol>' + A.PROCESS.map(function (s, i) { return '<li><b>' + String(i + 1).padStart(2, '0') + '</b>' + h(s) + '</li>'; }).join('') + '</ol>' +
      '</div></section>' +

      closing(null) + footnote() + '</div>';
    return { html: html, mount: function () {
      document.title = 'ASUS 기획전 | 팝콘AI';
      var root = document.getElementById('az-cards-root');
      loadInto(root, function () {
        if (!A.MODELS.length && !A.UNAVAILABLE.length) { root.innerHTML = statusBox('empty', '지금 표시할 구성이 없습니다.'); return; }
        root.innerHTML = (A.MODELS.length ? '<div class="az-cards">' + A.MODELS.map(card).join('') + '</div>' : '') +
          (A.UNAVAILABLE.length ? statusBox('partial', '일부 구성 정보를 표시할 수 없습니다. 문의해 주시면 안내해 드립니다.') : '');
      });
    } };
  }

  function closing(m) {
    var cta = '<a class="az-btn az-btn-cyan" href="' + h(m ? A.inquiryHref(m.id) : 'asus-consult.html') + '">PC 구성 문의하기' + arrow() + '</a>';
    return '<section class="az-closing" id="az-inquiry"><div class="az-wrap az-closing-row"><div>' +
      '<h2>사용하는 프로그램과 하려는 일을 알려주세요.</h2><p>필요한 구성과 설치 범위를 안내해 드립니다.</p>' +
      '<div class="az-closing-actions">' + cta + '</div></div></div></section>';
  }

  function footnote(text) { return '<p class="az-footnote">' + h(text || A.FOOTNOTE) + '</p>'; }

  // 제품 줄은 한 줄에 제품 1종과 수량. 사양(그래픽 메모리)과 안내(팬·운영체제)는 구성품처럼 보이지 않게 글자만 쓴다.
  function partRow(part) {
    var body = part.kind === 'product'
      ? '<div class="az-part-item">' + (part.image ? '<figure class="az-opt-thumb"><img data-az-thumb src="' + h(part.image) + '" alt="' + h(part.name) + '" width="88" height="88" loading="lazy" decoding="async"></figure>' : '') +
        '<p class="az-part-text"><strong>' + h(part.name) + '</strong><span class="az-part-qty">' + h(part.quantity) + '</span></p></div>'
      : '<p class="az-part-head">' + h(part.name) + '</p>';
    return '<tr data-az-part="' + h(part.kind) + '"><th scope="row">' + h(part.label) + '</th><td>' + body + '</td></tr>';
  }

  // 사진을 받지 못하면 깨진 그림 대신 제품명만 남긴다. 다른 그림으로 대신하지 않는다.
  function guardThumbs(root) {
    root.querySelectorAll('img[data-az-thumb]').forEach(function (img) {
      function drop() { if (img.parentNode) img.parentNode.remove(); }
      img.addEventListener('error', drop);
      if (img.complete && img.naturalWidth === 0 && img.getAttribute('src')) drop();
    });
  }

  function missing(title, text) {
    return '<section class="az-missing az-wrap"><h1>' + h(title) + '</h1><p>' + h(text) + '</p><a class="az-btn az-btn-solid" href="asus.html">ASUS 기획전 보기' + arrow() + '</a></section>';
  }

  function detailHtml(m) {
    var others = A.MODELS.filter(function (x) { return x.id !== m.id; });
    var core = [['CPU', m.cpu], ['그래픽카드', m.gpu], ['그래픽 메모리', m.vram], ['메모리', m.ram], ['SSD', m.ssd]];
    return '<section class="az-hero az-hero-detail" aria-labelledby="az-title"><div class="az-wrap az-detail-grid">' +
      '<figure class="az-detail-art"><img src="' + h(A.image(m.heroImage)) + '" alt="' + h(m.heroAlt) + '" width="800" height="800" fetchpriority="high"><figcaption><b>' + h(m.caseName) + '</b>' + h(A.BUILD_NOTE) + ' ' + h(A.LIGHT_NOTE) + '</figcaption></figure>' +
      '<div class="az-detail-copy"><p class="az-with">' + h(A.HEADLINE) + '</p><h1 id="az-title">' + h(m.name) + '</h1><p class="az-lead">' + h(m.tagline) + '</p>' +
      '<ul class="az-core">' + core.map(function (c) { return '<li><span>' + h(c[0]) + '</span><strong>' + h(c[1]) + '</strong></li>'; }).join('') + '</ul>' +
      '</div>' +
      '<aside class="az-detail-buy" aria-label="구매와 문의">' + P.asusCart.html(m.id, m.name) + '<a class="az-btn az-btn-cyan" href="' + h(A.inquiryHref(m.id)) + '">PC 구성 문의하기' + arrow() + '</a></aside>' +
      '</div>' +
      '<nav class="az-subnav" aria-label="이 페이지 안내"><div class="az-wrap"><a href="#az-who">추천 대상</a><a href="#az-uses">활용 업무</a><a href="#az-parts">전체 구성</a><a href="#az-install">설치·사용 안내</a></div></nav></section>' +

      '<section class="az-section" id="az-who" aria-labelledby="az-who-title"><div class="az-wrap"><h2 id="az-who-title">이런 분께 추천합니다</h2><ul class="az-who">' +
      m.forWho.map(function (w, i) { return '<li>' + P.icon(m.whoIcons[i]) + '<span>' + h(w) + '</span></li>'; }).join('') + '</ul>' +
      (m.explain ? '<p class="az-explain"><b>로컬 AI란?</b> ' + h(m.explain) + '</p>' : '') + '</div></section>' +

      '<section class="az-section az-section-tint" id="az-uses" aria-labelledby="az-uses-title"><div class="az-wrap"><h2 id="az-uses-title">이렇게 쓸 수 있어요</h2><ol class="az-uses">' +
      m.uses.map(function (u, i) {
        return '<li class="az-use"><figure><img src="' + h(A.useImage(u.image)) + '" alt="' + h(u.alt) + '" width="700" height="280" loading="lazy" decoding="async"><figcaption>사용 예시</figcaption></figure><div class="az-use-body"><h3><b>' + String(i + 1).padStart(2, '0') + '</b>' + h(u.title) + '</h3><p>' + h(u.text) + '</p>' +
          (u.example ? '<p class="az-use-example">' + h(u.example) + '</p>' : '') +
          '<ol class="az-steps" aria-label="진행 순서">' + u.steps.map(function (s) { return '<li>' + h(s) + '</li>'; }).join('') + '</ol></div></li>';
      }).join('') + '</ol>' +
      '<p class="az-caution">' + P.icon('info') + '<span>' + h(A.PHOTO_NOTE) + ' 예시 화면은 실측 결과가 아닙니다.</span></p>' +
      '<p class="az-caution az-caution-strong">' + P.icon('warning-circle-fill') + '<span>' + h(A.PERFORMANCE) + '</span></p>' +
      (m.limit ? '<p class="az-caution az-caution-strong" data-az-limit>' + P.icon('warning-circle-fill') + '<span>' + h(m.limit) + '</span></p>' : '') +
      (m.prepare ? '<p class="az-caution">' + P.icon('info') + '<span>준비 안내: ' + h(m.prepare) + '</span></p>' : '') +
      '</div></section>' +

      '<section class="az-section" id="az-parts" aria-labelledby="az-parts-title"><div class="az-wrap"><h2 id="az-parts-title">전체 부품 보기</h2>' +
      '<p class="az-sub">' + h(A.PARTS_NOTE) + '</p>' +
      '<div class="az-table-wrap"><table class="az-table"><caption class="visually-hidden">' + h(m.name) + ' 부품 구성</caption><thead><tr><th scope="col">항목</th><th scope="col">제품</th></tr></thead><tbody>' +
      m.parts.map(partRow).join('') + '</tbody></table></div>' +
      '<div class="az-notice"><p>' + P.icon('computer-tower') + '<span>' + h(A.COMPAT) + '</span></p></div>' +
      '</div></section>' +

      '<section class="az-section az-section-tint" id="az-install" aria-labelledby="az-install-title"><div class="az-wrap"><h2 id="az-install-title">설치·사용 안내</h2><div class="az-install">' +
      A.INSTALL.map(function (x) { return '<article>' + P.icon(x.icon) + '<div><h3>' + h(x.title) + '</h3><p>' + h(x.text) + '</p></div></article>'; }).join('') + '</div>' +
      '<ul class="az-sale-notes">' + A.SALE_NOTES.map(function (t) { return '<li>' + h(t) + '</li>'; }).join('') + '</ul></div></section>' +

      closing(m) +
      (others.length ? '<section class="az-section" aria-labelledby="az-others-title"><div class="az-wrap"><h2 id="az-others-title">다른 구성 보기</h2><div class="az-others">' +
      others.map(function (o) { return '<a href="' + h(A.detailHref(o.id)) + '"><img src="' + h(A.image(o.heroImage)) + '" alt="" width="124" height="124" loading="lazy" decoding="async"><span><strong>' + h(o.name) + '</strong><small>추천 대상: ' + h(o.forWho.join(' / ')) + '</small><small>' + h(o.gpu) + '</small><b>자세히 보기' + arrow() + '</b></span></a>'; }).join('') +
      '</div></div></section>' : '') + footnote(A.DETAIL_FOOTNOTE);
  }

  function detailPage() {
    var id = P.qs.get('model');
    if (!A.known(id)) {
      return { html: '<div class="az-page">' + brandBar('asus.html', 'ASUS 기획전') + missing('PC를 다시 선택해 주세요.', '선택한 구성을 찾을 수 없습니다.') + '</div>', mount: function () { document.title = 'ASUS 기획전 | 팝콘AI'; } };
    }
    var html = '<div class="az-page az-detail az-tone-' + h(A.META[id].tone) + '">' + brandBar('asus.html', 'ASUS 기획전') + '<div id="az-detail-root"></div></div>';
    return { html: html, mount: function () {
      document.title = 'ASUS 기획전 | 팝콘AI';
      var root = document.getElementById('az-detail-root');
      loadInto(root, function () {
        var m = A.find(id);
        if (!m) { root.innerHTML = missing('이 구성 정보를 표시할 수 없습니다.', '다른 구성을 보시거나 잠시 후 다시 확인해 주세요.'); return; }
        root.innerHTML = detailHtml(m);
        guardThumbs(root);
        document.title = m.name + ' | ASUS 기획전 | 팝콘AI';
        if (location.hash) { var anchor = document.getElementById(location.hash.slice(1)); if (anchor) anchor.scrollIntoView(); }
      });
    } };
  }

  P.pages['asus-home'] = homePage;
  P.pages['asus-detail'] = detailPage;
}());
