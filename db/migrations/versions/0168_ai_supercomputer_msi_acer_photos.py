"""AI 슈퍼컴퓨터 MSI EdgeXpert(130451)·Acer Veriton GN100(130452)에 대표 사진을 붙인다 (2026-10-20 대표 「사진 준비중인거 다 찾아서」).

0167 은 몰에 사진이 없어 두 제품의 사진을 비워 뒀다. 같은 제품군 공식 본체 사진(출처 assets/images/supercomputer/SOURCES.json)을
사진이 «비어 있을 때만» 넣는다 — 운영자가 관리자에서 이미 넣은 사진은 덮지 않는다.
"""
import json

import sqlalchemy as sa
from alembic import op

revision = '0168'
down_revision = '0167'
branch_labels = None
depends_on = None

IMG = 'assets/images/supercomputer/'
PHOTOS = [(130451, 'msi-edgexpert.png', 'MSI EdgeXpert'), (130452, 'acer-veriton-gn100.jpg', 'Acer Veriton GN100')]


def _images(img, name):
    return json.dumps([{'src': IMG + img, 'label': '전체 모습', 'alt': name + ' 본체'}], ensure_ascii=False)


def upgrade():
    bind = op.get_bind()
    for code, img, name in PHOTOS:
        bind.execute(sa.text(
            "UPDATE ai_device_profiles SET images = CAST(:img AS JSONB)"
            " WHERE product_code = :c AND (images IS NULL OR images = '[]'::jsonb)"),
            {'c': code, 'img': _images(img, name)})


def downgrade():
    bind = op.get_bind()
    for code, img, name in PHOTOS:              # 이 마이그레이션이 넣은 값 그대로일 때만 비운다
        bind.execute(sa.text(
            "UPDATE ai_device_profiles SET images = '[]'::jsonb WHERE product_code = :c AND images = CAST(:img AS JSONB)"),
            {'c': code, 'img': _images(img, name)})
