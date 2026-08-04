"""관리자 대시보드 — 처리 대기·오늘 흐름·시스템 상태 실집계 (읽기 전용).

각 타일은 해당 화면의 실집계와 같은 기준을 쓴다(중복 정의 금지 — 기준이 갈리면 숫자가 갈린다):
  검수 대기 = product_reviews 대기 / 가격 검토 = 가격 검토 파생 조건(admin_price_review PENDING)
  입고 대기 = 재고 0(admin_stock 파생) / 환불 처리 = 활성 환불(admin_orders.ACTIVE_REFUND)
정직 표기(원천 부재 — 값 대신 '—'):
  ① 오늘 적재 = csv_import_jobs 0행(CSV 파이프라인 미구현 T0)
  ② AI 사용량 = api_cost_logs 0행(LLM 연동 보류 — 착수 시 실값)
  ③ 적용 중인 버전(마진·호환 규칙·추천 기준) = 버전 관리 미모델링
목업의 '매입 대기'(sourcing 원천 0행)는 **입고 대기**로, '주문 재전달 필요'(전달 상태 컬럼 없음)는
**환불 처리 대기**로 교체 — 실제로 운영자 판단이 필요한 것을 가리키게 한다.
"""
from fastapi import APIRouter
from sqlalchemy import text

from .timeutil import iso
from .admin_activity_logs import ACTION_LABELS, KIND_LABELS
from .db import engine
from .taxonomy import CORE_TYPES

router = APIRouter(prefix="/api/admin")

_PRICE_PENDING = ("p.sale_price IS NULL AND p.review_required_yn = false"
                  " AND NOT (p.locked_fields @> '[\"sale_price\"]'::jsonb)")


def pending_counts(conn) -> dict:
    """처리 대기 집계 — **대시보드와 작업 패널의 단일 원천**(슬라이스 61).

    같은 것을 두 번 세면 두 화면이 다른 수를 말한다. 여기 한 곳만 고친다.
    """
    one = lambda sql: conn.execute(text(sql)).scalar_one()      # noqa: E731
    return {
        "review": one("SELECT COUNT(*) FROM product_reviews WHERE review_status='대기'"),
        "price": one(f"SELECT COUNT(*) FROM products p WHERE {_PRICE_PENDING}"),
        # admin_stock._PENDING과 동일 조건 — 재고 0 ∨ 안전재고 미달(0004 safety_stock)
        "inbound": one("SELECT COUNT(*) FROM products"
                       " WHERE status NOT IN ('단종','삭제대기')"
                       " AND (stock_qty=0"
                       "      OR (safety_stock IS NOT NULL AND stock_qty < safety_stock))"),
        "refund": one("SELECT COUNT(*) FROM refunds"
                      " WHERE status IN ('접수','검토','수거·처리')"),
        # 카테고리 매핑(슬라이스 C) — 기존 임대 관리자는 미매핑 1,458건을 별도 화면에
        # 두고 방치했다. 여기서는 대시보드가 먼저 말한다.
        "unmapped": one("SELECT COUNT(*) FROM products WHERE category_id IS NULL"),
        "unclassified": one("SELECT COUNT(*) FROM products WHERE part_type='ETC'"),
    }


@router.get("/dashboard")
def dashboard():
    with engine.connect() as conn:
        one = lambda sql: conn.execute(text(sql)).scalar_one()
        pending = pending_counts(conn)
        pool_ok = one("SELECT COUNT(*) FROM v_recommendation_candidates WHERE stock_qty>0")
        # 부품 종류 목록은 taxonomy가 단일 원천(슬라이스 A) — 여기 SQL에 박아 두면
        # 종류가 늘 때 이 수만 조용히 뒤처진다.
        core = conn.execute(text(
            "SELECT COUNT(*) FROM products WHERE category_group='core_part'"
            " AND part_type = ANY(:core)"), {"core": list(CORE_TYPES)}).scalar_one()
        sess_today = one("SELECT COUNT(*) FROM consult_sessions WHERE created_at::date=CURRENT_DATE")
        sess_done = one("SELECT COUNT(*) FROM consult_sessions s WHERE created_at::date=CURRENT_DATE"
                        " AND EXISTS (SELECT 1 FROM quote_snapshots q WHERE q.session_id=s.session_id)")
        orders = conn.execute(text(
            "SELECT status, COUNT(*) FROM orders GROUP BY status")).all()
        import_rows = one("SELECT COUNT(*) FROM csv_import_jobs")
        ai_rows = one("SELECT COUNT(*) FROM api_cost_logs")
        logs = conn.execute(text(
            "SELECT l.action, l.target_kind, l.target_id, COALESCE(o.name,'—') AS operator,"
            " l.created_at FROM admin_operator_activity_logs l"
            " LEFT JOIN admin_operators o USING (operator_id)"
            " ORDER BY l.log_id DESC LIMIT 3")).mappings().all()

    order_map = dict(orders)
    active = sum(n for s, n in orders if s in ("결제완료", "조립중", "출고", "배송중"))
    return {
        "pending": pending,
        "flow": {
            "import_rows": None if import_rows == 0 else import_rows,   # 원천 0 → '—'
            "pool_ok": pool_ok, "pool_core": core,
            "pool_rate": round(pool_ok / core * 100, 1) if core else 0.0,
            "sessions_today": sess_today, "sessions_done": sess_done,
            "sessions_drop": sess_today - sess_done,
            "orders_total": sum(order_map.values()), "orders_active": active,
            "orders_by_status": [{"status": s, "count": n} for s, n in
                                 sorted(orders, key=lambda x: -x[1])],
        },
        "system": {
            "ai_cost": None if ai_rows == 0 else ai_rows,               # 원천 0 → '—'
            "versions": None,                                           # 버전 관리 미모델링
            "recent_logs": [{
                "operator": g["operator"],
                "kind": KIND_LABELS.get(g["target_kind"], g["target_kind"]),
                "action": ACTION_LABELS.get(g["action"], g["action"]),
                "target": g["target_id"], "at": iso(g["created_at"]),
            } for g in logs],
        },
        "note": ("오늘 적재·AI 사용량·적용 버전은 원천(CSV 적재 파이프라인·LLM 연동·버전 관리)이"
                 " 준비되면 실값으로 바뀝니다 · '매입 대기'는 입고 대기로, '주문 재전달'은"
                 " 환불 처리 대기로 교체했습니다(원천 부재)."),
    }


