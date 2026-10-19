/* /mvp4 화면 진입 (2026-10-19). 승인 v8.1 의 design-boot 를 실제 서비스용으로 바꾼 것.
 *
 * - 모든 고객 화면은 /mvp4/?screen=<화면>&… 한 주소에서 그린다(직접 진입·새로고침·뒤로가기 그대로).
 * - 화면 상태(state)는 URL 이 아니라 실제 응답이 정한다. URL 로 받는 것은 대화의 시작 방식
 *   (welcome · product · clarify)뿐이다 — 「완료」「접수됨」 같은 결과 화면을 주소만으로 만들 수 없다.
 * - 개발·검토 안내(검토 띠·관찰 자료 문구)는 고객 화면에 싣지 않는다.
 */
(function () {
  'use strict';
  var P = window.PAI, q = P.qs;
  var SCREENS = ['home', 'catalog', 'product', 'component', 'chat', 'compare', 'options', 'quote', 'save', 'saved', 'consult'];
  var CHAT_ENTRY = ['welcome', 'product', 'clarify'];
  var screen = q.get('screen') || 'home';
  if (SCREENS.indexOf(screen) < 0 || !P.designScreens[screen]) screen = 'home';

  var map = { index: 'home', home: 'home', pcs: 'catalog', 'pc-detail': 'product', 'pc-finder': 'chat' };
  var originalHref = P.href;
  P.href = function (page, params) {
    if (map[page]) return P.designHref(map[page], map[page] === 'chat' ? 'welcome' : 'normal', params);
    if (page === 'bridge') return P.designHref(params && params.target === 'saved' ? 'saved' : 'quote', 'normal');
    return originalHref(page, params);
  };

  function paint(state) {
    var renderer = P.designScreens[screen];
    var result = renderer({ state: state, productId: q.get('id'), query: q });
    document.body.dataset.page = screen === 'catalog' || screen === 'product' ? 'pcs' : screen === 'chat' ? 'pc-finder' : screen;
    document.title = '팝콘AI · ' + (screen === 'home' ? '좋은 PC에서, 쓸모 있는 AI까지' : P.designLabels[screen] || '');
    document.getElementById('app').innerHTML = P.shell(result.html);
    var skip = document.querySelector('.skip-link'); if (skip) skip.href = location.pathname + location.search + '#main-content';
    P.bindShell(); if (result.mount) result.mount();
    var search = document.querySelector('[data-search-form]');
    if (search) { var clone = search.cloneNode(true); search.replaceWith(clone); clone.addEventListener('submit', function (e) { e.preventDefault(); location.href = P.designHref('catalog', 'normal', { q: clone.querySelector('input').value }); }); }
    document.querySelectorAll('img').forEach(function (img) {
      img.addEventListener('error', function () { if (img.classList.contains('icon') || img.hasAttribute('data-dp-photo') || !img.parentNode) return; img.hidden = true; var msg = document.createElement('span'); msg.className = 'ds-muted'; msg.textContent = '사진을 불러오지 못했어요'; img.parentNode.appendChild(msg); }, { once: true });
    });
  }

  function productIds() {
    if (screen === 'compare') return String(q.get('ids') || '').split(',').filter(Boolean).slice(0, 3);
    return q.get('id') ? [q.get('id')] : [];
  }

  // 응답으로 상태를 정한다.
  function stateAfterLoad() {
    var live = P.live.state;
    if (screen === 'catalog') return live === 'error' ? 'error' : live === 'empty' ? 'empty' : 'normal';
    if (screen === 'product') {
      var p = P.getCatalogProduct(q.get('id'));
      if (live === 'error') return 'detail-unavailable';
      if (!p) return 'not-found';
      if (!(typeof p.price === 'number' && p.price > 0)) return 'price-unavailable';
      return 'normal';
    }
    if (screen === 'component') return live === 'error' ? 'error' : 'normal';
    if (screen === 'chat') { var entry = q.get('state'); return CHAT_ENTRY.indexOf(entry) >= 0 ? entry : 'welcome'; }
    return 'normal';
  }

  // 목록·상세는 불러오는 중 화면을, 메인은 상품 줄 없이 먼저 그린다(빈 화면으로 기다리지 않게).
  var early = { catalog: 'loading', product: 'loading', component: 'loading', home: 'normal' }[screen];
  if (early) paint(early);
  P.live.loadCatalog().catch(function () { /* 상태는 stateAfterLoad 가 알린다 */ }).then(function () {
    return Promise.all(productIds().map(function (id) { return P.live.loadDetail(id); }));
  }).then(function () { paint(stateAfterLoad()); }, function () { paint(stateAfterLoad()); });
}());
