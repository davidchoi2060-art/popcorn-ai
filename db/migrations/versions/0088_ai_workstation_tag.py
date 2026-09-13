# -*- coding: utf-8 -*-
"""0088 — products.builtpc_kind · builtpc_spec — 완제품 워크스테이션 표시 컬럼 (2026-09-13 사장님 승인)

■ 왜
  팝콘PC 몰이 파는 NVIDIA AI 전용 완제품 워크스테이션을 고객 화면에 내보인다.
  「이 상품이 AI 워크스테이션이다」라는 판정을 **상품명 파싱이 아니라 명시 컬럼**에 둔다.
  CLAUDE.md — 이름으로 동작을 추정하는 검사는 표기가 바뀌는 날 빠져나간다. 지금 상품명은
  '워크스테이션 NO.07.113558 <font color=blue>[AI / 빅데이터 / 딥러닝]</font><p> [14900K/64G/1TB/RTX5090]'
  꼴(HTML 태그 + [용도] + [CPU/RAM/SSD/GPU])인데, 몰이 태그·용도 표기를 바꾸면 이름 기반 판정은
  조용히 0건이 된다(전례: 회원가입 문구 변경으로 후보 400건을 못 잡은 사고, CLAUDE.md §회귀).

■ 컬럼
  builtpc_kind  VARCHAR(20) NULL
      어휘(지금은 하나만 쓴다 · CHECK 로 묶지 않는다 — 다음 종류를 추가할 때 마이그레이션 없이
      값만 넣을 수 있게):
        'ai_workstation'  NVIDIA AI 전용 완제품 워크스테이션(2026-09-13 사장님 확정, 이번 범위)
        (향후 여지)       'office' · 'gaming' 등 — 사장님 확정 뒤에만 추가한다
      NULL = 표시 안 함(=완제품이어도 고객 화면 '완제품 워크스테이션' 칸에 안 나옴).
  builtpc_spec  JSONB NULL
      {cpu, ram_gb, ssd, gpu, gpu_count} — **사람이 확인한** 사양 요약, 화면 표시용.
      product_specs 와 다른 것: product_specs 는 부품 단위 정형 사양(호환 엔진 입력)이고
      완제품(PC_COMPLETE)은 그 표에 뜻있는 행이 없다. 이 JSON 은 「고객에게 보여 줄 한 줄 요약」이
      전부이며 호환 엔진·추천이 읽지 않는다. 초안은 tools/tag_ai_workstation.py 가 상품명에서
      파싱해 넣되 **파싱 실패 필드는 비운다(지어내지 않는다)** — 채우는 것은 사람 몫.

■ 적재가 되돌리지 않는다 — 확인 (2026-09-13 실측)
  api/catalog_ingest.py UPSERT_PRODUCTS_SQL (508~639행):
    INSERT 컬럼 목록 509~512행, SET 절 515~638행 — **builtpc_kind · builtpc_spec 둘 다 언급 없음**.
    ON CONFLICT DO UPDATE 는 SET 절에 적힌 컬럼만 바꾸므로, 목록에 없는 컬럼은 재적재가
    자동으로 건드리지 않는다. 0031(완제품 분류)이 08-15 적재에 340건 되돌아간 것은 part_type 이
    SET 절 안(570행)에 있었기 때문이고 이 둘은 그 경우가 아니다.
    적재 경로(api/catalog_ingest.py · tools/catalog_import.py · api/admin_catalog_import.py)에
    products 의 DELETE/TRUNCATE/전체 재생성은 없다(grep 실측 0건 · 모듈 docstring 11행
    "product_code 기준 upsert이고 삭제가 없다"). 따라서 locked_fields 잠금도 필요 없다.
  ⚠ 단, 앞으로 누가 UPSERT SET 절에 이 두 컬럼을 추가하면 이 보장이 깨진다 — 추가하려면
    CASE WHEN locked_fields 가드가 아니라 **아예 넣지 않는 것**이 맞다(원천 CSV 에 이 값이 없다).

■ 인덱스
  부분 인덱스 WHERE builtpc_kind IS NOT NULL — 표시 대상은 수십 건이고 나머지 2만여 건은 NULL 이라
  전체 인덱스는 낭비다. 고객 화면 조회(kind 별 목록)만 탄다.

Revision ID: 0088
Revises: 0087
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0088"
down_revision = "0087"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("builtpc_kind", sa.String(20), nullable=True))
    op.add_column("products", sa.Column(
        "builtpc_spec", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_index(
        "ix_products_builtpc_kind", "products", ["builtpc_kind"],
        postgresql_where=sa.text("builtpc_kind IS NOT NULL"),
    )
    op.execute(
        "COMMENT ON COLUMN products.builtpc_kind IS "
        "'완제품 표시 종류 — ai_workstation | NULL(향후 office·gaming 등 확장 여지, 사장님 확정 뒤 추가). "
        "사람이 정한 값 · catalog_ingest UPSERT 가 언급하지 않아 적재가 안 덮음(0088)'"
    )
    op.execute(
        "COMMENT ON COLUMN products.builtpc_spec IS "
        "'{cpu, ram_gb, ssd, gpu, gpu_count} — 사람이 확인한 사양 요약, 고객 화면 표시용. "
        "product_specs(호환 엔진 입력)와 다른 것 · 적재가 안 덮음(0088)'"
    )
    print("[0088] products.builtpc_kind · builtpc_spec + ix_products_builtpc_kind(부분) 생성")


def downgrade() -> None:
    op.drop_index("ix_products_builtpc_kind", table_name="products")
    op.drop_column("products", "builtpc_spec")
    op.drop_column("products", "builtpc_kind")
