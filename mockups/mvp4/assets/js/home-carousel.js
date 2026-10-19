(function () {
  'use strict';
  var P = window.PAI, h = P.h;
  var original = P.designScreens.home;
  function action(label, url, secondary) {
    return '<a class="btn '+(secondary?'btn-outline':'btn-primary')+'" href="'+h(url)+'">'+h(label)+P.icon('arrow-right')+'</a>';
  }
  function slides() {
    var catalog = P.designHref('catalog','normal'), chat = P.designHref('chat','welcome');
    return [
      {key:'showcase', label:'PC & AI', kicker:'GOOD PC, USEFUL AI', title:'좋은 PC에서,<br>쓸모 있는 <br>AI까지.', text:'PC 쇼핑과 업무용 AI 패키지를 한곳에서.', file:'hero-tv-commercial-clean.png', alt:'햇빛이 가득한 쇼룸에 전시된 모니터와 다양한 PC', actions:action('PC 둘러보기',catalog)+action('AI 패키지 보기','ai-packages.html',true)},
      {key:'gaming', label:'게이밍 PC', kicker:'PLAY YOUR WAY', title:'좋아하는 게임,<br>나답게 즐기다.', text:'나의 게임과 예산에 맞는 PC를 만나보세요.', file:'gaming-blue-clean.png', alt:'밝은 블루톤 공간에서 게이밍 PC와 함께하는 모습', actions:action('게이밍 PC 보기',P.designHref('catalog','normal',{category:'게이밍 PC'}))+action('AI와 게임 PC 찾기',chat,true)},
      {key:'ai', label:'AI 패키지', kicker:'AI FOR YOUR WORK', title:'일에 집중하도록,<br>AI는 당신 곁에.', text:'내 자료 정리부터 우리 팀의 업무까지.', file:'ai-lavender-clean.png', alt:'밝은 사무 공간에서 업무형 PC를 소개하는 모델', actions:action('AI 패키지 보기','ai-packages.html')+action('우리 업무로 도입 상담','ai-consult.html?package=business&intent=adoption',true)},
      {key:'people', label:'당신의 PC', kicker:'FIND YOUR EVERYDAY PC', title:'당신의 하루에,<br>딱 맞는 PC.', text:'작은 공간의 미니 PC부터 든든한 작업용 PC까지.', file:'model-showroom-clean.png', alt:'미니 PC와 화이트 PC를 소개하는 두 모델', actions:action('나에게 맞는 PC 찾기',chat)+action('모든 PC 둘러보기',catalog,true)},
      {key:'collection', label:'용도별 쇼핑', kicker:'PC COLLECTION', title:'게임도, 일도.<br>필요한 PC를 한곳에서.', text:'쓰임에 맞게 골라보세요.', file:'category-display-clean.png', alt:'게이밍 PC, 미니 PC, 업무형 AI PC의 세 가지 전시 공간', actions:''}
    ];
  }
  function render() {
    var items = slides();
    var slideHTML = items.map(function(s,i) {
      var collection = s.key==='collection' ? '<div class="hc-collections">'+
        [['게이밍 PC',P.designHref('catalog','normal',{category:'게이밍 PC'}),'high.webp'],['미니 PC',P.designHref('catalog','normal',{category:'미니 PC'}),'mini.png'],['AI 패키지','ai-packages.html','high.png']].map(function(c){return '<a href="'+h(c[1])+'"><img class="hc-tile-image" src="assets/images/'+c[2]+'" alt="" loading="lazy"><span>'+c[0]+'</span>'+P.icon('arrow-right')+'</a>';}).join('')+'</div>' : '';
      return '<article class="hc-slide hc-'+s.key+'" id="hc-slide-'+i+'" role="group" aria-roledescription="슬라이드" aria-label="'+(i+1)+' / '+items.length+' · '+h(s.label)+'"'+(i?' hidden inert':'')+'>'+
        '<img class="hc-image" src="assets/images/carousel/'+s.file+'" alt="'+h(s.alt)+'" width="2006" height="784" '+(i?'loading="lazy"':'fetchpriority="high"')+' draggable="false">'+
        '<div class="hc-copy"><p class="hc-kicker">'+s.kicker+'</p><h2>'+s.title+'</h2><p class="hc-description">'+s.text+'</p><div class="hc-actions">'+s.actions+'</div></div>'+collection+'</article>';
    }).join('');
    return '<section class="hc-carousel hm-container" aria-label="팝콘AI 추천 기획전" aria-roledescription="캐러셀" data-home-carousel><h1 class="visually-hidden">팝콘AI · 좋은 PC에서 쓸모 있는 AI까지</h1>'+
      '<div class="hc-stage">'+slideHTML+'</div><div class="hc-toolbar">'+
      '<div class="hc-selectors" role="group" aria-label="배너 선택">'+items.map(function(s,i){return '<button type="button" data-hc-go="'+i+'" aria-controls="hc-slide-'+i+'" aria-pressed="'+(!i)+'" aria-label="'+(i+1)+'번 배너: '+s.label+'"><span class="hc-dot"></span><span class="hc-label">'+s.label+'</span></button>';}).join('')+'</div>'+
      '<div class="hc-controls"><span class="hc-counter" aria-hidden="true"><b data-hc-current>01</b><span> / 05</span></span><button type="button" data-hc-prev aria-label="이전 배너">'+P.icon('arrow-left')+'</button><button type="button" data-hc-next aria-label="다음 배너">'+P.icon('arrow-right')+'</button><button type="button" class="hc-play" data-hc-toggle aria-label="배너 자동 넘김 정지">정지</button></div></div>'+
      '<p class="visually-hidden" data-hc-status role="status" aria-live="polite" aria-atomic="true"></p>'+
      '<a class="hc-chat" href="'+h(P.designHref('chat','welcome'))+'">'+P.icon('chat-circle')+'어떤 PC를 고를지 고민되나요? <strong>AI와 대화로 PC 찾기</strong>'+P.icon('arrow-right')+'</a></section>';
  }
  function mount() {
    var root=document.querySelector('[data-home-carousel]');
    if (!root || root.dataset.mounted) return;
    root.dataset.mounted='true';
    var panels=Array.from(root.querySelectorAll('.hc-slide')), selectors=Array.from(root.querySelectorAll('[data-hc-go]'));
    var toggle=root.querySelector('[data-hc-toggle]'), status=root.querySelector('[data-hc-status]');
    var motion=window.matchMedia('(prefers-reduced-motion: reduce)');
    var index=0, timer=null, manualPaused=motion.matches, hover=false, inView=true, touch=null, blockClickUntil=0;
    var interval=3000;
    function clear(){window.clearTimeout(timer);timer=null;}
    function blocked(){return manualPaused||hover||document.hidden||!inView||root.contains(document.activeElement);}
    function schedule(){clear();if(!blocked())timer=window.setTimeout(function(){show(index+1,false);},interval);}
    function paintToggle(){
      toggle.textContent=manualPaused?'재생':'정지';
      toggle.setAttribute('aria-label',manualPaused?'배너 자동 넘김 재생':'배너 자동 넘김 정지');
      root.dataset.autoplay=manualPaused?'paused':'enabled';
    }
    function show(next,manual){
      index=(next+panels.length)%panels.length;
      panels.forEach(function(panel,i){panel.hidden=i!==index;panel.inert=i!==index;});
      selectors.forEach(function(button,i){button.setAttribute('aria-pressed',String(i===index));});
      root.querySelector('[data-hc-current]').textContent=String(index+1).padStart(2,'0');
      root.dataset.activeSlide=String(index+1);
      if(manual){manualPaused=true;status.textContent=panels[index].getAttribute('aria-label');}
      paintToggle();schedule();
    }
    selectors.forEach(function(button,i){button.addEventListener('click',function(){show(i,true);});});
    root.querySelector('[data-hc-prev]').addEventListener('click',function(){show(index-1,true);});
    root.querySelector('[data-hc-next]').addEventListener('click',function(){show(index+1,true);});
    toggle.addEventListener('click',function(){manualPaused=!manualPaused;paintToggle();schedule();});
    root.addEventListener('mouseenter',function(){hover=true;clear();});
    root.addEventListener('mouseleave',function(){hover=false;schedule();});
    root.addEventListener('focusin',clear);
    root.addEventListener('focusout',function(){window.setTimeout(schedule,0);});
    root.querySelector('.hc-selectors').addEventListener('keydown',function(e){
      if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
      e.preventDefault();var next=e.key==='Home'?0:e.key==='End'?panels.length-1:index+(e.key==='ArrowRight'?1:-1);
      show(next,true);selectors[index].focus();
    });
    var stage=root.querySelector('.hc-stage');
    stage.addEventListener('touchstart',function(e){if(e.touches.length===1){touch={x:e.touches[0].clientX,y:e.touches[0].clientY};clear();}else{touch=null;}},{passive:true});
    stage.addEventListener('touchend',function(e){
      if(!touch){if(!e.touches.length)schedule();return;}
      var p=e.changedTouches[0],dx=p.clientX-touch.x,dy=p.clientY-touch.y;touch=null;
      if(Math.abs(dx)>55&&Math.abs(dx)>Math.abs(dy)*1.5){blockClickUntil=Date.now()+450;show(index+(dx<0?1:-1),true);}else schedule();
    },{passive:true});
    stage.addEventListener('touchcancel',function(){touch=null;schedule();},{passive:true});
    stage.addEventListener('click',function(e){if(Date.now()<blockClickUntil){e.preventDefault();e.stopPropagation();}},true);
    document.addEventListener('visibilitychange',schedule);
    window.addEventListener('pagehide',clear);
    window.addEventListener('pageshow',schedule);
    motion.addEventListener('change',function(){if(motion.matches){manualPaused=true;paintToggle();}schedule();});
    if('IntersectionObserver' in window){new IntersectionObserver(function(entries){inView=entries[0].isIntersecting;schedule();},{threshold:0.15}).observe(root);}
    show(0,false);
  }
  P.designScreens.home=function(options){
    var result=original(options), oldMount=result.mount;
    var start=result.html.indexOf('<section class="hm-hero ');
    var end=result.html.indexOf('</section>',start)+10;
    if(start<0||end<10)return result;
    result.html=result.html.slice(0,start)+render()+result.html.slice(end);
    result.mount=function(){if(oldMount)oldMount();mount();};
    return result;
  };
}());

