# -*- coding: utf-8 -*-
"""인계 원장 — `handoffs` · `handoff_items` (2026-08-11)

■ 왜 `orders` 를 쓰지 않나
  범위 확정(2026-08-11): 팝콘AI 는 **판매하지 않는다.** 견적을 만들어 팝콘PC 쇼핑몰로
  넘기고, 결제·배송·환불은 그쪽이 한다. 그러면 인계는 **주문이 아니다** —
  결제도, 재고 차감도, 배송지도 없다.

  `orders` 에 `channel='mall'` 로 섞어 넣으면 「주문 20건」이 실제 판매와 인계를 함께
  세게 된다. **화면이 사실을 흐리는 것** — 이 프로젝트가 고치고 있는 병이 그거다.
  그리고 유입 성과(인계 → 구매 전환)를 재려면 인계가 독립 사건이어야 한다.

■ 가격을 두 개 남긴다
  `price_quoted` 는 **고객에게 보여준 값**, `price_mall` 은 **인계 시점 몰 값**이다.
  둘이 다를 수 있다는 것이 오늘 실측으로 확인됐다(표본 10건 중 2건, HDD 는 5,100원
  싸게 안내 중이었다). 하나로 합치면 «우리가 뭘 보여줬는지»가 사라져 나중에 답할 수 없다.

■ 재고를 잠그지 않는다
  재고 원장은 쇼핑몰이 갖는다. 우리가 잠그면 두 곳이 어긋난다.
  품절은 인계 시점에 **알리기만** 한다.
"""
from alembic import op
import sqlalchemy as sa

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS handoffs (
            handoff_id    BIGSERIAL   PRIMARY KEY,
            handoff_no    VARCHAR(20) NOT NULL UNIQUE,
            session_id    BIGINT,
            snapshot_id   BIGINT,
            quote_type    VARCHAR(16),
            member_id     BIGINT,
            user_id       BIGINT,
            total_quoted  BIGINT      NOT NULL,
            total_mall    BIGINT,
            price_checked BOOLEAN     NOT NULL DEFAULT false,
            changed_cnt   INTEGER     NOT NULL DEFAULT 0,
            soldout_cnt   INTEGER     NOT NULL DEFAULT 0,
            status        VARCHAR(16) NOT NULL DEFAULT '인계',
            note          TEXT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )"""))
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS handoff_items (
            handoff_id    BIGINT      NOT NULL REFERENCES handoffs(handoff_id) ON DELETE CASCADE,
            line_no       INTEGER     NOT NULL,
            product_code  BIGINT,
            item_kind     VARCHAR(20) NOT NULL,
            part_type     VARCHAR(20),
            name_snap     TEXT        NOT NULL,
            price_quoted  BIGINT      NOT NULL,
            price_mall    BIGINT,
            qty           INTEGER     NOT NULL DEFAULT 1,
            mall_status   VARCHAR(16),
            PRIMARY KEY (handoff_id, line_no)
        )"""))
    for stmt in (
        "COMMENT ON TABLE handoffs IS "
        "'쇼핑몰 인계 원장. 주문이 아니다 — 결제·재고 차감·배송지가 없다(범위 결정 2026-08-11)'",
        "COMMENT ON COLUMN handoffs.price_checked IS "
        "'인계 시점에 몰 가격을 실제로 재확인했는가. false 면 견적 시점 가격 그대로 넘겼다'",
        "COMMENT ON COLUMN handoff_items.price_quoted IS '고객에게 보여준 값'",
        "COMMENT ON COLUMN handoff_items.price_mall IS "
        "'인계 시점 몰 값. price_quoted 와 다르면 고객에게 알린다'",
    ):
        conn.execute(sa.text(stmt))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_handoffs_created ON handoffs (created_at DESC)"))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_handoffs_session ON handoffs (session_id)"))


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS handoff_items"))
    conn.execute(sa.text("DROP TABLE IF EXISTS handoffs"))
