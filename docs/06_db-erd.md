# 06. DB 설계 (ERD & 스키마)

**파일 경로:** `docs/06_db-erd.md`
**문서 버전:** Ver 4.0
**DBMS:** PostgreSQL (DB명 `popcorn_pc`) — 구성 위치: 구글 클라우드(기구성, 사용자 확인 2026-07-21). **실제 DB 생성·마이그레이션은 본 개정본 검토 후 별도 승인으로 착수한다.**
**갱신일:** 2026-07-21
**선행 문서:** `12_data_normalization.md`, `13_standard_product_csv.md`, `07_api-spec.md`, `docs/decisions/decision-log.md`(A-10·주변기기·가격 산정·단가표 결정), `docs/decisions/admin-identity.md`(ADM-PRC-040)
**대체 선언:** Ver 3.0의 상품 스파인(§1~§9)을 계승하되, **원칙 3(재고 수량 미보유)을 폐기**하고(A-10 커머스 승격) §10~§13(커머스 원장 · 공급처 단가표 · 상담·회원 활동 · 운영 설정)을 증분한다. Ver 2.0 대체 관계는 Ver 3.0 선언을 승계한다.
**검토 이력:** 1차 검토 2026-07-23 — 이슈 6건 발견·반영(users↔members 관계 정의, member_reviews 상태·S2 인용 필드, refunds 단계 어휘, products.supplier 폐기 예고, settlement_batches 신설, 매핑 요청 시각).

---

## 1. 설계 원칙

1. **레이어 분리로 "원본 보존"과 "표준 단일화"를 동시에 만족한다.** 원본 보존은 `product_imports`가, 표준 확정본은 `products`가 담당한다. 두 원칙을 한 테이블에 욱여넣지 않는다.
2. **`products`는 운영의 단일 진실(Single Source of Truth)이다.** 추천 엔진, 관리자 화면, 소싱 매칭이 모두 이 테이블만 바라본다. `product_category_normalized` 테이블은 폐기한다.
3. **[Ver 4.0 개정 — A-10] 재고 차감 단일 원장 = 본 시스템.** `products.stock_qty`를 보유하고 `stock_movements`가 입출고 원장이다. 쇼핑몰 판매분은 API 유입(`movement_type='mall_sale'`)으로 정합을 유지하고, 자체 결제 진행 중 재고는 `stock_reservations`(hold)로 예약한다. (Ver 3.0의 "수량 미보유·상태만 동기화" 원칙은 폐기 — §9 참조)
4. **추천 후보 풀의 정의는 뷰 한 곳(`v_recommendation_candidates`)에만 존재한다.** 결정론 엔진, S1 후보 카운터, 스왑 대안 조회는 전부 이 뷰를 조회한다.
5. **회사 원장 필드와 공개 사실 필드를 구분한다.** 제품명·제품코드·매입가·판매가·상태는 회사만 아는 사실(CSV/실시간 업데이트로 관리), 소켓·TDP·치수·메모리 규격은 세상의 공개된 사실(AI 보강 파이프라인으로 관리)이다. §7 참조.
6. **[Ver 4.0] 주문 원장은 운영 모드와 무관하게 항상 본 시스템에 생성한다.** 인계 모드는 복제 전달일 뿐이다(A-10 — 스냅샷 재현·감사 체계). 주문 라인은 생성 시점의 가격·사양을 스냅샷으로 보존한다.
7. **[Ver 4.0] 운영 설정은 버전 관리한다.** 운영 모드 스위치 5종·가격 산정 파라미터(카드수수료·마진)는 현행값 테이블 + 이력 테이블 쌍으로 관리하고, 모든 변경은 작업자·사유와 함께 기록한다.

---

## 2. ERD 개요

```mermaid
erDiagram
  product_imports }o--o| products : "매칭·재정규화 원본"
  products ||--|| product_specs : "AI 연산 스펙 1:1"
  products ||--o{ product_price_history : "가격 변경 이력"
  products ||--o{ product_reviews : "통합 검수 큐"
  products ||--o{ recommendation_items : "추천 부품"
  products ||--o{ promo_click_logs : "클릭"
  products ||--o{ swap_event_logs : "스왑"
  recommendations ||--o{ recommendation_items : "포함"
  users ||--o{ recommendations : "요청"
  admin_operators ||--o{ admin_operator_activity_logs : "활동"

  %% Ver 4.0 증분
  users |o--o| members : "가입 승격 (익명→회원)"
  members ||--o{ orders : "주문"
  settlement_batches ||--o{ settlements : "일 마감"
  orders ||--o{ order_items : "라인(스냅샷)"
  orders ||--o{ payments : "결제"
  orders ||--o{ shipments : "배송"
  orders ||--o{ refunds : "환불·클레임"
  payments ||--o{ settlements : "정산"
  orders ||--o{ stock_reservations : "재고 예약(hold)"
  products ||--o{ stock_movements : "입출고 원장"
  suppliers ||--o{ supplier_presets : "파싱 프리셋"
  suppliers ||--o{ supplier_price_files : "일일 단가표"
  supplier_price_files ||--o{ supplier_price_rows : "정규화 행"
  suppliers ||--o{ supplier_product_map : "모델↔SKU 매핑"
  products ||--o{ product_supplier_prices : "공급처 가격 1:N"
  members ||--o{ consult_sessions : "상담"
  consult_sessions ||--o{ quote_snapshots : "견적 스냅샷"
  members ||--o{ member_reviews : "후기(구매 인증)"
  members ||--o{ member_favorites : "관심 부품"
```

---

## 3. 테이블 정의

### 3.1 product_imports — 원본 냉동 보관

