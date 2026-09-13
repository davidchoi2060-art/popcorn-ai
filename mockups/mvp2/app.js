if(!window.PopcornApp){(function(){'use strict';
// CUS-QUO-010 — A-128 ③ 실 API 연결(2026-09-13). 화면은 숫자·부품·판정을 지어내지 않는다.
//   ① POST /api/talk/parse   {text, history}   → constraints(단일 원천)·reply·pc_related
//   ② POST /api/grid/recommend {constraints}   → cards[] (이름·total·over_budget·parts·reasons 전부 서버 값)
//   ③ GET  /api/grid/workstations?usage=&budget_won= → shown 일 때 AI 워크스테이션 진열
// 파싱은 서버만 한다 — 화면에 정규식 파서를 두지 않는다(둘이 갈린다).
// 실패는 삼키지 않는다 — 고객에게는 읽을 수 있는 한 줄 + 다시 시도(폴백 UI 없음, A-128). 서버 원문은 console.warn 으로만.
const $=s=>document.querySelector(s);
const money=n=>Number.isFinite(n)?new Intl.NumberFormat('ko-KR').format(n):'—';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const copy=x=>JSON.parse(JSON.stringify(x));
const API='';   // 같은 오리진(127.0.0.1:8000)에서 서빙 — 외부 CDN·절대 주소 없음
const HISTORY_MAX=6;         // api/talk.HISTORY_MAX_TURNS 와 같은 수(서버도 잘라낸다)
const USAGE_AI='AI 작업';    // api/grid_workstations.USAGE_AI 와 같은 값
const SPEC_CATS=['CPU','그래픽카드','메모리','저장장치'];   // 카드 스펙 4칸 — parts[].cat 로 찾는다
const POSTER='assets/pc-front.png';   // 대표 예시 이미지(④ 소관) — 카드·견적 공통, 캡션으로 예시임을 밝힌다
// 조건 수정 다이얼로그의 용도 select 는 하드코딩하지 않는다 — state.usages(서버 용도 목록의 label)로 런타임 생성.
const SAVE_KEY='popcorn-quotes-v2';   // 옛 키(popcorn-demo-quotes)는 가짜 가격이라 읽지 않는다
const state={constraints:[],history:[],quotes:[],grid:null,selected:null,busy:false,retry:null,usages:null,videoUrl:null,saved:[]};
try{const saved=JSON.parse(localStorage.getItem(SAVE_KEY)||'[]');if(Array.isArray(saved))state.saved=saved.filter(x=>x&&Array.isArray(x.parts)&&Number.isFinite(x.total)).slice(0,10);}catch{}
function toast(message){$('#toast').textContent=message;$('#toast').classList.add('show');clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('#toast').classList.remove('show'),3200);}

// ── API ────────────────────────────────────────────────────────────────────
async function api(method,url,body){
 let res;
 try{res=await fetch(API+url,{method,headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined});}
 catch(e){throw new Error('서버에 연결하지 못했습니다(네트워크) — '+e.message);}
 let data=null;try{data=await res.json();}catch{}
 if(!res.ok){
  const d=data&&data.detail;
  if(d&&typeof d==='object')console.warn('api error detail',url,res.status,d);
  let msg;
  if(typeof d==='string')msg=(res.status===429?'요청이 많아 잠시 기다려 주세요':res.status>=500?'서버 오류':'요청 오류')+`(${res.status}) — ${d}`;
  else if(d&&typeof d==='object'&&d.message)msg=String(d.message);
  else if(d&&typeof d==='object'&&d.error==='rate_limited')msg='요청이 많아 잠시 기다려 주세요'+(Number.isFinite(d.retry_after_sec)?`(${d.retry_after_sec}초 후)`:'');
  else msg=(res.status===429?'요청이 많아 잠시 기다려 주세요':'서버 오류')+`(${res.status})`;
  throw new Error(msg);
 }
 return data||{};
}
function pushHistory(role,text){state.history.push({role,text:String(text).slice(0,300)});state.history=state.history.slice(-HISTORY_MAX);}
function setBusy(on){state.busy=on;document.querySelectorAll('#startForm .send,#chatForm .send,[data-purpose],[data-chat],[data-prompt],[data-action="retry"]').forEach(b=>{if(b.dataset.done)return;b.disabled=on;});}

// ── 말풍선 ─────────────────────────────────────────────────────────────────
function addMessage(role,content,html=false){const node=document.createElement('div');node.className='message '+role;node.innerHTML=role==='user'?`<div class="user-bubble">${esc(content)}</div>`:`<div class="assistant-label"><span class="ai-mark">✦</span>팝콘PC AI</div><div class="assistant-text">${html?content:esc(content)}</div>`;$('#messages').append(node);scrollChat();return node;}
function showError(err,retry){state.retry=retry;addMessage('assistant',`<strong>요청에 실패했습니다.</strong>\n${esc(err&&err.message||err)}<div class="change-actions"><button class="secondary" data-action="retry">다시 시도</button></div>`,true);}
function scrollChat(){requestAnimationFrame(()=>{$('#messages').scrollTop=$('#messages').scrollHeight;});}
function showWorkspace(){ $('#welcome').hidden=true;$('#welcomeFoot').hidden=true;$('#workspace').hidden=false; }
function setQuick(){$('#quickActions').innerHTML=['예산을 100만원으로','영상 편집 위주로','사무용으로 추천해줘'].map(t=>`<button data-chat="${esc(t)}">${esc(t)}</button>`).join('');}

// ── ① 입력 → 파서 ──────────────────────────────────────────────────────────
async function submit(text){
 text=(text||'').trim();if(!text||state.busy)return;
 showWorkspace();selectTab('chat');
 addMessage('user',text);pushHistory('user',text);
 const thinking=addMessage('assistant','조건을 읽는 중…');
 setBusy(true);
 let p;
 try{p=await api('POST','/api/talk/parse',{text,history:state.history.slice(0,-1)});}
 catch(e){thinking.remove();setBusy(false);showError(e,()=>{state.history.pop();submit(text);});return;}
 thinking.remove();
 state.constraints=Array.isArray(p.constraints)?p.constraints.filter(c=>c&&c.l&&c.v):[];
 const reply=p.reply||'';
 if(reply){addMessage('assistant',reply);pushHistory('assistant',reply);}
 if(Array.isArray(p.dropped)&&p.dropped.length){addMessage('assistant','반영하지 못한 조건: '+p.dropped.map(d=>`${d.l||'?'}=${d.v||'?'}(${d.reason||'사유 없음'})`).join(' · '));}
 if(p.pc_related===false){setBusy(false);return;}   // 서버 판정 — 카드로 가지 않는다(null 은 모름이라 진행)
 await recommend();
 setBusy(false);
}

// ── ② constraints → 격자 카드 ─────────────────────────────────────────────
async function recommend(){
 document.querySelectorAll('[data-select]').forEach(b=>b.disabled=true);
 let g;
 try{g=await api('POST','/api/grid/recommend',{constraints:state.constraints});}
 catch(e){showError(e,()=>{setBusy(true);recommend().finally(()=>setBusy(false));});return;}
 state.grid=g;state.quotes=Array.isArray(g.cards)?g.cards:[];state.selected=null;
 $('#workspace').classList.remove('has-quote','mobile-quote');
 const needsUsage=Array.isArray(g.needs)&&g.needs.includes('용도');
 const node=document.createElement('div');node.className='message recommendation-message';
 node.innerHTML=conditionsMarkup(needsUsage)+(needsUsage?'':recommendationMarkup(g));
 $('#messages').append(node);setQuick();
 requestAnimationFrame(()=>{const m=$('#messages');m.scrollTop=node.offsetTop-m.offsetTop-16;});
 loadUsages(node);
 if(!needsUsage&&g.usage_grid===USAGE_AI)await workstations(node,g);
}
async function loadUsages(node){
 if(!state.usages){try{const u=await api('GET','/api/usages');state.usages=Array.isArray(u.usages)?u.usages:[];}catch(e){state.usages=null;const box=node.querySelector('.purpose-options');if(box)box.innerHTML=`<span class="condition-note">용도 목록을 불러오지 못했습니다 — ${esc(e.message)}</span>`;return;}}
 const box=node.querySelector('.purpose-options');if(box)box.innerHTML=purposeButtons();
}
function currentUsage(){const c=state.constraints.find(x=>x.l==='용도');return c?c.v:null;}
function purposeButtons(){const cur=currentUsage();return (state.usages||[]).map(u=>`<button type="button" data-purpose="${esc(u.label)}" aria-pressed="${cur===u.label}" class="${cur===u.label?'active':''}"><span class="purpose-radio" aria-hidden="true"></span><span><b>${esc(u.label)}</b>${u.floor_note?`<small>${esc(u.floor_note)}</small>`:''}</span></button>`).join('');}
function conditionsMarkup(needsUsage){
 const chips=state.constraints.map(c=>`<button data-action="conditions">${esc(c.l)}: ${esc(c.v)} ✎</button>`).join('');
 return `<div class="purpose-picker"><div class="purpose-heading"><b>${needsUsage?'어떤 용도로 사용하시나요?':'용도를 바꾸려면 고르세요'}</b><span>하나만 고르세요</span></div><div class="purpose-options" role="group" aria-label="PC 사용 용도">${state.usages?purposeButtons():'<span class="condition-note">용도 목록 불러오는 중…</span>'}</div></div><div class="condition-row"><span class="condition-label">내 조건</span>${chips||'<span class="condition-note">읽힌 조건 없음</span>'}</div>`;
}
function specRows(card){
 const parts=Array.isArray(card.parts)?card.parts:[];
 return SPEC_CATS.map(cat=>{const p=parts.find(x=>x&&x.cat===cat);return `<div><dt>${esc(cat)}</dt><dd>${p?esc(p.name||'이름 없음')+(p.in_stock===false?' <em>재고 확인 필요</em>':''):'—'}</dd></div>`;}).join('');
}
function recommendationMarkup(g){
 const cards=state.quotes;
 const cardHtml=cards.map((q,i)=>{const badges=[q.tier?`<span class="rec-tag">${esc(q.tier)}</span>`:'',q.over_budget?'<span class="rec-tag">예산 초과</span>':''].join('');
  const reason=Array.isArray(q.reasons)&&q.reasons.length?q.reasons[0]:'';
  return `<article class="rec-card"><button class="rec-media" data-build-video="${i}" aria-label="${esc(q.name)} 대표 예시 이미지 보기"><img src="${POSTER}" alt="대표 예시 이미지 — 실제 구성과 다릅니다"><span class="rec-media-badge">대표 예시 이미지</span><span class="rec-media-play" aria-hidden="true">▶</span><span class="rec-media-caption">대표 예시 이미지 ↗</span></button><div class="rec-top"><span class="rec-num">구성 0${i+1}</span><span>${badges}</span></div><h3>${esc(q.name||'이름 없음')}</h3><div class="rec-price">${money(q.total)}<small>원</small></div><p class="rec-desc">${esc(reason)}</p><dl class="rec-specs">${specRows(q)}</dl><button class="primary" data-select="${i}">이 구성 자세히 보기 ↗</button></article>`;}).join('');
 const empties=Array.isArray(g.empty_cells)?g.empty_cells:[];
 const emptyHtml=empties.map(e=>`<p class="condition-note">${esc(e.tier||'')}: ${esc(e.reason||'')}</p>`).join('');
 const none=cards.length?'':`<p class="condition-note">이 조건에 맞는 격자 카드가 없습니다.${g.note?' '+esc(g.note):''}</p>`;
 return `<div class="recommendations">${cardHtml}</div>${none}${emptyHtml}<div data-workstations></div><p class="demo-note">카드 이미지는 대표 예시 이미지입니다(실제 구성과 다릅니다). 부품명·가격·재고는 서버 값입니다.</p>`;
}

// ── ③ AI 워크스테이션 진열 ───────────────────────────────────────────────
async function workstations(node,g){
 const slot=node.querySelector('[data-workstations]');if(!slot)return;
 const q=new URLSearchParams({usage:g.usage_grid});
 if(Number.isFinite(g.budget_won))q.set('budget_won',String(g.budget_won));
 if(g.budget_bound)q.set('budget_bound',g.budget_bound);
 let w;
 try{w=await api('GET','/api/grid/workstations?'+q.toString());}
 catch(e){slot.innerHTML=`<p class="condition-note">AI 워크스테이션 진열을 불러오지 못했습니다 — ${esc(e.message)} <button class="secondary" data-action="retry">다시 시도</button></p>`;state.retry=()=>workstations(node,g);return;}
 if(!w.shown)return;   // 서버 판정 — 안 보일 때는 자리도 두지 않는다
 const items=Array.isArray(w.items)?w.items:[];
 const cards=items.map(it=>`<article class="rec-card"><div class="rec-top"><span class="rec-num">완제품</span><span>${it.over_budget?'<span class="rec-tag">예산 초과</span>':''}${it.in_stock===false?'<span class="rec-tag">재고 확인 필요</span>':''}</span></div><h3>${esc(it.name||'이름 없음')}</h3><div class="rec-price">${money(it.price)}<small>원</small></div><p class="rec-desc">${esc(specSummary(it.spec))}</p><a class="primary" href="${esc(it.mall_url||'#')}" target="_blank" rel="noopener">팝콘PC 몰에서 보기 ↗</a></article>`).join('');
 slot.innerHTML=`<div class="parts-heading"><b>팝콘PC AI 워크스테이션</b><span>완제품</span></div>${cards?`<div class="recommendations">${cards}</div>`:''}${w.note?`<p class="condition-note">${esc(w.note)}</p>`:''}`;
}
function specSummary(spec){
 if(!spec||typeof spec!=='object')return '사양 정보 없음';
 const out=[];if(spec.cpu)out.push('CPU '+spec.cpu);if(spec.ram_gb!=null)out.push('메모리 '+spec.ram_gb+'GB');if(spec.ssd)out.push('SSD '+spec.ssd);if(spec.gpu)out.push('GPU '+spec.gpu+(spec.gpu_count>1?' ×'+spec.gpu_count:''));
 return out.join(' · ')||'사양 정보 없음';
}

// ── ⑤ 카드 선택 → 오른쪽 패널(서버 카드 그대로) ──────────────────────────
function selectQuote(index){const q=state.quotes[index];if(!q)return;state.selected=copy(q);$('#workspace').classList.add('has-quote');addMessage('user',(q.name||'선택한 구성')+' 자세히 볼게요.');addMessage('assistant','오른쪽에 부품과 이유를 펼쳤어요. 부품 교체 대화는 준비 중입니다.');renderQuote();selectTab('quote');}
function renderQuote(){
 const q=state.selected;if(!q)return;const parts=Array.isArray(q.parts)?q.parts:[];const reasons=Array.isArray(q.reasons)?q.reasons:[];
 // 배지는 서버 over_budget 만 — '예산 이내'를 화면이 유도하지 않는다. 저장 견적(fromSaved)은 다른 대화의 예산이라 배지 없음.
 const verdict=(!q.fromSaved&&q.over_budget===true)?'<span class="under over">예산 초과</span>':'';
 $('#quotePane').innerHTML=`<div class="quote-top"><span class="eyebrow">내 구성${q.tier?' · '+esc(q.tier):''}</span></div><div class="quote-title"><div><h2>${esc(q.name||'이름 없음')}</h2><p>${esc([q.usage,q.platform].filter(Boolean).join(' · '))}</p></div><div class="quote-total">${money(q.total)}<small>원</small>${verdict}</div></div><div class="quote-media"><img src="${POSTER}" alt="대표 예시 이미지 — 실제 구성과 다릅니다"><div class="media-caption">대표 예시 이미지<small>실제 부품은 아래 목록 기준</small></div><button data-action="video" aria-label="대표 예시 이미지 크게 보기">▶</button></div><div class="quote-reason"><b>✦ 이렇게 골랐어요</b>${reasons.length?'<ul>'+reasons.map(r=>`<li>${esc(r)}</li>`).join('')+'</ul>':'<br>서버가 준 이유가 없습니다.'}</div><div class="parts-heading"><b>구성 부품 <span>${parts.length}종</span></b><span>서버 가격 · 원</span></div><table class="parts" aria-label="현재 견적 부품 목록"><tbody>${parts.map(p=>`<tr><td class="category">${esc(p.cat)}</td><td class="part-name">${esc(p.name||'이름 없음')}${p.in_stock===false?' <em>재고 확인 필요</em>':''}</td><td class="part-price">${money(p.price)}</td></tr>`).join('')}</tbody></table><p class="quote-disclaimer">재고는 조회 시점 기준입니다.${q.generated_at?' 견적 생성 '+esc(String(q.generated_at).slice(0,10))+'.':''}</p><div class="quote-actions"><button class="secondary" data-action="save">견적 저장</button><button class="primary" data-action="cart" title="준비 중">장바구니 담기(준비 중)</button></div>`;
}
function requestChange(text){
 text=(text||'').trim();if(!text)return;
 if(!state.selected){submit(text);return;}
 addMessage('user',text);addMessage('assistant','부품 교체 대화는 준비 중입니다.');
}
function selectTab(tab){$('#workspace').classList.toggle('mobile-quote',tab==='quote');document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));}
function save(){if(!state.selected)return;const saved={...copy(state.selected),constraints:copy(state.constraints),savedAt:new Date().toISOString()};state.saved.unshift(saved);state.saved=state.saved.slice(0,10);try{localStorage.setItem(SAVE_KEY,JSON.stringify(state.saved));toast('이 브라우저에 견적을 저장했어요.');}catch{toast('브라우저 저장이 제한되어 이번 화면에서만 보관해요.');}$('#savedCount').textContent=state.saved.length;}
function showSaved(){$('#savedList').innerHTML=state.saved.length?state.saved.map((q,i)=>`<div class="saved-item"><div><b>${esc(q.name)}</b><small>${money(q.total)}원 · ${new Date(q.savedAt).toLocaleDateString('ko-KR')}</small></div><button class="primary" data-load="${i}">불러오기</button></div>`).join(''):'<div class="empty-saved">아직 저장한 견적이 없어요.<br>구성을 선택한 뒤 “견적 저장”을 눌러주세요.</div>';$('#savedDialog').showModal();}
async function showConditions(){const f=$('#conditionsForm');const b=state.grid&&Number.isFinite(state.grid.budget_won)?Math.round(state.grid.budget_won/10000):'';f.elements.budget.value=b;const cur=currentUsage();
 if(!state.usages){try{const u=await api('GET','/api/usages');state.usages=Array.isArray(u.usages)?u.usages:[];}catch(e){toast('용도 목록을 불러오지 못했습니다 — '+e.message);}}
 const sel=f.elements.purpose;sel.innerHTML=(state.usages||[]).map(u=>`<option value="${esc(u.label)}"${u.label===cur?' selected':''}>${esc(u.label)}</option>`).join('')||(cur?`<option value="${esc(cur)}" selected>${esc(cur)}</option>`:'');f.elements.monitor.checked=state.constraints.some(c=>c.l==='제외'&&/모니터 보유/.test(c.v));$('#conditionsDialog').showModal();}
