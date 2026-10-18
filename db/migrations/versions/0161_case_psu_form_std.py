"""케이스 지원 파워 규격을 사양 표준(std)에서 바로 읽는다 — 0160 의 public 사본을 걷는다.

0160 이 `product_specs.psu_form_factor_list` 를 만들어 `std.part_specs` 값을 복사했는데, 조립 보증 표준 항목은
`std` 에만 둔다는 원칙(0036 · 회귀 [43] 「신설 표준 항목이 public 에 새지 않았다」)을 어겼다. 그래서
  (1) 추천 뷰에서 그 컬럼을 걷고(뷰는 컬럼을 뺄 수 없어 DROP 후 CREATE — 0036 과 같은 방식),
  (2) 컬럼과 메타 행을 지운다 — 값은 `std.part_specs` 사본이라 사라지는 것이 없다,
  (3) 관계 지도 `std.compat_pairs` B5(파워 ↔ 케이스)에 규칙 `case_psu_form` 을 맨다(회귀 [43] 「엔진 규칙이 전부 지도에 있다」).
엔진은 `api/std_specs.attach` 로 std 값을 부품 행에 붙인다.
"""
import re

from alembic import op

revision = '0161'
down_revision = '0160'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    ddl = conn.exec_driver_sql(
        "SELECT pg_get_viewdef('v_recommendation_candidates'::regclass, true)").scalar()
    if ddl and re.search(r'\bps\.psu_form_factor_list\b', ddl):
        cleaned = re.sub(r',\s*\n?\s*ps\.psu_form_factor_list\b', '', ddl)
        if re.search(r'\bps\.psu_form_factor_list\b', cleaned):
            raise RuntimeError('[0161] view still has ps.psu_form_factor_list')
        conn.exec_driver_sql('DROP VIEW v_recommendation_candidates')
        conn.exec_driver_sql('CREATE VIEW v_recommendation_candidates AS ' + cleaned)
    op.execute('ALTER TABLE product_specs DROP COLUMN IF EXISTS psu_form_factor_list')
    op.execute("DELETE FROM spec_field_defs WHERE field_key = 'psu_form_factor_list'")
    has_pairs = conn.exec_driver_sql("SELECT to_regclass('std.compat_pairs') IS NOT NULL").scalar()
    if has_pairs:
        op.execute("UPDATE std.compat_pairs SET rule_key = 'case_psu_form'"
                   " WHERE pair_key = 'B5' AND rule_key IS NULL")


def downgrade():
    op.execute("UPDATE std.compat_pairs SET rule_key = NULL WHERE pair_key = 'B5' AND rule_key = 'case_psu_form'")
