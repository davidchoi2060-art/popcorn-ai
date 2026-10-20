/* /mvp4 AI 슈퍼컴퓨터 카테고리 목록 (2026-10-20 대표 승인 「제품 계속 추가될 거니까 카테고리를 만들어 놓는 게 중요해」).
 *
 * - 상품은 상품 데이터의 카테고리 분류('ai-supercomputer')로 조회한다(live-supercomputer.js). 상품번호를 여기 적지 않는다.
 * - 카드: 사진·이름·핵심 사양(가속기/프로세서·메모리·저장장치·OS)·가격 또는 견적 안내·판매 상태. 값이 없으면 «확인 필요».
 * - 필터는 실제 데이터에 두 가지 이상 값이 있는 항목(제조사·메모리·저장장치·가격대)만 보인다. 정렬: 추천순·낮은 가격순·높은 가격순.
 * - 필터·정렬은 주소(?maker=&memory=&storage=&price=&sort=)에, «더 보기» 수와 스크롤 위치는 이 탭의 sessionStorage 에 둔다
 *   — 상세에서 돌아오면 그대로 되살린다. 상세의 «목록으로»도 이 주소를 쓴다.
 * - 상태: 불러오는 중 · 조회 실패(다시 시도) · 카테고리에 상품 없음 · 필터 결과 없음(조건 지우기).
 */
