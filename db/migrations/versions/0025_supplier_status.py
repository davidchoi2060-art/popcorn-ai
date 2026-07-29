"""공급처에 상태를 준다 — 만들 수만 있고 접을 수 없으면 오타가 영원히 남는다.

배경(슬라이스 93): **빈 DB에서 공급처를 만들 수단이 아예 없었다.**
`INSERT INTO suppliers`는 `db/seed/seed.sql`에만 있었는데 그 시드는 개발용 더미 전용이라
실제 개업에 쓸 수 없다. API는 목록 조회(`GET /suppliers`)와 상품-공급처 매입가 연결
(`POST /products/{code}/suppliers`)뿐이고, 화면도 좌측 메뉴도 없었다.

그 결과 정직하게 빈 DB로 시작하면 이렇게 막힌다:

    공급처 0 → 매입가 넣을 대상 없음 → 판매가 산정 불가
              → 4중 게이트 통과 불가 → 추천 후보 0 → 견적 0건

`docs/07_운영-시작-순서.md`의 3단계가 유일하게 **화면 이름을 적지 않은 단계**였다.
쓸 때 이미 없었던 것이다.

■ 왜 status인가 — 삭제하지 않기 위해서다
suppliers를 참조하는 테이블이 **6개**다(supplier_presets · supplier_price_files ·
supplier_product_map · product_supplier_prices · product_price_history ·
product_sourcing_quotes). 매입 이력이 걸린 공급처를 지우면 과거 단가·매입 기록이 깨진다.

그래서 원장 규약대로 **삭제가 아니라 상태 전이**로 접는다. 이름을 잘못 만들어도
'중지'로 내리면 선택지에서 사라지되 과거 기록은 그대로 남는다.

기본값은 '활성' — 이미 있는 행이 조용히 사라지면 안 된다.

Revision ID: 0025
Revises: 0024
"""
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS status VARCHAR(20)")
    # 기존 행은 전부 활성으로 — NULL로 두면 목록에서 빠지거나 상태 판정이 갈린다.
    op.execute("UPDATE suppliers SET status = '활성' WHERE status IS NULL")
    op.execute("ALTER TABLE suppliers ALTER COLUMN status SET DEFAULT '활성'")
    op.execute("ALTER TABLE suppliers ALTER COLUMN status SET NOT NULL")
    # 같은 이름이 둘이면 매입가를 어느 쪽에 넣었는지 알 수 없다.
    # 대소문자·앞뒤 공백을 무시하고 막는다(운영자가 "MSI "와 "msi"를 따로 만들지 못하게).
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_suppliers_name"
               " ON suppliers (lower(btrim(name)))")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_suppliers_name")
    # 컬럼은 남긴다 — 지우면 '중지'로 내려둔 판단이 함께 사라진다.
