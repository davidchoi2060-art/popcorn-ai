// Streamline Ultimate Color 아이콘 스와퍼 — 출처: https://www.streamlinehq.com (CC BY 4.0)
(function(){
var BASE=(location.pathname.indexOf('/admin/')>-1||location.pathname.indexOf('/mvp1/')>-1)?'../shared/icons/su/':'shared/icons/su/';
var MS={"add": "ms-add", "admin_panel_settings": "ms-admin_panel_settings", "api": "ms-api", "architecture": "ms-architecture", "arrow_forward": "ms-arrow_forward", "arrow_upward": "ms-arrow_upward", "auto_awesome": "ms-auto_awesome", "balance": "ms-balance", "bar_chart": "ms-bar_chart", "bolt": "ms-bolt", "build": "ms-build", "cable": "ms-cable", "chat": "ms-chat", "check_circle": "ms-check_circle", "chevron_right": "ms-chevron_right", "close": "ms-close", "code": "ms-code", "database": "ms-database", "description": "ms-description", "desktop_windows": "ms-desktop_windows", "dns": "ms-dns", "expand_more": "ms-expand_more", "filter_alt": "ms-filter_alt", "format_quote": "ms-format_quote", "forum": "ms-forum", "grid_view": "ms-grid_view", "hub": "ms-hub", "info": "ms-info", "inventory": "ms-inventory", "inventory_2": "ms-inventory_2", "lightbulb": "ms-lightbulb", "link": "ms-link", "local_fire_department": "ms-local_fire_department", "lock": "ms-lock", "login": "ms-login", "memory": "ms-memory", "monitor_heart": "ms-monitor_heart", "package_2": "ms-package_2", "payments": "ms-payments", "pending": "ms-pending", "person": "ms-person", "photo_camera": "ms-photo_camera", "photo_library": "ms-photo_library", "power_settings_new": "ms-power_settings_new", "question_answer": "ms-question_answer", "receipt_long": "ms-receipt_long", "rule": "ms-rule", "savings": "ms-savings", "science": "ms-science", "share": "ms-share", "shield": "ms-shield", "show_chart": "ms-show_chart", "speed": "ms-speed", "subdirectory_arrow_right": "ms-subdirectory_arrow_right", "support_agent": "ms-support_agent", "swap_horiz": "ms-swap_horiz", "sync": "ms-sync", "timer": "ms-timer", "touch_app": "ms-touch_app", "tune": "ms-tune", "verified": "ms-verified", "verified_user": "ms-verified_user", "visibility": "ms-visibility", "warning": "ms-warning", "movie": "ms-movie", "sports_esports": "ms-sports_esports", "volume_off": "ms-volume_off", "memory_alt": "ms-memory_alt", "hard_drive": "ms-hard_drive", "developer_board": "ms-developer_board", "dashboard": "ms-dashboard", "monitor": "ms-monitor", "interests": "ms-interests", "palette": "ms-palette", "recycling": "ms-recycling", "star": "ms-star", "wifi": "ms-wifi", "error": "ms-error", "expand_less": "ms-expand_less"};
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
 d.style.cssText='text-align:center;font-size:11px;color:#9a968d;padding:12px 0 16px;font-family:Pretendard,sans-serif;';
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
