(function(){
  'use strict';
  var P=window.PAI;
  if(!P||!P.designScreens||!P.designScreens.catalog)return;
  var original=P.designScreens.catalog;
  P.designScreens.catalog=function(ctx){
    var result=original(ctx);
    var header='<header class="cb-banner" aria-labelledby="cb-title">'+
      '<img class="cb-art" src="assets/images/catalog-ai-discovery.png" alt="다양한 PC와 밝은 팝콘 모양 AI 코어가 연결된 모습" width="2009" height="783" fetchpriority="high">'+
      '<div class="cb-copy"><p class="cb-kicker">PC SHOP · AI PC FINDER</p>'+
      '<h1 id="cb-title">내게 맞는 PC를<br>찾아보세요.</h1>'+
      '<p class="cb-description">상품명과 부품을 살펴보고,<br class="cb-mobile-break"> 필요한 구성을 골라보세요.</p>'+
      '<a class="btn cb-ai-button" href="'+P.h(P.designHref('chat','welcome'))+'">'+P.icon('chat-circle')+'<span>AI와 대화로 PC 찾기</span>'+P.icon('arrow-right')+'</a>'+
      '<p class="cb-support">용도와 예산부터 편하게 이야기해 주세요.</p></div></header>';
    result.html=result.html.replace(/<header class="dp-catalog-heading">[\s\S]*?<\/header>/,header);
    return result;
  };
}());

