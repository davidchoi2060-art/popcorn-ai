"""AI 슈퍼컴퓨터 카테고리에 판매 중인 GB10 계열 완제품 7개를 넣고 사양표를 채운다 (2026-10-20 대표 「부품표도 채워서 넣어」).

분류가 비어 있던(NULL) 상품만 「AI 슈퍼컴퓨터」(public_key 'ai-supercomputer', 0166)로 옮긴다.
  129774 NVIDIA DGX Spark · 130446/130447/130448 ASUS Ascent GX10 1TB/2TB/4TB · 130449 HP ZGX nano G1n
  130451 MSI EdgeXpert · 130452 Acer Veriton GN100
표시 정보(ai_device_profiles)는 몰 상품명(용량·A/S)과 GB10 플랫폼 공통 사양(NVIDIA GB10 · 20코어 ARM · 128GB 통합 메모리 ·
NVIDIA DGX OS)으로 채운다. 사진은 팝콘PC 몰의 상품 대표 사진(…_600.jpg)이다 — 몰에 사진이 없는 MSI·Acer 는 비워 둔다.
이미 표시 정보가 있는 상품은 덮지 않는다.
"""
import json

import sqlalchemy as sa
from alembic import op

revision = '0167'
down_revision = '0166'
branch_labels = None
depends_on = None

KEY = 'ai-supercomputer'
IMG = 'assets/images/supercomputer/'
# (상품번호, 표시 이름, 제조사, 모델명, 짧은 이름, 저장장치, 모델 묶음, A/S, 사진 파일)
PRODUCTS = [
    (129774, 'NVIDIA DGX Spark', 'NVIDIA', 'DGX Spark', 'DGX Spark', '4TB', None, None, 'nvidia-dgx-spark.jpg'),
    (130446, 'ASUS Ascent GX10', 'ASUS', 'Ascent GX10', 'GX10', '1TB', 'asus-ascent-gx10', None, 'asus-ascent-gx10.jpg'),
    (130447, 'ASUS Ascent GX10', 'ASUS', 'Ascent GX10', 'GX10', '2TB', 'asus-ascent-gx10', None, 'asus-ascent-gx10.jpg'),
    (130448, 'ASUS Ascent GX10', 'ASUS', 'Ascent GX10', 'GX10', '4TB', 'asus-ascent-gx10', None, 'asus-ascent-gx10.jpg'),
    (130449, 'HP ZGX nano G1n', 'HP', 'ZGX nano G1n', 'ZGX nano', '4TB', None, None, 'hp-zgx-nano-g1n.jpg'),
    (130451, 'MSI EdgeXpert', 'MSI', 'EdgeXpert', 'EdgeXpert', '4TB', None, '3년', None),
    (130452, 'Acer Veriton GN100', 'Acer', 'Veriton GN100', 'GN100', '4TB', None, '2년', None),
]


