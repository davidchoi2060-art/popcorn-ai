if(!window.PopcornApp){(function(){'use strict';
const $=s=>document.querySelector(s);
const money=n=>new Intl.NumberFormat('ko-KR').format(n);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const copy=x=>JSON.parse(JSON.stringify(x));
const purposes={office:'사무용',game:'일반 게임용',highgame:'고사양 게임용',creator:'이미지/영상 작업용',ai:'AI 작업용'};
const purposeHints={office:'문서 · 인터넷 · 업무',game:'롤 · 발로란트 · 가벼운 게임',highgame:'고해상도 · 최신 게임',creator:'디자인 · 편집 · 렌더링',ai:'이미지 생성 · 로컬 AI'};
// Illustrative budget presets for the prototype, not market price guidance.
const purposeBudgets={office:700000,game:1200000,highgame:2200000,creator:2500000,ai:3500000};
function withPurpose(c,key){return {...c,purpose:key,budget:purposeBudgets[key],assumed:false,rangeLimited:false,budgetSource:'purpose',budgetChange:{from:c.budget,to:purposeBudgets[key]}};}
// Add a video URL per build when production videos are ready.
const buildMedia=[0,1,2].map(()=>({poster:'assets/pc-front.png',video:''}));
const state={conditions:null,quotes:[],selected:null,history:[],pending:null,videoUrl:null,revision:1,saved:[]};
try{const saved=JSON.parse(localStorage.getItem('popcorn-demo-quotes')||'[]');if(Array.isArray(saved))state.saved=saved.filter(x=>x&&Array.isArray(x.parts)&&x.conditions&&x.parts.every(p=>Number.isFinite(p.price))).slice(0,10);}catch{}
function toast(message){$('#toast').textContent=message;$('#toast').classList.add('show');clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('#toast').classList.remove('show'),3200);}
function total(q){return q.parts.reduce((n,p)=>n+p.price,0);}
function readConditions(text){
 const match=text.replace(/,/g,'').match(/(\d+(?:\.\d+)?)\s*만/);let budget=match?Math.round(Number(match[1])*10000):1500000;
 const ai=/\bAI\b|인공지능|로컬 모델|이미지 생성/i.test(text),high=/고사양|고해상도|4K.{0,8}게임|최신 게임/i.test(text),hasEdit=/편집|영상|렌더|디자인|포토샵|이미지/.test(text),office=/사무|문서|인강/.test(text);
 return {budget:Math.max(500000,Math.min(5000000,budget)),purpose:ai?'ai':hasEdit?'creator':high?'highgame':office?'office':'game',monitor:/모니터.{0,15}(있|보유|제외)/.test(text),quiet:/조용|저소음/.test(text),white:/화이트|흰색/.test(text),assumed:!match,rangeLimited:budget<500000||budget>5000000};
}
function mergeConditions(text,previous){
 const parsed=readConditions(text);if(!previous)return parsed;let c=copy(previous);
 if(/게임|배그|롤|발로란트|사무|인강|문서|영상|편집|렌더|디자인|이미지|AI|인공지능/i.test(text)&&parsed.purpose!==c.purpose)c=withPurpose(c,parsed.purpose);
 if(/\d+(?:\.\d+)?\s*만/.test(text)){c.budget=parsed.budget;c.assumed=false;c.rangeLimited=parsed.rangeLimited;c.budgetSource='user';c.budgetChange=null;}
 if(/모니터/.test(text))c.monitor=parsed.monitor;
 if(/조용|저소음/.test(text))c.quiet=true;if(/화이트|흰색/.test(text))c.white=true;
 return c;
}
function makeQuotes(c){
 const titles=c.purpose==='office'?['실속 사무형','조용한 사무형','여유로운 작업형']:c.purpose==='creator'?['디자인 입문형','편집 밸런스형','렌더링 집중형']:c.purpose==='ai'?['AI 입문형','AI 작업 밸런스형','GPU 메모리 집중형']:c.purpose==='highgame'?['고사양 게임 입문형','고사양 밸런스형','게임 성능 집중형']:['실속 게임형','밸런스 추천형','게임 성능형'];
 return [.79,.93,.99].map((factor,i)=>{
  const target=Math.floor(c.budget*factor/1000)*1000;
  const ram=c.purpose==='creator'||c.purpose==='ai'||c.purpose==='highgame'||i===2?'32GB (16GB × 2)':'16GB (8GB × 2)';
  const labels=c.purpose==='office'?['AMD Ryzen 5 · 내장 그래픽','A520M · DDR4','DDR4 '+ram,'CPU 내장 그래픽','NVMe SSD 500GB',c.white?'화이트 컴팩트 케이스':'블랙 컴팩트 케이스',c.quiet?'저소음 타워 쿨러':'기본 쿨러','정격 500W']:['AMD Ryzen 5 7500F','B650M · DDR5','DDR5 '+ram,i===0?'GeForce RTX 4060 8GB':i===1?'GeForce RTX 4060 Ti 8GB':'GeForce RTX 4070 12GB','NVMe SSD 1TB',c.white?'화이트 메쉬 케이스':'블랙 메쉬 케이스',c.quiet?'저소음 타워 쿨러':'타워 공랭 쿨러','정격 650W · 80 PLUS'];
  if(c.purpose==='ai')labels[3]=i===0?'GeForce RTX 3060 12GB':i===1?'GeForce RTX 4060 Ti 16GB':'GeForce RTX 3090 24GB · 예시';
  if(c.purpose==='highgame'){labels[0]=i===0?'AMD Ryzen 5 7600':'AMD Ryzen 7 7800X3D';labels[3]=i===0?'GeForce RTX 4070 12GB':i===1?'GeForce RTX 4070 SUPER 12GB':'GeForce RTX 4070 Ti SUPER 16GB';labels[4]='NVMe SSD 2TB';labels[7]='정격 850W · 80 PLUS Gold';}
  if(c.purpose==='creator'){labels[0]=i===0?'AMD Ryzen 7 7700':'AMD Ryzen 9 7900';labels[2]=i===0?'DDR5 32GB (16GB × 2)':'DDR5 64GB (32GB × 2)';labels[3]=i===0?'GeForce RTX 4060 Ti 16GB':'GeForce RTX 4070 SUPER 12GB';labels[4]='NVMe SSD 2TB';labels[7]='정격 750W · 80 PLUS Gold';}
  if(c.purpose==='ai'){labels[0]=i===0?'AMD Ryzen 7 7700':'AMD Ryzen 9 7900';labels[2]=i===0?'DDR5 32GB (16GB × 2)':'DDR5 64GB (32GB × 2)';labels[4]='NVMe SSD 2TB';labels[7]='정격 1000W · 80 PLUS Gold';}
  const weights=c.purpose==='office'?[.31,.19,.15,0,.15,.08,.04,.08]:c.purpose==='ai'?[.15,.10,.12,.43,.07,.05,.025,.055]:c.purpose==='creator'?[.25,.12,.14,.28,.08,.05,.025,.055]:c.purpose==='highgame'?[.18,.10,.10,.41,.08,.05,.025,.055]:[.20,.12,.10,.37,.08,.05,.025,.055];
  const cats=['CPU','메인보드','메모리','그래픽카드','저장장치','케이스','쿨러','파워'];
  const parts=cats.map((cat,k)=>({cat,name:labels[k],price:Math.floor(target*weights[k]/1000)*1000}));parts[0].price+=target-parts.reduce((n,p)=>n+p.price,0);
  return {id:i,name:titles[i],parts,media:copy(buildMedia[i]),conditions:copy(c),reason:i===0?`${purposes[c.purpose]}의 기본 구성에 집중해 예산 여유를 남겼어요.`:i===1?`${purposes[c.purpose]}에 맞춰 전체적인 균형을 고려했어요.`:`${purposes[c.purpose]}의 작업 성능을 우선한 예시예요.`,tradeoff:c.purpose==='ai'?'실행할 AI 모델에 따라 필요한 GPU 메모리가 달라져요.':i===0?'무거운 작업과 향후 확장에는 제약이 있어요.':i===1?'최고 사양보다 전체적인 균형을 우선해요.':'가격 여유가 적어 추가 옵션은 조정이 필요해요.'};
 });
}
function conditionsMarkup(){const c=state.conditions;return `<div class="purpose-picker"><div class="purpose-heading"><b>어떤 용도로 사용하시나요?</b><span>용도에 맞춰 예산과 부품을 함께 추천해요</span></div><div class="purpose-options" role="group" aria-label="PC 사용 용도">${Object.entries(purposes).map(([key,label])=>`<button type="button" data-purpose="${key}" aria-pressed="${c.purpose===key}" class="${c.purpose===key?'active':''}"><span class="purpose-radio" aria-hidden="true"></span><span><b>${label}</b><small>${purposeHints[key]}</small><em class="purpose-budget">기본 예산 ${money(purposeBudgets[key]/10000)}만원</em></span></button>`).join('')}</div></div><div class="condition-row"><span class="condition-label">내 조건</span><button data-action="conditions">${money(c.budget/10000)}만원 이하 ${c.budgetSource==='purpose'?'· 용도 기준':c.assumed?'· 임시':' '} ✎</button><button data-action="conditions">본체만 · OS 제외 ✎</button>${c.monitor?'<button data-action="conditions">모니터 보유 ✓</button>':''}${c.quiet?'<button data-action="conditions">저소음 선호 ✎</button>':''}</div><div class="condition-note">${c.rangeLimited?'목업 지원 범위인 50~500만원으로 조정했어요. ':''}용도 변경 시 기본 예산과 부품 구성을 함께 조정해요. 예산은 직접 수정할 수 있습니다. 기본 예산은 목업 예시입니다.</div>${c.budgetChange?`<div class="budget-update" role="status"><b>${purposes[c.purpose]}에 맞춰 예산을 조정했어요</b><span>${money(c.budgetChange.from/10000)}만원 → <strong>${money(c.budgetChange.to/10000)}만원</strong><small>부품 구성도 함께 변경</small></span></div>`:''}`;}
function recommendationMarkup(){return conditionsMarkup()+`<div class="recommendations">${state.quotes.map((q,i)=>`<article class="rec-card ${i===1?'featured':''}"><button class="rec-media" data-build-video="${i}" aria-label="${esc(q.name)} PC 이미지 및 영상 미리보기"><img src="${q.media.poster}" alt="${esc(q.name)} 위치에 들어갈 PC 대표 예시 이미지"><span class="rec-media-badge">PC 미리보기</span><span class="rec-media-play" aria-hidden="true">▶</span><span class="rec-media-caption">${q.media.video?'영상으로 살펴보기':'PC 이미지 · 영상 미리보기'} ↗</span></button><div class="rec-top"><span class="rec-num">구성 0${i+1}</span>${i===1?'<span class="rec-tag">추천</span>':'<span class="rec-tag">예시 구성</span>'}</div><h3>${q.name}</h3><div class="rec-price">${money(total(q))}<small>원</small></div><p class="rec-desc">${q.reason}</p><dl class="rec-specs">${[0,3,2,4].map(k=>`<div><dt>${q.parts[k].cat}</dt><dd>${esc(q.parts[k].name.replace('GeForce ','').replace('AMD ',''))}</dd></div>`).join('')}</dl><p class="tradeoff">${q.tradeoff}</p><button class="primary" data-select="${i}">이 구성으로 조정하기 ↗</button></article>`).join('')}</div><p class="demo-note">카드 이미지는 위치 확인용 공통 예시입니다. 부품명·가격·검증 상태도 화면 체험용 예시입니다.</p>`;}
function changePurpose(key,node){if(!purposes[key]||!state.conditions||state.conditions.purpose===key)return;state.conditions=withPurpose(state.conditions,key);state.quotes=makeQuotes(state.conditions);state.selected=null;state.history=[];state.pending=null;$('#workspace').classList.remove('has-quote','mobile-quote');selectTab('chat');node.innerHTML=recommendationMarkup();setQuick(false);toast(purposes[key]+' · 기본 예산 '+money(state.conditions.budget/10000)+'만원으로 구성도 변경했어요.');}
function openVideo(q){const media=q?.media||{poster:'assets/pc-front.png',video:''};$('#videoDialog h2').textContent=q?q.name+' · PC 미리보기':'만들어지는 순간까지, 투명하게.';$('#previewVideo').pause();$('#previewVideo').removeAttribute('src');$('#previewVideo').poster=media.poster;$('#videoPoster').src=media.poster;const video=media.video||state.videoUrl;$('#previewVideo').hidden=!video;$('#videoPoster').hidden=!!video;$('#videoEmpty').hidden=!!video;if(video){$('#previewVideo').src=video;$('#previewVideo').load();}$('#videoDialog').showModal();}
function addMessage(role,content,html=false){const node=document.createElement('div');node.className='message '+role;node.innerHTML=role==='user'?`<div class="user-bubble">${esc(content)}</div>`:`<div class="assistant-label"><span class="ai-mark">✦</span>팝콘PC AI</div><div class="assistant-text">${html?content:esc(content)}</div>`;$('#messages').append(node);scrollChat();return node;}
function scrollChat(){requestAnimationFrame(()=>{$('#messages').scrollTop=$('#messages').scrollHeight;});}
function showWorkspace(){ $('#welcome').hidden=true;$('#welcomeFoot').hidden=true;$('#workspace').hidden=false; }
function setQuick(selected){$('#quickActions').innerHTML=(selected?['20만원 줄여줘','화이트로 바꿔줘','더 조용하게','메모리 32GB로']:['예산을 100만원으로','영상 편집 위주로','사무용으로 추천해줘']).map(t=>`<button data-chat="${t}">${t}</button>`).join('');}
function recommend(text,conditions){
 document.querySelectorAll('[data-select],[data-purpose],[data-action="apply"],[data-action="cancel"]').forEach(b=>b.disabled=true);
 showWorkspace();state.pending=null;state.history=[];state.selected=null;state.conditions=conditions||readConditions(text);state.quotes=makeQuotes(state.conditions);$('#workspace').classList.remove('has-quote','mobile-quote');selectTab('chat');
 addMessage('user',text);addMessage('assistant','먼저 비교해 볼 수 있는 구성 3가지를 준비했어요.\n마음에 드는 구성을 고르면, 그 PC를 기준으로 함께 조정할게요.');
 const node=document.createElement('div');node.className='message recommendation-message';node.innerHTML=recommendationMarkup();$('#messages').append(node);setQuick(false);requestAnimationFrame(()=>{const m=$('#messages');m.scrollTop=node.offsetTop-m.offsetTop-16;});
}
function selectQuote(index){const q=state.quotes[index];if(!q)return;state.selected=copy(q);state.pending=null;state.history=[];state.revision=1;$('#workspace').classList.add('has-quote');$('#messages').querySelectorAll('[data-select]').forEach(b=>b.disabled=true);addMessage('user',q.name+'으로 조정할게요.');addMessage('assistant',`좋아요. ${q.name}을 기준으로 조정할게요.\n예산을 줄이거나 색상·소음·메모리를 바꿔보세요. 변경안은 적용하기 전에 비교할 수 있어요.`);setQuick(true);renderQuote();selectTab('quote');}
function renderQuote(changed=[]){
 const q=state.selected;if(!q)return;const sum=total(q),over=sum>state.conditions.budget;
 $('#quotePane').innerHTML=`<div class="quote-top"><span class="eyebrow">내 구성 · V${state.revision}</span><button data-action="undo" ${state.history.length?'':'disabled'}>↶ 이전 구성</button></div><div class="quote-title"><div><h2>${esc(q.name)}</h2><p>대화로 함께 완성하는 나의 PC</p></div><div class="quote-total">${money(sum)}<small>원</small><span class="under ${over?'over':''}">${over?'예산 상한 초과':`예산보다 ${money(state.conditions.budget-sum)}원 여유`}</span></div></div><div class="quote-media"><img src="assets/pc-front.png" alt="실제 견적과 다른 제작 예시 PC"><div class="media-caption">당신의 PC가 완성되는 순간<small>제작 예시 이미지 · 실제 부품은 아래 견적 기준</small></div><button data-action="video" aria-label="제작 영상 미리보기">▶</button></div><div class="quote-reason"><b>✦ 이렇게 골랐어요</b><br>${esc(q.reason)}</div><div class="parts-heading"><b>구성 부품 <span>8종</span></b><span>예시 금액 · 원</span></div><table class="parts" aria-label="현재 견적 부품 목록"><tbody>${q.parts.map((p,i)=>`<tr class="${changed.includes(i)?'part-highlight':''}"><td class="category">${p.cat}</td><td class="part-name">${esc(p.name)}</td><td class="part-price">${money(p.price)}<button class="part-change" data-part="${i}" aria-label="${p.cat} 변경 요청">변경</button></td></tr>`).join('')}</tbody></table><div class="verification"><span>✓ 호환성 확인 UI</span><span>✓ 재고 확인 UI</span><span>✓ 예산 ${over?'초과':'내 구성'}</span></div><p class="quote-disclaimer">검증 상태는 목업 예시입니다. 실제 부품 적합성·가격·재고는 확인하지 않았습니다.</p><div class="quote-actions"><button class="secondary" data-action="save">견적 저장</button><button class="primary" data-action="cart" ${isInCart(q)?'disabled':''}>${isInCart(q)?'장바구니에 담김 ✓':'장바구니 담기'}</button></div>`;
}
function requestChange(text){
 if(!text.trim())return;
 if(!state.selected){recommend(text,mergeConditions(text,state.conditions));return;}
 addMessage('user',text);state.pending=null;document.querySelectorAll('[data-action="apply"]').forEach(b=>b.disabled=true);
 if(/편집.*(위주|중심)|사무용|게임.*(위주|중심)|고사양 게임|AI 작업|이미지 작업/i.test(text)){const c=mergeConditions(text,state.conditions);recommend('용도를 바꿔 새로운 구성을 비교할게요.',c);return;}
 const q=copy(state.selected);let description='',changes=[],requestedSaving=0;const lower=/줄|저렴|낮춰|절약/.test(text);
 if(lower){const match=text.match(/(\d+)\s*만/);requestedSaving=match?Number(match[1])*10000:100000;let remaining=requestedSaving;for(const i of [3,0,5]){const p=q.parts[i];const reduction=Math.min(Math.floor(p.price*.35/1000)*1000,remaining);if(reduction<=0)continue;p.price-=reduction;remaining-=reduction;p.name=i===3?'보급형 그래픽카드 · 대체 예시':i===0?'실속형 CPU · 대체 예시':'기본 메쉬 케이스';changes.push(i);}description=`예산 절감을 위해 ${changes.map(i=>q.parts[i].cat).join('·')}를 조정했어요. 게임이나 작업 성능이 낮아질 수 있어요.${remaining>0?' 요청한 절감액 전부를 반영하지는 못했어요.':''}`;}
 else if(/화이트|흰색/.test(text)){if(q.parts[5].name.includes('화이트')){addMessage('assistant','현재 구성은 이미 화이트 케이스예요. 다른 부분을 조정해볼까요?');return;}q.parts[5].name='화이트 메쉬 케이스';q.parts[5].price+=20000;changes=[5];description='케이스를 화이트로 바꿨어요. 내부 부품 색상까지 모두 흰색으로 바뀌는 것은 아니에요.';}
 else if(/조용|소음|쿨러/.test(text)){if(q.parts[6].name.includes('저소음')){addMessage('assistant','저소음 쿨러가 이미 반영되어 있어요. 실제 소음 수치는 제품 테스트가 필요해요.');return;}q.parts[6].name='저소음 타워 쿨러';q.parts[6].price+=30000;changes=[6];description='쿨러를 저소음형으로 교체하는 예시예요. 실제 소음·간섭 여부는 최종 구성에서 확인해야 해요.';}
 else if(/메모리|램|32\s*GB/i.test(text)){if(q.parts[2].name.includes('32GB')){addMessage('assistant','현재 메모리는 이미 32GB예요. 이 구성은 그대로 유지할게요.');return;}q.parts[2].name=q.parts[2].name.replace(/16GB.*$/,'32GB (16GB × 2)');q.parts[2].price+=45000;changes=[2];description='메모리를 32GB로 늘려 여러 프로그램을 함께 쓰는 구성을 제안해요.';}
 else if(/예산/.test(text)&&/\d+\s*만/.test(text)){const c={...state.conditions,budget:Number(text.match(/(\d+)\s*만/)[1])*10000,assumed:false,budgetSource:'user',budgetChange:null};if(c.budget<500000||c.budget>5000000){addMessage('assistant','목업에서는 50~500만원 범위의 예산을 지원해요. 조건 수정에서 예산을 선택해주세요.');return;}recommend('새 예산으로 구성 다시 추천',c);return;}
 else{addMessage('assistant','이 목업에서는 예산 줄이기, 화이트 케이스, 저소음 쿨러, 메모리 32GB 변경을 체험할 수 있어요.\n아래 예시 버튼을 누르거나 “20만원 줄여줘”처럼 말씀해주세요. 실제 AI 연결 후에는 더 다양한 요청을 처리할 수 있습니다.');return;}
 if(!changes.length){addMessage('assistant','현재 구성에서는 더 줄일 수 있는 예시 부품이 없어요. 예산이나 용도를 바꿔 새 구성을 받아보세요.');return;}
 const before=total(state.selected),after=total(q),over=after>state.conditions.budget;
 q.reason=description;state.pending=over?null:{quote:q,changes};
 const html=`<div>${esc(description)}</div><div class="change-card"><h4>변경 전후 비교</h4>${changes.map(i=>`<div class="change-line"><span>${q.parts[i].cat} · ${esc(state.selected.parts[i].name)}</span><b>→ ${esc(q.parts[i].name)}</b></div>`).join('')}<div class="change-total"><span>${money(before)}원 → <b>${money(after)}원</b></span><b>${after-before>0?'+':''}${money(after-before)}원</b></div><p class="change-desc">${over?'예산 상한을 초과해 적용하지 않았어요. 다른 부품을 낮추거나 예산을 수정해주세요.':'기존 구성은 아직 유지 중이에요. 아래 버튼을 누르면 변경안이 반영됩니다.'}</p><div class="change-actions"><button class="secondary" data-action="cancel">기존 구성 유지</button>${over?'<button class="primary" data-action="conditions">예산 수정</button>':'<button class="primary" data-action="apply">이 변경 적용</button>'}</div></div>`;addMessage('assistant',html,true);
}
function applyChange(){if(!state.pending)return;const {quote,changes}=state.pending;state.history.push(copy(state.selected));state.selected=quote;state.pending=null;state.revision++;document.querySelectorAll('[data-action="apply"],[data-action="cancel"]').forEach(b=>b.disabled=true);renderQuote(changes);addMessage('assistant','변경안을 반영했어요. 현재 총액은 '+money(total(quote))+'원이에요.\n견적 상단의 “이전 구성”으로 되돌릴 수 있어요.');toast('견적에 변경사항을 반영했어요.');}
function selectTab(tab){$('#workspace').classList.toggle('mobile-quote',tab==='quote');document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));}
function save(){if(!state.selected)return;const saved={...copy(state.selected),conditions:copy(state.conditions),savedAt:new Date().toISOString()};state.saved.unshift(saved);state.saved=state.saved.slice(0,10);try{localStorage.setItem('popcorn-demo-quotes',JSON.stringify(state.saved));toast('이 브라우저에 견적을 저장했어요.');}catch{toast('브라우저 저장이 제한되어 이번 화면에서만 보관해요.');}$('#savedCount').textContent=state.saved.length;}
function showSaved(){$('#savedList').innerHTML=state.saved.length?state.saved.map((q,i)=>`<div class="saved-item"><div><b>${esc(q.name)}</b><small>${money(total(q))}원 · ${new Date(q.savedAt).toLocaleDateString('ko-KR')}</small></div><button class="primary" data-load="${i}">불러오기</button></div>`).join(''):'<div class="empty-saved">아직 저장한 견적이 없어요.<br>구성을 선택한 뒤 “견적 저장”을 눌러주세요.</div>';$('#savedDialog').showModal();}
function showConditions(){if(!state.conditions)return;const f=$('#conditionsForm');f.elements.budget.value=state.conditions.budget/10000;f.elements.purpose.value=state.conditions.purpose;f.elements.monitor.checked=state.conditions.monitor;$('#conditionsDialog').showModal();}
const demoCart=[];
function isInCart(q){return demoCart.some(item=>JSON.stringify(item.parts)===JSON.stringify(q.parts));}
function addToCart(){
 if(!state.selected)return;
 if(isInCart(state.selected)){toast('이미 목업 장바구니에 담긴 구성이에요.');return;}
 demoCart.push({...copy(state.selected),conditions:copy(state.conditions),quantity:1});
 renderQuote();
 toast('목업 장바구니에 담았어요. 실제 주문은 진행되지 않습니다.');
}

