/* 30인 이하 기업 AI 업무개선 컨설팅 — 화면 배선 (2026-10-21 대표 승인 「그렇게 해서.. 넘겨줘.. 그리고 화면 배선 정리 잘하고..」).
   어디서 들어왔는지(from)는 아래 정해진 값만 받는다. 그 밖의 값·외부 주소·임의 URL 은 버리고 업무형 안내로 보낸다.
     P = 업무형 상세의 개인/기업 구분 · D/M/R = 사내 문서 검색 / 회의록 정리 / 고객 답변 초안 설명 하단 · 없음 = 직접 진입
     T/U/W = 기본형 학습 자료 정리 / 자료 요약 / 글쓰기 초안, G/C = 고급형 이미지 제작 / 개발 보조 설명 하단(2026-10-23 승인, ai-task-guides.js)
   복귀 위치는 같은 /mvp4 안의 정해진 화면·앵커뿐이고, 저장소를 쓰지 않으므로 다른 탭의 흐름과 섞이지 않는다(주소가 곧 상태). */
(function () {
  'use strict';
  var P = window.PAI;
  var SOURCES = {
    P: {href: 'ai-detail.html?package=business#service-choice', label: '업무형 패키지로 돌아가기', name: '업무형 소개'},
    D: {href: 'ai-service.html?package=business&use=documents#company-link', label: '사내 문서 검색 설명으로 돌아가기', name: '사내 문서 검색 설명'},
    M: {href: 'ai-service.html?package=business&use=meetings#company-link', label: '회의록 정리 설명으로 돌아가기', name: '회의록 정리 설명'},
    R: {href: 'ai-service.html?package=business&use=replies#company-link', label: '고객 답변 초안 설명으로 돌아가기', name: '고객 답변 초안 설명'},
    T: {href: 'ai-service.html?package=basic&use=study#company-link', label: '학습 자료 정리 설명으로 돌아가기', name: '학습 자료 정리 설명'},
    U: {href: 'ai-service.html?package=basic&use=summary#company-link', label: '자료 요약 설명으로 돌아가기', name: '자료 요약 설명'},
    W: {href: 'ai-service.html?package=basic&use=writing#company-link', label: '글쓰기 초안 설명으로 돌아가기', name: '글쓰기 초안 설명'},
    G: {href: 'ai-service.html?package=advanced&use=image#company-link', label: '이미지 제작 설명으로 돌아가기', name: '이미지 제작 설명'},
    C: {href: 'ai-service.html?package=advanced&use=code#company-link', label: '개발 보조 설명으로 돌아가기', name: '개발 보조 설명'}
  };
  var FALLBACK = {href: 'ai-detail.html?package=business#service-choice', label: 'AI 패키지로 돌아가기', name: '직접 방문'};
  function from() { var f = P.qs.get('from'); return Object.prototype.hasOwnProperty.call(SOURCES, f) ? f : ''; }
  P.companyRoute = {
    SERVICE: 'company',
    from: from,
    source: function (f) { return Object.prototype.hasOwnProperty.call(SOURCES, f) ? SOURCES[f] : FALLBACK; },
    explain: function (f, anchor) { return 'ai-company.html' + (SOURCES[f] ? '?from=' + f : '') + (anchor ? '#' + anchor : ''); },
    consult: function (f) { return 'ai-consult.html?service=company&amp;intent=adoption' + (SOURCES[f] ? '&amp;from=' + f : ''); }
  };
}());
