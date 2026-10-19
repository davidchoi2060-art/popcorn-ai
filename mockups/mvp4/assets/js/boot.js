(function(){
  'use strict';
  var P=window.PAI, name=document.body.dataset.page||'home';
  if(!P||typeof P.pages[name]!=='function') { document.getElementById('app').textContent='화면을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.'; return; }
  var view=P.pages[name]();
  document.getElementById('app').innerHTML=P.shell(view.html);
  P.bindShell();
  if(typeof view.mount==='function') view.mount();
  if(location.hash){var anchor=document.getElementById(location.hash.slice(1));if(anchor)requestAnimationFrame(function(){anchor.scrollIntoView();});}
}());
