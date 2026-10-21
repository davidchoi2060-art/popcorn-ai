/* 업무형 「고객 답변 초안」 설명 화면 (/mvp4/ai-service.html?package=business&use=replies).
   2026-10-21 대표 승인(회의록 정리와 같은 승인) 정본 business-reply-guide.html(SHA256 052fc4cc…9a9878)의 본문만 옮겼다.
   - 사이트 공통 셸은 boot.js 가 그대로 그린다. 승인 원본의 위젯 호스트 상태 연동은 옮기지 않는다.
   - 원본의 상담 연결 표시는 실제 연결(ai-consult.html?package=business&use=replies&intent=adoption)로 바꿨다.
   - 복사는 지금 보이는 사례·말투의 초안만, 클립보드가 성공을 돌려준 뒤에만 완료로 표시한다. 안 되면 선택해 직접 복사하게 한다.
   - 검토 체크는 체험용이다. 네 개를 모두 골라도 승인·발송·저장되지 않는다. 사례·말투를 바꾸면 처음으로 돌아간다. */
(function () {
  'use strict';
  var P = window.PAI, h = P.h;
  var cases={
  setup:{title:'기존 PC로 다음 주 금요일에 설치할 수 있나요?',question:'우리 회사 12명이 문서 검색을 쓰려고 합니다. 기존 PC로 다음 주 금요일에 설치할 수 있나요? 계약서 자료는 외부로 나가면 안 됩니다.',facts:['사용 인원·자료·장비를 확인한 뒤 구성 제안','설치 일정은 담당자의 가능 일정 확인 후 안내','첫 상담에서는 문서 원본을 받지 않음'],unknown:['기존 PC에서 설치 가능한지','금요일 설치 가능 여부와 비용','내부 전용으로 구성·검증할 범위'],sources:[['도입 안내 §2','도입 안내 v2 · 2026-10-01 · §2','사용 인원, 자료 형식·분량, 현재 PC 사양과 접속 환경을 확인한 뒤 적용 가능한 구성과 설치 방식을 제안한다.'],['설치 일정 §3','설치 일정 안내 v1 · 2026-10-02 · §3','설치 요구사항과 담당자의 가능 일정을 확인한 뒤 설치 예정일을 안내한다. 확인 전 특정 날짜와 비용을 확정하지 않는다.'],['자료 취급 §1','자료 취급 안내 v2 · 2026-10-04 · §1','초기 상담에서는 자료 종류와 대략적인 분량만 확인하고 문서 원본·계정 비밀번호는 받지 않는다. 내부 전용 구성은 모델·검색 색인·기록 등 처리 경로와 외부 연결 제한을 점검한 뒤 확정한다.']],drafts:{detail:['안녕하세요. 12명이 사용할 문서 검색 환경과 <mark>계약서 자료의 외부 전송 제한</mark>을 함께 검토하고 계시군요.','기존 PC 활용 가능 여부는 장비 사양과 자료 형식·분량을 확인한 뒤 안내드리겠습니다. <mark>다음 주 금요일 설치는 아직 확정되지 않았으며</mark>, 담당자의 가능 일정을 확인해야 합니다.','현재 PC의 사양과 운영체제, 자료의 종류·대략적인 분량, 사용 환경을 알려주시겠어요? 문서 원본이나 비밀번호는 보내지 않으셔도 됩니다. 말씀하신 외부 전송 제한 요구를 기준으로 구성과 검증 범위를 함께 확인하겠습니다.'],brief:['안녕하세요. 12명 사용과 외부 전송 제한 요구를 확인했습니다.','<mark>기존 PC 활용과 금요일 설치는 확인 후 안내</mark>가 필요합니다. PC 사양·운영체제, 자료 종류·분량과 사용 환경을 알려주세요.','문서 원본이나 비밀번호는 보내지 않으셔도 됩니다. 요청하신 내부 처리 범위를 함께 확인하겠습니다.']}},
  trouble:{title:'새 매뉴얼이 검색되지 않아요. 오늘 고칠 수 있나요?',question:'어제 추가한 운영 매뉴얼이 검색되지 않습니다. 직원들은 예전 문서를 보고 답을 받고 있어요. 오늘 오전까지 고칠 수 있나요? 매뉴얼을 보내드릴까요?',facts:['파일 형식·추가 시각·마지막 처리 상태를 확인','자료가 검색에 반영되려면 처리 완료 여부 확인 필요','문서 원본·계정 정보 없이 초기 증상 확인'],unknown:['오류의 원인과 현재 자료 처리 상태','오늘 오전 복구 가능 여부','적용 중인 갱신 방식과 계약상 지원 범위'],sources:[['지원 접수 §1','지원 접수 안내 v3 · 2026-10-02 · §1','새 자료가 검색되지 않으면 파일 형식, 추가한 시각, 마지막 자료 처리 상태와 사용 환경을 확인한다. 초기 문의에서 문서 원본이나 계정 정보는 요구하지 않는다.'],['자료 갱신 §2','자료 갱신 안내 v2 · 2026-10-03 · §2','새 자료의 검색 반영은 합의된 갱신 방식과 자료 처리의 완료 여부에 따라 달라진다. 연결된 자료 위치와 적용 버전을 확인한다.'],['처리 일정 §4','지원 처리 안내 v1 · 2026-10-05 · §4','원인, 영향 범위와 계약상 지원 범위를 확인한 뒤 처리 방법과 일정을 안내한다. 확인 전 복구 시간과 완료 여부를 약속하지 않는다.']],drafts:{detail:['안녕하세요. 새로 추가한 매뉴얼이 검색되지 않아 이전 자료를 기준으로 확인하고 계신 상황이군요.','먼저 <mark>파일 형식, 추가한 시각과 마지막 자료 처리 상태</mark>, 현재 사용 환경을 알려주시겠어요? 새 자료가 어느 위치에 연결됐고 처리가 완료됐는지 확인이 필요합니다.','<mark>오늘 오전까지 복구 가능한지는 아직 확정할 수 없습니다.</mark> 원인과 지원 범위를 확인한 뒤 처리 방법과 일정을 안내드리겠습니다. 매뉴얼 원문이나 계정 정보는 보내지 않으셔도 됩니다.'],brief:['안녕하세요. 새 매뉴얼이 검색되지 않는다는 문의를 확인했습니다.','파일 형식·추가 시각·마지막 자료 처리 상태·사용 환경을 알려주세요. <mark>복구 일정은 원인과 지원 범위 확인 후 안내</mark>드리겠습니다.','매뉴얼 원문이나 계정 정보는 보내지 않으셔도 됩니다.']}}
 };
 var steps=['직원이 선택한 문의 중 업무에 필요한 내용만 사용합니다. 고객이 말한 증상·희망 일정은 내부에서 확인한 사실과 구분합니다.','회사에서 사용을 승인한 안내문과 최신 버전을 연결합니다. 문서가 없거나 서로 다르면 직원이 확인할 항목으로 남기도록 구성합니다.','확인된 사실과 아직 모르는 정보를 구분해 회사 말투로 정리합니다. 없는 가격·일정·지원 약속을 채워 넣지 않는지 검수합니다.','담당자가 원문·규정·표현·수신자를 확인하고 수정합니다. 초안 작성과 실제 발송은 분리하며, 체크 항목 선택만으로 고객에게 보내지 않습니다.'];
  var MARKUP =
    '<div class="rp-page" id="pop-reply-guide" lang="ko" data-use="replies">' +
    '<section class="rp-hero">' +
    ' <div class="rp-eyebrow">POPCORN AI · 업무 도입 패키지</div>' +
    ' <h1>우리 회사 기준으로 쓰고,<br>담당자가 확인해서 보냅니다.</h1>' +
    ' <p class="rp-lead">고객의 질문과 사내 안내 자료를 함께 살펴<br>답할 수 있는 내용과 확인이 필요한 내용을 나눕니다.<br>회사 말투와 응대 절차에 맞는 답변 초안을 구축합니다.</p>' +
    ' <div class="rp-tags"><span>사내 자료를 근거로</span><span>확인 전 약속은 보류</span><span>고객 발송은 직원이</span></div>' +
    '</section>' +
    '<section class="rp-section">' +
    ' <span class="rp-eyebrow">01 · 실제 업무는 이렇게 흐릅니다</span>' +
    ' <h2>초안 작성과 고객 발송은<br>분명하게 나눕니다.</h2>' +
    ' <div class="rp-boundary">' +
    '  <div class="rp-boundary-label"><img class="icon rp-icon" src="assets/icons/shield.svg" alt="" aria-hidden="true" width="24" height="24"> 회사 내부에서 처리하도록 구축하는 범위</div>' +
    '  <ol class="rp-flow" aria-label="고객 답변 초안 내부 처리 흐름">' +
    '   <li><button type="button" data-step="0" aria-pressed="false"><small>01</small><strong>문의 선택</strong><span>필요한 내용만</span></button></li>' +
    '   <li><button type="button" data-step="1" aria-pressed="true"><small>02</small><strong>기준 확인</strong><span>사내 자료·버전</span></button></li>' +
    '   <li><button type="button" data-step="2" aria-pressed="false"><small>03</small><strong>초안 작성</strong><span>사실·미확인 구분</span></button></li>' +
    '   <li><button type="button" data-step="3" aria-pressed="false"><small>04</small><strong>직원 검토</strong><span>근거·표현·수신자</span></button></li>' +
    '  </ol>' +
    '  <p class="rp-flow-detail" id="rp-step-detail" aria-live="polite">회사에서 사용을 승인한 안내문과 최신 버전을 연결합니다. 문서가 없거나 서로 다르면 직원이 확인할 항목으로 남기도록 구성합니다.</p>' +
    ' </div>' +
    ' <div class="rp-send-boundary"><img class="icon rp-icon" src="assets/icons/paper-plane-tilt.svg" alt="" aria-hidden="true" width="24" height="24"><div><strong>검토 후, 직원이 고객에게 발송</strong><br><span class="rp-small">메일·메신저 발송은 별도 행동입니다. 내부 AI가 자동으로 고객에게 보내는 구조가 아닙니다.</span></div></div>' +
    ' <p class="rp-note">내부 전용은 고객 환경의 모델 실행·자료·질문·답변·기록 경로를 구성하고 통신을 검증한 뒤 확정합니다. 외부 AI API형에는 ‘업무 데이터 외부 전송 없음’을 적용하지 않습니다.</p>' +
    '</section>' +
    '<section class="rp-section">' +
    ' <span class="rp-eyebrow">02 · 같은 문의도, 근거를 보고 답합니다</span>' +
    ' <h2>확인된 내용은 안내하고,<br>모르는 내용은 먼저 확인합니다.</h2>' +
    ' <p class="rp-small">아래 문의·사내 문서·날짜·답변은 모두 가상 예시입니다. 실제 고객 정보나 실시간 AI 응답을 사용하지 않았습니다.</p>' +
    ' <div class="rp-choice" aria-label="고객 문의 예시 선택">' +
    '  <button type="button" data-case="setup" aria-pressed="true">설치 일정 문의</button>' +
    '  <button type="button" data-case="trouble" aria-pressed="false">검색 오류 문의</button>' +
    ' </div>' +
    ' <article class="rp-example">' +
    '  <div class="rp-example-head"><span class="rp-caption">고객 문의 → 근거 대조 → 답변 초안</span><h3 id="rp-case-title">기존 PC로 다음 주 금요일에 설치할 수 있나요?</h3></div>' +
    '  <div class="rp-example-body">' +
    '   <div class="rp-customer"><div class="rp-caption">들어온 문의 · 고객이 말한 내용</div><p id="rp-question">우리 회사 12명이 문서 검색을 쓰려고 합니다. 기존 PC로 다음 주 금요일에 설치할 수 있나요? 계약서 자료는 외부로 나가면 안 됩니다.</p></div>' +
    '   <div class="rp-grid">' +
    '    <section class="rp-facts"><h3>사내 자료에서 확인</h3><ul id="rp-facts"><li>사용 인원·자료·장비를 확인한 뒤 구성 제안</li><li>설치 일정은 담당자의 가능 일정 확인 후 안내</li><li>첫 상담에서는 문서 원본을 받지 않음</li></ul></section>' +
    '    <section class="rp-unknown"><h3>아직 확인이 필요한 것</h3><ul id="rp-unknown"><li>기존 PC에서 설치 가능한지</li><li>금요일 설치 가능 여부와 비용</li><li>내부 전용으로 구성·검증할 범위</li></ul></section>' +
    '   </div>' +
    '   <div class="rp-evidence-buttons" aria-label="초안에 사용한 가상 사내 근거">' +
    '    <button type="button" data-source="0" aria-pressed="true">도입 안내 §2</button>' +
    '    <button type="button" data-source="1" aria-pressed="false">설치 일정 §3</button>' +
    '    <button type="button" data-source="2" aria-pressed="false">자료 취급 §1</button>' +
    '   </div>' +
    '   <div class="rp-source" aria-live="polite"><span class="rp-caption">선택한 근거 원문 · 가상 문서</span><strong id="rp-source-title">도입 안내 v2 · 2026-10-01 · §2</strong><p id="rp-source-body">사용 인원, 자료 형식·분량, 현재 PC 사양과 접속 환경을 확인한 뒤 적용 가능한 구성과 설치 방식을 제안한다.</p></div>' +
    '   <section class="rp-draft">' +
    '    <div class="rp-draft-head"><strong>담당자가 검토할 답변 초안</strong><div class="rp-tone" aria-label="가상 회사 말투 예시"><button type="button" data-tone="detail" aria-pressed="true">차분하고 상세하게</button><button type="button" data-tone="brief" aria-pressed="false">짧고 명확하게</button></div></div>' +
    '    <div class="rp-draft-body" id="rp-draft" aria-live="polite">' +
    '     <p>안녕하세요. 12명이 사용할 문서 검색 환경과 <mark>계약서 자료의 외부 전송 제한</mark>을 함께 검토하고 계시군요.</p>' +
    '     <p>기존 PC 활용 가능 여부는 장비 사양과 자료 형식·분량을 확인한 뒤 안내드리겠습니다. <mark>다음 주 금요일 설치는 아직 확정되지 않았으며</mark>, 담당자의 가능 일정을 확인해야 합니다.</p>' +
    '     <p>현재 PC의 사양과 운영체제, 자료의 종류·대략적인 분량, 사용 환경을 알려주시겠어요? 문서 원본이나 비밀번호는 보내지 않으셔도 됩니다. 말씀하신 외부 전송 제한 요구를 기준으로 구성과 검증 범위를 함께 확인하겠습니다.</p>' +
    '    </div>' +
    '    <div class="rp-draft-bottom"><span class="rp-small">확인되지 않은 가격·납기·성능은 약속하지 않습니다.</span><button type="button" id="rp-copy"><img class="icon rp-icon" src="assets/icons/clipboard-text.svg" alt="" aria-hidden="true" width="24" height="24"> 예시 초안 복사</button></div>' +
    '   </section>' +
    '   <p class="rp-small" id="rp-copy-status" role="status"></p><textarea id="rp-copy-fallback" class="rp-fallback" aria-label="직접 복사할 가상 답변 초안" readonly hidden></textarea>' +
    '   <h3 style="margin-top:24px">보내기 전, 직원이 확인할 내용</h3>' +
    '   <div class="rp-checks" id="rp-checks">' +
    '    <label><input type="checkbox" value="0"><span>현재 문서·업무 기준과 맞는가?</span></label>' +
    '    <label><input type="checkbox" value="1"><span>미확인 일정·비용을 약속하지 않았는가?</span></label>' +
    '    <label><input type="checkbox" value="2"><span>회사 자료·개인정보가 불필요하게 담기지 않았는가?</span></label>' +
    '    <label><input type="checkbox" value="3"><span>문의한 고객과 받는 사람이 일치하는가?</span></label>' +
    '   </div>' +
    '   <p class="rp-review-status" id="rp-review-status" aria-live="polite">검토 항목 0/4 선택 · 화면 체험용이며 승인·발송되지 않습니다.</p>' +
    '  </div>' +
    ' </article>' +
    '</section>' +
    '<section class="rp-section">' +
    ' <span class="rp-eyebrow">03 · 팝콘AI가 회사에 맞게 구성할 것</span>' +
    ' <h2>질문을 잘하는 법보다,<br>회사에서 답하는 기준을 만듭니다.</h2>' +
    ' <p class="rp-lead">일반 대화 도구에서도 초안을 쓸 수 있습니다. 구축 상담에서는 우리 자료와 말투, 확인 담당자, 내부 처리 환경을 함께 맞춥니다.</p>' +
    ' <div class="rp-custom">' +
    '  <article><span class="rp-number">01 · 무엇을 근거로 쓸지</span><h3>자료와 적용 버전</h3><p>자주 쓰는 안내문·제품 자료·업무 규정 중 사용할 문서를 정합니다. 서로 다른 안내나 오래된 자료의 처리 기준도 정합니다.</p><div class="rp-deliverable">합의할 결과물 · 기준 문서 목록 / 갱신 담당</div></article>' +
    '  <article><span class="rp-number">02 · 어떻게 말할지</span><h3>회사 말투와 답변 양식</h3><p>인사말, 필요한 질문, 답변 길이, 확인 전 약속하면 안 되는 표현을 정합니다. 직원이 쓰는 양식으로 맞춥니다.</p><div class="rp-deliverable">합의할 결과물 · 문의 유형별 초안 / 표현 기준</div></article>' +
    '  <article><span class="rp-number">03 · 어디까지 답할지</span><h3>답변 범위와 확인 담당</h3><p>가격·일정·지원 가능 여부처럼 별도 확인이 필요한 항목을 구분합니다. 자료가 없는 질문은 담당자가 확인하도록 구성합니다.</p><div class="rp-deliverable">합의할 결과물 · 확인 항목 / 담당 부서 기준</div></article>' +
    '  <article><span class="rp-number">04 · 누가 보고 보낼지</span><h3>접근·보관·발송 절차</h3><p>원문의 열람 범위와 저장 위치·기간을 정합니다. 고객 회신은 직원 검토 후 별도로 진행하고, 메일 연동은 포함 여부를 협의합니다.</p><div class="rp-deliverable">합의할 결과물 · 권한·보관 기준 / 검토 절차</div></article>' +
    ' </div>' +
    ' <details><summary>설치 후에는 이런 문의로 함께 검수합니다</summary><ul><li><strong>문서에 없는 납기:</strong> 날짜를 확약하지 않고 확인 질문을 남기는가?</li><li><strong>두 문서의 기준 충돌:</strong> 한쪽을 임의로 확정하지 않고 확인이 필요한 차이를 보여주는가?</li><li><strong>자료에 없는 문의:</strong> 근거를 만들어내지 않고 담당자 확인으로 이어지는가?</li><li><strong>민감한 정보가 있는 문의:</strong> 정한 처리 범위·열람 권한·외부 전송 제한을 지키는가?</li></ul><p>이 항목들은 구축 시 확인할 수용 기준입니다. 현재 사이트에서 해당 동작의 검증이 완료됐다는 뜻은 아닙니다.</p></details>' +
    '</section>' +
    '<section class="rp-section">' +
    ' <span class="rp-eyebrow">04 · 우리 회사용으로 도입하는 과정</span>' +
    ' <h2>대표 문의부터 골라,<br>실무에서 쓸 수 있는지 확인합니다.</h2>' +
    ' <ol class="rp-steps">' +
    '  <li><span>01</span><strong>업무 확인</strong><p>자주 오는 문의 유형, 처리 부서, 현재 불편을 정리합니다.</p></li>' +
    '  <li><span>02</span><strong>구성·범위 합의</strong><p>장비·내부 처리 방식·자료 연결·지원 범위와 비용을 확인합니다.</p></li>' +
    '  <li><span>03</span><strong>회사 기준 적용</strong><p>합의한 문서·답변 양식·말투·검토 절차로 환경을 구성합니다.</p></li>' +
    '  <li><span>04</span><strong>예외까지 검수</strong><p>모르는 질문·충돌 문서·민감정보·통신 경로를 실제 조건으로 확인합니다.</p></li>' +
    '  <li><span>05</span><strong>사용 안내·인계</strong><p>문서 갱신 방법과 직원 검토 방법, 합의한 지원 절차를 안내합니다.</p></li>' +
    ' </ol>' +
    ' <p class="rp-small">PC 구성·AI 설치·사용 안내를 상담합니다. 자동 메일 수집·CRM 연동·자동 발송·유지보수는 기본 포함으로 약속하지 않으며, 필요한 항목과 제공 가능 범위를 따로 확인합니다.</p>' +
    '</section>' +
    '<section class="rp-cta">' +
    ' <span class="rp-eyebrow">우리 회사의 응대 기준부터</span>' +
    ' <h2>반복되는 고객 문의,<br>어디까지 도와주면 좋을까요?</h2>' +
    ' <p class="rp-small">문의를 받는 부서와 자주 묻는 유형부터 알려주세요.<br>고객 원문이나 연락처를 먼저 보낼 필요는 없습니다.</p>' +
    ' <a class="rp-primary" id="rp-consult-link" href="ai-consult.html?package=business&amp;use=replies&amp;intent=adoption">우리 회사 고객 응대 방식으로 상담하기 <img class="icon rp-icon" src="assets/icons/arrow-right.svg" alt="" aria-hidden="true" width="24" height="24"></a>' +
    ' <a class="rp-back text-link" href="ai-detail.html?package=business">업무형 패키지로 돌아가기</a>' +
    ' <div class="rp-consult"><span class="rp-caption">상담 화면에 이어지는 선택</span><h3>업무형 · 고객 답변 초안 · 도입 상담</h3><p>원하는 업무: 사내 기준을 활용한 초안 작성과 직원 검토</p><ul><li>자주 오는 문의와 답변 담당 부서</li><li>사용할 안내 자료와 회사 답변 양식</li><li>내부 처리 요구, 자료 보관·접근 범위</li></ul><p class="rp-small rp-no-submit">이 화면을 본 것만으로 상담이 접수되거나 연락 동의가 되지 않습니다. 연락처 입력과 신청은 상담 화면에서 직접 하실 때만 진행됩니다.</p></div>' +
    '</section>' +
    '<p class="rp-foot">가상 업무 체험 · 실제 설치·보안 검증 또는 고객 회신 완료가 아닙니다.</p>' +
    '</div>';
  function body() { return MARKUP; }
  function mount() {
    var root = document.getElementById('pop-reply-guide');
    if (!root) return;
    var q = function (sel) { return root.querySelector(sel); };
    function each(sel, fn) { Array.prototype.forEach.call(root.querySelectorAll(sel), fn); }
    var selected = 'setup', tone = 'detail', source = 0, step = 1, checked = [];
    var KEY = 'pai-guide-replies';
    // 기업 컨설팅 설명에서 「돌아가기」나 브라우저 뒤로로 돌아왔을 때만 보던 사례·말투·근거·단계 을 되살린다(이 탭의 sessionStorage, 업무별 칸).
    function returning() { try { var nav = performance.getEntriesByType('navigation')[0]; return (nav && nav.type === 'back_forward') || location.hash === '#company-link'; } catch (e) { return false; } }
    function remember() { try { sessionStorage.setItem(KEY, JSON.stringify({selected: selected, tone: tone, source: source, step: step})); } catch (e) { /* 저장 못 해도 화면은 그대로 쓴다 */ } }
    function recall() { try { return returning() ? JSON.parse(sessionStorage.getItem(KEY) || 'null') : null; } catch (e) { return null; } }
    var saved = recall();   // 검토 체크는 되살리지 않는다 -- 체험용 표시라 돌아오면 처음부터
    if (saved && cases[saved.selected]) {
      selected = saved.selected;
      if (saved.tone === 'brief' || saved.tone === 'detail') tone = saved.tone;
      if (saved.source >= 0 && saved.source < 3) source = saved.source;
      if (saved.step >= 0 && saved.step < 4) step = saved.step;
    }
    function renderSource() {
      var c = cases[selected], s = c.sources[source];
      each('[data-source]', function (b) { b.textContent = c.sources[Number(b.dataset.source)][0]; b.setAttribute('aria-pressed', String(Number(b.dataset.source) === source)); });
      q('#rp-source-title').textContent = s[1]; q('#rp-source-body').textContent = s[2];
    }
    function renderDraft() {
      each('[data-tone]', function (b) { b.setAttribute('aria-pressed', String(b.dataset.tone === tone)); });
      q('#rp-draft').innerHTML = cases[selected].drafts[tone].map(function (x) { return '<p>' + x + '</p>'; }).join('');
    }
    function renderReview() {
      each('#rp-checks input', function (x) { x.checked = checked.indexOf(Number(x.value)) >= 0; });
      q('#rp-review-status').textContent = '검토 항목 ' + checked.length + '/4 선택 · ' + (checked.length === 4 ? '모두 선택해도 실제 승인·발송되지는 않습니다.' : '화면 체험용이며 승인·발송되지 않습니다.');
    }
    function renderStep() {
      each('[data-step]', function (b) { b.setAttribute('aria-pressed', String(Number(b.dataset.step) === step)); });
      q('#rp-step-detail').textContent = steps[step];
    }
    function renderCase() {
      var c = cases[selected];
      each('[data-case]', function (b) { b.setAttribute('aria-pressed', String(b.dataset.case === selected)); });
      q('#rp-case-title').textContent = c.title; q('#rp-question').textContent = c.question;
      q('#rp-facts').innerHTML = c.facts.map(function (x) { return '<li>' + h(x) + '</li>'; }).join('');
      q('#rp-unknown').innerHTML = c.unknown.map(function (x) { return '<li>' + h(x) + '</li>'; }).join('');
      renderSource(); renderDraft(); renderReview();
    }
    // 사례·말투가 바뀌면 검토 표시와 복사 안내를 처음으로 되돌린다 -- 다른 초안을 검토한 것처럼 남지 않게.
    function resetReview() {
      checked = [];
      q('#rp-copy-status').textContent = '';
      q('#rp-copy-fallback').hidden = true; q('#rp-copy-fallback').value = '';
    }
    function copyDraft() {
      var text = q('#rp-draft').innerText.trim();
      var status = q('#rp-copy-status'), box = q('#rp-copy-fallback');
      function fallback() {
        box.value = text; box.hidden = false; box.focus(); box.select();
        status.textContent = '자동 복사를 사용할 수 없습니다. 선택된 예시 문장을 직접 복사해 주세요.';
      }
      status.textContent = '';
      if (!navigator.clipboard || typeof navigator.clipboard.writeText !== 'function') { fallback(); return; }
      // 클립보드가 성공을 돌려준 뒤에만 완료라고 말한다. 고객에게 보내는 동작은 없다.
      navigator.clipboard.writeText(text).then(function () {
        box.hidden = true;
        status.textContent = '가상 예시 초안을 복사했습니다. 고객에게 발송된 것은 아닙니다.';
      }, fallback);
    }
    root.addEventListener('click', function (e) {
      var b = e.target.closest('button');
      if (!b || !root.contains(b)) return;
      if (b.dataset.case && cases[b.dataset.case]) { selected = b.dataset.case; source = 0; resetReview(); renderCase(); }
      else if (b.dataset.source !== undefined) { source = Number(b.dataset.source); renderSource(); }
      else if (b.dataset.tone) { tone = b.dataset.tone === 'brief' ? 'brief' : 'detail'; resetReview(); renderDraft(); renderReview(); }
      else if (b.dataset.step !== undefined) { step = Number(b.dataset.step); renderStep(); }
      else if (b.id === 'rp-copy') { copyDraft(); }
      remember();
    });
    root.addEventListener('change', function (e) {
      if (!e.target.matches('#rp-checks input')) return;
      checked = Array.prototype.filter.call(root.querySelectorAll('#rp-checks input'), function (x) { return x.checked; }).map(function (x) { return Number(x.value); });
      renderReview();
    });
    renderCase(); renderStep();
  }
  P.serviceGuides = P.serviceGuides || {};
  P.serviceGuides.replies = {label: '고객 답변 초안', title: '고객 답변 초안', body: body, mount: mount};
}());
