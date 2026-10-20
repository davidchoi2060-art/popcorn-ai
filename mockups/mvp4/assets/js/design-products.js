(function () {
  'use strict';
  var P = window.PAI = window.PAI || {};
  P.designScreens = P.designScreens || {};
  var catalogStates = ['normal', 'loading', 'empty', 'no-results', 'error', 'partial'];
  var productStates = ['normal', 'loading', 'not-found', 'out-of-stock', 'discontinued', 'missing-image', 'missing-specs', 'price-unavailable', 'price-changed', 'detail-unavailable'];
  function h(value) { return String(value === undefined || value === null ? '' : value).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function icon(name) { return typeof P.designIcon === 'function' ? P.designIcon(name) : (typeof P.icon === 'function' ? P.icon(name) : ''); }
  function href(screen, state, params) { return P.designHref(screen, state || 'normal', params || {}); }
  function query(ctx, key) {
    var q = ctx && ctx.query;
    if (q && typeof q.get === 'function') return q.get(key) || '';
    if (typeof q === 'string') return new URLSearchParams(q).get(key) || '';
    return q && q[key] !== undefined && q[key] !== null ? String(q[key]) : '';
  }
  function products() {
    var seen = Object.create(null);
    return (Array.isArray(P.catalogProducts) ? P.catalogProducts : []).filter(function (p) {
      if (!p || p.id === undefined || p.id === null || String(p.id) === '' || seen[String(p.id)]) return false;
      seen[String(p.id)] = true; return true;
    });
  }
  function getProduct(id) {
    if (typeof P.getCatalogProduct === 'function') { var p = P.getCatalogProduct(id); if (p) return p; }
    return products().find(function (p) { return String(p.id) === String(id); }) || null;
  }
  function specs(p) { return (Array.isArray(p.specs) ? p.specs : []).filter(function (s) { return s && s.label && s.value !== undefined && s.value !== null && String(s.value).trim() !== ''; }); }
  function specValue(spec) {
    var value = String(spec.value === undefined || spec.value === null ? '' : spec.value);
    if (spec.basis === 'registered-spec-source-text') return value;
    return typeof spec.quantity === 'number' && Number.isInteger(spec.quantity) && spec.quantity > 0 && !/[×x]\s*[0-9]+\s*$/i.test(value) ? value + ' × ' + spec.quantity : value;
  }
  function summarySpecs(p) { return (Array.isArray(p.summarySpecs) ? p.summarySpecs : []).filter(function (s) { return s && s.label && s.value !== undefined && s.value !== null && String(s.value).trim() !== ''; }); }
  function validPrice(p) { return typeof p.price === 'number' && Number.isFinite(p.price) && p.price > 0; }
  function money(p) { if (!validPrice(p)) return '가격 확인 필요'; return typeof P.catalogMoney === 'function' ? P.catalogMoney(p) : new Intl.NumberFormat('ko-KR').format(p.price) + '원'; }
  function photo(p) { return p.mediaStatus === 'missing' || p.mediaStatus === 'stale' ? null : typeof P.catalogImage === 'function' ? P.catalogImage(p) || null : null; }
  function categoryLabel(value) { return ({ gaming: '게임', office: '사무·업무', creative: '영상·디자인', mini: '미니 PC', high: '고성능 작업' })[value] || value; }
  function saleState(p) {
    var status = String(p.saleStatus || p.status || '').trim().toLowerCase().replace(/[\s_-]+/g, '');
    if (['단종', '판매종료', 'discontinued', 'ended'].indexOf(status) >= 0) return 'discontinued';
    if (['품절', 'outofstock', 'soldout'].indexOf(status) >= 0) return 'out-of-stock';
    if (typeof p.stockQty === 'number' && Number.isFinite(p.stockQty) && p.stockQty === 0) return 'out-of-stock';
    if (['판매중', 'onsale', 'selling', 'active', 'available'].indexOf(status) >= 0) return 'selling';
    return 'unknown';
  }
  function stateOf(p, state) {
    if (state === 'out-of-stock' || state === 'discontinued') return state;
    var sale = saleState(p);
    return sale === 'out-of-stock' || sale === 'discontinued' ? sale : state;
  }
  function saleLabel(p, state) {
    var sale = state === 'out-of-stock' || state === 'discontinued' ? state : saleState(p);
    return { selling: '판매 중', 'out-of-stock': '품절', discontinued: '판매 종료', unknown: '판매 상태 확인 필요' }[sale];
  }
  function isSelling(p) { return typeof p.isSelling === 'boolean' ? p.isSelling : saleState(p) === 'selling'; }
  function defaultPriority(p) {
    if (!isSelling(p)) return 0;
    var hasPhoto = Boolean(photo(p));
    var hasConfiguration = Boolean(p.configurationId && specs(p).length && p.bomStatus !== 'missing' && p.bomStatus !== 'mismatch');
    return hasPhoto && hasConfiguration ? 3 : hasPhoto ? 2 : hasConfiguration ? 1 : 0;
  }
  function needsReview(p) { return p.reviewRequired === true || p.bomStatus === 'mismatch' || p.configurationCompleteness === 'registered-core-unselected'; }
  function sourceModels(p) { return p.bomStatus === 'registered-source' || Boolean(p.source && p.source.bomBasis === 'registered-admin-spec-source-text'); }
  function badges(p, state) {
    return '<span class="dp-status' + (saleState(p) === 'selling' && state !== 'out-of-stock' && state !== 'discontinued' ? ' dp-status-selling' : '') + '">' + h(saleLabel(p, state)) + '</span>' + (needsReview(p) ? '<span class="dp-status dp-status-review">' + (p.configurationCompleteness === 'registered-core-unselected' ? '완성 구성 확인 필요' : '상세 확인 필요') + '</span>' : '');
  }
  function placeholder(text) { return '<span class="dp-photo-placeholder">' + icon('computer-tower') + '<span>' + h(text || '상품 사진 준비 중') + '</span></span>'; }
  function image(p, extraClass) { var src = photo(p); return src ? '<img class="' + h(extraClass || '') + '" data-dp-photo src="' + h(src) + '" alt="' + h(p.name || p.id) + ' 상품 사진" loading="lazy">' : placeholder(p.mediaStatus === 'stale' ? '상품 사진 확인 중' : '상품 사진 준비 중'); }
  function notice(title, text, tone) { return '<div class="dp-notice ' + (tone === 'warning' ? 'dp-notice-warning' : '') + '" role="status">' + icon(tone === 'warning' ? 'warning-circle' : 'info') + '<div><strong>' + h(title) + '</strong><p>' + h(text) + '</p></div></div>'; }
  function empty(title, text, button) { return '<section class="dp-empty">' + icon('computer-tower') + '<h2>' + h(title) + '</h2><p>' + h(text) + '</p>' + (button || '') + '</section>'; }
  function skeleton(detail) {
    // 목록 진입은 카테고리 로딩 1안(PC 그림·문구) + 실제 상품 칸과 같은 스켈레톤. 상세는 그대로(2026-10-20 대표).
    if (!detail && P.categoryLoading) return '<div class="dp-loading">' + P.categoryLoading('pc', { cards: 0 }) + '<div class="dp-grid" aria-hidden="true">' + Array.from({ length: 6 }, function () { return '<div class="dp-skeleton-card"><span class="dp-skeleton dp-skeleton-photo"></span><span class="dp-skeleton dp-skeleton-line"></span><span class="dp-skeleton dp-skeleton-line dp-short"></span></div>'; }).join('') + '</div></div>';
    return '<div class="dp-loading" role="status"><p>상품 정보를 불러오고 있어요.</p><div class="' + (detail ? 'dp-detail-skeleton' : 'dp-grid') + '" aria-hidden="true">' + Array.from({ length: detail ? 2 : 6 }, function () { return '<div class="dp-skeleton-card"><span class="dp-skeleton dp-skeleton-photo"></span><span class="dp-skeleton dp-skeleton-line"></span><span class="dp-skeleton dp-skeleton-line dp-short"></span></div>'; }).join('') + '</div></div>';
  }
  function bindImageFallback(scope) {
    scope.addEventListener('error', function (event) {
      var img = event.target;
      if (!img || !img.matches || !img.matches('img[data-dp-photo]')) return;
      var holder = img.parentElement;
      if (!holder) return;
      holder.innerHTML = placeholder();
      if (holder.tagName === 'BUTTON') { holder.disabled = true; holder.removeAttribute('data-dp-zoom'); holder.setAttribute('aria-label', '상품 사진 준비 중'); }
    }, true);
    scope.querySelectorAll('img[data-dp-photo]').forEach(function (img) { if (img.complete && img.naturalWidth === 0) img.dispatchEvent(new Event('error')); });
  }
  function compactSpecs(p) {
    var actual = p.bomStatus === 'mismatch' ? [] : specs(p), summary = summarySpecs(p), all = actual.length ? actual : summary;
    var wanted = [
      ['CPU', ['CPU'], /^(?:CPU|프로세서(?:\s*\(CPU\))?|중앙처리(?:장치)?)$/i],
      ['GPU', ['GPU'], /^(?:GPU|VGA|그래픽(?:카드)?|비디오(?:카드)?)$/i],
      ['RAM', ['RAM'], /^(?:RAM|메모리|MEMORY)$/i],
      ['SSD', ['SSD', 'HDD'], /^(?:SSD|HDD|저장장치|스토리지|하드디스크|STORAGE)$/i]
    ];
    var rows = wanted.map(function (pair) {
      var found = all.filter(function (s) {
        var slot = String(s.slot || '').trim().toUpperCase();
        return slot ? pair[1].indexOf(slot) >= 0 : pair[2].test(String(s.label || '').trim());
      });
      return found.length ? '<div><dt>' + pair[0] + '</dt><dd>' + h(found.map(specValue).join(' · ')) + '</dd></div>' : '';
    }).filter(Boolean);
    return (rows.length ? '<p class="dp-spec-origin">' + (actual.length ? sourceModels(p) ? '등록된 모델 정보 · 최종 구성 확인 필요' : '등록된 구성 정보' : '상품명 기준 요약') + '</p><dl class="dp-card-specs">' + rows.join('') + '</dl>' : p.summary ? '<p class="dp-card-summary">' + h(p.summary) + '</p>' : '<p class="dp-inline-note">상세 구성을 확인하고 있어요.</p>');
  }
  // Catalog-only presentation. Keep full names and BOM text in the detail renderers.
  function catalogCardName(p) {
    var full = String(p.name || ''), series = full.match(/^([^\[\]]{1,24}?)\s+NO\.?\s*(\d{1,3})[.\s]+(\d{4,8}[A-Z]*)\b/i);
    return series ? series[1].trim() + ' NO.' + series[2] + ' · ' + series[3] : String(p.category || '조립 PC') + ' · ' + String(p.id);
  }
  function cardSlot(p, slot) {
    return specs(p).filter(function (s) { return String(s.slot || '').trim().toUpperCase() === slot; });
  }
  function cardCpuModel(text) {
    var raw = String(text || ''), head = raw.split(/\[\s*Turbo\b/i)[0];
    if (!/(?:AMD|Intel|인텔|코어|Core|라이젠|Ryzen|스레드리퍼|Threadripper|EPYC|Xeon|제온|\bi[3579]\b)/i.test(head)) return null;
    var matches = head.match(/\b\d{3,5}(?:X3D|WX|GT|GE|KF|KS|HX|HS|F|K|X|G|T|U|H|P)?(?:\s+Plus)?(?![A-Za-z0-9])/gi) || [];
    var models = Array.from(new Set(matches.map(function (value) { return value.trim().replace(/\s+/g, ' '); })));
    return models.length === 1 ? [models[0]] : null;
  }
  function cardGpuModel(text) {
    var raw = String(text || ''), match;
    // Never use the precomputed GPU facts: some source facts contain truncated models.
    match = raw.match(/\bRTX\s+PRO\s+(\d{3,4})\s+(Blackwell)(?:\s+(MAX-Q))?(?![A-Za-z0-9])/i);
    if (match) return ['RTX PRO', match[1], match[2] + (match[3] ? ' ' + match[3] : '')];
    match = raw.match(/\b(RTX|GTX)\s*(\d{3,4})((?:\s*(?:Ti|SUPER)){0,2})(?![A-Za-z0-9])/i);
    if (match) return [match[1].toUpperCase(), match[2] + match[3].replace(/Ti/ig, ' Ti').replace(/SUPER/ig, ' SUPER').replace(/\s+/g, ' ').trimEnd()];
    match = raw.match(/\b(RX)\s*(\d{3,4})(?:\s*(XTX|XT|GRE))?(?![A-Za-z0-9])/i);
    if (match) return ['RX', match[2] + (match[3] ? ' ' + match[3].toUpperCase() : '')];
    match = raw.match(/\bRTX\s*(A\d{3,4})(?![A-Za-z0-9])/i);
    if (match) return ['RTX', match[1].toUpperCase()];
    match = raw.match(/\bArc\s+([AB]\d{3})(?![A-Za-z0-9])/i);
    if (match) return ['Arc', match[1].toUpperCase()];
    match = raw.match(/\bUHD(?:\s+Graphics)?\s*(\d{3})(?![A-Za-z0-9])/i);
    if (match) return ['UHD', match[1]];
    if (/\bUHD\s+Graphics\b/i.test(raw)) return ['UHD', 'Graphics'];
    if (/\bRadeon\s+Graphics\b/i.test(raw)) return ['Radeon', 'Graphics'];
    return null;
  }
  function cardCapacity(s, isRam) {
    // quantity describes the registered item count. Do not infer it from a name or multiply kits into a total.
    if (!Number.isInteger(s.quantity) || s.quantity <= 0) return null;
    var raw = String(s.value || ''), quantities = raw.match(/\b\d+(?:\.\d+)?\s*(?:TB|GB|G)(?![A-Za-z0-9])/ig) || [];
    if (!quantities.length) return null;
    var first = quantities[0].replace(/\s+/g, '').toUpperCase().replace(/G$/, 'GB');
    // A later smaller capacity is accepted only in an explicit kit expression (16GB [8G x 2]).
    var trailing = raw.slice(raw.indexOf(quantities[0]) + quantities[0].length);
    var other = quantities.slice(1);
    if (other.length && !/^\s*[)\]]?\s*(?:PC\d[-\d]*\s*)?\[\s*\d+(?:\.\d+)?\s*(?:G|GB|TB)\s*[x×]\s*\d+\s*\]/i.test(trailing)) return null;
    if (/[x×]\s*\d+/i.test(trailing)) {
      var suffix = trailing.match(/[x×]\s*(\d+)\s*$/i);
      if (suffix && Number(suffix[1]) !== s.quantity) return null;
    }
    var capacity = first + (s.quantity > 1 ? ' × ' + s.quantity : '');
    if (!isRam) return [capacity];
    var ddr = raw.match(/\b(?:LP)?DDR[3-6]X?(?![A-Za-z0-9])/i);
    return ddr ? [ddr[0].toUpperCase(), capacity] : null;
  }
  function cardQuickCell(p, slot) {
    if (p.bomStatus === 'mismatch') return { lines: ['구성 확인'], pending: true };
    var rows = cardSlot(p, slot), lines = null;
    if (rows.length === 1) {
      if (slot === 'CPU') lines = cardCpuModel(rows[0].value);
      else if (slot === 'GPU') lines = cardGpuModel(rows[0].value);
      else lines = cardCapacity(rows[0], slot === 'RAM');
    }
    return { lines: lines || ['상세 확인'], pending: !lines };
  }
  function catalogQuickSpecData(p) {
    return [['CPU', 'CPU'], ['그래픽', 'GPU'], ['메모리', 'RAM'], ['SSD', 'SSD']].map(function (pair) {
      var cell = cardQuickCell(p, pair[1]);
      return { label: pair[0], slot: pair[1], lines: cell.lines.slice(), pending: cell.pending };
    });
  }
  function catalogQuickSpecs(p) {
    return '<dl class="dp-quick-specs" aria-label="핵심 구성 요약">' + catalogQuickSpecData(p).map(function (cell) {
      return '<div' + (cell.pending ? ' class="is-pending"' : '') + '><dt>' + cell.label + '</dt><dd>' + cell.lines.map(function (line) { return '<span>' + h(line) + '</span>'; }).join('') + '</dd></div>';
    }).join('') + '</dl>' + (sourceModels(p) && p.bomStatus !== 'mismatch' ? '<p class="dp-card-source-note">등록 모델 요약 · 최종 구성 확인 필요</p>' : '');
  }
  function productCard(p, selected) {
    selected = Array.isArray(selected) ? selected : [];
    var id = String(p.id), status = stateOf(p, 'normal');
    return '<article class="dp-card dp-card-v12" data-dp-card="' + h(id) + '"><a class="dp-card-photo" href="' + h(href('product', 'normal', { id: id })) + '" aria-label="' + h(p.name || id) + ' 상품 자세히 보기">' + image(p) + '</a><div class="dp-card-content"><div class="dp-card-meta">' + (p.category ? '<span class="dp-category">' + h(categoryLabel(String(p.category))) + '</span>' : '<span></span>') + '<label class="dp-compare-check"><input type="checkbox" data-dp-compare value="' + h(id) + '"' + (selected.indexOf(id) >= 0 ? ' checked' : '') + '><span>비교<span class="visually-hidden"> ' + h(p.name || id) + '</span></span></label></div><h2><a href="' + h(href('product', 'normal', { id: id })) + '" title="' + h(p.name || id) + '" aria-label="' + h(p.name || id) + '">' + h(catalogCardName(p)) + '</a></h2>' + catalogQuickSpecs(p) + '<div class="dp-card-price"><strong>' + h(money(p)) + '</strong><div class="dp-status-row">' + badges(p, status) + '</div></div><a class="btn btn-outline dp-card-link" href="' + h(href('product', 'normal', { id: id })) + '">' + (needsReview(p) ? '상품 상세 확인하기' : '상품 자세히 보기') + icon('arrow-right') + '</a></div></article>';
  }
  // /mvp4: 승인 카드(B)는 P.catalogCardRenderer · P.catalogGridClass 로 실제 목록에 끼운다(live-cards.js). 없으면 기존 카드.
  // Local concept previews reuse this presentation contract without changing catalog data.
  P.cardTitleV12 = catalogCardName;
  P.cardQuickSpecsV12 = catalogQuickSpecs;
  P.cardQuickSpecDataV12 = catalogQuickSpecData;
  P.catalogCardV12 = productCard;
  P.catalogCardDataV12 = function (p) {
    var id = String(p.id), state = stateOf(p, 'normal');
    return { id: id, fullName: String(p.name || id), shortName: catalogCardName(p), category: categoryLabel(String(p.category || '조립 PC')),
      priceLabel: money(p), photoUrl: photo(p), detailHref: href('product', 'normal', { id: id }), chatHref: href('chat', 'product', { id: id }),
      saleLabel: saleLabel(p, state), needsReview: needsReview(p), specs: catalogQuickSpecData(p),
      sourceNote: sourceModels(p) && p.bomStatus !== 'mismatch' ? '등록 모델 요약 · 최종 구성 확인 필요' : '' };
  };
  P.designScreens.catalog = function (ctx) {
    ctx = ctx || {};
    var state = catalogStates.indexOf(ctx.state) >= 0 ? ctx.state : 'normal';
    var all = products(), term = query(ctx, 'q'), category = query(ctx, 'category') || query(ctx, 'purpose'), sort = query(ctx, 'sort') || 'default';
    var saleFilter = query(ctx, 'sale') === 'all' ? 'all' : 'selling', pageSize = 12, visibleCount = pageSize;
    var categories = Array.from(new Set(all.map(function (p) { return p.category ? String(p.category) : ''; }).filter(Boolean)));
    if (categories.indexOf(category) < 0) category = '';
    var selected = Array.from(new Set(query(ctx, 'ids').split(',').filter(function (id) { return all.some(function (p) { return String(p.id) === id; }); }))).slice(0, 3);
    if (['default', 'price-asc', 'price-desc', 'name'].indexOf(sort) < 0) sort = 'default';
    function filtered() {
      var needle = term.trim().toLocaleLowerCase('ko-KR');
      return all.filter(function (p) {
        var searchableSpecs = (p.bomStatus === 'mismatch' ? [] : specs(p)).concat(summarySpecs(p));
        var searchable = [p.name, p.id, p.summary, p.category].concat(searchableSpecs.map(function (s) { return s.label + ' ' + s.value; })).join(' ').toLocaleLowerCase('ko-KR');
        return (saleFilter === 'all' || isSelling(p)) && (!category || String(p.category) === category) && (!needle || searchable.indexOf(needle) >= 0);
      }).sort(function (a, b) {
        if (sort === 'name') return String(a.name || a.id).localeCompare(String(b.name || b.id), 'ko-KR');
        if (sort === 'price-asc' || sort === 'price-desc') {
          if (!validPrice(a) && !validPrice(b)) return 0;
          if (!validPrice(a)) return 1;
          if (!validPrice(b)) return -1;
          return sort === 'price-asc' ? a.price - b.price : b.price - a.price;
        }
        return defaultPriority(b) - defaultPriority(a);
      });
    }
    function body() {
      if (state === 'loading') return skeleton(false);
      if (state === 'error') return empty('상품을 불러오지 못했어요', '잠시 후 다시 확인해 주세요.', '<button class="btn btn-primary" type="button" data-dp-retry>다시 보기</button>');
      if (state === 'empty' || !all.length) return empty('상품을 확인하고 있어요', '상품 정보가 준비되면 이곳에서 확인할 수 있어요.', '<a class="btn btn-soft" href="' + h(href('chat', 'welcome')) + '">AI와 필요한 PC 상담하기' + icon('arrow-right') + '</a>');
      var shown = state === 'no-results' ? [] : filtered();
      var visible = shown.slice(0, visibleCount), remaining = shown.length - visible.length;
      return (state === 'partial' ? notice('일부 상품 정보를 불러오지 못했어요', '확인된 상품부터 살펴보세요. 목록을 다시 확인할 수도 있어요.') + '<button class="dp-text-button" data-dp-retry type="button">목록 다시 보기</button>' : '') + '<div class="dp-results-heading"><h2>상품 목록 <span>' + shown.length + '개</span></h2><p>' + (saleFilter === 'selling' ? '판매 중인 상품' : '품절 상품 포함') + '</p></div>' + (shown.length ? '<div class="' + (P.catalogGridClass || 'dp-grid') + '" id="dp-product-grid">' + visible.map(function (p) { return (P.catalogCardRenderer || productCard)(p, selected); }).join('') + '</div><div class="dp-pagination"><p>' + shown.length + '개 중 <strong>' + visible.length + '개</strong>를 보고 있어요.</p>' + (remaining > 0 ? '<button class="btn btn-outline" type="button" data-dp-more aria-controls="dp-product-grid">상품 ' + Math.min(pageSize, remaining) + '개 더 보기' + icon('caret-down') + '</button>' : '<span class="dp-all-loaded">마지막 상품까지 확인했어요.</span>') + '</div>' : empty('조건에 맞는 상품이 없어요', '검색어를 바꾸거나 판매 상태를 포함한 조건을 조정해 보세요.', '<button class="btn btn-primary" type="button" data-dp-reset>조건 초기화</button>'));
    }
    function compareBar() {
      selected = selected.filter(function (id) { return all.some(function (p) { return String(p.id) === id; }); });
      if (!selected.length) return '';
      return '<div class="dp-compare-bar"><div class="dp-compare-intro"><strong>상품 비교 <span>' + selected.length + '/3</span></strong><p>최대 3개까지 함께 살펴보세요.</p></div><ul class="dp-compare-items">' + selected.map(function (id) { var p = all.find(function (item) { return String(item.id) === id; }); return '<li><span>' + h(p.name || id) + '</span><button type="button" data-dp-remove="' + h(id) + '" aria-label="' + h(p.name || id) + ' 비교에서 제거">' + icon('x') + '</button></li>'; }).join('') + '</ul>' + (selected.length >= 2 ? '<a class="btn btn-primary" href="' + h(href('compare', 'normal', { ids: selected.join(',') })) + '">' + selected.length + '개 상품 비교하기' + icon('arrow-right') + '</a>' : '<button class="btn btn-primary" type="button" disabled>상품을 1개 더 선택해 주세요</button>') + '</div>';
    }
    return {
      html: '<section class="dp-page dp-catalog" data-dp-catalog><header class="dp-catalog-heading"><div><p class="eyebrow">PC SHOP</p><h1>내게 맞는 PC를<br>찾아보세요.</h1><p>상품명과 부품을 살펴보고, 필요한 구성을 골라보세요.</p></div><a class="dp-ai-entry" href="' + h(href('chat', 'welcome')) + '">' + icon('chat-text-duotone') + '<span><strong>어떤 PC가 좋을지 고민되나요?</strong><span>AI와 함께 찾아보기</span></span>' + icon('arrow-right') + '</a></header><form class="dp-catalog-controls" data-dp-filter-form><label class="dp-search"><span class="visually-hidden">상품명 또는 부품 검색</span>' + icon('magnifying-glass') + '<input type="search" name="q" value="' + h(term) + '" placeholder="상품명, CPU, 그래픽카드로 검색" maxlength="200" autocomplete="off"><button class="btn btn-primary" type="submit">검색</button></label><div class="dp-filter-row"><label>판매 상태<select name="sale"><option value="selling"' + (saleFilter === 'selling' ? ' selected' : '') + '>판매 중만</option><option value="all"' + (saleFilter === 'all' ? ' selected' : '') + '>품절 포함 전체</option></select></label><label>용도·분류<select name="category"><option value="">전체</option>' + categories.map(function (c) { return '<option value="' + h(c) + '"' + (category === c ? ' selected' : '') + '>' + h(categoryLabel(c)) + '</option>'; }).join('') + '</select></label><label>정렬<select name="sort">' + [['default', '기본순'], ['price-asc', '낮은 가격순'], ['price-desc', '높은 가격순'], ['name', '상품명순']].map(function (s) { return '<option value="' + s[0] + '"' + (sort === s[0] ? ' selected' : '') + '>' + s[1] + '</option>'; }).join('') + '</select></label><button class="dp-reset-button" data-dp-reset type="button">조건 초기화</button></div></form><p class="dp-live-message" data-dp-message aria-live="polite"></p><div data-dp-results>' + body() + '</div><div data-dp-comparison>' + compareBar() + '</div></section>',
      mount: function () {
        var scope = document.querySelector('[data-dp-catalog]'); if (!scope) return;
        var form = scope.querySelector('[data-dp-filter-form]'), results = scope.querySelector('[data-dp-results]'), comparison = scope.querySelector('[data-dp-comparison]'), message = scope.querySelector('[data-dp-message]');
        function redraw() { results.innerHTML = body(); comparison.innerHTML = compareBar(); }
        function apply() { term = form.elements.q.value; category = form.elements.category.value; sort = form.elements.sort.value; saleFilter = form.elements.sale.value; visibleCount = pageSize; if (state !== 'partial') state = 'normal'; redraw(); message.textContent = '조건에 맞는 상품 ' + filtered().length + '개를 찾았어요.'; }
        function reset() { term = ''; category = ''; sort = 'default'; saleFilter = 'selling'; visibleCount = pageSize; state = 'normal'; form.elements.q.value = ''; form.elements.category.value = ''; form.elements.sort.value = 'default'; form.elements.sale.value = 'selling'; message.textContent = '검색 조건을 초기화하고 판매 중인 상품을 표시했습니다.'; redraw(); }
        form.addEventListener('submit', function (e) { e.preventDefault(); apply(); });
        form.elements.q.addEventListener('input', apply);
        form.elements.category.addEventListener('change', apply);
        form.elements.sort.addEventListener('change', apply);
        form.elements.sale.addEventListener('change', apply);
        scope.addEventListener('click', function (e) {
          var resetButton = e.target.closest('[data-dp-reset]'), retry = e.target.closest('[data-dp-retry]'), remove = e.target.closest('[data-dp-remove]'), more = e.target.closest('[data-dp-more]');
          if (resetButton) reset();
          if (retry) { all = products(); selected = selected.filter(function (id) { return all.some(function (p) { return String(p.id) === id; }); }); visibleCount = pageSize; state = 'normal'; redraw(); message.textContent = '확인 가능한 상품 목록을 표시했습니다.'; }
          if (remove) { selected = selected.filter(function (id) { return id !== remove.getAttribute('data-dp-remove'); }); redraw(); message.textContent = '비교 선택에서 제외했습니다.'; }
          if (more) { var before = Math.min(visibleCount, filtered().length); visibleCount += pageSize; redraw(); var cards = results.querySelectorAll('[data-dp-card], [data-card-product]'); var firstNew = cards[before] && cards[before].querySelector('a'); if (firstNew) firstNew.focus(); message.textContent = '상품 ' + Math.max(0, cards.length - before) + '개를 더 표시했어요. 총 ' + cards.length + '개를 보고 있어요.'; }
        });
        scope.addEventListener('change', function (e) {
          var check = e.target; if (!check.matches('[data-dp-compare]')) return;
          if (check.checked && selected.indexOf(check.value) < 0) {
            if (selected.length >= 3) { check.checked = false; message.textContent = '비교는 최대 3개까지 선택할 수 있어요.'; return; }
            selected.push(check.value);
          } else if (!check.checked) selected = selected.filter(function (id) { return id !== check.value; });
          comparison.innerHTML = compareBar(); message.textContent = '비교할 상품 ' + selected.length + '개를 선택했습니다.';
        });
        bindImageFallback(scope);
      }
    };
  };
  function groupedSpecs(p, omit) {
    var rows = omit ? [] : specs(p), summary = summarySpecs(p), sourceOnly = sourceModels(p);
    var summaryBlock = summary.length ? '<section class="dp-name-summary"><h3>상품명 기준 요약</h3><p>상품명에 표시된 정보예요. 자세한 부품 모델과 최종 구성은 별도로 확인해 주세요.</p><dl>' + summary.map(function (s) { return '<div><dt>' + h(s.label) + '</dt><dd>' + h(s.value) + '</dd></div>'; }).join('') + '</dl></section>' : '';
    if (!rows.length) return summaryBlock + notice(p.bomStatus === 'mismatch' ? '부품 구성 확인이 필요해요' : '상세 부품 정보를 확인하고 있어요', p.bomStatus === 'mismatch' ? '상품 정보와 등록된 구성이 일치하는지 확인이 필요해요. 상담으로 필요한 구성을 확인해 주세요.' : '확인되지 않은 부품은 상세 모델이나 수량을 안내하기 어려워요. 필요한 구성은 상담으로 확인해 주세요.', p.bomStatus === 'mismatch' ? 'warning' : '');
    var groups = [{ title: '프로세서·그래픽', rows: [] }, { title: '메모리·저장장치', rows: [] }, { title: '보드·전원·케이스', rows: [] }, { title: '운영체제·기타 구성', rows: [] }];
    rows.forEach(function (s) { var label = String(s.label); var group = /cpu|프로세서|gpu|vga|그래픽|비디오/i.test(label) ? 0 : /ram|메모리|memory|ssd|hdd|저장|storage/i.test(label) ? 1 : /메인보드|motherboard|mainboard|파워|전원|psu|케이스|case|cooler|쿨러/i.test(label) ? 2 : 3; groups[group].rows.push(s); });
    var conflicts = Array.isArray(p.bomMismatches) ? p.bomMismatches : [];
    var nameConflict = conflicts.some(function (c) { return c.kind === 'product-name-vs-registered'; });
    var publicConflict = conflicts.some(function (c) { return c.kind === 'registered-vs-public'; });
    var conflictTitle = nameConflict && publicConflict ? '상품명과 부품 정보를 확인해 주세요' : publicConflict ? '등록된 부품 정보를 확인해 주세요' : '상품명과 등록 모델을 확인해 주세요';
    var guidance = p.bomStatus === 'mismatch' ? (nameConflict ? summaryBlock : '') + notice(conflictTitle, '확인한 자료에 모델명이나 설명이 다른 것으로 보이는 항목이 있어요. 아래 등록 정보를 살펴보고 최종 판매 구성과 수량은 상담으로 확인해 주세요.', 'warning') : sourceOnly ? notice('등록된 모델 정보입니다', '현재 판매 구성과 같은지 확인이 필요해요. 수량이 기재되지 않은 항목은 확인 중으로 표시합니다.') : p.bomStatus === 'configuration-only' ? notice('등록된 부품 구성을 확인하세요', '판매 상품과 연결된 구성 정보예요. 구매 전 최종 부품 구성은 다시 확인해 주세요.') : '';
    if (p.configurationCompleteness === 'registered-core-unselected') {
      var unselected = (p.unselectedComponentSlots || []).filter(function (s) { return ['CPU','RAM','GPU','SSD'].indexOf(s.slot) >= 0; }).map(function (s) { return s.label || s.slot; });
      guidance += notice('완성 구성을 확인해야 하는 상품입니다', '등록 정보에서 ' + unselected.join('·') + ' 항목이 미선택으로 표시되어 있어요. 현재 상태를 완성된 PC 구성으로 안내하기 어려우니 필요한 부품을 먼저 확인해 주세요.', 'warning');
    }
    return guidance + '<div class="dp-spec-groups">' + groups.filter(function (g) { return g.rows.length; }).map(function (g, i) { return '<details class="dp-spec-group"' + (i === 0 ? ' open' : '') + '><summary><strong>' + g.title + '</strong><span>' + g.rows.length + '개 항목 ' + icon('caret-down') + '</span></summary><table><caption class="visually-hidden">' + g.title + ' 상품 구성</caption><tbody>' + g.rows.map(function (s) {
      var localSource = s.basis === 'registered-spec-source-text' && Number.isInteger(s.sourceOrdinal) && s.sourceOrdinal >= 0;
      var params = s.partId ? {id:p.id,partId:s.partId} : localSource ? {id:p.id,sourceOrdinal:s.sourceOrdinal} : null;
      var partReview = conflicts.some(function (c) { return c.slot === s.slot; });
      return '<tr><th scope="row">' + h(s.label) + '</th><td>' + h(specValue(s)) + (partReview ? '<span class="dp-part-review-note">모델 정보 확인 필요</span>' : '') + (localSource ? '<span class="dp-quantity-note">' + (Number.isInteger(s.quantity) && s.quantity > 0 ? '원문 명시 수량 ' + s.quantity + '개' : '수량 확인 중') + '</span>' : '') + (params ? '<br><a class="dp-part-detail-link" href="'+h(href('component','normal',params))+'">' + (localSource ? '등록된 모델 정보 보기 ' : '부품 상세 보기 ') +icon('caret-right')+'</a>' : '') + '</td></tr>';
    }).join('') + '</tbody></table></details>'; }).join('') + '</div>';
  }
  P.designScreens.product = function (ctx) {
    ctx = ctx || {};
    var state = productStates.indexOf(ctx.state) >= 0 ? ctx.state : 'normal';
    var id = ctx.productId !== undefined && ctx.productId !== null ? String(ctx.productId) : query(ctx, 'id');
    var all = products(), p = id ? getProduct(id) : all[0] || null;
    var back = '<a class="dp-back" href="' + h(href('catalog', 'normal')) + '">' + icon('arrow-left') + 'PC 목록으로</a>';
    if (state === 'loading') return { html: '<section class="dp-page dp-product">' + back + skeleton(true) + '</section>' };
    if (state === 'not-found' || (!p && id)) return { html: '<section class="dp-page dp-product">' + back + empty('상품을 찾을 수 없어요', '목록에서 다른 상품을 확인해 주세요.', '<a class="btn btn-primary" href="' + h(href('catalog', 'normal')) + '">PC 목록 보기</a>') + '</section>' };
    if (!p) return { html: '<section class="dp-page dp-product">' + back + empty('상품 정보를 확인하고 있어요', '확인 가능한 상품이 준비되면 자세한 구성을 살펴볼 수 있어요.', '<a class="btn btn-primary" href="' + h(href('catalog', 'normal')) + '">PC 목록 보기</a>') + '</section>' };
    if (state === 'detail-unavailable') return { html: '<section class="dp-page dp-product">' + back + empty('상품 상세 정보를 확인할 수 없어요', '다른 상품을 살펴보거나 필요한 구성을 AI와 상담해 보세요.', '<div class="button-row"><a class="btn btn-primary" href="' + h(href('catalog', 'normal')) + '">다른 상품 보기</a><a class="btn btn-outline" href="' + h(href('chat', 'product', { id: p.id })) + '">AI와 상담하기</a></div>') + '</section>' };
    var requestedState = state;
    id = String(p.id); state = stateOf(p, state);
    var unavailable = state === 'out-of-stock' || state === 'discontinued', noPrice = requestedState === 'price-unavailable' || !validPrice(p), changed = requestedState === 'price-changed', acknowledged = false;
    var review = needsReview(p), needsConfirmation = review || sourceModels(p) || p.purchasable === false || saleState(p) === 'unknown';
    var src = requestedState === 'missing-image' ? null : photo(p);
    function nextActions() {
      var quoteBlocked = unavailable || noPrice || (changed && !acknowledged);
      var quoteText = unavailable ? '현재 견적 진행 불가' : noPrice ? '가격 확인 필요' : changed && !acknowledged ? '변경된 가격을 확인해 주세요' : '이 구성으로 견적 확인';
      if (needsConfirmation && !unavailable) return '<a class="btn btn-primary" href="' + h(href('chat', 'product', { id: id })) + '">' + (review ? '상세 확인 상담하기' : '상품 확인 상담하기') + icon('chat-circle') + '</a><button class="btn btn-outline" type="button" disabled aria-describedby="dp-action-note">구성 확인 필요</button>';
      return (quoteBlocked ? '<button class="btn btn-primary" type="button" disabled aria-describedby="dp-action-note">' + quoteText + '</button>' : '<a class="btn btn-primary" href="' + h(href('quote', 'normal', { id: id })) + '">' + quoteText + icon('arrow-right') + '</a>') + (unavailable || noPrice || p.bomStatus === 'missing' ? '<button class="btn btn-outline" type="button" disabled aria-describedby="dp-action-note">구성 확인 필요</button>' : '<a class="btn btn-outline" href="' + h(href('options', 'normal', { id: id })) + '">구성 변경</a>');
    }
    var alert = state === 'out-of-stock' ? notice('현재 품절된 상품입니다', '다른 PC를 살펴보거나 필요한 구성을 AI와 상담해 보세요.', 'warning') : state === 'discontinued' ? notice('판매가 종료된 상품입니다', '대신 사용할 PC를 목록에서 찾아보세요.', 'warning') : review ? notice('상품의 상세 확인이 필요해요', '부품 구성이나 판매 정보를 확인한 뒤 견적을 이어갈 수 있어요. 먼저 상담으로 필요한 내용을 알려 주세요.', 'warning') : needsConfirmation ? notice('판매 정보를 확인하고 있어요', '필요한 구성은 상담할 수 있어요. 견적 진행 전 상품 정보를 먼저 확인해 주세요.') : noPrice ? notice('가격을 확인하고 있어요', '가격 확인 전에는 견적 진행과 구성 변경을 이용할 수 없어요.') : changed ? notice('상품 가격이 변경되었습니다', '현재 표시된 가격을 확인한 후 견적을 진행해 주세요.', 'warning') : '';
    var actionNote = unavailable ? '이 상품은 현재 견적 진행과 구성을 변경할 수 없어요.' : needsConfirmation ? '상담에서 상품을 먼저 확인한 뒤 견적을 이어갈 수 있어요.' : noPrice ? 'AI와 먼저 필요한 구성을 상담할 수 있어요.' : changed ? '표시된 가격을 확인하면 견적 단계로 이동할 수 있어요.' : p.bomStatus === 'missing' ? '부품 변경은 상세 구성을 확인한 뒤 진행할 수 있어요.' : '견적 단계에서 선택한 상품과 구성을 확인하세요.';
    return {
      html: '<section class="dp-page dp-product" data-dp-product>' + back + alert + '<div class="dp-product-layout"><figure class="dp-product-gallery"><div class="dp-photo-surface">' + (src ? '<button class="dp-zoom-button" type="button" data-dp-zoom aria-label="' + h(p.name || id) + ' 상품 사진 확대"><img data-dp-photo src="' + h(src) + '" alt="' + h(p.name || id) + ' 상품 사진"></button><figcaption>사진을 선택하면 크게 볼 수 있어요.</figcaption>' : placeholder(p.mediaStatus === 'stale' ? '상품 사진 확인 중' : '상품 사진 준비 중')) + '</div>' + (src ? '<div class="dp-gallery-thumbs"><button type="button" class="dp-thumb" data-dp-zoom aria-label="상품 사진 확대">' + '<img src="' + h(src) + '" alt="" loading="lazy"></button><span>상품 사진 1장</span></div>' : '') + '</figure><div class="dp-product-info"><div class="dp-product-badges">' + (p.category ? '<span class="dp-category">' + h(categoryLabel(String(p.category))) + '</span>' : '') + badges(p, state) + '</div><p class="dp-product-code">상품 코드 <span>' + h(id) + '</span></p><h1>' + h(p.name || id) + '</h1>' + (p.summary ? '<p class="dp-product-summary">' + h(p.summary) + '</p>' : '') + '<div class="dp-product-price"><span>PC 전체 구성 가격</span><strong>' + h(noPrice ? '가격 확인 필요' : money(p)) + '</strong></div>' + (requestedState === 'missing-specs' ? '<p class="dp-inline-note">상품의 상세 부품 정보를 확인하고 있어요.</p>' : compactSpecs(p)) + (changed && !noPrice && !needsConfirmation && !unavailable ? '<label class="dp-price-confirm"><input type="checkbox" data-dp-price-confirm><span>현재 표시된 가격을 확인했습니다.</span></label>' : '') + '<div class="dp-product-actions" data-dp-next-actions>' + nextActions() + '</div><p id="dp-action-note" class="dp-action-note">' + actionNote + '</p><a class="dp-product-chat" href="' + h(href('chat', 'product', { id: id })) + '">' + icon('chat-text-duotone') + (unavailable ? '대안 PC를 AI와 상담하기' : 'AI와 이 상품 상담하기') + icon('arrow-right') + '</a>' + (unavailable || noPrice ? '<a class="dp-alternative-link" href="' + h(href('catalog', 'normal', p.category ? { category: p.category } : {})) + '">다른 상품 보기' + icon('arrow-right') + '</a>' : '') + '</div></div><section class="dp-product-specs" aria-labelledby="dp-spec-title"><div class="dp-section-heading"><div><p class="eyebrow">PC COMPONENTS</p><h2 id="dp-spec-title">제품 구성</h2><p>등록된 부품 정보와 구성 수량을 살펴보세요.</p></div><button class="dp-text-button" data-dp-expand-specs type="button">모두 펼치기</button></div>' + groupedSpecs(p, requestedState === 'missing-specs') + '</section>' + (src ? '<dialog class="dp-image-dialog" data-dp-image-dialog aria-labelledby="dp-image-title"><header><h2 id="dp-image-title">' + h(p.name || id) + '</h2><button class="icon-button" type="button" data-dp-close-image aria-label="상품 사진 닫기">' + icon('x') + '</button></header><img src="' + h(src) + '" alt="' + h(p.name || id) + ' 상품 사진 확대"></dialog>' : '') + '</section>',
      mount: function () {
        var scope = document.querySelector('[data-dp-product]'); if (!scope) return;
        var dialog = scope.querySelector('[data-dp-image-dialog]'), returnFocus = null;
        function close() { if (!dialog) return; if (typeof dialog.close === 'function') dialog.close(); else dialog.removeAttribute('open'); if (returnFocus) returnFocus.focus(); }
        scope.addEventListener('click', function (e) {
          var zoom = e.target.closest('[data-dp-zoom]'), closeButton = e.target.closest('[data-dp-close-image]'), expand = e.target.closest('[data-dp-expand-specs]');
          if (zoom && dialog) { returnFocus = zoom; if (typeof dialog.showModal === 'function') dialog.showModal(); else { dialog.setAttribute('open', ''); dialog.querySelector('button').focus(); } }
          if (closeButton || (dialog && e.target === dialog)) close();
          if (expand) { var groups = Array.from(scope.querySelectorAll('.dp-spec-group')); var open = groups.some(function (g) { return !g.open; }); groups.forEach(function (g) { g.open = open; }); expand.textContent = open ? '모두 접기' : '모두 펼치기'; }
        });
        scope.addEventListener('change', function (e) { if (e.target.matches('[data-dp-price-confirm]')) { acknowledged = e.target.checked; scope.querySelector('[data-dp-next-actions]').innerHTML = nextActions(); } });
        if (dialog) { dialog.addEventListener('close', function () { if (returnFocus) returnFocus.focus(); }); dialog.addEventListener('keydown', function (e) { if (e.key === 'Escape' && typeof dialog.close !== 'function') close(); }); }
        var expandButton = scope.querySelector('[data-dp-expand-specs]'); if (expandButton && !scope.querySelector('.dp-spec-group')) expandButton.hidden = true;
        bindImageFallback(scope);
      }
    };
  };
})();
