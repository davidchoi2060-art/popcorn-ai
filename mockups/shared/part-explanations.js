(function(root){
 'use strict';
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const url=v=>{try{const u=new URL(v);return u.protocol==='https:'?u.href:null;}catch{return null;}};
 function markup(p,{open=false,review=false}={}){
  const image=url(p.image_url);
  const facts=(p.facts||[]).map(f=>`<tr><th>${esc(f.label)}</th><td>${esc(f.value)}${review?`<small>${esc(f.verification)}</small>`:''}</td></tr>`).join('');
  return `<details class="pc-part"${open?' open':''}><summary><span class="pc-part-kind">${esc(p.slot_label||p.slot)}</span><span class="pc-part-heading"><strong>${esc(p.name)}</strong><span>${esc(p.role)}</span><span class="pc-toggle">상세 사양 펼치기 / 접기</span></span><span class="pc-part-price">${Number.isFinite(p.price)?esc(p.price.toLocaleString('ko-KR'))+'원':'가격 확인 필요'}</span></summary><div class="pc-part-body"><figure>${image?`<img src="${esc(image)}" alt="${esc(p.name)} 판매처 등록 이미지" loading="lazy" referrerpolicy="no-referrer">`:'<div class="pc-no-image">제품 이미지 미확인</div>'}<figcaption>${esc(p.image_caption||'')}</figcaption></figure><section><h3>${esc(p.slot_label||p.slot)} 상세 정보</h3><table><tbody>${facts}</tbody></table><h4>제품 특징</h4><ul>${(p.highlights||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ul></section><section><h3>어떤 역할을 하나요?</h3><p>${esc(p.role)}</p><h4>선택할 때 확인하세요</h4>${(p.cautions||[]).map(x=>`<p>${esc(x)}</p>`).join('')}<button type="button" class="pc-question" data-part-question="${esc(p.product_code)}">이 부품에 대해 질문하기</button><div class="pc-answer" hidden tabindex="-1" aria-live="polite"></div></section></div>${review?`<div class="pc-review"><b>검토 초안</b> · 상품코드 ${esc(p.product_code)}${p.product_linked===false?' · DB 연결 대기':''}${p.source_current===false?' · 현재 상품 원문과 대조 필요':''}<ul>${(p.review_issues||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ul><details><summary>사양 근거 보기</summary>${(p.sources||[]).map(s=>url(s.url)?`<p><a href="${esc(url(s.url))}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a> · ${esc(s.observed_at)}</p>`:'').join('')}</details></div>`:''}</details>`;
 }
 function attach(container,items){
  const byCode=new Map(items.map(p=>[String(p.product_code),p]));
  container.onclick=e=>{
   const b=e.target.closest('[data-part-question]');if(!b)return;
   const p=byCode.get(b.dataset.partQuestion),answer=b.nextElementSibling;if(!p||!answer)return;
   answer.replaceChildren();
   const title=document.createElement('strong');title.textContent='자주 묻는 질문';answer.append(title);
   for(const qa of p.questions||[]){const d=document.createElement('details'),s=document.createElement('summary'),a=document.createElement('p');s.textContent=qa.question;a.textContent=qa.answer;d.append(s,a);answer.append(d);}
   answer.hidden=false;answer.focus();
  };
  container.querySelectorAll('.pc-part img').forEach(img=>img.addEventListener('error',()=>{
   const fallback=document.createElement('div');fallback.className='pc-no-image';fallback.textContent='제품 이미지를 불러오지 못했습니다';img.replaceWith(fallback);
  },{once:true}));
 }
 root.PopcornPartExplanations={markup,attach};
 if(typeof module!=='undefined')module.exports={markup};
})(typeof window!=='undefined'?window:globalThis);
