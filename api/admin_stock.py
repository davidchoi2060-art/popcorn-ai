"""ADM-SRC-020 재고 입고 — 입출고 원장 쓰기 (ERD §8 T10, 3중 게이트의 마지막).

원장 계약(ERD §10.6): 입고 = stock_movements(inbound|adjust, qty_delta +) + products.stock_qty 증가.
**단가는 원장 밖** — stock_movements에 단가 컬럼이 없다(product_code·movement_type·qty_delta·
ref_kind·ref_id·created_at). 따라서 입고로 매입가를 바꾸지 않는다(매입가 갱신은 단가표
ADM-PRC-040·매입 견적 ADM-SRC-010 소관). 화면 매입가는 참조 표시.
품절 복귀: 입고로 재고>0이 되면 status='품절'→'판매중'(재고 없음이 품절의 사유였으므로).
'단종'·'삭제대기'는 건드리지 않는다.
undo = **역방향 원장 행**(adjust, -qty) — 원장은 삭제하지 않는다(order_events 전례).
pool_entered는 추측하지 않고 v_recommendation_candidates 실측으로 판정 — 재고만 열려도
검수·가격이 미완이면 false(3중 게이트).
목록 = 파생(stock_qty=0 ∧ status NOT IN 단종·삭제대기). 안전재고 미달 유형은 기준 컬럼이
없어 LIVE 제외(목업 연출 각주 유지 — 컬럼화 이관).
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from .admin_orders import _log
from .admin_products import PART_TYPE_LABELS
from .db import engine

router = APIRouter(prefix="/api/admin")

WHY = ("inbound", "adjust")
NOTE = ("입고 대기 = 재고 0 상품입니다. 안전재고 미달 유형은 기준 컬럼이 준비되면 합류합니다"
        " · 매입가 변경은 단가표·매입 견적 소관(입고 원장에는 단가를 남기지 않습니다).")

_PENDING = """
    SELECT p.product_code, p.sku, p.product_name, p.part_type, p.status, p.stock_qty,
           p.purchase_price, p.sale_price, p.review_required_yn, p.ai_candidate_yn,
           psp.cost_price, s.name AS supplier,
           EXISTS(SELECT 1 FROM product_specs sp WHERE sp.product_code = p.product_code) AS has_specs
    FROM products p
    LEFT JOIN (SELECT DISTINCT ON (product_code) product_code, supplier_id, cost_price
               FROM product_supplier_prices ORDER BY product_code, cost_price) psp
           USING (product_code)
    LEFT JOIN suppliers s USING (supplier_id)
    WHERE p.stock_qty = 0 AND p.status NOT IN ('단종','삭제대기')
    ORDER BY p.product_code
