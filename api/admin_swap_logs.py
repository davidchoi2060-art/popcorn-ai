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

        # 근거 클릭 — 슬라이스 49부터 S2 부품 행 클릭이 쌓인다(그 전은 기록 자체가 없다).
        # 자주 눌린 부품 = 설명만으로 납득이 안 된 부품. 추천 기준을 손볼 지점이다.
        clicks = conn.execute(text("SELECT count(*) FROM promo_click_logs")).scalar_one()
        click_ident = conn.execute(text(
            "SELECT count(*) FROM promo_click_logs WHERE user_id IS NOT NULL")).scalar_one()
        click_top = conn.execute(text("""
            SELECT c.product_code, p.sku, p.product_name, p.part_type, count(*) n
              FROM promo_click_logs c LEFT JOIN products p USING (product_code)
             GROUP BY 1, 2, 3, 4 ORDER BY n DESC, 1 LIMIT 10
        """)).mappings().all()

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
        # 수집 경로는 슬라이스 49에서 생겼다. 그래도 0건이면 '측정값 0'이 아니라
        # '아직 아무도 누르지 않음'이다 — 둘을 같은 말로 보여주지 않는다(배지 3종 규약).
        "clicks": {
            "empty": clicks == 0, "count": clicks,
            # user_id는 회원이 아니라 **익명 방문자 키**다(FK: users). 로그인해도 방문자 키가
            # 없으면 식별되지 않으므로 '게스트'라고 부르면 거짓이 된다 — '식별 없음'이다.
            "identified": click_ident,
            "unidentified": clicks - click_ident,
            "top": [{
                "product_code": c["product_code"], "sku": c["sku"], "name": c["product_name"],
                "part_type": c["part_type"],
                "label": PART_TYPE_LABELS.get(c["part_type"], c["part_type"] or "—"),
                "n": c["n"],
            } for c in click_top],
            "reason": ("아직 근거를 눌러본 고객이 없습니다 — 수집 경로는 열려 있습니다"
                       "(S2 부품 행 클릭 → /api/promo-click). 0건이 곧 '관심 없음'은 아닙니다."
                       if clicks == 0 else
                       f"S2에서 근거를 확인하려 누른 {clicks:,}건입니다"
                       f"(방문자 식별 {click_ident:,} · 식별 없음 {clicks - click_ident:,})."
                       " 자주 눌린 부품은 설명만으로 납득되지 않은 부품입니다."
                       " 누가 눌렀는지는 방문자 키가 있을 때만 남습니다 — 회원 ID는 담지 않습니다."),
        },
        "note": ("교체 기록은 슬라이스 46부터 쌓입니다(그 전 교체는 기록이 없습니다)."
                 " 어느 슬롯을 자주 바꾸는지가 추천 기준을 고칠 신호입니다 —"
                 " GPU가 잦으면 GPU 선정 기준, POWER가 잦으면 전원 여유 기준을 봅니다."),
    }