CSV 업로드 원본 행을 JSONB로 통째 보존한다. 목적은 감사(audit)가 아니라 **재정규화 가능성**이다. 정규화 룰이 개선되면 이 테이블에서 다시 돌린다.

```sql
CREATE TABLE product_imports (
  import_id    BIGSERIAL PRIMARY KEY,
  job_id       BIGINT REFERENCES csv_import_jobs(job_id),
  product_code BIGINT,                -- 매칭된 상품 (없으면 NULL)
  raw_row      JSONB NOT NULL,        -- category1~4, spec_raw 포함 원본 행 전체
  imported_at  TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX idx_imports_product ON product_imports (product_code, imported_at DESC);
```

레거시 `category1~4`, `spec_raw`는 `products`에 컬럼으로 유지하지 않는다. 원본이 필요하면 이 테이블을 본다.

### 3.2 products — 표준 확정본 (단일 진실)

```sql
CREATE TABLE products (
  product_code        BIGINT PRIMARY KEY,          -- 자체상품코드
  product_name        VARCHAR(500) NOT NULL,
  maker               VARCHAR(100),
  brand               VARCHAR(100),
  model_name          VARCHAR(255),
  part_type           VARCHAR(50) NOT NULL,        -- 표준 부품 타입
  category_group      VARCHAR(50) NOT NULL,        -- core_part/peripheral/service/prebuilt_pc/internal/unknown
  status              VARCHAR(20) NOT NULL,        -- 판매중/품절/단종/삭제대기
  ai_candidate_yn     BOOLEAN NOT NULL DEFAULT false,
  review_required_yn  BOOLEAN NOT NULL DEFAULT false,

  purchase_price      BIGINT,                      -- 매입가 (회사 원장)
  sale_price          BIGINT,                      -- 판매가 (회사 원장)
  market_price        BIGINT,                      -- 시중가 (참고)

  locked_fields       JSONB NOT NULL DEFAULT '[]', -- 운영자 보정 잠금 (§4)
  supplier            VARCHAR(200),                -- [검토: 폐기 예정] §11.4 product_supplier_prices(1:N)로 대체 — 마이그레이션 시 제거 여부 확정
  warranty_months     INTEGER,
  spec_source_text    TEXT,                        -- 원본 스펙 정제본

  -- [Ver 4.0 추가]
  danawa_code         VARCHAR(20),                 -- 다나와 상품코드 — 거래처 간 교차 매칭 키 (§11)
  stock_qty           INTEGER NOT NULL DEFAULT 0,  -- 재고 수량 — 단일 원장 (A-10, 원칙 3)

  created_at          TIMESTAMP NOT NULL DEFAULT now(),
  updated_at          TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX idx_products_candidate ON products (status, ai_candidate_yn, part_type);
CREATE INDEX idx_products_name_trgm ON products USING gin (product_name gin_trgm_ops);
CREATE UNIQUE INDEX idx_products_danawa ON products (danawa_code) WHERE danawa_code IS NOT NULL;  -- [Ver 4.0]
```

기존 `margin_locked` 단일 플래그는 폐기하고 `locked_fields`로 대체한다.

### 3.3 product_specs — AI 연산 정형 필드 (1:1)

호환성 검증과 결정론 추천 엔진의 입력값. 와이드 테이블 유지(부품 타입별 개별 테이블·EAV 채택 안 함 — 조인 복잡도와 타입 안정성 사유).

```sql
CREATE TABLE product_specs (
  product_code    BIGINT PRIMARY KEY REFERENCES products(product_code),
  part_type       VARCHAR(50) NOT NULL,

  socket          VARCHAR(30),      -- CPU/MB
  chipset         VARCHAR(50),      -- MB/GPU
  mem_type        VARCHAR(10),      -- DDR4/DDR5
  capacity_gb     INTEGER,          -- RAM/SSD/HDD
  clock_mhz       INTEGER,          -- RAM
  tdp_watt        INTEGER,          -- CPU/GPU 소비전력
  rated_watt      INTEGER,          -- POWER 정격 출력
  required_power_watt INTEGER,      -- GPU 권장 파워
  length_mm       INTEGER,          -- GPU 길이
  gpu_max_mm      INTEGER,          -- CASE GPU 장착 한계
  cooler_height_mm INTEGER,         -- CASE 쿨러 한계 / 공랭 높이
  cooler_tdp      INTEGER,          -- 쿨러 대응 TDP
  pcie_gen        VARCHAR(20),
  form_factor     VARCHAR(50),      -- ATX/M-ATX/Mini-ITX
  interface       VARCHAR(50),      -- NVMe/SATA
  tag_white       BOOLEAN NOT NULL DEFAULT false,
  tag_rgb         BOOLEAN NOT NULL DEFAULT false,
  tag_silent      BOOLEAN NOT NULL DEFAULT false,

  -- [Ver 4.0] 주변기기 사양 (와이드 테이블 기조 유지 — EAV 채택 안 함)
  size_inch       NUMERIC(4,1),     -- MONITOR 화면 크기
  resolution      VARCHAR(20),      -- MONITOR: FHD/QHD/UHD…
  refresh_hz      INTEGER,          -- MONITOR 주사율 — 함께 구성 GPU 매칭 근거
  panel           VARCHAR(20),      -- MONITOR: IPS/VA/OLED…
  ports           JSONB,            -- MONITOR 출력 포트 예: {"dp":1,"hdmi":2}
  switch_type     VARCHAR(30),      -- KEYBOARD 스위치
  key_layout      VARCHAR(20),      -- KEYBOARD 배열(풀/텐키리스…)
  connection      VARCHAR(20),      -- KEYBOARD/MOUSE/HEADSET: 유선/무선/블루투스

  extract_source  VARCHAR(20),      -- 'rule' / 'ai_text' / 'ai_knowledge' / 'manual'
  confidence      NUMERIC(4,2),     -- 자동 추출 신뢰도
  verified_yn     BOOLEAN NOT NULL DEFAULT false,  -- 확정 승격 여부 (§7.3)
  updated_at      TIMESTAMP NOT NULL DEFAULT now()
);
```

