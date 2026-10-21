/* /mvp4 업무별 「이 업무에 사용할 PC」 칸 (2026-10-21 구매·견적·AI 비교 1번 승인).
 *
 * 사내 문서 검색·회의록 정리·고객 답변 초안 설명의 구축 과정 뒤, 설치·구축 상담 앞에 둔다(업무 문맥은 주소의 use 를 그대로 잇는다).
 * 후보는 «그 업무의 실행 조건으로 확인을 마친 실제 판매 상품»만 보인다 — P.taskPcCandidates[use] 에 검증된 항목이 있을 때만이다.
 * 지금은 검증을 마친 후보가 없다. 그래서 빈 이유·확인할 조건·기존 PC 활용 상담 길을 보이고, 고가 PC나 AI 슈퍼컴퓨터로 대신 채우지 않는다.
 * 시안의 127316·129615 는 배치 예시였고 추천 승인이 아니므로 여기 적지 않는다. 2~3개를 맞추려고 후보를 늘리지 않는다.
 * 후보 카드(검증된 항목이 생기면): 상품번호·사진·핵심 사양·현재 가격(없으면 「가격 확인 필요」)·선정 이유·확인된 실행 조건과 제한,
 *   상품 상세 · 팝콘PC몰 구매(가격 안내 거침) · AI 비교에 담기 — 모두 같은 상품번호를 쓴다. 구매에 저장·연락처·상담을 끼우지 않는다.
 */
