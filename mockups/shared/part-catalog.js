// 조립 부품 판매 준비 — 조립PC 부품마다 판매 상품으로 팔 수 있는지와 막힌 이유 (부품 상품화 1단계)
// 판정은 서버(api/part_catalog.py)가 한다. 이 화면은 받은 판정을 그대로 그리고 수를 세지 않는다.
(()=>{'use strict';
const box=document.getElementById('pc-cat');if(!box)return;
const $=s=>box.querySelector(s),esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=x=>Number.isFinite(x)&&x>0?x.toLocaleString('ko-KR')+'원':'-';
const ORDER=['no_product','not_on_sale','no_price','missing_specs','ready'];
let state='',used=true,offset=0,limit=20,seq=0;
async function load(){
  const my=++seq,q=new URLSearchParams({state,used:String(used),offset:String(offset),limit:String(limit)});
  $('#pc-cat-msg').textContent='불러오는 중';
  let data;
  try{const r=await fetch('/api/admin/part-catalog?'+q,{credentials:'same-origin'});
    if(!r.ok){let j=null;try{j=await r.json();}catch{}throw new Error(window.popcornProgress?window.popcornProgress.errText(j,r.status,'부품 판매 준비'):'오류 '+r.status);}
    data=await r.json();}
  catch(e){if(my===seq)$('#pc-cat-msg').textContent='조회 실패: '+(e.message||e);return;}
  if(my!==seq)return;
  const s=used?data.summary.used_by_state:data.summary.by_state,all=used?data.summary.used:data.summary.total;
  $('#pc-cat-chips').innerHTML=`<button data-state="" aria-pressed="${state===''}">전체 ${all}</button>`+
    ORDER.map(k=>`<button data-state="${k}" data-kind="${k}" aria-pressed="${state===k}">${esc(data.state_labels[k])} ${s[k]}</button>`).join('');
  $('#pc-cat-msg').textContent=data.rule_count?`호환 규칙 ${data.rule_count}개 기준 · ${data.note}`:'활성 호환 규칙이 없어 사양 판정을 하지 못합니다.';
  $('#pc-cat-rows').innerHTML=data.items.length?data.items.map(i=>`<tr>
    <td><b>${esc(i.name)}</b><small>${esc(i.slot_label)} · ${i.product_code==null?'상품 없음 ('+i.code+')':'상품 '+i.product_code}</small></td>
    <td><span class="pc-cat-state" data-kind="${esc(i.state)}">${esc(i.state_label)}</span>${i.reasons.length>1?`<small>${esc(i.reasons.slice(1).join(' · '))}</small>`:''}${i.missing_fields.length?`<small>빠진 사양: ${esc(i.missing_fields.join(', '))}</small>`:''}${i.conditional_missing.length?`<small>짝에 따라 필요: ${esc(i.conditional_missing.join(', '))}</small>`:''}</td>
    <td class="num" data-label="판매가">${money(i.sale_price)}${i.sale_status?`<small>${esc(i.sale_status)}</small>`:''}</td>
    <td class="num" data-label="재고">${i.stock_qty??'-'}</td>
    <td class="num" data-label="사용 PC">${i.active_configuration_count}</td></tr>`).join(''):'<tr><td colspan="5" class="pc-cat-empty">해당 부품 없음</td></tr>';
  const page=Math.floor(offset/limit)+1,pages=Math.max(1,Math.ceil(data.total/limit));
  $('#pc-cat-page').textContent=`${page} / ${pages} · ${data.total}개`;
  $('#pc-cat-prev').disabled=offset===0;$('#pc-cat-next').disabled=offset+limit>=data.total;
}
$('#pc-cat-chips').addEventListener('click',e=>{const b=e.target.closest('button[data-state]');if(!b)return;state=b.dataset.state;offset=0;load();});
$('#pc-cat-used').addEventListener('change',e=>{used=e.target.checked;offset=0;load();});
$('#pc-cat-prev').addEventListener('click',()=>{offset=Math.max(0,offset-limit);load();});
$('#pc-cat-next').addEventListener('click',()=>{offset+=limit;load();});
load();
})();