function addToCart(){toast('장바구니는 준비 중입니다.');}
function openVideo(q){$('#videoDialog h2').textContent=q&&q.name?q.name+' · 대표 예시 이미지':'만들어지는 순간까지, 투명하게.';$('#previewVideo').pause();$('#previewVideo').removeAttribute('src');$('#previewVideo').poster=POSTER;$('#videoPoster').src=POSTER;const video=state.videoUrl;$('#previewVideo').hidden=!video;$('#videoPoster').hidden=!!video;$('#videoEmpty').hidden=!!video;if(video){$('#previewVideo').src=video;$('#previewVideo').load();}$('#videoDialog').showModal();}
function home(){$('#welcome').hidden=false;$('#welcomeFoot').hidden=false;$('#workspace').hidden=true;$('#messages').innerHTML='';$('#quotePane').innerHTML='<div class="quote-empty"><span class="ai-mark">✦</span><h2>마음에 드는 구성을<br>골라주세요.</h2><p>구성을 고르면<br>부품과 이유를 볼 수 있어요.</p></div>';/* 교체 대화가 붙으면 「대화로 조정할 수 있어요」로 되돌린다 */state.selected=null;state.constraints=[];state.history=[];state.quotes=[];state.grid=null;state.retry=null;$('#workspace').classList.remove('has-quote','mobile-quote');$('#startInput').value='';window.scrollTo(0,0);$('#startInput').focus();}

