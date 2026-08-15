# -*- coding: utf-8 -*-
"""product_price_history.new_price — NOT NULL 해제 ("지움"도 가격 변경이다).

■ 무엇이 깨져 있었나 — 확인자 실측(2026-08-15, 데모 상품 93720 · 원복 완료)
  ① PATCH {"sale_price": 16501}  -> 정상: history_id 29019, old=16500 new=16501.
  ② PATCH {"sale_price": ""}     -> **"changed:1" 성공 응답**, products.sale_price는
     정상적으로 NULL이 됐는데 **product_price_history에는 행이 0개**.
  ③ 그 시점에 「가격 원장 드리프트」(tests/regression.py, products.{field} 현재값 vs
     이 표의 마지막 new_price 불일치 건수)가 2건 -> 3건으로 늘어나는 것을 직접
     만들어 확인.
  ④ undo로 원복하자 드리프트가 다시 2건으로 줄었다.

  원인은 `api/admin_products.py`의 두 자리(patch_product · undo_product_edit)가
  "new_price는 NOT NULL이니 값을 지우는 패치는 이 표에 못 담는다"고 **의도적으로**
  건너뛰고 있었던 것 — 주석에도 그렇게 적혀 있었다. 그런데 "값이 없어졌다"도
  가격 변경이다. 건너뛰면 운영자가 가격 이력 화면에서 마지막 기록(예: "16,501원")을
  보고 그게 지금 가격이라 믿게 되는데, 실제로는 판매가가 비어 있다 — ERD §6 원칙 3
  ("모든 가격 변경은 reason·ref_id와 함께 기록한다")이 깨지는 사례다.
  ERD 개정 = docs/06_db-erd.md §3.4·§6 (이 리비전과 같은 날, 같은 작업).

■ 왜 스키마를 고치나 — 대안(코드에서 자리표시 값을 넣는 것)을 기각한 이유
  0(원)이나 -1 같은 자리표시 값을 넣는 방법도 있었지만, 그러면 "정말 0원으로
  바꾼 것"과 "값을 지운 것"을 원장에서 구분할 수 없다("모르는 것을 지어내지
  않는다" — CANON). NULL을 그대로 허용하면 "값이 없음"을 원장이 그대로 말한다.

■ old_price는 손대지 않는다 — 이미 처음부터 NULL 허용이다
  `0001_initial_schema.py`부터 "old_price BIGINT,"이고 NOT NULL이 없다(ERD §3.4도
  동일). 이번 변경은 new_price 한 컬럼만 그 대칭에 맞추는 것이다.

■ 의존 코드 전수 확인(2026-08-15, grep 실측) — new_price가 NOT NULL이라 가정하고
  죽거나 값을 잘못 계산하는 자리는 찾지 못했다:
  · api/admin_price_history.py:125,127,136   이미 `new_price is None` 가드 있음
                                              (읽기 전용 — 이번 리비전 담당 밖, 손대지 않음)
  · api/admin_ui_sale_price.py:348-349       이미 동일한 None 가드 있음
  · api/catalog_ingest.py:417                `new = raw_new if raw_new is not None else old`
                                              — NULL을 절대 넣지 않는다(다른 제작자 담당
                                              영역이라 이번 리비전에서 건드리지 않음)
  · tests/regression.py:4505                 `p.{col} IS DISTINCT FROM h.new_price` —
                                              NULL과 NULL을 이미 "다르지 않음"으로 올바르게 처리
                                              (이 불변식이 이번 수정의 회귀 기준이 된다)
  · templates/admin/price_history.html.j2:336,590  `won()`·차트 max 계산 모두 `== null`
                                              가드 있음(다른 제작자가 그 화면을 만지는 중이라
                                              읽기만 하고 손대지 않음)

Revision ID: 0050
Revises: 0049
"""
from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # DROP NOT NULL은 기존 행에 안전하다 — 지금 있는 행은 전부 new_price가 채워져
    # 있으므로 그대로 남고, 앞으로 들어올 새 행만 NULL을 쓸 수 있게 된다.
    # (PostgreSQL은 이 변경에 테이블 재작성이 필요 없다 — 카탈로그만 갱신)
    op.execute(
        "ALTER TABLE product_price_history ALTER COLUMN new_price DROP NOT NULL"
    )


def downgrade() -> None:
    # ⚠ 데이터를 잃게 만들지 않는다. NULL 행을 0이나 다른 값으로 지어내 채우고
    # SET NOT NULL을 강행하지 않는다("모르는 것을 지어내지 않는다" — CANON).
    #
    # 이 업그레이드 이후 실제로 new_price가 NULL인 행이 하나라도 쌓였다면(가격을
    # 지운 변경이 이번 수정으로 정상 기록된 것 — 의도된 결과다), 아래 SET NOT NULL은
    # PostgreSQL이 "column contains null values"로 **실패한다.** 이것은 의도된
    # 실패다 — 그 NULL 행 자체가 "그 시점에 가격이 지워졌다"는 원장 사실이므로,
    # downgrade 한 줄이 그 사실을 자동으로 지우거나 값을 지어내 메우면 안 된다.
    # 이 revision을 되돌려야 한다면, 먼저 사람이 그 NULL 행들을 어떻게 할지
    # (예: 마지막 비-NULL 값으로 되돌릴지, 그대로 둘지) 판단해야 한다 — 그 판단은
    # 이 downgrade 함수의 책임 밖이다.
    op.execute(
        "ALTER TABLE product_price_history ALTER COLUMN new_price SET NOT NULL"
    )
