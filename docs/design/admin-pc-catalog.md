# 조립PC 제품군 관리자 목록 · 2026-09-29

사용자 승인 시안 03-split-v2를 실제 관리자 셸에 적용했다. 메뉴는 상품관리 → 조립PC 제품군이며 `/admin2/pc-configurations`로 진입한다. 목록과 오른쪽 요약, 전체 구성·부품 상세 대화상자, 검색 및 출처/정보검토/공개 필터, 서버 페이지네이션, 현재 검색 결과 XLSX 내보내기를 제공한다.

## 데이터의 의미

- `pc_configurations`, `pc_configuration_parts`, `pc_configuration_offers`, `product_explanations`를 읽는다. 이번 변경에는 DB 쓰기나 마이그레이션이 없다.
- 정보 검토는 기존 `part_needs_review`와 같은 판정이다. 설명 해시·원천 사양 변경·검토 이슈를 검사한다. 「정보 변경 없음」은 호환성 검증 완료가 아니다.
- 호환성 최종 검수 결과는 아직 연결하지 않았다. 고객 공개는 기존 API 계약대로 false다. 화면 필터가 공개 승인을 대신하지 않는다.
- 기준 가격은 저장된 offer의 최저 가격이며 기준일·포함 조건을 표시한다. 조립비를 다시 더하지 않는다. 상세 부품의 가격은 현재 DB 개별 판매가로 완제품 가격의 분해값이 아니다.
- 사진은 정확한 BOM의 케이스 부품에 연결된 기존 GCS 이미지다. 「케이스 이미지」로 표시한다. 별도 생성 중인 조립 완성 예시 이미지는 아직 연결하지 않았다.

## 다음 단계

신규 구성 등록, 구성 수정, 호환성 검수 결과 연결, 공개 승인, 고객 확정 견적의 제품군 등록은 후속 범위다. 「추천 테스트」는 기존 `/admin2/configuration-consultation`으로 연결하고 상세 요약에는 두지 않는다.

## 검증

`python -m unittest tests.test_pc_catalog_admin tests.test_pc_configuration_copy tests.test_part_explanations tests.test_configuration_consultation -q` 및 JS 구문 검사. 필터 조합·페이지 총수·비공개 경계·XLSX 라우트 우선순위·엑셀 수식 주입 방지 검증을 포함한다.
로컬 브라우저에서 실 DB 목록, 신규 15건, 정보 확인 필터의 빈 결과, 다음 페이지, P97909 검색, 엑셀 다운로드, 전체 부품과 CPU 사양 펼치기를 확인했다. 자세한 시각 검토는 루트 `design-qa.md`.