document.addEventListener('click',e=>{
 const b=e.target.closest('button');if(!b)return;
 if(b.dataset.close){$('#'+b.dataset.close).close();return;}
 if(b.dataset.prompt){$('#messages').innerHTML='';submit(b.dataset.prompt);return;}
 if(b.dataset.chat){requestChange(b.dataset.chat);return;}
 if(b.dataset.purpose){submit(b.dataset.purpose+'용으로 쓸 거예요');return;}
 if(b.dataset.buildVideo!==undefined){openVideo(state.quotes[Number(b.dataset.buildVideo)]);return;}
 if(b.dataset.select!==undefined){selectQuote(Number(b.dataset.select));return;}
 if(b.dataset.tab){selectTab(b.dataset.tab);return;}
 if(b.dataset.load!==undefined){const q=copy(state.saved[Number(b.dataset.load)]);if(!q)return;$('#savedDialog').close();showWorkspace();state.constraints=Array.isArray(q.constraints)?q.constraints:[];q.fromSaved=true;state.selected=q;$('#messages').innerHTML='';$('#workspace').classList.add('has-quote');addMessage('assistant','저장한 '+(q.name||'견적')+'을 불러왔어요(저장 시점 값 — 현재 가격·재고와 다를 수 있어요).');setQuick();renderQuote();selectTab('quote');return;}
 const actions={home,saved:showSaved,video:()=>openVideo(state.selected),conditions:showConditions,save,cart:addToCart,retry:()=>{const r=state.retry;state.retry=null;if(r){b.disabled=true;b.dataset.done='1';r();}/* A7: 한 번 누른 '다시 시도'는 성공 후에도 다시 살리지 않는다 */}};
 actions[b.dataset.action]?.();
});
function init(){
 if(!$('#startForm')||!$('#videoFile')||!$('#toast')){setTimeout(init,120);return;}
 if(init.done)return;init.done=true;
 $('#startForm').addEventListener('submit',e=>{e.preventDefault();const text=$('#startInput').value.trim();if(text){$('#messages').innerHTML='';submit(text);}});
 $('#chatForm').addEventListener('submit',e=>{e.preventDefault();const text=$('#chatInput').value.trim();$('#chatInput').value='';requestChange(text);});
 document.querySelectorAll('textarea').forEach(t=>t.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();t.form.requestSubmit();}}));
 // 조건 수정 다이얼로그 — 화면이 조건을 직접 만들지 않는다. 문장으로 바꿔 파서에 보낸다.
 $('#conditionsForm').addEventListener('submit',e=>{e.preventDefault();const f=e.currentTarget;const budget=Number(f.elements.budget.value);const label=f.elements.purpose.value;const parts=[];if(Number.isFinite(budget)&&budget>0)parts.push(`예산 ${budget}만원 이하`);if(label)parts.push(`${label}용`);if(f.elements.monitor.checked)parts.push('모니터는 있어요');$('#conditionsDialog').close();submit('조건을 바꿀게요. '+parts.join(', '));});
 $('#videoFile').addEventListener('change',e=>{const f=e.target.files[0];if(!f)return;if(!f.type.startsWith('video/')){toast('동영상 파일을 선택해주세요.');return;}if(state.videoUrl)URL.revokeObjectURL(state.videoUrl);state.videoUrl=URL.createObjectURL(f);$('#previewVideo').src=state.videoUrl;$('#previewVideo').hidden=false;$('#videoPoster').hidden=true;$('#videoEmpty').hidden=true;$('#previewVideo').play().catch(()=>toast('재생 버튼을 눌러 영상을 확인해주세요.'));});
 $('#previewVideo').addEventListener('error',()=>{toast('이 브라우저에서 재생 가능한 MP4 또는 WebM 영상을 선택해주세요.');$('#previewVideo').hidden=true;$('#videoPoster').hidden=false;$('#videoEmpty').hidden=false;});
 $('#videoDialog').addEventListener('close',()=>$('#previewVideo').pause());
 document.querySelectorAll('dialog').forEach(d=>d.addEventListener('click',e=>{if(e.target===d){const r=d.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)d.close();}}));
 $('#savedCount').textContent=state.saved.length;
}
window.PopcornApp={init};
// 선택적 페이지 도구 — 화면과 같은 상태(서버 값)를 읽는다.
if(document.modelContext?.registerTool){
 const lifecycle=new AbortController();
 const toolSpecs=[
  {name:'start_pc_recommendation',description:'Send a Korean PC request to the parser and grid APIs (live server data).',inputSchema:{type:'object',properties:{request:{type:'string',minLength:1,maxLength:300}},required:['request'],additionalProperties:false},async execute(input){if(typeof input?.request!=='string'||!input.request.trim()||input.request.length>300)throw new Error('A request of 1–300 characters is required.');await submit(input.request);return {constraints:copy(state.constraints),builds:state.quotes.map((q,i)=>({index:i,name:q.name,total:q.total,over_budget:q.over_budget}))};}},
  {name:'select_pc_build',description:'Select one of the current recommendation cards and show it in the quote pane.',inputSchema:{type:'object',properties:{index:{type:'integer',minimum:0}},required:['index'],additionalProperties:false},execute(input){if(!Number.isInteger(input?.index)||!state.quotes[input.index])throw new Error('Choose an available build index.');selectQuote(input.index);return {name:state.selected.name,total:state.selected.total};}},
  {name:'read_pc_quote',description:'Read the currently selected quote (server card) without modifying it.',annotations:{readOnlyHint:true},inputSchema:{type:'object',properties:{},additionalProperties:false},execute(){return {constraints:copy(state.constraints),quote:copy(state.selected)};}}
 ];
 for(const spec of toolSpecs){try{Promise.resolve(document.modelContext.registerTool({...spec,annotations:{readOnlyHint:false,...spec.annotations}},{signal:lifecycle.signal})).catch(()=>{});}catch{}}
 window.addEventListener('pagehide',()=>lifecycle.abort(),{once:true});
}

})();}
