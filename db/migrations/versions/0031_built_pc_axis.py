"""완성품 축 — 완제품 PC / 베어본을 part_type 으로 옮긴다 (사용자 결정 2026-08-05).

422건(완제품 318 · 베어본 104)이 `part_type='ETC'` 에 섞여 있었다. ETC 는 "적재가 종류를
정하지 못한 것"이라는 뜻인데, 이것들은 **무엇인지 알면서** ETC 였다.

■ 왜 판매 분류(categories)만으로 부족한가 — 세 가지가 각각 다른 이유로 요구했다
  · **기록**: 사양을 걸 수 있는 축은 `part_type` 하나다(`spec_field_defs.part_types` ·
    `ASSIGNABLE_TYPES`). 2.2억짜리 H100 4WAY 워크스테이션에 지금 적을 수 있는 사실은
    이름·가격·수량뿐이고, 그 문은 판매 분류로도 새 컬럼으로도 열리지 않는다.
  · **재생산**: `part_type` 은 적재마다 다시 계산되는 파생값이고, 적재 UPSERT 는
    `category_id` 를 읽지도 쓰지도 않는다(실측). 판매 분류에만 살면 적재가 되돌린다.
  · **역사**: 주문·견적 스냅샷이 박는 것은 `part_type` 이다. `categories` 는 어느
    스냅샷에도 없어서 과거 주문에서 완제품이었다는 사실을 되살릴 수 없다.

■ 엔진은 0줄 건드린다
  두 후보 뷰가 `category_group`(core_part/peripheral)과 `part_type` 을 **둘 다
  화이트리스트**로 건다(실측). 새 값은 정의상 어느 쪽에도 들어갈 수 없다.
  `category_group` 은 `'etc'` 그대로 둔다 — 한 슬라이스에서 두 축을 동시에 옮기지 않는다.
  회귀가 "완제품·베어본은 어느 후보에도 없다"를 지킨다(이 마이그레이션 **전에** 걸어 뒀다).

■ 근거는 운영자가 이미 갈라 놓은 판매 분류다
  원천 CSV 가 리포에 없고 `product_imports` 도 0행이라 원천 분류 토큰을 잴 수 없다.
  추측으로 상품명을 훑지 않는다(슬라이스 51 오탐 전례). 운영자가 손으로 갈라 놓은
  '완제품 PC' · '미니PC·베어본' 노드가 지금 가진 가장 확실한 사실이다.

■ 필수 사양은 걸지 않는다(사용자 결정)
  축만 만든다. 지금 걸면 값이 비어 있어 422건이 그 자리에서 검수 대기가 된다.
  ETC 와 달리 이제는 언제든 걸 수 있다 — 그게 이 축을 만든 이유이기도 하다.
"""
from alembic import op
import sqlalchemy as sa

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None

MAP = [("완제품 PC", "PC_COMPLETE"), ("미니PC·베어본", "BAREBONE")]


def upgrade():
    conn = op.get_bind()
    for cat, pt in MAP:
        n = conn.execute(sa.text(
            "UPDATE products SET part_type = :pt, updated_at = now()"
            " WHERE part_type = 'ETC'"
            "   AND category_id = (SELECT category_id FROM categories WHERE name = :c)"),
            {"pt": pt, "c": cat}).rowcount
        # product_specs 의 분류도 함께 옮긴다 — 어긋나면 적재·검수가 서로 다른 종류로 본다
        conn.execute(sa.text(
            "UPDATE product_specs SET part_type = :pt"
            " WHERE part_type = 'ETC' AND product_code IN ("
            "   SELECT product_code FROM products WHERE part_type = :pt)"),
            {"pt": pt})
        print("  %s -> %s : %d건" % (cat, pt, n))


def downgrade():
    conn = op.get_bind()
    for _cat, pt in MAP:
        conn.execute(sa.text(
            "UPDATE product_specs SET part_type = 'ETC' WHERE part_type = :pt"), {"pt": pt})
        conn.execute(sa.text(
            "UPDATE products SET part_type = 'ETC', updated_at = now()"
            " WHERE part_type = :pt"), {"pt": pt})
