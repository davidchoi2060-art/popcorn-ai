/* 회사 맞춤 내부 AI 구축 — 업무형 「사내 문서 검색」 설명 화면 (/mvp4/ai-service.html?package=business&use=documents).
   2026-10-21 대표 승인 「사내문서 검색을 누르면 업무 예시랑 우리 회사에 맞게 구축해주는 과정을 먼저 보여주고, 그다음 상담으로
   이어지게 해줘. 기존 헤더랑 메뉴는 그대로 두고.」 정본 business-local-ai-service.html(SHA256 772629e8…)의 본문만 옮겼다.
   - 사이트 공통 셸(헤더·메뉴·띠메뉴·푸터)은 boot.js 가 그대로 그린다. 승인 시안의 window.openai 상태 연동은 옮기지 않는다.
   - 시안의 「상담 연결 미리보기」는 실제 연결(ai-consult.html?package=business&use=documents&intent=adoption)로 바꿨다.
     이 화면은 아무것도 보내지 않는다(네트워크 요청·저장·동의 없음). 비교 탭·단계·사례 버튼은 화면 표시만 바꾼다.
   - 문서·금액·답변은 가상 예시이고, 내부 전용은 구축·통신 검증 뒤 확정하는 목표라는 표시를 그대로 둔다. */
