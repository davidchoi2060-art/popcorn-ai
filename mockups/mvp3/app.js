(function(){'use strict';
const DIRECT_ACTION='gateway-talk';
const M=window.MVP3LiveModel,A=window.MVP3Api;
const {customerPhoto}=window.MVP3LivePhoto;
const $=s=>document.querySelector(s),view=$('#view'),actions=$('#actions'),mobile=matchMedia('(max-width:760px)');
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const uiIcon=(name,cls='')=>'<img class="ui-icon '+cls+'" src="assets/icons/'+name+'.svg" alt="">';
const button=(label,action,cls='',data='')=>'<button type="button" class="'+cls+'" data-action="'+action+'" '+data+'>'+label+'</button>';
const money=value=>Number.isInteger(value)?value.toLocaleString('ko-KR')+'원':'금액 미확인';
const flow=window.MVP3LiveFlow.createFlow(A,{onChange:render}),state=flow.state;
let lastScreen=null,chatPreference=null,noticeTimer,retryTimer,lastMessages='',enteringRoute=true;
const draft={version:1,start_mode:null,usage_choice:null,budget_won:null,budget_bound:null,draft_text:'',draft_edited:false};
const ui={surface:!location.hash||location.hash==='#start'?'gateway':location.hash==='#purpose'?'usage':'consultation',epoch:window.crypto.randomUUID?window.crypto.randomUUID():Array.from(window.crypto.getRandomValues(new Uint32Array(4)),x=>x.toString(16)).join('-')};
const workspace=$('.workspace'),gateway=document.createElement('main'),toolbar=document.createElement('nav');
gateway.id='gateway-root';gateway.className='gateway-root';gateway.setAttribute('aria-label','시작방식 선택');
toolbar.className='gateway-route-toolbar';toolbar.setAttribute('aria-label','시작 경로');
workspace.before(gateway,toolbar);
const productsButton=document.createElement('button');productsButton.type='button';productsButton.dataset.action='gateway-products';productsButton.className='gateway-products';productsButton.textContent='상품 보기';$('.topbar nav').prepend(productsButton);
$('.brand').dataset.action='gateway';
const usageLabels={game:'게임',edit:'영상 편집',office:'사무',unknown:'아직 모르겠어요'};
const screenNames=['welcome','results','detail','final','saved'];
function draftSummary(){return (usageLabels[draft.usage_choice]||'용도 미정')+' · '+(draft.budget_won?draft.budget_won/10000+'만원 이하':'예산 미정');}
function generatedDraft(){
  const known=draft.usage_choice&&draft.usage_choice!=='unknown';
  if(!known&&draft.budget_won===null)return '어떤 PC가 좋을지 함께 정하고 싶어요.';
  return (known?(draft.usage_choice==='office'?'문서 작업과 일상 업무':usageLabels[draft.usage_choice])+'에 쓸 PC를 찾고 있어요.':'어떤 PC가 좋을지 함께 정하고 싶어요.')+' '+(draft.budget_won===null?'예산은 아직 정하지 않았어요.':'예산은 '+draft.budget_won/10000+'만원 이하예요.');
}
function captureDraft(){draft.draft_text=$('#request').value;}
function setDraft(text,edited=false){draft.draft_text=text;draft.draft_edited=edited;$('#request').value=text;}
function refreshDraft(){if(!draft.draft_edited)setDraft(generatedDraft());}
function uiHash(){return ui.surface==='gateway'?'#start':ui.surface==='usage'?'#purpose':'#'+state.screen;}
function uiEntry(){return {screen:state.screen,surface:ui.surface,ui_epoch:ui.epoch};}
function showSurface(surface,{push=true,focus=true}={}){
  captureDraft();
  if(ui.surface===surface){render();if(focus)focusSurface();return;}
  // Direct #welcome and actual result entries also need a UI-only return anchor
  // before opening gateway/usage; otherwise Back delegates to cancel/navigate.
  if(push)history.replaceState(uiEntry(),'',location.hash);
  ui.surface=surface;
  if(push)history.pushState(uiEntry(),'',uiHash());
  render();if(focus)focusSurface();
}
function focusSurface(){
  if(ui.surface==='consultation'){chatPreference=true;syncChat();if(!state.phase)$('#request').focus({preventScroll:true});else view.querySelector('h2')?.focus({preventScroll:true});}
  else{gateway.querySelector('h1')?.focus({preventScroll:true});window.scrollTo(0,0);}
}
function renderGateway(){
  const icon=name=>uiIcon(name),arrow=icon('arrow-right');
  if(ui.surface==='gateway')gateway.innerHTML='<section class="gateway-screen"><div class="gateway-intro"><h1 tabindex="-1"><span>어디서부터</span> 시작할까요?</h1><p>용도를 고르며 시작하거나,<br class="mobile-break"> 원하는 조건을 바로 이야기해 주세요.</p></div><div class="gateway-choices">'+
    [['game-controller','용도부터 시작하기','게임, 작업, 일상 중 필요한 용도부터 골라요.','예산은 아직 몰라도 괜찮아요.','gateway-use'],['chat-circle','바로 상담하기','원하는 사양이나 조건을 자유롭게 이야기해 주세요.','생각해 둔 조건부터 말해 주세요.',DIRECT_ACTION]].map(([image,title,text,small,action])=>button(uiIcon(image,'entry-icon')+'<h2>'+title+'</h2><p>'+text+'</p><small>'+small+'</small><span class="entry-action">'+title+' '+arrow+'</span>',action,'entry-card')).join('')+'</div><p class="change-note">선택한 방식은 언제든 바꿀 수 있어요.</p>'+(draft.draft_text||state.talk?button('작성하던 상담 이어가기 '+arrow,'gateway-continue','continue-draft'):'')+'</section>';
  else gateway.innerHTML=button(icon('arrow-left')+' 처음으로 돌아가기','gateway','route-back')+'<section class="purpose-layout"><div class="purpose-controls"><h1 tabindex="-1">어떤 일에 쓸 PC인가요?</h1><p class="purpose-description">부품 이름보다, 하고 싶은 일부터 시작하세요.</p><fieldset><legend class="sr-only">PC 용도</legend><div class="usage-grid">'+
    [['game','game-controller','즐겨 하는 게임에 쓸 PC예요.'],['edit','video-camera','영상 편집과 작업에 쓸 PC예요.'],['office','monitor','문서 작업과 일상 업무에 써요.'],['unknown','question','어떤 용도가 좋을지 함께 정해요.']].map(([value,image,text])=>button(icon(image)+'<strong>'+usageLabels[value]+'</strong><span>'+text+'</span>','gateway-usage','','data-usage="'+value+'" aria-pressed="'+(draft.usage_choice===value)+'"')).join('')+'</div></fieldset><div class="budget-controls"><label for="gateway-budget">예산은 어느 정도인가요?</label><select id="gateway-budget"><option value="">예산 미정도 괜찮아요</option>'+[100,150,200,250].map(n=>'<option value="'+n+'" '+(draft.budget_won===n*10000?'selected':'')+'>'+n+'만원 이하</option>').join('')+'</select></div><p class="condition-summary" aria-live="polite">'+draftSummary()+'</p>'+button('이 조건으로 상담 시작 '+arrow,'gateway-begin','gateway-button')+'</div><figure class="purpose-image"><img src="assets/gateway-pc-example.png" alt="PC 본체 예시 이미지"><figcaption>예시 이미지 · 실제 추천 상품과 다를 수 있어요.</figcaption></figure></section>';
  gateway.insertAdjacentHTML('beforeend','<footer class="gateway-footer"><span class="gateway-brand"><img src="assets/popcorn-mark.png" alt=""><strong>팝콘AI</strong></span><small>나에게 맞는 PC를 함께 찾아요.</small></footer>');
}
function renderSurface(){
  const consultation=ui.surface==='consultation';document.body.dataset.surface=ui.surface;workspace.hidden=!consultation;gateway.hidden=consultation;toolbar.hidden=!consultation||state.screen==='results';
  $('.topbar [data-action="new"]').hidden=!consultation;productsButton.hidden=consultation;
  if(!consultation)renderGateway();
  toolbar.innerHTML=(draft.start_mode==='use_first'?button(uiIcon('arrow-left')+' 용도 선택으로 돌아가기','gateway-use',''):'<span></span>')+button('시작방식 바꾸기','gateway','');
  if(consultation&&(draft.start_mode==='use_first'||draft.usage_choice||draft.budget_won))view.insertAdjacentHTML('afterbegin','<section class="draft-context"><strong>상담 초안</strong><p>'+draftSummary()+'</p><p>선택한 조건을 입력창에서 확인하고 수정해 주세요.</p>'+button('선택 조건으로 초안 바꾸기','gateway-rebuild','',''+(state.phase?'disabled':''))+'</section>');
}
function notice(text){$('#notice').textContent=text;$('#notice').hidden=false;clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>$('#notice').hidden=true,7000);}
function budget(product,talk=state.selectionState||state.talk){
  const won=talk?.budget_won;
  if(!Number.isInteger(product.price)||!Number.isInteger(won))return '예산 조건 미확인';
  if(talk.budget_bound==='이상')return '입력하신 최소 예산 '+money(won);
  const delta=won-product.price;
  return delta>0?'예산보다 '+money(delta)+' 낮아요':delta<0?'예산보다 '+money(-delta)+' 높아요':'예산과 같아요';
}
// 예산 초과 색은 문구(budget)와 같은 금액·같은 기준으로 정한다. 부품을 바꾸면 서버의 over_budget 은
// 기본 구성 금액 기준이라 낡으므로, 바꾼 구성은 새 금액으로 다시 센다(하한 「이상」은 초과가 없다).
function overBudget(product,talk=state.selectionState||state.talk){
  if(!product.build)return product.over_budget===true;
  const won=talk?.budget_won;
  return Number.isInteger(product.price)&&Number.isInteger(won)&&talk.budget_bound!=='이상'&&product.price>won;
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
  if(!state.error)return '';
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
    (product.over_budget?'<p class="warn-text">'+esc(budget(product,state.talk))+'</p>':'')+
    button(strong?'추천 견적 자세히 보기'+uiIcon('arrow-right'):'구성 자세히 보기',action,(strong?'primary':'outline')+' card-detail','data-id="'+esc(id)+'"')+'</section>';
}
// 새로 나온 PC(부품 상품화 5단계): 운영자가 부품을 골라 만든 조립PC. 몰 카드와 따로 두고 「새로 나온 PC」 화면으로 보낸다.
// 용도 적합도는 서버 판정(fit · 정보 없음)을 그대로 적는다 — 정보가 없어도 숨기지 않는다(2026-10-10 결정).
function customCards(group){
  if(!group.custom?.length)return '';
  return '<section class="custom-pc-group" aria-label="새로 나온 PC"><h4>새로 나온 PC · 팝콘PC가 부품을 골라 만든 조립PC</h4><div class="quote-cards">'+group.custom.map(c=>
    '<section class="quote-card live-product-card custom-pc-card" data-custom-pc="'+esc(c.configuration_id)+'"><span class="pill">새로 나온 PC</span><h3>'+esc(c.title)+'</h3>'+
    '<strong class="price">'+money(c.price)+'</strong><p class="muted">'+esc(c.price_note)+'</p>'+
    '<p class="custom-pc-fit">용도 적합도: '+esc(c.fit==='fit'?c.level_text:'정보 없음')+'</p>'+
    (c.parts.length?'<dl class="live-card-spec">'+c.parts.map(x=>'<div><dt>'+esc(x.slot_label)+'</dt><dd>'+esc(x.name)+(x.quantity>1?' × '+x.quantity:'')+'</dd></div>').join('')+'</dl>':'')+
    '<a class="outline card-detail custom-pc-link" href="'+esc(c.url)+'">자세히 보기 · 구매 상담</a></section>').join('')+'</div></section>';
}
function renderResults(){
  const groups=state.groups,hasProducts=groups.some(g=>g.products.length);
  const gameLabels=[['spec_summary','게임 사양 안내'],['why_this_pc','PC 선택 안내'],['upgrade_hint','업그레이드 안내'],['caution','확인할 내용']];
  const products=groups.flatMap(g=>g.products),withinBudget=Number.isInteger(state.talk?.budget_won)&&state.talk.budget_bound!=='이상'&&products.every(p=>!p.over_budget);
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
function productSummary(){
  const p=state.selected,description=p.public_configuration?.description,title=description?.title||p.name;
  const intro=state.savedQuote?'금액과 상품 기록은 보관 시점 기준입니다. 부품 구성과 사진은 조회 시점의 공개 상태를 따릅니다.':description?.intro||p.reasons[0]||p.tag||p.level||'판매 중인 완제품 구성입니다.';
  return '<section class="final-summary live-summary"><div class="live-summary-copy"><h3>'+esc(title)+'</h3>'+(title!==p.name?'<p class="live-product-name">'+esc(p.name)+'</p>':'')+'<p>'+esc(intro)+'</p></div><div class="final-summary-price"><strong>'+money(p.price)+'</strong>'+(p.build?'<p class="muted">부품 '+p.build.changes.length+'개를 바꾼 금액이에요 · 기본 구성 대비 '+signedMoney(p.price-p.build.base_price)+'</p>'+(p.build.warnings||[]).map(w=>'<p class="warn-text">'+esc(w)+'</p>').join(''):'')+'<p class="'+(overBudget(p)?'warn-text':'green')+'">'+esc(budget(p))+'</p>'+'</div>'+productImage(p,true)+'</section>';
}
function publicBomDetails(configuration,p,information,finalOnly){
  const roles={
    CPU:['CPU','cpu','프로그램의 명령을 계산하고 처리하는 부품이에요.'],
    GPU:['그래픽카드','graphics-card','게임 화면과 그림을 출력하는 부품이에요.'],
    RAM:['메모리','memory','실행 중인 프로그램의 정보를 잠시 담아두는 부품이에요.'],
    SSD:['저장장치','hard-drive','게임과 파일을 저장하는 부품이에요.'],
    HDD:['저장장치','hard-drive','게임과 파일을 저장하는 부품이에요.'],
    MB:['메인보드','gear','CPU와 메모리 등 여러 부품을 연결하는 부품이에요.'],
    PSU:['파워','plug','각 부품에 전원을 공급하는 부품이에요.'],
    CASE:['케이스','computer-tower','부품을 담고 공기가 흐를 공간을 만드는 부품이에요.']};
  const rows=configuration.parts.map(part=>{
    const [label,icon,role]=(Object.hasOwn(roles,part.slot)?roles[part.slot]:null)||[part.pseudo?'서비스':part.slot,'gear','등록된 사양과 설명을 확인해주세요.'];
    const id='bom-unavailable-'+part.ordinal,swap=!part.pseudo,change=p.build?.changes.find(c=>c.ordinal===part.ordinal);
    const open=state.build?.ordinal===part.ordinal;
    if(change)return buildChangedRow(part,label,icon,change,finalOnly,open);
    const specs=part.specs.length?'<dl class="live-spec-grid">'+part.specs.map(x=>'<div><dt>'+esc(x.label)+'</dt><dd>'+esc(x.value.trim()||'정보 없음')+'</dd></div>').join('')+'</dl>':'<p>정보 없음</p>';
    return '<tr data-part="bom-'+part.ordinal+'"><td colspan="3"><details class="public-bom-disclosure" data-detail="bom-'+part.ordinal+'"><summary>'+
      '<div class="final-part-description">'+uiIcon(icon,'part-symbol')+'<div><h4><span>'+esc(label)+'</span><span class="part-name">'+esc(part.name||'정보 없음')+'</span><span class="public-bom-quantity">수량 '+part.quantity+'</span></h4><p>'+esc(part.description||'정보 없음')+'</p>'+
      '<span class="public-bom-toggle"><span class="when-closed">상세 사양 펼치기</span><span class="when-open">상세 사양 접기</span>'+uiIcon('caret-down')+'</span></div></div>'+
      '<span class="final-part-price">미확인</span><span class="final-part-change">'+changeButton(part,label,finalOnly,open,id)+'</span></summary><div class="final-part-expanded public-bom-expanded">'+
      (part.photo?.state==='approved'?'<figure class="public-bom-photo" data-product-photo><img data-product-image src="'+esc(part.photo.url)+'" alt="'+esc(part.name||label)+' 부품 사진" loading="lazy" decoding="async"><p class="live-product-image-status" data-product-image-status hidden>부품 사진을 불러오지 못했습니다</p></figure>':'<div class="public-bom-photo">정보 없음</div>')+'<div class="public-bom-specs">'+specs+'</div><div class="public-bom-role"><h5>이 부품의 역할</h5><p>'+esc(role)+'</p>'+button(uiIcon('chat-circle')+'이 부품 질문하기','unavailable','outline small','disabled aria-describedby="'+id+'"')+
      '<p class="public-bom-unavailable" id="'+id+'">'+(swap?(finalOnly?'부품 질문은 아직 지원하지 않아요. 부품은 「상품 상세 다시 보기」에서 바꿀 수 있어요.':'부품 질문은 아직 지원하지 않아요. 이 부품은 오른쪽 「변경」으로 바꿀 수 있어요.'):'부품 질문은 아직 지원하지 않아요. 이 줄은 바꿀 수 없어요.')+'</p></div></div></details></td></tr>'+(open?buildRow():'');
  }).join('');
  const b=p.build,foot=b?'<tr><th scope="row">기본 구성 금액</th><td colspan="2">'+money(b.base_price)+'</td></tr><tr><th scope="row">부품 변경</th><td colspan="2">'+signedMoney(p.price-b.base_price)+'</td></tr><tr><th scope="row">바꾼 구성 금액</th><td colspan="2">'+money(p.price)+'</td></tr>'
    :'<tr><th scope="row">상품 참고 금액</th><td colspan="2">'+money(p.price)+'</td></tr>';
  return '<section class="final-parts public-bom"><h3>부품 구성과 선택 이유</h3><div class="final-table-wrap"><table class="final-table"><colgroup><col class="part-description-col"><col class="part-price-col"><col class="part-action-col"></colgroup>'+
    '<thead><tr><th scope="col">부품 · 등록 사양</th><th scope="col">금액</th><th scope="col">변경</th></tr></thead><tbody>'+rows+'</tbody><tfoot>'+foot+'</tfoot></table></div></section>'+
    (finalOnly?'<details class="public-bom-information" data-detail="spec"><summary>추천 근거·변경 안내 펼치기</summary><div class="final-part-expanded">'+information+'</div></details>':information);
}
// 부품 직접 바꾸기(api/mvp3_build): 공개된 구성표의 줄마다 「변경」. 호환 규칙을 통과한 판매 부품만,
// 금액은 서버가 다시 계산한 값만 쓴다(화면이 더하지 않는다). 가상 줄(조립비 등)은 바꾸지 않는다.
function changeButton(part,label,finalOnly,open,id){
  if(part.pseudo||finalOnly)return button('변경','unavailable','outline small','disabled aria-describedby="'+id+'"');
  return button('변경','build-options','outline small'+(open?' is-active':''),'data-ordinal="'+part.ordinal+'" aria-expanded="'+open+'" aria-label="'+esc(label)+' 바꾸기"'+(state.phase?' disabled':''));
}
function buildChangedRow(part,label,icon,c,finalOnly,open){
  const id='bom-unavailable-'+part.ordinal;
  return '<tr data-part="bom-'+part.ordinal+'" class="build-changed"><td colspan="3"><details class="public-bom-disclosure" data-detail="bom-'+part.ordinal+'"><summary>'+
    '<div class="final-part-description">'+uiIcon(icon,'part-symbol')+'<div><h4><span>'+esc(label)+'</span><span class="part-name">'+esc(c.after.name)+'</span><span class="public-bom-quantity">수량 '+c.quantity+'</span></h4>'+
    '<p class="build-changed-note">바꾼 부품 · 원래 부품: '+esc(c.before.name)+'</p>'+
    '<span class="public-bom-toggle"><span class="when-closed">상세 펼치기</span><span class="when-open">상세 접기</span>'+uiIcon('caret-down')+'</span></div></div>'+
    '<span class="final-part-price">'+signedMoney(c.delta)+'</span><span class="final-part-change">'+changeButton(part,label,finalOnly,open,id)+'</span></summary><div class="final-part-expanded public-bom-expanded">'+
    '<p id="'+id+'">부품 판매가 '+money(c.after.price)+' · 원래 부품 '+money(c.before.price)+'. 바꾼 부품의 설명과 사진은 아직 준비되지 않았어요.</p></div></details></td></tr>'+(open?buildRow():'');
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
  if(!d.options.length)return '<div class="part-options" role="status">'+head+'<p>지금 이 PC에 맞는 다른 판매 부품이 없어요.</p>'+untested+'</div>';
  return '<div class="part-options">'+head+'<p class="'+(warned?'warn-text':'muted')+'">'+esc(d.note||(warned?d.warnings.join(' '):'호환 규칙을 통과한 판매 중 부품만 보여 드려요.'))+'</p>'+untested+'<ul class="part-option-list">'+
    d.options.map(o=>'<li class="part-option" data-build-option="'+o.product_code+'"><div class="part-option-copy"><strong>'+esc(o.name)+'</strong><span class="part-option-name">부품 판매가 '+money(o.price)+'</span></div>'+
      '<div class="part-option-price"><strong>'+money(o.total)+'</strong><span class="'+(o.price_diff>0?'warn-text':'green')+'">'+signedMoney(o.price_diff)+'</span>'+
      button('이걸로 바꾸기','build-pick','primary small','data-code="'+o.product_code+'"'+(state.phase?' disabled':''))+'</div></li>').join('')+'</ul></div>';
}
// 부품 바꾸기(api/mvp3_part_options): 고른 판매 PC 에서 그 부품만 다른 판매 PC 를 고른다.
// 금액·차액·함께 바뀌는 것은 서버가 준 값만 쓴다. 상품 상세에서만 바꾼다(최종 견적은 안내만).
const SWAP_OF={CPU:'cpu',GPU:'gpu',RAM:'ram',SSD:'ssd'};
const SWAP_BUTTONS=[['cpu','CPU','cpu'],['gpu','그래픽카드','graphics-card'],['ram','메모리','memory'],['ssd','저장장치','hard-drive']];
function signedMoney(d){return d===0?'같은 금액':(d>0?'+':'-')+Math.abs(d).toLocaleString('ko-KR')+'원';}
function partOptionsPanel(){
  const q=state.parts;if(!q?.slot)return '';
  const name=(SWAP_BUTTONS.find(x=>x[0]===q.slot)||[])[1]||q.slot;
  const head='<div class="part-options-head"><h4>'+esc(name)+' 바꾸기'+(q.data?.current?' · 지금 '+esc(q.data.current):'')+'</h4>'+button('닫기','part-close','text-button')+'</div>';
  if(state.phase==='parts')return '<div class="part-options" role="status">'+head+'<p class="muted">판매 중인 PC에서 선택지를 찾는 중이에요.</p></div>';
  if(q.error)return '<div class="part-options" role="alert">'+head+'<p class="warn-text">'+esc(q.error)+'</p>'+button('다시 찾기','part-options','outline small','data-slot="'+q.slot+'"')+'</div>';
  if(!q.data)return '';
  if(!q.data.options.length)return '<div class="part-options" role="status">'+head+'<p>지금 판매 중인 PC 중에는 '+esc(name)+'만 다른 구성이 없어요. 원하는 조건을 상담창에 말씀해 주시면 다시 찾아 드려요.</p></div>';
  return '<div class="part-options">'+head+'<p class="muted">몰에서 조립해 파는 PC 중 '+esc(name)+'만 다른 것을 보여 드려요. 호환이 확인된 구성이고, 금액은 그 PC의 판매가예요.</p><ul class="part-option-list">'+
    q.data.options.map(o=>'<li class="part-option" data-part-option="'+o.product_code+'"><div class="part-option-copy"><strong>'+esc(o.swap.value)+'</strong><span class="part-option-name">'+esc(o.name)+'</span>'+
      o.swap.also.map(x=>'<span class="part-option-also">'+esc(x.label)+'도 함께 바뀌어요: '+esc(x.from)+'에서 '+esc(x.to)+'로</span>').join('')+
      (o.over_budget?'<span class="warn-text">예산을 넘어요</span>':'')+'</div><div class="part-option-price"><strong>'+money(o.price)+'</strong><span class="'+(o.swap.price_diff>0?'warn-text':'green')+'">'+signedMoney(o.swap.price_diff)+'</span>'+
      button('이걸로 바꾸기','part-swap','primary small','data-code="'+o.product_code+'"'+(state.phase?' disabled':''))+'</div></li>').join('')+'</ul></div>';
}
function partChange(finalOnly,configured){
  if(configured){
    const p=state.selected,b=p.build;
    return '<section class="live-capabilities" id="part-change"><h3>부품 바꾸기</h3><p>'+(finalOnly?'부품은 「상품 상세 다시 보기」에서 바꿀 수 있어요.':'부품 구성 표의 「변경」을 누르면 이 PC에 맞는 판매 부품을 보여 드려요. 호환 규칙을 통과한 부품만 나오고, 금액은 PC 판매가에 부품 가격 차이를 더해 다시 계산해요.')+'</p>'+
      (b?'<p>바꾼 부품 '+b.changes.length+'개 · 기본 구성 '+money(b.base_price)+'에서 '+signedMoney(p.price-b.base_price)+'</p>'+(finalOnly?'':button('원래 구성으로','build-reset','outline small',state.phase?'disabled':'')):'')+'</section>';
  }
  if(finalOnly)return '<section class="live-capabilities" id="part-change"><h3>부품 바꾸기</h3><p>CPU·그래픽카드·메모리·저장장치는 「상품 상세 다시 보기」에서 바꿀 수 있어요. 바꾸면 그 구성으로 판매 중인 PC로 옮기고, 견적을 다시 보관해요.</p></section>';
  return '<section class="live-capabilities" id="part-change"><h3>부품 바꾸기</h3><p>바꾸고 싶은 부품을 고르세요. 그 부품만 다른 판매 중인 PC를 찾아 드려요. 게임 FPS 비교 자료는 아직 제공되지 않아요.</p><div>'+
    SWAP_BUTTONS.map(([slot,label,icon])=>button(uiIcon(icon)+label+' 바꾸기','part-options','outline small'+(state.parts?.slot===slot?' is-active':''),'data-slot="'+slot+'" aria-expanded="'+(state.parts?.slot===slot)+'"'+(state.phase?' disabled':''))).join('')+'</div>'+partOptionsPanel()+'</section>';
}
function productDetails(finalOnly=false){
  const p=state.selected;
  // Read only the selected recommendation group; saved/recovery records have no game-context contract.
  const context=state.savedQuote||state.pendingSave?null:(state.selectedContext||(state.groups||[]).find(g=>Number.isInteger(p.index)&&g.products.some(item=>item.index===p.index&&item.product_code===p.product_code)));
  const ctx=context?.game_context,url=M.safeUrl(ctx?.source.url);
  const gameLabels=[['spec_summary','게임 사양 안내'],['why_this_pc','PC 선택 안내'],['upgrade_hint','업그레이드 안내'],['caution','확인할 내용']];
  const rows=M.specRows(p.spec),spec=rows.length?'<dl class="live-spec-grid">'+rows.map(([label,value])=>'<div><dt>'+esc(label)+'</dt><dd>'+esc(value)+'</dd></div>').join('')+'</dl>':'<p class="live-full-spec">'+esc(M.specText(p.spec)||'등록된 상세 사양을 확인하지 못했어요.')+'</p>';
  const information=
    '<section class="live-explanation"><h3>이 상품을 추천한 이유</h3>'+
    '<p class="muted">상담 조건: '+M.conditions(state.selectionState||state.talk).map(esc).join(' · ')+'</p>'+
    (p.reasons.length?'<ul>'+p.reasons.map(r=>'<li>'+esc(r)+'</li>').join(''):'<p>추천 이유가 제공되지 않았어요.</p>')+'</section>'+
    (ctx?'<section class="live-explanation"><h3>게임 안내 · '+esc(ctx.game_name)+'</h3><ul>'+gameLabels.filter(([key])=>ctx[key]).map(([key,label])=>'<li><strong>'+label+': </strong>'+esc(ctx[key])+'</li>').join('')+'</ul>'+(url?'<p class="muted"><a href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">자세히 보기</a></p>':'')+'</section>':'')+
    partChange(finalOnly,!!M.publicConfiguration(p.public_configuration,p.product_code));
  const configuration=M.publicConfiguration(p.public_configuration,p.product_code);
  if(configuration)return publicBomDetails(configuration,p,information,finalOnly);
  return '<section class="final-parts"><h3>부품 구성과 선택 이유</h3><p class="public-bom-empty" role="status">부품 구성 정보는 아직 연결되지 않았어요. 등록된 완제품 사양을 먼저 확인해주세요.</p><div class="final-table-wrap"><table class="final-table"><colgroup><col class="part-description-col"><col class="part-price-col"><col class="part-action-col"></colgroup>'+
    '<thead><tr><th scope="col">상품 · 등록 사양</th><th scope="col">금액</th><th scope="col">변경</th></tr></thead><tbody><tr data-part="pc"><td><div class="final-part-description">'+uiIcon('computer-tower','part-symbol')+
    '<div><h4><span>조립 PC</span><span class="part-name">'+esc(p.name)+'</span></h4><p>등록된 판매 상품의 구성입니다.</p><details data-detail="spec"><summary><span class="when-closed">'+(finalOnly?'상세 사양·추천 근거·변경 안내 펼치기':'상세 사양 펼치기')+'</span><span class="when-open">'+(finalOnly?'상세 사양·추천 근거·변경 안내 접기':'상세 사양 접기')+'</span>'+uiIcon('caret-down')+'</summary><div class="final-part-expanded">'+spec+(finalOnly?information:'')+'</div></details></div></div></td><td class="final-part-price">'+money(p.price)+'</td><td class="final-part-change"><span aria-label="부품 변경 미지원">-</span></td></tr></tbody>'+
    '<tfoot><tr><th scope="row">상품 참고 금액</th><td colspan="2">'+money(p.price)+'</td></tr></tfoot></table></div></section>'+(finalOnly?'':information);
}
function finalConditions(){
  const row=(name,label,text)=>'<div>'+uiIcon(name)+'<dt>'+label+'</dt><dd>'+esc(text)+'</dd></div>';
  return '<section class="final-conditions"><h3>구매 전 확인할 내용</h3><div class="final-conditions-grid"><dl>'+
    row('gear','호환성','실제 조립 검수 결과는 확인되지 않았어요.')+row('tag','가격',state.savedQuote?'보관 시점 참고 금액 · 확정가 아님':state.selected.price_src||'가격 기준 미확인')+
    row('package','재고','재고 확보 전 · 구매 전 확인')+'</dl><dl>'+row('squares-four','운영체제','포함 여부 재확인 필요')+
    row('monitor','키보드 · 마우스 · 모니터','포함 여부 미확인')+row('shield','보증','기간 · 범위 재확인 필요')+'</dl></div></section>';
}
function renderDetail(){
  view.innerHTML=heading('추천 구성 상세')+errorPanel()+productSummary()+productDetails()+finalConditions();
  const p=state.selected;
  actions.innerHTML='<div><span>조회 시점 참고 금액</span><strong>'+money(p.price)+'</strong></div><div class="footer-buttons">'+button('부품 바꾸기','part-focus','outline')+button('이 견적 저장하기','final','primary')+'</div>';actions.hidden=false;
}
// 보관하는 순간의 쇼핑몰 현재가 확인(api/mall_price_live). 같으면 말하지 않고, 바뀌었거나 못 읽었으면 서버 문장을 그대로 보인다.
function priceCheckPanel(){
  const q=state.savedQuote,c=q&&state.saveState==='saved'&&!(state.handoff&&state.handoff.quote_id===q.id)?q.price_check:null;
  if(!c||c.status==='same'||!c.message)return '';
  return '<section class="live-explanation live-price-check" role="status" data-price-check="'+esc(c.status)+'"><h3>'+(c.status==='changed'?'쇼핑몰 가격이 바뀌었어요':'쇼핑몰 가격 확인')+'</h3><p>'+esc(c.message)+'</p></section>';
}
// Mall handoff result (api/mvp3_handoff.py). Price differences are told, never hidden.
function handoffPanel(h){
  const changed=h.status==='가격변동'&&Number.isInteger(h.price_mall),soldout=h.status==='품절',unknown=h.status==='확인못함';
  const line=changed?'쇼핑몰 현재 가격은 '+money(h.price_mall)+'이에요. 보관한 금액('+money(h.price_quoted)+')과 달라 보관 견적을 쇼핑몰 가격으로 고쳤어요. 결제 금액은 쇼핑몰에서 최종 확인해 주세요.':
    soldout?'쇼핑몰에서 지금 품절로 표시돼요. 구매 전에 쇼핑몰에서 재고를 확인해주세요.':
    unknown?'현재 가격 확인이 안 되어 쇼핑몰에서 최종 확인됩니다.':
    '쇼핑몰 가격도 '+money(h.price_quoted)+'으로 같아요.';
  return '<section class="live-explanation live-handoff" role="status"><h3>팝콘PC 쇼핑몰로 연결할 준비가 됐어요</h3><p>'+esc(line)+'</p>'+
    '<p><a class="primary" href="'+esc(h.mall_url)+'" target="_blank" rel="noopener noreferrer">쇼핑몰 상품 페이지 열기</a></p>'+
    (h.changes?'<p class="warn-text">쇼핑몰 상품 페이지는 기본 구성 기준이에요. 바꾼 부품 '+h.changes+'개(차액 '+esc(signedMoney(h.delta))+')는 연결 번호 '+esc(h.handoff_no)+'로 기록해 두었어요. 주문할 때 요청사항에 이 번호를 적어 주세요.</p>':'')+
    '<p class="muted">연결 번호 '+esc(h.handoff_no)+' · 결제·배송·보증은 쇼핑몰에서 안내해요.</p></section>';
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
function renderFinal(){
  const handoffDone=!!(state.handoff&&state.savedQuote&&state.handoff.quote_id===state.savedQuote.id);
  const label={idle:'아직 보관 전',saving:'보관 확인 중',saved:'서버에 보관됨',uncertain:'보관 결과 미확인',failed:'보관되지 않음'};
  const saved=state.saveState==='saved',disabled=!!state.phase||saved||state.needsRefresh||state.selected.price===null||!!state.pendingSave||!!state.pendingProblem;
  view.innerHTML=button(uiIcon('arrow-left')+'상품 상세 다시 보기','edit','back final-back')+
    '<div class="final-title-row"><div><h2 tabindex="-1">최종 견적 확인</h2><span class="save-status '+(saved?'is-saved':'')+'">'+uiIcon(saved?'file-text':'warning-circle-fill')+label[state.saveState]+'</span></div><span class="data-note">보관은 상품·시점 가격의 참고 기록입니다.</span></div>'+
    errorPanel()+priceCheckPanel()+productSummary()+productDetails(true)+finalConditions()+
    '<footer class="final-footer"><p>'+uiIcon('info')+'<span>포함 품목과 보증 조건은 구매 전에 확인해주세요.</span></p><div><div class="final-buttons">'+button('다른 상품 비교','results','outline')+
    button(saved?'보관 완료':state.phase==='save'?'서버 확인 중…':state.pendingSave?'이전 보관 결과 확인 필요':'견적 보관하기','save','primary',disabled?'disabled':'')+
    (saved&&state.savedQuote&&!handoffDone?button(state.phase==='handoff'?'쇼핑몰 가격 확인 중…':'팝콘PC 쇼핑몰에서 구매하기','handoff','primary',state.phase?'disabled':''):'')+
    '</div><small>'+(saved?'결제와 배송은 팝콘PC 쇼핑몰에서 진행돼요. 이 화면에서는 결제하지 않아요.':'주문 · 결제 · 가격 확정 · 재고 확보는 진행되지 않습니다. 견적을 보관하면 팝콘PC 쇼핑몰 구매로 이어갈 수 있어요.')+'</small></div></footer>'+
    (handoffDone?handoffPanel(state.handoff):'')+
    (!state.inquiry.open&&!state.inquiry.done?'<p class="live-inquiry-open">'+button('여러 대 · 할인 · 세금계산서는 구매 상담 신청','inquiry-open','outline',state.phase?'disabled':'')+'</p>':'')+
    inquiryPanel()+
    (state.savedQuote?'<p class="muted live-saved-note">보관일 '+esc(new Date(state.savedQuote.saved_at).toLocaleString('ko-KR'))+' · 이 브라우저의 보관 키로 접근합니다.</p>':'');
  actions.hidden=true;
}
function renderSaved(){
  view.innerHTML=heading('내 견적',false)+'<p class="muted">이 브라우저의 보관 키로 접근하는 서버 기록입니다. 다른 기기나 회원 계정에서는 이 보관 기록을 이어 볼 수 없어요.</p>'+errorPanel()+
    (state.phase==='list'?'<div class="empty small-empty"><p>보관 기록을 불러오는 중이에요.</p></div>':state.error?'':state.quotes.length?
      '<div class="quote-cards">'+state.quotes.map(q=>'<section class="quote-card live-product-card">'+productImage(q.product)+'<span class="pill">보관 시점 기록</span><h3>'+esc(q.product.name)+'</h3><strong class="price">'+money(q.product.price)+'</strong><p>'+esc(new Date(q.saved_at).toLocaleString('ko-KR'))+'</p>'+button('보관 견적 보기','load','primary','data-id="'+esc(q.id)+'"')+'</section>').join('')+'</div>':
      '<div class="empty small-empty"><h3>보관된 견적이 없어요</h3><p>상담 후 상품을 선택하면 서버에 보관할 수 있어요.</p>'+button('상담으로 돌아가기','back','outline')+'</div>')+
    (state.hasMore?'<p class="muted">최근 20개의 보관 기록을 표시하고 있어요.</p>':'');
  actions.hidden=true;
}
function renderWelcome(){view.innerHTML=`<header class="welcome-heading"><h2 tabindex="-1">나에게 맞는 PC</h2><p>말씀해주신 조건에 맞춰 이곳에 견적을 정리해드려요.</p></header><section class="welcome-card"><div class="welcome-illustration"><img src="assets/welcome-pc.png" alt="옅은 민트색 PC 본체 일러스트"></div><h3>어떤 PC가 필요한지 들려주세요</h3><p class="welcome-subtitle">게임과 예산만 알려주셔도 시작할 수 있어요.</p><ol class="welcome-steps"><li><span class="step-icon">${uiIcon('chat-circle')}</span><h4>원하는 조건 말하기</h4><p>게임, 예산, 용도 등을<br>자유롭게 말씀해주세요.</p>${uiIcon('arrow-right','step-arrow')}</li><li><span class="step-icon">${uiIcon('file-text')}</span><h4>추천 견적 비교하기</h4><p>입력하신 조건에 맞춰<br>최적의 견적을 제안해드려요.</p>${uiIcon('arrow-right','step-arrow')}</li><li><span class="step-icon">${uiIcon('gear')}</span><h4>부품 구성 확인하기</h4><p>상세한 부품과 사양을<br>한눈에 확인할 수 있어요.</p></li></ol><p class="welcome-help">${uiIcon('info')}잘 모르는 항목은 상담하면서 정하면 돼요.</p></section>`;actions.hidden=true;}
function render(){
  const changed=lastScreen!==state.screen,openDetails=[...view.querySelectorAll('details[open]')].map(e=>e.dataset.detail),scroll=view.scrollTop,focused=document.activeElement?.dataset.action;
  const gatewayFocus=gateway.contains(document.activeElement)?{id:document.activeElement.id,usage:document.activeElement.dataset.usage,action:focused,heading:document.activeElement.tagName==='H1'}:null;
  document.body.dataset.screen=state.screen;document.body.classList.add('live-mode');document.body.classList.toggle('original-flow',['welcome','results','detail','final'].includes(state.screen));
  view.dataset.screen=state.screen;
  // 예외 입력·상담 실패 뒤에는 사람 상담 길을 연다(서버 handoff_offer). 신청 칸은 구매 상담 신청과 같다.
  const handoffBlock=()=>(state.handoffOffer||state.inquiry.open||state.inquiry.done)?
    (!state.inquiry.open&&!state.inquiry.done?'<p class="live-inquiry-open">'+button('사람 상담 남기기','inquiry-open','outline',(state.phase?'disabled ':'')+'data-human="1"')+'</p>':'')+inquiryPanel():'';
  if(state.screen==='welcome'){renderWelcome();if(state.error)view.insertAdjacentHTML('afterbegin',errorPanel());view.insertAdjacentHTML('beforeend',handoffBlock());}
  // 견적을 보던 중에 받은 예외 입력도 같은 길을 연다(보던 견적은 그대로 둔다).
  else if(state.screen==='results'){renderResults();if(state.handoffOffer)view.insertAdjacentHTML('beforeend',handoffBlock());}
  // 상세를 보던 중에도 같은 길을 연다(코덱스 PR136 검수 「상세 화면의 상담 버튼」).
  else if(state.screen==='detail'&&state.selected){renderDetail();if(state.handoffOffer)view.insertAdjacentHTML('beforeend',handoffBlock());}
  else if(state.screen==='final'&&state.selected)renderFinal();
  else if(state.screen==='saved')renderSaved();
  const recovery=recoveryBanner();if(recovery)view.insertAdjacentHTML('afterbegin',recovery);
  renderMessages();syncChat();renderSurface();
  if(ui.surface==='consultation'){
    if(!changed){for(const e of view.querySelectorAll('details'))if(openDetails.includes(e.dataset.detail))e.open=true;view.scrollTop=scroll;if(focused)[...document.querySelectorAll('[data-action]')].find(e=>e.dataset.action===focused&&!e.disabled)?.focus({preventScroll:true});}
    else{view.scrollTop=0;view.querySelector('h2')?.focus({preventScroll:true});if(mobile.matches)window.scrollTo(0,0);}
    if(!enteringRoute&&lastScreen!==state.screen&&location.hash!=='#'+state.screen)history.pushState({screen:state.screen},'','#'+state.screen);
  }else{
    if(!enteringRoute)history.replaceState(uiEntry(),'',uiHash());
    const target=gatewayFocus?.id?$('#'+gatewayFocus.id):gatewayFocus?.usage?gateway.querySelector('[data-usage="'+gatewayFocus.usage+'"]'):gatewayFocus?.action?gateway.querySelector('[data-action="'+gatewayFocus.action+'"]'):gatewayFocus?.heading?gateway.querySelector('h1'):null;
    target?.focus({preventScroll:true});
  }
  lastScreen=state.screen;
  clearTimeout(retryTimer);if(state.error?.retryAt>Date.now())retryTimer=setTimeout(()=>render(),1000);
}
function openSaved(){ui.surface='consultation';if(state.screen==='saved'&&state.phase==='list'){render();return;}void flow.list();}
function enterRoute(hash,initial=false){
  enteringRoute=true;
  try{
    if(initial)flow.reset({restore:true});
    if(initial&&(!hash||hash==='#start'||hash==='#purpose')){
      ui.surface=hash==='#purpose'?'usage':'gateway';history.replaceState(uiEntry(),'',uiHash());render();return;
    }
    ui.surface='consultation';let screen=hash.slice(1);
    if(!screenNames.includes(screen)||(['detail','final'].includes(screen)&&!state.selected)||(screen==='results'&&!state.recommendation))screen='welcome';
    if(initial||hash!=='#'+screen)history.replaceState({screen},'','#'+screen);
    if(screen==='saved')openSaved();else flow.navigate(screen);
    // 새로고침 전에 보던 견적이 있으면 같은 조건으로 다시 물어 그 상품을 다시 연다(값은 지금 기준).
    if(initial&&screen!=='saved'&&state.restoredCurrent&&state.talk)void flow.resume();
  }finally{enteringRoute=false;}
}
function back(){flow.navigate({results:'welcome',detail:'results',final:'detail',saved:state.selected?'final':state.groups.length?'results':'welcome'}[state.screen]||'welcome');}
async function submit(text,{fromInput=false}={}){if(!String(text||'').trim()){notice('원하는 조건을 입력해주세요.');$('#request').focus();return;}
  if(text.trim().length>20000){notice('한 번에 20,000자까지 보낼 수 있어요. 나눠서 보내 주세요.');return;}
  if(state.phase)return;
  const sent=text.trim();await flow.submit(text);
  // submit() also returns true after errors. Only validated conversation history
  // with no current error permits clearing the unchanged, visible input.
  if(fromInput&&ui.surface==='consultation'&&!state.error&&state.history.some(x=>x.role==='user'&&x.text===sent)&&draft.draft_text===text)setDraft('');
}
// 「바로 상담하기」는 2차 대화 화면(talk.html)으로 간다(2026-10-11 사장님 「그냥 다 풀어」).
// 이 화면의 상담(기존 상담 화면)은 지우지 않았다 -- 상단 「새 상담」과 대화 화면의 「기존 상담 화면」으로 들어온다.
// 되돌리려면 DIRECT_ACTION 을 'gateway-direct' 로 바꾼다.
document.addEventListener('click',e=>{
  const b=e.target.closest('[data-action]');if(!b||b.disabled)return;e.preventDefault();
  switch(b.dataset.action){
    case 'gateway':showSurface('gateway');break;
    case 'gateway-use':draft.start_mode='use_first';showSurface('usage');break;
    case 'gateway-direct':draft.start_mode='direct';showSurface('consultation');break;
    case 'gateway-talk':location.href='talk.html';break;
    case 'gateway-continue':showSurface('consultation');break;
    case 'gateway-usage':captureDraft();draft.usage_choice=draft.usage_choice===b.dataset.usage?null:b.dataset.usage;if(!draft.draft_edited)refreshDraft();render();gateway.querySelector('[data-usage="'+b.dataset.usage+'"]')?.focus({preventScroll:true});break;
    case 'gateway-begin':draft.start_mode='use_first';if(!draft.draft_edited)refreshDraft();showSurface('consultation');break;
    case 'gateway-rebuild':refreshDraftExplicitly();break;
    case 'gateway-products':if(state.recommendation){showSurface('consultation',{focus:false});flow.navigate('results');}else{showSurface('consultation');notice('원하는 용도와 예산을 상담창에 알려주시면 추천 상품을 확인할 수 있어요.');}break;
    case 'new':chatPreference=null;lastMessages='';Object.assign(draft,{start_mode:null,usage_choice:null,budget_won:null,budget_bound:null});setDraft('');ui.surface='consultation';flow.reset();break;
    case 'saved':captureDraft();openSaved();break;
    case 'prompt':submit(b.dataset.text);break;
    case 'explore':void flow.explore(b.dataset.dir,b.dataset.label);break;
    case 'detail':flow.select(Number(b.dataset.id));break;
    case 'final':flow.navigate('final');break;
    case 'edit':flow.navigate('detail');break;
    case 'results':flow.navigate('results');break;
    case 'back':back();break;
    case 'save':void flow.save();break;
    case 'handoff':void flow.handoff();break;
    case 'inquiry-open':void flow.openInquiry({human:b.dataset.human==='1'});break;
    case 'part-options':void flow.openParts(b.dataset.slot);break;
    case 'part-close':flow.closeParts();break;
    case 'part-swap':flow.swapPart(Number(b.dataset.code));break;
    case 'build-options':{if(b.dataset.retry)flow.state.build.error='';void flow.openBuild(Number(b.dataset.ordinal));break;}
    case 'build-close':flow.closeBuild();break;
    case 'build-pick':void flow.pickBuild(Number(b.dataset.code));break;
    case 'build-reset':void flow.resetBuild();break;
    case 'part-focus':{const s=view.querySelector('#part-change');s?.scrollIntoView({block:'start'});(s?.querySelector('button')||view.querySelector('[data-action=build-options]'))?.focus({preventScroll:true});break;}
    case 'inquiry-close':flow.inquiryDraft(inquiryValues());flow.closeInquiry();break;
    case 'inquiry-send':void flow.inquire(inquiryValues());break;
    case 'recover':void flow.recover();break;
    case 'load':flow.load(b.dataset.id);break;
    case 'retry':void flow.retry();break;
    case 'attachment':notice('파일 첨부는 아직 지원하지 않아요. 필요한 조건을 글로 알려주세요.');break;
    case 'conditions':chatPreference=true;syncChat();$('#request').focus({preventScroll:true});if(mobile.matches)$('#chat-toggle').scrollIntoView({block:'start'});notice('바꿀 예산이나 용도를 상담창에 알려주세요. 실제 추천을 다시 조회해요.');break;
  }
});
function refreshDraftExplicitly(){setDraft(generatedDraft());$('#request').focus({preventScroll:true});}
document.addEventListener('change',e=>{if(e.target.id==='gateway-budget'){captureDraft();const n=Number(e.target.value);draft.budget_won=[100,150,200,250].includes(n)?n*10000:null;draft.budget_bound=draft.budget_won===null?null:'이하';if(!draft.draft_edited)refreshDraft();render();$('#gateway-budget')?.focus({preventScroll:true});}});
// 신청 칸은 다시 그려져도 적던 값이 남게 입력마다 상태에 옮긴다(다시 그리지는 않는다).
view.addEventListener('input',e=>{if(e.target.closest?.('[data-inquiry]'))flow.inquiryDraft(inquiryValues());});
view.addEventListener('change',e=>{if(e.target.closest?.('[data-inquiry]'))flow.inquiryDraft(inquiryValues());});
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
  captureDraft();const entry=e.state;
  if(entry?.ui_epoch===ui.epoch&&['gateway','usage','consultation'].includes(entry.surface)&&screenNames.includes(entry.screen)){
    enteringRoute=true;try{ui.surface=entry.surface;render();history.replaceState(uiEntry(),'',uiHash());focusSurface();}finally{enteringRoute=false;}
  }else enterRoute(location.hash);
});
enterRoute(location.hash,true);focusSurface();
})();
