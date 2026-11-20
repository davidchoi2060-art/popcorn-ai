"""0180 — 11월 몰에 새로 올라온 완제PC 9개를 팝콘AI 판매 목록에 넣는다 (2026-11-20 사장님 「권장안대로」).

■ 왜
  고객 화면(/mvp4) 판매 목록·추천은 `product_fit_products` 와 `products`(판매중)를 함께 본다(0169 와 같은 이유).
  몰 판매중 조립PC 중 ASUS 스페셜 8개(130855·130856·131542~131547)와 오피스 NO.03 131676 이 두 표 어디에도 없었다
  (2026-11-20 운영 세션이 몰 관리자 목록·price API 와 대조).

■ 무엇을 넣나 — 데이터 db/migrations/data/new_builtpc_20261120.json
  `tools/mall_builtpc_fetch.py` 로 받은 공개 상세 페이지 값(상품명 · 판매가 · 시중가 · 기본 구성 부품 줄)을
  `tools/mall_new_builtpc_seed.py` 가 0169 와 같은 모양으로 바꾸고 `tools/product_fit.py` 로 용도를 매겼다(기준표 불변).
  평가는 상품명이 아니라 기본 구성 부품 줄로 했다 — 몰 상품명과 구성이 다른 상품이 있다(131545·131546·131547:
  이름은 32G/1TB, 구성은 64GB/2TB 등). 다른 점은 balance 에 적어 관리자 용도 매트릭스에서 보인다.
  이미 있는 상품번호는 건드리지 않는다(ON CONFLICT DO NOTHING) — 몰 엑셀 적재가 먼저 넣었으면 그 값을 둔다.

■ 가격
  판매가는 몰 페이지 값으로 넣고, 그 뒤로는 쇼핑몰 가격 자동 갱신이 따라간다.
"""
import json
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0180"
down_revision = "0179"
branch_labels = None
depends_on = None

DATA = Path(__file__).resolve().parents[1] / "data" / "new_builtpc_20261120.json"
PRICE_REASON = "mall_price_page_20261120"


def upgrade() -> None:
    d = json.loads(DATA.read_text(encoding="utf-8"))
    conn = op.get_bind()
    rank = {(r.usage, r.level): r.level_rank for r in conn.execute(sa.text(
        "SELECT usage, level, level_rank FROM product_fit_levels"))}
    for p in d["products"]:
        added = conn.execute(sa.text(
            "INSERT INTO products (product_code, product_name, maker, part_type, category_group, status,"
            " sale_price, market_price, spec_source_text, data_origin)"
            " VALUES (:c, :n, '팝콘PC', 'PC_COMPLETE', 'etc', '판매중', :sp, :mp, :sst, 'real')"
            " ON CONFLICT (product_code) DO NOTHING RETURNING product_code"),
            {"c": p["code"], "n": p["name"], "sp": p["sale_price"], "mp": p["market_price"],
             "sst": p["spec_source_text"]}).scalar()
        if added is not None:
            # 판매가 기준일 문구(api/admin_product_fit.price_basis)가 「11월 20일 기준 쇼핑몰 가격」이 되게
            conn.execute(sa.text(
                "INSERT INTO product_price_history (product_code, field, old_price, new_price, reason)"
                " VALUES (:c, 'sale', NULL, :sp, :r)"),
                {"c": p["code"], "sp": p["sale_price"], "r": PRICE_REASON})
        conn.execute(sa.text(
            "INSERT INTO product_fit_products (product_code, crawl_name, crawl_price, mall_url, excluded,"
            " includes, spec, balance, dominated_by, source, evaluated_at)"
            " VALUES (:c, :n, :p, :url, NULL, :inc, CAST(:sp AS JSONB), :bal, :dom, :src, :at)"
            " ON CONFLICT (product_code) DO NOTHING"),
            {"c": p["code"], "n": p["name"], "p": p["sale_price"], "url": p["url"], "inc": p["includes"],
             "sp": json.dumps(p["spec"], ensure_ascii=False), "bal": p["balance"], "dom": p["dominated_by"],
             "src": d["source"], "at": d["evaluated_at"]})
        for f in p["fit"]:
            conn.execute(sa.text(
                "INSERT INTO product_usage_fit (product_code, usage, level, level_rank, blocked)"
                " VALUES (:c, :u, :l, :r, CAST(:b AS JSONB)) ON CONFLICT (product_code, usage) DO NOTHING"),
                {"c": p["code"], "u": f["usage"], "l": f["level"], "r": rank.get((f["usage"], f["level"]), 0),
                 "b": json.dumps(f["blocked"], ensure_ascii=False)})


def downgrade() -> None:
    # products 행은 남긴다 — 그 사이 주문·견적·가격 갱신이 붙었을 수 있다. 판매 목록(평가 표)에서만 뺀다.
    d = json.loads(DATA.read_text(encoding="utf-8"))
    codes = [p["code"] for p in d["products"]]
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM product_fit_products WHERE product_code = ANY(:c) AND source = :s"),
                 {"c": codes, "s": d["source"]})
    conn.execute(sa.text("DELETE FROM product_price_history WHERE product_code = ANY(:c) AND reason = :r"),
                 {"c": codes, "r": PRICE_REASON})
