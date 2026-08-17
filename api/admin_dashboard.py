"""관리자 대시보드 — 처리 대기·오늘 흐름·시스템 상태 실집계 (읽기 전용).

각 타일은 해당 화면의 실집계와 같은 기준을 쓴다(중복 정의 금지 — 기준이 갈리면 숫자가 갈린다):
  검수 대기 = product_reviews 대기 / 가격 검토 = 가격 검토 파생 조건(admin_price_review PENDING)
  입고 대기 = admin_stock.pending_where() **를 부른다**(조건을 여기 다시 적지 않는다 —
             재고 0 ∨ 안전재고 미달, 보류분 제외) / 환불 처리 = 활성 환불(admin_orders.ACTIVE_REFUND)
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
# 입고 대기 조건은 **admin_stock 이 정본**이다(그 파일 §입고 대기 조건). 여기서 SQL 을 다시
# 적으면 보류(0056) 같은 조건 변경이 한쪽에만 들어가 세 화면이 다른 수를 말한다 —
# 실제로 2026-08-17 보류 도입 때 stock-inbound 만 15,724, 여기와 매입 견적은 15,725 였다.
# 순환 없음: admin_stock 은 admin_orders·admin_products·auth·db·timeutil 만 가져오고
# 그 어느 것도 이 모듈(또는 admin_sourcing)을 가져오지 않는다.
from .admin_stock import pending_where
from .db import engine
from .taxonomy import CORE_TYPES, PART_LABELS

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
        # 입고 대기 = admin_stock.pending_where() **그 자체**(조건을 여기 다시 적지 않는다).
        # 기본값 exclude — 보류(「지금 안 한다」)는 운영자의 할 일이 아니므로 빠진다.
        # ⚠ 별칭 `p` 고정이라 FROM 절에 별칭이 필요하다(예전엔 무별칭 FROM products 였다).
        "inbound": one(f"SELECT COUNT(*) FROM products p WHERE {pending_where()}"),
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


@router.get("/quote-quality")
def quote_quality():
    """견적 품질 — **AI 가 제 일을 하는가**(재구축 대시보드의 수요 축 · UX-34).

    기존 `/dashboard` 의 `sessions_today` 는 **오늘치**만 본다. 재구축 대시보드는
    **누적 성립률**을 중심 지표로 삼기로 했다 — "AI 제안이 얼마나 효율적인가"에
    가장 가까운 답이고, 도매꾹에도 Phoenix 에도 없는 우리만의 지표이기 때문이다.

    ■ 불성립은 **명시적으로 기록되지 않는다** — 근사임을 밝힌다
      세션은 있는데 스냅샷이 없는 것으로 센다. 그래서 **왜 못 냈는지**(어느 슬롯이
      비었나 · 어느 조건이 걸렸나)는 여기서 줄 수 없다. 그 축을 넣으려면
      `consult_sessions` 에 결과 컬럼이 필요하다. **화면이 이 한계를 먼저 말한다** —
      성립률만 보여주고 원인을 아는 척하면 그게 지어낸 근거다.

    ■ 재고 정합은 관계식으로 센다
      `stock_qty = SUM(qty_delta)` 는 회귀가 전 상품에서 지키는 불변식이다(슬라이스 98).
      여기서도 **같은 식**으로 센다 — 두 곳이 다른 식을 쓰면 두 수가 갈린다.
    """
    with engine.connect() as conn:
        one = lambda sql: conn.execute(text(sql)).scalar_one()
        sess = one("SELECT COUNT(*) FROM consult_sessions")
        done = one("SELECT COUNT(DISTINCT session_id) FROM quote_snapshots")
        modes = conn.execute(text(
            "SELECT mode, COUNT(*) FROM consult_sessions GROUP BY 1 ORDER BY 2 DESC")).all()
        tiers = conn.execute(text(
            "SELECT quote_type, COUNT(*) FROM quote_snapshots GROUP BY 1 ORDER BY 2 DESC")).all()
        # 상관 서브쿼리(상품 22,840건 × 매 행마다 stock_movements 전량 스캔)가
        # EXPLAIN ANALYZE 실측 13.7초 — quote-quality 응답 시간의 사실상 전부였다
        # (loops=22840짜리 SubPlan, stock_movements(product_code)에 인덱스 없음).
        # GROUP BY로 미리 한 번만 집계해 LEFT JOIN하면 같은 식·같은 결과를 20ms대로
        # 낸다(약 680배) — 인덱스 추가 없이 쿼리 형태만 바꿔 해결된다(실측 후 판단).
        # 결과가 한 건도 달라지면 안 된다 — 재고 정합 판정(불변식 stock_qty=SUM(qty_delta))이다.
        drift = one(
            "SELECT COUNT(*) FROM products p LEFT JOIN ("
            " SELECT product_code, SUM(qty_delta) AS total_delta"
            " FROM stock_movements GROUP BY product_code"
            " ) m ON m.product_code = p.product_code"
            " WHERE p.stock_qty <> COALESCE(m.total_delta, 0)")
        members = one("SELECT COUNT(*) FROM members")
        payments = one("SELECT COUNT(*) FROM payments")

    MODE_KO = {"guided": "가이드형", "chat": "대화형", "talk": "음성"}
    return {
        "sessions": sess,
        "quoted": done,
        "unquoted": sess - done,
        "rate": round(done / sess * 100, 1) if sess else 0.0,
        "modes": [{"key": m, "label": MODE_KO.get(m, m), "count": n} for m, n in modes],
        "tiers": [{"key": t, "count": n} for t, n in tiers],
        "stock_drift": drift,          # 0이어야 한다 — 아니면 원장 안 남기는 경로가 생긴 것
        "members": members,
        "payments": payments,
        "note": ("불성립은 별도로 기록되지 않아 **세션은 있는데 견적 스냅샷이 없는 것**으로"
                 " 셉니다. 그래서 왜 못 냈는지(빈 슬롯·걸린 조건)는 아직 알 수 없습니다 —"
                 " consult_sessions 에 결과 컬럼이 붙어야 답할 수 있습니다."),
    }


@router.get("/funnel")
def funnel():
    """고객 깔때기 — 접속 → 문의 → 성공 → S2 도달 → 장바구니 → 구매.

    ■ **방문자 키가 붙은 것만 센다** — 이게 이 집계의 전제다
      2026-08-09 이전 상담 3,885건에는 방문자 키가 없다. 소급해서 키를 만들면
      **없던 관계를 발명하는 것**이라(재고를 기초 재고로 기록한 것과 같은 규칙)
      NULL 로 두었다. 그래서 이 깔때기는 **키가 생긴 뒤 발생분**만 센다.
      화면이 그 사실을 먼저 말해야 한다 — 안 그러면 "상담이 3건뿐"으로 읽힌다.

    ■ 각 단계가 **앞 단계의 부분집합**이어야 깔때기다
      그래서 전부 `user_id` 로 센다. 모집단이 다른 수를 나란히 놓고 깔때기라 부르면
      **화면이 있지도 않은 관계를 주장**하게 된다.

    ■ ④ "끝까지 확인" = **S2 도달**(사용자 결정 2026-08-09)
      S2 는 견적 제안서다. 견적 스냅샷이 생기면 S2 가 그릴 것이 있다는 뜻이므로
      **스냅샷 존재로 판정**한다. 별도 페이지뷰 기록이 없기 때문이고,
      그래서 이건 **근사**다 — 화면이 그렇게 밝힌다.

    ■ ⑤ 장바구니는 **원천이 없다**
      `carts` 테이블 자체가 없다. 0 을 주지 않고 `null` 을 준다 —
      **0 은 "담은 사람이 없다"는 사실 주장이고, 우리는 그걸 모른다.**
    """
    with engine.connect() as conn:
        one = lambda sql: conn.execute(text(sql)).scalar_one()
        visitors = one("SELECT COUNT(*) FROM users WHERE anon_key NOT LIKE 'seed-%'")
        consulted = one("SELECT COUNT(DISTINCT user_id) FROM consult_sessions"
                        " WHERE user_id IS NOT NULL")
        quoted = one("SELECT COUNT(DISTINCT s.user_id) FROM consult_sessions s"
                     " WHERE s.user_id IS NOT NULL AND EXISTS"
                     " (SELECT 1 FROM quote_snapshots q WHERE q.session_id=s.session_id)")
        # ④ S2 도달 = 견적 스냅샷이 생긴 상담을 가진 방문자 (=③과 같은 집합).
        #    지금은 ③과 구분되지 않는다 — S2 페이지뷰 기록이 없기 때문이다.
        #    구분하려면 화면 도달 이벤트가 필요하고, 그건 별도 배관이다.
        reached_s2 = quoted
        ordered = one("SELECT COUNT(DISTINCT user_id) FROM orders WHERE user_id IS NOT NULL")
        members_linked = one("SELECT COUNT(*) FROM members WHERE user_id IS NOT NULL")

    def step(key, label, value, note=None):
        return {"key": key, "label": label, "value": value, "note": note}

    return {
        "steps": [
            step("visit", "접속(방문자)", visitors),
            step("consult", "AI 부품 문의", consulted),
            step("quote", "견적 성공", quoted),
            step("s2", "제안서(S2) 도달", reached_s2,
                 "지금은 「견적 성공」과 같은 집합입니다 — S2 화면 도달 기록이 따로 없습니다"),
            step("cart", "장바구니", None, "장바구니 테이블이 없습니다 — 원천 부재"),
            step("order", "구매 완료", ordered),
        ],
        "members_linked": members_linked,
        "since_note": ("방문자 키는 2026-08-09 에 붙였습니다. **그 이전 상담·주문은 키가 없어"
                       " 이 깔때기에 잡히지 않습니다** — 소급해서 키를 만들지 않았습니다."),
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

    # ETC 라벨은 taxonomy.PART_LABELS가 정본이다 — 여기 문자열로 박으면 라벨이
    # 바뀔 때 이 화면만 따로 남는다.
    etc_label = PART_LABELS["ETC"]
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
         "href": "stock-inbound.html",
         "hint": "재고 0 또는 안전재고 미달 (보류 제외)"},
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
         "focus": p["unclassified"], "focus_label": etc_label,
         "href": "category-mapping.html",
         "hint": f"판매 분류가 없거나 부품 종류가 {etc_label}인 상품"},
    ]
    return {"items": items, "total": sum(i["count"] for i in items), "pool": pool}
