(function () {
  'use strict';
  var P = window.PAI;
  var h = P.h;
  function photo(file, alt, className, eager) {
    return '<img class="' + h(className || '') + '" src="' + h(P.image(file)) + '" alt="' + h(alt) + '" loading="' + (eager ? 'eager' : 'lazy') + '" decoding="async">';
  }
  function scene(key, fallback) {
    var item = (P.data.scenes || {})[key];
    return typeof item === 'string' ? item : (item && item.image ? item.image : fallback);
  }
  function link(label, href, style) {
    return '<a class="btn ' + (style || 'btn-primary') + '" href="' + h(href) + '">' + h(label) + P.icon('arrow-right') + '</a>';
  }
  P.pages.home = function () {
    var products = P.data.products || [];
    var gaming = products.find(function (p) { return p.id === 'gaming'; });
    var office = products.find(function (p) { return p.id === 'office'; });
    var business = P.data.packages.business;
    var categories = [
      ['게이밍 PC', 'gaming.webp', P.href('pcs', { purpose: 'gaming' })],
      ['사무용 PC', 'office.png', P.href('pcs', { purpose: 'office' })],
      ['디자인·작업용', 'creative.webp', P.href('pcs', { purpose: 'creative' })],
      ['미니 PC', 'mini.png', P.href('pcs', { form: 'mini' })],
      ['고성능 PC', 'high.png', P.href('pcs', { tier: 'high' })],
      ['모니터·주변기기', 'peripherals.png', P.href('peripherals')]
    ];
    var categoryHtml = categories.map(function (c) {
      return '<a class="home-category" href="' + h(c[2]) + '">' + photo(c[1], '', 'category-image') + '<span>' + h(c[0]) + P.icon('arrow-right') + '</span></a>';
    }).join('');
    var uses = business.uses.map(function (u) {
      return '<li>' + P.icon(u.icon) + '<span>' + h(u.title) + '</span></li>';
    }).join('');
    var packages = ['basic', 'advanced'].map(function (id) {
      var item = P.data.packages[id];
      return '<a class="home-package-shortcut" href="' + P.href('ai-detail', { package: id }) + '"><span class="shortcut-icon">' + P.icon(item.uses[0].icon) + '</span><span><span class="shortcut-title"><b>' + h(item.type) + '</b><strong>' + h(item.name) + '</strong></span><span class="shortcut-description">' + h(item.description) + '</span></span>' + P.icon('caret-right') + '</a>';
    }).join('');
    var others = [
      { title: '사무·업무용', image: office.image, model: scene('office', 'model-business.png'), description: office.summary, price: P.money(office.price), label: '상품 보기', href: P.href('pc-detail', { id: 'office' }) },
      { title: '미니 PC', image: 'mini.png', model: scene('mini', 'model-business.png'), description: '작지만 실용적인 성능', label: '구성 살펴보기', href: P.href('pcs', { form: 'mini' }) },
      { title: '디자인·작업용', image: 'creative.webp', model: scene('creativeCard', 'model-creative.png'), description: '영상 편집 · 그래픽 · 3D 작업', label: '구성 살펴보기', href: P.href('pcs', { purpose: 'creative' }) }
    ].map(function (c) {
      return '<article class="home-other-card"><div class="other-scene">' + photo(c.model, c.title + ' 사용 장면', '') + '</div><div class="other-product"><a class="other-product-image" href="' + c.href + '" aria-label="' + h(c.title) + ' 보기">' + photo(c.image, c.title + ' PC', '') + '</a><div class="other-product-copy"><h3><a href="' + c.href + '">' + h(c.title) + '</a></h3><p>' + h(c.description) + '</p>' + (c.price ? '<strong class="other-price">' + h(c.price) + '</strong>' : '') + link(c.label, c.href, 'btn-outline btn-small') + '</div></div></article>';
    }).join('');
    var services = [
      ['chat-text-duotone', 'AI로 내 PC 찾기', '용도와 예산을 편하게 말씀해주세요.', P.href('pc-finder')],
      ['file-text', '맞춤 견적', '원하는 구성으로 견적을 받아보세요.', P.href('bridge', { target: 'custom' })],
      ['headset', '배송·A/S 안내', '구매 전 필요한 안내를 확인하세요.', P.href('support') + '#sales-policy'],
      ['clipboard-text', '내 견적', '저장한 견적을 확인하세요.', P.href('bridge', { target: 'saved' })]
    ].map(function (s) {
      return '<a class="home-service" href="' + h(s[3]) + '">' + P.icon(s[0]) + '<span><strong>' + h(s[1]) + '</strong><small>' + h(s[2]) + '</small></span>' + P.icon('caret-right') + '</a>';
    }).join('');
    return {
      html: '<div class="home-page">' +
        '<section class="home-hero home-hero-ai container" aria-labelledby="home-hero-title"><div class="hero-copy"><h1 id="home-hero-title">좋은 PC에서,<br>쓸모 있는 AI까지.</h1><p>PC 쇼핑과 업무용 AI 패키지를 한곳에서.</p><div class="hero-actions">' + link('AI로 내 PC 찾기', P.href('pc-finder')) + link('PC 둘러보기', P.href('pcs'), 'btn-outline') + '</div></div>' +
        '<div class="home-ai-scene" data-home-ai-motion aria-label="용도에 맞는 PC 선택을 소개하는 이미지">' + photo('hero-pc.png', '모니터와 다양한 크기의 PC', 'home-ai-scene-product', true) +
        photo('ai-popcorn-core-v5.png', '팝콘AI를 나타내는 입체 오브젝트', 'home-ai-core', true) +
        '<div class="home-ai-scene-caption"><span>AI와 함께 고르는 PC</span><strong>용도부터, 나에게 맞게.</strong></div>' +
        '<ul class="home-ai-keywords" aria-label="PC를 찾는 용도"><li class="home-ai-keyword is-active" data-home-ai-keyword>' + P.icon('game-controller') + '<span>게임</span></li><li class="home-ai-keyword" data-home-ai-keyword>' + P.icon('video-camera') + '<span>영상 편집</span></li><li class="home-ai-keyword" data-home-ai-keyword>' + P.icon('monitor') + '<span>업무</span></li></ul>' +
        '<button type="button" class="home-ai-motion-control" data-home-ai-motion-toggle aria-pressed="false" aria-label="소개 모션 멈추기">모션 멈추기</button></div></section>' +
        '<section class="home-finder container" aria-labelledby="home-finder-title"><div class="home-finder-intro"><span class="home-finder-symbol">' + P.icon('chat-text-duotone') + '</span><div><p class="eyebrow">AI PC FINDER</p><h2 id="home-finder-title">어떤 PC가 필요한가요?</h2><p>용도와 예산만 알려주세요. 함께 찾아드릴게요.</p></div></div><form class="home-finder-form" data-home-finder><label class="visually-hidden" for="home-finder-input">원하는 PC의 용도와 예산</label><div class="home-finder-input-row"><textarea id="home-finder-input" name="request" rows="2" maxlength="10000" placeholder="배그랑 영상 편집을 하고, 예산은 150만 원이에요."></textarea><button class="btn btn-primary" type="submit">AI로 내 PC 찾기 ' + P.icon('arrow-right') + '</button></div><div class="home-finder-suggestions"><span>이렇게 시작해보세요</span><button type="button" data-finder-prompt="게임용 PC를 찾고 있어요.">게임용 PC</button><button type="button" data-finder-prompt="영상 편집용 PC를 찾고 있어요.">영상 편집</button><button type="button" data-finder-prompt="어떤 PC가 필요한지 아직 잘 모르겠어요.">아직 잘 모르겠어요</button></div><p class="error" data-home-finder-error role="alert" hidden></p></form></section>' +
        '<nav class="home-categories container" aria-label="PC 용도별 상품">' + categoryHtml + '</nav>' +
        '<section class="home-ai container" aria-labelledby="home-ai-title"><div class="business-feature"><div class="business-copy"><p class="eyebrow">AI 패키지 · 기획 상품</p><h2 id="home-ai-title">일에 집중하도록,<br>AI는 당신 곁에.</h2><a class="business-name" href="' + P.href('ai-detail', { package: 'business' }) + '">팝콘AI 업무형 로컬 AI</a><div class="business-offer"><a class="business-product" href="' + P.href('ai-detail', { package: 'business' }) + '" aria-label="업무형 AI 패키지 자세히 보기">' + photo(business.image, '업무형 AI용 PC', '') + '</a><div class="business-use-copy"><ul class="business-uses">' + uses + '</ul><p class="business-includes">PC · AI 설치 · 사용 교육</p></div></div><div class="business-actions">' + link('견적 문의', P.href('ai-consult', { package: 'business', intent: 'quote' }), 'btn-outline') + link('우리 업무로 도입 상담하기', P.href('ai-consult', { package: 'business', intent: 'adoption' })) + '</div></div><figure class="business-model">' + photo(business.model, 'PC로 업무에 집중하는 모습', '') + '</figure></div><div class="home-package-shortcuts">' + packages + '</div><p class="home-ai-note">필요한 구성과 지원 범위를 상담해보세요.</p></section>' +
        '<section class="home-gaming container" aria-labelledby="home-gaming-title"><figure class="gaming-model">' + photo(scene('gamingHero', 'model-gaming.png'), '새 게이밍 PC 세트를 앞에 두고 팔을 벌려 기뻐하는 학생', '') + '</figure><div class="gaming-copy"><p class="eyebrow">GAMING PC</p><h2 id="home-gaming-title">좋아하는 게임,<br>나답게 즐기다.</h2><div class="gaming-offer"><a class="gaming-product-image" href="' + P.href('pc-detail', { id: 'gaming' }) + '" aria-label="QHD 게이밍 PC 자세히 보기">' + photo(gaming.image, 'QHD 게이밍 PC', '') + '</a><div class="gaming-product-copy"><h3><a href="' + P.href('pc-detail', { id: 'gaming' }) + '">' + h(gaming.name) + '</a></h3><p>' + h(gaming.summary) + '</p><strong class="home-gaming-price">' + h(P.money(gaming.price)) + '</strong>' + link('게이밍 PC 보기', P.href('pc-detail', { id: 'gaming' }), 'btn-blue') + '</div></div></div></section>' +
        '<section class="home-other container" aria-labelledby="home-other-title"><h2 id="home-other-title" class="section-title">다른 용도의 PC도 만나보세요</h2><div class="home-other-grid">' + others + '</div></section>' +
        '<nav class="home-services container" aria-label="PC 선택과 구매 지원">' + services + '</nav></div>',
      mount: function () {
        if (P.homeAiMotion && typeof P.homeAiMotion.mount === 'function') P.homeAiMotion.mount();
        var form=document.querySelector('[data-home-finder]');
        if (!form) return;
        var input=form.querySelector('textarea'), error=form.querySelector('[data-home-finder-error]');
        form.querySelectorAll('[data-finder-prompt]').forEach(function(button){
          button.addEventListener('click',function(){
            var prompt=button.dataset.finderPrompt;
            var next=input.value ? input.value+'\n'+prompt : prompt;
            if(next.length>10000){error.textContent='한 번에 10,000자까지 적을 수 있어요. 내용을 나누어 주세요.';error.hidden=false;input.focus();return;}
            input.value=next;input.focus();error.hidden=true;
          });
        });
        form.addEventListener('submit',function(event){
          event.preventDefault();
          try {P.finderEntry.start({text:input.value,source:'home'});}
          catch(exception){error.textContent='입력한 내용을 이어가지 못했어요. 브라우저 설정을 확인한 뒤 다시 시도해 주세요.';error.hidden=false;input.focus();}
        });
      }
    };
  };
}());
