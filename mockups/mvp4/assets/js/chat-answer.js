/* AI 대화 답변 표시 (2026-10-20 대표 승인 「형광펜 노트 + 카드 브리핑」).
 *
 * 받은 답(reply)의 글자는 바꾸지 않는다. 이 파일이 하는 일은 셋뿐이다.
 *   1. 나누기  -- 문단·목록 줄·문장으로 나눈다. 목록 줄이 서버가 준 판매 PC(agent_cards)의 이름과 같을 때만 상품 카드로 그린다.
 *   2. 강조    -- 서버 형식 ==어구== 만 <mark> 로 바꾼다. 나머지 글은 전부 이스케이프한다(받은 HTML 은 실행하지 않는다).
 *   3. 복사    -- 문장·선택 문장·답변 전체를 본문 글자만 복사한다(버튼 이름·순번 장식은 넣지 않는다).
 * 답변마다 turn_id · recommendation_set_id · 순번 · 상품 유형 · product_id 를 한 묶음으로 둔다 -- 본문 카드·상세 링크·
 * 비교 담기·다음 질문의 「위 N번째」가 모두 같은 묶음을 본다.
 */
(function () {
  'use strict';
  var P = window.PAI = window.PAI || {};
  var MARK = /==([^=\n]{1,80})==/g, ITEM = /^\s*(?:[-*•·]|\d{1,2}[.)])\s+(.+)$/, ASK = /[?？]\s*$|알려\s*주|말씀해\s*주/;
  var seq = 0;

  function strip(s) { return String(s || '').replace(MARK, '$1').replace(/==/g, ''); }
  function esc(s) { return typeof P.h === 'function' ? P.h(s) : String(s).replace(/[&<>"']/g, function (c) { return '&#' + c.charCodeAt(0) + ';'; }); }
  function fmt(s) { return esc(s).replace(MARK, '<mark>$1</mark>').replace(/==/g, ''); }
  function norm(s) { return strip(s).toLowerCase().replace(/[\s\[\]()·,._\/|+-]/g, ''); }

  // 문장 끝(. ! ? 뒤에 공백·끝)에서만 자른다 -- 「3.5GHz」·「7~8B」는 자르지 않는다.
  function sentences(text) {
    var out = [], cur = '', s = String(text || '');
    for (var i = 0; i < s.length; i++) {
      var c = s.charAt(i); cur += c;
      if (c === '\n' || (/[.!?？。]/.test(c) && (i + 1 >= s.length || /\s/.test(s.charAt(i + 1))))) { if (cur.trim()) out.push(cur.trim()); cur = ''; }
    }
    if (cur.trim()) out.push(cur.trim());
    return out;
  }

  function newId(prefix) { seq += 1; return prefix + Date.now().toString(36) + seq.toString(36); }

  // 서버가 준 판매 PC 카드 중 화면에 쓸 값만(상품번호·이름·답변 가격·가격 기준·메모리).
  function cleanCards(list) {
    var seen = Object.create(null);
    return (Array.isArray(list) ? list : []).filter(function (c) {
      var ok = c && Number.isSafeInteger(c.product_code) && c.product_code > 0 && typeof c.name === 'string' && c.name.trim() && !seen[c.product_code];
      if (ok) seen[c.product_code] = true; return ok;
    }).map(function (c) {
      return { product_code: c.product_code, name: c.name, price: Number.isSafeInteger(c.price) ? c.price : null, price_src: typeof c.price_src === 'string' ? c.price_src : '',
        ram_gb: c.spec && Number.isSafeInteger(c.spec.ram_gb) ? c.spec.ram_gb : null };
    });
  }

  /* reply · agent_cards · 화면에 보인 PC(products) -> 답변 묶음.
   * 묶음 순서 = 본문이 소개한 순서(카드로 맞춘 목록 줄) 다음에 본문에 없던 화면 PC. 본문 순번이 화면 순서에 덮이지 않는다. */
  function build(reply, agentCards, shown) {
    var cards = cleanCards(agentCards), used = Object.create(null), blocks = [], cur = null, gap = true;
    String(reply || '').split('\n').forEach(function (line) {
      if (!line.trim()) { cur = null; gap = true; return; }
      var m = ITEM.exec(line);
      if (m) { cur = { kind: 'item', head: m[1], line: line, body: [] }; blocks.push(cur); gap = false; return; }
      if (cur && cur.kind === 'item' && !gap) { cur.body.push(line); return; }
      if (cur && cur.kind === 'para') { cur.text += '\n' + line; return; }
      cur = { kind: 'para', text: line }; blocks.push(cur); gap = false;
    });
    blocks.forEach(function (b) {
      if (b.kind !== 'item') return;
      var split = /^(.*?)\s+[—–-]\s+([\d,]+\s*원.*)$/.exec(strip(b.head)), name = split ? split[1] : strip(b.head), key = norm(name), head = norm(b.head);
      var hit = cards.find(function (c) { var n = norm(c.name); return !used[c.product_code] && n.length >= 4 && (head.indexOf(n) >= 0 || (key.length >= 6 && n.indexOf(key) >= 0)); });
      if (!hit) return;
      used[hit.product_code] = true;
      b.kind = 'card'; b.code = hit.product_code; b.name = split ? split[1] : strip(b.head); b.priceText = split ? split[2] : '';
      b.card = hit;
      // 상품명의 메모리(128G)와 본문의 메모리(256GB)가 다르면 고치지 않고 확인 대상으로 남긴다.
      var nameRam = /\/(\d{1,4})G(?:B)?\//i.exec(b.name), bodyRam = /메모리\s*(\d{1,4})\s*GB/i.exec(strip(b.body.join(' ')));
      if (nameRam && bodyRam && nameRam[1] !== bodyRam[1]) b.check = '상품명은 ' + nameRam[1] + 'G, 설명은 ' + bodyRam[1] + 'GB입니다. 실제 메모리 용량 확인이 필요합니다.';
    });
    var ordinal = 0, set = [];
    blocks.forEach(function (b) { if (b.kind === 'card') { ordinal += 1; b.ordinal = ordinal; set.push({ ordinal: ordinal, product_code: b.code, in_body: true }); } });
    (Array.isArray(shown) ? shown : []).forEach(function (p) {
      var code = Number(p && p.id); if (!Number.isSafeInteger(code) || set.some(function (x) { return x.product_code === code; })) return;
      ordinal += 1; set.push({ ordinal: ordinal, product_code: code, in_body: false });
    });
    var turnId = newId('t');
    return { turnId: turnId, setId: set.length ? 'rs-' + turnId : null, raw: String(reply || ''), blocks: blocks, set: set.slice(0, 6), copy: null };
  }

  function typeOf(code) {
    if (typeof P.getCatalogProduct === 'function' && P.getCatalogProduct(String(code))) return 'pc';
    var ai = P.aiDevices && P.aiDevices.data && Array.isArray(P.aiDevices.data.items) ? P.aiDevices.data.items : [];
    return ai.some(function (d) { return String(d && d.id) === String(code); }) ? 'ai_device' : 'unknown';
  }

  /* opts: {pcHref(id), issue(p), money(p)} — 상품 줄의 찜하기는 wish-ui.js 버튼(2026-10-21 찜하기·찜목록 확정). AI 장비도 담는다(2026-10-21 구매 1번 승인). */
  function render(entry, opts) {
    var a = entry.answer, list = [], cards = a.blocks.filter(function (b) { return b.kind === 'card'; });
    function line(text, cls) {
      return sentences(text).map(function (s) {
        var i = list.push(strip(s)) - 1;
        return '<p class="pa-sentence' + (cls ? ' ' + cls : '') + '">' + fmt(s) + '<button type="button" class="pa-copy pa-line-copy" data-nocopy data-pa-copy="line" data-pa-turn="' + esc(a.turnId) + '" data-pa-i="' + i + '" aria-label="이 문장 복사">문장 복사</button></p>';
      }).join('');
    }
    // 가격이 붙은 목록 줄인데 서버가 확인한 상품번호와 맞지 않으면 링크를 걸지 않고 그 사실을 적는다(이름이 닮은 다른 상품을 붙이지 않는다).
    function plain(b) {
      if (b.kind === 'para') return line(b.text);
      var priced = /[—–-]\s+[\d,]+\s*원/.test(strip(b.head));
      return line([b.line].concat(b.body).join('\n')) + (priced ? '<p class="pa-issue" role="note">이 상품은 확인된 추천 목록에서 찾지 못해 링크와 비교 담기를 넣지 않았어요.</p>' : '');
    }
    function card(b) {
      var code = String(b.code), type = typeOf(code), p = type === 'pc' && typeof P.getCatalogProduct === 'function' ? P.getCatalogProduct(code) : null;
      var href = type === 'pc' ? opts.pcHref(code) : type === 'ai_device' ? 'supercomputer.html?id=' + encodeURIComponent(code) : '';
      var issue = type === 'unknown' ? '지금 판매 목록에서 이 상품을 확인할 수 없어요.' : p && opts.issue ? opts.issue(p) : '';
      var now = p && typeof p.price === 'number' && b.card.price !== null && p.price !== b.card.price && opts.money ? '지금 목록 가격 ' + opts.money(p) + ' · 답변의 가격과 달라요' : '';
      var body = b.body.join('\n'), parts = sentences(body);
      var title = href ? '<a href="' + esc(href) + '" target="_blank" rel="noopener">' + fmt(b.name) + '</a>' : fmt(b.name);
      return '<section class="pa-product" data-product-id="' + esc(code) + '" data-product-type="' + type + '" data-pa-ordinal="' + b.ordinal + '"><header class="pa-product-head"><span class="pa-count" data-nocopy>' + (b.ordinal < 10 ? '0' : '') + b.ordinal + '</span><h3>' + title + '</h3>' +
        // 답 줄에 금액이 없어도 서버 카드 가격이 있으면 그 값을 쓴다(2026-10-21 「70만원」 캡처: 판매가가 있는데 「가격 확인 필요」).
        (b.priceText ? '<span class="pa-price">' + fmt(b.priceText) + '</span>' : typeof b.card.price === 'number' && b.card.price > 0 && P.money ? '<span class="pa-price">' + esc(P.money(b.card.price)) + '</span>' : '<span class="pa-price pa-price-none">가격 확인 필요</span>') +
        (b.card.price_src ? '<small class="pa-price-src">' + esc(b.card.price_src) + '</small>' : '') + (now ? '<small class="pa-price-now">' + esc(now) + '</small>' : '') + '</header>' +
        (parts.length ? line(parts[0], 'pa-spec') + (parts.length > 1 ? line(parts.slice(1).join(' '), 'pa-fit') : '') : '') +
        (b.check ? '<aside class="pa-check"><strong>확인 필요 · 답변 안의 불일치</strong>' + esc(b.check) + '</aside>' : '') +
        (issue ? '<p class="pa-issue" role="note">' + esc(issue) + '</p>' : '') +
        '<div class="pa-product-actions" data-nocopy>' + (href ? '<a href="' + esc(href) + '" target="_blank" rel="noopener">상품 상세 ↗</a>' : '') +
        (type === 'pc' && p && P.mallBuyLink ? P.mallBuyLink(p, 'pa-mall-buy', '팝콘PC몰에서 바로 구매') : '') +
        (type === 'pc' || type === 'ai_device' ? (P.wishButton ? P.wishButton({ kind: type, id: code, name: strip(b.name), cls: 'pa-wish' }) : '') : '') + '</div></section>';
    }
    var body;
    if (!cards.length) body = a.blocks.map(plain).join('');
    else {
      var first = a.blocks.indexOf(cards[0]), last = a.blocks.lastIndexOf(cards[cards.length - 1]);
      var intro = a.blocks.slice(0, first), mid = a.blocks.slice(first, last + 1), after = a.blocks.slice(last + 1);
      var nextAt = after.length && after[after.length - 1].kind === 'para' && ASK.test(strip(after[after.length - 1].text)) ? after.length - 1 : -1;
      var choice = after.filter(function (b, i) { return i !== nextAt; });
      body = (intro.length ? '<div class="pa-intro"><span class="pa-heading" data-nocopy>중요한 선택 기준</span>' + intro.map(plain).join('') + '</div>' : '') +
        '<div class="pa-list">' + mid.map(function (b) { return b.kind === 'card' ? card(b) : '<div class="pa-between">' + plain(b) + '</div>'; }).join('') + '</div>' +
        (choice.length ? '<div class="pa-choice"><span class="pa-heading" data-nocopy>어떻게 고르면 될까요?</span>' + choice.map(plain).join('') + '</div>' : '') +
        (nextAt >= 0 ? '<div class="pa-next"><span class="pa-heading" data-nocopy>다음으로 알려주세요</span>' + plain(after[nextAt]) + '</div>' : '');
    }
    entry.sentences = list;
    var c = a.copy || {};
    return '<div class="pa-formatted pa-approved-hybrid" data-pa-answer="' + esc(a.turnId) + '"' + (a.setId ? ' data-pa-set="' + esc(a.setId) + '"' : '') + '><div class="pa-body">' + body + '</div>' +
      '<div class="pa-copy-footer" data-nocopy><button type="button" class="pa-copy" data-pa-copy="all" data-pa-turn="' + esc(a.turnId) + '">답변 전체 복사</button><button type="button" class="pa-copy" data-pa-copy="sel" data-pa-turn="' + esc(a.turnId) + '">선택한 문장 복사</button></div>' +
      '<p class="pa-status" role="status" aria-live="polite" data-nocopy>' + esc(c.status || '') + '</p>' +
      (c.fallback ? '<textarea class="pa-fallback" data-nocopy data-pa-fallback="' + esc(a.turnId) + '" aria-label="복사할 글" readonly>' + esc(c.fallback) + '</textarea>' : '') + '</div>';
  }

  // 선택 영역 -> 본문 글자만(버튼·순번·안내 줄 제외).
  function selectionText(sel, within) {
    if (!sel || sel.isCollapsed || !sel.rangeCount) return '';
    var range = sel.getRangeAt(0);
    if (!within || !within.contains(range.commonAncestorContainer)) return '';
    var box = document.createElement('div'); box.appendChild(range.cloneContents());
    Array.prototype.forEach.call(box.querySelectorAll('[data-nocopy]'), function (n) { n.remove(); });
    Array.prototype.forEach.call(box.querySelectorAll('p,h3,section,div,li'), function (n) { n.appendChild(document.createTextNode('\n')); });
    return box.textContent.replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
  }

  // 클립보드에 실제로 들어갔을 때만 true. 막히면 false(화면이 고를 수 있는 글로 내민다).
  function writeClipboard(text) {
    if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function' && window.isSecureContext !== false) {
      return navigator.clipboard.writeText(text).then(function () { return true; }, function () { return false; });
    }
    return Promise.resolve(false);
  }

  P.chatAnswer = { build: build, render: render, strip: strip, sentences: sentences, selectionText: selectionText, writeClipboard: writeClipboard, cleanCards: cleanCards };
}());
