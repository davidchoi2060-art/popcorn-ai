/* 기본형·고급형 업무 상세 5개 (/mvp4/ai-service.html?package=basic|advanced&use=...) -- 2026-10-23 대표 승인 시안 적용.
   요청서: 코덱스-검수/2026-10-23-기본형-고급형-5개-업무상세-적용요청.txt
   승인 ZIP: popcorn-basic-advanced-task-design-20261023.zip (SHA256 1f800d3b7a574e189a05aa13acb61cfe0c6dbda70e82e566d789a613d74b577b)
   업무별 내용은 시안 prototype/src/data.js 를 그대로 옮겼다(문구 수정 없음). 화면 구성·상호작용은 App.jsx 를 기존 사이트 방식(문자열 렌더)으로 옮겼다.
   - 사이트 공통 셸(헤더·로고·검색·메뉴·띠메뉴·푸터)은 boot.js 가 그대로 그린다. 시안의 헤더 복사본·업무 전환 막대·푸터는 옮기지 않는다.
   - 시안의 「상담 연결 미리보기」는 실제 연결 ai-consult.html?package=..&use=..&intent=adoption&pc=existing|new 로 바꿨다.
     이 화면은 아무것도 보내지 않는다(네트워크 요청·저장·동의 없음). 탭·원문·단계·PC 선택은 화면 표시와 상담 링크만 바꾼다.
   - 자료·질문·결과·원문은 가상 예시다. 상품 번호·가격·성능 보장은 넣지 않는다. 로컬 실행은 조건(설치·통신 점검)과 함께 설명한다. */
