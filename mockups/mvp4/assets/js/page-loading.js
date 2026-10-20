/* /mvp4 카테고리별 진입 로딩 — 대표 선택 1안(2026-10-20 「카테고리별 로딩은 1안으로」).
 *
 * 같은 체계(작은 그림 · 한 줄 문구 · 노랑 점 3개)에 카테고리마다 다른 그림과 문구를 쓴다. 상품 자리 스켈레톤은
 * 각 화면이 실제 레이아웃에 맞게 그대로 그린다 — 이 파일은 그 위의 머리 부분만 만든다.
 *   pc      PC 본체        «PC 상품을 불러오고 있어요»
 *   package AI 도구 묶음   «AI 패키지를 불러오고 있어요»   (타사 로고 없이 중립 도구 모티프)
 *   super   연산 장비      «AI 슈퍼컴퓨터를 불러오고 있어요»
 *   chat    대화 말풍선    «대화 화면을 준비하고 있어요»
 * 그림: assets/images/loading/*.png — 승인 1안(option-1.png)에서 잘라 배경만 투명하게 한 것(provenance.json).
 * 실제로 데이터를 기다리는 동안만 쓴다(최소 표시 시간·진행률 없음). 움직임 줄이기 설정이면 점이 멈춘다.
 */
(function () {
  'use strict';
  var P = window.PAI;
  if (!P || P.pageLoading) return;
  var KINDS = {
    pc: { img: 'pc.png', w: 250, h: 152, text: 'PC 상품을 불러오고 있어요' },
    package: { img: null, text: 'AI 패키지를 불러오고 있어요' },
    super: { img: 'super.png', w: 295, h: 140, text: 'AI 슈퍼컴퓨터를 불러오고 있어요' },
    chat: { img: 'chat.png', w: 280, h: 162, text: '대화 화면을 준비하고 있어요' }
  };
  function packageArt() {
    var ic = function (n) { return '<img src="assets/icons/' + n + '.svg" alt="" width="22" height="22">'; };
    return '<span class="pl-pkg" aria-hidden="true"><span class="pl-pkg-tile t1">' + ic('file-text') + '</span><span class="pl-pkg-tile t2">' + ic('chat-circle') + '</span><span class="pl-pkg-tile t3">' + ic('code') + '</span><span class="pl-pkg-base"><b>AI</b></span></span>';
  }
  // compact: 다른 구획 안에 들어가는 작은 형태(예: AI 패키지 아래 판매 제품).
  function head(kind, compact) {
    var k = KINDS[kind] || KINDS.pc;
    var art = k.img ? '<img class="pl-art" src="assets/images/loading/' + k.img + '" alt="" width="' + k.w + '" height="' + k.h + '">' : packageArt();
    return '<div class="pl-head pl-' + (KINDS[kind] ? kind : 'pc') + (compact ? ' pl-compact' : '') + '">' + art +
      '<p class="pl-text">' + k.text + '</p><span class="pl-dots" aria-hidden="true"><i></i><i></i><i></i></span></div>';
  }
  P.pageLoading = { head: head, kinds: KINDS };
}());
