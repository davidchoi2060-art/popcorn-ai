/* /mvp4 AI 슈퍼컴퓨터(v15) — 실제 상품 조회 어댑터 (2026-10-19 대표 승인 v15).
 *
 * 시안의 관찰 데이터 모듈(10/19 관찰 가격)을 대신한다. 가격·판매 상태·상품명·용량은
 * GET /api/customer/supercomputers 응답만 쓴다 — 화면에 가격을 다시 적지 않는다.
 *   price = null 이거나 sale_state = 'check' 이면 «가격 확인 필요»·«판매 여부 확인 중» 상태로 그린다.
 *   조회 실패는 «상품 정보를 불러오지 못했어요»(다시 불러오기)로 그린다.
 * 두 모델(129615 = 2TB · 129614 = 4TB)은 고정 완제품이다 — 부품 변경은 없고 모델·수량만 고른다.
 */
(function () {
  'use strict';
  var P = window.PAI;
  if (!P) return;
  var IDS = ['129615', '129614'];
  var IMAGE = 'assets/images/supercomputer/gb10-product.jpg';
  var pending = null;
  function item(x) {
    var price = typeof x.price === 'number' && isFinite(x.price) && x.price > 0 ? x.price : null;
    return { id: String(x.product_code), name: x.name || 'Dell Pro Max GB10', fullName: x.official_name || '', storage: x.storage || null,
      memory: x.memory || '128GB', price: price, saleState: x.sale_state === 'on_sale' && price !== null ? 'on_sale' : 'check', image: IMAGE };
  }
  function load(force) {
    if (pending && !force) return pending;
    var ctrl = new AbortController(), timer = setTimeout(function () { ctrl.abort(); }, 20000);
    pending = fetch('/api/customer/supercomputers', { credentials: 'same-origin', cache: 'no-store',
      headers: { Accept: 'application/json', 'X-Popcorn-Surface': 'mvp4' }, signal: ctrl.signal })
      .then(function (r) { clearTimeout(timer); return r.json().catch(function () { return null; }).then(function (d) {
        if (!r.ok || !d || d.ok !== true || !Array.isArray(d.items)) throw new Error('supercomputers ' + r.status);
        var products = {};
        d.items.forEach(function (x) { var p = item(x); if (IDS.indexOf(p.id) >= 0) products[p.id] = p; });
        P.gb10.data = { products: products, checkedAt: d.checked_at || null };
        return P.gb10.data;
      }); }, function (e) { clearTimeout(timer); throw e; })
      .catch(function (e) { pending = null; throw e; });
    return pending;
  }
  P.gb10 = { ids: IDS, image: IMAGE, data: null, load: load };
}());
