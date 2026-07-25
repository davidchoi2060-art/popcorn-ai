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

from .admin_activity_logs import ACTION_LABELS, KIND_LABELS
from .db import engine

router = APIRouter(prefix="/api/admin")

_PRICE_PENDING = ("p.sale_price IS NULL AND p.review_required_yn = false"
                  " AND NOT (p.locked_fields @> '[\"sale_price\"]'::jsonb)")


@router.get("/dashboard")
def dashboard():
    with engine.connect() as conn:
        one = lambda sql: conn.execute(text(sql)).scalar_one()
        pending = {
            "review": one("SELECT COUNT(*) FROM product_reviews WHERE review_status='대기'"),
            "price": one(f"SELECT COUNT(*) FROM products p WHERE {_PRICE_PENDING}"),
            "inbound": one("SELECT COUNT(*) FROM products"
                           " WHERE stock_qty=0 AND status NOT IN ('단종','삭제대기')"),
            "refund": one("SELECT COUNT(*) FROM refunds"
                          " WHERE status IN ('접수','검토','수거·처리')"),
        }
        pool_ok = one("SELECT COUNT(*) FROM v_recommendation_candidates WHERE stock_qty>0")
        core = one("SELECT COUNT(*) FROM products WHERE category_group='core_part'"
                   " AND part_type = ANY(ARRAY['CPU','GPU','MB','RAM','SSD','HDD','POWER','CASE',"
                   "'COOLER_CPU_AIR','COOLER_CPU_AIO'])")
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
                "target": g["target_id"], "at": g["created_at"].isoformat(),
            } for g in logs],
        },
        "note": ("오늘 적재·AI 사용량·적용 버전은 원천(CSV 적재 파이프라인·LLM 연동·버전 관리)이"
                 " 준비되면 실값으로 바뀝니다 · '매입 대기'는 입고 대기로, '주문 재전달'은"
                 " 환불 처리 대기로 교체했습니다(원천 부재)."),
    }
