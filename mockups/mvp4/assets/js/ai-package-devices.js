/* /mvp4 AI 패키지 아래 — 등록된 AI 슈퍼컴퓨터 판매 제품 (2026-10-20 대표 확정).
 *
 * - 공개 API(live-supercomputer.js → /api/customer/supercomputers)를 그대로 쓴다. 모델·가격·사양을 지어내지 않는다.
 * - 개별 모델(2TB/4TB 등)을 각각 카드로 두고, 카드마다 그 상품 상세로 간다.
 * - 기본 정렬 = 낮은 가격순(가격 확인 필요는 뒤로). 손님이 고른 정렬은 주소(?scsort=)에 남겨 돌아와도 지킨다.
 * - 재고 수량·즉시 배송·납기는 적지 않는다. 사진이 없어도 «사진 준비 중»일 뿐 판매 상태와 무관하다.
 */
(function () {
  'use strict';
  var P = window.PAI;
  if (!P || !P.aiDevices || document.body.dataset.page !== 'ai-packages') return;
  var h = P.h, icon = P.icon, D = P.aiDevices;
  var SORTS = [['price-asc', '낮은 가격순'], ['price-desc', '높은 가격순'], ['featured', '추천순']], DEFAULT_SORT = 'price-asc';
  var items = null, failed = false;
  function sortKey() { var s = new URLSearchParams(location.search).get('scsort'); return SORTS.some(function (x) { return x[0] === s; }) ? s : DEFAULT_SORT; }
  function price(p) { return p.saleState === 'on_sale' ? p.price : null; }
  function sorted(list) {
    var s = sortKey();
    if (s === 'featured') return list;
    return list.slice().sort(function (x, y) {
      var px = price(x), py = price(y);
      if (px === null && py === null) return 0; if (px === null) return 1; if (py === null) return -1;
      return s === 'price-asc' ? px - py : py - px;
    });
  }
  function priceText(p) { return p.saleState === 'stopped' ? '판매 중지' : price(p) ? P.money(p.price) : '가격 확인 필요'; }
  function card(p) {
    var spec = [p.accelerator || p.processor, p.memory, p.storage].filter(Boolean).join(' · ');
    return '<li class="apd-card"><a href="supercomputer.html?id=' + h(p.id) + '" data-apd-item="' + h(p.id) + '"><div class="apd-photo">' + (p.image ? '<img src="' + h(p.image) + '" alt="" loading="lazy" width="320" height="240">' : '<span class="apd-photo-none">' + icon('package') + '사진 준비 중</span>') + '</div>' +
      '<div class="apd-body"><p class="apd-maker">' + h(p.maker || 'AI 전용 장비') + (p.modelLabel && p.modelGroup ? ' · ' + h(p.modelLabel) + ' 모델' : '') + '</p><h3>' + h(p.name) + '</h3><p class="apd-spec">' + h(spec || '사양 확인 필요') + '</p>' +
      (P.llmExamples ? P.llmExamples.badges(p) : '') +
      '<div class="apd-foot"><strong class="' + (price(p) ? '' : 'is-quiet') + '">' + h(priceText(p)) + '</strong><span>자세히 보기 ' + icon('arrow-right') + '</span></div></div></a></li>';
  }
  function html() {
    var body = items === null ? (failed ? '<p class="apd-state">제품 목록을 불러오지 못했어요. <a href="supercomputers.html">AI 슈퍼컴퓨터 목록</a>에서 다시 확인해 주세요.</p>' : (P.categoryLoading ? P.categoryLoading('package') : '<p class="apd-state" aria-busy="true">제품을 불러오고 있어요.</p>'))
      : !items.length ? '<p class="apd-state">아직 등록된 제품이 없어요.</p>'
      : '<ul class="apd-grid">' + sorted(items).map(card).join('') + '</ul>';
    return '<div class="apd-head"><div><span class="eyebrow">AI 슈퍼컴퓨터</span><h2 id="apd-title">AI를 직접 돌릴 장비도 있어요.</h2><p>지금 판매 중인 AI 전용 장비예요. 모델과 설치 구성은 전문상담사가 함께 맞춰드립니다.</p></div>' +
      '<div class="apd-tools">' + (items && items.length > 1 ? '<label>정렬<select data-apd-sort>' + SORTS.map(function (s) { return '<option value="' + s[0] + '"' + (sortKey() === s[0] ? ' selected' : '') + '>' + s[1] + '</option>'; }).join('') + '</select></label>' : '') +
      '<a href="supercomputers.html">전체 보기 ' + icon('arrow-right') + '</a></div></div>' + body;
  }
  function paint() {
    var page = document.querySelector('.ap-page');
    if (!page) return false;
    var box = page.querySelector('[data-apd]');
    if (!box) { box = document.createElement('section'); box.className = 'apd'; box.setAttribute('data-apd', ''); box.setAttribute('aria-labelledby', 'apd-title'); page.appendChild(box); }
    box.innerHTML = html();
    var s = box.querySelector('[data-apd-sort]');
    if (s) s.addEventListener('change', function () {
      var q = new URLSearchParams(location.search);
      if (s.value === DEFAULT_SORT) q.delete('scsort'); else q.set('scsort', s.value);
      history.replaceState(null, '', location.pathname + (q.toString() ? '?' + q : '') + location.hash);
      paint();
      var again = document.querySelector('[data-apd-sort]'); if (again) again.focus();
    });
    return true;
  }
  // 패키지 화면은 boot.js 가 그린다 — 그린 뒤(그리고 다시 그릴 때마다) 아래에 붙인다.
  new MutationObserver(function () { var page = document.querySelector('.ap-page'); if (page && !page.querySelector('[data-apd]')) paint(); }).observe(document.getElementById('app') || document.body, { childList: true, subtree: true });
  paint();
  D.list().then(function (d) { items = d.items; paint(); }, function () { failed = true; paint(); });
}());
