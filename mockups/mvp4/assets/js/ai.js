(function () {
  'use strict';
  var P = window.PAI, h = P.h, i = P.icon, link = P.href;
  function pkg() { return P.data.packages[P.qs.get('package')] || P.data.packages.business; }
  function crumb(label) { return '<nav class="breadcrumb" aria-label="현재 위치"><a href="index.html">홈</a>' + i('caret-right') + '<a href="ai-packages.html">AI 패키지</a>' + i('caret-right') + '<span>' + h(label) + '</span></nav>'; }
  function btn(text, page, params, style) { return '<a class="btn ' + (style || 'btn-primary') + '" href="' + link(page, params) + '">' + h(text) + i('arrow-right') + '</a>'; }
  function model(p) { return '<figure class="ai-scene"><img src="' + P.image(p.detailModel || p.model) + '" alt="' + h(p.modelAlt || 'PC를 활용하는 모습') + '"></figure>'; }
  // 2026-10-21 대표 승인 「사내문서 검색을 누르면 업무 예시랑 … 구축해주는 과정을 먼저 보여주고, 그다음 상담으로」 --
  // 업무형의 사내 문서 검색(상단 타일·아래 활용 카드)만 설명 화면으로 간다. 다른 업무·패키지는 기존 상담 연결 그대로.
  // 2026-10-21 같은 날 승인 「회의록 정리랑 고객답변 초안을 누르면 각각 업무 예시와 … 구축하는 과정을 먼저 보여주고 상담으로」 --
  // 업무형의 세 업무(사내 문서 검색·회의록 정리·고객 답변 초안)가 각자의 설명 화면으로 간다. 다른 패키지는 기존 상담 연결 그대로.
  var SERVICE_USES = {documents: 1, meetings: 1, replies: 1};
  // 2026-10-23 대표 승인 -- 기본형·고급형 다섯 업무도 상담보다 각자의 설명 화면(ai-task-guides.js)을 먼저 연다.
  var TASK_USES = {basic: {study: 1, summary: 1, writing: 1}, advanced: {image: 1, code: 1}};
  function useHref(p, u) { return p.id === 'business' && SERVICE_USES[u.id] ? 'ai-service.html?package=business&amp;use=' + u.id : TASK_USES.hasOwnProperty(p.id) && TASK_USES[p.id][u.id] === 1 ? 'ai-service.html?package=' + p.id + '&amp;use=' + u.id : link('ai-consult', {package:p.id, use:u.id}); }
  function uses(p, compact) { return '<div class="ai-use-grid' + (compact ? ' compact' : '') + '">' + p.uses.map(function (u) { return '<a class="ai-use" href="' + useHref(p, u) + '"><span class="ai-icon">' + i(u.icon) + '</span><div><h3>' + h(u.title) + '</h3>' + (compact ? '' : '<p>' + h(u.text) + '</p>') + '</div>' + i('caret-right') + (!compact && p.id==='business' ? demo(u.id) : '') + '</a>'; }).join('') + '</div>'; }
  function demo(id) {
    var content={documents:'<div class="demo-query">'+i('magnifying-glass')+'휴가 규정 알려줘</div><div class="demo-paper">'+i('file-text')+'<strong>사내 복지 규정.pdf</strong><p>필요한 내용을 찾고<br>참고 원문을 함께 확인합니다.</p></div>',meetings:'<div class="demo-paper"><strong>회의록 초안</strong><p>주요 논의 · 일정 조정<br>할 일 · 자료 준비<br>확인할 내용 · 담당자 검토</p></div>',replies:'<div class="demo-paper"><strong>답변 초안</strong><p>안녕하세요.<br>문의하신 내용을 확인했습니다.<br>안내할 내용을 검토한 뒤<br>고객에게 직접 보냅니다.</p></div>'};
    return '<div class="ai-demo"><small>활용 화면</small>'+content[id]+'</div>';
  }
  function faq(p) { return '<section class="ai-section"><h2 class="section-title">자주 묻는 질문</h2><div class="ai-faq">' + [
    ['기존 PC로도 상담할 수 있나요?', '네. 현재 사용 중인 PC 사양과 원하는 작업을 알려주시면 구성 검토에 참고합니다. 설치 가능 여부와 제공 범위는 상담 후 확인합니다.'],
    ['어떤 자료를 활용할 수 있나요?', '상담에서 자료 형식과 사용 목적을 먼저 확인합니다. 지금은 문서 원본이나 개인정보가 들어 있는 자료를 올리지 마세요.'],
    [p.id === 'advanced' ? '이미지 제작과 개발 보조가 모두 포함되나요?' : 'AI가 만든 내용을 바로 사용해도 되나요?', p.id === 'advanced' ? '이미지 제작 또는 개발 보조 중 필요한 전문 기능을 선택해 상담합니다. 두 기능이 모두 기본 포함되는 구성은 아닙니다.' : 'AI의 답변과 초안은 사람이 원문과 사실을 확인한 뒤 사용해야 합니다. 실제 성능과 지원 범위는 선택한 구성 및 자료에 따라 달라질 수 있습니다.']
  ].map(function (q) { return '<details><summary>' + i('question') + h(q[0]) + i('caret-down') + '</summary><p>' + h(q[1]) + '</p></details>'; }).join('') + '</div></section>'; }

  P.pages['ai-packages'] = function () {
    var cards = ['basic','business','advanced'].map(function (id) { var p=P.data.packages[id]; return '<article class="ai-package-card ' + (id==='business'?'featured':'') + '"><span class="eyebrow">' + h(p.type) + '</span><h2>' + h(p.name) + '</h2><p class="muted">' + h(p.description) + '</p><div class="ai-package-product"><img src="' + P.image(p.image) + '" alt="' + h(p.type) + ' PC"></div><ul class="ai-check-list">' + p.uses.map(function(u){return '<li>' + i(u.icon) + h(u.title) + '</li>';}).join('') + '</ul><p class="ai-quote">견적 문의</p>' + btn('패키지 자세히 보기','ai-detail',{package:id},id==='business'?'btn-primary':'btn-outline') + '</article>'; }).join('');
    return {html:'<div class="container">' + crumb('패키지 비교') + '<section class="ai-intro"><span class="eyebrow">POPCORN AI PACKAGE</span><h1>내 일에 맞는 AI를<br>찾아보세요.</h1><p>PC와 AI 설치, 사용 안내까지.<br class="mobile-only"> 필요한 일부터 함께 살펴봅니다.</p></section><div class="ai-package-grid">' + cards + '</div><p class="ai-footnote">구성 · 설치 · 교육 · 지원 범위는 상담 후 견적으로 안내합니다.</p><section class="ai-help-panel"><div>' + i('chat-circle') + '<h2>어떤 패키지가 맞을지 고민되나요?</h2><p>지금 하고 있는 일과 필요한 기능부터 알려주세요.</p></div>' + btn('우리 업무로 상담하기','ai-consult',{package:'business'}) + '</section></div>'};
  };

  // 2026-10-21 대표 승인(30인 이하 기업 컨설팅, 정본 1번의 위쪽 구분만) -- 업무형 소개 바로 뒤에 개인 업무 AI 와 기업 컨설팅을 나눠 보인다.
  // 개인 쪽은 기존 활용 업무(#uses)로, 기업 쪽은 기업 컨설팅 설명(ai-company.html?from=P)으로만 간다. 모달·필수 선택·상담 단계는 없다.
  function serviceChoice() {
    return '<section class="ai-choice" id="service-choice" aria-labelledby="ai-choice-title"><h2 id="ai-choice-title">내 업무를 돕는 AI,<br><em>우리 회사의 흐름을 바꾸는 컨설팅.</em></h2><p class="ai-choice-lead">필요한 범위부터 선택하세요.</p><div class="ai-choice-grid">' +
      '<article class="ai-choice-card"><span class="ai-choice-tag">나의 업무를 더 효율적으로</span><h3>개인 업무 자동화 AI</h3><p>내 PC의 로컬 LLM으로,<br>내가 맡은 반복 업무를 줄입니다.</p><p class="ai-choice-note">회사에 맞춘다는 것은 담당자 한 사람이 맡은 업무의 자료·양식·규칙에 맞춘다는 뜻입니다.</p><a class="text-link" id="choice-personal" href="#uses">개인 업무 예시 보기 ' + i('arrow-right') + '</a></article>' +
      '<article class="ai-choice-card ai-choice-company"><span class="ai-choice-tag">30인 이하 기업 대상</span><h3>기업 AI 업무개선 컨설팅</h3><p>여러 담당자 사이에서 이어지는<br>회사 업무를 함께 살펴봅니다.</p><p class="ai-choice-note">개인 업무 AI 패키지와 별도로 진행하는 컨설팅입니다.</p><a class="text-link" id="choice-company" href="ai-company.html?from=P">회사 업무 흐름 살펴보기 ' + i('arrow-right') + '</a></article>' +
      '</div></section>';
  }
  P.pages['ai-detail'] = function () {
    var p=pkg();
    return {html:'<div class="container">' + crumb(p.type) + '<section class="ai-detail-hero"><div class="ai-hero-visual" data-package="' + h(p.id) + '">' + model(p) + '</div><div class="ai-hero-copy"><span class="eyebrow">' + h(p.id === 'business' ? '업무 도입 패키지 · 업무형' : p.type + ' · AI PACKAGE') + '</span><h1>' + h(p.headline).replace(/\n/g,'<br>') + '</h1><h2>' + h(p.fullName) + '</h2><p>' + h(p.id === 'business' ? 'PC 구성부터 AI 설치·사용 안내까지.' : p.description) + '</p>' + uses(p,true) + '<span class="ai-quote">' + (p.id === 'business' ? '상담 후 견적 안내' : '견적 문의') + '</span>' + btn(p.cta,'ai-consult',p.id === 'business' ? {package:p.id,intent:'adoption'} : {package:p.id}) + '<a class="text-link" href="ai-packages.html">패키지 비교 ' + i('arrow-right') + '</a></div></section>' + (p.id === 'business' ? serviceChoice() : '') + '<nav class="ai-tabs" aria-label="상품 상세 안내"><a href="#uses">활용 업무</a><a href="#scope">구성 안내</a><a href="#process">도입 과정</a></nav><section class="ai-section" id="uses"><span class="eyebrow">일하는 방식에 맞게</span><h2 class="section-title">이런 일에 활용해보세요.</h2>' + uses(p,false) + '<p class="ai-footnote">필요한 기능과 지원 범위는 상담 후 확인합니다.</p></section><section class="ai-section ai-scope" id="scope"><div><span class="eyebrow">PC + AI + 사용 안내</span><h2 class="section-title">PC부터 설치·사용 안내까지.</h2><p>자료 형식과 사용 업무를 확인한 뒤<br>구성과 제공 범위를 견적으로 안내합니다.</p></div><div class="ai-scope-grid">' + [['computer-tower','PC 구성','업무와 필요한 사양을 함께 검토합니다.'],['gear','AI 설치','선택한 기능에 맞는 환경을 구성합니다.'],['users','사용 안내','담당자의 작업 흐름에 맞춰 안내합니다.']].map(function(a){return '<div>'+i(a[0])+'<h3>'+a[1]+'</h3><p>'+a[2]+'</p></div>';}).join('') + '</div></section><section class="ai-section" id="process"><h2 class="section-title">필요한 일부터, 차근차근.</h2><ol class="ai-process">' + [['file-text','업무 확인','자료 형식과 활용 목적 확인'],['squares-four','구성 제안','사양 · 기능 · 지원 범위 협의'],['monitor','설치','합의한 구성으로 환경 준비'],['users','사용 안내','실제 업무에 맞춰 사용 안내']].map(function(a,n){return '<li><span class="ai-icon">'+i(a[0])+'</span><small>0'+(n+1)+'</small><h3>'+a[1]+'</h3><p>'+a[2]+'</p></li>';}).join('') + '</ol></section>' + faq(p) + '<div class="ai-bottom-cta"><div><strong>'+h(p.name)+'</strong><span>내 업무에 맞는 구성부터 확인하세요.</span></div>' + btn(p.cta,'ai-consult',p.id === 'business' ? {package:p.id,intent:'adoption'} : {package:p.id}) + '</div></div>'};
  };

  function resultMarkup(p, status, use, requestId) {
    var states = {
      received: {icon:'check-circle', label:'접수 완료', title:'상담 신청이<br>접수되었습니다.', description:'신청하신 내용을 확인한 뒤 선택한 연락 방법으로 안내드립니다.'},
      pending: {icon:'clock', label:'접수 확인', title:'접수 여부를<br>확인하고 있어요.', description:'접수 결과를 아직 확인하지 못했습니다. 중복 신청 전에 접수 여부를 확인해 주세요.'},
      failed: {icon:'warning-circle', label:'상담 신청', title:'상담을 접수하지<br>못했습니다.', description:'입력한 내용을 확인한 뒤 다시 신청해 주세요.'},
      neutral: {icon:'clock', label:'상담 신청', title:'상담 접수 상태를<br>확인해 주세요.', description:'이 페이지에서 확인할 수 있는 상담 접수 정보가 없습니다.'}
    };
    var s = states[status] || states.neutral;
    var u = p.uses.find(function (item) { return item.id === use; });
    var receipt = status === 'received' && typeof requestId === 'string' && requestId.trim() ? '<div><dt>접수 번호</dt><dd>' + h(requestId.trim()) + '</dd></div>' : '';
    return '<section class="ai-result" aria-labelledby="result-title"><div class="result-symbol ' + (status === 'neutral' ? 'pending' : h(status)) + '">' + i(s.icon) + '</div><span class="eyebrow">' + s.label + '</span><h1 id="result-title" tabindex="-1">' + s.title + '</h1><p>' + s.description + '</p><dl class="result-summary"><div><dt>선택한 패키지</dt><dd>' + h(p.type + ' · ' + p.name) + '</dd></div><div><dt>관심 기능</dt><dd>' + h(u ? u.title : '상담에서 확인') + '</dd></div>' + receipt + '</dl><div class="button-row result-actions"><button class="btn btn-outline" type="button" data-return-form>' + (status === 'received' ? '신청 내용 확인' : status === 'neutral' ? '상담 신청으로' : '입력 내용 확인') + ' ' + i('arrow-left') + '</button>' + btn('AI 패키지 둘러보기', 'ai-packages', {}, status === 'received' ? 'btn-primary' : 'btn-outline') + '</div></section>';
  }

  P.pages['ai-consult'] = function () {
    var p = pkg(), selected = P.qs.get('use');
    var selectedUse = p.uses.some(function (item) { return item.id === selected; }) ? selected : '';
    var form='<div id="consult-input"><div class="ai-consult-heading"><span class="eyebrow">'+h(p.type)+' · 도입 상담</span><h1>'+h(p.id==='business'?'우리 업무에 맞는 AI,':p.name+',')+'<br>함께 살펴볼까요?</h1><p>필요한 일과 연락받을 방법을 알려주세요.</p></div><div class="ai-consult-layout"><aside class="consult-context">'+model(p)+'<div><span class="eyebrow">선택한 패키지</span><h2>'+h(p.name)+'</h2><p>'+h(p.description)+'</p><a class="text-link" href="ai-detail.html?package='+p.id+'">패키지 다시 보기 '+i('arrow-right')+'</a></div><div class="consult-steps"><span>'+i('file-text')+'필요 업무 확인</span><span>'+i('computer-tower')+'구성 · 견적 안내</span><span>'+i('users')+'도입 범위 협의</span></div></aside><form id="ai-consult-form" class="consult-form" novalidate><div class="notice">'+i('info')+'<p><strong>상담에 필요한 내용을 알려주세요.</strong><br>관심 업무와 연락받을 방법을 확인한 뒤 신청해 주세요.</p></div><fieldset class="use-fieldset" aria-describedby="use-error"><legend>어떤 기능이 필요하세요? <span class="required">필수</span></legend><p class="field-hint">'+(p.id==='advanced'?'이미지 제작 또는 개발 보조 중 한 가지를 선택해 주세요.':'가장 관심 있는 업무를 선택해 주세요.')+'</p><div class="use-options">'+p.uses.map(function(u){return '<label><input type="radio" name="use" aria-describedby="use-error" value="'+u.id+'"'+(selectedUse===u.id?' checked':'')+'>'+i(u.icon)+'<span>'+h(u.title)+'</span></label>';}).join('')+'</div><p class="error" id="use-error" hidden>관심 기능을 선택해 주세요.</p></fieldset><div class="form-two"><div class="formfield"><label for="consult-name">이름 <span class="muted">선택</span></label><input id="consult-name" name="name" maxlength="40" autocomplete="off" placeholder="이름을 입력해 주세요."></div><div class="formfield"><label for="consult-company">회사 · 기관 <span class="muted">선택</span></label><input id="consult-company" name="company" maxlength="80" autocomplete="off" placeholder="회사 또는 기관명"></div></div><fieldset class="contact-fieldset"><legend>연락받을 방법 <span class="required">필수</span></legend><div class="contact-method"><label><input type="radio" name="method" value="phone" checked>'+i('phone-duotone')+'전화</label><label><input type="radio" name="method" value="email">'+i('envelope-duotone')+'이메일</label></div><div class="formfield"><label id="contact-label" for="consult-contact">연락처</label><input id="consult-contact" name="contact" type="tel" inputmode="tel" autocomplete="off" maxlength="100" placeholder="연락받을 번호를 입력해 주세요." aria-describedby="contact-error"><p class="error" id="contact-error" hidden></p></div></fieldset><div class="formfield"><label for="consult-request">어떤 일에 활용하고 싶으세요? <span class="muted">선택</span></label><textarea id="consult-request" name="request" maxlength="1500" rows="4" placeholder="활용 업무, 현재 PC, 필요한 기능 등을 간단히 적어주세요."></textarea><small>문서 원본 · 비밀번호 · 민감한 개인정보는 입력하지 마세요.</small></div><div class="consent-box"><label><input type="checkbox" id="consult-consent" name="contactRequested" aria-describedby="consent-error"> <span>상담 안내를 위해 입력한 연락처로 연락받기를 요청합니다. <span class="required">필수</span></span></label><details><summary>연락 요청 안내 '+i('caret-down')+'</summary><p>상담을 신청하면 선택한 연락 방법으로 안내를 요청하게 됩니다. 연락받을 방법과 입력 내용을 확인해 주세요.</p></details><p class="error" id="consent-error" hidden>상담 연락 요청 확인란을 선택해 주세요.</p></div><button class="btn btn-primary btn-full" type="submit">도입 상담 신청하기 '+i('arrow-right')+'</button><p class="error" id="consult-submit-error" role="alert" tabindex="-1" hidden></p><p class="ai-footnote">선택한 연락 방법으로 상담 안내를 요청합니다.</p></form></div></div><div id="consult-output" hidden aria-live="polite"></div>';
    return {html:'<div class="container">' + crumb('도입 상담') + form + '</div>', mount:function () {
      var form = document.getElementById('ai-consult-form');
      var contact = document.getElementById('consult-contact');
      var output = document.getElementById('consult-output');
      var input = document.getElementById('consult-input');
      var submitButton = form.querySelector('[type="submit"]');
      var submitLabel = submitButton.innerHTML;
      var submitting = false, accepted = false;
      var failedMessage = '상담을 접수하지 못했습니다. 잠시 후 다시 시도해 주세요.';

      function showError(id, text) {
        var element = document.getElementById(id);
        element.hidden = !text;
        element.textContent = text || '';
      }
      function setBusy(busy) {
        submitting = busy;
        form.setAttribute('aria-busy', String(busy));
        submitButton.disabled = busy || accepted;
        submitButton.innerHTML = busy ? '신청 내용을 확인하고 있습니다.' : accepted ? '상담 접수 완료' : submitLabel;
      }
      function showFailure() {
        showError('consult-submit-error', failedMessage);
        document.getElementById('consult-submit-error').focus();
      }
      form.querySelectorAll('[name=method]').forEach(function (radio) {
        radio.addEventListener('change', function () {
          var email = radio.value === 'email';
          contact.type = email ? 'email' : 'tel';
          contact.inputMode = email ? 'email' : 'tel';
          contact.placeholder = email ? '이메일 주소를 입력해 주세요.' : '연락받을 번호를 입력해 주세요.';
          document.getElementById('contact-label').textContent = email ? '이메일 주소' : '연락처';
          contact.value = '';
          contact.removeAttribute('aria-invalid');
          showError('contact-error', '');
        });
      });
      function showResult(status, use, requestId) {
        input.hidden = true;
        output.hidden = false;
        output.innerHTML = resultMarkup(p, status, use, requestId);
        output.querySelector('[data-return-form]').addEventListener('click', function () {
          output.hidden = true;
          output.innerHTML = '';
          input.hidden = false;
          var chosen = form.querySelector('[name=use]:checked') || form.querySelector('[name=use]');
          if (chosen) chosen.focus();
        });
        document.getElementById('result-title').focus();
        output.scrollIntoView({block:'start'});
      }

      // Optional adapter: PAI.submitConsult(payload) -> Promise<{status:'accepted'|'pending'|'failed', requestId?:string}>.
      // contactRequested confirms a contact request only; it is not privacy-policy consent.
      // The adapter owns the real endpoint and approved privacy-policy requirements.
      // This file never creates a network request or persists contact details.
      form.addEventListener('submit', function (event) {
        event.preventDefault();
        if (submitting || accepted) return;
        var use = form.querySelector('[name=use]:checked');
        var method = form.querySelector('[name=method]:checked').value;
        var value = contact.value.trim();
        var confirmation = document.getElementById('consult-consent');
        var validContact = method === 'email' ? /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value) : /^(0\d{8,10}|\+82\d{8,10})$/.test(value.replace(/[\s()-]/g, ''));
        showError('consult-submit-error', '');
        showError('use-error', use ? '' : '관심 기능을 선택해 주세요.');
        showError('contact-error', validContact ? '' : method === 'email' ? '올바른 이메일 주소를 입력해 주세요.' : '올바른 연락처를 입력해 주세요.');
        showError('consent-error', confirmation.checked ? '' : '상담 연락 요청 확인란을 선택해 주세요.');
        form.querySelectorAll('[name=use]').forEach(function (radio) { radio.setAttribute('aria-invalid', String(!use)); });
        contact.setAttribute('aria-invalid', String(!validContact));
        confirmation.setAttribute('aria-invalid', String(!confirmation.checked));
        if (!use) { form.querySelector('[name=use]').focus(); return; }
        if (!validContact) { contact.focus(); return; }
        if (!confirmation.checked) { confirmation.focus(); return; }
        if (typeof P.submitConsult !== 'function') { showFailure(); return; }

        var payload = {
          packageId:p.id,
          use:use.value,
          contactMethod:method,
          contact:value,
          name:document.getElementById('consult-name').value.trim(),
          company:document.getElementById('consult-company').value.trim(),
          request:document.getElementById('consult-request').value.trim(),
          contactRequested:confirmation.checked
        };
        var submitConsult = P.submitConsult;
        setBusy(true);
        Promise.resolve().then(function () {
          return submitConsult.call(P, payload);
        }).then(function (result) {
          if (result && result.status === 'accepted') {
            accepted = true;
            showResult('received', payload.use, result.requestId);
          } else if (result && result.status === 'failed') {
            showResult('failed', payload.use);
          } else {
            showResult('pending', payload.use);
          }
        }, function () {
          // A lost response cannot prove non-receipt; avoid suggesting an automatic retry.
          showResult('pending', payload.use);
        }).then(function () { setBusy(false); });
      });
    }};
  };

  P.pages['ai-result'] = function () {
    var p = pkg();
    // A URL query is not evidence of receipt. Confirmed results stay in the submitting page.
    return {html:'<div class="container">' + crumb('상담 신청') + resultMarkup(p, 'neutral', P.qs.get('use')) + '</div>', mount:function () {
      document.querySelector('[data-return-form]').addEventListener('click', function () {
        location.href = link('ai-consult', {package:p.id, use:P.qs.get('use')});
      });
    }};
  };

  P.pages.bridge = function () {
    var target = P.qs.get('target');
    if (!target || target === 'recommend') return {html:'<div class="container"><section class="bridge-page"><span class="ai-icon">'+i('chat-text-duotone')+'</span><span class="eyebrow">POPCORN AI</span><h1>AI로 내 PC 찾기</h1><p>용도와 예산을 알려주시면 함께 살펴볼게요.</p><a class="btn btn-primary" href="'+P.href('pc-finder')+'">대화 시작하기 '+i('arrow-right')+'</a><a class="text-link" href="index.html">첫 화면으로 '+i('arrow-left')+'</a></section></div>'};
    var map = {
      recommend:['PC 추천받기', '원하는 용도와 예산으로 PC를 찾아보세요.', 'monitor'],
      custom:['맞춤 견적', '직접 부품을 고르고 구성을 살펴보세요.', 'file-text'],
      saved:['내 견적', '저장한 견적을 이어서 확인하세요.', 'clipboard-text']
    };
    var s = map[target] || map.recommend;
    target = map[target] ? target : 'recommend';
    var url = P.config.integration[target];
    var enabled = P.config.integration.liveLinksEnabled === true && location.protocol !== 'file:' && /^\/mvp[13]\//.test(url);
    return {html:'<div class="container"><section class="bridge-page"><span class="ai-icon">' + i(s[2]) + '</span><span class="eyebrow">팝콘AI 서비스</span><h1>' + s[0] + '</h1><p>' + s[1] + '</p><div class="notice">' + i('info') + '<p>' + (enabled ? '선택하신 서비스를 이어서 이용해 보세요.' : '지금은 서비스를 연결할 수 없습니다. 잠시 후 다시 이용해 주세요.') + '</p></div>' + (enabled ? '<a class="btn btn-primary" href="' + h(url) + '">서비스로 이동 ' + i('arrow-right') + '</a>' : '<button class="btn btn-primary" disabled>현재 연결할 수 없습니다</button>') + '<a class="text-link" href="index.html">첫 화면으로 ' + i('arrow-left') + '</a><small>견적 보관은 상담 신청과 별개입니다. 상담은 별도 신청을 통해 진행합니다.</small></section></div>'};
  };

  P.pages.support = function () {
    return {html:'<div class="container">' + crumb('고객지원') + '<section class="ai-intro"><span class="eyebrow">POPCORN AI SUPPORT</span><h1>구매 전부터, 사용하면서도.</h1><p>필요한 안내를 한곳에서 확인하세요.</p></section><div class="support-grid"><a href="ai-consult.html?package=business">' + i('chat-circle') + '<h2>AI 도입 상담</h2><p>업무와 필요한 기능부터</p>' + i('arrow-right') + '</a><a href="bridge.html?target=custom">' + i('file-text') + '<h2>PC 맞춤 견적</h2><p>원하는 구성 살펴보기</p>' + i('arrow-right') + '</a><a href="#sales-policy">' + i('headset') + '<h2>배송 · A/S 안내</h2><p>구매 전 확인할 사항</p>' + i('arrow-right') + '</a></div><section class="policy-section" id="sales-policy"><h2>배송 · A/S · 쇼핑몰 운영정책</h2><p>배송비와 출고 일정, 보증 및 반품·A/S 조건은 상품별로 다를 수 있습니다. 구매하실 판매 페이지의 안내를 확인해 주세요.</p></section><section class="policy-section" id="terms"><h2>이용약관</h2><p>이용약관은 검토 중입니다.</p><a class="text-link" href="terms.html">이용약관 화면 ' + i('arrow-right') + '</a></section><section class="policy-section" id="privacy"><h2>개인정보처리방침</h2><p>개인정보처리방침은 검토 중입니다.</p><a class="text-link" href="privacy.html">개인정보처리방침 화면 ' + i('arrow-right') + '</a></section><section class="policy-section" id="company"><h2>회사정보</h2><p>팝콘AI 운영사는 주식회사 팝콘컴퓨터입니다.</p><a class="text-link" href="company.html">회사정보 보기 ' + i('arrow-right') + '</a></section><section class="policy-section"><h2>저작권 및 라이선스</h2><p>서비스에 사용된 글꼴과 아이콘의 라이선스 정보를 확인할 수 있습니다.</p><a class="text-link" href="credits.html">라이선스 안내 ' + i('arrow-right') + '</a></section></div>'};
  };
}());
