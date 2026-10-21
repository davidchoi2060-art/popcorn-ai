/* /mvp4 찜목록 → 성능 비교 (2026-10-21 대표 확정 1번 시안 02·03, 화면 주소 ?screen=compare).
 *
 * 찜목록  고객이 실제로 찜한 상품만 보인다(추천 상품을 채워 넣지 않는다 · 주소의 상품번호로 목록을 만들지 않는다).
 *         비교할 2~3개를 체크한다. 처음엔 0개, 넷째 체크는 막고 앞의 셋을 지킨다. 체크 해제 = 이번 비교에서만 제외,
 *         찜 해제 = 찜목록에서 삭제(그 체크도 함께 풀린다). 체크는 이 탭(sessionStorage)에만 둔다.
 * 비교    ?pick=pc:113835,pc:113330 — 찜목록에 있는 것만 비교한다. 가격 · 용도 수준(팝콘 기준표, 실측 아님) · 실제 사양 차이.
 *         %·FPS·작업 시간·「몇 배 빠름」은 쓰지 않는다. 코어 수 차이를 속도 차이로 바꾸지 않는다. 근거가 없으면 「확인 불가」.
 * 이 화면은 질문을 보내거나 AI·견적·상담·주문을 부르지 않는다. 「AI에게 차이 물어보기」는 대화 화면으로 갈 뿐 자동 전송하지 않는다.
 */
