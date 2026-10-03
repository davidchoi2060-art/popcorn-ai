# MVP3 실연결 프런트 — 디자인·브라우저 QA
2026-10-03 KST. 판정 범위는 승인된 welcome/results/detail/final의 고객 UI와 실제 HTTP 계약을 사용하는 프런트다. 실행 검증은 운영 DB·LLM과 분리된 HTTP 응답 환경이다. 사용자 원본·실렌더를 함께 열고 판단했다. 서버·마이그레이션 적용·배포·운영 저장 E2E 판정이 아니다.

## 비교 대상·밀도·상태
원본 경로 기본: D:/WORK/PopcornAI/outputs/customer-ui-parallel-20261003/
- welcome: original-review-assets/a85d7409-cf8f-48bd-8084-2df77798bda2.png ↔ implemented/live-connection/01-welcome-native.jpg, 1487×1058 CSS px/pixels, DPR1, 무요청·복구기록 없는 초기 화면.
- results: original-review-assets/8dfcc10a-5b43-45f2-90b3-ee8935f93b2e.png ↔ 02-results-native.jpg, 1487×1058, DPR1, 상담 후 두 판매 상품을 비교하는 상태.
- detail: original-review-assets/ef7d3b24-1cd6-42c7-94c4-79dbbd963372.png ↔ 03-detail-native.jpg, 1487×1058, DPR1, 선택한 추천 상품·사양 접힘. 추가 펼침은03-detail-expanded-native.jpg.
- final: 03-최종견적-저장전.png ↔ 04-final-native.jpg, 1402×1122, DPR1, 최종 확인·보관 전·사양 접힘. 추가1440×1000은22-final-pc1440.jpg.
- 모바일390×844: 11-results-mobile-full,12-detail-mobile-full,13-final-mobile-full,14-welcome-mobile-full. fullPage는 실제 페이지 전체 높이며 844높이 캡처를 가장하지 않는다.

원본의 예시 대화/상품/가격/가상 사진/부품8행은 실제 공개 sold 상품과 같지 않다. 같은 흐름 상태·viewport·밀도로 구조를 비교하되 원본의 가짜 행/시각/가격/FPS를 복제하지 않았다. 통합 담당이 해당 원본과 실캡처를 보고 왼쪽 상담/오른쪽2카드/사양 label-value/낮은요약/1완제품행+펼침/금액·확인/조건 구조를 수용했다. 예산 초과 후보는 supplied flag와 실제 금액 관계를 맞춘 격리 응답이다.

## 원본·구현 결합 증거
30-compare-welcome-full,31-compare-results-full,32-compare-detail-full,33-compare-final-full.jpg를 각각 한 입력에서 열었다. 두 이미지를 동일0.45배율로 표시했고 source와actual의 native 크기는 같다. viewer viewport1460×850, 전체region 프레임과 외부 비교 제목은 구현 UI가 아니다.
집중:34-compare-spec-focused.jpg(0.70 동일배율, 실제 가격·사양),35-compare-hero-focused.jpg(0.78, 그림·제목·단계),36-compare-footer-focused.jpg(0.72, 구매조건·행동). 행수·내용 차이로 의미 영역의 y좌표를 각각 선택했다. 최초 focused clip에서 가격 첫자/조건 끝이 잘린 증거는 범위를 넓혀 재촬영하고 최종 파일로 대체했다. crop 잘림을 제품 문제로 판정하지 않았다.
뷰어: http://127.0.0.1:8765/live-comparison.html. 캡처 기본: D:/WORK/PopcornAI/outputs/customer-ui-parallel-20261003/implemented/live-connection/.

## 발견·수정·재검사
- P1: results/detail/saved에서 avatar-mark의 원본 PNG 크기가 그대로 렌더되어 상담 영역을 덮었다. live avatar에 크기/contain을 제한하고 승인된 상담 셸을 core4화면에 적용. 초기03-detail-expanded-pc.jpg는 이 실패의 이전 증거이며 현재 판정에서 제외한다. 수정 후 native03과30~33,모바일11~14에서 정상 크기 확인.
- P2: 사양 object를 문자열 전용 변환하면서 실제 CPU/GPU/RAM/SSD가 지워졌다. publicSpec allowlist와 label/value dl을 추가, cpu/gpu 문자열·ram_gb/ssd_gb/vram_gb 숫자만 표시. nested 값과 cpu_mt/cpu_st/gpu_idx는 제외한다. 새 계약 검사와34집중/12펼침에서 확인.
- P2: 추천 사양이 긴 한 줄로 표시되어 원본의 비교 정렬이 사라졌다. card label/value 정렬을 복원하고 desktop label폭120px/mobile86px로 조정. 변경 후02/10/11/31/34.
- P2: 취소 중 saveState=saving 잔류 및 reload시 새 요청ID 위험. POST 전 최소 고정payload/UUID를 sessionStorage에 보존하고 취소는 uncertain, 자동POST 없이 목록/같은요청 확인을 분리. 목록이 있어도 pending완료를 추론하지 않는다. 05~08,19~20 및 계약18~28 검증.
- P2: 151만원 대안의 격리 추천이유가 예산 안이라는 모순, 예산 초과 안내색 미정의. 테스트 응답만 정정하고 warn-text #92510c 적용.10/02/31에서 높은금액·문장·색 관계 확인. 실제 DB자료 변경 없음.

