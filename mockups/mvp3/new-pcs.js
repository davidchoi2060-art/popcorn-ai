// 「새로 나온 PC」(부품 상품화 4단계 · api/mvp3_custom_pcs.py). 운영자가 부품을 골라 만든 조립PC 중
// 고객 공개된 것만 서버가 준다. 가격은 서버가 오늘 부품 판매가로 다시 센 값만 쓴다(화면이 더하지 않는다).
// 쇼핑몰 상품번호가 없으므로 구매는 구매 상담 신청(api/mvp3_purchase_inquiry.py)으로 받는다.
(()=>{
'use strict';
const list=document.querySelector('#new-pcs-list'),noteEl=document.querySelector('#new-pcs-note');
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=x=>Number(x).toLocaleString('ko-KR')+'원';
let items=[],form=null,openId=null,sending=false,result={};
async function call(method,url,body){
  const r=await fetch(url,{method,credentials:'same-origin',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});
  let d={};try{d=await r.json();}catch{}
  if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:r.status===422?'입력한 내용을 확인해 주세요.':'잠시 후 다시 시도해 주세요.');
  return d;
}
function formHtml(id){
  const r=result[id]||{};
  if(r.done)return `<p class="new-pc-done" role="status">${esc(r.done)}</p>`;
  return `<form class="new-pc-form" data-form="${esc(id)}" novalidate>
    <label>이름(선택)<input name="name" maxlength="30" autocomplete="name"></label>
    <label>전화번호<input name="phone" maxlength="20" inputmode="tel" autocomplete="tel" placeholder="010-1234-5678"></label>
    <label>이메일<input name="email" maxlength="120" type="email" autocomplete="email"></label>
    <label>남길 말(선택)<textarea name="message" maxlength="500" rows="3" placeholder="예: 다음 주 안에 받고 싶어요"></textarea></label>
    <label class="consent"><input type="checkbox" name="consent"><span>${esc(form?.consent_text||'')}</span></label>
    ${r.error?`<p class="new-pc-error" role="alert">${esc(r.error)}</p>`:''}
    <button class="primary" type="submit" ${sending?'disabled':''}>${sending?'보내는 중…':'구매 상담 신청 보내기'}</button>
  </form>`;
}
function card(x){
  const id=x.configuration_id;
  const parts=x.parts.map(p=>`<tr><th scope="row">${esc(p.slot_label)}</th><td>${esc(p.name)}${p.quantity>1?' × '+p.quantity:''}</td></tr>`).join('');
  const benefits=x.benefits.length?`<h3>이런 점이 좋아요</h3><ul>${x.benefits.map(b=>`<li><strong>${esc(b.title)}</strong> ${esc(b.text)}</li>`).join('')}</ul>`:'';
  const checks=x.checks.length?`<h3>구매 전에 확인해 주세요</h3><ul>${x.checks.map(c=>`<li>${esc(c)}</li>`).join('')}</ul>`:'';
  return `<article class="new-pc" data-pc="${esc(id)}"><div class="new-pc-head"><div><h2>${esc(x.title)}</h2></div>
    <div class="new-pc-price"><strong>${money(x.price)}</strong><small>${esc(x.price_note)}</small></div></div>
    <p>${esc(x.intro)}</p>${x.scene?`<p class="muted">${esc(x.scene)}</p>`:''}
    <table class="new-pc-parts"><caption class="sr-only">부품 구성</caption><tbody>${parts}</tbody></table>${benefits}${checks}
    <p class="muted">쇼핑몰 상품 페이지가 아직 없는 PC예요. 구매 상담을 신청하시면 담당자가 연락드려 주문을 도와드려요. 가격은 연락드릴 때 다시 확인해 드려요.</p>
    <div class="new-pc-actions"><button type="button" class="${openId===id?'outline':'primary'}" data-inquiry="${esc(id)}" aria-expanded="${openId===id}">구매 상담 신청</button></div>
    ${openId===id?formHtml(id):''}</article>`;
}
function draw(){list.innerHTML=items.length?items.map(card).join(''):'<p class="muted">지금 공개된 새 PC가 없어요. PC 상담에서 원하는 조건을 말씀해 주시면 맞는 PC를 찾아 드려요.</p>';}
async function load(){
  try{const d=await call('GET','/api/mvp3/custom-pcs');items=d.items||[];if(d.note)noteEl.textContent=d.note;draw();
    // 추천 카드의 「자세히 보기」(new-pcs.html#구성번호)에서 왔으면 그 PC 로 바로 간다.
    const id=decodeURIComponent(location.hash.slice(1));const target=id&&list.querySelector(`[data-pc="${CSS.escape(id)}"]`);
    if(target){target.classList.add('is-target');target.scrollIntoView?.({block:'start'});}}
  catch(e){list.innerHTML=`<p class="new-pc-error" role="alert">목록을 불러오지 못했어요. ${esc(e.message)}</p>`;}
}
list.addEventListener('click',async e=>{
  const b=e.target.closest('[data-inquiry]');if(!b)return;
  const id=b.dataset.inquiry;openId=openId===id?null:id;
  if(openId&&!form){try{form=await call('GET','/api/mvp3/purchase-inquiries/form');}catch(x){result[id]={error:x.message};}}
  draw();list.querySelector(`[data-form="${CSS.escape(id)}"] input`)?.focus();
});
list.addEventListener('submit',async e=>{
  const f=e.target.closest('[data-form]');if(!f)return;e.preventDefault();if(sending)return;
  const id=f.dataset.form,v=n=>f.elements[n].value.trim()||null;
  const keep={name:v('name'),phone:v('phone'),email:v('email'),message:v('message'),consent:f.elements.consent.checked};
  sending=true;result[id]={};draw();
  try{
    const d=await call('POST','/api/mvp3/purchase-inquiries',{topic:'주문 희망',...keep,configuration_id:id});
    result[id]={done:d.note+' 신청 번호 '+d.inquiry_no};
  }catch(x){result[id]={error:x.message};}
  finally{
    sending=false;draw();
    const again=list.querySelector(`[data-form="${CSS.escape(id)}"]`);
    if(again)for(const [k,val] of Object.entries(keep)){if(k==='consent')again.elements.consent.checked=val;else again.elements[k].value=val||'';}
  }
});
load();
})();
