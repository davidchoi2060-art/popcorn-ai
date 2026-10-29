(function () {
  'use strict';
  var P = window.PAI, h = P.h;
  var arrow = function () { return P.icon('arrow-right'); };
  // 상단 전체 카테고리(header-ui.js)와 같은 이름 -- PC 쇼핑 「용도·분류」를 따른다(2026-10-29 사장님).
  var categories = [
    ['게이밍', '게이밍 PC', 'categories/category-gaming-v14.png'],
    ['사무·업무용', '사무·업무용', 'categories/category-office-v14.png'],
    ['디자인·영상', '디자인·영상', 'categories/category-creator-v14.png'],
    ['미니 PC', '미니 PC', 'categories/category-mini-v14.png'],
    ['AI·고성능', 'AI·고성능 PC', 'categories/category-performance-v14.png'],
    ['주변기기', null, 'categories/category-peripherals-v14.png']
  ];
  function link(label, href, style) {
    return '<a class="btn ' + (style || 'btn-primary') + '" href="' + h(href) + '">' + h(label) + arrow() + '</a>';
  }
  function available(id) {
    var p = P.getCatalogProduct(id);
    return p && p.isSelling === true && p.stockQty !== 0 && p.statusKey !== 'oos' ? p : null;
  }
  function productRow(p, label) {
    if (!p) return '';
    var href = P.designHref('product', 'normal', { id: p.id });
    return '<article class="hm-product-row" data-product-id="' + h(p.id) + '">' +
      '<a class="hm-row-image" href="' + h(href) + '" aria-label="' + h(p.name) + ' 상품 상세"><img src="' + h(P.catalogImage(p)) + '" alt="' + h(p.name) + '" loading="lazy" width="180" height="180"></a>' +
      '<div class="hm-row-copy"><p class="hm-product-type">' + h(label) + '</p><h3><a href="' + h(href) + '">' + h(p.name) + '</a></h3><p class="hm-spec">' + h(p.summary) + '</p><strong class="hm-price">' + h(P.catalogMoney(p)) + '</strong></div>' +
      link('상품 보기', href, 'btn-outline') + '</article>';
  }
  P.designScreens.home = function () {
    var gaming = available('102112');
    var gamingHref = gaming ? P.designHref('product', 'normal', { id: gaming.id }) : P.designHref('catalog', 'normal', { category: '게이밍 PC' });
    var gamingProduct = gaming ? '<div class="hm-gaming-product" data-product-id="' + h(gaming.id) + '"><a class="hm-gaming-image" href="' + h(gamingHref) + '" aria-label="' + h(gaming.name) + ' 상품 상세"><img src="' + h(P.catalogImage(gaming)) + '" alt="' + h(gaming.name) + '" loading="lazy" width="260" height="260"></a><div class="hm-gaming-copy"><p class="hm-product-type">화이트 게이밍 PC</p><h3><a href="' + h(gamingHref) + '">' + h(gaming.name) + '</a></h3><p class="hm-spec">' + h(gaming.summary) + '</p><strong class="hm-price">' + h(P.catalogMoney(gaming)) + '</strong><div class="hm-gaming-actions">' + link('이 PC 자세히 보기', gamingHref, 'btn-blue') + '<a class="hm-text-link" href="' + h(P.designHref('chat', 'product', { id: gaming.id })) + '">' + P.icon('chat-circle') + '이 PC, 나에게 맞을까? ' + arrow() + '</a></div></div></div>' : '<div class="hm-gaming-fallback">' + link('게이밍 PC 보기', gamingHref, 'btn-blue') + '</div>';
    return {
      html: '<div class="hm-home">' +
        '<section class="hm-hero hm-container" aria-labelledby="hm-hero-title"><img class="hm-hero-scene" src="assets/images/hero-pc.png" alt="모니터와 미니 PC, 화이트 PC, 고성능 PC" width="1774" height="887" fetchpriority="high"><div class="hm-hero-copy"><h1 id="hm-hero-title">좋은 PC에서,<br>쓸모 있는 AI까지.</h1><p>PC 쇼핑과 업무용 AI 패키지를 한곳에서.</p><div class="hm-hero-actions">' + link('PC 둘러보기', P.designHref('catalog', 'normal')) + link('AI 패키지 보기', 'ai-packages.html', 'btn-outline') + '</div><a class="hm-hero-chat" href="' + h(P.designHref('chat', 'welcome')) + '">' + P.icon('chat-circle') + '<strong>AI와 대화로 PC 찾기</strong>' + arrow() + '</a></div></section>' +
        '<nav class="hm-categories hm-category-scenes hm-container" id="home-categories" aria-label="용도별 PC와 주변기기">' + categories.map(function (c) { return '<a href="' + h(c[1] ? P.designHref('catalog', 'normal', { category: c[1] }) : 'peripherals.html') + '"><img src="assets/images/' + c[2].replace(/\.png$/, '-768.webp') + '" srcset="assets/images/' + c[2].replace(/\.png$/, '-768.webp') + ' 768w, assets/images/' + c[2].replace(/\.png$/, '-1536.webp') + ' 1536w" sizes="(max-width: 600px) 46vw, 380px" alt="" loading="lazy" width="1536" height="1024"><span>' + h(c[0]) + arrow() + '</span></a>'; }).join('') + '</nav>' +
        '<section class="hm-ai hm-container" id="home-business" aria-labelledby="hm-ai-title"><div class="hm-section-heading"><p class="hm-kicker">업무 도입 패키지</p><h2 id="hm-ai-title">일에 집중하도록, AI는 당신 곁에.</h2></div><a class="hm-scene-link" href="ai-detail.html?package=business" aria-label="업무형 로컬 AI 패키지 자세히 보기"><img class="hm-business-scene" src="assets/images/model-business.png" alt="밝은 사무실에서 업무에 집중하는 모습" loading="lazy" width="1536" height="1024"></a><div class="hm-ai-card"><a class="hm-ai-product" href="ai-detail.html?package=business" aria-label="팝콘AI 업무형 로컬 AI 구성 보기"><img src="assets/images/high-transparent.png" alt="업무형 로컬 AI 패키지 PC" loading="lazy" width="1254" height="1254"></a><div class="hm-ai-copy"><a href="ai-detail.html?package=business"><h3>팝콘AI 업무형 로컬 AI</h3></a><ul class="hm-ai-features">' + [['file-magnifying-glass-duotone','사내 문서 검색','documents'],['users-three-duotone','회의록 정리','meetings'],['chat-text-duotone','고객 답변 초안','replies']].map(function (f) { return '<li><a href="' + (/^(documents|meetings|replies)$/.test(f[2]) ? 'ai-service.html?package=business&amp;use=' + f[2] : 'ai-consult.html?package=business&amp;use=' + f[2]) + '">' + P.icon(f[0]) + '<span>' + f[1] + '</span></a></li>'; }).join('') + '</ul><p class="hm-ai-includes">PC 구성 · AI 설치 · 사용 안내</p></div><div class="hm-ai-actions">' + link('패키지 구성 보기','ai-detail.html?package=business','btn-outline') + link('우리 업무로 도입 상담하기','ai-consult.html?package=business&intent=adoption') + '</div><p class="hm-ai-scope-note">업무·자료 확인 후 구성과 지원 범위를 안내합니다.</p><div class="hm-package-links"><a href="ai-detail.html?package=basic"><span class="hm-package-icon">' + P.icon('file-text-duotone') + '</span><span><strong>기본형</strong><b>내 자료 AI 비서</b><small>학습 · 자료 요약 · 글쓰기 지원</small></span>' + P.icon('caret-right') + '</a><a href="ai-detail.html?package=advanced"><span class="hm-package-icon">' + P.icon('code-duotone') + '</span><span><strong>고급형</strong><b>전문 제작 AI</b><small>이미지 제작 · 개발 보조</small></span>' + P.icon('caret-right') + '</a></div></div></section>' +
        '<section class="hm-gaming hm-container" aria-labelledby="hm-gaming-title"><div class="hm-section-heading"><p class="hm-kicker">GAMING PC</p><h2 id="hm-gaming-title">좋아하는 게임, 나답게 즐기다.</h2></div><a class="hm-scene-link" href="' + h(P.designHref('catalog','normal',{category:'게이밍 PC'})) + '" aria-label="게이밍 PC 둘러보기"><img class="hm-gaming-scene" src="assets/images/model-gaming.png" alt="게이밍 PC와 함께 게임을 즐기는 모습" loading="lazy" width="1536" height="1024"></a>' + gamingProduct + '</section>' +
        '<section class="hm-other hm-container" aria-labelledby="hm-other-title"><div class="hm-other-heading"><h2 id="hm-other-title">다른 용도의 PC</h2><a class="hm-text-link" href="' + h(P.designHref('catalog','normal')) + '">전체 보기 ' + arrow() + '</a></div>' + productRow(available('113314'),'사무 · 업무용') + '<article class="hm-product-row hm-mini-row"><a class="hm-row-image" href="' + h(P.designHref('catalog','normal',{category:'미니 PC'})) + '" aria-label="미니 PC 전체 보기"><img src="assets/images/mini.png" alt="은색 미니 PC" loading="lazy" width="180" height="180"></a><div class="hm-row-copy"><h3>미니 PC</h3><p class="hm-spec">공간에 맞게, 필요한 성능으로.</p></div>' + link('구성 보기',P.designHref('catalog','normal',{category:'미니 PC'}),'btn-outline') + '</article>' + productRow(available('110994'),'디자인 · 작업용') + '</section>' +
        '<section class="hm-finder hm-container" aria-labelledby="hm-finder-title"><div><p class="hm-kicker">AI PC FINDER</p><h2 id="hm-finder-title">나에게 맞는 PC,<br>대화로 찾아볼까요?</h2><p>게임, 작업, 예산을 편하게 알려주세요.</p></div><form id="ds-home-question"><label for="ds-home-text">어떤 PC가 필요한가요?</label><textarea id="ds-home-text" maxlength="10000" placeholder="배그랑 영상 편집을 하고, 예산은 150만 원이에요."></textarea><button class="btn btn-primary" type="submit">AI로 PC 찾기 ' + arrow() + '</button></form></section>' +
        '<nav class="hm-services hm-container" aria-label="PC 구매 도우미">' + [['monitor','PC 추천받기','용도에 맞는 구성을 찾아보세요.',P.designHref('chat','welcome')],['squares-four','PC 비교하기','관심 있는 PC를 나란히 살펴보세요.',P.designHref('compare','normal')],['headset','배송 · A/S 안내','구매 전 궁금한 내용을 확인하세요.','support.html#sales-policy'],['clipboard-text','내 견적','보관한 견적을 확인하세요.',P.designHref('saved','normal')]].map(function (s) { return '<a href="' + h(s[3]) + '">' + P.icon(s[0]) + '<span><strong>' + s[1] + '</strong><small>' + s[2] + '</small></span>' + P.icon('caret-right') + '</a>'; }).join('') + '</nav></div>',
      mount: function () {
        document.getElementById('ds-home-question').addEventListener('submit', function (e) {
          e.preventDefault();
          var text = document.getElementById('ds-home-text').value;
          try { sessionStorage.setItem('pai-design-question', text); }
          catch (ignore) {
            var notice = document.getElementById('ds-home-transfer-error');
            if (!notice) { notice = document.createElement('p'); notice.id = 'ds-home-transfer-error'; notice.className = 'ds-form-error'; notice.setAttribute('role', 'alert'); this.appendChild(notice); }
            notice.textContent = '입력한 내용을 이어가지 못했어요. 내용은 그대로 두었으니 브라우저 설정을 확인해 주세요.';
            return;
          }
          location.href = P.designHref('chat', text ? 'clarify' : 'welcome');
        });
        // Search shortcuts use the same category vocabulary as the v7 catalog.
        var shortcuts = document.querySelectorAll('.search-suggestions a');
        ['게이밍 PC','사무·업무용','미니 PC'].forEach(function (category, index) {
          if (shortcuts[index]) shortcuts[index].href = P.designHref('catalog','normal',{category:category});
        });
      }
    };
  };
}());
