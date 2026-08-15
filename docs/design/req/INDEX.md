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
>
> ⚠ **2026-08-15 발견 — 「마진 정책」화면이 이 목차에 아예 없다.** 실측:
> `templates/admin/margin_policy.html.j2` · `api/admin_ui_margin_policy.py`
> (라우트 `/admin2/margin-policy`) · `docs/design/req/req-margin-policy.md` ·
> `docs/design/spec-margin-policy.md` 넷 다 존재하는데, 이 목차에도 `api/admin_nav.py`
> (「판매가」 그룹 3항목뿐)에도 행이 없다. **행을 추가하려면 화면 ID·그룹 내 순서를
> 정해야 하는데 그건 기계적 편집 범위 밖이라 여기서 임의로 채우지 않는다** — 하네스
> 확인 필요(위 §① 「가격 검토 대기」 정정과 같은 병이지만, 이건 상태가 아니라 **행
> 자체가 없는** 경우라 한 단계 더 나쁘다).

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
| 6 | **삭제 상품 조회** | [req-product-deleted.md](req-product-deleted.md) | `dc-product-deleted-2안.html` | **구축 중** (ADM-DEL-010 · UX-26 → 1b + 빈 상태 1c · 2026-08-15 실측: 템플릿·라우트 있음, 검증 전) |

## 3. 상품사양관리

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 7 | **조립 호환 지도** | [req-build-map.md](req-build-map.md) | `dc-build-map-v2.html` | **재구축 대기** (`/admin2/build-map` · UX-20 → v2 클릭 고정) |
| 8 | **조립 사양 표준** | [req-spec-standard.md](req-spec-standard.md) | `dc-spec-standard-2안.html` | **재구축 중** (`/admin2/spec-standard` · UX-24 → **1a**) |
| 9 | **상품 사양 정의** | [req-spec-field-defs.md](req-spec-field-defs.md) | `dc-spec-field-defs-2안.html` | **디자인** (ADM-PRD-050 · UX-27 → 1a) |
| 10 | **상품 사양 검수** | [req-admin2-reviews-2026-08-13.md](../req-admin2-reviews-2026-08-13.md) | `dc-review-screen.html` | **지음** (`/admin2/reviews`) |
| 11 | **조립 호환 규칙** | [req-compat-rules.md](req-compat-rules.md) · [req-compat-required.md](req-compat-required.md)(「필수 사양 안내」 탭) | `dc-compat-rules-2안.html` | **지음** (`/admin2/compat-rules` · ADM-ENG-010 · UX-28 → 1b · 커밋 `3ffe740` · 메뉴 연결 `68daf6e`. **+2026-08-15: 「필수 사양 안내」 탭 신설**(`spec-compat-required.md` 계약 — 결정 로그 ⑤ 설계 간극을 채움) · 확인자 2차 검증 결함 0 · 커밋 `89019e2`. 메뉴는 안 바뀜 — 기존 화면 안 탭 추가) |
| 12 | **용도별 최소 사양** | [req-usage-floors.md](req-usage-floors.md) | `spec-usage-floors.md`(계약) | **구축 중** (ADM-ENG-040 · UX-29 → 두 안 참고 · 검증 통과 이력 있으나 그 뒤 수정분 재검증 전) |
| 13 | **부품 등급 관리** | [req-part-grade.md](req-part-grade.md) | `spec-part-grade.md`(계약) | **지음** (`/admin2/part-grade` · ADM-ENG-050 · UX-30 → 1a + 1b 우측 입력 · 확인자 검증 통과 · 커밋 `112c5a7` · 메뉴 연결 `7949c98`) |
| 14 | **추천 기준 보기** (구 「추천 기준 설정」) | [req-policy-weights.md](req-policy-weights.md) | `spec-policy-weights.md`(계약) | **지음** (`/admin2/policy-weights` · ADM-ENG-020 · UX-31 → 1a · 조회 전용 · 개명 · 확인자 검증 통과 · 커밋 `3ffe740` · 메뉴 연결 `68daf6e`) |
| 15 | **추천 가능 재고 현황** | [req-candidate-pool.md](req-candidate-pool.md) | `spec-candidate-pool.md`(계약) | **구축 중** (ADM-ENG-030 · UX-32 → 1a · 조회 전용 · 템플릿은 확인자 검증 통과·커밋 `ec4b7ba`, 라우트 파일이 지금 다른 작업으로 미커밋 수정 중이라 메뉴 미연결) |
| 16 | **견적 상담 기록** | [req-consult-sessions.md](req-consult-sessions.md) | `spec-consult-sessions.md`(계약) | **지음** (`/admin2/consult-sessions` · ADM-ORD-010 · UX-33 → 1a + 우측 서랍 · 재검증 «결함 0» · 커밋 `d792434` · 메뉴 연결 `68daf6e`) |
| 17 | 부품 교체 · 클릭 기록 | [req-swap-click-logs.md](req-swap-click-logs.md) | — | **구축 중** (2026-08-15 실측: 템플릿·라우트 있음, 검증 전) |

