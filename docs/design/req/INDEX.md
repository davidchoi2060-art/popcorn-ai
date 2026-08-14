# 화면 요구사항 정의서 목차 — LNB 순서

> 사장님이 UI 디자인을 공유하실 때 **다음 차례가 무엇인지 바로 누를 수 있게** 만든 목차다.
> 순서는 좌측 메뉴 정본(`api/admin_nav.py`) 그대로다. 상태는 이 파일이 아니라 실제로
> 재서 안다 — `git status` · `/admin2/*` 라우트 존재 여부.
>
> 상태 표기: **지음** = admin2에 구축됨(라우트가 있다) · **디자인** = 승인 디자인 있음(구축 대기) ·
> **정의서** = 요구사항만 있음 · **없음** = 아직 ·
> **재정의** = 지어졌으나 다시 정의하기로 함 · **셸만** = 새 사이드바에 옛 본문이 붙은 상태 ·
> **구축 중 / 신설 대기** = 승인 디자인을 받아 짓는 중 / 아직 라우트 없음 ·
> **재구축 중 / 재구축 대기** = 이미 지어진 화면을 승인 디자인대로 다시 짓는 중 / 대기
>
> ⚠ **범례에 없는 말을 표에 쓰지 않는다** — 2026-08-14 실측 시점에 표는 「구축 중 ·
> 재구축 대기 · 재구축 중 · 신설 대기」를 쓰는데 범례에는 넷 다 없었다. 상태 어휘가
> 범례 밖으로 자라면 같은 말을 사람마다 다르게 읽는다.
>
> **「셸만」은 완료가 아니다.** 셸 정본화(2026-08-13) 때 본문 재설계를 범위 밖에 뒀기
> 때문에 새 껍데기에 옛 Phoenix 본문이 붙은 화면이 있다.
>
> ⚠ **2026-08-14 정정** — 처음에 넷을 「셸만」으로 일괄 표기했으나 **실측 결과 둘뿐이었다**
> (대시보드 · 상품 관리). **조립 호환 지도와 조립 사양 표준은 Phoenix 더미가 아니라 실 API에
> 완전히 연동된 화면**이다(정의서 작성 중 실호출로 확인). 셸 정본화 보고를 화면별로 확인하지
> 않고 하네스가 넷을 묶어 적은 것이 원인이다 — **상태는 적지 말고 재서 안다**는 규칙을
> 목차 자신이 어겼다.

## 1. 대시보드

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 1 | **대시보드** | [req-dashboard.md](req-dashboard.md) | `dc-dashboard-3안.html` | **재구축 중** (ADM-DASH-010 · UX-22 → 1b) |

## 2. 상품관리

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 2 | **상품 분류 관리** | [req-product-category.md](req-product-category.md) | `dc-product-category.html` | **지음** (`/admin2/categories` · ADM-CAT-010) |
| 3 | **상품 관리** | [req-products.md](req-products.md) | `dc-products-3안.html` | **재구축 대기** (ADM-PRD-010 · UX-23 → 1a) |
| 4 | **상품 분류 매핑** | [req-product-category-map.md](req-product-category-map.md) | `dc-product-category-map.html` | **지음** (`/admin2/category-mapping`) |
| 5 | **상품 일괄 등록** | [req-product-bulk-import.md](req-product-bulk-import.md) | `dc-product-bulk-import.html` | **구축 중** (ADM-CSV-010 · UX-21 → 1b) |
| 6 | **삭제 상품 조회** | [req-product-deleted.md](req-product-deleted.md) | `dc-product-deleted-2안.html` | **신설 대기** (ADM-DEL-010 · UX-26 → 1b + 빈 상태 1c) |

## 3. 상품사양관리

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 7 | **조립 호환 지도** | [req-build-map.md](req-build-map.md) | `dc-build-map-v2.html` | **재구축 대기** (`/admin2/build-map` · UX-20 → v2 클릭 고정) |
| 8 | **조립 사양 표준** | [req-spec-standard.md](req-spec-standard.md) | `dc-spec-standard-2안.html` | **재구축 대기** (`/admin2/spec-standard` · UX-24 → 1b) |
| 9 | 상품 사양 정의 | [req-spec-field-defs.md](req-spec-field-defs.md) | — | 정의서 |
| 10 | **상품 사양 검수** | [req-admin2-reviews-2026-08-13.md](../req-admin2-reviews-2026-08-13.md) | `dc-review-screen.html` | **지음** (`/admin2/reviews`) |
| 11 | 조립 호환 규칙 | [req-compat-rules.md](req-compat-rules.md) | — | 정의서 |
| 12 | 용도별 최소 사양 | [req-usage-floors.md](req-usage-floors.md) | — | 정의서 |
| 13 | 부품 등급 관리 | [req-part-grade.md](req-part-grade.md) | — | 정의서 |
| 14 | 추천 기준 설정 | [req-policy-weights.md](req-policy-weights.md) | — | 정의서 |
| 15 | 추천 가능 재고 현황 | [req-candidate-pool.md](req-candidate-pool.md) | — | 정의서 |
| 16 | 견적 상담 기록 | [req-consult-sessions.md](req-consult-sessions.md) | — | 정의서 |
| 17 | 부품 교체 · 클릭 기록 | [req-swap-click-logs.md](req-swap-click-logs.md) | — | 정의서 |

