# 관리자 화면 통합 담당 범위 · 2026-10-08

중헌님 지시(2026-10-08 21:20 KST): 관리자 화면과 고객 화면 담당을 나눈다. 이 문서는 관리자 화면 통합 담당(Claude)과 고객 화면 통합 담당(Claude, PR #18)이 같은 파일을 동시에 고치지 않도록 경계를 정하고, 관리자 화면에서 끝까지 이어지지 않는 흐름을 적는다. 기준 커밋 `d2c66b3`(main), PR #10 head `356df8a`.

## 1. 파일 경계

| 구역 | 관리자 담당 | 고객 담당 |
|---|---|---|
| 템플릿 | `templates/admin/**` 전부 | 없음 |
| 화면 JS·CSS | `mockups/shared/admin*`, `mockups/shared/admin2/**`, `mockups/shared/pc-*`, `parts-management.*`, `part-explanations.*`, `configuration-consultation.js`, `hub-fab.js`, `ui-chart.js`·`ui-choices.js`·`ui-daterange.js`·`ui-list.js` | `mockups/mvp3/**`, `mockups/mvp2/**`, `mockups/mvp1/**`(백업, 수정 없음) |
| 서버 | `api/admin_*.py`, `api/admin_ui_*.py`, `api/pc_configuration_*.py`, `api/pc_customer_publication.py`, `api/part_explanation_approval.py`·`api/part_photo_approval.py`·`api/pc_publication_source_reader.py`(PR #10), `api/pricing*.py`, `api/catalog_*.py`, `api/sale_readiness_*.py` | `api/talk*.py`, `api/grid_public.py`, `api/sold_reco.py`, `api/mvp3_saved_quotes.py`, `api/customer_*.py`, `api/my_*.py`, `api/candidates.py`, `api/recommend.py`, `api/swap.py` |
| 테스트 | 위 관리자 파일을 대상으로 하는 `tests/*` | `mockups/mvp3/tests/**`와 고객 파일을 대상으로 하는 `tests/*` |

공용 파일은 한쪽이 고치기 전에 PR #2에 먼저 알린다: `design-system/tokens.css`, `mockups/shared/fonts/**`, `ui-progress.js`, `su-icons.js`, `auth.js`, `assembly-fee.js`, `fmt-time.js`, `api/main.py`, `api/db.py`.

경계 파일 하나: `api/customer_sold_offer_read.py`는 고객 담당이 고치고, 그 파일이 읽는 공개 승인 기록(`pc_customer_publication.read_current`)의 쓰기 쪽은 관리자 담당이 만든다. 응답 필드 계약을 바꿀 때는 두 담당이 PR #2에서 먼저 맞춘다.

화면 문구(`templates/admin/**`의 문장, 버튼명)와 시안은 Codex 담당이다. 관리자 담당 Claude는 문구 파일을 Codex와 동시에 고치지 않고, 서버·연결 코드와 Codex가 넘긴 문구의 적용만 한다.

## 2. 끝까지 이어지지 않는 관리자 흐름

| # | 흐름 | 지금 상태(근거) | 막힌 곳 |
|---|---|---|---|
| A1 | 구성 검토 → 부품 설명 승인 → 부품 사진 승인 → 고객 공개 | 검토 저장은 있다(`pc_configuration_review.py` GET/PUT). 설명·사진 승인과 공개 승인은 코어만 있고 HTTP 경로·화면이 없다(`part_explanation_approval.py`·`part_photo_approval.py`는 PR #10에만, `pc_customer_publication.py`는 "no routes"). 승인 표는 main에 있다(마이그레이션 0130·0131). | 운영자가 공개를 승인할 방법이 없어 고객 판매 구성 읽기(`customer_sold_offer_read`)에 나갈 것이 없다 |
| A2 | 공개 원천 읽기 연결 | `pc_customer_publication`이 `source_reader=None`이면 승인을 거부한다. 운영 원천 읽기(`pc_publication_source_reader.py`)는 PR #10에만 있다 | A1의 공개 승인 경로가 생겨도 원천 읽기가 연결돼야 승인이 성립한다 |
| A3 | 부품 설명 관리 화면 | `/admin2/part-explanations`는 조회 전용(GET 두 개). 승인·반려 버튼과 API가 없다 | A1의 설명 승인 단계를 화면에서 할 수 없다 |
| A4 | 마진 정책 저장 → 판매가 반영 | 전역값 저장(`POST /api/admin/pricing-settings`)과 분류별 예외(`PUT /api/admin/categories/{cid}/margin`)는 동작한다. 분류별 예외는 대량 재산정에만 적용되고 가격 검토 승인(`admin_price_review.py`)·단가표 반영(`admin_price_import.py`)은 `resolve_margins`를 부르지 않는다(화면이 경고로 적어 둠) | 같은 상품이 경로에 따라 다른 마진으로 판매가가 정해진다. 의도인지 결정이 없다 |
| A5 | 마진 정책 화면 안내 | 오른쪽 안내가 "판매가 재산정 — 화면 없음"이라 적는데 `/admin2/reprice`는 이미 있고 메뉴에도 연결돼 있다 | 운영자가 재산정 화면을 찾지 못한다(문구라 Codex 담당) |
| A6 | 카탈로그 반영 후 사람 판단 보존 | 일괄 등록 드라이런·적용은 동작한다. 재적재 때 잠금이 매입가·판매가만 지켜 분류·검수 회부가 되돌아간다(CLAUDE.md §데이터 잠금 항목) | 손으로 고친 분류와 검수 회부가 다음 적재에서 지워진다 |
| A7 | 몰 실시간 조회 | 쇼핑몰 동기화의 「지금 확인」, 판매가 관리의 「지금 물어보기」가 비활성(실서비스 조회 API 없음) | 몰 가격·상태를 화면에서 확인할 수 없다 |
| A8 | 격자 재생성 | 상품 매트릭스 관리의 재생성 버튼 셋이 비활성(재생성 API 없음) | 실패 칸을 화면에서 다시 만들 수 없다 |
| A9 | 상품 등록 일부 | 상품 등록의 두 구역이 "API 미연결", 상품 관리 일괄 동작 넷(CSV 내려받기·일괄 삭제·일괄 노출/숨김·행 복사)이 "향후 사용예정" | 화면에 보이지만 할 수 없는 동작이다 |

유입 성과의 몰 구간(인계 → 클릭 → 구매)과 접근 IP 목록, 용도 신설은 외부 데이터나 결정이 필요한 항목이라 이 목록에서 뺐다.

## 3. 진행 순서 제안

A1·A2·A3를 하나의 흐름으로 먼저 잇는다(고객 판매 구성 공개의 전제). PR 하나당 한 항목 규칙에 따라 ① 설명 승인 HTTP 경로 ② 사진 승인 HTTP 경로 ③ 공개 승인 HTTP 경로 + 원천 읽기 연결 ④ 화면 연결 순으로 나눈다. PR #10의 코어 세 파일은 PC 원본이라 PR #10 병합 뒤 그 위에서 시작한다. A4는 중헌님 결정이 필요하다. A5는 Codex 문구 요청, A6~A9는 배정을 받아 진행한다.
