# -*- coding: utf-8 -*-
"""0100: 추천 후보 뷰에 `cpu_gpu`(CPU 내장그래픽 유무) 컬럼 싣기

■ 왜 필요한가 - 사무용 견적이 외장 GPU 를 강제하던 실사고

  견적 엔진의 iGPU 판정(`api/catalog_map.cpu_has_igpu`)은 지금까지 **상품명
  문자열**만 봤다. 그 규칙에 「AMD 는 모델명에 G 가 붙어야 내장그래픽」이라는
  Zen3 기준이 박혀 있어서, 라이젠 7000(Zen4)/9000(Zen5) 35 종을 전부
  「내장그래픽 없음」으로 오판했다. 그 결과 GPU 성능 하한이 없는 사무용
  견적에도 최저 297,700 원짜리 외장 그래픽카드가 **강제로** 들어갔다.

  `product_specs.cpu_gpu` 백필이 끝나(TRUE 358 · FALSE 274 · NULL 51)
  이제 믿을 수 있는 원천이 생겼다. 그런데 후보 뷰가 `ps.*` 가 아니라 컬럼을
  일일이 나열하는 구조라, 여기 싣지 않으면 `_load_pool` 이 이 값을 읽을 수
  없다(0094 gpu_power_draw_watt 와 정확히 같은 자리, 같은 이유).

■ 왜 「끝에 한 줄만」 끼우는가 (★건드리면 깨진다)

  `CREATE OR REPLACE VIEW` 는 **기존 컬럼의 순서 변경·삭제를 거부**한다
  ("cannot drop columns from view"). 그래서 기존 정의를 한 글자도 바꾸지 않고
  마지막 컬럼 뒤에 `, ps.cpu_gpu` 만 끼워 넣는다 - 0022 · 0094 전례 그대로
  `pg_get_viewdef` 로 현재 정의를 읽어 `FROM products p` 직전에 삽입한다.
  현재 정의를 하드코딩해 다시 쓰지 않는 이유: 그 사이 다른 마이그레이션이
  뒤에 붙인 컬럼(vram_gb · cpu_cores · gpu_power_draw_watt 등)을 **조용히
  지워버리기** 때문이다.

■ 이미 있으면 아무것도 하지 않는다

  `admin_spec_fields._add_col_to_view` 가 운영 중 같은 컬럼을 먼저 붙였을 수
  있다. 컬럼 존재를 먼저 확인하고 RETURN 한다(재실행 안전).

■ downgrade

  뷰에서 컬럼을 「빼는」 것은 CREATE OR REPLACE 로 안 되고 DROP VIEW 가 필요한데,
  이 뷰에 의존하는 다른 객체가 함께 죽는다. 컬럼 하나가 더 실려 있는 것은
  아무 동작도 바꾸지 않으므로(엔진이 안 읽으면 그만) downgrade 는 no-op 으로
  둔다 - 0094 와 같은 판단.
"""
from alembic import op

revision = "0100"
down_revision = "0099"
branch_labels = None
depends_on = None


VIEW = "v_recommendation_candidates"


def upgrade():
    op.execute(f"""
        DO $$
        DECLARE ddl text; pos int;
        BEGIN
          IF EXISTS (SELECT 1 FROM information_schema.columns
                      WHERE table_name='{VIEW}'
                        AND column_name='cpu_gpu') THEN RETURN; END IF;
          ddl := pg_get_viewdef('{VIEW}', true);
          pos := position('FROM products p' in ddl);
          EXECUTE 'CREATE OR REPLACE VIEW {VIEW} AS '
               || substr(ddl, 1, pos - 1) || ', ps.cpu_gpu ' || substr(ddl, pos);
        END $$;
    """)


def downgrade():
    # 뷰 컬럼 제거는 DROP VIEW 가 필요해 의존 객체를 함께 죽인다 - no-op (0094 전례).
    pass
