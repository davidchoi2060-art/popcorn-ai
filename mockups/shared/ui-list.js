/* 표의 검색·정렬 — Phoenix `list.js` 를 붙이는 **공용 헬퍼** (슬라이스 G 후속 정리).
 *
 * 왜 공용인가: 슬라이스 G에서 열두 화면에 같은 문제(유령 List 인스턴스)를 각자 풀게 했더니
 * 해법이 두 갈래(cloneNode 파 / removeAttribute 파)로 갈라졌고, 정렬 비교 함수도 다섯 벌이
 * 됐다. 슬라이스 A가 부품 어휘에서, H가 choices 에서 겪은 그 병이다. 여기 한 곳만 고친다.
 *
 * ────────────────────────────────────────────────────────────────────
 * 이 헬퍼가 대신 처리하는 것 — 전부 **브라우저에서 실제로 겪은 것**이다
 *
 * ① 유령 인스턴스
 *    `phoenix.js` 의 `listInit` 은 docReady 때 `[data-list]` 를 훑어 List 를 만든다.
 *    우리 표는 fetch 뒤에 그리지만 **컨테이너는 마크업에 있으므로 인스턴스는 만들어지고
 *    th 에 정렬 핸들러를 건다.** 우리 것과 둘이 같은 th 를 물면
 *      · 클릭 한 번에 두 번 뒤집혀 **desc 에서 굳고**
 *      · 낡은 쪽 update() 가 tbody 를 비우며 **지워진 더미 행을 되살린다**
 *    → th 를 cloneNode 로 갈아끼워 유령의 핸들러를 떼고, `data-list` 를 지운다.
 *
 * ② 정렬 커서·화살표 CSS
 *    `theme.min.css` 에 `[data-list] .sort[data-sort], .table-list .sort[data-sort]` 짝뿐이라
 *    속성만 지우면 **어포던스가 통째로 사라진다** → `class="table-list"` 를 함께 넣는다.
 *
 * ③ 콤마 있는 금액이 거꾸로 정렬된다
 *    실측: `naturalSort("239,000원","1,299,000원")` = **+2** (239,000 이 더 크다고 판정).
 *    콤마에서 숫자 덩어리가 끊겨 앞자리만 비교하기 때문이다.
 *    → 기본 비교기가 셀에서 숫자를 뽑아 **수치로** 비교한다(뽑을 수 없으면 한국어 문자열 비교).
 *
 * ④ 다시 그리면 정렬이 풀리는데 화살표는 남는다
 *    `reIndex()` 는 행만 다시 읽고 정렬을 다시 걸지 않는다. 표는 서버 순서로 돌아오는데
 *    헤더는 '이 열로 정렬됨'이라고 **거짓말한다** — 마진 오름차순으로 놓고 승인하던 운영자가
 *    다음 맨 윗줄을 '그 다음으로 나쁜 마진'으로 믿고 엉뚱한 상품을 확정한다.
 *    → 다시 그린 뒤 걸려 있던 정렬을 되건다.
 *
 * ⑤ vendor 가 아직 없을 수 있다
 *    `vendors/list.js` 는 문서 끝에서 로드되는데 화면은 fetch 응답으로 표를 그린다.
 *    응답이 먼저 오면 `window.List` 가 없다 → 포기하지 않고 `load` 에서 한 번 더 건다.
 *    그 사이에도 표는 보인다(기능이 사라지지 않는다).
 *
 * ────────────────────────────────────────────────────────────────────
 * 쓰는 법
 *
 *   render() 끝에서:  window.popcornList.wire("prodList", VALUE_NAMES, {
 *                        numeric: ["price", "stock"],     // 수치로 비교할 열(생략 가능)
 *                        searchInput: "qBox"              // reIndex 뒤 검색어를 되걸 입력 id
 *                     });
 *
 * `valueNames` 는 list.js 규약 그대로다(문자열 또는 {name, attr} 객체).
 * `{name,attr}` 로 원단위 정수를 따로 실었다면 `numeric` 에 넣지 않아도 된다.
 */
