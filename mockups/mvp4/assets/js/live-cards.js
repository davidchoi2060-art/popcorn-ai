/* /mvp4 승인 v12 표현 계층을 실제 목록·상세에 연결 (2026-10-19 대표 승인 「B 부품 탐색형」).
 *
 * 1) 상품 목록 = B 부품 탐색형 카드. 승인 시안 card-concepts.js 의 cardB()/parts()/partHref() 렌더만 옮겼다
 *    (비교용 고정 3상품·페이지 초기화·임시 상세 route override 는 싣지 않는다). 검색·필터·정렬·더 보기는
 *    design-products.js 의 실제 목록 그대로이고, 카드만 P.catalogCardRenderer 로 바꾼다.
 *    부품 줄은 상품마다 상세와 같은 경로(P.live.loadDetail: 공개 구성 /api/customer/pc-offers/{code}, 비공개면
 *    몰 등록 구성 /api/customer/pc-registered/{code})로 화면에 가까운 카드부터 차례로 읽어 채운다.
 * 2) 상품 상세 = 승인 구성 상세(configuration-concept.js). 부품마다 사진·실제 사양·역할을 펼친다.
 *    부품 사진은 서버가 그 부품 설명 코드로 공개 승인한 사진(parts[].photo)만 쓴다 — 이름으로 찾지 않는다.
 *    기존 /mvp3 상세가 보여 주던 것(소개·장점·구매 전 확인·AI 상담·팝콘PC 옵션 변경)을 함께 둔다.
 * 부품 개별 단가는 보이지 않는다. 금액은 PC 한 대 금액과 대수 합계뿐이다(1~10대).
 */