(function () {
  'use strict';
  var P = window.PAI, h = P.h, icon = P.icon, D = P.aiDevices;
  var app = document.getElementById('app'), PAGE = 12, KEY_URL = 'pai-sc-list-url', KEY_VIEW = 'pai-sc-list-view';
  var FILTERS = [['maker', '제조사'], ['memory', '메모리'], ['storage', '저장장치'], ['price', '가격대']];
  // 기본 정렬 = 낮은 가격순(2026-10-20 대표 확정, 가격 확인 필요는 뒤로). 손님이 고른 정렬은 주소(?sort=)에 남아 그대로 지킨다.
  var SORTS = [['price-asc', '낮은 가격순'], ['price-desc', '높은 가격순'], ['featured', '추천순']], DEFAULT_SORT = 'price-asc';
  var BANDS = [['~10000000', '1,000만 원 이하', 0, 10000000], ['10000000~20000000', '1,000만~2,000만 원', 10000001, 20000000], ['20000000~', '2,000만 원 초과', 20000001, Infinity]];
  var state = 'loading', items = [], shown = PAGE, query = new URLSearchParams(location.search);
  // R03(2026-10-20): 필터를 직접 접거나 펼쳤으면 그 상태를 지킨다(다시 그려도·상세에서 돌아와도). null = 아직 손대지 않음(기본 규칙).
  var filterOpen = null;
  // 복원은 이 화면이 직접 한다(브라우저 자동 스크롤 복원이 뒤늦게 덮지 않게).
  try { if ('scrollRestoration' in history) history.scrollRestoration = 'manual'; } catch (e) { /* 무시 */ }
  function store(k, v) { try { if (v === undefined) return sessionStorage.getItem(k); sessionStorage.setItem(k, v); } catch (e) { return null; } return null; }
  function band(p) { if (p.saleState !== 'on_sale' || !p.price) return null; var b = BANDS.find(function (x) { return p.price >= x[2] && p.price <= x[3]; }); return b ? b[0] : null; }
  function valueOf(p, key) { return key === 'price' ? band(p) : p[key]; }
  function options(key) {
    var seen = [];
    items.forEach(function (p) { var v = valueOf(p, key); if (v && seen.indexOf(v) < 0) seen.push(v); });
    if (key === 'price') return BANDS.filter(function (b) { return seen.indexOf(b[0]) >= 0; }).map(function (b) { return [b[0], b[1]]; });
    return seen.sort(function (a, b) { return a.localeCompare(b, 'ko', { numeric: true }); }).map(function (v) { return [v, v]; });
  }
  function active() { var a = {}; FILTERS.forEach(function (f) { var v = query.get(f[0]); if (v) a[f[0]] = v; }); return a; }
  function sort() { var s = query.get('sort'); return SORTS.some(function (x) { return x[0] === s; }) ? s : DEFAULT_SORT; }
  function visible() {
    var a = active(), list = items.filter(function (p) { return Object.keys(a).every(function (k) { return valueOf(p, k) === a[k]; }); });
    var s = sort();
    if (s !== 'featured') list = list.slice().sort(function (x, y) {
      var px = x.saleState === 'on_sale' ? x.price : null, py = y.saleState === 'on_sale' ? y.price : null;
      if (px === null && py === null) return 0; if (px === null) return 1; if (py === null) return -1;   // 가격 없는 상품은 뒤로
      return s === 'price-asc' ? px - py : py - px;
    });
    return list;
  }
  function priceText(p) { return p.saleState === 'stopped' ? '판매 중지' : p.saleState === 'on_sale' && p.price ? P.money(p.price) : '가격 확인 필요'; }
  function badge(p) { return p.saleState === 'on_sale' ? '' : '<span class="scl-badge ' + (p.saleState === 'stopped' ? 'is-stopped' : 'is-check') + '">' + (p.saleState === 'stopped' ? '판매 중지' : '판매 확인 필요') + '</span>'; }
  function card(p) {
    var specs = D.specs(p);
    return '<li class="scl-card"><a href="supercomputer.html?id=' + h(p.id) + '" data-scl-item="' + h(p.id) + '"><div class="scl-photo">' + (p.image ? '<img src="' + h(p.image) + '" alt="" loading="lazy" width="320" height="240" data-scl-img>' : '<span class="scl-photo-none">' + icon('package') + '사진 준비 중</span>') + badge(p) + '</div>' +
      '<div class="scl-body"><p class="scl-maker">' + h(p.maker || '제조사 확인 필요') + (p.modelLabel && p.modelGroup ? ' · ' + h(p.modelLabel) + ' 모델' : '') + '</p><h2>' + h(p.name) + '</h2>' +
      '<dl class="scl-specs">' + specs.map(function (s) { return '<div><dt>' + h(s[1]) + '</dt><dd' + (s[2] ? '' : ' class="is-missing"') + '>' + h(s[2] || '확인 필요') + '</dd></div>'; }).join('') + '</dl>' + (P.llmExamples ? P.llmExamples.badges(p) : '') +
      '<div class="scl-foot"><strong class="' + (p.saleState === 'on_sale' ? '' : 'is-quiet') + '">' + h(priceText(p)) + '</strong><span class="scl-go">자세히 보기 ' + icon('arrow-right') + '</span></div><p class="scl-id">상품번호 ' + h(p.id) + '</p></div></a></li>';
  }
  function filtersHtml() {
    var a = active(), groups = FILTERS.map(function (f) { var o = options(f[0]); return o.length >= 2 || a[f[0]] ? [f, o] : null; }).filter(Boolean);
    var sortHtml = '<label class="scl-sort"><span>정렬</span><select data-scl-sort>' + SORTS.map(function (s) { return '<option value="' + s[0] + '"' + (sort() === s[0] ? ' selected' : '') + '>' + s[1] + '</option>'; }).join('') + '</select></label>';
    if (!groups.length) return '<div class="scl-tools">' + sortHtml + '</div>';
    var count = Object.keys(a).length;
    var open = filterOpen !== null ? filterOpen : !!(count || window.matchMedia('(min-width: 900px)').matches);
    return '<details class="scl-filters"' + (open ? ' open' : '') + '><summary>' + icon('squares-four') + '조건으로 찾기' + (count ? ' <b>' + count + '</b>' : '') + icon('caret-down') + '</summary><div class="scl-filter-groups">' +
      groups.map(function (g) { return '<fieldset><legend>' + h(g[0][1]) + '</legend><div>' + g[1].map(function (o) { var on = a[g[0][0]] === o[0]; return '<button type="button" data-scl-filter="' + h(g[0][0]) + '" data-value="' + h(o[0]) + '" aria-pressed="' + on + '">' + h(o[1]) + '</button>'; }).join('') + '</div></fieldset>'; }).join('') +
      (count ? '<button type="button" class="scl-clear" data-scl-clear>조건 지우기</button>' : '') + '</div></details><div class="scl-tools">' + sortHtml + '</div>';
  }
  function head(n) {
    return '<nav class="sc-breadcrumb" aria-label="현재 위치"><a href="index.html">홈</a>' + icon('caret-right') + '<span aria-current="page">AI 슈퍼컴퓨터</span></nav>' +
      '<header class="scl-head"><p class="sc-eyebrow">AI 전용 장비</p><h1>AI 슈퍼컴퓨터</h1><p>AI 모델 실행·개발을 위한 완제품을 비교해 보세요. AI 설치·교육은 장비 구매와 별도로 상담합니다.</p>' + (n !== null ? '<p class="scl-count" aria-live="polite">' + n + '개 제품</p>' : '') + '</header>';
  }
  function message(kind) {
    var m = { loading: ['cpu', '제품을 불러오고 있어요.', '현재 가격과 판매 상태를 확인합니다.', ''], error: ['warning-circle', '제품 목록을 불러오지 못했어요.', '잠시 후 다시 시도해 주세요.', '<button type="button" class="btn btn-primary" data-scl-retry>다시 시도</button>'],
      none: ['package', '아직 등록된 제품이 없어요.', '새 제품이 등록되면 이곳에 나옵니다.', '<a class="btn btn-outline" href="index.html">홈으로</a>'], filtered: ['magnifying-glass', '조건에 맞는 제품이 없어요.', '선택한 조건을 바꾸거나 지워 보세요.', '<button type="button" class="btn btn-primary" data-scl-clear>조건 지우기</button>'] }[kind];
    return '<section class="sc-empty scl-empty"' + (kind === 'loading' ? ' aria-busy="true"' : '') + '><span class="sc-empty-icon">' + icon(m[0]) + '</span><h2>' + m[1] + '</h2><p>' + m[2] + '</p>' + (m[3] ? '<div class="sc-empty-actions">' + m[3] + '</div>' : '') + '</section>';
  }
  function render() {
    var body;
    if (state === 'loading' && P.categoryLoading) body = head(null) + P.categoryLoading('supercomputer');   // 카테고리 로딩 1안(2026-10-20)
    else if (state !== 'ready') body = head(null) + message(state);
    else if (!items.length) body = head(0) + message('none');
    else {
      var list = visible();
      body = head(list.length) + '<div class="scl-layout">' + filtersHtml() + (list.length ? '<ul class="scl-grid">' + list.slice(0, shown).map(card).join('') + '</ul>' + (list.length > shown ? '<div class="scl-more"><button type="button" class="btn btn-outline" data-scl-more>더 보기 (' + (list.length - shown) + '개 남음)</button></div>' : '') : message('filtered')) + '</div>';
    }
    app.innerHTML = P.shell('<div class="container sc-page scl-page">' + body + '<p class="scl-note">가격·공급 일정은 문의 시 확인합니다. 업무에 맞춘 AI 도입은 <a href="ai-detail.html?package=business">업무 도입 패키지</a>에서 따로 상담합니다.</p></div>');
    P.bindShell();
    bind();
  }
  function setQuery(next) {
    query = next; shown = PAGE;
    var s = query.toString(), url = 'supercomputers.html' + (s ? '?' + s : '');
    history.replaceState(null, '', url); store(KEY_URL, url); render();
  }
  function bind() {
    app.querySelectorAll('[data-scl-filter]').forEach(function (b) { b.addEventListener('click', function () { var n = new URLSearchParams(query); var k = b.dataset.sclFilter; if (n.get(k) === b.dataset.value) n.delete(k); else n.set(k, b.dataset.value); setQuery(n); }); });
    app.querySelectorAll('[data-scl-clear]').forEach(function (b) { b.addEventListener('click', function () { var n = new URLSearchParams(query); FILTERS.forEach(function (f) { n.delete(f[0]); }); setQuery(n); }); });
    var s = app.querySelector('[data-scl-sort]'); if (s) s.addEventListener('change', function () { var n = new URLSearchParams(query); if (s.value === DEFAULT_SORT) n.delete('sort'); else n.set('sort', s.value); setQuery(n); });
    var m = app.querySelector('[data-scl-more]'); if (m) m.addEventListener('click', function () { shown += PAGE; render(); });
    var r = app.querySelector('[data-scl-retry]'); if (r) r.addEventListener('click', start);
    var det = app.querySelector('.scl-filters'); if (det) det.addEventListener('toggle', function () { filterOpen = det.open; });
    // 상세로 가기 직전 «더 보기» 수·필터 열림·누른 카드와 그 카드의 화면 안 위치를 남긴다(뒤로 오면 같은 카드를 같은 자리에 되살린다).
    app.querySelectorAll('[data-scl-item]').forEach(function (a) { a.addEventListener('click', function () {
      var d = app.querySelector('.scl-filters');
      store(KEY_VIEW, JSON.stringify({ url: location.search, shown: shown, y: Math.round(window.scrollY), filterOpen: d ? d.open : null,
        card: a.dataset.sclItem, cardTop: Math.round(a.getBoundingClientRect().top) }));
    }); });
  }
  app.addEventListener('error', function (e) { var img = e.target; if (img && img.matches && img.matches('[data-scl-img]')) img.parentNode.replaceChild(Object.assign(document.createElement('span'), { className: 'scl-photo-none', innerHTML: icon('package') + '사진 준비 중' }), img); }, true);
  function start() {
    state = 'loading'; render();
    D.list(true).then(function (data) {
      items = data.items; state = 'ready';
      var saved = null; try { saved = JSON.parse(store(KEY_VIEW) || 'null'); } catch (e) { saved = null; }
      var same = saved && saved.url === location.search;
      if (same && saved.shown > PAGE) shown = saved.shown;
      if (same && typeof saved.filterOpen === 'boolean') filterOpen = saved.filterOpen;
      store(KEY_URL, 'supercomputers.html' + location.search);
      render();
      if (same) restore(saved);
    }, function () { state = 'error'; render(); });
  }
  // 누른 카드가 여전히 목록에 있으면 그 카드를 떠날 때와 같은 화면 높이에 둔다. 결과가 바뀌어 카드가 없으면 남긴 스크롤 높이로,
  // 그 높이가 목록보다 길면 목록 끝으로 간다(없는 카드를 지어내지 않는다).
  function restoreOnce(saved) {
    var card = saved.card ? app.querySelector('[data-scl-item="' + String(saved.card).replace(/[^0-9]/g, '') + '"]') : null;
    if (card && typeof saved.cardTop === 'number') window.scrollTo(0, Math.max(0, card.getBoundingClientRect().top + window.scrollY - saved.cardTop));
    else if (saved.y > 0) window.scrollTo(0, saved.y);
    return Math.round(window.scrollY);
  }
  // 그린 직후 한 번, 그 뒤 2초 동안 머리글·글꼴·사진 자리 등 늦은 배치 변화가 있을 때마다 다시 맞춘다.
  // 손님이 직접 스크롤(휠·터치·키·누름)하면 바로 멈춘다 — 브라우저의 자동 스크롤 보정은 손님 동작으로 치지 않는다.
  function restore(saved) {
    var stopped = false, ro = null, evs = ['wheel', 'touchstart', 'keydown', 'mousedown'];
    function stop() { if (stopped) return; stopped = true; if (ro) ro.disconnect(); evs.forEach(function (n) { window.removeEventListener(n, stop, true); }); }
    function again() { if (!stopped) restoreOnce(saved); }
    evs.forEach(function (n) { window.addEventListener(n, stop, { capture: true, passive: true }); });
    restoreOnce(saved);
    if (window.ResizeObserver) { ro = new ResizeObserver(again); ro.observe(document.body); }
    [120, 400, 900, 1500].forEach(function (ms) { setTimeout(again, ms); });
    setTimeout(stop, 2000);
  }
  window.addEventListener('pageshow', function (e) { if (e.persisted) start(); });
  start();
}());