> `extract_source`는 필드 그룹 대표값이다. 필드별 출처 추적이 필요해지면 별도 메타 테이블로 승격한다(현 규모에서는 과설계로 판단, 보류).

### 3.4 product_price_history — 가격 변경 이력

```sql
CREATE TABLE product_price_history (
  history_id   BIGSERIAL PRIMARY KEY,
  product_code BIGINT NOT NULL REFERENCES products(product_code),
  field        VARCHAR(20) NOT NULL,   -- 'purchase' / 'sale' / 'market'
  old_price    BIGINT,
  new_price    BIGINT NOT NULL,
  reason       VARCHAR(30) NOT NULL,   -- 'csv' / 'sourcing' / 'margin_policy' / 'manual'
  ref_id       BIGINT,                 -- sourcing_id, job_id 등 근거 참조
  changed_by   BIGINT,                 -- 운영자 (시스템이면 NULL)
  changed_at   TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX idx_price_history_product ON product_price_history (product_code, changed_at DESC);
```

### 3.5 product_reviews — 통합 검수 큐

기존 `product_upload_reviews`를 확장 대체한다. CSV 오류 행, 저신뢰 추출, 교차검증 불일치, 소싱 매칭 보류를 한 큐로 받는다.

```sql
CREATE TABLE product_reviews (
  review_id     BIGSERIAL PRIMARY KEY,
  product_code  BIGINT REFERENCES products(product_code),
  review_type   VARCHAR(30) NOT NULL,  -- 'csv_error' / 'spec_missing' / 'spec_conflict' / 'low_confidence' / 'sourcing_hold'
  field_name    VARCHAR(50),           -- 대상 필드 (해당 시)
  detail        TEXT,                  -- 사유·비교값 (예: "원문 272mm vs 지식 251mm")
  review_status VARCHAR(30) NOT NULL DEFAULT '대기',  -- 대기/검수중/승인/수정/보류/제외
  reviewed_by   BIGINT,
  reviewed_at   TIMESTAMP,
  created_at    TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX idx_reviews_queue ON product_reviews (review_status, created_at);
```

### 3.6 v_recommendation_candidates — 추천 후보 뷰 (유일한 정의처)

```sql
CREATE VIEW v_recommendation_candidates AS
SELECT p.*, ps.*
FROM products p
JOIN product_specs ps USING (product_code)
WHERE p.status = '판매중'
  AND p.ai_candidate_yn = true
  AND p.review_required_yn = false
  AND p.category_group = 'core_part'
  AND p.part_type IN ('CPU','GPU','MB','RAM','SSD','HDD','POWER','CASE','COOLER_CPU_AIR','COOLER_CPU_AIO');
```

품절/단종 토글 → `products.status` 변경 → 뷰에서 즉시 제외(1초 룰 자동 충족). 후보 풀 캐시를 도입할 경우 상태 변경 시 캐시 무효화 훅을 함께 건다.

**[Ver 4.0] v_companion_candidates — 함께 구성(주변기기) 후보 뷰.** 본체 엔진과 분리된 제안 풀. 엔진 검증 대상이 아니라 권장 매칭 근거(주사율↔GPU·포트)로만 쓰인다(주변기기 결정 2026-07-21).

```sql
CREATE VIEW v_companion_candidates AS
SELECT p.*, ps.*
FROM products p
JOIN product_specs ps USING (product_code)
WHERE p.status = '판매중'
  AND p.review_required_yn = false
  AND p.category_group = 'peripheral'
  AND p.part_type IN ('MONITOR','KEYBOARD','MOUSE','HEADSET','SPEAKER','WEBCAM');
```

### 3.7 유지 테이블

`users`, `logs`, `recommendations`, `recommendation_items`, `policy_weights`, `category_margin_policies`, `api_cost_logs`, `promo_click_logs`, `swap_event_logs`, `rate_limit_policies`, `cost_thresholds`, `csv_import_jobs`, `csv_import_errors`, `admin_operators`, `admin_operator_activity_logs`, 제품 소싱 3종(`sourcing_batches`, `product_sourcing_quotes`, `product_sourcing_match_candidates`)은 Ver 2.0 정의를 유지한다.

---

## 4. 필드 소유권 & 덮어쓰기 규칙

### 4.1 소유권 매트릭스

| 필드 그룹 | 원장 | 갱신 경로 | 비고 |
|---|---|---|---|
| 제품코드·제품명·상태 | 회사(쇼핑몰) | CSV 업서트 / 실시간 API | 회사만 아는 사실 |
| 매입가·판매가·시중가 | 회사 | CSV / 소싱 확정 / 마진 정책 제안 승인 | §6 가격 흐름 |
| part_type·category_group | 정규화 파이프라인 | 룰 테이블 + 검수 | |
| 스펙 정형 필드(specs.*) | 공개 사실 | AI 보강 파이프라인(§7) + 운영자 검수 | |
| ai_candidate_yn·review_required_yn | 시스템 산출 | 파이프라인 자동 | |

### 4.2 덮어쓰기 우선순위

```text
운영자 수동(locked) > 소싱 확정 > CSV 업서트 > AI 보강 > 룰 추출
```

### 4.3 locked_fields 규칙

