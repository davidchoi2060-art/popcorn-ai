# MVP3 고객 PC 상담 — 실연결 프런트
현재 HTML은 live-model.js → api-client.js → live-flow.js → app.js를 로드한다. fixtures.js/model.js의 가상제품·149만원·FPS 산식은 현재 화면에서 사용하지 않는다. CSP connect-src self, 같은 origin의 실제 서버 API만 호출한다.

## 현재 계약
- POST /api/talk/parse: 최대300자 text, 직전state/chat_flow, 이번 입력 이전history6개. answer/reply/own-web출처/누락조건/오류·재시도 분리.
- POST /api/grid/recommend {state}: card_sets kind=sold의 실제 상품·참고가격·공개사양·추천이유. CPU/GPU/RAM/SSD/VRAM만 정렬 표시하고 내부평가값 제외. 없는 사진/부품가격/FPS/옵션 변경을 만들지 않는다.
- GET/POST /api/mvp3/saved-quotes: 서버가 최신추천과가격을 다시 확인한 snapshot 보관. request_id/product_code/expected_price/state만 제출. 보관은 주문·가격확정·재고확보가 아니다.
- Web Crypto32byte 손님 보관키만 localStorage에 저장하고 X-Access-Key header로 보낸다. 최초GET으로 pc_vid 준비. pending UUID+고정 최소payload+비밀키 아닌key hash는 sessionStorage에만 보존한다. POST전에 세션 보존이 안되면 보내지 않는다. 이동/취소/reload는 결과미확인, 목록으로 완료추론 안함, 같은 요청을 사용자가 직접확인하며 자동재전송 없음. 접근 키가 바뀌면 replay 차단. provider 키·대화전체·보관결과본문은 브라우저 지속 저장하지 않는다.

## 검사와 실행
node --test mockups/mvp3/tests/contract.test.cjs : 현재 실연결 계약30/30. JS4개구문/전용diffcheck통과. design-qa.md는4화면 원본/실렌더 결합 대조와 PC1440·mobile390·보관취소/reload/오류·empty/console 검증범위에서 passed다. 실제200% 확대는미확인.
실제 서비스에서는 /api와 UI를 동일 origin의 앱서버로 제공한다. Python http.server8763은UI 파일만 제공하므로 실제 API 서버가 아니다. 검수용8766은 작업실의격리HTTP응답 서버이며 운영DB/LLM 동작증명이 아니다.
통합 서버0123 적용/배포/운영E2E는 root 소유, 운영 시험보관행 생성/개별commit/push없음. 프런트 전용 인계: D:/WORK/PopcornAI/outputs/customer-ui-parallel-20261003/MVP3-실연결-최종프런트인계.md. 현재 파일은 통합 선택을 위해 동결한다.

---

## 이전 데모의 실행·계약 이력
# MVP3 고객 견적 데모

직접 진입: `/mvp3/index.html`. 승인된 고객 이미지 흐름의 독립 로컬 구현이다. 서버/관리자/공통 인증/DB/루트 진입 변경 없음.

## 실행

저장소 루트에서 `python -m http.server 8763 --bind 127.0.0.1 --directory mockups`, 브라우저 `http://127.0.0.1:8763/mvp3/index.html`.

순서: 상담 예시 시작 → 추천 견적 상세 → 모든 부품 설명 펼침 → SSD 변경 → GPU 후보 선택 → 누적 변경 비교 → 최종 확인 → 데모 저장. 새 상담·뒤로가기·부품별 취소·내 견적·조건 수정도 동작한다. GPU C와 SSD 2TB는 총 149만원, 예산 150만원보다 1만원 낮다.

## 데이터와 저장

`fixtures.js`의 모든 제품/금액/FPS/호환 결과는 가상 예시. 제품 이미지는 ImageGen으로 생성한 가상 제품이다. `localStorage`에는 전용 키 `popcorn-mvp3-demo-quote-v1`로 `{origin,version,gpu,ssd}`만 저장한다. 대화·개인정보·access_key를 저장하지 않는다. 저장 실패·저장 파일 형식 오류는 화면 안내와 현재 구성 보존으로 처리한다. 상담은 고정 데모 동작이며 AI/운영 API 호출 없음. CSP의 `connect-src 'none'`으로 네트워크 API 연결을 막는다.

## 공개 API 계약과 closed 동작

제안 경로는 GET `/api/customer/pc-configurations/{configuration_id}`, POST `/api/customer/quote-change-preview`. 실제 라우트 구현 없음. `api-client.js`의 공개 fixture는 publication allowed + customer_publishable true + 현재 basis의 명시 approved/eligible를 모두 만족하는 때만 제한 projection을 반환한다. 기본은 closed/404. 실제 연결 함수는 연결 미준비 오류를 반환하며 네트워크를 호출하지 않는다.

상세 계약은 작업실 `outputs/customer-ui-parallel-20261003/공개API-계약제안과-시안검토.md`. 공개 게이트·최신 근거 재조회·익명/회원 소유·가격/재고 상태·저장 버전·승인된 상품 설명 projection이 확정된 뒤 전용 API를 연결한다. 관리자 상세 및 swap/apply를 preview에 연결하지 않는다.

## 격리 검사

`node --test mockups/mvp3/tests/contract.test.cjs`. 합산/취소/합계·저장 allowlist·closed/public basis·unknown/stale 비노출·보증 범위 보존·운영 API 미호출을 검사한다. DB/LLM 호출 없음.

브라우저 검증: 1280/900/390px 가로 넘침 없음, 상세 사양 8개 펼침, 후보 검색 없음/필터에서 선택이 빠지면 갱신 비활성, 개별 변경 취소, Esc 초점 복원, Enter 전송, 뒤로/앞으로 대화 유지, 저장/불러오기 및 저장 실패 시 구성 유지. 저장 실패 재현: /mvp3/tests/storage-blocked.html (검증 전용). 2026-10-03 Node 검사 10/10 통과.
실제 캡처 및 인수인계: 작업실 outputs/customer-ui-parallel-20261003/MVP3-구현결과와-인수인계.md. 개별 배포하지 않았으며 통합 반영 대상은 신규 mockups/mvp3/ 폴더만이다.
