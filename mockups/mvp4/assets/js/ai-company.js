/* 30인 이하 기업 AI 업무개선 컨설팅 설명 화면 (/mvp4/ai-company.html, 논리 화면 E).
   2026-10-21 대표 승인 정본 approved-detail-displayed-3.png(SHA256 a25c69bc…)의 읽는 순서·위계를 반응형 HTML 로 옮겼다.
   - 정본 이미지를 통째로 붙이지 않는다. 사진 두 장만 개별 자산으로 쓴다(assets/images/company/SOURCES.json) — 가상 소개 사진이다.
   - 「실제 업무 예시 살펴보기」는 「업무 예시 살펴보기」로 고쳐 같은 화면의 가상 사례로 보낸다.
   - 상담은 아래 「기업 컨설팅 상담하기」 링크로만 간다(company-routes.js). 이 화면은 아무것도 보내거나 저장하지 않는다.
   - AI 보조/사람 확인은 색과 함께 글자로도 표시한다. 재고·가격·배송 자동 조회나 자동 발송을 말하지 않는다. */
(function () {
  'use strict';
  var P = window.PAI, h = P.h, i = P.icon, R = P.companyRoute;
  var FLOW = [
    {n: 1, role: 'ai', title: '문의 정리', icon: 'clipboard-text', items: ['수량 10대', '희망일 다음 주', '확인할 질문: 납품 가능 여부']},
    {n: 2, role: 'human', title: '사람이 확인', icon: 'check-circle', items: ['재고 확인', '납기 확인', '판매 조건 확인']},
    {n: 3, role: 'ai', title: '초안 작성', icon: 'file-text', items: ['확인된 조건 반영', '회사 승인 안내문 포함']},
    {n: 4, role: 'human', title: '검토·발송', icon: 'envelope', items: ['담당자가 내용 확인', '승인 후 담당자가 발송']}
  ];
  var QUESTIONS = [
    ['note-pencil-duotone', '중복 입력은 어디에 있나요?', '여러 문서와 시스템에 같은 내용을 반복 입력하는 지점을 함께 찾습니다.'],
    ['users', '누가 확인하고 승인하나요?', '업무마다 필요한 확인과 승인 절차를 정리합니다.'],
    ['check-circle', '어떤 업무부터 시작할까요?', '효과를 확인할 수 있는 작은 범위부터 우선순위를 정합니다.']
  ];
  var STEPS = [
    ['magnifying-glass', '업무 파악', '우리 회사의 주요 업무와 현재 방식, 어려운 지점을 함께 살펴봅니다.'],
    ['squares-four', '현재 흐름도', '여러 담당자가 함께하는 업무 흐름을 그려 개선할 지점을 찾습니다.'],
    ['funnel', '개선 우선순위', '효과와 준비 여건을 고려해 먼저 적용할 업무 범위를 정합니다.'],
    ['wrench', '작은 범위 시범 적용', '선정한 업무에 AI를 적용해 실제 업무에서 쓸 수 있는지 함께 확인합니다.'],
    ['check', '결과 확인 후 확대', '시범 적용 결과를 바탕으로 다른 업무로의 확대 방안을 검토합니다.']
  ];
  function role(r) { return r === 'ai' ? '<span class="co-role co-role-ai">AI 보조</span>' : '<span class="co-role co-role-human">' + i('user', 'co-role-icon') + '사람 확인</span>'; }
  function crumb() { return '<nav class="breadcrumb" aria-label="현재 위치"><a href="index.html">홈</a>' + i('caret-right') + '<a href="ai-packages.html">AI 패키지</a>' + i('caret-right') + '<a href="ai-detail.html?package=business">업무형</a>' + i('caret-right') + '<span>기업 컨설팅</span></nav>'; }
  function body() {
    var f = R.from(), src = R.source(f);
    return '<div class="co-page" id="company-consulting" data-from="' + h(f || 'direct') + '">' +
      '<a class="co-return text-link" id="co-return" href="' + h(src.href) + '">' + i('arrow-left') + h(src.label) + '</a>' +
      '<section class="co-hero" aria-labelledby="co-title"><div class="co-hero-copy">' +
        '<span class="co-target">30인 이하 기업 대상</span>' +
        '<h1 id="co-title">작은 회사에 맞게.<br>한 가지 업무부터, 제대로.</h1>' +
        '<p class="co-lead">우리 회사의 업무를 살펴보고, AI가 도울 지점과<br>사람이 판단할 지점을 함께 정합니다.</p>' +
        '<p class="co-scope-note">직원 30명 이하(30명 포함) 회사를 위한 별도 컨설팅입니다. 개인 업무용 AI 패키지 설치나 장비 견적과는 따로 상담합니다.</p>' +
        '<a class="co-primary" href="#company-case">업무 예시 살펴보기 ' + i('arrow-right', 'co-down') + '</a>' +
        '<a class="co-personal text-link" href="ai-detail.html?package=business#uses">내 업무용 로컬 AI가 필요하다면 ' + i('arrow-right') + '</a>' +
      '</div><figure class="co-hero-photo"><img src="assets/images/company/company-consulting-hero.jpg" alt="상담하는 모습을 연출한 가상 소개 사진" width="489" height="378"></figure></section>' +
      '<section class="co-card co-case" id="company-case" aria-labelledby="co-case-title" tabindex="-1">' +
        '<span class="co-tag">가상 사례 · 15명 유통회사</span>' +
        '<h2 id="co-case-title">견적 답변 하나, 왜 여러 번 손이 갈까요?</h2>' +
        '<div class="co-chat">' + i('user', 'co-avatar') + '<p>제품 10대가 필요해요. 다음 주에 받을 수 있나요?</p><time>오전 10:24</time></div>' +
        '<ol class="co-flow" aria-label="문의 하나를 처리하는 흐름">' + FLOW.map(function (s) {
          return '<li class="co-step co-step-' + s.role + '"><div class="co-step-head"><span class="co-num">' + s.n + '</span><h3>' + s.title + '</h3>' + role(s.role) + '</div>' + i(s.icon, 'co-step-icon') + '<ul>' + s.items.map(function (x) { return '<li>' + h(x) + '</li>'; }).join('') + '</ul></li>';
        }).join('') + '</ol>' +
        '<p class="co-legend"><span><i class="co-dot co-dot-ai" aria-hidden="true"></i>보라색: AI 보조</span><span><i class="co-dot co-dot-human" aria-hidden="true"></i>노란색: 사람 확인</span></p>' +
        '<p class="co-summary">' + i('info', 'co-summary-icon') + 'AI는 정리와 초안을 돕고, 조건 확인과 최종 발송은 담당자가 합니다.</p>' +
        '<p class="co-small">회사·문의·수량·시각은 모두 가상 예시입니다. AI가 재고·가격·배송을 직접 조회하거나 고객에게 자동으로 발송하지 않습니다.</p>' +
      '</section>' +
      '<div class="co-two">' +
        '<section class="co-card co-questions" aria-labelledby="co-q-title"><span class="co-eyebrow">함께 보는 우리 회사의 업무</span><h2 id="co-q-title">개인의 도구를 넘어,<br>함께 일하는 흐름을 살펴봅니다.</h2><p class="co-muted">반복되는 업무만이 아니라, 여러 사람이 함께 처리하는<br>업무 흐름 전체를 확인해 우리 회사에 맞는 도입 방향을 제안합니다.</p><ul class="co-q-list">' + QUESTIONS.map(function (q) { return '<li>' + i(q[0], 'co-q-icon') + '<div><h3>' + q[1] + '</h3><p>' + q[2] + '</p></div></li>'; }).join('') + '</ul></section>' +
        '<section class="co-card co-process" aria-labelledby="co-p-title"><span class="co-eyebrow">기업 AI 업무개선 컨설팅 진행 단계</span><h2 id="co-p-title">우리 회사에 맞는 순서로, 함께 진행합니다.</h2><ol class="co-steps">' + STEPS.map(function (s, n) { return '<li><span class="co-step-no">' + (n + 1) + '</span>' + i(s[0], 'co-p-icon') + '<div><h3>' + s[1] + '</h3><p>' + s[2] + '</p></div></li>'; }).join('') + '</ol></section>' +
      '</div>' +
      '<section class="co-cta" id="company-consult" aria-labelledby="co-cta-title" tabindex="-1"><div class="co-cta-copy"><span class="co-tag">기업 AI 업무개선 컨설팅 · 30인 이하 기업 대상</span><h2 id="co-cta-title">우리 회사의 첫 적용 업무를 찾아보세요.</h2>' +
        '<a class="co-primary" id="co-consult-link" href="' + R.consult(f) + '">기업 컨설팅 상담하기 ' + i('arrow-right') + '</a>' +
        '<ul class="co-checks"><li>' + i('check-circle') + '진단·설계와 실제 구축, 시스템 연동·시범 적용·운영 지원의 범위는 별도로 정합니다.</li><li>' + i('check-circle') + '자료 처리와 외부 연결 방식은 회사 환경을 확인한 뒤 설계합니다. 로컬 LLM을 쓰는 것만으로 외부 전송 없음이나 회사 전체 보안을 보장하지 않습니다.</li><li>' + i('check-circle') + '이 화면을 본 것만으로 상담이 접수되거나 연락 동의가 되지 않습니다.</li></ul>' +
        '<a class="co-personal text-link" href="ai-detail.html?package=business#uses">개인 업무 자동화 예시로 돌아가기 ' + i('arrow-right') + '</a>' +
      '</div><figure class="co-cta-photo"><img src="assets/images/company/company-consulting-cta.jpg" alt="업무 흐름도를 함께 살펴보는 모습을 연출한 가상 소개 사진" width="420" height="183"></figure></section>' +
    '</div>';
  }
  // 「업무 예시 살펴보기」 — 주소에 #company-case 를 남기고, 제목이 보이는 자리로 옮긴 뒤 초점을 사례로 보낸다.
  function mount() {
    var link = document.querySelector('.co-hero .co-primary');
    if (link) link.addEventListener('click', function (e) {
      var target = document.getElementById('company-case');
      if (!target) return;
      e.preventDefault();
      if (location.hash !== '#company-case') history.pushState(null, '', '#company-case');
      target.scrollIntoView({block: 'start'});
      target.focus({preventScroll: true});
    });
  }
  P.pages['ai-company'] = function () {
    document.title = '30인 이하 기업 AI 업무개선 컨설팅 | 팝콘AI';
    return {html: '<div class="container">' + crumb() + body() + '</div>', mount: mount};
  };
}());
