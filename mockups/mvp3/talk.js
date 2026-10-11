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
const flow=LF.createFlow(A,{onChange:render,keepCurrent:true}),state=flow.state;
// 새로고침 전에 보던 구성을 다시 연 경우. 그 전에 보관했는지는 이 탭이 모르므로 「아직 저장하지 않았어요」라고 단정하지 않는다.
let resumed=false;

function budgetGap(product,talk){
  const won=talk?.budget_won;
  if(!Number.isInteger(product?.price)||!Number.isInteger(won))return '';
  if(talk.budget_bound==='이상')return '최소 예산 '+money(won)+' 조건';
  const d=won-product.price;
  return d>0?'예산보다 '+money(d)+' 낮아요':d<0?'예산보다 '+money(-d)+' 높아요':'예산과 같아요';
}
function photo(product){
  const p=customerPhoto(product.photo,product.product_code);
  if(p.state!=='available')return '';
  return '<figure class="tk-photo"><img src="'+esc(p.url+'?size=card')+'" alt="'+esc(product.name)+' · AI 조립 예시" loading="lazy" decoding="async"><figcaption>'+esc(p.notice)+'</figcaption></figure>';
}
function specList(spec){
  const rows=M.cardSpecRows(spec);
  return rows.length?'<dl class="tk-spec">'+rows.map(([k,v])=>'<div><dt>'+esc(k)+'</dt><dd>'+esc(v)+'</dd></div>').join('')+'</dl>':'';
}
function conditionsText(talk){const c=M.conditions(talk);return c.length?c.join(' · '):'';}

// 말풍선 아래 추천 카드. 가장 최근 제안만 고를 수 있고, 지난 제안은 그때 값 그대로 「이전 제안」으로 둔다.
function proposalBlock(p,latest){
  const products=p.groups.flatMap(g=>g.products);
  if(!products.length)return '<div class="tk-cards is-empty" data-proposal="'+p.id+'"><p>현재 조건에서 보여드릴 구성을 찾지 못했어요. 조건을 조금 바꾸거나 사람에게 문의할 수 있어요.</p>'+
    (latest?button('사람에게 문의하기','inquiry-open','outline','data-human="1"'):'')+'</div>';
  const head=latest?'':'<p class="tk-cards-note">이전 제안 · 그때 조건('+esc(conditionsText(p.talk)||'조건 미확인')+') 기준 금액이에요.</p>';
  const many=p.groups.filter(g=>g.products.length).length>1;
  return '<div class="tk-cards'+(latest?'':' is-past')+'" data-proposal="'+p.id+'">'+head+p.groups.filter(g=>g.products.length).map(g=>
    (many&&g.usage?'<h3 class="tk-group">'+esc(g.usage)+'</h3>':'')+'<ul class="tk-card-list">'+g.products.map(x=>card(x,p,latest)).join('')+'</ul>').join('')+'</div>';
}
function card(x,p,latest){
  const chosen=state.selected?.product_code===x.product_code;
  const reason=Array.isArray(x.reasons)&&x.reasons[0]?'<p class="tk-reason">'+esc(x.reasons[0])+'</p>':'';
  const gap=budgetGap(x,p.talk);
  return '<li class="tk-card'+(chosen?' is-chosen':'')+'"><span class="pill">'+esc(x.tag||x.level||'판매 중 PC')+'</span><h4>'+esc(x.name)+'</h4>'+photo(x)+
    '<p class="tk-price"><strong>'+money(x.price)+'</strong> <span class="muted">'+esc(x.price_src||'가격 기준 미확인')+'</span></p>'+
    (gap?'<p class="'+(x.price>p.talk?.budget_won&&p.talk?.budget_bound!=='이상'?'warn-text':'muted')+'">'+esc(gap)+'</p>':'')+specList(x.spec)+reason+
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
  let html=talked?'':'<section class="tk-welcome"><h1 tabindex="-1">무엇을 도와드릴까요?</h1><p>궁금한 것부터 편하게 물어보세요. PC를 찾거나 부품을 바꿀 때도 이어서 도와드릴게요.</p>'+
    '<div class="tk-examples" aria-label="시작 예시">'+['게임용 PC를 찾고 있어요.','지금 쓰는 PC를 업그레이드하고 싶어요.','그래픽카드와 메모리는 어떤 역할을 해요?']
      .map(t=>button(esc(t),'example','outline','data-text="'+esc(t)+'"')).join('')+'</div></section>';
  msgs.forEach((m,i)=>{
    if(!(m.who==='ai'&&m.text===LF.GREETING))html+='<div class="tk-msg is-'+(m.who==='user'?'user':'ai')+'"><p>'+esc(m.text)+'</p></div>';
    for(const p of after.get(i)||[])html+=proposalBlock(p,p===last&&state.recommendation!==null);
  });
  if(state.handoffOffer&&!state.inquiry.open&&!state.inquiry.done)html+='<div class="tk-msg-actions">'+button('사람에게 문의하기','inquiry-open','outline','data-human="1"')+'</div>';
  if(state.error){
    const recommend=state.retry?.kind==='recommend'||state.retry?.kind==='resume';
    const wait=Math.max(0,Math.ceil(((state.error.retryAt||0)-Date.now())/1000));
    html+='<div class="tk-msg is-ai is-error" role="alert"><p>'+(recommend?'새 추천을 불러오지 못했어요.'+(state.selected?' 앞서 고른 견적은 유지할게요.':''):'이번 답변을 불러오지 못했어요. 다시 시도하거나 사람에게 문의할 수 있어요.')+'</p>'+
      '<p class="muted">'+esc(state.error.message)+'</p><div class="tk-msg-actions">'+
      (state.retry?button(wait?wait+'초 뒤 다시 시도':'다시 시도','retry','outline',wait||state.phase?'disabled':''):'')+
      button('사람에게 문의하기','inquiry-open','outline','data-human="1"')+'</div></div>';
  }
  log.innerHTML=html;
  if(atBottom||state.phase==='talk'){if(pageScroll)scrollTo(0,doc.scrollHeight);else log.scrollTop=log.scrollHeight;}
}

