# 화면 요구사항 정의서 목차 — LNB 순서

> 사장님이 UI 디자인을 공유하실 때 **다음 차례가 무엇인지 바로 누를 수 있게** 만든 목차다.
> 순서는 좌측 메뉴 정본(`api/admin_nav.py`) 그대로다. 상태는 이 파일이 아니라 실제로
> 재서 안다 — `git status` · `/admin2/*` 라우트 존재 여부.
>
> 상태 표기: **지음** = admin2에 구축됨(라우트가 있다) · **디자인** = 승인 디자인 있음(구축 대기) ·
> **정의서** = 요구사항만 있음 · **없음** = 아직 ·
> **재정의** = 지어졌으나 다시 정의하기로 함 · **셸만** = 새 사이드바에 옛 본문이 붙은 상태 ·
> **구축 중 / 신설 대기** = 승인 디자인을 받아 짓는 중 / 아직 라우트 없음 ·
> **재구축 중 / 재구축 대기** = 이미 지어진 화면을 승인 디자인대로 다시 짓는 중 / 대기 ·
> **수정 완료 · 확인자 재검증 대기** = 라우트·결함 수정은 끝났으나 확인자의 브라우저
> 실측이 아직이라 메뉴에는 연결하지 않은 상태(2026-08-15 추가 — 용도별 최소 사양이
> 첫 사례. 실측 없이 메뉴를 열면 운영자가 눈으로 안 본 화면에 먼저 들어간다)
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
> ⚠ **2026-08-15 발견(03:19) → 그날 안에 해소(11:44, 행 22B) — 그런데 이 발견
> 노트 자신은 안 고쳐진 채 남아 있었다.** 발견 당시 실측:
> `templates/admin/margin_policy.html.j2` · `api/admin_ui_margin_policy.py`
> (라우트 `/admin2/margin-policy`) · `docs/design/req/req-margin-policy.md` ·
> `docs/design/spec-margin-policy.md` 넷 다 존재하는데 이 목차에도
> `api/admin_nav.py`에도 행이 없었다. **커밋 `eaaec25`가 화면 ID `ADM-PRC-020`·
> 그룹 내 순서(010 다음·030 앞)를 정해 22B로 편입했다** — 아래 §5. 판매가 표에
> 있다. **다만 이 발견 노트 자체는 그 뒤로도 지워지지 않아, 한 파일 안에서
> 「없다」와 「22B에 있다」가 동시에 남는 자기모순이 됐다** — 행을 고쳐도 그
> 행을 가리키던 다른 문단이 저절로 안 고쳐진다는 것을 이 목차 스스로 보여준
> 사례다. 지우지 않고 여기서 정정한다(CANON §5 — 폐기된 것은 지우지 말고
> 폐기라고 적는다. 이 노트는 폐기가 아니라 해소된 발견이라 「해소」로 적는다).

## 0. 로그인 — LNB 밖

> 로그인 화면은 좌측 메뉴에 없다(실측: `api/admin_nav.py` 전수 검색 "로그인" 0건 —
> 인증 전 화면이라 메뉴 대상이 아니다). 번호 `0`은 목차 맨 앞에 두기 위한 표기일
> 뿐 LNB 순번이 아니다.

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 0 | 로그인 | [req-login.md](req-login.md) | — | **정의서 작성 완료 · 승인 디자인 대기** (제안 ID `ADM-SYS-021`(기존 재사용) · 제안 경로 `/admin2/login` — 인증 게이트 예외 신설 필요, 정의서 §⑦ ㉮ 참조) |

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
| 5 | **상품 일괄 등록** | [req-product-bulk-import.md](req-product-bulk-import.md) | `dc-product-bulk-import.html` | **지음** (`/admin2/catalog-import` · ADM-CSV-010 · UX-21 → 1b · 라우트·템플릿 커밋 `82a55a1` · ⚠⚠ owner 업로드가 영구히 잠기던 결함 수정(셸 스크립트 중복 로드로 `window.Admin2Shell` 인스턴스가 둘 생겨 권한 갱신이 안 됐다, 커밋 `08541f7`) · 확인자 재검증 통과(`script[src]` 정확히 2개 · 잠금 문구 사라짐 · 파일 입력 3개 열림 · `canWrite('owner')===true`) · 메뉴 연결 `9fdae6d`) |
| 6 | **삭제 상품 조회** | [req-product-deleted.md](req-product-deleted.md) | `dc-product-deleted-2안.html` | **지음** (`/admin2/deleted-products` · ADM-DEL-010 · UX-26 → 1b + 빈 상태 1c · 라우트·템플릿 커밋 `82a55a1` · 로딩 표시 CSS 결함 수정(`hidden`인데 `display:flex`였다, 커밋 `107e819`) · 확인자 재검증 통과(화면 수치 ↔ API 응답 전수 대조 일치) · 메뉴 연결 `9fdae6d`) |

