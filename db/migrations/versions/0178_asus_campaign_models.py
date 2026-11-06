# -*- coding: utf-8 -*-
"""0178 — ASUS 기획전 3종 전용 표 + PR447 초깃값 (2026-11-06).

■ 왜 새 표인가: 3종은 확정 판매 상품이 아니다. products · sale_price · 추천 후보에 넣으면 기획 검토가가 판매가로
  읽힌다. 그래서 다른 표를 참조하는 것은 수정자(admin_operators)뿐이고 다른 표는 읽지도 쓰지도 않는다.
■ 다시 적용해도 안전: CREATE TABLE IF NOT EXISTS + INSERT ON CONFLICT DO NOTHING. 관리자가 고친 값을 덮어쓰지 않고
  빠진 모델만 채운다. 초깃값 = db/migrations/data/asus_campaign_models_20261106.json (PR447 asus-data.js 그대로).
■ 되돌리기: 관리자가 고친 행이 있으면 멈춘다(그 값은 이 표에만 있다). 수정 행이 없을 때만 표를 지운다.
"""
import json
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0178"
down_revision = "0177"
branch_labels = None
depends_on = None

DATA = Path(__file__).resolve().parents[1] / "data" / "asus_campaign_models_20261106.json"


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS asus_campaign_models (
      model_id          TEXT PRIMARY KEY CHECK (model_id IN ('business', 'video', 'local-ai')),
      plan_review_price INTEGER CHECK (plan_review_price IS NULL OR plan_review_price > 0),
      content           JSONB NOT NULL,
      version           INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
      origin            TEXT NOT NULL DEFAULT 'seed' CHECK (origin IN ('seed', 'admin')),
      updated_by        BIGINT REFERENCES admin_operators(operator_id),
      updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
    )""")
    op.execute("COMMENT ON TABLE asus_campaign_models IS "
               "'ASUS 기획전 3종 기획 자료 - 판매 상품 아님, plan_review_price 는 기획 검토가(ASUS 협의 전) - 0178'")
    models = json.loads(DATA.read_text(encoding="utf-8"))["models"]
    conn = op.get_bind()
    for model_id, row in models.items():
        conn.execute(sa.text(
            "INSERT INTO asus_campaign_models (model_id, plan_review_price, content)"
            " VALUES (:i, :p, CAST(:c AS JSONB)) ON CONFLICT (model_id) DO NOTHING"),
            {"i": model_id, "p": row["plan_review_price"], "c": json.dumps(row["content"], ensure_ascii=False)})


def downgrade() -> None:
    conn = op.get_bind()
    edited = conn.execute(sa.text("SELECT count(*) FROM asus_campaign_models WHERE origin <> 'seed'")).scalar()
    if edited:
        raise RuntimeError("asus_campaign_models has admin edits; export them before dropping the table")
    op.execute("DROP TABLE asus_campaign_models")
