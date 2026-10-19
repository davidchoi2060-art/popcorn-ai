"""AI 슈퍼컴퓨터를 «계속 추가되는 카테고리»로 — 판매 탐색 분류 + 상품별 고객 표시 정보 (2026-10-20 대표 승인).

■ 분류(어떤 상품이 목록에 나오나)
  `categories.public_key` (TEXT, NULL 허용, 고유) — 고객 화면이 이름 대신 쓰는 고정 키. 이름은 관리자가 바꿀 수 있어서다.
  「완제품」(55) 아래 「AI 슈퍼컴퓨터」 카테고리를 만들고 키를 'ai-supercomputer' 로 둔다.
  지금 판매 중인 Dell Pro Max GB10 두 상품(129615 · 129614)은 분류가 비어 있어(NULL) 이 카테고리로 넣는다.
  이후 상품은 관리자 「카테고리 매핑」 화면(api/admin_category_mapping)으로 이 카테고리에 옮기면 고객 목록에 나온다.
  카테고리는 판매 탐색 축이다 — 마진 정책이 하나도 없어(category_margin_policies 0행) 판매가는 바뀌지 않는다.

■ 상품별 고객 표시 정보 `ai_device_profiles`
  제조사·모델명·사진·가속기/프로세서·메모리·저장장치·운영체제·아키텍처·같은 제품의 모델 묶음과 상세 내용(사양표·연결·사용 환경·FAQ).
  상품마다 한 행이다. 행이 없거나 값이 비면 고객 화면은 «확인 필요»로 보인다 — 다른 상품(GB10)의 값을 물려주지 않는다.
  두 GB10 행은 승인 v15/v15.1 화면의 내용을 그대로 옮긴 것이다(Dell 사진·DGX OS·ARM·포트·FAQ 는 GB10 에만 있다).
"""
import json

import sqlalchemy as sa
from alembic import op

revision = '0166'
down_revision = '0165'
branch_labels = None
depends_on = None

KEY = 'ai-supercomputer'
CODES = (129615, 129614)
GROUP = 'dell-pro-max-gb10'
IMG = 'assets/images/supercomputer/'


def _gb10(storage):
    return {
        'brand_label': 'DELL',
        'short_name': 'GB10',
        'eyebrow': 'DESKTOP AI SUPERCOMPUTER',
        'lead': 'AI 모델 실행·개발을 위한 완제품.',
        'gallery_caption': ['작은 공간에서 시작하는', '나만의 AI 개발 환경.'],
        'model_note': '128GB 통합 메모리',
        'facts': [['cpu', 'AI 프로세서', 'NVIDIA GB10'], ['memory', '통합 메모리', '128GB'], ['hard-drive', 'SSD', storage], ['code', '운영체제', 'DGX OS']],
        'spec_rows': [['제품명', 'Dell Pro Max GB10'], ['AI 프로세서', 'NVIDIA GB10 Grace Blackwell'],
                      ['CPU', '20코어 ARM 기반 CPU'], ['메모리', '128GB LPDDR5x 통합 메모리'],
                      ['저장장치', 'M.2 NVMe SSD ' + storage], ['운영체제', 'NVIDIA DGX OS · Ubuntu 기반 Linux'],
                      ['네트워크', '10GbE · NVIDIA ConnectX-7'], ['판매 구성', '선택한 사양의 완제품']],
        'connectivity': {'title': '연결까지, 한눈에.', 'text': '제품 뒷면의 실제 연결 단자를 확인하세요.',
                         'labels': ['10GbE', 'ConnectX-7'],
                         'image': {'src': IMG + 'gb10-rear-1600.webp', 'alt': 'Dell GB10 후면, 네트워크 및 연결 단자',
                                   'width': 1600, 'height': 562, 'caption': 'Dell GB10 후면'}},
        'environment': {'title': ['사용할 프로그램부터', '함께 확인해요.'],
                        'text': 'DGX OS와 ARM 기반으로 작동하는 AI 전용 환경입니다. 사용하려는 모델과 프로그램의 지원 여부를 먼저 확인해 주세요.',
                        'chips': ['Linux', 'ARM', 'NVIDIA DGX OS']},
        'faq': [['2TB와 4TB는 어떻게 선택하나요?', '저장공간이 다른 두 완제품 모델입니다. 위에서 원하는 모델을 선택하면 해당 상품의 가격과 사양을 확인할 수 있습니다.'],
                ['Windows 프로그램도 사용할 수 있나요?', '이 제품은 Ubuntu 기반 DGX OS를 사용합니다. 일반 Windows 프로그램의 실행을 전제로 구매하지 마시고, 필요한 프로그램이 Linux와 ARM 환경을 지원하는지 먼저 확인해 주세요.'],
                ['사내 문서 검색도 바로 제공되나요?', '제품 구매는 하드웨어 기준입니다. 업무형 로컬 AI 패키지가 기본 포함되는 것은 아닙니다. 문서 검색 등 필요한 기능, 데이터 연결, 설치·교육 범위와 지원 가능 여부는 별도 상담에서 확인합니다.'],
                ['어떤 AI 모델까지 사용할 수 있나요?', '모델 종류와 정밀도, 문맥 길이, 동시 사용 인원에 따라 실행 조건과 응답 성능이 달라집니다. 도입 상담에 사용하려는 모델과 업무를 알려주시면 검토 범위를 안내합니다.'],
                ['배송과 보증 조건은 어디서 확인하나요?', '실제 공급 일정, 국내 공급 모델과 보증 조건은 견적 문의에서 확인할 수 있습니다.']],
    }


