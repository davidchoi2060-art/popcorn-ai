/* /mvp4 「AI로 비교하기」 담기 전달 (2026-10-21 구매 1번 승인).
 *
 * AI로 PC 찾기 화면 밖(AI 슈퍼컴퓨터 상세·업무별 PC 칸)에서 누른 「AI로 비교하기」를 AI로 PC 찾기의 관심·비교상품으로 넘긴다.
 * 넘기는 것은 상품 종류와 상품번호뿐이다(이름·가격은 받는 쪽이 서버에서 다시 읽는다 — 이름·배열로 상품을 정하지 않는다).
 * 열려 있는 AI로 PC 찾기 화면은 바로 받고(storage 이벤트), 없으면 다음에 열 때 받는다. 30분이 지난 것은 버린다.
 * 대화·입력 중인 문장·추천 조건은 이 전달이 건드리지 않는다. 질문을 보내거나 AI를 부르지 않는다.
 */
(function () {
  'use strict';
  var P = window.PAI = window.PAI || {};
  var KEY = 'pai-compare-carry-v1', TTL = 30 * 60 * 1000, KINDS = { pc: 1, ai_device: 1 };
  function read() {
    try {
      var raw = JSON.parse(window.localStorage.getItem(KEY) || '[]'), now = Date.now();
      return (Array.isArray(raw) ? raw : []).filter(function (x) { return x && KINDS[x.kind] && /^\d{1,18}$/.test(String(x.id)) && typeof x.at === 'number' && now - x.at < TTL; });
    } catch (e) { return []; }
  }
  function write(list) { try { if (list.length) window.localStorage.setItem(KEY, JSON.stringify(list)); else window.localStorage.removeItem(KEY); return true; } catch (e) { return false; } }
  P.compareCarry = {
    // 같은 상품이 이미 기다리고 있으면 다시 넣지 않는다. 저장소를 못 쓰면 false — 화면이 그 사실을 알린다.
    add: function (kind, id) {
      if (!KINDS[kind] || !/^\d{1,18}$/.test(String(id))) return false;
      var list = read().filter(function (x) { return !(x.kind === kind && String(x.id) === String(id)); });
      list.push({ kind: kind, id: String(id), at: Date.now() });
      return write(list.slice(-6));
    },
    take: function () { var list = read(); write([]); return list; },
    listen: function (cb) { window.addEventListener('storage', function (e) { if (e.key === KEY && e.newValue) cb(P.compareCarry.take()); }); }
  };
}());
