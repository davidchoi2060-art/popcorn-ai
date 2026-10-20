/* /mvp4 AI 슈퍼컴퓨터 카테고리 — 실제 상품 조회 어댑터 (v15 2026-10-19 · 카테고리 확장 2026-10-20).
 *
 * 목록  GET /api/customer/supercomputers        — 상품 데이터의 카테고리 분류('ai-supercomputer')로 조회한 상품 전부
 * 상세  GET /api/customer/supercomputers/{code} — 그 상품의 표시 정보·상세 내용·같은 제품의 고정 모델(예: 2TB/4TB)
 * 상품번호를 화면 코드에 적지 않는다. 관리자가 상품을 이 카테고리로 옮기면 목록·상세·문의에 그대로 나온다.
 * 값이 없으면 null — 화면은 «확인 필요»로 그리고, 다른 상품(GB10)의 값을 채워 넣지 않는다.
 *   sale_state: on_sale(가격 있음) · check(가격 확인 필요) · stopped(판매 중지)
 */
(function () {
  'use strict';
  var P = window.PAI;
  if (!P) return;
  var IMG = /^(assets\/images\/[A-Za-z0-9/_.-]+\.(png|jpe?g|webp)|\/api\/product-images\/\d+\/(detail|thumbnail))$/;
  var pending = null;
  function str(v) { return typeof v === 'string' && v.trim() ? v.trim() : null; }
  function item(x) {
    var price = typeof x.price === 'number' && isFinite(x.price) && x.price > 0 ? x.price : null;
    var images = (Array.isArray(x.images) ? x.images : []).filter(function (im) { return im && typeof im.src === 'string' && IMG.test(im.src); });
    var state = x.sale_state === 'on_sale' && price !== null ? 'on_sale' : x.sale_state === 'stopped' ? 'stopped' : 'check';
    return { id: String(x.product_code), name: str(x.name) || '상품명 확인 필요', officialName: str(x.official_name), maker: str(x.maker), modelName: str(x.model_name),
      accelerator: str(x.accelerator), processor: str(x.processor), memory: str(x.memory), storage: str(x.storage), os: str(x.os), architecture: str(x.architecture),
      modelGroup: str(x.model_group), modelLabel: str(x.model_label), featuredRank: typeof x.featured_rank === 'number' ? x.featured_rank : null,
      images: images, image: images.length ? images[0].src : null, price: price, saleState: state,
      derived: Array.isArray(x.derived) ? x.derived.filter(function (k) { return typeof k === 'string'; }) : [],
      detail: x.detail && typeof x.detail === 'object' ? x.detail : {},
      models: Array.isArray(x.models) ? x.models.map(function (m) { var mp = typeof m.price === 'number' && m.price > 0 ? m.price : null; return { id: String(m.product_code), label: str(m.model_label), price: mp, saleState: m.sale_state === 'on_sale' && mp !== null ? 'on_sale' : m.sale_state === 'stopped' ? 'stopped' : 'check' }; }) : [] };
  }
  function get(path) {
    var ctrl = new AbortController(), timer = setTimeout(function () { ctrl.abort(); }, 20000);
    return fetch(path, { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json', 'X-Popcorn-Surface': 'mvp4' }, signal: ctrl.signal })
      .then(function (r) { clearTimeout(timer); return r.json().catch(function () { return null; }).then(function (d) {
        if (r.ok && d && d.ok === true) return d;
        var e = new Error('http ' + r.status); e.status = r.status; throw e;
      }); }, function (e) { clearTimeout(timer); e.status = 0; throw e; });
  }
  function list(force) {
    if (pending && !force) return pending;
    pending = get('/api/customer/supercomputers').then(function (d) {
      if (!Array.isArray(d.items)) throw new Error('items');
      var items = d.items.map(item);
      P.aiDevices.data = { items: items, category: d.category || null, checkedAt: d.checked_at || null };
      return P.aiDevices.data;
    }).catch(function (e) { pending = null; throw e; });
    return pending;
  }
  // 상세: 없는 상품(분류에서 빠짐·노출 꺼짐)은 404 → notFound 로 구분한다.
  function detail(id) {
    if (!/^\d{1,18}$/.test(String(id || ''))) { var e = new Error('bad id'); e.status = 404; return Promise.reject(e); }
    return get('/api/customer/supercomputers/' + id).then(function (d) { return item(d.item); });
  }
  // 값이 없으면 «확인 필요». 사양 묶음은 화면마다 같은 순서로 쓴다.
  // 상품명에서 읽은 값(표시 정보에 직접 적지 않은 값)에는 «상품명 기준»을 붙인다(X01 2026-10-20).
  function mark(p, key, value) { return value && (p.derived || []).indexOf(key) >= 0 ? value + ' (상품명 기준)' : value; }
  function specs(p) {
    // [아이콘, 이름, 값, 상품명 기준 여부] — 값 칸에는 붙이지 않고 화면이 작은 줄로 따로 밝힌다(좁은 칸에서 값이 잘리지 않게).
    var d = function (k) { return (p.derived || []).indexOf(k) >= 0; };
    var c = p.accelerator ? 'accelerator' : 'processor';
    return [['cpu', p.accelerator ? 'AI 가속기' : '프로세서', p[c], d(c)], ['memory', '메모리', p.memory, d('memory')], ['hard-drive', '저장장치', p.storage, d('storage')], ['code', '운영체제', p.os, false]];
  }
  P.aiDevices = { data: null, list: list, detail: detail, specs: specs, mark: mark, listUrl: 'supercomputers.html' };
}());
