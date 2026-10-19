"""가격 확인 기록의 유효 종료일 — 대표가 정한 상품만 7일 규칙 대신 그 날까지 유효 (2026-10-19 대표 결정 「이 두 개만」).

`mall_price_checks.valid_until` — NULL 이면 지금처럼 확인 후 EVIDENCE_DAYS(7일)까지 유효하다(api/customer_bom_gaps).
값이 있으면 그 시각까지 유효하다. 판매가가 바뀌면 바로 무효인 것은 같다(mall_price = 지금 판매가 조건 그대로).

이 표는 추가만 한다(0145) — 기존 행을 고치지 않는다. 그래서 연장은 새 확인 행을 하나 더 쌓는다:
  대상  109547(삼성 DDR4 16GB) · 127555(KLEVV DDR5 32GB) — 2026-10-15 확인, 10/22 만료 예정이던 두 메모리
  조건  그 상품의 가장 최근 bom-gap 기록이 'same' 이고 그 가격이 지금 판매가와 같을 때만(가격 그대로 연장)
  기록  outcome 'same' · mall_price = 그 확인 가격 · valid_until 2026-12-31 23:59:59 · note 에 대표 지시 표시
조건이 맞지 않으면(가격이 바뀌었거나 기록이 없으면 — 새로 세우는 운영 DB 포함) 아무것도 넣지 않는다.
"""
from alembic import op

revision = '0164'
down_revision = '0163'
branch_labels = None
depends_on = None

CODES = (109547, 127555)
UNTIL = '2026-12-31 23:59:59'
NOTE = 'bom-gap: operator confirmed - owner extension to 2026-12-31 (2026-10-19)'


def upgrade():
    op.execute('ALTER TABLE mall_price_checks ADD COLUMN valid_until TIMESTAMP')
    op.execute(f"""
        INSERT INTO mall_price_checks (moment, product_code, our_price, mall_price, diff, outcome, note, valid_until)
        SELECT 'manual', p.product_code, p.sale_price, last.mall_price, 0, 'same', '{NOTE}', TIMESTAMP '{UNTIL}'
          FROM products p
          JOIN LATERAL (SELECT c.outcome, c.mall_price FROM mall_price_checks c
                         WHERE c.product_code = p.product_code AND c.note LIKE 'bom-gap:%'
                         ORDER BY c.checked_at DESC, c.check_id DESC LIMIT 1) last ON true
         WHERE p.product_code IN {CODES}
           AND last.outcome = 'same' AND last.mall_price = p.sale_price""")


def downgrade():
    # 기록은 지우지 않는다(추가만 하는 표). 열을 지우면 연장 기록의 의미가 사라지므로 막는다.
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM mall_price_checks WHERE valid_until IS NOT NULL)
      THEN RAISE EXCEPTION 'valid_until records must be preserved'; END IF; END $$""")
    op.execute('ALTER TABLE mall_price_checks DROP COLUMN valid_until')
