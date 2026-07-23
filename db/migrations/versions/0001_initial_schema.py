"""ERD Ver 4.0 초기 스키마 — 상품 스파인 + 커머스 원장 + 공급처 단가표 + 상담 스냅샷 + 운영 설정

단일 원천: docs/06_db-erd.md Ver 4.0 (1차 검토 반영판)
DDL 작성 시 2차 검토 반영 2건:
  - products.sku 추가 — 화면(ADM-PRD-010)의 SKU(P-xxxx)는 product_code(자체상품번호)와 별개 식별자
  - 후보 뷰: SELECT p.*, ps.* 는 중복 컬럼으로 불가 → 명시 컬럼 + ps.updated_at 별칭(spec_updated_at)
Ver 2.0 유지 테이블은 원문 DDL 부재로 최소 정의(주석 [V2-min]) — API 단계에서 필드 확장.

Revision ID: 0001
Revises:
Create Date: 2026-07-23
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

DDL = r"""
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ======================= 0. [V2-min] 기반 테이블 (최소 정의) =======================

CREATE TABLE users (                       -- 익명 포함 요청 주체 (세션·디바이스 단위)
  user_id     BIGSERIAL PRIMARY KEY,
  anon_key    VARCHAR(64) UNIQUE,          -- 브라우저/디바이스 식별
  created_at  TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE admin_operators (
  operator_id BIGSERIAL PRIMARY KEY,
  name        VARCHAR(100) NOT NULL,
  email       VARCHAR(255) UNIQUE,
  role        VARCHAR(30) NOT NULL DEFAULT 'operator',
  status      VARCHAR(20) NOT NULL DEFAULT 'active',
  created_at  TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE admin_operator_activity_logs (
  log_id      BIGSERIAL PRIMARY KEY,
  operator_id BIGINT REFERENCES admin_operators(operator_id),
  action      VARCHAR(100) NOT NULL,
  target_kind VARCHAR(50), target_id VARCHAR(100),
  detail      JSONB,
  created_at  TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE csv_import_jobs (
  job_id      BIGSERIAL PRIMARY KEY,
  file_name   VARCHAR(300),
  row_total   INTEGER, row_ok INTEGER, row_error INTEGER,
  status      VARCHAR(20) NOT NULL DEFAULT '대기',
  created_by  BIGINT REFERENCES admin_operators(operator_id),
  created_at  TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE csv_import_errors (
  error_id    BIGSERIAL PRIMARY KEY,
  job_id      BIGINT NOT NULL REFERENCES csv_import_jobs(job_id),
  row_no      INTEGER,
  raw_row     JSONB,
  reason      VARCHAR(300),
  created_at  TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE policy_weights (              -- 추천 스코어 가중치
  key         VARCHAR(50) PRIMARY KEY,
  weight      NUMERIC(6,3) NOT NULL,
  updated_at  TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE category_margin_policies (
  category    VARCHAR(50) PRIMARY KEY,
  margin_rate NUMERIC(5,4) NOT NULL DEFAULT 0,
  updated_at  TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE api_cost_logs (
  log_id      BIGSERIAL PRIMARY KEY,
  provider    VARCHAR(50), model VARCHAR(100),
  tokens_in   INTEGER, tokens_out INTEGER, cost_usd NUMERIC(10,5),
  created_at  TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE rate_limit_policies (
  key         VARCHAR(50) PRIMARY KEY,
  per_minute  INTEGER, per_day INTEGER,
  updated_at  TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE cost_thresholds (
  key         VARCHAR(50) PRIMARY KEY,
  daily_usd   NUMERIC(10,2),
  action      VARCHAR(30),                 -- warn / mock_mode / block
  updated_at  TIMESTAMP NOT NULL DEFAULT now()
);

-- ======================= 1. 상품 스파인 (ERD §3) =======================

CREATE TABLE products (
  product_code        BIGINT PRIMARY KEY,          -- 자체상품번호 (예: 20481001)
  sku                 VARCHAR(20) UNIQUE,          -- [2차 검토] 화면 표기 SKU (예: P-1001)
  product_name        VARCHAR(500) NOT NULL,
  maker               VARCHAR(100),
  brand               VARCHAR(100),
  model_name          VARCHAR(255),
  part_type           VARCHAR(50) NOT NULL,
  category_group      VARCHAR(50) NOT NULL,        -- core_part/peripheral/service/prebuilt_pc/internal/unknown
  status              VARCHAR(20) NOT NULL,        -- 판매중/품절/단종/삭제대기
  ai_candidate_yn     BOOLEAN NOT NULL DEFAULT false,
  review_required_yn  BOOLEAN NOT NULL DEFAULT false,
  purchase_price      BIGINT,
  sale_price          BIGINT,
  market_price        BIGINT,
  locked_fields       JSONB NOT NULL DEFAULT '[]',
  supplier            VARCHAR(200),                -- [폐기 예정] product_supplier_prices로 대체
  warranty_months     INTEGER,
  spec_source_text    TEXT,
  danawa_code         VARCHAR(20),                 -- 거래처 간 교차 매칭 키
  stock_qty           INTEGER NOT NULL DEFAULT 0,  -- 재고 단일 원장 (A-10)
  created_at          TIMESTAMP NOT NULL DEFAULT now(),
  updated_at          TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX idx_products_candidate ON products (status, ai_candidate_yn, part_type);
CREATE INDEX idx_products_name_trgm ON products USING gin (product_name gin_trgm_ops);
CREATE UNIQUE INDEX idx_products_danawa ON products (danawa_code) WHERE danawa_code IS NOT NULL;

CREATE TABLE product_specs (
  product_code    BIGINT PRIMARY KEY REFERENCES products(product_code),
  part_type       VARCHAR(50) NOT NULL,
  socket          VARCHAR(30),
  chipset         VARCHAR(50),
  mem_type        VARCHAR(10),
  capacity_gb     INTEGER,
  clock_mhz       INTEGER,
  tdp_watt        INTEGER,
  rated_watt      INTEGER,
  required_power_watt INTEGER,
  length_mm       INTEGER,
  gpu_max_mm      INTEGER,
  cooler_height_mm INTEGER,
  cooler_tdp      INTEGER,
  pcie_gen        VARCHAR(20),
  form_factor     VARCHAR(50),
  interface       VARCHAR(50),
  tag_white       BOOLEAN NOT NULL DEFAULT false,
  tag_rgb         BOOLEAN NOT NULL DEFAULT false,
  tag_silent      BOOLEAN NOT NULL DEFAULT false,
  -- 주변기기 (Ver 4.0)
  size_inch       NUMERIC(4,1),
  resolution      VARCHAR(20),
  refresh_hz      INTEGER,
  panel           VARCHAR(20),
  ports           JSONB,
  switch_type     VARCHAR(30),
  key_layout      VARCHAR(20),
  connection      VARCHAR(20),
  extract_source  VARCHAR(20),
  confidence      NUMERIC(4,2),
  verified_yn     BOOLEAN NOT NULL DEFAULT false,
  updated_at      TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE product_imports (
  import_id    BIGSERIAL PRIMARY KEY,
  job_id       BIGINT REFERENCES csv_import_jobs(job_id),
  product_code BIGINT,
  raw_row      JSONB NOT NULL,
  imported_at  TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX idx_imports_product ON product_imports (product_code, imported_at DESC);

CREATE TABLE product_price_history (
  history_id   BIGSERIAL PRIMARY KEY,
  product_code BIGINT NOT NULL REFERENCES products(product_code),
  field        VARCHAR(20) NOT NULL,   -- purchase / sale / market
  old_price    BIGINT,
  new_price    BIGINT NOT NULL,
  reason       VARCHAR(30) NOT NULL,   -- csv / sourcing / margin_policy / manual / price_import
  ref_id       BIGINT,
  changed_by   BIGINT,
  changed_at   TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX idx_price_history_product ON product_price_history (product_code, changed_at DESC);

CREATE TABLE product_reviews (
  review_id     BIGSERIAL PRIMARY KEY,
  product_code  BIGINT REFERENCES products(product_code),
  review_type   VARCHAR(30) NOT NULL,
  field_name    VARCHAR(50),
  detail        TEXT,
  review_status VARCHAR(30) NOT NULL DEFAULT '대기',
  reviewed_by   BIGINT,
  reviewed_at   TIMESTAMP,
  created_at    TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX idx_reviews_queue ON product_reviews (review_status, created_at);

-- [V2-min] 추천·로그·소싱
CREATE TABLE recommendations (
  recommendation_id BIGSERIAL PRIMARY KEY,
  user_id     BIGINT REFERENCES users(user_id),
  quote_type  VARCHAR(20),
  constraints JSONB,
  created_at  TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE recommendation_items (
  item_id           BIGSERIAL PRIMARY KEY,
  recommendation_id BIGINT NOT NULL REFERENCES recommendations(recommendation_id),
  product_code      BIGINT REFERENCES products(product_code),
  slot              VARCHAR(30),
  reason            TEXT
);

CREATE TABLE promo_click_logs (
  log_id       BIGSERIAL PRIMARY KEY,
  product_code BIGINT REFERENCES products(product_code),
  user_id      BIGINT REFERENCES users(user_id),
  created_at   TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE swap_event_logs (
  log_id       BIGSERIAL PRIMARY KEY,
  from_product BIGINT REFERENCES products(product_code),
  to_product   BIGINT REFERENCES products(product_code),
  user_id      BIGINT REFERENCES users(user_id),
  created_at   TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE sourcing_batches (
  batch_id    BIGSERIAL PRIMARY KEY,
  title       VARCHAR(200),
  status      VARCHAR(20) NOT NULL DEFAULT '진행',
  created_at  TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE product_sourcing_quotes (
  quote_id    BIGSERIAL PRIMARY KEY,
  batch_id    BIGINT REFERENCES sourcing_batches(batch_id),
  product_code BIGINT REFERENCES products(product_code),
  vendor      VARCHAR(200),
  price       BIGINT,
  status      VARCHAR(20) NOT NULL DEFAULT '대기',
  created_at  TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE product_sourcing_match_candidates (
  candidate_id BIGSERIAL PRIMARY KEY,
  quote_id    BIGINT REFERENCES product_sourcing_quotes(quote_id),
  product_code BIGINT REFERENCES products(product_code),
  similarity  NUMERIC(4,2),
  created_at  TIMESTAMP NOT NULL DEFAULT now()
);

-- ======================= 2. 커머스 원장 (ERD §10, A-10) =======================

CREATE TABLE members (
  member_id      BIGSERIAL PRIMARY KEY,
  user_id        BIGINT REFERENCES users(user_id),   -- 익명→회원 승격 연결
  email          VARCHAR(255) UNIQUE,
  nickname       VARCHAR(100) NOT NULL,
  joined_via     VARCHAR(20) NOT NULL,               -- email / kakao / naver
  mall_member_id VARCHAR(100),
  mall_map_requested_at TIMESTAMP,
  status         VARCHAR(20) NOT NULL DEFAULT 'active',
  created_at     TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE orders (
  order_id     BIGSERIAL PRIMARY KEY,
  order_no     VARCHAR(20) UNIQUE NOT NULL,
  member_id    BIGINT REFERENCES members(member_id),
  channel      VARCHAR(10) NOT NULL,                 -- own / mall
  status       VARCHAR(30) NOT NULL,                 -- 접수/결제완료/조립중/출고/배송중/완료/취소
  total_amount BIGINT NOT NULL,
  ops_snapshot JSONB NOT NULL,
  created_at   TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE order_items (
  item_id      BIGSERIAL PRIMARY KEY,
  order_id     BIGINT NOT NULL REFERENCES orders(order_id),
  product_code BIGINT REFERENCES products(product_code),
  item_kind    VARCHAR(20) NOT NULL,                 -- core_part / peripheral / assembly_service
  name_snap    VARCHAR(500) NOT NULL,
  price_snap   BIGINT NOT NULL,
  spec_snap    JSONB,
  qty          INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE order_events (
  event_id   BIGSERIAL PRIMARY KEY,
  order_id   BIGINT NOT NULL REFERENCES orders(order_id),
  from_state VARCHAR(30), to_state VARCHAR(30) NOT NULL,
  actor      VARCHAR(50),
  created_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE payments (
  payment_id BIGSERIAL PRIMARY KEY,
  order_id   BIGINT NOT NULL REFERENCES orders(order_id),
  pay_mode   VARCHAR(10) NOT NULL,     -- own / mall
  method     VARCHAR(30),
  pg_ref     VARCHAR(100),
  amount     BIGINT NOT NULL,
  status     VARCHAR(20) NOT NULL,     -- 대기/승인/취소/환불
  paid_at    TIMESTAMP
);

CREATE TABLE settlement_batches (
  batch_id    BIGSERIAL PRIMARY KEY,
  settle_date DATE NOT NULL UNIQUE,
  gross       BIGINT NOT NULL,
  fee         BIGINT NOT NULL,
  net         BIGINT NOT NULL,
  status      VARCHAR(10) NOT NULL DEFAULT '대기',
  closed_by   BIGINT, closed_at TIMESTAMP
);

CREATE TABLE settlements (
  settlement_id BIGSERIAL PRIMARY KEY,
  payment_id    BIGINT NOT NULL REFERENCES payments(payment_id),
  batch_id      BIGINT REFERENCES settlement_batches(batch_id),
  settle_mode   VARCHAR(10) NOT NULL,
  fee_amount    BIGINT,
  net_amount    BIGINT,
  settled_at    TIMESTAMP
);

CREATE TABLE shipments (
  shipment_id BIGSERIAL PRIMARY KEY,
  order_id    BIGINT NOT NULL REFERENCES orders(order_id),
  ship_mode   VARCHAR(10) NOT NULL,
  carrier     VARCHAR(50), tracking_no VARCHAR(50),
  status      VARCHAR(20) NOT NULL,    -- 준비/출고/배송중/완료
  shipped_at  TIMESTAMP, delivered_at TIMESTAMP
);

CREATE TABLE refunds (
  refund_id   BIGSERIAL PRIMARY KEY,
  order_id    BIGINT NOT NULL REFERENCES orders(order_id),
  refund_mode VARCHAR(10) NOT NULL,
  reason_type VARCHAR(30) NOT NULL,
  amount      BIGINT NOT NULL,
  status      VARCHAR(20) NOT NULL,    -- 접수/검토/수거·처리/완료/반려
  created_at  TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE stock_reservations (
  reservation_id BIGSERIAL PRIMARY KEY,
  order_id       BIGINT NOT NULL REFERENCES orders(order_id),
  product_code   BIGINT NOT NULL REFERENCES products(product_code),
  qty            INTEGER NOT NULL,
  status         VARCHAR(20) NOT NULL DEFAULT 'held',
  expires_at     TIMESTAMP NOT NULL,
  created_at     TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE stock_movements (
  movement_id   BIGSERIAL PRIMARY KEY,
  product_code  BIGINT NOT NULL REFERENCES products(product_code),
  movement_type VARCHAR(20) NOT NULL,  -- inbound/own_sale/mall_sale/adjust/return
  qty_delta     INTEGER NOT NULL,
  ref_kind      VARCHAR(20), ref_id BIGINT,
  created_at    TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE member_reviews (
  review_id     BIGSERIAL PRIMARY KEY,
  member_id     BIGINT NOT NULL REFERENCES members(member_id),
  order_item_id BIGINT NOT NULL REFERENCES order_items(item_id),
  rating        SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
  body          TEXT,
  status        VARCHAR(20) NOT NULL DEFAULT '게시',
  cite_s2       BOOLEAN NOT NULL DEFAULT false,
  moderation_note VARCHAR(300),
  created_at    TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE member_favorites (
  favorite_id  BIGSERIAL PRIMARY KEY,
  member_id    BIGINT NOT NULL REFERENCES members(member_id),
  product_code BIGINT NOT NULL REFERENCES products(product_code),
  price_alert  BOOLEAN NOT NULL DEFAULT false,
  created_at   TIMESTAMP NOT NULL DEFAULT now(),
  UNIQUE (member_id, product_code)
);

-- ======================= 3. 공급처 단가표 (ERD §11) =======================

CREATE TABLE suppliers (
  supplier_id   BIGSERIAL PRIMARY KEY,
  name          VARCHAR(100) NOT NULL,
  platform      VARCHAR(50),
  brands        VARCHAR(200),
  created_at    TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE supplier_presets (
  preset_id    BIGSERIAL PRIMARY KEY,
  supplier_id  BIGINT NOT NULL REFERENCES suppliers(supplier_id),
  rules        JSONB NOT NULL,
  version      INTEGER NOT NULL DEFAULT 1,
  updated_at   TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE supplier_price_files (
  file_id     BIGSERIAL PRIMARY KEY,
  supplier_id BIGINT NOT NULL REFERENCES suppliers(supplier_id),
  file_name   VARCHAR(300) NOT NULL,
  received_at TIMESTAMP NOT NULL,
  row_count   INTEGER,
  status      VARCHAR(20) NOT NULL DEFAULT '대기'
);

CREATE TABLE supplier_price_rows (
  row_id       BIGSERIAL PRIMARY KEY,
  file_id      BIGINT NOT NULL REFERENCES supplier_price_files(file_id),
  model_name   VARCHAR(300) NOT NULL,
  danawa_code  VARCHAR(20),
  prices       JSONB NOT NULL,
  cost_price   BIGINT NOT NULL,        -- 가격 열 중 최저가 판정값
  supply_state VARCHAR(10),            -- 가능/품절/문의
  memo         VARCHAR(200)
);
CREATE INDEX idx_price_rows_file ON supplier_price_rows (file_id);

CREATE TABLE supplier_product_map (
  map_id       BIGSERIAL PRIMARY KEY,
  supplier_id  BIGINT NOT NULL REFERENCES suppliers(supplier_id),
  model_key    VARCHAR(300) NOT NULL,
  product_code BIGINT NOT NULL REFERENCES products(product_code),
  match_method VARCHAR(20) NOT NULL,   -- danawa_code / similarity / manual
  confirmed_by BIGINT, confirmed_at TIMESTAMP,
  UNIQUE (supplier_id, model_key)
);

CREATE TABLE product_supplier_prices (
  psp_id       BIGSERIAL PRIMARY KEY,
  product_code BIGINT NOT NULL REFERENCES products(product_code),
  supplier_id  BIGINT NOT NULL REFERENCES suppliers(supplier_id),
  cost_price   BIGINT NOT NULL,
  supply_state VARCHAR(10) NOT NULL,
  src_file_id  BIGINT REFERENCES supplier_price_files(file_id),
  updated_at   TIMESTAMP NOT NULL DEFAULT now(),
  UNIQUE (product_code, supplier_id)
);

-- ======================= 4. 상담·견적 스냅샷 (ERD §12) =======================

CREATE TABLE consult_sessions (
  session_id  BIGSERIAL PRIMARY KEY,
  member_id   BIGINT REFERENCES members(member_id),
  mode        VARCHAR(10) NOT NULL,    -- guided/chat/expert/talk
  constraints JSONB NOT NULL DEFAULT '[]',
  created_at  TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE quote_snapshots (
  snapshot_id BIGSERIAL PRIMARY KEY,
  session_id  BIGINT NOT NULL REFERENCES consult_sessions(session_id),
  quote_type  VARCHAR(20) NOT NULL,
  items       JSONB NOT NULL,
  companion   JSONB,
  total_amount BIGINT NOT NULL,
  created_at  TIMESTAMP NOT NULL DEFAULT now()
);

-- ======================= 5. 운영 설정 (ERD §13) =======================

CREATE TABLE ops_settings (
  key        VARCHAR(30) PRIMARY KEY,   -- member/pay/settle/ship/refund
  mode       VARCHAR(10) NOT NULL,      -- own / mall
  updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE ops_settings_history (
  history_id BIGSERIAL PRIMARY KEY,
  changes    JSONB NOT NULL,
  version    INTEGER NOT NULL,
  changed_by BIGINT NOT NULL,
  reason     VARCHAR(300),
  changed_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE pricing_settings (
  setting_id    BIGSERIAL PRIMARY KEY,
  card_fee_rate NUMERIC(5,4) NOT NULL,
  margin_rate   NUMERIC(5,4) NOT NULL DEFAULT 0,
  effective_from TIMESTAMP NOT NULL,
  created_by    BIGINT,
  created_at    TIMESTAMP NOT NULL DEFAULT now()
);

-- ======================= 6. 뷰 (명시 컬럼 — p.*, ps.* 중복 컬럼 회피) =======================

CREATE VIEW v_recommendation_candidates AS
SELECT p.*,
  ps.socket, ps.chipset, ps.mem_type, ps.capacity_gb, ps.clock_mhz, ps.tdp_watt,
  ps.rated_watt, ps.required_power_watt, ps.length_mm, ps.gpu_max_mm, ps.cooler_height_mm,
  ps.cooler_tdp, ps.pcie_gen, ps.form_factor, ps.interface,
  ps.tag_white, ps.tag_rgb, ps.tag_silent,
  ps.extract_source, ps.confidence, ps.verified_yn, ps.updated_at AS spec_updated_at
FROM products p
JOIN product_specs ps USING (product_code)
WHERE p.status = '판매중'
  AND p.ai_candidate_yn = true
  AND p.review_required_yn = false
  AND p.category_group = 'core_part'
  AND p.part_type IN ('CPU','GPU','MB','RAM','SSD','HDD','POWER','CASE','COOLER_CPU_AIR','COOLER_CPU_AIO');

CREATE VIEW v_companion_candidates AS
SELECT p.*,
  ps.size_inch, ps.resolution, ps.refresh_hz, ps.panel, ps.ports,
  ps.switch_type, ps.key_layout, ps.connection,
  ps.confidence, ps.verified_yn, ps.updated_at AS spec_updated_at
FROM products p
JOIN product_specs ps USING (product_code)
WHERE p.status = '판매중'
  AND p.review_required_yn = false
  AND p.category_group = 'peripheral'
  AND p.part_type IN ('MONITOR','KEYBOARD','MOUSE','HEADSET','SPEAKER','WEBCAM');
"""

DROP = r"""
DROP VIEW IF EXISTS v_companion_candidates;
DROP VIEW IF EXISTS v_recommendation_candidates;
DROP TABLE IF EXISTS
  pricing_settings, ops_settings_history, ops_settings,
  quote_snapshots, consult_sessions,
  product_supplier_prices, supplier_product_map, supplier_price_rows, supplier_price_files, supplier_presets, suppliers,
  member_favorites, member_reviews, stock_movements, stock_reservations, refunds, shipments,
  settlements, settlement_batches, payments, order_events, order_items, orders, members,
  product_sourcing_match_candidates, product_sourcing_quotes, sourcing_batches,
  swap_event_logs, promo_click_logs, recommendation_items, recommendations,
  product_reviews, product_price_history, product_imports, product_specs, products,
  cost_thresholds, rate_limit_policies, api_cost_logs, category_margin_policies, policy_weights,
  csv_import_errors, csv_import_jobs, admin_operator_activity_logs, admin_operators, users
CASCADE;
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute(DROP)
