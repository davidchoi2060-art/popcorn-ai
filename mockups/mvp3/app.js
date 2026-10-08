(function(){'use strict';
const M=window.MVP3LiveModel,A=window.MVP3Api;
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
    [['game-controller','용도부터 시작하기','게임, 작업, 일상 중 필요한 용도부터 골라요.','예산은 아직 몰라도 괜찮아요.','gateway-use'],['chat-circle','바로 상담하기','원하는 사양이나 조건을 자유롭게 이야기해 주세요.','생각해 둔 조건부터 말해 주세요.','gateway-direct']].map(([image,title,text,small,action])=>button(uiIcon(image,'entry-icon')+'<h2>'+title+'</h2><p>'+text+'</p><small>'+small+'</small><span class="entry-action">'+title+' '+arrow+'</span>',action,'entry-card')).join('')+'</div><p class="change-note">선택한 방식은 언제든 바꿀 수 있어요.</p>'+(draft.draft_text||state.talk?button('작성하던 상담 이어가기 '+arrow,'gateway-continue','continue-draft'):'')+'</section>';
  else gateway.innerHTML=button(icon('arrow-left')+' 처음으로 돌아가기','gateway','route-back')+'<section class="purpose-layout"><div class="purpose-controls"><h1 tabindex="-1">어떤 일에 쓸 PC인가요?</h1><p class="purpose-description">부품 이름보다, 하고 싶은 일부터 시작하세요.</p><fieldset><legend class="sr-only">PC 용도</legend><div class="usage-grid">'+
    [['game','game-controller','즐겨 하는 게임에 쓸 PC예요.'],['edit','video-camera','영상 편집과 작업에 쓸 PC예요.'],['office','monitor','문서 작업과 일상 업무에 써요.'],['unknown','question','어떤 용도가 좋을지 함께 정해요.']].map(([value,image,text])=>button(icon(image)+'<strong>'+usageLabels[value]+'</strong><span>'+text+'</span>','gateway-usage','','data-usage="'+value+'" aria-pressed="'+(draft.usage_choice===value)+'"')).join('')+'</div></fieldset><div class="budget-controls"><label for="gateway-budget">예산은 어느 정도인가요?</label><select id="gateway-budget"><option value="">예산 미정도 괜찮아요</option>'+[100,150,200,250].map(n=>'<option value="'+n+'" '+(draft.budget_won===n*10000?'selected':'')+'>'+n+'만원 이하</option>').join('')+'</select></div><p class="condition-summary" aria-live="polite">'+draftSummary()+'</p>'+button('이 조건으로 상담 시작 '+arrow,'gateway-begin','gateway-button')+'</div><figure class="purpose-image"><img src="assets/gateway-pc-example.png" alt="PC 본체 예시 이미지"><figcaption>예시 이미지 · 실제 추천 상품과 다를 수 있어요.</figcaption></figure></section>';
  gateway.insertAdjacentHTML('beforeend','<footer class="gateway-footer"><span class="gateway-brand"><img src="assets/popcorn-mark.png" alt=""><strong>팝콘AI</strong></span><small>나에게 맞는 PC를 함께 찾아요.</small></footer>');
}
function renderSurface(){
  const consultation=ui.surface==='consultation';document.body.dataset.surface=ui.surface;workspace.hidden=!consultation;gateway.hidden=consultation;toolbar.hidden=!consultation;
  $('.topbar [data-action="new"]').hidden=!consultation;productsButton.hidden=consultation;
  if(!consultation)renderGateway();
  toolbar.innerHTML=(draft.start_mode==='use_first'?button(uiIcon('arrow-left')+' 용도 선택으로 돌아가기','gateway-use',''):'<span></span>')+button('시작방식 바꾸기','gateway','');
  if(consultation&&(draft.start_mode==='use_first'||draft.usage_choice||draft.budget_won))view.insertAdjacentHTML('afterbegin','<section class="draft-context"><strong>상담 초안</strong><p>'+draftSummary()+'</p><p>선택한 조건을 입력창에서 확인하고 수정해 주세요.</p>'+button('선택 조건으로 초안 바꾸기','gateway-rebuild','',''+(state.phase?'disabled':''))+'</section>');
}
function notice(text){$('#notice').textContent=text;$('#notice').hidden=false;clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>$('#notice').hidden=true,7000);}
function budget(product,talk=state.selectionState||state.talk){
  const won=talk?.budget_won;
  if(!Number.isInteger(product.price)||!Number.isInteger(won))return '예산 조건 미확인';
  if(talk.budget_bound==='이상')return '입력하신 예산 하한 '+money(won);
  const delta=won-product.price;
  return delta>0?'예산보다 '+money(delta)+' 낮아요':delta<0?'예산보다 '+money(-delta)+' 높아요':'예산과 같아요';
}
function syncChat(){
  const open=!mobile.matches||(chatPreference??state.screen==='welcome');
  const body=$('#chat-body'),toggle=$('#chat-toggle');
  if(!open&&body.contains(document.activeElement))toggle.focus({preventScroll:true});
  body.hidden=!open;toggle.setAttribute('aria-expanded',String(open));$('#chat-toggle-label').textContent=open?'상담 접기 ▴':'상담 내용 보기 ▾';
  $('#chat-summary').textContent=M.conditions(state.talk).join(' · ')||'게임과 예산을 알려주세요';
}
function renderSources(items){
  if(!items?.length)return '';
  return '<div class="message-sources">'+['own','web'].map(kind=>{
    const group=items.filter(x=>x.kind===kind);if(!group.length)return '';
    return '<div><strong>'+(kind==='own'?'우리 자료':'찾아본 자료')+'</strong><ul>'+group.map(x=>'<li>'+(x.url?'<a href="'+esc(x.url)+'" target="_blank" rel="noopener noreferrer">'+esc(x.label)+'</a>':esc(x.label))+'</li>').join('')+'</ul></div>';
  }).join('')+'</div>';
}
function renderMessages(){
  const key=JSON.stringify(state.messages);
  if(key!==lastMessages){
    $('#messages').innerHTML=state.messages.map(x=>'<div class="message '+(x.who==='user'?'user':'ai')+'"><span class="avatar">'+(x.who==='user'?uiIcon('user'):'<img class="avatar-mark" src="assets/popcorn-mark.png" alt="팝콘AI">')+'</span><div class="message-content"><p>'+(
      x.text==='안녕하세요! 즐기는 게임과 예산을 알려주시면 나에게 맞는 PC를 함께 찾아드릴게요.'&&state.screen==='welcome'?
      '안녕하세요! 즐기는 게임과 예산을<br>알려주시면 나에게 맞는 PC를<br>함께 찾아드릴게요.':esc(x.text))+'</p>'+(x.notice?'<small class="answer-notice">'+esc(x.notice)+'</small>':'')+renderSources(x.sources)+'</div></div>').join('');
    $('#messages').scrollTop=$('#messages').scrollHeight;lastMessages=key;
  }
  const examples=$('#start-examples');examples.hidden=state.screen!=='welcome';
  if(!examples.hidden)examples.innerHTML=[['game-controller','배그와 롤, 150만원으로 추천해줘'],['video-camera','영상 편집용 PC가 필요해요'],['question','아직 잘 모르겠어요']].map(pair=>
    button(uiIcon(pair[0])+'<span>'+pair[1]+'</span>'+uiIcon('caret-right','example-chevron'),'prompt','start-example','data-text="'+pair[1]+'" '+(state.phase?'disabled':''))).join('');
  const prompts=state.screen==='welcome'?['QHD로 해줘요','예산을 좀 더 낮춰줘요','다른 게임도 추가할게요']:['예산을 바꿀게요','용도를 바꿀게요'];
  $('#suggestions').innerHTML=prompts.map(text=>button(text,'prompt','chip','data-text="'+text+'" '+(state.phase?'disabled':''))).join('');
  $('#request').disabled=!!state.phase;$('#chat-form .send').disabled=!!state.phase;
  const label={talk:'AI가 조건과 답변을 확인하고 있어요.',recommend:'조건에 맞는 판매 중 PC를 조회하고 있어요.',save:'서버에서 최신 상품과 가격을 확인해 보관하고 있어요.',list:'이 브라우저의 보관 기록을 불러오고 있어요.'};
  $('#operation-status').textContent=label[state.phase]||'';$('#operation-status').hidden=!state.phase;
}
function requirements(){
  const labels=M.conditions(state.talk);
  return labels.length?'<div class="requirements">'+labels.map(label=>button(esc(label),'conditions','chip')).join('')+'</div>':'';
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
function heading(title,back=true){
  return (back?button(uiIcon('arrow-left')+'이전 화면','back','back live-back'):'')+'<div class="title-row"><h2 tabindex="-1">'+title+'</h2><span class="data-note">판매 중 PC · 조회 시점 참고 금액</span></div>'+requirements();
}
function productCard(product,action='detail',id=product.index){
  const rows=M.specRows(product.spec),spec=rows.length?'<dl class="live-card-spec">'+rows.map(([label,value])=>'<div><dt>'+esc(label)+'</dt><dd>'+esc(value)+'</dd></div>').join('')+'</dl>':'<p class="live-product-spec">'+esc(M.specText(product.spec)||'등록된 상세 사양이 없어요.')+'</p>';
  return '<section class="quote-card live-product-card"><span class="pill '+(product.tag.includes('최고')?'strong':'')+'">'+esc(product.tag||product.level||'판매 중 PC')+'</span>'+
    '<h3>'+esc(product.name)+'</h3>'+
    '<strong class="price">'+money(product.price)+'</strong><p class="muted">'+esc(product.price_src||'가격 기준 미확인')+'</p>'+
    spec+
    '<ul class="live-reasons">'+product.reasons.map(reason=>'<li>'+esc(reason)+'</li>').join('')+'</ul>'+
    '<p class="'+(product.over_budget?'warn-text':'green')+'">'+esc(budget(product,state.talk))+'</p>'+
    button('추천 상품 자세히 보기',action,'primary','data-id="'+esc(id)+'"')+'</section>';
}
function renderResults(){
  const groups=state.groups,hasProducts=groups.some(g=>g.products.length);
  view.innerHTML=heading('나에게 맞는 PC',false)+errorPanel()+
    groups.map(group=>'<section class="live-result-group"><h3>'+esc(group.usage||group.usage_grid||'추천 상품')+'</h3>'+
      (group.empty_note?'<p class="muted">'+esc(group.empty_note)+'</p>':'')+
      (group.products.length?'<div class="quote-cards">'+group.products.map(p=>productCard(p)).join('')+'</div>':'<div class="empty small-empty"><h3>'+esc(group.empty_reason||'추천 상품이 없어요')+'</h3><p>조건을 더 알려주시거나 예산·용도를 바꿔주세요.</p></div>')+'</section>').join('')+
    (!hasProducts&&!groups.length?'<div class="empty"><h3>'+(state.missing.length?'조건을 조금 더 알려주세요':'현재 조건의 추천 상품이 없어요')+'</h3><p>상담은 계속할 수 있어요. 예산이나 사용 목적을 알려주세요.</p></div>':'')+
    (state.assumed.includes('game.resolution=1080p')?'<p class="muted">해상도를 정하지 않아 FHD(1080p)를 기준으로 조회했어요.</p>':'')+
    (state.recommendation?.aiEstimated.length?'<p class="muted">일부 게임 등급은 AI 추정입니다. 실제 게임 성능 측정값과는 달라요.</p>':'');
  actions.hidden=true;
}
function productSummary(){
  const p=state.selected;
  return '<section class="final-summary live-summary"><div><h3>'+esc(p.name)+'</h3><p>'+esc(state.savedQuote?'보관 시점의 상품 구성과 참고 금액입니다.':p.tag||p.level||'판매 중인 완제품 구성입니다.')+'</p></div><div class="final-summary-price"><strong>'+money(p.price)+'</strong><p class="'+(p.over_budget?'warn-text':'green')+'">'+esc(budget(p))+'</p></div></section>';
}
function productDetails(){
  const p=state.selected;
  const rows=M.specRows(p.spec),spec=rows.length?'<dl class="live-spec-grid">'+rows.map(([label,value])=>'<div><dt>'+esc(label)+'</dt><dd>'+esc(value)+'</dd></div>').join('')+'</dl>':'<p class="live-full-spec">'+esc(M.specText(p.spec)||'등록된 상세 사양을 확인하지 못했어요.')+'</p>';
  return '<section class="final-parts"><h3>구성 상품 상세</h3><div class="final-table-wrap"><table class="final-table"><colgroup><col class="part-description-col"><col class="part-price-col"><col class="part-action-col"></colgroup>'+
    '<thead><tr><th scope="col">상품 · 등록 사양</th><th scope="col">금액</th><th scope="col">변경</th></tr></thead><tbody><tr data-part="pc"><td><div class="final-part-description">'+uiIcon('computer-tower','part-symbol')+
    '<div><h4><span>조립 PC</span><span class="part-name">'+esc(p.name)+'</span></h4><p>등록된 판매 상품의 구성입니다.</p><details data-detail="spec"><summary><span class="when-closed">상세 사양 펼치기</span><span class="when-open">상세 사양 접기</span>'+uiIcon('caret-down')+'</summary><div class="final-part-expanded">'+spec+'</div></details></div></div></td><td class="final-part-price">'+money(p.price)+'</td><td class="final-part-change"><span aria-label="부품 변경 미지원">-</span></td></tr></tbody>'+
    '<tfoot><tr><th scope="row">상품 참고 금액</th><td colspan="2">'+money(p.price)+'</td></tr></tfoot></table></div></section>'+
    '<section class="live-explanation"><h3>이 상품을 추천한 이유</h3>'+(p.reasons.length?'<ul>'+p.reasons.map(r=>'<li>'+esc(r)+'</li>').join(''):'<p>추천 이유가 제공되지 않았어요.</p>')+'</section>'+
    '<section class="live-capabilities"><div>'+button('다른 GPU 선택','unavailable','outline small','disabled aria-describedby="change-unavailable"')+
    button('저장장치 변경','unavailable','outline small','disabled aria-describedby="change-unavailable"')+'</div><p id="change-unavailable">현재 판매 중인 완제품을 안내해요. 부품별 옵션 변경과 게임 FPS 비교 자료는 아직 제공되지 않아요.</p></section>';
}
function finalConditions(){
  const row=(name,label,text)=>'<div>'+uiIcon(name)+'<dt>'+label+'</dt><dd>'+esc(text)+'</dd></div>';
  return '<section class="final-conditions"><h3>구매 전 확인할 내용</h3><div class="final-conditions-grid"><dl>'+
    row('gear','호환성','실제 조립 검수 결과 미확인')+row('tag','가격',state.savedQuote?'보관 시점 참고 금액 · 확정가 아님':state.selected.price_src||'가격 기준 미확인')+
    row('package','재고','재고 확보 전 · 구매 전 확인')+'</dl><dl>'+row('squares-four','운영체제','포함 여부 재확인 필요')+
    row('monitor','키보드 · 마우스 · 모니터','포함 여부 미확인')+row('shield','보증','기간 · 범위 재확인 필요')+'</dl></div></section>';
}
function renderDetail(){
  view.innerHTML=heading('추천 구성 상세')+errorPanel()+productSummary()+productDetails()+finalConditions();
  const p=state.selected;
  actions.innerHTML='<div><span>조회 시점 참고 금액</span><strong>'+money(p.price)+'</strong></div><div class="footer-buttons">'+button('다른 추천 상품 보기','results','outline')+button('이 견적으로 확인','final','primary')+'</div>';actions.hidden=false;
}
function renderFinal(){
  const label={idle:'아직 보관 전',saving:'보관 확인 중',saved:'서버에 보관됨',uncertain:'보관 결과 미확인',failed:'보관되지 않음'};
  const saved=state.saveState==='saved',disabled=!!state.phase||saved||state.needsRefresh||state.selected.price===null||!!state.pendingSave||!!state.pendingProblem;
  view.innerHTML=button(uiIcon('arrow-left')+'상품 상세 다시 보기','edit','back final-back')+
    '<div class="final-title-row"><div><h2 tabindex="-1">최종 견적 확인</h2><span class="save-status '+(saved?'is-saved':'')+'">'+uiIcon(saved?'file-text':'warning-circle-fill')+label[state.saveState]+'</span></div><span class="data-note">보관은 상품·시점 가격의 참고 기록입니다.</span></div>'+
    errorPanel()+productSummary()+productDetails()+finalConditions()+
    '<footer class="final-footer"><p>'+uiIcon('info')+'<span>포함 품목과 보증 조건은 구매 전에 확인해주세요.</span></p><div><div class="final-buttons">'+button('다른 상품 비교','results','outline')+
    button(saved?'보관 완료':state.phase==='save'?'서버 확인 중…':state.pendingSave?'이전 보관 결과 확인 필요':'견적 보관하기','save','primary',disabled?'disabled':'')+'</div><small>주문 · 결제 · 가격 확정 · 재고 확보는 진행되지 않습니다.</small></div></footer>'+
    (state.savedQuote?'<p class="muted live-saved-note">보관일 '+esc(new Date(state.savedQuote.saved_at).toLocaleString('ko-KR'))+' · 이 브라우저의 보관 키로 접근합니다.</p>':'');
  actions.hidden=true;
}
function renderSaved(){
  view.innerHTML=heading('내 견적',false)+'<p class="muted">이 브라우저의 보관 키로 접근하는 서버 기록입니다. 다른 기기와 회원 계정 동기화는 지원하지 않아요.</p>'+errorPanel()+
    (state.phase==='list'?'<div class="empty small-empty"><p>보관 기록을 불러오는 중이에요.</p></div>':state.error?'':state.quotes.length?
      '<div class="quote-cards">'+state.quotes.map(q=>'<section class="quote-card live-product-card"><span class="pill">보관 시점 기록</span><h3>'+esc(q.product.name)+'</h3><strong class="price">'+money(q.product.price)+'</strong><p>'+esc(new Date(q.saved_at).toLocaleString('ko-KR'))+'</p>'+button('보관 견적 보기','load','primary','data-id="'+esc(q.id)+'"')+'</section>').join('')+'</div>':
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
  if(state.screen==='welcome'){renderWelcome();if(state.error)view.insertAdjacentHTML('afterbegin',errorPanel());}
  else if(state.screen==='results')renderResults();
  else if(state.screen==='detail'&&state.selected)renderDetail();
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
    if(initial)flow.reset();
    if(initial&&(!hash||hash==='#start'||hash==='#purpose')){
      ui.surface=hash==='#purpose'?'usage':'gateway';history.replaceState(uiEntry(),'',uiHash());render();return;
    }
    ui.surface='consultation';let screen=hash.slice(1);
    if(!screenNames.includes(screen)||(['detail','final'].includes(screen)&&!state.selected)||(screen==='results'&&!state.recommendation))screen='welcome';
    if(initial||hash!=='#'+screen)history.replaceState({screen},'','#'+screen);
    if(screen==='saved')openSaved();else flow.navigate(screen);
  }finally{enteringRoute=false;}
}
function back(){flow.navigate({results:'welcome',detail:'results',final:'detail',saved:state.selected?'final':state.groups.length?'results':'welcome'}[state.screen]||'welcome');}
async function submit(text,{fromInput=false}={}){if(!String(text||'').trim()){notice('원하는 조건을 입력해주세요.');$('#request').focus();return;}
  if(text.trim().length>300){notice('상담 요청은 300자 이내로 입력해주세요.');return;}
  if(state.phase)return;
  const sent=text.trim();await flow.submit(text);
  // submit() also returns true after errors. Only validated conversation history
  // with no current error permits clearing the unchanged, visible input.
  if(fromInput&&ui.surface==='consultation'&&!state.error&&state.history.some(x=>x.role==='user'&&x.text===sent)&&draft.draft_text===text)setDraft('');
}
document.addEventListener('click',e=>{
  const b=e.target.closest('[data-action]');if(!b||b.disabled)return;e.preventDefault();
  switch(b.dataset.action){
    case 'gateway':showSurface('gateway');break;
    case 'gateway-use':draft.start_mode='use_first';showSurface('usage');break;
    case 'gateway-direct':draft.start_mode='direct';showSurface('consultation');break;
    case 'gateway-continue':showSurface('consultation');break;
    case 'gateway-usage':captureDraft();draft.usage_choice=draft.usage_choice===b.dataset.usage?null:b.dataset.usage;if(!draft.draft_edited)refreshDraft();render();gateway.querySelector('[data-usage="'+b.dataset.usage+'"]')?.focus({preventScroll:true});break;
    case 'gateway-begin':draft.start_mode='use_first';if(!draft.draft_edited)refreshDraft();showSurface('consultation');break;
    case 'gateway-rebuild':refreshDraftExplicitly();break;
    case 'gateway-products':if(state.recommendation){showSurface('consultation',{focus:false});flow.navigate('results');}else{showSurface('consultation');notice('원하는 용도와 예산을 상담창에 알려주시면 추천 상품을 확인할 수 있어요.');}break;
    case 'new':chatPreference=null;lastMessages='';Object.assign(draft,{start_mode:null,usage_choice:null,budget_won:null,budget_bound:null});setDraft('');ui.surface='consultation';flow.reset();break;
    case 'saved':captureDraft();openSaved();break;
    case 'prompt':submit(b.dataset.text);break;
    case 'detail':flow.select(Number(b.dataset.id));break;
    case 'final':flow.navigate('final');break;
    case 'edit':flow.navigate('detail');break;
    case 'results':flow.navigate('results');break;
    case 'back':back();break;
    case 'save':void flow.save();break;
    case 'recover':void flow.recover();break;
    case 'load':flow.load(b.dataset.id);break;
    case 'retry':void flow.retry();break;
    case 'attachment':notice('파일 첨부는 아직 지원하지 않아요. 필요한 조건을 글로 알려주세요.');break;
    case 'conditions':chatPreference=true;syncChat();$('#request').focus({preventScroll:true});if(mobile.matches)$('#chat-toggle').scrollIntoView({block:'start'});notice('바꿀 예산이나 용도를 상담창에 알려주세요. 실제 추천을 다시 조회해요.');break;
  }
});
function refreshDraftExplicitly(){setDraft(generatedDraft());$('#request').focus({preventScroll:true});}
document.addEventListener('change',e=>{if(e.target.id==='gateway-budget'){captureDraft();const n=Number(e.target.value);draft.budget_won=[100,150,200,250].includes(n)?n*10000:null;draft.budget_bound=draft.budget_won===null?null:'이하';if(!draft.draft_edited)refreshDraft();render();$('#gateway-budget')?.focus({preventScroll:true});}});
$('#request').addEventListener('input',()=>{captureDraft();draft.draft_edited=true;});
$('#chat-form').addEventListener('submit',e=>{e.preventDefault();if(state.phase)return;captureDraft();void submit(draft.draft_text,{fromInput:true});});
$('#request').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('#chat-form').requestSubmit();}});
$('#chat-toggle').addEventListener('click',()=>{chatPreference=$('#chat-toggle').getAttribute('aria-expanded')!=='true';syncChat();});
mobile.addEventListener('change',syncChat);
window.addEventListener('popstate',e=>{
  captureDraft();const entry=e.state;
  if(entry?.ui_epoch===ui.epoch&&['gateway','usage','consultation'].includes(entry.surface)&&screenNames.includes(entry.screen)){
    enteringRoute=true;try{ui.surface=entry.surface;render();history.replaceState(uiEntry(),'',uiHash());focusSurface();}finally{enteringRoute=false;}
  }else enterRoute(location.hash);
});
enterRoute(location.hash,true);focusSurface();
})();
