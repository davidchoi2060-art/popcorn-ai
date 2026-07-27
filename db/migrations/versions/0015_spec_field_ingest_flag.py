"""적재 대상 플래그 — spec_field_defs.in_ingest (슬라이스 56).

`SPEC_COLS`(적재가 product_specs에 넣는 컬럼 목록)를 part_types로 **유도할 수 없다**.
실제 목록이 불규칙하기 때문이다: 모니터 필드(size_inch·resolution·refresh_hz·panel)는
들어 있는데 키보드 필드(switch_type 등)는 없고, `socket_list`는 있는데 `form_factor_list`는
없다(별도 경로로 처리된다). 태그 3종도 `extract_tags`가 따로 채운다.

추측으로 목록을 만들면 적재가 조용히 달라진다. 그래서 **지금 코드가 넣는 컬럼 그대로**를
플래그로 적는다. 앞으로 필드를 추가할 때 이 플래그로 적재 포함 여부를 정한다.

Revision ID: 0015
Revises: 0014
"""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

# api/catalog_ingest.SPEC_COLS 그대로 (2026-07-28 시점)
INGEST = [
    "socket", "socket_list", "chipset", "mem_type", "capacity_gb", "clock_mhz",
    "tdp_watt", "rated_watt", "required_power_watt", "length_mm", "gpu_max_mm",
    "cooler_height_mm", "cooler_tdp", "pcie_gen", "form_factor", "interface",
    "size_inch", "resolution", "refresh_hz", "panel",
]


def upgrade() -> None:
    op.execute("ALTER TABLE spec_field_defs ADD COLUMN in_ingest BOOLEAN NOT NULL DEFAULT false")
    keys = ",".join("'%s'" % k for k in INGEST)
    op.execute(f"UPDATE spec_field_defs SET in_ingest = true WHERE field_key IN ({keys})")


def downgrade() -> None:
    op.execute("ALTER TABLE spec_field_defs DROP COLUMN IF EXISTS in_ingest")