- 운영자가 편집 패널에서 필드를 수정·저장하면 해당 필드명이 `products.locked_fields`에 등록된다.
- `product_specs` 소속 필드는 `"specs."` 접두 네임스페이스로 표기한다. 예: `["specs.length_mm", "sale_price"]`
- **CSV 업서트와 AI 보강 파이프라인은 locked_fields에 등록된 필드를 건너뛴다.** 잠금 조회는 `products` 한 곳에서만 한다(두 테이블 분산 금지).
- 잠금 해제는 편집 패널에서 운영자가 명시적으로 수행한다.
- 잠금 등록·해제는 운영자 활동 로그 기록 대상이다.
- UI 반영: ADM-CSV-010 사전 검증 카드에 "잠긴 필드 N건 보호됨"을 표기한다.

---

## 5. 부품 타입별 필수 연산 필드 매트릭스

`review_required_yn` 판정과 호환성 엔진 입력의 기준. **필수 필드 중 하나라도 NULL이면 review_required_yn = true**이며 추천 풀에서 제외된다.

| part_type | 필수 필드 | 권장 필드 |
|---|---|---|
| CPU | socket, tdp_watt | — |
| GPU | length_mm, tdp_watt | required_power_watt, pcie_gen |
| MB | socket, chipset, mem_type, form_factor | — |
| RAM | mem_type, capacity_gb | clock_mhz |
| SSD/HDD | interface, capacity_gb | pcie_gen |
| POWER | rated_watt | — |
| CASE | gpu_max_mm, cooler_height_mm, form_factor | — |
| COOLER_CPU_AIR | cooler_tdp, cooler_height_mm | socket |
| COOLER_CPU_AIO | cooler_tdp | socket |

**[Ver 4.0] 주변기기(함께 구성 풀 — 분류별 필수 사양 세트가 본체와 다름):**

| part_type | 필수 필드 | 권장 필드 |
|---|---|---|
| MONITOR | size_inch, resolution, refresh_hz, ports | panel |
| KEYBOARD | connection | switch_type, key_layout |
| MOUSE | connection | — |
| HEADSET / SPEAKER / WEBCAM | connection | — |

이 매트릭스는 호환성 검증 룰의 입력 필드와 1:1로 일치해야 하며, 검증 룰 변경 시 본 표를 함께 개정한다. 주변기기 필수 필드 미확정 시에도 `review_required_yn = true`로 함께 구성 풀에서 제외된다(모니터 주사율 검수 케이스 — ADM-PRD-020).

---

## 6. 가격 흐름 3원칙

1. **소싱 확정 매칭 시 매입가 갱신은 자동이 아니다.** 확정 모달에서 운영자가 "매입가 갱신" 여부를 선택한다. 갱신 시 `history(reason='sourcing', ref_id=sourcing_id)`.
2. **판매가 재계산은 제안 + 승인 방식이다.** 매입가 변경 시 시스템은 `카테고리 마진 정책 기준 권장 판매가`를 산출해 상품 마스터에 제안 배지로 노출한다. 운영자 승인 시에만 `sale_price` 반영, `history(reason='margin_policy')`. 자동 집행하지 않는다 — 가격 결정권은 운영자에게 있다.
   - UI 파급: ADM-DSH-010 대시보드에 "가격 검토 대기 N건" 미니 위젯 추가.
3. **모든 가격 변경은 `product_price_history`에 reason·ref_id와 함께 기록한다.** 근거 리포트("모든 견적에는 이유가 있습니다")의 가격 출처 추적 기반이다. **[Ver 4.0] reason에 `price_import`(단가표 일일 반영) 추가** — ref_id = supplier_price_files.file_id.

`sale_price`가 locked_fields에 등록된 상품은 제안 배지만 노출하고 CSV·정책에 의한 변경을 차단한다.

**[Ver 4.0] 4. 판매가 현행 산정 공식 = 매입가 + 카드수수료 + 마진(기본 0%).** 매입 구조 = 다중 거래처가 플랫폼(윈윈 등)에 단품가 입력 → **매입가 판정 = 단가표 가격 열 중 최저가**(특정 열 고정 매핑 아님, 2026-07-21 사용자 확정). 수수료율·마진율은 `pricing_settings`(§13)에서 버전 관리한다. 마진 상세 구조는 미정(향후 확정)이므로 파라미터화로 수용한다. 단가표 diff 반영 시 재계산 판매가는 §6.2 제안+승인 원칙을 따르되, ADM-PRC-040의 "선택 일괄 반영"이 승인 행위에 해당한다.

---

## 7. AI 스펙 보강 파이프라인

### 7.1 역할 경계

회사 원장 필드(§4.1)는 AI가 건드리지 않는다. AI 보강 대상은 **세상의 공개된 사실**인 스펙 정형 필드에 한정한다. AI는 채우는 노동을 담당하고, 신뢰는 교차검증 게이트가 만든다.

**LLM 역할 원칙 개정:** "LLM의 역할은 셋이다 — ① 입력 파서, ② 설명 생성기, ③ **오프라인 데이터 보강(검증 게이트 필수)**." 추천 시점의 부품 선택은 여전히 결정론 엔진만 수행한다. 본 파이프라인은 오프라인에서 결정론 엔진의 입력 데이터를 채우는 작업이므로 기존 아키텍처 원칙과 충돌하지 않는다.

### 7.2 4단계 처리

