(()=>{
'use strict';
const screen=document.querySelector('#builder-screen'), message=document.querySelector('#builder-message');
const labels={CPU:'CPU',GPU:'그래픽카드',RAM:'메모리',SSD:'SSD',MB:'메인보드',COOLER:'CPU쿨러',POWER:'파워',CASE:'케이스'};
let step=1,slot='CPU',source='sale',q='',offset=0,items=[],total=0,parts=[],title='',integrated=false,bundled=false,preview=null,busy=false,requestId=crypto.randomUUID(),saved=null,searchTimer;
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const assemblyFee=window.PopcornAssemblyFee.ASSEMBLY_FEE;
const money=x=>Number(x||0).toLocaleString('ko-KR')+'원';
function note(text,error=false){message.textContent=text;message.className=error?'builder-error':'builder-success';}
async function api(url,body){const r=await fetch(url,{credentials:'same-origin',headers:body?{'Content-Type':'application/json'}:{},method:body?'POST':'GET',body:body?JSON.stringify(body):undefined});const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'입력 내용 또는 로그인 상태를 확인해 주세요.');return d;}
function input(){return {title,parts:parts.map(p=>({code:p.code,quantity:p.quantity,source:p.source})),integrated_gpu:integrated,bundled_cooler:bundled,request_id:requestId,preview_token:preview?.preview_token||null};}
const draftKey='popcorn.pc-builder.draft.v1';
function remember(){
 if(parts.some(p=>!Number.isInteger(p.quantity)||p.quantity<1||p.quantity>16))return;
 try{if(!parts.length&&!title.trim()){sessionStorage.removeItem(draftKey);return;}
 sessionStorage.setItem(draftKey,JSON.stringify({title,parts:parts.map(p=>({code:p.code,quantity:p.quantity,source:p.source})),integrated_gpu:integrated,bundled_cooler:bundled,request_id:requestId}));}catch{note('브라우저 초안 보관을 사용할 수 없습니다. 화면을 닫기 전에 검토 대기로 저장해 주세요.',true);}
}
function forget(){try{sessionStorage.removeItem(draftKey);}catch{}}
function invalidate(){preview=null;saved=null;remember();}
async function start(){
 let draft;try{draft=JSON.parse(sessionStorage.getItem(draftKey)||'null');}catch{note('초안 읽기 실패 · 부품을 다시 선택해 주세요.',true);}
 if(draft){busy=true;draw();try{const resolved=await api('/api/admin/pc-builder/draft/resolve',draft);
 title=draft.title;parts=resolved.items;integrated=draft.integrated_gpu;bundled=draft.bundled_cooler;requestId=draft.request_id;
 remember();note(resolved.note+(resolved.rejected.length?' · 복원 제외: '+resolved.rejected.map(p=>p.name+' ('+p.reason+')').join(', '):''),resolved.rejected.length>0);
 }catch(e){note('초안 복원 실패 · 보관된 초안은 유지합니다. '+e.message,true);}finally{busy=false;draw();}}
 await load();
}
const order=['CPU','GPU','MB','RAM','SSD','COOLER','POWER','CASE'];
function missingSlots(){return order.filter(k=>!parts.some(p=>p.slot===k)&&!(k==='GPU'&&integrated)&&!(k==='COOLER'&&bundled));}
function capacityText(p){
 const key=p.slot==='RAM'?'상품 용량':'용량',value=p.facts?.find(f=>f.label===key)?.value;
 const match=String(value||'').match(/^\s*(\d+(?:\.\d+)?)\s*\(?\s*(GB|TB)\s*\)?\s*$/i);
 if(!match)return '용량 자료 확인 필요';
 return '총 '+(Number(match[1])*p.quantity).toLocaleString('ko-KR')+match[2].toUpperCase();
}
function quantityNote(p){return ['RAM','SSD'].includes(p.slot)?`판매 패키지 ${p.quantity}개 · ${capacityText(p)}`:'1개';}
function updateSummary(){
 const subtotal=parts.reduce((sum,p)=>sum+p.unit_price*p.quantity,0);
 const amount=screen.querySelector('#builder-estimate'),base=screen.querySelector('#builder-subtotal');
 if(amount)amount.textContent=money(subtotal+assemblyFee);if(base)base.textContent=money(subtotal);
 const missing=missingSlots(),hint=screen.querySelector('#builder-missing');
 if(hint)hint.innerHTML=missing.length?'선택 필요: '+missing.map(k=>`<button data-slot="${k}">${labels[k]}</button>`).join(''):'필수 부품 선택 완료 · 호환 검사 전';
 const button=screen.querySelector('#builder-preview');if(button)button.disabled=busy||missing.length>0||!title.trim()||parts.some(p=>!Number.isInteger(p.quantity)||p.quantity<1||p.quantity>16);
}
let loadVersion=0,loading=false;
async function load(){const version=++loadVersion;loading=true;draw();try{const d=await api('/api/admin/pc-builder/parts?'+new URLSearchParams({slot,source,q,offset,limit:20}));if(version!==loadVersion)return;loading=false;items=d.items;total=d.total;const list=screen.querySelector('.builder-part-list');if(list)list.scrollTop=0;draw();}catch(e){if(version===loadVersion){loading=false;items=[];total=0;draw();note(e.message,true);}}}
function draw(){
 const oldList=screen.querySelector('.builder-part-list'),oldSelection=screen.querySelector('.builder-selection-scroll');
 const listTop=oldList?.scrollTop||0,selectionTop=oldSelection?.scrollTop||0,optionsOpen=screen.querySelector('.builder-cpu-options')?.open;
 const active=document.activeElement,searchFocus=active?.id==='builder-search',cursor=searchFocus?active.selectionStart:null;
 document.querySelectorAll('[data-step]').forEach(b=>{b.classList.toggle('active',Number(b.dataset.step)===step);b.disabled=busy;});
 if(saved){screen.innerHTML=`<section class="builder-card"><h2>검토 대기 제품군으로 등록했습니다</h2><p>${esc(saved.configuration_id)}</p><p>추천 승인과 고객 공개는 검토 후 별도로 진행합니다.</p><div class="builder-actions"><a href="/admin2/pc-workspace?id=${encodeURIComponent(saved.configuration_id)}">등록된 제품 검토하기</a><button id="builder-reset">다른 신규 구성 만들기</button></div></section>`;return;}
 if(step===2&&preview){const r=preview.review;screen.innerHTML=`<section class="builder-card"><h2>${esc(title)} · 구성·가격 확인</h2><p class="builder-note">DB 호환 검토 결과입니다. 미확인 사양과 실제 조립·부하 검수는 별도입니다. 검토 대기 저장은 호환성 통과·추천 승인이 아닙니다.</p><table class="builder-bom"><thead><tr><th>부품</th><th>제품 · 수량</th><th>금액</th></tr></thead><tbody>${preview.lines.map(p=>`<tr><td>${esc(labels[p.slot])}</td><td>${esc(p.name)} × ${p.quantity}<br><small>${p.source==='owned'?'DB 보유 부품':'판매 DB 부품'}</small></td><td>${money(p.total)}</td></tr>`).join('')}<tr><td colspan="2">조립비 · 한 번 포함</td><td>${money(preview.assembly_fee)}</td></tr></tbody></table><div class="builder-money"><span>예상 총액</span><b>${money(preview.total)}</b></div><h2>호환성 검사</h2>${r.checks.map(c=>`<div class="builder-check"><b class="builder-state-${esc(c.state)}">${{pass:'DB 규격 일치',fail:'불일치',unknown:'확인 필요'}[c.state]}</b>${esc(c.label)}<p class="builder-muted">${esc(c.detail)}</p></div>`).join('')}${r.assembly_checks?.length?`<h3>실제 조립 시 확인할 항목</h3>${r.assembly_checks.map(c=>`<div class="builder-check"><b class="builder-state-unknown">조립 확인 필요</b>${esc(c.label)}<p class="builder-muted">${esc(c.detail)}</p></div>`).join('')}`:''}${r.blockers.length?`<h3>검토 시 보완할 항목</h3><ul>${r.blockers.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:''}<p class="builder-note">${preview.duplicate_id?'같은 구성의 기존 제품군: '+esc(preview.duplicate_id):'동일한 부품·수량의 기존 제품군 없음'}<br>부품 자료·가격·재고·호환 규칙이 변경되면 다시 확인해야 합니다.</p><div class="builder-actions"><button data-step="1">부품 구성으로 돌아가기</button><button class="primary" id="builder-save" ${busy||!preview.can_save||preview.duplicate_id?'disabled':''}>${busy?'저장 중…':'검토 대기 제품군으로 저장'}</button></div></section>`;return;}
 screen.innerHTML=`<div class="builder-grid">
 <section class="builder-card builder-catalog"><div class="builder-card-head"><h2>부품 찾기</h2><div class="builder-source" role="group" aria-label="부품 출처"><button data-source="sale" class="${source==='sale'?'selected':''}" aria-pressed="${source==='sale'}">판매 부품</button><button data-source="owned" class="${source==='owned'?'selected':''}" aria-pressed="${source==='owned'}">보유 부품</button></div></div>
 <div class="builder-controls"><input class="builder-search" id="builder-search" maxlength="100" aria-label="부품 검색" placeholder="제품명 또는 상품 코드로 검색" value="${esc(q)}"><span class="builder-sort">가격 낮은 순</span></div>
 <div class="builder-slots" aria-label="부품 종류">${order.map(k=>`<button data-slot="${k}" class="${slot===k?'selected':''}" aria-pressed="${slot===k}">${labels[k]}</button>`).join('')}</div>
 <div class="builder-list-heading"><b>${labels[slot]} · 부품 선택</b><span>${total.toLocaleString('ko-KR')}개</span></div>
 <div class="builder-part-list" aria-busy="${loading}" tabindex="0" aria-label="부품 검색 결과">${items.map(p=>{const selected=parts.some(x=>x.code===p.code);return `<article class="builder-part ${selected?'is-selected':''}"><img src="${esc(p.image_url)}" alt="" loading="lazy"><div><strong>${esc(p.name)}</strong><small>${esc((p.facts||[]).slice(0,2).map(f=>f.label+' '+f.value).join(' · '))}</small><small>코드 ${p.code} · DB 재고 ${p.stock_qty??'미확인'}</small>${!p.source_current?'<small class="builder-error">설명 갱신 필요</small>':''}</div><div class="builder-part-price"><span class="builder-badge">${esc(p.sale_status)}</span><b>${money(p.unit_price)}</b></div><button data-add="${p.code}" ${loading||!p.source_current||selected?'disabled':''} aria-label="${esc(p.name)} ${selected?'선택됨':'추가'}">${selected?'선택됨':'추가'}</button></article>`;}).join('')||'<p class="builder-empty">해당 조건의 부품 없음</p>'}</div>
 <footer class="builder-pagination"><small>보유 수량은 DB 기준 · 실사 및 출고 확인 별도</small><div><button id="builder-prev" ${offset===0?'disabled':''}>이전</button><span>${total?Math.floor(offset/20)+1:0} / ${Math.ceil(total/20)}</span><button id="builder-next" ${offset+20>=total?'disabled':''}>다음</button></div></footer></section>
 <section class="builder-card builder-selection"><div class="builder-card-head"><h2>현재 조립 구성</h2><span>선택 ${parts.length}종</span><button id="builder-clear" ${!parts.length&&!title?'disabled':''}>초기화</button></div>
 <label class="builder-name-label" for="builder-title">조립PC 제품명</label><input class="builder-title" id="builder-title" maxlength="180" placeholder="신규 조립PC 제품명 입력" value="${esc(title)}">
 <div class="builder-selection-scroll" tabindex="0" aria-label="선택한 부품 구성"><table class="builder-bom"><thead><tr><th>부품</th><th>제품 · 수량</th><th>금액</th><th><span class="builder-sr-only">제거</span></th></tr></thead><tbody>${order.map(k=>{const rows=parts.map((p,i)=>({...p,index:i})).filter(p=>p.slot===k);if(!rows.length)return `<tr class="builder-missing-row"><td>${labels[k]}</td><td colspan="3">${k==='GPU'&&integrated?'CPU 내장그래픽 · 지원 근거 확인':k==='COOLER'&&bundled?'CPU 기본 쿨러 · 포함 근거 확인':`<button data-slot="${k}">${labels[k]} 선택 필요 →</button>`}</td></tr>`;return rows.map(p=>`<tr><td>${labels[k]}</td><td><div class="builder-selected-name"><img src="${esc(p.image_url)}" alt=""><strong>${esc(p.name)}</strong></div><small class="builder-muted">${p.source==='owned'?'DB 보유':'판매 부품'} · 개별 ${money(p.unit_price)}</small>${['RAM','SSD'].includes(k)?`<div class="builder-quantity"><button data-adjust="${p.index}" data-delta="-1" ${p.quantity<=1?'disabled':''} aria-label="${esc(p.name)} 수량 줄이기">−</button><input data-qty="${p.index}" type="number" min="1" max="16" value="${p.quantity}" aria-label="${esc(p.name)} 판매 패키지 수량"><button data-adjust="${p.index}" data-delta="1" ${p.quantity>=16?'disabled':''} aria-label="${esc(p.name)} 수량 늘리기">+</button></div>`:''}<small data-quantity-note="${p.index}" class="builder-muted">${esc(quantityNote(p))}</small></td><td data-line-total="${p.index}" class="builder-line-price">${money(p.unit_price*p.quantity)}</td><td><button data-remove="${p.index}" aria-label="${esc(p.name)} 제거">×</button></td></tr>`).join('');}).join('')}</tbody></table>
 <details class="builder-cpu-options"><summary>CPU 내장그래픽 · 기본 쿨러 옵션</summary><label class="builder-option"><input id="builder-integrated" type="checkbox" ${integrated?'checked':''}> CPU 내장그래픽 사용 · 지원 근거 확인</label><label class="builder-option"><input id="builder-bundled" type="checkbox" ${bundled?'checked':''}> CPU 기본 쿨러 사용 · 포함 근거 확인</label></details>
 <p class="builder-pack-note">메모리 수량은 판매 패키지 기준입니다. 16GB × 2 세트는 패키지 1개, 총 32GB입니다. 실제 용량은 등록된 사양으로 표시합니다.</p></div>
 <footer class="builder-summary"><div class="builder-subtotal">부품가 <b id="builder-subtotal"></b> + 조립비 <b>${money(assemblyFee)}</b></div><div class="builder-money"><span>예상 합계</span><b id="builder-estimate"></b><span class="builder-state-unknown builder-status">호환 검사 전</span></div><div id="builder-missing" class="builder-missing" aria-live="polite"></div><button class="primary" id="builder-preview">${busy?'검사 중…':'구성·가격 확인 →'}</button><small>검토 대기 등록 이후 고객 공개·추천 승인 별도</small></footer></section></div>`;
 updateSummary();
 screen.querySelector('.builder-part-list').scrollTop=listTop;screen.querySelector('.builder-selection-scroll').scrollTop=selectionTop;
 if(optionsOpen)screen.querySelector('.builder-cpu-options').open=true;
 if(searchFocus){const search=screen.querySelector('#builder-search');search.focus({preventScroll:true});search.setSelectionRange(cursor,cursor);}
 screen.querySelectorAll('input,select').forEach(el=>{el.disabled=busy;});
}
screen.addEventListener('input',e=>{const t=e.target;if(t.id==='builder-title'){title=t.value;invalidate();updateSummary();}if(t.dataset.qty!==undefined){parts[Number(t.dataset.qty)].quantity=Number(t.value);invalidate();const amount=document.querySelector('#builder-estimate');if(amount)amount.textContent=money(parts.reduce((s,p)=>s+p.unit_price*p.quantity,0)+assemblyFee);const line=screen.querySelector(`[data-line-total="${t.dataset.qty}"]`),caption=screen.querySelector(`[data-quantity-note="${t.dataset.qty}"]`);if(line)line.textContent=money(parts[Number(t.dataset.qty)].unit_price*Number(t.value));if(caption)caption.textContent=quantityNote(parts[Number(t.dataset.qty)]);updateSummary();}if(t.id==='builder-search'){q=t.value;offset=0;clearTimeout(searchTimer);searchTimer=setTimeout(load,350);}});
screen.addEventListener('change',e=>{const t=e.target;if(t.id==='builder-source'){source=t.value;offset=0;load();}if(t.id==='builder-integrated'){integrated=t.checked;invalidate();draw();}if(t.id==='builder-bundled'){bundled=t.checked;invalidate();draw();}});
async function act(e){const t=e.target.closest('button');if(!t||busy)return;if(t.dataset.step){step=Number(t.dataset.step);if(step===2&&!preview){note('부품 구성에서 구성·가격 확인을 먼저 진행해 주세요.',true);step=1;}draw();return;}if(t.dataset.source){source=t.dataset.source;offset=0;load();return;}if(t.dataset.adjust!==undefined){const p=parts[Number(t.dataset.adjust)];p.quantity=Math.min(16,Math.max(1,(Number(p.quantity)||1)+Number(t.dataset.delta)));invalidate();draw();return;}if(t.id==='builder-clear'){if(confirm('현재 구성 초안을 초기화하시겠습니까? 저장된 제품군은 변경되지 않습니다.')){parts=[];title='';integrated=false;bundled=false;requestId=crypto.randomUUID();invalidate();note('구성 초안 초기화 완료');draw();}return;}if(t.dataset.slot){slot=t.dataset.slot;offset=0;load();return;}if(t.dataset.add){if(loading)return;const p=items.find(p=>p.code===Number(t.dataset.add));if(p){if(!['RAM','SSD'].includes(p.slot)&&parts.some(x=>x.slot===p.slot)){note('같은 종류의 부품을 제거한 뒤 추가해 주세요.',true);return;}parts.push({...p,quantity:1,source});invalidate();draw();}return;}if(t.dataset.remove!==undefined){parts.splice(Number(t.dataset.remove),1);invalidate();draw();return;}
 if(t.id==='builder-prev'||t.id==='builder-next'){offset+=t.id==='builder-next'?20:-20;load();return;}
 if(t.id==='builder-reset'){parts=[];title='';integrated=false;bundled=false;requestId=crypto.randomUUID();invalidate();step=1;note('새 구성을 시작합니다.');draw();return;}
 if(t.id==='builder-preview'||t.id==='builder-save'){busy=true;draw();try{const result=await api('/api/admin/pc-builder/'+(t.id==='builder-save'?'save':'preview'),input());if(t.id==='builder-save'){saved=result;forget();note('검토 대기 저장 완료');}else{preview=result;step=2;note('현재 부품·가격·호환 규칙 기준으로 확인했습니다.');}}catch(e){if(t.id==='builder-save')preview=null;note(e.message,true);if(!preview)step=1;}finally{busy=false;draw();}}
}
screen.addEventListener('click',act);document.querySelector('.builder-steps').addEventListener('click',act);draw();start();
})();
