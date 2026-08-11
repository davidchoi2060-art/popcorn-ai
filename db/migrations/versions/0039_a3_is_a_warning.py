# -*- coding: utf-8 -*-
"""A3(BIOS)는 막는 관계가 아니라 **경고**다 (2026-08-11)

■ 회귀 `[43] 막는 관계는 부품 둘 이상이 얽힌다` 가 잡았다
  A3 에 얽힌 부품이 메인보드 하나뿐이었다(`bios_min_version`). 호환은 쌍이라
  한쪽만으로는 판정할 수 없으니, 이 상태로는 **영원히 못 막는 규칙**이다.

■ 그런데 짝을 채우는 것이 답이 아니다 — 애초에 막을 수 없는 관계다
  A3 판정에 필요한 것은 「이 보드의 **현재** BIOS 버전」인데, 그건 **출고 시점마다
  다르고 재고 단위로도 다르다.** 우리는 알 수 없고 알 방법도 없다.
  막는 규칙으로 두면 `bios_min_version` 을 채우는 순간 **멀쩡한 조합이 전부 탈락**한다.

  실무에서 할 수 있는 최선은 *"이 조합은 BIOS 업데이트가 필요할 수 있습니다"* 라고
  **알리는 것**이다. 그래서 경고로 내린다.

  『화면 정직성』과 같은 규칙이다 — **검증하지 않는 것을 검증한 척하지 않는다.**
  대신 검증하지 않는다는 사실을 말한다.

■ `cpu_generation` 은 A2 에만 둔다
  A3 에도 태그하면 A3 가 다시 '막는 관계'로 잡힌다(그 항목이 막음이므로).
  세대 값은 A2(칩셋이 그 세대를 지원하는가)에서 쓰이고, A3 경고 문구를 만들 때
  참조할 뿐이다.
"""
from alembic import op
import sqlalchemy as sa

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE std.spec_defs"
        "   SET is_blocking = false,"
        "       note = COALESCE(note,'') || ' / 막지 않고 경고한다 — 보드의 현재 BIOS"
        " 버전은 출고 시점마다 달라 우리가 알 수 없다(0039)'"
        " WHERE field_key = 'bios_min_version'"))


def downgrade():
    op.get_bind().execute(sa.text(
        "UPDATE std.spec_defs SET is_blocking = true WHERE field_key = 'bios_min_version'"))
