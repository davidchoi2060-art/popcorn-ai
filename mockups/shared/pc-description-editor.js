(function(root){
'use strict';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const keys=['title','intro','benefits','scene','checks','faq','recommendation_policy'];
const clone=v=>JSON.parse(JSON.stringify(v));
const select=c=>Object.fromEntries(keys.map(k=>[k,clone(c[k]??(k==='recommendation_policy'?{}:['benefits','checks','faq'].includes(k)?[]:''))]));
const icon=n=>`<img class="pcd-icon" src="/shared/icons/admin/${n}.svg" alt="">`;
const date=v=>v?new Date(v).toLocaleString('ko-KR'):'기록 없음';
function mount(host,d,renderCopy){
 const panel=host.querySelector('#pcd-panel-copy'),footer=host.querySelector('.pcd-footer'),originalFooter=footer.innerHTML,dialog=host.closest('dialog');
 let saved=select(d.content),draft=clone(saved),revision=d.revision,saving=false,changed=false,disposed=false;
 const dirty=()=>JSON.stringify(saved)!==JSON.stringify(draft);
 host.pcDescriptionDirty=()=>dirty()||saving;
 const control=(key,value,label,multi=false,max=3000)=>`<div class="pce-control"><${multi?'textarea':'input'} data-field="${esc(key)}" aria-label="${esc(label)}" maxlength="${max}" required ${multi?`rows="${key.startsWith('benefits.')?2:3}"`:`value="${esc(value)}"`}>${multi?esc(value)+'</textarea>':''}<small data-count="${esc(key)}">${String(value||'').length}/${max}</small></div>`;
 function fields(){return `${d.content._admin_bom_edit?.review_required?'<p class="pcp-warning">부품 변경 후 설명 재검토 대기 · 설명 저장만으로 호환성 검토가 완료되지는 않습니다.</p>':''}<div class="pce-heading"><h3>상품 설명 편집</h3><span data-edit-state role="status"></span><button type="button" class="pcd-text-button" data-history>${icon('rotate-ccw')} 변경 이력</button></div><p class="pce-message" role="alert" data-edit-message></p><form class="pce-form"><div class="pce-row"><label>상품명</label>${control('title',draft.title,'상품명',false,200)}</div><div class="pce-row"><label>상품 소개</label>${control('intro',draft.intro,'상품 소개',true)}</div><div class="pce-row"><label>이 구성의 특징</label><div class="pce-benefits">${draft.benefits.map((b,i)=>`<div class="pce-benefit"><strong>${String(i+1).padStart(2,'0')}</strong><div>${control(`benefits.${i}.0`,b[0],`특징 ${i+1} 제목`,false,200)}${control(`benefits.${i}.1`,b[1],`특징 ${i+1} 설명`,true)}</div><button type="button" data-delete-benefit="${i}" aria-label="특징 ${i+1} 삭제" ${draft.benefits.length===1?'disabled':''}>${icon('trash-2')}</button></div>`).join('')}<button type="button" class="pcd-text-button" data-add-benefit ${draft.benefits.length>=12?'disabled':''}>${icon('plus')} 특징 추가</button></div></div><details class="pce-section"><summary>사용 상황 <span>${esc(draft.scene)}</span></summary>${control('scene',draft.scene,'사용 상황',true)}</details><details class="pce-section"><summary>사용 전 확인할 내용 <span>${draft.checks.length}개 항목</span></summary><p>한 줄에 한 항목씩 입력해 주세요.</p><textarea data-checks aria-label="사용 전 확인할 내용" rows="5" maxlength="90000">${esc(draft.checks.join('\n'))}</textarea></details><details class="pce-section"><summary>추천 기준 <span>알뜰·추천 설명</span></summary>${Object.entries(draft.recommendation_policy).map(([k,v])=>`<label>${esc(k)}</label>${control('recommendation_policy.'+k,v,k+' 추천 기준',true)}`).join('')}</details><details class="pce-section"><summary>자주 묻는 질문 <span>${draft.faq.length}개</span></summary><div data-faq-list>${draft.faq.map((q,i)=>`<div class="pce-faq"><div>${control(`faq.${i}.question`,q.question,`질문 ${i+1}`,false,200)}${control(`faq.${i}.answer`,q.answer,`답변 ${i+1}`,true)}</div><button type="button" data-delete-faq="${i}" aria-label="질문 ${i+1} 삭제">${icon('trash-2')}</button></div>`).join('')}</div><button type="button" class="pcd-text-button" data-add-faq ${draft.faq.length>=30?'disabled':''}>${icon('plus')} 질문 추가</button></details></form>`;}
 function render(){const open=[...panel.querySelectorAll('.pce-section')].map(x=>x.open);const top=panel.scrollTop;panel.innerHTML=fields();panel.querySelectorAll('.pce-section').forEach((x,i)=>x.open=!!open[i]);panel.scrollTop=top;panel.querySelector('form').onsubmit=e=>e.preventDefault();update();}
 function update(){const status=panel.querySelector('[data-edit-state]');status.textContent=saving?'저장 중…':dirty()?'저장하지 않은 변경':'저장된 내용';status.classList.toggle('pce-dirty',dirty());
  const active=!panel.hidden;footer.classList.toggle('pce-footer',active);
  if(active&&!footer.querySelector('[data-save-copy]'))footer.innerHTML=`<div>저장하면 상품 설명에 반영됩니다. 고객 공개 상태는 유지됩니다.<small data-last-saved></small></div><div class="pce-actions"><button type="button" data-cancel-copy>취소</button><button type="button" data-customer-preview>${icon('eye')} 고객 미리보기</button><button type="button" class="pce-save" data-save-copy>변경사항 저장</button></div>`;
  if(!active)footer.innerHTML=originalFooter;
  const save=footer.querySelector('[data-save-copy]');if(save){save.disabled=saving||!dirty();save.textContent=saving?'저장 중…':'변경사항 저장';footer.querySelector('[data-cancel-copy]').disabled=saving;footer.querySelector('[data-last-saved]').textContent='마지막 저장 '+date(d.updated_at);}
  panel.querySelectorAll('input,textarea,button').forEach(x=>{if(saving)x.disabled=true;});
 }
 function message(text){panel.querySelector('[data-edit-message]').textContent=text;}
 function preview(){const pop=host.querySelector('.pcd-customer-dialog');pop.querySelector('.pcd-copy').outerHTML=renderCopy({...d.content,...draft});pop.querySelector('.pcd-disclaimer').textContent=dirty()?'저장하지 않은 수정 내용의 미리보기입니다.':'관리자 미리보기 · 실제 공개 상태는 변경되지 않습니다.';pop.showModal();}
 function discard(action){if(saving)return;if(!dirty()){action();return;}let pop=host.querySelector('.pce-discard');if(!pop){pop=document.createElement('dialog');pop.className='pcd-customer-dialog pce-discard';pop.setAttribute('aria-label','수정 내용 확인');host.append(pop);}pop.innerHTML='<h2>저장하지 않은 변경이 있습니다</h2><p>수정 내용을 버리고 마지막 저장 상태로 돌아갈까요?</p><div class="pce-actions"><button type="button" data-keep-edit>계속 편집</button><button type="button" data-discard-edit>변경 취소</button></div>';pop.onclick=e=>{if(e.target.closest('[data-keep-edit]'))pop.close();if(e.target.closest('[data-discard-edit]')){pop.close();draft=clone(saved);action();}};pop.showModal();}
 async function save(){if(saving||!dirty())return;
  const invalid=[...panel.querySelectorAll('input,textarea')].find(x=>!x.checkValidity());if(invalid){let p=invalid.parentElement;while(p&&p!==panel){if(p.tagName==='DETAILS')p.open=true;p=p.parentElement;}invalid.reportValidity();invalid.focus();return;}
  if(draft.checks.length>30||draft.checks.some(x=>x.length>3000)){message('확인할 내용은 최대 30개, 항목당 3,000자까지 입력해 주세요.');return;}
  const submitted=clone(draft);saving=true;update();message('');
  try{const r=await fetch(`/api/admin/pc-configurations/${encodeURIComponent(d.configuration_id)}/description`,{method:'PUT',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision,content:submitted})});const result=await r.json();if(!r.ok)throw Error(typeof result.detail==='string'?result.detail:'저장하지 못했습니다. 입력 내용과 로그인 상태를 확인해 주세요.');revision=result.revision;d.revision=revision;d.content=result.content;d.updated_at=result.updated_at;saved=select(result.content);draft=clone(saved);changed=changed||result.changed;
   const overview=host.querySelector('.pcd-overview');overview.querySelector('h3').textContent=d.content.title;overview.querySelector('section:last-of-type>p').textContent=d.content.intro;
   saving=false;render();message(result.changed?'상품 설명을 저장했습니다.':'변경된 내용이 없습니다.');
  }catch(e){saving=false;render();message(e.message);}
 }
 async function history(){let pop=host.querySelector('.pce-history');if(!pop){pop=document.createElement('dialog');pop.className='pcd-customer-dialog pce-history';pop.setAttribute('aria-label','제품군 변경 이력');host.append(pop);}pop.innerHTML=`<header><h2>제품군 변경 이력</h2><button type="button" data-history-close aria-label="변경 이력 닫기">${icon('x')}</button></header><div data-history-items>불러오는 중…</div>`;pop.showModal();let offset=0;
  const fetchPage=async()=>{const target=pop.querySelector('[data-history-items]');try{const r=await fetch(`/api/admin/pc-configurations/${encodeURIComponent(d.configuration_id)}/description-history?offset=${offset}&limit=10`,{credentials:'same-origin'});if(!r.ok)throw Error('변경 이력을 불러오지 못했습니다.');const h=await r.json();target.innerHTML=h.items.map(x=>`<details><summary>이전 버전 ${x.revision} · ${esc(date(x.archived_at))}</summary><p>${x.edit?(x.edit.kind==='parts'?'부품 구성 변경 · ':'설명 수정 · ')+esc(x.edit.name||'관리자'):'이전 자료 갱신 기록'}</p>${x.edit?.kind==='parts'?`<ul>${(x.edit.changes||[]).map(p=>`<li>${esc(p.label)}: ${esc(p.before.name)} × ${p.before.quantity} → ${esc(p.after.name)} × ${p.after.quantity}</li>`).join('')}</ul>`:''}<p>아래는 변경 전 저장 내용입니다.</p>${renderCopy(x.content)}</details>`).join('')||'<p>이전 버전이 없습니다. 설명을 수정해 저장하면 이력이 남습니다.</p>';target.innerHTML+=`<div class="pce-history-pages"><button type="button" data-history-prev ${offset===0?'disabled':''}>이전</button><span>전체 ${h.total}개</span><button type="button" data-history-next ${offset+h.items.length>=h.total?'disabled':''}>다음</button></div>`;}catch(e){target.textContent=e.message;}};
  pop.onclick=e=>{if(e.target.closest('[data-history-close]'))pop.close();if(e.target.closest('[data-history-next]')){offset+=10;fetchPage();}if(e.target.closest('[data-history-prev]')){offset-=10;fetchPage();}};await fetchPage();
 }
 const onInput=e=>{if(e.target.hasAttribute('data-checks'))draft.checks=e.target.value.split('\n').map(x=>x.trim()).filter(Boolean);else if(e.target.dataset.field){const path=e.target.dataset.field.split('.');let obj=draft;path.slice(0,-1).forEach(k=>obj=obj[k]);obj[path.at(-1)]=e.target.value;const count=e.target.parentElement.querySelector('small');if(count)count.textContent=e.target.value.length+'/'+e.target.maxLength;}update();};
 const onClick=e=>{const b=e.target.closest('button');if(!b)return;
  if(b.matches('#catalog-dialog-close,[data-detail-close]')){if(dirty()||saving){e.preventDefault();e.stopImmediatePropagation();discard(()=>dialog.close());}return;}
  if(b.hasAttribute('data-customer-preview')){e.stopImmediatePropagation();if(host.pcPartsDirty?.()){host.querySelector('[data-pcp-message]').textContent='부품 변경을 저장하거나 취소한 후 고객 설명을 확인해 주세요.';return;}preview();return;}
  if(b.hasAttribute('data-save-copy'))save();
  if(b.hasAttribute('data-cancel-copy'))discard(()=>{draft=clone(saved);render();});
  if(b.hasAttribute('data-add-benefit')){draft.benefits.push(['','']);render();panel.querySelectorAll('.pce-benefit input')[draft.benefits.length-1].focus();}
  if(b.hasAttribute('data-delete-benefit')&&draft.benefits.length>1){draft.benefits.splice(Number(b.dataset.deleteBenefit),1);render();}
  if(b.hasAttribute('data-add-faq')){draft.faq.push({question:'',answer:''});render();panel.querySelector('.pce-section:last-of-type').open=true;panel.querySelectorAll('.pce-faq input')[draft.faq.length-1].focus();}
  if(b.hasAttribute('data-delete-faq')){draft.faq.splice(Number(b.dataset.deleteFaq),1);render();}
  if(b.hasAttribute('data-history'))history();
  
 };
 const onCancel=e=>{if(e.target===dialog&&(dirty()||saving)){e.preventDefault();discard(()=>dialog.close());}};
 const beforeUnload=e=>{if(dirty()||saving){e.preventDefault();e.returnValue='';}};
 const tabObserver=new MutationObserver(update);tabObserver.observe(panel,{attributes:true,attributeFilter:['hidden']});
 const cleanup=()=>{if(disposed)return;disposed=true;tabObserver.disconnect();dialog.removeEventListener('click',onClick,true);dialog.removeEventListener('cancel',onCancel);dialog.removeEventListener('close',onClose);window.removeEventListener('beforeunload',beforeUnload);host.removeEventListener('input',onInput);};
 const onClose=()=>{cleanup();if(changed)host.dispatchEvent(new CustomEvent('pc-description-saved',{bubbles:true}));};
 dialog.addEventListener('click',onClick,true);dialog.addEventListener('cancel',onCancel);dialog.addEventListener('close',onClose);window.addEventListener('beforeunload',beforeUnload);host.addEventListener('input',onInput);render();
}
root.PcDescriptionEditor={mount};
})(window);