(function () {
  'use strict';
  var P = window.PAI, h = P.h, i = P.icon;
var stages=[
  {title:'먼저, 어떤 업무를 내부에서 처리할지 정합니다.',provider:'반복되는 질문과 자료 유형을 살펴보고, 내부 실행이 필요한 범위를 함께 정리합니다.',customer:'사용 부서·인원, 문서 보관 위치, 외부 전송이 금지된 정보와 접속 제한 조건을 확인합니다.',output:'합의할 결과물: 대상 업무 · 자료 범위 · 외부 연결 제한 요구사항'},
  {title:'장비와 설치 방식, 제공 범위를 견적에 담습니다.',provider:'필요 장비와 AI 설치 방식을 검토하고, 자료 연결·교육·지원의 포함 여부를 구분합니다.',customer:'구성·비용·일정·담당 책임을 확인합니다. 내부 전용인지 외부 API 연결형인지 분명히 정합니다.',output:'합의할 결과물: 구성안 · 견적 · 제공 항목과 제외 항목'},
  {title:'합의한 범위 안에서 장비와 AI를 구성합니다.',provider:'장비·AI 실행 환경을 구성하고, 계약에 포함된 자료 연결과 접근 설정을 진행합니다.',customer:'사용 가능한 자료와 유효한 문서 버전, 사용자 범위, 설치 위치를 확인합니다.',output:'합의할 결과물: 설치 구성 · 연결 자료 목록 · 접속 방법'},
  {title:'고객의 실제 질문과 통신 경로로 확인합니다.',provider:'예시 질문의 답변·출처·모르는 내용 처리를 점검하고, 외부 접근과 외부 전송 여부를 확인합니다.',customer:'실무에 쓸 수 있는 결과인지 검토합니다. 품질·속도·허용 범위와 남은 문제를 함께 확인합니다.',output:'합의할 결과물: 업무별 검수 결과 · 통신 점검 범위와 결과 · 보완 사항'},
  {title:'직원이 사용할 수 있도록 안내하고 인계합니다.',provider:'합의한 사용 안내와 운영 문서를 전달합니다. 지원 기간·접수 방법·유지보수는 정한 범위로 안내합니다.',customer:'담당자를 정하고, 자료 변경·사용자 변경·장애 발생 시의 처리 방법을 확인합니다.',output:'합의할 결과물: 사용 안내 · 자료 갱신 방법 · 지원 범위와 연락 절차'}
 ];
 var examples={
  policy:{title:'신입 직원이 교육 신청 규정을 확인할 때',setup:'교육비 규정과 신청서 안내 중 유효한 자료를 지정합니다. 읽을 수 있는 직원과 자료 갱신 담당자를 정하고, 내부 AI에서 검색할 범위를 구성합니다.',question:'외부 교육을 신청하려는데, 지원 한도와 신청 순서를 알려줘.',answer:'<strong>가상 규정의 연간 지원 한도는 <mark>30만 원</mark>입니다.</strong><ul><li>교육명과 필요성을 신청서에 작성합니다.</li><li><mark>신청 전에 팀장 승인</mark>을 받습니다.</li><li>승인된 신청서를 교육 담당 부서에 제출합니다.</li></ul><p>개인별 남은 한도는 이 자료에서 확인되지 않습니다.</p>',sourceLabel:'가상 교육비 규정 §3·신청서 안내 · 내부 원문 보기',source:'<strong>내부 문서 발췌 · 가상 예시</strong><p>교육비 지원 규정 §3: “외부 교육비는 직원 1인당 <mark>연간 30만 원 한도</mark>로 지원한다. 신청 전 팀장 승인을 받아야 한다.”</p><p>교육 신청서 안내: “교육명과 필요성을 작성한 뒤 팀장 승인을 받고, 승인된 신청서를 교육 담당 부서에 제출한다.”</p><p>자료 위치 예시: 인사 공용 자료 / 교육비 지원 규정·교육 신청서 안내. 이 버튼은 외부 문서 서비스로 연결되지 않습니다.</p>',outcome:'직원은 조건을 확인하고 신청서를 준비합니다.',detail:'팝콘AI의 구성 범위는 이 질문에 필요한 자료와 확인 경로를 마련하는 것입니다. 실제 신청·승인은 회사 담당자가 처리합니다.'},
  sales:{title:'영업 담당자가 고객 제안서의 근거를 모을 때',setup:'사내 제품 소개서·적용 사례·제안서 양식 중 공유 가능한 자료를 정합니다. 고객별 비공개 자료를 섞지 않도록 연결 범위와 열람 대상을 별도로 확인합니다.',question:'직원 30명이 사용할 문서 검색 서비스를 제안하려고 해. 기존 자료에서 근거를 찾아줘.',answer:'<strong><mark>확인된 기능과 적용 조건</mark>을 구분해 정리할 수 있습니다.</strong><ul><li>가상 소개서에는 문서 검색과 출처 확인 기능이 있습니다.</li><li>가상 구축 사례는 직원 20명이 사용한 예시입니다.</li><li><mark>30명 환경의 비용·성능은 자료에 없습니다.</mark></li></ul>',sourceLabel:'가상 제품 소개서·구축 사례 · 내부 원문 보기',source:'<strong>내부 문서 발췌 · 가상 예시</strong><p>소개서: “검색한 문서의 근거를 함께 표시한다.”</p><p>구축 사례: “사용 대상은 <mark>직원 20명</mark>이다.” 30명 환경의 성능이나 비용을 확정하는 내용은 없습니다.</p>',outcome:'회사 양식에 맞춰 제안서 초안을 준비합니다.',detail:'자료 연결과 양식 지원은 계약에 포함된 범위로 구성합니다. 영업 담당자는 비용·적용 조건을 확인한 뒤 고객에게 제안합니다.'},
  support:{title:'고객에게 설치 준비 사항을 안내할 때',setup:'설치 안내서와 고객 응대 지침을 지정합니다. 준비 사항을 찾는 기능과 실제 설치 일정을 조회하는 기능은 구분하고, 일정 시스템 연동은 별도 검토합니다.',question:'고객이 다음 주 설치 전에 무엇을 준비해야 하냐고 물었어. 안내할 내용을 정리해줘.',answer:'<strong>가상 안내서의 <mark>사전 준비 사항</mark>입니다.</strong><ul><li>설치 공간과 전원 위치를 확인합니다.</li><li>네트워크 연결 가능 여부를 확인합니다.</li><li>당일 함께 확인할 담당자를 정합니다.</li></ul><p><mark>다음 주 설치 가능 여부는 문서에서 확인되지 않습니다.</mark></p>',sourceLabel:'가상 설치 사전 안내서 p.3 · 내부 원문 보기',source:'<strong>내부 문서 발췌 · 가상 예시</strong><p>“설치 공간, 전원, 네트워크 연결 여부를 확인한다. 현장 담당자를 지정한다.”</p><p>응대 지침: “일정 담당자의 확인을 받은 뒤 설치 일정을 안내한다.”</p>',outcome:'담당자가 초안을 검토한 뒤 고객에게 회신합니다.',detail:'내부 AI는 안내 자료와 초안 작성을 돕습니다. 고객 회신은 직원이 선택하는 별도 업무이며, ‘AI 내부 처리’가 모든 외부 연락의 금지를 뜻하지는 않습니다.'}
 };

  function crumb(label) { return '<nav class="breadcrumb" aria-label="현재 위치"><a href="index.html">홈</a>' + i('caret-right') + '<a href="ai-packages.html">AI 패키지</a>' + i('caret-right') + '<a href="ai-detail.html?package=business">업무형</a>' + i('caret-right') + '<span>' + h(label) + '</span></nav>'; }
  function body() {
    return '<div class="ls-page" id="pop-local-service" data-use="documents">' +
      '<section class="ls-hero">' +
      '  <div class="ls-eyebrow">팝콘AI 업무 도입 패키지</div>' +
      '  <h1>회사 자료는 회사 안에.<br>AI는 우리 업무에 맞게.</h1>' +
      '  <p class="ls-lead">우리 회사 장비와 자료, 일하는 방식에 맞춰<br>AI를 도입하는 과정을 함께 설계합니다.</p>' +
      '  <div class="ls-row"><span class="ls-pill">' + i('shield', 'ls-icon') + '내부 전용 구축 목표</span><span class="ls-pill">PC 구성 · AI 설치 · 사용 안내</span></div>' +
      '  <div class="ls-promise"><strong>외부 전송 없는 내부 전용 환경을 목표로 상담합니다.</strong><br>자료 저장 위치와 실제 통신 경로를 점검한 뒤 적용 범위를 확정합니다.</div>' +
      '</section>' +
      '<section class="ls-section" aria-labelledby="ls-network-title">' +
      '  <div class="ls-eyebrow">01 · 데이터가 어디로 가는지가 다릅니다</div><h2 id="ls-network-title">문서도, 질문도, AI 처리도<br>회사 내부에서 끝나는 구성.</h2>' +
      '  <p class="ls-lead">‘사내 PC에서 접속’하는 것만으로는 충분하지 않습니다. 답을 만드는 AI 모델까지 어디에서 실행되는지 확인합니다.</p>' +
      '  <div class="ls-toggle" role="group" aria-label="데이터 처리 구조 비교"><button type="button" data-mode="internal" aria-pressed="true">내부 전용 목표 구성</button><button type="button" data-mode="api" aria-pressed="false">외부 API 연결 구성과 비교</button></div>' +
      '  <div aria-live="polite">' +
      '    <div class="ls-boundary">' +
      '      <div class="ls-boundary-head"><strong>' + i('squares-four', 'ls-icon') + '우리 회사 내부망</strong><span class="ls-small" id="ls-mode-caption">제안 구성 · 구축 후 검증</span></div>' +
      '      <div class="ls-net" id="ls-network-flow" role="group" aria-label="사내 문서와 질문이 내부 AI 장비를 거쳐 직원에게 돌아오는 구조">' +
      '        <div class="ls-net-node">' + i('file-text-duotone', 'ls-icon') + '<strong>회사 자료</strong><small>선택한 규정·매뉴얼<br>검색용 색인도 내부 보관</small></div><div class="ls-net-arrow" aria-hidden="true">→</div>' +
      '        <div class="ls-net-node">' + i('hard-drive', 'ls-icon') + '<strong id="ls-engine-title">사내 AI 장비</strong><small id="ls-engine-text">문서 검색 + AI 모델 실행<br>질문·답변·기록 내부 처리</small></div><div class="ls-net-arrow" aria-hidden="true">↔</div>' +
      '        <div class="ls-net-node">' + i('monitor', 'ls-icon') + '<strong>직원의 업무 화면</strong><small>질문 → 근거 답변 확인<br>원문 검토 후 업무에 활용</small></div>' +
      '      </div>' +
      '      <div class="ls-net-foot" id="ls-data-tags"><span>문서</span><span>검색용 색인</span><span>질문·답변</span><span>처리 기록</span><span>모델 실행</span></div>' +
      '    </div>' +
      '    <div class="ls-outside" id="ls-outside" data-connected="false">' + i('plug', 'ls-icon') + '<div><strong id="ls-outside-title">외부 AI 서비스로 보내는 경로를 두지 않는 설계</strong><p id="ls-outside-text">인터넷 검색·외부 AI API·클라우드 저장을 사용하는 구성에는 이 설명을 적용하지 않습니다.</p></div></div>' +
      '  </div>' +
      '  <div class="ls-safety-pair"><article><h3>밖에서 들어오지 못하도록</h3><p>인터넷 공개 여부, 접속 경로, 사용자를 확인합니다. 원격 접속도 별도로 정합니다.</p></article><article><h3>안의 업무 내용이 나가지 않도록</h3><p>문서·질문·답변뿐 아니라 검색용 데이터, 백업과 처리 기록의 외부 전송도 확인합니다.</p></article></div>' +
      '  <details class="ls-tech-note"><summary>‘외부망 비노출’은 무엇을 확인한 뒤 말하나요?</summary><ul><li>외부에서 접속 가능한 주소·통로가 없는지</li><li>답변 생성과 문서 검색에 외부 AI API가 쓰이지 않는지</li><li>문서·검색용 데이터·질문·답변·로그가 외부로 전송되지 않는지</li><li>업데이트·원격지원·백업·진단 기능에 외부 연결이 있는지</li><li>고객이 정한 사용 환경에서 실제 통신 점검을 통과했는지</li></ul><p>인터넷 연결을 물리적으로 끊는 구성인지, 통신 정책으로 제한하는 구성인지도 구분합니다. 이 그림은 구축 목표이며 보안 검증 완료 증명은 아닙니다.</p></details>' +
      '</section>' +
      '<div class="ls-divider"></div>' +
      '<section class="ls-section" aria-labelledby="ls-compare-title">' +
      '  <div class="ls-eyebrow">02 · ChatGPT와 무엇이 다른가요?</div><h2 id="ls-compare-title">차이는 ‘질문 기능’보다<br>회사에 맞춰 구축하는 범위에 있습니다.</h2>' +
      '  <p class="ls-lead">ChatGPT도 문서 분석과 업무 도구 연결을 제공합니다. 팝콘AI의 업무형은 장비와 설치, 회사 자료와 사용 방법을 함께 상담하는 서비스입니다.</p>' +
      '  <div class="ls-comparison">' +
      '    <div class="ls-compare-head"><h3>ChatGPT 등 직접 이용</h3><p class="ls-small">제공 기능과 회사의 설정을 조합</p></div><div class="ls-compare-head"><h3>팝콘AI 회사 맞춤 구축</h3><p class="ls-small">고객 환경에 맞춰 범위·견적 확정</p></div>' +
      '    <div class="ls-compare-cell"><span class="ls-mobile-label">ChatGPT 등 직접 이용</span><strong>문서 질문·요약·도구 연결</strong><p>이미 제공되는 기능입니다. 회사 자료 연결도 가능합니다.</p></div><div class="ls-compare-cell"><span class="ls-mobile-label">팝콘AI 회사 맞춤 구축</span><strong>우리 회사가 실제로 쓸 업무부터 선정</strong><p>반복 질문, 참고 자료, 결과 양식을 정하고 적용 범위를 상담합니다.</p></div>' +
      '    <div class="ls-compare-cell"><span class="ls-mobile-label">ChatGPT 등 직접 이용</span><strong>이용 서비스의 처리·저장 정책 확인</strong><p>로컬 파일을 읽는 것과 AI 추론까지 내부에서 실행하는 것은 다릅니다.</p></div><div class="ls-compare-cell"><span class="ls-mobile-label">팝콘AI 회사 맞춤 구축</span><strong>사내 장비에서 처리하는 목표 구성</strong><p>외부 전송이 없는 구성이 필요한지 검토하고, 구축 후 실제 경로를 점검합니다.</p></div>' +
      '    <div class="ls-compare-cell"><span class="ls-mobile-label">ChatGPT 등 직접 이용</span><strong>조직에서 도입·운영 방식 결정</strong><p>자료, 사용자, 연결 도구와 업무 적용 방법을 정해야 합니다.</p></div><div class="ls-compare-cell"><span class="ls-mobile-label">팝콘AI 회사 맞춤 구축</span><strong>PC 구성부터 설치·사용 안내까지 상담</strong><p>고객 자료 설정과 추가 지원은 합의한 범위에 맞춰 견적에 명시합니다.</p></div>' +
      '  </div>' +
      '  <p class="ls-caption">ChatGPT Business·Enterprise 등도 업무 데이터를 기본적으로 모델 학습에 사용하지 않습니다. <strong>‘학습에 사용하지 않음’과 ‘외부로 전송하지 않음’은 다른 조건입니다.</strong></p>' +
      '  <p class="ls-caption">비교 근거: <a href="https://learn.chatgpt.com/docs/use-chatgpt" target="_blank" rel="noreferrer">OpenAI 공식 기능 안내</a> · <a href="https://learn.chatgpt.com/docs/enterprise/chatgpt-work-cloud-security" target="_blank" rel="noreferrer">기업용 데이터 보호 안내</a></p>' +
      '</section>' +
      '<div class="ls-divider"></div>' +
      '<section class="ls-section" aria-labelledby="ls-scope-title">' +
      '  <div class="ls-eyebrow">03 · 팝콘AI가 함께하는 일</div><h2 id="ls-scope-title">장비를 고르는 것부터,<br>직원이 사용하는 방법까지.</h2>' +
      '  <p class="ls-lead">기본 상담 범위와 회사마다 달라지는 구축 항목을 나눠, 무엇을 제공받는지 분명하게 안내합니다.</p>' +
      '  <div class="ls-scope"><article><span class="ls-label">현재 안내하는 상담 범위</span><h3>PC 구성 · AI 설치 · 사용 안내</h3><ul><li>업무와 사용 인원에 맞는 장비 구성 상담</li><li>AI 설치 방식과 실행 환경 상담</li><li>업무에 맞는 사용 방법 안내 범위 협의</li><li>구성과 지원 범위를 정한 뒤 견적 안내</li></ul></article><article><span class="ls-label">회사별 제공 가능 여부·범위 확정</span><h3>자료 연결 · 권한 · 운영 지원</h3><ul><li>문서 형식·자료량·보관 위치와 연결 방법</li><li>부서별 열람 권한과 자료 갱신 방식</li><li>회사 양식과 기존 업무 도구 연동</li><li>교육·초기 지원·유지보수 범위와 비용</li></ul></article></div>' +
      '  <p class="ls-caption">모든 파일 지원, 자동 권한 연동, 무제한 지원이 기본 포함된다는 뜻은 아닙니다. 내부 전용 구축 가능 여부도 실제 환경을 확인한 뒤 확정합니다.</p>' +
      '  <ol class="ls-service-flow" aria-label="회사 맞춤 구축의 5단계 제안 흐름">' +
      '    <li><button type="button" data-stage="0" aria-pressed="true"><span>01</span><strong>업무 진단</strong></button></li>' +
      '    <li><button type="button" data-stage="1" aria-pressed="false"><span>02</span><strong>설계·견적</strong></button></li>' +
      '    <li><button type="button" data-stage="2" aria-pressed="false"><span>03</span><strong>설치·구성</strong></button></li>' +
      '    <li><button type="button" data-stage="3" aria-pressed="false"><span>04</span><strong>실무 검수</strong></button></li>' +
      '    <li><button type="button" data-stage="4" aria-pressed="false"><span>05</span><strong>안내·인계</strong></button></li>' +
      '  </ol>' +
      '  <div class="ls-stage-detail" aria-live="polite"><span class="ls-label">합의할 제공 과정 · 단계별 예시</span><h3 id="ls-stage-title"></h3><div class="ls-stage-grid"><div><strong>팝콘AI가 할 일</strong><p id="ls-stage-provider"></p></div><div><strong>고객과 확인할 일</strong><p id="ls-stage-customer"></p></div></div><div class="ls-output" id="ls-stage-output"></div></div>' +
      '</section>' +
      '<div class="ls-divider"></div>' +
      '<section class="ls-section" aria-labelledby="ls-work-title">' +
      '  <div class="ls-eyebrow">04 · 구축한 뒤의 실무 모습</div><h2 id="ls-work-title">우리 회사 자료로,<br>우리 직원의 질문에 답하는 과정.</h2>' +
      '  <p class="ls-small">아래 문서·질문·답변은 모두 가상 예시입니다. 실제 고객 자료나 현재 서비스의 실행 결과가 아닙니다.</p>' +
      '  <div class="ls-toggle" role="group" aria-label="업무 활용 시나리오"><button type="button" data-case="policy" aria-pressed="true">사내 규정 확인</button><button type="button" data-case="sales" aria-pressed="false">영업 제안 준비</button><button type="button" data-case="support" aria-pressed="false">고객 안내 작성</button></div>' +
      '  <div class="ls-example" aria-live="polite"><h3 id="ls-case-title"></h3><div class="ls-setup-box"><div class="ls-eyebrow">이 업무를 위해 먼저 구성할 것</div><p id="ls-case-setup"></p></div>' +
      '    <div class="ls-mini-flow" aria-label="실무 처리 흐름"><span>지정한 내부 자료</span> → <span>직원 질문</span> → <span>사내 AI 처리</span> → <span>근거 확인</span> → <span>담당자 활용</span></div>' +
      '    <div class="ls-chat-caption">직원의 질문 · 내부 전용 구성 예시</div><div class="ls-question" id="ls-question"></div>' +
      '    <div class="ls-chat-caption">가상 자료에서 찾은 답변 예시</div><div class="ls-answer"><div id="ls-answer"></div><button type="button" class="ls-source" id="ls-source-button" aria-expanded="false" aria-controls="ls-source-content"></button></div>' +
      '    <div class="ls-source-content" id="ls-source-content" hidden></div>' +
      '    <div class="ls-outcome"><strong id="ls-outcome-title"></strong><p id="ls-outcome-text"></p></div>' +
      '  </div>' +
      '  <details class="ls-gap"><summary>자료에 없거나 서로 다른 답이 나오면?</summary><p>근거가 없으면 ‘현재 자료에서 확인하지 못했습니다’라고 표시하도록 설계하고, 실제 질문으로 동작을 검수합니다. 규정이 서로 다르면 두 근거와 적용 조건을 보여주고 담당자의 확인으로 이어지도록 설계합니다. ‘사내 AI’라는 이유로 답변이 항상 정확하다고 보장하지 않습니다.</p></details>' +
      '</section>' +
      '<section class="ls-cta"><div class="ls-eyebrow">우리 회사 환경으로 시작하기</div><h2>외부 전송이 어려운 자료가 있나요?</h2><p class="ls-lead">어떤 업무를 내부에서 처리해야 하는지부터 살펴봅니다.<br>자료 원본을 보내기 전에, 자료의 종류와 사용 환경부터 상담하세요.</p><a class="ls-primary" id="ls-consult-link" href="ai-consult.html?package=business&amp;use=documents&amp;intent=adoption">우리 회사 내부 AI 구축 상담하기 ' + i('arrow-right') + '</a><p class="ls-small">상담 후 적용 가능 범위 · 구성 · 비용 안내</p><a class="ls-back text-link" href="ai-detail.html?package=business">업무형 패키지로 돌아가기</a><div class="ls-consult-note"><span class="ls-label">상담 화면에 이어지는 선택</span><h3>업무형 · 사내 문서 검색 · 도입 상담</h3><p>상담에서 함께 확인할 내용</p><ul><li>외부 접근 제한과 업무 데이터 외부 전송 제한 요구</li><li>반복되는 업무와 사용 인원</li><li>자료의 종류·분량·현재 보관 위치</li><li>인터넷 차단 필요 여부와 기존 장비 환경</li></ul><p class="ls-small">이 화면을 본 것만으로 상담이 접수되거나 연락 동의가 되지 않습니다. 연락처 입력과 신청은 상담 화면에서 직접 하실 때만 진행됩니다.</p></div></section>' +
      '<div class="ls-footer">내부 전용은 구축·통신 검증 후 확정하는 목표 구성입니다.<br>운영 사이트의 보안 검증 완료나 고객 설치 완료를 뜻하지 않습니다.</div>' +
      '</div>';
  }
  function unknown() {
    return '<div class="ls-page"><section class="ls-unknown"><div class="ls-eyebrow">AI 패키지</div><h1>이 업무의 설명 화면은 준비 중입니다.</h1><p class="ls-lead">업무형 패키지의 사내 문서 검색·회의록 정리·고객 답변 초안 설명만 이 화면에서 볼 수 있습니다.</p><p style="margin-top:18px"><a class="text-link" href="ai-detail.html?package=business">업무형 패키지 보기 ' + i('arrow-right') + '</a></p></section></div>';
  }
  // 업무별 설명은 P.serviceGuides 에 모인다(회의록 정리 = ai-meeting-guide.js, 고객 답변 초안 = ai-reply-guide.js).
  // 화면은 주소의 use 만 보고 고른다 -- 새로고침·뒤로·앞으로·직접 주소가 모두 같은 업무를 연다.
  P.serviceGuides = P.serviceGuides || {};
  P.serviceGuides.documents = {label: '사내 문서 검색', body: body, mount: mount};
  // 2026-10-21 승인(30인 이하 기업 컨설팅) -- 세 업무 설명 하단에 기업 컨설팅 설명으로 가는 보조 링크만 둔다. 위의 개인 상담 버튼은 그대로다.
  var COMPANY_FROM = {documents: 'D', meetings: 'M', replies: 'R'};
  function companyLink(use) {
    return '<aside class="svc-company" id="company-link" aria-labelledby="svc-company-title"><div><span class="svc-company-tag">30인 이하 기업 대상 · 별도 컨설팅</span><h2 id="svc-company-title">여러 담당자가 함께하는 회사 업무라면</h2><p>이 화면의 회사 맞춤은 담당자 한 사람이 맡은 업무의 자료·양식·규칙에 맞추는 범위입니다. 여러 담당자·부서에 걸친 업무 흐름은 기업 AI 업무개선 컨설팅에서 따로 살펴봅니다.</p></div><a class="text-link" id="svc-company-link" href="ai-company.html?from=' + COMPANY_FROM[use] + '">30인 이하 기업 컨설팅 ' + i('arrow-right') + '</a></aside>';
  }
  P.pages['ai-service'] = function () {
    var use = P.qs.get('use'), g = P.qs.get('package') === 'business' && Object.prototype.hasOwnProperty.call(P.serviceGuides, use) ? P.serviceGuides[use] : null;
    if (g && g.label) document.title = '회사 맞춤 내부 AI 구축 · ' + g.label + ' | 팝콘AI';
    return {html: '<div class="container">' + crumb(g ? g.label : '업무 설명') + (g ? g.body() + companyLink(use) : unknown()) + '</div>', mount: g ? g.mount : null};
  };
  function mount() {
    var root = document.getElementById('pop-local-service');
    var q = function (sel) { return root.querySelector(sel); };
    var mode = 'internal', stage = 0, scenario = 'policy', sourceOpen = false;
    function each(sel, fn) { Array.prototype.forEach.call(root.querySelectorAll(sel), fn); }
    function renderMode() {
      var internal = mode === 'internal';
      each('[data-mode]', function (b) { b.setAttribute('aria-pressed', String(b.dataset.mode === mode)); });
      q('#ls-network-title').innerHTML = internal ? '문서도, 질문도, AI 처리도<br>회사 내부에서 끝나는 구성.' : '외부 AI 서비스와 연결되는<br>비교 구성입니다.';
      q('#ls-network-flow').setAttribute('aria-label', internal ? '사내 문서와 질문을 내부 AI 장비에서 처리하고 직원에게 답변하는 목표 구조' : '사내 연결 프로그램에서 질문과 필요한 문서 내용을 외부 AI API로 보내는 비교 구조');
      q('#ls-mode-caption').textContent = internal ? '제안 구성 · 구축 후 검증' : '비교용 예시 · 내부 전용 아님';
      q('#ls-engine-title').textContent = internal ? '사내 AI 장비' : '사내 연결 프로그램';
      q('#ls-engine-text').innerHTML = internal ? '문서 검색 + AI 모델 실행<br>질문·답변·기록 내부 처리' : '질문·필요 문서 내용을<br>외부 AI API로 전송';
      q('#ls-data-tags').innerHTML = (internal ? ['문서', '검색용 색인', '질문·답변', '처리 기록', '모델 실행'] : ['내부 자료', '연결 설정', '외부 전송 데이터 별도 확인']).map(function (x) { return '<span>' + x + '</span>'; }).join('');
      q('#ls-outside').dataset.connected = String(!internal);
      q('#ls-outside-title').textContent = internal ? '외부 AI 서비스로 보내는 경로를 두지 않는 설계' : '사내 프로그램 → 외부 AI API → 답변 반환';
      q('#ls-outside-text').textContent = internal ? '인터넷 검색·외부 AI API·클라우드 저장을 사용하는 구성에는 이 설명을 적용하지 않습니다.' : '이 구성에는 ‘업무 데이터 외부 전송 없음’을 적용할 수 없습니다. 어떤 정보가 어디로 전송·저장되는지 별도로 확인해야 합니다.';
    }
    function renderStage() {
      var s = stages[stage];
      each('[data-stage]', function (b) { b.setAttribute('aria-pressed', String(Number(b.dataset.stage) === stage)); });
      q('#ls-stage-title').textContent = s.title; q('#ls-stage-provider').textContent = s.provider;
      q('#ls-stage-customer').textContent = s.customer; q('#ls-stage-output').textContent = s.output;
    }
    function renderCase() {
      var e = examples[scenario];
      each('[data-case]', function (b) { b.setAttribute('aria-pressed', String(b.dataset.case === scenario)); });
      q('#ls-case-title').textContent = e.title; q('#ls-case-setup').textContent = e.setup; q('#ls-question').textContent = e.question;
      q('#ls-answer').innerHTML = e.answer; q('#ls-source-button').textContent = e.sourceLabel;
      q('#ls-source-button').setAttribute('aria-expanded', String(sourceOpen));
      q('#ls-source-content').innerHTML = e.source; q('#ls-source-content').hidden = !sourceOpen;
      q('#ls-outcome-title').textContent = e.outcome; q('#ls-outcome-text').textContent = e.detail;
    }
    // 비교 탭은 설명용이다 -- 상담 링크(내부 전용 요구)와 아무 상태도 주고받지 않는다.
    root.addEventListener('click', function (event) {
      var b = event.target.closest('button');
      if (!b || !root.contains(b)) return;
      if (b.dataset.mode) { mode = b.dataset.mode; renderMode(); }
      else if (b.dataset.stage !== undefined) { stage = Number(b.dataset.stage); renderStage(); }
      else if (b.dataset.case) { scenario = b.dataset.case; sourceOpen = false; renderCase(); }
      else if (b.id === 'ls-source-button') { sourceOpen = !sourceOpen; renderCase(); }
    });
    renderMode(); renderStage(); renderCase();
  }
}());