def detail(name, short, storage, group, warranty):
    rows = [['제품명', name], ['AI 프로세서', 'NVIDIA GB10 Grace Blackwell'], ['CPU', '20코어 ARM 기반 CPU'],
            ['메모리', '128GB LPDDR5x 통합 메모리'], ['저장장치', 'M.2 NVMe SSD ' + storage],
            ['운영체제', 'NVIDIA DGX OS · Ubuntu 기반 Linux']]
    if warranty:
        rows.append(['A/S', warranty + ' (상품 등록 정보 기준)'])
    rows.append(['판매 구성', '선택한 사양의 완제품'])
    faq = []
    if group:
        faq.append(['1TB·2TB·4TB는 어떻게 선택하나요?', '저장공간이 다른 완제품 모델입니다. 위에서 원하는 모델을 선택하면 해당 상품의 가격과 사양을 확인할 수 있습니다.'])
    faq += [
        ['Windows 프로그램도 사용할 수 있나요?', '이 제품은 Ubuntu 기반 NVIDIA DGX OS를 사용합니다. 일반 Windows 프로그램의 실행을 전제로 구매하지 마시고, 필요한 프로그램이 Linux와 ARM 환경을 지원하는지 먼저 확인해 주세요.'],
        ['사내 문서 검색도 바로 제공되나요?', '제품 구매는 하드웨어 기준입니다. 업무형 로컬 AI 패키지가 기본 포함되는 것은 아닙니다. 문서 검색 등 필요한 기능, 데이터 연결, 설치·교육 범위와 지원 가능 여부는 별도 상담에서 확인합니다.'],
        ['어떤 AI 모델까지 사용할 수 있나요?', '모델 종류와 정밀도, 문맥 길이, 동시 사용 인원에 따라 실행 조건과 응답 성능이 달라집니다. 도입 상담에 사용하려는 모델과 업무를 알려주시면 검토 범위를 안내합니다.'],
        ['배송과 보증 조건은 어디서 확인하나요?', '실제 공급 일정, 국내 공급 모델과 보증 조건은 견적 문의에서 확인할 수 있습니다.'],
    ]
    return {
        'short_name': short, 'eyebrow': 'DESKTOP AI SUPERCOMPUTER', 'lead': 'AI 모델 실행·개발을 위한 완제품.',
        'model_note': '128GB 통합 메모리',
        'facts': [['cpu', 'AI 프로세서', 'NVIDIA GB10'], ['memory', '통합 메모리', '128GB'], ['hard-drive', 'SSD', storage],
                  ['code', '운영체제', 'DGX OS']],
        'spec_rows': rows,
        'environment': {'title': ['사용할 프로그램부터', '함께 확인해요.'],
                        'text': 'NVIDIA DGX OS와 ARM 기반으로 작동하는 AI 전용 환경입니다. 사용하려는 모델과 프로그램의 지원 여부를 먼저 확인해 주세요.',
                        'chips': ['Linux', 'ARM', 'NVIDIA DGX OS']},
        'faq': faq,
    }


def upgrade():
    bind = op.get_bind()
    cid = bind.execute(sa.text('SELECT category_id FROM categories WHERE public_key = :k'), {'k': KEY}).scalar()
    if cid is None:
        return
    codes = [p[0] for p in PRODUCTS]
    bind.execute(sa.text('UPDATE products SET category_id = :i WHERE product_code = ANY(:c) AND category_id IS NULL'),
                 {'i': cid, 'c': codes})
    for code, name, maker, model, short, storage, group, warranty, img in PRODUCTS:
        images = [{'src': IMG + img, 'label': '전체 모습', 'alt': name + ' 본체'}] if img else []
        bind.execute(sa.text(
            "INSERT INTO ai_device_profiles (product_code, display_name, maker, model_name, accelerator, processor, memory,"
            " storage, os, architecture, model_group, model_label, images, detail, updated_by)"
            " SELECT :c, :n, :mk, :md, 'NVIDIA GB10', '20코어 ARM 기반 CPU', '128GB', :s, 'DGX OS', 'ARM', :g, :lbl,"
            " CAST(:img AS JSONB), CAST(:d AS JSONB), 'migration 0167 (대표 지시 2026-10-20)'"
            " WHERE EXISTS (SELECT 1 FROM products WHERE product_code = :c AND category_id = :cid)"
            " ON CONFLICT (product_code) DO NOTHING"),
            {'c': code, 'n': name, 'mk': maker, 'md': model, 's': storage, 'g': group, 'lbl': storage if group else None,
             'img': json.dumps(images, ensure_ascii=False), 'cid': cid,
             'd': json.dumps(detail(name, short, storage, group, warranty), ensure_ascii=False)})


def downgrade():
    bind = op.get_bind()
    codes = [p[0] for p in PRODUCTS]
    bind.execute(sa.text("DELETE FROM ai_device_profiles WHERE product_code = ANY(:c) AND updated_by LIKE 'migration 0167%'"),
                 {'c': codes})
    bind.execute(sa.text("UPDATE products SET category_id = NULL WHERE product_code = ANY(:c)"
                         " AND category_id = (SELECT category_id FROM categories WHERE public_key = :k)"),
                 {'c': codes, 'k': KEY})