(function () {
  'use strict';
  var P = window.PAI, h = P.h;
  if (!P || typeof P.catalogCardDataV12 !== 'function') return;
  // 카드 이름: 서버 카드 이름(광고 문구를 뗀 이름)이 짧은 이름, 몰 정식 상품명은 title·aria·상세 「전체 상품명」.
  // v12 의 짧은 이름 규칙은 몰 원문(「NO.xx」)을 기대해서, 정리된 이름에는 「분류 · 번호」가 되어 상품명을 잃는다.
  var baseCardData = P.catalogCardDataV12;
  P.catalogCardDataV12 = function (p) {
    var data = baseCardData(p);
    if (p && typeof p.name === 'string' && p.name.trim()) data.shortName = p.name.trim();
    if (p && typeof p.officialName === 'string' && p.officialName.trim()) data.fullName = p.officialName.trim();
    return data;
  };
  var IMG_RE =/^(assets\/|https:\/\/)|^\/api\/(product-images\/\d+\/detail|customer\/products\/\d+\/representative-image(\?size=card)?)$/;
  // 부품 타일은 48~54px 칸이다. 같은 승인 자산을 384px 로 줄여 둔 썸네일(WebP)을 쓰고, 상세 화면은 원본(detail)을 그대로 쓴다.
  // 썸네일을 못 읽으면 원본으로 한 번 바꿔 읽는다(error 처리 아래). 주소가 부품 설명 코드 하나로 정해져 같은 부품은 같은 주소다.
  function tileSrc(src) { return src.replace(/^(\/api\/product-images\/\d+)\/detail$/, '$1/thumbnail'); }

  // ── B 카드 (card-concepts.js cardB 와 같은 마크업) ─────────────────────
  function photo(data) {
    return '<a class="cc-photo" href="' + h(data.detailHref) + '" aria-label="' + h(data.fullName) + ' 상품 자세히 보기">' + (data.photoUrl ? '<img data-cc-photo src="' + h(data.photoUrl) + '" alt="' + h(data.fullName) + ' 상품 사진" loading="lazy">' : '<span class="cc-no-photo">' + P.icon('computer-tower') + '<span>상품 사진 준비 중</span></span>') + '</a>';
  }
  function title(data) {
    var name = data.shortName.split(' · ');
    return '<h2><a href="' + h(data.detailHref) + '" title="' + h(data.fullName) + '" aria-label="' + h(data.fullName) + '">' + h(name[0]) + (name.length > 1 ? '<span class="cc-card-name-detail">' + h(name.slice(1).join(' · ')) + '</span>' : '') + '</a></h2>';
  }
  function quickSpecs(data) {
    return '<dl class="cc-specs" aria-label="핵심 구성 요약">' + data.specs.map(function (spec) { return '<div' + (spec.pending ? ' class="is-pending"' : '') + '><dt>' + h(spec.label) + '</dt><dd>' + spec.lines.map(function (line) { return '<span>' + h(line) + '</span>'; }).join('') + '</dd></div>'; }).join('') + '</dl>';
  }
  function partIcon(spec) { return ({ CPU: 'cpu', GPU: 'graphics-card', RAM: 'memory', SSD: 'hard-drive', HDD: 'hard-drive', MB: 'squares-four', COOLER: 'gear', POWER: 'plug', PSU: 'plug', CASE: 'computer-tower' })[String(spec.slot || '').toUpperCase()] || 'package'; }
  function partLabel(spec) { return ({ CPU: 'CPU', GPU: '그래픽', RAM: '메모리', SSD: 'SSD', HDD: 'HDD', MB: '보드', COOLER: '쿨러', POWER: '파워', PSU: '파워', CASE: '케이스' })[String(spec.slot || '').toUpperCase()] || spec.label; }
  function partHref(product, spec) {
    if (spec.partId !== undefined && spec.partId !== null && String(spec.partId)) return P.designHref('component', 'normal', { id: product.id, partId: spec.partId });
    return null;
  }
  function parts(product, data) {
    if (product.liveDetail === 'pending') return '<section class="cc-parts" aria-busy="true" aria-label="' + h(data.shortName) + ' 부품 구성"><div class="cc-parts-heading"><h3>부품 구성</h3></div><p class="cc-source-note">부품 구성을 불러오고 있어요.</p></section>';
    var list = product.bomStatus === 'mismatch' ? [] : (product.specs || []).filter(function (spec) { return spec && spec.label && spec.value; }).slice(0, 8);
    if (!list.length) return '';
    return '<section class="cc-parts" aria-label="' + h(data.shortName) + ' 부품 구성"><div class="cc-parts-heading"><h3>부품 구성</h3><a href="' + h(data.detailHref) + '">전체 구성' + P.icon('caret-right') + '</a></div><ul class="cc-part-grid">' + list.map(function (spec) {
      var link = partHref(product, spec);
      // 이 부품 행이 가진 사진만(서버 공개 승인). 없으면 아이콘.
      var src = typeof spec.image === 'string' && IMG_RE.test(spec.image) ? spec.image : null;
      var media = src ? '<img data-cc-part-photo data-cc-part-icon="' + partIcon(spec) + '" data-cc-part-full="' + h(src) + '" src="' + h(tileSrc(src)) + '" alt="' + h(spec.value) + '" loading="lazy" decoding="async">' : P.icon(partIcon(spec));
      return '<li><' + (link ? 'a href="' + h(link) + '"' : 'span') + ' class="cc-part" title="' + h(spec.value) + '"' + (link ? ' aria-label="' + h(spec.label + ': ' + spec.value + ' 상세 보기') + '"' : '') + '><span class="cc-part-media">' + media + '</span><span>' + h(partLabel(spec)) + '</span></' + (link ? 'a' : 'span') + '></li>';
    }).join('') + '</ul></section>';
  }
  // 구성을 아직 못 읽었거나 공개·등록 구성 모두 없는 상품: 핵심 4칸을 서버 카드 사양(상품 평가 사양 · /api/customer/pc-catalog spec)으로
  // 채운다. 구성표 기반이 아님을 밝힌다(추정 용량·합산은 하지 않는다 — 서버 값 그대로).
  function withSummary(product, data) {
    if (Array.isArray(product.specs) && product.specs.length) return data;
    var rows = Array.isArray(product.summarySpecs) ? product.summarySpecs : [], used = false;
    data.specs = data.specs.map(function (cell) {
      if (!cell.pending) return cell;
      var row = rows.find(function (r) { return String(r.slot || '').toUpperCase() === cell.slot; });
      if (!row || !String(row.value || '').trim()) return cell;
      used = true; return { label: cell.label, slot: cell.slot, lines: [String(row.value)], pending: false };
    });
    // 읽는 중에는 아래 「부품 구성을 불러오고 있어요」가 대신 말한다 — 끝내 구성이 없을 때만 이 안내를 둔다.
    if (used && !data.sourceNote && product.liveDetail !== 'pending') data.sourceNote = '상품 사양 요약 · 정확한 부품 구성은 상세에서 확인';
    return data;
  }
  // 상품명(몰 제목)의 [CPU/메모리/SSD/그래픽] 이 기준이다(2026-10-21 대표 「제목이 틀리긴 힘드니까 그걸 기준으로」).
  // 몰 구성이나 요약 사양이 제목과 다른 칸만 제목 값으로 바꾼다. 같거나 제목에 없는 칸은 그대로 둔다.
  var TITLE_RE = /\[\s*([^\[\]\/]+?)\s*\/\s*(\d+)\s*G(?:B)?\s*\/\s*([^\/\]]+?)\s*\/\s*([^\]]+?)\s*(?:\]|$)/i;
  function titleSpec(product) {
    var m = String(product.officialName || product.name || '').match(TITLE_RE);
    if (!m) return null;
    var ssd = m[3].split('+')[0].trim(), gpu = m[4].replace(/\s*\*\s*\d+\s*EA\s*$/i, '').trim();
    return { CPU: m[1].trim(), RAM: Number(m[2]), SSD: ssd, GPU: gpu };
  }
  function gbOf(text) {
    var m = String(text || '').match(/(\d+(?:\.\d+)?)\s*(TB|GB|G)(?![A-Za-z0-9])/i);
    return m ? Math.round(Number(m[1]) * (/^T/i.test(m[2]) ? 1000 : 1)) : null;
  }
  // 메모리 총량: 구성 줄(용량 × 개수 · 「* N개」)을 더한다. 읽지 못한 줄이 하나라도 있으면 모른다(null).
  function ramTotal(product) {
    var rows = (product.specs || []).filter(function (s) { return String(s.slot || '').toUpperCase() === 'RAM'; });
    if (!rows.length) {
      var sum = (product.summarySpecs || []).find(function (r) { return r.slot === 'RAM'; });
      return sum ? gbOf(sum.value) : null;
    }
    var total = 0;
    for (var i = 0; i < rows.length; i++) {
      var gb = gbOf(rows[i].value);
      if (gb === null) return null;
      var kits = String(rows[i].value).match(/[*x×]\s*(\d+)\s*개/);
      var qty = kits ? Number(kits[1]) : (Number.isInteger(rows[i].quantity) && rows[i].quantity > 0 ? rows[i].quantity : 1);
      total += gb * qty;
    }
    return total;
  }
  function modelKey(text, slot) {
    var t = String(text || '').toUpperCase().replace(/\s+/g, '');
    if (slot === 'GPU') { var g = t.match(/(\d{3,4})(TI|SUPER|XT)?/); return g ? g[1] + (g[2] || '') : null; }
    var c = String(text || '').toUpperCase().match(/(?:^|[^0-9A-Z])(\d{3,5}[A-Z0-9]{0,4})(?![0-9A-Z])/); return c ? c[1] : null;
  }
  function withTitle(product, data) {
    var t = titleSpec(product);
    if (!t) return data;
    data.specs = data.specs.map(function (cell) {
      var shown = cell.lines.join(' '), want = null;
      if (cell.slot === 'RAM') { var have = ramTotal(product); if (cell.pending || (have !== null && have !== t.RAM)) want = t.RAM + 'GB'; }
      else if (cell.slot === 'SSD') { var a = gbOf(t.SSD); if (a !== null && (cell.pending || gbOf(shown) !== a)) want = t.SSD.replace(/G$/i, 'GB'); }
      else if (cell.slot === 'CPU' || cell.slot === 'GPU') {
        var k = modelKey(t[cell.slot], cell.slot);
        if (k && (cell.pending || modelKey(shown, cell.slot) !== k)) want = t[cell.slot];
      }
      return want ? { label: cell.label, slot: cell.slot, lines: [want], pending: false } : cell;
    });
    return data;
  }
  function cardB(product) {
    var data = withTitle(product, withSummary(product, P.catalogCardDataV12(product)));
    return '<article class="cc-card cc-card-b" data-card-product="' + h(data.id) + '"><div class="cc-card-top"><div class="cc-card-copy"><span class="cc-category">' + h(data.category || '조립 PC') + '</span>' + title(data) + '<strong class="cc-price">' + h(data.priceLabel) + '</strong><span class="cc-status">' + P.icon('tag') + h(data.saleLabel) + '</span></div>' + photo(data) + '</div><div class="cc-card-lower">' + quickSpecs(data) + (data.sourceNote ? '<p class="cc-source-note">' + h(data.sourceNote) + '</p>' : '') + parts(product, data) + '<p class="cc-card-caption">주요 부품부터, 전체 구성을 확인하세요.</p><div class="cc-card-actions"><a class="btn btn-primary" href="' + h(data.detailHref) + '">상품 자세히 보기' + P.icon('arrow-right') + '</a><a class="btn btn-outline" href="' + h(data.chatHref) + '">' + P.icon('chat-circle') + 'AI에게 물어보기</a></div></div></article>';
  }
  P.catalogCardRenderer = function (p) { return cardB(p); };
  P.catalogGridClass = 'cc-grid cc-grid-b';

  // 보이는 카드의 공개 구성을 차례로(동시 3개) 읽어 그 카드만 다시 그린다.
  // 차례는 지금 화면에 가까운 카드부터다(390px 에서는 첫 한두 장만 보인다). 화면 밖 카드도 빼지 않고 뒤에 읽는다.
  var queue = [], running = 0, seen = Object.create(null);
  function distance(id) {
    var el = document.querySelector('[data-card-product="' + id + '"]');
    if (!el) return Infinity;
    var r = el.getBoundingClientRect(), vh = window.innerHeight || 0;
    return r.bottom < 0 ? -r.bottom : r.top > vh ? r.top - vh : 0;
  }
  function next() {
    var best = 0, bestD = Infinity;
    for (var i = 0; i < queue.length; i++) { var d = distance(queue[i]); if (d < bestD) { best = i; bestD = d; if (!d) break; } }
    return queue.splice(best, 1)[0];
  }
  function pump() {
    while (running < 3 && queue.length) {
      var id = next(); running++;
      P.live.loadDetail(id).then(function (p) {
        running--; if (!p) return pump();
        if (p.liveDetail === 'pending') p.liveDetail = 'error';
        document.querySelectorAll('[data-card-product="' + p.id + '"]').forEach(function (old) { old.outerHTML = cardB(p); });
        pump();
      }, function () { running--; pump(); });
    }
  }
  function scan() {
    document.querySelectorAll('.cc-card-b[data-card-product]').forEach(function (el) {
      var id = el.getAttribute('data-card-product'), p = P.getCatalogProduct(id);
      // 공개 승인 구성이 없는 상품도 읽는다 — 상세처럼 몰 등록 구성으로 부품 줄을 채운다(2026-10-21 대표: 목록만 부품 구성이 비었음).
      if (!p || seen[id] || p.liveDetail !== 'pending') return;
      seen[id] = true; queue.push(id);
    });
    pump();
  }
  new MutationObserver(function () { scan(); }).observe(document.documentElement, { childList: true, subtree: true });
  // 사진을 못 읽으면 아이콘으로(승인 시안과 같은 대체).
  document.addEventListener('error', function (event) {
    var img = event.target;
    if (!img || !img.matches) return;
    if (img.matches('img[data-cc-part-photo]')) {
      // 썸네일 실패 -> 원본 한 번 -> 잠시 뒤 같은 주소 한 번 더(일시 오류) -> 아이콘.
      var full = img.getAttribute('data-cc-part-full');
      if (full && img.getAttribute('src') !== full) { img.setAttribute('src', full); return; }
      if (!img.hasAttribute('data-cc-retried')) { img.setAttribute('data-cc-retried', ''); setTimeout(function () { if (img.isConnected) img.setAttribute('src', full || img.getAttribute('src')); }, 1500); return; }
      img.parentElement.innerHTML = P.icon(img.getAttribute('data-cc-part-icon') || 'package'); return;
    }
    if (img.matches('img[data-cc-photo]')) img.parentElement.innerHTML = '<span class="cc-no-photo">' + P.icon('computer-tower') + '<span>상품 사진을 확인하고 있어요.</span></span>';
  }, true);

  // ── 상품 상세 = 승인 구성 상세 + 기존 /mvp3 상세 정보 ──────────────────
  var C = P.configurationConceptV12;
  if (!C) return;
  // 상품 설명 자리(2026-10-21 코발트 승인 「자리만」): 부품 구성 바로 다음에 늘 같은 구조를 둔다.
  // 운영에 있는 소개(ABOUT THIS PC)는 이 자리 안에 그대로 보인다. 소개가 없는 상품은 자리만 두고 숨긴다 -- 설명을 지어 넣지 않는다.
  function intro(p) {
    var d = p.description;
    var benefits = d ? (Array.isArray(d.benefits) ? d.benefits : []).map(function (b) { return Array.isArray(b) ? { title: b[0], text: b[1] } : b; }).filter(function (b) { return b && (b.title || b.text); }) : [];
    var body = d ? '<span class="cf-eyebrow">ABOUT THIS PC</span><h3 class="cf-desc-title">' + h(d.title || '이 PC 소개') + '</h3>' +
      (d.intro ? '<p>' + h(d.intro) + '</p>' : '') + (d.scene ? '<p class="cf-muted">' + h(d.scene) + '</p>' : '') +
      (benefits.length ? '<ul class="cf-benefits">' + benefits.map(function (b) { return '<li><strong>' + h(b.title || '') + '</strong>' + (b.text ? '<p>' + h(b.text) + '</p>' : '') + '</li>'; }).join('') + '</ul>' : '') : '';
    return '<section class="cf-components cf-description" data-product-description aria-labelledby="cf-desc-heading"' + (body ? '' : ' hidden') + '><div class="cf-section-heading"><div><h2 id="cf-desc-heading">상품 설명</h2></div></div><div class="cf-desc-body">' + body + '</div></section>';
  }
  function checks(p) {
    var c = p.customerConditions;
    if (!c) return '';
    var rows = Object.keys(c).map(function (k) { return c[k] && c[k].customer_statement; }).filter(function (s) { return typeof s === 'string' && s.trim(); });
    if (!rows.length) return '';
    return '<section class="cf-components" aria-labelledby="cf-check-title"><div class="cf-section-heading"><div><span class="cf-eyebrow">BEFORE YOU BUY</span><h2 id="cf-check-title">구매 전 확인</h2></div></div><ul class="cf-checks">' + rows.map(function (s) { return '<li>' + P.icon('info') + '<span>' + h(s) + '</span></li>'; }).join('') + '</ul></section>';
  }
  function more(p) {
    return '<div class="cf-more-actions"><a class="btn btn-outline" href="' + h(P.designHref('chat', 'product', { id: p.id })) + '">' + P.icon('chat-circle') + '이 PC, 나에게 맞을까? AI에게 물어보기</a>' +
      (p.mallUrl ? '<a class="btn btn-outline" href="' + h(p.mallUrl) + '" target="_blank" rel="noopener">팝콘PC에서 부품 옵션 변경하기 <span aria-hidden="true">↗</span></a>' : '') + '</div>';
  }
  var originalProduct = P.designScreens.product;
  P.designScreens.product = function (ctx) {
    ctx = ctx || {};
    var q = C.quantity(ctx.query && ctx.query.get ? ctx.query.get('quantity') || ctx.query.get('sets') : 1);
    var id = ctx.productId || (ctx.query && ctx.query.get ? ctx.query.get('id') : null);
    var p = id ? P.getCatalogProduct(id) : null;
    if (ctx.state === 'loading') return { html: C.render(null, q, 'loading') };
    if (!p) return { html: C.render(null, q, ctx.state === 'detail-unavailable' ? 'error' : 'not-found') };
    var html = C.render(p, q, ctx.state === 'price-unavailable' ? 'price-unavailable' : 'normal');
    // 소개·구매 전 확인·AI 상담/옵션 변경을 부품 구성 아래(「다른 PC 살펴보기」 앞)에 둔다.
    var extra = intro(p) + checks(p) + more(p);
    html = html.replace('<a class="cf-back"', extra + '<a class="cf-back"');
    // 대표 사진 고지(서버 문장 · /mvp3 와 같은 「AI 조립 예시」 안내)를 사진 바로 아래에 둔다.
    if (p.photoNotice && p.image) html = html.replace('</details></div></section><section class="cf-components"', '</details></div></section><p class="cf-photo-notice">' + h(p.photoNotice) + '</p><section class="cf-components"');
    document.title = P.cardTitleV12(p) + ' · PC 구성 | 팝콘AI';
    return { html: html, mount: function () { var root = document.querySelector('.cf-page'); if (root && !(ctx.state === 'price-unavailable')) C.mount(root, p, q); } };
  };
  P.designScreens.productLegacy = originalProduct;
}());