## 4. 매입 · 소싱

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 18 | 공급처 | [req-suppliers.md](req-suppliers.md) | — | 정의서 |
| 19 | 매입 견적(용산) | [req-sourcing-quote.md](req-sourcing-quote.md) | — | 정의서 |
| 20 | 단가표 반영 | [req-price-sheet-apply.md](req-price-sheet-apply.md) | — | 정의서 |

## 5. 판매가

> ⚠ **번호는 `api/admin_nav.py` 순서를 그대로 따르되, 새로 끼워 넣은 화면은 뒤 섹션
> 전체를 밀어 renumbering 하지 않고 `22B`처럼 옆에 붙인다** — 이 목차의 번호를 그대로
> 인용하는 아래 「디자인 원안」·「계약 요약」 두 표를 전부 손대는 것은 이번 작업 범위
> 밖이라 판단해 미뤘다(연쇄 갱신 위험 대비 최소 변경).
>
> **`docs/design/req/req-reprice.md` §②의 판매가 그룹 번호**(010 가격 검토 대기 ·
> 020 마진 정책 · 030 가격 이력 · 040 단가표 일일 반영 · 050 판매가 재산정 ·
> 060 판매가 관리)와 이 표의 번호는 **다른 채번 체계다** — 저건 화면 ID 접두어
> `ADM-PRC-0nn`의 순번이고 이 표는 LNB 노출 순서다. `040`(단가표 일일 반영)은
> 이 표에서는 **20번 "단가표 반영"**(매입·소싱 그룹)과 같은 화면이다 — 그룹이
> 다르게 잡혀 있을 뿐 화면은 하나다.

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 21 | 판매가 관리 | [req-sale-price.md](req-sale-price.md) | — | **구축 중** (2026-08-15 실측: 템플릿·라우트 있음, 검증 통과 이력 있으나 그 뒤 수정분 재검증 전) |
| 22 | 가격 검토 대기 | [req-price-review-queue.md](req-price-review-queue.md) | `spec-price-review.md`(계약) | **지음** (`/admin2/price-review` · ADM-PRC-010 · 확인자 검증 통과 · 메뉴 연결 `879ee61` · ⚠ 아직 미커밋) |
| 22B | 마진 정책 | [req-margin-policy.md](req-margin-policy.md) | `spec-margin-policy.md`(계약) | **지음** (`/admin2/margin-policy` · ADM-PRC-020 · 확인자 2차 검증 결함 0 · 커밋 `a4d5d44` · 메뉴 연결 `879ee61`) |
| 23 | 가격 이력 | [req-price-history.md](req-price-history.md) · [spec-price-history.md](../spec-price-history.md)(2026-08-15 「(신규)」 표기 정정) | — | **지음** — 구현 `/admin2/price-history`(커밋 `140a5ba`·`77dbbef`·`bdf7e7c`) · 검증 확인자 브라우저 실측 통과 3라운드(①7행 3종 판정·ref_id null 실값·401/400/404 경계·768px ②마이그레이션 0050 「비움」 표시 — DB↔DOM 5행 대조·new_price=0 실데이터로 0과 NULL 구분 확인 ③「부품 종류」 확인 중… 고정 결함 — 10ms 폴링 프레임 단위 캡처로 재발 0·정상 로딩 노출은 유지 확인) · 계약 정정 `8e35508` · 연결 `api/admin_nav.py` `91dd3a1` |
| 23B | 판매가 재산정 | [req-reprice.md](req-reprice.md) | — | **구축 중** (ADM-PRC-050·경로 `/admin2/reprice` 둘 다 req-reprice.md 자신이 「제안」·「관례상」으로 표시 — 확정 아님. 2026-08-15 제작 착수) |

## 6. 인계 · 성과

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 24 | 쇼핑몰 동기화 | [req-mall-sync.md](req-mall-sync.md) | — | **구축 중** (2026-08-15 실측: 템플릿·라우트 있음, 검증 전) |
| 25 | 인계 기록 | [req-handoff-log.md](req-handoff-log.md) | — | **구축 중** (2026-08-15 실측: 템플릿·라우트 있음, 검증 통과 이력 있으나 그 뒤 수정분 재검증 전) |
| 26 | 유입 성과 | [req-funnel-performance.md](req-funnel-performance.md) | — | 정의서 |