## 3. 상품사양관리

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 7 | **조립 호환 지도** | [req-build-map.md](req-build-map.md) | `dc-build-map-v2.html` | **재구축 대기** (`/admin2/build-map` · UX-20 → v2 클릭 고정) |
| 8 | **조립 사양 표준** | [req-spec-standard.md](req-spec-standard.md) | `dc-spec-standard-2안.html` | **재구축 중** (`/admin2/spec-standard` · UX-24 → **1a**) |
| 9 | **상품 사양 정의** | [req-spec-field-defs.md](req-spec-field-defs.md) | `dc-spec-field-defs-2안.html` | **지음** (`/admin2/spec-field-defs` · ADM-PRD-050 · UX-27 → 1a · 라우트·템플릿 커밋 `82a55a1` · 확인자 재검증 통과(결함 없음) · 메뉴 연결 `9fdae6d`) |
| 10 | **상품 사양 검수** | [req-admin2-reviews-2026-08-13.md](../req-admin2-reviews-2026-08-13.md) | `dc-review-screen.html` | **지음** (`/admin2/reviews`) |
| 11 | **조립 호환 규칙** | [req-compat-rules.md](req-compat-rules.md) · [req-compat-required.md](req-compat-required.md)(「필수 사양 안내」 탭) | `dc-compat-rules-2안.html` | **지음** (`/admin2/compat-rules` · ADM-ENG-010 · UX-28 → 1b · 커밋 `3ffe740` · 메뉴 연결 `68daf6e`. **+2026-08-15: 「필수 사양 안내」 탭 신설**(`spec-compat-required.md` 계약 — 결정 로그 ⑤ 설계 간극을 채움) · 확인자 2차 검증 결함 0 · 커밋 `89019e2`. 메뉴는 안 바뀜 — 기존 화면 안 탭 추가) |
| 12 | **용도별 최소 사양** | [req-usage-floors.md](req-usage-floors.md) | `spec-usage-floors.md`(계약) | **수정 완료 · 확인자 재검증 대기** (`/admin2/usage-floors` · ADM-ENG-040 · UX-29 → 두 안 참고 · 헤더·본문이 서로 다른 가로 스크롤 컨테이너였던 결함을 `.uf-tablewrap` 단일 컨테이너 + `.uf-thead` sticky 로 수정(커밋 `917baea`) · 확인자 실측(1024px, thead·tbody scrollLeft 어긋남) 근거로 고쳤으나 브라우저로 직접 보는 재검증은 아직 · 메뉴 미연결 — 「검증 통과가 조건」이라 이번 물결(7차)에서 제외) |
| 13 | **부품 등급 관리** | [req-part-grade.md](req-part-grade.md) | `spec-part-grade.md`(계약) | **지음** (`/admin2/part-grade` · ADM-ENG-050 · UX-30 → 1a + 1b 우측 입력 · 확인자 검증 통과 · 커밋 `112c5a7` · 메뉴 연결 `7949c98`) |
| 14 | **추천 기준 보기** (구 「추천 기준 설정」) | [req-policy-weights.md](req-policy-weights.md) | `spec-policy-weights.md`(계약) | **지음** (`/admin2/policy-weights` · ADM-ENG-020 · UX-31 → 1a · 조회 전용 · 개명 · 확인자 검증 통과 · 커밋 `3ffe740` · 메뉴 연결 `68daf6e`) |
| 15 | **추천 가능 재고 현황** | [req-candidate-pool.md](req-candidate-pool.md) | `spec-candidate-pool.md`(계약) | **지음** (`/admin2/candidate-pool` · ADM-ENG-030 · UX-32 → 1a · 조회 전용 · 템플릿 커밋 `ec4b7ba` · 라우트 커밋 `82a55a1` · 확인자 재검증 통과(결함 없음) · 메뉴 연결 `9fdae6d`) |
| 16 | **견적 상담 기록** | [req-consult-sessions.md](req-consult-sessions.md) | `spec-consult-sessions.md`(계약) | **지음** (`/admin2/consult-sessions` · ADM-ORD-010 · UX-33 → 1a + 우측 서랍 · 재검증 «결함 0» · 커밋 `d792434` · 메뉴 연결 `68daf6e`) |
| 17 | 부품 교체 · 클릭 기록 | [req-swap-click-logs.md](req-swap-click-logs.md) | `spec-swap-click-logs.md`(계약 · 커밋 `c75656e` 2026-08-14 23:47 — 이 목차의 최종 편집(`08cfe9e` 16:25)보다 먼저 커밋됐는데 반영이 안 됐었다) | **지음** (`/admin2/swap-click-logs` · 라우트·템플릿 커밋 `82a55a1` · 확인자 재검증 통과(결함 없음) · 메뉴 연결 `9fdae6d`) |