(function () {
  'use strict';
  var P = window.PAI, h = P.h;
  // 업무별 내용(시안 data.js 그대로, 키 = 패키지:업무)
  var TASKS = {
   "basic:study": {
    "id": "study",
    "tier": "basic",
    "name": "학습 자료 정리",
    "icon": "file-text-duotone",
    "title": [
     "흩어진 학습 자료를,",
     "나만의 공부 흐름으로."
    ],
    "desc": "강의 자료와 내 메모를 한곳에서 살펴보고,\n개념 정리부터 복습 질문까지 이어갑니다.",
    "tag": "내 자료 · 내 공부 방식",
    "outcome": "단원별 개념 노트 + 복습 질문",
    "audience": "강의 PDF와 필기를 함께 보는 학생·자격시험 준비자·직장인",
    "intro": "자료는 쌓였는데,\n어디부터 복습할지 막막할 때.",
    "example": "강의 PDF와 필기를 단원별 복습 노트로",
    "files": [
     "강의자료_표본과모집단.pdf · 12쪽",
     "나의_강의필기.txt · 2쪽"
    ],
    "prompt": "올린 자료에서 모집단과 표본의 차이를 정리하고, 헷갈리기 쉬운 부분과 복습 질문 3개를 만들어줘. 근거 쪽수도 적어줘.",
    "source": [
     {
      "label": "강의자료 · 4쪽",
      "body": "모집단은 조사 대상 전체이고, 표본은 그중 조사 대상으로 뽑은 일부이다. 표본을 고른 방법에 따라 결과가 달라질 수 있다."
     },
     {
      "label": "내 필기 · 1쪽",
      "body": "모든 사람을 조사하기 어렵기 때문에 일부를 조사한다. 단, 표본이 전체를 잘 대표하는지 확인해야 한다. 표본 수가 많아도 선택 방법이 치우치면 전체를 잘 대표하지 못할 수 있다."
     }
    ],
    "variants": [
     {
      "name": "개념 노트",
      "heading": "모집단과 표본, 이렇게 구분해요.",
      "bullets": [
       "모집단: 알고 싶은 대상 전체입니다. [강의자료 4쪽]",
       "표본: 모집단 중 실제로 조사한 일부입니다. [강의자료 4쪽]",
       "헷갈리는 지점: 표본 수가 많아도 선택 방법이 치우치면 결과가 달라질 수 있습니다. [내 필기 1쪽]"
      ],
      "ref": "강의자료 4쪽 · 내 필기 1쪽"
     },
     {
      "name": "복습 질문",
      "heading": "답을 보기 전에, 먼저 설명해 보세요.",
      "bullets": [
       "모집단과 표본을 한 문장씩 설명할 수 있나요?",
       "표본을 고르는 방법은 왜 중요할까요?",
       "이번 자료만으로 판단할 수 없는 것은 무엇인가요?"
      ],
      "ref": "사용자가 복습하는 용도 · 정답은 원문과 대조"
     }
    ],
    "review": "모르는 내용은 원문으로 돌아가 확인합니다. 자료에 없는 시험 범위나 출제 가능성을 만들어 넣지 않습니다.",
    "flow": [
     [
      "자료 고르기",
      "강의 PDF·내 필기"
     ],
     [
      "단원 묶기",
      "목차·개념 연결"
     ],
     [
      "복습 노트",
      "개념·질문 정리"
     ],
     [
      "근거 확인",
      "원문 쪽수 대조"
     ],
     [
      "내 노트 저장",
      "수정한 내용 보관"
     ]
    ],
    "setup": [
     [
      "내 자료 읽기 설정",
      "실제 PDF·텍스트를 시험해 읽히는 형식과 범위를 정합니다."
     ],
     [
      "공부용 질문 틀",
      "개념 정리·비교·복습 질문 양식을 사용 목적에 맞춥니다."
     ],
     [
      "내 PC 사용 안내",
      "자료 추가·갱신·삭제와 원문 확인 방법을 함께 익힙니다."
     ]
    ],
    "prepare": [
     "자료 형식과 대략적인 분량",
     "정리하고 싶은 과목·시험·학습 목적",
     "현재 PC 사양과 인터넷 차단 필요 여부"
    ],
    "hardware": "텍스트 자료량, 동시에 펼칠 문서 수, 답변 속도에 맞춰 메모리와 모델 크기를 봅니다. 스캔 강의 자료는 글자 인식 품질을 먼저 확인합니다.",
    "boundary": "강의 사이트 자동 수집·문제은행 무단 복제·시험 결과 보장은 포함하지 않습니다.",
    "faq": [
     [
      "손글씨나 스캔 PDF도 되나요?",
      "읽기 품질에 따라 달라집니다. 대표 파일을 시험한 뒤 가능한 범위를 정합니다."
     ],
     [
      "모든 과목을 알아서 가르쳐 주나요?",
      "지정한 자료를 정리하고 질문하는 방식부터 구성합니다. 교재 밖의 정답·최신 시험 정보는 별도 확인이 필요합니다."
     ]
    ],
    "flowDetails": [
     "이번에 복습할 강의 PDF와 내 필기만 고릅니다. 스캔 자료라면 글자가 제대로 읽히는지 먼저 확인합니다.",
     "목차와 단원 이름을 기준으로 관련 필기를 묶습니다. 서로 다른 개념을 같은 내용으로 합치지 않았는지 확인합니다.",
     "개념·비교·복습 질문을 나눠 노트를 만듭니다. 설명 옆에는 확인할 문서와 쪽수를 표시하는 양식을 씁니다.",
     "원문을 펼쳐 정의와 예시가 맞는지 확인합니다. 답이 자료에 없으면 확인이 필요한 질문으로 남깁니다.",
     "내가 수정한 노트를 보관하고 다음 복습에 씁니다. 새로운 강의 자료를 추가하는 방법도 안내합니다."
    ]
   },
   "basic:summary": {
    "id": "summary",
    "tier": "basic",
    "name": "자료 요약",
    "icon": "file-text-duotone",
    "title": [
     "긴 자료의 핵심을,",
     "근거와 함께 한눈에."
    ],
    "desc": "읽어야 할 문서에서 필요한 내용만 정리하고,\n숫자와 조건은 원문으로 다시 확인합니다.",
    "tag": "핵심 요약 · 원문 확인",
    "outcome": "핵심 요약 + 조건·주의사항 + 출처",
    "audience": "매뉴얼·리포트·조사 자료를 빠르게 파악해야 하는 개인",
    "intro": "긴 문서를 읽기 전에,\n중요한 조건부터 보고 싶을 때.",
    "example": "장비 사용 설명서를 처음 쓰는 사람용으로 요약",
    "files": [
     "장비_사용설명서.pdf · 18쪽",
     "추가_사용메모.txt · 1쪽"
    ],
    "prompt": "처음 사용하는 사람을 위해 시작 순서, 보관 조건, 주의사항을 나눠 요약해줘. 숫자는 그대로 적고, 없는 정보는 없다고 표시해줘.",
    "source": [
     {
      "label": "사용설명서 · 3쪽",
      "body": "처음 사용하기 전 부속품을 확인하고 안내된 설치 순서를 따른다. 전원을 연결하기 전에 케이블 연결 상태를 확인한다."
     },
     {
      "label": "사용설명서 · 11쪽",
      "body": "보관 온도는 5~35℃이며 물이 닿지 않는 곳에 보관한다. 본 설명서에는 소모품 교체 주기가 기재되어 있지 않다."
     }
    ],
    "variants": [
     {
      "name": "핵심 요약",
      "heading": "처음 사용할 때 확인할 3가지",
      "bullets": [
       "시작 순서: 부속품 확인 → 케이블 연결 확인 → 안내된 설치 순서 진행. [3쪽]",
       "보관 조건: 5~35℃, 물이 닿지 않는 장소. [11쪽]",
       "소모품 교체 주기: 제공된 자료에서 확인되지 않습니다."
      ],
      "ref": "사용설명서 3쪽 · 11쪽"
     },
     {
      "name": "확인할 조건",
      "heading": "숫자와 빠진 정보는 따로 확인해요.",
      "bullets": [
       "원문 수치 5~35℃를 유지했는지 확인합니다.",
       "보관 온도와 작동 온도를 같은 조건으로 바꾸지 않습니다.",
       "소모품 교체 주기는 판매자 또는 제조사의 최신 안내를 확인합니다."
      ],
      "ref": "요약의 빈칸을 추측으로 채우지 않는 설계"
     }
    ],
    "review": "요약은 빠르게 읽기 위한 초안입니다. 계약·안전·의사결정에 쓰는 수치와 조건은 원문을 확인합니다.",
    "flow": [
     [
      "자료 지정",
      "읽을 문서 선택"
     ],
     [
      "목적 정하기",
      "핵심·조건·비교"
     ],
     [
      "내용 정리",
      "요약과 출처"
     ],
     [
      "원문 대조",
      "숫자·예외 확인"
     ],
     [
      "요약 보관",
      "검토본 저장"
     ]
    ],
    "setup": [
     [
      "문서 읽기 확인",
      "표·스캔·다단 문서가 어떻게 읽히는지 샘플로 확인합니다."
     ],
     [
      "요약 양식 설정",
      "핵심 5줄·주의사항·자료 간 비교 등 사용할 결과 틀을 만듭니다."
     ],
     [
      "출처 확인 경로",
      "원문 제목과 위치를 함께 확인하는 사용 흐름을 구성합니다."
     ]
    ],
    "prepare": [
     "문서 종류와 평균 페이지 수",
     "원하는 요약 길이와 항목",
     "표·이미지·스캔 자료 포함 여부"
    ],
    "hardware": "평균 문서 길이와 한 번에 비교할 자료 수를 먼저 봅니다. 긴 문서는 나누어 처리할 수 있는지도 확인하고 필요한 사양을 정합니다.",
    "boundary": "원문보다 정확한 해석을 보장하거나, 빠진 정보를 임의로 채우는 서비스가 아닙니다.",
    "faq": [
     [
      "표의 숫자도 정확하게 요약하나요?",
      "표 구조와 읽기 품질부터 확인합니다. 중요한 숫자는 원문 대조 단계를 두며 정확도를 무조건 보장하지 않습니다."
     ],
     [
      "인터넷의 최신 자료도 찾아주나요?",
      "지정한 로컬 자료를 대상으로 하는 기본 흐름입니다. 인터넷 검색 연결은 별도 범위로 구분합니다."
     ]
    ],
    "flowDetails": [
     "요약할 설명서와 문서 버전을 고릅니다. 원하는 분량과 꼭 남겨야 할 조건을 함께 정합니다.",
     "본문과 표가 읽히는지 확인하고 핵심 항목을 찾습니다. 온도·단위·사용 조건 같은 숫자 정보를 따로 살핍니다.",
     "한눈에 볼 핵심 요약과 자세히 확인할 조건을 분리합니다. 자료에 없는 항목은 ‘확인 필요’로 남깁니다.",
     "요약에 적힌 수치·조건·예외를 원문 쪽수와 비교합니다. 짧게 줄이는 과정에서 중요한 제한이 빠졌는지 살핍니다.",
     "검토한 요약본을 원문과 구분해서 저장합니다. 원문이 바뀌면 요약도 다시 확인해야 합니다."
    ]
   },
   "basic:writing": {
    "id": "writing",
    "tier": "basic",
    "name": "글쓰기 초안",
    "icon": "file-text-duotone",
    "title": [
     "내 메모를 바탕으로,",
     "첫 문장을 쉽게."
    ],
    "desc": "생각해 둔 내용과 참고 자료로 글의 구조를 잡고,\n내 말투에 맞게 다듬을 초안을 준비합니다.",
    "tag": "내 메모 · 내 말투",
    "outcome": "글의 목차 + 초안 + 확인할 빈칸",
    "audience": "안내문·소개글·블로그 글의 시작이 막막한 개인",
    "intro": "하고 싶은 말은 있는데,\n글로 꺼내기 어려울 때.",
    "example": "짧은 메모를 모임 안내문 초안으로",
    "files": [
     "모임_준비메모.txt · 1쪽",
     "지난_안내문.txt · 1쪽"
    ],
    "prompt": "메모만 바탕으로 독서 모임 안내문을 써줘. 일시와 장소는 미정이니 빈칸으로 남기고, 준비물은 책과 필기도구만 적어줘.",
    "source": [
     {
      "label": "준비 메모",
      "body": "작은 독서 모임을 열 예정. 각자 읽고 있는 책과 필기도구를 가져오기. 일시와 장소는 아직 정하지 않음. 신청 방법도 미정."
     },
     {
      "label": "지난 안내문 · 말투 참고",
      "body": "안녕하세요. 함께 읽고 이야기하는 시간을 준비했어요. 부담 없이 참여해 주세요."
     }
    ],
    "variants": [
     {
      "name": "글의 구조",
      "heading": "먼저, 들어갈 내용부터 정리해요.",
      "bullets": [
       "첫 문단: 독서 모임의 목적과 초대 인사",
       "본문: 일시 [확인 필요] · 장소 [확인 필요]",
       "마무리: 준비물 — 읽고 있는 책, 필기도구 · 신청 방법 [확인 필요]"
      ],
      "ref": "준비 메모에서 확인된 사실만 사용"
     },
     {
      "name": "안내문 초안",
      "heading": "함께 읽고 이야기해요.",
      "bullets": [
       "안녕하세요. 각자 읽고 있는 책을 나누는 작은 독서 모임을 준비했어요.",
       "일시: [확인 필요] / 장소: [확인 필요]",
       "읽고 있는 책과 필기도구를 가져와 주세요. 신청 방법은 [확인 필요]입니다."
      ],
      "ref": "친근한 말투 예시 · 게시 전 직접 검토"
     }
    ],
    "review": "날짜·장소·비용처럼 메모에 없는 사실은 빈칸으로 남깁니다. 게시와 발송은 사용자가 검토한 뒤 직접 합니다.",
    "flow": [
     [
      "메모 모으기",
      "사실·참고글"
     ],
     [
      "목적 정하기",
      "독자·말투·길이"
     ],
     [
      "구조와 초안",
      "목차부터 작성"
     ],
     [
      "내가 다듬기",
      "사실·표현 확인"
     ],
     [
      "최종본 사용",
      "직접 게시·전달"
     ]
    ],
    "setup": [
     [
      "자주 쓰는 글 설정",
      "안내문·소개글 등 필요한 글 종류와 결과 형식을 정합니다."
     ],
     [
      "내 표현 참고",
      "사용 권한이 있는 글과 말투를 참고하도록 범위를 정합니다."
     ],
     [
      "초안 검토 안내",
      "빠진 사실 표시, 원문 확인, 최종 수정 방법을 안내합니다."
     ]
    ],
    "prepare": [
     "자주 작성하는 글의 종류",
     "원하는 독자·말투·길이",
     "사용 가능한 참고글과 현재 PC"
    ],
    "hardware": "주로 쓰는 글의 길이와 참고 문서량을 기준으로 모델과 메모리를 봅니다. 짧은 글 초안만으로 고사양 PC가 필요하다고 정하지 않습니다.",
    "boundary": "자동 게시·대량 발송·표절 여부 보장·전문 자격이 필요한 문서의 최종 판단은 별도입니다.",
    "faq": [
     [
      "내 말투를 학습시키는 건가요?",
      "우선 참고 문장과 작성 규칙을 적용하는 방식입니다. 모델 재학습이 기본 포함되는 것은 아닙니다."
     ],
     [
      "작성한 글이 바로 공개되나요?",
      "아닙니다. 초안을 검토하고 사용자가 직접 게시·전달하는 흐름으로 설계합니다."
     ]
    ],
    "flowDetails": [
     "누구에게 어떤 글을 쓸지 정하고 내 메모를 모읍니다. 날짜·장소·신청 방법처럼 필요한 사실을 구분합니다.",
     "읽는 사람과 목적에 맞춰 제목·핵심 안내·신청 방법 순으로 뼈대를 잡습니다.",
     "확인된 메모를 바탕으로 초안을 씁니다. 메모에 없는 시간·장소는 임의로 채우지 않고 빈 항목으로 남깁니다.",
     "표현과 사실을 직접 고칩니다. 빠진 일정과 연락 방법을 확인하고, 내가 전달하려는 의미와 맞는지 읽어봅니다.",
     "확인한 글을 복사하거나 저장해 직접 게시합니다. AI가 대신 공지하거나 메시지를 발송하는 과정은 포함하지 않습니다."
    ]
   },
   "advanced:image": {
    "id": "image",
    "tier": "advanced",
    "name": "이미지 제작",
    "icon": "image-duotone",
    "title": [
     "머릿속 이미지에서,",
     "내 작업에 맞는 시안으로."
    ],
    "desc": "참고 이미지와 제작 조건을 바탕으로,\n내 PC에서 만들고 고르는 이미지 작업 흐름을 구성합니다.",
    "tag": "로컬 이미지 모델 · 제작 흐름",
    "outcome": "이미지 시안 + 수정 기록 + 제작 설정",
    "audience": "썸네일·분위기 컷·배경 시안을 반복 제작하는 개인 제작자",
    "intro": "같은 설명을 매번 반복하지 않고,\n원하는 분위기를 찾아갈 때.",
    "example": "제품 소개용 배경 분위기 시안 만들기",
    "files": [
     "내가_촬영한_참고이미지.png",
     "제작_조건메모.txt"
    ],
    "prompt": "밝은 원목 테이블과 부드러운 아침빛의 배경 시안을 만들어줘. 오른쪽은 문구를 넣을 수 있게 비워두고, 글자와 로고는 넣지 마.",
    "source": [
     {
      "label": "제작 조건",
      "body": "용도: 제품 소개에 사용할 배경 분위기 검토. 밝은 원목·차분한 연보라 소품. 오른쪽 문구 공간. 글자와 로고 제외."
     },
     {
      "label": "검토 기준",
      "body": "시안의 색감·여백·형태 오류를 확인한다. 실제 제품과 합성할 때 외형·로고·재질을 바꾸지 않았는지 별도 확인한다."
     }
    ],
    "variants": [
     {
      "name": "제작 조건",
      "heading": "반복해서 쓸 제작 기준을 먼저 정해요.",
      "bullets": [
       "용도·가로세로 비율·문구 영역을 먼저 지정합니다.",
       "허용된 참고 이미지와 제외할 요소를 정합니다.",
       "선택한 모델·설정·참고 자료를 함께 기록합니다."
      ],
      "ref": "배경 제작 예시 · 이미지 결과와 원본 검수는 별도"
     },
     {
      "name": "검토할 결과",
      "heading": "예쁜 이미지인지, 쓸 수 있는 이미지인지.",
      "bullets": [
       "문구가 들어갈 여백과 최종 크기를 확인합니다.",
       "제품 외형·글자·로고·손 등 깨지기 쉬운 부분을 확대해 봅니다.",
       "참고 자료 권리와 모델 이용 조건을 확인하고 최종 사용합니다."
      ],
      "ref": "시안 제작 → 선택 → 부분 수정 → 사람의 최종 확인"
     }
    ],
    "review": "상단 그림은 작업 흐름을 설명하는 미니어처입니다. 납품 PC에서 생성한 실측 결과가 아닙니다. 실제 상품을 대표하는 사진은 제품 일치 확인이 필요합니다.",
    "flow": [
     [
      "제작 조건",
      "용도·비율·참고"
     ],
     [
      "로컬 생성",
      "이미지 모델 실행"
     ],
     [
      "시안 선택",
      "분위기·형태 비교"
     ],
     [
      "부분 수정",
      "수정 범위 지정"
     ],
     [
      "검토·내보내기",
      "권리·규격 확인"
     ]
    ],
    "setup": [
     [
      "제작 환경 설치",
      "선택한 이미지 모델과 작업 화면의 설치 가능 여부를 확인합니다."
     ],
     [
      "작업 틀 구성",
      "목적별 크기·참고 이미지·수정·저장 흐름을 설정합니다."
     ],
     [
      "내 장비로 시험",
      "샘플 생성·수정·저장, 소요 시간과 메모리 사용을 확인합니다."
     ]
    ],
    "prepare": [
     "만들 이미지의 용도·크기·작업량",
     "사용 권한이 있는 참고 이미지",
     "그래픽카드 모델과 VRAM"
    ],
    "hardware": "이미지 모델, 해상도, 한 번에 만들 수량에 따라 GPU 메모리 요구가 달라집니다. 대표 작업을 시험한 뒤 적정 PC를 정합니다.",
    "boundary": "모든 모델 설치·무제한 제작 속도·정확한 제품 복제·상업적 권리 일괄 보장은 포함하지 않습니다.",
    "faq": [
     [
      "고급형이면 이미지와 개발이 모두 포함되나요?",
      "기본은 필요한 전문 기능을 선택해 범위를 정합니다. 두 기능을 함께 쓰려면 설치·지원 범위와 장비 적합성을 별도로 확인합니다."
     ],
     [
      "로컬 LLM으로 이미지를 만드나요?",
      "이미지는 별도의 이미지 생성 모델과 도구를 사용합니다. 글을 다루는 로컬 LLM과 실행 환경이 다르므로 별도로 구성합니다."
     ]
    ],
    "flowDetails": [
     "직접 쓰거나 사용 권한이 있는 사진을 고릅니다. 제품 원형 유지 여부와 필요한 이미지 크기를 함께 정합니다.",
     "정한 크기·색·빛·여백 조건을 선택한 로컬 이미지 모델에 적용해 시안을 만듭니다. 생성 기록과 임시 파일의 저장 위치도 확인합니다.",
     "여러 시안을 비교해 목적에 맞는 구도를 고릅니다. 제품 사진을 그대로 유지할 부분과 새로 생성한 부분을 구분합니다.",
     "제품 모양·로고·색상·깨진 형태를 확대해서 확인합니다. 수정할 조건을 바꿔 다시 만들거나 수작업 보정을 검토합니다.",
     "최종 검토한 결과를 필요한 형식으로 내보냅니다. 실제 게시 전 모델 이용 조건과 참고 자료의 사용 권한을 확인합니다."
    ]
   },
   "advanced:code": {
    "id": "code",
    "tier": "advanced",
    "name": "개발 보조",
    "icon": "code-duotone",
    "title": [
     "반복하는 작은 작업부터,",
     "내 도구로 바꾸세요."
    ],
    "desc": "코드 설명과 수정 초안을 내 환경에서 살펴보고,\n테스트를 거쳐 반복 업무에 쓸 도구를 준비합니다.",
    "tag": "로컬 코드 모델 · 사람이 검토",
    "outcome": "코드 초안 + 변경 설명 + 테스트 항목",
    "audience": "반복 파일 작업을 줄이려는 실무자·개인 개발자",
    "intro": "매번 손으로 정리하던 표를,\n검토할 수 있는 코드 초안으로.",
    "example": "상품 목록 CSV의 공백·중복 정리 도구 만들기",
    "files": [
     "상품목록_가상샘플.csv · 4행",
     "정리_규칙.txt · 1쪽"
    ],
    "prompt": "상품코드 앞뒤 공백을 없애고, 같은 코드와 이름인 중복 행만 정리하는 코드 초안을 만들어줘. 같은 코드인데 이름이 다르면 확인 목록으로 분리하고 원본은 건드리지 마.",
    "source": [
     {
      "label": "가상 CSV 샘플",
      "body": "상품코드,상품명\n A001 ,키보드\nA001,키보드\nB002,마우스\nB002,무선마우스"
     },
     {
      "label": "정리 규칙",
      "body": "원본 보존. 공백 제거 후 코드와 이름이 모두 같은 행만 중복 처리. 코드만 같고 이름이 다르면 별도 확인. 결과는 새 파일로 저장."
     }
    ],
    "variants": [
     {
      "name": "변경 내용",
      "heading": "무엇을 바꾸고, 무엇을 남길지.",
      "bullets": [
       "A001 앞뒤 공백 제거 후 동일한 키보드 행은 하나로 정리합니다.",
       "B002는 이름이 서로 다르므로 임의로 합치지 않고 확인 목록으로 분리합니다.",
       "원본 CSV를 수정하지 않고 정리본과 확인 목록을 새 파일로 만듭니다."
      ],
      "ref": "설명용 제안 결과 · 실제 코드 실행 결과 아님"
     },
     {
      "name": "테스트 항목",
      "heading": "실행 전에 확인할 것부터 준비해요.",
      "bullets": [
       "빈 파일, 한글, 쉼표가 들어간 상품명은 정상 처리하는가?",
       "동일 코드·다른 이름을 임의로 삭제하지 않는가?",
       "원본 파일이 그대로이고 오류 시 저장 결과를 구분할 수 있는가?"
      ],
      "ref": "검토할 테스트 목록 · 통과 결과를 표시한 것이 아님"
     }
    ],
    "review": "코드는 초안이며 사람이 검토하고 격리된 복사본에서 시험합니다. 운영 서버 실행·자동 배포·비밀키 입력을 기본 동작으로 두지 않습니다.",
    "flow": [
     [
      "작업 설명",
      "입출력·규칙"
     ],
     [
      "코드 초안",
      "설명·변경 제안"
     ],
     [
      "수정 검토",
      "변경점 확인"
     ],
     [
      "복사본 시험",
      "정상·예외 확인"
     ],
     [
      "직접 적용",
      "원본·버전 보존"
     ]
    ],
    "setup": [
     [
      "개발 도구 연결",
      "사용 언어·편집기·실행 환경에 맞는 로컬 모델 연결을 검토합니다."
     ],
     [
      "내 작업 규칙",
      "참조할 코드 범위, 제외 파일, 답변·수정 형식을 정합니다."
     ],
     [
      "검토·시험 흐름",
      "변경점 확인과 테스트 후 직접 반영하는 방법을 안내합니다."
     ]
    ],
    "prepare": [
     "개발 언어와 현재 편집기",
     "줄이고 싶은 반복 작업의 예시",
     "코드 반출 제한·기존 PC 환경"
    ],
    "hardware": "코드 길이, 동시에 참조할 파일 수, 모델 크기와 응답 속도로 사양을 정합니다. 저장소 전체를 한 번에 이해한다고 가정하지 않습니다.",
    "boundary": "완성 프로그램 납품·코드 보안 보증·운영 서버 자동 실행·무제한 저장소 연동은 기본 범위가 아닙니다.",
    "faq": [
     [
      "코딩을 몰라도 쓸 수 있나요?",
      "작업 설명과 코드 이해에 도움을 받을 수 있지만 실행·권한·결과 검토는 필요합니다. 별도 개발이 필요한 일은 상담에서 구분합니다."
     ],
     [
      "회사 시스템 전체 자동화도 해주나요?",
      "개인 업무 도구 보조와 범위가 다릅니다. 여러 담당자와 시스템에 걸친 작업은 30인 이하 기업 컨설팅에서 따로 검토합니다."
     ]
    ],
    "flowDetails": [
     "민감한 정보가 없는 샘플 CSV와 정리 규칙을 준비합니다. 원본은 그대로 두고 복사본을 작업 대상으로 정합니다.",
     "정한 공백 처리·중복 기준을 코드 초안으로 만듭니다. 같은 코드인데 이름이 다른 항목은 별도 확인 목록으로 보냅니다.",
     "코드가 읽고 쓰는 파일 경로와 변경점을 확인합니다. 원본을 덮어쓰거나 정해 둔 규칙 밖의 데이터를 지우지 않는지 검토합니다.",
     "복사본으로 실행해 입력·출력 행 수와 중복 처리 결과를 비교합니다. 오류가 나면 원인과 수정안을 검토합니다.",
     "확인한 코드와 사용 방법을 보관합니다. 운영 데이터나 실제 시스템 적용은 별도 검토와 승인 범위로 남깁니다."
    ]
   }
  };
  // ── 화면 ───────────────────────────────────────────────────────────────
  var TIER = {basic: '기본형', advanced: '고급형'};
  var PKG_NAME = {basic: '내 자료 AI 비서', advanced: '전문 제작 AI'};
  // 기업 컨설팅 설명으로 갈 때 넘기는 진입 출처(company-routes.js 의 SOURCES 와 같은 글자).
  var COMPANY_FROM = {study: 'T', summary: 'U', writing: 'W', image: 'G', code: 'C'};
  function i(name) { return P.icon(name); }
  function br(text) { return h(text).replace(/\n/g, '<br>'); }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function consultHref(t, pc) {
    return 'ai-consult.html?package=' + t.tier + '&amp;use=' + t.id + '&amp;intent=adoption&amp;pc=' + (pc === 'new' ? 'new' : 'existing');
  }
  function heading(number, label, title, side) {
    return '<div class="tg-heading"><div><p class="tg-eyebrow">' + number + ' · ' + h(label) + '</p><h2>' + title + '</h2></div>' +
      (side ? '<p class="tg-side">' + side + '</p>' : '') + '</div>';
  }
  function body(t) {
    var tier = TIER[t.tier];
    var tabs = t.variants.map(function (v, n) {
      return '<button type="button" role="tab" id="tg-tab-' + n + '" aria-controls="tg-result" aria-selected="' + (n === 0) + '" tabindex="' + (n === 0 ? 0 : -1) + '" data-tg-tab="' + n + '">' + h(v.name) + '</button>';
    }).join('');
    var flow = t.flow.map(function (s, n) {
      return '<li><button type="button" data-tg-step="' + n + '" aria-pressed="' + (n === 0) + '"' + (n === 0 ? ' class="is-active"' : '') + '><span class="tg-flow-count">' + pad(n + 1) + '</span><strong>' + h(s[0]) + '</strong><small>' + h(s[1]) + '</small></button>' + (n < t.flow.length - 1 ? i('arrow-right') : '') + '</li>';
    }).join('');
    var scope = t.setup.map(function (s, n) {
      return '<div class="tg-scope-item"><span class="tg-scope-number">0' + (n + 1) + '</span><h3>' + h(s[0]) + '</h3><p>' + h(s[1]) + '</p></div>';
    }).join('');
    var timeline = ['사용할 업무 확인', '자료·장비 시험', '범위·견적 합의', '설치·작업 설정', '함께 써보고 인계'].map(function (s, n, a) {
      return '<li><b>' + (n + 1) + '</b><span>' + h(s) + '</span>' + (n < a.length - 1 ? i('arrow-right') : '') + '</li>';
    }).join('');
    var faq = t.faq.map(function (q) { return '<details><summary>' + h(q[0]) + i('caret-right') + '</summary><p>' + h(q[1]) + '</p></details>'; }).join('');
    var prepare = t.prepare.map(function (x, n) { return '<li><span>' + (n + 1) + '</span>' + h(x) + '</li>'; }).join('');
    var files = t.files.map(function (f) { return '<div>' + i('file-text-duotone') + '<span>' + h(f) + '</span></div>'; }).join('');
    var source = t.source.map(function (s) { return '<div class="tg-source-excerpt"><h3>' + h(s.label) + '</h3><p>' + br(s.body) + '</p></div>'; }).join('');
    return '<div class="tg-page tg-' + h(t.id) + '" id="pop-task-guide" data-package="' + h(t.tier) + '" data-use="' + h(t.id) + '">' +
      '<article class="tg-article">' +
      // 업무 소개
      '<section class="tg-hero" aria-labelledby="tg-hero-title"><div class="tg-hero-copy"><p class="tg-eyebrow">' + tier + ' · ' + PKG_NAME[t.tier] + ' / ' + h(t.name) + '</p>' +
      '<h1 id="tg-hero-title">' + h(t.title[0]) + '<br>' + h(t.title[1]) + '</h1><p class="tg-hero-desc">' + br(t.desc) + '</p>' +
      '<div class="tg-hero-tags"><span>' + i('shield') + '로컬 실행 구성 목표</span><span>' + h(t.tag) + '</span></div>' +
      '<div class="tg-hero-actions"><a class="tg-primary" href="#tg-example">실제 사용 예시 보기 ' + i('arrow-right') + '</a><a class="tg-textlink" href="#tg-scope">우리가 해드리는 일 ' + i('caret-right') + '</a></div>' +
      '<p class="tg-hero-foot">PC 구성부터 설치·사용 안내까지, 내 작업에 맞춰 상담합니다.</p></div>' +
      '<figure class="tg-hero-art"><img src="assets/images/task-guides/' + h(t.id) + '.webp" width="1200" height="800" alt="' + h(t.name) + '를 표현한 미니어처 작업 공간"></figure></section>' +
      '<nav class="tg-section-nav" aria-label="상세 페이지 내용">' + [['tg-example', '업무 예시'], ['tg-workflow', '작업 흐름'], ['tg-scope', '설치·설정 범위'], ['tg-pc', 'PC 확인'], ['tg-consult', '도입 상담']].map(function (x) { return '<a href="#' + x[0] + '">' + x[1] + '</a>'; }).join('') + '</nav>' +
      // 01 가상 예시
      '<section class="tg-section" id="tg-example">' + heading('01', '이렇게 써요', br(t.intro), h(t.audience) + '<br><strong>' + h(t.outcome) + '</strong>으로 연결합니다.') +
      '<p class="tg-disclaimer">' + i('file-text-duotone') + '아래 자료·질문·결과는 이해를 돕는 가상 예시입니다. 실제 고객 자료나 현재 AI의 실행 결과가 아닙니다.</p>' +
      '<div class="tg-workspace"><div class="tg-input"><div class="tg-pane-label"><span class="tg-step-number">01</span><h3>내가 준비하는 것</h3></div><h4>' + h(t.example) + '</h4><div class="tg-files">' + files + '</div>' +
      '<div class="tg-prompt"><span>이렇게 요청해요</span><p>' + h(t.prompt) + '</p></div><button type="button" class="tg-source-button" data-tg-source aria-haspopup="dialog" aria-controls="tg-source-dialog">가상 원문 보기 ' + i('caret-right') + '</button></div>' +
      '<div class="tg-result"><div class="tg-pane-label"><span class="tg-step-number">02</span><h3>검토할 결과 예시</h3><span class="tg-draft">검토 전 초안</span></div>' +
      '<div class="tg-tabs" role="tablist" aria-label="예시 결과 형식">' + tabs + '</div>' +
      '<div class="tg-document" id="tg-result" role="tabpanel" aria-labelledby="tg-tab-0" tabindex="0"></div>' +
      '<div class="tg-review">' + i('shield') + '<div><strong>마지막 확인은 내가 합니다.</strong><p>' + h(t.review) + '</p></div></div></div></div></section>' +
      // 02 5단계 흐름
      '<section class="tg-section" id="tg-workflow">' + heading('02', '한눈에 보는 작업 흐름', '자료를 넣는 순간부터,<br>내가 쓸 결과가 될 때까지.', '각 단계를 눌러 역할을 확인하세요.<br>AI의 초안 다음에는 사람의 검토가 있습니다.') +
      '<ol class="tg-workflow">' + flow + '</ol><div class="tg-flow-detail" aria-live="polite"><span id="tg-flow-num">01</span><div><h3 id="tg-flow-title"></h3><p id="tg-flow-text"></p></div></div></section>' +
      // 로컬 실행 설명(조건부 -- 인터넷이 전혀 없다고 단정하지 않는다)
      '<section class="tg-local"><div><p class="tg-eyebrow">왜 내 PC에 구성하나요?</p><h2>내 자료와 작업 도구를,<br>내 환경에 맞춰 준비합니다.</h2></div><div class="tg-local-explainer"><p>쓸 장비·모델·자료·작업 양식과 사용 방법을 함께 맞추는 구성입니다. 매번 웹 서비스에 자료를 넣는 방식과 달리, 로컬 실행 환경을 먼저 준비합니다.</p>' +
      '<div class="tg-local-flow"><span>' + i('file-text-duotone') + '내 자료</span>' + i('arrow-right') + '<span>' + i('computer-tower') + '내 PC의 AI</span>' + i('arrow-right') + '<span>' + i('monitor') + '내 검토 화면</span></div>' +
      '<p class="tg-fineprint">외부 AI API를 쓰지 않는 구성을 목표로 합니다. 설치·모델 다운로드·업데이트와 일상 작업을 구분하고, 자료·질문·로그·백업의 실제 통신 경로를 점검한 뒤 내부 처리 범위를 확정합니다. 클라우드 AI를 쓰는 「AI로 PC 찾기」 상담과는 다른 서비스입니다.</p></div></section>' +
      // 03 구축·제외 범위
      '<section class="tg-section" id="tg-scope">' + heading('03', '팝콘AI가 해드리는 일', '설치만 하고 끝내지 않도록,<br>내 업무 기준으로 범위를 정합니다.') +
      '<div class="tg-scope-grid">' + scope + '</div><div class="tg-boundary"><strong>견적에서 함께 확정할 항목</strong><p>프로그램·모델과 이용 조건, 지원 파일·분량, 사용자·장비 수, 교육·초기 지원·유지보수 범위.</p><p>' + h(t.boundary) + '</p></div>' +
      '<div class="tg-timeline"><h3>도입은 이렇게 진행해요</h3><ol>' + timeline + '</ol></div></section>' +
      // 04 기존 PC / 새 PC
      '<section class="tg-section" id="tg-pc">' + heading('04', '어떤 PC가 필요할까요?', '지금 쓰는 PC부터,<br>가능한지 살펴볼게요.') +
      '<div class="tg-pc-layout"><div><p>' + h(t.hardware) + '</p><div class="tg-hardware" role="group" aria-label="사용할 PC"><button type="button" data-tg-pc="existing" aria-pressed="true">' + i('monitor') + '기존 PC 활용</button><button type="button" data-tg-pc="new" aria-pressed="false">' + i('computer-tower') + '새 PC도 검토</button></div>' +
      '<p class="tg-hardware-help" id="tg-hardware-help" aria-live="polite">현재 PC의 CPU·메모리·그래픽카드와 대표 작업을 먼저 확인합니다.</p></div>' +
      '<div class="tg-pc-empty">' + i('computer-tower') + '<h3>업무에 맞는 사양을 확인한 뒤 안내합니다.</h3><p>확인되지 않은 고가 PC를 대신 추천하지 않습니다.<br>장비 가격과 설치·설정 비용은 구분해 상담합니다.</p>' +
      '<a class="tg-outline" data-tg-consult href="' + consultHref(t, 'existing') + '">내 환경으로 상담하기 ' + i('arrow-right') + '</a></div></div></section>' +
      // FAQ
      '<section class="tg-section tg-faq"><p class="tg-eyebrow">미리 궁금할 수 있어요</p><h2>시작 전에 확인할 것</h2>' + faq + '</section>' +
      // 해당 업무 도입 상담
      '<section class="tg-consult" id="tg-consult"><div><p class="tg-eyebrow">' + tier + ' · ' + h(t.name) + '</p><h2>내 작업에 맞춰,<br>가능한 범위부터 알아보세요.</h2><p>자료 원본보다, 어떤 일을 하고 싶은지 먼저 알려주세요.</p>' +
      '<a class="tg-primary" data-tg-consult id="tg-consult-link" href="' + consultHref(t, 'existing') + '">이 업무로 설치 상담하기 ' + i('arrow-right') + '</a><small>상담 후 구성·제공 범위·비용을 안내합니다.</small>' +
      '<a class="tg-back text-link" href="ai-detail.html?package=' + h(t.tier) + '">' + tier + ' 패키지로 돌아가기</a></div>' +
      '<div class="tg-prepare"><h3>상담 전에 이것만 정리해 주세요</h3><ol>' + prepare + '</ol><p>상담 화면에 <strong>' + tier + ' · ' + h(t.name) + '</strong> 선택과 <strong id="tg-pc-choice">기존 PC 활용 우선</strong>을 이어갑니다. 이 화면을 본 것만으로 상담이 접수되거나 연락 동의가 되지 않습니다.</p></div></section>' +
      '<aside class="tg-company" id="company-link"><div><span>여러 담당자의 업무를 함께 바꾸고 싶다면</span><p>개인용 도구 구성과 회사 전체 업무 개선은 범위가 다릅니다.</p></div><a href="ai-company.html?from=' + COMPANY_FROM[t.id] + '">30인 이하 기업 컨설팅 ' + i('arrow-right') + '</a></aside>' +
      '</article>' +
      '<dialog class="tg-dialog" id="tg-source-dialog" aria-labelledby="tg-source-title"><div class="tg-dialog-inside"><button type="button" class="tg-dialog-close" data-tg-close aria-label="원문 닫기">' + i('x') + '</button>' +
      '<p class="tg-eyebrow">자료와 답변을 대조해요</p><h2 id="tg-source-title">가상 원문</h2><p class="tg-dialog-sub">설명을 위해 만든 샘플이며 실제 고객 문서가 아닙니다.</p>' + source +
      '<button type="button" class="tg-primary" data-tg-close>예시로 돌아가기</button></div></dialog>' +
      '</div>';
  }
  function mount(t) {
    var root = document.getElementById('pop-task-guide');
    if (!root) return;
    var q = function (sel) { return root.querySelector(sel); };
    var each = function (sel, fn) { Array.prototype.forEach.call(root.querySelectorAll(sel), fn); };
    var variant = 0, step = 0, pc = 'existing', opener = null;
    function renderVariant() {
      var v = t.variants[variant];
      each('[data-tg-tab]', function (b) { var on = Number(b.dataset.tgTab) === variant; b.setAttribute('aria-selected', String(on)); b.tabIndex = on ? 0 : -1; });
      var doc = q('#tg-result');
      doc.setAttribute('aria-labelledby', 'tg-tab-' + variant);
      doc.innerHTML = '<h4>' + h(v.heading) + '</h4><ol>' + v.bullets.map(function (b, n) { return '<li><span>' + pad(n + 1) + '</span><p>' + h(b) + '</p></li>'; }).join('') + '</ol><p class="tg-reference">' + i('file-text-duotone') + h(v.ref) + '</p>';
    }
    function renderStep() {
      each('[data-tg-step]', function (b) { var on = Number(b.dataset.tgStep) === step; b.setAttribute('aria-pressed', String(on)); b.classList.toggle('is-active', on); });
      q('#tg-flow-num').textContent = pad(step + 1);
      q('#tg-flow-title').textContent = t.flow[step][0];
      q('#tg-flow-text').textContent = t.flowDetails[step];
    }
    function renderPc() {
      each('[data-tg-pc]', function (b) { b.setAttribute('aria-pressed', String(b.dataset.tgPc === pc)); });
      q('#tg-hardware-help').textContent = pc === 'existing' ? '현재 PC의 CPU·메모리·그래픽카드와 대표 작업을 먼저 확인합니다.' : '대표 작업으로 적합성이 확인된 실제 판매 상품만 후보로 연결합니다.';
      q('#tg-pc-choice').textContent = pc === 'existing' ? '기존 PC 활용 우선' : '새 PC도 검토';
      each('[data-tg-consult]', function (a) { a.setAttribute('href', consultHref(t, pc).replace(/&amp;/g, '&')); });
    }
    root.addEventListener('click', function (e) {
      var b = e.target.closest('[data-tg-tab],[data-tg-step],[data-tg-pc],[data-tg-source],[data-tg-close]');
      if (!b || !root.contains(b)) return;
      if (b.hasAttribute('data-tg-tab')) { variant = Number(b.dataset.tgTab); renderVariant(); }
      else if (b.hasAttribute('data-tg-step')) { step = Number(b.dataset.tgStep); renderStep(); }
      else if (b.hasAttribute('data-tg-pc')) { pc = b.dataset.tgPc === 'new' ? 'new' : 'existing'; renderPc(); }
      else if (b.hasAttribute('data-tg-source')) { var d = q('#tg-source-dialog'); opener = b; if (d.showModal) d.showModal(); else d.setAttribute('open', ''); var c = d.querySelector('[data-tg-close]'); if (c) c.focus(); }
      else if (b.hasAttribute('data-tg-close')) { q('#tg-source-dialog').close(); }
    });
    // 결과 탭 키보드: ←/→/Home/End 로 옮기고 초점을 따라간다(roving tabindex).
    q('.tg-tabs').addEventListener('keydown', function (e) {
      var keys = {ArrowLeft: -1, ArrowRight: 1, Home: 'first', End: 'last'};
      if (!(e.key in keys)) return;
      e.preventDefault();
      var n = t.variants.length, k = keys[e.key];
      variant = k === 'first' ? 0 : k === 'last' ? n - 1 : (variant + k + n) % n;
      renderVariant();
      var tab = q('#tg-tab-' + variant); if (tab) tab.focus();
    });
    var dialog = q('#tg-source-dialog');
    dialog.addEventListener('close', function () { if (opener) opener.focus(); });   // Esc·닫기 뒤 원문 버튼으로 초점 복귀
    dialog.addEventListener('click', function (e) { if (e.target === dialog) dialog.close(); });   // 바깥(배경) 누르면 닫기
    renderVariant(); renderStep(); renderPc();
  }
  P.serviceGuides = P.serviceGuides || {};
  Object.keys(TASKS).forEach(function (key) {
    var t = TASKS[key];
    P.serviceGuides[key] = {label: t.name, title: t.name + ' · ' + TIER[t.tier] + ' 로컬 AI | 팝콘AI', ownCompanyLink: true,
      body: function () { return body(t); }, mount: function () { mount(t); }};
  });
}());