## 7. AI 관리

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 27 | **작업 현황판** | [req-dash.md](req-dash.md) | `dc-dash.html` | **재구축 중** (`/admin2/dash` · UX-25 단일안 · 2026-08-15 실측: 「대기」였는데 실제로는 작업 중이었다) |
| 28 | 웹 사양 채움 | [req-spec-fill.md](req-spec-fill.md)(2026-08-15 전면 재작성 — 구 [방향 제안](../spec-fill-ui-direction-2026-08-13.md) — 폐기) | — | **재구축 대기** (`/admin2/spec-fill` · **ADM-AI-020**. ⚠ admin2 37개 중 유일하게 Phoenix 벤더를 실제 로드하는 화면 — 2026-08-14 18:40 지어짐, 그 4시간59분 뒤 Phoenix 금지 확정, 이후 커밋 0건. **화면 자체는 「고칠 것」이 아니라 승인 디자인 받아 「새로 지을 것」이라 승인 디자인 대기 중.** ⚠ 그런데 **[검수 화면에서 승인하기] 버튼은 이미 열렸다**(커밋 `e84d61f`, 결함 0) — 재구축을 기다리는 동안 막아 둘 이유가 없다는 사장님 판단(`spec_web_suggestions` 38건·정본 반영 0/38이던 것이 이제 검수 화면으로 갈 수 있다). **⚠ 「승인 경로 개방」과 「화면 재구축 완료」는 다른 사실이다 — 섞지 않는다.** 같은 물결에서 사장님 확정 셋: ①실행 수단=사람 없이 도는 작업 ②대상 필드=`cooler_tdp` 하나 ⑤승인 경로=지금 개방(나머지 ③④⑥은 미정으로 남음, req-spec-fill.md 참조)) |
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
| 8 | 조립 사양 표준 **(2안 비교본)** | [dc-spec-standard-2안.html](../dc-spec-standard-2안.html) | 재구축 중 · UX-24 → **1a** |
| 9 | 상품 사양 정의 **(2안 비교본)** | [dc-spec-field-defs-2안.html](../dc-spec-field-defs-2안.html) | 디자인 · UX-27 → 1a |
| 11 | 조립 호환 규칙 **(2안 비교본)** | [dc-compat-rules-2안.html](../dc-compat-rules-2안.html) | 구축 중 · UX-28 → 1b |
| 27 | 작업 현황판 **(단일안)** | [dc-dash.html](../dc-dash.html) | 재구축 대기 · UX-25 |

### 계약 요약으로 전달된 승인 디자인

**원안은 Claude Design 서버에 있고, 팀에는 계약 요약(`docs/design/spec-*.md`)으로 전달한다.**
`DesignSync` 가 서브에이전트에서 막혀 있어(2026-08-14 확인) 제작자가 원안을 직접 못 받기
때문이다 — **위 `dc-*.html` 과 성격이 다른 것이 아니라 전달 경로만 다르다.** 그 제약이
풀리면 이 표는 위 표로 합쳐진다.

| # | 화면 | 계약 요약 | 구축 |
|---|------|----------|------|
| 12 | 용도별 최소 사양 | [spec-usage-floors.md](../spec-usage-floors.md) | 구축 중 · UX-29 → 두 안 참고 |
| 13 | 부품 등급 관리 | [spec-part-grade.md](../spec-part-grade.md) | 구축 중 · UX-30 → 1a + 1b 우측 입력 |
| 14 | 추천 기준 보기 | [spec-policy-weights.md](../spec-policy-weights.md) | 구축 중 · UX-31 → 1a · 조회 전용 |
| 15 | 추천 가능 재고 현황 | [spec-candidate-pool.md](../spec-candidate-pool.md) | 구축 중 · UX-32 → 1a · 조회 전용 |
| 16 | 견적 상담 기록 | [spec-consult-sessions.md](../spec-consult-sessions.md) | 구축 중 · UX-33 → 1a + 우측 서랍 |

**7번은 완성본이 아니라 「3안 비교본」이다.** 지도형(1a)·진단형(1b)·매트릭스형(1c) 셋이
한 캔버스에 있다. 사장님이 **셋을 다 탭으로 두고 운영자가 고르게** 하기로 확정했다(UX-20).

**1번도 「3안 비교본」이다.** 큐 목록형(1a)·카드 그리드형(1b)·브리핑형(1c) 셋이 한 캔버스에
있고, 셋은 **「지금 할 일」의 표현 방식만** 다르다. 사장님이 **1b 카드 그리드형**으로 확정했다
(UX-22). 조감도와 달리 여기서는 **하나만 고른다** — 대시보드는 첫 화면이라 선택지를 주면
오히려 판단을 미루게 된다.

> **`UX-26` 은 2026-08-14 결정 로그에 세웠다.** 한때 목차만 이 번호를 인용하고 로그에는
> 항목이 없었다(기록자 실측으로 발견 · 하네스가 기록을 빠뜨린 것). **결정 ID 를 인용하면
> 로그에 그 항목이 서 있는지 함께 확인한다** — 가리키는 곳이 없는 번호는 중복된 번호만큼
> 나쁘다. 둘 다 「믿을 수 없는 인용」이라는 같은 병이다.

## 이 목차를 쓰는 법 (하네스 규약)

사장님이 화면 UI를 공유하실 때마다, 하네스는 **그 화면의 정의서 링크와 다음 차례
두세 개를 함께** 올린다. 사장님이 위로 스크롤해 찾지 않게 하기 위해서다
(2026-08-13 사장님 지시).
