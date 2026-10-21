"""0169 — 9월 25일 이후 몰에 새로 올라온 완제PC 111개를 팝콘AI 판매 목록에 넣는다 (2026-10-21 대표 「추가해」).

■ 왜
  고객 화면(/mvp4) 판매 목록은 `product_fit_products`(0115 · 2026-09-25 몰 212개로 한 번 만든 표)와
  `products`(판매중)를 함께 본다. 그 뒤 몰에 올라온 130569~130679(「다중카메라 편집 PC 권장」 같은
  용도 이름 상품)는 두 표 어디에도 없어 고객 화면에 안 보였다(2026-10-21 몰 323개 · 팝콘AI 211개 대조).

■ 무엇을 넣나 — 데이터 db/migrations/data/new_builtpc_20261021.json
  products            몰 공개 상품 페이지 값: 상품명 · 판매가 · 시중가 · 부품 구성 원문
                      (spec_source_text — 몰 엑셀과 같은 「슬롯@@값 ,@@」 모양, 몰 등록 구성 표가 읽는다)
  product_fit_products · product_usage_fit
                      `tools/product_fit.py` 로 매긴 용도 평가(기준표는 0115 와 같다 — 바꾸지 않았다)
  이미 있는 상품번호는 건드리지 않는다(ON CONFLICT DO NOTHING) — 몰 엑셀 적재가 먼저 넣었으면 그 값을 둔다.

■ 가격
  판매가는 몰 페이지 값으로 넣고, 그 뒤로는 쇼핑몰 가격 자동 갱신(하루 2번)이 따라간다.
"""
import json
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0169"
down_revision = "0168"
branch_labels = None
depends_on = None

DATA = Path(__file__).resolve().parents[1] / "data" / "new_builtpc_20261021.json"


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
            # 판매가 기준일 문구(api/admin_product_fit.price_basis)가 「10월 21일 기준 쇼핑몰 가격」이 되게
            conn.execute(sa.text(
                "INSERT INTO product_price_history (product_code, field, old_price, new_price, reason)"
                " VALUES (:c, 'sale', NULL, :sp, 'mall_price_page_20261021')"),
                {"c": p["code"], "sp": p["sale_price"]})
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
    # products 행은 남긴다 — 그 사이 주문·견적이 붙었을 수 있다. 판매 목록(평가 표)에서만 뺀다.
    d = json.loads(DATA.read_text(encoding="utf-8"))
    codes = [p["code"] for p in d["products"]]
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM product_fit_products WHERE product_code = ANY(:c) AND source = :s"),
                 {"c": codes, "s": d["source"]})
    conn.execute(sa.text("DELETE FROM product_price_history WHERE product_code = ANY(:c)"
                         " AND reason = 'mall_price_page_20261021'"), {"c": codes})
