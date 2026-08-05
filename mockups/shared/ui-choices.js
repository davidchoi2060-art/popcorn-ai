/* 검색되는 셀렉트 — Phoenix `choices` 를 붙이는 **공용 헬퍼** (슬라이스 H).
 *
 * 왜 공용인가: 슬라이스 G에서 같은 문제(유령 List 인스턴스)에 열두 화면이 제각각 대응해
 * 해법이 두 갈래로 갈라졌다. 슬라이스 A가 부품 어휘에서 겪은 그 병이다. 그래서 이번에는
 * 처음부터 한 곳에 둔다 — 고칠 일이 생기면 여기만 고친다.
 *
 * ■ 왜 필요한가
 *   제조사 셀렉트는 **620개**다. 평범한 <select> 로는 찾을 수 없다.
 *   카테고리도 35개이고 계속 는다.
 *
 * ■ 계약 (2026-08-05 실측)
 *   · `choicesInit` 은 `docReady` 때 1회만 돈다 — 우리 셀렉트는 fetch 뒤에 채워지므로 안 닿는다.
 *     그래서 `window.Choices` 로 직접 붙인다(vendors/choices 로 들어와 있다).
 *   · Choices 는 원래 <select> 를 감싸고 자기 UI 를 만든다. 옵션을 다시 채우려면
 *     **감싼 것을 먼저 풀어야(destroy) 한다** — 안 풀고 innerHTML 을 갈면 UI 와 값이 어긋난다.
 *   · destroy() 는 원래 <select> 를 되돌려 준다. 그래서 순서는 항상
 *         풀기 → 옵션 채우기 → 다시 감싸기
 *     이다. 이 순서를 지키라고 `refill()` 하나로 묶어 둔다.
 *   · vendor 가 없으면 조용히 아무것도 하지 않는다(평범한 셀렉트로 남는다 — 기능은 살아 있다).
 */
(function (w) {
  'use strict';

  var DEFAULTS = {
    itemSelectText: '',
    allowHTML: true,
    shouldSort: false,           // 우리가 정한 순서(정렬 순서·트리 깊이)를 흔들지 않는다
    searchResultLimit: 30,
    searchPlaceholderValue: '검색',
    noResultsText: '결과가 없습니다',
    noChoicesText: '선택할 것이 없습니다',
    loadingText: '불러오는 중…',
    removeItemButton: false
  };

  function unwrap(el) {
    if (el && el.__choices) {
      try { el.__choices.destroy(); } catch (e) { /* 이미 풀렸으면 무시 */ }
      el.__choices = null;
    }
  }

  /** 셀렉트에 검색을 붙인다(이미 붙어 있으면 다시 붙인다).
   *
   * vendor(`choices.min.js`)는 문서 끝에서 로드되는데 화면은 fetch 응답으로 셀렉트를 채운다.
   * 응답이 vendor 보다 먼저 오면 여기서 `w.Choices` 가 아직 없다 — **실측으로 겪었다**
   * (제조사 621개가 평범한 셀렉트로 남았다). 그때는 포기하지 않고 `load` 에서 한 번 더 건다.
   * 그 사이에도 셀렉트는 평범하게 동작한다(기능이 사라지지 않는다).
   */
  function wire(id, opts) {
    var el = (typeof id === 'string') ? document.getElementById(id) : id;
    if (!el) return null;
    if (!w.Choices) {
      if (!el.__choicesPending) {
        el.__choicesPending = true;
        w.addEventListener('load', function () {
          el.__choicesPending = false;
          wire(el, opts);
        }, { once: true });
      }
      return null;
    }
    unwrap(el);
    var o = {}, k;
    for (k in DEFAULTS) { if (DEFAULTS.hasOwnProperty(k)) o[k] = DEFAULTS[k]; }
    if (opts) { for (k in opts) { if (opts.hasOwnProperty(k)) o[k] = opts[k]; } }
    try { el.__choices = new w.Choices(el, o); } catch (e) { el.__choices = null; }
    return el.__choices;
  }

  /**
   * 옵션을 다시 채운다. **이 함수를 써라** — 순서(풀기 → 채우기 → 감싸기)를 대신 지켜 준다.
   *   refill("moveTo", function(sel){ sel.innerHTML = "<option>…</option>"; }, {opts})
   * fill 콜백은 감싸지 않은 진짜 <select> 를 받는다. 이전 선택값은 살려서 되돌린다.
   */
  function refill(id, fill, opts) {
    var el = (typeof id === 'string') ? document.getElementById(id) : id;
    if (!el) return null;
    var keep = el.value;
    unwrap(el);
    if (typeof fill === 'function') fill(el);
    if (keep) {
      // 옵션이 사라졌으면 되돌리지 않는다 — 없는 값을 고른 척하지 않는다.
      for (var i = 0; i < el.options.length; i++) {
        if (el.options[i].value === keep) { el.value = keep; break; }
      }
    }
    return wire(el, opts);
  }

  w.popcornChoices = { wire: wire, refill: refill, unwrap: unwrap };
})(window);
