/* ASUS AI PC 기획전 v4 화면 데이터 (2026-11-05). 카드·상단·전체표가 이 파일 하나를 읽어 표기가 어긋나지 않게 한다.
 *
 * 원천: 보완전달서_v4 > 팝콘PC_판매중가격확인_20261105 > 한국어_화면문구_정리_v2 > 개발전달서 v3.
 * API·DB를 읽지 않는 정적 자료다. 가격은 2026-11-05 관리자 상품목록을 읽기 전용으로 조회한 값이며 실시간 값이 아니다.
 * plan = 기획 검토가(ASUS 협의 전). 판매가·소비자가 합계가 아니므로 부품 가격과 더하지 않는다.
 * no = 몰 상품번호(대조용, 화면에 쓰지 않는다). 품절·단종·0원은 넣지 않는다.
 * 넣지 않은 값: v3의 케이스·쿨러 참고가(판매중 가격 아님), 5080·5090·PRIME 쿨러의 과거 등록가.
 *
 * state: sale      판매중 확인
 *        candidate 판매중 확인 · 최종 모델 미확정
 *        check     판매중이나 세대·규격·표기 확인 필요
 *        conflict  자료 불일치, 확인 전 확정 불가
 *        supply    판매중 동일 상품 미확인, 공급 확인 필요
 *        separate  별도 문의, 가격 미표시
 */
