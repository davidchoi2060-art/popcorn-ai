# -*- coding: utf-8 -*-
"""0157 — 사무용 «기본» 단계의 램 기준을 8GB 에서 16GB 로 (2026-10-13 사장님 「R03은 16GB로 해」)

■ 왜
  상담 답 품질 비교 R03 「사무용 컴퓨터 50만원 정도로 맞출 수 있어요?」에서 우리 설명은 기준표대로
  「램 8GB」를 말했고 카드도 8GB 였다. 비교 판정은 「램 8GB 는 모순 · 16GB 가 보통 권장」으로 우리가 못하다고 봤다.
  사장님 결정: 사무용 기본도 16GB.

■ 무엇을 바꾸나 (세 군데가 같은 기준을 본다 -- 하나만 바꾸면 설명·카드·신규 PC 평가가 서로 어긋난다)
  1. product_fit_levels   사무용 기본 조건 문장 「램 8GB 이상」 -> 「램 16GB 이상」(상담 설명의 기준 줄)
  2. product_usage_fit    사무용 «기본»에 올라 있던 램 16GB 미만 상품 -> 단계 없음(rank 0),
                          막힌 이유 「램 16GB 미만(현재 N GB)」. 고객 카드는 이 표의 단계로 고른다(sold_reco).
  3. tools/product_fit.REQUIREMENTS (코드, 같은 PR) -- 신규 조립PC 평가(custom_pc_fit)와 다음 평가 실행.
  쾌적 단계(이미 16GB)는 그대로다. 상품 사양·가격은 건드리지 않는다.

■ 영향 (2026-10-13 개발 DB 실측)
  판매 중 사무용 «기본» 상품 중 램 8GB 16대가 사무용 추천에서 빠진다. 사무용 최저가 카드가
  595,700원(8GB) -> 740,300원(16GB)으로 오른다. 「사무용 50만원」은 예산 안 카드 없이
  「예산을 넘는 최저가」 참고 카드로 안내된다.

■ 되돌리기
  product_usage_fit 의 원래 값은 0115 가 실은 평가 자료(db/migrations/data/product_fit_20260925.json)에 있다 --
  그 자료에서 사무용 «기본»이었던 행만 원래 막힌 이유와 함께 되살린다.
"""
import json
from pathlib import Path

from alembic import op
import sqlalchemy as sa

revision = "0157"
down_revision = "0156"
branch_labels = None
depends_on = None

USAGE, LEVEL = "사무용", "기본"
OLD_COND, NEW_COND = "램 8GB 이상", "램 16GB 이상"
MIN_RAM = 16
DATA = Path(__file__).resolve().parents[1] / "data" / "product_fit_20260925.json"


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE product_fit_levels SET conditions = replace(conditions, :old, :new)"
        " WHERE usage = :u AND level = :l"),
        {"old": OLD_COND, "new": NEW_COND, "u": USAGE, "l": LEVEL})
    # 램을 읽은 상품만 -- 램 미확인(NULL)은 원래도 단계 없음이고 여기서 판단하지 않는다.
    conn.execute(sa.text(
        "UPDATE product_usage_fit u"
        " SET level = NULL, level_rank = 0,"
        "     blocked = jsonb_build_array(format('램 %sGB 미만(현재 %sGB)', CAST(:m AS int), f.spec->>'ram_gb'))"
        " FROM product_fit_products f"
        " WHERE f.product_code = u.product_code AND u.usage = :u AND u.level = :l"
        "   AND jsonb_typeof(f.spec->'ram_gb') = 'number' AND (f.spec->>'ram_gb')::numeric < :m"),
        {"u": USAGE, "l": LEVEL, "m": MIN_RAM})


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE product_fit_levels SET conditions = replace(conditions, :new, :old)"
        " WHERE usage = :u AND level = :l"),
        {"old": OLD_COND, "new": NEW_COND, "u": USAGE, "l": LEVEL})
    d = json.loads(DATA.read_text(encoding="utf-8"))
    for p in d["products"]:
        for f in p["fit"]:
            if f["usage"] != USAGE or f["level"] != LEVEL:
                continue
            ram = (p.get("spec") or {}).get("ram_gb")
            if not isinstance(ram, (int, float)) or ram >= MIN_RAM:
                continue
            conn.execute(sa.text(
                "UPDATE product_usage_fit SET level = :l, level_rank = 1, blocked = CAST(:b AS JSONB)"
                " WHERE product_code = :c AND usage = :u AND level_rank = 0"),
                {"l": LEVEL, "b": json.dumps(f["blocked"], ensure_ascii=False), "c": p["code"], "u": USAGE})
