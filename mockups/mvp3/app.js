(function(){'use strict';
// 처음 화면은 하나다(2026-10-16 중헌 님 「첫화면 게이트웨이를 세군대로 나누는게 의미가 없어 … 예전처럼 단일 화면으로」).
// 서비스의 핵심은 완제 조립PC와 관리자가 맞춰 둔 PC를 보여 주는 것이라, 들어오면 바로 상담 + 추천 PC 화면이다.
// 세 갈래 입구(#151·#159)와 그 앞의 두 갈래(용도부터/바로 상담, 1ecf4df)는 걷었다. 대화 화면(talk.html)은 머리띠
// 「대화 화면」으로, 관리자가 맞춰 둔 PC 는 첫 화면 아래 목록과 머리띠 「새로 구성된 PC」로 간다.
const M=window.MVP3LiveModel,A=window.MVP3Api;
const {customerPhoto}=window.MVP3LivePhoto;
const $=s=>document.querySelector(s),view=$('#view'),actions=$('#actions'),mobile=matchMedia('(max-width:760px)');
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const uiIcon=(name,cls='')=>'<img class="ui-icon '+cls+'" src="assets/icons/'+name+'.svg" alt="">';
const button=(label,action,cls='',data='')=>'<button type="button" class="'+cls+'" data-action="'+action+'" '+data+'>'+label+'</button>';
const money=value=>Number.isInteger(value)?value.toLocaleString('ko-KR')+'원':'금액 미확인';
const flow=window.MVP3LiveFlow.createFlow(A,{onChange:render}),state=flow.state,keepUi=window.MVP3LiveFlow.createKeepUi(flow,document,{page:true});
// 대화 화면(talk.html)에서 넘어왔는지(talk.js FROM_TALK_KEY · 한 번 읽고 지운다). 넘어왔으면 「대화로 돌아가기」를
// 보이고, 「부품 바꾸기」로 넘어왔으면 상세가 열린 뒤 부품 바꾸기 칸으로 옮긴다. 대화·견적은 같은 탭 보관으로 온다.
const FROM_TALK_KEY='popcorn-mvp3-from-talk-v1';
const arrival=(()=>{try{const raw=sessionStorage.getItem(FROM_TALK_KEY);sessionStorage.removeItem(FROM_TALK_KEY);const v=raw?JSON.parse(raw):null;return v&&typeof v==='object'?{focus:v.focus==='parts'}:null;}catch{return null;}})();
// 대화 화면에서 온 상세에는 옛 상담창을 붙이지 않는다 -- 대화는 「대화로 돌아가기」로 이어 간다(2026-10-12 카드 검수:
// 상세 왼쪽·모바일 위쪽에 옛 상담창 「어떤 PC를 찾으세요?」가 통째로 나왔다).
if(arrival){$('#back-to-talk').hidden=false;document.body.dataset.fromTalk='1';}
// restoring: 처음 열 때 보관된 견적·추천을 다시 불러오는 동안. 그 사이 화면이 바뀌어도 방문 기록을 늘리지 않는다 --
// 늘리면 대화 화면에서 상세로 온 고객이 「뒤로」를 눌렀을 때 대화가 아니라 빈 첫 화면이 나온다(2026-10-12 고객단 끝까지 검수 E15).
let restoring=false;
let lastScreen=null,chatPreference=null,noticeTimer,retryTimer,lastMessages='',enteringRoute=true;
const draft={version:1,draft_text:'',draft_edited:false};
$('.brand').dataset.action='home';
const screenNames=['welcome','results','detail','final','saved'];
function captureDraft(){draft.draft_text=$('#request').value;}
function setDraft(text,edited=false){draft.draft_text=text;draft.draft_edited=edited;$('#request').value=text;}
function focusConsultation(){chatPreference=true;syncChat();if(!state.phase)$('#request').focus({preventScroll:true});else view.querySelector('h2')?.focus({preventScroll:true});}
// 첫 화면 아래 「팝콘PC가 맞춰 둔 PC」 목록은 welcome-pcs.js 가 불러와 그린다(이 파일은 서버를 API 클라이언트로만 부른다).
// 목록이 도착하면 첫 화면을 한 번 다시 그린다.
const welcomePcs=()=>window.MVP3WelcomePcs?.html()||'';
window.addEventListener('mvp3:welcome-pcs',()=>{if(state.screen==='welcome')render();});
function notice(text){$('#notice').textContent=text;$('#notice').hidden=false;clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>$('#notice').hidden=true,7000);}
// 여러 대(wants.units)면 한 대 예산으로 견준다(M.budgetGapText · 코덱스 C10-F01). 조건과 같은 때의 wants 를 쓴다.
function wantsFor(talk){return talk&&talk===state.selectionState?state.selectionWants:state.wants;}
function budget(product,talk=state.selectionState||state.talk,wants=wantsFor(talk)){
  const won=talk?.budget_won;
  if(!Number.isInteger(product.price)||!Number.isInteger(won))return '예산 조건 미확인';
  if(talk.budget_bound==='이상')return '입력하신 최소 예산 '+money(won);
  return M.budgetGapText(product.price,talk,wants,money);
}
// 예산 초과 색은 문구(budget)와 같은 금액·같은 기준으로 정한다. 부품을 바꾸면 서버의 over_budget 은
// 기본 구성 금액 기준이라 낡으므로, 바꾼 구성은 새 금액으로 다시 센다(하한 「이상」은 초과가 없다).
function overBudget(product,talk=state.selectionState||state.talk,wants=wantsFor(talk)){
  const multi=(M.budgetBasis(talk,wants)?.units??1)!==1;
  if(!product.build&&!multi)return product.over_budget===true;
  return M.overUnitBudget(product.price,talk,wants);
}
// 상세의 예산 문장은 위 조건 칩(지금 조건 = state.talk)과 같은 기준이어야 한다. 고른 뒤 상담에서 예산을 바꾸면
// selectionState(고를 때 조건)와 칩이 갈라져, 칩은 80만원인데 초과액은 150만원 기준 124,400원으로 남았다
// (2026-10-15 코덱스 오픈테스트 C05-F01). 두 기준이 다르면 기준을 밝혀 둘 다 적는다.
function budgetLines(p){
  const basis=state.selectionState,now=state.talk,line=(cls,text)=>'<p class="'+cls+'">'+esc(text)+'</p>';
  const same=!basis||!now||basis.budget_won===now.budget_won&&basis.budget_bound===now.budget_bound;
  // 여러 대인데 대수를 몰라 견주지 않은 줄은 통과(초록)로 칠하지 않는다.
  const cls=(t=state.selectionState||state.talk)=>overBudget(p,t)?'warn-text':M.budgetBasis(t,wantsFor(t))?.units===0?'muted':'green';
  if(same)return line(cls(),budget(p));
  const label=t=>Number.isInteger(t?.budget_won)?' 예산 '+money(t.budget_won)+' 기준 · ':' ';
  return line(cls(now),'지금'+label(now)+budget(p,now))+
    line('muted','고를 때'+label(basis)+budget(p,basis));
}
function syncChat(){
  const open=!mobile.matches||(chatPreference??state.screen==='welcome');
  const body=$('#chat-body'),toggle=$('#chat-toggle');
  if(!open&&body.contains(document.activeElement))toggle.focus({preventScroll:true});
  body.hidden=!open;toggle.setAttribute('aria-expanded',String(open));$('#chat-toggle-label').textContent=open?'상담 접기 ▴':'상담 내용 보기 ▾';
  $('#chat-summary').textContent=M.conditions(state.talk).join(' · ')||'게임과 예산을 알려주세요';
}
// Quick replies follow what the consultation is asking for: the server's `missing`
// (usages → 용도, game.grade → 게임). Game-only options stay for game talk.
function quickPrompts(){
  const missing=Array.isArray(state.missing)?state.missing:[];
  if(state.screen==='welcome'&&missing.includes('usages'))return ['게임용이에요','영상 편집용이에요','사무용이에요'];
  if(state.screen==='welcome'&&missing.includes('game.grade'))return ['배그를 해요','롤을 해요','배그와 롤 둘 다 해요'];
  return state.screen==='welcome'?['QHD로 해줘요','예산을 좀 더 낮춰줘요','다른 게임도 추가할게요']:['예산을 바꿀게요','용도를 바꿀게요'];
}
// After cards: the server's quick choices (cheaper / better than the card being looked at,
// or change conditions). Disabled ones are left out — the server found nothing that way.
function exploreButtons(cls){
  const choices=state.screen==='results'&&state.recommendation?state.choices||[]:[];
  return choices.filter(c=>c.enabled).map(c=>c.id==='change'?button(esc(c.label),'conditions',cls,state.phase?'disabled':''):
    button(esc(c.label),'explore',cls,'data-dir="'+c.id+'" data-label="'+esc(c.label)+'" '+(state.phase?'disabled':''))).join('');
}
// Show the newest message from its first line; a long answer that does not fit
// starts at its top instead of being cut mid-sentence at the top of the log.
function scrollToLatest(){
  const log=$('#messages'),last=log.lastElementChild;
  if(!last){log.scrollTop=0;return;}
  const top=last.getBoundingClientRect().top-log.getBoundingClientRect().top+log.scrollTop-8;
  log.scrollTop=last.offsetHeight>log.clientHeight-16?Math.max(0,top):log.scrollHeight;
  markScroll();
}
// A scrolled log gets an upper edge so the clipped bubble does not look stuck to the intro.
function markScroll(){const log=$('#messages'),on=log.scrollTop>0;log.classList.toggle('is-scrolled',on);$('#chat-body').classList.toggle('log-scrolled',on);}
function renderMessages(){
  const key=JSON.stringify(state.messages);
  if(key!==lastMessages){
    $('#messages').innerHTML=state.messages.map(x=>'<div class="message '+(x.who==='user'?'user':'ai')+'"><span class="avatar">'+(x.who==='user'?uiIcon('user'):'<img class="avatar-mark" src="assets/popcorn-mark.png" alt="팝콘AI">')+'</span><div class="message-content"><p>'+(
      x.text==='안녕하세요! 어떤 용도로 쓰실 PC인지와 예산을 알려주시면 맞는 PC를 함께 찾아드릴게요.'&&state.screen==='welcome'?
      '안녕하세요! 어떤 용도로 쓰실 PC인지와<br>예산을 알려주시면 맞는 PC를<br>함께 찾아드릴게요.':esc(x.text))+'</p></div></div>').join('');
    scrollToLatest();lastMessages=key;
  }
  // 고객이 한 번 말한 뒤에는 첫 질문 머리말을 감춘다(2026-10-12 사장님 「계속 어떤 PC를 찾으세요? 이게 나오는데」).
  // 고정 머리말이 대화 위에 남아 같은 질문을 계속 되묻는 것처럼 읽혔다.
  $('#chat-body .chat-intro').hidden=state.messages.some(x=>x.who==='user');
  const examples=$('#start-examples');examples.hidden=state.screen!=='welcome';
  if(!examples.hidden)examples.innerHTML=[['game-controller','배그와 롤, 150만원으로 추천해줘'],['video-camera','영상 편집용 PC가 필요해요'],['question','아직 잘 모르겠어요']].map(pair=>
    button(uiIcon(pair[0])+'<span>'+pair[1]+'</span>'+uiIcon('caret-right','example-chevron'),'prompt','start-example','data-text="'+pair[1]+'" '+(state.phase?'disabled':''))).join('');
  const prompts=quickPrompts(),explore=exploreButtons('chip');
  $('#suggestions').innerHTML=explore||prompts.map(text=>button(text,'prompt','chip','data-text="'+text+'" '+(state.phase?'disabled':''))).join('');
  $('#request').disabled=!!state.phase;$('#chat-form .send').disabled=!!state.phase;
  const label={talk:'AI가 조건과 답변을 확인하고 있어요.',recommend:'조건에 맞는 판매 중 PC를 조회하고 있어요.',save:'서버에서 최신 상품과 가격을 확인해 보관하고 있어요.',list:'이 브라우저의 보관 기록을 불러오고 있어요.'};
  $('#operation-status').textContent=label[state.phase]||'';$('#operation-status').hidden=!state.phase;
}
function requirements(withAssumed=false){
  const chips=M.conditionChips(state.talk,withAssumed?state.assumed:[]);
  // Chips change conditions through the consultation (no server-side removal API).
  return chips.length?'<div class="requirements">'+chips.map(c=>c.assumed?'<span class="chip condition-chip is-assumed" title="'+esc(c.note)+'">'+uiIcon(c.icon)+'<span>'+esc(c.label)+'</span></span>':
    button(uiIcon(c.icon)+'<span>'+esc(c.label)+'</span><span class="chip-change" aria-hidden="true">×</span>','conditions','chip condition-chip','aria-label="'+esc(c.label)+' 조건 바꾸기"')).join('')+'</div>':'';
}
function errorPanel(){
  if(!state.error||handoffFailed())return '';
  const e=state.error,seconds=Math.max(0,Math.ceil((e.retryAt-Date.now())/1000));
  const uncertain=state.saveState==='uncertain';
  const retryLabel=state.retry?.kind==='recommend'?'최신 추천 다시 조회':['save','recover'].includes(state.retry?.kind)?'같은 보관 요청 확인':'다시 시도';
  return '<section class="live-error" role="alert"><h3>'+(uncertain?'보관 결과를 확인하지 못했어요':'요청을 완료하지 못했어요')+'</h3><p>'+esc(e.message)+'</p>'+
    (uncertain?'<p>현재 상품은 유지돼요. 내 견적에서 확인하거나 같은 요청으로 다시 시도할 수 있어요.</p>':'')+
    '<div>'+button(seconds?'다시 시도까지 '+seconds+'초':retryLabel,'retry','outline',state.phase||seconds?'disabled':'')+
    (uncertain?button('내 견적 확인','saved','text-button'):'')+'</div></section>';
}
function recoveryBanner(){
  if(!state.pendingSave&&!state.pendingProblem)return '';
  const p=state.pendingSave?.payload;
  return '<section class="live-recovery" role="status"><h3>이전 보관 요청 확인</h3><p>'+esc(state.pendingProblem||'상품번호 '+p.product_code+' · 요청 당시 '+money(p.expected_price)+'의 보관 결과를 아직 확인하지 못했어요. 새로고침 뒤에도 같은 요청을 유지합니다.')+'</p><p>목록 조회만으로 이 요청의 완료를 확정하지 않아요. 자동 재전송 없이 직접 확인할 수 있어요.</p><div>'+button('보관 목록 확인','saved','outline',state.phase?'disabled':'')+
    (p?button('같은 보관 요청 확인','recover','primary',state.phase||Date.now()<(state.error?.retryAt||0)?'disabled':''):'')+'</div></section>';
}
function heading(title,back=true,subtitle='',withAssumed=false){
  return (back?button(uiIcon('arrow-left')+'이전 화면','back','back live-back'):'')+'<div class="title-row"><div class="title-copy"><h2 tabindex="-1">'+title+'</h2>'+(subtitle?'<p class="results-subtitle">'+esc(subtitle)+'</p>':'')+'</div><span class="data-note">판매 중 PC · 조회 시점 참고 금액</span></div>'+requirements(withAssumed);
}
// Cards ask for the small card photo; the detail summary keeps the original.
function productImage(product,full){
  const photo=customerPhoto(product.photo,product.product_code);
  if(photo.state!=='available')return '<figure class="live-product-photo is-unavailable" data-product-photo data-image-state="'+photo.state+'"><p class="live-product-image-status">'+(photo.state==='temporarily_unavailable'?'이미지를 불러오지 못했습니다':'정보 없음')+'</p></figure>';
  return '<figure class="live-product-photo" data-product-photo><img data-product-image src="'+esc(full?photo.url:photo.url+'?size=card')+'" alt="'+esc(product.name)+' · AI 조립 예시" loading="lazy" decoding="async"><p class="live-product-image-status" data-product-image-status hidden>이미지를 불러오지 못했습니다</p><figcaption class="live-product-photo-notice">'+esc(photo.notice)+'</figcaption></figure>';
}
// The emphasized card is the server's "recommended" role (normalized in live-model.js).
function recommendedCard(product){return product.role==='recommended';}
const cardsClass=group=>'quote-cards'+(group.products.length===3?' has-three':'');
// Approved part photos on the card itself; parts without one are simply left out (no placeholder).
function cardPartPhotos(product){
  const photos=M.cardPartPhotos(product);
  if(!photos.length)return '';
  return '<ul class="card-part-photos" aria-label="부품 사진">'+photos.map(x=>'<li><figure data-card-part-photo><img data-card-part-image src="'+esc(x.url)+'" alt="'+esc(x.name||x.label)+' 부품 사진" loading="lazy" decoding="async"><figcaption>'+esc(x.label)+'</figcaption></figure></li>').join('')+'</ul>';
}
function productCard(product,action='detail',id=product.index,comparison=null){
  const rows=M.cardSpecRows(product.spec),strong=recommendedCard(product),description=product.public_configuration?.description;
  const spec=rows.length?'<dl class="live-card-spec">'+rows.map(([label,value])=>'<div><dt>'+esc(label)+'</dt><dd>'+esc(value)+'</dd></div>').join('')+'</dl>':'<p class="live-product-spec">'+esc(M.specText(product.spec)||'정보 없음')+'</p>';
  const featured=Boolean(description?.intro),intro=description?.intro||M.cardFallbackIntro(product,comparison),title=description?.title||product.name;
  const sameBasis=comparison&&product.price_src&&product.price_src===comparison.price_src&&Number.isSafeInteger(product.price)&&Number.isSafeInteger(comparison.price);
  const delta=sameBasis?product.price-comparison.price:null;
  const difference=delta===null?'':delta===0?'다른 구성과 같은 금액이에요.':(comparison.tag||'다른 구성')+'보다 '+money(Math.abs(delta))+(delta>0?' 높아요.':' 낮아요.');
  return '<section class="quote-card live-product-card"><div class="live-card-heading"><div class="live-card-copy"><span class="pill '+(strong?'strong':'')+'">'+esc(product.tag||product.level||'판매 중 PC')+'</span>'+
    '<h3>'+esc(title)+'</h3>'+(title!==product.name?'<p class="live-product-name">'+esc(product.name)+'</p>':'')+(intro?(featured?'<p class="live-card-intro-label">이 PC 특징</p>':'')+'<p class="live-card-intro">'+esc(intro)+'</p>':'')+'</div>'+productImage(product)+'</div>'+
    '<strong class="price">'+money(product.price)+'</strong><p class="muted">'+esc(product.price_src||'가격 기준 미확인')+'</p>'+spec+cardPartPhotos(product)+
    (difference?'<p class="live-price-difference">'+esc(difference)+'</p>':'')+
    // Full reasons stay on the detail screen; the card keeps only the over-budget verdict.
    (overBudget(product,state.talk)?'<p class="warn-text">'+esc(budget(product,state.talk))+'</p>':'')+
    button(strong?'추천 견적 자세히 보기'+uiIcon('arrow-right'):'구성 자세히 보기',action,(strong?'primary':'outline')+' card-detail','data-id="'+esc(id)+'"')+'</section>';
}
// 새로 구성된 PC(부품 상품화 5단계): 운영자가 부품을 골라 만든 조립PC. 몰 카드와 따로 두고 「새로 구성된 PC」 화면으로 보낸다.
// 용도 적합도는 서버 판정(fit · 정보 없음)을 그대로 적는다 — 정보가 없어도 숨기지 않는다(2026-10-10 결정).
function customCards(group){
  if(!group.custom?.length)return '';
  return '<section class="custom-pc-group" aria-label="새로 구성된 PC"><h4>새로 구성된 PC · 팝콘PC가 용도에 맞춰 부품을 골라 구성한 완제조립PC</h4><div class="quote-cards">'+group.custom.map(c=>
    '<section class="quote-card live-product-card custom-pc-card" data-custom-pc="'+esc(c.configuration_id)+'"><span class="pill">새로 구성된 PC</span><h3>'+esc(c.title)+'</h3>'+
    '<strong class="price">'+money(c.price)+'</strong><p class="muted">'+esc(c.price_note)+'</p>'+
    '<p class="custom-pc-fit">용도 적합도: '+esc(c.fit==='fit'?c.level_text:'정보 없음')+'</p>'+
    (c.parts.length?'<dl class="live-card-spec">'+c.parts.map(x=>'<div><dt>'+esc(x.slot_label)+'</dt><dd>'+esc(x.name)+(x.quantity>1?' × '+x.quantity:'')+'</dd></div>').join('')+'</dl>':'')+
    '<a class="outline card-detail custom-pc-link" href="'+esc(c.url)+'">자세히 보기 · 구매 상담</a></section>').join('')+'</div></section>';
}
function renderResults(){
  const groups=state.groups,hasProducts=groups.some(g=>g.products.length);
  const gameLabels=[['spec_summary','게임 사양 안내'],['why_this_pc','PC 선택 안내'],['upgrade_hint','업그레이드 안내'],['caution','확인할 내용']];
  const products=groups.flatMap(g=>g.products),withinBudget=Number.isInteger(state.talk?.budget_won)&&state.talk.budget_bound!=='이상'&&(M.budgetBasis(state.talk,state.wants)?.units??1)===1&&products.every(p=>!p.over_budget);
  const subtitle=groups.length===1&&products.length===2?(withinBudget?'예산 안에서 비교할 수 있는 두 가지 구성입니다.':'비교할 수 있는 두 가지 구성입니다.'):
    groups.length===1&&products.length===3?'싼 구성부터 더 높은 사양까지 세 가지를 비교해 보세요.':'';
  // A usage heading is needed only to tell several usage groups apart.
  const groupHeading=group=>groups.length>1?'<h3>'+esc(group.usage||group.usage_grid||'추천 상품')+'</h3>':'';
  view.innerHTML=heading('나에게 맞는 PC',false,subtitle,true)+errorPanel()+
    groups.map(group=>{const ctx=group.game_context,url=M.safeUrl(ctx?.source.url);return '<section class="live-result-group">'+groupHeading(group)+
      (group.empty_note?'<p class="muted">'+esc(group.empty_note)+'</p>':'')+
      (group.products.length?'<div class="'+cardsClass(group)+'">'+group.products.map((p,n)=>productCard(p,'detail',p.index,n>0?group.products[n-1]:null)).join('')+'</div>':'<div class="empty small-empty"><h3>'+esc(group.empty_reason||'추천 상품이 없어요')+'</h3><p>조건을 더 알려주시거나 예산·용도를 바꿔주세요.</p></div>')+customCards(group)+
      (ctx?'<div class="live-explanation"><h4>게임 안내 · '+esc(ctx.game_name)+'</h4><ul>'+gameLabels.filter(([key])=>ctx[key]).map(([key,label])=>'<li><strong>'+label+': </strong>'+esc(ctx[key])+'</li>').join('')+'</ul>'+(url?'<p class="muted"><a href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">자세히 보기</a></p>':'')+'</div>':'')+'</section>';}).join('')+
    (!hasProducts&&!groups.length?'<div class="empty"><h3>'+(state.missing.length?'조건을 조금 더 알려주세요':'현재 조건의 추천 상품이 없어요')+'</h3><p>상담은 계속할 수 있어요. 예산이나 사용 목적을 알려주세요.</p></div>':'')+
    (hasProducts&&exploreButtons('outline small')?'<div class="explore-choices" role="group" aria-label="다른 구성 보기">'+exploreButtons('outline small')+'</div>':'')+
    (hasProducts?'<p class="results-note">'+uiIcon('info')+'해상도나 포함 품목을 바꾸면 견적이 달라질 수 있어요.</p>':'')+
    (state.recommendation?.aiEstimated.length?'<p class="muted">일부 게임 등급은 AI 추정입니다. 실제 게임 성능 측정값과는 달라요.</p>':'');
  actions.hidden=true;
}
// 공개 소개 글은 상품마다 한 벌이고 대개 게임 기준으로 쓰였다. 게임이 아닌 상담(영상편집·사무용)에서 「게임 화면의
// 화질과 움직임」이 대표 문장이 되지 않게, 그때는 상품 이름과 이 상담의 추천 이유를 쓴다(코덱스 24조합 검수 1번).
function summaryDescription(p){
  const d=p.public_configuration?.description;if(!d)return null;
  const cond=state.selectionState||state.talk,usages=Array.isArray(cond?.usages)?cond.usages:[];
  if(!usages.some(u=>typeof u==='string'&&u.includes('게임'))&&/게임/.test((d.title||'')+' '+(d.intro||'')))return null;
  return d;
}
function productSummary(){
  const p=state.selected,description=summaryDescription(p),title=description?.title||p.name;
  const intro=state.savedQuote?'금액과 상품 기록은 보관 시점 기준입니다. 부품 구성과 사진은 조회 시점의 공개 상태를 따릅니다.':M.changedIntro(description?.intro,p.build)||p.reasons[0]||p.tag||p.level||'판매 중인 완제품 구성입니다.';
  return '<section class="final-summary live-summary"><div class="live-summary-copy"><h3>'+esc(title)+'</h3>'+(title!==p.name?'<p class="live-product-name">'+esc(p.name)+'</p>':'')+(M.changedPartsNote(p.build)?'<p class="muted" data-changed-parts>'+esc(M.changedPartsNote(p.build))+'</p>':'')+'<p>'+esc(intro)+'</p></div><div class="final-summary-price"><strong>'+money(p.price)+'</strong>'+(p.build?'<p class="muted" data-pc-total-move>바꾼 부품 '+p.build.changes.length+'개 · '+totalMove(p)+'</p>'+(p.build.warnings||[]).map(w=>'<p class="warn-text">'+esc(w)+'</p>').join(''):'')+(p.sets>1&&Number.isSafeInteger(p.price)?'<p data-sets-total><strong>같은 구성 '+p.sets+'대 · 합계 '+money(p.price*p.sets)+'</strong></p>':'')+budgetLines(p)+'</div>'+productImage(p,true)+'</section>';
}
function publicBomDetails(configuration,p,information,finalOnly){
  const roles=BOM_ROLES;
  const rows=configuration.parts.map(part=>{
    const [label,icon,role]=(Object.hasOwn(roles,part.slot)?roles[part.slot]:null)||[part.pseudo?'서비스':part.slot,'gear','등록된 사양과 설명을 확인해주세요.'];
    const id='bom-unavailable-'+part.ordinal,swap=!part.pseudo,change=p.build?.changes.find(c=>c.ordinal===part.ordinal);
    const open=state.build?.ordinal===part.ordinal;
    if(change)return buildChangedRow(part,label,icon,change,finalOnly,open);
    const shown=pseudoPart(part);
    const specs=part.specs.length?'<dl class="live-spec-grid">'+part.specs.map(x=>'<div><dt>'+esc(x.label)+'</dt><dd>'+esc(x.value.trim()||'정보 없음')+'</dd></div>').join('')+'</dl>':'<p>정보 없음</p>';
    return '<tr data-part="bom-'+part.ordinal+'"><td colspan="3"><details class="public-bom-disclosure" data-detail="bom-'+part.ordinal+'"><summary>'+
      '<div class="final-part-description">'+uiIcon(icon,'part-symbol')+'<div><h4><span>'+esc(label)+'</span><span class="part-name">'+esc(shown.name||part.name||'정보 없음')+'</span><span class="public-bom-quantity">수량 '+part.quantity+'</span>'+(part.assembly_only?'<span class="mp-assembly">조립 전용</span>':'')+'</h4><p>'+esc(shown.description||part.description||'정보 없음')+'</p>'+
      '<span class="public-bom-toggle"><span class="when-closed">상세 정보 펼치기</span><span class="when-open">상세 정보 접기</span>'+uiIcon('caret-down')+'</span></div></div>'+
      '<span class="final-part-price">'+partLinePrice(part)+'</span><span class="final-part-change">'+changeButton(part,label,finalOnly,open,id)+'</span></summary><div class="final-part-expanded public-bom-expanded">'+
      (part.photo?.state==='approved'?'<figure class="public-bom-photo" data-product-photo><img data-product-image src="'+esc(part.photo.url)+'" alt="'+esc(part.name||label)+' 부품 사진" loading="lazy" decoding="async"><p class="live-product-image-status" data-product-image-status hidden>부품 사진을 불러오지 못했습니다</p></figure>':'<div class="public-bom-photo">정보 없음</div>')+'<div class="public-bom-specs">'+specs+'</div><div class="public-bom-role"><h5>이 부품의 역할</h5><p>'+esc(role)+'</p></div></div></details></td></tr>'+(open?buildRow():'');
  }).join('');
  const b=p.build,foot=b?footRow('기본 구성 PC 총액',money(b.base_price))+footRow('바꾼 구성 PC 총액',totalNow(p)+'<small class="muted foot-note">바꾼 부품 '+b.changes.length+'개 · 변경 후 총액을 한 대 기준으로 표시해요.</small>','mp-total-row')
    :footRow('기본 구성 PC 총액',money(p.price),'mp-total-row');
  return '<section class="final-parts public-bom"><h3>부품 구성과 선택 이유</h3><div class="final-table-wrap"><table class="final-table"><colgroup><col class="part-description-col"><col class="part-price-col"><col class="part-action-col"></colgroup>'+
    '<thead><tr><th scope="col">부품 · 등록 사양</th><th scope="col">기본 구성 / 변경 차액</th><th scope="col">'+(finalOnly?'<span class="sr-only">변경</span>':'변경')+'</th></tr></thead><tbody>'+rows+'</tbody><tfoot>'+foot+'</tfoot></table></div><p class="mp-info-line">표시 금액은 PC 한 대의 구성 금액이에요. 실제 구매 금액과 포함 품목은 구매 전에 확인해 주세요.</p></section>'+
    (finalOnly?'<details class="public-bom-information" data-detail="spec"><summary>'+(canSwapHere(p)?'추천 근거·변경 안내 펼치기':'추천 근거 펼치기')+'</summary><div class="final-part-expanded">'+information+'</div></details>':information);
}
// 부품 종류별 이름 · 아이콘 · 역할 문장(상세 v2 와 최종 견적이 함께 쓴다).
const BOM_ROLES={
    CPU:['CPU','cpu','프로그램의 명령을 계산하고 처리하는 부품이에요.'],
    GPU:['그래픽카드','graphics-card','게임 화면과 그림을 출력하는 부품이에요.'],
    RAM:['메모리','memory','실행 중인 프로그램의 정보를 잠시 담아두는 부품이에요.'],
    SSD:['저장장치','hard-drive','게임과 파일을 저장하는 부품이에요.'],
    HDD:['저장장치','hard-drive','게임과 파일을 저장하는 부품이에요.'],
    MB:['메인보드','gear','CPU와 메모리 등 여러 부품을 연결하는 부품이에요.'],
    PSU:['파워','plug','각 부품에 전원을 공급하는 부품이에요.'],
    POWER:['파워','plug','각 부품에 전원을 공급하는 부품이에요.'],
    COOLER:['쿨러','gear','CPU에서 나는 열을 식히는 부품이에요.'],
    CASE:['케이스','computer-tower','부품을 담고 공기가 흐를 공간을 만드는 부품이에요.']};
// 부품 직접 바꾸기(api/mvp3_build): 공개된 구성표의 줄마다 「변경」. 호환 규칙을 통과한 판매 부품만,
// 금액은 서버가 다시 계산한 값만 쓴다(화면이 더하지 않는다). 가상 줄(조립비 등)은 바꾸지 않는다.
function changeButton(part,label,finalOnly,open,id){
  if(finalOnly)return '';
  if(part.pseudo)return button('변경','unavailable','outline small','disabled aria-describedby="'+id+'"');
  return button('변경','build-options','outline small'+(open?' is-active':''),'data-ordinal="'+part.ordinal+'" aria-expanded="'+open+'" aria-label="'+esc(label)+' 바꾸기"'+(state.phase?' disabled':''));
}
// 부품 줄에는 금액을 쓰지 않는다(2026-10-15 사장님 결정): 기본 구성이면 「기본 구성」, 바꾼 줄은 서버 차액만.
// 그래픽카드 자리의 서비스 줄 = 판매 구성에 별도 그래픽카드가 없다는 뜻(CPU 내장 그래픽으로 출력 — api/build_check.py
// 「CPU 내장 그래픽 사용」과 같은 판정).
function pseudoPart(part){
  if(part.pseudo&&part.slot==='GPU')return {name:'별도 그래픽카드 없음',description:'CPU 내장 그래픽으로 화면을 출력하는 구성이에요.',price:'별도 부품 없음'};
  return {};
}
// 수량이 2개 이상이면 줄 금액이 «단가 × 수량» 합계라는 것을 함께 적는다(2026-10-12 코덱스 24조합 검수 6번:
// 메모리 수량 2 줄의 319,000원이 단가인지 줄 합계인지 알 수 없었다).
function partLinePrice(part){
  if(pseudoPart(part).price)return pseudoPart(part).price;
  return '<span class="mp-base-label">기본 구성</span>';
}
// 총액 표시는 서버 값만: PC 총액 = p.price, 기본 구성 = build.base_price. 화면은 더하거나 빼지 않는다.
function totalNow(p){return Number.isSafeInteger(p.price)?money(p.price):'변경 후 총액 미확인';}
function totalMove(p){
  const b=p.build;if(!b)return '';
  return '기본 구성 '+(Number.isSafeInteger(b.base_price)?money(b.base_price):'총액 미확인')+' \u2192 바꾼 구성 '+totalNow(p);
}
// 합계 줄은 금액을 부품 줄과 같은 「금액」 열에 둔다(두 열을 합쳐 가운데 두면 금액 열과 어긋난다).
function footRow(label,value,cls){
  return '<tr'+(cls?' class="'+cls+'"':'')+'><th scope="row">'+label+'</th><td class="final-part-price">'+value+'</td><td aria-hidden="true"></td></tr>';
}
function buildChangedRow(part,label,icon,c,finalOnly,open){
  const id='bom-unavailable-'+part.ordinal;
  return '<tr data-part="bom-'+part.ordinal+'" class="build-changed"><td colspan="3"><details class="public-bom-disclosure" data-detail="bom-'+part.ordinal+'"><summary>'+
    '<div class="final-part-description">'+uiIcon(icon,'part-symbol')+'<div><h4><span>'+esc(label)+'</span><span class="part-name">'+esc(c.after.name)+'</span><span class="public-bom-quantity">수량 '+c.quantity+'</span></h4>'+
    '<p class="build-changed-note"><span class="mp-changed-badge">변경됨</span> 기본 구성: '+esc(c.before.name)+'</p>'+
    '<span class="public-bom-toggle"><span class="when-closed">상세 펼치기</span><span class="when-open">상세 접기</span>'+uiIcon('caret-down')+'</span></div></div>'+
    '<span class="final-part-price">'+diffHtml(c.delta)+'</span><span class="final-part-change">'+changeButton(part,label,finalOnly,open,id)+'</span></summary><div class="final-part-expanded public-bom-expanded">'+
    '<p id="'+id+'">바꾼 부품의 설명과 사진은 아직 준비되지 않았어요.'+(finalOnly?'':' 「변경」에서 다른 부품을 고르거나 「원래 구성으로」로 되돌릴 수 있어요.')+'</p></div></details></td></tr>'+(open?buildRow():'');
}
function buildRow(){return '<tr class="build-options-row"><td colspan="3">'+buildPanel()+'</td></tr>';}
function buildPanel(){
  const q=state.build,d=q?.data;if(!q||q.ordinal===null)return '';
  const head='<div class="part-options-head"><h4>'+esc(d?.label||'부품')+' 바꾸기'+(d?.current?' · 지금 '+esc(d.current.name):'')+'</h4>'+button('닫기','build-close','text-button')+'</div>';
  if(state.phase==='build')return '<div class="part-options" role="status">'+head+'<p class="muted">'+(d?'바꾼 구성의 호환과 금액을 다시 확인하는 중이에요.':'이 PC에 맞는 판매 부품을 찾는 중이에요.')+'</p></div>';
  if(q.error)return '<div class="part-options" role="alert">'+head+'<p class="warn-text">'+esc(q.error)+'</p>'+button('다시 찾기','build-options','outline small','data-ordinal="'+q.ordinal+'" data-retry="1"')+'</div>';
  if(!d)return '';
  // 쿨러 미확인 경고는 서버 안내(note)가 한 문장으로 품는다 — 「모두 통과」와 경고를 따로 나란히 두지 않는다.
  const warned=(d.warnings||[]).length>0,untested=d.untested?'<p class="muted">사양 정보가 모자라 호환을 확인하지 못한 부품 '+d.untested+'개는 빼고 보여 드려요.</p>':'';
  if(!d.options.length)return '<div class="part-options" role="status">'+head+quantityBlock(d)+'<p>지금 이 PC에 맞는 다른 판매 부품이 없어요.</p>'+untested+'</div>';
  return '<div class="part-options">'+head+quantityBlock(d)+'<p class="'+(warned?'warn-text':'muted')+'">'+esc(d.note||(warned?d.warnings.join(' '):'호환 규칙을 통과한 판매 중 부품만 보여 드려요.'))+'</p><p class="muted mp-candidate-head">기본 부품 대비 차액</p>'+untested+'<ul class="part-option-list">'+
    d.options.map(o=>'<li class="part-option" data-build-option="'+o.product_code+'"><div class="part-option-copy"><strong>'+esc(o.name)+'</strong>'+(hasDiff(o.price_diff)?'':'<span class="part-option-name">가격을 확인한 뒤 선택할 수 있어요.</span>')+'</div>'+
      '<div class="part-option-price">'+diffHtml(o.price_diff)+
      (hasDiff(o.price_diff)?button('이걸로 바꾸기','build-pick','primary small','data-code="'+o.product_code+'"'+(state.phase?' disabled':'')):'<span class="mp-hold">선택 보류</span>')+'</div></li>').join('')+'</ul><p class="muted mp-candidate-note">차액은 기본 구성의 부품과 비교한 금액이에요. 확인한 차액이 없는 후보는 선택할 수 없어요.</p></div>';
}
// 메모리·저장장치 수량(api/mvp3_quantity). 범위·근거는 서버가 준 것만 쓴다(2026-10-12 중헌 님 7번).
// 메인보드 정보를 모르면(known=false) 늘리는 단추를 잠그고 그 이유를 그대로 보여 준다. 줄이는 것은 1개까지 된다.
function stepper(action,attr,n,min,max,unit,label){
  const dis=state.phase?' disabled':'';
  return '<span class="qty-stepper" role="group" aria-label="'+esc(label)+'">'+
    button('−',action,'outline small',attr+'="'+(n-1)+'" aria-label="'+esc(label)+' 줄이기"'+(n<=min?' disabled':dis))+
    '<strong aria-live="polite">'+n+unit+'</strong>'+
    button('+',action,'outline small',attr+'="'+(n+1)+'" aria-label="'+esc(label)+' 늘리기"'+(n>=max?' disabled':dis))+'</span>';
}
function quantityBlock(d){
  const q=d?.quantity;if(!q)return '';
  return '<div class="part-qty" data-part-qty><span>수량</span>'+stepper('build-qty','data-qty',q.current,q.min,q.max,'개',(d.label||'부품')+' 수량')+
    '<p class="'+(q.known?'muted':'warn-text')+'">'+esc(q.basis)+(q.known?' '+q.max+'개까지 고를 수 있어요.':'')+'</p></div>';
}
// 같은 구성 여러 대(2026-10-12 중헌 님 7번). 금액은 한 대 값(서버)이고 합계는 그 값 × 대수다. 보관·쇼핑몰 연결은 서버가 다시 곱한다.
function setsBlock(p){
  const n=p.sets||1,edit=state.screen==='detail'&&!state.savedQuote;
  if(!edit&&n===1)return '';
  return '<div class="final-sets" data-sets><span>같은 구성 대수</span>'+(edit?stepper('sets','data-sets',n,1,10,'대','같은 구성 대수'):'<strong>'+n+'대</strong>')+
    '<p class="muted">'+(n>1&&Number.isSafeInteger(p.price)?n+'대 합계 '+money(p.price*n)+' · 한 대 '+money(p.price)+'. ':'')+'금액은 한 대 기준이고, 저장과 쇼핑몰 연결에 대수를 함께 넘겨요.</p></div>';
}
// 부품 바꾸기(api/mvp3_part_options): 고른 판매 PC 에서 그 부품만 다른 판매 PC 를 고른다.
// 금액·차액·함께 바뀌는 것은 서버가 준 값만 쓴다. 상품 상세에서만 바꾼다(최종 견적은 안내만).
// ===== 쇼핑몰 PC 는 우리 화면에서 부품을 바꾸지 않는다 (2026-10-16 사장님 결정) =====
// 쇼핑몰 상품 페이지(mall_url)가 있는 PC = 쇼핑몰에서 파는 구성 그대로다. 「변경」을 누르면 팝콘PC 로 옮길지 묻고, 상품 페이지를 새 탭으로 연다.
// 페이지 주소는 서버가 상품에 실어 준 mall_url(없으면 쇼핑몰 연결 응답의 주소)만 쓰고, 부품 선택용 매개변수를 지어내지 않는다.
// 부품 바꾸기 구현(openBuild·선택 패널)은 지우지 않았다 -- 팝콘AI 가 직접 구성한 상품(쇼핑몰 페이지 없음)은 그대로 바꿀 수 있다.
function mallUrlOf(p){
  const own=M.safeUrl(p?.mall_url);if(own)return own;
  const h=state.handoff,q=state.savedQuote;
  return h&&q&&p===state.selected&&h.quote_id===q.id?M.safeUrl(h.mall_url):null;
}
// 팝콘AI 가 직접 구성한 상품(서버가 ai_composed 로 확인해 준 것)만 우리 화면에서 부품을 바꾼다. 쇼핑몰 상품이 주소만 없다고 AI 구성으로 바꾸지 않는다 --
// 주소가 없으면 「연결할 수 없음」으로 안내한다(2026-10-16 두 구매 흐름 기준).
function canSwapHere(p){return p?.ai_composed===true;}
let mallDlg=null,mallDirect=false;
function closeMallDialog(){
  if(state.mall.step==='moving')return;
  const had=mallDlg;flow.closeMall();mallDirect=false;     // 상태를 비우면 syncMallDialog 가 창을 지운다 -- 아래는 초점만 돌려준다
  if(!had)return;
  const {opener,ordinal}=had;let target=opener&&opener.isConnected?opener:null;
  if(!target&&ordinal!==undefined)target=[...document.querySelectorAll('[data-action=build-options]')].find(e=>e.dataset.ordinal===ordinal);
  (target||document.querySelector('[data-action=mall-view]'))?.focus({preventScroll:true});
}
function mallDlgKey(e){
  if(!mallDlg?.el)return;
  if(e.key==='Escape'){e.preventDefault();e.stopPropagation();closeMallDialog();return;}
  if(e.key!=='Tab')return;
  const items=[...mallDlg.el.querySelectorAll('a[href],button:not([disabled])')];if(!items.length)return;
  const first=items[0],last=items[items.length-1],now=document.activeElement;
  if(!mallDlg.el.contains(now)){e.preventDefault();first.focus();}
  else if(e.shiftKey&&now===first){e.preventDefault();last.focus();}
  else if(!e.shiftKey&&now===last){e.preventDefault();first.focus();}
}
// 「변경」을 누르면 이 창을 연다(팝콘PC 로 이동 안내). 문구 정본: 대표 전달 「화면별-문구-정본.csv」(승인 시안 02).
// 연결 실패·주소 확인 필요는 창이 아니라 오른쪽 요약 칸 안에서 말한다(승인 시안 12·13).
function openMallDialog(opener){
  if(state.mall.open){if(state.mall.step==='moving')return;flow.closeMall();}
  mallDirect=false;mallDlg={opener,ordinal:opener?.dataset?.ordinal};flow.openMall();
}
// 오른쪽 요약 칸의 「팝콘PC에서 상품 보기」(승인 시안 01): 안내창 없이 바로 이동한다.
function mallView(){
  if(state.phase||state.mall.step==='moving'||!mallLinkable(state.selected))return;
  if(state.mall.open)flow.closeMall();
  mallDirect=true;mallDlg=null;void window.MVP3LiveFlow.moveToMall(flow,window);
}
function mallLinkable(p){return !!mallUrlOf(p)||!!(state.savedQuote&&state.savedQuote.product?.product_code===p?.product_code);}
function mallDialogShown(){const m=state.mall;return m.open&&(m.step==='ask'||(m.step==='moving'&&!mallDirect));}
function mallDialogHtml(){
  const m=state.mall,url=mallLinkable(state.selected);
  const card=(title,inner)=>'<div class="mall-dlg-card" role="dialog" aria-modal="true" aria-labelledby="mall-dlg-title"><button type="button" class="mall-dlg-x" data-action="mall-dialog-close" aria-label="안내 닫기"'+(m.step==='moving'?' disabled':'')+'><span aria-hidden="true">×</span></button><h3 id="mall-dlg-title" tabindex="-1">'+title+'</h3>'+inner+'</div>';
  // 주소를 모르는 상품 -- 이동도 인계 기록도 만들지 않는다.
  if(m.step==='ask'&&!url)
    return card('상품 페이지를 확인하고 있어요.','<p id="mall-dlg-desc" data-mall-state="no-url">지금은 연결할 수 없어요. 상품 주소를 확인한 뒤 다시 안내해 드릴게요.</p><div class="mall-dlg-actions"><button type="button" class="outline" data-action="mall-dialog-close">닫기</button></div>');
  const busy=m.step==='moving';
  return card('팝콘PC에서 부품을<br>변경해 주세요','<p id="mall-dlg-desc">이 상품의 부품은 팝콘PC 상품 페이지에서 옵션으로 바꿀 수 있어요.</p><p>선택한 옵션에 따라 금액이 달라져요.<br>팝콘PC로 이동할까요?</p>'+
    '<div class="mall-dlg-actions"><button type="button" class="primary" data-action="mall-move"'+(busy?' disabled':'')+'>'+(busy?'이동하는 중…':'팝콘PC로 이동 <span aria-hidden="true">↗</span>')+'</button>'+
    '<button type="button" class="outline" data-action="mall-dialog-close"'+(busy?' disabled':'')+'>취소</button></div>');
}
// 화면을 그릴 때마다 부른다. 안내창은 상태(state.mall)가 말하는 대로만 그린다.
function syncMallDialog(){
  const m=state.mall;
  if(!mallDialogShown()){if(mallDlg?.el){mallDlg.el.remove();document.removeEventListener('keydown',mallDlgKey,true);mallDlg.el=null;}return;}
  mallDlg=mallDlg||{};
  const key=m.step+'|'+m.blocked+'|'+(m.error||'')+'|'+(state.handoff?.handoff_no||'');
  if(mallDlg.el&&mallDlg.key===key)return;
  const fresh=!mallDlg.el;
  if(fresh){
    const el=document.createElement('div');el.className='mall-dlg';el.dataset.mallDialog='';
    el.addEventListener('click',e=>{if(e.target===el)closeMallDialog();});
    mallDlg.el=el;document.body.append(el);document.addEventListener('keydown',mallDlgKey,true);
  }
  mallDlg.key=key;mallDlg.el.innerHTML=mallDialogHtml();
  mallDlg.el.querySelector('#mall-dlg-title').focus({preventScroll:true});
}
const SWAP_OF={CPU:'cpu',GPU:'gpu',RAM:'ram',SSD:'ssd'};
const SWAP_BUTTONS=[['cpu','CPU','cpu'],['gpu','그래픽카드','graphics-card'],['ram','메모리','memory'],['ssd','저장장치','hard-drive']];
// 부품을 바꿀 때의 금액은 «기본 부품 대비 차액»만 말한다(2026-10-15 사장님 「몰처럼 PC 금액만」). 서버가 준 차액만 쓰고,
// 없으면(null·정수 아님) 0 으로 바꾸지 않고 「차액 확인 필요」로 둔다.
function hasDiff(d){return Number.isSafeInteger(d);}
function diffText(d){
  if(!hasDiff(d))return '차액 확인 필요';
  return d===0?'추가 금액 없음':(d>0?'+':'\u2212')+Math.abs(d).toLocaleString('ko-KR')+'원';
}
function diffHtml(d){
  const sign=hasDiff(d)&&d!==0?'<small class="mp-diff-tag">'+(d>0?'추가':'감소')+'</small>':'';
  return '<span class="mp-diff'+(hasDiff(d)?(d>0?' is-plus':d<0?' is-minus':' is-zero'):' is-missing')+'">'+diffText(d)+'</span>'+sign;
}
function partOptionsPanel(){
  const q=state.parts;if(!q?.slot)return '';
  const name=(SWAP_BUTTONS.find(x=>x[0]===q.slot)||[])[1]||q.slot;
  const head='<div class="part-options-head"><h4>'+esc(name)+' 바꾸기'+(q.data?.current?' · 지금 '+esc(q.data.current):'')+'</h4>'+button('닫기','part-close','text-button')+'</div>';
  if(state.phase==='parts')return '<div class="part-options" role="status">'+head+'<p class="muted">판매 중인 PC에서 선택지를 찾는 중이에요.</p></div>';
  if(q.error)return '<div class="part-options" role="alert">'+head+'<p class="warn-text">'+esc(q.error)+'</p>'+button('다시 찾기','part-options','outline small','data-slot="'+q.slot+'"')+'</div>';
  if(!q.data)return '';
  if(!q.data.options.length)return '<div class="part-options" role="status">'+head+'<p>지금 판매 중인 PC 중에는 '+esc(name)+'만 다른 구성이 없어요. 원하는 조건을 상담창에 말씀해 주시면 다시 찾아 드려요.</p></div>';
  return '<div class="part-options">'+head+'<p class="muted">몰에서 조립해 파는 PC 중 '+esc(name)+'만 다른 것을 보여 드려요. 호환이 확인된 구성이에요.</p><p class="muted mp-candidate-head">기본 부품 대비 차액</p><ul class="part-option-list">'+
    q.data.options.map(o=>'<li class="part-option" data-part-option="'+o.product_code+'"><div class="part-option-copy"><strong>'+esc(o.swap.value)+'</strong><span class="part-option-name">'+esc(o.name)+'</span>'+
      o.swap.also.map(x=>'<span class="part-option-also">'+esc(x.label)+'도 함께 바뀌어요: '+esc(x.from)+'에서 '+esc(x.to)+'로</span>').join('')+
      (o.over_budget?'<span class="warn-text">예산을 넘어요</span>':'')+'</div><div class="part-option-price">'+diffHtml(o.swap.price_diff)+
      (hasDiff(o.swap.price_diff)?button('이걸로 바꾸기','part-swap','primary small','data-code="'+o.product_code+'"'+(state.phase?' disabled':'')):'<span class="mp-hold">선택 보류</span>')+'</div></li>').join('')+'</ul><p class="muted mp-candidate-note">차액은 기본 구성의 부품과 비교한 금액이에요. 확인한 차액이 없는 후보는 선택할 수 없어요.</p></div>';
}
function partChange(finalOnly,configured){
  return partChangeBody(finalOnly,configured).replace('</h3>','</h3>'+setsBlock(state.selected));
}
function partChangeBody(finalOnly,configured){
  // 쇼핑몰 상품 페이지가 있는 PC 는 여기서 부품을 바꾸지 않는다 -- 팝콘PC 상품 페이지에서 바꾸게 안내한다(2026-10-16 사장님).
  if(!canSwapHere(state.selected)){
    if(finalOnly)return '';
    return '<section class="live-capabilities" id="part-change"><h3>부품 변경</h3><p>쇼핑몰에서 파는 구성 그대로 보여 드려요. 부품을 바꾸려면 팝콘PC 상품 페이지에서 이 PC를 기준으로 변경해 주세요.</p>'+button('팝콘PC에서 부품 변경하기','mall-change','outline small')+'</section>';
  }
  if(configured){
    const p=state.selected,b=p.build;
    return '<section class="live-capabilities" id="part-change"><h3>부품 바꾸기</h3><p>'+(finalOnly?'부품은 「상품 상세 다시 보기」에서 바꿀 수 있어요.':'부품 구성 표의 「변경」을 누르면 이 PC에 맞는 판매 부품을 보여 드려요. 호환 규칙을 통과한 부품만 나오고, 후보에는 기본 부품 대비 차액만 보여 드려요. 확인한 차액이 없는 후보는 선택할 수 없어요.')+'</p>'+
      (b?'<p>바꾼 부품 '+b.changes.length+'개 · '+esc(totalMove(p))+'</p>'+(finalOnly?'':button('원래 구성으로','build-reset','outline small',state.phase?'disabled':'')):'')+'</section>';
  }
  if(finalOnly)return '<section class="live-capabilities" id="part-change"><h3>부품 바꾸기</h3><p>CPU·그래픽카드·메모리·저장장치는 「상품 상세 다시 보기」에서 바꿀 수 있어요. 바꾸면 그 구성으로 판매 중인 PC로 옮기고, 견적을 다시 보관해요.</p></section>';
  return '<section class="live-capabilities" id="part-change"><h3>부품 바꾸기</h3><p>바꾸고 싶은 부품을 고르세요. 그 부품만 다른 판매 중인 PC를 찾아 드려요. 게임 FPS 비교 자료는 아직 제공되지 않아요.</p><div>'+
    SWAP_BUTTONS.map(([slot,label,icon])=>button(uiIcon(icon)+label+' 바꾸기','part-options','outline small'+(state.parts?.slot===slot?' is-active':''),'data-slot="'+slot+'" aria-expanded="'+(state.parts?.slot===slot)+'"'+(state.phase?' disabled':''))).join('')+'</div>'+partOptionsPanel()+'</section>';
}
// 추천 이유·게임 안내. 상세(추천 구성 상세)에서는 오른쪽 열로, 최종 견적에서는 접힌 칸 안으로 간다.
function selectedGameContext(p){
  // Read only the selected recommendation group; saved/recovery records have no game-context contract.
  const context=state.savedQuote||state.pendingSave?null:(state.selectedContext||(state.groups||[]).find(g=>Number.isInteger(p.index)&&g.products.some(item=>item.index===p.index&&item.product_code===p.product_code)));
  return context?.game_context||null;
}
function gameContextHtml(p){
  const ctx=selectedGameContext(p),url=M.safeUrl(ctx?.source.url);
  const gameLabels=[['spec_summary','게임 사양 안내'],['why_this_pc','PC 선택 안내'],['upgrade_hint','업그레이드 안내'],['caution','확인할 내용']];
  return ctx?'<section class="live-explanation"><h3>게임 안내 · '+esc(ctx.game_name)+'</h3><ul>'+gameLabels.filter(([key])=>ctx[key]).map(([key,label])=>'<li><strong>'+label+': </strong>'+esc(ctx[key])+'</li>').join('')+'</ul>'+(url?'<p class="muted"><a href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">자세히 보기</a></p>':'')+'</section>':'';
}
function detailReason(p,bare=false){
  return '<section class="live-explanation">'+(bare?'':'<h3>이 상품을 추천한 이유</h3>'+
    '<p class="muted">상담 조건: '+M.conditions(state.selectionState||state.talk).map(esc).join(' · ')+'</p>')+
    (p.reasons.length?'<ul>'+p.reasons.map(r=>'<li>'+esc(r)+'</li>').join(''):'<p>추천 이유가 제공되지 않았어요.</p>')+'</section>'+gameContextHtml(p);
}
// split: 추천 구성 상세의 두 열 배치(2026-10-15 코덱스 디자인 v1). 왼쪽 열에는 구성만 두고, 추천 이유·부품 바꾸기는 renderDetail 이 따로 놓는다.
function productDetails(finalOnly=false,split=false){
  const p=state.selected;
  const rows=M.changedSpecRows(M.specRows(p.spec),p.build),spec=rows.length?'<dl class="live-spec-grid">'+rows.map(([label,value])=>'<div><dt>'+esc(label)+'</dt><dd>'+esc(value)+'</dd></div>').join('')+'</dl>':'<p class="live-full-spec">'+esc(M.specText(p.spec)||'등록된 상세 사양을 확인하지 못했어요.')+'</p>';
  const information=split?'':detailReason(p)+partChange(finalOnly,!!M.publicConfiguration(p.public_configuration,p.product_code));
  const configuration=M.publicConfiguration(p.public_configuration,p.product_code);
  if(configuration)return publicBomDetails(configuration,p,information,finalOnly);
  // 부품별 구성표가 없는 상품도 카드에 보인 사양(CPU·GPU·램·저장장치·케이스·파워)은 상세에서 바로 보이게 한다 -- 완제품 한 줄만
  // 나와 카드와 상세가 다른 상품처럼 읽혔다(코덱스 24조합 검수 4번, 사무용100 8600G 상품).
  const cardRows=M.cardSpecRows(p.spec),cardGrid=cardRows.length?'<dl class="live-spec-grid" data-card-spec>'+cardRows.map(([label,value])=>'<div><dt>'+esc(label)+'</dt><dd>'+esc(value)+'</dd></div>').join('')+'</dl>':'';
  return '<section class="final-parts"><h3>부품 구성과 선택 이유</h3><p class="public-bom-empty" role="status">부품 구성 정보는 아직 연결되지 않았어요. 이 상품은 부품별 구성표와 부품 가격이 등록되지 않아'+(cardGrid?', 추천 카드와 같은 등록 사양을 먼저 보여 드려요.':' 등록된 완제품 사양을 먼저 확인해주세요.')+'</p>'+cardGrid+'<div class="final-table-wrap"><table class="final-table"><colgroup><col class="part-description-col"><col class="part-price-col"><col class="part-action-col"></colgroup>'+
    '<thead><tr><th scope="col">상품 · 등록 사양</th><th scope="col">금액</th><th scope="col">변경</th></tr></thead><tbody><tr data-part="pc"><td><div class="final-part-description">'+uiIcon('computer-tower','part-symbol')+
    '<div><h4><span>조립완제PC</span><span class="part-name">'+esc(p.name)+'</span></h4><p>등록된 판매 상품의 구성입니다.</p><details data-detail="spec"><summary><span class="when-closed">'+(finalOnly?'상세 사양·추천 근거·변경 안내 펼치기':'상세 사양 펼치기')+'</span><span class="when-open">'+(finalOnly?'상세 사양·추천 근거·변경 안내 접기':'상세 사양 접기')+'</span>'+uiIcon('caret-down')+'</summary><div class="final-part-expanded">'+spec+(finalOnly?information:'')+'</div></details></div></div></td><td class="final-part-price">'+money(p.price)+'</td><td class="final-part-change"><span aria-label="부품 변경 미지원">-</span></td></tr></tbody>'+
    '<tfoot><tr><th scope="row">상품 참고 금액</th><td colspan="2">'+money(p.price)+'</td></tr></tfoot></table></div></section>'+(finalOnly?'':information);
}
function condRows(){
  return [['gear','호환성','실제 조립 검수 결과는 확인되지 않았어요.'],['tag','가격',state.savedQuote?'보관 시점 참고 금액 \u00b7 확정가 아님':state.selected.price_src||'가격 기준 미확인'],
    ['package','재고','주문 전 팝콘PC에서 확인'],['squares-four','운영체제','팝콘PC 상품 페이지에서 포함 여부 확인'],
    ['monitor','키보드 \u00b7 마우스 \u00b7 모니터','팝콘PC 상품 페이지에서 포함 여부 확인'],['shield','보증','팝콘PC 상품 페이지에서 보증 안내 확인']];
}
function finalConditions(){
  const row=([name,label,text])=>'<div>'+uiIcon(name)+'<dt>'+label+'</dt><dd>'+esc(text)+'</dd></div>',r=condRows();
  return '<section class="final-conditions"><h3>구매 전 확인할 내용</h3><div class="final-conditions-grid"><dl>'+
    r.slice(0,3).map(row).join('')+'</dl><dl>'+r.slice(3).map(row).join('')+'</dl></div></section>';
}
// ===== 고객 상세 v2 (2026-10-16 코덱스 통합안 v2 -- 선택한 부품 표 + 오른쪽 요약, 「변경」은 옆 패널) =====
// 금액은 서버 값만 쓴다: 총액 = p.price, 기본 구성 = build.base_price, 줄·후보 차액 = 서버가 준 delta / price_diff.
// 단품 가격·부품 합계·조립 기타 줄은 두지 않는다(2026-10-15 사장님 결정). 고르는 중인 후보(dv2.temp)는 임시 선택이라
// 적용(build-apply -> flow.pickBuild)이 성공하기 전에는 본문·변경 개수·총액을 바꾸지 않는다.
const mob768=matchMedia('(max-width:768px)');
const dv2={hist:false,skipPop:false,temp:null,applied:null,panelFor:null,open:{},focusHandled:false};
const DV2_LABEL={CPU:'CPU',GPU:'그래픽',RAM:'메모리',SSD:'SSD',HDD:'HDD',MB:'메인보드',PSU:'파워',POWER:'파워',COOLER:'쿨러',CASE:'케이스'};
function dv2OpenAttr(key,def){return (Object.hasOwn(dv2.open,key)?dv2.open[key]:def)?' open':'';}
function dv2Label(part){return (Object.hasOwn(DV2_LABEL,part.slot)?DV2_LABEL[part.slot]:null)||(Object.hasOwn(BOM_ROLES,part.slot)?BOM_ROLES[part.slot][0]:part.pseudo?'서비스':part.slot);}
// 바꾼 구성이 기본 구성보다 얼마나 다른가 = 서버 총액 − 서버 기본 구성(둘 다 서버 값일 때만).
function dv2Move(p){const b=p.build;return b&&Number.isSafeInteger(b.base_price)&&Number.isSafeInteger(p.price)?p.price-b.base_price:null;}
function dv2MoveText(d){
  if(!Number.isSafeInteger(d))return '확인 필요';
  return d===0?'기본 구성과 같아요':'기본 구성보다 '+Math.abs(d).toLocaleString('ko-KR')+'원 '+(d>0?'추가':'감소');
}
function dv2Diff(d){return '<span class="mp-diff'+(hasDiff(d)?(d>0?' is-plus':d<0?' is-minus':' is-zero'):' is-missing')+'">'+diffText(d)+'</span>';}
function dv2ChangeList(p){
  const b=p.build;if(!b)return '';
  const ram=M.systemRamGb(b);
  return '<ul class="dv2-change-list">'+b.changes.map(c=>'<li><span>'+esc(c.label)+' 변경</span>'+dv2Diff(c.delta)+'</li>').join('')+'</ul>'+(ram?'<p class="muted" data-changed-parts>바꾼 구성의 시스템 메모리는 총 '+ram+'GB예요.</p>':'');
}
function dv2Row(part,p){
  const [,icon,role]=(Object.hasOwn(BOM_ROLES,part.slot)?BOM_ROLES[part.slot]:null)||[part.slot,'gear','등록된 사양과 설명을 확인해주세요.'];
  const label=dv2Label(part),id='bom-unavailable-'+part.ordinal,shown=pseudoPart(part);
  const swappable=canSwapHere(p),change=p.build?.changes.find(c=>c.ordinal===part.ordinal),editing=swappable&&state.build?.ordinal===part.ordinal;
  const name=change?change.after.name:(shown.name||part.name||'정보 없음'),qty=change?change.quantity:part.quantity;
  const integrated=part.pseudo&&part.slot==='GPU',desc=String(shown.description||part.description||'정보 없음').trim();
  const action=part.pseudo?'<span class="dv2-na">'+(integrated?'내장 그래픽':'변경 불가')+'</span>'
    :button('변경','build-options','outline small'+(editing?' is-active':''),'data-ordinal="'+part.ordinal+'" aria-expanded="'+editing+'" aria-label="'+esc(label)+' 변경"'+(state.phase?' disabled':''));
  const chg=change?'<span class="mp-changed-badge">변경됨</span> '+dv2Diff(change.delta)+(swappable?'<br>'+button('기본 부품으로','build-undo','dv2-link','data-ordinal="'+part.ordinal+'" aria-label="'+esc(label)+' 기본 부품으로"'+(state.phase?' disabled':''))+'':''):'';
  const specs=part.specs.length?'<dl class="live-spec-grid">'+part.specs.map(x=>'<div><dt>'+esc(x.label)+'</dt><dd>'+esc(x.value.trim()||'정보 없음')+'</dd></div>').join('')+'</dl>':'<p>정보 없음</p>';
  const photo=!change&&part.photo?.state==='approved'?'<figure class="public-bom-photo" data-product-photo><img data-product-image src="'+esc(part.photo.url)+'" alt="'+esc(part.name||label)+' 부품 사진" loading="lazy" decoding="async"><p class="live-product-image-status" data-product-image-status hidden>부품 사진을 불러오지 못했습니다</p></figure>':'<div class="public-bom-photo">정보 없음</div>';
  const body=change?'<div class="public-bom-specs"><p>기본 구성: '+esc(change.before.name)+'</p></div><div class="public-bom-role"><p id="'+id+'">바꾼 부품의 설명과 사진은 아직 준비되지 않았어요.'+(swappable?' 「변경」에서 다른 부품을 고르거나 「기본 부품으로」로 되돌릴 수 있어요.':'')+'</p></div>'
    :'<div class="public-bom-specs">'+specs+'</div><div class="public-bom-role"><h5>이 부품의 역할</h5><p>'+esc(role)+'</p>'+(desc&&desc!==role?'<p>'+esc(desc)+'</p>':'')+'</div>';
  return '<tr data-part="bom-'+part.ordinal+'" class="dv2-row'+(change?' build-changed':'')+(editing?' is-editing':'')+'"><td colspan="3"><details class="dv2-details" data-detail="bom-'+part.ordinal+'"><summary>'+
    '<h4 class="dv2-cat">'+uiIcon(icon,'part-symbol')+'<span>'+esc(label)+'</span></h4>'+
    '<span class="dv2-model"><span class="part-name">'+esc(name)+'</span>'+(qty>1?' <span class="public-bom-quantity">수량 '+qty+'</span>':'')+(part.assembly_only?'<span class="mp-assembly">조립 전용</span>':'')+'</span>'+
    '<span class="dv2-chg">'+chg+'</span>'+
    '<span class="dv2-more">상세 정보'+uiIcon('caret-down')+'</span><span class="dv2-act">'+action+'</span></summary><div class="final-part-expanded public-bom-expanded">'+photo+body+'</div></details></td></tr>';
}
// 후보 목록: 기본 부품 · (바꾼 줄이면) 지금 적용된 부품 · 서버 후보. 차액은 모두 «기본 부품 대비».
// 서버 후보의 price_diff 는 지금 적용된 부품 대비이므로, 이 줄이 바뀐 상태면 같은 줄의 서버 변경 차액(delta)을 더해 기본 부품 대비로 옮긴다
// (둘 다 서버 값일 때만 -- 하나라도 없으면 null = 「차액 확인 필요」로 두고 0 으로 바꾸지 않는다).
function dv2Candidates(p,q){
  const d=q.data,c=p.build?.changes.find(x=>x.ordinal===q.ordinal);
  const baseCode=c?c.before.product_code:d.current?.product_code,baseName=c?c.before.name:d.current?.name;
  const applied=c?c.after.product_code:d.current?.product_code;
  const rows=[];
  if(Number.isSafeInteger(baseCode))rows.push({code:baseCode,base:true,name:baseName,diff:0});
  if(c)rows.push({code:applied,name:c.after.name,diff:Number.isSafeInteger(c.delta)?c.delta:null});
  for(const o of d.options){
    if(o.product_code===baseCode||o.product_code===applied)continue;
    const diff=!hasDiff(o.price_diff)?null:c?(Number.isSafeInteger(c.delta)?o.price_diff+c.delta:null):o.price_diff;
    rows.push({code:o.product_code,name:o.name,diff});
  }
  return {rows,applied,baseCode,changed:!!c};
}
function dv2Totals(p){
  const b=p.build,move=dv2Move(p);
  return '<div class="dv2-total-box"><div><strong>현재 적용된 구성</strong><small>1대 기준</small></div><strong class="dv2-total-num" data-dv2-total>'+money(p.price)+'</strong></div>'+
    '<dl class="dv2-sums"><div><dt>기본 구성</dt><dd>'+(b?money(b.base_price):money(p.price))+'</dd></div><div><dt>부품 변경 합계</dt><dd>'+(b?dv2Diff(move):'변경 없음')+'</dd></div></dl>';
}
function dv2Panel(p,labelOf){
  const q=state.build,d=q.data,label=labelOf(q.ordinal)||d?.label||'부품',busy=state.phase==='build';
  const modal=mob768.matches;
  const head='<div class="dv2-panel-head"><h3 id="dv2-panel-title" tabindex="-1">'+esc(label)+' 변경</h3>'+button('<span aria-hidden="true">×</span>','build-close','dv2-x','aria-label="'+esc(label)+' 변경 닫기"')+'</div>';
  const shell=inner=>'<div class="dv2-panel" role="dialog" aria-labelledby="dv2-panel-title"'+(modal?' aria-modal="true"':'')+'>'+head+inner+'</div>';
  if(!d){
    if(q.error)return shell('<p class="warn-text" role="alert">'+esc(q.error)+'</p><div class="dv2-actions">'+button('다시 찾기','build-options','outline','data-ordinal="'+q.ordinal+'" data-retry="1"')+button('취소','build-close','dv2-link')+'</div>');
    return shell('<p class="muted" role="status">이 PC에 맞는 판매 부품을 찾는 중이에요.</p><div class="dv2-actions">'+button('취소','build-close','dv2-link')+'</div>');
  }
  const {rows,applied,baseCode,changed}=dv2Candidates(p,q);
  dv2.applied=applied;
  if(dv2.temp==null||!rows.some(r=>r.code===dv2.temp))dv2.temp=applied;
  const warned=(d.warnings||[]).length>0;
  const list=rows.map(r=>{
    const known=hasDiff(r.diff)&&Number.isSafeInteger(r.code),picked=r.code===dv2.temp;
    return '<li class="dv2-cand'+(picked?' is-picked':'')+(known?'':' is-disabled')+'" data-build-option="'+r.code+'"><label><input type="radio" name="dv2-pick" data-dv2-radio value="'+r.code+'"'+(picked?' checked':'')+(known&&!state.phase?'':' disabled')+'>'+
      '<span class="dv2-cand-copy"><strong>'+(r.base?'기본 '+esc(label):esc(r.name))+'</strong>'+(r.base?'<span class="dv2-cand-model">'+esc(r.name)+'</span>':'')+(known?'':'<span class="dv2-cand-model">선택 불가</span>')+'</span>'+
      '<span class="dv2-cand-diff">'+dv2Diff(r.diff)+(r.code===applied?'<span class="dv2-current-tag">현재 선택</span>':'')+'</span></label></li>';
  }).join('');
  const untested=d.untested?'<p class="muted">사양 정보가 모자라 확인하지 못한 부품 '+d.untested+'개는 빼고 보여 드려요.</p>':'';
  const none=!d.options.length?'<p class="muted" role="status">지금 이 PC에 맞는 다른 판매 부품이 없어요.</p>':'';
  return shell('<p class="dv2-lead">사용할 부품을 골라 주세요.</p><p class="muted">기본 구성과 비교한 금액이에요.</p>'+
    (q.error?'<p class="warn-text" role="alert">'+esc(q.error)+'</p>':'')+(warned?'<p class="warn-text">'+esc(d.note||d.warnings.join(' '))+'</p>':'')+
    '<ul class="dv2-cands" role="radiogroup" aria-labelledby="dv2-panel-title">'+list+'</ul>'+none+untested+
    (changed?button('<span aria-hidden="true">↶</span> 기본 부품으로','build-pick-base','dv2-link dv2-base-link','data-code="'+baseCode+'"'+(state.phase?' disabled':'')):'')+quantityBlock(d)+
    dv2Totals(p)+'<p class="dv2-assembly muted">변경한 구성의 실제 조립 검수는 확인이 필요해요.</p>'+
    '<div class="dv2-actions">'+button(busy?'적용하는 중이에요':'선택한 부품 적용','build-apply','primary dv2-apply','data-dv2-apply'+(state.phase||dv2.temp===applied?' disabled':''))+button('취소','build-close','dv2-cancel')+'</div>'+
    '<p class="dv2-foot muted">적용 전에는 구성이 바뀌지 않아요.</p>');
}
function dv2SelectTemp(code){
  dv2.temp=code;
  for(const li of view.querySelectorAll('.dv2-cand')){const on=Number(li.dataset.buildOption)===code;li.classList.toggle('is-picked',on);const r=li.querySelector('input');if(r)r.checked=on;}
  const apply=view.querySelector('[data-dv2-apply]');if(apply)apply.disabled=!!state.phase||code===dv2.applied;
}
function dv2Inert(on){
  for(const el of [document.querySelector('.topbar'),document.querySelector('.chat'),actions,view.querySelector('.dv2-head'),view.querySelector('.dv2-main')])if(el)el.inert=on;
}
// ===== 두 구매 흐름 · 승인 시안 그대로 (2026-10-16 코덱스 독립 재검수 P2-1) =====
// 상품 화면(상세·보관·보관 완료·상담·접수)은 왼쪽 상담창 없이 한 열로 그린다. 위 머리띠는 「상담으로 돌아가기」와 「내 견적」만.
// 완제품(팝콘PC 판매 상품)과 팝콘AI 맞춤 구성은 서버가 확인한 ai_composed 로만 나눈다(canSwapHere).
// 문구 정본: 대표 전달 「화면별-문구-정본.csv」 · 화면 PC1440/M390/M360 01~15.
function storageText(gb){return gb>=1000&&gb%1000===0?gb/1000+'TB':gb+'GB';}
function specLine(p,sep){
  const s=p?.spec;if(!s||typeof s!=='object')return '';
  const out=[];if(s.cpu)out.push(s.cpu);if(Number.isFinite(s.ram_gb))out.push(s.ram_gb+'GB');if(Number.isFinite(s.ssd_gb))out.push(storageText(s.ssd_gb));if(s.gpu)out.push(s.gpu);
  return out.join(sep);
}
function changeLines(p){return (p.build?.changes||[]).map(c=>'<p class="tf-chg">'+esc((c.label||c.slot)+' 변경 · '+c.after.name)+'</p>').join('');}
function tfSteps(cur){
  const names=['내 PC 구성','견적 보관','구매 상담'];
  return '<ol class="tf-steps" aria-label="견적 진행 단계">'+names.map((n,i)=>{const k=i+1,done=k<cur,on=k===cur;
    return '<li class="'+(done?'is-done':on?'is-on':'')+'"'+(on?' aria-current="step"':'')+'><span class="tf-step-n" aria-hidden="true">'+(done?'✓':k)+'</span>'+n+(done?'<span class="sr-only"> 완료</span>':'')+'</li>';}).join('')+'</ol>';
}
function kindLabel(p){return canSwapHere(p)?'팝콘AI 맞춤 구성':'팝콘PC 판매 상품';}
// 견적 요약 카드(보관 · 보관 완료 · 상담 · 접수 화면 공용). 금액·번호는 서버 값만.
function tfCard(p,{parts=false}={}){
  const q=state.savedQuote&&state.saveState==='saved'?state.savedQuote:null,n=p.sets||1,spec=specLine(p,' · ');
  const rows=parts?M.cardSpecRows(p.spec).filter(([,v])=>v!=='정보 없음').concat((p.build?.changes||[]).map(c=>[c.label||c.slot,c.after.name])):[];
  return '<section class="tf-card'+(parts?' has-parts':'')+'"><div class="tf-card-copy"><p class="tf-eyebrow">'+kindLabel(p)+'</p><h3 class="tf-card-name">'+esc(p.name)+'</h3>'+
    (spec?'<p class="tf-spec">'+esc(spec)+'</p>':'')+changeLines(p)+(q?'<p class="tf-qno"><span>보관 견적</span> <strong>'+esc(keepUi.quoteNo(q.id))+'</strong></p>':'')+'</div>'+
    '<div class="tf-card-price"><strong>'+money(p.price)+'</strong><small>'+n+'대'+(n>1&&Number.isSafeInteger(p.price)?' · 합계 '+money(p.price*n):'')+'</small></div>'+
    (rows.length?'<dl class="tf-card-parts">'+rows.map(([l,v])=>'<div><dt>'+esc(l)+'</dt><dd>'+esc(v)+'</dd></div>').join('')+'</dl>':'')+'</section>';
}
function tfSets(p){
  // 대수를 바꾸면 보관 견적과 연결 기록이 풀리고(flow.setSets) 다시 보관·연결할 때 새로 만든다.
  const n=p.sets||1;
  return '<div class="dv2-sets" data-sets><strong>PC 대수</strong>'+stepper('sets','data-sets',n,1,10,'대','PC 대수')+'</div>'+
    (n>1&&Number.isSafeInteger(p.price)?'<p class="dv2-sets-total" data-sets-total><strong>같은 구성 '+n+'대 · 합계 '+money(p.price*n)+'</strong></p>':'');
}
function tfReason(p,title){
  const conds=M.conditions(state.selectionState||state.talk);
  return '<section class="tf-info"><h4>'+uiIcon('file-text')+title+'</h4>'+(conds.length?'<p>'+conds.map(esc).join(' · ')+'</p>':'')+
    (p.reasons.length?'<ul>'+p.reasons.map(r=>'<li>'+esc(r)+'</li>').join('')+'</ul>':'')+'</section>'+gameContextHtml(p);
}
function tfOver(p){return Number.isInteger((state.selectionState||state.talk)?.budget_won)&&overBudget(p)?'<div class="dv2-notes">'+budgetLines(p)+'</div>':'';}
// 완제품 오른쪽 칸(승인 시안 01 · 12 주소 확인 필요 · 13 연결 실패).
function tfMallSide(p){
  const m=state.mall,linkable=mallLinkable(p),moving=m.open&&m.step==='moving';
  return tfMallAside(p,linkable,moving,mallAlert(p));
}
// 완제품 이동 상태 안내(주소 미확인 · 연결 실패). 구성표 없는 옛 상세도 같은 안내를 쓴다 — 안 쓰면 실패가 화면에 안 남는다.
function mallAlert(p){
  const m=state.mall,linkable=mallLinkable(p),failed=m.open&&m.step==='failed';
  return !linkable?'<div class="tf-alert" role="alert" data-mall-state="no-url"><strong>상품 페이지를 확인하고 있어요.</strong><p>지금은 연결할 수 없어요. 상품 주소를 확인한 뒤 다시 안내해 드릴게요.</p></div>':
    failed?'<div class="tf-alert" role="alert" data-mall-state="failed"><strong>상품 페이지를 열지 못했어요.</strong><p>현재 구성은 그대로예요. 잠시 후 다시 시도해 주세요.</p>'+button('다시 연결하기','mall-view','outline')+'</div>':'';
}
function tfMallAside(p,linkable,moving,alert){
  return '<aside class="dv2-side tf-side" data-keep="1" aria-label="상품 금액과 구매 안내"><section class="tf-sum"><div class="dv2-sum-head"><h3>상품 금액</h3><small>'+(p.sets||1)+'대</small></div><strong class="dv2-total-num" data-dv2-total>'+money(p.price)+'</strong></section>'+
    (p.build?'<section class="tf-changes"><h4 data-pc-total-move>변경 내용 '+p.build.changes.length+'개</h4>'+dv2ChangeList(p)+'<p class="muted">팝콘PC 상품 페이지는 기본 구성 기준이에요.</p></section>':'')+
    tfSets(p)+button((moving?'이동하는 중…':'팝콘PC에서 상품 보기')+' <span aria-hidden="true">↗</span>','mall-view','primary tf-main',(linkable&&!moving&&!state.phase?'':'disabled'))+
    '<p class="tf-mainnote">옵션 선택에 따라 금액이 달라져요. 주문과 결제는 팝콘PC에서 진행해요.</p>'+alert+tfOver(p)+
    tfReason(p,'이 상품을 추천한 이유')+
    '<section class="tf-info"><h4>'+uiIcon('info')+'구매 전 확인해 주세요</h4><p>현재 판매 구성과 재고, 운영체제·보증 포함 여부는 팝콘PC 상품 페이지에서 확인해 주세요.</p></section></aside>';
}
// 견적 보관이 실패하면 보관 화면을 닫고 이 칸 안에서 말한다(승인 시안 14). 적은 연락처는 그대로 두고 같은 값으로 다시 보낸다.
function keepFailedOnDetail(){const k=state.keep;return k.open&&k.purpose==='save'&&k.failed&&!k.busy&&k.code!=='contact_required';}
// 맞춤 구성 오른쪽 칸(승인 시안 05 · 06 · 14).
function tfAiSide(p){
  const b=p.build,saved=!!(state.savedQuote&&state.saveState==='saved'),busy=['save','contact'].includes(state.phase);
  const can=!state.phase&&!state.needsRefresh&&!state.pendingProblem&&Number.isInteger(p.price);
  return '<aside class="dv2-side tf-side" data-keep="1" aria-label="선택한 구성 요약"><section class="tf-sum"><div class="dv2-sum-head"><h3>선택한 구성</h3><small>'+(p.sets||1)+'대</small></div><strong class="dv2-total-num" data-dv2-total>'+money(p.price)+'</strong></section>'+
    (b?'<section class="tf-changes"><h4 data-pc-total-move>변경 내용 '+b.changes.length+'개</h4>'+dv2ChangeList(p)+'<dl class="dv2-sums"><div><dt>기본 구성 금액</dt><dd>'+money(b.base_price)+'</dd></div></dl>'+
      (saved?'':button('전체 원래 구성으로','build-reset','dv2-link',state.phase?'disabled':''))+(b.warnings||[]).map(w=>'<p class="warn-text">'+esc(w)+'</p>').join('')+'</section>':'')+
    tfSets(p)+(saved?button('보관한 견적 보기','final','primary tf-main'):
      button(uiIcon('file-text')+(busy?'확인하는 중…':'견적 보관하기'),'save','primary tf-main',can?'':'disabled')+'<p class="tf-mainnote">견적을 보관할 때 연락받을 전화번호를 한 번 입력해 주세요.</p>')+
    (keepFailedOnDetail()?'<div class="tf-alert" role="alert" data-keep-retry tabindex="-1"><strong>견적을 보관하지 못했어요.</strong><p>선택한 부품과 금액은 그대로예요. 잠시 후 다시 시도해 주세요.</p><button type="button" class="outline" data-kact="submit">다시 보관하기</button></div>':'')+
    tfOver(p)+tfReason(p,'이렇게 구성했어요')+
    '<section class="tf-info"><h4>'+uiIcon('info')+'구매 전 확인해 주세요</h4><p>최종 금액, 재고와 운영체제·보증 포함 여부는 구매 상담 때 확인해 주세요.</p><p>변경한 구성의 실제 조립 검수는 확인이 필요해요.</p></section></aside>';
}
function renderDetailV2(p,configuration){
  // 쇼핑몰 PC 는 선택 패널을 열지 않는다(「변경」은 안내창으로 간다).
  const ai=canSwapHere(p),cur=ai?state.build.ordinal:null,opened=cur!==null&&cur!==dv2.panelFor,closed=cur===null&&dv2.panelFor!==null,prev=dv2.panelFor;
  if(opened||closed)dv2.temp=null;
  dv2.panelFor=cur;
  const labels=new Map(configuration.parts.map(x=>[x.ordinal,dv2Label(x)]));
  const b=p.build,move=dv2Move(p),spec=specLine(p,' / ');
  const photo=productImage(p,true).includes('is-unavailable')?'':'<div class="dv2-photo">'+productImage(p,true)+'<small>외관 예시</small></div>';
  const head='<div class="dv2-head"><div class="dv2-head-copy"><p class="tf-eyebrow">'+kindLabel(p)+'</p><h2 tabindex="-1">'+(ai?'내 PC 구성하기':'상품 구성 확인')+'</h2><p class="dv2-name">'+esc(p.name)+'</p>'+
    (spec?'<p class="tf-spec">'+esc(spec)+'</p>':'')+(state.savedQuote&&state.savedQuote.id===loadedQuoteId?'<p class="muted">금액과 상품 기록은 보관 시점 기준이에요.</p>':'')+'</div>'+photo+
    (b?'<details class="dv2-mchanges" data-detail="dv2-mchanges"'+dv2OpenAttr('dv2-mchanges',false)+'><summary><span>변경 내역 '+b.changes.length+'개'+uiIcon('caret-down')+'</span><small>'+esc(dv2MoveText(move))+'</small></summary>'+dv2ChangeList(p)+'</details>':'')+'</div>';
  const side=cur!==null?'<aside class="dv2-side is-panel" data-keep="1">'+dv2Panel(p,o=>labels.get(o))+'</aside>':ai?tfAiSide(p):tfMallSide(p);
  view.innerHTML='<div class="dv2 tf-detail'+(cur!==null?' has-panel':'')+'">'+errorPanel()+(ai?tfSteps(1):'')+
    '<div class="dv2-layout"><div class="dv2-main">'+head+'<section class="final-parts public-bom dv2-parts"><div class="tf-parts-head"><h3>'+(ai?'선택한 부품':'기본 구성 부품')+'</h3><span>'+(ai?'나에게 맞게 바꿔 보세요':'옵션 변경은 팝콘PC에서')+'</span></div><div class="final-table-wrap"><table class="final-table dv2-table"><thead><tr><th scope="col">분류</th><th scope="col">현재 선택된 모델</th><th scope="col">변경</th></tr></thead><tbody>'+
    configuration.parts.map(x=>dv2Row(x,p)).join('')+'</tbody></table></div><p class="tf-foot-note">'+uiIcon('info')+(ai?'부품을 바꾼 뒤 견적을 보관하면 구매 상담을 신청할 수 있어요.':'부품 옵션을 바꾸려면 팝콘PC 상품 페이지로 이동해 주세요.')+'</p></section></div>'+side+'</div></div>';
  actions.hidden=true;
  dv2Inert(mob768.matches&&cur!==null);
  if(opened&&mob768.matches&&!dv2.hist){try{history.pushState(history.state,'',location.href);dv2.hist=true;}catch{}}
  if(closed&&dv2.hist){dv2.hist=false;dv2.skipPop=true;try{history.back();}catch{dv2.skipPop=false;}}
  // 후보를 불러오거나 적용에 실패해 패널이 다시 그려져도 초점이 몸통으로 빠지지 않게 제목으로 되돌린다(눌러 둔 단추는 render 가 따로 되살린다).
  const lost=!document.activeElement||document.activeElement===document.body;
  if(opened||(cur!==null&&lost)){dv2.focusHandled=true;view.querySelector('#dv2-panel-title')?.focus({preventScroll:true});}
  else if(closed){
    dv2.focusHandled=true;
    if(lastScreen==='detail'){const t=[...view.querySelectorAll('[data-action=build-options]')].find(e=>Number(e.dataset.ordinal)===prev);t?.focus({preventScroll:true});}
  }
}
// 견적 보관 화면(승인 시안 07 처음 · 08 다음 견적). 연락처 입력·검사·보관은 live-flow(createKeepUi page)가 맡는다.
let keepSig='';
function renderKeepPage(){
  // 적는 중에 다른 일(연락처 조회 등)로 다시 그려져 입력 칸 초점이 빠지지 않게, 보관 화면 상태가 그대로면 다시 그리지 않는다.
  const k=state.keep,p=state.selected,sig=JSON.stringify([k.purpose,k.after,k.editing,k.busy,k.error,k.failed,state.contact,p.product_code,p.price,p.sets,state.phase]);
  if(sig===keepSig&&view.querySelector('[data-keep-page]')){actions.hidden=true;return;}
  keepSig=sig;
  view.innerHTML='<div class="tf-wrap">'+keepUi.pageHtml({steps:tfSteps(2),summary:tfCard(state.selected)})+'</div>';actions.hidden=true;
}
// 쇼핑몰로 이동한 뒤(승인 시안 03). 연결 번호는 서버 인계 기록이고, 주문·결제가 된 것이 아니다.
function renderMallMoved(){
  const p=state.selected,h=state.handoff,m=state.mall;
  const base=h.status==='가격변동'&&Number.isInteger(h.price_mall)?h.price_mall:h.price_quoted;
  const warn=[h.status==='가격변동'&&Number.isInteger(h.price_mall)&&h.price_mall!==h.price_quoted?'팝콘PC의 지금 기본 구성 금액은 '+money(h.price_mall)+'이에요. 보던 금액('+money(h.price_quoted)+')과 달라요.':'',
    h.status==='품절'?'팝콘PC에서 지금 품절로 표시돼요. 재고를 확인해 주세요.':'',
    h.status==='확인못함'?'지금 금액을 확인하지 못했어요. 팝콘PC에서 최종 금액을 확인해 주세요.':'',
    h.sets>1?'같은 구성 '+h.sets+'대예요. 팝콘PC에서 수량을 '+h.sets+'대로 골라 주세요.':'',
    h.changes?'바꾼 부품 '+h.changes+'개는 연결 번호로 기록해 두었어요. 주문할 때 요청사항에 이 번호를 적어 주세요.':''].filter(Boolean);
  const photo=productImage(p,true).includes('is-unavailable')?'':'<div class="tf-moved-photo">'+productImage(p,true)+'</div>',spec=specLine(p,' / ');
  view.innerHTML='<div class="tf-wrap"><section class="tf-page tf-moved" data-mall-state="moved"><div class="tf-check is-out" aria-hidden="true">↗</div><p class="tf-eyebrow">팝콘PC 판매 상품</p><h2 tabindex="-1">팝콘PC에서 원하는 옵션을 선택해 주세요.</h2>'+
    '<p class="tf-sub">선택한 옵션에 따라 금액이 달라져요.<br>주문과 결제는 팝콘PC에서 진행해요.</p>'+
    '<div class="tf-moved-card">'+photo+'<div><h3 class="tf-card-name">'+esc(p.name)+'</h3>'+(spec?'<p class="tf-spec">'+esc(spec)+'</p>':'')+'<p class="tf-base">기본 구성 '+money(base)+'</p></div></div>'+
    '<p class="tf-ho"><span>연결 번호</span><strong>'+esc(h.handoff_no)+'</strong></p>'+
    (m.blocked?'<p class="tf-alert" role="status">새 창이 열리지 않았어요. 아래 「상품 페이지 다시 보기」를 눌러 주세요.</p>':'')+
    warn.map(w=>'<p class="warn-text">'+esc(w)+'</p>').join('')+
    '<a class="primary tf-wide" data-mall-reopen href="'+esc(h.mall_url)+'" target="_blank" rel="noopener noreferrer">상품 페이지 다시 보기 <span aria-hidden="true">↗</span></a>'+
    button('상세로 돌아가기','mall-dialog-close','outline tf-wide')+'<p class="tf-foot-line">주문이나 결제가 완료된 상태는 아니에요.</p></section></div>';
  actions.hidden=true;
}
function tfReg(busy){
  return state.contact.has?'<div class="keep-reg tf-reg"><span>등록된 연락처</span><strong>'+esc(state.contact.masked)+'</strong>'+button('연락처 변경','contact-change','keep-link',busy?'disabled':'')+'</div>':'';
}
// 보관 완료 · 견적서(승인 시안 09). 주 동작은 「상담 신청 접수」 -- 보관만으로는 신청이 생기지 않는다.
let keptContactAsked=false;
// 보관하는 순간 서버가 쇼핑몰 현재가와 비교해 바뀐 가격으로 보관했으면(price_check changed) 그 사실을 밝힌다.
// 안 밝히면 상세에서 본 금액과 다른 금액이 이유 없이 보인다.
function keptPriceNote(q){
  const c=q?.price_check;if(c?.status!=='changed'||!Number.isInteger(c.quoted)||!Number.isInteger(c.mall))return '';
  return '<p class="tf-alert warn-text" role="status" data-price-changed>보관할 때 팝콘PC 판매 가격이 '+money(c.quoted)+'에서 '+money(c.mall)+'으로 바뀌어, 바뀐 가격으로 보관했어요.</p>';
}
function renderKept(){
  const p=state.selected,q=state.savedQuote,c=state.consult,done=c.done&&c.done.quote_id===q.id?c.done:null,busy=!!state.phase;
  if(!state.contact.loaded&&!keptContactAsked&&!state.phase){keptContactAsked=true;void flow.loadContact({quiet:true});}
  const ask=done?'<section class="tf-ask consult-done" role="status" data-consult-done="already"><h3>이미 상담 신청이 접수된 견적이에요</h3><p class="consult-order">'+keepUi.ORDER_LINE+'</p>'+
      (c.showRows?keepUi.doneRows(done):button('상담 접수 내역 보기','consult-rows','outline','data-show="1"'))+'<p class="muted">주문·결제는 아직 진행되지 않았어요.</p></section>':
    '<section class="tf-ask" data-consult-ask><h3>필요할 때 상담을 신청해 주세요.</h3><p>보관한 견적과 등록한 전화번호로 상담을 접수해요.</p>'+
      button((state.phase==='consult'?'접수하는 중…':'상담 신청 접수')+' <span aria-hidden="true">→</span>','consult-send','primary tf-go',busy?'disabled':'')+
      '<div class="tf-center">'+button('상담 내용 남기기 (선택)','consult-note','tf-textbtn',busy?'disabled':'')+'</div></section>';
  view.innerHTML='<div class="tf-wrap"><section class="tf-page tf-kept" data-keep-done>'+errorPanel()+tfSteps(2)+'<div class="tf-check" aria-hidden="true">✓</div><p class="tf-eyebrow">내 견적</p><h2 tabindex="-1">견적을 보관했어요</h2><p class="tf-sub">선택한 부품과 금액을 다시 볼 수 있어요.</p>'+
    tfCard(p)+keptPriceNote(q)+tfReg(busy)+'<p class="keep-note keep-nocall">'+keepUi.NO_CALL+'</p>'+ask+
    '<div class="tf-foot">'+button('내 견적 보기','saved','outline')+button('구성 다시 수정','edit','tf-textbtn')+'</div></section></div>';
  actions.hidden=true;
}
// 상담할 내용 남기기(승인 시안 10 · 실패 15). 주제 선택지는 서버(구매 상담 신청 양식)가 준 것만, 기본은 「주문 희망」.
function renderConsultPage(){
  const p=state.selected,c=state.consult,busy=!!state.phase,topics=state.inquiry.meta?.topics||null,sel=topics&&topics.includes(c.topic)?c.topic:'주문 희망';
  if(!topics)void flow.loadConsultTopics();
  const topic=topics?'<label class="keep-field"><span>상담 주제</span><select data-consult-topic'+(busy?' disabled':'')+'>'+topics.map(t=>'<option'+(t===sel?' selected':'')+'>'+esc(t)+'</option>').join('')+'</select></label>':
    '<p class="consult-topic"><span>상담 주제</span><strong>주문 희망</strong></p>';
  view.innerHTML='<div class="tf-wrap is-wide"><section class="tf-page tf-consult">'+tfSteps(3)+'<p class="tf-eyebrow">구매 상담</p><h2 tabindex="-1">상담할 내용을 남겨 주세요</h2><p class="tf-sub">상담 전에 궁금한 점을 적어 주셔도 좋아요.</p>'+
    '<div class="tf-consult-grid">'+
    // 견적을 먼저 확인하고 연락처·접수로 간다(승인 모바일 10·15 순서 · 키보드 순서도 같다). PC는 CSS가 견적을 오른쪽에 둔다.
    '<aside class="tf-consult-side"><h3>상담할 견적</h3>'+tfCard(p,{parts:true})+'<p class="keep-note">'+uiIcon('file-text')+'이 견적이 상담 신청에 함께 전달돼요.</p>'+button('내 견적 보기','saved','tf-textbtn')+'</aside>'+
    '<div class="tf-consult-form"><h3>연락받을 곳</h3>'+tfReg(busy)+'<p class="keep-note">견적을 보관할 때 등록한 전화번호예요.</p>'+topic+
    '<label class="keep-field"><span>상담할 내용 <em>선택</em></span><textarea data-consult-message maxlength="500" rows="4" placeholder="궁금한 점이나 연락받기 편한 때를 적어 주세요."'+(busy?' disabled':'')+'>'+esc(c.message)+'</textarea></label>'+
    '<small class="consult-count">'+c.message.length+' / 500자</small><p class="keep-note">이 견적과 등록한 연락처가 상담 담당자에게 함께 전달돼요.</p>'+
    (c.error?'<div class="tf-alert" role="alert" tabindex="-1"><strong>상담 신청을 접수하지 못했어요.</strong><p>보관한 견적과 입력한 내용은 그대로예요. 다시 신청해 주세요.</p></div>':'')+
    button(state.phase==='consult'?'접수하는 중…':'상담 신청 접수','consult-send','primary tf-wide',busy?'disabled':'')+'<p class="keep-foot">상담 신청만 접수돼요. 주문·결제는 진행되지 않아요.</p></div></div></section></div>';
  actions.hidden=true;
}
// 접수 완료(승인 시안 11). 실제 접수 성공 응답(PI 번호)을 받은 뒤에만 그린다.
function renderConsultDone(done){
  view.innerHTML='<div class="tf-wrap"><section class="tf-page tf-done" role="status" data-consult-done="new">'+tfSteps(3)+'<div class="tf-check" aria-hidden="true">✓</div><p class="tf-eyebrow">구매 상담</p><h2 tabindex="-1">상담 신청이 접수됐어요</h2>'+
    '<p class="consult-order"><strong>'+keepUi.ORDER_LINE+'</strong></p>'+keepUi.doneRows(done)+tfCard(state.selected)+
    '<p class="keep-foot">주문·결제는 아직 진행되지 않았어요.</p><div class="tf-center">'+button('내 견적 보기','saved','primary tf-go')+'</div></section></div>';
  actions.hidden=true;
}
// 상품 화면 갈래: 보관 화면 > 몰 이동 뒤 > (맞춤 구성 보관 견적) 접수 완료 · 상담 내용 · 보관 완료 > 상세.
let productPage='',loadedQuoteId=null;   // 「내 견적」에서 다시 연 보관 견적(몰 이동 때 조용히 만든 보관과 구분한다)
function renderProduct(){
  const p=state.selected;if(!state.keep.open)keepSig='';
  if(state.keep.open&&!keepFailedOnDetail()){renderKeepPage();return;}
  if(!canSwapHere(p)&&state.mall.open&&state.mall.step==='moved'&&state.handoff&&state.savedQuote&&state.handoff.quote_id===state.savedQuote.id){renderMallMoved();return;}
  if(canSwapHere(p)&&state.screen==='final'&&state.savedQuote&&state.saveState==='saved'){
    const c=state.consult,done=c.done&&c.done.quote_id===state.savedQuote.id?c.done:null;
    if(done&&!done.already){renderConsultDone(done);return;}
    if(!done&&(c.open||c.error)){renderConsultPage();return;}
    renderKept();return;
  }
  renderDetail();
}
// 추천 구성 상세(2026-10-15 코덱스 디자인 v1 -- D:\\WORK\\코덱스-디자인\\2026-10-15-추천구성상세-v1). 왼쪽 = 상품·구성·부품 바꾸기,
// 오른쪽 = 추천 이유·같은 구성 대수·구매 전 안내, 그 아래 구매 전 확인 6칸. 담는 정보와 동작은 그대로이고 배치만 바뀐다.
function renderDetail(){
  const p=state.selected,configuration=M.publicConfiguration(p.public_configuration,p.product_code),configured=!!configuration;
  // 부품별 구성표가 공개된 PC 는 v2 상세(선택한 부품 표 + 오른쪽 요약/변경 패널). 구성표가 없는 상품은 아래 기존 배치(다른 판매 PC 로 옮기는 부품 바꾸기)를 쓴다.
  if(configuration){renderDetailV2(p,configuration);return;}
  actions.classList.remove('dv2-bar');
  view.innerHTML='<div class="dt-detail">'+heading('추천 구성 상세',false,'구성을 살펴보고, 나에게 맞게 조정해 보세요.')+errorPanel()+
    '<div class="dt-layout"><div class="dt-main-col">'+productSummary()+productDetails(false,true)+partChangeBody(false,configured)+'</div>'+
    '<aside class="dt-aside" aria-label="추천 이유와 대수">'+detailReason(p)+setsBlock(p)+
    (canSwapHere(p)?'':mallAlert(p))+'<div class="dt-alt-note"><strong>구매 전에 확인해 주세요</strong>표시 금액은 조회 시점의 참고 금액이에요. 실제 구매 금액과 포함 품목은 구매 전에 확인해 주세요.</div></aside></div>'+
    finalConditions()+'</div>';
  actions.innerHTML='<div><span>PC 총액 · 한 대 기준</span><strong>'+money(p.price)+'</strong></div><div class="footer-buttons">'+(canSwapHere(p)?button('부품 바꾸기','part-focus','outline')+(state.savedQuote&&state.saveState==='saved'?button('보관한 견적 보기','final','primary'):button('견적 보관하기','save','primary',state.phase||state.needsRefresh?'disabled':'')):
    button('팝콘PC에서 상품 보기 <span aria-hidden="true">↗</span>','mall-view','primary',mallLinkable(p)&&!state.phase?'':'disabled'))+'</div>';actions.hidden=false;
}
// 구매 상담 신청 칸(api/mvp3_purchase_inquiry.py). 주제·동의 문구는 서버가 준 것만 쓴다.
// 연락처를 남길 뿐 주문·결제·가격 확정은 하지 않는다고 칸 안에서 먼저 말한다.
function inquiryPanel(){
  const q=state.inquiry;if(!q.open&&!q.done)return '';
  // 「사람 상담 남기기」 단추로 열었으면 구매 상담 문구 대신 일반 상담 문구를 쓴다(코덱스 PR136 검수 「신청 문구의 범위」).
  const human=!!q.human,title=human?'사람 상담 남기기':'구매 상담 신청';
  if(q.done)return '<section class="live-explanation live-inquiry" role="status" data-inquiry-done><h3>'+title+'</h3><p>'+esc(q.done.note)+'</p>'+
    '<p class="muted">신청 번호 '+esc(q.done.inquiry_no)+' · 주문과 결제는 아직 진행되지 않았어요.</p></section>';
  const busy=state.phase==='inquiry'||state.phase==='inquiry-form',d=q.draft;
  const err=q.error?'<p class="live-inquiry-error" role="alert">'+esc(q.error)+'</p>':'';
  if(!q.meta)return '<section class="live-explanation live-inquiry" data-inquiry-form><h3>'+title+'</h3>'+
    (busy?'<p class="muted">신청 양식을 불러오는 중이에요.</p>':err+button('다시 불러오기','inquiry-open','outline',human?'data-human="1"':''))+'</section>';
  const field=(name,label,input)=>'<label class="live-inquiry-field"><span>'+label+'</span>'+input+'</label>';
  const dis=busy?' disabled':'';
  return '<section class="live-explanation live-inquiry" data-inquiry-form><h3>'+title+'</h3>'+
    '<p class="muted">'+(human?'상담에서 바로 답하기 어려운 내용은 팝콘PC 담당자가 연락드려 안내해요.':'여러 대 구매 · 할인 · 세금계산서처럼 상담에서 정할 수 없는 내용은 팝콘PC 담당자가 연락드려 안내해요.')+' 이 신청으로 주문이나 결제가 진행되지는 않아요.</p>'+
    field('topic','문의 주제','<select data-inquiry="topic"'+dis+'><option value="">주제를 골라 주세요</option>'+q.meta.topics.map(t=>'<option'+(d.topic===t?' selected':'')+'>'+esc(t)+'</option>').join('')+'</select>')+
    field('name','이름 (선택)','<input data-inquiry="name" maxlength="30" autocomplete="name" value="'+esc(d.name)+'"'+dis+'>')+
    field('phone','전화번호','<input data-inquiry="phone" type="tel" maxlength="20" autocomplete="tel" placeholder="010-1234-5678" value="'+esc(d.phone)+'"'+dis+'>')+
    field('email','이메일','<input data-inquiry="email" type="email" maxlength="120" autocomplete="email" value="'+esc(d.email)+'"'+dis+'>')+
    '<p class="muted live-inquiry-hint">전화번호나 이메일 중 하나는 적어 주세요.</p>'+
    field('message','문의 내용 (선택)','<textarea data-inquiry="message" maxlength="500" rows="3"'+dis+'>'+esc(d.message)+'</textarea>')+
    '<label class="live-inquiry-consent"><input type="checkbox" data-inquiry="consent"'+(d.consent?' checked':'')+dis+'><span>'+esc(q.meta.consent_text)+' 동의합니다.</span></label>'+
    err+'<div class="live-inquiry-buttons">'+button('닫기','inquiry-close','outline',busy?'disabled':'')+
    button(state.phase==='inquiry'?'보내는 중…':'신청 보내기','inquiry-send','primary',busy?'disabled':'')+'</div></section>';
}
function inquiryValues(){
  const out={};
  for(const e of view.querySelectorAll('[data-inquiry]'))out[e.dataset.inquiry]=e.type==='checkbox'?e.checked:e.value;
  return out;
}
// 쇼핑몰 연결이 실패하면 단추 바로 아래에 말한다(2026-10-12 끝까지 검수 O4 -- 오류 칸이 화면 맨 위라 모바일에서 3,700px
// 위에 있었다). 같은 단추를 다시 누르면 다시 시도한다. 화면 맨 위 오류 칸에는 따로 싣지 않는다(errorPanel).
function handoffFailed(){return !!(state.error&&state.retry?.kind==='handoff'&&state.screen==='final');}
function renderSaved(){
  view.innerHTML=heading('내 견적',false)+'<p class="muted">이 브라우저의 보관 키로 접근하는 서버 기록입니다. 다른 기기나 회원 계정에서는 이 보관 기록을 이어 볼 수 없어요.</p>'+errorPanel()+
    (state.phase==='list'?'<div class="empty small-empty"><p>보관 기록을 불러오는 중이에요.</p></div>':state.error?'':state.quotes.length?
      '<div class="quote-cards">'+state.quotes.map(q=>'<section class="quote-card live-product-card">'+productImage(q.product)+'<span class="pill">보관 시점 기록</span><h3>'+esc(q.product.name)+'</h3><strong class="price">'+money(q.product.price)+'</strong><p>'+esc(new Date(q.saved_at).toLocaleString('ko-KR'))+'</p>'+button('저장한 견적 보기','load','primary','data-id="'+esc(q.id)+'"')+'</section>').join('')+'</div>':
      '<div class="empty small-empty"><h3>보관된 견적이 없어요</h3><p>상담 후 상품을 선택하면 서버에 보관할 수 있어요.</p>'+button('상담으로 돌아가기','back','outline')+'</div>')+
    (state.hasMore?'<p class="muted">최근 20개의 보관 기록을 표시하고 있어요.</p>':'');
  actions.hidden=true;
}
function renderWelcome(){view.innerHTML=`<header class="welcome-heading"><h2 tabindex="-1">나에게 맞는 PC</h2><p>말씀해주신 조건에 맞춰 이곳에 견적을 정리해드려요.</p></header>${welcomePcs()}<section class="welcome-card"><div class="welcome-illustration"><img src="assets/welcome-pc.png" alt="옅은 민트색 PC 본체 일러스트"></div><h3>어떤 PC가 필요한지 들려주세요</h3><p class="welcome-subtitle">게임과 예산만 알려주셔도 시작할 수 있어요.</p><ol class="welcome-steps"><li><span class="step-icon">${uiIcon('chat-circle')}</span><h4>원하는 조건 말하기</h4><p>게임, 예산, 용도 등을<br>자유롭게 말씀해주세요.</p>${uiIcon('arrow-right','step-arrow')}</li><li><span class="step-icon">${uiIcon('file-text')}</span><h4>추천 견적 비교하기</h4><p>입력하신 조건에 맞춰<br>최적의 견적을 제안해드려요.</p>${uiIcon('arrow-right','step-arrow')}</li><li><span class="step-icon">${uiIcon('gear')}</span><h4>부품 구성 확인하기</h4><p>상세한 부품과 사양을<br>한눈에 확인할 수 있어요.</p></li></ol><p class="welcome-help">${uiIcon('info')}잘 모르는 항목은 상담하면서 정하면 돼요.</p></section>`;actions.hidden=true;}
// 「AI 답변 준비중」(2026-10-15 중헌 님 「로딩되는 순간 메인화면이 보이니까.. 헷갈려」). 대화 화면에서 상세로 넘어오거나
// 새로고침해 보던 견적을 다시 불러오는 동안(restoring) 상세가 아직 없으면 첫 화면 대신 이것을 그린다.
// 진행률은 모르므로 숫자를 말하지 않는다. 10초가 넘으면 문장만 바꾼다.
const PREP_LONG_MS=10000;let prepStarted=0,prepTimer;
function renderPreparing(){
  if(!prepStarted){prepStarted=Date.now();clearTimeout(prepTimer);prepTimer=setTimeout(()=>{if(restoring)render();},PREP_LONG_MS);}
  const long=Date.now()-prepStarted>=PREP_LONG_MS;
  const msg=long?'조금 더 걸리고 있어요.<span class="ai-prep-pause">잠시만 기다려 주세요.</span>':'고르신 PC의 구성과 금액을<span class="ai-prep-pause">지금 기준으로 다시 확인하고 있어요.</span>';
  // 머리띠 높이는 화면 폭마다 다르다(PC 82~84px · 좁으면 줄바꿈). 덮개 윗변을 실측값에 맞춘다.
  const bar=document.querySelector('.topbar');document.documentElement.style.setProperty('--ai-prep-top',(bar?Math.max(0,Math.round(bar.getBoundingClientRect().bottom)):82)+'px');
  // 다시 그려질 때마다 움직임이 처음부터 시작되지 않게, 이미 떠 있으면 문구만 바꾼다(10초가 지나면 한 번).
  const shown=view.querySelector('.ai-prep-message');
  if(shown){if(shown.dataset.long!==String(long)){shown.innerHTML=msg;shown.dataset.long=String(long);}actions.hidden=true;return;}
  const spark='<svg class="ai-prep-spark ai-prep-spark--KIND" viewBox="0 0 20 20" fill="none"><path d="M10 2v16M2 10h16" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>';
  view.innerHTML='<section class="ai-prep-root ai-prep-overlay" role="status" aria-live="polite" aria-atomic="true" aria-labelledby="ai-prep-title"><div class="ai-prep-content">'+
    '<div class="ai-prep-scene" aria-hidden="true"><div class="ai-prep-halo"></div><div class="ai-prep-orbit"><span class="ai-prep-orbit-dot"></span><span class="ai-prep-orbit-dot ai-prep-orbit-dot--small"></span></div>'+
    '<img class="ai-prep-image" src="assets/welcome-pc.png" alt="" width="350" height="350">'+spark.replace('KIND','one')+spark.replace('KIND','two')+'</div>'+
    '<h2 class="ai-prep-title" id="ai-prep-title" tabindex="-1">AI 답변 준비중</h2>'+
    '<p class="ai-prep-description"><span class="ai-prep-message" data-long="'+long+'">'+msg+'</span></p>'+
    '<div class="ai-prep-indicator" aria-hidden="true"><span class="ai-prep-dot"></span><span class="ai-prep-dot"></span><span class="ai-prep-dot"></span></div></div></section>';
  actions.hidden=true;
}
function render(){
  const changed=lastScreen!==state.screen,openDetails=[...view.querySelectorAll('details[open]')].map(e=>e.dataset.detail),scroll=view.scrollTop,focused=document.activeElement?.dataset.action,focusedOrd=document.activeElement?.dataset.ordinal;
  dv2.focusHandled=false;actions.classList.remove('dv2-bar');if(state.screen!=='detail'){dv2.panelFor=null;dv2.temp=null;dv2Inert(false);}
  document.body.dataset.screen=state.screen;
  // 상품 화면은 상담창 없이 한 열(승인 시안 01~15). 머리띠는 「상담으로 돌아가기」·「내 견적」만 남긴다.
  if(state.selected&&['detail','final'].includes(state.screen))document.body.dataset.page='product';else delete document.body.dataset.page;
  $('#consult-back').hidden=document.body.dataset.page!=='product';document.body.classList.add('live-mode');document.body.classList.toggle('original-flow',['welcome','results','detail','final'].includes(state.screen));
  view.dataset.screen=state.screen;
  // 예외 입력·상담 실패 뒤에는 사람 상담 길을 연다(서버 handoff_offer). 신청 칸은 구매 상담 신청과 같다.
  const handoffBlock=()=>(state.handoffOffer||state.inquiry.open||state.inquiry.done)?
    (!state.inquiry.open&&!state.inquiry.done?'<p class="live-inquiry-open">'+button('사람 상담 남기기','inquiry-open','outline',(state.phase?'disabled ':'')+'data-human="1"')+'</p>':'')+inquiryPanel():'';
  if(state.screen==='welcome'&&restoring&&!state.error){renderPreparing();}
  else if(state.screen==='welcome'){renderWelcome();if(state.error)view.insertAdjacentHTML('afterbegin',errorPanel());view.insertAdjacentHTML('beforeend',handoffBlock());}
  // 견적을 보던 중에 받은 예외 입력도 같은 길을 연다(보던 견적은 그대로 둔다).
  else if(state.screen==='results'){renderResults();if(state.handoffOffer)view.insertAdjacentHTML('beforeend',handoffBlock());}
  // 상세를 보던 중에도 같은 길을 연다(코덱스 PR136 검수 「상세 화면의 상담 버튼」).
  else if(state.screen==='detail'&&state.selected){renderProduct();if(state.handoffOffer&&!state.keep.open)view.insertAdjacentHTML('beforeend',handoffBlock());}
  else if(state.screen==='final'&&state.selected)renderProduct();
  else if(state.screen==='saved')renderSaved();
  const recovery=recoveryBanner();if(recovery)view.insertAdjacentHTML('afterbegin',recovery);
  renderMessages();syncChat();document.body.dataset.surface='consultation';
  {
    if(!changed){for(const e of view.querySelectorAll('details'))if(openDetails.includes(e.dataset.detail))e.open=true;view.scrollTop=scroll;if(focused&&!dv2.focusHandled)[...document.querySelectorAll('[data-action]')].find(e=>e.dataset.action===focused&&!e.disabled&&(focusedOrd===undefined||e.dataset.ordinal===focusedOrd))?.focus({preventScroll:true});}
    else{view.scrollTop=0;view.querySelector('h2')?.focus({preventScroll:true});if(mobile.matches)window.scrollTo(0,0);}
    if(!enteringRoute&&lastScreen!==state.screen&&location.hash!=='#'+state.screen)history[restoring?'replaceState':'pushState']({screen:state.screen},'','#'+state.screen);
  }
  lastScreen=state.screen;
  if(!(restoring&&state.screen==='welcome')){prepStarted=0;clearTimeout(prepTimer);}
  clearTimeout(retryTimer);if(state.error?.retryAt>Date.now())retryTimer=setTimeout(()=>render(),1000);
  keepUi.sync();syncMallDialog();      // 안내창은 화면 위에 뜬다 -- 그린 뒤 마지막에 초점을 가져간다
  settleProductFocus();
  settleArrival();                      // 대화에서 「부품 바꾸기」로 넘어온 초점은 제목 초점보다 뒤에 둔다(안 그러면 제목이 가져간다)
}
// 상품 화면 안에서 화면이 바뀌면(상세 -> 보관 -> 보관 완료 -> 상담 -> 접수) 맨 위로 올리고 제목에 초점을 둔다.
// 실패를 말하는 칸이 새로 나타나면 그 칸으로 옮긴다(시안 12~15).
function settleProductFocus(){
  const v=view.firstElementChild,key=document.body.dataset.page!=='product'?'':view.querySelector('[data-keep-page]')?'keep:'+state.keep.purpose:
    v?.querySelector?.('.tf-moved')?'moved':view.querySelector('.tf-done')?'done':view.querySelector('.tf-consult')?'consult':view.querySelector('.tf-kept')?'kept':'detail';
  const alert=view.querySelector('.keep-error,[data-keep-retry],.tf-consult .tf-alert,[data-mall-state=failed]'),akey=alert?alert.className+(alert.textContent||'').length:'';
  if(key&&key!==productPage&&lastScreen!==null){
    view.scrollTop=0;if(mobile.matches)window.scrollTo(0,0);
    if(!mallDialogShown())(view.querySelector('#keep-title')||view.querySelector('h2'))?.focus({preventScroll:true});
  }
  if(alert&&akey!==settleProductFocus.alert){const t=alert.matches('[data-mall-state=failed]')?alert.querySelector('button'):alert;if(t){if(!t.hasAttribute('tabindex')&&t.tagName!=='BUTTON')t.tabIndex=-1;t.focus({preventScroll:true});t.scrollIntoView?.({block:'nearest'});}}
  // 같은 화면을 다시 그리면(예: 상담 주제 목록이 늦게 도착) 초점이 있던 요소가 사라져 body 로 떨어진다 -- 제목으로 되돌린다.
  else if(key&&key===productPage&&settleProductFocus.inView&&document.activeElement===document.body&&!mallDialogShown())(alert&&alert.hasAttribute('tabindex')?alert:view.querySelector('#keep-title')||view.querySelector('h2'))?.focus({preventScroll:true});
  settleProductFocus.alert=akey;productPage=key;settleProductFocus.inView=view.contains(document.activeElement);
}
// 「부품 전체 구성 확인 및 변경」(대화 화면 · 2026-10-12 중헌 님 고객단 5번)과 아래 「부품 바꾸기」가 여기로 온다.
// 구성표가 공개된 PC 는 부품 구성 표(줄마다 「변경」)로, 아니면 다른 판매 PC 로 옮기는 부품 바꾸기 칸으로 옮긴다.
function focusParts(){
  const pick=view.querySelector('[data-action=build-options]');
  if(pick){view.querySelector('.final-parts')?.scrollIntoView({block:'start'});pick.focus({preventScroll:true});return;}
  const s=view.querySelector('#part-change');s?.scrollIntoView({block:'start'});(s?.querySelector('[data-action=part-options]')||s?.querySelector('button:not([disabled])'))?.focus({preventScroll:true});
}
// 넘어온 직후 견적을 다시 불러오는 일이 끝나면 한 번만 부품 바꾸기 칸으로 옮긴다(못 불러왔으면 옮기지 않고 끝낸다).
function settleArrival(){if(!arrival?.focus||enteringRoute||state.phase)return;arrival.focus=false;if(state.screen==='detail'&&state.selected)focusParts();}
function openSaved(){if(state.screen==='saved'&&state.phase==='list'){render();return;}void flow.list();}
function enterRoute(hash,initial=false){
  enteringRoute=true;
  try{
    if(initial)flow.reset({restore:true});
    // 옛 입구 주소(#start · #purpose)와 빈 주소는 모두 상담 첫 화면(#welcome)이다.
    let screen=hash.slice(1);const asked=screen;
    if(!screenNames.includes(screen)||(['detail','final'].includes(screen)&&!state.selected)||(screen==='results'&&!state.recommendation))screen='welcome';
    if(initial||hash!=='#'+screen)history.replaceState({screen},'','#'+screen);
    const willResume=initial&&screen!=='saved'&&state.restoredCurrent&&state.talk,willRefresh=!willResume&&initial&&screen==='welcome'&&['results','detail'].includes(asked)&&state.talk;
    // 다시 불러올 것이 있으면 navigate 가 그리는 첫 화면부터 「AI 답변 준비중」이 되게 먼저 표시한다.
    if(willResume||willRefresh)restoring=true;
    if(screen==='saved')openSaved();else flow.navigate(screen);
    // 새로고침 전에 보던 견적이 있으면 같은 조건으로 다시 물어 그 상품을 다시 연다(값은 지금 기준).
    if(willResume){void flow.resume({arrived:!!arrival}).finally(()=>{restoring=false;render();});}
    // 고른 견적 없이 조건만 넘어왔으면(대화 화면의 「기존 상담 화면」) 그 조건으로 추천을 다시 받아 추천 목록을 연다.
    else if(willRefresh){void flow.refresh().finally(()=>{restoring=false;render();});}
  }finally{enteringRoute=false;}
}
function back(){flow.navigate({results:'welcome',detail:'results',final:'detail',saved:state.selected?'final':state.groups.length?'results':'welcome'}[state.screen]||'welcome');}
async function submit(text,{fromInput=false}={}){if(!String(text||'').trim()){notice('원하는 조건을 입력해주세요.');$('#request').focus();return;}
  if(text.trim().length>20000){notice('한 번에 20,000자까지 보낼 수 있어요. 나눠서 보내 주세요.');return;}
  if(state.phase)return;
  const sent=text.trim();await flow.submit(text);
  // submit() also returns true after errors. Only validated conversation history
  // with no current error permits clearing the unchanged, visible input.
  if(fromInput&&!state.error&&state.history.some(x=>x.role==='user'&&x.text===sent)&&draft.draft_text===text)setDraft('');
}
document.addEventListener('click',e=>{
  const b=e.target.closest('[data-action]');if(!b||b.disabled)return;e.preventDefault();
  if(keepUi.handle(b.dataset.action,b))return;
  switch(b.dataset.action){
    case 'home':if(state.screen!=='welcome'&&!state.phase)flow.navigate('welcome');else{view.scrollTop=0;window.scrollTo(0,0);}break;
    case 'new':chatPreference=null;lastMessages='';setDraft('');flow.reset();break;
    case 'saved':captureDraft();openSaved();break;
    case 'prompt':submit(b.dataset.text);break;
    case 'explore':void flow.explore(b.dataset.dir,b.dataset.label);break;
    case 'detail':flow.select(Number(b.dataset.id));break;
    case 'final':flow.navigate('final');break;
    case 'edit':flow.navigate('detail');break;
    case 'results':flow.navigate('results');break;
    case 'back':back();break;
    case 'handoff':void window.MVP3LiveFlow.handoffAndOpen(flow,window);break;
    case 'inquiry-open':void flow.openInquiry({human:b.dataset.human==='1'});break;
    case 'part-options':void flow.openParts(b.dataset.slot);break;
    case 'part-close':flow.closeParts();break;
    case 'part-swap':flow.swapPart(Number(b.dataset.code));break;
    case 'mall-change':openMallDialog(b);break;
    case 'mall-dialog-close':closeMallDialog();break;
    case 'mall-move':mallDirect=false;void window.MVP3LiveFlow.moveToMall(flow,window);break;
    case 'mall-view':mallView();break;
    case 'consult-back':consultBack();break;
    case 'build-options':{if(!canSwapHere(state.selected)){openMallDialog(b);break;}if(b.dataset.retry)flow.state.build.error='';void flow.openBuild(Number(b.dataset.ordinal));break;}
    case 'build-close':flow.closeBuild();break;
    case 'build-pick':void flow.pickBuild(Number(b.dataset.code));break;
    case 'build-reset':void flow.resetBuild();break;
    case 'build-undo':void flow.undoBuild(Number(b.dataset.ordinal));break;
    case 'build-pick-base':dv2SelectTemp(Number(b.dataset.code));break;
    case 'build-apply':if(dv2.temp!==null&&dv2.temp!==dv2.applied)void flow.pickBuild(dv2.temp);break;
    case 'build-qty':void flow.setBuildQuantity(Number(b.dataset.qty));break;
    case 'sets':if(state.screen==='final')flow.navigate('detail');flow.setSets(Number(b.dataset.sets));break;   // 보관 견적으로 연 완제품 상세도 대수를 바꿀 수 있게
    case 'part-focus':focusParts();break;
    case 'inquiry-close':flow.inquiryDraft(inquiryValues());flow.closeInquiry();break;
    case 'inquiry-send':void flow.inquire(inquiryValues());break;
    case 'recover':void flow.recover();break;
    case 'load':loadedQuoteId=b.dataset.id;flow.load(b.dataset.id);break;
    case 'retry':void flow.retry();break;
    case 'attachment':notice('파일 첨부는 아직 지원하지 않아요. 필요한 조건을 글로 알려주세요.');break;
    case 'conditions':chatPreference=true;syncChat();$('#request').focus({preventScroll:true});if(mobile.matches)$('#chat-toggle').scrollIntoView({block:'start'});notice('바꿀 예산이나 용도를 상담창에 알려주세요. 실제 추천을 다시 조회해요.');break;
  }
});
// 「상담으로 돌아가기」: 대화 화면에서 왔으면 대화로, 아니면 추천 목록(없으면 상담 첫 화면)으로.
function consultBack(){
  if(state.keep.open&&!state.keep.busy)flow.closeKeep();
  if(state.consult.open)flow.consultToggle(false);
  if(state.mall.open&&state.mall.step!=='moving'){flow.closeMall();mallDirect=false;}
  if(arrival){location.href='talk.html';return;}
  flow.navigate(state.recommendation?'results':'welcome');
}
// 신청 칸은 다시 그려져도 적던 값이 남게 입력마다 상태에 옮긴다(다시 그리지는 않는다).
view.addEventListener('input',e=>{if(e.target.closest?.('[data-inquiry]'))flow.inquiryDraft(inquiryValues());});
// 상세 v2: 라디오로 고르는 것은 임시 선택이다(화면을 다시 그리지 않고 적용 단추 상태만 바꾼다). 접힌 칸의 열림 상태는 다시 그려도 지킨다.
view.addEventListener('change',e=>{if(e.target.matches?.('[data-dv2-radio]'))dv2SelectTemp(Number(e.target.value));});
view.addEventListener('toggle',e=>{const k=e.target?.dataset?.detail;if(k&&k.startsWith('dv2-'))dv2.open[k]=e.target.open;},true);
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!e.defaultPrevented&&state.screen==='detail'&&state.build?.ordinal!==null&&canSwapHere(state.selected)){e.preventDefault();flow.closeBuild();}});
view.addEventListener('change',e=>{if(e.target.closest?.('[data-inquiry]'))flow.inquiryDraft(inquiryValues());if(e.target.matches?.('[data-consult-topic]'))flow.consultTopic(e.target.value);});
$('#request').addEventListener('input',()=>{captureDraft();draft.draft_edited=true;});
$('#chat-form').addEventListener('submit',e=>{e.preventDefault();if(state.phase)return;captureDraft();void submit(draft.draft_text,{fromInput:true});});
$('#request').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('#chat-form').requestSubmit();}});
$('#chat-toggle').addEventListener('click',()=>{chatPreference=$('#chat-toggle').getAttribute('aria-expanded')!=='true';syncChat();if(!$('#chat-body').hidden)scrollToLatest();});
$('#messages').addEventListener('scroll',markScroll,{passive:true});
mobile.addEventListener('change',syncChat);
for(const type of ['load','error'])document.addEventListener(type,e=>{
  const image=e.target;if(!(image instanceof HTMLImageElement))return;
  // A card thumbnail that fails to load disappears instead of showing a placeholder.
  if(image.hasAttribute('data-card-part-image')){if(type==='error'){const item=image.closest('li');if(item)item.hidden=true;}return;}
  if(!image.hasAttribute('data-product-image'))return;
  const photo=image.closest('[data-product-photo]');if(!photo)return;
  const failed=type==='error';image.hidden=failed;photo.classList.toggle('is-unavailable',failed);
  photo.dataset.imageState=failed?'temporarily_unavailable':'loaded';photo.querySelector('[data-product-image-status]').hidden=!failed;
},true);
window.addEventListener('popstate',e=>{
  // 모바일 선택창: 뒤로가기는 화면을 옮기지 않고 패널만 닫는다(적용된 구성 · 대수 · 스크롤은 그대로).
  if(dv2.skipPop){dv2.skipPop=false;return;}
  if(dv2.hist){dv2.hist=false;if(state.screen==='detail'&&state.build?.ordinal!==null)flow.closeBuild();return;}
  captureDraft();
  enterRoute(location.hash);
});
// 대화 화면(talk.html)과 오갈 때 보내지 않은 입력 문장을 넘긴다(코덱스 #148 검수 P2). 고객이 직접 쓴 문장만
// 넘기고(자동으로 만든 안내 문장은 넘기지 않는다), 받은 문장은 입력 칸에 채우기만 한다 -- 보내지 않는다.
const draftHandoff=window.MVP3LiveFlow.createDraftHandoff();
window.addEventListener('pagehide',()=>{captureDraft();draftHandoff.put(draft.draft_edited?draft.draft_text:'');});
{const carried=draftHandoff.take();if(carried&&!(draft.draft_edited&&draft.draft_text.trim()))setDraft(carried,true);}
enterRoute(location.hash,true);focusConsultation();settleArrival();
})();
