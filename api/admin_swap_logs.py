"""ADM-ANL-020 부품 교체 · 클릭 기록 (슬라이스 46).

**두 원천의 상태가 다르다 — 화면이 그것을 구분해야 한다.**
  · 교체 기록(`swap_event_logs`): 슬라이스 46부터 쌓인다. S3에서 고객이 부품을 바꾸면 기록된다.
  · 근거 클릭(`promo_click_logs`): **0행이고 쌓이는 경로가 없다.** 고객 화면이 클릭 이벤트를
    보내지 않기 때문이다. 0건을 '클릭이 없었다'로 보여주면 거짓이 된다 —
    `empty=true` + 사유를 내려 화면이 '원천 준비 중'으로 표기하게 한다(배지 3종 규약).

교체 집계가 말해주는 것: 추천이 어디서 자주 거부되는가. GPU를 자주 바꾼다면 GPU 선정 기준을,
POWER를 자주 올린다면 전원 여유 기준을 손봐야 한다는 신호다(추천 기준 설정 화면과 이어진다).
"""
from sqlalchemy import text

from fastapi import APIRouter

from .admin_products import PART_TYPE_LABELS
from .db import engine

router = APIRouter(prefix="/api/admin")

SLOT_KO = {"CPU": "CPU", "MB": "메인보드", "RAM": "메모리", "GPU": "그래픽카드",
           "CASE": "케이스", "COOLER": "CPU쿨러", "POWER": "파워", "SSD": "SSD"}


def _signal(delta, n) -> str:
    """교체 신호 해석 — 가격 방향이 무엇을 뜻하는지. 추측은 하지 않고 사실만 말한다."""
    if delta is None:
        return "가격 정보 없음"
    if delta > 0:
        return f"평균 {delta:,}원 상향 — 추천이 보수적이었을 수 있음"
    if delta < 0:
        return f"평균 {abs(delta):,}원 하향 — 예산 압박 신호"
    return "가격 변화 없음 — 취향·재고 사유"


@router.get("/swap-logs")
def swap_logs(limit: int = 100):
    limit = max(1, min(limit, 500))
    with engine.connect() as conn:
        total = conn.execute(text("SELECT count(*) FROM swap_event_logs")).scalar_one()

        pairs = conn.execute(text("""
            SELECT e.from_product, e.to_product, e.slot, count(*) AS n,
                   ROUND(AVG(e.price_delta))::int AS avg_delta,
                   f.product_name AS from_name, f.sku AS from_sku,
                   t.product_name AS to_name, t.sku AS to_sku
              FROM swap_event_logs e
              LEFT JOIN products f ON f.product_code = e.from_product
              LEFT JOIN products t ON t.product_code = e.to_product
             GROUP BY e.from_product, e.to_product, e.slot,
                      f.product_name, f.sku, t.product_name, t.sku
             ORDER BY n DESC, e.slot
             LIMIT :lim
        """), {"lim": limit}).mappings().all()

        by_slot = conn.execute(text("""
            SELECT slot, count(*) n, ROUND(AVG(price_delta))::int avg_delta
              FROM swap_event_logs WHERE slot IS NOT NULL
             GROUP BY slot ORDER BY n DESC
        """)).mappings().all()

        recent = conn.execute(text("""
            SELECT e.log_id, e.slot, e.price_delta, e.created_at, e.session_id,
                   f.sku AS from_sku, t.sku AS to_sku,
                   f.product_name AS from_name, t.product_name AS to_name
              FROM swap_event_logs e
              LEFT JOIN products f ON f.product_code = e.from_product
              LEFT JOIN products t ON t.product_code = e.to_product
             ORDER BY e.log_id DESC LIMIT 20
        """)).mappings().all()

        clicks = conn.execute(text("SELECT count(*) FROM promo_click_logs")).scalar_one()

    return {
        "total": total,
        "pairs": [{
            "slot": p["slot"], "slot_label": SLOT_KO.get(p["slot"], p["slot"] or "—"),
            "from_sku": p["from_sku"], "from_name": p["from_name"],
            "to_sku": p["to_sku"], "to_name": p["to_name"],
            "n": p["n"], "pct": round(p["n"] * 100 / total) if total else 0,
            "avg_delta": p["avg_delta"], "signal": _signal(p["avg_delta"], p["n"]),
        } for p in pairs],
        "by_slot": [{
            "slot": s["slot"], "label": SLOT_KO.get(s["slot"], s["slot"]),
            "n": s["n"], "pct": round(s["n"] * 100 / total) if total else 0,
            "avg_delta": s["avg_delta"],
        } for s in by_slot],
        "recent": [{
            "log_id": r["log_id"], "slot": r["slot"],
            "slot_label": SLOT_KO.get(r["slot"], r["slot"] or "—"),
            "from_sku": r["from_sku"], "to_sku": r["to_sku"],
            "from_name": r["from_name"], "to_name": r["to_name"],
            "delta": r["price_delta"], "session_id": r["session_id"],
            "at": r["created_at"].isoformat(),
        } for r in recent],
        # 클릭 원천은 상태가 다르다 — 0을 성과처럼 보여주지 않는다(배지 3종 규약)
        "clicks": {
            "empty": clicks == 0, "count": clicks,
            "reason": ("근거 리포트 클릭을 기록하는 경로가 아직 없습니다 — 고객 화면(S2)이"
                       " 클릭 이벤트를 보내지 않습니다. 0건이 아니라 '측정하지 않음'입니다."),
        },
        "note": ("교체 기록은 슬라이스 46부터 쌓입니다(그 전 교체는 기록이 없습니다)."
                 " 어느 슬롯을 자주 바꾸는지가 추천 기준을 고칠 신호입니다 —"
                 " GPU가 잦으면 GPU 선정 기준, POWER가 잦으면 전원 여유 기준을 봅니다."),
    }
