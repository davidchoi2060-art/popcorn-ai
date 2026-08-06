/* ui-chart.js — echarts 공용 배선 (단일 원천)
 *
 * 왜 헬퍼인가: 대시보드 한 화면에만 있던 차트 배선을 다른 화면에 복제하면
 * 이 프로젝트가 가장 자주 걸리는 병(같은 것을 두 벌 두기)이 또 시작된다.
 * 좌측 메뉴·토큰·부품 어휘·마진 상속에서 넷 다 이미 갈라진 뒤에 고쳤다.
 *
 * 이 파일이 책임지는 것 — 화면은 **옵션만** 만든다:
 *   ① vendor 가 아직 없을 때  echarts.min.js 는 vendor 12개 중 하나라 fetch 가 먼저
 *      끝날 수 있다. 그때 그냥 반환하면 화면은 '실데이터'라 말하면서 차트만 빈 채로
 *      남는다 — 죽은 줄 모르는 화면이 가장 나쁘다. 옵션을 들고 있다가 load 뒤 다시 그린다.
 *   ② phoenix 의 basicEchartsInit 회피  그것은 `data-echarts` 를 훑어 **2022년 날짜가
 *      박힌 데모 기본값**을 씌운다. 우리 컨테이너에는 그 속성을 절대 쓰지 않고
 *      echarts.init 을 직접 부른다.
 *   ③ 값이 없으면 그리지 않고 그렇게 말한다  화면 정직성(슬라이스 47·48). 빈 차트는
 *      '0'처럼 보이지만 '모른다'와 '0'은 다르다.
 *   ④ 창 크기 변경  인스턴스를 모아 한 번만 등록한다.
 */
(function () {
  "use strict";

  var PENDING = {};      // id -> {build, empty}  아직 못 그린 것
  var IDS = {};          // 리사이즈 대상
  var BOUND = false;

  function utils() {
    return (window.phoenix && window.phoenix.utils) || {};
  }

  /* 테마 색은 phoenix 가 CSS 변수에서 읽어 준다. 없으면 폴백 —
     여기에 HEX 를 새로 정하지 않는다(토큰이 단일 원천). */
  function color(name, fallback) {
    try {
      var u = utils();
      return u.getColor ? (u.getColor(name) || fallback) : fallback;
    } catch (e) {
      return fallback;
    }
  }

  function tooltip(extra) {
    var t = {
      backgroundColor: color("body-highlight-bg", "#fff"),
      borderColor: color("border-color", "#ddd"),
      borderWidth: 1,
      textStyle: { color: color("light-text-emphasis", "#333") },
      padding: [7, 10]
    };
    if (extra) for (var k in extra) if (extra.hasOwnProperty(k)) t[k] = extra[k];
    return t;
  }

  function num(v) {
    return (v == null) ? "—" : Number(v).toLocaleString("ko-KR");
  }

  function note(id, text) {
    var el = document.getElementById(id + "Note");
    if (el) el.textContent = text;
  }

  /* 원천이 없을 때 — 빈 캔버스를 두지 않고 한 줄로 말한다. */
  function sayEmpty(el, text) {
    var c = window.echarts && window.echarts.getInstanceByDom(el);
    if (c) c.dispose();
    el.innerHTML = "";
    var p = document.createElement("p");
    p.className = "text-body-tertiary fs-9 mb-0 d-flex align-items-center " +
                  "justify-content-center h-100 text-center";
    p.textContent = text;
    el.appendChild(p);
  }

  function bindResize() {
    if (BOUND) return;
    BOUND = true;
    window.addEventListener("resize", function () {
      Object.keys(IDS).forEach(function (id) {
        var el = document.getElementById(id);
        var c = el && window.echarts && window.echarts.getInstanceByDom(el);
        if (c) c.resize();
      });
    });
  }

  /* 컨테이너가 **숨겨진 채로** init 되면 너비 0으로 굳는다.
   * 그러면 캔버스는 만들어졌는데 화면은 빈 카드다 — '죽은 줄 모르는 화면'의 전형이다.
   * (reprice 에서 실제로 겪었다: 미리보기 결과 블록이 보이기 전에 그렸다.)
   * 창 resize 리스너로는 못 잡는다 — 창은 그대로고 요소만 커지기 때문이다.
   */
  function watchSize(el, inst) {
    if (!window.ResizeObserver || el.__pcObserved) return;
    el.__pcObserved = true;
    var ro = new ResizeObserver(function () {
      if (el.clientWidth > 0) inst.resize();
    });
    ro.observe(el);
  }

  /* draw(id, build, emptyText, onReady)
   *   build : function(C, TIP, num) -> echarts option  |  null 이면 '값 없음'
   *           함수로 받는 이유 — vendor 가 늦게 오면 **색을 다시 읽어야** 한다.
   *   emptyText : 값이 없을 때 그 자리에 적을 말. 원천이 없다는 사실을 그대로 쓴다.
   *   onReady : function(instance) — 클릭 배선처럼 인스턴스가 있어야 하는 것.
   *           **여기서 해야 한다.** draw 가 대기열에 넣고 null 을 돌려준 뒤
   *           호출부에서 getInstanceByDom 을 부르면 그때는 아직 없어서, 나중에
   *           차트는 그려지는데 클릭만 안 먹는 화면이 된다.
   */
  function draw(id, build, emptyText, onReady) {
    var el = document.getElementById(id);
    if (!el) return null;

    if (!window.echarts) {          // vendor 가 아직 — 들고 있다가 load 뒤 다시
      PENDING[id] = { build: build, empty: emptyText, ready: onReady };
      return null;
    }
    delete PENDING[id];

    var option;
    try {
      option = build(color, tooltip, num);
    } catch (e) {
      option = null;
      if (window.console) console.error("[ui-chart] " + id, e);
    }
    if (!option) {
      sayEmpty(el, emptyText || "표시할 값이 없습니다");
      return null;
    }

    var c = window.echarts.getInstanceByDom(el);
    if (!c) {
      // 컨테이너에 '불러오는 중…' 같은 자리표시자가 있으면 캔버스 **아래에 그대로 남는다**.
      // echarts 는 자기 캔버스만 붙일 뿐 남의 자식을 치우지 않는다.
      el.innerHTML = "";
      c = window.echarts.init(el);
    }
    c.setOption(option, true);      // true = 이전 옵션을 병합하지 않는다(잔상 방지)
    IDS[id] = true;
    bindResize();
    watchSize(el, c);
    if (el.clientWidth === 0) c.resize();   // 이미 보이게 됐다면 즉시 한 번
    if (onReady) {
      try {
        onReady(c);
      } catch (e2) {
        if (window.console) console.error("[ui-chart] onReady " + id, e2);
      }
    }
    return c;
  }

  function flush() {
    Object.keys(PENDING).forEach(function (id) {
      var p = PENDING[id];
      draw(id, p.build, p.empty, p.ready);
    });
  }

  // vendor 가 늦게 오는 경우의 유일한 구제 지점.
  window.addEventListener("load", flush);

  window.popcornChart = {
    draw: draw,
    color: color,
    tooltip: tooltip,
    num: num,
    note: note,
    flush: flush
  };
})();
