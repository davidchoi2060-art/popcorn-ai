"""판매 카테고리 트리 — 부품 종류와 분리된 두 번째 축 (슬라이스 B).

■ 왜 만드나
우리에겐 **판매용 카테고리가 아예 없었다.** 있는 것은 `products.part_type`(17종, 엔진이
읽는 닫힌 집합)과 `category_group`(core_part/etc/peripheral 3종짜리 거친 묶음)뿐이다.

■ 기존 임대 관리자에서 배운 것 (`docs/research/legacy-admin-2026-08-04.md`)
그쪽 대분류 20개는 **다섯 축을 같은 층에 섞고 있었다** — 상품분류 · 완제품유형 ·
마케팅노출(`베스트7주력부품` · `네이버노출`) · 내부업무(`내부관리용` · `고객님 개인결제`) ·
폐기(`삭제대기`). `내부관리용` 아래에는 `상품평 0개/20개이하/21~50개/51개이상`이 있었다 —
**리뷰 개수가 카테고리라서, 리뷰가 21개가 되면 상품이 분류를 옮겨야 한다.**

결과는 숫자로 나왔다: **미매핑 1,458건(그중 판매중 325건).** 4단 고정이 너무 깊어
바닥을 못 채웠고, 그 상품들은 고객이 카테고리로 훑으면 나오지 않는다.

그래서 여기서는 축을 가른다:

    part_type    부품 종류. 닫힌 집합. **엔진이 읽는다.** 운영자가 못 늘린다(taxonomy.py).
    categories   판매 탐색. 트리. **운영자가 자유롭게 만든다. 엔진은 읽지 않는다.**

**가장 중요한 계약: 카테고리를 옮겨도 견적 결과가 변하면 안 된다**(A-02 재현성).
회귀가 "엔진 모듈이 categories를 참조하지 않는다"를 소스 스캔으로 지킨다.

■ 고정 깊이를 두지 않는다
`parent_id` 자기참조만 둔다. `depth` 컬럼은 **일부러 만들지 않았다** — 저장하는 순간
"4단까지"가 생기고, 그게 저쪽에서 1,458건을 만든 원인이다. 깊이는 필요할 때 파생한다.

■ 루트 이름 중복은 UNIQUE(parent_id, name)로 못 막는다
PostgreSQL에서 NULL은 서로 같지 않다. `parent_id IS NULL`인 행 둘이 같은 이름이어도
복합 유니크는 통과한다. 그래서 **부분 인덱스 둘**로 나눠 건다.

■ allowed_part_types — 저쪽에 없던 안전장치
카테고리에 "여기 올 수 있는 part_type"을 걸어 둘 수 있다(NULL이면 제한 없음).
저쪽은 이게 없어서 `컴퓨터주변기기` 밑에 `위메이드`(회사명)와 `전체리스트`(카테고리 아님)가
들어갔다. 매핑 위반을 **막지는 않되 화면이 근거와 함께 경고**한다.

■ 초기 트리 = part_type 17종 (사용자 확정 2026-08-04)
빈 트리로 시작하면 22,838건이 전부 미매핑이 된다 — 저쪽이 방치한 그 상태로 출발하는 셈이다.
그래서 part_type을 1단으로 깔고 같은 뜻의 매핑을 함께 채운다. **트리를 part_type에서
만드는 것과 그 매핑은 같은 행위라 나눌 수 없다.** 그 다음(슬라이스 C)이 진짜 일이다 —
`미분류` 5,148건을 사람이 갈라내는 것.

멱등하다: 이름이 이미 있으면 넣지 않고, `category_id`가 NULL인 상품만 채운다.
운영 서버는 빈 DB에서 시작하므로(I-01) 상품 백필은 거기서 0건이다.

■ 되돌리기
downgrade는 컬럼과 표를 지운다. 운영자가 만든 카테고리도 함께 사라지므로
**상품 매핑이 사라진다는 뜻**이다 — 되돌릴 일이 있으면 먼저 트리를 내보내 둔다.
"""
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

# part_type → (1단 카테고리 이름, 정렬 순서).
# 이름은 taxonomy.PART_LABELS와 같게 둔다 — 두 벌이 되면 어긋난다(슬라이스 A의 교훈).
# 순서는 견적 슬롯 순 → HDD → 주변기기 → 미분류. 운영자가 화면에서 바꿀 수 있다.
SEED = [
    ("CPU", "CPU", 10),
    ("MB", "메인보드", 20),
    ("RAM", "메모리", 30),
    ("GPU", "그래픽카드", 40),
    ("CASE", "케이스", 50),
    ("COOLER_CPU_AIR", "CPU쿨러(공랭)", 60),
    ("COOLER_CPU_AIO", "CPU쿨러(수랭)", 70),
    ("POWER", "파워", 80),
    ("SSD", "SSD", 90),
    ("HDD", "HDD", 100),
    ("MONITOR", "모니터", 110),
    ("KEYBOARD", "키보드", 120),
    ("MOUSE", "마우스", 130),
    ("HEADSET", "헤드셋", 140),
    ("SPEAKER", "스피커", 150),
    ("WEBCAM", "웹캠", 160),
    ("ETC", "미분류", 900),   # 갈라내야 할 덩어리 — 맨 뒤에 둔다
]


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            category_id        SERIAL PRIMARY KEY,
            parent_id          INTEGER REFERENCES categories(category_id),
            name               VARCHAR(80)  NOT NULL,
            sort_order         INTEGER      NOT NULL DEFAULT 0,
            is_visible         BOOLEAN      NOT NULL DEFAULT TRUE,
            allowed_part_types JSONB,
            created_at         TIMESTAMP    NOT NULL DEFAULT now(),
            updated_at         TIMESTAMP    NOT NULL DEFAULT now()
        )
    """)
    # 자기 자신을 부모로 두는 것만은 DB가 막는다(1단계 순환).
    # 더 긴 순환(A→B→A)은 CHECK로 표현할 수 없어 API와 회귀가 막는다.
    op.execute("ALTER TABLE categories DROP CONSTRAINT IF EXISTS ck_categories_not_self")
    op.execute("ALTER TABLE categories ADD CONSTRAINT ck_categories_not_self"
               " CHECK (parent_id IS NULL OR parent_id <> category_id)")

    # 같은 부모 밑 같은 이름 금지. NULL은 서로 같지 않으므로 루트는 따로 막는다.
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_categories_sibling"
               " ON categories(parent_id, name) WHERE parent_id IS NOT NULL")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_categories_root"
               " ON categories(name) WHERE parent_id IS NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_categories_parent ON categories(parent_id)")

    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS category_id INTEGER"
               " REFERENCES categories(category_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_category ON products(category_id)")

    # 초기 트리 — 이름이 이미 있으면 건너뛴다(멱등).
    for pt, name, order in SEED:
        op.execute(f"""
            INSERT INTO categories (parent_id, name, sort_order, allowed_part_types)
            SELECT NULL, '{name}', {order}, '["{pt}"]'::jsonb
            WHERE NOT EXISTS (SELECT 1 FROM categories
                              WHERE parent_id IS NULL AND name = '{name}')
        """)

    # 같은 뜻의 매핑을 함께 채운다 — 아직 매핑이 없는 상품만.
    for pt, name, _ in SEED:
        op.execute(f"""
            UPDATE products p SET category_id = c.category_id
            FROM categories c
            WHERE c.parent_id IS NULL AND c.name = '{name}'
              AND p.part_type = '{pt}' AND p.category_id IS NULL
        """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_products_category")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS category_id")
    op.execute("DROP TABLE IF EXISTS categories")
