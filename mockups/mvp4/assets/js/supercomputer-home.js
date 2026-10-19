/* /mvp4 메인 AI 슈퍼컴퓨터 진열 (v15/v15.1 · 카테고리 확장 · v16 1번 AI 연구소 대표 진열, 2026-10-20).
 * 자리: AI 패키지 아래 · 게이밍 PC 위. 위쪽은 v16 대표 진열(GB10 장면·제목·성능 수치·조건·버튼, 실제 HTML),
 * 아래 모델 줄은 카테고리 데이터(GET /api/customer/supercomputers)의 대표 상품(featured_rank 순, 없으면 앞에서부터 2개)으로 그린다.
 * «AI 슈퍼컴퓨터 전체 보기»(v16 문구)는 카테고리 목록(supercomputers.html)으로 간다. 상품번호를 여기 적지 않는다.
 * 응답 전에는 «가격 확인 중», 실패·판매 확인 필요면 «가격 확인 필요». 링크는 /mvp4 내부 화면뿐이다.
 */
(function () {
  'use strict';
  var P = window.PAI;
  if (!P || !P.designScreens || !P.designScreens.home || !P.aiDevices) return;
  var original = P.designScreens.home, scrolled = false, D = P.aiDevices, SCENE = 'assets/images/supercomputer/gb10-ai-lab-v16-option1';
  function priceText(p) { return p.saleState === 'stopped' ? '판매 중지' : p.saleState === 'on_sale' && p.price ? P.money(p.price) : '가격 확인 필요'; }
  // X01(2026-10-20): 이 구획은 Dell Pro Max GB10 광고다(장면·이름·성능 수치가 GB10 것). 모델 줄과 대표 버튼은 같은 제품군
  // (상품 표시 정보의 model_group 'dell-pro-max-gb10')의 판매 가능한 모델로만 잇는다 — 다른 장비가 추가되거나 대표 순위가
  // 앞서도 그 가격·버튼을 이 광고에 끼우지 않는다. 제품군이 없으면 모델 줄은 목록 안내로, 대표 버튼은 감춘다.
  var AD_GROUP = 'dell-pro-max-gb10';
  function featured(items) {
    return items.filter(function (p) { return p.modelGroup === AD_GROUP && p.saleState !== 'stopped'; })
      .sort(function (a, b) { return (a.featuredRank === null ? 99 : a.featuredRank) - (b.featuredRank === null ? 99 : b.featuredRank) || (parseFloat(a.modelLabel || a.storage) || 0) - (parseFloat(b.modelLabel || b.storage) || 0) || Number(a.id) - Number(b.id); })
      .slice(0, 3);
  }
  D.adFamily = featured;
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
    // 대표 소개(사진·사양·가격 보기)는 이 광고 제품군의 첫 모델로 간다. 제품군이 없으면 버튼은 감추고 사진은 목록으로.
    document.querySelectorAll('[data-gb-home-lead]').forEach(function (a) {
      a.href = list.length ? 'supercomputer.html?id=' + encodeURIComponent(list[0].id) : D.listUrl;
      if (a.classList.contains('btn')) a.hidden = !list.length;
    });
  }
  function jump() {
    if (scrolled || location.hash !== '#home-supercomputer') return;
    var el = document.getElementById('home-supercomputer');
    if (el) { scrolled = true; el.scrollIntoView({ block: 'start' }); }
  }
  P.designScreens.home = function () {
    var screen = original.apply(this, arguments), icon = P.icon, oldMount = screen.mount, cached = D.data;
    // v16 1번(AI 연구소, 2026-10-20 대표 최종 승인): 문구 없는 장면 사진 위에 제목·성능 수치·조건·버튼을 실제 HTML 로 얹는다.
    // 수치 조건은 숫자 바로 아래에 읽히는 글자로 둔다(최대 2,000억 = FP4 로컬 추론 · 128GB = CPU·GPU 통합 메모리 · 최대 1PFLOP = FP4·희소성 기준).
    // 이 구획은 GB10 대표 진열이다 — 다른 카테고리 상품에 이 사진·수치를 쓰지 않는다. 가격은 아래 모델 줄이 실제 조회로 그린다.
    var metric = function (pre, value, label) { return '<li><strong>' + (pre ? '<small>' + pre + '</small> ' : '') + value + '</strong><span>' + label + '</span></li>'; };
    var markup = '<section class="hm-container gb-home gb16" id="home-supercomputer" aria-labelledby="gb-home-title">' +
      '<div class="gb16-hero"><figure class="gb16-scene"><img src="' + SCENE + '-1586.webp" srcset="' + SCENE + '-900.webp 900w, ' + SCENE + '-1586.webp 1586w" sizes="(max-width: 800px) 100vw, 1200px" alt="밝은 AI 연구소 공간에 놓인 Dell Pro Max GB10과 신경망 그래픽" width="1586" height="992" loading="lazy"></figure>' +
      '<div class="gb16-head"><p class="gb16-eyebrow">AI 전용 장비 <span aria-hidden="true">|</span> <b>DELL PRO MAX GB10</b></p><h2 id="gb-home-title">큰 AI를 다루는,<br>나만의 슈퍼컴퓨터.</h2><p class="gb16-lead">대형 AI 모델의 실행부터 개발·실험까지.</p></div>' +
      '<div class="gb16-body"><ul class="gb16-metrics" aria-label="제조사 공개 사양">' + metric('최대', '2,000억', '파라미터 모델 · FP4 로컬 추론') + metric('', '128GB', 'CPU·GPU 통합 메모리') + metric('최대', '1PFLOP', 'FP4 · 희소성 적용 기준') + '</ul>' +
      '<p class="gb16-device"><strong>NVIDIA GB10 Grace Blackwell</strong><span>128GB · SSD 2TB / 4TB</span></p>' +
      '<div class="gb-home-actions gb16-actions"><a class="btn btn-primary" data-gb-home-lead href="' + D.listUrl + '">제품 사양·가격 보기 ' + icon('arrow-right') + '</a><a class="gb16-all" href="' + D.listUrl + '">AI 슈퍼컴퓨터 전체 보기 ' + icon('arrow-right') + '</a></div>' +
      '<p class="gb16-notes">제조사 공개 사양 기준. 모델·정밀도·실행 환경에 따라 지원 범위와 성능이 달라집니다.<br>AI 설치·교육은 별도 상담입니다.</p></div></div>' +
      '<div class="gb-home-bottom"><div class="gb-home-models" data-gb-home-models>' + models(cached ? featured(cached.items) : null) + '</div></div></section>';
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
