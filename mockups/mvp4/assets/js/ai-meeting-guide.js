/* 업무형 「회의록 정리」 설명 화면 (/mvp4/ai-service.html?package=business&use=meetings).
   2026-10-21 대표 승인 「회의록 정리랑 고객답변 초안을 누르면 각각 업무 예시와 우리 회사에 맞게 구축하는 과정을 먼저 보여주고
   상담으로 이어지게 해줘. 기존 헤더랑 메뉴는 그대로 두고.」 정본 business-meeting-guide.html(SHA256 c4441a57…bd821)의 본문만 옮겼다.
   - 사이트 공통 셸(헤더·메뉴·띠메뉴·푸터)은 boot.js 가 그대로 그린다. 승인 원본의 위젯 호스트 상태 연동은 옮기지 않는다.
   - 원본의 상담 연결 표시는 실제 연결(ai-consult.html?package=business&use=meetings&intent=adoption)로 바꿨다.
     이 화면은 아무것도 보내지 않는다(네트워크 요청·저장·동의 없음). 탭·근거·단계·문서 버튼은 화면 표시만 바꾼다.
   - 회의·발언·날짜·결과는 가상 예시다. 「맡을 수 있을 것 같아요」·「수요일이면 좋겠는데」는 미정으로 남긴다. */