function inquiryForm(){
  const q=state.inquiry;if(!q.open&&!q.done)return '';
  const human=!!q.human,title=human?'사람에게 문의하기':'구매 조건 문의';
  if(q.done)return '<section class="tk-inquiry" role="status"><h3>'+title+'</h3><p>'+esc(q.done.note)+'</p><p class="muted">신청 번호 '+esc(q.done.inquiry_no)+' · 주문과 결제는 진행되지 않았어요.</p></section>';
  const busy=state.phase==='inquiry'||state.phase==='inquiry-form',d=q.draft,dis=busy?' disabled':'';
  const err=q.error?'<p class="warn-text" role="alert">'+esc(q.error)+'</p>':'';
  const intro=human?'연락처와 궁금한 내용을 남겨주세요. 이 신청으로 주문이나 결제가 진행되지는 않아요.':'여러 대 구매·할인·세금계산서 등 확인할 내용을 남겨주세요. 이 신청으로 주문이나 결제가 진행되지는 않아요.';
  if(!q.meta)return '<section class="tk-inquiry"><h3>'+title+'</h3>'+(busy?'<p class="muted">문의 신청 양식을 불러오는 중이에요.</p>':err+button('다시 불러오기','inquiry-open','outline',human?'data-human="1"':''))+'</section>';
  const field=(label,el)=>'<label class="tk-field"><span>'+label+'</span>'+el+'</label>';
  return '<section class="tk-inquiry"><h3>'+title+'</h3><p class="muted">'+intro+'</p>'+
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
    html+='<p class="muted">'+(state.restoredCurrent&&state.phase==='recommend'?'새로고침 전에 보던 구성을 다시 확인하고 있어요.':'구성을 선택하면 여기에 모아둘게요.')+'</p>'+(now?'<p class="tk-cond">지금 조건 · '+esc(now)+'</p>':'');
  }else{
    const basis=conditionsText(state.selectionState),changed=JSON.stringify(state.selectionState)!==JSON.stringify(state.talk);
    const saved=state.saveState==='saved'&&state.savedQuote;
    html+='<p class="tk-now-label">지금 선택한 구성</p><h3>'+esc(p.name)+'</h3>'+photo(p)+
      (basis?'<p class="tk-cond">고를 때 조건 · '+esc(basis)+'</p>':'')+
      (changed&&now?'<p class="tk-cond is-new">지금 조건 · '+esc(now)+'</p>':'')+
      (changed&&state.phase==='recommend'?'<p class="tk-note" role="status">새 조건으로 다시 살펴보는 중이에요. 지금 견적은 그대로 남겨둘게요.</p>':'')+
      '<p class="tk-price"><strong>'+money(p.price)+'</strong> <span class="muted">'+esc(p.price_src||'가격 기준 미확인')+'</span></p>'+
      (budgetGap(p,state.talk)?'<p class="muted">'+esc(budgetGap(p,state.talk))+(changed?' (지금 조건 기준)':'')+'</p>':'')+
      specList(p.spec)+
      (p.build?.changes?.length?'<p class="muted">바꾼 부품 '+p.build.changes.length+'개를 반영한 금액이에요.</p>':'')+
      '<p class="muted">재고·판매 조건은 저장하거나 구매할 때 다시 확인해요.</p>'+
      '<p class="tk-save-state">'+(saved?'견적을 저장했어요.':state.saveState==='uncertain'?'저장 결과를 확인하지 못했어요. 내 견적에서 확인해 주세요.':resumed?'새로고침 전 저장 여부는 내 견적에서 확인할 수 있어요.':'아직 저장하지 않았어요.')+'</p>'+
      '<div class="tk-row">'+button('구성 자세히 보기','open-detail','outline',busy?'disabled':'')+button('부품 바꾸기','open-detail','outline',busy?'disabled':'')+
      button(saved?'저장 완료':state.phase==='save'?'저장하는 중…':'견적 저장','save','primary',busy||saved||state.needsRefresh||!!state.pendingSave||!!state.pendingProblem||!Number.isInteger(p.price)?'disabled':'')+'</div>';
    if(saved){
      const h=state.handoff?.quote_id===state.savedQuote.id?state.handoff:null;
      html+='<div class="tk-buy">'+(h?'<a class="primary tk-link" href="'+esc(h.mall_url)+'" target="_blank" rel="noopener noreferrer">쇼핑몰에서 구매 이어가기</a><p class="muted">연결 번호 '+esc(h.handoff_no)+' · 결제·배송·보증은 쇼핑몰에서 안내해요.</p>'
        :button(state.phase==='handoff'?'쇼핑몰 가격 확인 중…':'쇼핑몰에서 구매 이어가기','handoff','outline',busy?'disabled':'')+'<p class="muted">결제는 이 화면이 아니라 팝콘PC 쇼핑몰에서 진행돼요.</p>')+'</div>';
    }
  }
  if(!q.open&&!q.done)html+='<div class="tk-ask">'+button('사람에게 문의하기','inquiry-open','outline',(busy?'disabled ':'')+'data-human="1"')+(p?button('구매 조건 문의','inquiry-open','outline',busy?'disabled':''):'')+'</div>';
  panel.innerHTML=html+inquiryForm();
}

