"""쇼핑몰 가격 반영 — 실행 기록(mall_price_runs) · 가격 확인 기록(mall_price_checks) (2026-10-11).

■ 왜 (2026-10-11 품질관리 R10 · 중헌 님 지시)
  고객 카드 가격(products.sale_price)은 2026-09-28 쇼핑몰 CSV 적재 뒤로 바뀐 적이 없고,
  쇼핑몰 가격은 그 뒤로 계속 움직였다(98149: 카드 1,585,100 · 쇼핑몰 1,624,400).
  중헌 님이 정한 구조는 «두 겹 안전장치»다.

      1겹 배치    관리자 엑셀 업로드(file) · 쇼핑몰 자동 갱신 하루 1~2회(auto) · 손 실행(manual)
      2겹 실시간  장바구니에 넣는 순간(cart) · 결제로 넘어가는 순간(checkout)

  두 겹이 **같은 표 하나**에 남는다 — `moment` 가 어느 겹의 어느 시점인지 말한다.
  그래야 관리자가 한 화면에서 「이 상품 가격이 언제 무엇 때문에 바뀌었나」를 본다.

■ 두 표의 역할
  mall_price_runs    배치 한 번 = 한 행. 언제·성공/실패·건수·실패 사유·되돌림 여부.
                     되돌릴 근거(상품별 이전 값)는 여기 두지 않고 활동 로그(apply_log_id)에
                     둔다 — 다른 일괄 작업(A-115·A-116·mall_daily_sync)과 같은 자리다.
  mall_price_checks  상품 하나를 쇼핑몰과 비교한 한 번 = 한 행. **추가만 한다**(수정·삭제 없음).
                     배치는 «다른 것»만 남기고(같은 값은 실행 요약의 건수로 충분하다),
                     실시간은 «같은 것»도 남긴다(고객이 그 순간 어떤 값을 봤는지가 기록이다).

  실제로 판매가가 바뀐 사실은 지금까지처럼 product_price_history 에 남는다
  (reason = mall_price_file · mall_price_auto · mall_price_manual · mall_price_cart ·
  mall_price_checkout, 배치 되돌림은 각 사유 + _undo). 이 두 표는 그 옆의 «왜·언제 확인했나» 기록이다.

Revision ID: 0145
Revises: 0141
"""
from alembic import op

revision = "0145"
down_revision = "0141"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE mall_price_runs (
          run_id          BIGSERIAL PRIMARY KEY,
          moment          VARCHAR(12) NOT NULL CHECK (moment IN ('file','auto','manual')),
          source          VARCHAR(12),           -- file · export(관리자 상품엑셀) · pages(공개 상품 페이지)
          file_name       VARCHAR(200),
          include_parts   BOOLEAN NOT NULL DEFAULT false,
          started_at      TIMESTAMP NOT NULL DEFAULT now(),
          finished_at     TIMESTAMP,
          ok              BOOLEAN,               -- NULL = 진행 중(또는 끝나지 못하고 죽음)
          fail_reason     VARCHAR(300),
          seen_count      INTEGER,               -- 쇼핑몰 쪽에서 읽은 상품 수
          matched_count   INTEGER,               -- 그중 우리 상품이고 반영 범위인 수
          changed_count   INTEGER,               -- 판매가를 실제로 바꾼 수
          up_count        INTEGER,
          down_count      INTEGER,
          held_count      INTEGER,               -- 큰 변동이라 자동 실행이 보류한 수
          locked_count    INTEGER,               -- 판매가가 잠겨 있어 건너뛴 수
          apply_log_id    BIGINT REFERENCES admin_operator_activity_logs(log_id),
          undo_log_id     BIGINT REFERENCES admin_operator_activity_logs(log_id),
          undone_at       TIMESTAMP,
          operator_id     BIGINT,
          detail          JSONB
        )
    """)
    op.execute("CREATE INDEX ix_mall_price_runs_started ON mall_price_runs (started_at DESC)")
    op.execute("""
        CREATE TABLE mall_price_checks (
          check_id        BIGSERIAL PRIMARY KEY,
          checked_at      TIMESTAMP NOT NULL DEFAULT now(),
          moment          VARCHAR(12) NOT NULL
                          CHECK (moment IN ('file','auto','manual','cart','checkout')),
          run_id          BIGINT REFERENCES mall_price_runs(run_id),
          product_code    BIGINT NOT NULL,
          our_price       BIGINT,                -- 확인 직전 우리 판매가
          mall_price      BIGINT,                -- 쇼핑몰에서 읽은 값(못 읽었으면 NULL)
          diff            BIGINT,                -- mall_price - our_price
          outcome         VARCHAR(12) NOT NULL
                          CHECK (outcome IN ('changed','same','held','locked','stale','failed')),
          note            VARCHAR(200),
          source_url      VARCHAR(300),
          quote_id        UUID,                  -- 실시간 확인일 때 고객의 저장 견적
          visitor_ref     VARCHAR(64)            -- 실시간 확인일 때 고객 세션(익명 방문자 키)
        )
    """)
    op.execute("CREATE INDEX ix_mall_price_checks_at ON mall_price_checks (checked_at DESC)")
    op.execute("CREATE INDEX ix_mall_price_checks_product ON mall_price_checks (product_code, checked_at DESC)")
    op.execute("CREATE INDEX ix_mall_price_checks_run ON mall_price_checks (run_id)")


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM mall_price_runs LIMIT 1) OR EXISTS (SELECT 1 FROM mall_price_checks LIMIT 1)
      THEN RAISE EXCEPTION 'mall price records must be preserved'; END IF; END $$""")
    op.execute("DROP TABLE mall_price_checks")
    op.execute("DROP TABLE mall_price_runs")