"""


def _in_pool(conn, pc: int) -> bool:
    return conn.execute(text(
        "SELECT 1 FROM v_recommendation_candidates WHERE product_code=:pc AND stock_qty>0"),
        {"pc": pc}).first() is not None


def _note_of(r) -> str:
    if r["review_required_yn"]:
        return "검수 미통과 — 입고해도 추천에 쓰이지 않습니다"
    if r["sale_price"] is None:
        return "판매가 미산정 — 가격 검토 후 추천 진입"
    if not r["has_specs"]:
        # 추천 뷰는 product_specs를 조인한다 — 사양 행이 없으면 재고·가격이 다 채워져도 미진입
        return "사양 미등록(specs 행 없음) — 재고만으로는 추천 진입 불가"
    if r["status"] == "품절":
        return "품절 표시 상태 — 입고 시 판매중으로 복귀하며 추천 진입"
    return "검수·가격 완료 — 입고 시 추천 가능 재고 진입"


@router.get("/stock-inbound")
def stock_inbound():
    with engine.connect() as conn:
        rows = conn.execute(text(_PENDING)).mappings().all()
        catalog = conn.execute(text(
            "SELECT product_code, sku, product_name, part_type, purchase_price, stock_qty,"
            " sale_price, review_required_yn"
            " FROM products WHERE status NOT IN ('단종','삭제대기') ORDER BY sku")).mappings().all()
    return {
        "items": [{
            "product_code": r["product_code"], "sku": r["sku"], "name": r["product_name"],
            "cat": PART_TYPE_LABELS.get(r["part_type"], r["part_type"]),
            "purchase": r["purchase_price"] or r["cost_price"],
            "supplier": r["supplier"] or "—", "stock": r["stock_qty"],
            "priced": r["sale_price"] is not None,
            "reviewed": not r["review_required_yn"],
            "has_specs": r["has_specs"],
            "status": r["status"], "why": "inbound", "note": _note_of(r),
        } for r in rows],
        "catalog": [{
            "product_code": c["product_code"], "sku": c["sku"], "name": c["product_name"],
            "cat": PART_TYPE_LABELS.get(c["part_type"], c["part_type"]),
            "purchase": c["purchase_price"], "stock": c["stock_qty"],
            "priced": c["sale_price"] is not None, "reviewed": not c["review_required_yn"],
        } for c in catalog],
        "note": NOTE,
    }


class InboundBody(BaseModel):
    qty: int
    why: str = "inbound"


@router.post("/stock-inbound/{product_code}")
def inbound(product_code: int, body: InboundBody):
    if body.why not in WHY:
        raise HTTPException(400, f"알 수 없는 사유: {body.why}")
    if body.qty <= 0:
        raise HTTPException(400, "입고 수량은 1 이상이어야 합니다")
    with engine.begin() as conn:
        p = conn.execute(text(
            "SELECT product_code, sku, stock_qty, status FROM products"
            " WHERE product_code=:pc FOR UPDATE"), {"pc": product_code}).mappings().first()
        if p is None:
            raise HTTPException(404, "상품이 없습니다")
        if p["status"] in ("단종", "삭제대기"):
            raise HTTPException(400, f"'{p['status']}' 상품에는 입고할 수 없습니다")
        before, status_changed = p["stock_qty"], False
        log_id = _log(conn, "stock_inbound", p["sku"],
                      {"product_code": product_code, "sku": p["sku"], "qty": body.qty,
                       "why": body.why, "before": {"stock_qty": before, "status": p["status"]}},
                      kind="stock")
        conn.execute(text(
            "INSERT INTO stock_movements (product_code, movement_type, qty_delta, ref_kind, ref_id)"
            " VALUES (:pc, :t, :q, 'manual', :ref)"),
            {"pc": product_code, "t": body.why, "q": body.qty, "ref": log_id})
        conn.execute(text(
            "UPDATE products SET stock_qty = stock_qty + :q, updated_at=now()"
            " WHERE product_code=:pc"), {"q": body.qty, "pc": product_code})
        if p["status"] == "품절":   # 재고가 들어왔으므로 품절 사유 소멸
            conn.execute(text(
                "UPDATE products SET status='판매중' WHERE product_code=:pc"), {"pc": product_code})
            status_changed = True
        return {"ok": True, "undo_id": log_id, "sku": p["sku"],
                "stock_before": before, "stock_after": before + body.qty,
                "status_changed": status_changed,
                "pool_entered": _in_pool(conn, product_code)}


@router.post("/stock-inbound/undo/{log_id}")
def undo_inbound(log_id: int):
    with engine.begin() as conn:
        log = conn.execute(text(
            "SELECT action, detail FROM admin_operator_activity_logs WHERE log_id=:i"),
            {"i": log_id}).mappings().first()
        if log is None or log["action"] != "stock_inbound":
            raise HTTPException(404, "되돌릴 입고 기록이 없습니다")
        if conn.execute(text(
                "SELECT 1 FROM admin_operator_activity_logs"
                " WHERE action='stock_inbound_undo' AND (detail->>'ref_log_id')::int=:i LIMIT 1"),
                {"i": log_id}).first():
            raise HTTPException(409, "이미 되돌린 입고입니다")
        d = log["detail"]
        p = conn.execute(text(
            "SELECT stock_qty, status FROM products WHERE product_code=:pc FOR UPDATE"),
            {"pc": d["product_code"]}).mappings().first()
        if p is None:
            raise HTTPException(404, "상품이 없습니다")
        if p["stock_qty"] < d["qty"]:
            raise HTTPException(409, "입고분보다 재고가 적습니다 — 이후 판매·조정이 있어 되돌릴 수 없습니다")
        # 원장은 삭제하지 않는다 — 역방향 행으로 상쇄(order_events 전례)
        conn.execute(text(
            "INSERT INTO stock_movements (product_code, movement_type, qty_delta, ref_kind, ref_id)"
            " VALUES (:pc, 'adjust', :q, 'manual', :ref)"),
            {"pc": d["product_code"], "q": -d["qty"], "ref": log_id})
        conn.execute(text(
            "UPDATE products SET stock_qty = stock_qty - :q, updated_at=now()"
            " WHERE product_code=:pc"), {"q": d["qty"], "pc": d["product_code"]})
        before = d.get("before") or {}
        if before.get("status") == "품절" and p["status"] == "판매중":
            conn.execute(text(
                "UPDATE products SET status='품절' WHERE product_code=:pc"),
                {"pc": d["product_code"]})
        _log(conn, "stock_inbound_undo", str(log_id),
             {"ref_log_id": log_id, "product_code": d["product_code"], "qty": d["qty"]},
             kind="stock")
        return {"ok": True, "sku": d.get("sku"), "stock_after": p["stock_qty"] - d["qty"]}
