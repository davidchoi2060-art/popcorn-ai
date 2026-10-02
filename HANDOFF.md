# 최신 인계 · 2026-10-02 대표 이미지 실생성·클라우드·선택 검증 완료

사용자가 콘솔에서 VM Storage 읽기·쓰기 범위를 적용하고 시작했다. gcloud VM RUNNING/devstorage.read_write 및 health HTTP200 확인. 추가 유료1장 재생성 명시 승인 후 N07 생성 job 4fd70b96-2e26-4621-8f6a-0ab6ad641c24 완료, private GCS popcorn-ai-product-media-045e861b/pc-configurations/4fd70b96-2e26-4621-8f6a-0ab6ad641c24/representative.png 저장, 대표 선택 완료. 실제 DB ready/complete/selected=true/staged_png NULL 확인. GCS 원본 다운로드 SHA256 30a10a64e3f0ac4e968c7bcab0acf4b10290959af14d6e8eebe846e5b40a318a가 DB와 일치. 운영 목록/요약/전체 구성 보기에서 AI 조립 예시 표시 및 이미지 naturalWidth1024 확인. 이번 유료호출1회, 누적 실제 생성2회(첫 회 저장 실패 기록은 보존). 과거 실패 원본은 복구되지 않았으며 새 작업으로 대체했다. BOM·가격·추천 승인 변경 없음. 이미지 운영 기능 실검증 완료, 영상 생성 API 연결은 별도 후속. 로컬 증빙 outputs/admin-new-pc-design-20261001/16-media-selected-live.png,17-detail-selected-image.png,N07-representative.png(채팅 작업폴더).
# 최신 인계 · 2026-10-02 실제 이미지 1회 시험과 원본 보존 보완

서버 복구 후 IAM 사전검사가 true여서 사용자 승인된 대표 N07 이미지1회 생성 실행. job 989f0bcd-4c28-465c-be76-3a3738462964는 생성 단계 성공 후 클라우드 저장 실패. 원본 조회도 불가하며 추가 유료 재생성은 하지 않았다. 사전검사가 VM OAuth 조회전용 범위를 놓치는 문제 수정(3db4327, 배포36954428680 성공). 현재 VM은 read_only 유지이므로 생성/저장 재시도 버튼 비활성화. 임시파일 원본은 배포/재시작 지속성을 보장하지 못해 0121 staged_png에 원본을 저장하고 클라우드 성공 후 제거하는 방식으로 개선(267a511). PC133검사, 실제DB 실패→원본보존→유료호출 없이 저장재시도→성공 후 임시원본 제거 전량롤백 통과. 이 정정은 이전 기록의 실유료0회/원본 보유 표현을 대체한다. 현재까지 실제 유료 생성 요청은1회, 성공 클라우드 업로드/대표 선택은0회. 콘솔에서 Storage 읽기·쓰기 설정 후 실저장 검증은 미완료.

# 최신 인계 · 2026-10-02 클라우드 권한 일부 적용 및 서버 복구

사용자 승인 후 기존 이미지 버킷에 서버 계정 objectCreator 추가 완료(objectViewer 유지). VM 중지 후 Storage 범위를 read_write로 바꾸는 명령이 실행 도구의 자동 승인 심사에서 차단됨. 추가 차단 이유는 제공되지 않았다. 기존 설정 그대로 VM을 다시 시작했고 RUNNING, /api/health HTTP200 ok=true, 인증 관리자 화면 조회를 확인했다. 현재 VM Storage 범위는 read_only 유지, 이미지 생성은 비활성이고 실유료 생성/업로드는 실행하지 않았다. Google Cloud 콘솔 직접 변경 후 대표1개 실검증이 남았다. 변경 전 설정은 작업폴더 vm-before-media.json 및 bucket-before-media.json에 보관. 사용자 승인은 이미 받았으므로 같은 승인 질문을 반복하지 않는다.

# 최신 인계 · 2026-10-02 대표 이미지 연결

