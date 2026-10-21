/* /mvp4 내 견적 서버 요청 — 화면 공용 (2026-10-21 구매 1번 승인 · live-checkout.js 에서 옮김).
 *
 * 내 견적(GET) · 보관(POST) · 개별 삭제(DELETE, 실제로는 내 목록에서 숨김) · 되돌리기(POST …/restore)를 한곳에서 부른다.
 * 이 브라우저의 견적 접근 키는 mvp3 와 같은 키다(같은 브라우저의 내 견적이 한 목록이 된다).
 * 실패는 그대로 던진다 — 화면이 성공처럼 보이지 않게 한다.
 */
(function () {
  'use strict';
  var P = window.PAI;
  if (!P) return;
  var KEY = 'popcorn-mvp3-guest-access-v1', KEY_RE = /^[A-Za-z0-9_-]{32,128}$/;
  function accessKey() {
    try {
      var k = window.localStorage.getItem(KEY);
      if (k && KEY_RE.test(k)) return k;
      var b = new Uint8Array(32); window.crypto.getRandomValues(b);
      k = Array.from(b, function (x) { return x.toString(16).padStart(2, '0'); }).join('');
      window.localStorage.setItem(KEY, k);
      return window.localStorage.getItem(KEY) === k ? k : null;
    } catch (e) { return null; }
  }
  function err(kind, status, message, detail) { var e = new Error(message || kind); e.kind = kind; e.status = status; e.detail = detail; e.sentence = message; return e; }
  function call(method, path, body, withKey) {
    var headers = { Accept: 'application/json', 'X-Popcorn-Surface': 'mvp4' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (withKey) { var k = accessKey(); if (!k) return Promise.reject(err('storage', 0, '이 브라우저에 견적 보관 키를 저장할 수 없어요. 브라우저 설정을 확인해 주세요.')); headers['X-Access-Key'] = k; }
    var ctrl = new AbortController(), timer = setTimeout(function () { ctrl.abort(); }, 30000);
    return fetch(path, { method: method, credentials: 'same-origin', cache: 'no-store', headers: headers, body: body === undefined ? undefined : JSON.stringify(body), signal: ctrl.signal })
      .then(function (r) {
        clearTimeout(timer);
        return r.json().catch(function () { return null; }).then(function (data) {
          if (r.ok && data && data.ok === true) return data;
          var d = data && data.detail, sentence = typeof d === 'string' ? d : d && typeof d.detail === 'string' ? d.detail : '';
          var code = d && typeof d === 'object' && typeof d.error === 'string' ? d.error : '';
          throw err(r.status >= 500 ? 'unknown' : code || 'http', r.status, sentence, d);
        });
      }, function () { clearTimeout(timer); throw err('unknown', 0, ''); });
  }
  function uuid() { if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID(); var b = new Uint8Array(16); window.crypto.getRandomValues(b); b[6] = b[6] & 15 | 64; b[8] = b[8] & 63 | 128; var x = Array.from(b, function (v) { return v.toString(16).padStart(2, '0'); }).join(''); return x.slice(0, 8) + '-' + x.slice(8, 12) + '-' + x.slice(12, 16) + '-' + x.slice(16, 20) + '-' + x.slice(20); }
  function message(e, fallback) {
    if (e.status === 429) return '요청이 잠시 많아요. 잠시 후 다시 시도해 주세요.';
    if (e.status === 403) return '이 브라우저의 견적 보관 기록에 접근할 수 없어요. 견적을 보관했던 브라우저에서 확인해 주세요.';
    if (e.sentence && e.sentence.length <= 200) return e.sentence;
    return fallback;
  }
  function id(q) { return encodeURIComponent(String(q)); }
  P.savedQuotes = {
    call: call, err: err, uuid: uuid, message: message,
    list: function () { return call('GET', '/api/mvp3/saved-quotes?limit=20', undefined, true); },
    // AI 슈퍼컴퓨터 보관 — 같은 요청 번호(request_id)로 다시 보내면 서버가 같은 결과를 돌려준다(중복 저장 없음).
    // 서버가 방문자 연결을 먼저 요구하므로 목록 조회(GET)를 앞에 둔다.
    saveDevice: function (body) { return call('GET', '/api/mvp3/saved-quotes?limit=1', undefined, true).then(function () { return call('POST', '/api/mvp3/saved-quotes', body, true); }); },
    remove: function (q) { return call('DELETE', '/api/mvp3/saved-quotes/' + id(q), undefined, true); },
    restore: function (q) { return call('POST', '/api/mvp3/saved-quotes/' + id(q) + '/restore', undefined, true); }
  };
}());
