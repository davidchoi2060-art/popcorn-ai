# -*- coding: utf-8 -*-
"""상품 원본 관리 확장 -- 몰 반출용 필드군

■ 왜
  통합 상품관리 v6 승인 디자인(docs/design/incoming/dc-product-unified-admin.html)
  등록 폼 12섹션을 현행 스키마와 전수 대조한 결과(req-product-new.md §4), 31항목이
  "표 신설 필요"였다. 이 화면 성격은 몰(팝콘PC 윈윈)로 내보낼 상품 원본 관리로
  확정됐다(spec-product-unified.md §4-②) -- 팝콘AI가 직접 판매하지 않는다는 결정
  (2026-08-11)은 유지된다. 배송비 반품비 혜택 채널 필드는 "우리가 그 일을 한다"가
  아니라 "몰에 실어 보낼 값을 여기서 관리한다"는 뜻이다.

  상세 설계 근거는 06_db-erd.md §20(이 마이그레이션과 같은 물결에 추가).

■ 이 개정에서 정한 것 (스키마 형태만 -- 값의 정책은 대부분 사장님 결정 대기로 남김)
  - 정상가 = products.list_price 신규 컬럼. 기존 market_price(가격검토 화면이 쓰는
    시장 관측가)는 재사용하지 않는다 -- 재사용하면 두 화면이 다른 뜻으로 같은 값을 흔든다.
  - product_options.option_stock 은 컬럼만 만들고 stock_movements 원장 연동은 안 한다
    (CANON §2-2 stock_qty=SUM(qty_delta) 불변식을 옵션 단위로 확장할지는 재고 정책
    결정이라 이 개정 범위 밖).
  - 임시저장(draft) 표는 만들지 않는다 -- 저장 위치 3안(서버표/브라우저/미저장)이
    아직 열려 있다(req-product-new.md 결정8). 표부터 만들면 사실상 서버표 안으로
    정하는 셈이 된다.
  - 다건 항목(이미지 옵션 추가상품 태그 채널)은 별도 표, 스칼라 항목은 products
    컬럼 추가 -- 기존 스키마 원칙(§1 "레이어 분리", 1:N을 컬럼에 욱여넣지 않는다).

■ 이름이 같은 다른 개념과 구분 (원안 필드명이 기존 컬럼/테이블과 헷갈릴 수 있는 지점)
  product_notice.origin        제조국.  products.data_origin(데이터 출처)과 동명이의
  product_notice.warranty_note 자유 문구 보증. products.warranty_months(정수 개월)와 다른 것
  product_channels.channel     노출 설정. orders.channel(주문 유입 채널)과 다른 것
  product_channel_keywords     검색 마케팅 키워드. product_specs.tag_*(호환 엔진이
                                읽는 구조화 선호 플래그)와 다른 것
  supplier_product_code        공급사 상품코드. danawa_code · supplier(명칭 자유텍스트)와 다른 축

■ 상한 값은 DB 제약으로 넣지 않는다
  추가 이미지 9건 · 네이버 태그 10 · 쿠팡 태그 20은 원안 마크업 상수일 뿐 서버 규칙이
  아직 없다(req-product-new.md 결정7). 없는 규칙을 스키마에 하드코딩하지 않는다 --
  필요해지면 API 검증으로 추가한다.

Revision ID: 0081
Revises: 0080
"""
import sqlalchemy as sa
from alembic import op