function render(){
  renderLog();renderPanel();
  const busy={talk:'답변을 준비하고 있어요.',recommend:'구성을 찾고 있어요.',save:'견적을 저장하고 있어요.',handoff:'쇼핑몰 가격을 확인하고 있어요.'}[state.phase]||'';
  status.textContent=busy;status.hidden=!busy;
  $('#tk-send').disabled=!!state.phase;
}

function goDetail(){location.href='index.html#detail';}
async function send(){
  const text=input.value;
  if(!text.trim()){status.textContent='궁금한 내용이나 원하는 조건을 적어주세요.';status.hidden=false;input.focus();return;}
  if(text.trim().length>MAX_TEXT){status.textContent='한 번에 20,000자까지 보낼 수 있어요. 나눠서 보내 주세요.';status.hidden=false;return;}
  if(state.phase)return;
  input.value='';count();
  const sent=await flow.submit(text);
  if(!sent&&!input.value)input.value=text;
}
function count(){const n=input.value.length;$('#tk-count').textContent=n>1000?n.toLocaleString('ko-KR')+' / 20,000자':'';}

document.addEventListener('click',e=>{
  const b=e.target.closest('[data-action]');if(!b||b.disabled)return;
  switch(b.dataset.action){
    case 'example':input.value=b.dataset.text;count();input.focus();break;
    case 'choose':{const i=Number(b.dataset.index);flow.select(i);if(state.selected){resumed=false;flow.message('「'+state.selected.name+'」 구성을 지금 견적으로 골랐어요. 저장은 따로 할 수 있어요.');flow.emit();}break;}
    case 'detail':flow.select(Number(b.dataset.index));if(state.selected)goDetail();break;
    case 'open-detail':if(state.selected)goDetail();break;
    case 'save':void flow.save();break;
    case 'handoff':void flow.handoff();break;
    case 'retry':void flow.retry();break;
    case 'inquiry-open':void flow.openInquiry({human:b.dataset.human==='1'});break;
    case 'inquiry-close':flow.closeInquiry();break;
    case 'inquiry-send':void flow.inquire(inquiryValues());break;
    case 'new':if(!state.messages.some(m=>m.who==='user')||confirm('지금 대화와 지금 견적을 지우고 새 상담을 시작할까요?')){resumed=false;flow.reset();input.value='';count();}break;
    case 'toggle-now':{const open=$('#tk-now').classList.toggle('is-open');b.setAttribute('aria-expanded',String(open));break;}
  }
});
document.addEventListener('input',e=>{if(e.target.closest('[data-inquiry]'))flow.inquiryDraft(inquiryValues());if(e.target===input)count();});
document.addEventListener('change',e=>{if(e.target.closest('[data-inquiry]'))flow.inquiryDraft(inquiryValues());});
$('#tk-form').addEventListener('submit',e=>{e.preventDefault();void send();});
input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();void send();}});

flow.reset({restore:true});
if(state.restoredCurrent&&state.talk){resumed=true;void flow.resume();}
})();
