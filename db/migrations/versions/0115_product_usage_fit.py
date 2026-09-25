# -*- coding: utf-8 -*-
"""0115 — 판매 상품 용도 적합성 (2026-09-25 재설계 3단계 · 사장님 「승인」 12:33 UTC)

■ 무엇인가
  격자 칸마다 조합을 «생성»하던 방식을 버리고(사장님 「기존거는 모두 무시하고」),
  이미 파는 몰 조립PC 를 용도별로 평가한 결과를 싣는다. 칸에는 상품을 «표시»만 한다.
  평가 도구 `tools/product_fit.py`, 검토 엑셀은 사장님이 12:33 승인.

■ 표 셋
  product_fit_levels    기준표 — 용도 x 단계(기본/쾌적/전문 · 게임은 캐주얼/FHD/QHD/4K),
                        작업 설명(프로그램·규모)과 조건 문장
  product_fit_products  평가한 몰 상품 — 수집가·평가 제외 사유·가격 포함 품목(모니터·윈도우)·
                        판독한 사양·구성 균형 메모·「더 싼 상위 호환」
  product_usage_fit     상품 x 용도 -> 도달 단계 + 다음 단계에서 막힌 이유

■ 가격은 여기 두지 않는다(수집가만 참고로 둔다)
  화면·API 는 `products.sale_price`·`products.status` 를 조인해 **현재값**을 쓴다.
  가격이 바뀌면 칸이 저절로 옮겨 가고, 품절이면 저절로 빠진다. products 에 없는 상품만
  수집가로 보이고 그 사실을 표시한다.

■ 기존 격자 표(grid_cells·grid_quotes·grid_budget_bands)는 건드리지 않는다 — 끄는 것은
  4단계(mvp2 전환)에서 따로 한다.
"""
import json
from pathlib import Path

from alembic import op
import sqlalchemy as sa

revision = "0115"
down_revision = "0114"
branch_labels = None
depends_on = None

DATA = Path(__file__).resolve().parents[1] / "data" / "product_fit_20260925.json"


def upgrade() -> None:
    op.execute("""
    CREATE TABLE product_fit_levels (
      usage       VARCHAR(30) NOT NULL,
      level       VARCHAR(10) NOT NULL,
      level_rank  SMALLINT NOT NULL,
      work        TEXT NOT NULL,
      conditions  TEXT NOT NULL,
      sort_order  INTEGER NOT NULL,
      PRIMARY KEY (usage, level)
    )""")
    op.execute("""
    CREATE TABLE product_fit_products (
      product_code  BIGINT PRIMARY KEY,
      crawl_name    TEXT NOT NULL,
      crawl_price   BIGINT,
      mall_url      TEXT,
      excluded      TEXT,
      includes      TEXT,
      spec          JSONB NOT NULL,
      balance       TEXT,
      dominated_by  BIGINT,
      source        TEXT NOT NULL,
      evaluated_at  DATE NOT NULL
    )""")
    op.execute("""
    CREATE TABLE product_usage_fit (
      product_code  BIGINT NOT NULL REFERENCES product_fit_products(product_code) ON DELETE CASCADE,
      usage         VARCHAR(30) NOT NULL,
      level         VARCHAR(10),
      level_rank    SMALLINT NOT NULL DEFAULT 0,
      blocked       JSONB NOT NULL DEFAULT '[]'::jsonb,
      PRIMARY KEY (product_code, usage)
    )""")

    d = json.loads(DATA.read_text(encoding="utf-8"))
    conn = op.get_bind()
    rank = {}
    for i, lv in enumerate(d["levels"]):
        rank[(lv["usage"], lv["level"])] = lv["rank"]
        conn.execute(sa.text(
            "INSERT INTO product_fit_levels (usage, level, level_rank, work, conditions, sort_order)"
            " VALUES (:u, :l, :r, :w, :c, :s)"),
            {"u": lv["usage"], "l": lv["level"], "r": lv["rank"], "w": lv["work"],
             "c": lv["conditions"], "s": i})
    for p in d["products"]:
        conn.execute(sa.text(
            "INSERT INTO product_fit_products (product_code, crawl_name, crawl_price, mall_url, excluded,"
            " includes, spec, balance, dominated_by, source, evaluated_at)"
            " VALUES (:c, :n, :p, :url, :ex, :inc, CAST(:sp AS JSONB), :bal, :dom, :src, :at)"),
            {"c": p["code"], "n": p["name"], "p": p["price"], "url": p["url"], "ex": p["excluded"],
             "inc": p["includes"], "sp": json.dumps(p["spec"], ensure_ascii=False), "bal": p["balance"],
             "dom": p["dominated_by"], "src": d["source"], "at": d["evaluated_at"]})
        for f in p["fit"]:
            conn.execute(sa.text(
                "INSERT INTO product_usage_fit (product_code, usage, level, level_rank, blocked)"
                " VALUES (:c, :u, :l, :r, CAST(:b AS JSONB))"),
                {"c": p["code"], "u": f["usage"], "l": f["level"],
                 "r": rank.get((f["usage"], f["level"]), 0),
                 "b": json.dumps(f["blocked"], ensure_ascii=False)})


def downgrade() -> None:
    op.execute("DROP TABLE product_usage_fit")
    op.execute("DROP TABLE product_fit_products")
    op.execute("DROP TABLE product_fit_levels")
