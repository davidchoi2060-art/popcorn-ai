// 2차 대화 중심 상담 화면(코덱스 1816 보강3 상세기획). 대화가 주 화면이고, 고객이 고른 구성은 옆 칸
// 「지금 견적」에 남는다. 상담·추천·보관·문의는 1차와 같은 흐름(live-flow.js)과 같은 서버 응답만 쓴다.
// 1차 화면과 같은 탭 보관(대화·조건·지금 견적 상품 번호)을 함께 써서, 두 화면을 오가도 대화가 이어진다.
(function(){'use strict';
const M=window.MVP3LiveModel,A=window.MVP3Api,{customerPhoto}=window.MVP3LivePhoto,LF=window.MVP3LiveFlow;
const $=s=>document.querySelector(s);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=v=>Number.isInteger(v)?v.toLocaleString('ko-KR')+'원':'금액 미확인';
const button=(label,action,cls='',data='')=>'<button type="button" class="'+cls+'" data-action="'+action+'" '+data+'>'+label+'</button>';
const MAX_TEXT=20000;
const log=$('#tk-log'),panel=$('#tk-now-body'),input=$('#tk-input'),status=$('#tk-status');
const flow=LF.createFlow(A,{onChange:render,keepCurrent:true}),state=flow.state,keepUi=LF.createKeepUi(flow,document);
// 새로고침 전에 보던 구성을 다시 연 경우. 그 전에 보관했는지는 이 탭이 모르므로 「아직 저장하지 않았어요」라고 단정하지 않는다.
let resumed=false;
// 첫 화면 시작 단추(코덱스 1816 보강6 의견 v1 §2 — 입구는 하나, 안에 시작 단추 셋). 문구는 여기 한곳에서 바꾼다.
// 누르면 입력창에 초안만 넣고 보내지 않는다(고객이 고쳐 보낸다). 이미 적던 말은 지우지 않고 뒤에 붙인다.
// key 는 그 초안으로 시작한 첫 메시지에 실려 서버 로그로만 센다 -- api/talk.py ENTRY_KEYS 와 같아야 한다.
const STARTERS=[
  {key:'new_pc',label:'새 PC 찾기',draft:'새 PC를 찾고 있어요.'},
  {key:'upgrade',label:'쓰던 PC 업그레이드',draft:'지금 쓰는 PC에서 불편한 점을 상담하고 싶어요.'},
  {key:'parts',label:'부품·구성 물어보기',draft:'PC 부품이나 구성에서 궁금한 점이 있어요.'}];
let entry=null;
// 처음 화면의 세 갈래에서 들어오면(talk.html?start=키) 그 갈래 초안을 입력창에 넣어 둔다(보내지 않는다).
// 처음 화면에서 갈래를 고르면 새 상담으로 시작한다(2026-10-12 중헌 님 -- 전에는 하던 대화에 이어 붙였다, 보강6 의견 §1).
// 주소에서 지워 새로고침 때 다시 넣지 않게 한다.
// 처음 화면 채팅창에 쓴 글이 있으면 꺼내 바로 보낸다(고객이 이미 「보내기」를 눌렀다). 갈래는 서버가 글
// 내용으로 고른다. 오래된 글(10분 넘음)은 버린다 -- 다른 날 연 탭에서 갑자기 보내지 않게.
const FIRST_KEY='popcorn-mvp3-first-message-v1';
function takeFirstMessage(){
  let raw=null;try{raw=sessionStorage.getItem(FIRST_KEY);sessionStorage.removeItem(FIRST_KEY);}catch{return '';}
  try{const m=JSON.parse(raw||'null');return m&&typeof m.text==='string'&&Date.now()-m.at<600000?m.text.trim().slice(0,MAX_TEXT):'';}catch{return '';}
}
// 처음 화면에서 새 상담을 시작하고 들어왔는가(채팅창에 쓴 글이 아직 남아 있거나 주소에 갈래 키가 있다). 읽기만 한다 --
// 꺼내 쓰는 일은 startFromGateway 가 한다.
function gatewayStarted(){
  try{const m=JSON.parse(sessionStorage.getItem(FIRST_KEY)||'null');if(m&&typeof m.text==='string'&&m.text.trim()&&Date.now()-m.at<600000)return true;}catch{}
  try{const key=new URLSearchParams(location.search).get('start');return STARTERS.some(x=>x.key===key);}catch{return false;}
}
async function startFromGateway(){
  const first=takeFirstMessage();
  if(first){
    if(state.phase){input.value=first;count();status.textContent='보던 견적을 불러오는 중이에요. 다 불러온 뒤 「보내기」를 눌러 주세요.';status.hidden=false;return;}
    const sent=await flow.submit(first);if(!sent&&!input.value){input.value=first;count();}
    return;
  }
  let key=null;try{key=new URLSearchParams(location.search).get('start');}catch{}
  if(!key)return;
  try{history.replaceState(history.state,'',location.pathname+location.hash);}catch{}
  const t=STARTERS.find(x=>x.key===key);
  if(!t||input.value.trim())return;
  input.value=t.draft;entry=t.key;count();input.focus();
}

// 여러 대(wants.units -- 서버가 고객 문장에서 읽은 대수)면 한 대 예산으로 견준다(M.budgetGapText · 코덱스 C10-F01).
function budgetGap(product,talk,wants){
  const won=talk?.budget_won;
  if(!Number.isInteger(product?.price)||!Number.isInteger(won))return '';
  if(talk.budget_bound==='이상')return '최소 예산 '+money(won)+' 조건';
  return M.budgetGapText(product.price,talk,wants,money);
}
function photo(product){
  const p=customerPhoto(product.photo,product.product_code);
  if(p.state!=='available')return '';
  return '<figure class="tk-photo"><img src="'+esc(p.url+'?size=card')+'" alt="'+esc(product.name)+' · AI 조립 예시" loading="lazy" decoding="async"><figcaption>'+esc(p.notice)+'</figcaption></figure>';
}
function specList(spec,build){
  const rows=M.changedSpecRows(M.cardSpecRows(spec),build);
  return rows.length?'<dl class="tk-spec">'+rows.map(([k,v])=>'<div><dt>'+esc(k)+'</dt><dd>'+esc(v)+'</dd></div>').join('')+'</dl>':'';
}
function conditionsText(talk){const c=M.conditions(talk);return c.length?c.join(' · '):'';}

// 말풍선 아래 추천 카드. 가장 최근 제안만 고를 수 있고, 지난 제안은 그때 값 그대로 「이전 제안」으로 둔다.
function proposalBlock(p,latest){
  const products=p.groups.flatMap(g=>g.products);
  // 예산이 너무 낮아 카드를 안 낸 경우(「10만원」) 서버가 준 「○○원부터 가능합니다」를 그대로 보인다.
  const notes=[...new Set(p.groups.map(g=>g.empty_note).filter(Boolean))];
  const head=latest?'':'<p class="tk-cards-note">이전 제안 · 그때 조건('+esc(conditionsText(p.talk)||'조건 미확인')+') 기준 금액이에요.</p>';
  // 지난 제안은 비어 있어도 「이전 제안」 머리와 is-past 를 단다 -- 지난 「못 찾았어요」가 지금 답처럼 보였다(2026-10-12 검수 9da2 P2-2).
  if(!products.length)return '<div class="tk-cards is-empty'+(latest?'':' is-past')+'" data-proposal="'+p.id+'">'+head+
    (notes.length?notes.map(n=>'<p class="warn-text tk-group-note">'+esc(n)+'</p>').join(''):'<p>현재 조건에서 보여드릴 구성을 찾지 못했어요. 조건을 조금 바꾸거나 전문가에게 문의할 수 있어요.</p>')+
    (latest?nextChoices(false)+button('전문가에게 문의하기','inquiry-open','outline','data-human="1"'):'')+'</div>';
  const many=p.groups.filter(g=>g.products.length).length>1;
  return '<div class="tk-cards'+(latest?'':' is-past')+'" data-proposal="'+p.id+'">'+head+p.groups.filter(g=>g.products.length).map(g=>
    (many&&g.usage?'<h3 class="tk-group">'+esc(g.usage)+'</h3>':'')+
    // 예산 안에 판매 구성이 없을 때 서버가 준 사유(「이 작업은 595,700원부터 가능합니다」)를 카드 위에 둔다 --
    // 예산을 넘는 카드만 말없이 나오면 설명과 어긋나 보인다(2026-10-11 일반 AI 비교 R03).
    (g.empty_note?'<p class="warn-text tk-group-note">'+esc(g.empty_note)+'</p>':'')+'<ul class="tk-card-list">'+g.products.map(x=>card(x,p,latest)).join('')+'</ul>').join('')+
    (latest?nextChoices(true):'')+'</div>';
}
// 카드 바로 아래 「다음 선택」 단추(2026-10-12 사장님 결정 · 카드 검수 C2 「아래에서 골라 주세요」인데 단추가 없음).
// 더 싼 PC · 더 높은 사양은 되묻지 않고 같은 조건으로 바로 다음 카드를 부른다(서버 choices · 옛 화면 app.js 와 같은 호출).
// 서버가 그 방향에 판매 PC가 없다고 한 단추(enabled=false)는 내지 않는다 -- 눌러도 같은 목록이다.
// 조건 바꾸기만 예산·용도 칸을 연다. 카드가 없을 때는 조건 바꾸기만 둔다.
const CHOICE_TEXT={cheaper:'더 싼 PC',better:'더 높은 사양',change:'조건 바꾸기'};
let condOpen=false;
function nextChoices(withCards){
  const dis=state.phase?' disabled':'';
  const list=withCards?(state.choices||[]).filter(c=>c.enabled):[];
  let html=list.filter(c=>c.id!=='change').map(c=>button(CHOICE_TEXT[c.id],'explore','outline','data-dir="'+c.id+'" data-label="'+esc(c.label)+'"'+dis)).join('');
  html+=button(CHOICE_TEXT.change,'cond-open','outline','aria-expanded="'+condOpen+'"'+dis);
  return '<div class="tk-next" role="group" aria-label="다음 선택">'+html+'</div>'+(condOpen?conditionForm():'');
}
// 예산·용도 칸. 지금 조건을 미리 채우고, 바꾼 것만 한 문장으로 상담에 보낸다(서버가 같은 규칙으로 다시 찾는다).
function conditionForm(){
  const t=state.talk||{},won=Number.isInteger(t.budget_won)?Math.round(t.budget_won/10000):'';
  const usage=Array.isArray(t.usages)?t.usages.filter(x=>typeof x==='string').join(', '):'';
  const dis=state.phase?' disabled':'';
  return '<form class="tk-cond-form" data-cond-form aria-label="조건 바꾸기">'+
    '<label class="tk-field"><span>예산 (만원)</span><input data-cond="budget" type="number" inputmode="numeric" min="10" max="5000" step="1" value="'+esc(won)+'"'+dis+'></label>'+
    '<label class="tk-field"><span>용도</span><input data-cond="usage" maxlength="60" placeholder="예: 게임, 4K 영상 편집, 사무용" value="'+esc(usage)+'"'+dis+'></label>'+
    '<div class="tk-row">'+button('닫기','cond-close','outline',dis.trim())+'<button type="submit" class="primary"'+dis+'>이 조건으로 다시 찾기</button></div></form>';
}
function conditionSentence(form){
  const t=state.talk||{},parts=[];
  const won=Number(form.querySelector('[data-cond=budget]').value),usage=form.querySelector('[data-cond=usage]').value.trim();
  const before=Number.isInteger(t.budget_won)?Math.round(t.budget_won/10000):null;
  if(Number.isFinite(won)&&won>0&&won!==before)parts.push('예산은 '+Math.round(won)+'만원으로');
  const was=Array.isArray(t.usages)?t.usages.join(', '):'';
  if(usage&&usage!==was)parts.push('용도는 '+usage+'(으)로');
  return parts.length?parts.join(', ')+' 바꿀게요.':'';
}
// 이 PC로 할 수 있는 작업 수준(서버 reasons[0] = 「용도 수준 — 작업」, api/sold_reco._item)을 카드 맨 위에 크게 둔다.
// 예: 「영상편집 쾌적」 / 「4K 편집」. 전에는 사양표 아래 작은 줄이라 한눈에 안 보였다(2026-10-12 사장님 결정 「크게」).
function fitLine(x){
  const r=Array.isArray(x.reasons)&&typeof x.reasons[0]==='string'?x.reasons[0].trim():'';
  if(!r)return '';
  const i=r.indexOf(' — '),head=i>0?r.slice(0,i).trim():r,work=i>0?r.slice(i+3).trim():'';
  return '<p class="tk-fit"><strong>'+esc(head)+'</strong>'+(work?'<span>'+esc(work)+'</span>':'')+'</p>';
}
// 카드에는 상품명을 두지 않는다(2026-10-12 중헌 님 고객단 4번: 「오피스 초슬림/미니타워[12100/8G/256GB/UHD 730]」이
// 아래 사양 줄과 겹쳤다). 이름은 사진 설명(alt)과 「지금 견적」·상세에 남는다. 사양 줄에 케이스·파워가 더해졌다.
function card(x,p,latest){
  const chosen=state.selected?.product_code===x.product_code;
  const gap=budgetGap(x,p.talk,p.wants);
  return '<li class="tk-card'+(chosen?' is-chosen':'')+'"><span class="pill">'+esc(x.tag||x.level||'판매 중 PC')+'</span>'+fitLine(x)+photo(x)+
    '<p class="tk-price"><strong>'+money(x.price)+'</strong> <span class="muted">'+esc(x.price_src||'가격 기준 미확인')+'</span></p>'+
    (gap?'<p class="'+(M.overUnitBudget(x.price,p.talk,p.wants)?'warn-text':'muted')+'">'+esc(gap)+'</p>':'')+specList(x.spec)+
    (latest?'<div class="tk-card-actions">'+button('상세 보기','detail','outline','data-index="'+x.index+'"')+
      (chosen?'<span class="tk-chosen">지금 견적으로 고른 구성</span>':button('이 구성 선택','choose','primary','data-index="'+x.index+'"'))+'</div>':'')+'</li>';
}

function renderLog(){
  // 넓은 화면은 대화 칸이, 좁은 화면은 페이지가 스크롤한다. 읽던 위치를 빼앗지 않도록 맨 아래에 있었을 때만 따라 내려간다.
  const pageScroll=getComputedStyle(log).overflowY==='visible',doc=document.documentElement;
  const atBottom=pageScroll?innerHeight+scrollY>=doc.scrollHeight-48:log.scrollHeight-log.scrollTop-log.clientHeight<48;
  const msgs=state.messages,talked=msgs.some(m=>m.who==='user');
  const props=state.proposals||[],last=props[props.length-1];
  const after=new Map();for(const p of props){const k=Math.max(0,p.at-1);after.set(k,[...(after.get(k)||[]),p]);}
  let html=talked?'':'<section class="tk-welcome"><h1 tabindex="-1">어떤 PC가 필요하세요?</h1><p>PC로 할 일이나 바꾸고 싶은 점을 편하게 말씀해 주세요. 필요한 조건은 대화하면서 함께 정리할게요.</p></section>';
  // 첫 화면에서는 입력창을 제목 바로 아래로 올리고 시작 단추를 그 아래에 둔다(보강6 의견 §2 배치). 대화가 시작되면 걷는다.
  $('.tk-chat').classList.toggle('is-fresh',!talked);
  const starters=$('#tk-starters');starters.hidden=talked;
  starters.innerHTML=talked?'':STARTERS.map(t=>button(esc(t.label),'starter','outline','data-entry="'+esc(t.key)+'"')).join('');
  msgs.forEach((m,i)=>{
    if(!(m.who==='ai'&&m.text===LF.GREETING))html+='<div class="tk-msg is-'+(m.who==='user'?'user':'ai')+'"><p>'+esc(m.text)+'</p></div>';
    for(const p of after.get(i)||[])html+=proposalBlock(p,p===last&&state.recommendation!==null);
  });
  if(state.freeBuildOffer)html+='<div class="tk-msg-actions">'+button('이 조건으로 부품 고르기','free-build-open','outline',state.phase?'disabled':'')+'</div>';
  if(state.handoffOffer&&!state.inquiry.open&&!state.inquiry.done)html+='<div class="tk-msg-actions">'+button('전문가에게 문의하기','inquiry-open','outline','data-human="1"')+'</div>';
  if(state.error){
    const kind=state.retry?.kind,recommend=kind==='recommend'||kind==='resume',reprice=kind==='reprice';
    const wait=Math.max(0,Math.ceil(((state.error.retryAt||0)-Date.now())/1000));
    const head=reprice?(state.error.status===409?'저장하는 사이 금액이 바뀌어 저장하지 못했어요. 지금 견적은 그대로 두었어요. 지금 금액을 다시 확인한 뒤 저장할 수 있어요.':'지금 금액을 다시 확인하지 못했어요. 지금 견적은 그대로 두었어요.')
      :recommend?'새 추천을 불러오지 못했어요.'+(state.selected?' 앞서 고른 견적은 유지할게요.':''):'이번 답변을 불러오지 못했어요. 다시 시도하거나 전문가에게 문의할 수 있어요.';
    const again=reprice&&state.error.status===409?'지금 금액 다시 확인':'다시 시도';
    html+='<div class="tk-msg is-ai is-error" role="alert"><p>'+head+'</p>'+
      '<p class="muted">'+esc(state.error.message)+'</p><div class="tk-msg-actions">'+
      (state.retry?button(wait?wait+'초 뒤 다시 시도':again,'retry','outline',wait||state.phase?'disabled':''):'')+
      button('전문가에게 문의하기','inquiry-open','outline','data-human="1"')+'</div></div>';
  }
  log.innerHTML=html;
  if(atBottom||state.phase==='talk'){if(pageScroll)scrollTo(0,doc.scrollHeight);else log.scrollTop=log.scrollHeight;}
}

function inquiryForm(){
  const q=state.inquiry;if(!q.open&&!q.done)return '';
  const human=!!q.human,title=human?'전문가에게 문의하기':'구매 조건 문의';
  if(q.done)return '<section class="tk-inquiry" role="status" tabindex="-1"><h3>'+title+'</h3><p>'+esc(q.done.note)+'</p><p class="muted">신청 번호 '+esc(q.done.inquiry_no)+' · 주문과 결제는 진행되지 않았어요.</p></section>';
  const busy=state.phase==='inquiry'||state.phase==='inquiry-form',d=q.draft,dis=busy?' disabled':'';
  const err=q.error?'<p class="warn-text" role="alert">'+esc(q.error)+'</p>':'';
  const intro=human?'연락처와 궁금한 내용을 남겨주세요. 이 신청으로 주문이나 결제가 진행되지는 않아요.':'여러 대 구매·할인·세금계산서 등 확인할 내용을 남겨주세요. 이 신청으로 주문이나 결제가 진행되지는 않아요.';
  if(!q.meta)return '<section class="tk-inquiry" tabindex="-1"><h3>'+title+'</h3>'+(busy?'<p class="muted">문의 신청 양식을 불러오는 중이에요.</p>':err+button('다시 불러오기','inquiry-open','outline',human?'data-human="1"':''))+'</section>';
  const field=(label,el)=>'<label class="tk-field"><span>'+label+'</span>'+el+'</label>';
  return '<section class="tk-inquiry" tabindex="-1"><h3>'+title+'</h3><p class="muted">'+intro+'</p>'+
    field('문의 주제','<select data-inquiry="topic"'+dis+'><option value="">주제를 골라 주세요</option>'+q.meta.topics.map(t=>'<option'+(d.topic===t?' selected':'')+'>'+esc(t)+'</option>').join('')+'</select>')+
    field('이름 (선택)','<input data-inquiry="name" maxlength="30" autocomplete="name" value="'+esc(d.name)+'"'+dis+'>')+
    field('전화번호','<input data-inquiry="phone" type="tel" maxlength="20" autocomplete="tel" placeholder="010-1234-5678" value="'+esc(d.phone)+'"'+dis+'>')+
    field('이메일','<input data-inquiry="email" type="email" maxlength="120" autocomplete="email" value="'+esc(d.email)+'"'+dis+'>')+
    '<p class="muted">전화번호나 이메일 중 하나는 적어 주세요.</p>'+
    field('문의 내용 (선택)','<textarea data-inquiry="message" maxlength="500" rows="3"'+dis+'>'+esc(d.message)+'</textarea>')+
    '<label class="tk-consent"><input type="checkbox" data-inquiry="consent"'+(d.consent?' checked':'')+dis+'><span>'+esc(q.meta.consent_text)+' 동의합니다.</span></label>'+
    err+'<div class="tk-row">'+button('닫기','inquiry-close','outline',busy?'disabled':'')+button(state.phase==='inquiry'?'보내는 중…':'신청 보내기','inquiry-send','primary',busy?'disabled':'')+'</div></section>';
}
function inquiryValues(){const out={};for(const e of panel.querySelectorAll('[data-inquiry]'))out[e.dataset.inquiry]=e.type==='checkbox'?e.checked:e.value;return out;}

// 옆 칸 「지금 견적」: 가장 최근 AI 제안이 아니라 고객이 고른 구성이다.
function renderPanel(){
  const p=state.selected,q=state.inquiry,busy=!!state.phase;
  const summary=$('#tk-now-summary');
  summary.textContent=p?'지금 견적 · '+p.name+' · '+money(p.price):'지금 견적 · 아직 고른 구성이 없어요';
  let html='<h2>지금 견적</h2>';
  const now=conditionsText(state.talk);
  if(!p){
    html+='<p class="muted">'+(state.restoredCurrent&&state.phase==='recommend'?'보던 구성을 지금 금액으로 다시 확인하고 있어요.':'구성을 선택하면 여기에 모아둘게요.')+'</p>'+(now?'<p class="tk-cond">지금 조건 · '+esc(now)+'</p>':'');
  }else{
    const basis=conditionsText(state.selectionState),changed=JSON.stringify(state.selectionState)!==JSON.stringify(state.talk);
    const saved=state.saveState==='saved'&&state.savedQuote;
    html+='<p class="tk-now-label">지금 선택한 구성</p><h3>'+esc(p.name)+'</h3>'+(M.changedPartsNote(p.build)?'<p class="muted" data-changed-parts>'+esc(M.changedPartsNote(p.build))+'</p>':'')+photo(p)+
      (basis?'<p class="tk-cond">고를 때 조건 · '+esc(basis)+'</p>':'')+
      (changed&&now?'<p class="tk-cond is-new">지금 조건 · '+esc(now)+'</p>':'')+
      (changed&&state.phase==='recommend'?'<p class="tk-note" role="status">새 조건으로 다시 살펴보는 중이에요. 지금 견적은 그대로 남겨둘게요.</p>':'')+
      '<p class="tk-price"><strong>'+money(p.price)+'</strong> <span class="muted">'+esc(p.price_src||'가격 기준 미확인')+'</span></p>'+
      // 같은 구성 여러 대(상세 화면에서 고른 대수). 금액은 한 대 값이고 합계는 그 값 × 대수다(2026-10-12 중헌 님 7번).
      (p.sets>1&&Number.isInteger(p.price)?'<p class="tk-sets"><strong>같은 구성 '+p.sets+'대 · 합계 '+money(p.price*p.sets)+'</strong></p>':'')+
      (budgetGap(p,state.talk,state.wants)?'<p class="muted">'+esc(budgetGap(p,state.talk,state.wants))+(changed?' (지금 조건 기준)':'')+'</p>':'')+
      specList(p.spec,p.build)+
      (p.build?.changes?.length?'<p class="muted">바꾼 부품 '+p.build.changes.length+'개를 반영한 금액이에요.</p>':'')+
      '<p class="muted">재고·판매 조건은 저장하거나 구매할 때 다시 확인해요.</p>'+
      '<p class="tk-save-state">'+(saved?'견적을 저장했어요.':state.needsRefresh?'금액이 바뀌어 저장하지 못했어요. 지금 금액을 다시 확인한 뒤 저장할 수 있어요.':state.saveState==='uncertain'?'저장 결과를 확인하지 못했어요. 내 견적에서 확인해 주세요.':resumed?'새로고침 전 저장 여부는 내 견적에서 확인할 수 있어요.':'아직 저장하지 않았어요.')+'</p>'+
      // 「구성 자세히 보기」와 「부품 바꾸기」는 같은 상세 화면을 열어 하나로 합쳤다(2026-10-12 중헌 님 고객단 5번).
      '<div class="tk-row">'+button('부품 전체 구성 확인 및 변경','open-detail','outline',(busy?'disabled ':'')+'data-focus="parts"')+
      (state.needsRefresh&&!saved?button(state.phase==='reprice'?'금액 확인 중…':'지금 금액 다시 확인','reprice','primary',busy?'disabled':''):
        button(saved?'저장 완료':state.phase==='save'?'저장하는 중…':'견적 저장','save','primary',busy||saved||state.needsRefresh||!!state.pendingSave||!!state.pendingProblem||!Number.isInteger(p.price)?'disabled':''))+'</div>';
    if(saved){
      const h=state.handoff?.quote_id===state.savedQuote.id?state.handoff:null;
      html+=keepUi.panelHtml();
      html+='<div class="tk-buy">'+(h?'<a class="primary tk-link" href="'+esc(h.mall_url)+'" target="_blank" rel="noopener noreferrer">쇼핑몰에서 구매 이어가기</a>'+
        // 쇼핑몰 상품 페이지는 기본 구성이다 -- 바꾼 부품은 연결 번호로만 전해진다(옛 화면 app.js 와 같은 안내).
        (h.changes?'<p class="warn-text">쇼핑몰 상품 페이지는 기본 구성 기준이에요. 바꾼 부품 '+esc(h.changes)+'개는 연결 번호 '+esc(h.handoff_no)+'로 기록해 두었어요. 주문할 때 요청사항에 이 번호를 적어 주세요.</p>':'')+
        (h.sets>1?'<p class="warn-text">쇼핑몰에서 수량을 '+h.sets+'대로 골라 주세요.</p>':'')+
        '<p class="muted">연결 번호 '+esc(h.handoff_no)+' · 결제·배송·보증은 쇼핑몰에서 안내해요.</p>'
        :button(state.phase==='handoff'?'쇼핑몰 가격 확인 중…':'쇼핑몰에서 구매 이어가기','handoff','outline',busy?'disabled':'')+
          // 실패하면 단추 바로 아래에 말한다(2026-10-12 끝까지 검수 O4). 같은 단추를 다시 누르면 다시 시도한다.
          (state.error&&state.retry?.kind==='handoff'?'<p class="warn-text" role="alert">쇼핑몰 연결을 준비하지 못했어요. '+esc(state.error.message)+' 잠시 뒤 다시 눌러 주세요.</p>':'')+
          '<p class="muted">결제는 이 화면이 아니라 팝콘PC 쇼핑몰에서 진행돼요. 누르면 쇼핑몰 상품 페이지가 새 창으로 열려요.</p>')+'</div>';
    }
  }
  if(!q.open&&!q.done)html+='<div class="tk-ask">'+button('전문가에게 문의하기','inquiry-open','outline',(busy?'disabled ':'')+'data-human="1"')+(p?button('구매 조건 문의','inquiry-open','outline',busy?'disabled':''):'')+'</div>'+
    // 구매 확정은 끝이 아니다 -- 확정 뒤에도 상담사가 전화로 구성을 다시 살펴본다(2026-10-11 사장님).
    '<p class="muted tk-phone">구매를 확정한 뒤에도 상담사가 전화로 구성을 함께 살펴봐요.</p>';
  panel.innerHTML=html+inquiryForm();
}

// 대화·견적 칸을 그리다 예외가 나도 아래 상태 줄과 보내기 단추 상태는 반드시 갱신한다. 예전에는 그리기가 중간에 죽으면
// state.phase 가 남은 채 단추는 켜져 있어, 보내기를 눌러도 아무 표시 없이 무시됐다(2026-10-15 코덱스 오픈테스트
// C01-F02 · C06-F03 · C07-F02 · C08-F02 「보내기 1회 뒤 60초 넘게 반응 없음」).
let renderFailed=false;
function render(){
  try{renderLog();renderPanel();renderFailed=false;}
  catch(error){renderFailed=true;console.error('[mvp3 talk] render failed',error);}
  // 지금 상담 갈래(서버가 글 내용이나 고른 단추로 정한 것)를 상단에 보여 준다.
  const g=STARTERS.find(x=>x.key===state.chatFlow?.entry);$('.demo-label').textContent=g?'PC 상담 · '+g.label:'PC 상담';
  const busy=busyText()||(renderFailed?'화면을 다 그리지 못했어요. 「새 상담」을 누르거나 새로고침해 주세요.':'');
  status.textContent=busy;status.hidden=!busy;
  $('#tk-send').disabled=!!state.phase;
  $('#tk-old').href='index.html#'+oldScreen();
  keepUi.sync();
}

// 기존 상담 화면(index.html)으로 넘어간다. 대화·조건·지금 견적은 같은 탭 보관(CONVERSATION_KEY)으로 넘어가고,
// 주소에는 화면 이름만 싣는다(고객 글·조건은 싣지 않는다). FROM_TALK_KEY 는 「대화로 돌아가기」와
// 「부품 바꾸기」 칸 바로 열기에만 쓰는 한 번짜리 표시다 -- app.js 가 읽고 지운다.
const FROM_TALK_KEY='popcorn-mvp3-from-talk-v1';
function markFromTalk(focus){try{sessionStorage.setItem(FROM_TALK_KEY,JSON.stringify({focus:focus||null}));}catch{}}
// 고른 구성이 있으면 상세, 조건이나 추천이 있으면 추천 목록, 없으면 상담 첫 화면.
function oldScreen(){return state.selected||state.restoredCurrent?'detail':state.recommendation||state.talk?'results':'welcome';}
function goDetail(focus){markFromTalk(focus);location.href='index.html#detail';}
// 좁은 화면에서 접힌 「지금 견적」을 펼친다(문의 양식이 그 안에 있다 -- 코덱스 PR142·143 검수 4).
function expandNow(){const now=$('#tk-now');if(now.classList.contains('is-open'))return;now.classList.add('is-open');$('[data-action="toggle-now"]').setAttribute('aria-expanded','true');}
// 문의 양식이 그려진 뒤 첫 입력 칸(없으면 양식 자체)으로 초점을 옮긴다.
function focusInquiry(){const box=panel.querySelector('.tk-inquiry');if(!box)return;const f=box.querySelector('[data-inquiry]:not([disabled])')||box;f.focus({preventScroll:true});box.scrollIntoView?.({block:'nearest'});}
// 진행 중인 요청마다 고객이 읽을 문장. 목록에 없는 단계도 빈칸으로 두지 않는다(빈칸이면 보내기가 왜 안 되는지 알 수 없다).
function busyText(){
  if(!state.phase)return '';
  return {talk:'답변을 준비하고 있어요.',recommend:'구성을 찾고 있어요.',save:'견적을 저장하고 있어요.',reprice:'지금 금액을 다시 확인하고 있어요.',handoff:'쇼핑몰 가격을 확인하고 있어요.'}[state.phase]||'이전 요청을 처리하고 있어요.';
}
// 앞 요청이 끝나지 않아 보내지 못하면 말없이 무시하지 않고, 쓴 글은 입력 칸에 둔 채 이유를 알린다.
function busyNotice(){status.textContent=busyText()+' 끝나면 다시 보내 주세요. 쓴 글은 입력 칸에 그대로 있어요.';status.hidden=false;}
async function send(){
  const text=input.value;
  if(!text.trim()){status.textContent='궁금한 내용이나 원하는 조건을 적어주세요.';status.hidden=false;input.focus();return;}
  if(text.trim().length>MAX_TEXT){status.textContent='한 번에 20,000자까지 보낼 수 있어요. 나눠서 보내 주세요.';status.hidden=false;return;}
  if(state.phase){busyNotice();return;}
  input.value='';count();
  const from=entry;entry=null;
  const sent=await flow.submit(text,{entry:from});
  if(!sent){if(!input.value){input.value=text;count();}if(state.phase)busyNotice();}
}
function count(){const n=input.value.length;$('#tk-count').textContent=n>1000?n.toLocaleString('ko-KR')+' / 20,000자':'';}

document.addEventListener('click',e=>{
  const b=e.target.closest('[data-action]');if(!b||b.disabled)return;
  if(keepUi.handle(b.dataset.action,b))return;
  switch(b.dataset.action){
    case 'free-build-open':if(!state.phase&&state.freeBuildOffer&&!window.MVP3FreeBuildEntry?.open(state.freeBuildOffer)){status.textContent='조건을 다음 화면으로 옮기지 못했어요. 부품 직접 고르기 화면에서 다시 적어 주세요.';status.hidden=false;}break;
    case 'starter':{
      const t=STARTERS.find(x=>x.key===b.dataset.entry);if(!t)break;
      const now=input.value.trim();
      input.value=!now||STARTERS.some(x=>x.draft===now)?t.draft:now+' '+t.draft;
      entry=t.key;count();input.focus();break;}
    case 'choose':{const i=Number(b.dataset.index);flow.select(i);if(state.selected){resumed=false;flow.message('「'+state.selected.name+'」 구성을 지금 견적으로 골랐어요. 저장은 따로 할 수 있어요.');flow.emit();}break;}
    case 'detail':{
      // 이미 고른 구성이면 그대로 연다(바꾼 부품·저장 상태를 지우지 않는다). 다른 구성이면 지금 견적이 바뀐다고 먼저 묻는다.
      const i=Number(b.dataset.index),x=state.groups.flatMap(g=>g.products).find(p=>p.index===i);if(!x)break;
      if(state.selected?.product_code===x.product_code){goDetail();break;}
      if(state.selected&&!confirm('상세를 열면 지금 견적이 「'+x.name+'」 구성으로 바뀌어요. 계속할까요?'))break;
      flow.select(i);if(state.selected)goDetail();break;}
    case 'open-detail':if(state.selected)goDetail(b.dataset.focus);break;
    case 'reprice':void flow.reprice();break;
    case 'handoff':void LF.handoffAndOpen(flow,window);break;
    case 'retry':void flow.retry();break;
    case 'explore':condOpen=false;void flow.explore(b.dataset.dir,b.dataset.label);break;
    case 'cond-open':condOpen=!condOpen;render();if(condOpen)log.querySelector('[data-cond=budget]')?.focus({preventScroll:true});break;
    case 'cond-close':condOpen=false;render();break;
    case 'inquiry-open':expandNow();void flow.openInquiry({human:b.dataset.human==='1'}).then(focusInquiry);break;
    case 'inquiry-close':flow.closeInquiry();break;
    case 'inquiry-send':void flow.inquire(inquiryValues());break;
    // 「새 상담」은 묻지 않고 바로 새로 시작한다(2026-10-15 중헌 님: 「지금 견적을 지우고…」 확인 창은 필요 없다 -- 새로 하고 싶으면 이 단추를 누르면 된다).
    // 서버에 저장한 「내 견적」은 그대로이고, 비우는 것은 이 탭의 대화·조건·지금 견적뿐이다.
    case 'new':resumed=false;entry=null;condOpen=false;flow.reset();input.value='';count();break;
    case 'toggle-now':{const open=$('#tk-now').classList.toggle('is-open');b.setAttribute('aria-expanded',String(open));break;}
  }
});
document.addEventListener('input',e=>{if(e.target.closest('[data-inquiry]'))flow.inquiryDraft(inquiryValues());if(e.target===input){count();if(!input.value.trim())entry=null;}});
document.addEventListener('change',e=>{if(e.target.closest('[data-inquiry]'))flow.inquiryDraft(inquiryValues());});
$('#tk-old').addEventListener('click',()=>markFromTalk(null));
$('#tk-form').addEventListener('submit',e=>{e.preventDefault();void send();});
log.addEventListener('submit',e=>{
  const form=e.target.closest('[data-cond-form]');if(!form)return;e.preventDefault();
  if(state.phase){busyNotice();return;}
  const text=conditionSentence(form);
  if(!text){status.textContent='바꿀 예산이나 용도를 적어 주세요.';status.hidden=false;return;}
  condOpen=false;void flow.submit(text);
});
input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();void send();}});

