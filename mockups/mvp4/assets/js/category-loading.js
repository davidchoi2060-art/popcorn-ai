/* /mvp4 카테고리별 진입 로딩(1안)과 AI 대화 응답 대기 (2026-10-20 대표 「카테고리별 로딩은 1안으로, AI 대화는 마지막 시안을 작게 해서 애니메이션」).
 * 실제로 불러오는 동안에만 화면이 이 조각을 그리고, 응답이 오면 화면이 다시 그려지며 사라진다. 진행률·남은 시간·최소 표시 시간은 없다.
 * 그림은 승인 시안에서 잘라 낸 자산(assets/images/loading/SOURCES.json). AI 패키지 그림은 시안 속 타사 로고를 옮기지 않고 중립 도구 모양으로 그린다.
 */
(function () {
  'use strict';
  var P = window.PAI;
  if (!P) return;
  var IMG = 'assets/images/loading/';
  var KINDS = {
    pc: ['PC 상품을 불러오고 있어요', 'loading-pc.webp', 230, 150],
    package: ['AI 패키지를 불러오고 있어요'],
    supercomputer: ['AI 슈퍼컴퓨터를 불러오고 있어요', 'loading-supercomputer.webp', 284, 130],
    chat: ['대화 화면을 준비하고 있어요', 'loading-chat.webp', 276, 160]
  };
  function icon(name) { return P.icon ? P.icon(name) : ''; }
  function art(k) {
    if (k[1]) return '<img src="' + IMG + k[1] + '" width="' + k[2] + '" height="' + k[3] + '" alt="">';
    return '<span class="cl-pkg"><span class="cl-pkg-tile">' + icon('file-text') + '</span><span class="cl-pkg-tile">' + icon('chat-circle') + '</span><span class="cl-pkg-tile">' + icon('magnifying-glass') + '</span><span class="cl-pkg-base"><b>AI</b></span></span>';
  }
  function cards(n) {
    var one = '<span class="cl-card"><span class="cl-sk cl-sk-photo"></span><span class="cl-sk"></span><span class="cl-sk cl-sk-short"></span></span>';
    return n ? '<div class="cl-cards" aria-hidden="true">' + new Array(n + 1).join(one) + '</div>' : '';
  }
  // kind: pc · package · supercomputer · chat. opts.cards = 스켈레톤 카드 수(기본 3), opts.skeleton = 그 화면 전용 스켈레톤 HTML.
  P.categoryLoading = function (kind, opts) {
    var k = KINDS[kind] || KINDS.pc;
    opts = opts || {};
    return '<div class="cl-loading cl-' + (KINDS[kind] ? kind : 'pc') + '" role="status" aria-busy="true"><div class="cl-head"><span class="cl-art" aria-hidden="true">' + art(k) + '</span>' +
      '<p class="cl-text">' + k[0] + '</p><span class="cl-dots" aria-hidden="true"><i></i><i></i><i></i></span></div>' +
      (opts.skeleton !== undefined ? opts.skeleton : cards(opts.cards === undefined ? 3 : opts.cards)) + '</div>';
  };
  // AI 대화 응답 대기 — 코어(시안에서 분리) + 모이는 빛 + 이어지는 점선. 대화 흐름 안의 작은 영역이다.
  P.chatWaitArt = function () {
    return '<span class="cw-art" aria-hidden="true"><svg class="cw-lines" viewBox="0 0 100 100" focusable="false"><ellipse cx="50" cy="50" rx="44" ry="20" transform="rotate(-18 50 50)"/><ellipse cx="50" cy="50" rx="40" ry="16" transform="rotate(28 50 50)"/></svg>' +
      '<img class="cw-core" src="' + IMG + 'chat-wait-core.webp" width="190" height="190" alt=""><i></i><i></i><i></i><i></i></span>';
  };
}());
