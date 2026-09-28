/* Server owns products/prices; browser owns only conversation display and stale-response guard. */
(()=>{'use strict';
const $=id=>document.getElementById('cc-'+id),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),money=n=>Number(n).toLocaleString('ko-KR')+'원';
let revision=0,conditions={},history=[],controller=null,detailRevision=0;
function append(who,text){const p=document.createElement('p');p.className='cc-message';p.textContent=who+'\n'+text;$('log').append(p);$('log').scrollTop=$('log').scrollHeight;}
function clearCards(){detailRevision++;$('cards').replaceChildren();$('details').replaceChildren();$('difference').textContent='';}
async function request(url,options={}){const r=await fetch(url,{credentials:'same-origin',...options});let d;try{d=await r.json();}catch{throw Error('서버 응답을 읽지 못했습니다. 잠시 후 다시 시도해주세요.');}if(!r.ok){if(r.status===401||r.status===403)throw Error('관리자 로그인이 필요합니다. 로그인 후 다시 시도해주세요.');throw Error(typeof d.detail==='string'?d.detail:d.detail?.detail||'상담 요청을 처리하지 못했습니다. 입력을 유지했습니다.');}return d;}
function showResult(d){
 clearCards();const labels={needs_conditions:'사용 조건 확인',evidence_pending:'추가 근거 확인',catalog_gap:'구성·자료 검토 필요',budget_exceeded:'예산 확인',comparison:'구성 비교 후보'};
 $('status').textContent=(labels[d.state]||'상담 결과')+' · 실제 AI API 응답';
 $('reason').textContent=d.reason|| (d.state==='needs_conditions'?'대화에서 필요한 조건을 더 확인합니다.':d.state==='budget_exceeded'?`현재 비교 후보는 ${money(d.minimum_price)}부터이며 본체 예산보다 ${money(d.shortfall)} 높습니다.`:'');
 $('cards').innerHTML=d.candidates.map(c=>`<article class="cc-card"><small>${esc(c.label)} · 검토 후보</small><h3>${esc(c.title)}</h3><div class="cc-price">${money(c.price_snapshot)}</div><p>${esc(c.facts.cpu)} · ${esc(c.facts.gpu)} · RAM ${esc(c.facts.ram_gb)}GB · SSD ${esc(c.facts.storage_gb)}GB</p><p>${esc(c.price_note)}</p><small>가격 관측일 ${esc(c.observed_date)}</small><ul>${c.reasons.map(x=>`<li>${esc(x)}</li>`).join('')}</ul><details><summary>추가 확인 사항</summary><ul>${c.pending.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></details><button type="button" data-detail="${esc(c.configuration_id)}">전체 부품 설명</button></article>`).join('');
 if(d.additional_cost!=null)$('difference').textContent=`여유 용량 후보와의 가격 차이는 ${money(d.additional_cost)}입니다. ${d.candidates.length<2?'원하는 용량 차이와 추가 지출 가능 금액을 대화로 확인합니다.':'용량 차이만으로 게임 FPS나 작업 속도 향상을 보장하지 않습니다.'}`;
 for(const b of $('cards').querySelectorAll('[data-detail]'))b.addEventListener('click',async()=>{
   const seq=++detailRevision;b.disabled=true;try{const pc=await request('/api/admin/pc-configurations/'+encodeURIComponent(b.dataset.detail));if(seq!==detailRevision)return;
     $('details').innerHTML=`<section class="cc-panel"><h3>${esc(pc.content.title)} · 부품 구성</h3>${pc.needs_review?'<p>부품 자료 변경 또는 출고 모델 확인 사항이 있습니다.</p>':''}${pc.parts.map(p=>`<details><summary>${esc(p.slot)} · ${esc(p.explanation?.name||'CPU 포함 기능')} · 수량 ${p.quantity}</summary><p>${esc(p.selection_note)}</p><p>${esc(p.explanation?.role||'별도 판매 부품이 아닙니다.')}</p><table>${(p.explanation?.facts||[]).map(f=>`<tr><td>${esc(f.label)}</td><td>${esc(f.value)}</td></tr>`).join('')}</table></details>`).join('')}</section>`;
   }catch(e){if(seq===detailRevision)$('details').textContent=e.message;}finally{b.disabled=false;}
 });
}
$('form').addEventListener('submit',async e=>{e.preventDefault();const message=$('message').value.trim();if(!message)return;
 const seq=++revision;controller?.abort();controller=new AbortController();const localController=controller;
 $('send').disabled=true;$('status').textContent='AI가 사용 조건을 확인하고 있습니다…';clearCards();$('reason').textContent='변경한 조건으로 확인 중입니다.';
 const timer=setTimeout(()=>localController.abort(),90000);
 try{const d=await request('/api/admin/configuration-consultation',{method:'POST',headers:{'Content-Type':'application/json'},signal:localController.signal,body:JSON.stringify({message,conditions,history:history.slice(-12),profile_revision:seq})});
   if(seq!==revision||d.profile_revision!==seq)return;
   conditions=d.conditions;$('conditions').textContent=JSON.stringify(conditions,null,2);
   const reply=['요청 요약: '+d.summary,...d.questions].join('\n');append('고객',message);append('팝콘AI',reply);
   history.push({role:'user',content:message},{role:'assistant',content:reply});history=history.slice(-12);$('message').value='';showResult(d);
 }catch(error){if(seq!==revision)return;$('status').textContent=error.name==='AbortError'?'응답 시간이 길어 요청을 중단했습니다. 입력을 유지했으니 다시 시도해주세요.':error.message;$('reason').textContent='상담이 완료되지 않아 상품을 새로 선정하지 않았습니다.';}
 finally{clearTimeout(timer);if(seq===revision)$('send').disabled=false;}
});
$('reset').addEventListener('click',()=>{revision++;controller?.abort();conditions={};history=[];$('log').replaceChildren();$('conditions').textContent='아직 입력된 조건이 없습니다.';$('message').value='';$('status').textContent='새 상담을 시작합니다.';$('reason').textContent='사용 조건을 알려주시면 비교를 시작합니다.';$('send').disabled=false;clearCards();});
})();