(function () {
  'use strict';
  var P = window.PAI = window.PAI || {};

  var STATES = {
    sale: '판매중 확인',
    candidate: '구성 후보',
    check: '확인 필요',
    conflict: '자료 확인 전 확정 불가',
    supply: '공급 확인 필요',
    separate: '별도 문의'
  };

  function opt(name, state, price, premium, note, no) {
    return { name: name, state: state, price: price || null, premium: premium || null, note: note || '', no: no || null };
  }

  var CASE = { label: '케이스', head: 'ASUS TUF Gaming GT502 BLACK', status: 'candidate', options: [
    opt('ASUS TUF Gaming GT502 BLACK', 'candidate', 206300, 201140, '3종 공통 케이스 후보. 일반 GT502이며 Horizon 모델이 아닙니다.', 126548)
  ] };
  var COOLER = { label: 'CPU 쿨러', head: 'ASUS PRIME LC 360 ARGB', status: 'supply', options: [
    opt('ASUS PRIME LC 360 ARGB', 'supply', null, null, '판매중 동일 상품을 확인하지 못해 가격을 표시하지 않습니다.')
  ] };
  var FAN = { label: '추가 시스템팬', head: '포함 여부 확인 필요', status: 'check', options: [
    opt('제품·수량·비용 미정', 'check', null, null, '견적 단계에서 포함 여부를 별도로 확인합니다.')
  ] };
  var OS = { label: '운영체제', head: '정품 Windows 별도', status: 'separate', options: [
    opt('정품 Windows', 'separate', null, null, '구성 금액에 포함하지 않으며 별도 문의입니다.')
  ] };
  var SSD = { label: 'SSD(저장장치)', head: '2TB NVMe', status: 'candidate', options: [
    opt('BIWIN M350 M.2 NVMe 2TB', 'candidate', 405000, 394880, '조회한 판매중 NVMe 2TB 중 낮은 표시가. 최종 모델 미확정.', 128452),
    opt('마이크론 Crucial E100 NVMe 2TB', 'candidate', 405600, 395460, '대안', 127681),
    opt('ESSENCORE KLEVV C910G NVMe 2TB', 'candidate', 439200, 428220, 'TLC 표기 대안', 128441)
  ] };
  var RAM64 = { label: '메모리(RAM)', head: '64GB DDR5', status: 'check', options: [
    opt('삼성 DDR5-5600 64GB [32G×2]', 'candidate', 1611000, 1570730, '비교 후보', 113590),
    opt('TeamGroup DDR5-5600 CL46 Elite 64GB [32G×2]', 'conflict', 1525400, 1487270, '제목은 64GB, 사양 표기는 16GB/1EA로 서로 다릅니다.', 127181)
  ] };
  var CPU_9950X = { label: 'CPU(중앙처리장치)', head: 'Ryzen 9 9950X', status: 'candidate', options: [
    opt('Ryzen 9 9950X 벌크', 'candidate', 667200, 650520, '벌크 상품으로 정품 BOX와 패키지가 다릅니다.', 124310)
  ] };
  var BOARD_B850 = { label: '메인보드', head: 'ASUS TUF B850 계열 구성 후보', status: 'candidate', options: [
    opt('ASUS TUF Gaming B850-PLUS WIFI 인텍', 'candidate', 297700, 290260, 'ATX 구성 후보', 123726),
    opt('ASUS TUF Gaming B850M-E WIFI 인텍', 'candidate', 219000, 213530, 'mATX 대안. 위 ATX 후보와 다른 상품입니다.', 130987)
  ] };

  var GPU_NOTE_SUPPLY = '조회한 등록 상품이 품절이라 과거 등록가를 표시하지 않습니다.';

  var MODELS = [
    {
      id: 'business',
      name: '문서·업무용 PC',
      tagline: '문서를 찾고 정리하는 일을 더 편하게.',
      tone: 'blue',
      plan: 3990000,
      gpu: 'ASUS PRIME RTX 5070 Ti 16GB',
      gpuStatus: 'candidate',
      vram: '16GB',
      cpu: 'Ryzen 9 9900X',
      ram: '64GB DDR5',
      ssd: '2TB NVMe',
      forWho: ['문서를 많이 다루는 분', '고객 문의를 담당하는 분', '개인 업무에 AI를 써 보고 싶은 분'],
      whoIcons: ['file-text', 'headset', 'user'],
      inquiry: { package: 'business', use: 'documents' },
      uses: [
        { title: '문서에서 필요한 내용 찾기', text: '매뉴얼과 제품 자료를 검색하고, 원문을 확인합니다.', example: '질문 예시: 이 제품의 보증 제외 조건을 찾아줘.', steps: ['문서 준비', '질문', '원문 확인'], image: 'use-business-1.webp', alt: '문서 검색 화면을 띄운 모니터' },
        { title: '회의 내용과 할 일 정리하기', text: '녹취와 메모를 바탕으로 결정 사항과 담당자별 할 일을 정리합니다.', steps: ['녹음·메모 준비', '글로 변환', '요약', '내용 확인'], image: 'use-business-2.webp', alt: '음성 파형을 띄운 모니터' },
        { title: '고객 문의 분류하고 답변 초안 쓰기', text: '문의 종류를 나누고, 회사 안내에 맞는 답변 초안을 작성합니다. 담당자가 확인한 뒤 보냅니다.', steps: ['문의 분류', '답변 작성', '담당자 확인'], image: 'use-business-3.webp', alt: '문의 목록을 띄운 모니터' }
      ],
      prepare: '문서 검색·음성 인식 프로그램 설치와 자료 정리가 필요합니다.',
      parts: [
        { label: 'CPU(중앙처리장치)', head: 'Ryzen 9 9900X', status: 'candidate', options: [
          opt('Ryzen 9 9900X 멀티팩 정품', 'candidate', 610800, 595530, '', 121803)
        ] },
        { label: 'GPU(그래픽카드)', head: 'ASUS PRIME RTX 5070 Ti 16GB', status: 'candidate', options: [
          opt('ASUS PRIME RTX 5070 Ti 16GB 코잇', 'candidate', 2179000, 2124530, '비OC 후보', 130847),
          opt('ASUS PRIME RTX 5070 Ti OC 16GB 코잇', 'candidate', 2100300, 2047790, 'OC 후보. 비OC와 다른 상품입니다.', 129630)
        ] },
        { label: '그래픽 메모리', head: '16GB', status: 'plain', options: [] },
        RAM64,
        SSD,
        BOARD_B850,
        { label: '파워(PSU)', head: 'ASUS 850W 이상 구성 후보', status: 'check', options: [
          opt('ASUS ROG STRIX 850G', 'check', 161200, 157170, '세대·16핀 케이블 확인 전에는 선정하지 않습니다.', 108213),
          opt('ASUS ROG STRIX 850W Platinum 인텍', 'check', 341000, 332480, '12V2x6 표기가 있는 대안', 130851)
        ] },
        CASE, COOLER, FAN, OS
      ]
    },
    {
      id: 'video',
      name: '영상·디자인용 PC',
      tagline: '영상 편집과 이미지 작업을 한 PC에서.',
      tone: 'violet',
      plan: 5990000,
      gpu: 'ASUS PRIME RTX 5080 16GB',
      gpuStatus: 'supply',
      vram: '16GB',
      cpu: 'Ryzen 9 9950X',
      ram: '64GB DDR5',
      ssd: '2TB NVMe',
      forWho: ['영상 편집자', '강의·인터뷰 제작자', '홍보 이미지 제작자'],
      whoIcons: ['video-camera', 'users', 'image'],
      inquiry: { package: 'advanced', use: 'image' },
      uses: [
        { title: '영상 편집하고 저장하기', text: '영상을 편집하고 색감·효과를 조정한 뒤 원하는 형식으로 저장합니다.', steps: ['영상 준비', '편집·보정', '확인', '저장'], image: 'use-video-1.webp', alt: '영상 편집 프로그램을 띄운 모니터' },
        { title: '음성을 글로 바꾸고 자막 만들기', text: '인터뷰와 강의를 받아쓰고, 틀린 부분을 고쳐 자막으로 만듭니다.', steps: ['음성 추출', '받아쓰기', '자막 수정'], image: 'use-video-2.webp', alt: '음성 파형과 자막을 띄운 모니터' },
        { title: '썸네일과 이미지 만들기', text: '원하는 분위기의 시안을 만들고 필요한 부분을 수정합니다.', steps: ['작업 방향 정하기', '이미지 생성·보정', '최종 편집'], image: 'use-video-3.webp', alt: '이미지 편집 프로그램을 띄운 모니터' }
      ],
      prepare: '편집 프로그램과 AI 도구는 별도 설치가 필요합니다. 유료 프로그램 이용료는 별도입니다.',
      parts: [
        CPU_9950X,
        { label: 'GPU(그래픽카드)', head: 'ASUS PRIME RTX 5080 16GB', status: 'supply', options: [
          opt('ASUS PRIME RTX 5080 16GB', 'supply', null, null, GPU_NOTE_SUPPLY)
        ] },
        { label: '그래픽 메모리', head: '16GB', status: 'plain', options: [] },
        RAM64,
        SSD,
        BOARD_B850,
        { label: '파워(PSU)', head: 'ASUS 1000W급 구성 후보', status: 'check', options: [
          opt('ASUS TUF Gaming 1000W GOLD', 'check', 260700, 254180, '정확한 세대·케이블 확인 필요', 122070)
        ] },
        CASE, COOLER, FAN, OS
      ]
    },
    {
      id: 'local-ai',
      name: '로컬 AI 개발용 PC',
      tagline: 'AI 모델을 직접 실행하고 시험해 보세요.',
      tone: 'teal',
      plan: 12990000,
      gpu: 'ASUS TUF RTX 5090 32GB',
      gpuStatus: 'supply',
      vram: '32GB',
      cpu: 'Ryzen 9 9950X',
      ram: '128GB DDR5',
      ssd: '2TB NVMe',
      forWho: ['AI 모델을 직접 시험하는 개발자', '회사에 AI 도입을 검토하는 담당자', 'AI 연구·실험을 하는 분'],
      whoIcons: ['code', 'users', 'cpu'],
      inquiry: { package: 'advanced', use: 'code' },
      explain: '인터넷 서비스에 질문하는 방식과 달리, 내 PC에서 AI 모델을 실행하는 방식입니다. 사용하는 프로그램에 따라 인터넷 연결이 필요할 수 있습니다.',
      limit: '모든 AI 모델이 실행되는 것은 아닙니다. 모델 크기와 설정에 맞춰 확인해야 합니다.',
      uses: [
        { title: '회사 문서에서 답 찾기', text: '회사 자료를 검색하고, 근거 문서와 함께 내용을 확인합니다.', steps: ['문서 준비', '검색 환경 설정', '질문', '출처 확인'], image: 'use-ai-1.webp', alt: '문서 검색 결과를 띄운 모니터' },
        { title: 'AI 모델 실행하고 결과 비교하기', text: '모델과 실행 프로그램을 선택하고, 같은 질문으로 결과를 비교합니다.', steps: ['모델 선택', '프로그램 설치', '실행', '결과 비교'], image: 'use-ai-2.webp', alt: '두 모델을 나란히 비교한 예시 화면' },
        { title: '반복 업무에 AI 연결하기', text: '문의 분류·정보 추출·답변 작성을 기존 업무 도구와 연결합니다. 연결 설정과 담당자 확인 절차가 필요합니다.', steps: ['문의 접수', 'AI 분류', '초안 작성', '담당자 확인'], image: 'use-ai-3.webp', alt: '문서에서 AI를 거쳐 설정으로 이어지는 흐름 화면' }
      ],
      parts: [
        CPU_9950X,
        { label: 'GPU(그래픽카드)', head: 'ASUS TUF RTX 5090 32GB', status: 'supply', options: [
          opt('ASUS TUF RTX 5090 32GB', 'supply', null, null, GPU_NOTE_SUPPLY)
        ] },
        { label: '그래픽 메모리', head: '32GB', status: 'plain', options: [] },
        { label: '메모리(RAM)', head: '128GB DDR5', status: 'check', options: [
          opt('삼성 DDR5-5600 128GB [32G×4]', 'check', 3223700, 3143110, '비교 후보. 4개 장착 시 동작 속도·QVL 확인 필요.', 113591),
          opt('TeamGroup DDR5-5600 CL46 Elite 128GB [32G×4]', 'conflict', 3050900, 2974630, '제목은 128GB, 사양 표기는 16GB/1EA로 서로 다릅니다.', 127182),
          opt('킹스톤 DDR5-5600 CL46 128GB [64G×2]', 'check', 3490200, 3402950, '2개 구성 대안. 단품·세트 표기 확인 필요.', 130703)
        ] },
        SSD,
        { label: '메인보드', head: 'ASUS ProArt X870E 계열 구성 후보', status: 'candidate', options: [
          opt('ASUS ProArt X870E-CREATOR WIFI 대원', 'candidate', 778000, 758550, '', 122148)
        ] },
        { label: '파워(PSU)', head: 'ASUS 1200W급 구성 후보', status: 'check', options: [
          opt('ASUS ROG STRIX 1200W Platinum', 'check', 348000, 339300, '정확한 모델·전원 커넥터 확인 필요', 128514)
        ] },
        CASE, COOLER, FAN, OS
      ]
    }
  ];

  P.asus = {
    STATES: STATES,
    MODELS: MODELS,
    HEADLINE: 'ASUS의 강력한 성능, 나의 AI 작업실.',
    INTRO: '문서 정리부터 영상 편집, 내 PC에서 AI 실행까지.',
    FIELDS: ['내 PC에서 AI 실행', '영상 편집·제작', '반복 업무 줄이기'],
    PROCESS: ['용도 상담', '구성 검토', 'ASUS 가격 확정'],
    PLAN_LABEL: '기획 검토가 · ASUS 협의 전',
    PLAN_NOTE: '아직 판매 가격이 정해지지 않았습니다.',
    PERFORMANCE: '사용 프로그램과 AI 모델, 설정에 따라 결과가 달라집니다.',
    PHOTO_NOTE: '사용 예시 / 실제 판매 제품과 다를 수 있습니다.',
    CASE_NAME: 'ASUS TUF Gaming GT502 BLACK',
    BUILD_NOTE: '제품 이미지는 연출이며 실제 구성과 다를 수 있습니다.',
    LIGHT_NOTE: '내부 부품 없는 케이스 연출입니다. 푸른 빛은 외부 조명으로, RGB 부품 포함을 뜻하지 않습니다.',
    FOOTNOTE: '디자인 시안 · 제품 이미지는 연출 · 최종 가격 ASUS 협의 후 확정 · Windows 별도',
    PRICE_BASIS: '2026-11-05 관리자 상품목록을 읽기 전용으로 조회한 판매중 상품의 표시가입니다. 품절·단종·0원 상품은 제외했으며, 조회한 범위의 낮은 후보일 뿐 시장 전체 최저가가 아닙니다.',
    PRICE_MEMBER: '일반회원가와 프리미엄 표시가는 적용 조건이 다르며, 회원 조건과 실제 상품 화면 적용가는 재확인이 필요합니다. 판매중 표시는 재고나 즉시 출고를 보장하지 않습니다. 배송비·조립비·부가 옵션은 포함하지 않았습니다.',
    TOTAL_NOTE: '5080·5090·PRIME 쿨러 공급, 메모리 자료 불일치, 팬·조립·검수·배송비·운영체제가 정리되지 않아 전체 합계를 표시하지 않습니다. 기획 검토가는 부품 합계가 아닙니다.',
    COMPAT: '표기 치수상 GT502 범위 안의 후보입니다(그래픽카드 최대 400mm, 상단 360mm 라디에이터, 파워 최대 200mm). 전원 커넥터 굽힘·유리 패널 여유·라디에이터와 메모리 간섭은 실제 조립 확인 전이라 호환 완료가 아닙니다.',
    INSTALL: [
      { icon: 'computer-tower', title: '본체 조립·검수', text: '부품 조립과 기본 검수 범위는 판매 조건이 정해지면 안내합니다.' },
      { icon: 'gear', title: '프로그램 설치·사용 안내', text: '프로그램 설치와 사용 안내는 별도 문의해 주세요. Windows, AI 프로그램 설치, 문서 검색 설정, 업무 도구 연결, 교육 비용도 별도 문의입니다.' }
    ],
    SALE_NOTES: ['정확한 부품과 호환성, 가격은 공급 조건과 테스트 후 정합니다.', '배송·AS 접수처·지원 기간은 확정된 내용만 표시합니다.'],
    find: function (id) {
      for (var i = 0; i < MODELS.length; i += 1) if (MODELS[i].id === id) return MODELS[i];
      return null;
    },
    detailHref: function (id) { return 'asus-pc.html?model=' + encodeURIComponent(id); },
    inquiryHref: function (id) { return 'asus-consult.html?model=' + encodeURIComponent(id); },
    image: function (file) { return 'assets/images/asus/' + file; },
    won: function (value) { return Number(value).toLocaleString('ko-KR') + '원'; }
  };
}());