## 4. 매입 · 소싱

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 18 | 공급처 | [req-suppliers.md](req-suppliers.md) | `spec-suppliers.md`(계약 · 1b 안) | **지음** (`/admin2/suppliers` · **ADM-SRC-030** · 커밋 `e5572eb` · 확인자 재검증 통과(하네스 통보 2026-08-15 — 커밋 자신은 "제작 완료·검증 중"이라 적었으나 그 뒤 통과) · 메뉴 연결 `6b3d637`) |
| 19 | 매입 견적(용산) | [req-sourcing-quote.md](req-sourcing-quote.md) | `spec-sourcing.md`(계약 · 1a 안) | **지음** (`/admin2/sourcing` · **ADM-SRC-010** · 커밋 `d53732c` · 확인자 재검증 통과(하네스 통보 2026-08-15 — 위와 같은 경위) · 메뉴 연결 `6b3d637` · ⚠ 마이그레이션 `0053_sourcing_confirmed_at`은 스키마만이고 DB 미적용 — 적용 전까지 「오늘 확정 N건」은 `null`+사유 문구로 대신 응답한다) |
| 20 | 단가표 반영 | [req-price-sheet-apply.md](req-price-sheet-apply.md) | `spec-price-import.md`(계약 · 1b 안) | **지음** (`/admin2/price-import` · **ADM-PRC-040** · 커밋 `4b23e78`(라우트·템플릿 함께) — 그 커밋 메시지 자신은 "재검증 진행 중"이라 적었다. **decision-log `T-11`**: 같은 시각 다른 제작자가 배포를 막던 결함 둘(0행 복원 no-op·되돌리기 버튼 소실)을 같은 두 파일에서 고치다 working tree가 겹쳐 이 커밋에 조용히 함께 들어갔다 — A-46이 그 결함을 처음 실행 가능하게 만들어서야 드러난 잠복 결함이었다. 그 뒤 확인자 재검증 통과(하네스 통보 2026-08-15) · 메뉴 연결 `6b3d637`) |

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
| 21 | 판매가 관리 | [req-sale-price.md](req-sale-price.md) | `spec-sale-price.md`(계약 · 커밋 `6f75d49` 2026-08-15 01:30 — 이 목차의 최종 편집(`08cfe9e` 16:25)보다 먼저 커밋됐는데 반영이 안 됐었다) | **지음** (`/admin2/sale-price` · 라우트 커밋 `096aec2`(결함 3건 수정 포함) · 템플릿 커밋 `82a55a1` · 확인자 재검증 통과(결함 없음) · 메뉴 연결 `9fdae6d`) |
| 22 | 가격 검토 대기 | [req-price-review-queue.md](req-price-review-queue.md) | `spec-price-review.md`(계약) | **지음** (`/admin2/price-review` · ADM-PRC-010 · 확인자 검증 통과 · 메뉴 연결 `879ee61` · 커밋 `28c49dd`(뒤늦게 반영, 내용 변경 없음 — 이 목차 최종 편집 뒤에 커밋돼 그 사이 "미커밋"으로 남아 있었다. 조사자 목록엔 없던 여덟 번째 사례, 기록자가 같은 검사 중 발견)) |
| 22B | 마진 정책 | [req-margin-policy.md](req-margin-policy.md) | `spec-margin-policy.md`(계약) | **지음** (`/admin2/margin-policy` · ADM-PRC-020 · 확인자 2차 검증 결함 0 · 커밋 `a4d5d44` · 메뉴 연결 `879ee61`) |
| 23 | 가격 이력 | [req-price-history.md](req-price-history.md) · [spec-price-history.md](../spec-price-history.md)(2026-08-15 「(신규)」 표기 정정) | — | **지음** — 구현 `/admin2/price-history`(커밋 `140a5ba`·`77dbbef`·`bdf7e7c`) · 검증 확인자 브라우저 실측 통과 3라운드(①7행 3종 판정·ref_id null 실값·401/400/404 경계·768px ②마이그레이션 0050 「비움」 표시 — DB↔DOM 5행 대조·new_price=0 실데이터로 0과 NULL 구분 확인 ③「부품 종류」 확인 중… 고정 결함 — 10ms 폴링 프레임 단위 캡처로 재발 0·정상 로딩 노출은 유지 확인) · 계약 정정 `8e35508` · 연결 `api/admin_nav.py` `91dd3a1` |
| 23B | 판매가 재산정 | [req-reprice.md](req-reprice.md) | `spec-reprice.md`(계약 · 1a 안, 커밋 `82a55a1`) | **지음** (`/admin2/reprice` · **ADM-PRC-050** — ID·경로 대조 완료(spec-reprice.md가 남겨 둔 "대조 필요"를 이걸로 해소 — `api/admin_ui_reprice.py`의 `APIRouter(prefix="/admin2")` + `@router.get("/reprice")`로 실측). **1a 안 확정**(회차 표 → 범위 → 미리보기 → 실행 한 줄기, 「지난 회차 기록」이 화면의 축이지 경고 배너가 아니다, 2026-08-15 사장님 결정). **확인자 검증 통과(2026-08-15)** — 「지난 회차」 표가 맨 앞·`note` 열 실재·간격 "1분 1.5초" 형식 확인, 금지 문구(「99.99%」·「세 번째도」 등) grep 전수 0건, **apply(7,174건)->undo 왕복 실완주(log_id 7720)로 구 화면의 핵심 결함("새로고침하면 되돌릴 방법이 사라진다") 해소 확인**, 되돌린 뒤 수치 원값과 완전 일치(7,279/6,899/275/105/0), 미로그인 401을 preview·apply·undo·페이지 네 곳 모두 확인(계약 §⑧ "무세션 실측 못 함" 항목 해소), 콘솔 에러 0·404 자원 0·외부 CDN 0. **nav 항목 자체가 없던 유일한 화면**이었는데 이번에 신설 + 메뉴 연결(`api/admin_nav.py` 커밋 `c6d662e` — 「판매가」 그룹 물리적 끝에 배치, 근거는 그 커밋의 6차 노트). ⚠ 남은 결함 하나(마크다운 별표 노출)는 다른 제작자가 수정 중이고 ⓐ류(문구 렌더링)라 연결을 막지 않았다) |

