# 부품 설명 상세

사용자 승인: 2026-09-28, 실부품 설명 작성 및 DB 추가·변경 허용. 첨부 펼침형 상세 화면을 기준으로 한다.

부품 행을 펼치면 이미지, 사양 표, 역할, 특징, 확인사항, 질문 버튼을 표시한다. 이미지 미확인은 명시한다. 실제 상품명·용량을 사용하며 제조사 대조는 필드별로 표시한다. RAM 키트와 PC 장착 수량을 구분한다.

관리자 원문은 판매처 근거이며 제조사 검증 완료가 아니다. 충돌하는 값은 확인사항에 기록하고 자동 공개하지 않는다. 설명은 초안 적재 후 검수한다. 가격·재고·호환 정본과 기존 추천 상태는 바꾸지 않는다. 알뜰 구성/추천 구성은 PC와 고객 조건의 속성이며 부품 설명에 고정하지 않는다.

관리자: `/admin2/part-explanations` (ADM-PRD-030), 검색·유형 필터·서버 페이지네이션. 공개 API는 승인된 설명 중 현재 원문과 일치하는 것만 제공한다. 이번 단계는 초안 검토 화면이며 일괄 자동 승인을 제공하지 않는다. 질문 버튼은 해당 부품의 질문을 표시하고, 실제 상담을 전송한 것처럼 표시하지 않는다.

조립 서비스는 30,000원이며 화면 공통 원천 `mockups/shared/assembly-fee.js`를 재사용한다. 기존 조립비 포함 상품에 중복 가산하지 않는다.

다음 차례: 제조사 대조와 충돌 검수 → 구성별 선택 이유 → 승인된 알뜰/추천 구성에 상세 연결.

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
