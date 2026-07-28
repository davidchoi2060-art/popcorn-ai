"""수랭 라디에이터 장착 검증 — 사양 2종 + 규칙 1종 (슬라이스 82-B).

0021로 수랭이 견적에 들어올 수 있게 됐는데, **케이스에 들어가는지는 아무도 안 본다.**
공랭은 높이로 보지만 수랭은 라디에이터가 케이스 어디에 붙느냐의 문제라 다른 값이 필요하다.

원문에 둘 다 있다(2026-07-29 실측, 판매중·재고 기준):

    수랭  '수랭팬개수 : 3(EA)'        197/239  (82%)
    케이스 '수랭쿨러 지원 : 최대 3열'   607/895  (68%)

같은 단위다 — 열 = 라디에이터에 붙는 팬 줄 수. 그래서 규칙 하나로 선다.

**한쪽만 채우면 안 된다**: 규칙은 양변을 요구한다(NULL 불통과). 수랭만 채우고 케이스를
비워 두면 수랭이 또 전멸한다 — 0021이 고친 것과 똑같은 상태가 다른 이유로 반복된다.
그래서 두 필드를 함께 넣고, 값이 찬 뒤에 규칙을 켠다.

**필수 사양으로 지정하지 않는다.** 필수로 걸면 값이 없는 케이스 288개가 그 즉시
검수 대기로 떨어져 추천에서 빠진다. 규칙은 값을 아는 조합만 통과시키면 되고,
모르는 조합은 통과시키지 않는 것으로 충분하다(NULL 불통과가 이미 그렇게 한다).

Revision ID: 0022
Revises: 0021
"""
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE product_specs ADD COLUMN IF NOT EXISTS radiator_rows INTEGER")
    op.execute("ALTER TABLE product_specs ADD COLUMN IF NOT EXISTS radiator_max_rows INTEGER")

    op.execute("""
        INSERT INTO spec_field_defs
          (field_key, label, data_type, unit, part_types, required_for,
           is_engine, is_custom, in_ingest, sort_order, note)
        VALUES
          ('radiator_rows', '라디에이터 열', 'INTEGER', '열',
           '["COOLER_CPU_AIO"]'::jsonb, '[]'::jsonb, true, false, true, 170,
           '수랭 라디에이터에 붙는 팬 줄 수 — 원문 ''수랭팬개수''와 상품명 규격 중 큰 값'),
          ('radiator_max_rows', '수랭 최대 열', 'INTEGER', '열',
           '["CASE"]'::jsonb, '[]'::jsonb, true, false, true, 171,
           '케이스가 받는 라디에이터 최대 열 — 원문 ''수랭쿨러 지원 : 최대 N열''')
        ON CONFLICT (field_key) DO NOTHING
    """)

    # 엔진이 읽는 값이므로 추천 뷰에 실어야 한다. 뷰는 **끝에 컬럼 추가만** 된다
    # (CREATE OR REPLACE VIEW는 순서 변경·삭제를 거부한다 — 슬라이스 56 전례).
    for col in ("radiator_rows", "radiator_max_rows"):
        op.execute(f"""
            DO $$
            DECLARE ddl text; pos int;
            BEGIN
              IF EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='v_recommendation_candidates'
                            AND column_name='{col}') THEN RETURN; END IF;
              ddl := pg_get_viewdef('v_recommendation_candidates', true);
              pos := position('FROM products p' in ddl);
              EXECUTE 'CREATE OR REPLACE VIEW v_recommendation_candidates AS '
                   || substr(ddl, 1, pos - 1) || ', ps.{col} ' || substr(ddl, pos);
            END $$;
        """)

    # 규칙은 **값을 채운 뒤** 켠다 — 백필(tools/respec.py)이 끝나기 전에 active면
    # 수랭이 통째로 탈락한다. 여기서는 비활성으로 넣고 0023이 켠다.
    op.execute("""
        INSERT INTO compat_rules
          (rule_key, slot, field, op, ref_slot, ref_field, label, detail_fmt,
           sort_order, part_types, active)
        VALUES
          ('radiator', 'COOLER', 'radiator_rows', 'lte', 'CASE', 'radiator_max_rows',
           '라디에이터 장착', '{v}열 ≤ 케이스 {r}열', 65, '["COOLER_CPU_AIO"]'::jsonb, false)
        ON CONFLICT (rule_key) DO NOTHING
    """)


def downgrade() -> None:
    # 컬럼은 남긴다(값이 함께 사라진다 — 슬라이스 56 규약). 규칙·메타만 되돌린다.
    op.execute("DELETE FROM compat_rules WHERE rule_key = 'radiator'")
    op.execute("DELETE FROM spec_field_defs"
               " WHERE field_key IN ('radiator_rows', 'radiator_max_rows')")
