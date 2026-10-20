(function () {
  'use strict';
  var P = window.PAI, h = P.h;
  var icons = { CPU: 'cpu', GPU: 'graphics-card', RAM: 'memory', SSD: 'hard-drive', HDD: 'hard-drive', MB: 'cpu', COOLER: 'gear', POWER: 'plug', CASE: 'computer-tower' };
  var labels = { CPU: 'CPU', GPU: '그래픽카드', RAM: '메모리', SSD: 'SSD', HDD: '하드디스크', MB: '메인보드', COOLER: 'CPU 쿨러', POWER: '파워', CASE: '케이스' };
  function quantity(value) { var str = String(value == null ? '' : value).trim(); var n = /^\d+$/.test(str) ? Number(str) : 1; return Number.isInteger(n) && n >= 1 && n <= 10 ? n : 1; }
  function validPrice(p) { return p && typeof p.price === 'number' && Number.isFinite(p.price) && p.price > 0; }
  function amount(p, q) { return validPrice(p) ? P.money(p.price * quantity(q)) : '가격 확인 필요'; }
  function sourceModel(s) { return s.basis === 'registered-spec-source-text' && Number.isInteger(s.sourceOrdinal) && s.sourceOrdinal >= 0 && Boolean(String(s.modelText || '').trim()); }
  function parts(p) {
    if (!p || !Array.isArray(p.specs) || p.bomStatus === 'missing') return [];
    if (p.source && p.source.kind === 'current-admin-observation' && !p.configurationId && p.source.bomBasis !== 'registered-admin-spec-source-text') return [];
    return p.specs.filter(function (s) { return s && String(s.value || s.modelText || '').trim() && (s.registered === true || sourceModel(s) || s.partId !== undefined && s.partId !== null); });
  }
  function pending(p) {
    if (p.source && p.source.kind === 'historical') return '현재 판매 여부와 구성을 확인해 주세요.';
    if (p.isSelling !== true || p.statusKey === 'oos' || p.stockQty === 0 || /품절|판매\s*종료|단종/.test(p.saleStatus || '')) return '현재 판매 여부를 확인해야 합니다.';
    if (!validPrice(p)) return '현재 상품 가격을 확인해야 합니다.';
    // 구성 확인은 막는 조건이 아니다 — 금액·사양이 다르면 상담사가 전화로 조정해 판매한다(2026-10-20 대표).
    return '';
  }
  function route(screen, p, q) { return P.designHref(screen, 'normal', { id: p.id, quantity: quantity(q) }); }
  function partRoute(p, s) {
    var params = { id: p.id };
    if (s.registered) return '';
    if (sourceModel(s)) params.sourceOrdinal = s.sourceOrdinal;
    else if (s.partId !== undefined && s.partId !== null) params.partId = s.partId;
    else return '';
    return P.designHref('component', 'normal', params);
  }
  // /mvp4: 서버가 공개 승인한 같은 출처 사진 경로(부품 사진 · 대표 사진)도 받는다. 그 밖의 값은 아이콘으로.
  function safeImage(value) { return typeof value === 'string' && (/^(assets\/|https:\/\/)/.test(value) || /^\/api\/(product-images\/\d+\/detail|customer\/products\/\d+\/representative-image(\?size=card)?)$/.test(value)) ? value : ''; }
  function media(src, icon, alt, cls) {
    return '<div class="' + cls + '">' + (src ? '<img data-cf-image data-cf-fallback="' + icon + '" src="' + h(src) + '" alt="' + h(alt) + '" loading="lazy">' : '<span class="cf-icon-image">' + P.icon(icon) + '</span>') + '</div>';
  }
  function facts(s) {
    return (Array.isArray(s.facts) ? s.facts : []).filter(function (f) {
      if (!f || !String(f.label || '').trim() || f.value === undefined || f.value === null || !String(f.value).trim()) return false;
      // Some observed GPU facts contain a truncated family (RTX 50/RTX 30).
      // Omit that incomplete fact; the exact registered model remains in the row heading.
      return !(s.slot === 'GPU' && /모델/.test(f.label) && /^(RTX|GTX|RX)\s*\d{1,2}$/i.test(String(f.value).trim()));
    });
  }
  function partRow(p, s, i) {
    var label = labels[s.slot] || s.label || '부품', icon = icons[s.slot] || 'package';
    var name = String(s.value || s.modelText || ''), fs = facts(s), link = partRoute(p, s);
    var mismatch = (Array.isArray(p.bomMismatches) ? p.bomMismatches : []).some(function (m) { return m.slot === s.slot; });
    var count = Number.isInteger(s.quantity) && s.quantity > 0 ? s.quantity + '개' : '수량 확인';
    // Future component API contract: spec.image must be an approved local assets/ or HTTPS URL
    // for this exact part. Never substitute an unrelated PC/product photo as a component image.
    var photo = safeImage(s.image);
    // 2026-10-20 대표 「CPU도 처음엔 닫힌 상태로, 누르면 펼쳐지게」 -- 모든 부품 행은 닫힌 채로 시작한다(실제 open 속성).
    return '<details class="cf-part"><summary><span class="cf-part-type">' + P.icon(icon) + '<span>' + h(label) + '</span></span><span class="cf-part-name">' + h(name) + (mismatch ? '<span class="cf-part-warning">모델 정보 확인 필요</span>' : '') + '</span><span class="cf-part-count">' + h(count) + '</span>' + P.icon('caret-down') + '</summary>' +
      '<div class="cf-part-expanded">' + media(photo, icon, name + ' 부품 사진', 'cf-component-media') + '<section class="cf-facts"><h3>상세 사양</h3>' + (fs.length ? '<dl>' + fs.map(function (f) { return '<div><dt>' + h(f.label) + '</dt><dd>' + h(f.value) + '</dd></div>'; }).join('') + '</dl>' : '<p class="cf-muted">등록된 모델명 외 상세 사양은 확인이 필요합니다.</p>') + '</section><section class="cf-role"><h3>어떤 역할을 하나요?</h3><p>' + h(s.role || '등록된 부품의 역할 설명을 확인하고 있습니다.') + '</p>' + (link ? '<a class="cf-text-link" href="' + h(link) + '">부품 정보 자세히' + P.icon('arrow-right') + '</a>' : '') + '</section></div></details>';
  }
  function sourceNotice(p) {
    var issue = pending(p);
    if (!issue && p.bomStatus === 'registered') return '<p class="cf-source">' + P.icon('info') + '<span>팝콘PC 몰에 등록된 구성입니다. 최종 구성과 금액은 상담 시 확정합니다.' + (p.service ? ' · ' + h(p.service) : '') + '</span></p>';
    if (issue) return '<p class="cf-source cf-source-warning">' + P.icon('info') + '<span>' + h(issue) + '</span></p>';
    if (p.configurationCompleteness === 'unverified' || p.bomStatus === 'configuration-only') return '<p class="cf-source">' + P.icon('info') + '<span>상품에 연결된 부품 구성입니다. 최종 구성과 수급은 상담 시 확인해 주세요.</span></p>';
    return '';
  }
  function purchase(p, q) {
    var issue = pending(p);
    return '<aside class="cf-purchase" aria-labelledby="cf-purchase-title"><h2 id="cf-purchase-title">이 PC의 견적</h2><div class="cf-total"><span>PC 합계</span><strong data-cf-total>' + h(amount(p, q)) + '</strong></div><div class="cf-unit"><span>PC 본체 단가</span><span>' + h(amount(p, 1)) + '</span></div><div class="cf-quantity-row"><span id="cf-quantity-label">수량</span><div class="cf-quantity" role="group" aria-labelledby="cf-quantity-label"><button type="button" data-cf-minus aria-label="PC 수량 1대 줄이기"' + (q === 1 ? ' disabled' : '') + '>−</button><output id="cf-quantity" aria-live="polite">' + q + '<span>대</span></output><button type="button" data-cf-plus aria-label="PC 수량 1대 늘리기"' + (q === 10 ? ' disabled' : '') + '>+</button></div></div><p class="cf-delivery">배송·추가 서비스는 상담 시 확인합니다.</p><div class="cf-purchase-actions">' +
      (issue ? '<button class="btn btn-primary" disabled>견적 보관 전 확인 필요</button>' : '<a class="btn btn-primary" data-cf-action="save" href="' + h(route('save', p, q)) + '">' + P.icon('clipboard-text') + '견적 보관하기</a>') +
      '<a class="btn cf-consult" data-cf-action="consult" href="' + h(route('consult', p, q)) + '">' + P.icon('chat-circle') + (issue ? '상품·구성 문의' : '구매 상담 신청') + '</a></div><p class="cf-consent-note">견적 보관과 구매 상담은 별개입니다.<br>보관만 한 경우에는 먼저 연락하지 않습니다.</p></aside>';
  }
  function render(p, q, state) {
    q = quantity(q); state = state || 'normal';
    var catalog = P.designHref('catalog', 'normal');
    var crumb = '<nav class="cf-breadcrumb" aria-label="현재 위치"><a href="' + h(P.designHref('home', 'normal')) + '">홈</a>' + P.icon('caret-right') + '<a href="' + h(catalog) + '">PC 쇼핑</a>' + P.icon('caret-right') + '<span aria-current="page">PC 구성</span></nav>';
    if (state === 'loading') return '<div class="container cf-page">' + crumb + '<section class="cf-empty" aria-busy="true" role="status"><h1>PC 구성을 불러오고 있어요.</h1><div class="cf-loading"></div></section></div>';
    if (!p || state === 'error' || state === 'not-found') return '<div class="container cf-page">' + crumb + '<section class="cf-empty"><h1>' + (state === 'error' ? 'PC 구성을 불러오지 못했어요.' : '선택한 PC를 찾을 수 없어요.') + '</h1><p>' + (state === 'error' ? '잠시 후 다시 확인해 주세요.' : '상품 목록에서 PC를 다시 선택해 주세요.') + '</p><div class="cf-empty-actions">' + (p && state === 'error' ? '<a class="btn btn-primary" href="' + h(route('product', p, q)) + '">다시 확인하기</a>' : '') + '<a class="btn btn-outline" href="' + h(catalog) + '">PC 둘러보기</a></div></section></div>';
    // Explicit local review states affect this view only; the catalog snapshot is never mutated.
    p = Object.assign({}, p);
    if (state === 'out-of-stock') { p.isSelling = false; p.saleStatus = '품절'; }
    if (state === 'discontinued') { p.isSelling = false; p.saleStatus = '판매 종료'; }
    if (state === 'price-unavailable') p.price = null;
    if (state === 'missing-specs') { p.specs = []; p.bomStatus = 'missing'; }
    if (state === 'missing-image') p.mediaStatus = 'missing';
    var data = P.catalogCardDataV12(p), list = parts(p);
    var photo = p.mediaStatus === 'missing' || p.mediaStatus === 'stale' ? '' : safeImage(P.catalogImage(p));
    return '<div class="container cf-page">' + crumb + '<div class="cf-layout"><div class="cf-main"><section class="cf-product-header">' + media(photo, 'computer-tower', p.name + ' 상품 사진', 'cf-product-media') + '<div class="cf-product-intro"><div class="cf-meta"><span>상품번호 ' + h(p.id) + '</span><span class="cf-sale">' + h(data.saleLabel) + '</span></div><h1>' + h(data.shortName) + '</h1><details class="cf-official-name"><summary>전체 상품명 보기 ' + P.icon('caret-down') + '</summary><p>' + h(p.officialName || p.name) + '</p></details></div></section><section class="cf-components" aria-labelledby="cf-components-title"><div class="cf-section-heading"><div><span class="cf-eyebrow">PC CONFIGURATION</span><h2 id="cf-components-title">한눈에 보는 부품 구성</h2></div><span class="cf-parts-count">' + list.length + '개 부품</span></div>' + sourceNotice(p) + '<div class="cf-part-list">' + (list.length ? list.map(function (s, i) { return partRow(p, s, i); }).join('') : '<div class="cf-empty-parts">' + P.icon('package') + '<h3>부품 구성을 확인하고 있어요.</h3><p>정확한 구성은 상품 문의를 통해 확인해 주세요.</p></div>') + '</div></section><a class="cf-back" href="' + h(catalog) + '">' + P.icon('arrow-left') + '다른 PC 살펴보기</a></div>' + purchase(p, q) + '</div></div>';
  }
  function mount(root, p, initialQuantity) {
    var q = quantity(initialQuantity);
    function change(next) {
      q = Math.max(1, Math.min(10, next));
      root.querySelector('[data-cf-total]').textContent = amount(p, q);
      root.querySelector('#cf-quantity').innerHTML = q + '<span>대</span>';
      root.querySelector('[data-cf-minus]').disabled = q === 1;
      root.querySelector('[data-cf-plus]').disabled = q === 10;
      root.querySelectorAll('[data-cf-action]').forEach(function (a) { a.href = route(a.dataset.cfAction, p, q); });
      var url = new URL(window.location.href); url.searchParams.set('quantity', q);
      window.history.replaceState(null, '', url.href);
    }
    var minus = root.querySelector('[data-cf-minus]'), plus = root.querySelector('[data-cf-plus]');
    if (minus) minus.addEventListener('click', function () { change(q - 1); });
    if (plus) plus.addEventListener('click', function () { change(q + 1); });
    root.addEventListener('error', function (event) {
      var img = event.target;
      if (!img || !img.matches || !img.matches('img[data-cf-image]')) return;
      img.parentElement.innerHTML = '<span class="cf-icon-image">' + P.icon(img.dataset.cfFallback || 'package') + '</span>';
    }, true);
  }
  // 2026-10-20 승인 「누른 항목만 제자리에서」 -- 부품 행은 한 번에 하나만 열린다. 열고 닫기는 native details 그대로
  // (클릭·Enter·Space 한 번에 한 번 토글)이고, 여기서는 다른 열린 행만 닫는다. 위쪽 행이 닫혀 문서가 줄어도
  // 누른 행이 화면에서 같은 자리에 머물도록 그 차이만큼만 스크롤을 보정한다(이동·재렌더·history 변경 없음).
  if (!P.cfPartSingleOpen) {
    P.cfPartSingleOpen = true;
    document.addEventListener('toggle', function (event) {
      var part = event.target;
      if (!part || !part.matches || !part.matches('details.cf-part') || !part.open) return;
      var list = part.closest('.cf-part-list');
      if (!list) return;
      var summary = part.querySelector('summary'), before = summary.getBoundingClientRect().top;
      Array.prototype.forEach.call(list.querySelectorAll('details.cf-part[open]'), function (other) {
        if (other !== part) other.open = false;
      });
      var shift = summary.getBoundingClientRect().top - before;
      if (Math.abs(shift) > 1) window.scrollBy({ top: shift, behavior: 'instant' });
    }, true);
  }
  P.configurationConceptV12 = { render: render, mount: mount, quantity: quantity, parts: parts, facts: facts, pending: pending };
  if (!document.body || !document.body.hasAttribute('data-configuration-concept')) return;
  var query = new URLSearchParams(window.location.search), selected = P.getCatalogProduct(query.get('id') || '90623');
  var state = query.get('state') || 'normal', q = quantity(query.get('quantity'));
  var app = document.getElementById('app');
  app.innerHTML = P.shell(render(selected, q, state));
  document.title = (selected ? P.cardTitleV12(selected) + ' · PC 구성' : 'PC 구성 살펴보기') + ' | 팝콘AI';
  P.bindShell();
  if (selected && ['loading', 'error', 'not-found'].indexOf(state) < 0) mount(app, state === 'price-unavailable' ? Object.assign({}, selected, { price: null }) : selected, q);
}());