## 6. 인계 · 성과

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 24 | 쇼핑몰 동기화 | [req-mall-sync.md](req-mall-sync.md) | `spec-mall-sync.md`(계약 · 커밋 `6f75d49` 2026-08-15 01:30 — 이 목차의 최종 편집(`08cfe9e` 16:25)보다 먼저 커밋됐는데 반영이 안 됐었다) | **지음** (`/admin2/mall-sync` · 라우트 커밋 `0eaa890` · 템플릿 커밋 `82a55a1` · 콘텐츠가 스크롤 수단 없이 잘리던 결함 수정(배너~각주까지 한 덩어리로 스크롤, 커밋 `f3cec63`) · 확인자 재검증 통과 — ⚠ 부작용 하나 남음(표 헤더 sticky 무력화, 작업 #51 · 확인자 판정 「화면 기능은 정상, 배포를 막을 사유 아님」) · 메뉴 연결 `9fdae6d`) |
| 25 | 인계 기록 | [req-handoff-log.md](req-handoff-log.md) | `spec-handoff-log.md`(계약 · 커밋 `6f75d49` 2026-08-15 01:30 — 이 목차의 최종 편집(`08cfe9e` 16:25)보다 먼저 커밋됐는데 반영이 안 됐었다) | **지음** (`/admin2/handoff-log` · 라우트·템플릿 커밋 `82a55a1` · 확인자 재검증 통과(결함 없음) · 메뉴 연결 `9fdae6d`) |
| 26 | 유입 성과 | [req-funnel-performance.md](req-funnel-performance.md) | `spec-funnel.md`(계약 · 1a 안) | **지음** (경로 `/admin2/funnel-performance` — spec-funnel.md의 「가칭」 그대로 확정 표기를 따른다. **ADM-HND-030 후보 — 화면 ID는 여전히 미배정**(spec-funnel.md 자신이 명시. ID 미정이 메뉴 연결을 막지는 않는다). 커밋 `adb6d4d` · 확인자 재검증 통과(하네스 통보 2026-08-15) · 메뉴 연결 `6b3d637`) |

## 7. AI 관리

| # | 화면 | 요구사항 정의서 | 디자인 | 상태 |
|---|------|----------------|--------|------|
| 27 | **작업 현황판** | [req-dash.md](req-dash.md) | `dc-dash.html` | **재구축 중** (`/admin2/dash` · UX-25 단일안 · 2026-08-15 실측: 「대기」였는데 실제로는 작업 중이었다) |
| 28 | 웹 사양 채움 | [req-spec-fill.md](req-spec-fill.md)(2026-08-15 전면 재작성 — 구 [방향 제안](../spec-fill-ui-direction-2026-08-13.md) — 폐기) | `spec-spec-fill.md`(계약 · 1a 안) | **지음** (`/admin2/spec-fill` · **ADM-AI-020**. ⚠ admin2 화면 중 유일하게 Phoenix 벤더를 실제 로드하던 화면 — 2026-08-14 18:40 지어짐, 그 4시간59분 뒤 Phoenix 금지 확정. **2026-08-15 승인 디자인(1a·실행 원장 중심) 도착, 재구축** — 실측: `api/admin_ui_spec_fill.py`·`templates/admin/spec_fill.html.j2` 커밋 `04a99dc`(그 커밋 메시지 자신은 당시 "재구축 중(제작 착수, 확인자 검증 전)"이라 적었다). 같은 물결 사장님 확정 셋: ①실행 수단=사람 없이 도는 작업 ②대상 필드=`cooler_tdp` 하나 ⑤승인 경로=이미 개방(커밋 `e84d61f`) — 나머지 ③④⑥은 미정(req-spec-fill.md 참조). **⚠ 「승인 경로 개방」과 「화면 재구축 완료」는 다른 사실이다 — 섞지 않는다.** ⚠⚠ **해소(2026-08-15, 기록자 6차)** — 커밋 `04a99dc`의 1a 버전이 "검증 전인데 메뉴에 이미 노출돼 있다"는 우려를 남겨 뒀었다(admin_nav.py 5차 노트 — 그때는 이 화면의 href를 새로 만들지도 끊지도 않고 범위 밖으로 판단해 하네스 보고에만 남겼다). **그 뒤 확인자 재검증이 통과했다** — `review_pending_empty` 렌더 · DOM 순서 · `scrollLeft` 리셋 셋 다 해소 확인, 47.6%→100%. 메뉴 연결은 이번에 새로 한 것이 없다(기존 href 그대로 — 검증이 뒤늦게 노출을 따라잡았을 뿐이다)) |
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
| 5 | 상품 일괄 등록 | [dc-product-bulk-import.html](../dc-product-bulk-import.html) | 지음 · UX-21 → 1b · 메뉴 연결 |
| 6 | 삭제 상품 조회 **(2안 + 빈 상태)** | [dc-product-deleted-2안.html](../dc-product-deleted-2안.html) | 지음 · UX-26 → 1b + 빈 상태 1c · 메뉴 연결 |
| 8 | 조립 사양 표준 **(2안 비교본)** | [dc-spec-standard-2안.html](../dc-spec-standard-2안.html) | 재구축 중 · UX-24 → **1a** |
| 9 | 상품 사양 정의 **(2안 비교본)** | [dc-spec-field-defs-2안.html](../dc-spec-field-defs-2안.html) | 지음 · UX-27 → 1a · 메뉴 연결 |
| 11 | 조립 호환 규칙 **(2안 비교본)** | [dc-compat-rules-2안.html](../dc-compat-rules-2안.html) | 지음 |
| 27 | 작업 현황판 **(단일안)** | [dc-dash.html](../dc-dash.html) | 재구축 대기 · UX-25 |

### 계약 요약으로 전달된 승인 디자인

**원안은 Claude Design 서버에 있고, 팀에는 계약 요약(`docs/design/spec-*.md`)으로 전달한다.**
`DesignSync` 가 서브에이전트에서 막혀 있어(2026-08-14 확인) 제작자가 원안을 직접 못 받기
때문이다 — **위 `dc-*.html` 과 성격이 다른 것이 아니라 전달 경로만 다르다.** 그 제약이
풀리면 이 표는 위 표로 합쳐진다.

| # | 화면 | 계약 요약 | 구축 |
|---|------|----------|------|
| 12 | 용도별 최소 사양 | [spec-usage-floors.md](../spec-usage-floors.md) | 수정 완료 · 확인자 재검증 대기 · UX-29 → 두 안 참고 · 메뉴 미연결 |
| 13 | 부품 등급 관리 | [spec-part-grade.md](../spec-part-grade.md) | 구축 중 · UX-30 → 1a + 1b 우측 입력 |
| 14 | 추천 기준 보기 | [spec-policy-weights.md](../spec-policy-weights.md) | 구축 중 · UX-31 → 1a · 조회 전용 |
| 15 | 추천 가능 재고 현황 | [spec-candidate-pool.md](../spec-candidate-pool.md) | 지음 · UX-32 → 1a · 조회 전용 · 메뉴 연결 |
| 16 | 견적 상담 기록 | [spec-consult-sessions.md](../spec-consult-sessions.md) | 구축 중 · UX-33 → 1a + 우측 서랍 |
| 17 | 부품 교체 · 클릭 기록 | [spec-swap-click-logs.md](../spec-swap-click-logs.md) | 지음 · 메뉴 연결 (2026-08-15 신규 등재 — 커밋 `c75656e`이 이 목차 최종 편집보다 먼저였는데 빠져 있었다. 그 뒤 확인자 재검증 통과 · 메뉴 연결) |
| 18 | 공급처 | [spec-suppliers.md](../spec-suppliers.md) | 지음 · 1b 안 · 메뉴 연결 |
| 19 | 매입 견적(용산) | [spec-sourcing.md](../spec-sourcing.md) | 지음 · 1a 안 · 메뉴 연결 |
| 20 | 단가표 반영 | [spec-price-import.md](../spec-price-import.md) | 지음 · 1b 안 · 메뉴 연결 |
| 21 | 판매가 관리 | [spec-sale-price.md](../spec-sale-price.md) | 지음 · 메뉴 연결 (2026-08-15 신규 등재 — 커밋 `6f75d49`이 이 목차 최종 편집보다 먼저였는데 빠져 있었다. 그 뒤 확인자 재검증 통과 · 메뉴 연결) |
| 23B | 판매가 재산정 | [spec-reprice.md](../spec-reprice.md) | 지음 · 1a 안 · 검증 통과 · 메뉴 연결(`c6d662e`) |
| 24 | 쇼핑몰 동기화 | [spec-mall-sync.md](../spec-mall-sync.md) | 지음 · 메뉴 연결 (2026-08-15 신규 등재 — 커밋 `6f75d49`이 이 목차 최종 편집보다 먼저였는데 빠져 있었다. 그 뒤 스크롤 결함 수정(커밋 `f3cec63`) · 확인자 재검증 통과 · 메뉴 연결) |
| 25 | 인계 기록 | [spec-handoff-log.md](../spec-handoff-log.md) | 지음 · 메뉴 연결 (2026-08-15 신규 등재 — 커밋 `6f75d49`이 이 목차 최종 편집보다 먼저였는데 빠져 있었다. 그 뒤 확인자 재검증 통과 · 메뉴 연결) |
| 26 | 유입 성과 | [spec-funnel.md](../spec-funnel.md) | 지음 · 1a 안 · 화면 ID 미배정 · 메뉴 연결 |
| 28 | 웹 사양 채움 | [spec-spec-fill.md](../spec-spec-fill.md) | 지음 · 1a 안 · 검증 통과(2026-08-15) · 메뉴 연결(기존 href) |

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