(function () {
  'use strict';
  var P = window.PAI, h = P.h;
  var raw={
    u1:{time:'00:18',role:'인사팀장',text:'이번에는 신입사원 입사 전 준비 안내만 개편하겠습니다. 교육 일정은 이번 범위에서 빼죠.'},
    u2:{time:'01:02',role:'인사 담당',text:'준비 서류, 계정 신청, 첫 출근 안내 세 부분으로 나누면 어떨까요?'},
    u3:{time:'01:26',role:'인사팀장',text:'좋습니다. 그 세 부분으로 구성하고 기존 안내문을 기준으로 고칩시다.'},
    u4:{time:'02:10',role:'인사 담당',text:'준비 서류 부분의 초안은 제가 10월 26일까지 작성하겠습니다.'},
    u5:{time:'03:05',role:'IT 담당',text:'계정 신청 절차는 제가 10월 27일 오후 3시까지 확인해서 전달하겠습니다.'},
    u6:{time:'04:20',role:'총무 담당',text:'출근 동선 사진은 제가 맡을 수 있을 것 같아요. 이번 주에 촬영 가능한지부터 알아볼게요.'},
    u7:{time:'05:12',role:'인사 담당',text:'다음 주 수요일에 배포하면 좋겠는데, 팀장님 검토가 그전에 끝날까요?'},
    u8:{time:'05:50',role:'인사팀장',text:'배포일은 검토가 끝나면 정합시다. 검토 완료 전에는 공유하지 말아 주세요.'}
  };
  var groups={
    decisions:[
      {id:'d1',label:'범위 확정',title:'입사 전 준비 안내만 개편',body:'교육 일정은 이번 개편 범위에서 제외합니다.',refs:['u1'],context:'개편 대상과 제외 범위를 명시한 발언을 근거로 정리했습니다.'},
      {id:'d2',label:'구성 확정',title:'준비 서류 · 계정 신청 · 첫 출근 안내',body:'세 부분으로 나누고 기존 안내문을 기준으로 수정합니다.',refs:['u2','u3'],context:'인사 담당의 제안만이 아니라, 그 세 부분을 승인한 다음 발언까지 함께 확인합니다.'},
      {id:'d3',label:'배포 조건',title:'검토 완료 전에는 공유하지 않기',body:'검토 후 배포일을 정합니다. 구체적인 배포일은 아직 확정되지 않았습니다.',refs:['u8'],context:'검토 전 공유 금지는 확인되지만, 실제 배포 날짜는 이 발언에 없습니다.'}
    ],
    tasks:[
      {id:'t1',label:'후속 작업',title:'준비 서류 초안 작성',body:'기존 안내문의 준비 서류 부분을 작성합니다.',owner:'인사 담당',due:'10월 26일까지',refs:['u4'],context:'발언에 담당 역할과 날짜가 명시되어 있습니다. 실제 인사 담당자의 이름은 별도로 확인해야 합니다.'},
      {id:'t2',label:'후속 작업',title:'계정 신청 절차 확인·전달',body:'계정 신청 절차를 확인해 전달합니다.',owner:'IT 담당',due:'10월 27일 오후 3시까지',refs:['u5'],context:'담당 역할과 날짜·시각은 발언에서 확인됩니다. 전달 대상의 구체적인 이름은 원문에 없습니다.'}
    ],
    pending:[
      {id:'p1',label:'담당·기한 확인 필요',title:'출근 동선 사진의 촬영 담당과 일정',body:'총무 담당이 담당 의사를 제안하고 촬영 가능 여부를 알아보겠다고 했습니다. 촬영 담당 확정·촬영일·확인 완료 기한은 미정입니다.',refs:['u6'],context:'“맡을 수 있을 것 같아요”를 확정 배정으로 바꾸지 않습니다. “알아볼게요”도 촬영 완료 약속과 구분합니다.'},
      {id:'p2',label:'일정 확인 필요',title:'최종 배포일과 검토 완료 예정일',body:'“다음 주 수요일”은 희망 일정입니다. 팀장은 검토 후 배포일을 정하자고 했습니다.',refs:['u7','u8'],context:'제안된 날짜와 최종 결정이 다릅니다. 수요일을 확정 일정으로 등록하지 않는 예시입니다.'}
    ]
  };
  var steps=[
    {title:'회의 메모·텍스트를 준비합니다.',text:'입사 안내문 개편 회의의 발언 메모를 선택합니다. 발언 역할과 문단을 함께 보관해 나중에 근거를 확인할 수 있도록 구성합니다.',result:'예시 입력: 가상 발언 8개 · 인사/IT/총무 역할 표시'},
    {title:'사내 환경에서 정리할 초안을 만듭니다.',text:'합의된 내부 전용 구성에서 결정·할 일·미정사항을 나누고 근거 발언을 연결하는 방식입니다. 사용 모델과 실제 처리·저장 경로는 구축 시 검증합니다.',result:'예시 출력: 결정 3건 · 담당과 기한이 있는 작업 2건 · 미정 2건'},
    {title:'사람이 근거와 빠진 내용을 확인합니다.',text:'인사 담당의 10월 26일 기한이 맞는지 원문을 확인합니다. 사진 촬영 담당과 배포일은 담당자에게 확인하고 수정할 대상으로 남깁니다.',result:'검토 대상: 담당·기한·배포 조건 · 애매한 발언의 해석'},
    {title:'검토한 문서를 정해진 사람에게 공유합니다.',text:'실제 검토자가 회사 양식을 확인한 뒤 공유 범위와 배포 방법을 정합니다. 이 예시는 문서를 자동 승인하거나 메일·협업 도구로 배포하지 않습니다.',result:'회사별 합의: 최종 검토자 · 사내 공유 대상 · 배포 방법'}
  ];
  var MARKUP =
    '<div class="mg-page" id="pop-meeting-guide" lang="ko" data-use="meetings">' +
    '<section class="mg-hero">' +
    '  <div class="mg-kicker">회사 맞춤 AI · 회의록 정리</div>' +
    '  <h1>회의가 끝나면,<br>할 일이 분명해지도록.</h1>' +
    '  <p class="mg-lead">긴 대화에서 결정과 할 일을 나누고,<br>누가 언제까지 할지, 아직 정하지 않은 것은 무엇인지 확인합니다.</p>' +
    '  <div class="mg-pills"><span class="mg-pill"><img class="icon mg-icon" src="assets/icons/shield.svg" alt="" aria-hidden="true" width="24" height="24">내부 전용 구축 목표</span><span class="mg-pill">우리 회사 회의록 양식</span></div>' +
    '  <p class="mg-hero-note">회사 자료·입력 방식·검토 절차에 맞춰 구성하는 업무 예시입니다. 내부 전용 적용 범위는 구축과 실제 통신 점검 후 확정합니다.</p>' +
    '</section>' +
    '<section class="mg-section" aria-labelledby="mg-example-title">' +
    '  <div class="mg-kicker">실무 예시 · 결정과 제안을 구분하기</div>' +
    '  <h2 id="mg-example-title">“수요일이면 좋겠는데”를<br>확정 일정으로 적지 않습니다.</h2>' +
    '  <div class="mg-disclosure">아래 회의·문서·날짜·발언·결과는 모두 <strong>가상 예시</strong>입니다. 실제 녹음이나 LLM 실행 결과가 아닙니다.</div>' +
    '  <div class="mg-result-shell">' +
    '    <div class="mg-result-head"><div><div class="mg-kicker">신입사원 입사 안내문 개편 회의</div><h3>회의 내용을 업무로 정리한 예시</h3></div><span class="mg-state-label">담당자 검토 전</span></div>' +
    '    <div class="mg-meeting-meta"><span><img class="icon mg-icon" src="assets/icons/clock.svg" alt="" aria-hidden="true" width="24" height="24">2026.10.23 · 가상 회의</span><span><img class="icon mg-icon" src="assets/icons/users.svg" alt="" aria-hidden="true" width="24" height="24">인사·IT·총무</span></div>' +
    '    <div class="mg-tabs" role="group" aria-label="회의 정리 결과 구분">' +
    '      <button type="button" data-mg-kind="decisions" aria-pressed="false">결정사항 <span>3</span></button>' +
    '      <button type="button" data-mg-kind="tasks" aria-pressed="true">할 일 <span>2</span></button>' +
    '      <button type="button" data-mg-kind="pending" aria-pressed="false">미정사항 <span>2</span></button>' +
    '    </div>' +
    '    <div class="mg-results" id="mg-results" aria-live="polite"></div>' +
    '    <div class="mg-selected-source" id="mg-source-panel" hidden aria-live="polite"><div class="mg-kicker" id="mg-source-heading">이 정리의 근거 발언</div><div id="mg-source-quotes"></div><div class="mg-source-context" id="mg-source-context"></div></div>' +
    '  </div>' +
    '  <details class="mg-transcript" id="mg-transcript"><summary>가상 원문 8개 발언 전체 보기</summary><ol>' +
    '    <li id="mg-u1" data-mg-utterance="u1"><div class="mg-utterance-head"><span>00:18</span><strong>인사팀장</strong><span class="mg-linked-label" hidden>선택한 근거</span></div><blockquote>“이번에는 신입사원 입사 전 준비 안내만 개편하겠습니다. 교육 일정은 이번 범위에서 빼죠.”</blockquote></li>' +
    '    <li id="mg-u2" data-mg-utterance="u2"><div class="mg-utterance-head"><span>01:02</span><strong>인사 담당</strong><span class="mg-linked-label" hidden>선택한 근거</span></div><blockquote>“준비 서류, 계정 신청, 첫 출근 안내 세 부분으로 나누면 어떨까요?”</blockquote></li>' +
    '    <li id="mg-u3" data-mg-utterance="u3"><div class="mg-utterance-head"><span>01:26</span><strong>인사팀장</strong><span class="mg-linked-label" hidden>선택한 근거</span></div><blockquote>“좋습니다. 그 세 부분으로 구성하고 기존 안내문을 기준으로 고칩시다.”</blockquote></li>' +
    '    <li id="mg-u4" data-mg-utterance="u4"><div class="mg-utterance-head"><span>02:10</span><strong>인사 담당</strong><span class="mg-linked-label" hidden>선택한 근거</span></div><blockquote>“준비 서류 부분의 초안은 제가 10월 26일까지 작성하겠습니다.”</blockquote></li>' +
    '    <li id="mg-u5" data-mg-utterance="u5"><div class="mg-utterance-head"><span>03:05</span><strong>IT 담당</strong><span class="mg-linked-label" hidden>선택한 근거</span></div><blockquote>“계정 신청 절차는 제가 10월 27일 오후 3시까지 확인해서 전달하겠습니다.”</blockquote></li>' +
    '    <li id="mg-u6" data-mg-utterance="u6"><div class="mg-utterance-head"><span>04:20</span><strong>총무 담당</strong><span class="mg-linked-label" hidden>선택한 근거</span></div><blockquote>“출근 동선 사진은 제가 맡을 수 있을 것 같아요. 이번 주에 촬영 가능한지부터 알아볼게요.”</blockquote></li>' +
    '    <li id="mg-u7" data-mg-utterance="u7"><div class="mg-utterance-head"><span>05:12</span><strong>인사 담당</strong><span class="mg-linked-label" hidden>선택한 근거</span></div><blockquote>“다음 주 수요일에 배포하면 좋겠는데, 팀장님 검토가 그전에 끝날까요?”</blockquote></li>' +
    '    <li id="mg-u8" data-mg-utterance="u8"><div class="mg-utterance-head"><span>05:50</span><strong>인사팀장</strong><span class="mg-linked-label" hidden>선택한 근거</span></div><blockquote>“배포일은 검토가 끝나면 정합시다. 검토 완료 전에는 공유하지 말아 주세요.”</blockquote></li>' +
    '  </ol><p class="mg-small" style="padding:0 18px 18px">시각은 가상 발언의 위치 표시입니다. 텍스트 메모를 쓰는 구성에서는 문단 번호로 근거를 연결할 수 있습니다.</p></details>' +
    '  <div class="mg-exception"><div class="mg-kicker">사람이 확인할 경계</div><h3>가능성은 가능성으로 남깁니다.</h3><div class="mg-exception-line"><div>“제가 맡을 수 있을 것 같아요.”</div><div class="mg-arrow" aria-hidden="true">→</div><div><mark>촬영 담당 제안 · 확정 필요</mark></div></div><p>촬영 가능 여부를 알아보겠다는 말과 촬영 완료 약속은 다릅니다. 담당·기한을 추측해 채우지 않고, 확인할 항목으로 남기도록 구성합니다.</p></div>' +
    '</section>' +
    '<div class="mg-divider"></div>' +
    '<section class="mg-section" aria-labelledby="mg-flow-title">' +
    '  <div class="mg-kicker">입력부터 사내 공유까지</div><h2 id="mg-flow-title">초안은 AI가 돕고,<br>확정은 담당자가 합니다.</h2>' +
    '  <ol class="mg-flow" aria-label="회의록을 만드는 업무 흐름">' +
    '    <li><button type="button" data-mg-stage="0" aria-pressed="true"><span>01</span><strong>회의 내용 입력</strong></button></li>' +
    '    <li><button type="button" data-mg-stage="1" aria-pressed="false"><span>02</span><strong>사내 AI 정리</strong></button></li>' +
    '    <li><button type="button" data-mg-stage="2" aria-pressed="false"><span>03</span><strong>사람이 검토</strong></button></li>' +
    '    <li><button type="button" data-mg-stage="3" aria-pressed="false"><span>04</span><strong>사내 공유</strong></button></li>' +
    '  </ol>' +
    '  <div class="mg-flow-detail" aria-live="polite"><h3 id="mg-stage-title"></h3><p id="mg-stage-text"></p><div class="mg-flow-result" id="mg-stage-result"></div></div>' +
    '  <button type="button" class="mg-secondary" id="mg-document-button" aria-expanded="false" aria-controls="mg-document">회사 양식의 검토할 문서 예시 보기</button>' +
    '  <article class="mg-document" id="mg-document" hidden aria-label="가상 회의록 검토 문서">' +
    '    <div class="mg-doc-top"><span class="mg-state-label">가상 문서 · 검토 전</span><h3>신입사원 입사 안내문 개편 회의록</h3><p class="mg-small">회의일 2026.10.23 · 참석 역할 인사팀장 / 인사 담당 / IT 담당 / 총무 담당</p></div>' +
    '    <h4>회의 목적</h4><p>입사 전 준비 안내문의 개편 범위와 후속 작업을 정리합니다.</p>' +
    '    <h4>결정사항</h4><ul><li>입사 전 준비 안내만 개편하고 교육 일정은 제외합니다. <span class="mg-small">[00:18]</span></li><li>준비 서류·계정 신청·첫 출근 안내로 구성하고 기존 안내문을 기준으로 수정합니다. <span class="mg-small">[01:02 · 01:26]</span></li><li>검토 완료 전에는 배포하지 않습니다. <span class="mg-small">[05:50]</span></li></ul>' +
    '    <h4>후속 작업</h4><div class="mg-doc-task"><strong>준비 서류 초안 작성</strong><span>인사 담당 · 2026.10.26까지 · 근거 02:10</span></div><div class="mg-doc-task"><strong>계정 신청 절차 확인·전달</strong><span>IT 담당 · 2026.10.27 오후 3시까지 · 근거 03:05</span></div>' +
    '    <h4>확인이 필요한 사항</h4><ul><li>사진 촬영 담당은 제안 단계입니다. 촬영 가능 여부를 알아보겠다는 발언은 있으나 확인 완료 기한과 촬영일은 미정입니다. <span class="mg-small">[04:20]</span></li><li>다음 주 수요일은 희망 배포일입니다. 검토 완료 예정일과 최종 배포일을 확인해야 합니다. <span class="mg-small">[05:12 · 05:50]</span></li></ul>' +
    '    <div class="mg-review-note"><strong>검토할 문서 예시입니다.</strong><br>이 버튼으로 업무가 등록되거나 문서가 승인·배포되지 않습니다. 실제 검토자·공유 대상·배포 방법은 회사 절차에 맞춰 정합니다.</div>' +
    '  </article>' +
    '</section>' +
    '<div class="mg-divider"></div>' +
    '<section class="mg-section" aria-labelledby="mg-config-title">' +
    '  <div class="mg-kicker">회사에 맞춰 먼저 정할 것</div><h2 id="mg-config-title">같은 회의라도,<br>남겨야 할 내용은 다르니까요.</h2>' +
    '  <ol class="mg-config-list">' +
    '    <li><span class="mg-config-number">01</span><div><h3>입력 자료와 방식</h3><p>회의 메모·텍스트의 형식을 정합니다. 녹음 파일 처리와 음성 전사는 제공 가능 여부 및 범위를 별도로 합의합니다.</p></div></li>' +
    '    <li><span class="mg-config-number">02</span><div><h3>우리 회사 회의록 양식</h3><p>결정사항·후속 작업·담당·기한·미정사항 중 필요한 항목과 요약 수준을 정합니다.</p></div></li>' +
    '    <li><span class="mg-config-number">03</span><div><h3>담당·기한을 확정하는 규칙</h3><p>역할과 이름을 연결할지, ‘다음 주’와 같은 날짜나 애매한 발언을 누가 확인할지 정합니다.</p></div></li>' +
    '    <li><span class="mg-config-number">04</span><div><h3>접근 권한과 자료 보관</h3><p>원문과 회의록을 볼 사람, 보관 위치·기간·삭제 방법을 정합니다. 자동 권한 연동은 별도 확인 항목입니다.</p></div></li>' +
    '    <li><span class="mg-config-number">05</span><div><h3>검토와 공유 승인</h3><p>검토자와 공유 대상을 정합니다. 실시간 녹음, 자동 업무 등록·배포, 협업 도구 연동이 기본 포함되는 것은 아닙니다.</p></div></li>' +
    '  </ol>' +
    '  <div class="mg-security"><strong>내부 전용은 고객 환경에서 확인하는 구축 목표입니다.</strong><br>문서·질문·답변·처리 기록의 저장과 외부 통신, 업데이트·원격지원·백업 경로를 확인합니다. 외부 AI API를 사용하는 구성에는 ‘업무 데이터 외부 전송 없음’을 약속할 수 없습니다.</div>' +
    '  <p class="mg-small" style="margin-top:14px">PC 구성·AI 설치·사용 안내를 상담하고, 자료 연결·접근 설정·교육·운영지원은 제공 가능 여부와 포함 범위를 확인한 뒤 견적에 명시합니다.</p>' +
    '  <h3 class="mg-build-heading" id="mg-build-title">우리 회사 회의록으로 구축하는 과정</h3>' +
    '  <p class="mg-small" style="margin-top:7px">회의 한 건을 정리하는 업무 흐름과 별도로, 도입 전에 합의할 과정입니다.</p>' +
    '  <ol class="mg-build-list" aria-labelledby="mg-build-title">' +
    '    <li><strong>회의 유형·기존 양식 확인</strong><span>어떤 회의에서 무엇을 남길지, 현재 양식과 검토 방식을 살펴봅니다.</span></li>' +
    '    <li><strong>장비·내부 처리·범위와 견적 합의</strong><span>입력 방식과 설치 환경, 제공 항목·제외 항목·비용을 정합니다.</span></li>' +
    '    <li><strong>합의한 양식·자료·접근 설정 구성</strong><span>계약에 포함된 자료 연결과 사용자 접근 범위에 맞춰 구성합니다.</span></li>' +
    '    <li><strong>실제 발언·애매한 담당과 날짜·통신 검수</strong><span>고객이 허용한 사례로 근거와 미정사항 처리를 확인하고 실제 통신 경로를 점검합니다.</span></li>' +
    '    <li><strong>사용 안내·인계</strong><span>담당자에게 사용·검토·공유 방법을 안내하고, 지원 범위를 구분해 전달합니다.</span></li>' +
    '  </ol>' +
    '</section>' +
    '<section class="mg-cta" aria-labelledby="mg-cta-title">' +
    '  <div class="mg-kicker">업무형 · 회의록 정리</div><h2 id="mg-cta-title">우리 회사 회의 방식으로<br>상담을 시작해보세요.</h2><p class="mg-lead">실제 회의 원문을 보내기 전에,<br>회의 유형과 현재 쓰는 양식부터 이야기합니다.</p>' +
    '  <a class="mg-primary" id="mg-consult-link" href="ai-consult.html?package=business&amp;use=meetings&amp;intent=adoption">이 업무로 도입 상담하기 <img class="icon mg-icon" src="assets/icons/arrow-right.svg" alt="" aria-hidden="true" width="24" height="24"></a><p class="mg-small">상담 후 제공 가능 범위·구성·비용 안내</p>' +
    '  <a class="mg-back text-link" href="ai-detail.html?package=business">업무형 패키지로 돌아가기</a>' +
    '  <div class="mg-consult"><span class="mg-state-label">상담 화면에 이어지는 선택</span><h3 style="margin-top:13px">업무형 · 회의록 정리 · 도입 상담</h3><dl><dt>함께 확인할 내용</dt><dd>회의 메모 형식 · 회사 양식 · 검토자와 공유 범위</dd><dt>구축 방향</dt><dd>내부 전용 목표 구성 · 실제 환경 검토 후 확정</dd></dl><p class="mg-small mg-no-submit">이 화면을 본 것만으로 상담이 접수되거나 연락 동의가 되지 않습니다. 연락처 입력과 신청은 상담 화면에서 직접 하실 때만 진행됩니다.</p></div>' +
    '</section>' +
    '</div>';
  function body() { return MARKUP; }
  function mount() {
    var root = document.getElementById('pop-meeting-guide');
    if (!root) return;
    var q = function (sel) { return root.querySelector(sel); };
    function each(sel, fn) { Array.prototype.forEach.call(root.querySelectorAll(sel), fn); }
    function has(o, k) { return Object.prototype.hasOwnProperty.call(o, k); }
    function esc(v) { return h(String(v)); }
    var kind = 'tasks', stage = 0, sourceKey = null, transcriptOpen = false, documentOpen = false, syncDetails = false;
    var allItems = groups.decisions.concat(groups.tasks, groups.pending);
    function renderResults() {
      each('[data-mg-kind]', function (b) { b.setAttribute('aria-pressed', String(b.dataset.mgKind === kind)); });
      q('#mg-results').innerHTML = groups[kind].map(function (item, n) {
        return '<article class="mg-result"><div class="mg-result-top"><span>' + esc(item.label) + '</span><span>' + String(n + 1).padStart(2, '0') + '</span></div><h3>' + esc(item.title) + '</h3><p>' + esc(item.body) + '</p>' +
          (item.owner ? '<dl class="mg-task-fields"><div><dt>담당</dt><dd>' + esc(item.owner) + '</dd></div><div><dt>기한</dt><dd><mark>' + esc(item.due) + '</mark></dd></div></dl>' : '') +
          '<button type="button" class="mg-source-button" data-mg-ref="' + item.id + '" aria-expanded="' + String(sourceKey === item.id) + '" aria-controls="mg-source-panel">근거 보기 · ' + item.refs.map(function (id) { return raw[id].time; }).join(' / ') + '</button></article>';
      }).join('');
    }
    function renderSource() {
      var item = null;
      allItems.forEach(function (x) { if (x.id === sourceKey) item = x; });
      q('#mg-source-panel').hidden = !item;
      q('#mg-source-heading').textContent = item ? '“' + item.title + '”의 근거' : '이 정리의 근거 발언';
      q('#mg-source-quotes').innerHTML = item ? item.refs.map(function (id) { return '<div class="mg-source-quote"><strong>' + raw[id].time + ' · ' + esc(raw[id].role) + '</strong><blockquote>“' + esc(raw[id].text) + '”</blockquote></div>'; }).join('') : '';
      q('#mg-source-context').textContent = item ? item.context : '';
      each('[data-mg-utterance]', function (el) {
        var linked = !!item && item.refs.indexOf(el.dataset.mgUtterance) >= 0;
        el.dataset.linked = String(linked);
        el.querySelector('.mg-linked-label').hidden = !linked;
      });
      each('[data-mg-ref]', function (b) { b.setAttribute('aria-expanded', String(b.dataset.mgRef === sourceKey)); });
    }
    function renderStage() {
      var s = steps[stage];
      each('[data-mg-stage]', function (b) { b.setAttribute('aria-pressed', String(Number(b.dataset.mgStage) === stage)); });
      q('#mg-stage-title').textContent = s.title; q('#mg-stage-text').textContent = s.text; q('#mg-stage-result').textContent = s.result;
    }
    function renderAux() {
      syncDetails = true; q('#mg-transcript').open = transcriptOpen; syncDetails = false;
      q('#mg-document').hidden = !documentOpen;
      q('#mg-document-button').setAttribute('aria-expanded', String(documentOpen));
      q('#mg-document-button').textContent = documentOpen ? '검토할 문서 예시 접기' : '회사 양식의 검토할 문서 예시 보기';
    }
    // 탭·근거·단계·문서 버튼은 화면 표시만 바꾼다 -- 저장·전송·상담 접수가 없다. 상담은 아래 링크로만 간다.
    root.addEventListener('click', function (e) {
      var b = e.target.closest('button');
      if (!b || !root.contains(b)) return;
      if (b.dataset.mgKind && has(groups, b.dataset.mgKind)) { kind = b.dataset.mgKind; sourceKey = null; renderResults(); renderSource(); }
      else if (b.dataset.mgStage !== undefined) { var next = Number(b.dataset.mgStage); if (next >= 0 && next < steps.length) { stage = next; renderStage(); } }
      else if (b.dataset.mgRef) {
        if (!groups[kind].some(function (x) { return x.id === b.dataset.mgRef; })) return;
        sourceKey = sourceKey === b.dataset.mgRef ? null : b.dataset.mgRef;
        if (sourceKey) transcriptOpen = true;
        renderSource(); renderAux();
      }
      else if (b.id === 'mg-document-button') { documentOpen = !documentOpen; renderAux(); }
    });
    q('#mg-transcript').addEventListener('toggle', function () { if (!syncDetails) transcriptOpen = q('#mg-transcript').open; });
    renderResults(); renderSource(); renderStage(); renderAux();
  }
  P.serviceGuides = P.serviceGuides || {};
  P.serviceGuides.meetings = {label: '회의록 정리', title: '회의록 정리', body: body, mount: mount};
}());
