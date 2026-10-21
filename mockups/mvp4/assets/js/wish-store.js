/* /mvp4 찜목록 저장소 (2026-10-21 대표 확정 「찜하기·찜목록」).
 *
 * 추천·AI 답변 카드·PC 쇼핑 카드·상품 상세·AI 장비, 모든 진입점이 이 목록 하나를 쓴다. 「비교함」을 따로 두지 않는다.
 * 고객 로그인 저장소가 없으므로 이 브라우저의 localStorage 에 오래 둔다(30분 전달·sessionStorage 가 아니다).
 * 다른 기기와 맞춰지지 않는다 — 화면은 「이 브라우저에만 저장」이라고만 말한다.
 * 담는 것은 상품 종류와 상품번호뿐이다(이름·가격은 화면이 서버에서 다시 읽는다).
 * 찜 수에는 상한이 없다. 한 번에 비교하는 수(최대 3)는 이 모듈이 아니라 비교 화면이 정한다.
 * 저장하지 못하면 성공인 척하지 않는다 — 모든 쓰기는 { ok, reason } 을 돌려준다.
 * 같은 탭은 'pai-wish-change' 이벤트, 다른 탭은 storage 이벤트로 바뀐 목록을 받는다.
 * 선택·추천된 상품을 저절로 찜하지 않는다. 이 모듈은 질문을 보내거나 AI·서버를 부르지 않는다.
 */
(function () {
  'use strict';
  var P = window.PAI = window.PAI || {};
  var KEY = 'pai-wish-v1', MIGRATED = 'pai-wish-migrated-v1', EVENT = 'pai-wish-change';
  var CARRY = 'pai-compare-carry-v1', CHAT = 'pai-finder-chat-v1', KINDS = { pc: 1, ai_device: 1 };

  function valid(kind, id) { return !!KINDS[kind] && /^\d{1,18}$/.test(String(id)); }
  function clean(raw) {
    var seen = {};
    return (Array.isArray(raw) ? raw : []).filter(function (x) {
      if (!x || !valid(x.kind, x.id) || typeof x.at !== 'number') return false;
      var k = x.kind + ':' + x.id; if (seen[k]) return false; seen[k] = 1; return true;
    }).map(function (x) { return { kind: x.kind, id: String(x.id), at: x.at }; });
  }
  function storage() { try { return window.localStorage; } catch (e) { return null; } }
  function read() { var s = storage(); if (!s) return []; try { return clean(JSON.parse(s.getItem(KEY) || '[]')); } catch (e) { return []; } }
  function write(list) {
    var s = storage(); if (!s) return { ok: false, reason: 'storage' };
    try { if (list.length) s.setItem(KEY, JSON.stringify(list)); else s.removeItem(KEY); }
    catch (e) { return { ok: false, reason: 'storage' }; }
    // 써 놓고 다시 읽어 맞는지 본다 — 조용히 버려진 쓰기를 성공으로 말하지 않는다.
    if (read().length !== list.length) return { ok: false, reason: 'storage' };
    try { window.dispatchEvent(new CustomEvent(EVENT, { detail: { list: list.slice() } })); } catch (e) { /* 알림만 못 함 */ }
    return { ok: true, count: list.length };
  }
  function index(list, kind, id) { for (var i = 0; i < list.length; i++) if (list[i].kind === kind && list[i].id === String(id)) return i; return -1; }

  P.wishlist = {
    KEY: KEY, EVENT: EVENT,
    available: function () { var s = storage(); if (!s) return false; try { s.setItem(KEY + '-probe', '1'); s.removeItem(KEY + '-probe'); return true; } catch (e) { return false; } },
    list: function () { return read().sort(function (a, b) { return b.at - a.at; }); },
    count: function () { return read().length; },
    has: function (kind, id) { return valid(kind, id) && index(read(), kind, id) >= 0; },
    // 이미 찜한 상품이면 다시 넣지 않고 ok(already) 로 답한다.
    add: function (kind, id) {
      if (!valid(kind, id)) return { ok: false, reason: 'invalid' };
      var list = read(); if (index(list, kind, id) >= 0) return { ok: true, already: true, count: list.length };
      list.push({ kind: kind, id: String(id), at: Date.now() }); return write(list);
    },
    remove: function (kind, id) {
      if (!valid(kind, id)) return { ok: false, reason: 'invalid' };
      var list = read(), i = index(list, kind, id); if (i < 0) return { ok: true, already: true, count: list.length };
      list.splice(i, 1); return write(list);
    },
    toggle: function (kind, id) {
      var on = !P.wishlist.has(kind, id), r = on ? P.wishlist.add(kind, id) : P.wishlist.remove(kind, id);
      r.wished = r.ok ? on : !on; return r;
    },
    // 같은 탭·다른 탭 어디서 바뀌든 cb(목록) 을 부른다. 되돌림 함수를 준다.
    onChange: function (cb) {
      function local(e) { cb(e.detail && e.detail.list ? e.detail.list.slice() : P.wishlist.list()); }
      function other(e) { if (e.key === KEY || e.key === null) cb(P.wishlist.list()); }
      window.addEventListener(EVENT, local); window.addEventListener('storage', other);
      return function () { window.removeEventListener(EVENT, local); window.removeEventListener('storage', other); };
    },
    // 기존 「비교」에 실제로 담겨 있던 것(30분 전달 대기분 · AI로 PC 찾기 화면의 비교 목록)을 한 번만 찜으로 옮긴다.
    // 선택한 PC·추천 목록은 옮기지 않는다. 한 번 옮긴 뒤에는 다시 하지 않는다 — 고객이 뺀 것을 되살리지 않기 위해서다.
    migrate: function () {
      var s = storage(); if (!s) return { ok: false, reason: 'storage', moved: 0 };
      try { if (s.getItem(MIGRATED)) return { ok: true, already: true, moved: 0 }; } catch (e) { return { ok: false, reason: 'storage', moved: 0 }; }
      var found = [], now = Date.now();
      try { found = found.concat((JSON.parse(s.getItem(CARRY) || '[]') || []).filter(function (x) { return x && now - x.at < 30 * 60 * 1000; })); } catch (e) { /* 깨진 값은 건너뛴다 */ }
      try { var snap = JSON.parse(window.sessionStorage.getItem(CHAT) || 'null'); if (snap && Array.isArray(snap.compare)) found = found.concat(snap.compare.map(function (c) { return { kind: c.kind === 'ai_device' ? 'ai_device' : 'pc', id: c.id }; })); } catch (e) { /* 같다 */ }
      var list = read(), moved = 0;
      found.forEach(function (x) { if (valid(x.kind, x.id) && index(list, x.kind, x.id) < 0) { list.push({ kind: x.kind, id: String(x.id), at: now + moved }); moved++; } });
      var r = moved ? write(list) : { ok: true };
      if (!r.ok) return { ok: false, reason: r.reason, moved: 0 };
      try { s.setItem(MIGRATED, String(now)); } catch (e) { /* 다음에 다시 시도해도 중복은 생기지 않는다 */ }
      return { ok: true, moved: moved };
    }
  };
}());
