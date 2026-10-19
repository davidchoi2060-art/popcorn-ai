/* F04(2026-10-20): 공통 검색에서 AI 슈퍼컴퓨터도 찾는다.
 *
 * 헤더 검색·PC 쇼핑 검색은 /mvp4/?screen=catalog&q=… (조립PC 목록)로 간다. 조립PC 검색은 그대로 두고, 같은 검색어로
 * AI 슈퍼컴퓨터 카테고리(GET /api/customer/supercomputers — 분류로 조회한 실제 상품)도 찾아 목록 위에 «AI 슈퍼컴퓨터 n개»로
 * 보인다. 카드는 그 상품의 슈퍼컴퓨터 상세(supercomputer.html?id=)로 간다. 검색어가 없거나 맞는 장비가 없으면 아무것도 넣지 않는다.
 * 찾는 범위: 표시 이름·몰 상품명·상품번호·제조사·모델명·가속기·프로세서·메모리·저장장치·OS.
 */
(function () {
  'use strict';
  var P = window.PAI;
  if (!P || !P.designScreens || !P.designScreens.catalog || !P.aiDevices) return;
  var original = P.designScreens.catalog, D = P.aiDevices, h = P.h;
  function norm(s) { return String(s || '').toLocaleLowerCase('ko-KR').replace(/\s+/g, ''); }
  function matches(items, term) {
    var needle = norm(term);
    if (!needle) return [];
    return items.filter(function (p) {
      return norm([p.name, p.officialName, p.id, p.maker, p.modelName, p.accelerator, p.processor, p.memory, p.storage, p.os].join(' ')).indexOf(needle) >= 0;
    });
  }
  function price(p) { return p.saleState === 'stopped' ? '판매 중지' : p.saleState === 'on_sale' && p.price ? P.money(p.price) : '가격 확인 필요'; }
  function block(list, term) {
    if (!list.length) return '';
    return '<section class="cad-results" aria-labelledby="cad-title"><div class="cad-head"><h2 id="cad-title">AI 슈퍼컴퓨터 <span>' + list.length + '개</span></h2><a href="' + h(D.listUrl) + '">AI 슈퍼컴퓨터 전체 보기 ' + P.icon('arrow-right') + '</a></div>' +
      '<p class="cad-note">「' + h(term) + '」에 맞는 AI 전용 장비입니다.</p><ul class="cad-list">' + list.map(function (p) {
        return '<li><a href="supercomputer.html?id=' + h(p.id) + '"><span class="cad-photo">' + (p.image ? '<img src="' + h(p.image) + '" alt="" loading="lazy" width="96" height="96">' : P.icon('cpu')) + '</span><span class="cad-body"><small>' + h(p.maker || 'AI 전용 장비') + (p.modelLabel && p.modelGroup ? ' · ' + h(p.modelLabel) + ' 모델' : '') + ' · 상품번호 ' + h(p.id) + '</small><strong>' + h(p.name) + '</strong><span>' + h([p.accelerator || p.processor, p.memory, p.storage].filter(Boolean).join(' · ')) + '</span></span><span class="cad-price">' + h(price(p)) + '</span></a></li>';
      }).join('') + '</ul></section>';
  }
  P.designScreens.catalog = function (ctx) {
    var screen = original.apply(this, arguments), oldMount = screen.mount;
    screen.mount = function () {
      if (oldMount) oldMount.apply(this, arguments);
      var scope = document.querySelector('[data-dp-catalog]'); if (!scope) return;
      var form = scope.querySelector('[data-dp-filter-form]'), results = scope.querySelector('[data-dp-results]');
      if (!form || !results) return;
      var box = document.createElement('div'); box.setAttribute('data-cad-box', ''); box.setAttribute('aria-live', 'polite');
      results.parentNode.insertBefore(box, results);
      var items = null;
      function update() {
        var term = form.elements.q ? form.elements.q.value.trim() : '';
        if (!term) { box.innerHTML = ''; return; }
        if (items === null) { D.list().then(function (d) { items = d.items; update(); }, function () { items = []; }); return; }
        box.innerHTML = block(matches(items, term), term);
      }
      form.addEventListener('input', update);
      form.addEventListener('change', update);
      form.addEventListener('submit', function () { setTimeout(update, 0); });
      scope.addEventListener('click', function (e) { if (e.target.closest('[data-dp-reset]')) setTimeout(update, 0); });
      update();
    };
    return screen;
  };
  D.searchMatches = matches;
}());
