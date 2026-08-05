"""CPU쿨러 공랭·수랭 카테고리를 하나로 합친다 (사용자 결정 2026-08-05).

0027이 `part_type` 17종을 그대로 1단 카테고리로 깔면서 'CPU쿨러(공랭)'·'CPU쿨러(수랭)'
두 노드가 생겼다. 운영자가 판매 분류를 훑을 때 쿨러만 두 줄로 갈라져 있을 이유가 없다.

**엔진의 `part_type`은 건드리지 않는다.** `radiator_rows`(라디에이터 열)는
`COOLER_CPU_AIO`에만 적용되고(0022), 라디에이터 장착 규칙이 그 값으로 케이스 수납을
판정한다. part_type을 합치면 수랭 628건 중 **589건이 들고 있는 판정 근거가 대상을 잃고**,
수랭이 안 들어가는 케이스에 수랭이 붙는다. 여기서 합치는 것은 **판매 탐색 축뿐**이고,
남는 노드의 `allowed_part_types`가 공랭·수랭을 **둘 다** 받는다.

노드를 이름이 아니라 **`allowed_part_types`로 찾는다** — 운영자가 이름을 바꿨을 수 있고,
category_id는 새 DB에서 다르다. 이 표를 참조하는 FK는 `categories.parent_id`와
`products.category_id` 둘뿐이고(확인 2026-08-05), 이동 로그는 JSON에 숫자만 남기므로
노드를 지워도 원장은 깨지지 않는다. 지워지는 노드에 자식이 있으면 **옮기지 않고 멈춘다**
(판매 트리를 말없이 재배치하지 않는다).

되돌리기(downgrade)는 노드를 되살리되 **상품은 되돌리지 않는다** — 어느 상품이 원래
수랭 노드에 있었는지는 part_type으로 정확히 알 수 있으므로 그 기준으로 되돌린다.
"""
from alembic import op
import sqlalchemy as sa

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None

AIR = '["COOLER_CPU_AIR"]'
AIO = '["COOLER_CPU_AIO"]'
BOTH = '["COOLER_CPU_AIR", "COOLER_CPU_AIO"]'


def _find(conn, allowed):
    return conn.execute(sa.text(
        "SELECT category_id FROM categories"
        " WHERE allowed_part_types = CAST(:a AS JSONB)"), {"a": allowed}).scalar()


def upgrade():
    conn = op.get_bind()
    keep = _find(conn, AIR)          # 공랭 노드를 남긴다
    drop = _find(conn, AIO)
    if keep is None or drop is None:
        return                        # 이미 합쳐졌거나 그런 노드가 없는 DB — 조용히 지나간다

    kids = conn.execute(sa.text(
        "SELECT count(*) FROM categories WHERE parent_id = :d"), {"d": drop}).scalar()
    if kids:
        raise RuntimeError(
            "수랭 카테고리(id=%s)에 하위 카테고리 %d개가 있습니다 — "
            "판매 트리를 말없이 옮기지 않습니다. 먼저 화면에서 정리하세요." % (drop, kids))

    conn.execute(sa.text(
        "UPDATE categories SET name = 'CPU쿨러',"
        "       allowed_part_types = CAST(:b AS JSONB), updated_at = now()"
        " WHERE category_id = :k"), {"b": BOTH, "k": keep})
    conn.execute(sa.text(
        "UPDATE products SET category_id = :k WHERE category_id = :d"),
        {"k": keep, "d": drop})
    conn.execute(sa.text("DELETE FROM categories WHERE category_id = :d"), {"d": drop})


def downgrade():
    conn = op.get_bind()
    keep = _find(conn, BOTH)
    if keep is None:
        return
    row = conn.execute(sa.text(
        "SELECT parent_id, sort_order FROM categories WHERE category_id = :k"),
        {"k": keep}).mappings().first()

    conn.execute(sa.text(
        "UPDATE categories SET name = 'CPU쿨러(공랭)',"
        "       allowed_part_types = CAST(:a AS JSONB), updated_at = now()"
        " WHERE category_id = :k"), {"a": AIR, "k": keep})
    drop = conn.execute(sa.text(
        "INSERT INTO categories (parent_id, name, sort_order, allowed_part_types)"
        " VALUES (:p, 'CPU쿨러(수랭)', :s, CAST(:a AS JSONB))"
        " RETURNING category_id"),
        {"p": row["parent_id"], "s": row["sort_order"], "a": AIO}).scalar()
    # 수랭이던 상품만 되돌린다 — part_type이 그 사실을 정확히 알고 있다.
    conn.execute(sa.text(
        "UPDATE products SET category_id = :d"
        " WHERE category_id = :k AND part_type = 'COOLER_CPU_AIO'"),
        {"d": drop, "k": keep})