@router.get("/worklist")
def worklist():
    """작업 패널 — 어느 화면에서든 '지금 할 일'과 그 화면으로 가는 길(슬라이스 61).

    대시보드는 같은 것을 보여주지만 **보려면 대시보드로 돌아가야 한다.** 이 패널의
    값어치는 거기 있다 — 작업하던 화면을 떠나지 않고 확인하고 바로 이동한다.

    숫자는 `pending_counts` 하나에서 나온다(대시보드와 같은 원천). 화면이 세지 않는다.
    """
    with engine.connect() as conn:
        p = pending_counts(conn)
        # 검수는 전체보다 **판매중·재고 있는 것**이 실제 작업 목록이다(6,000건을 다
        # 훑을 수는 없다). admin_reviews의 sellable과 같은 기준.
        review_focus = conn.execute(text(
            "SELECT COUNT(*) FROM product_reviews r JOIN products p USING (product_code)"
            " WHERE r.review_status='대기' AND p.status='판매중' AND p.stock_qty > 0")).scalar_one()
        orders_wait = conn.execute(text(
            "SELECT COUNT(*) FROM orders WHERE status='결제완료'")).scalar_one()
        # 매입 견적 = 보낸 뒤 답을 기다리는 것(admin_sourcing과 같은 기준)
        sourcing_wait = conn.execute(text(
            "SELECT COUNT(*) FROM product_sourcing_quotes WHERE status='요청'")).scalar_one()
        # 단가표 = 공급사별 최신 파일 중 아직 다 반영하지 않은 것(price_import 화면과 같은 기준)
        price_files = conn.execute(text(
            "SELECT COUNT(*) FROM (SELECT DISTINCT ON (supplier_id) status"
            "   FROM supplier_price_files ORDER BY supplier_id, received_at DESC) t"
            " WHERE status IS DISTINCT FROM '반영 완료'")).scalar_one()
        pool = conn.execute(text(
            "SELECT COUNT(*) FROM v_recommendation_candidates"
            " WHERE stock_qty > 0")).scalar_one()

    items = [
        {"key": "review", "label": "상품 검수", "count": p["review"],
         "focus": review_focus, "focus_label": "판매중·재고 있는 것",
         "href": "review-queue.html", "hint": "사양이 비어 추천에서 빠진 상품"},
        {"key": "orders", "label": "주문 처리", "count": orders_wait,
         "focus": None, "focus_label": None,
         "href": "orders.html", "hint": "결제완료 — 조립 대기"},
        {"key": "price", "label": "가격 검토", "count": p["price"],
         "focus": None, "focus_label": None,
         "href": "price-review.html", "hint": "판매가가 없어 팔 수 없는 상품"},
        {"key": "inbound", "label": "재고 입고", "count": p["inbound"],
         "focus": None, "focus_label": None,
         "href": "stock-inbound.html", "hint": "재고 0 또는 안전재고 미달"},
        {"key": "refund", "label": "환불 처리", "count": p["refund"],
         "focus": None, "focus_label": None,
         "href": "refunds.html", "hint": "접수·검토·수거 중"},
        {"key": "price_import", "label": "단가표 반영", "count": price_files,
         "focus": None, "focus_label": None,
         "href": "price-import.html", "hint": "공급사 최신 파일 중 미반영"},
        {"key": "sourcing", "label": "매입 견적", "count": sourcing_wait,
         "focus": None, "focus_label": None,
         "href": "sourcing.html", "hint": "요청 후 회신 대기"},
        # 미매핑과 미분류는 **다른 일이다**: 미매핑은 카테고리가 아예 없는 것,
        # 미분류는 적재가 부품 종류를 못 정해 `미분류`에 들어간 것. 둘을 합치면
        # "0건"으로 보이는데 실제로는 5천 건이 쌓여 있을 수 있다(슬라이스 C 실제 상황).
        {"key": "category", "label": "카테고리 매핑", "count": p["unmapped"] + p["unclassified"],
         "focus": p["unclassified"], "focus_label": "미분류(부품 종류 미정)",
         "href": "category-mapping.html", "hint": "판매 분류가 없거나 미분류인 상품"},
    ]
    return {"items": items, "total": sum(i["count"] for i in items), "pool": pool}
