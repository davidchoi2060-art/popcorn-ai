// Streamline Ultimate Color 아이콘 스와퍼 — 출처: https://www.streamlinehq.com (CC BY 4.0)
(function(){
/* 아이콘 경로.
   HTTP 로 서빙될 때는 **루트 절대경로**를 쓴다 — `mockups/` 가 `/` 에 마운트돼 있으므로
   `/shared/icons/su/` 는 어느 경로에서 열어도 같은 파일을 가리킨다.
   예전에는 pathname 에 `/admin/`·`/mvp1/` 이 들어 있는지로 상대경로를 골랐는데,
   그건 화면이 그 두 폴더 밑에만 있다는 전제였다. 서버 렌더 화면(`/admin2/...`)에서
   전부 404 가 났다(2026-08-08). 경로를 추측하지 말고 마운트 지점을 쓴다.
   `file://` 로 직접 열 때는 루트가 드라이브 루트라 절대경로를 못 쓴다 — 그때만 예전 규칙. */
/* 2026-08-19 결함 수정 — hourglass_top(S1 로딩 문구)·ac_unit(SLOT_ICON.COOLER)이
   매핑에 없어 아이콘 이름이 글자 그대로 화면에 남았다(회귀가 hourglass_top을 잡았고,
   ac_unit은 JS 변수 주입이라 정규식 밖이라 확인자 DOM 실측으로 잡았다). 화면 쪽
   (s1-session.html)은 건드리지 않는다 — 매핑에 등재하는 것이 이 저장소의 방식이다.
     hourglass_top -> ms-hourglass_top.svg  새로 받은 파일. 같은 출처(Streamline
       Ultimate Color, CC BY 4.0)의 "loading"(제공처 슬러그, _map.json에 기록) — 이
       화면에서 "로딩 중" 문맥으로 쓰는 건 이 자리가 처음이라 재사용할 기존 아이콘이
       없었다.
     ac_unit -> ms-sync.svg  새 파일을 받지 않고 기존 파일을 재사용한다. COOLER는
       s3-detail.html·s4-cart.html에서 썸네일이 없을 때(PIMG에 COOLER만 빠져 있음)
       이미 "mode_fan"(-> 바로 아래서 이 파일과 동일한 ms-sync)으로 그려지고 있었다 —
       같은 부품에 새 아이콘을 만들면 화면마다 쿨러 아이콘이 달라진다. sync 파일을
       sync·recycling·mode_fan 셋이 이미 공유하는 이 파일의 기존 등재 방식 그대로,
       넷째로 얹었다. */
/* 2026-08-21 결함 수정 — s1-session.html checkVisual()·s2-result.html의 같은 로직
   (둘 다 「확인 보류」 = pass:null)이 ic:'help' 를 반환하는데 매핑이 없어 글자
   "help" 가 그대로 떴다(오늘 전 슬롯 기본값을 "(선택 안 함)"으로 바꾼 뒤로 이
   경로를 훨씬 자주 만난다). 같은 물결로 **JS 가 아이콘 이름을 만들어 넣는 자리
   전수**를 s1~s5·main-landing·my-*·index 11+1개 화면과 공용 JS에서 훑어, 매핑에
   없는 이름 넷을 더 찾았다(전부 서버/사용자 입력에 따라 갈리는 조건부 아이콘이라
   정적 HTML 스캔·회귀 [30]에는 안 잡힌다 — 그 검사는 마크업에 박힌 글자만 본다).
     help -> ms-pending.svg  새로 받지 않고 재사용. 이미 이 파일에 등재돼 있었지만
       (아래 "pending" 키) 어느 화면 JS 도 그 키로는 안 불렀다 — 정작 "확인 보류"
       뱃지가 실제로 쓰는 이름은 'help' 였다. 문서(시계 얹힌 파일) 도상이 "확인
       보류/대기 중" 의미로 s1-session.html 자체에서 이미 정적으로도 쓰이고 있어
       (조건 반영 단계 배지, 초기값) 화면 안에서 같은 뜻으로 겹쳐 쓰인다.
     category -> ms-grid_view.svg  새로 받지 않고 재사용. SLOT_ICON[k]||'category'
       (s1-session.html) 의 방어용 기본값이다 — 지금은 SLOTS(taxonomy.py, 8개)가
       SLOT_ICON 의 키 8개와 정확히 같아 실제로는 안 걸린다. 그래도 채워 둔다 —
       help 도 "지금은 안 걸린다"가 아니라 "오늘 배선이 바뀌어 갑자기 걸리기
       시작한" 사례였다.
     speaker -> ms-speaker.svg  새로 받았다(iconify, streamline-ultimate-color
       "speaker-1"). s2-result.html의 PICON.SPEAKER('스피커' 컴패니언 상품 카드)가
       직접 이 이름을 반환한다 — taxonomy.py PART_LABELS 에 SPEAKER="스피커"가
       정식 부품종류라 실제로 나온다. 재사용 후보(ms-volume_off, 음소거 배지가
       달린 스피커 도상)도 있었지만, "이 상품은 스피커다"를 말하는 자리에 "음소거"
       배지가 붙은 도상을 쓰는 건 오독을 부른다고 판단해 새로 받았다.
     videocam -> ms-photo_camera.svg  새로 받지 않고 재사용. 같은 PICON.WEBCAM
       ('웹캠') 대상 — 카메라 도상이 웹캠과 의미가 바로 겹쳐 재사용이 안전하다.
     volume_up -> ms-volume_up.svg  새로 받았다(iconify, streamline-ultimate-color
       "volume-control-up-3"). main-landing.html 히어로 영상의 음소거 해제 버튼이
       `vid.muted ? 'volume_off' : 'volume_up'` 로 토글한다 — volume_off 는 이미
       매핑돼 있었는데 그 짝인 volume_up 만 없었다(토글 버튼이라 같은 모양 재사용은
       음소거/재생 상태를 구분 못 하게 만든다).
   iconify 수신 절차(문서화된 절차가 없어 실제로 밟은 순서를 남긴다):
     ① https://api.iconify.design/search?query=<검색어>&prefix=streamline-ultimate-color
        로 그 컬렉션 안에서만 후보를 찾는다(다른 세트가 섞이면 화풍이 어긋난다).
     ② https://api.iconify.design/streamline-ultimate-color/<슬러그>.svg 로 원본을 그대로 받는다.
     ③ 기존 122개와 규격 대조 — width="1em" height="1em" viewBox="0 0 24 24",
        currentColor 미사용(0/122, 다색 세트라 고정 hex/gray 를 그대로 쓴다).
        어긋나면 이 세트가 아니다.
     ④ mockups/shared/icons/su/ms-<이름>.svg 로 저장, _map.json 에 "ms-<이름>": "<슬러그>"
        1행 추가(출처 표기용 기록 — CC BY 4.0 요구), 아래 MS 맵에 키를 더한다. */
var BASE=(location.protocol==='file:')
  ? ((location.pathname.indexOf('/admin/')>-1||location.pathname.indexOf('/mvp1/')>-1)?'../shared/icons/su/':'shared/icons/su/')
  : '/shared/icons/su/';
var MS={"add": "ms-add", "admin_panel_settings": "ms-admin_panel_settings", "api": "ms-api", "architecture": "ms-architecture", "arrow_forward": "ms-arrow_forward", "arrow_upward": "ms-arrow_upward", "auto_awesome": "ms-auto_awesome", "balance": "ms-balance", "bar_chart": "ms-bar_chart", "bolt": "ms-bolt", "build": "ms-build", "cable": "ms-cable", "chat": "ms-chat", "check_circle": "ms-check_circle", "chevron_right": "ms-chevron_right", "close": "ms-close", "code": "ms-code", "database": "ms-database", "description": "ms-description", "desktop_windows": "ms-desktop_windows", "dns": "ms-dns", "expand_more": "ms-expand_more", "filter_alt": "ms-filter_alt", "format_quote": "ms-format_quote", "forum": "ms-forum", "grid_view": "ms-grid_view", "hub": "ms-hub", "info": "ms-info", "inventory": "ms-inventory", "inventory_2": "ms-inventory_2", "lightbulb": "ms-lightbulb", "link": "ms-link", "local_fire_department": "ms-local_fire_department", "lock": "ms-lock", "login": "ms-login", "memory": "ms-memory", "monitor_heart": "ms-monitor_heart", "package_2": "ms-package_2", "payments": "ms-payments", "pending": "ms-pending", "person": "ms-person", "photo_camera": "ms-photo_camera", "photo_library": "ms-photo_library", "power_settings_new": "ms-power_settings_new", "question_answer": "ms-question_answer", "receipt_long": "ms-receipt_long", "rule": "ms-rule", "savings": "ms-savings", "science": "ms-science", "share": "ms-share", "shield": "ms-shield", "show_chart": "ms-show_chart", "speed": "ms-speed", "subdirectory_arrow_right": "ms-subdirectory_arrow_right", "support_agent": "ms-support_agent", "swap_horiz": "ms-swap_horiz", "sync": "ms-sync", "timer": "ms-timer", "touch_app": "ms-touch_app", "tune": "ms-tune", "verified": "ms-verified", "verified_user": "ms-verified_user", "visibility": "ms-visibility", "warning": "ms-warning", "movie": "ms-movie", "sports_esports": "ms-sports_esports", "volume_off": "ms-volume_off", "memory_alt": "ms-memory_alt", "hard_drive": "ms-hard_drive", "developer_board": "ms-developer_board", "dashboard": "ms-dashboard", "monitor": "ms-monitor", "interests": "ms-interests", "palette": "ms-palette", "recycling": "ms-recycling", "star": "ms-star", "wifi": "ms-wifi", "error": "ms-error", "expand_less": "ms-expand_less", "send": "ft-send", "workspace_premium": "ms-verified", "fact_check": "ms-rule", "task_alt": "ms-check_circle", "credit_card": "ms-payments", "rate_review": "ms-forum", "alternate_email": "ms-link", "arrow_back": "ms-chevron_right", "assignment_return": "ms-receipt_long", "check": "ms-check_circle", "history": "ms-timer", "leaderboard": "ms-bar_chart", "link_off": "ms-link", "local_shipping": "ms-package_2", "psychology": "ms-lightbulb", "schedule": "ms-timer", "arrow_downward": "ms-arrow_upward", "devices": "ms-monitor", "headphones": "ms-forum", "keyboard": "ms-grid_view", "mouse": "ms-touch_app", "mode_fan": "ms-sync", "hourglass_top": "ms-hourglass_top", "ac_unit": "ms-sync", "help": "ms-pending", "category": "ms-grid_view", "speaker": "ms-speaker", "videocam": "ms-photo_camera", "volume_up": "ms-volume_up"};
var FT={"alert-triangle": "ft-alert-triangle", "alert-octagon": "ft-alert-octagon", "list": "ft-list", "edit": "ft-edit", "percent": "ft-percent", "trending-up": "ft-trending-up", "shield": "ft-shield", "sliders": "ft-sliders", "repeat": "ft-repeat", "clock": "ft-clock", "archive": "ft-archive", "arrow-right": "ft-arrow-right", "bell": "ft-bell", "box": "ft-box", "check": "ft-check", "check-circle": "ft-check-circle", "clipboard": "ft-clipboard", "corner-left-up": "ft-corner-left-up", "cpu": "ft-cpu", "dollar-sign": "ft-dollar-sign", "external-link": "ft-external-link", "file-text": "ft-file-text", "globe": "ft-globe", "help-circle": "ft-help-circle", "home": "ft-home", "inbox": "ft-inbox", "info": "ft-info", "layers": "ft-layers", "lock": "ft-lock", "log-out": "ft-log-out", "message-square": "ft-message-square", "moon": "ft-moon", "pie-chart": "ft-pie-chart", "search": "ft-search", "send": "ft-send", "settings": "ft-settings", "sun": "ft-sun", "truck": "ft-truck", "upload-cloud": "ft-upload-cloud", "user": "ft-user", "user-plus": "ft-user-plus", "users": "ft-users"};
function mkimg(file,size){var img=document.createElement('img');img.src=BASE+file+'.svg';img.alt='';img.setAttribute('data-su','1');img.style.width=size+'px';img.style.height=size+'px';img.style.display='inline-block';img.style.verticalAlign='middle';return img;}
function swapMS(){
 var spans=document.querySelectorAll('span,i');
 for(var i=0;i<spans.length;i++){var el=spans[i];
  var st=el.getAttribute('style')||'';var cls=String(el.className||'');
  if(st.indexOf('Material Symbols')<0&&cls.indexOf('material-symbols')<0&&cls.indexOf('msym')<0)continue;
  if(el.getAttribute('data-su-done')&&el.querySelector('img'))continue; /* 정상 교체 상태 */
  var name=(el.textContent||'').trim();var file=MS[name];if(!file)continue;
  var fs=parseFloat(getComputedStyle(el).fontSize)||18;
  el.textContent='';el.appendChild(mkimg(file,Math.round(fs)));el.setAttribute('data-su-done','1');
 }
}
function swapFT(){
 var els=document.querySelectorAll('[data-feather]');
 for(var i=0;i<els.length;i++){var el=els[i];var name=el.getAttribute('data-feather');var file=FT[name];if(!file)continue;
  var w=parseFloat(getComputedStyle(el).width)||16;
  var img=mkimg(file,Math.round(w)||16);el.parentNode.replaceChild(img,el);
 }
 var svgs=document.querySelectorAll('svg.feather');
 for(var j=0;j<svgs.length;j++){var sv=svgs[j];var mcl=(sv.getAttribute('class')||'').match(/feather-([a-z-]+)/);if(!mcl)continue;
  var f2=FT[mcl[1]];if(!f2)continue;var sz=sv.getBoundingClientRect().width||16;
  var img2=mkimg(f2,Math.round(sz));sv.parentNode.replaceChild(img2,sv);
 }
}
function sweep(){swapMS();swapFT();}
function credit(){
 if(document.getElementById('su-credit'))return;
 var d=document.createElement('div');d.id='su-credit';
 d.style.cssText='text-align:center;font-size:11px;color:#9a968d;padding:12px 0 16px;font-family:var(--font);';
 d.innerHTML='아이콘: <a href="https://www.streamlinehq.com" target="_blank" rel="noopener" style="color:#8a8578;">Streamline Ultimate Color</a> · CC BY 4.0';
 document.body.appendChild(d);
}
function init(){sweep();credit();
 var mo=new MutationObserver(function(){clearTimeout(mo._t);mo._t=setTimeout(sweep,80);});
 mo.observe(document.body,{childList:true,subtree:true,characterData:true});
 setTimeout(sweep,400);setTimeout(sweep,1200);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
