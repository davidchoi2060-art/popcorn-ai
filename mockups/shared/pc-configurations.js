(()=>{'use strict';
const $=id=>document.getElementById('catalog-'+id),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=v=>Number.isFinite(v)?v.toLocaleString('ko-KR')+'원':'가격 확인 필요';
const badge=(text,tone='')=>`<span class="catalog-badge ${tone}">${esc(text)}</span>`;
const cap=v=>v==null?'확인 필요':esc(v)+'GB';
let offset=0,total=0,items=[],selected=null,request=0,detailRequest=0;
const params=()=>new URLSearchParams({q:$('q').value.trim(),source:$('source').value,review:$('review').value,visibility:$('visibility').value});
function photo(p){return `<figure class="catalog-photo">${p.image_url?`<img src="${esc(p.image_url)}" alt="${esc(p.title)} 케이스" loading="lazy">`:'<span>이미지 미등록</span>'}<figcaption>${esc(p.image_caption||'케이스 이미지')}</figcaption></figure>`;}
function images(container){container.querySelectorAll('img').forEach(img=>img.addEventListener('error',()=>{const t=document.createElement('span');t.textContent='이미지 확인 필요';img.replaceWith(t);},{once:true}));}
function select(id,updateUrl=true){selected=items.find(r=>r.configuration_id===id)||null;
 $('rows').querySelectorAll('tr[data-id]').forEach(tr=>{const on=tr.dataset.id===id;tr.classList.toggle('selected',on);tr.querySelector('input').checked=on;});
 $('detail').disabled=!selected;const idx=items.indexOf(selected);$('previous-product').disabled=idx<=0;$('next-product').disabled=idx<0||idx===items.length-1;
 if(!selected){$('summary').innerHTML='<p class="catalog-empty">선택할 상품이 없습니다. 검색 조건을 바꿔 주세요.</p>';return;}
 if(updateUrl)history.replaceState(null,'','#'+encodeURIComponent(id));
 const p=selected,f=p.facts;
 $('summary').innerHTML=`<div class="catalog-hero">${photo(p)}<div><span>${esc(id)}</span><h3>${esc(p.title)}</h3>${badge(p.source==='신규'?'신규 구성':'기존 판매 상품',p.source==='신규'?'green':'blue')}<p class="catalog-price-label">기준 가격</p><strong class="catalog-price">${money(p.price)}</strong><p class="catalog-price-date">가격 기준일 ${esc(p.observed_date)}</p></div></div>
 <h3 class="catalog-subtitle">주요 사양</h3><dl class="catalog-specs"><dt>CPU</dt><dd>${esc(f.cpu||'확인 필요')}</dd><dt>GPU</dt><dd>${esc(f.gpu||'확인 필요')}</dd><dt>메모리</dt><dd>${cap(f.ram_gb)}</dd><dt>저장장치</dt><dd>${cap(f.storage_gb)}</dd></dl>
 <h3 class="catalog-subtitle">상태 정보</h3><div class="catalog-status"><div><span>상품 설명</span>${badge(p.description_ready?'설명 등록':'보완 필요',p.description_ready?'green':'amber')}<small>구성·부품 설명</small></div><div><span>정보 검토</span>${badge(p.needs_review?'확인 필요':'변경 없음',p.needs_review?'amber':'green')}<small>${p.needs_review?'부품 정보 확인 필요':'현재 연결 정보 기준'}</small></div><div><span>호환성</span>${badge('검증 대기','amber')}<small>최종 검수 결과 미연결</small></div><div><span>고객 공개</span>${badge('비공개')}<small>관리자 검토용</small></div></div><p class="catalog-note">${esc(p.price_note||'저장 당시 기준 가격입니다.')}<br>최신 판매가·출고 여부는 별도 확인이 필요합니다.</p>`;
 images($('summary'));
}
function pages(){const limit=Number($('limit').value),page=Math.floor(offset/limit)+1,last=Math.max(1,Math.ceil(total/limit));
 const targets=new Set([1,last,page-1,page,page+1]);let html=`<button type="button" data-page="${page-1}" ${page===1?'disabled':''}>이전</button>`,prev=0;
 [...targets].filter(x=>x>=1&&x<=last).sort((a,b)=>a-b).forEach(n=>{if(prev&&n-prev>1)html+='<span>…</span>';html+=`<button type="button" data-page="${n}" ${n===page?'aria-current="page"':''}>${n}</button>`;prev=n;});
 $('pages').innerHTML=html+`<button type="button" data-page="${page+1}" ${page>=last?'disabled':''}>다음</button>`;
 $('range').textContent=`전체 ${total}개 중 ${total?offset+1:0}–${Math.min(offset+limit,total)} 표시`;
}
async function load(){const seq=++request;++detailRequest;if($('dialog').open)$('dialog').close();$('message').textContent='';$('count').textContent='불러오는 중';$('detail').disabled=true;$('export').disabled=true;$('rows').setAttribute('aria-busy','true');
 const args=params();args.set('offset',offset);args.set('limit',$('limit').value);
 try{const r=await fetch('/api/admin/pc-configurations?'+args,{credentials:'same-origin'});if(!r.ok)throw Error(r.status===401||r.status===403?'관리자 로그인이 필요합니다.':'목록을 불러오지 못했습니다.');const d=await r.json();if(seq!==request)return;
 total=d.total;items=d.items;if(offset>=total&&offset>0){offset=0;return load();}
 $('count').textContent=`전체 ${total}개`+(total!==d.catalog_total?` / 등록 ${d.catalog_total}개`:'');
 $('rows').innerHTML=items.map(p=>`<tr data-id="${esc(p.configuration_id)}"><td><input type="radio" name="configuration" aria-label="${esc(p.configuration_id)} 선택"></td><td>${photo(p)}</td><td><button class="catalog-title" type="button"><small>${esc(p.configuration_id)}</small>${esc(p.title)}</button></td><td>${esc(p.facts.cpu||'CPU 확인 필요')}<small>${esc(p.facts.gpu||'GPU 확인 필요')}<br>RAM ${cap(p.facts.ram_gb)} / SSD ${cap(p.facts.storage_gb)}</small></td><td><strong>${money(p.price)}</strong></td><td>${badge(p.source==='신규'?'신규 구성':'기존 판매 상품',p.source==='신규'?'green':'blue')}<br>${badge(p.description_ready?'설명 등록':'설명 보완',p.description_ready?'':'amber')}<br>${badge(p.needs_review?'정보 확인 필요':'정보 변경 없음',p.needs_review?'amber':'green')} ${badge('비공개')}</td></tr>`).join('')||'<tr><td colspan="6"><p class="catalog-empty">조건에 맞는 제품군이 없습니다.</p></td></tr>';
 images($('rows'));pages();const desired=decodeURIComponent(location.hash.slice(1));select(items.find(x=>x.configuration_id===desired)?.configuration_id||items[0]?.configuration_id);$('export').disabled=false;
 }catch(e){if(seq!==request)return;items=[];selected=null;$('rows').replaceChildren();$('pages').replaceChildren();$('range').textContent='';$('count').textContent='목록 조회 실패';$('message').textContent=e.message+' 검색 버튼으로 다시 시도해 주세요.';select(null,false);}finally{if(seq===request)$('rows').removeAttribute('aria-busy');}}
async function detail(){if(!selected)return;const id=selected.configuration_id,seq=++detailRequest;$('dialog-id').textContent=id;$('dialog-title').textContent=selected.title;$('dialog-body').textContent='전체 구성과 부품을 불러오는 중입니다.';$('dialog').showModal();
 try{const r=await fetch('/api/admin/pc-configurations/'+encodeURIComponent(id),{credentials:'same-origin'});if(!r.ok)throw Error('상세 정보를 불러오지 못했습니다.');const d=await r.json();if(seq!==detailRequest)return;const c=d.content,offer=d.offers[0];
 const parts=d.parts.filter(p=>!p.pseudo).map(p=>({...p.explanation,slot_label:p.slot_label,product_code:p.explanation_code,image_url:p.image_url,price:p.current_unit_price,_part:p}));
 $('dialog-body').innerHTML=`<div class="catalog-detail-intro"><strong>${money(offer?.price_snapshot)}</strong><p>${esc(offer?.payload?.price_note||'가격 확인 필요')} · 기준일 ${esc(d.observed_date)}</p><p>${esc(c.intro)}</p>${badge('고객 비공개')}${badge(d.needs_review?'부품 정보 확인 필요':'부품 정보 변경 없음',d.needs_review?'amber':'green')}</div><h3>이 구성의 특징</h3><div class="catalog-benefits">${(c.benefits||[]).map(b=>`<article><h3>${esc(b[0])}</h3><p>${esc(b[1])}</p></article>`).join('')}</div><p>${esc(c.appearance||'')}</p><h3>전체 부품 구성 · ${parts.length}종</h3><p>부품별 금액은 현재 개별 판매가입니다. 위의 완제품 기준 가격을 나눈 금액이 아닙니다.</p><div id="catalog-all-parts">${parts.map(p=>`<p class="catalog-part-note">${esc(p.slot_label)} · 수량 ${esc(p._part.quantity)} · 상품코드 ${esc(p.product_code)}${p._part.needs_review?' · 정보 확인 필요':''}<br>${esc(p._part.selection_note||'')}</p>${PopcornPartExplanations.markup(p,{review:true})}`).join('')}</div><section class="catalog-checks"><h3>선택 전에 확인할 내용</h3><ul>${(c.checks||[]).map(s=>`<li>${esc(s)}</li>`).join('')}</ul><p>호환성 최종 검수·현재 재고·출고 가능 여부는 별도 확인이 필요합니다.</p></section><h3>가격 구성</h3><table class="catalog-offers"><thead><tr><th>구성 ID</th><th>기준 가격</th><th>포함 조건</th></tr></thead><tbody>${d.offers.map(o=>`<tr><td>${esc(o.offer_id)}</td><td>${money(o.price_snapshot)}</td><td>${esc(o.payload?.price_note||'확인 필요')}</td></tr>`).join('')}</tbody></table><h3>자주 묻는 질문</h3>${(c.faq||[]).map(q=>`<details><summary>${esc(q.question)}</summary><p>${esc(q.answer)}</p></details>`).join('')}`;
 PopcornPartExplanations.attach($('all-parts'),parts);
 }catch(e){if(seq===detailRequest)$('dialog-body').textContent=e.message+' 창을 닫고 다시 시도해 주세요.';}}
$('filters').onsubmit=e=>{e.preventDefault();offset=0;load();};['source','review','visibility','limit'].forEach(id=>$(id).onchange=()=>{offset=0;load();});$('reset').onclick=()=>{$('filters').reset();offset=0;load();};
$('rows').onclick=e=>{const row=e.target.closest('tr[data-id]');if(row)select(row.dataset.id);};$('rows').onchange=e=>{const row=e.target.closest('tr[data-id]');if(row)select(row.dataset.id);};
$('pages').onclick=e=>{const b=e.target.closest('button[data-page]');if(b&&!b.disabled){offset=(Number(b.dataset.page)-1)*Number($('limit').value);load();}};
$('previous-product').onclick=()=>select(items[items.indexOf(selected)-1]?.configuration_id);$('next-product').onclick=()=>select(items[items.indexOf(selected)+1]?.configuration_id);
$('detail').onclick=detail;$('dialog-close').onclick=()=>{$('dialog').close();};$('dialog').addEventListener('close',()=>{++detailRequest;});
$('export').onclick=async()=>{const b=$('export');b.disabled=true;$('message').textContent='';try{const r=await fetch('/api/admin/pc-configurations/export.xlsx?'+params(),{credentials:'same-origin'});if(!r.ok)throw Error('엑셀을 내려받지 못했습니다. 다시 시도해 주세요.');const url=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=url;a.download='조립PC_제품군.xlsx';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){$('message').textContent=e.message;}finally{b.disabled=false;}};
load();
})();
