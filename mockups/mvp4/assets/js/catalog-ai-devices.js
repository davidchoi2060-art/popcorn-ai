/* F04(2026-10-20): 공통 검색에서 AI 슈퍼컴퓨터도 찾는다. R01(2026-10-20): 두 결과의 범위·개수·빈 상태 문구를 나눠 보인다.
 *
 * 헤더 검색·PC 쇼핑 검색은 /mvp4/?screen=catalog&q=… (조립PC 목록)로 간다. 조립PC 검색은 그대로 두고, 같은 검색어로
 * AI 슈퍼컴퓨터 카테고리(GET /api/customer/supercomputers — 분류로 조회한 실제 상품)도 찾아 목록 위에 «AI 슈퍼컴퓨터 n개»로
 * 보인다. 카드는 그 상품의 슈퍼컴퓨터 상세(supercomputer.html?id=)로 간다.
 * 찾는 범위: 표시 이름·몰 상품명·상품번호·제조사·모델명·가속기·프로세서·메모리·저장장치·OS.
 *
 * 검색어가 있을 때 결과 범위(R01):
 *   - 검색어·판매 상태(판매 중만/품절 포함)는 두 결과에 모두 적용한다. 용도·분류·정렬은 조립PC 목록에만 적용된다고 밝힌다.
 *   - 조립PC 목록 제목은 «조립PC n개»로 바꾼다(«상품 목록»이 전체 결과처럼 읽히지 않게).
 *   - AI 결과가 있고 조립PC 가 0개면 공통 빈 상태(«조건에 맞는 상품이 없어요») 대신 «조립PC에서는 맞는 상품이 없어요» 한 줄로.
 *   - 둘 다 없으면 빈 상태 문장에 «조립PC와 AI 슈퍼컴퓨터 모두»라고 밝힌다.
 */
(function () {
  'use strict';
  var P = window.PAI;
  if (!P || !P.designScreens || !P.designScreens.catalog || !P.aiDevices) return;
  var original = P.designScreens.catalog, D = P.aiDevices, h = P.h;
  function norm(s) { return String(s || '').toLocaleLowerCase('ko-KR').replace(/\s+/g, ''); }
  function matches(items, term, sale) {
    var needle = norm(term);
    if (!needle) return [];
    return items.filter(function (p) {
      if (sale !== 'all' && p.saleState === 'stopped') return false;   // «판매 중만»이면 판매 중지 장비는 뺀다
      return norm([p.name, p.officialName, p.id, p.maker, p.modelName, p.accelerator, p.processor, p.memory, p.storage, p.os].join(' ')).indexOf(needle) >= 0;
    });
  }
  function price(p) { return p.saleState === 'stopped' ? '판매 중지' : p.saleState === 'on_sale' && p.price ? P.money(p.price) : '가격 확인 필요'; }
  function block(list, term, sale) {
    if (!list.length) return '';
    return '<section class="cad-results" aria-labelledby="cad-title"><div class="cad-head"><h2 id="cad-title">AI 슈퍼컴퓨터 <span>' + list.length + '개</span></h2><a href="' + h(D.listUrl) + '">AI 슈퍼컴퓨터 전체 보기 ' + P.icon('arrow-right') + '</a></div>' +
      '<p class="cad-note">「' + h(term) + '」에 맞는 AI 전용 장비입니다. ' + (sale === 'all' ? '판매 중지 장비도 포함했어요.' : '판매 중인 장비만 보여요.') + ' 용도·정렬 조건은 아래 조립PC 목록에만 적용돼요.</p><ul class="cad-list">' + list.map(function (p) {
        return '<li><a href="supercomputer.html?id=' + h(p.id) + '" data-cad-item="' + h(p.id) + '"><span class="cad-photo">' + (p.image ? '<img src="' + h(p.image) + '" alt="" loading="lazy" width="96" height="96">' : P.icon('cpu')) + '</span><span class="cad-body"><small>' + h(p.maker || 'AI 전용 장비') + (p.modelLabel && p.modelGroup ? ' · ' + h(p.modelLabel) + ' 모델' : '') + ' · 상품번호 ' + h(p.id) + '</small><strong>' + h(p.name) + '</strong><span>' + h([p.accelerator || p.processor, p.memory, p.storage].filter(Boolean).join(' · ')) + '</span></span><span class="cad-price">' + h(price(p)) + '</span></a></li>';
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
      var items = null, aiCount = 0, busy = false;
      function term() { return form.elements.q ? form.elements.q.value.trim() : ''; }
      function sale() { return form.elements.sale ? form.elements.sale.value : 'selling'; }
      // 조립PC 결과(design-products 가 다시 그릴 때마다)의 제목·빈 상태 문구를 검색 범위에 맞춘다.
      function label() {
        if (busy) return;
        busy = true;
        var t = term(), head = results.querySelector('.dp-results-heading h2'), empty = results.querySelector('.dp-empty');
        if (t && head && head.firstChild && head.firstChild.nodeType === 3) head.firstChild.nodeValue = '조립PC ';
        if (t && empty && !empty.hasAttribute('data-cad-labeled')) {
          empty.setAttribute('data-cad-labeled', '');
          var title = empty.querySelector('h2'), text = empty.querySelector('p');
          if (aiCount > 0) {
            empty.classList.add('cad-pc-none');
            if (title) title.textContent = '조립PC에서는 「' + t + '」에 맞는 상품이 없어요.';
            if (text) text.textContent = '위 AI 슈퍼컴퓨터 결과를 확인하거나, 검색어·판매 상태를 바꿔 보세요.';
          } else {
            if (title) title.textContent = '조립PC와 AI 슈퍼컴퓨터 모두에서 「' + t + '」에 맞는 상품이 없어요.';
          }
        }
        busy = false;
      }
      new MutationObserver(label).observe(results, { childList: true, subtree: true });
      function update() {
        var t = term();
        if (!t) { aiCount = 0; box.innerHTML = ''; label(); return; }
        if (items === null) { D.list().then(function (d) { items = d.items; update(); }, function () { items = []; update(); }); return; }
        var list = matches(items, t, sale());
        aiCount = list.length;
        box.innerHTML = block(list, t, sale());
        var empty = results.querySelector('.dp-empty'); if (empty) empty.removeAttribute('data-cad-labeled');
        label();
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
