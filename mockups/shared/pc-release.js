// 신규 조립PC 고객 공개 (부품 상품화 4단계 · api/admin_pc_release.py).
// 판정·가격은 서버 값만 쓴다. 공개는 화면에서 본 가격을 함께 보내 그사이 판매가가 바뀌면 다시 확인하게 한다.
(()=>{
'use strict';
const box=document.querySelector('#release-screen');if(!box)return;
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=x=>x==null?'가격 확인 불가':Number(x).toLocaleString('ko-KR')+'원';
const STATE={public:['고객 공개 중','builder-state-pass'],hidden:['공개 기록 있음 · 고객 화면에서 빠짐','builder-state-unknown'],not_released:['비공개','builder-muted']};
let items=[],busy='',msg='',err=false,priceNote='';
async function call(url,body){
  const r=await fetch(url,{credentials:'same-origin',method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});
  let d={};try{d=await r.json();}catch{}
  if(!r.ok){const e=window.popcornProgress?.errText;throw Error(typeof d.detail==='string'?d.detail:(e?e(r.status,d):'요청 처리 실패 ('+r.status+')'));}
  return d;
}
async function load(){try{const d=await call('/api/admin/pc-releases');items=d.items;priceNote=d.price_note;}catch(e){items=null;msg=e.message;err=true;}draw();}
function card(x){
  const [label,cls]=STATE[x.release_state],c=x.check,id=esc(x.configuration_id);
  const parts=x.parts.map(p=>`<tr><td>${esc(p.slot_label)}</td><td>${esc(p.name)} × ${p.quantity}</td><td>${p.sale_status==='판매중'&&p.sale_price>0?money(p.sale_price*p.quantity):'<span class="builder-state-fail">'+esc(p.sale_status||'판매 상품 없음')+'</span>'}</td></tr>`).join('');
  const blockers=c.blockers.length?`<h3>공개 전 보완 항목</h3><ul>${c.blockers.map(b=>`<li class="builder-state-fail">${esc(b)}</li>`).join('')}</ul>`:'<p class="builder-state-pass">공개 점검 통과 · 부품 판매중 · 판매가 확인 · 호환 불일치 없음 · 구성 검토 승인</p>';
  const notes=c.notes.length?`<ul class="builder-muted">${c.notes.map(n=>`<li>${esc(n)}</li>`).join('')}</ul>`:'';
  const last=x.last_event?`<p class="builder-muted">최근 기록 · ${x.last_event.action==='release'?'고객 공개':'공개 중지'} · ${esc(x.last_event.at.slice(0,16).replace('T',' '))}${x.last_event.note?' · '+esc(x.last_event.note):''}</p>`:'';
  const open=x.last_event?.action==='release';
  const actions=`<div class="builder-actions"><a href="/admin2/pc-workspace?id=${encodeURIComponent(x.configuration_id)}">구성 검토 열기</a>`+
    (x.release_state!=='public'?`<button class="primary" data-release="${id}" data-price="${x.price??''}" ${busy||c.blockers.length||x.price==null?'disabled':''}>${busy===x.configuration_id?'처리 중…':'고객 공개'}</button>`:'')+
    (open?`<button data-withdraw="${id}" ${busy?'disabled':''}>공개 중지</button>`:'')+'</div>';
  return `<section class="builder-card" data-release-id="${id}"><div class="builder-card-head"><h2>${esc(x.title||x.configuration_id)}</h2><span>${id} · 판 ${x.revision}</span><b class="${cls}">${label}</b></div>`+
    (x.release_hidden_reason?`<p class="builder-state-unknown">${esc(x.release_hidden_reason)}</p>`:'')+
    `<table class="builder-bom"><thead><tr><th>부품</th><th>제품 · 수량</th><th>판매가</th></tr></thead><tbody>${parts}<tr><td colspan="2">조립비</td><td>${money(x.assembly_fee)}</td></tr></tbody></table>`+
    `<div class="builder-money"><span>지금 고객 가격</span><b>${money(x.price)}</b></div>${blockers}${notes}${last}${actions}</section>`;
}
function draw(){
  const head=`<h2 class="release-title">고객 공개</h2><p class="builder-note">「신규 조립PC 생성」으로 저장한 제품군을 고객 화면 「새로 구성된 PC」에 공개합니다. ${esc(priceNote)}. 부품이 품절되거나 호환 불일치가 생기면 고객 화면에서 자동으로 빠집니다. 쇼핑몰 상품번호가 없어 구매는 구매 상담 신청으로 받습니다.</p>`+
    (msg?`<p class="${err?'builder-error':'builder-success'}" role="status">${esc(msg)}</p>`:'');
  if(items===null){box.innerHTML=head;return;}
  box.innerHTML=head+(items.length?items.map(card).join(''):'<p class="builder-empty">신규 조립PC 생성에서 저장한 제품군이 없습니다.</p>');
}
box.addEventListener('click',async e=>{
  const b=e.target.closest('button');if(!b||busy)return;
  const id=b.dataset.release||b.dataset.withdraw;if(!id)return;
  let body;
  if(b.dataset.release){if(!confirm('고객 화면에 공개하시겠습니까? 지금 가격 '+money(Number(b.dataset.price))))return;body={expected_price:Number(b.dataset.price),note:''};}
  else{const reason=prompt('공개 중지 사유를 입력해 주세요.');if(!reason||!reason.trim())return;body={reason:reason.trim()};}
  busy=id;msg='';draw();
  try{const d=await call('/api/admin/pc-releases/'+encodeURIComponent(id)+'/'+(b.dataset.release?'release':'withdraw'),body);msg=d.note;err=false;}
  catch(x){msg=x.message;err=true;}
  finally{busy='';await load();}
});
load();
})();
