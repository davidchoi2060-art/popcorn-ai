"""호환 규칙에 '적용 부품 종류' 조건 — 공랭용 규칙이 수랭을 죽이고 있었다 (슬라이스 82).

규칙은 **슬롯 단위**로만 걸렸다. 그런데 한 슬롯에 성격이 다른 부품이 들어온다:
CPU쿨러 슬롯은 공랭(COOLER_CPU_AIR)과 수랭(COOLER_CPU_AIO)을 함께 받는다.

그래서 이런 일이 벌어졌다(2026-07-29 실측):

    cooler_height 규칙 = COOLER.cooler_height_mm <= CASE.cooler_height_mm
    그런데 cooler_height_mm의 적용 부품은 CASE·COOLER_CPU_AIR 뿐 —
    수랭에는 그 값을 채울 자리가 없다(후보 49개 전부 NULL).
    NULL 불통과 계약이 걸리면서 **수랭은 견적에 한 번도 들어가지 못했다.**

500도 경고도 없다. 조용히 사라진다. 화면은 "수랭 재고 239개"라고 말하고 운영자는
팔 수 있다고 믿는다. 규칙이 겨냥하지 않은 부품까지 같이 죽인 것이다.

`part_types`가 비어 있으면 예전처럼 슬롯 전체에 적용한다(기존 7종은 그대로).
`cooler_height`만 공랭 한정으로 좁힌다.

**수랭이 케이스에 들어가는지는 이 마이그레이션으로 검증되지 않는다.** 라디에이터 규칙은
다음 단계다 — 그때까지 수랭 견적의 근거가 그 사실을 밝힌다.

Revision ID: 0021
Revises: 0020
"""
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE compat_rules ADD COLUMN IF NOT EXISTS"
               " part_types JSONB NOT NULL DEFAULT '[]'::jsonb")
    # 빈 배열 = 슬롯 전체(기존 동작). 공랭 높이 규칙만 좁힌다.
    op.execute("UPDATE compat_rules SET part_types = '[\"COOLER_CPU_AIR\"]'::jsonb"
               " WHERE rule_key = 'cooler_height'")


def downgrade() -> None:
    # 컬럼을 지우면 조건이 사라져 다시 슬롯 전체 적용으로 돌아간다(예전 동작).
    op.execute("ALTER TABLE compat_rules DROP COLUMN IF EXISTS part_types")
