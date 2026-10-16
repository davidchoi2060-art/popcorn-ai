// 첫 화면 아래 「팝콘PC가 맞춰 둔 PC」(2026-10-16 중헌 님 — 완제 조립PC와 관리자가 맞춰 놓은 PC를 보여 주는 것이 핵심).
// 운영자가 부품을 골라 만든 조립PC 중 고객 공개된 것만 서버가 준다(api/mvp3_custom_pcs.py · new-pcs.js 와 같은 응답).
// 가격은 서버가 오늘 부품 판매가로 다시 센 값만 쓴다(화면이 더하지 않는다). 못 불러오거나 공개된 것이 없으면 칸을 그리지 않는다.
(()=>{
'use strict';
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=x=>Number.isInteger(x)?x.toLocaleString('ko-KR')+'원':'금액 확인 중';
const MAX=6;
let items=[];
function html(){
  if(!items.length)return '';
  const card=x=>'<li><a class="welcome-pc" href="new-pcs.html#'+encodeURIComponent(x.configuration_id)+'"><strong>'+esc(x.title)+'</strong>'+
    (x.intro?'<span>'+esc(x.intro)+'</span>':'')+'<b>'+money(x.price)+'</b><small>자세히 보기 <img class="ui-icon" src="assets/icons/arrow-right.svg" alt=""></small></a></li>';
  return '<section class="welcome-pcs" aria-labelledby="welcome-pcs-title"><header><h3 id="welcome-pcs-title">팝콘PC가 맞춰 둔 PC</h3>'+
    (items.length>MAX?'<a href="new-pcs.html">전체 보기</a>':'')+'</header><ul>'+items.slice(0,MAX).map(card).join('')+'</ul></section>';
}
window.MVP3WelcomePcs={html};
(async()=>{
  try{
    const r=await fetch('/api/mvp3/custom-pcs',{credentials:'same-origin'});if(!r.ok)return;
    const d=await r.json();items=Array.isArray(d.items)?d.items.filter(x=>x&&x.configuration_id&&x.title):[];
    if(items.length)window.dispatchEvent(new Event('mvp3:welcome-pcs'));
  }catch{}
})();
})();
