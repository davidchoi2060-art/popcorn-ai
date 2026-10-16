// 첫 화면 「새로 구성된 PC」(2026-10-16 중헌 님 — 관리자가 부품으로 직접 용도를 맞춰 구성한 완제조립PC를 보여 준다.
// 「새로 나온 PC」라는 이름은 쓰지 않는다). 운영자가 부품을 골라 만든 조립PC 중 고객 공개된 것만 서버가 준다
// (api/mvp3_custom_pcs.py · new-pcs.js 와 같은 응답). 가격은 서버가 오늘 부품 판매가로 다시 센 값만 쓰고(화면이 더하지 않는다),
// 용도는 서버가 부품 사양으로 판정한 usages 만 적는다. 못 불러오거나 공개된 것이 없으면 칸을 그리지 않는다.
(()=>{
'use strict';
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=x=>Number.isInteger(x)?x.toLocaleString('ko-KR')+'원':'금액 확인 중';
const MAX=6,MAX_USAGES=3,KEY_SLOTS=['CPU','GPU'];
const PLACEHOLDER=/^운영자가 부품을 선택한/;   // api/custom_pc.PLACEHOLDER_INTRO — 고객 문구가 아니다
let items=[];
function blurb(x){
  if(x.scene)return x.scene;
  return x.intro&&!PLACEHOLDER.test(x.intro)?x.intro:'';
}
function card(x){
  const usages=(Array.isArray(x.usages)?x.usages:[]).slice(0,MAX_USAGES);
  const keys=(Array.isArray(x.parts)?x.parts:[]).filter(p=>KEY_SLOTS.includes(p.slot));
  const text=blurb(x);
  return '<li><a class="welcome-pc" href="new-pcs.html#'+encodeURIComponent(x.configuration_id)+'">'+
    (usages.length?'<span class="welcome-pc-usages" aria-label="맞춘 용도">'+usages.map(u=>'<em>'+esc(u.usage)+' '+esc(u.level)+'</em>').join('')+'</span>':'')+
    '<strong>'+esc(x.title)+'</strong>'+(text?'<span>'+esc(text)+'</span>':'')+
    (keys.length?'<dl class="welcome-pc-parts">'+keys.map(p=>'<div><dt>'+esc(p.slot_label)+'</dt><dd>'+esc(p.name)+'</dd></div>').join('')+'</dl>':'')+
    '<b>'+money(x.price)+'</b><small>자세히 보기 <img class="ui-icon" src="assets/icons/arrow-right.svg" alt=""></small></a></li>';
}
function html(){
  if(!items.length)return '';
  return '<section class="welcome-pcs" aria-labelledby="welcome-pcs-title"><header><div><h3 id="welcome-pcs-title">새로 구성된 PC</h3>'+
    '<p>팝콘PC가 용도에 맞춰 부품을 직접 골라 구성한 완제조립PC예요.</p></div>'+
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
