# -*- coding: utf-8 -*-
"""상품별 공급처 다건 수집 — 연락처·순위·리베이트·수집 시각 칸을 연다.

■ 배경
  지금 `product_supplier_prices`는 상품당 행이 사실상 1개뿐이다(2026-08-25 공급처
  정리·연결 작업 — `docs/supplier-consolidation-2026-08-25.md` — 이 `products.supplier`
  텍스트 1건을 이름 매칭해 넣은 결과, 후보 상품 2,959건 중 2,731건이 정확히 1행이고
  228건은 0행이다. **테이블 자체는 이미 (product_code, supplier_id) UNIQUE 라 상품당
  여러 공급처를 담을 수 있는 구조다** — 이번 마이그레이션은 그 구조를 넓히는 것이
  아니라, 몰 관리자 페이지(`/adm_cate/product_com_list.php?pd_no=`)가 실제로 보여주는
  「업체 여러 곳」의 부가 정보(순위·리베이트·발주가·연락처·수집 시각)를 담을 칸이
  없어서 여는 것이다.

■ 왜 연락처는 product_supplier_prices가 아니라 suppliers인가
  몰 페이지의 연락처 줄("(주)메종시스템 Tmaison 통합관리자 전화 : 02-706-0102
  발주번호 : 01027874718")은 **업체 단위 정보**다 — 상품이 바뀐다고 그 업체의 담당자·
  전화가 바뀌지 않는다. product_supplier_prices에 넣으면 같은 업체가 공급하는 상품
  수만큼(현재 매칭된 것만 최대 수백 건) 같은 문자열이 반복된다. suppliers는 이미
  업체 단위 표(공급처 정리 작업으로 117개 실제 회사가 들어와 있다)이므로 그 표에
  더한다. 다만 페이지마다 연락처가 실제로 항상 같은지는 이번 마이그레이션 시점엔
  확인할 수 없어(수집 전) `contact_raw`에 원문을 함께 보존한다 — 수집 도구가 기존
  값과 다른 원문을 만나면 그 사실을 알리고(조용히 덮어쓰지 않고) 사람이 판단하게
  한다(`tools/mall_supplier_fetch.py` 참조).

■ 왜 product_supplier_prices에도 칸을 더하는가
  순위(몰의 배열 첨자, 0=1순위)·리베이트 %·리베이트 금액·발주가·몰 재고상태 원문
  (판매중/품절/단종)은 **(상품, 공급처) 조합마다 다른 값**이라 거기 넣는다.

  `mall_state_raw`를 따로 두고 기존 `supply_state`는 건드리지 않는 이유: 이 컬럼은
  이미 '가능'/'품절'/'문의' 세 값으로 `api/admin_price_import.py`의 `_reprice()`가
  `s == '가능'`으로 최저가 후보를 고른다. 몰의 '판매중'을 그대로 넣으면 그 비교식이
  하나도 안 맞아 몰에서 받은 행이 전부 "가능한 공급처 없음" 취급으로 조용히 밀려난다
  — 수집 도구가 판매중→가능, 품절→품절, 단종→품절(둘 다 "지금 여기서 못 산다"는
  점은 같다 — 다만 원문 구분은 잃지 않도록 `mall_state_raw`에 원문 그대로 남긴다)로
  정규화해 기존 `supply_state`에 넣고, 몰이 실제로 뭐라고 표기했는지는
  `mall_state_raw`가 그대로 보존한다.

  `fetched_at`(수집 시각)은 기존 `updated_at`과 다른 것을 답한다 — `updated_at`은
  단가표 엑셀 반영(`price-import`)도 같이 건드리는 범용 "마지막으로 이 행이 바뀐
  시각"이고, `fetched_at`은 "몰 페이지를 실제로 읽어 이 값을 관측한 시각"이다.
  `fetched_at IS NULL`이면 이 행이 몰 수집이 아니라 다른 경로(단가표 엑셀·2026-08-25
  공급처 연결)로 들어왔다는 뜻이다 — 별도 출처 컬럼을 두지 않고 이 컬럼 하나로
  기존 6,561행과 새 몰 수집분을 구분한다.

■ 왜 지금 안 채우는가
  이 마이그레이션은 칸만 연다. 실제로 채우는 것은 `tools/mall_supplier_fetch.py`이고
  그 도구의 `--apply`는 이번 작업 범위 밖이다(드라이런까지만). 기존 6,561행은 전부
  새 컬럼이 NULL인 채로 남는다 — "몰에서 아직 안 읽었다"는 뜻 그대로다.

■ 잠금(locked_fields)과 무관
  이 컬럼들은 products가 아니라 suppliers·product_supplier_prices에 있다 —
  `locked_fields` 잠금 개념은 products 컬럼에만 있고 이 두 표에는 적용되지 않는다
  (2026-08-25 작업 기록 §8-7과 같은 사실).

Revision ID: 0066
Revises: 0065
"""
from alembic import op

revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── suppliers: 업체 단위 연락처 ────────────────────────────────────────
    # 전부 NULL 허용 — 기존 122행(5 기존 + 117 공급처 정리)은 몰에서 연락처를
    # 아직 안 읽었다는 뜻으로 그대로 NULL이 된다.
    op.execute("ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS contact_name VARCHAR(100)")
    op.execute("ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS contact_phone VARCHAR(30)")
    op.execute("ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS order_phone VARCHAR(30)")
    # 파싱이 틀렸을 때(이름·전화·발주번호 경계를 잘못 잘랐을 때) 되짚을 원문.
    op.execute("ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS contact_raw VARCHAR(300)")
    op.execute("ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS contact_fetched_at TIMESTAMP")

    # ── product_supplier_prices: (상품, 공급처) 조합별 부가 정보 ────────────
    # 기존 6,561행은 전부 NULL — 2026-08-25 정리 작업은 몰의 이 페이지를 읽은 것이
    # 아니라 엑셀의 "매입가" 열 + 이름 매칭으로 넣은 값이라 순위·리베이트·발주가
    # 원본이 없다(실제로 없는 값이지 못 채운 값이 아니다).
    op.execute(
        "ALTER TABLE product_supplier_prices ADD COLUMN IF NOT EXISTS mall_rank SMALLINT")
    op.execute(
        "ALTER TABLE product_supplier_prices ADD COLUMN IF NOT EXISTS rebate_pct NUMERIC(6,3)")
    op.execute(
        "ALTER TABLE product_supplier_prices ADD COLUMN IF NOT EXISTS rebate_price BIGINT")
    op.execute(
        "ALTER TABLE product_supplier_prices ADD COLUMN IF NOT EXISTS order_price BIGINT")
    op.execute(
        "ALTER TABLE product_supplier_prices ADD COLUMN IF NOT EXISTS mall_state_raw VARCHAR(10)")
    op.execute(
        "ALTER TABLE product_supplier_prices ADD COLUMN IF NOT EXISTS fetched_at TIMESTAMP")


def downgrade() -> None:
    # 컬럼은 남긴다 — 지우면 몰에서 받은 순위·리베이트·연락처가 함께 사라지고
    # 되돌릴 수 없다(0025·사양 항목 컬럼과 같은 규칙). downgrade는 no-op.
    pass
