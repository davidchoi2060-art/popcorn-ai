"""케이스 지원 보드 규격 목록 — form_factor_list + 호환 규칙 8번째 (슬라이스 43).

사용자 결정(2026-07-26, 선택 ②): CASE의 보드 규격을 **필수 사양으로 유지하고 호환 규칙을
추가한다**. 규칙이 쓰지 않는 필드를 게이트로 요구하던 상태를 해소하는 방향이다.

**단일값으로는 표현할 수 없다**: 케이스는 보드 규격을 여러 개 지원한다(실측 2,326건 중
3개 지원 1,110 · 4개 566 · 2개 228 · 1개 228). 쿨러 소켓(0009)과 같은 문제이므로 같은
해법을 쓴다 — `form_factor_list JSONB` + `op='contains'`.

새 규칙: `CASE.form_factor_list contains MB.form_factor`
  = "이 케이스가 이 보드의 규격을 수용하는가". NULL·빈 목록은 불통과(기존 원칙 유지).

원천에서 92%가 회수된다(목록이 스펙 문자열에 'ATX / mATX / MiniITX'로 적혀 있다).
못 뽑는 194건은 검수 대상으로 남는다 — 값을 지어내지 않는다.

Revision ID: 0012
Revises: 0011
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

COLS = """p.product_code, p.sku, p.product_name, p.maker, p.brand, p.model_name,
    p.part_type, p.category_group, p.status, p.ai_candidate_yn, p.review_required_yn,
    p.purchase_price, p.sale_price, p.market_price, p.locked_fields, p.supplier,
    p.warranty_months, p.spec_source_text, p.danawa_code, p.stock_qty,
    p.created_at, p.updated_at,
    ps.socket, ps.chipset, ps.mem_type, ps.capacity_gb, ps.clock_mhz, ps.tdp_watt,
    ps.rated_watt, ps.required_power_watt, ps.length_mm, ps.gpu_max_mm,
    ps.cooler_height_mm, ps.cooler_tdp, ps.pcie_gen, ps.form_factor, ps.interface,
    ps.tag_white, ps.tag_rgb, ps.tag_silent, ps.extract_source, ps.confidence,
    ps.verified_yn, ps.updated_at AS spec_updated_at,
    ps.socket_list, ps.spec_sources, p.data_origin"""

WHERE = """WHERE p.status = '판매중' AND p.ai_candidate_yn = true
      AND p.review_required_yn = false AND p.category_group = 'core_part'
      AND p.part_type = ANY (ARRAY['CPU','GPU','MB','RAM','SSD','HDD','POWER','CASE',
                                   'COOLER_CPU_AIR','COOLER_CPU_AIO']::varchar[])"""


def upgrade() -> None:
    op.execute(f"""
        ALTER TABLE product_specs ADD COLUMN form_factor_list JSONB;

        CREATE OR REPLACE VIEW v_recommendation_candidates AS
        SELECT {COLS}, ps.form_factor_list
        FROM products p JOIN product_specs ps USING (product_code)
        {WHERE};
    """)


def downgrade() -> None:
    op.execute(f"""
        UPDATE compat_rules SET active = false WHERE rule_key = 'case_board';
        DROP VIEW IF EXISTS v_recommendation_candidates;
        CREATE VIEW v_recommendation_candidates AS
        SELECT {COLS}
        FROM products p JOIN product_specs ps USING (product_code)
        {WHERE};
        ALTER TABLE product_specs DROP COLUMN IF EXISTS form_factor_list;
    """)
