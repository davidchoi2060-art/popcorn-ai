# 구성 설명 DB 인계 — 2026-09-28

## 반영 상태

Cloud SQL에 0117 스키마와 구성 설명을 실제 저장하고 원본과 전수 대조했다. 고객 추천·공개는 변경하지 않았다. 상세 결과: 로컬 outputs/catalog-db-20260928/verification.json. 숫자는 이 검증 파일 또는 DB를 다시 조회한다.

## 재현 명령

- `.venv/Scripts/python tools/import_pc_configuration_copy.py db/migrations/data/pc_configuration_catalog_20260928.json --parts db/migrations/data/pc_configuration_parts_20260928.json --output <검증폴더>`: 기본 dry-run.
- 최초 저장은 `--apply`. 기존 변경 구성은 검토 후 `--replace --apply`; 이전 데이터는 history와 별도 백업에 보존한다.
- `tools/repair_catalog_copy.py db/migrations/data/part_copy_corrections_20260928.json`: 부품 설명 변경 계획 확인. 이미 적용됐으면 0건. `--apply --backup <새 파일>` 사용 시 원본 해시가 일치하는 draft만 갱신한다.
- `api/pc_configuration_copy.py`: 관리자 목록/상세 조회. source hash와 설명 hash 차이 및 미해결 사항을 needs_review로 반환한다. 2개 조립 전용 부품은 독립 products 행이 없어도 실제 BOM과 연결된다.

## 미완료 항목

110899 PM9A1 256GB의 출고 P/N, 113685 H610M H V2 D4의 출고 리비전 확인. 제조사 표의 조건부 속도와 실제 지원 단자를 혼동하지 않는다. 관련 구성은 별도 재검토 표시가 유지된다. parts DB 스펙 엔진의 수치를 자동 수정하지 않았으며 이번 보완은 설명 자료다.

LLM 상담 새 계약, 프로그램별 성능 근거 보완, 고객 공개는 후속이다. 현재 관리자 API는 설명 검토용이며 read-only. 등록 가격은 2026-09-28 관측값이다.

## 검증

부품/구성 단위 테스트, BOM·조립비·가격·FK 전수 대조. 실제 DB에서 설명 변경 감지·중복 실행·가격 변경의 이력 보존을 트랜잭션 롤백으로 확인했다. 원래 상품과 재고 이력 건수는 동일하다.
