(function () {
  'use strict';

  var P = window.PAI;
  var h = P.h;
  var states = ['normal', 'loading', 'missing', 'error'];
  P.designScreens = P.designScreens || {};

  function param(ctx, key) {
    var query = ctx && ctx.query;
    if (!query) return null;
    return typeof query.get === 'function' ? query.get(key) : query[key];
  }

  function hasDetail(spec) {
    return spec && (isSourceModel(spec) || (typeof spec.detail === 'string' && spec.detail.trim().length > 0) ||
      (typeof spec.role === 'string' && spec.role.trim().length > 0) ||
      (Array.isArray(spec.facts) && spec.facts.some(function (fact) { return fact && fact.label && fact.value; })));
  }

  function isSourceModel(spec) {
    return Boolean(spec && spec.basis === 'registered-spec-source-text' && Number.isInteger(spec.sourceOrdinal) &&
      spec.sourceOrdinal >= 0 && typeof spec.modelText === 'string' && spec.modelText.trim());
  }

  function partsFor(product) {
    if (!product || !Array.isArray(product.specs)) return [];
    if (product.bomStatus === 'missing') return [];
    if (product.source && product.source.kind === 'current-admin-observation' && !product.configurationId &&
      product.source.bomBasis !== 'registered-admin-spec-source-text') return [];
    return product.specs.filter(function (spec) { return spec && (isSourceModel(spec) || spec.partId !== undefined && spec.partId !== null); });
  }

  function partIcon(label) {
    var key = String(label || '').toUpperCase();
    if (/CPU|프로세서/.test(key)) return 'cpu';
    if (/GPU|VGA|그래픽/.test(key)) return 'graphics-card';
    if (/RAM|메모리/.test(key)) return 'memory';
    if (/SSD|HDD|저장/.test(key)) return 'hard-drive';
    if (/CASE|케이스/.test(key)) return 'computer-tower';
    if (/PSU|파워/.test(key)) return 'plug';
    return 'package';
  }

  function action(label, screen, state, params, style, icon) {
    return '<a class="btn ' + (style || 'btn-outline') + '" href="' + h(P.designHref(screen, state, params)) + '">' +
      (icon ? P.icon(icon) : '') + '<span>' + h(label) + '</span></a>';
  }

  function owner(product) {
    if (!product) return '';
    var image = P.catalogImage(product);
    return '<aside class="dcp-owner" aria-labelledby="dcp-owner-title">' +
      '<p class="eyebrow">이 정보가 등록된 PC</p>' +
      '<div class="dcp-owner-product"><div class="dcp-owner-photo">' +
      (image ? '<img src="' + h(image) + '" alt="' + h(product.name) + '">' : P.icon('computer-tower') + '<span>상품 사진 준비 중</span>') +
      '</div><div><span class="dcp-code">상품번호 ' + h(product.id) + '</span><h2 id="dcp-owner-title">' + h(product.name) + '</h2>' +
      (product.summary ? '<p>' + h(product.summary) + '</p>' : '') + '</div></div>' +
      '<div class="dcp-owner-price"><span>PC 전체 구성 가격</span><strong>' + h(typeof product.price === 'number' && product.price > 0 ? P.catalogMoney(product) : '가격 확인 필요') + '</strong></div>' +
      '<div class="dcp-owner-actions">' +
      action('소속 PC로 돌아가기', 'product', 'normal', { id: product.id }, 'btn-primary', 'arrow-left') +
      action('이 PC로 대화', 'chat', 'product', { id: product.id }, 'btn-outline', 'chat-circle') +
      '</div></aside>';
  }

  function siblingParts(product, selected) {
    var parts = partsFor(product).filter(function (spec) {
      return spec && (isSourceModel(spec) || spec.partId !== undefined && spec.partId !== null && String(spec.partId) !== '');
    });
    if (parts.length < 2) return '';
    return '<nav class="dcp-other-parts" aria-label="이 PC의 다른 구성 부품"><h2>다른 구성 부품</h2><div>' +
      parts.map(function (spec) {
        var active = spec === selected;
        return '<a class="dcp-part-link' + (active ? ' is-current' : '') + '"' + (active ? ' aria-current="page"' : '') +
          ' href="' + h(P.designHref('component', 'normal', isSourceModel(spec) ? { id: product.id, sourceOrdinal: spec.sourceOrdinal } : { id: product.id, partId: spec.partId })) + '">' +
          P.icon(partIcon(spec.label)) + '<span>' + h(spec.label || '부품') + '</span></a>';
      }).join('') + '</div></nav>';
  }

  function detailBody(product, spec) {
    var sourceOnly = isSourceModel(spec);
    var publicEvidence = spec.publicModelEvidence || null;
    var rowConflicts = (product.bomMismatches || []).filter(function (c) { return c.slot === spec.slot; });
    var value = typeof spec.value === 'string' ? spec.value : '';
    var suffix = sourceOnly ? null : value.match(/\s*×\s*([0-9]+)\s*$/);
    var quantity = Number.isInteger(spec.quantity) && spec.quantity > 0 ? spec.quantity : suffix ? Number(suffix[1]) : null;
    var name = suffix ? value.slice(0, suffix.index) : value;
    var facts = (Array.isArray(spec.facts) ? spec.facts : []).filter(function (fact) { return fact && typeof fact.label === 'string' && typeof fact.value === 'string'; });
    var details = facts.length ? '<dl class="dcp-spec-facts">' + facts.map(function (fact) { return '<div><dt>' + h(fact.label) + '</dt><dd>' + h(fact.value || '정보 없음') + '</dd></div>'; }).join('') + '</dl>' : '<p class="dcp-detail-text">' + h(sourceOnly ? '이 모델의 별도 상세 설명과 부품 사진은 확인 중입니다. 필요한 정보는 이 PC로 대화에서 문의해 주세요.' : spec.detail || '상세 사양 확인 필요') + '</p>';
    return '<article class="dcp-detail" aria-labelledby="dcp-part-title">' +
      (sourceOnly || product.bomStatus === 'mismatch' ? '<div class="dcp-source-note" role="status">' + P.icon('info') + '<div><strong>' + (rowConflicts.length ? '이 부품의 모델 정보를 확인해야 해요' : '상품에 등록된 모델 정보입니다') + '</strong><p>현재 판매 구성과 같은지, 정확한 부품과 수량은 상담으로 확인해 주세요.</p></div></div>' : '') +
      '<div class="dcp-part-heading"><span class="dcp-part-symbol">' + P.icon(partIcon(spec.label)) + '</span><div>' +
      '<p class="dcp-part-category">' + h(spec.label || '구성 부품') + '</p><h2 id="dcp-part-title">' + h(name || '부품명 확인 필요') + '</h2></div></div>' +
      '<dl class="dcp-part-facts"><div><dt>' + (spec.partIdKind === 'explanation-code' ? '부품 정보 코드' : '부품 코드') + '</dt><dd>' + h(spec.partId !== undefined && spec.partId !== null && String(spec.partId) !== '' ? spec.partId : '확인 필요') + '</dd></div>' +
      '<div><dt>' + (sourceOnly ? '원문에 명시된 수량' : '구성 수량') + '</dt><dd>' + (quantity ? h(quantity) + '개' : '수량 확인 중') + '</dd></div></dl>' +
      '<section class="dcp-original-value" aria-labelledby="dcp-value-title"><h3 id="dcp-value-title">' + (sourceOnly ? '등록된 원문 모델 정보' : '이 PC의 구성 부품') + '</h3><p>' + h(sourceOnly ? spec.modelText : value || '구성 정보 확인 필요') + '</p>' + (sourceOnly ? '<p class="dcp-original-label">원문 항목: ' + h(spec.sourceLabel || spec.label) + '</p>' : '') + '</section>' +
      (rowConflicts.length ? '<section class="dcp-comparison-note" aria-label="모델 정보 확인 항목"><h3>확인이 필요한 정보</h3>' + rowConflicts.map(function (c) {
        if (c.kind === 'product-name-vs-registered') return '<p><strong>상품명 표기</strong> ' + h(c.productNameValue || '') + '<br><strong>등록 모델 표기</strong> ' + h(c.registeredModelIdentity || '') + '</p>';
        return '<p><strong>등록된 모델</strong> ' + h(c.registeredModel || spec.modelText) + '<br><strong>대조 자료의 표기</strong> ' + h(Array.isArray(c.publicModels) && c.publicModels.length ? c.publicModels.join(' · ') : '이 모델의 선택 여부 확인 중') + '</p>';
      }).join('') + '<p class="dcp-comparison-help">어느 정보가 현재 판매 구성인지 확인한 뒤 안내해 드릴 수 있어요.</p></section>' : '') +
      (publicEvidence && publicEvidence.publicPartProductCode ? '<dl class="dcp-reference-code"><div><dt>원상품 참고 부품 코드</dt><dd>' + h(publicEvidence.publicPartProductCode) + '</dd></div></dl><p class="dcp-code-help">원상품에서 확인한 참고 코드예요. 이 PC에서 변경할 수 있는 부품은 상담으로 확인해 주세요.</p>' : '') +
      '<section class="dcp-description" aria-labelledby="dcp-description-title"><div class="dcp-section-title">' + P.icon('clipboard-text') + '<h3 id="dcp-description-title">상세 명세</h3></div>' +
      details + '</section>' +
      (typeof spec.role === 'string' && spec.role.trim() ? '<section class="dcp-role"><h3>부품의 역할</h3><p class="dcp-detail-text">' + h(spec.role) + '</p></section>' : '') +
      '<div class="dcp-help">' + P.icon('chat-circle') + '<div><strong>이 부품이 내 용도에 맞는지 궁금하신가요?</strong><p>사용할 프로그램과 원하는 작업을 알려 주세요.</p>' +
      '<a href="' + h(P.designHref('chat', 'product', { id: product.id })) + '">이 PC로 대화' + P.icon('arrow-right') + '</a></div></div></article>';
  }

  function statusBody(state, product, selected, partId, sourceOrdinal) {
    var title, copy, icon;
    if (state === 'loading') {
      title = '부품 정보를 불러오고 있어요';
      copy = '선택한 PC의 구성 정보를 확인하고 있어요.';
      icon = 'clock';
    } else if (state === 'error') {
      title = '부품 정보를 불러오지 못했어요';
      copy = '잠시 후 다시 확인해 주세요. 선택한 PC는 그대로 유지돼요.';
      icon = 'warning-circle';
    } else {
      title = product ? '부품 상세를 확인해야 해요' : '소속 PC를 찾을 수 없어요';
      copy = !product ? 'PC 상품 목록에서 상품을 다시 선택해 주세요.' :
        selected ? '이 부품의 상세 명세가 아직 준비되지 않았어요. PC 구성이나 대화에서 필요한 내용을 확인해 주세요.' :
          partId !== null && partId !== undefined || sourceOrdinal !== null && sourceOrdinal !== undefined ? '이 PC에서 선택한 부품을 찾지 못했어요. PC 구성에서 부품을 다시 선택해 주세요.' :
            '이 PC의 부품별 상세 명세가 아직 준비되지 않았어요. 확인하고 싶은 내용을 대화로 알려 주세요.';
      icon = 'info';
    }
    var retryParams = product ? { id: product.id } : {};
    if (partId !== undefined && partId !== null) retryParams.partId = partId;
    if (sourceOrdinal !== undefined && sourceOrdinal !== null) retryParams.sourceOrdinal = sourceOrdinal;
    return '<section class="dcp-status dcp-status-' + state + '"' + (state === 'loading' ? ' aria-busy="true"' : '') + '>' +
      '<span class="dcp-status-symbol">' + P.icon(icon) + '</span><div role="' + (state === 'error' ? 'alert' : 'status') + '"><h2>' + h(title) + '</h2><p>' + h(copy) + '</p></div>' +
      (selected ? '<p class="dcp-status-part">' + h(selected.value || selected.label || '') + '</p>' : '') +
      (state === 'loading' ? '<div class="dcp-loading-lines" aria-hidden="true"><span></span><span></span><span></span></div>' : '') +
      '<div class="dcp-status-actions">' +
      ((state === 'error' || state === 'loading') && product ? action('다시 확인', 'component', 'normal', retryParams, 'btn-primary', 'arrow-counter-clockwise') : '') +
      (product ? action('PC 구성으로 돌아가기', 'product', 'normal', { id: product.id }, 'btn-outline', 'arrow-left') : action('PC 둘러보기', 'catalog', 'normal', {}, 'btn-primary', 'computer-tower')) +
      '</div></section>';
  }

  P.designScreens.component = function (ctx) {
    ctx = ctx || {};
    var state = states.indexOf(ctx.state) >= 0 ? ctx.state : 'normal';
    var productId = ctx.productId !== undefined && ctx.productId !== null ? ctx.productId : param(ctx, 'id');
    var product = productId !== undefined && productId !== null && String(productId) !== '' ? P.getCatalogProduct(productId) : null;
    var partId = param(ctx, 'partId');
    var suppliedPart = partId !== undefined && partId !== null;
    var sourceOrdinal = param(ctx, 'sourceOrdinal');
    var suppliedOrdinal = sourceOrdinal !== undefined && sourceOrdinal !== null;
    var validOrdinal = suppliedOrdinal && /^(0|[1-9][0-9]*)$/.test(String(sourceOrdinal)) && Number.isSafeInteger(Number(sourceOrdinal));
    var specs = partsFor(product);
    var selected = suppliedPart && suppliedOrdinal ? null : suppliedOrdinal ? validOrdinal ? specs.find(function (spec) {
      return isSourceModel(spec) && spec.sourceOrdinal === Number(sourceOrdinal);
    }) : null : suppliedPart ? specs.find(function (spec) {
      return spec && spec.partId !== undefined && spec.partId !== null && String(spec.partId) === String(partId);
    }) : specs.find(hasDetail);
    // A supplied but unknown ID never falls back to a different PC or component.
    if (!product || (state === 'normal' && !hasDetail(selected))) state = 'missing';
    var content = state === 'normal' ? detailBody(product, selected) : statusBody(state, product, selected, partId, sourceOrdinal);
    return { html: '<div class="container ds-page dcp-page"><nav class="ds-crumb dcp-crumb" aria-label="현재 위치">' +
      '<a href="' + h(P.designHref('catalog', 'normal')) + '">PC 상품</a>' + P.icon('caret-right') +
      (product ? '<a href="' + h(P.designHref('product', 'normal', { id: product.id })) + '">상품 상세</a>' + P.icon('caret-right') : '') +
      '<span>부품 상세</span></nav><div class="ds-heading dcp-heading"><p class="eyebrow">PC COMPONENT</p><h1>PC 속 부품을 자세히.</h1><p>선택한 PC에 포함된 부품 정보를 확인하세요.</p></div>' +
      '<div class="dcp-layout' + (!product ? ' dcp-layout-single' : '') + '"><div class="dcp-main">' + content +
      (product && state === 'normal' ? siblingParts(product, selected) : '') + '</div>' + owner(product) + '</div></div>' };
  };
}());
