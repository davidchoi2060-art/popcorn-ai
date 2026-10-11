"""결제·정산 기록장 — 관리자가 은행·PG 에서 확인한 거래를 적는다 (2026-10-11 사장님 「기록장」 · 「표시만」).

옛 정산(`settlement_batches`·`settlements`, ADM-PAY-010)은 그대로 둔다. 이 표들은 그 옆에 따로 선다.
기록을 적어도 주문·결제·환불·재고 상태는 바뀌지 않는다 — 이 표들만 쓴다.

  · `payment_confirmation_records`      거래 1건 = 1행. 고치지 않고 추가만 한다.
                                        정정·철회는 새 행이 원래 행을 `supersedes_id` 로 가리킨다.
                                        한 행은 한 번만 이어받을 수 있다(동시 정정 충돌을 DB 가 막는다).
  · `payment_confirmation_allocations`  그 거래를 어느 주문에 얼마씩 나눴나(부분 입금 · 여러 주문 합산).
  · `payment_month_reviews`             「월별 기록 점검 완료」 표시. 잠그지 않는다(사장님 「표시만」).
"""
from alembic import op

revision = '0155'
down_revision = '0154'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE payment_confirmation_records (
  record_id     BIGSERIAL PRIMARY KEY,
  kind          VARCHAR(12) NOT NULL CHECK (kind IN ('deposit','settlement','refund')),
  source        VARCHAR(8)  NOT NULL CHECK (source IN ('bank','pg','mall')),
  institution   VARCHAR(60) NOT NULL CHECK (length(btrim(institution)) > 0),
  external_ref  VARCHAR(120) CHECK (external_ref IS NULL OR length(btrim(external_ref)) > 0),
  amount        BIGINT NOT NULL CHECK (amount > 0),
  occurred_on   DATE NOT NULL,
  confirmed_on  DATE NOT NULL,
  memo          TEXT,
  action        VARCHAR(10) NOT NULL DEFAULT 'create' CHECK (action IN ('create','correct','withdraw')),
  supersedes_id BIGINT REFERENCES payment_confirmation_records(record_id),
  reason        TEXT,
  recorded_by   BIGINT NOT NULL REFERENCES admin_operators(operator_id),
  recorded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK ((action = 'create') = (supersedes_id IS NULL)),
  CHECK (action = 'create' OR length(btrim(coalesce(reason, ''))) > 0)
);
CREATE UNIQUE INDEX payment_confirmation_records_successor
  ON payment_confirmation_records(supersedes_id) WHERE supersedes_id IS NOT NULL;
CREATE INDEX payment_confirmation_records_month ON payment_confirmation_records(occurred_on);
CREATE INDEX payment_confirmation_records_ref
  ON payment_confirmation_records(institution, external_ref) WHERE external_ref IS NOT NULL;

CREATE TABLE payment_confirmation_allocations (
  allocation_id BIGSERIAL PRIMARY KEY,
  record_id     BIGINT NOT NULL REFERENCES payment_confirmation_records(record_id),
  order_id      BIGINT NOT NULL REFERENCES orders(order_id),
  amount        BIGINT NOT NULL CHECK (amount > 0),
  UNIQUE (record_id, order_id)
);
CREATE INDEX payment_confirmation_allocations_order ON payment_confirmation_allocations(order_id);

CREATE TABLE payment_month_reviews (
  review_id   BIGSERIAL PRIMARY KEY,
  month       DATE NOT NULL CHECK (EXTRACT(DAY FROM month) = 1),
  note        TEXT,
  reviewed_by BIGINT NOT NULL REFERENCES admin_operators(operator_id),
  reviewed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX payment_month_reviews_month ON payment_month_reviews(month, reviewed_at DESC);
""")


def downgrade():
    op.execute('DROP TABLE payment_month_reviews')
    op.execute('DROP TABLE payment_confirmation_allocations')
    op.execute('DROP TABLE payment_confirmation_records')