(function () {
  'use strict';
  var P = window.PAI;
  if (!P || !P.wishlist) return;
  P.designScreens = P.designScreens || {};
  var h = P.h, icon = P.icon, W = P.wishlist, PICK = 'pai-wish-pick-v1', MAX = 3;
  var USAGE_OF = { '게이밍 PC': '게임', '사무·업무용': '사무용', '디자인·영상': '영상편집', 'AI·고성능 PC': '로컬 AI', '미니 PC': '사무용' };
  // 상품 분류에 맞는 대표 용도 수준 하나(상세 배지용). 평가가 없으면 빈 값 — 지어내지 않는다.
  P.primaryFit = function (p) { var u = p && USAGE_OF[p.category]; return u && p.fit && p.fit[u] ? u + ' ' + p.fit[u] : ''; };
  function D() { return P.dcHelpers || {}; }
  function key(x) { return x.kind + ':' + x.id; }
  function parsePick(raw) { return String(raw || '').split(',').map(function (s) { var m = /^(pc|ai_device):(\d{1,18})$/.exec(s.trim()); return m ? { kind: m[1], id: m[2] } : null; }).filter(Boolean); }
  function readPick() { try { var v = JSON.parse(window.sessionStorage.getItem(PICK) || '[]'); return Array.isArray(v) ? v.filter(function (s) { return typeof s === 'string'; }) : []; } catch (e) { return []; } }
  function savePick(list) { try { window.sessionStorage.setItem(PICK, JSON.stringify(list)); } catch (e) { /* 체크 보존만 빠진다 */ } }
  function url(screen, state, values) { return P.designHref(screen, state, values || {}); }
  function steps(at) {
    return '<ol class="wl-steps" aria-label="진행 단계">' + [['찜목록', 1], ['성능 비교', 2], ['상품 상세 · 구매', 3]].map(function (s) {
      return '<li' + (s[1] === at ? ' class="is-current" aria-current="step"' : '') + '><b>' + s[1] + '</b><span>' + s[0] + '</span></li>';
    }).join('') + '</ol>';
  }
  P.wishSteps = steps;
  // 찜 항목 → 화면 항목. PC 는 판매 목록에서, AI 장비는 서버 상세에서 읽는다(이름·가격을 저장소에 두지 않는다).
  var devices = Object.create(null);
  function resolve(x) {
    if (x.kind === 'pc') { var p = D().product ? D().product(x.id) : null; return { x: x, p: p, missing: !p }; }
    var d = devices[x.id];
    return { x: x, p: d && d.item || null, missing: !!(d && d.failed), loading: !d };
  }
  function loadDevices(list, done) {
    var want = list.filter(function (x) { return x.kind === 'ai_device' && !devices[x.id]; });
    if (!want.length || !P.aiDevices) { want.forEach(function (x) { devices[x.id] = { failed: true }; }); if (want.length) done(); return; }
    Promise.all(want.map(function (x) {
      return P.aiDevices.detail(x.id).then(function (d) { devices[x.id] = { item: D().deviceOf(d) }; }, function () { devices[x.id] = { failed: true }; });
    })).then(done);
  }
  function specLine(r) {
    if (!r.p) return '';
    if (r.x.kind === 'ai_device') return [r.p.accelerator || r.p.processor, r.p.memory, r.p.storage].filter(Boolean).join(' · ');
    return r.p.summary || '';
  }
  function price(r) { return r.p ? (r.x.kind === 'ai_device' ? (r.p.saleState === 'on_sale' && r.p.price ? P.money(r.p.price) : '가격 확인 필요') : D().money(r.p)) : ''; }
  function detailHref(r, extra) { return r.x.kind === 'ai_device' ? 'supercomputer.html?id=' + encodeURIComponent(r.x.id) : url('product', 'normal', Object.assign({ id: r.x.id }, extra || {})); }
  function photo(r) { return D().photograph ? D().photograph(r.p) : ''; }
  function back(from) {
    if (from === 'chat') return '<a class="wl-back" href="' + h(url('chat', 'welcome')) + '">' + icon('arrow-left') + 'AI 대화로 돌아가기</a>';
    if (/^\d{1,18}$/.test(String(from || ''))) return '<a class="wl-back" href="' + h(url('product', 'normal', { id: from })) + '">' + icon('arrow-left') + '상품 상세로 돌아가기</a>';
    if (from === 'catalog') return '<a class="wl-back" href="' + h(url('catalog', 'normal')) + '">' + icon('arrow-left') + 'PC 쇼핑으로 돌아가기</a>';
    return '';
  }

  /* ---------- 02 찜목록 ---------- */
  function wishlistView(ctx) {
    var from = ctx.query && ctx.query.get ? ctx.query.get('from') : null;
    var root = null, picks = readPick(), note = '';
    function items() { return W.list().map(resolve); }
    function pickable(r) { return !r.missing && !r.loading && !!r.p; }
    function clean() { var have = {}; items().forEach(function (r) { if (pickable(r)) have[key(r.x)] = 1; }); picks = picks.filter(function (k) { return have[k]; }); savePick(picks); }
    function row(r) {
      var k = key(r.x), on = picks.indexOf(k) >= 0, name = r.p ? r.p.name : '상품번호 ' + r.x.id;
      var check = '<label class="wl-check"><input type="checkbox" data-wl-pick="' + h(k) + '"' + (on ? ' checked' : '') + (pickable(r) ? '' : ' disabled') + '><span class="visually-hidden">' + h(name) + ' 이번 비교에 포함</span></label>';
      if (r.loading) return '<li class="wl-row is-loading">' + check + '<div class="wl-info"><h2>' + h(name) + '</h2><p>AI 장비 정보를 불러오고 있어요.</p></div></li>';
      if (r.missing) return '<li class="wl-row is-missing">' + check + '<span class="dc-photo-placeholder">' + icon('computer-tower') + '</span><div class="wl-info"><h2>' + h(name) + '</h2><p class="dc-unavailable-label">지금 판매 목록에서 확인할 수 없는 상품이라 비교할 수 없어요.</p></div><div class="wl-manage">' + P.wishButton({ kind: r.x.kind, id: r.x.id, name: name, cls: 'wl-unwish', on: '찜 해제', off: '다시 찜하기' }) + '</div></li>';
      var issue = r.x.kind === 'ai_device' ? D().deviceIssue(r.p) : D().purchaseIssue(r.p);
      return '<li class="wl-row' + (on ? ' is-picked' : '') + '">' + check + '<a class="wl-photo" href="' + h(detailHref(r, { from: 'wish' })) + '" tabindex="-1" aria-hidden="true">' + photo(r) + '</a><div class="wl-info">' + (r.x.kind === 'ai_device' ? '<span class="pa-kind">AI 장비</span>' : '') + '<h2><a href="' + h(detailHref(r, { from: 'wish' })) + '">' + h(name) + '</a></h2><p>' + h(specLine(r)) + '</p><strong>' + h(price(r)) + '</strong>' + (issue ? '<p class="dc-unavailable-label">' + h(issue) + '</p>' : '') + '</div>' +
        '<div class="wl-manage"><a class="btn btn-outline wl-detail" href="' + h(detailHref(r, { from: 'wish' })) + '">자세히 보기' + icon('caret-right') + '</a>' + P.wishButton({ kind: r.x.kind, id: r.x.id, name: name, cls: 'wl-unwish', on: '찜 해제', off: '다시 찜하기' }) + '</div></li>';
    }
    function markup() {
      var list = items(), n = list.length, chosen = list.filter(function (r) { return picks.indexOf(key(r.x)) >= 0; });
      var head = back(from) + '<header class="wl-head"><div><h1>찜목록 <b class="wl-badge" data-wish-count>' + n + '</b></h1><p>' + (n >= 2 ? '비교할 PC를 2~3개 체크해 주세요. 마음에 드는 PC는 바로 살펴볼 수도 있어요.' : '찜한 상품을 모아 두고 2~3개를 골라 비교할 수 있어요.') + '</p></div>' + steps(1) + '</header>';
      if (!n) return head + '<section class="wl-empty">' + icon('computer-tower') + '<h2>아직 찜한 상품이 없어요.</h2><p>추천 PC나 상품 상세에서 ♡ 찜하기를 누르면 이곳에 모여요. 이 브라우저에만 저장돼요.</p><div class="wl-empty-actions"><a class="btn btn-primary" href="' + h(url('catalog', 'normal')) + '">PC 둘러보기</a><a class="btn btn-outline" href="' + h(url('chat', 'welcome')) + '">AI로 PC 찾기</a></div></section>';
      var all = n >= 2 && n <= MAX && list.every(pickable);
      var allOn = all && chosen.length === n;
      var bar = '<div class="wl-bar" role="region" aria-label="비교 선택"><div class="wl-bar-count">' + icon('check-circle') + '<div><strong aria-live="polite">' + chosen.length + '개 선택했어요</strong><small>' + (chosen.length ? h(chosen.map(function (r) { return r.p.name; }).join(' · ')) : '비교할 PC를 체크해 주세요.') + '</small></div></div>' +
        (chosen.length >= 2 ? '<a class="btn btn-primary wl-go" href="' + h(url('compare', 'normal', { pick: chosen.map(function (r) { return key(r.x); }).join(',') })) + '">' + chosen.length + '개 비교하기' + icon('arrow-right') + '</a>' : '<button class="btn btn-primary wl-go" type="button" disabled>' + (n === 1 ? '비교하려면 한 개 더 찜해 주세요' : '2개 이상 체크해 주세요') + '</button>') + '</div>';
      return head + (note ? '<p class="wl-note" role="status">' + h(note) + '</p>' : '') +
        '<section class="wl-table" aria-label="찜한 상품"><div class="wl-table-head">' + (all ? '<label class="wl-check"><input type="checkbox" data-wl-all' + (allOn ? ' checked' : '') + '><span>비교할 PC</span></label>' : '<span>비교할 PC</span>') + '<span>상품 정보</span><span>가격 및 관리</span></div><ul>' + list.map(row).join('') + '</ul></section>' +
        (n === 1 ? '<p class="wl-hint">' + icon('info') + '비교는 2개부터 할 수 있어요. 다른 PC를 하나 더 찜해 주세요. <a href="' + h(url('catalog', 'normal')) + '">PC 둘러보기</a></p>' : '') +
        bar + '<p class="wl-hint">' + icon('info') + '찜 해제는 목록에서 삭제하고, 체크 해제는 이번 비교에서만 제외해요. 찜목록은 이 브라우저에만 저장돼요.</p>';
    }
    // 다시 그려도 키보드 위치를 잃지 않게: 같은 체크·찜 버튼으로, 그 줄이 사라졌으면 제목으로 돌려 놓는다.
    function render() {
      clean(); if (!root) return;
      var f = document.activeElement, inside = f && root.contains(f), sel = inside && f.dataset.wlPick ? '[data-wl-pick="' + f.dataset.wlPick + '"]' : inside && f.dataset.wishId ? '[data-wish-kind="' + f.dataset.wishKind + '"][data-wish-id="' + f.dataset.wishId + '"]' : null;
      root.innerHTML = markup();
      if (!sel) return; var again = root.querySelector(sel) || root.querySelector('h1');
      if (again) { if (again.tagName === 'H1') again.setAttribute('tabindex', '-1'); again.focus(); }
    }
    clean();
    return { html: '<section class="container wl-page" data-wl>' + markup() + '</section>', mount: function () {
      root = document.querySelector('[data-wl]'); if (!root) return;
      loadDevices(W.list(), render);
      W.onChange(function () { note = ''; loadDevices(W.list(), render); render(); });
      root.addEventListener('change', function (e) {
        var t = e.target;
        if (t.hasAttribute('data-wl-all')) { picks = t.checked ? items().filter(pickable).map(function (r) { return key(r.x); }) : []; note = ''; savePick(picks); render(); var a = root.querySelector('[data-wl-all]'); if (a) a.focus(); return; }
        var k = t.dataset.wlPick; if (!k) return;
        if (t.checked) {
          if (picks.length >= MAX) { t.checked = false; note = '비교는 한 번에 3개까지 고를 수 있어요. 앞서 고른 3개는 그대로 두었어요.'; render(); return; }
          picks.push(k);
        } else picks = picks.filter(function (x) { return x !== k; });
        note = ''; savePick(picks); render();
      });
    } };
  }

  /* ---------- 03 성능 비교 ---------- */
  function cpuFacts(p) {
    var part = (Array.isArray(p.specs) ? p.specs : []).find(function (s) { return s.slot === 'CPU'; });
    var f = {}; (part && Array.isArray(part.facts) ? part.facts : []).forEach(function (x) { f[x.label] = x.value; });
    function n(v) { var m = /(\d+)/.exec(String(v || '')); return m ? Number(m[1]) : null; }
    var cores = n(f['코어 구성']), threads = n(f['스레드']);
    return { cores: cores, threads: threads };
  }
  function summaryValue(p, label) { var s = (p.summarySpecs || []).find(function (x) { return x.label === label; }); return s ? s.value : ''; }
  function compareView(ctx, pick) {
    var root = null, usage = null;
    function chosen() { var wished = {}; W.list().forEach(function (x) { wished[key(x)] = 1; }); return pick.filter(function (x) { return wished[key(x)]; }).slice(0, MAX).map(resolve).filter(function (r) { return r.p; }); }
    function levelsOf(u) { return (P.fitLevels || []).filter(function (l) { return l.usage === u; }).sort(function (a, b) { return a.rank - b.rank; }); }
    function usages(list) {
      var seen = []; (P.fitLevels || []).forEach(function (l) { if (seen.indexOf(l.usage) < 0 && list.some(function (r) { return r.x.kind === 'pc' && r.p.fit && r.p.fit[l.usage]; })) seen.push(l.usage); });
      return seen;
    }
    function pickUsage(list) {
      var opts = usages(list); if (usage && opts.indexOf(usage) >= 0) return usage;
      var first = list.find(function (r) { return r.x.kind === 'pc'; }), guess = first && USAGE_OF[first.p.category];
      return opts.indexOf(guess) >= 0 ? guess : opts[0] || null;
    }
    function levelCell(r, u) {
      if (r.x.kind === 'ai_device') return '<td class="cmp-level"><p class="cmp-unknown">확인 불가 · AI 장비는 팝콘 용도 기준표 대상이 아니에요</p></td>';
      var lv = u && r.p.fit ? r.p.fit[u] : null, all = levelsOf(u), at = all.find(function (l) { return l.level === lv; });
      if (!lv || !at) return '<td class="cmp-level"><p class="cmp-unknown">확인 불가 · 이 용도의 기준표 평가가 없어요</p></td>';
      return '<td class="cmp-level"><ol class="cmp-scale" aria-label="' + h(u) + ' 수준 ' + all.length + '단계 중 ' + h(lv) + '">' + all.map(function (l) { return '<li' + (l.level === lv ? ' class="is-on"' : '') + '><i></i>' + h(l.level) + '</li>'; }).join('') + '</ol>' + (at.work ? '<p class="cmp-work">' + h(at.work) + '</p>' : '') + '</td>';
    }
    function cpuCell(r, base) {
      if (r.x.kind === 'ai_device') return '<td><strong>' + h(r.p.processor || '확인 불가') + '</strong></td>';
      var name = summaryValue(r.p, 'CPU') || '확인 불가', f = cpuFacts(r.p), b = base && base !== r ? cpuFacts(base.p) : null;
      var line = f.cores && f.threads ? f.cores + '코어 · ' + f.threads + '스레드' : '코어 정보 확인 불가';
      var diff = b && f.cores && b.cores && f.threads && b.threads && (f.cores !== b.cores || f.threads !== b.threads) ? (f.cores - b.cores >= 0 ? '+' : '') + (f.cores - b.cores) + '코어 · ' + (f.threads - b.threads >= 0 ? '+' : '') + (f.threads - b.threads) + '스레드' : '';
      return '<td><strong>' + h(name) + '</strong><span>' + h(line) + '</span>' + (diff ? '<em class="cmp-diff">' + h(diff) + '</em>' : '') + '</td>';
    }
    function valueRow(label, list, get) {
      var vals = list.map(get), same = list.length > 1 && vals.every(function (v) { return v && v === vals[0] && v.indexOf('확인 불가') < 0; });
      return '<tr><th scope="row"><span class="cmp-label">' + label + '</span></th>' + vals.map(function (v) { return '<td><span>' + h(v || '확인 불가') + '</span>' + (same ? '<em class="cmp-same">동일</em>' : '') + '</td>'; }).join('') + '</tr>';
    }
    function headline(list, u) {
      if (list.length !== 2) {
        var priced = list.filter(function (r) { return typeof r.p.price === 'number' && r.p.price > 0; }).sort(function (a, b) { return a.p.price - b.p.price; });
        return priced.length >= 2 ? '<strong>가격은 ' + h(priced[0].p.name) + ' 쪽이 가장 낮고, ' + h(priced[priced.length - 1].p.name) + ' 쪽이 가장 높아요.</strong>' : '<strong>세 상품의 확인된 사양을 나란히 놓았어요.</strong>';
      }
      var a = list[0], b = list[1], money = '', cores = '';
      if (typeof a.p.price === 'number' && typeof b.p.price === 'number' && a.p.price > 0 && b.p.price > 0) {
        var d = b.p.price - a.p.price;
        money = d === 0 ? '두 PC의 가격은 같' : b.p.name + '는 ' + P.money(Math.abs(d)) + ' 더 ' + (d > 0 ? '높' : '낮');
      }
      var fa = a.x.kind === 'pc' ? cpuFacts(a.p) : {}, fb = b.x.kind === 'pc' ? cpuFacts(b.p) : {};
      if (fa.cores && fb.cores && fa.cores !== fb.cores) cores = 'CPU 코어가 ' + Math.abs(fb.cores - fa.cores) + '개 더 ' + (fb.cores > fa.cores ? '많아요' : '적어요');
      var text = money && cores ? money + '고, ' + cores + '.' : money ? money + (money.slice(-1) === '같' ? '아요.' : '아요.') : cores ? b.p.name + '는 ' + cores + '.' : '두 상품의 확인된 사양을 나란히 놓았어요.';
      var la = u && a.p.fit ? a.p.fit[u] : null, lb = u && b.p.fit ? b.p.fit[u] : null, sub = '';
      if (u && la && lb) sub = la === lb ? '두 상품의 ' + u + ' 평가는 같은 ' + la + ' 단계예요.' : u + ' 평가는 ' + la + '와 ' + lb + '로 달라요.';
      else if (u) sub = '한 상품은 ' + u + ' 평가를 확인할 수 없어요.';
      return '<strong>' + h(text) + '</strong>' + (sub ? '<span>' + h(sub) + '</span>' : '');
    }
    function markup() {
      var list = chosen(), pickKey = list.map(function (r) { return key(r.x); }).join(',');
      var head = '<div class="cmp-top"><a class="wl-back" href="' + h(url('compare', 'normal')) + '">' + icon('arrow-left') + '찜목록으로 돌아가기</a>' + P.wishLink({ label: '찜목록', cls: 'cmp-wish-link' }) + '</div>';
      if (list.length < 2) return head + '<section class="wl-empty">' + icon('info') + '<h2>비교할 상품이 2개 이상 필요해요.</h2><p>찜목록에서 빠졌거나 확인할 수 없는 상품은 비교에서 뺐어요. 찜목록에서 다시 골라 주세요.</p><div class="wl-empty-actions"><a class="btn btn-primary" href="' + h(url('compare', 'normal')) + '">찜목록에서 고르기</a></div></section>';
      var u = usage = pickUsage(list), opts = usages(list);
      var title = list.length === 2 ? '두 PC, <em>얼마나 다를까요?</em>' : '세 PC, <em>얼마나 다를까요?</em>';
      var ask = '<a class="cmp-ask" href="' + h(url('chat', 'welcome', { ask: pickKey })) + '">' + icon('chat-circle') + 'AI에게 차이 물어보기' + icon('caret-right') + '</a>';
      return head + '<header class="wl-head cmp-head"><div><h1>' + title + '</h1><p>' + (list.length === 2 ? '두' : '세') + ' 상품의 주요 사양을 한눈에 비교해 보세요.' + ask + '</p></div>' + steps(2) + '</header>' +
        '<div class="cmp-summary">' + icon('check-circle') + '<div>' + headline(list, u) + '</div></div>' +
        '<div class="cmp-wrap" data-cols="' + list.length + '"><table class="cmp-table"><caption class="visually-hidden">찜한 상품의 가격, 용도 수준, CPU, 메모리, 저장공간, 그래픽 비교</caption><thead><tr><th scope="col" class="cmp-corner">상품 정보</th>' + list.map(function (r) {
          return '<th scope="col"><div class="cmp-product">' + photo(r) + '<div>' + (r.x.kind === 'ai_device' ? '<span class="pa-kind">AI 장비</span>' : '') + '<h2>' + h(r.p.name) + '</h2><p>' + h(specLine(r)) + '</p><strong>' + h(price(r)) + '</strong></div></div></th>';
        }).join('') + '</tr></thead><tbody>' +
        '<tr class="cmp-level-row"><th scope="row"><span class="cmp-label">' + (opts.length > 1 ? '<label><span class="visually-hidden">용도 고르기</span><select data-cmp-usage>' + opts.map(function (o) { return '<option' + (o === u ? ' selected' : '') + '>' + h(o) + '</option>'; }).join('') + '</select></label>' : h(u || '용도')) + ' 수준<small>팝콘 기준 · 실측 아님</small></span></th>' + list.map(function (r) { return levelCell(r, u); }).join('') + '</tr>' +
        '<tr class="cmp-cpu-row"><th scope="row"><span class="cmp-label">CPU 구성</span></th>' + list.map(function (r) { return cpuCell(r, list[0]); }).join('') + '</tr>' +
        valueRow('메모리 / 저장공간', list, function (r) { return r.x.kind === 'ai_device' ? [r.p.memory, r.p.storage].filter(Boolean).join(' / ') : [summaryValue(r.p, '메모리'), summaryValue(r.p, '저장장치')].filter(Boolean).join(' / '); }) +
        valueRow('그래픽', list, function (r) { return r.x.kind === 'ai_device' ? r.p.accelerator || '' : summaryValue(r.p, '그래픽카드'); }) +
        '<tr class="cmp-note-row"><td colspan="' + (list.length + 1) + '">' + icon('info') + '<span>' + h(P.fitLevelsBasis || '팝콘 용도 기준표(부품 사양으로 판정) · 실측 아님') + '. 같은 수준이라도 속도가 같다는 뜻은 아니에요. 코어 수 차이가 그대로 속도 차이는 아니며, 실제 속도 차이(%)는 확인된 실측 자료가 없어요.</span></td></tr>' +
        '</tbody><tfoot><tr><th scope="row"><span class="visually-hidden">상세와 구매</span></th>' + list.map(function (r) {
          var buy = r.x.kind === 'ai_device' ? D().buyButton(r.p, false, 'cmp-buy') : (P.mallBuyLink ? P.mallBuyLink(r.p, 'cmp-buy', '팝콘PC몰에서 바로 구매') : '');
          return '<td><a class="btn btn-primary cmp-detail" href="' + h(detailHref(r, { from: 'compare', pick: pickKey })) + '"><span class="cmp-detail-name">' + h(r.p.name) + ' </span>자세히 보기' + icon('arrow-right') + '</a>' + (buy || '') + '</td>';
        }).join('') + '</tr></tfoot></table></div>';
    }
    function render() { if (root) root.innerHTML = markup(); }
    return { html: '<section class="container wl-page cmp-page" data-cmp>' + markup() + '</section>', mount: function () {
      root = document.querySelector('[data-cmp]'); if (!root) return;
      var pcs = pick.filter(function (x) { return x.kind === 'pc'; });
      loadDevices(pick, render);
      // CPU 코어·스레드는 공개 구성의 부품 정보에만 있다 — 받아 오면 다시 그린다(없으면 「확인 불가」 그대로).
      if (P.live && P.live.loadDetail) Promise.all(pcs.map(function (x) { return P.live.loadDetail(x.id).catch(function () { return null; }); })).then(render);
      W.onChange(render);
      root.addEventListener('change', function (e) { if (e.target.hasAttribute('data-cmp-usage')) { usage = e.target.value; render(); var s = root.querySelector('[data-cmp-usage]'); if (s) s.focus(); } });
    } };
  }

  P.designScreens.compare = function (ctx) {
    ctx = ctx || {};
    var raw = ctx.query && ctx.query.get ? ctx.query.get('pick') : null, pick = parsePick(raw);
    return pick.length ? compareView(ctx, pick) : wishlistView(ctx);
  };
}());
