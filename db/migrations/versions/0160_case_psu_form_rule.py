"""케이스-파워 규격 호환 규칙 (2026-10-18 중헌 님 승인 — 「케이스와 파워 규격을 맞추는 규칙을 모든 견적에」).

배경
  부품 직접 고르기가 일반 케이스(투민시스템 TM40)에 슬림형 TFX500W 파워를 넣었다(2026-10-17 개발 서버).
  호환 규칙에 케이스가 받는 파워 규격을 보는 항목이 없었다. 케이스의 «지원 파워» 값은 사양 표준
  (`std.part_specs`, field_key='psu_form_factor_list', `tools/std_parse.p_psu_ff`)에만 있고 엔진이 읽는
  `product_specs` 에는 없었다(0036 이 빈 컬럼을 되돌렸다).

이 마이그레이션이 하는 일
  (1) `product_specs.psu_form_factor_list`(JSONB) — 케이스가 받는 파워 규격 목록. 사양 표준 값으로 채운다.
  (2) 추천 뷰에 그 컬럼을 끝에 붙인다(안 실으면 규칙이 값을 못 본다 — 0094 와 같은 방식).
  (3) 규칙 `case_psu_form`: POWER.form_factor 가 CASE.psu_form_factor_list 안에 있는가(op 'in').
      `null_ref_mode='skip_any'` — 어느 쪽 값이든 모르면 판정 불가로 넘긴다. 케이스 목록이나 파워 규격이
      비어 있는 부품을 «호환 안 됨»으로 떨어뜨리면 그 부품이 견적에서 통째로 사라진다(§조용한 죽음).
      규격 표기는 엔진이 맞춰 비교한다(`recommend.psu_form_key` — ATX · SFX · SFX-L · TFX · FLEX).
"""
from alembic import op

revision = '0160'
down_revision = '0159'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    op.execute('ALTER TABLE product_specs ADD COLUMN IF NOT EXISTS psu_form_factor_list JSONB')
    op.execute("""
        INSERT INTO spec_field_defs
          (field_key, label, data_type, unit, part_types, required_for,
           is_engine, is_custom, in_ingest, sort_order, note)
        VALUES ('psu_form_factor_list', '수용 파워 규격', 'JSONB', NULL,
                '["CASE"]'::jsonb, '[]'::jsonb,
                true, false, false,
                (SELECT COALESCE(MAX(sort_order), 0) + 10 FROM spec_field_defs),
                '케이스가 받는 파워 규격 목록(ATX · SFX · TFX 등). 호환 규칙 case_psu_form 이 읽는다. '
                '필수로 잡지 않는다 - 값이 없으면 판정 불가로 넘긴다.')
        ON CONFLICT (field_key) DO NOTHING
    """)
    has_std = conn.exec_driver_sql("SELECT to_regclass('std.part_specs') IS NOT NULL").scalar()
    if has_std:
        n = conn.exec_driver_sql("""
            UPDATE product_specs ps SET psu_form_factor_list = s.value_json
              FROM std.part_specs s, products p
             WHERE s.product_code = ps.product_code AND p.product_code = ps.product_code
               AND p.part_type = 'CASE' AND s.field_key = 'psu_form_factor_list'
               AND jsonb_typeof(s.value_json) = 'array' AND jsonb_array_length(s.value_json) > 0
               AND ps.psu_form_factor_list IS NULL""").rowcount
        print('[0160] psu_form_factor_list backfill: %d CASE rows' % n)
    op.execute("""
        DO $$
        DECLARE ddl text; pos int;
        BEGIN
          IF EXISTS (SELECT 1 FROM information_schema.columns
                      WHERE table_name='v_recommendation_candidates'
                        AND column_name='psu_form_factor_list') THEN RETURN; END IF;
          ddl := pg_get_viewdef('v_recommendation_candidates', true);
          pos := position('FROM products p' in ddl);
          EXECUTE 'CREATE OR REPLACE VIEW v_recommendation_candidates AS '
               || substr(ddl, 1, pos - 1) || ', ps.psu_form_factor_list ' || substr(ddl, pos);
        END $$;
    """)
    op.execute("""
        INSERT INTO compat_rules (rule_key, slot, field, op, ref_slot, ref_field, label, detail_fmt,
                                  sort_order, null_ref_mode)
        VALUES ('case_psu_form', 'POWER', 'form_factor', 'in', 'CASE', 'psu_form_factor_list',
                '파워 규격 수용', '{v} 파워 · 케이스 지원 {r}', 75, 'skip_any')
        ON CONFLICT (rule_key) DO NOTHING
    """)


def downgrade():
    # 컬럼은 남긴다 — 지우면 값이 함께 사라진다(0022·0094 규약).
    op.execute("DELETE FROM compat_rules WHERE rule_key = 'case_psu_form'")
