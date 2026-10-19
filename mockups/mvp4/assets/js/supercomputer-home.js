/* /mvp4 메인 AI 슈퍼컴퓨터 진열 (v15 승인 시안 supercomputer-home.js 를 실제 조회에 연결, 2026-10-19).
 * 자리: AI 패키지 아래 · 게이밍 PC 위. 모델 두 줄의 가격은 GET /api/customer/supercomputers(live-supercomputer.js)가 채운다 —
 * 응답 전에는 «가격 확인 중», 실패·판매 확인 필요면 «가격 확인 필요». 링크는 /mvp4 내부 상세(supercomputer.html)뿐이다.
 */
(function () {
  'use strict';
  var P = window.PAI;
  if (!P || !P.designScreens || !P.designScreens.home || !P.gb10) return;
  var original = P.designScreens.home, scrolled = false;
  var LABEL = { '129615': 'SSD 2TB', '129614': 'SSD 4TB' };
  function priceText(p) { return p && p.saleState === 'on_sale' && p.price ? P.money(p.price) : '가격 확인 필요'; }
  function fill(data) {
    P.gb10.ids.forEach(function (id) {
      var p = data && data.products[id];
      document.querySelectorAll('[data-gb-home-price="' + id + '"]').forEach(function (node) { node.textContent = data ? priceText(p) : '가격 확인 필요'; });
      document.querySelectorAll('[data-gb-home-label="' + id + '"]').forEach(function (node) { if (p && p.storage) node.textContent = p.memory + ' · SSD ' + p.storage; });
    });
  }
  function jump() {
    if (scrolled || location.hash !== '#home-supercomputer') return;
    var el = document.getElementById('home-supercomputer');
    if (el) { scrolled = true; el.scrollIntoView({ block: 'start' }); }
  }
  P.designScreens.home = function () {
    var screen = original.apply(this, arguments), icon = P.icon, oldMount = screen.mount, cached = P.gb10.data;
    var markup = '<section class="hm-container gb-home" id="home-supercomputer" aria-labelledby="gb-home-title">' +
      '<div class="gb-home-hero"><div class="gb-home-copy"><p class="gb-home-eyebrow">AI SUPERCOMPUTER <span>DELL</span></p><h2 id="gb-home-title">책상 위에 놓는<br>나만의 AI 슈퍼컴퓨터.</h2><p class="gb-home-lead">로컬 AI 실행부터 개발까지.<br>작은 공간에서 시작하는 새로운 가능성.</p><div class="gb-home-facts"><span>' + icon('cpu') + 'NVIDIA GB10</span><span>' + icon('memory') + '128GB 통합 메모리</span></div><a class="btn btn-primary" href="supercomputer.html?id=129615">슈퍼컴퓨터 알아보기 ' + icon('arrow-right') + '</a></div><a class="gb-home-picture" href="supercomputer.html?id=129615" aria-label="Dell Pro Max GB10 제품 자세히 보기"><img src="' + P.gb10.image + '" alt="Dell Pro Max GB10 AI 슈퍼컴퓨터" loading="lazy" width="600" height="600"><span>Dell Pro Max GB10</span></a></div>' +
      '<div class="gb-home-bottom"><div class="gb-home-models">' + P.gb10.ids.map(function (id) {
        var p = cached && cached.products[id];
        return '<a class="gb-home-model" href="supercomputer.html?id=' + id + '"><div><span class="gb-model-label" data-gb-home-label="' + id + '">' + (p && p.storage ? P.h(p.memory + ' · SSD ' + p.storage) : '128GB · ' + LABEL[id]) + '</span><strong data-gb-home-price="' + id + '">' + (cached ? priceText(p) : '가격 확인 중') + '</strong></div><span class="gb-model-go">모델 보기 ' + icon('arrow-right') + '</span></a>';
      }).join('') + '</div><p class="gb-home-caption">로컬 AI 전용 완제품 · NVIDIA DGX OS <span>AI 설치·도입은 별도 상담</span></p></div></section>';
    if (screen.html.indexOf('<section class="hm-gaming') >= 0) screen.html = screen.html.replace('<section class="hm-gaming', markup + '<section class="hm-gaming');
    screen.mount = function () {
      if (oldMount) oldMount.apply(this, arguments);
      jump();
      P.gb10.load().then(function (data) { fill(data); jump(); }, function () { fill(null); });
    };
    return screen;
  };
}());
