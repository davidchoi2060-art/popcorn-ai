"""0171 — 0170 이 공개 승인 구성 25개의 몰 구성 원문까지 바꾼 것을 되돌린다.

■ 왜
  몰 등록 구성 표(api/customer_pc_registered)는 «승인된 구성의 원문 문구 = 그 구성의 부품»으로 사진·설명을 배운다.
  0170 이 승인 구성 25개의 원문 쿨러를 JF120R 로 바꾸자, 승인 구성 부품은 아직 ABKO 자이로스라
  「JF120R 문구 = ABKO 사진」을 배워 다른 상품의 JF120R 줄에 옛 쿨러 사진·설명이 붙었다(2026-10-21 실측).
  승인 구성을 다시 승인할 때(구성표 부품 수정) 원문도 함께 바꾼다 — 그 전까지 둘을 맞춰 둔다.
"""
import importlib.util
from pathlib import Path

from alembic import op

revision = "0171"
down_revision = "0170"
branch_labels = None
depends_on = None

_spec = importlib.util.spec_from_file_location("m0170", Path(__file__).with_name("0170_mall_parts_20261021.py"))
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)


def upgrade() -> None:
    M._apply(op.get_bind(), "new", "old", only_public=True)


def downgrade() -> None:
    M._apply(op.get_bind(), "old", "new", only_public=True)
