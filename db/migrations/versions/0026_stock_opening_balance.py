"""기초 재고 — 원장 밖에 있던 재고를 원장 안으로 (슬라이스 98).

■ 무엇이 어긋나 있었나
카탈로그 적재가 `products.stock_qty`를 직접 넣으면서 `stock_movements`에는 아무것도
남기지 않았다. 그래서 이런 상태가 됐다(2026-07-30 실측):

    재고 != 원장 합       7,594건
    재고>0 인데 원장 없음  7,547건
    원장 실제 내용        own_sale 63 · inbound 14 · return 10 · adjust 6

**`stock_movements` 합으로 재고를 검증할 수 없다는 뜻**이다. 재고 정합성 불변식을
세울 수 없고, "이 재고가 어디서 왔나"에 답할 수 없다(슬라이스 69가 경고한 상태).

■ 왜 '기초 재고'인가 — 없는 이력을 지어내지 않기 위해서다
과거 입고 시점·수량을 우리는 모른다. 그럴듯한 `inbound` 행을 날짜까지 만들어 넣으면
그건 지어낸 값이고, 이 프로젝트가 금지한 것이다("지어낸 태그는 '조용하게'라고 말한
이유를 배신한다" — 선호 태그 결정과 같은 원칙).

회계에는 이 상황을 위한 개념이 있다 — **기초 재고(opening balance)**.
"과거를 재구성하지 않고, 지금 시점에 이만큼 있다고 기록한다."
그래서 `ref_kind='opening'`으로 남긴다. 이 행은 **입고를 주장하지 않는다.**
언제 들어왔는지 모른다는 사실까지 함께 기록하는 셈이다.

■ 멱등하다
재고>0이면서 원장이 아예 없는 상품만 대상이다. 두 번 돌려도 두 번 생기지 않는다.
운영 서버는 빈 DB에서 시작하므로(I-01) 여기서 0건이고, 그쪽은 적재가 처음부터
원장을 남긴다(같은 슬라이스에서 `catalog_ingest`를 고쳤다).

■ 되돌리기
downgrade는 이 마이그레이션이 만든 행만 지운다(`ref_kind='opening'`).
원장을 지우는 것이 규약에 어긋나 보이지만, 이 행들은 거래가 아니라 **기준선**이다 —
기준선을 잘못 그었으면 다시 그을 수 있어야 한다.

Revision ID: 0026
Revises: 0025
"""
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO stock_movements (product_code, movement_type, qty_delta, ref_kind, ref_id)
        SELECT p.product_code, 'adjust', p.stock_qty, 'opening', NULL
          FROM products p
         WHERE p.stock_qty > 0
           AND NOT EXISTS (SELECT 1 FROM stock_movements m
                            WHERE m.product_code = p.product_code)
    """)
    # 남은 어긋남 — 원장은 있으나 합이 재고와 다른 상품(판매·반품이 섞인 경우).
    # 차액만 기초 재고로 메운다. 여기서도 과거를 재구성하지 않는다.
    op.execute("""
        INSERT INTO stock_movements (product_code, movement_type, qty_delta, ref_kind, ref_id)
        SELECT p.product_code, 'adjust', p.stock_qty - s.sum_delta, 'opening', NULL
          FROM products p
          JOIN (SELECT product_code, SUM(qty_delta) AS sum_delta
                  FROM stock_movements GROUP BY product_code) s
               ON s.product_code = p.product_code
         WHERE p.stock_qty <> s.sum_delta
    """)


def downgrade() -> None:
    op.execute("DELETE FROM stock_movements WHERE ref_kind = 'opening'")
