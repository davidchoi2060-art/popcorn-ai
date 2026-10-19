/* /mvp4 메인 AI 슈퍼컴퓨터 진열 (v15/v15.1 승인 시안 · 카테고리 확장 2026-10-20).
 * 자리: AI 패키지 아래 · 게이밍 PC 위. 승인된 밝은 구획(대표 상품 Dell GB10 소개)은 그대로 두고,
 * 아래 모델 줄은 카테고리 데이터(GET /api/customer/supercomputers)의 대표 상품(featured_rank 순, 없으면 앞에서부터 2개)으로 그린다.
 * «전체 AI 슈퍼컴퓨터 보기»는 카테고리 목록(supercomputers.html)으로 간다. 상품번호를 여기 적지 않는다.
 * 응답 전에는 «가격 확인 중», 실패·판매 확인 필요면 «가격 확인 필요». 링크는 /mvp4 내부 화면뿐이다.
 */
(function () {
  'use strict';
  var P = window.PAI;
  if (!P || !P.designScreens || !P.designScreens.home || !P.aiDevices) return;
  var original = P.designScreens.home, scrolled = false, D = P.aiDevices, IMAGE = 'assets/images/supercomputer/gb10-product.jpg';
  function priceText(p) { return p.saleState === 'stopped' ? '판매 중지' : p.saleState === 'on_sale' && p.price ? P.money(p.price) : '가격 확인 필요'; }
  function featured(items) {
    var f = items.filter(function (p) { return p.featuredRank !== null; }).sort(function (a, b) { return a.featuredRank - b.featuredRank; });
    return (f.length ? f : items).slice(0, 2);
  }
  function label(p) { return p.memory && p.storage ? p.memory + ' · SSD ' + p.storage : p.modelLabel || p.name; }
  function models(list) {
    if (list === null) return '<div class="gb-home-model is-loading"><div><span class="gb-model-label">AI 슈퍼컴퓨터</span><strong>가격 확인 중</strong></div></div>';
    if (!list.length) return '<a class="gb-home-model" href="' + D.listUrl + '"><div><span class="gb-model-label">AI 슈퍼컴퓨터</span><strong>제품 목록 보기</strong></div><span class="gb-model-go">목록 보기 ' + P.icon('arrow-right') + '</span></a>';
    return list.map(function (p) {
      return '<a class="gb-home-model" href="supercomputer.html?id=' + P.h(p.id) + '"><div><span class="gb-model-label">' + P.h(label(p)) + '</span><strong>' + P.h(priceText(p)) + '</strong></div><span class="gb-model-go">모델 보기 ' + P.icon('arrow-right') + '</span></a>';
    }).join('');
  }
  function fill(data) {
    var box = document.querySelector('[data-gb-home-models]');
    if (!box) return;
    var list = data ? featured(data.items) : [];
    box.innerHTML = models(list);
    box.classList.toggle('is-single', list.length < 2);
    // 대표 소개(사진·사양·가격 보기)는 대표 상품 1순위로 간다. 데이터가 없으면 목록으로 둔다.
    if (list.length) document.querySelectorAll('[data-gb-home-lead]').forEach(function (a) { a.href = 'supercomputer.html?id=' + encodeURIComponent(list[0].id); });
  }
  function jump() {
    if (scrolled || location.hash !== '#home-supercomputer') return;
    var el = document.getElementById('home-supercomputer');
    if (el) { scrolled = true; el.scrollIntoView({ block: 'start' }); }
  }
  P.designScreens.home = function () {
    var screen = original.apply(this, arguments), icon = P.icon, oldMount = screen.mount, cached = D.data;
    var markup = '<section class="hm-container gb-home" id="home-supercomputer" aria-labelledby="gb-home-title">' +
      '<div class="gb-home-hero"><div class="gb-home-copy"><p class="gb-home-eyebrow">AI 전용 장비 <span>DELL</span></p><h2 id="gb-home-title">책상 위에 놓는<br>나만의 AI 슈퍼컴퓨터.</h2><p class="gb-home-lead">AI 모델 실행과 개발을 위한<br>Dell GB10 완제품.</p><div class="gb-home-facts"><span>' + icon('cpu') + 'NVIDIA GB10</span><span>' + icon('memory') + '128GB 통합 메모리</span></div><div class="gb-home-actions"><a class="btn btn-primary" data-gb-home-lead href="' + D.listUrl + '">제품 사양·가격 보기 ' + icon('arrow-right') + '</a><a class="btn btn-outline gb-home-all" href="' + D.listUrl + '">전체 AI 슈퍼컴퓨터 보기</a></div></div><a class="gb-home-picture" data-gb-home-lead href="' + D.listUrl + '" aria-label="Dell Pro Max GB10 제품 자세히 보기"><img src="' + IMAGE + '" alt="Dell Pro Max GB10 AI 슈퍼컴퓨터" loading="lazy" width="600" height="600"><span>Dell Pro Max GB10</span></a></div>' +
      '<div class="gb-home-bottom"><div class="gb-home-models" data-gb-home-models>' + models(cached ? featured(cached.items) : null) + '</div><p class="gb-home-caption">로컬 AI 전용 완제품 · NVIDIA DGX OS <span>AI 설치·교육은 별도 상담</span></p></div></section>';
    if (screen.html.indexOf('<section class="hm-gaming') >= 0) screen.html = screen.html.replace('<section class="hm-gaming', markup + '<section class="hm-gaming');
    screen.mount = function () {
      if (oldMount) oldMount.apply(this, arguments);
      jump();
      if (cached) fill(cached);
      D.list().then(function (data) { fill(data); jump(); }, function () { fill(null); });
    };
    return screen;
  };
}());