## 4. 매입 · 소싱

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 18 | 공급처 | [req-suppliers.md](req-suppliers.md) | — | 정의서 |
| 19 | 매입 견적(용산) | [req-sourcing-quote.md](req-sourcing-quote.md) | — | 정의서 |
| 20 | 단가표 반영 | [req-price-sheet-apply.md](req-price-sheet-apply.md) | — | 정의서 |

## 5. 판매가

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 21 | 판매가 관리 | [req-sale-price.md](req-sale-price.md) | — | 정의서 |
| 22 | 가격 검토 대기 | [req-price-review-queue.md](req-price-review-queue.md) | — | 정의서 |
| 23 | 가격 이력 | [req-price-history.md](req-price-history.md) | — | 정의서 |

## 6. 인계 · 성과

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 24 | 쇼핑몰 동기화 | [req-mall-sync.md](req-mall-sync.md) | — | 정의서 |
| 25 | 인계 기록 | [req-handoff-log.md](req-handoff-log.md) | — | 정의서 |
| 26 | 유입 성과 | [req-funnel-performance.md](req-funnel-performance.md) | — | 정의서 |

## 7. AI 관리

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 27 | **작업 현황판** | [req-dash.md](req-dash.md) | `dc-dash.html` | **재구축 대기** (`/admin2/dash` · UX-25 단일안) |
| 28 | 웹 사양 채움 | [req-spec-fill.md](req-spec-fill.md) (구 [방향 제안](../spec-fill-ui-direction-2026-08-13.md) — 폐기) | — | **재정의** (`/admin2/spec-fill` 존재) |
| 29 | **AI 작업 설정** | [req-ai-task-settings.md](req-ai-task-settings.md) | `dc-ai-task-settings.html` | **지음** (`/admin2/ai-task-settings`) |
| 30 | **AI 연동 설정** | [req-ai-integration.md](req-ai-integration.md) | `dc-ai-integration.html` | **지음** (`/admin2/ai-integration`) |
| 31 | **AI 사용량 · 비용** | [req-ai-usage-cost.md](req-ai-usage-cost.md) | `dc-ai-usage-cost.html` | **지음** (`/admin2/ai-usage-cost`) |
| 32 | **AI 응답 기록** | [req-ai-response-log.md](req-ai-response-log.md) | `dc-ai-response-log.html` | **지음** (`/admin2/ai-response-log`) |
| 33 | **운영 도우미 설정** | [req-ops-assistant.md](req-ops-assistant.md) | `dc-ops-assistant.html` | **지음** (`/admin2/ops-assistant`) |

## 8. 시스템

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 34 | **오픈 단계 설정** (구 「운영 전환 설정」) | [req-ops-switch.md](req-ops-switch.md) | `dc-ops-stage.html` | **지음** (`/admin2/ops-settings` · A-34) |
| 35 | **운영자 · 권한** | [req-operators-roles.md](req-operators-roles.md) | `dc-operators-roles.html` | **지음** (`/admin2/operators`) |
| 36 | **작업 기록** | [req-activity-logs.md](req-activity-logs.md) | `dc-activity-logs.html` | **지음** (`/admin2/activity-logs`) |
| 37 | **엑셀 다운로드 관리** | [req-excel-export.md](req-excel-export.md) | `dc-excel-export.html` | **지음** (`/admin2/excel-exports`) |

---

## 디자인 원안 (사장님 확정본)

