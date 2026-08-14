# 화면 요구사항 정의서 목차 — LNB 순서

> 사장님이 UI 디자인을 공유하실 때 **다음 차례가 무엇인지 바로 누를 수 있게** 만든 목차다.
> 순서는 좌측 메뉴 정본(`api/admin_nav.py`) 그대로다. 상태는 이 파일이 아니라 실제로
> 재서 안다 — `git status` · `/admin2/*` 라우트 존재 여부.
>
> 상태 표기: **지음** = admin2에 구축됨 · **디자인** = 승인 디자인 있음(구축 대기) ·
> **정의서** = 요구사항만 있음 · **없음** = 아직 ·
> **재정의** = 지어졌으나 다시 정의하기로 함 · **셸만** = 새 사이드바에 옛 본문이 붙은 상태
>
> **「셸만」은 완료가 아니다.** 셸 정본화(2026-08-13) 때 본문 재설계를 범위 밖에 뒀기
> 때문에 넷은 새 껍데기에 옛 Phoenix 본문이 붙어 있다. admin2 전면 개편·재구축 전제에서
> 이 넷도 결국 디자인이 필요하다.

## 1. 대시보드

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 1 | 대시보드 | — | — | **셸만** (`/admin2/`) |

## 2. 상품관리

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 2 | **상품 분류 관리** | [req-product-category.md](req-product-category.md) | `dc-product-category.html` | **구축 중** (ADM-CAT-010) |
| 3 | 상품 관리 | — | — | **셸만** (`/admin2/products`) |
| 4 | **상품 분류 매핑** | [req-product-category-map.md](req-product-category-map.md) | `dc-product-category-map.html` | **지음** (`/admin2/category-mapping`) |
| 5 | 상품 일괄 등록 | [req-product-bulk-import.md](req-product-bulk-import.md) | — | 정의서 |
| 6 | 삭제 상품 조회 | [req-product-deleted.md](req-product-deleted.md) | — | 정의서 |

## 3. 상품사양관리

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 7 | 조립 호환 지도 | — | — | **셸만** (`/admin2/build-map`) |
| 8 | 조립 사양 표준 | — | — | **셸만** (`/admin2/spec-standard`) |
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
| 27 | 작업 현황판 | — | — | 지음 (`/admin2/dash`) |
| 28 | 웹 사양 채움 | [req-spec-fill.md](req-spec-fill.md) (구 [방향 제안](../spec-fill-ui-direction-2026-08-13.md) — 폐기) | — | **재정의** (`/admin2/spec-fill` 존재) |
| 29 | **AI 작업 설정** | [req-ai-task-settings.md](req-ai-task-settings.md) | `dc-ai-task-settings.html` | **디자인** (ADM-AI-030) |
| 30 | **AI 연동 설정** | [req-ai-integration.md](req-ai-integration.md) | `dc-ai-integration.html` | **디자인** (ADM-AI-040) |
| 31 | **AI 사용량 · 비용** | [req-ai-usage-cost.md](req-ai-usage-cost.md) | `dc-ai-usage-cost.html` | **디자인** (ADM-AI-050) |
| 32 | **AI 응답 기록** | [req-ai-response-log.md](req-ai-response-log.md) | `dc-ai-response-log.html` | **디자인** (ADM-AI-060) |
| 33 | **운영 도우미 설정** | [req-ops-assistant.md](req-ops-assistant.md) | `dc-ops-assistant.html` | **디자인** (ADM-AI-070) |

## 8. 시스템

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 34 | **오픈 단계 설정** (구 「운영 전환 설정」) | [req-ops-switch.md](req-ops-switch.md) | `dc-ops-stage.html` | **디자인** (ADM-OPS-010 · A-34) |
| 35 | **운영자 · 권한** | [req-operators-roles.md](req-operators-roles.md) | `dc-operators-roles.html` | **디자인** (ADM-SYS-020) |
| 36 | **작업 기록** | [req-activity-logs.md](req-activity-logs.md) | `dc-activity-logs.html` | **디자인** (ADM-SYS-030) |
| 37 | **엑셀 다운로드 관리** | [req-excel-export.md](req-excel-export.md) | `dc-excel-export.html` | **디자인** (ADM-SYS-050) |

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
| 34 | 오픈 단계 설정 | [dc-ops-stage.html](../dc-ops-stage.html) | 대기 |
| 35 | 운영자 · 권한 | [dc-operators-roles.html](../dc-operators-roles.html) | 대기 |
| 36 | 작업 기록 | [dc-activity-logs.html](../dc-activity-logs.html) | 대기 |
| 37 | 엑셀 다운로드 관리 | [dc-excel-export.html](../dc-excel-export.html) | 대기 |

사장님 프로젝트에는 아직 안 가져온 디자인이 하나 더 있다 — **「조립 호환 조감도」**(`조립 호환 조감도.dc.html`).
7번 「조립 호환 지도」에 해당하는 것으로 보이나 **확인 전이라 가져오지 않았다.**

## 이 목차를 쓰는 법 (하네스 규약)

사장님이 화면 UI를 공유하실 때마다, 하네스는 **그 화면의 정의서 링크와 다음 차례
두세 개를 함께** 올린다. 사장님이 위로 스크롤해 찾지 않게 하기 위해서다
(2026-08-13 사장님 지시).
