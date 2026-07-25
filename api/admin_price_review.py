"""ADM-PRC-010 가격 검토 대기 — 판매가 제안 + 운영자 승인 (ERD §6.2).

ERD §6.2: "판매가 재계산은 제안+승인 — 운영자 승인 시에만 sale_price 반영,
history(reason='margin_policy'). 자동 집행하지 않는다 — 가격 결정권은 운영자에게 있다."

목록 = 파생(가격 검토 대기 테이블 없음):
  sale_price IS NULL ∧ review_required=false ∧ 'sale_price' NOT IN locked_fields
  → **v1은 '첫 산정' 유형만 실데이터.** ±15% 매입가 임계 유형은 purchase 이력 의존(현 DB 희소),
  마진 위반 유형은 **스키마 원천 부재**(category_margin_policies에 최소 마진율·끝자리·정책 버전
  컬럼 없음) — 응답 note로 정직 표기하고 이관. 검수 미통과 상품은 검수 큐 소관이라 제외.
제안가 = purchase × (1 + card_fee + margin) 천원 half-up (pricing_settings 실값 —
현행 2.2% + 0%라 목업의 마진 12~19% 연출과 달리 실제 ~2.1%로 표기된다).
액션 3종은 모두 지속 처리(목록이 파생이므로 재등장 방지):
  approve = _reprice(reason='margin_policy') 재사용(정본 경로 — 매입가 재판정 동반.
            공급처가 여럿인 상품은 purchase도 최저가로 재판정될 수 있음)
  keep    = locked_fields에 'sale_price' 등록(ERD §6.3 "locked면 제안만·정책 변경 차단")
  manual  = 입력값 반영 + history(reason='manual') + 잠금(product-edit "직접 수정 = 운영자
            확정 → 잠금" 서사 승계). 천원 단위 강제 없음(운영자 판단 존중).
undo 없음 = 목업 스펙(price-review에 되돌리기 UI 부재) — before는 로그 detail에 감사 기록만.
"""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from .admin_orders import OPERATOR_ID, _log
from .admin_price_import import _half_up_1000, _reprice, _settings
from .admin_products import PART_TYPE_LABELS
from .db import engine

router = APIRouter(prefix="/api/admin")

PENDING = ("p.sale_price IS NULL AND p.review_required_yn = false"
           " AND NOT (p.locked_fields @> '[\"sale_price\"]'::jsonb)")
NOTE = ("v1은 '첫 산정'(판매가 미산정) 유형만 실데이터입니다 — 매입가 ±15% 임계·마진 정책 위반"
        " 유형은 원천(매입가 이력·마진 정책 컬럼)이 준비되면 합류합니다.")


def _rows(conn):
    return conn.execute(text(
        "SELECT p.product_code, p.sku, p.product_name, p.part_type, p.purchase_price,"
        " p.sale_price, s.name AS supplier, psp.cost_price"
        " FROM products p"
        " LEFT JOIN (SELECT DISTINCT ON (product_code) product_code, supplier_id, cost_price"
        "            FROM product_supplier_prices ORDER BY product_code, cost_price) psp"
        "       USING (product_code)"
        " LEFT JOIN suppliers s USING (supplier_id)"
        f" WHERE {PENDING} ORDER BY p.product_code")).mappings().all()


@router.get("/price-review")
def price_review():
    with engine.connect() as conn:
        fee, margin = _settings(conn)
        rows = _rows(conn)
    items = []
    for r in rows:
        purchase = r["purchase_price"] or r["cost_price"] or 0
        proposed = _half_up_1000(purchase * (1 + fee + margin)) if purchase else None
        items.append({
            "product_code": r["product_code"], "sku": r["sku"], "name": r["product_name"],
            "cat": PART_TYPE_LABELS.get(r["part_type"], r["part_type"]),
            "supplier": r["supplier"] or "—",
            "purchase": purchase or None, "current": r["sale_price"], "proposed": proposed,
            "margin_pct": round((proposed - purchase) / purchase * 100, 1)
                          if (purchase and proposed) else None,
            "kind": "first",  # 첫 산정 — v1 유일 유형
            "why": "첫 산정 — 판매가 미정",
        })
    return {"items": items, "fee_rate": fee, "margin_rate": margin, "note": NOTE}


class DecideBody(BaseModel):
    action: str            # approve | keep | manual
    price: int | None = None   # manual 전용


@router.post("/price-review/{product_code}/decide")
def decide(product_code: int, body: DecideBody):
    if body.action not in ("approve", "keep", "manual"):
        raise HTTPException(400, f"알 수 없는 액션: {body.action}")
    if body.action == "manual" and not (body.price and body.price > 0):
        raise HTTPException(400, "직접 수정에는 0보다 큰 판매가가 필요합니다")
    with engine.begin() as conn:
        p = conn.execute(text(
            "SELECT product_code, sku, purchase_price, sale_price, locked_fields"
            f" FROM products p WHERE product_code=:pc AND {PENDING} FOR UPDATE"),
            {"pc": product_code}).mappings().first()
        if p is None:
            raise HTTPException(400, "가격 검토 대기 대상이 아닙니다(판매가 산정·잠금·검수 대기 확인)")
        fee, margin = _settings(conn)
        before = {"sale_price": p["sale_price"], "purchase_price": p["purchase_price"],
                  "locked_fields": p["locked_fields"] or []}
        log_id = _log(conn, "price_review_decide", p["sku"],
                      {"product_code": product_code, "sku": p["sku"], "action": body.action,
                       "before": before, "price": body.price}, kind="product")
        applied = None
        if body.action == "approve":
            rp = _reprice(conn, product_code, fee, margin, "margin_policy", log_id)
            applied = conn.execute(text(
                "SELECT sale_price FROM products WHERE product_code=:pc"),
                {"pc": product_code}).scalar()
            result = {"sale_price": applied, "purchase_changed": rp["purchase_changed"]}
        else:
            locked = list(before["locked_fields"])
            if "sale_price" not in locked:
                locked.append("sale_price")
            if body.action == "manual":
                conn.execute(text(
                    "UPDATE products SET sale_price=:v, locked_fields=CAST(:lf AS JSONB),"
                    " updated_at=now() WHERE product_code=:pc"),
                    {"v": body.price, "lf": json.dumps(locked), "pc": product_code})
                conn.execute(text(
                    "INSERT INTO product_price_history"
                    " (product_code, field, old_price, new_price, reason, ref_id, changed_by)"
                    " VALUES (:pc, 'sale', :o, :n, 'manual', :ref, :op)"),
                    {"pc": product_code, "o": p["sale_price"], "n": body.price,
                     "ref": log_id, "op": OPERATOR_ID})
                applied = body.price
            else:  # keep — 판매가 미산정 유지 + 제안 차단(잠금)
                conn.execute(text(
                    "UPDATE products SET locked_fields=CAST(:lf AS JSONB), updated_at=now()"
                    " WHERE product_code=:pc"), {"lf": json.dumps(locked), "pc": product_code})
            result = {"sale_price": applied, "locked": True}
        return {"ok": True, "log_id": log_id, "action": body.action, **result}
