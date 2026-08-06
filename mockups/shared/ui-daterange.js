/* 기간 필터 — **공용 헬퍼** (2026-08-05).
 *
 * 왜 필요했나: 주문·가격 이력·활동 기록·결제에 기간으로 거를 방법이 **화면에도 서버에도
 * 아예 없었다**(실측: `type="date"` 0건, 서버 파라미터 0건). 운영자가 "지난주 주문"을
 * 볼 수 없었다. 도매꾹 상품공급사센터는 이걸 기본으로 갖고 있다
 * (`docs/research/domeggook-sc-2026-08-05.md`).
 *
 * ■ 화면은 **서울 날짜만** 보낸다
 *   UTC 경계로 바꾸는 일은 서버의 `timeutil.kst_day_range` 하나가 한다.
 *   화면이 시간대를 계산하기 시작하면 **9시간 함정이 화면 수만큼** 생긴다 —
 *   슬라이스 100에서 표기로 이미 한 번 겪었고, 이번엔 조회 조건이라 더 조용하다.
 *
 * ■ 왜 URL 에 싣고 새로 그리나
 *   화면마다 데이터를 불러오는 구조가 다르다(`load()` 가 있는 곳, fetch 를 바로 부르는 곳,
 *   상품을 골라야 도는 곳). 공통 진입점이 없으므로 **URL 을 단일 상태**로 삼는다.
 *   덤으로 기간이 붙은 화면을 그대로 북마크·공유할 수 있다.
 *
 * ■ 쓰는 법
 *   ① 화면 마크업에 `<div data-daterange>` 바를 둔다(아래 `render()` 가 채운다)
 *   ② fetch 할 때 `window.popcornDate.qs()` 를 붙인다 — **이 한 줄이 전부다**
 *        fetch("/api/admin/orders" + popcornDate.qs("?"))
 */
(function (w, d) {
  'use strict';

  var KEYS = ['date_from', 'date_to'];

  function params() {
    var out = {}, sp = new URLSearchParams(w.location.search);
    KEYS.forEach(function (k) { if (sp.get(k)) out[k] = sp.get(k); });
    return out;
  }

  /** 현재 기간을 질의 문자열로. 없으면 빈 문자열 — 붙여도 URL 이 지저분해지지 않는다. */
  function qs(prefix) {
    var p = params(), parts = [];
    KEYS.forEach(function (k) { if (p[k]) parts.push(k + '=' + encodeURIComponent(p[k])); });
    if (!parts.length) return '';
    return (prefix || '') + parts.join('&');
  }

  function pad(n) { return String(n).padStart(2, '0'); }
  function str(dt) { return dt.getFullYear() + '-' + pad(dt.getMonth() + 1) + '-' + pad(dt.getDate()); }

  /** 빠른 선택 — 도매꾹이 기본으로 주는 것(금일·금주·금월·전월). */
  function quick(kind) {
    var now = new Date(), a = new Date(now), b = new Date(now);
    if (kind === 'week') { a.setDate(now.getDate() - now.getDay()); }        // 일요일 시작
    else if (kind === 'month') { a.setDate(1); }
    else if (kind === 'prevmonth') {
      a = new Date(now.getFullYear(), now.getMonth() - 1, 1);
      b = new Date(now.getFullYear(), now.getMonth(), 0);                    // 전월 말일
    }
    return [str(a), str(b)];
  }

  function apply(from, to) {
    var sp = new URLSearchParams(w.location.search);
    KEYS.forEach(function (k) { sp.delete(k); });
    if (from) sp.set('date_from', from);
    if (to) sp.set('date_to', to);
    var q = sp.toString();
    w.location.search = q ? '?' + q : '';
  }

  var HTML =
    '<span class="fs-10 text-body-tertiary">기간</span>' +
    '<input type="date" class="form-control form-control-sm" id="dtFrom" style="width:9.5rem;" aria-label="시작일">' +
    '<span class="fs-10 text-body-tertiary">~</span>' +
    '<input type="date" class="form-control form-control-sm" id="dtTo" style="width:9.5rem;" aria-label="종료일">' +
    '<div class="btn-group btn-group-sm" role="group" aria-label="빠른 선택">' +
      '<button class="btn btn-phoenix-secondary" type="button" data-quick="today">금일</button>' +
      '<button class="btn btn-phoenix-secondary" type="button" data-quick="week">금주</button>' +
      '<button class="btn btn-phoenix-secondary" type="button" data-quick="month">금월</button>' +
      '<button class="btn btn-phoenix-secondary" type="button" data-quick="prevmonth">전월</button>' +
    '</div>' +
    '<button class="btn btn-primary btn-sm" type="button" id="dtApply">조회</button>' +
    '<button class="btn btn-link btn-sm p-0 ms-1 fs-9" type="button" id="dtClear" hidden>기간 해제</button>' +
    '<span class="fs-10 text-body-tertiary" id="dtNote"></span>';

  function render() {
    var host = d.querySelector('[data-daterange]');
    if (!host || host.__done) return;
    host.__done = true;
    host.className = 'd-flex flex-wrap align-items-center gap-2 mt-2';
    host.innerHTML = HTML;

    var p = params();
    if (p.date_from) d.getElementById('dtFrom').value = p.date_from;
    if (p.date_to) d.getElementById('dtTo').value = p.date_to;
    // **지금 기간이 걸려 있다는 사실을 화면이 말한다** — 목록이 적은 이유를 모르면
    // 운영자는 데이터가 없어졌다고 읽는다.
    if (p.date_from || p.date_to) {
      d.getElementById('dtClear').hidden = false;
      d.getElementById('dtNote').textContent =
        '이 기간만 보고 있습니다 (' + (p.date_from || '처음') + ' ~ ' + (p.date_to || '지금') + ')';
    }

    host.addEventListener('click', function (ev) {
      var q = ev.target.closest('[data-quick]');
      if (q) { ev.preventDefault(); var r = quick(q.getAttribute('data-quick')); apply(r[0], r[1]); return; }
      if (ev.target.closest('#dtApply')) {
        ev.preventDefault();
        apply(d.getElementById('dtFrom').value, d.getElementById('dtTo').value);
        return;
      }
      if (ev.target.closest('#dtClear')) { ev.preventDefault(); apply('', ''); }
    });
  }

  if (d.readyState === 'loading') d.addEventListener('DOMContentLoaded', render);
  else render();

  w.popcornDate = { qs: qs, params: params, render: render };
})(window, document);