## 2026-10-02 대표 이미지 운영 기능
승인한 대표이미지 기능을 /admin2/pc-media?id=제품ID에 연결했다. 기존 제품군 작업공간/상세에서 진입. 전체 BOM과 현재 호환규칙·부품 원문/판매 상태, 케이스 사진·장착 쿨러 확인 후 운영자 버튼으로 1장 생성한다. 기존 GEMINI_API_KEY 및 google-genai 사용, PC_IMAGE_MODEL 기본 gemini-3.1-flash-image(공식 https://ai.google.dev/gemini-api/docs/generate-content/image-generation 확인). 기존 private product media bucket을 재사용하고 서버 ADC의 create/get 권한 사전 확인. 자동 유료호출/모델폴백 없음. 작업은 새 pc_media_jobs(0120)에 기록하며 BOM·가격·설명·revision·추천 승인은 변경하지 않는다. 요청UUID 재요청/진행중 중복 차단, 작업 중단 가능 표기, 실패 재생성 자동 실행 없음. 클라우드 저장 실패는 서버 임시 원본으로 저장만 재시도한다(서버 임시파일 유실 시 새 생성 필요). 대표선택은 현재 시각구성 해시 일치 필수. 구성·사진·냉각 정보가 바뀌면 이전 이미지가 목록/상세 대표에서 빠지고 관리화면에서 변경 안내, 가격만 변경되면 시각기준 유지. AI 조립 예시 표시. 이미지 작업/선택은 기존 추천승인 무효화 없음. 영상은 후속.
검사132개, 기존 Node2개, 실제 DB 등록/중복/선택/목록·상세/수량변경 무효화 전량롤백 통과. provider/cloud는 시험에서 대체했고 유료 생성0회. 운영 배포0dd6a9e/run36909271195 및 공통LNB스타일5f02769/run36909671645 success. 인증된 N07 운영UI 실제8부품/케이스사진/공랭/생성조건 표시 확인. 클라우드 업로드는 미활성: VM popcorn-app storage.read_only scope 및 기존 버킷 계정 objectViewer 실설정 확인. 버킷 objectCreator 추가+VM Storage read_write 범위 변경과 서버중지/재시작에 대해 사용자에게 명시 확인 요청 중이며 아직 수행하지 않음. API키 설정은 운영UI에서 확인됨. 실유료 생성/클라우드업로드/대표선택은 미실시.

# 최신 인계 · 2026-10-02 신규 조립PC 생성 구현

`/admin2/pc-builder`: 실제 판매 DB/DB 재고 부품 선택, 빈 BOM/수량, 기본쿨러·내장그래픽 근거, 현재 호환규칙 검사, 현재 판매가 + 조립비 30,000원, 동일 BOM 차단, 검토 대기 저장/작업 공간 이동. 기존 제품군·설명·검토 원천 재사용, DDL 없음. 이미지·영상 생성 API/클라우드 업로드는 후속이며 localhost8785는 디자인 시안. PC 검사127개, 기존 Node2개, 실제 DB 신규저장/중복/재시도/가격변경 차단 전량 롤백 통과. 배포 run36896742537 및 조립 확인 안내 보완 run36897288633 성공. 운영 로그인 UI 실제8부품 선택·조립비·N07 중복 저장 차단·SSD3개 수량/금액/장착 확인 안내 표시 확인. 운영 화면 시험 저장은 하지 않았음. 실상품 신규 등록/추천 승인은 시험에서 남기지 않았음.

# 최신 인계 · 신규PC/이미지 생성 시안

2026-10-01 사용자 승인: 신규PC 빈BOM 생성 + 대표이미지. 비용정정: 전체 부품 구성 완료와 최신 호환성 검사 완료 이후 운영자 버튼으로만 이미지생성. localhost8785 클릭시안 작성, 실제 N07 부품 DB읽기 표본과 기존 예시이미지, 운영저장/API연결없음. 디자인 docs/design/admin-new-pc-builder-20261001.md, 로컬 outputs/admin-new-pc-design-20261001. 다음: 신규BOM API/검사/가격/임시구성/이미지작업/검토등록 연결.

# 최신 인계 · 2026-10-01 AI 일괄 보완 구현

`/admin2/pc-batch`: 실제 DB 공통부품/보완사유 묶음, 최대10개 제품별 기존 task.ops_assist LLM 제안, 항목 선택/비교/재생성, 선택 설명 일괄 저장. 각 제품 revision와 검토 basis 재대조, 충돌별 결과, 기존 설명 이력/검토 무효화 재사용. BOM·가격·승인 자동변경 없음. PC unittest115개, 기존Node2개, 실제DB 2제품 부분성공/충돌/재저장차단/BOM가격유지 시험 통과·전량롤백. 운영 배포 run36852920069 성공, 인증된 UI 실제105개 조회·2제품 실제Gemini제안·항목선택·저장전확인 완료. 실제 설명 저장은 미수행. 신규 조립PC 빈BOM 생성은 다음 필수 기능.

# HANDOFF — 2026-09-29 관리자 제품군 화면 추가

## 최신 인계 · 2026-10-01 AI일괄보완 시안 / 신규생성 필수

사용자승인범위에따라 일괄보완 대상선택→제안비교→저장확인 클릭시안을 outputs/admin-ai-batch-design-20261001에 준비. http://127.0.0.1:8784/는 실제105개DB스냅샷 읽기 시안이며 LLM/저장없음. 운영구현후속. 사용자명시추가: 보유부품으로 운영자가 빈구성에서 신규조립PC제품군생성 기능 필수. 기존PC수정→새저장으로대체하지말것. 상세 docs/design/admin-ai-batch-plan-20261001.md / 중앙결정 popcorn-admin-new-pc-builder-required-20261001. 관리자개편마무리전 리마인드 heartbeat ai-pc ACTIVE(변화없는경우조용히).

## 최신 인계 · 2026-10-01 관리자 AI 흐름 재검증

대표 듀얼 SSD/일반 N07/제외 P119302의 실제 AI 제안3회 및 저장·이력·검토 전환은 실DB에서 전량 롤백 검증했다. 종료 후 상품/revision/이력 불변. 시험 승인도 남기지 않았다. 운영 로그인 UI에서 Gemini 실제 생성·선택 적용·되돌리기 확인. 검토 모달 재귀 이벤트 오류와 AI초안의 잘못된 저장 배너 발견/수정, 코드 dd37d60·배포 run36849074699 성공. 운영 화면에서 검토 탭 직접 열기·설명 탭 전환·N07자료8개조회·저장배너없음 재확인. 상세 docs/design/admin-ai-workspace-flow-20261001.md. 자료찾기는 기존등록근거만, 외부웹/일괄AI후속. 남은 편집기 검토 문구도 동일하게 정정.

## 최신 인계 · 2026-10-01 관리자 AI 작업 공간

사용자 승인 AI 결합 시안을 `/admin2/pc-workspace`에 구현·배포. 코드 `8e88b48`, 배포 run `36843318444` 성공. 기존 관리자 메뉴에 '처리할 일 · AI 도움' 추가, 새 작업 공간은 간결한 중앙 메뉴·실제 DB 작업 목록·설명 편집·AI 제안 비교/선택 적용/되돌리기·기존 상세/검토/이력 연결. 실제 LLM 기존 task.ops_assist 라우팅으로 Gemini 호출1회 성공(log1574), 상품 저장·검토 승인 없음. 자료 찾기는 등록된 근거 조회이며 외부 웹 검색은 미구현. 설명 작성 여부와 부품 변경 후 검토 필요를 분리. PC unittest112개, 실제105개 DB 읽기 및 API 오류·권한·불변 테스트, 로컬 브라우저 선택 적용·되돌리기 확인. 배포 후 health 정상·라우터 등록·JS정본 일치·미인증API401 확인; 운영 로그인 UI는 계정 전환 후 미확인. 상세 `docs/design/admin-ai-workspace-20261001.md`, 로컬 근거 `outputs/admin-ai-workspace-20261001/`. 스키마/BOM/가격/승인 데이터 변경 없음. 기존 개편 별도 스레드의 '시안 선택 대기'는 사용자 승인 및 이번 구현으로 해소. 게임·AI 자료 준비는 별도 미완료이며 docs/design/data/ 조사 순위가 미추적 상태로 남아 있음.

- 2026-10-01 관리자 운영 보완: 내장그래픽 신규 4개 검사 적용 오류와 목록/상세 승인 근거 불일치 수정. 현재 후보 52/조건부 46/보완 5/제외 1. 공통 보완 사유 묶음 및 가격·판매 DB 변경 알림/필터/엑셀 추가. 103개 검사와 실제 DB 롤백 통합 검사 통과, 영구 DB 데이터 변경 없음. 상세 `docs/design/admin-pc-operations-20261001.md`. 코드 eebc4d4 / 배포 run36810266418 성공, 인증된 서버 UI의 분류·공통 보완 링크·가격 대조 확인.

## 최신 인계 · 2026-09-30

- 표시·검색 개선 배포 확인: `4522946`, run `36691473245` 성공. 서버 변경 JS/CSS 일치. 동작 검증은 실제DB 읽기전용 로컬 기준, 운영 인증 UI 재조작은 이번 미실시.

- 제품군 표시·검색 개선: 10/20/30개 선택을 이 브라우저에 영속 저장하고 위·아래 선택기를 동기화했다. 검색은 여러 단어 AND/순서 무관, 모델명 정규화, 구성 부품명·코드 및 RAM/SSD 용량 별칭까지 확장했다. 최근 검색5개와 같은 탭의 검색조건 복원, 검색어만 지우기/조건 초기화 분리. 조건 초기화는 표시 개수를 유지하며 엑셀은 마지막 조회 성공 조건을 사용한다. 관련37검사와 실제DB 로컬 UI 재방문·초기화·검색 검증. 상세 docs/design/admin-catalog-search-20260930.md.

- 관리자 마무리 배포: main `12f424c`, run `36689863214` 성공. 서버 변경 JS 3개·CSS 1개 내용 일치 확인. 로컬 화면·엑셀 검증 완료, 배포 후 Chrome 제어 연결 실패로 운영 UI 재촬영은 미완료. 고객단은 후속 별도 범위로 유지한다.

- 관리자 마무리 범위 확정: 사용자는 고객단을 별도 세밀한 작업으로 미루고 관리자 페이지 마무리를 요청했다. 제품군 목록에 실제 DB 기준 추천 분류별 건수/필터(52/42/9/1), 최신 상태 조회, 검토·설명 탭 바로 이동을 추가했다. 우측 호환성은 최신 검토를 표시하고 과거 문서 자료는 별도 접힌 영역으로 분리했다. 엑셀도 같은 분류와 보완 사유를 포함한다. 일부 부품명에 재등장한 회원가입 계좌이체 할인 문구는 표시만 제거하며 원문/해시는 보존한다. DDL/상품 DB 변경, 고객단 및 신규 고객 견적 등록 연결 없음. 91관련검사·상품명2검사 통과, 실제104조회 및 로컬 필터→검토·N10 엑셀1행 검증. 상세 `docs/design/admin-catalog-finish-20260930.md`.

- 추천/조립 분리 배포: main `3bb0da5`, run `36686385722` 성공. 서버 health 및 변경 JS 3종 내용 일치 확인. 실제 고객 데이터 저장 없음.

- 추천/조립 단계 분리: 16:50 KST 전수감사 52 추천 가능 후보 / 42 조건부 후보 / 9 추천 전 보완 / 1 우선 제외(총104). 42는 새 사실 확보가 아니라 확인 단계 재분류. 알려진 충돌과 핵심 규격 미확인은 계속 차단하며, 고객 필수 모니터/SSD 속도 조건이면 이관 항목도 추천 전 재확인한다. 부품2종의 단계 근거·관련31구성 해시/이력만 동기화했고 BOM·가격·사양·승인 상태는 유지했다. 고객별 조립·전화 기록 API/패널 추가(0119 재사용, DDL 없음). 동의는 정확한 변경안에 묶고 새 견적 버전+재검수로 처리한다. 현재 실제 고객 견적0건이며 견적/변경안/검증 생성 상위 흐름은 별도 연결 필요. 관련88검사+실DB8검사 롤백 통과. 상세 `docs/design/recommendation-assembly-workflow-20260930.md`.

- 예외 중심 자동 보완 1차: 사용자 진행 승인 후 `triage_pc_catalog.py`로 공통 사유를 묶고 검토된 판매처 보완 계획을 적용했다. 16:16 KST 재감사 52 후보 / 51 보완 / 1 우선 제외(총104). DN-240 114514의 TDP290W를 merchant 출처로 채워 P90622 1개 추가 해소, 최초37 대비 총15개 개선. 남은 사유는 14개 공통 작업(보완51+제외1 포함). 관련58검사와 실DB rollback/적용 후 보호값 확인 통과. 자동 웹수집·OCR/LLM·예외 UI는 후속이며 현재는 읽기 전용 분류+검토된 근거 적용 도구. 상세 `docs/design/pc-catalog-automation-20260930.md`.

- 판매처 3곳 대조 조사: 다나와·컴퓨존·오마이PC에서 보완 대상 부품 9종 및 기본 쿨러 식별용 CPU 1종을 확인했다. DN-240의 컴퓨존 290W, PALADIN 400 현행 235W(2025년 변경 이력), 보드 HDMI/D-SUB 일치, PM9A1 256GB 속도 정정 근거를 확보했다. A13 소켓 변경·SF360 길이 397/394mm·ABKO1851 지원 차이는 분리 관리 필요. 이번 조사는 DB 미반영이며 51/52/1은 아래 14:38 스냅샷 값 유지. 상세 출처·반영 순서: `docs/design/pc-catalog-retailer-review-20260930.md`.

- 보완 자료 추가 조사: 2026-09-30 14:38 KST 기준 공식 자료 7종(소매 사양 5필드, 조립 전용 6필드)을 추가하고 15개 제품군 설명·이력을 동기화했다. 기존 보완 66개 중 14개 해소 → 51 후보 / 52 보완 / 1 우선 제외. 최종 승인 아님. `api/pc_review_specs.py`는 원문 지문과 제조사 출처가 유효한 조립 전용 CPU/보드 사양만 관리자 검토에 연결하며 소매 사양은 public.product_specs 유지. 82개 검사 및 실제 DB 7개 대표 구성 검토 읽기 통과. 잔여 항목과 66개 전수 추적은 `docs/design/pc-catalog-enrichment-20260930.md`. 외장 GPU 없는 19개 구성의 규칙 적용 문제가 포함되며 그중 4개는 그것만 남았다. 규칙 삭제·자동 승인 없음.

- 전수 점검 및 근거 수정: 2026-09-30 14:16 KST 스냅샷의 104개 제품군을 37 추천 가능 후보 / 66 보완 필요 / 1 우선 제외 대상으로 분류했다. 이는 보고서 분류이며 승인·제외 상태를 일괄 변경하지 않았다. 9종 부품 13개 정보 항목을 DB에 보완하고 40개 제품군의 설명 해시와 이력을 동기화했다. BOM·가격·승인 상태 유지. 관련 검사 77개 통과. 자세한 근거·잔여 작업·백업은 `docs/design/pc-catalog-audit-20260930.md`. 조립 전용 부품 사양, 보드 리비전·SSD 품번, 냉각 근거 확인이 후속이다. 물리적 출고 가능을 확인한 결과는 아니다.

- 검토 기능 배포 확인: main `9b8f1cc`, run `36662946904` 성공. 인증된 서버 화면 P97909에서 현재 규칙 8건 및 근거 입력/승인 버튼 확인, JS 오류 없음. 실제 승인 없음. 화면 증빙은 작업 폴더 `outputs/admin-review-20260930/review-live.png`.

- 관리자 검토 워크플로 추가: `api/pc_configuration_review.py`, `pc-review-editor.js/css`. 현재 BOM/compat_rules 대조 → 근거 입력 → 대기 저장/승인/추천 제외. 변경 BOM의 승인이 유효할 때 관리자 상담 후보로 복귀한다. 구성·설명·가격·사양·규칙 변경 시 해시 불일치로 재검토/추천 제외. 과거 검토는 접힌 이력. 기존 미검토 카탈로그의 종전 필터는 유지한다. 고객 공개·출고·0119 고객 경로는 별도 후속이며 DDL 없음. 74개 검사와 실제 DB 전체 상태 전이/이력/추천 필터 롤백 검사를 통과했다.

- 부품 편집 배포 확인: main `a7c40df`, run `36586903883` 성공. 서버에서 P100866의 메모리 변경 미리보기 1,054,900 + 28,700 = 1,083,600원 확인 후 취소. 실제 상품 변경은 저장하지 않았다. 중앙 기록: `기록/팝콘AI/결과/popcorn-parts-editor-result-20260930.md`.

- 부품 편집 결합안 구현: 구성표 → 우측 후보 비교 → 변경 확인 → 기존 수정/새 제품군 저장. `pc-parts-editor.js/css`, `api/pc_configuration_parts_edit.py`. 판매중·설명 등록 후보 범위, 실제 단품 차액은 관리용 예상가이며 완제품 옵션가 확정 아님. 변경 BOM은 history에 보관하고 검토 대기/비공개로 저장하며 추천 테스트에서 제외한다. 스키마 변경 없음. 60개 검사 및 실제 DB update/new 롤백 검사 통과. 자동 호환성 판정·검토 승인·고객 공개 및 0119 고객 경로는 후속.

- 상품 설명 편집은 승인 시안 1(`exec-5c17e547-7ca4-4904-80f5-6110b0ce9d97.png`)로 구현. `pc-description-editor.js/css`와 `api/pc_configuration_edit.py`가 편집·미저장 미리보기·저장·변경 이력을 제공한다. 기존 history 테이블을 사용하며 새 DB 마이그레이션은 없다. revision 충돌은 409, 부품·가격·공개·검수 상태는 수정하지 않는다. 실제 저장은 operator/owner만 가능하다. 테스트는 49개, 실 DB 변경 테스트는 전량 롤백했고 실제 상품 내용은 유지했다.

- 전체 구성 보기의 승인된 2번 시안을 구현했다. 왼쪽 상품 요약과 오른쪽 부품 구성 / 상품 설명 / 검토 기록 3개 탭, 고객 설명 미리보기를 제공한다. LNB 그룹 아이콘은 기존 vendored Feather의 단색 선 아이콘으로 통일했다. 기존 상세 API만 사용하며 DB 변경은 없다. 관련 코드: `mockups/shared/pc-configuration-detail.{js,css}`. 상세 UI 검증은 `design-qa.md`의 마지막 절을 참고한다.

- 우측 상세 패널의 상품 설명·정보 검토·호환성·고객 공개 영역에 기존 내용을 읽기 전용으로 출력한다. 호환성은 api/data/pc_catalog_review_snapshot.json의 과거 검토 기록이며 승인 기능은 아니다. 고객 공개는 설명 미리보기만 제공하며 실제 공개 전환 연결은 사용자 요청대로 후속 처리한다.

- 아래 기존 절은 과거 인계 기록이다. 현재 체크아웃은 `D:/DEV/popcorn-ai`, main이며 기존 배포 기준은 `9aaef01`(0119)이다. 이번 커밋은 관리자 제품군 목록을 추가한다. DB 마이그레이션은 없다.
- 화면 `/admin2/pc-configurations` → 검색/필터/페이지/우측 요약 → 전체 구성·부품 상세. 현재 결과를 XLSX로 내보낸다. 서버 기존 관리자 인증을 그대로 적용한다.
- 상품 설명·부품 설명은 기존 DB에서 읽는다. 정보 검토와 호환성 최종 검수는 다르다. 최종 검수·공개 승인은 이번 범위 밖이며 공개 상태는 false다.
- 빈 구성에서 신규 등록·검토/공개 승인 UI와 0119의 고객 변경 견적 흐름은 아직 연결 전이다. 기존 제품군에서 부품을 바꾸어 새 제품군으로 저장하는 관리자 흐름은 구현했다. 케이스 실사진을 사용하며 별도 조립 완성 이미지 생성 작업의 결과는 미연결이다.
- 구현/검증: `docs/design/admin-pc-catalog.md`, `design-qa.md`. 과거 아래의 PC 접근 불가·683개 파일 CRLF 서술은 현재 작업 상태를 나타내지 않는다.

---

## 이전 인계 기록 (2026-09-28)

> 다음 에이전트가 이어받기 위한 현재 상태. **비밀값(비밀번호·API 키·토큰)은 여기 적지 않는다** —
> 이름만 적는다. 현재 수(상품·후보·검수 대기)는 적지 않는다: `.venv/Scripts/python scripts/state.py` 로 잰다.
> 규약·배경의 원천은 `CLAUDE.md` · `docs/decisions/decision-log.md` · `.claude/CANON.md` 다.

---

## 1. 현재 브랜치와 미커밋 변경

- **GitHub `main` = `a3e77cf`** (2026-09-25 13:46 UTC, 「고객 추천을 판매 중인 몰 조립PC 최대 2개로 전환」).
  이 HANDOFF 커밋이 그 위에 얹힌다. 작업 브랜치·열린 PR 없음 — **main 직접 커밋이 규약**이다.
- 클라우드 클론(`/home/claude/popcorn-ai`)은 origin/main 과 같고 미커밋 변경 없음.
- **사장님 PC `D:/DEV/popcorn-ai` 의 상태는 확인 못 함** (원격 폴더 연결 없음). 알려진 것:
  - `git status` 에 **683개 파일이 M** 으로 보이는데 CRLF/LF 차이뿐이다. **checkout/restore 금지.**
  - PC 는 2026-09-22 이후 클라우드에서 푸시된 커밋을 아직 `git pull` 안 했을 수 있다 — 「확인 필요」.
- 데이터 가지(배포 안 됨, 실행마다 덮어씀): `data/mall-fetch`(몰 완제PC 수집 결과) · `data/mall-price`(시중가 반영 로그).

## 2. 최근 완료한 작업 (최신순)

### 2026-09-25 방향 전환 — 「판매 상품 기준 추천 재설계」 (①~④ 완료·서버 반영)
사장님 「다시 작업 하자.. 기존거는 모두 무시하고」(12:03 UTC). 용도×가격 칸마다 부품 조합을 **생성**하던
격자 방식을 접고, **몰에서 이미 파는 조립PC 를 기준표로 채점해 표에 표시**한다. 한 상품이 여러 칸에
들어갈 수 있고, 맞는 상품이 없으면 빈칸이 정답이다.

| 단계 | 내용 | 커밋 · 배포 |
|---|---|---|
| ① 기준표 | 용도 11종 × 기본/쾌적/전문 (프로그램·규모 기준). CPU/GPU 지수는 공개 벤치 **근사** 등급표(코드 안 상수) | `7ad49de` |
| ② 채점 | `tools/product_fit.py` — 입력 popcornpc-catalog.xlsx(230행) → 평가 211 · 제외 19(품절·상세 없음·테스트 상품·구성 미선택). 산출 `/mnt/project-files/판매상품_적합성_20260925/`(엑셀·product_fit.json·product_fit_seed.json). DB 무접촉 | `7ad49de`, `fbbcfc6` |
| ③ 관리자 표 | `/admin2/product-fit` (ADM-GRD-020, 상품관리 → 「판매 상품 용도 매트릭스」). 가격대 7 × 용도·수준, 칸별 상품 수·최저가 대표·빈칸 이유. **마이그레이션 0115** · API `GET /api/admin/product-fit` | `0d2df98`, run 36136189052 ✅ |
| ④ 고객 추천 | mvp2 추천을 실제 판매 상품 **최대 2개**로 (사장님 「최대 2개 · 승인」 13:43). 예산 안 최고 수준 + 가장 저렴한 선택, 예산 안에 없으면 「○원부터」+ 최저가 1개. 몰 링크·판매가 카드 | `a3e77cf`, run 36143152042 ✅ |

- 스위치: `api/grid_public.py` `POPCORN_RECO_SOURCE` (기본 `sold`, `grid` 면 옛 조합 격자). **옛 엔진·격자 표는 지우지 않고 꺼 두기만** 했다.
- 실측 발견: 몰 조립PC 는 싸지 않다 — 90만 미만은 사무용 기본뿐, FHD 대작 게임·영상편집 최저 158.5만.
- 「판매 이유 점검」: 더 싼 상품이 모든 용도에서 같거나 높은 단계인 상품 211건 중 160건(단계가 거칠어 과대 추정 가능).
- 몰 상품명 GPU 와 기본 구성 GPU 가 다른 상품 3건(90631·128599·129805) — 관리자 표에 표시만.

### 2026-09-22 ~ 09-25 (방향 전환 이전, 결과는 남아 있음)
- S2 게임 근거 `game_context` 형제 필드 (A-137, `b6ab16e`) · 게임 별칭 표 `talk_game_aliases` 0113 (A-138, `03fdc74`).
- 부품 조합 균형 — 보조 슬롯 최저가 (A-139, `ef7b35e`) · 비게임 격자 구간 이동 0114 (`803f717`).
- 몰 완제PC 212건 수집(`tools/mall_builtpc_fetch.py`, 워크플로 `mall-fetch.yml`) · 몰 시중가를 `products.market_price` 에 202건 반영 (A-140, `mall-price.yml`).
- 서버 VM self-hosted 러너 자동 배포 구축 (`979c427` 외, 아래 §5).

## 3. 진행 중 / 대기 중인 작업

- **격자 재생성 — 보류.** 2026-09-25 15:06 사장님 「일단 보류.. 기획을 해서 줄께」. 빈칸 채우기 안
  (판매 상품 표 203칸 중 113칸 참, 빈 90칸은 전부 「몰 상품이 그 가격대보다 비쌈」)은 **미승인·미착수**.
  사장님 기획이 오면 그것을 새 기준으로 삼는다. **그 전에 격자 생성 재개 금지.**
- **디자인·조판 GPU 하한 기획** (`docs/design/plan-design-gpu-floor-2026-09-25.md`, 안 ㉮/㉯) — 방향 전환으로 **미적용 폐기 상태**. 되살릴 땐 실측 근거부터 다시 확인.
- **mvp2 실화면 확인** — ④ 배포 뒤 사장님 육안 확인 결과를 아직 못 받음 (클라우드는 브라우저 없음) — 「확인 필요」.
- 결정 로그에 2026-09-25 재설계(①~④)가 **아직 등재 안 됨** (마지막 A-140). 다음 기록 때 A-141 로 등재.
- 사장님 결정 대기(임의로 채우지 않는다): U-59 조사 붙은 줄임말(「롤이랑」) · U-60 피파·스타·와우 별칭 ·
  U-61 고객 화면 내부 필드명 노출(`mockups/mvp2/app.js`) · U-62 회귀 [62] DB 항목 기존 FAIL.
- 게임 근거 문구 86종은 관리자 `/admin2/game-copy-review` 에서 **승인 클릭**을 해야 고객에게 나간다 (0112 기준 전부 대기였음 — 현재 상태 「확인 필요」).

## 4. 알려진 문제

- **회귀 미실행 상태.** 서버 회귀가 `/etc/popcorn-ai.env` 에 `ADMIN_PW` 이름의 값이 없어 멈췄다(run 35804371636). 이후 설정 여부 「확인 필요」. 회귀는 운영 Cloud SQL 에 검사용 행을 넣고 지우므로 수동 실행만.
- **재설계(③④)를 지키는 회귀 항목이 없다** — `tests/regression.py` 에 `sold_reco`·`product-fit` 검사 없음.
- 기준표 CPU/GPU 지수는 근사치 — 정밀 벤치 아님. 「판매 이유 점검」 160건은 과대 추정 가능.
- 평가 원천이 ChatGPT 수집 엑셀(2026-09-25 스냅샷)이다. 몰 상품이 바뀌면 재평가 → 새 날짜 시드 → 새 마이그레이션 필요(자동 갱신 없음).
- `deploy/verify.sh` 는 낡아서 **항상 exit 0** — 배포 게이트에서 뺐다. 현행화 미착수.
- 고객 인증은 여전히 dev 어댑터(`api/customer_auth.py`, 이메일만 확인) — CLAUDE.md 「베타 배포 상태」 참조.
- 몰에 테스트 상품 pd_no 123456 「테스트용PC」가 공개로 남아 있음.

## 5. 실행·검증 방법

**배포 (지금 방식 — 예전의 「PC 에서 git pull → alembic → 서버 배포」는 낡았다)**
- `main` 에 푸시 → 서버 VM `popcorn-app` 의 self-hosted 러너(라벨 `popcorn-vm`, 계정 `ghrunner`)가
  `.github/workflows/deploy.yml` 로 **자동 배포**: pull · pip · `alembic upgrade head` · `popcorn-api` 재시작 · 헬스체크.
  `*.md`·`docs/**` 만 바뀐 커밋은 건너뛴다. 결과는 GitHub Actions 「배포」 실행에서 본다.
- root 작업은 서버 고정 스크립트 `/usr/local/bin/popcorn-ci` 한 곳(원본 `deploy/popcorn-ci`). 허용 부명령:
  `deploy | regression | verify | grid | grid-dry | mall-price | mall-price-dry`. **`deploy/popcorn-ci` 를 바꾸면 사장님이 서버에서 `sudo install` 을 다시 해야 반영된다.** 설치 절차 `deploy/RUNNER.md`.
- 수동 워크플로(Actions 탭, workflow_dispatch): `regression.yml`(회귀) · `grid.yml`(격자, dry 가능 — **보류 중**) ·
  `mall-fetch.yml`(몰 수집) · `mall-price.yml`(시중가 반영, dry 가능).

**로컬(사장님 PC, Windows)**
- API: `.venv` + `uvicorn api.main:app` (8000). DB 접속은 루트 `.env`(gitignore)의 `DATABASE_URL`.
- 현재 수: `.venv/Scripts/python scripts/state.py`
- 회귀: API 서버 띄운 뒤 `.venv/Scripts/python tests/regression.py --quiet`
- 재평가: `tools/product_fit.py` (DB 불필요, 엑셀·JSON·시드 출력)

**클라우드 컨테이너(이 하네스)**
- 되는 것: 코드 수정·정적 검사·커밋·푸시, `github.com`, `popcornai.co.kr` HTTPS.
- 안 되는 것: DB 5432 · SSH 22 (설정으로도 불가), Actions 로그·산출물 zip 다운로드 → 서버 결과는 데이터 가지에 커밋해 받는다.
- 브라우저 없음 — 화면 확인은 node 가짜 document 로 대신하고 육안은 사장님 몫.
- 첫 턴: `add_repo` → clone → `register_repo_root` (그래야 `.claude/agents/` 11명이 잡힌다).

## 6. 로컬과 배포 서버의 차이

| | 사장님 PC | 서버 VM `popcorn-app` (개발/스테이징) |
|---|---|---|
| 코드 | `D:/DEV/popcorn-ai` (CRLF 683 M 파일) | `/srv/popcorn-ai`, 러너가 main 을 받음 |
| 설정 | 루트 `.env` | `/etc/popcorn-ai.env` (계정 `popcorn`만 읽음, 러너 `ghrunner` 는 못 읽음) |
| 실행 | `uvicorn` 수동 | systemd `popcorn-api`, `127.0.0.1:8000` + nginx(`deploy/nginx-popcorn.conf`) |
| DB | 같은 Cloud SQL `popcorn-db` / `popcorn_pc` 를 공유 | 동일 |
| 테스트 표시 | `X-Popcorn-Test` 헤더가 먹힘(localhost) | 헤더 **항상 무시** — 배치·회귀는 자기 session_id 를 직접 `data_origin='test'` 로 표시 |
| 기타 | 크롤 작업공간 `D:/Hermes-Workspace`, 에이전트 정의 미러 `E:\DEV\.claude\agents\` | 다나와 재수집 타이머·실패 알림(`deploy/README.md`) |

- 서버 env 주요 **이름**(값은 적지 않음): `DATABASE_URL`, `ADMIN_PW`, `POPCORN_RECO_SOURCE`(미설정 = sold), `POPCORN_ARCHIVE_DIR`, 텔레그램 알림 값.
- 주소: 고객 `https://popcornai.co.kr/mvp2/index.html` · 관리자 `https://admin.popcornai.co.kr/admin2/` · 몰 `https://popcornpc.co.kr` (`products.product_code` == 몰 `pd_no`).
- 서버는 개발/스테이징이다. 운영은 새로 세운다(decision-log I-01).

## 7. DB 마이그레이션 적용 상태

- 저장소 head = **`0115_product_usage_fit`** (down_revision 0114).
- 서버 적용: 배포 run 40(`0d2df98`, 36136189052) 이 `alembic upgrade head` 로 0115 를 적용해 **성공**, 이후 run 41(`a3e77cf`, 36143152042)도 성공 → **서버 DB = 0115 로 판단**(Actions 기록 근거, DB 직접 조회는 못 함).
- 최근: 0113 `talk_game_aliases` · 0114 비게임 격자 구간 · 0115 `product_fit_levels`/`product_fit_products`/`product_usage_fit` (시드 `db/migrations/data/product_fit_20260925.json`).
- DB 는 PC 와 서버가 공유하므로 PC 에서 따로 upgrade 할 필요는 없다. 스키마 변경 순서: ERD(`docs/06_db-erd.md`) 개정 → 새 마이그레이션.

## 8. 반드시 유지해야 할 결정

- **추천 원천 = 판매 중인 몰 조립PC** (2026-09-25). 격자 생성기는 끈 채로 둔다. 격자 재개는 사장님 기획을 받은 뒤.
- 고객에게 보이는 실제 상품은 **최대 2개**.
- 고객 화면은 **mvp2 하나** (`mockups/mvp2/`). S1~S4(mvp1)는 옛 백업.
- 게임 근거는 reasons 에 섞지 않는 `game_context` 형제 필드. 검수 게이트(`reviewed_by IS NOT NULL`)는 `api/game_copy.py` 한 곳에만.
- 워크플로에 **`sudo` 직접 쓰기·`pull_request` 트리거 금지**(공개 리포 → 포크 코드가 서버에서 돈다). root 작업은 `popcorn-ci` 에만.
- 서버 env 에 **`POPCORN_TEST_HEADER_ENABLED` 절대 넣지 않는다** (실고객 행이 test 로 숨는다, A-75).
- 러너 계정 `ghrunner` 는 `popcorn` 그룹에 넣지 않는다.
- 비밀값은 리포·설정·메모리에 저장 금지. 서버 코드 직접 수정 금지(배포 타깃).
- 작업 규칙(사장님): 3~5줄 계획 승인 후 착수 · 한 단계씩 checker 검증 · `.claude/agents/*.md` 의 `model:` 덮어쓰지 않기 · main 직접 커밋 · 보고는 짧게 핵심만 · 사장님께 시킬 일은 한 목록으로 묶기.
- `usage_alloc` 비율은 규칙으로 박지 않는다(A-139 부기 확정). 숫자를 지어내지 않는다.

### 관련 파일
- 재설계: `tools/product_fit.py` · `api/sold_reco.py` · `api/grid_public.py`(스위치) · `api/admin_product_fit.py` · `api/admin_ui_product_fit.py` · `mockups/mvp2/app.js` · `db/migrations/versions/0115_product_usage_fit.py` · `/mnt/project-files/판매상품_적합성_20260925/`
- 배포: `.github/workflows/deploy.yml` · `deploy/popcorn-ci` · `deploy/RUNNER.md` · `deploy/README.md`
- 기록: `CLAUDE.md` · `docs/decisions/decision-log.md` · `.claude/CANON.md` · `docs/design/plan-design-gpu-floor-2026-09-25.md`
- 몰 수집: `tools/mall_builtpc_fetch.py` · `tools/mall_market_price_apply.py` · `api/mall.py`

---

## 사장님께 필요한 것 (꼭 필요한 것만)

1. mvp2 에서 추천 카드(실제 상품 최대 2개)가 제대로 나오는지 한 번 확인.
2. 격자 작업 기획(보류 해제 시).
3. PC 에서 `git pull` 로 최신 main 받기(683 CRLF 파일은 그대로 둔 채).

## 2026-09-28 추가 인계 — 부품 설명 기반 마련

이 절은 위 9/25 스냅샷 이후의 변경이며 현재 DB 상태 판단에 우선한다.

- **공유 서버 DB를 직접 확인하고 0116을 적용했다.** `product_explanations` 테이블에 201종 초안 저장, 기존 상품 연결 199종 / 조립 전용 미연결 2종(127201·127203). 모두 draft이며 공개 승인 0건. 기존 상품의 가격·사양·상태·검수 플래그는 반영 전후 동일함을 확인했다.
- 설명의 제조사 전체 검증은 미완료다. 등록 이미지 주소 200종이며 실물 모델 대조 전으로 표시한다. SSD 110899·MB 113685의 출처 충돌과 RAM 127555의 용량 충돌을 설명에 기록했다. 사양 원문 부족 3종은 보완 필요로 남긴다.
- 추가 API: `/api/admin/part-explanations`(목록·상세), `/api/part-explanations/{code}`(공개 게이트). 관리자 화면 `/admin2/part-explanations`. **로컬 코드 구현·검증까지이며 서버 API/UI 배포 전**이다. 새 마이그레이션은 이미 적용됐으므로 공유 DB에 재적용 작업을 별도로 하지 않는다.
- 실제 고객 추천 화면 연결, 자유 질의 전송, 설명 수정·승인 UI는 아직 없다. 현재 질문 버튼은 FAQ 펼침이며 고객용 알뜰/추천 카드 생성·공개를 의미하지 않는다.
- 로컬 검토 자료: `C:/Users/leon2/OneDrive/Documents/ChatGPT/팝콘AI/outputs/part-explanations-20260928/`. `index.html`, `부품설명-201종.md`, `부품설명-201종.json`, DB 적용 전후 보고서와 HTTP 검사 결과를 함께 저장했다. 로컬 미리보기 `http://127.0.0.1:8766/`(정적 서버 실행 중일 때).
- 재현 도구: `tools/build_part_explanations.py`, `tools/preview_part_explanations.py`. `tools/apply_part_explanations.py --apply`는 0115→0116 최초 추가만 허용하므로 이미 반영된 DB에 다시 실행하지 않는다.
- 후속: 제조사별 실제 모델 대조 → 충돌·미연결 해결 → 승인 워크플로 → 확정 PC와 설명 연결 → 알뜰/추천 구성별 선택 이유. 104개 구성은 후보이며 모두 실제 출고 승인됐다는 뜻이 아니다.
- 이번 변경은 기존 상품 재수집/품절 상태 반영과 별개인 설명 테이블 추가 작업이다. 기존 카탈로그 수집 결과와 104개 후보 엑셀은 `outputs/final-catalog-20260928/` 및 이전 산출물에 보존돼 있다.

### 2026-09-28 사용자 표시·자료 기준 변경

- 부품 설명의 표시 상품명에서 `[회원가입 계좌이체 맞춤할인 -2.5%]` 문구를 제거한다. `api/product_name.py:remove_discount_label`을 생성·조회 경로에서 공유한다. 제품 원본과 수집 근거는 보존한다.
- 판매처에 등록된 제품별 사양·이미지는 사용 가능한 자료로 인정한다. 제조사 전체 대조를 일괄 선행 조건으로 강제하지 않고, `대조 전`이라는 공통 문구를 제거한다. 이미 발견된 사양 충돌·자료 누락·DB 미연결은 계속 표시한다. 이는 조립 호환성이나 출고 승인을 뜻하지 않는다.
- DB 설명 상품명 40종과 공통 대조 전 안내 201종을 수정했다. 변경 전 백업은 로컬 산출물의 `discount-label-before.json`, `merchant-source-accepted-before.json`이다. 승인 상태·공개 여부는 바꾸지 않았다. 초기 0116 시드 파일은 당시 이력으로 보존한다.

## 2026-09-28 제품 이미지 저장소 적용

사용자가 원본 픽셀을 유지한 자동 여백 재단과 자체 저장소 이관을 승인했다.

- Google Cloud 프로젝트 `project-045e861b-da1d-423a-b84`(popcorn-db가 있는 프로젝트), 서울 리전의 비공개 버킷 `popcorn-ai-product-media-045e861b` 생성. Public Access Prevention + uniform bucket access. 기존 popcorn-app 서비스 계정에 이 버킷 objectViewer만 부여했다. 서버 VM의 storage read-only OAuth scope는 이미 존재해 변경하지 않았다.
- 원본 200개 / 상세 PNG 200개 / 썸네일 WebP 200개 업로드, 전체 600개 파일 크기·MD5 일치 확인. 195종은 균일 외곽 여백 재단, 5종은 원래 경계 유지, 1종(127920)은 판매처 이미지 미확보. 원본 바이트를 보존하고 상세 PNG는 재단 영역의 디코딩 픽셀이 동일함을 전수 확인했다. 네 장의 목록 이미지로 200종도 육안 확인했다.
- DB `product_explanations.content.image_asset`에 200종 연결. 원본 image_url/수집 근거·상품 사양·가격·판매상태·설명 승인 상태는 그대로다. 변경 전 백업 `outputs/product-images-20260928/image-assets-db-before.json`.
- 로컬 미리보기에는 가공 이미지가 적용됐다. 서버 배포용 `/api/product-images/{code}/{detail|thumbnail}`은 ADC로 비공개 저장소를 읽으며 원본·임의 object key는 공개하지 않는다. 코드 구현·로컬 API의 실제 Cloud Storage 읽기 검증까지 완료했으며, 서버 API/UI 배포는 아직 하지 않았다.
- 파일 저장 구조: `products/<상품코드>/<원본 SHA256 앞 16자>/original.jpg`, `detail.png`, `thumb.webp`. 약 86.3 MiB. 외곽 여백은 2% 안전 여유를 남긴다. 원본에 있는 박스·글자·반사·그림자는 재생성하거나 지우지 않았다.
- 재현 도구: `tools/prepare_product_images.py`(Pillow 필요), `tools/apply_product_images.py`(기본 dry-run, Cloud Storage inventory의 MD5·크기를 전수 대조 후 --apply), `tools/preview_part_explanations.py --image-assets <원본 저장 디렉터리>`. 가공 바이너리는 Git에 넣지 않는다.
- 산출물 루트: `C:/Users/leon2/OneDrive/Documents/ChatGPT/팝콘AI/outputs/product-images-20260928/`. manifest.json, cloud-inventory.json, image-assets-apply-result.json, image-http-verification.json, qa-contact-1~4.jpg. 현재 로컬 미리보기: `http://127.0.0.1:8766/`.

**같은 작업 최종 보완:** 127920의 판매처 상세 페이지를 직접 재조회해 `img#viewimg`의 대표 이미지를 추가 확보했다. 최종 **201종 / 603개 파일 / DB 연결 201종 / 재단 196종 / 경계 유지 5종 / 미확보 0종**이다. 위 200종 수치는 최초 처리 시점 기록이다. 추가 1종은 `image-127920-before.json`으로 별도 백업했으며 최종 검사 결과는 `image-final-verification.json`이다.

**표시 정리(사용자 요청):** 사양표의 `판매처 원문` 등 근거 배지, 이미지 출처 캡션, 출처 안내와 근거 펼침을 화면에서 제거했다. 출처·검증 기록은 DB와 설명 문서에 유지한다. 실제 확인사항은 유지한다.


## 2026-09-28 최신 인계 — 구성 DB와 실제 LLM 상담

이 절이 위 과거 상태보다 우선한다. 현재 작업 위치는 `D:/DEV/popcorn-ai`, main 직접 커밋·푸시이다. 이전의 PC 접근 불가·683파일 미확인·0115 추정은 과거 기록이다. 공유 DB에 직접 접속하여 0117 구성 설명과 0118 사용 시나리오 마이그레이션을 적용했다. 0117 코드 배포 커밋은 `ab9e43f`, Actions run `36424324870` 성공이다.

- 구성 원천은 `pc_configurations`/`pc_configuration_parts`/`pc_configuration_offers`, 상세 조회 `/api/admin/pc-configurations/{id}`. 설명 버전·원문 변경을 조회 시 대조한다. 127201/127203은 조립 전용 설명 코드이며 가짜 단품 상품을 만들지 않았다.
- 이번 추가 경로: `/admin2/configuration-consultation`, `POST /api/admin/configuration-consultation`. 기존 LLM 모듈과 `task.s1_parse`를 사용하며 관리자 인증 안에서 검토한다. 기존 mvp2의 옛 parse/추천 경로는 변경하지 않았다.
- LLM은 고객 조건·질문만 정리한다. 상품/가격/부품은 DB에서 가져온다. 해상도/FPS/모니터 수의 인용 검증, 가격 예산 분리, 필수 미달·오래된 설명 제외, 중단·재시도·새 상담 뒤 응답 역전 방어가 있다. 모든 비교 응답은 customer_publishable=false이다.
- 미해결: 복합 동시 작업의 실제 자원 요구, AI 모델 적재, 미등록 용도/선호 조건에 대한 근거 확장 및 고객 공개 흐름. 110899 출고 SSD P/N과 113685 출고 보드 리비전 확인은 계속 필요하다. 단순 RAM/VRAM 용량으로 FPS·작업 성능을 확정하지 않는다.
- 검증: `.venv/Scripts/python -m unittest tests.test_configuration_consultation tests.test_pc_configuration_copy tests.test_part_explanations -q`, `node --check mockups/shared/configuration-consultation.js`.
- 로컬 실제 API 검토: `http://127.0.0.1:8772/`, 실행 도구와 실제 응답·화면 증거는 `C:/Users/leon2/OneDrive/Documents/ChatGPT/팝콘AI/outputs/llm-consultation-20260928/`. 이 루프백 전용 하네스는 배포용 인증을 대체하지 않는다. 기존 정적 미리보기는 8766이다.
- 실제 공급자 테스트 중 기존 LLM 가격표 유효기간 경고가 발생했다. 공급자 가격표/비용 정책은 이번 작업에서 변경하지 않았다.


## 2026-09-29 최신 인계 — 부품 변경 견적 DB 설계

사용자 제공 화면(부품 변경 전후 + 오른쪽 GPU 비교 패널)을 기준으로 ERD §24와 `docs/design/pc-component-change-contract.md`를 작성하고 0119 신규 테이블/제약을 추가했다. 기존 원본 구성과 고객 견적을 분리하며, draft revision·누적 교체/추가/제거·검증·확정 버전·감사 기록을 보관한다. 적용은 동일 BOM/revision의 유효한 pass 검사 및 확인 가격을 요구하고 현재 버전 이동까지 원자적으로 처리한다. 소유권 및 최신 가격/사양 재조회·JSON 구조 검증은 후속 API 책임이다.

추가 사용자 결정: 고객이 최종 확정한 견적은 제품군 관리로 축적한다. `pc_quote_confirmations` INSERT는 `pc_catalog_submissions` pending을 같은 트랜잭션에서 자동 생성한다. 동일 BOM은 기존 제품군에 연결하고 신규 BOM만 새 관리 구성으로 추가할 계약이다. 최종 확정 버튼/API와 실제 pending 처리기·제품군 생성은 아직 구현하지 않았다. 단순 부품 변경 적용만으로 등록하지 않는다.

검증 도구 `tools/check_pc_quote_schema.py`는 신규 DDL/테스트 행을 단일 트랜잭션에서 검사 후 rollback한다. 실제 고객/상품/재고는 변경하지 않는다. 기존 quote_snapshots/스왑/고객 UI는 그대로이며 새 기능이 화면에서 동작한다고 안내하지 않는다. populated downgrade는 거부한다.

이미지 제작은 사용자 요청으로 별도 대화 「조립PC 104개 제품군 완성 예시 이미지 제작」(thread `01a0eb9f-022f-71a1-9b64-5be368859dab`)에서 진행한다. 케이스/공랭·수랭/LED 중심의 생성 예시이며 결과는 이 작업 폴더의 outputs/assembled-pc-images-20260929/에 저장하도록 요청했다. 이 DB 작업과 파일/DB 쓰기 충돌이 없도록 분리했다.


## 2026-10-01 CPU 포함 쿨러 분류

104개 전수 분류: CPU 기본 쿨러 포함 명시 9 / 미포함 또는 벌크 78 / 포함 여부 미확인 17. 실제 BOM은 별도 쿨러 99 / CPU 포함 쿨러 5. 미확인 17개에도 별도 쿨러가 있다.

기존 보완 5개 P113193/P113334/P113838/P113843/P120220은 121359 Ryzen 5500GT 멀티팩 원문과 AMD MPK 공식 사양으로 Wraith Stealth 포함을 확인했다. '기본 쿨러 모델 미확인'을 정정한다. 해당 구성만 소켓 근거 연결, 높이/부하 냉각은 조립 확인, 라디에이터 비적용으로 처리한다. 자동 승인이나 BOM·가격 변경은 없다. 해당 5개 검토 근거는 바뀌어 재검토가 필요하다. 별도 쿨러가 있는 구성에는 기본 쿨러 예외를 적용하지 않는다.

분류 API/관리자 부품·검토 탭 반영, 저소음 등 기본 쿨러 추가 요구 재검토 조건 추가. 전수 판정은 추천 가능 후보 52 / 조건부 후보 51 / 제외 대상 1. P119302의 120X4 지원 소켓은 현재 DB와 다나와 최신 표기가 다르므로 제조사/실제 브래킷 확인 후 보완한다. 판매처 표기만으로 덮어쓰지 않았다.

설계: docs/design/pc-cooling-policy-20261001.md. 증거: 작업 폴더 outputs/cooler-policy-20261001/. 검증: Python 109개 통과, JS 구문 및 diff 검사 통과, 운영 DB 관리자 저장 흐름 5항목 확인 후 전부 rollback. 고객 화면은 계속 별도 범위다.

최종 배포: 14ffcb8 / Actions 36814095797 성공. 운영 관리자 P113193 부품·검토 탭의 쿨러 모델, CPU 가격 포함, 조건부 후보, 조립 확인 문구를 직접 확인. 스크린샷 outputs/cooler-policy-20261001/admin-cooling-review.png.


## 2026-10-01 CPU별 냉각 방향 제품 적용
- 104개 제품군에 현재 등록 냉각 방식과 CPU별 제조사 안내·사내 검토 방향 연결. 기본 공랭 5 / 별도 공랭 86 / 수랭 13, CPU 모델 안내 104개 연결.
- 관리자 목록 냉각 방식 필터(기존 CPU 검색과 병용), 상세·검토 화면, 엑셀 내보내기에 적용. 필터는 세션 내 유지.
- 사내 방향은 검토 기준이며 실조립 성공을 뜻하지 않는다. BOM·가격·추천 승인·고객단 변경 없음. 기존 승인 해시는 유지.
- 제조사 수랭 권장 CPU의 공랭 구성은 유지하되 부하 온도·전력 설정·소음 검수 확인 항목 표시.
- unittest PC 테스트 104개, JS 구문 검사, 전수 읽기 검사 통과. 실제 관리 워크플로는 롤백 전용 검사.


## 2026-10-01 대표 제품 검토→추천 흐름 검증
- 가격 payload를 검토 assess에 전달하던 KeyError 수정: 전체 offer DB 행으로 근거 계산, 추천 매칭에는 payload 전달.
- 대표 N07/N02/P113193/N14/P112769/N12/P119302의 승인·대기·변경·차단 및 추천 가격/BOM 연결을 실제 DB 롤백으로 검증. 유지된 승인0, LLM 호출0.
- 104개 모두 신규 검토 기록 없음. 기존 목록 유지 정책에서 103개 비교 가능(승인 완료 아님).
- 30개 시나리오: 비교24 / 모델 근거 대기2 / 편집 저장장치2개 조건으로 빈 후보4. 상세 `docs/design/admin-review-recommendation-flow-20261001.md`.
- PC104 + 상담17 테스트 통과. 재현 도구 `tools/check_pc_review_recommendation_flow.py --output <path>`.

- 후속 사용자 정정(외장 아닌 본체 내부 SSD 추가): N07 파생 `AC11F5AEA43924DBA` 신규 검토 대기 등록. 1TB NVMe×2 / 총2TB / 예상2,133,000원(추가224,800원). 설명·특장점·FAQ 완료, 기존N07 유지. 검사 승인만 savepoint 롤백, 실제 승인 없음. C03~C06 편집 후보 연결 검증. 전체 제품군105개, 서버 화면 수량2 확인. 로더 수정 b90b5ec 배포36816948684 성공.

2026-10-01 사용자추가승인: 신규/기존104개 제품군 개별 영상버튼, 확정대표이미지 기반6초확대이동 MP4, 클라우드파일저장 및 DB자산연결. 시안localhost8785 반영, 운영미구현. 상세 admin-new-pc-builder-20261001.md.