(function () {
  'use strict';
  var P = window.PAI = window.PAI || {};
  var TASKS = {
    documents: { label: '사내 문서 검색', from: 'D', basis: ['실행할 언어 모델의 크기와 양자화 방식', '검색할 문서의 양과 색인 크기', '한 번에 읽어야 하는 문맥 길이', '쓰려는 프로그램과 운영체제(Windows·Linux 등)', '함께 쓰는 사람 수'] },
    meetings: { label: '회의록 정리', from: 'M', basis: ['회의 녹음 길이와 하루 처리할 분량(전사 처리량)', '회의가 끝난 뒤 정리본이 나와야 하는 시간', '전사·요약에 쓸 모델의 크기와 양자화 방식', '쓰려는 프로그램과 운영체제', '함께 쓰는 사람 수'] },
    replies: { label: '고객 답변 초안', from: 'R', basis: ['초안을 만들 언어 모델의 크기와 양자화 방식', '참고할 응대 기준·자료의 양', '하루 문의 건수와 초안을 기다릴 수 있는 시간', '쓰려는 프로그램과 운영체제', '함께 쓰는 사람 수'] }
  };
  function esc(v) { return String(v === null || v === undefined ? '' : v).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function i(name) { return P.icon ? P.icon(name) : ''; }
  function consultHref(use) { return 'ai-consult.html?package=business&amp;use=' + use + '&amp;intent=adoption'; }
  // 검증된 후보만 받는다: 상품 종류·상품번호·이름·선정 이유·확인된 실행 조건이 있어야 한다.
  function verified(use) {
    var list = P.taskPcCandidates && Array.isArray(P.taskPcCandidates[use]) ? P.taskPcCandidates[use] : [];
    return list.filter(function (c) { return c && (c.kind === 'pc' || c.kind === 'ai_device') && /^\d{1,18}$/.test(String(c.id)) && c.name && c.why && Array.isArray(c.conditions) && c.conditions.length; }).slice(0, 3);
  }
  function card(c) {
    var detail = c.kind === 'ai_device' ? 'supercomputer.html?id=' + encodeURIComponent(c.id) : './?screen=product&amp;id=' + encodeURIComponent(c.id);
    var price = typeof c.price === 'number' && c.price > 0 ? c.price : null, stopped = c.saleState === 'stopped';
    var buy = stopped ? '<button type="button" class="btn tp-buy" disabled>판매 중지</button>' : (P.mallBuyAnchor && P.mallBuyAnchor({ id: c.id, url: c.mallUrl, name: c.name, price: price, image: c.image, cls: 'btn tp-buy', label: '팝콘PC몰에서 구매' })) || '<button type="button" class="btn tp-buy" disabled>구매 링크 확인 필요</button>';
    return '<article class="tp-card" data-tp-id="' + esc(c.id) + '" data-tp-kind="' + esc(c.kind) + '"><span class="tp-tag">검증 후보</span>' + (c.image ? '<img src="' + esc(c.image) + '" alt="" width="200" height="150" loading="lazy">' : '') +
      '<div class="tp-body"><h3>' + esc(c.name) + '</h3><small>상품번호 ' + esc(c.id) + '</small>' + (c.specs ? '<p class="tp-specs">' + esc(c.specs) + '</p>' : '') +
      '<p class="tp-price">' + (stopped ? '판매 중지' : price ? esc(price.toLocaleString('ko-KR')) + '원' : '가격 확인 필요') + (price && c.priceAt ? '<small>' + esc(c.priceAt) + ' 기준 · 팝콘AI 표시 금액</small>' : '') + '</p>' +
      '<p class="tp-why"><b>선정 이유</b> ' + esc(c.why) + '</p><ul class="tp-cond">' + c.conditions.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>' + (c.limits ? '<p class="tp-limit"><b>제한</b> ' + esc(c.limits) + '</p>' : '') + (c.photoNote ? '<p class="tp-limit">' + esc(c.photoNote) + '</p>' : '') +
      '<div class="tp-actions"><a class="btn btn-outline" href="' + detail + '">상품 상세</a>' + buy + '<button type="button" class="btn tp-compare" data-tp-compare>' + i('arrows-left-right') + 'AI 비교에 담기</button></div><p class="tp-status" role="status" aria-live="polite"></p></div></article>';
  }
  function section(use) {
    var t = TASKS[use]; if (!t) return '';
    var list = verified(use);
    var tabs = Object.keys(TASKS).map(function (k) { return k === use ? '<span class="tp-task is-current" aria-current="page">' + esc(TASKS[k].label) + '</span>' : '<a class="tp-task" href="ai-service.html?package=business&amp;use=' + k + '#task-pc">' + esc(TASKS[k].label) + '</a>'; }).join('');
    var body = list.length ? '<div class="tp-cards">' + list.map(card).join('') + '</div>'
      : '<div class="tp-empty" role="note"><h3>이 업무로 확인을 마친 PC가 아직 없어요.</h3><p>아래 조건으로 실제 판매 상품을 확인한 뒤에만 후보로 보여 드립니다. 확인되지 않은 고가 PC나 AI 슈퍼컴퓨터를 대신 추천하지 않습니다.</p><p>지금 쓰는 PC로 충분한지, 어떤 사양이면 되는지는 상담에서 함께 확인해요.</p></div>';
    return '<section class="tp-section" id="task-pc" aria-labelledby="tp-title" tabindex="-1">' +
      '<ol class="tp-steps" aria-label="진행 순서"><li>업무 예시</li><li>구축 과정</li><li aria-current="step">PC 살펴보기</li><li>설치·구축 상담</li></ol>' +
      '<div class="tp-head"><div><h2 id="tp-title">이 업무에 사용할 PC를 살펴보세요.</h2><nav class="tp-tasks" aria-label="업무 선택">' + tabs + '</nav><p class="tp-note">실행할 모델과 자료량에 맞춰 후보를 검토합니다. 업무 적합성이 확인된 PC만 보여 드립니다.</p></div>' +
      '<aside class="tp-reuse"><div><strong>기존 PC 활용도 먼저 확인해요.</strong><p>지금 사용 중인 PC로도 가능할 수 있습니다.</p></div><a class="btn btn-outline" href="' + consultHref(use) + '">내 PC로 상담 ' + i('arrow-right') + '</a></aside></div>' +
      body +
      '<details class="tp-basis"><summary>' + esc(t.label) + ' PC를 고를 때 확인하는 조건</summary><ul>' + t.basis.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul><p>세 업무는 필요한 조건이 달라 같은 목록을 쓰지 않습니다.</p></details>' +
      '<div class="tp-band"><div><strong>PC만 필요하면 구매로, 설치·구축까지 필요하면 상담으로.</strong><p>업무에 맞는 도입 방식을 함께 검토해 드립니다.</p></div><a class="btn tp-consult" href="' + consultHref(use) + '">' + i('chat-circle') + '내 업무로 구축 상담</a><a class="tp-company" href="ai-company.html?from=' + t.from + '">30인 이하 기업 전체 컨설팅은 별도로 안내합니다.</a></div>' +
      '</section>';
  }
  function bind() {
    var root = document.getElementById('task-pc'); if (!root || root.dataset.bound) return; root.dataset.bound = '1';
    root.addEventListener('click', function (e) {
      var b = e.target.closest('[data-tp-compare]'); if (!b) return;
      var c = b.closest('[data-tp-id]'), st = c.querySelector('.tp-status');
      var ok = P.compareCarry && P.compareCarry.add(c.dataset.tpKind, c.dataset.tpId);
      st.innerHTML = ok ? 'AI로 PC 찾기 관심·비교상품에 담았어요. 질문은 보내지 않았어요. <a href="./?screen=chat" target="_blank" rel="noopener">AI로 PC 찾기에서 보기 ↗</a>' : '이 브라우저에서는 비교 목록으로 넘길 수 없어요.';
    });
  }
  // 설명 본문의 설치·구축 상담 구획(ls-cta · mg-cta · rp-cta) 바로 앞에 끼운다. 그 구획이 없으면 본문 끝에 둔다.
  function insert(html, use) {
    var s = section(use); if (!s) return html;
    var m = /<section class="(ls|mg|rp)-cta"/.exec(html);
    return m ? html.slice(0, m.index) + s + html.slice(m.index) : html + s;
  }
  P.taskPc = { section: section, insert: insert, bind: bind, tasks: TASKS };
}());
