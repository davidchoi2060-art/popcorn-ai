"""조립 부품 판매 보기 — 조립PC 부품마다 판매 상품 연결 상태를 한 줄로 (2026-10-11 부품 상품화 1단계).

조립PC 구성표(`pc_configuration_parts`)는 부품을 `product_explanations` 로 가리키고, 판매
상품(`products`)은 그 설명 행의 `product_code`(NULL 허용)로만 이어진다. 그래서 「이 PC 의
부품을 하나씩 팔 수 있나」를 보려면 표 넷을 매번 엮어야 했다.

이 마이그레이션은 **보기(view) 하나만** 만든다. 기존 표의 값은 읽기만 하고 바꾸지 않는다.

  v_assembly_parts   부품 설명 한 줄 = 한 행
                     판매 상품 연결 · 판매 상태 · 판매가 · 재고 · 사양 행 유무 ·
                     이 부품을 쓰는 구성표 수(보관 제외 / 전체)

판매 가능 판정(호환 사양이 다 있는가 등)은 규칙을 읽어야 하므로 여기 적지 않는다 —
`api/part_catalog.py` 한 곳이 정의한다.
"""
from alembic import op

revision = '0140'
down_revision = '0139'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE VIEW v_assembly_parts AS
      SELECT e.source_product_code,
             e.product_code,
             e.content->>'slot' AS slot,
             e.content->>'name' AS part_name,
             e.content->>'availability_scope' AS availability_scope,
             e.status AS explanation_status,
             p.part_type,
             p.status AS sale_status,
             p.sale_price,
             p.stock_qty,
             p.data_origin,
             (s.product_code IS NOT NULL) AS has_specs,
             COALESCE(u.configuration_count, 0) AS configuration_count,
             COALESCE(u.active_configuration_count, 0) AS active_configuration_count
      FROM product_explanations e
      LEFT JOIN products p ON p.product_code = e.product_code
      LEFT JOIN product_specs s ON s.product_code = e.product_code
      LEFT JOIN (
        SELECT pp.explanation_code,
               count(DISTINCT pp.configuration_id) AS configuration_count,
               count(DISTINCT pp.configuration_id) FILTER (WHERE c.status <> 'retired') AS active_configuration_count
        FROM pc_configuration_parts pp
        JOIN pc_configurations c USING (configuration_id)
        WHERE NOT pp.pseudo
        GROUP BY pp.explanation_code
      ) u ON u.explanation_code = e.source_product_code""")


def downgrade():
    op.execute('DROP VIEW IF EXISTS v_assembly_parts')
