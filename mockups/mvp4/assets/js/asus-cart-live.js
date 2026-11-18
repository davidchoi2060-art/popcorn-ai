/* ASUS 기획전 장바구니 — 서버 연결 (2026-11-18). asus-cart.js 의 setAdapter 계약으로 두 경로를 잇는다.
 *   GET  /api/customer/asus-cart/status   {enabled, models:{id:{available, reason}}, origins, notice, notice_separate}
 *   POST /api/customer/asus-cart/add      {modelId, quantity: 1} -> {ok: true, url, notice, ...} | {ok: false, code}
 * status 가 꺼져 있거나(404 포함) 실패하면 setAdapter 를 부르지 않는다 — 버튼은 지금처럼 비활성 + 준비 중 안내로 남는다.
 * 켜져 있어도 available 이 아닌 모델은 비활성이다. 성공하면 서버가 준 안내 문구를 보이고 주소를 새 창으로 연다.
 * 판매처 주소는 이 파일에 없다. status 의 origins(정규 https 출처)만 믿고, 그 밖의 주소로는 가지 않는다(asus-cart.js 가 거른다). */
(function () {
  'use strict';
  var P = window.PAI;
  if (!P || !P.asusCart) return;
  var STATUS = '/api/customer/asus-cart/status';
  var ADD = '/api/customer/asus-cart/add';
  var TIMEOUT_MS = 15000;

  function headers(extra) {
    var h = { Accept: 'application/json', 'X-Popcorn-Surface': 'mvp4' };
    if (extra) for (var k in extra) if (Object.prototype.hasOwnProperty.call(extra, k)) h[k] = extra[k];
    return h;
  }

  // 같은 출처로만 보낸다. 응답은 {status, body(JSON 또는 null)} 로 정리하고, 시간 초과는 실패다.
  function request(url, options) {
    var ctrl = new AbortController();
    var timer = setTimeout(function () { ctrl.abort(); }, TIMEOUT_MS);
    options.signal = ctrl.signal;
    options.credentials = 'same-origin';
    options.cache = 'no-store';
    return fetch(url, options).then(function (r) {
      return r.json().catch(function () { return null; }).then(function (d) {
        clearTimeout(timer);
        return { status: r.status, body: d };
      });
    }, function (e) { clearTimeout(timer); throw e; });
  }

  // 실패 사유 코드. 서버의 {ok:false, code} · FastAPI 의 {detail:{error}} · 그 밖은 http_<상태>.
  function codeOf(res) {
    var d = res.body;
    if (d && typeof d.code === 'string') return d.code;
    if (d && d.detail && typeof d.detail.error === 'string') return d.detail.error;
    return 'http_' + res.status;
  }

  function available(models, id) {
    return !!(models && Object.prototype.hasOwnProperty.call(models, id) && models[id] && models[id].available === true);
  }

  function connect(status) {
    if (!status || status.enabled !== true || !status.models || !Array.isArray(status.origins)) return false;
    var models = status.models;
    var anyOn = Object.keys(models).some(function (id) { return available(models, id); });
    if (!anyOn) return false;
    P.asusCart.setAdapter({
      origins: status.origins,
      newWindow: true,
      available: function (id) { return available(models, id); },
      add: function (req) {
        var body = JSON.stringify({ modelId: req.modelId, quantity: req.quantity });
        return request(ADD, { method: 'POST', headers: headers({ 'Content-Type': 'application/json' }), body: body }).then(function (res) {
          var d = res.body;
          if (res.status === 200 && d && d.ok === true && typeof d.url === 'string') {
            var notice = typeof d.notice === 'string' ? d.notice : '';
            if (typeof d.notice_separate === 'string' && d.notice_separate) notice += (notice ? ' ' : '') + d.notice_separate;
            return { ok: true, url: d.url, notice: notice };
          }
          return { ok: false, code: codeOf(res) };
        });
      }
    });
    return true;
  }

  function start() {
    return request(STATUS, { method: 'GET', headers: headers() }).then(function (res) {
      if (res.status !== 200) return false;
      try { return connect(res.body); } catch (e) { return false; }   // origins 가 정규 https 출처가 아니면 연결하지 않는다
    }, function () { return false; });
  }

  P.asusCartLive = { connect: connect, start: start, codeOf: codeOf };
  start();
}());