revision = "0081"
down_revision = "0080"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- products 스칼라 컬럼 10종 -----------------------------------------
    op.add_column("products", sa.Column("supplier_product_code", sa.String(80)))
    op.add_column("products", sa.Column("barcode", sa.String(64)))
    op.add_column("products", sa.Column(
        "is_visible", sa.Boolean, nullable=False, server_default=sa.true()))
    op.add_column("products", sa.Column(
        "min_order_qty", sa.Integer, nullable=False, server_default="1"))
    op.add_column("products", sa.Column(
        "tax_type", sa.String(8), nullable=False, server_default="과세"))
    op.add_column("products", sa.Column(
        "is_reserve_sale", sa.Boolean, nullable=False, server_default=sa.false()))
    op.add_column("products", sa.Column("list_price", sa.Integer))
    op.add_column("products", sa.Column("description_html", sa.Text))
    op.add_column("products", sa.Column(
        "point_buy", sa.Integer, nullable=False, server_default="0"))
    op.add_column("products", sa.Column(
        "point_review", sa.Integer, nullable=False, server_default="0"))

    op.create_check_constraint(
        "ck_products_tax_type", "products",
        "tax_type IN ('과세','면세','영세')")
    op.create_check_constraint(
        "ck_products_min_order_qty", "products", "min_order_qty >= 1")
    op.create_check_constraint(
        "ck_products_list_price", "products",
        "list_price IS NULL OR list_price BETWEEN 0 AND 100000000")
    op.create_check_constraint(
        "ck_products_point_buy", "products", "point_buy >= 0")
    op.create_check_constraint(
        "ck_products_point_review", "products", "point_review >= 0")

    op.execute(
        "COMMENT ON COLUMN products.list_price IS "
        "'정상가 -- market_price(시장 관측가·가격검토 화면 전용)와 다른 컬럼. "
        "06_db-erd.md §20-B 근거'"
    )
    op.execute(
        "COMMENT ON COLUMN products.is_visible IS "
        "'노출 여부 -- status(판매 가능 여부)와 별개 축'"
    )

    # --- product_media -------------------------------------------------
    op.create_table(
        "product_media",
        sa.Column("media_id", sa.Integer, primary_key=True),
        sa.Column("product_code", sa.BigInteger,
                   sa.ForeignKey("products.product_code"), nullable=False),
        sa.Column("media_type", sa.String(10), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("sort_order", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                   server_default=sa.func.now()),
        sa.CheckConstraint("media_type IN ('image','video')", name="ck_media_type"),
        sa.CheckConstraint("role IN ('main','sub')", name="ck_media_role"),
    )
    op.create_index("ix_product_media_product_code", "product_media", ["product_code"])
    op.create_index(
        "uq_media_one_main", "product_media", ["product_code"],
        unique=True,
        postgresql_where=sa.text("role='main' AND media_type='image'"),
    )
    op.execute(
        "COMMENT ON TABLE product_media IS "
        "'상품 이미지·동영상(1:N). 대표 이미지는 상품당 1건(uq_media_one_main)'"
    )

    # --- product_options -------------------------------------------------
    op.create_table(
        "product_options",
        sa.Column("option_id", sa.Integer, primary_key=True),
        sa.Column("product_code", sa.BigInteger,
                   sa.ForeignKey("products.product_code"), nullable=False),
        sa.Column("option_name", sa.String(80), nullable=False),
        sa.Column("option_value", sa.String(80), nullable=False),
        sa.Column("extra_price", sa.Integer, nullable=False, server_default="0"),
        sa.Column("option_stock", sa.Integer, nullable=False, server_default="0"),
        sa.Column("sort_order", sa.SmallInteger, nullable=False, server_default="0"),
    )
    op.create_index("ix_product_options_product_code", "product_options", ["product_code"])
    op.execute(
        "COMMENT ON COLUMN product_options.option_stock IS "
        "'옵션별 재고 -- stock_movements 원장과 아직 연동 안 됨(의도적 보류, "
        "06_db-erd.md §20-B). products.stock_qty 불변식과 무관'"
    )

    # --- product_addons -------------------------------------------------
    op.create_table(
        "product_addons",
        sa.Column("addon_id", sa.Integer, primary_key=True),
        sa.Column("product_code", sa.BigInteger,
                   sa.ForeignKey("products.product_code"), nullable=False),
        sa.Column("addon_name", sa.String(120), nullable=False),
        sa.Column("addon_price", sa.Integer, nullable=False, server_default="0"),
        sa.Column("sort_order", sa.SmallInteger, nullable=False, server_default="0"),
    )
    op.create_index("ix_product_addons_product_code", "product_addons", ["product_code"])

    # --- product_shipping_policy (1:1) ------------------------------------
    op.create_table(
        "product_shipping_policy",
        sa.Column("product_code", sa.BigInteger,
                   sa.ForeignKey("products.product_code"), primary_key=True),
        sa.Column("ship_method", sa.String(12), nullable=False, server_default="택배"),
        sa.Column("ship_fee", sa.Integer, nullable=False, server_default="0"),
        sa.Column("free_ship_over", sa.Integer),
        sa.Column("return_fee", sa.Integer, nullable=False, server_default="0"),
        sa.Column("exchange_fee", sa.Integer, nullable=False, server_default="0"),
        sa.Column("return_note", sa.Text),
        sa.CheckConstraint(
            "ship_method IN ('택배','직접배송','방문수령')", name="ck_ship_method"),
    )
    op.execute(
        "COMMENT ON TABLE product_shipping_policy IS "
        "'몰 반출용 배송·반품/교환 정책(1:1) -- 본 시스템이 배송을 수행한다는 뜻이 "
        "아니라 몰에 실어 보낼 값의 보관처. 06_db-erd.md §20-A'"
    )

    # --- product_notice (1:1) ---------------------------------------------
    op.create_table(
        "product_notice",
        sa.Column("product_code", sa.BigInteger,
                   sa.ForeignKey("products.product_code"), primary_key=True),
        sa.Column("notice_group", sa.String(40)),
        sa.Column("origin", sa.String(80)),
        sa.Column("warranty_note", sa.Text),
        sa.Column("as_name", sa.String(80)),
        sa.Column("as_phone", sa.String(20)),
        sa.Column("remarks", sa.Text),
    )
    op.execute(
        "COMMENT ON COLUMN product_notice.origin IS "
        "'제조국 -- products.data_origin(데이터 출처 구분)과 동명이의, 다른 개념'"
    )
    op.execute(
        "COMMENT ON COLUMN product_notice.warranty_note IS "
        "'품질보증기준 자유 문구 -- products.warranty_months(정수 개월)와 다른 것'"
    )

    # --- product_channels ---------------------------------------------
    op.create_table(
        "product_channels",
        sa.Column("product_code", sa.BigInteger,
                   sa.ForeignKey("products.product_code"), primary_key=True),
        sa.Column("channel", sa.String(20), primary_key=True),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    op.execute(
        "COMMENT ON TABLE product_channels IS "
        "'채널별 노출 설정 -- orders.channel(주문 유입 채널 원장)과 다른 것'"
    )

    # --- product_channel_keywords ---------------------------------------
    op.create_table(
        "product_channel_keywords",
        sa.Column("keyword_id", sa.Integer, primary_key=True),
        sa.Column("product_code", sa.BigInteger,
                   sa.ForeignKey("products.product_code"), nullable=False),
        sa.Column("channel", sa.String(20)),  # NULL = 공통 키워드
        sa.Column("keyword", sa.String(40), nullable=False),
        sa.Column("sort_order", sa.SmallInteger, nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_product_channel_keywords_product_code",
        "product_channel_keywords", ["product_code"])
    op.execute(
        "COMMENT ON COLUMN product_channel_keywords.channel IS "
        "'NULL=공통 키워드, 값 있으면 그 채널 전용(원안: 공통을 복사해 채널별 독립 관리)'"
    )
    op.execute(
        "COMMENT ON TABLE product_channel_keywords IS "
        "'검색·마케팅용 자유 키워드 -- product_specs.tag_*(호환엔진이 읽는 구조화 "
        "선호 플래그)와 다른 것'"
    )

    print("[0081] products 컬럼 10종 + 신규 테이블 7종 생성 완료"
          " (product_media/options/addons/shipping_policy/notice/channels/channel_keywords)")


def downgrade() -> None:
    # 06_db-erd.md §20-F: 전부 신규 생성이라 역방향은 단순 DROP.
    # 실사용 데이터가 쌓인 뒤에는 이 downgrade를 그대로 실행하지 않는다(DBA 판단).
    op.drop_table("product_channel_keywords")
    op.drop_table("product_channels")
    op.drop_table("product_notice")
    op.drop_table("product_shipping_policy")
    op.drop_index("ix_product_addons_product_code", table_name="product_addons")
    op.drop_table("product_addons")
    op.drop_index("ix_product_options_product_code", table_name="product_options")
    op.drop_table("product_options")
    op.drop_index("uq_media_one_main", table_name="product_media")
    op.drop_index("ix_product_media_product_code", table_name="product_media")
    op.drop_table("product_media")

    op.drop_constraint("ck_products_point_review", "products")
    op.drop_constraint("ck_products_point_buy", "products")
    op.drop_constraint("ck_products_list_price", "products")
    op.drop_constraint("ck_products_min_order_qty", "products")
    op.drop_constraint("ck_products_tax_type", "products")
    op.drop_column("products", "point_review")
    op.drop_column("products", "point_buy")
    op.drop_column("products", "description_html")
    op.drop_column("products", "list_price")
    op.drop_column("products", "is_reserve_sale")
    op.drop_column("products", "tax_type")
    op.drop_column("products", "min_order_qty")
    op.drop_column("products", "is_visible")
    op.drop_column("products", "barcode")
    op.drop_column("products", "supplier_product_code")