```text
1단계  룰 추출 (extract_source='rule')
       spec_source_text에서 정규식 룰 테이블로 추출. 결정론·무비용. 항상 최우선.

2단계  LLM 원문 추출 (extract_source='ai_text')
       룰이 못 뽑은 필드를 상품명 + spec_source_text에서 LLM이 추출.
       원문에 존재하지만 표기가 비정형인 경우 담당.

3단계  LLM 지식 보강 (extract_source='ai_knowledge')
       원문에 없는 필드를 LLM의 공개 스펙 지식으로 채움.
       모델명 기반 조회 (예: "이엠텍 RTX 4060 WHITE 8GB"의 공개 스펙).

4단계  교차검증 게이트
       2단계(원문)와 3단계(지식)가 독립적으로 산출한 값을 비교.
       - 일치        → verified_yn = true 자동 승격
       - 불일치      → product_reviews(type='spec_conflict', detail에 양측 값) 큐행
       - 한쪽만 존재 → confidence 기준 적용 (0.85 이상 반영·미검증, 미만 큐행)
```

### 7.3 호환성 치명 필드 게이트 (양보 불가 원칙)

`length_mm`, `gpu_max_mm`, `rated_watt`, `socket`은 **verified_yn = true가 되기 전까지 추천 풀 제외**를 유지한다. 근거: 동일 칩셋이라도 제조사 모델별 실측 치수가 크게 다르며(RTX 4060 기준 199~300mm), 이 필드의 오류는 "조립 불가 PC 미출고" 핵심 약속을 직접 깨뜨린다. AI 보강의 목적은 검수 폐지가 아니라 검수 대상을 "빈칸 전부 → 교차검증 불일치분"으로 축소하는 것이다.

### 7.4 검수 운영 규칙

- **검수 큐 기본 정렬은 추천 노출 빈도 내림차순.** 많이 팔리는 부품부터 verified를 채워 체감 커버리지를 최속으로 올린다.
- **"같은 모델 상품에 스펙 복제" 기능.** 동일 model_name의 타 상품코드에 검증 스펙을 복사(verified 유지). 모델 마스터 테이블은 MVP1에서 도입하지 않으며, 검수 부하가 실측 병목이 될 때 정식 승격을 재검토한다.
- 3단계 LLM 호출은 관리자 도메인의 비용 통제(Rate Limit → Cost Guard → Mock Mode) 게이트를 동일하게 거친다.

### 7.5 화면 파급

| 화면 | 변경 |
|---|---|
| ADM-PRD-020 (신규) | 통합 검수 큐 — 대기 목록, 승인/수정/제외, 노출 빈도순 정렬, 스펙 복제 버튼, 교차검증 비교 뷰 |
| ADM-PRD-010 | AI 필드 상태 배지에 verified 구분 추가, 잠금 필드 표시 |
| ADM-CSV-010 | 사전 검증 카드에 "잠긴 필드 N건 보호됨" |
| ADM-DSH-010 | "가격 검토 대기 N건" 미니 위젯 |

---

## 8. 상품 라이프사이클 (워크스루 요약)

| 단계 | 이벤트 | 주요 변경 |
|---|---|---|
| T0 | CSV 최초 업로드 | imports 냉동 + products INSERT + 동기 정규화·룰 추출 실행 |
| T1 | AI 추출 부분 실패 | specs 부분 채움, review_required=true, reviews 큐 등록 |
| T2 | 운영자 검수 보정 | specs 수동값 + verified, locked_fields 등록, review 해제 |
| T3 | CSV 재업로드 | imports 누적, 가격 갱신+history, 잠긴 필드 스킵 |
| T4 | 소싱 확정 매칭 | 매입가 갱신 선택 + history, 판매가 제안 배지 |
| T5 | 품절 토글 | status 변경 → 뷰에서 즉시 제외 (1초 룰) |
| T6 | [Ver 4.0] 단가표 일일 수신 | 프리셋 파싱 → rows 스냅샷 → 어제 대비 diff → 일괄 반영 시 매입가 갱신+history(reason='price_import') + 재계산 판매가 제안 + 발주 상태 갱신 |
| T7 | [Ver 4.0] 자체 주문 생성 | orders+order_items(가격·사양 스냅샷) → stock_reservations(hold) → 결제 승인 시 stock_movements 차감·hold 해제 |

정규화·스펙 추출(1단계)은 **CSV 업서트 트랜잭션 내 동기 실행**한다(룰 기반·LLM 미호출·26,480행 규모 근거). LLM 보강(2~3단계)은 업서트 완료 후 비동기 잡으로 수행한다.

---

## 9. 폐기·대체 항목

| 항목 | 처리 |
|---|---|
| `product_category_normalized` 테이블 | 폐기. 분류 결과는 products 직접 보유, confidence/verified는 specs로 이동 |
| `products.category1~4`, `spec_raw` 컬럼 | 폐기. 원본은 product_imports.raw_row |
| `product_specs.margin_locked` | 폐기. products.locked_fields로 대체 |
| `product_upload_reviews` | product_reviews로 확장 대체 |
| 12번 문서 §9, §18 | 본 문서 §3, §4가 대체 |
| Ver 2.0 추천 후보 쿼리 | §3.6 뷰가 유일한 정의 |
| [Ver 4.0] Ver 3.0 원칙 3 "재고 수량 미보유·상태만 동기화" | 폐기. A-10 커머스 승격 — 재고 단일 원장 = 본 시스템 (§1 원칙 3 개정, §10.6) |
| [Ver 4.0] "주문·고객 = 읽기 전용, 주문 원장 = 쇼핑몰"(A-09 일부) | 폐기. 주문 원장 항상 본 시스템 (§1 원칙 6, §10) |

---

## 10. [Ver 4.0] 커머스 원장 (A-10)

운영 모드 스위치 5종(회원 연동·결제·정산·배송·환불 — 각 `own`/`mall`)과 무관하게 **주문 원장은 항상 본 시스템에 생성**된다. 인계 모드는 복제 전달일 뿐이다.

