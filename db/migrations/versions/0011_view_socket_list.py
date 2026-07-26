"""추천 후보 뷰에 socket_list · data_origin 노출 (슬라이스 39).

① 쿨러 다중 소켓 규칙(`COOLER.socket_list contains CPU.socket`)이 작동하려면 엔진이 읽는
   뷰가 그 컬럼을 내놓아야 한다.
② 데모/실데이터 구분(`data_origin`)을 뷰에 실어, 베타에서 **데모 부품이 실견적에 섞이는지**
   API가 판단할 수 있게 한다(필터는 호출부 선택 — 뷰는 사실만 노출한다).

컬럼은 **맨 끝에만** 추가한다(CREATE OR REPLACE VIEW는 기존 컬럼 순서·타입 변경 불가).

기록으로 남길 사실: 이 뷰의 WHERE가 곧 추천 게이트다 —
  판매중 ∧ ai_candidate ∧ ¬review_required ∧ **category_group='core_part'** ∧ part_type 10종
  (+ 호출부에서 stock_qty>0). 적재가 category_group을 채우지 않으면 아무리 사양이 완전해도
  추천 풀에 들어오지 않는다.

Revision ID: 0011
Revises: 0010
"""
from alembic import op

revision = "0011"
down_revision = "0010"
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
    ps.verified_yn, ps.updated_at AS spec_updated_at"""

WHERE = """WHERE p.status = '판매중' AND p.ai_candidate_yn = true
      AND p.review_required_yn = false AND p.category_group = 'core_part'
      AND p.part_type = ANY (ARRAY['CPU','GPU','MB','RAM','SSD','HDD','POWER','CASE',
                                   'COOLER_CPU_AIR','COOLER_CPU_AIO']::varchar[])"""


def upgrade() -> None:
    op.execute(f"""
        CREATE OR REPLACE VIEW v_recommendation_candidates AS
        SELECT {COLS},
            ps.socket_list, ps.spec_sources, p.data_origin
        FROM products p JOIN product_specs ps USING (product_code)
        {WHERE};
    """)


def downgrade() -> None:
    op.execute(f"""
        DROP VIEW IF EXISTS v_recommendation_candidates;
        CREATE VIEW v_recommendation_candidates AS
        SELECT {COLS}
        FROM products p JOIN product_specs ps USING (product_code)
        {WHERE};
    """)
