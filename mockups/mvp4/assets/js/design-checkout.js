(function(){
'use strict';var P=window.PAI,h=P.h;
function requestedId(ctx){return ctx.productId||(ctx.query&&typeof ctx.query.get==='function'?ctx.query.get('id'):null);}
function product(ctx){var id=requestedId(ctx);if(id)return P.getCatalogProduct(id);return P.catalogProducts.find(function(p){return !issue(p);})||P.catalogProducts.find(function(p){return p.recommendable===true;})||P.catalogProducts.find(function(p){return p.isSelling===true;})||null;}
function issue(p){if(!p)return '상품을 다시 선택해 주세요.';if(p.source&&p.source.kind==='historical')return '이전 자료의 상품입니다. 현재 판매 여부와 구성을 확인해 주세요.';if(p.isSelling!==true)return p.saleStatus==='품절'?'현재 품절로 표시된 상품입니다. 판매 여부를 확인해 주세요.':'현재 판매 여부를 확인해야 합니다.';if(p.statusKey==='oos'||p.stockQty===0)return '현재 재고·판매 상태 확인이 필요합니다.';if(p.reviewRequired===true)return '상품 정보 검수가 필요합니다.';if(!(typeof p.price==='number'&&isFinite(p.price)&&p.price>0))return '현재 상품 가격을 확인해야 합니다.';if(p.bomStatus==='mismatch')return '상품 정보와 연결된 구성표가 달라 확인이 필요합니다.';if(p.bomStatus==='missing'||!p.configurationId||!Array.isArray(p.specs)||!p.specs.length)return '이 상품의 정확한 부품 구성표를 확인해야 합니다.';return '';}
function candidates(p){return P.catalogProducts.filter(function(x){return x.recommendable===true&&(!p||String(x.id)!==String(p.id));});}
function blocked(p,screen){return P.designNotice('상품 정보를 먼저 확인해 주세요',issue(p),'bad')+P.designProductSummary(p)+'<div class="ds-actions">'+link('상품 상세 보기','product','normal',p,'btn-outline')+link('AI에게 질문하기','chat','product',p,'btn-outline')+link('상품·구성 문의','consult','normal',p)+'<button class="btn btn-outline" disabled>'+(screen==='save'?'견적 보관 전 확인 필요':'견적 진행 전 확인 필요')+'</button></div>';}
function configuration(p){return p.specs&&p.specs.length?P.designSpecTable(p):P.designNotice('부품 구성표를 확인하고 있어요','상품명에 적힌 요약 정보는 실제 부품 구성표와 별도로 확인해야 합니다.');}
function params(p){return p?{id:p.id}:{};}
function link(t,s,st,p,style){return P.designLink(t,s,st,params(p),style);}
function steps(active){return '<nav class="ds-step" aria-label="견적 단계">'+['상품 선택','구성 확인','견적 보관','구매 상담'].map(function(t,i){return (i?P.icon('caret-right'):'')+(i===active?'<b aria-current="step">':'<span>')+t+(i===active?'</b>':'</span>');}).join('')+'</nav>';}
function aside(p,extra){return '<aside class="ds-panel ds-sticky">'+P.designProductSummary(p)+'<div class="ds-price-line"><span>PC 본체</span><b>'+h(P.catalogMoney(p))+'</b></div><div class="ds-price-line"><span>수량</span><b>1대</b></div><div class="ds-price-line"><span>배송·추가 서비스</span><span>상담 시 확인</span></div><div class="ds-price-line total"><b>PC 금액</b><strong>'+h(P.catalogMoney(p))+'</strong></div>'+extra+'</aside>';}
function loading(title,description){return '<div role="status" aria-busy="true"><h2>'+h(title)+'</h2><p class="ds-muted">'+h(description)+'</p><div class="ds-skeleton"></div><div class="ds-skeleton"></div></div>';}
function fail(title,copy,p,screen){return P.designNotice(title,copy,'bad')+'<div class="ds-actions">'+link('다시 확인하기',screen,'normal',p)+link('PC 둘러보기','catalog','normal',p,'btn-outline')+'</div>';}
function optionGroups(p){return p&&Array.isArray(p.optionGroups)?p.optionGroups:[];}
P.designScreens.options=function(ctx){var p=product(ctx),s=ctx.state||'normal',groups=optionGroups(p);var body='';
 if(!p)return {html:P.designWrap('구성 확인','선택한 상품을 확인해 주세요.',P.designEmpty('선택한 PC를 찾을 수 없어요','상품 목록에서 다시 선택해 주세요.'))};
 if(issue(p)&&s!=='alternative-pc')body=blocked(p,'options');
 else if(s==='loading')body=loading('변경 가능한 구성을 찾고 있어요','현재 상품과 함께 사용할 수 있는 부품인지 확인합니다.');
 else if(s==='error')body=fail('구성 정보를 불러오지 못했어요','선택한 PC는 유지했어요. 잠시 후 다시 확인해 주세요.',p,'options');
 else if(s==='unavailable')body=fail('이 PC는 지금 구성 변경을 제공하지 않아요','기본 구성으로 살펴보거나, 필요한 변경을 AI에게 물어보세요.',p,'product');
 else {body=(s==='compatibility'?P.designNotice('함께 사용할 수 있는지 확인이 필요해요','이 변경은 아직 견적에 반영되지 않았어요. 기본 구성으로 돌아가거나 다른 PC를 살펴보세요.','bad'):'')+(s==='price-changed'?P.designNotice('구성 가격을 다시 확인해야 해요','이전에 본 금액으로 확정하지 않고, 현재 PC 총액과 변경 차액을 함께 확인합니다.','bad'):'')+(s==='applied'?P.designNotice(groups.length?'변경 내용을 확인해 주세요':'아직 적용할 변경 내역이 없어요',groups.length?'선택한 변경 사항은 호환 여부와 금액을 다시 확인해야 합니다.':'기본 구성만 표시하고 있습니다. 원하는 변경은 상품 문의로 알려 주세요.'):'');
 if(s==='alternative-pc')body+='<h2>다른 판매 PC로 바꾸기</h2><p class="ds-muted">기존 PC의 부품을 교체하는 대신, 원하는 사양을 갖춘 다른 판매 상품을 고릅니다. 상품번호도 함께 바뀝니다.</p><div class="ds-product-grid">'+candidates(p).slice(0,2).map(P.designCard).join('')+'</div>';
 else body+='<h2>기본 구성</h2>'+P.designSpecTable(p)+'<h2 style="margin-top:28px">부품별 변경</h2><p class="ds-muted">후보를 고른 뒤 적용해야 견적이 바뀝니다. PC 전체 금액과 기본 구성 대비 차액을 확인하세요.</p>'+(groups.length?groups.map(function(g,i){return '<details class="ds-option-details" '+(i===0?'open':'')+'><summary>'+h(g.label)+' 선택지</summary><label class="ds-option"><input type="radio" name="option-'+i+'" value="base" checked><div>기본 구성 유지<span>'+h(g.base||'원래 상품의 구성')+'</span></div></label>'+g.items.map(function(o,n){return '<label class="ds-option"><input type="radio" name="option-'+i+'" value="'+h(o.id||String(n))+'"><div>'+h(o.name)+'<span>'+(typeof o.priceDiff==='number'?'당시 기본 구성 대비 '+(o.priceDiff>0?'+':'')+h(P.money(o.priceDiff)):'적용 차액 확인 필요')+'</span></div></label>';}).join('')+'</details>';}).join(''):P.designNotice('변경 가능한 부품을 확인 중이에요','확인된 기본 구성을 살펴볼 수 있습니다. 원하는 변경 사항은 상품 문의에서 알려 주세요.'))+'<div class="ds-actions">'+link('기본 구성으로 견적 보기','quote','normal',p)+(groups.length?'<button class="btn btn-outline" id="ds-apply-options" type="button">변경 내용 확인</button>':'')+'</div>';
 }
 return {html:P.designWrap('원하는 구성으로 살펴보세요','원래 PC와 변경할 내용을 구분해서 확인합니다.',steps(1)+'<div class="ds-two-col"><section class="ds-panel">'+body+'</section>'+aside(p,link('이 PC에 대해 AI에게 질문','chat','product',p,'btn-outline'))+'</div>'),mount:function(){var b=document.getElementById('ds-apply-options');if(b)b.addEventListener('click',function(){location.href=P.designHref('options','compatibility',params(p));});}};
};
P.designScreens.quote=function(ctx){var p=product(ctx),s=ctx.state||'normal',body='';
 if(s==='empty'||!p)body=P.designEmpty('아직 선택한 PC가 없어요','상품을 고르거나 AI와 대화한 뒤 견적을 이어가세요.');
 else if(issue(p))body='<section class="ds-panel">'+blocked(p,'quote')+'</section>';
 else if(s==='refreshing')body='<section class="ds-panel">'+loading('현재 금액과 구성을 확인하고 있어요','선택한 상품과 변경 내역을 다시 확인합니다.')+'</section>';
 else if(s==='unavailable'||s==='error')body='<section class="ds-panel">'+fail(s==='unavailable'?'지금은 이 견적을 진행할 수 없어요':'견적을 확인하지 못했어요','선택한 내용은 유지됩니다. 현재 판매 상태와 구성 정보를 다시 확인해 주세요.',p,'quote')+'</section>';
 else body='<div class="ds-two-col"><div><section class="ds-panel"><h2>선택한 PC</h2>'+P.designProductSummary(p)+P.designSpecTable(p)+'<div class="ds-actions">'+link('상품 상세','product','normal',p,'btn-outline')+link('구성 살펴보기','options','normal',p,'btn-outline')+'</div></section>'+P.designNotice('견적 보관과 구매 상담은 별개예요','견적만 보관한 경우에는 먼저 연락하지 않습니다. 상담을 원할 때 별도로 신청해 주세요.')+'</div>'+aside(p,(s==='price-changed'?P.designNotice('이전에 확인한 가격이 달라졌어요','현재 표시된 금액을 확인한 뒤 보관해 주세요.','bad'):'')+'<div class="ds-actions">'+link('이 견적 보관하기','save','normal',p)+'</div><p class="ds-muted">보관한 견적에서 구매 상담을 신청할 수 있습니다.</p>')+'</div>';
 return {html:P.designWrap('내 PC 견적','상품과 구성을 확인하고, 필요할 때 다시 찾아보세요.',steps(1)+body)};
};
function errorState(s,screen){var map={error:['요청을 완료하지 못했어요','입력할 내용을 확인한 뒤 다시 시도해 주세요.'],forbidden:['이 견적에 접근할 수 없어요','견적을 보관했던 브라우저에서 확인해 주세요.'],conflict:['이 요청의 내용이 달라졌어요','보관할 상품과 금액을 다시 확인한 뒤 진행해 주세요.'],'rate-limit':['요청이 잠시 많아졌어요','잠시 후 다시 시도해 주세요.'],'price-changed':['보관 전에 가격을 다시 확인해 주세요','현재 금액이 처음 확인한 견적과 달라졌어요.'],'contact-required':['연락처를 등록해 주세요','견적 보관에 사용할 연락처와 동의를 확인해 주세요.'],'not-found':['연결된 견적을 찾을 수 없어요','내 견적에서 상품을 다시 선택해 주세요.']};return map[s]?P.designNotice(map[s][0],map[s][1],'bad'):'';}
// Page-memory review state only. There is no contact persistence, request transport, or server result here.
// GET /contact currently returns has_contact/masked_phone/name; expiry reasons and consent versions need an adapter contract.
var checkoutRecords=Object.create(null),localContact=null,requestSequence=0;
var contactStates=['contact-first','contact-existing','contact-change','contact-expired','contact-reconsent','contact-loading','contact-error'];
var resultStates=['unknown','checking','still-unknown','confirmed-success','confirmed-failure'];
function newRequestId(){requestSequence++;return 'design-request-'+(window.crypto&&typeof window.crypto.randomUUID==='function'?window.crypto.randomUUID():Date.now().toString(36)+'-'+requestSequence);}
function recordKey(screen,p){return screen+':'+String(p.id);}
function recordFor(screen,p,s){
 var key=recordKey(screen,p),r=checkoutRecords[key];
 if(!r){r=checkoutRecords[key]={screen:screen,productId:String(p.id),requestId:null,phase:'idle',draft:{name:'',phone:'',topic:'',message:'',consent:false},contactMode:localContact?'reuse':'first',maskedPhone:localContact&&localContact.masked_phone||'',hasContact:!!localContact,submitted:false,fingerprint:null,queuedResult:null,result:null,notify:null};}
 if(contactStates.indexOf(s)>=0){
  r.contactMode={'contact-first':'first','contact-existing':'reuse','contact-change':'change','contact-expired':'expired','contact-reconsent':'reconsent','contact-loading':'loading','contact-error':'error'}[s];
  r.hasContact=['reuse','change','reconsent'].indexOf(r.contactMode)>=0;r.reconsentRequired=s==='contact-reconsent';
  r.maskedPhone=r.hasContact?(localContact&&localContact.masked_phone||'010-••••-••••'):'';
 }
 if(resultStates.indexOf(s)>=0||s==='submitting'){
  if(!r.requestId)r.requestId=newRequestId();
  r.phase=s;
  // Direct state selection is an explicit review fixture, never an actual request result.
  if(s==='confirmed-success')r.result={kind:'design-fixture',outcome:'accepted',reference:'review-only'};
  if(s==='confirmed-failure')r.result={kind:'design-fixture',outcome:'failed',reason:'review-only'};
 }
 return r;
}
function resultMarkup(screen,p,r){
 var saving=screen==='save',phase=r.phase,title='',copy='',busy=phase==='checking'||phase==='submitting';
 if(phase==='confirmed-success')return successMarkup(screen,p,'success');
 if(phase==='confirmed-failure'){title=saving?'견적이 보관되지 않은 것을 확인했어요':'문의가 접수되지 않은 것을 확인했어요';copy='입력한 내용을 확인한 뒤 다시 진행할 수 있습니다.';}
 else if(phase==='checking'){title='같은 요청의 처리 상태를 확인하고 있어요';copy='새 요청을 보내지 않고 기존 요청의 결과만 확인합니다.';}
 else if(phase==='submitting'){title=saving?'견적 보관 요청을 확인하고 있어요':'문의 신청을 확인하고 있어요';copy='입력한 내용은 유지됩니다. 같은 요청을 다시 보내지 않아도 됩니다.';}
 else if(phase==='still-unknown'){title='아직 처리 결과를 확인하지 못했어요';copy='완료 여부가 확인될 때까지 다시 제출하지 마세요. 같은 요청의 상태를 다시 확인할 수 있습니다.';}
 else {title='처리 결과를 확인하지 못했어요';copy='요청이 처리되었을 수 있어요. 중복 제출 전에 같은 요청의 상태를 확인해 주세요.';}
 return (busy?loading(title,copy):P.designNotice(title,copy,phase==='confirmed-failure'?'bad':''))+'<div class="ds-actions">'+(phase==='confirmed-failure'?'<button type="button" class="btn btn-primary" data-ds-edit-after-failure>내용 확인 후 다시 진행</button>':'<button type="button" class="btn btn-primary" data-ds-check-result '+(busy?'disabled':'')+'>처리 상태 확인</button>')+(r.submitted?'<button type="button" class="btn btn-outline" data-ds-view-input>입력 내용 보기</button>':'')+link('상품으로 돌아가기','product','normal',p,'btn-outline')+'</div>';
}
function successMarkup(screen,p,s){var isSave=screen==='save',inquiry=!isSave&&!!issue(p);return '<div class="ds-success">'+P.icon('check-circle')+'<h2>'+(isSave?'견적을 보관했어요':s==='duplicate'?'이미 신청한 문의가 있어요':inquiry?'상품 문의를 신청했어요':'구매 상담을 신청했어요')+'</h2><p>'+(isSave?'내 견적에서 구성을 다시 확인할 수 있어요.<br>상담을 원할 때 별도로 신청해 주세요.':s==='duplicate'?'같은 요청으로 신청한 문의 내역을 확인해 주세요.<br>새로운 문의를 중복해서 접수하지 않았어요.':inquiry?'문의한 상품의 구성과 판매 여부를 확인한 뒤 안내드립니다.':'신청 내역을 확인한 뒤 남겨주신 연락처로 안내드릴게요.')+'</p></div>'+P.designProductSummary(p)+'<div class="ds-actions">'+link(isSave?'내 견적 보기':'상품 계속 둘러보기',isSave?'saved':'catalog','normal',p)+(isSave?link('구매 상담 신청','consult','contact-existing',p,'btn-outline'):'')+'</div>';}
function contactFields(screen,r){
 var reuse=r.contactMode==='reuse',reconsent=r.contactMode==='reconsent',existing=r.hasContact,changing=r.contactMode==='change',showPhone=!reuse&&!reconsent;
 var notice=r.contactMode==='expired'?P.designNotice('연락처를 다시 등록해 주세요','기존 연락처의 보관 기간이 지나 사용할 수 없습니다. 연락처와 동의를 새로 확인해 주세요.') : reconsent?P.designNotice('현재 동의 내용을 확인해 주세요','기존 연락처를 사용하려면 변경된 수집·이용 내용을 확인하고 다시 동의해 주세요.'):'';
 return notice+(existing?'<div class="ds-contact-summary"><div><span class="ds-muted">보관된 연락처</span><strong>'+h(r.maskedPhone)+'</strong><p class="ds-muted">'+(reuse?'이 연락처를 그대로 사용합니다. 다시 입력하지 않아도 됩니다.':'전체 전화번호는 표시하지 않습니다.')+'</p></div><button type="button" class="btn btn-outline" data-ds-contact-change '+(changing?'hidden':'')+'>연락처 변경</button><button type="button" class="btn btn-outline" data-ds-contact-reuse '+(!changing?'hidden':'')+'>기존 연락처 사용</button></div>':'')+'<div data-ds-contact-inputs '+(!showPhone?'hidden':'')+'><label for="ds-name">이름 <span class="ds-muted">선택</span></label><input id="ds-name" name="name" autocomplete="name" maxlength="30" value="'+h(r.draft.name)+'" placeholder="이름을 입력해 주세요"><label for="ds-phone">'+(changing?'새 전화번호':'전화번호')+' <span aria-label="필수">*</span></label><input id="ds-phone" name="phone" type="tel" autocomplete="tel" inputmode="tel" maxlength="20" value="'+h(r.draft.phone)+'" placeholder="010-0000-0000" aria-describedby="ds-phone-help ds-form-errors"><p class="ds-muted" id="ds-phone-help">'+(screen==='consult'?'신청한 문의를 위해 연락받을 번호를 입력해 주세요.':'견적 보관에 사용할 연락처입니다. 보관만 하면 상담 연락을 드리지 않습니다.')+'</p></div>';
}
function contactForm(screen,p,s,r){
 var consultation=screen==='consult',inquiry=consultation&&!!issue(p),meta=(window.POPCORN_CATALOG_SETS||{}).inquiry||{},needsConsent=consultation||r.contactMode!=='reuse';
 if(!r.draft.topic&&inquiry)r.draft.topic='기타';
 if(!r.draft.message&&inquiry&&!r.submitted)r.draft.message='상품번호 '+p.id+'의 구성과 판매 여부를 확인하고 싶습니다.';
 return '<form id="ds-contact-form" class="ds-form" novalidate '+(['idle','editing-after-failure'].indexOf(r.phase)<0?'hidden':'')+'><p id="ds-form-errors" class="ds-form-error" role="alert" tabindex="-1" '+(s==='validation'?'':'hidden')+'>'+(s==='validation'?'전화번호와 필수 동의를 확인해 주세요.':'')+'</p><div class="ds-notice" data-ds-input-locked hidden><div><strong>처리 중인 요청의 입력 내용</strong><p>결과가 확인되기 전에는 내용을 바꾸거나 다시 제출할 수 없습니다.</p><button class="btn btn-outline" type="button" data-ds-back-result>처리 상태로 돌아가기</button></div></div><fieldset class="ds-form-fields" data-ds-fields><div data-ds-contact-fields>'+contactFields(screen,r)+'</div>'+(consultation?'<label for="ds-topic">상담 주제</label><select id="ds-topic" name="topic">'+(meta.topics||[]).map(function(topic){return '<option'+(r.draft.topic===topic?' selected':'')+'>'+h(topic)+'</option>';}).join('')+'</select><label for="ds-message">궁금한 점 <span class="ds-muted">선택</span></label><textarea id="ds-message" name="message" maxlength="2000" placeholder="사용할 프로그램이나 원하는 구성 변경을 알려주세요.">'+h(r.draft.message)+'</textarea>':'')+'<label class="ds-consent" data-ds-consent-label '+(!needsConsent?'hidden':'')+'><input type="checkbox" name="consent" '+(needsConsent?'required ':'')+(r.draft.consent?'checked':'')+'><span>'+(consultation?h(meta.consent_text||'구매 상담을 위한 개인정보 수집·이용에 동의합니다.'):'견적 보관을 위한 연락처 수집·이용에 동의합니다.')+'</span></label>'+(consultation?'<p class="ds-muted">견적 보관 동의와 별개로, 이번 상담 신청에 대한 동의를 확인합니다.</p>':'<p class="ds-muted">이 단계는 견적 보관입니다. 상담을 신청한 것은 아닙니다.</p>')+'<a class="ds-muted" href="support.html#privacy">개인정보 처리방침 보기</a></fieldset><div class="ds-actions"><button class="btn btn-primary" type="submit">'+(consultation?(inquiry?'상품 문의 신청':'구매 상담 신청'):r.contactMode==='reuse'?'기존 연락처로 견적 보관':'견적 보관하기')+P.icon('arrow-right')+'</button></div></form>';
}
function maskPhone(raw){var d=String(raw).replace(/\D/g,'');return d.slice(0,d.indexOf('02')===0?2:3)+'-••••-'+d.slice(-4);}
function bindForm(screen,p,r){return function(){
 var f=document.getElementById('ds-contact-form'),region=document.getElementById('ds-request-result');if(!f||!region)return;
 var err=document.getElementById('ds-form-errors'),button=f.querySelector('button[type=submit]'),fieldset=f.querySelector('[data-ds-fields]'),timer=null,revision=0,disposed=false;
 function capture(){['name','phone','topic','message'].forEach(function(k){var el=f.querySelector('[name='+k+']');if(el)r.draft[k]=el.value;});var c=f.querySelector('[name=consent]');r.draft.consent=!!(c&&c.checked);}
 function clearTimer(){revision++;if(timer!==null){window.clearTimeout(timer);timer=null;}}
 function focusRegion(){region.tabIndex=-1;region.focus();}
 function bindResult(){
  var b=region.querySelector('[data-ds-check-result]');if(b)b.addEventListener('click',check);
  b=region.querySelector('[data-ds-view-input]');if(b)b.addEventListener('click',function(){showForm(true);});
  b=region.querySelector('[data-ds-edit-after-failure]');if(b)b.addEventListener('click',function(){r.phase='editing-after-failure';showForm(false);});
 }
 function showStatus(phase){if(disposed)return;r.phase=phase;f.hidden=true;button.disabled=true;region.hidden=false;region.innerHTML=resultMarkup(screen,p,r);bindResult();focusRegion();}
 function showForm(locked){if(disposed)return;f.hidden=false;region.hidden=true;fieldset.disabled=!!locked;button.disabled=!!locked;f.querySelector('[data-ds-input-locked]').hidden=!locked;f.removeAttribute('aria-busy');if(locked)f.querySelector('[data-ds-back-result]').focus();else button.focus();}
 function completeCheck(){
  var result=r.queuedResult;r.queuedResult=null;
  if(result&&result.requestId===r.requestId&&result.kind==='design-fixture'&&result.outcome==='accepted'&&result.reference){
   r.result=result;if(screen==='save'){localContact={has_contact:true,masked_phone:r.contactMode==='reuse'||r.contactMode==='reconsent'?r.maskedPhone:maskPhone(r.draft.phone)};}
   showStatus('confirmed-success');
  }else if(result&&result.requestId===r.requestId&&result.kind==='design-fixture'&&result.outcome==='failed'&&result.reason){r.result=result;showStatus('confirmed-failure');}
  else showStatus('still-unknown');
 }
 function check(){if(disposed||r.phase==='checking'||r.phase==='submitting'||r.phase==='confirmed-success')return;clearTimer();showStatus('checking');var turn=revision;timer=window.setTimeout(function(){if(disposed||turn!==revision)return;timer=null;completeCheck();},650);}
 function bindContact(){
  var b=f.querySelector('[data-ds-contact-change]');if(b)b.addEventListener('click',function(){if(fieldset.disabled)return;capture();r.contactMode='change';r.draft.consent=false;refreshContact();});
  b=f.querySelector('[data-ds-contact-reuse]');if(b)b.addEventListener('click',function(){if(fieldset.disabled)return;capture();r.contactMode=r.reconsentRequired?'reconsent':'reuse';r.draft.consent=false;refreshContact();});
 }
 function refreshContact(){f.querySelector('[data-ds-contact-fields]').innerHTML=contactFields(screen,r);var c=f.querySelector('[name=consent]'),need=screen==='consult'||r.contactMode!=='reuse';c.checked=r.draft.consent;c.required=need;f.querySelector('[data-ds-consent-label]').hidden=!need;button.innerHTML=(screen==='consult'?(issue(p)?'상품 문의 신청':'구매 상담 신청'):r.contactMode==='reuse'?'기존 연락처로 견적 보관':'견적 보관하기')+P.icon('arrow-right');bindContact();}
 f.querySelector('[data-ds-back-result]').addEventListener('click',function(){showStatus(r.phase);});
 f.addEventListener('input',capture);f.addEventListener('change',capture);bindContact();
 f.addEventListener('submit',function(e){
  e.preventDefault();if(disposed||['idle','editing-after-failure'].indexOf(r.phase)<0)return;
  if(screen==='save'&&issue(p)){err.textContent=issue(p);err.hidden=false;return;}
  capture();var phone=f.querySelector('[name=phone]'),consent=f.querySelector('[name=consent]'),usesExisting=r.contactMode==='reuse'||r.contactMode==='reconsent',needsConsent=screen==='consult'||r.contactMode!=='reuse',problems=[];
  var phoneInvalid=!usesExisting&&!/^0\d{8,10}$/.test(r.draft.phone.replace(/[\s-]/g,''));
  if(phoneInvalid)problems.push('연락받을 전화번호를 정확히 입력해 주세요.');
  if(usesExisting&&(!r.hasContact||!r.maskedPhone))problems.push('기존 연락처를 확인한 뒤 진행해 주세요.');
  if(needsConsent&&!consent.checked)problems.push(screen==='consult'?'이번 상담 신청의 개인정보 수집·이용 동의를 확인해 주세요.':'연락처 수집·이용 동의를 확인해 주세요.');
  phone.setAttribute('aria-invalid',String(phoneInvalid));consent.setAttribute('aria-invalid',String(needsConsent&&!consent.checked));
  if(problems.length){err.textContent=problems.join(' ');err.hidden=false;(phoneInvalid?phone:consent).focus();return;}
  var fingerprint=JSON.stringify({productId:r.productId,contactMode:r.contactMode,name:usesExisting?'':r.draft.name,phone:usesExisting?'':r.draft.phone,topic:r.draft.topic,message:r.draft.message,consent:needsConsent?r.draft.consent:true,consultationRequested:screen==='consult'});
  // Unknown requests keep one identity and immutable inputs. Only a confirmed failure permits an edited new logical request.
  if(!r.requestId||r.fingerprint!==null&&r.fingerprint!==fingerprint){r.requestId=newRequestId();}
  r.fingerprint=fingerprint;r.submitted=true;r.result=null;err.hidden=true;f.setAttribute('aria-busy','true');showStatus('submitting');
  clearTimer();var turn=revision;timer=window.setTimeout(function(){if(disposed||turn!==revision)return;timer=null;showStatus('unknown');},650);
 });
 r.notify=function(){if(!disposed&&r.phase!=='checking'&&r.phase!=='submitting')check();};
 if(r.phase!=='idle'&&r.phase!=='editing-after-failure'){showStatus(r.phase);if(r.phase==='checking'||r.phase==='submitting'){var initialTurn=revision;timer=window.setTimeout(function(){if(disposed||initialTurn!==revision)return;timer=null;if(r.phase==='checking')completeCheck();else showStatus('unknown');},650);}}
 else showForm(false);
 if(typeof window.addEventListener==='function')window.addEventListener('pagehide',function(){disposed=true;clearTimer();r.notify=null;},{once:true});
};}
// Explicit development review hook. It accepts only same-request fixtures, never fetches, stores, or claims a server result.
// Production must replace this hook with an authenticated, idempotent result-status adapter.
P.designCheckoutReview={
 inspect:function(screen,id){var r=checkoutRecords[screen+':'+String(id)];return r?{requestId:r.requestId,phase:r.phase,productId:r.productId,submitted:r.submitted,contactMode:r.contactMode,hasContact:r.hasContact,maskedPhone:r.maskedPhone,kind:'design-only-memory'}:null;},
 queueResult:function(screen,id,result){var r=checkoutRecords[screen+':'+String(id)];if(!r||!result||result.kind!=='design-fixture'||!r.requestId||result.requestId!==r.requestId||['unknown','still-unknown','checking','submitting'].indexOf(r.phase)<0)return false;if(result.outcome==='accepted'&&!result.reference||result.outcome==='failed'&&!result.reason||['accepted','failed','pending'].indexOf(result.outcome)<0)return false;r.queuedResult={kind:'design-fixture',requestId:r.requestId,outcome:result.outcome,reference:result.reference||null,reason:result.reason||null};return true;}
};
function bindContactUnavailable(r){return function(){var retry=document.querySelector('[data-ds-contact-retry]');if(!retry)return;retry.addEventListener('click',function(){if(retry.disabled)return;retry.disabled=true;var box=document.getElementById('ds-contact-availability');box.innerHTML=loading('보관된 연락처를 확인하고 있어요','연락처 확인이 끝난 뒤 다음 단계를 이어갈 수 있습니다.');window.setTimeout(function(){box.innerHTML=P.designNotice('연락처를 확인하지 못했어요','기존 연락처가 없다고 확인된 것은 아닙니다. 잠시 후 다시 확인해 주세요.','bad');retry.disabled=false;},650);});};}
['save','consult'].forEach(function(screen){P.designScreens[screen]=function(ctx){
 var p=product(ctx),s=ctx.state||'normal',isSave=screen==='save',inquiry=!isSave&&!!issue(p),title=isSave?'견적을 보관해두세요':inquiry?'상품·구성을 문의하세요':'구매 상담을 신청하세요',body='',mount;
 if(!p)return {html:P.designWrap(title,'선택한 상품을 확인해 주세요.',P.designEmpty('연결된 PC를 찾을 수 없어요','상품 목록에서 다시 선택해 주세요.'))};
 var r=recordFor(screen,p,s);
 if(isSave&&issue(p))body='<section class="ds-panel ds-limit">'+blocked(p,'save')+'</section>';
 else if(s==='success'||s==='duplicate')body='<div class="ds-panel ds-limit">'+successMarkup(screen,p,s)+'</div>';
 else if(s==='contact-loading'||s==='contact-error'){body='<section class="ds-panel ds-limit"><div id="ds-contact-availability">'+(s==='contact-loading'?loading('보관된 연락처를 확인하고 있어요','확인된 연락처가 있으면 다시 입력하지 않고 사용할 수 있습니다.'):P.designNotice('연락처를 확인하지 못했어요','기존 연락처가 없다고 확인된 것은 아닙니다. 잠시 후 다시 확인해 주세요.','bad'))+'</div><div class="ds-actions"><button class="btn btn-primary" type="button" data-ds-contact-retry>연락처 다시 확인</button>'+link('상품으로 돌아가기','product','normal',p,'btn-outline')+'</div></section>';mount=bindContactUnavailable(r);}
 else if(['forbidden','conflict','price-changed','not-found'].indexOf(s)>=0)body='<div class="ds-panel ds-limit">'+errorState(s,screen)+P.designProductSummary(p)+'<div class="ds-actions">'+link(isSave?'견적 다시 확인':'내 견적 확인',isSave?'quote':'saved','normal',p)+link('상품으로 돌아가기','product','normal',p,'btn-outline')+'</div></div>';
 else {body='<div class="ds-two-col"><section class="ds-panel">'+errorState(s,screen)+(isSave?P.designNotice('보관만 해도 괜찮아요','이 단계에서는 상담을 신청하지 않습니다. 나중에 마음이 정해지면 내 견적에서 신청해 주세요.'):'<h2>어떤 도움이 필요한가요?</h2><p class="ds-muted">선택한 상품에 대해 필요한 내용을 확인합니다.</p>')+(inquiry?P.designNotice('상품·구성 확인 문의',issue(p)+' 이 문의만으로 구매나 견적이 확정되지 않습니다.'):'')+contactForm(screen,p,s,r)+'<div id="ds-request-result" class="ds-form-progress" '+(['idle','editing-after-failure'].indexOf(r.phase)>=0?'hidden':'')+'>'+(['idle','editing-after-failure'].indexOf(r.phase)<0?resultMarkup(screen,p,r):'')+'</div></section>'+aside(p,link('견적 내용 다시 보기','quote','normal',p,'btn-outline'))+'</div>';mount=bindForm(screen,p,r);}
 return {html:P.designWrap(title,isSave?'선택한 PC를 다시 찾기 쉽도록 보관하세요.':'구매 전 궁금한 점과 필요한 변경 사항을 알려주세요.',steps(isSave?2:3)+body),mount:mount};
};});
// A frozen catalog observation supplies the visual saved-quote fixture; no customer record is read or created.
P.designScreens.saved=function(ctx){var base=product(ctx),s=ctx.state||'normal';
var fixture=base?{kind:'design-scenario-from-catalog-observation',isActualCustomerQuote:false,quoteId:null,observedAt:base.source&&base.source.observedAt,product:JSON.parse(JSON.stringify(base))}:null;
var p=fixture&&fixture.product,body='';
if(s==='empty'||!p)body=P.designEmpty('보관한 견적이 없어요','마음에 드는 PC를 골라 견적을 보관해보세요.');
else if(s==='loading')body=loading('보관한 견적을 불러오고 있어요','견적을 보관한 브라우저인지 확인합니다.');
else if(s==='error')body=fail('내 견적을 불러오지 못했어요','보관한 견적이 삭제된 것은 아닙니다. 잠시 후 다시 확인해 주세요.',p,'saved');
else body=P.designNotice('내 속도에 맞게 결정하세요','견적을 보관했다고 상담을 신청한 것은 아닙니다. 상담이 필요하면 아래에서 별도로 신청해 주세요.')+'<section class="ds-panel">'+
(s==='expired'?P.designNotice('보관 이후 상품 정보가 달라졌을 수 있어요','보관한 구성과 현재 판매 정보를 나누어 확인해 주세요.','bad'):'')+
(s==='unavailable'?P.designNotice('현재 판매 여부를 확인할 수 없어요','보관 당시 견적은 남아 있습니다. 대체 PC를 살펴보거나 상담을 신청해 주세요.','bad'):'')+
'<h2>보관한 견적</h2>'+P.designProductSummary(p)+'<div class="ds-price-line"><span>보관한 PC 금액</span><b>'+h(P.catalogMoney(p))+'</b></div><div class="ds-price-line"><span>현재 금액·판매 여부</span><span>다시 확인 필요</span></div><details class="ds-option-details"><summary>보관한 구성 보기</summary>'+configuration(p)+'</details><div class="ds-actions">'+link('현재 상품 확인','product','normal',p,'btn-outline')+link('AI와 이어서 대화','chat','product',p,'btn-outline')+link(issue(p)?'상품·구성 문의':'구매 상담 신청','consult','normal',p)+'</div></section>';
return {html:P.designWrap('내 견적','보관한 PC를 다시 살펴보고 다음 단계를 이어가세요.',body)};};
}());