IMAGES = [{'src': IMG + 'gb10-product.jpg', 'label': '전체 모습', 'alt': 'Dell Pro Max GB10 본체'},
          {'src': IMG + 'gb10-front-1600.webp', 'label': '전면', 'alt': 'Dell Pro Max GB10 전면'},
          {'src': IMG + 'gb10-rear-1600.webp', 'label': '후면·연결 단자', 'alt': 'Dell Pro Max GB10 후면 연결 단자'}]


def upgrade():
    bind = op.get_bind()
    op.execute('ALTER TABLE categories ADD COLUMN public_key TEXT')
    op.execute("ALTER TABLE categories ADD CONSTRAINT categories_public_key_chk CHECK (public_key ~ '^[a-z0-9-]{2,40}$')")
    op.execute('CREATE UNIQUE INDEX categories_public_key_uq ON categories (public_key) WHERE public_key IS NOT NULL')
    parent = bind.execute(sa.text("SELECT category_id FROM categories WHERE parent_id IS NULL AND name = '완제품'")).scalar()
    cid = bind.execute(sa.text(
        "SELECT category_id FROM categories WHERE name = 'AI 슈퍼컴퓨터' AND parent_id IS NOT DISTINCT FROM :p"),
        {'p': parent}).scalar()
    if cid is None:
        cid = bind.execute(sa.text(
            "INSERT INTO categories (parent_id, name, sort_order, allowed_part_types, public_key)"
            " VALUES (:p, 'AI 슈퍼컴퓨터', 15, CAST(:t AS JSONB), :k) RETURNING category_id"),
            {'p': parent, 't': json.dumps(['BAREBONE', 'PC_COMPLETE', 'ETC']), 'k': KEY}).scalar()
    else:
        bind.execute(sa.text('UPDATE categories SET public_key = :k WHERE category_id = :i'), {'k': KEY, 'i': cid})
    # 분류가 비어 있는 GB10 두 상품만 넣는다(이미 다른 분류에 있으면 관리자 판단을 덮지 않는다).
    bind.execute(sa.text('UPDATE products SET category_id = :i WHERE product_code = ANY(:c) AND category_id IS NULL'),
                 {'i': cid, 'c': list(CODES)})

    op.execute('''CREATE TABLE ai_device_profiles (
        product_code   BIGINT PRIMARY KEY REFERENCES products(product_code),
        display_name   TEXT,
        maker          TEXT,
        model_name     TEXT,
        accelerator    TEXT,
        processor      TEXT,
        memory         TEXT,
        storage        TEXT,
        os             TEXT,
        architecture   TEXT,
        model_group    TEXT CHECK (model_group ~ '^[a-z0-9-]{2,60}$'),
        model_label    TEXT,
        featured_rank  SMALLINT CHECK (featured_rank BETWEEN 1 AND 99),
        images         JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(images) = 'array'),
        detail         JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(detail) = 'object'),
        updated_at     TIMESTAMP NOT NULL DEFAULT now(),
        updated_by     TEXT
    )''')
    for code, storage, rank in ((129615, '2TB', 1), (129614, '4TB', 2)):
        bind.execute(sa.text(
            "INSERT INTO ai_device_profiles (product_code, display_name, maker, model_name, accelerator, processor, memory,"
            " storage, os, architecture, model_group, model_label, featured_rank, images, detail, updated_by)"
            " SELECT :c, 'Dell Pro Max GB10', 'Dell', 'Pro Max GB10', 'NVIDIA GB10', '20코어 ARM 기반 CPU', '128GB',"
            " :s, 'DGX OS', 'ARM', :g, :s, :r, CAST(:img AS JSONB), CAST(:d AS JSONB), 'migration 0166 (v15 승인 내용)'"
            " WHERE EXISTS (SELECT 1 FROM products WHERE product_code = :c)"),
            {'c': code, 's': storage, 'g': GROUP, 'r': rank, 'img': json.dumps(IMAGES, ensure_ascii=False),
             'd': json.dumps(_gb10(storage), ensure_ascii=False)})


def downgrade():
    bind = op.get_bind()
    op.execute('DROP TABLE IF EXISTS ai_device_profiles')
    cid = bind.execute(sa.text('SELECT category_id FROM categories WHERE public_key = :k'), {'k': KEY}).scalar()
    if cid is not None:
        bind.execute(sa.text('UPDATE products SET category_id = NULL WHERE category_id = :i AND product_code = ANY(:c)'),
                     {'i': cid, 'c': list(CODES)})
        left = bind.execute(sa.text('SELECT count(*) FROM products WHERE category_id = :i'), {'i': cid}).scalar()
        if left:
            raise RuntimeError('AI supercomputer category still has products; move them first')
        bind.execute(sa.text('DELETE FROM categories WHERE category_id = :i'), {'i': cid})
    op.execute('DROP INDEX IF EXISTS categories_public_key_uq')
    op.execute('ALTER TABLE categories DROP CONSTRAINT IF EXISTS categories_public_key_chk')
    op.execute('ALTER TABLE categories DROP COLUMN IF EXISTS public_key')