function home(){$('#welcome').hidden=false;$('#welcomeFoot').hidden=false;$('#workspace').hidden=true;$('#messages').innerHTML='';state.selected=null;state.pending=null;state.conditions=null;$('#startInput').value='';window.scrollTo(0,0);$('#startInput').focus();}
document.addEventListener('click',e=>{
 const b=e.target.closest('button');if(!b)return;
 if(b.dataset.close){$('#'+b.dataset.close).close();return;}
 if(b.dataset.prompt){$('#messages').innerHTML='';recommend(b.dataset.prompt);return;}
 if(b.dataset.chat){requestChange(b.dataset.chat);return;}
 if(b.dataset.purpose){changePurpose(b.dataset.purpose,b.closest('.recommendation-message'));return;}
 if(b.dataset.buildVideo!==undefined){openVideo(state.quotes[Number(b.dataset.buildVideo)]);return;}
 if(b.dataset.select!==undefined){selectQuote(Number(b.dataset.select));return;}
 if(b.dataset.tab){selectTab(b.dataset.tab);return;}
 if(b.dataset.load!==undefined){const q=copy(state.saved[Number(b.dataset.load)]);if(!q)return;$('#savedDialog').close();showWorkspace();state.conditions=q.conditions;state.selected=q;state.history=[];state.pending=null;state.revision=1;$('#messages').innerHTML='';$('#workspace').classList.add('has-quote');addMessage('assistant','저장한 '+q.name+'을 불러왔어요. 이 구성을 기준으로 계속 조정할 수 있어요.');setQuick(true);renderQuote();selectTab('quote');return;}
 if(b.dataset.part!==undefined){selectTab('chat');const p=state.selected.parts[Number(b.dataset.part)];$('#chatInput').value=p.cat+'를 ';$('#chatInput').focus();toast('대화창에 원하는 변경 내용을 이어서 적어주세요.');return;}
 const actions={home,saved:showSaved,video:()=>openVideo(state.selected),conditions:showConditions,apply:applyChange,save,cart:addToCart,cancel:()=>{state.pending=null;document.querySelectorAll('[data-action="apply"],[data-action="cancel"]').forEach(x=>x.disabled=true);addMessage('assistant','변경안을 적용하지 않고 기존 구성을 유지할게요.');},undo:()=>{if(!state.history.length)return;state.selected=state.history.pop();state.pending=null;state.revision++;renderQuote();addMessage('assistant','이전 구성으로 되돌렸어요. 총액은 '+money(total(state.selected))+'원이에요.');}};
 actions[b.dataset.action]?.();
});
function init(){
 if(!$('#startForm')||!$('#videoFile')||!$('#toast')){setTimeout(init,120);return;}
 if(init.done)return;init.done=true;
 $('#startForm').addEventListener('submit',e=>{e.preventDefault();const text=$('#startInput').value.trim();if(text){$('#messages').innerHTML='';recommend(text);}});
$('#chatForm').addEventListener('submit',e=>{e.preventDefault();const text=$('#chatInput').value.trim();$('#chatInput').value='';requestChange(text);});
document.querySelectorAll('textarea').forEach(t=>t.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();t.form.requestSubmit();}}));
$('#conditionsForm').elements.purpose.addEventListener('change',e=>{$('#conditionsForm').elements.budget.value=purposeBudgets[e.target.value]/10000;});
$('#conditionsForm').addEventListener('submit',e=>{e.preventDefault();const f=e.currentTarget;const key=f.elements.purpose.value;const changed=key!==state.conditions.purpose;const c={...state.conditions,budget:Number(f.elements.budget.value)*10000,purpose:key,monitor:f.elements.monitor.checked,assumed:false,budgetSource:changed&&Number(f.elements.budget.value)*10000===purposeBudgets[key]?'purpose':'user',budgetChange:changed?{from:state.conditions.budget,to:Number(f.elements.budget.value)*10000}:null};$('#conditionsDialog').close();recommend('조건을 수정했어요. '+money(c.budget/10000)+'만원 이하, '+purposes[c.purpose]+' 용도로 다시 추천해주세요.',c);});
$('#videoFile').addEventListener('change',e=>{const f=e.target.files[0];if(!f)return;if(!f.type.startsWith('video/')){toast('동영상 파일을 선택해주세요.');return;}if(state.videoUrl)URL.revokeObjectURL(state.videoUrl);state.videoUrl=URL.createObjectURL(f);$('#previewVideo').src=state.videoUrl;$('#previewVideo').hidden=false;$('#videoPoster').hidden=true;$('#videoEmpty').hidden=true;$('#previewVideo').play().catch(()=>toast('재생 버튼을 눌러 영상을 확인해주세요.'));});
$('#previewVideo').addEventListener('error',()=>{toast('이 브라우저에서 재생 가능한 MP4 또는 WebM 영상을 선택해주세요.');$('#previewVideo').hidden=true;$('#videoPoster').hidden=false;$('#videoEmpty').hidden=false;});
$('#videoDialog').addEventListener('close',()=>$('#previewVideo').pause());
document.querySelectorAll('dialog').forEach(d=>d.addEventListener('click',e=>{if(e.target===d){const r=d.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)d.close();}}));
$('#savedCount').textContent=state.saved.length;
$('#startInput').placeholder='150만원으로 게임도 하고 영상 편집도 하는\n조용한 PC를 찾고 있어요.';

}
window.PopcornApp={init};
// Optional page tools share exactly the same mock state as the visible controls.
if(document.modelContext?.registerTool){
 const lifecycle=new AbortController();
 const toolSpecs=[
  {name:'start_pc_recommendation',description:'Start a mock PC recommendation from a Korean request. Uses example data, not live AI or inventory.',inputSchema:{type:'object',properties:{request:{type:'string',minLength:1,maxLength:500}},required:['request'],additionalProperties:false},execute(input){if(typeof input?.request!=='string'||!input.request.trim()||input.request.length>500)throw new Error('A request of 1–500 characters is required.');recommend(input.request);return {mock:true,builds:state.quotes.map(q=>({index:q.id,name:q.name,total:total(q)}))};}},
  {name:'select_pc_build',description:'Select one of the current mock recommendation cards and open its editable quote.',inputSchema:{type:'object',properties:{index:{type:'integer',minimum:0,maximum:2}},required:['index'],additionalProperties:false},execute(input){if(!Number.isInteger(input?.index)||!state.quotes[input.index])throw new Error('Choose an available build index from 0 to 2.');selectQuote(input.index);return {mock:true,name:state.selected.name,total:total(state.selected)};}},
  {name:'read_pc_quote',description:'Read the currently selected example quote and any staged change without modifying it.',annotations:{readOnlyHint:true},inputSchema:{type:'object',properties:{},additionalProperties:false},execute(){return {mock:true,conditions:copy(state.conditions),quote:copy(state.selected),pending:copy(state.pending)};}}
 ];
 for(const spec of toolSpecs){try{Promise.resolve(document.modelContext.registerTool({...spec,annotations:{readOnlyHint:false,...spec.annotations}},{signal:lifecycle.signal})).catch(()=>{});}catch{}}
 window.addEventListener('pagehide',()=>lifecycle.abort(),{once:true});
}

})();}
