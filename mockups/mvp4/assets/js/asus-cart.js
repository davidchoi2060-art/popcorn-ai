/* ASUS 기획전 장바구니 버튼. 완제품 3종을 각 1대 담는 자리다(2026-11-06 사용자 확정).
 * 판매처 연결 전 기본 상태: 버튼 비활성 + 준비 중 안내. 네트워크 쓰기 · 이동 · 브라우저 저장을 하지 않는다.
 * 연결 지점은 setAdapter 하나다. 계약 = docs/asus-ai-pc-v4/CART-ADAPTER.md(내부 제안, 실제 API 명세 아님).
 * 이 파일은 모델 id 와 수량만 넘긴다. 부품 번호와 기획 검토가는 완제품 담기 값이 아니므로 받지도 넘기지도 않는다. */
(function () {
  'use strict';
  var P = window.PAI, A = P.asus, h = P.h;
  var QUANTITY = 1;
  var TIMEOUT_MS = 15000;
  var LABEL = '장바구니에 담기';
  var PENDING = '담는 중';
  var NOT_READY = '장바구니 준비 중입니다.';
  var FAILED = '장바구니에 담지 못했습니다. 잠시 후 다시 시도해 주세요.';

  var adapter = null;
  var pending = {};
  var failed = {};

  function paint(box) {
    var id = box.getAttribute('data-az-cart');
    var button = box.querySelector('button');
    var note = box.querySelector('[data-az-cart-note]');
    var busy = !!pending[id];
    button.disabled = !adapter || busy;
    button.textContent = busy ? PENDING : LABEL;
    button.setAttribute('aria-busy', String(busy));
    note.textContent = !adapter ? NOT_READY : failed[id] ? FAILED : '';
    note.hidden = !note.textContent;
  }

  function refresh() {
    Array.prototype.forEach.call(document.querySelectorAll('[data-az-cart]'), paint);
  }

  // 판매처가 준 이동 주소가 허용한 출처일 때만 쓴다. 아니면 성공으로 치지 않는다.
  function allowedUrl(url) {
    if (typeof url !== 'string') return null;
    try {
      var parsed = new URL(url);
      return adapter.origins.indexOf(parsed.origin) >= 0 ? parsed.href : null;
    } catch (e) { return null; }
  }

  function add(id) {
    if (!adapter) return Promise.resolve({ ok: false, code: 'not_connected' });
    if (!A.known(id)) return Promise.resolve({ ok: false, code: 'unknown_model' });
    if (pending[id]) return Promise.resolve({ ok: false, code: 'busy' });
    pending[id] = true;
    failed[id] = false;
    refresh();
    var timer;
    var timeout = new Promise(function (resolve) { timer = setTimeout(function () { resolve({ ok: false, code: 'timeout' }); }, TIMEOUT_MS); });
    var call;
    try { call = Promise.resolve(adapter.add({ modelId: id, quantity: QUANTITY })); } catch (e) { call = Promise.reject(e); }
    return Promise.race([call, timeout]).then(function (r) {
      var url = r && r.ok === true ? allowedUrl(r.url) : null;
      return url ? { ok: true, url: url } : { ok: false, code: r && r.code || 'bad_result' };
    }, function () { return { ok: false, code: 'failed' }; }).then(function (result) {
      clearTimeout(timer);
      pending[id] = false;
      failed[id] = !result.ok;
      refresh();
      if (result.ok) window.location.assign(result.url);
      return result;
    });
  }

  // 판매처 연결 코드만 부른다. origins = 담은 뒤 이동해도 되는 출처 목록.
  function setAdapter(next) {
    if (next !== null && !(next && typeof next.add === 'function' && Array.isArray(next.origins) && next.origins.length)) throw new Error('adapter');
    adapter = next;
    pending = {};
    failed = {};
    refresh();
  }

  function html(id, name) {
    return '<div class="az-cart" data-az-cart="' + h(id) + '"><button class="az-btn az-btn-solid az-cart-btn" type="button" aria-label="' + h(name) + ' ' + LABEL + '" disabled>' + LABEL + '</button>' +
      '<p class="az-cart-note" data-az-cart-note role="status">' + NOT_READY + '</p></div>';
  }

  document.addEventListener('click', function (event) {
    var button = event.target && event.target.closest ? event.target.closest('.az-cart-btn') : null;
    if (!button || button.disabled) return;
    add(button.parentNode.getAttribute('data-az-cart'));
  });

  P.asusCart = { html: html, add: add, setAdapter: setAdapter, refresh: refresh, connected: function () { return !!adapter; } };
}());