(function (w, d) {
  'use strict';

  /** 셀 문자열에서 수를 뽑는다. 못 뽑으면 null. */
  function toNum(v) {
    if (v == null) return null;
    var s = String(v).replace(/<[^>]*>/g, ' ');          // 배지 마크업 제거
    var m = s.replace(/,/g, '').match(/-?\d+(\.\d+)?/);   // 콤마를 지운 뒤 첫 수
    return m ? parseFloat(m[0]) : null;
  }

  /** 비교용 평문 — 마크업과 앞뒤 공백을 걷어낸다. */
  function plain(v) {
    return String(v == null ? '' : v).replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
  }

  /** 양쪽이 **순수한 수**로만 이뤄져 있는가(상품코드·수량 같은 열). */
  function bothPlainNumbers(a, b) {
    return /^-?\d+(\.\d+)?$/.test(a) && /^-?\d+(\.\d+)?$/.test(b);
  }

  function cmpNum(x, y) {
    // 값이 없는 행은 **항상 꼬리로** 보낸다 — 오름/내림 어느 쪽이든 '모르는 것'이
    // 맨 위에 오면 목록을 오해한다.
    if (x === null && y === null) return 0;
    if (x === null) return 1;
    if (y === null) return -1;
    return x < y ? -1 : (x > y ? 1 : 0);
  }

  function makeSort(numeric) {
    var NUM = {};
    (numeric || []).forEach(function (k) { NUM[k] = true; });
    return function (a, b, opt) {
      var k = opt.valueName, av = a.values()[k], bv = b.values()[k];
      // ⓐ 지정된 열 — 지저분한 표기에서 수를 뽑아 비교한다("1,299,000원", 배지 마크업 등)
      if (NUM[k]) return cmpNum(toNum(av), toNum(bv));
      var pa = plain(av), pb = plain(bv);
      // ⓑ 지정하지 않았어도 **양쪽이 순수한 수면 수치로** 비교한다.
      //    list.js 기본(naturalSort)이 하던 일이라, 이게 없으면 상품코드가
      //    "1002" < "999" 로 뒤집힌다(전환 중 실제로 지적된 회귀).
      if (bothPlainNumbers(pa, pb)) return cmpNum(parseFloat(pa), parseFloat(pb));
      return pa.localeCompare(pb, 'ko');
    };
  }

  /** 지금 걸려 있는 정렬을 헤더 화살표에서 읽는다 — list.js 가 그 클래스를 단일 원천으로 쓴다. */
  function activeSort(host) {
    var els = host.querySelectorAll('.sort[data-sort]');
    for (var i = 0; i < els.length; i++) {
      if (els[i].classList.contains('asc')) return { v: els[i].getAttribute('data-sort'), o: 'asc' };
      if (els[i].classList.contains('desc')) return { v: els[i].getAttribute('data-sort'), o: 'desc' };
    }
    return null;
  }

  /** 유령 인스턴스가 걸어 둔 핸들러를 뗀다(①). 화살표 CSS 는 살린다(②). */
  function exorcise(host) {
    var ths = host.querySelectorAll('th.sort');
    for (var i = 0; i < ths.length; i++) {
      ths[i].parentNode.replaceChild(ths[i].cloneNode(true), ths[i]);
    }
    host.classList.add('table-list');
    host.removeAttribute('data-list');
  }

  /**
   * 표에 검색·정렬을 붙인다. 렌더할 때마다 불러도 된다(멱등).
   * @returns list.js 인스턴스 또는 null(vendor 미로드 등)
   */
  function wire(hostId, valueNames, opts) {
    var host = (typeof hostId === 'string') ? d.getElementById(hostId) : hostId;
    if (!host) return null;
    opts = opts || {};

    if (!w.List) {                                        // ⑤ vendor 가 아직이면 나중에 다시
      if (!host.__listPending) {
        host.__listPending = true;
        w.addEventListener('load', function () {
          host.__listPending = false;
          wire(host, valueNames, opts);
        }, { once: true });
      }
      return null;
    }

    if (!host.__list) {
      exorcise(host);
      try {
        host.__list = new w.List(host, {
          valueNames: valueNames,
          sortFunction: opts.sortFunction || makeSort(opts.numeric)
        });
      } catch (e) { host.__list = null; }
    } else {
      var s = activeSort(host);                           // ④ 정렬을 기억했다가
      try { host.__list.reIndex(); } catch (e) { /* 행이 없으면 무시 */ }
      if (s) { try { host.__list.sort(s.v, { order: s.o }); } catch (e) { /* 열이 사라졌으면 무시 */ } }
    }

    // reIndex 는 검색 상태도 지운다 — 입력창에 남은 검색어와 표가 어긋나지 않게 되건다.
    if (host.__list && opts.searchInput) {
      var q = d.getElementById(opts.searchInput);
      if (q && q.value) { try { host.__list.search(q.value); } catch (e) { /* 무시 */ } }
    }
    return host.__list;
  }

  /* ⑥ 유령을 **Phoenix 보다 먼저** 없앤다 (2026-08-05 — 브라우저에서 실제로 잡은 것)
   *
   * ①의 `exorcise` 는 `wire()` 안에서 돈다. 그런데 `wire()` 는 **fetch 응답 뒤**에
   * 불리고, `phoenix.js` 의 `listInit` 은 그보다 훨씬 앞선 docReady 에 이미
   * `[data-list]` 를 훑어 간다. 그래서 ①은 유령을 **뒤늦게** 걷어낼 뿐, 유령이
   * 태어나는 것 자체를 막지 못했다.
   *
   * 그 사이에 실제로 나던 일: 셸의 검색창(`navbar-top-search-box`)은 더미 결과를
   * 걷어낸 뒤로 항상 0건인데, list.js 는 **0건이면 예외를 던진다**
   *   "The list needs to have at least one item on init..."
   * 전 36화면에서 로드마다 uncaught 로 터지고 있었다. 지금은 아이콘·트리뷰가
   * 살아 있어 눈에 안 띄지만, 이 프로젝트는 **uncaught 예외가 뒤따르는 초기화를
   * 통째로 죽이는** 사고를 이미 겪었다(슬라이스 58 — 죽은 줄 모르고 다른 구성이
   * 장바구니에 담겼다).
   *
   * `ui-list.js` 는 `<head>`(3번째), `phoenix.js` 는 문서 끝(13번째)이라 여기서 먼저
   * 건 리스너가 **먼저** 돈다 — 유령이 태어나기 전에 표식을 뗀다.
   *
   * **행이 이미 있는 표는 건드리지 않는다** — 서버가 그려 보낸 표라면 Phoenix 가
   * 정상으로 처리하는 게 맞다. 우리 표는 전부 fetch 뒤에 그리므로 이때는 비어 있다.
   */
  function sweep() {
    var hosts = d.querySelectorAll('[data-list]');
    for (var i = 0; i < hosts.length; i++) {
      var body = hosts[i].querySelector('.list');
      if (body && body.children.length) continue;
      hosts[i].classList.add('table-list');      // ② 정렬 화살표 CSS 는 살린다
      hosts[i].removeAttribute('data-list');
    }
  }

  if (d.readyState === 'loading') {
    d.addEventListener('DOMContentLoaded', sweep);
  } else {
    sweep();                                     // 이미 늦었으면 지금이라도 (wire 가 뒤를 받는다)
  }

  w.popcornList = { wire: wire, toNum: toNum, activeSort: activeSort, sweep: sweep };
})(window, document);
