"""카탈로그 적재(T0) 준비 — 데모/실데이터 구분 · 다중 소켓 · 사양 출처 · GPU 권장파워 참조표.

ERD Ver 4.0 7th review §3.12 (2026-07-26), slice 39.

실파일 실측(24,303행 · 사양 EAV 339,650행)에서 나온 4가지 요구:

① **데모/실데이터 구분**(사용자 지시): 직원 베타에서 실운영 데이터가 쌓이기 시작하면
   시드 데모와 섞여 분리할 수 없다. 앞으로도 데모를 올려 테스트하므로 `data_origin`을
   원장 3곳(products·members·orders)에 둔다. 기존 시드는 전부 'demo'로 이행한다.

② **쿨러는 소켓을 여러 개 지원한다**(실측: 6개 지원 180건·5개 73건·7개 43건).
   `socket VARCHAR` 단일값으로 표현 불가 → `socket_list JSONB`(배열) 추가 +
   `compat_rules.op`에 'contains' 어휘 추가(컬럼 변경 없음 — 값 어휘만 확장).

③ **필드별 출처**: GPU 권장파워는 원천에 9건뿐이라 칩셋 표준표로 채운다(사용자 결정).
   행 단위 `extract_source`로는 "이 필드만 참조값"을 말할 수 없다 → `spec_sources JSONB`
   (필드 → eav|feature|name|reference)로 **근거가 창작이 아니라 사실이 되게** 한다.

④ **GPU 칩셋별 권장 파워 참조표**: 상품명에서 칩셋 모델을 91% 추출할 수 있으므로
   모델 → 권장W 표를 둔다. **값은 확인 대기 상태로 넣고 운영자가 고친다**(출처를 숨기지
   않는다 — 참조값임이 화면에 드러난다).

적재 원장(csv_import_jobs·csv_import_errors·product_imports)은 이미 있어 그대로 쓰고
`data_origin`만 더한다.

Revision ID: 0009
Revises: 0008
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        -- ① 데모/실데이터 구분 — 새 행은 'real'이 기본, 기존 시드는 'demo'로 이행
        ALTER TABLE products ADD COLUMN data_origin VARCHAR(10) NOT NULL DEFAULT 'real';
        ALTER TABLE members  ADD COLUMN data_origin VARCHAR(10) NOT NULL DEFAULT 'real';
        ALTER TABLE orders   ADD COLUMN data_origin VARCHAR(10) NOT NULL DEFAULT 'real';
        ALTER TABLE csv_import_jobs ADD COLUMN data_origin VARCHAR(10) NOT NULL DEFAULT 'real';
        UPDATE products SET data_origin = 'demo';
        UPDATE members  SET data_origin = 'demo';
        UPDATE orders   SET data_origin = 'demo';
        CREATE INDEX idx_products_origin ON products (data_origin);

        -- 적재 결과를 화면이 정직하게 말하려면 '검수 회부' 수가 ok/error와 별도로 필요하다
        ALTER TABLE csv_import_jobs ADD COLUMN row_review INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE csv_import_jobs ADD COLUMN source VARCHAR(40);

        -- ② 다중 소켓(쿨러) + ③ 필드별 출처
        ALTER TABLE product_specs ADD COLUMN socket_list  JSONB;
        ALTER TABLE product_specs ADD COLUMN spec_sources JSONB;

        -- ④ GPU 칩셋별 권장 파워 참조표 — 원천에 없는 값을 '참조값'으로 명시해 채운다
        CREATE TABLE gpu_power_reference (
          chipset_key   VARCHAR(40) PRIMARY KEY,   -- 예: 'RTX 5070 TI' (정규화 키)
          recommended_watt INTEGER NOT NULL,
          confirmed_yn  BOOLEAN NOT NULL DEFAULT false,  -- 운영자 확인 여부(기본 미확인)
          source_note   VARCHAR(200) NOT NULL,
          updated_by    BIGINT REFERENCES admin_operators(operator_id),
          updated_at    TIMESTAMP NOT NULL DEFAULT now()
        );
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS gpu_power_reference;
        ALTER TABLE product_specs DROP COLUMN IF EXISTS spec_sources;
        ALTER TABLE product_specs DROP COLUMN IF EXISTS socket_list;
        ALTER TABLE csv_import_jobs DROP COLUMN IF EXISTS source;
        ALTER TABLE csv_import_jobs DROP COLUMN IF EXISTS row_review;
        DROP INDEX IF EXISTS idx_products_origin;
        ALTER TABLE csv_import_jobs DROP COLUMN IF EXISTS data_origin;
        ALTER TABLE orders   DROP COLUMN IF EXISTS data_origin;
        ALTER TABLE members  DROP COLUMN IF EXISTS data_origin;
        ALTER TABLE products DROP COLUMN IF EXISTS data_origin;
    """)