// 처음 화면에서 새로 시작해 들어왔으면(채팅창에 쓴 글 · 세 갈래 단추) 이 탭에 남은 지난 대화·조건·지금 견적을 되살리지 않고
// 비운 채 시작한다(2026-10-12 중헌 님 고객단 1·2번: 홈으로 돌아와 다른 상담을 골라도 지난 대화와 조건이 그대로 남았다).
// 서버에 저장한 「내 견적」은 지우지 않는다 -- 비우는 것은 이 탭의 대화 보관뿐이다.
// 지난 대화를 이어 가려면 처음 화면의 「작성하던 상담 이어가기」나 상단 「대화 화면」으로 들어온다(주소에 start 가 없다).
const freshStart=gatewayStarted();
flow.reset({restore:!freshStart});
if(state.restoredCurrent&&state.talk){resumed=true;void flow.resume();}
// 고른 구성 없이 카드만 보던 중 새로고침했으면 같은 조건으로 카드를 다시 받는다(값은 지금 기준 · AI 호출 없음).
else if(state.restoredShown&&state.talk)void flow.refresh({notes:false});
// 처음 화면과 오갈 때 보내지 않은 입력 문장을 넘긴다(코덱스 #148 검수 P2). 받은 문장은 입력 칸에 채우기만 한다.
// 새로 시작한 상담에는 지난 화면에서 적다 만 문장을 넣지 않는다.
const draftHandoff=LF.createDraftHandoff();
window.addEventListener('pagehide',()=>{draftHandoff.put(input.value);});
{const carried=draftHandoff.take();if(carried&&!freshStart&&!input.value.trim()){input.value=carried;count();}}
void startFromGateway();
})();