현재 남은 actionable P0/P1/P2는 확인되지 않았다. 위 차이는 실제 source/구현 결합 비교·수정 후 캡처로 판단했고 이전 데모 검수10/10으로 대체하지 않았다.

## 필수 충실도 검토
- Fonts/typography: 제공된 local Pretendard Variable, 일반16px/보조14px, 제목/가격 위계와 줄바꿈 확인. 실제자료의 이름이 길어져도 overflow-wrap으로 보존. 원본 정확한 폰트명/안티앨리어싱과 가격 크기의 작은 차이는 P3.
- Spacing/layout: 독립 둥근 상담패널과 약1:2 PC비율, 초기 큰 그림·3단계, 추천2열/모바일1열, 낮은요약, 상세표·금액·조건2열/모바일적층, 하단행동 유지. native final footer bottom약901px/viewOverflow0; PC1440및mobile390에서 가로넘침0. 1완제품+공개사양으로 밀도가 줄어든 차이는 계약상 의도된 제품 제약이다.
- Colors/tokens: 기존 민트·진녹색·중성선·주황 미보관/미확인·녹색 보관완료 사용. 예산초과는 #92510c. source 말풍선/사양 배경/조건 구분 유지.
- Image quality: 기존 생성된 welcome PC/브랜드 PNG와 Phosphor SVG 재사용, 새 이미지 없음. 결과상품 사진은 서버 제공 없음으로 생략하고 가상 그림을 실상품 사진으로 사용하지 않는다. 그림/마크 곡선의 차이는 P3. 아이콘과 이미지를 CSS그림/글자그림으로 바꾸지 않았다.
- Copy/content: 실제 answer와reply/own-web 출처, supplied 상품명·사양·가격원천·추천이유, unknown 구매조건을 표시. 현재 단품 변경/FPS는 미제공 안내와 disabled. 보관은 시점참고snapshot이며 주문/확정가격/재고예약으로 표시하지 않는다.

## 브라우저·기능 검사
http://127.0.0.1:8766/mvp3/index.html의 **격리 API 응답**으로 실제 제품 프런트 파일을 검증했다. 테스트 서버는 D:/WORK/PopcornAI/outputs/customer-ui-parallel-20261003/live-qa/server.py, 운영 DB/LLM 호출 없음.
- PC1440×1000/native 두 크기/390×844, 상담 예시·Enter·다중용도/두후보/상세펼침/뒤로/새상담/내견적.
- 실제사양5항목과 선택한 상품가격, 원천/추천이유, 미지원 옵션버튼 확인.
- 보관중 이동/늦은응답 무시/reload/동일 요청확인. 격리 control에서 save2회/unique1회/replayed true 관찰. server를 테스트응답 정정을 위해 재시작한 전후 자료를 운영 기록처럼 취급하지 않는다.
- 목록 조회만으로 pending 해제하지 않음, mobile복구완료 후 배너제거·저장완료 확인.
- 429 UI/대기/수동재시도(사용자말풍선1개 유지),409 최신조회·저장차단,추천없음,긴상품명/특수문자 literal·img실행0·내부평가값 비노출.
- 모바일 상담조건 버튼으로 상담펼침/textarea focus=request 확인.
- 콘솔error/warn [] 및 broken image0. observed-state-checks.json/console-check.json 참고.
- node --test tests/contract.test.cjs: 실연결 계약30/30. JS4개 syntax 및 전용 diff check 통과. legacy fixture 테스트/기능은 현재 판정 대상이 아니다.

## 남은 확인과 경계
실제 브라우저200% 확대는 도구의 ctrl+plus에서 CSS크기/DPR 변화가 없어 미확인이다. ctrl+0 복원,720×500 reflow/가로넘침0을 별도 확인했으며200%라고 보고하지 않는다. 모바일 승인 원본은 없어 반응형 적응으로 검수했다.
통합 담당 최신 전달: 실제 공개DB 읽기·task.s1_parse LLM 응답·서버16검사 완료. 이 고객 담당의 브라우저 검증은 격리이며 운영DB0123 적용/실저장/배포/E2E 완료를 입증하지 않는다. 실제 저장 시험행은 만들지 않는다.
회원/공급처/판매가/영상/공통 API·인증·비공개구성은 변경하지 않았다. 개별 commit/push 금지, 전용 파일 인계 후동결.

## 체크리스트
- [x] 4개 화면 native원본과 구현 전체·집중 결합 비교.
- [x] 발견P1/P2 수정 후 재촬영·재판정.
- [x] PC/390 실제DOM·사양/저장복구·오류/empty·console 검증.
- [x] 실제 HTTP 계약30검사·구문·전용diff check.
- [ ] 실제200% 브라우저 확대.
- [ ] root 운영적용·배포·운영E2E 판정.

final result: passed
