(function(){'use strict';
const $=id=>document.getElementById(id),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let rows=[],kind='',page=0,size=20,query='';
try{const saved=JSON.parse(localStorage.getItem('admin.new.queue')||'{}');size=[10,20,30].includes(saved.size)?saved.size:20;query=String(saved.query||'').slice(0,100);kind=['copy','price','review'].includes(saved.kind)?saved.kind:'';}catch(_){}
$('an-size').value=String(size);$('an-search').value=query;
function draw(){
 const q=query.trim().toLocaleLowerCase();const hits=rows.filter(r=>(!kind||r.task_kind===kind)&&(!q||JSON.stringify([r.configuration_id,r.title,r.task_reason,r.facts,r.parts]).toLocaleLowerCase().includes(q)));
 page=Math.min(page,Math.max(0,Math.ceil(hits.length/size)-1));
 const names={copy:'정보 보완',price:'가격 확인',review:'검토 대기'},next={copy:'설명·AI 초안 확인',price:'가격·판매 조건 확인',review:'구성·호환·근거 검토'};
 $('an-rows').innerHTML=hits.slice(page*size,(page+1)*size).map(r=>`<tr><td><a class="an-product" href="/admin2/pc-workspace?id=${encodeURIComponent(r.configuration_id)}">${r.image_url?`<img src="${esc(r.image_url)}" alt="" loading="lazy">`:''}<span>${esc(r.title||r.configuration_id)}<small>${esc(r.configuration_id)}</small></span></a></td><td>${esc(r.task_reason)}</td><td>${esc(next[r.task_kind]||'제품 확인')}</td><td><span class="an-badge">${esc(names[r.task_kind]||'확인 필요')}</span></td></tr>`).join('')||'<tr><td colspan="4">조건에 맞는 작업이 없습니다.</td></tr>';
 $('an-status').textContent=`작업 ${hits.length}건 · 전체 작업 ${rows.length}건`;$('an-page').textContent=hits.length?`${page+1} / ${Math.ceil(hits.length/size)}`:'0 / 0';$('an-prev').disabled=page===0;$('an-next').disabled=(page+1)*size>=hits.length;
 document.querySelectorAll('.an-filters [data-kind]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.kind===kind)));
 try{localStorage.setItem('admin.new.queue',JSON.stringify({size,query,kind}));}catch(_){}
}
async function load(){ $('an-refresh').disabled=true;try{const res=await fetch('/api/admin/pc-workspace/tasks',{credentials:'same-origin'});if(!res.ok)throw new Error(`조회 실패 (${res.status})`);const data=await res.json();if(!Array.isArray(data.items))throw new Error('작업 목록 형식 확인 필요');rows=data.items;for(const key of ['copy','price','review'])$('an-'+key).textContent=String(data.counts[key]??'—');draw();}catch(e){rows=[];$('an-rows').innerHTML='';['copy','price','review'].forEach(k=>$('an-'+k).textContent='—');$('an-status').textContent=e.message+' · 새로고침으로 재시도';$('an-prev').disabled=$('an-next').disabled=true;$('an-page').textContent='';}finally{$('an-refresh').disabled=false;}}
document.querySelectorAll('[data-kind]').forEach(b=>b.addEventListener('click',()=>{kind=b.dataset.kind;page=0;draw();}));$('an-search').addEventListener('input',()=>{query=$('an-search').value;page=0;draw();});$('an-size').addEventListener('change',()=>{size=Number($('an-size').value);page=0;draw();});$('an-prev').onclick=()=>{page--;draw();};$('an-next').onclick=()=>{page++;draw();};$('an-refresh').onclick=load;load();
})();