### 10.1 members — 자체 회원 (+ 쇼핑몰 계정 매핑)

```sql
CREATE TABLE members (
  member_id      BIGSERIAL PRIMARY KEY,
  user_id        BIGINT REFERENCES users(user_id),  -- [검토 반영] 익명 활동 주체와의 승격 관계 — 가입 시 기존 상담·추천 이력 연결
  email          VARCHAR(255) UNIQUE,
  nickname       VARCHAR(100) NOT NULL,
  joined_via     VARCHAR(20) NOT NULL,   -- 'email' / 'kakao' / 'naver'
  mall_member_id VARCHAR(100),           -- 기존 쇼핑몰 계정 매핑 (미연결 NULL — MY-010 "계정 연결")
  mall_map_requested_at TIMESTAMP,       -- [검토 반영] 관리자 매핑 요청 발송 시각 (ADM-CUS-010, 동의 대기)
  status         VARCHAR(20) NOT NULL DEFAULT 'active',
  created_at     TIMESTAMP NOT NULL DEFAULT now()
);
```

> **users ↔ members 관계(검토 이슈 #1):** Ver 2.0 `users`는 **익명 포함 요청 주체**(세션·디바이스 단위)로 유지한다 — `recommendations.user_id`는 그대로. `members`는 가입 회원 원장이며 `user_id`로 익명 이력과 1:0..1 연결된다(가입 시 승격). 상담·주문은 `member_id`(비회원 NULL) 기준.

### 10.2 orders / order_items — 주문 원장 (항상 생성)

```sql
CREATE TABLE orders (
  order_id     BIGSERIAL PRIMARY KEY,
  order_no     VARCHAR(20) UNIQUE NOT NULL,     -- 'ORD-84216'
  member_id    BIGINT REFERENCES members(member_id),
  channel      VARCHAR(10) NOT NULL,            -- 'own' / 'mall'(인계 복제)
  status       VARCHAR(30) NOT NULL,            -- 접수/결제완료/조립중/출고/배송중/완료/취소
  total_amount BIGINT NOT NULL,
  ops_snapshot JSONB NOT NULL,                  -- 생성 시점 운영 모드 5종 스냅샷 (감사)
  created_at   TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE order_items (
  item_id      BIGSERIAL PRIMARY KEY,
  order_id     BIGINT NOT NULL REFERENCES orders(order_id),
  product_code BIGINT REFERENCES products(product_code),
  item_kind    VARCHAR(20) NOT NULL,            -- 'core_part' / 'peripheral' / 'assembly_service'
  name_snap    VARCHAR(500) NOT NULL,           -- 스냅샷 (원칙 6)
  price_snap   BIGINT NOT NULL,
  spec_snap    JSONB,
  qty          INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE order_events (                      -- 상태 이력 (감사)
  event_id   BIGSERIAL PRIMARY KEY,
  order_id   BIGINT NOT NULL REFERENCES orders(order_id),
  from_state VARCHAR(30), to_state VARCHAR(30) NOT NULL,
  actor      VARCHAR(50),                        -- 운영자/시스템/PG
  created_at TIMESTAMP NOT NULL DEFAULT now()
);
```

### 10.3 payments / settlements — 결제·정산 (정산은 결제를 따라간다)

```sql
CREATE TABLE payments (
  payment_id BIGSERIAL PRIMARY KEY,
  order_id   BIGINT NOT NULL REFERENCES orders(order_id),
  pay_mode   VARCHAR(10) NOT NULL,   -- 'own'(자체 PG) / 'mall'(쇼핑몰 인계)
  method     VARCHAR(30),            -- 카드/계좌이체/… (own일 때)
  pg_ref     VARCHAR(100),           -- PG 거래 참조 (own)
  amount     BIGINT NOT NULL,
  status     VARCHAR(20) NOT NULL,   -- 대기/승인/취소/환불
  paid_at    TIMESTAMP
);

CREATE TABLE settlements (
  settlement_id BIGSERIAL PRIMARY KEY,
  payment_id    BIGINT NOT NULL REFERENCES payments(payment_id),
  batch_id      BIGINT REFERENCES settlement_batches(batch_id),  -- [검토 반영] 일 마감 소속
  settle_mode   VARCHAR(10) NOT NULL,  -- 결제 모드를 따라감 (A-10 자동 보정 규칙)
  fee_amount    BIGINT,                -- 카드수수료 등
  net_amount    BIGINT,
  settled_at    TIMESTAMP
);

-- [검토 반영 — 이슈 #5] 일 단위 정산 마감 (ADM-PAY-010 '정산 마감' 액션의 원장)
CREATE TABLE settlement_batches (
  batch_id    BIGSERIAL PRIMARY KEY,
  settle_date DATE NOT NULL UNIQUE,
  gross       BIGINT NOT NULL,
  fee         BIGINT NOT NULL,         -- pricing_settings.card_fee_rate 기준
  net         BIGINT NOT NULL,
  status      VARCHAR(10) NOT NULL DEFAULT '대기',  -- 대기/마감
  closed_by   BIGINT, closed_at TIMESTAMP
);
```

### 10.4 shipments / refunds — 배송·환불(클레임)

```sql
CREATE TABLE shipments (
  shipment_id BIGSERIAL PRIMARY KEY,
  order_id    BIGINT NOT NULL REFERENCES orders(order_id),
  ship_mode   VARCHAR(10) NOT NULL,   -- 'own' / 'mall'
  carrier     VARCHAR(50), tracking_no VARCHAR(50),
  status      VARCHAR(20) NOT NULL,   -- 준비/출고/배송중/완료
  shipped_at  TIMESTAMP, delivered_at TIMESTAMP
);

CREATE TABLE refunds (
  refund_id   BIGSERIAL PRIMARY KEY,
  order_id    BIGINT NOT NULL REFERENCES orders(order_id),
  refund_mode VARCHAR(10) NOT NULL,   -- own-refund는 own-payment 전제 (A-10 자동 보정)
  reason_type VARCHAR(30) NOT NULL,   -- 단순변심/초기불량/오배송/…
  amount      BIGINT NOT NULL,
  status      VARCHAR(20) NOT NULL,   -- 접수/검토/수거·처리/완료/반려 — [검토 반영] ADM-CLM-010 화면 단계와 일치
  created_at  TIMESTAMP NOT NULL DEFAULT now()
);
```

### 10.5 stock_reservations — 재고 예약 (hold)

자체 결제(pay=own) 진행 중에만 활성. 결제 승인 → 차감 전환, 이탈·만료 → 해제.

```sql
CREATE TABLE stock_reservations (
  reservation_id BIGSERIAL PRIMARY KEY,
  order_id       BIGINT NOT NULL REFERENCES orders(order_id),
  product_code   BIGINT NOT NULL REFERENCES products(product_code),
  qty            INTEGER NOT NULL,
  status         VARCHAR(20) NOT NULL DEFAULT 'held',  -- held/converted/released/expired
  expires_at     TIMESTAMP NOT NULL,
  created_at     TIMESTAMP NOT NULL DEFAULT now()
);
```

### 10.6 stock_movements — 입출고 원장

```sql
CREATE TABLE stock_movements (
  movement_id   BIGSERIAL PRIMARY KEY,
  product_code  BIGINT NOT NULL REFERENCES products(product_code),
  movement_type VARCHAR(20) NOT NULL,  -- inbound(매입)/own_sale/mall_sale(API 유입)/adjust/return
  qty_delta     INTEGER NOT NULL,      -- +입고 / -출고
  ref_kind      VARCHAR(20), ref_id BIGINT,   -- order_id, sourcing_id 등
  created_at    TIMESTAMP NOT NULL DEFAULT now()
);
```

### 10.7 member_reviews / member_favorites — 후기(구매 인증만)·관심 부품

```sql
CREATE TABLE member_reviews (
  review_id     BIGSERIAL PRIMARY KEY,
  member_id     BIGINT NOT NULL REFERENCES members(member_id),
  order_item_id BIGINT NOT NULL REFERENCES order_items(item_id),  -- 구매 인증 강제 (A-10: 후기=구매 인증만)
  rating        SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
  body          TEXT,
  status        VARCHAR(20) NOT NULL DEFAULT '게시',  -- [검토 반영] 게시/숨김/신고됨 (ADM-CUS-020)
  cite_s2       BOOLEAN NOT NULL DEFAULT false,       -- [검토 반영] S2 "먼저 받아본 사람들" 근거 인용 여부 — 운영자 선별
  moderation_note VARCHAR(300),                       -- 숨김·신고 처리 사유
  created_at    TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE member_favorites (
  favorite_id  BIGSERIAL PRIMARY KEY,
  member_id    BIGINT NOT NULL REFERENCES members(member_id),
  product_code BIGINT NOT NULL REFERENCES products(product_code),
  price_alert  BOOLEAN NOT NULL DEFAULT false,   -- MY-010 가격 알림 토글
  created_at   TIMESTAMP NOT NULL DEFAULT now(),
  UNIQUE (member_id, product_code)
);
```

---

## 11. [Ver 4.0] 공급처 단가표 (ADM-PRC-040)

거래처가 1일 1회 보내는 단가표 엑셀의 정규화·diff·반영 파이프라인. 실파일 2종(MSI_단가표0716, GBT PCD 0721클릭)으로 검증된 설계다.

### 11.1 suppliers / supplier_presets

```sql
CREATE TABLE suppliers (
  supplier_id   BIGSERIAL PRIMARY KEY,
  name          VARCHAR(100) NOT NULL,   -- '클릭나라', 'MSI(웨이코스)'
  platform      VARCHAR(50),             -- '윈윈' 등 입력 플랫폼
  brands        VARCHAR(200),            -- 취급 브랜드 메모
  created_at    TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE supplier_presets (
  preset_id    BIGSERIAL PRIMARY KEY,
  supplier_id  BIGINT NOT NULL REFERENCES suppliers(supplier_id),
  rules        JSONB NOT NULL,   -- 시트 인식(제외 시트 포함)·헤더 행·칩셋 캐리포워드·스킵 행·가격 열 후보·상태 어휘 정규화(O→가능/X→품절)
  version      INTEGER NOT NULL DEFAULT 1,
  updated_at   TIMESTAMP NOT NULL DEFAULT now()
);
```

### 11.2 supplier_price_files / supplier_price_rows — 일일 스냅샷 (diff 원천)

```sql
CREATE TABLE supplier_price_files (
  file_id     BIGSERIAL PRIMARY KEY,
  supplier_id BIGINT NOT NULL REFERENCES suppliers(supplier_id),
  file_name   VARCHAR(300) NOT NULL,
  received_at TIMESTAMP NOT NULL,
  row_count   INTEGER,
  status      VARCHAR(20) NOT NULL DEFAULT '대기'   -- 대기/반영 완료/부분 반영
);

CREATE TABLE supplier_price_rows (
  row_id       BIGSERIAL PRIMARY KEY,
  file_id      BIGINT NOT NULL REFERENCES supplier_price_files(file_id),
  model_name   VARCHAR(300) NOT NULL,
  danawa_code  VARCHAR(20),             -- 있으면 최우선 매칭 키
  prices       JSONB NOT NULL,          -- 원본 가격 열 전부 {"공급가":..,"현금딜러몰":..}
  cost_price   BIGINT NOT NULL,         -- 매입가 판정값 = 가격 열 중 최저가 (결측 자동 승계)
  supply_state VARCHAR(10),             -- 정규화: 가능/품절/문의
  memo         VARCHAR(200)             -- 비고 원문 ('0721 가격변동', '인상 품절')
);

CREATE INDEX idx_price_rows_file ON supplier_price_rows (file_id);
```

어제 대비 diff(가격 변동/신규/발주 상태 전환/무변동)는 같은 supplier의 직전 file rows와의 비교로 산출한다 — 별도 diff 테이블 없음(스냅샷이 원천).

### 11.3 supplier_product_map — 모델 ↔ SKU 매핑 기억

```sql
CREATE TABLE supplier_product_map (
  map_id       BIGSERIAL PRIMARY KEY,
  supplier_id  BIGINT NOT NULL REFERENCES suppliers(supplier_id),
  model_key    VARCHAR(300) NOT NULL,   -- 정규화된 공급처 모델명(또는 상품코드)
  product_code BIGINT NOT NULL REFERENCES products(product_code),
  match_method VARCHAR(20) NOT NULL,    -- 'danawa_code'(자동) / 'similarity'(후보→검수 확정) / 'manual'
  confirmed_by BIGINT, confirmed_at TIMESTAMP,
  UNIQUE (supplier_id, model_key)
);
```

매칭 우선순위: ① 기억된 map → ② danawa_code 일치(자동 확정) → ③ 이름 유사도(후보 제시) → ④ 검수 확정. 한 번 확정되면 이후 매일 자동.

### 11.4 product_supplier_prices — 상품 1:N 공급처 최신가

```sql
CREATE TABLE product_supplier_prices (
  psp_id       BIGSERIAL PRIMARY KEY,
  product_code BIGINT NOT NULL REFERENCES products(product_code),
  supplier_id  BIGINT NOT NULL REFERENCES suppliers(supplier_id),
  cost_price   BIGINT NOT NULL,
  supply_state VARCHAR(10) NOT NULL,    -- 가능/품절/문의 — 매입 견적(발주 가능성) 신호
  src_file_id  BIGINT REFERENCES supplier_price_files(file_id),
  updated_at   TIMESTAMP NOT NULL DEFAULT now(),
  UNIQUE (product_code, supplier_id)
);
```

`products.purchase_price` 갱신 후보 = 이 테이블의 공급처 간 최저 `cost_price`(발주 가능 상태 우선). "타 공급처 최저가" 표시의 원천.

---

## 12. [Ver 4.0] 상담·견적 스냅샷 (S1·S2·MY-010)

```sql
CREATE TABLE consult_sessions (
  session_id  BIGSERIAL PRIMARY KEY,
  member_id   BIGINT REFERENCES members(member_id),   -- 비회원 NULL
  mode        VARCHAR(10) NOT NULL,    -- guided/chat/expert/talk
  constraints JSONB NOT NULL DEFAULT '[]',   -- 단일 제약객체 스냅샷 (S1 상태 관리 원칙)
  created_at  TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE quote_snapshots (
  snapshot_id BIGSERIAL PRIMARY KEY,
  session_id  BIGINT NOT NULL REFERENCES consult_sessions(session_id),
  quote_type  VARCHAR(20) NOT NULL,    -- value/recommend/highend
  items       JSONB NOT NULL,          -- 부품·가격·근거 스냅샷 — MY-010 "그때 가격으로 다시 보기"
  companion   JSONB,                   -- 함께 구성(주변기기) 선택 스냅샷
  total_amount BIGINT NOT NULL,
  created_at  TIMESTAMP NOT NULL DEFAULT now()
);
```

기존 `recommendations`/`recommendation_items`(Ver 2.0 유지분)는 엔진 산출 기록으로 유지하고, `quote_snapshots`는 **고객에게 보여준 그대로**의 보존본이라는 점에서 역할이 다르다(재현·감사).

---

## 13. [Ver 4.0] 운영 설정 (버전 관리 — 원칙 7)

```sql
CREATE TABLE ops_settings (               -- 운영 모드 스위치 5종 현행값
  key        VARCHAR(30) PRIMARY KEY,     -- member/pay/settle/ship/refund
  mode       VARCHAR(10) NOT NULL,        -- 'own' / 'mall'
  updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE ops_settings_history (
  history_id BIGSERIAL PRIMARY KEY,
  changes    JSONB NOT NULL,              -- 변경 전→후 5종 묶음
  version    INTEGER NOT NULL,
  changed_by BIGINT NOT NULL,             -- 관리자 전용 (A-10)
  reason     VARCHAR(300),
  changed_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE pricing_settings (           -- 판매가 산정 파라미터 (§6.4)
  setting_id    BIGSERIAL PRIMARY KEY,
  card_fee_rate NUMERIC(5,4) NOT NULL,    -- 예: 0.0220 (실요율 확정 필요 — 목업 예시값)
  margin_rate   NUMERIC(5,4) NOT NULL DEFAULT 0,
  effective_from TIMESTAMP NOT NULL,
  created_by    BIGINT,
  created_at    TIMESTAMP NOT NULL DEFAULT now()
);
```

**정합 규칙(A-10, 화면 ADM-OPS-010과 동일):** ① settle은 pay를 따라간다(자동 보정). ② refund=own은 pay=own 전제. ③ 스위치 변경은 관리자 전용 + history 필수. ④ 재고 예약(hold)은 pay=own에서만 활성.
