# -*- coding: utf-8 -*-
"""0172 — 승인 구성이 없는 판매 PC 의 상세 소개(「ABOUT THIS PC」) 표 (2026-10-21 대표 「진행해」 · 「DB화 하는거지?」)

■ 왜
  /mvp4 상세 하단 소개는 승인 구성(pc_configurations.content)이 있는 82대에만 있었다(판매 PC 322대 중 · 2026-10-21 실측).
  몰 등록 구성만 있는 240대는 소개 자료가 없어 구획이 빠졌다. 화면 코드에 박지 않고 DB 에 두어 관리자가 고친다.

■ 무엇을 넣나
  pc_registered_about   상품마다 소개 한 벌(content: title·intro·benefits·scene) · origin auto|admin
                        content 는 api/registered_about.build — 몰 상품명 [CPU/메모리/SSD/그래픽](대표: 제목이 기준)과
                        용도 평가(product_usage_fit · product_fit_levels.work)만 옮긴다. 새 사실을 만들지 않는다.
  채우기                product_fit_products 의 완제PC 전부(승인 구성이 있는 상품도 — 상세는 승인 구성 소개를 먼저 쓴다).
                        이미 있는 행은 건드리지 않는다(관리자가 고친 값을 지킨다).

■ 번호
  같은 날 0170·0171(몰 부품)이 먼저 병합돼 그 뒤에 잇는다(head 가 둘이면 배포의 `alembic upgrade head` 가 멈춘다).
"""
import json
import sys
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0172"
down_revision = "0171"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE pc_registered_about (
      product_code BIGINT PRIMARY KEY REFERENCES products(product_code),
      content      JSONB NOT NULL,
      origin       TEXT NOT NULL DEFAULT 'auto' CHECK (origin IN ('auto', 'admin')),
      history      JSONB NOT NULL DEFAULT '[]'::jsonb,
      updated_by   BIGINT REFERENCES admin_operators(operator_id),
      updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
    )""")
    op.execute("COMMENT ON TABLE pc_registered_about IS "
               "'승인 구성이 없는 판매 PC 의 상세 소개(ABOUT THIS PC) - 0172 · api/registered_about'")
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from api.registered_about import build   # noqa: E402  (단일 원천 — 읽을 때 만들기와 같은 함수)
    conn = op.get_bind()
    works = {(r.usage, r.level): r.work for r in conn.execute(sa.text("SELECT usage, level, work FROM product_fit_levels"))}
    order = {(r.usage, r.level): r.sort_order for r in conn.execute(sa.text("SELECT usage, level, sort_order FROM product_fit_levels"))}
    fits = {}
    for r in conn.execute(sa.text("SELECT product_code, usage, level, level_rank FROM product_usage_fit")):
        fits.setdefault(r.product_code, []).append(
            {"usage": r.usage, "level": r.level, "rank": r.level_rank, "work": works.get((r.usage, r.level)),
             "_o": order.get((r.usage, r.level), 999)})
    rows = conn.execute(sa.text(
        "SELECT f.product_code, f.crawl_name, f.spec, p.product_name FROM product_fit_products f"
        " JOIN products p ON p.product_code = f.product_code WHERE p.part_type = 'PC_COMPLETE'")).all()
    for r in rows:
        fs = [{k: v for k, v in x.items() if k != "_o"} for x in sorted(fits.get(r.product_code, []), key=lambda x: x["_o"])]
        content = build(r.crawl_name or r.product_name, r.spec, fs)
        if content:
            conn.execute(sa.text(
                "INSERT INTO pc_registered_about (product_code, content) VALUES (:c, CAST(:j AS JSONB))"
                " ON CONFLICT (product_code) DO NOTHING"),
                {"c": r.product_code, "j": json.dumps(content, ensure_ascii=False)})


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pc_registered_about")