| # | 화면 | 파일 | 구축 |
|---|------|------|------|
| 2 | 상품 분류 관리 | [dc-product-category.html](../dc-product-category.html) | 지음 |
| 4 | 상품 분류 매핑 | [dc-product-category-map.html](../dc-product-category-map.html) | 지음 |
| 10 | 상품 사양 검수 | [dc-review-screen.html](../dc-review-screen.html) | 지음 |
| 29 | AI 작업 설정 | [dc-ai-task-settings.html](../dc-ai-task-settings.html) | 지음 |
| 30 | AI 연동 설정 | [dc-ai-integration.html](../dc-ai-integration.html) | 지음 |
| 31 | AI 사용량 · 비용 | [dc-ai-usage-cost.html](../dc-ai-usage-cost.html) | 지음 |
| 32 | AI 응답 기록 | [dc-ai-response-log.html](../dc-ai-response-log.html) | 지음 |
| 33 | 운영 도우미 설정 | [dc-ops-assistant.html](../dc-ops-assistant.html) | 지음 |
| 34 | 오픈 단계 설정 | [dc-ops-stage.html](../dc-ops-stage.html) | 지음 |
| 35 | 운영자 · 권한 | [dc-operators-roles.html](../dc-operators-roles.html) | 지음 |
| 36 | 작업 기록 | [dc-activity-logs.html](../dc-activity-logs.html) | 지음 |
| 37 | 엑셀 다운로드 관리 | [dc-excel-export.html](../dc-excel-export.html) | 지음 |
| 7 | 조립 호환 지도 **(v2 · 정본)** | [dc-build-map-v2.html](../dc-build-map-v2.html) | 재구축 대기 · UX-20 → 클릭 고정 |
| 7 | 조립 호환 조감도 (3안 비교본 — v2로 대체됨) | [dc-build-map-3안.html](../dc-build-map-3안.html) | 참고용 |
| 1 | 대시보드 **(3안 비교본)** | [dc-dashboard-3안.html](../dc-dashboard-3안.html) | 재구축 중 · UX-22 → 1b |
| 3 | 상품 관리 **(3안 비교본)** | [dc-products-3안.html](../dc-products-3안.html) | 재구축 대기 · UX-23 → 1a |
| 5 | 상품 일괄 등록 | [dc-product-bulk-import.html](../dc-product-bulk-import.html) | 구축 중 · UX-21 → 1b |
| 6 | 삭제 상품 조회 **(2안 + 빈 상태)** | [dc-product-deleted-2안.html](../dc-product-deleted-2안.html) | 신설 대기 · UX-26 → 1b + 빈 상태 1c |
| 8 | 조립 사양 표준 **(2안 비교본)** | [dc-spec-standard-2안.html](../dc-spec-standard-2안.html) | 재구축 대기 · UX-24 → 1b |
| 27 | 작업 현황판 **(단일안)** | [dc-dash.html](../dc-dash.html) | 재구축 대기 · UX-25 |

**7번은 완성본이 아니라 「3안 비교본」이다.** 지도형(1a)·진단형(1b)·매트릭스형(1c) 셋이
한 캔버스에 있다. 사장님이 **셋을 다 탭으로 두고 운영자가 고르게** 하기로 확정했다(UX-20).

**1번도 「3안 비교본」이다.** 큐 목록형(1a)·카드 그리드형(1b)·브리핑형(1c) 셋이 한 캔버스에
있고, 셋은 **「지금 할 일」의 표현 방식만** 다르다. 사장님이 **1b 카드 그리드형**으로 확정했다
(UX-22). 조감도와 달리 여기서는 **하나만 고른다** — 대시보드는 첫 화면이라 선택지를 주면
오히려 판단을 미루게 된다.

> ⚠ **`UX-26` 은 아직 결정 로그에 없다** (2026-08-14 기록자 실측). 6번(삭제 상품 조회)의
> 상태가 `UX-26 → 1b + 빈 상태 1c` 를 인용하는데 `docs/decisions/decision-log.md` 에 그
> 항목이 없다(현재 최대는 `UX-25`). 승인 디자인 `dc-product-deleted-2안.html` 머리에
> 사장님 공통 확정 사항이 적혀 있으므로 **결정은 있었고 기록만 안 된 것으로 보이나,
> 기록자가 임의로 적지 않는다** — 무엇이 확정됐는지 정하는 자리는 사장님·하네스다.
> 로그에 항목이 서기 전까지 이 인용은 **가리키는 곳이 없는 번호**다.

## 이 목차를 쓰는 법 (하네스 규약)

사장님이 화면 UI를 공유하실 때마다, 하네스는 **그 화면의 정의서 링크와 다음 차례
두세 개를 함께** 올린다. 사장님이 위로 스크롤해 찾지 않게 하기 위해서다
(2026-08-13 사장님 지시).
