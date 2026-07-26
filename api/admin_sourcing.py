"""ADM-SRC-010 매입 견적 — 안전재고 미달 자동 등록 → 견적 요청 → 회신 기록 → 매입 확정.

대기 목록은 **저장하지 않고 파생**한다(ERD §3.9): `stock_qty=0 ∨ stock_qty < safety_stock`.
별도 큐 테이블을 두면 재고가 변할 때마다 동기화해야 하고, 그 동기화가 곧 버그다.
저장하는 것은 **운영자가 실제로 한 행위**뿐 — 견적 요청(quote 생성)·회신 기록·확정.

정직 3건:
  ① **회신은 자동 수신이 아니라 운영자 대행 입력**이다(공급처 회신은 전화·메일로 온다).
     외부 연동이 없으므로 우리가 가짜 회신을 만들지 않는다.
  ② 견적 '요청 발송'도 실제 메일·API 전송이 아니라 **요청 기록**이다(발송 연동 이관).
  ③ 확정은 **가격 결정**이며 재고는 늘지 않는다 — 수량이 들어오는 사건은 입고(T10) 소관.
     확정 후 그 상품은 입고 대기(ADM-SRC-020)에 이미 있다(재고 미달 상태이므로).
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from .admin_orders import _log
from .auth import current_operator_id
from .admin_price_import import _reprice, _settings
from .admin_products import PART_TYPE_LABELS
from .db import engine

router = APIRouter(prefix="/api/admin")

# 대기 사유 파생 — 입고 화면(admin_stock)과 같은 조건을 쓴다(기준이 갈리면 숫자가 갈린다)
_PENDING = """
    SELECT p.product_code, p.sku, p.product_name, p.part_type, p.stock_qty, p.safety_stock,
           p.purchase_price
    FROM products p
    WHERE p.status NOT IN ('단종','삭제대기')
      AND (p.stock_qty = 0 OR (p.safety_stock IS NOT NULL AND p.stock_qty < p.safety_stock))
    ORDER BY p.stock_qty, p.product_code
"""


def _why(r) -> str:
    if r["stock_qty"] == 0:
        return "재고 0 — 자동 등록"
    return f"재고 {r['stock_qty']} → 안전재고 {r['safety_stock']} 미달 — 자동 등록"


@router.get("/sourcing")
def sourcing():
    with engine.connect() as conn:
        rows = conn.execute(text(_PENDING)).mappings().all()
        quotes = conn.execute(text(
            "SELECT q.quote_id, q.product_code, q.supplier_id, q.vendor, q.price, q.status,"
            " q.replied_at, q.memo, q.created_at, s.name AS supplier"
            " FROM product_sourcing_quotes q LEFT JOIN suppliers s USING (supplier_id)"
            " WHERE q.status IN ('요청','회신') ORDER BY q.quote_id")).mappings().all()
        sups = conn.execute(text(
            "SELECT supplier_id, name FROM suppliers ORDER BY supplier_id")).mappings().all()
        done = conn.execute(text(
            "SELECT COUNT(*) FROM product_sourcing_quotes"
            " WHERE status='확정' AND created_at::date = CURRENT_DATE")).scalar_one()
        # 최근 확정 — 확정해도 재고가 0이면 대기에 남으므로(가격 결정 ≠ 입고) 이력을 함께 보여준다
        confirmed = conn.execute(text(
            "SELECT DISTINCT ON (q.product_code) q.product_code, q.price, q.replied_at,"
            " s.name AS supplier FROM product_sourcing_quotes q"
            " LEFT JOIN suppliers s USING (supplier_id)"
            " WHERE q.status='확정' ORDER BY q.product_code, q.quote_id DESC")).mappings().all()
    last_fix = {c["product_code"]: {"price": c["price"], "supplier": c["supplier"]}
                for c in confirmed}

    by_pc: dict = {}
    for q in quotes:
        by_pc.setdefault(q["product_code"], []).append(q)

    items = []
    for r in rows:
        qs = by_pc.get(r["product_code"], [])
        replied = [q for q in qs if q["price"] is not None]
        best = min((q["price"] for q in replied), default=None)
        state = "req" if not qs else ("reply" if replied else "wait")
        items.append({
            "product_code": r["product_code"], "sku": r["sku"], "name": r["product_name"],
            "cat": PART_TYPE_LABELS.get(r["part_type"], r["part_type"]),
            "stock": r["stock_qty"], "safety_stock": r["safety_stock"],
            "purchase": r["purchase_price"], "why": _why(r), "state": state,
            "last_fix": last_fix.get(r["product_code"]),   # 매입 확정됨 — 입고만 남음
            "quotes": [{
                "quote_id": q["quote_id"], "supplier_id": q["supplier_id"],
                "supplier": q["supplier"] or q["vendor"] or "—",
                "price": q["price"], "status": q["status"],
                "replied_at": q["replied_at"].isoformat() if q["replied_at"] else None,
                "memo": q["memo"], "best": q["price"] is not None and q["price"] == best,
            } for q in qs],
        })
    return {"items": items, "done_today": done,
            "suppliers": [{"id": s["supplier_id"], "name": s["name"]} for s in sups],
            "note": ("대기 목록은 재고·안전재고에서 파생합니다(별도 큐 테이블 없음) ·"
                     " 견적 요청·회신은 **기록**이며 실제 발송·자동 수신 연동은 준비 중입니다"
                     " — 공급처 회신은 운영자가 대행 입력합니다 ·"
                     " 확정은 가격 결정이며 재고는 입고 화면에서 늘어납니다.")}


class RequestBody(BaseModel):
    product_code: int
    supplier_ids: list[int] = []


@router.post("/sourcing/request")
def request_quotes(body: RequestBody):
    if not body.supplier_ids:
        raise HTTPException(400, "견적을 요청할 공급처를 선택하세요")
    with engine.begin() as conn:
        p = conn.execute(text(
            "SELECT sku, product_name FROM products WHERE product_code=:pc"),
            {"pc": body.product_code}).mappings().first()
        if p is None:
            raise HTTPException(404, "상품이 없습니다")
        dup = conn.execute(text(
            "SELECT 1 FROM product_sourcing_quotes WHERE product_code=:pc"
            " AND status IN ('요청','회신') LIMIT 1"), {"pc": body.product_code}).first()
        if dup:
            raise HTTPException(409, "이미 진행 중인 견적 요청이 있습니다")
        batch_id = conn.execute(text(
            "INSERT INTO sourcing_batches (title, status) VALUES (:t, '진행') RETURNING batch_id"),
            {"t": f"{p['sku']} 매입 견적"}).scalar()
        made = []
        for sid in body.supplier_ids:
            s = conn.execute(text("SELECT name FROM suppliers WHERE supplier_id=:s"),
                             {"s": sid}).scalar()
            if s is None:
                raise HTTPException(404, f"공급처가 없습니다: {sid}")
            qid = conn.execute(text(
                "INSERT INTO product_sourcing_quotes"
                " (batch_id, product_code, supplier_id, vendor, status)"
                " VALUES (:b, :pc, :s, :v, '요청') RETURNING quote_id"),
                {"b": batch_id, "pc": body.product_code, "s": sid, "v": s}).scalar()
            made.append({"quote_id": qid, "supplier": s})
        log_id = _log(conn, "sourcing_request", p["sku"],
                      {"product_code": body.product_code, "batch_id": batch_id,
                       "quotes": made}, kind="sourcing")
        return {"ok": True, "batch_id": batch_id, "quotes": made, "undo_id": log_id}


class ReplyBody(BaseModel):
    price: int
    memo: str | None = None


@router.post("/sourcing/quotes/{quote_id}/reply")
def record_reply(quote_id: int, body: ReplyBody):
    """공급처 회신을 운영자가 대행 입력(자동 수신 아님 — 정직)."""
    if body.price <= 0:
        raise HTTPException(400, "회신 매입가는 1원 이상이어야 합니다")
    with engine.begin() as conn:
        q = conn.execute(text(
            "SELECT quote_id, product_code, status FROM product_sourcing_quotes"
            " WHERE quote_id=:i FOR UPDATE"), {"i": quote_id}).mappings().first()
        if q is None:
            raise HTTPException(404, "견적 요청이 없습니다")
        if q["status"] not in ("요청", "회신"):
            raise HTTPException(409, f"'{q['status']}' 상태에서는 회신을 기록할 수 없습니다")
        conn.execute(text(
            "UPDATE product_sourcing_quotes SET price=:p, memo=:m, status='회신',"
            " replied_at=now() WHERE quote_id=:i"),
            {"p": body.price, "m": body.memo, "i": quote_id})
        _log(conn, "sourcing_reply", str(quote_id),
             {"quote_id": quote_id, "product_code": q["product_code"], "price": body.price},
             kind="sourcing")
        return {"ok": True, "price": body.price}


@router.post("/sourcing/quotes/{quote_id}/confirm")
def confirm_quote(quote_id: int):
    """매입 확정 — psp 갱신 + 재판정(가격 이력 reason='sourcing'). 재고는 늘지 않는다(T10 경계)."""
    with engine.begin() as conn:
        q = conn.execute(text(
            "SELECT q.quote_id, q.product_code, q.supplier_id, q.price, q.status, q.batch_id,"
            " p.sku FROM product_sourcing_quotes q JOIN products p USING (product_code)"
            " WHERE q.quote_id=:i FOR UPDATE"), {"i": quote_id}).mappings().first()
        if q is None:
            raise HTTPException(404, "견적이 없습니다")
        if q["status"] != "회신" or q["price"] is None:
            raise HTTPException(409, "회신이 기록된 견적만 확정할 수 있습니다")
        fee, margin = _settings(conn)
        before = conn.execute(text(
            "SELECT cost_price, supply_state FROM product_supplier_prices"
            " WHERE product_code=:pc AND supplier_id=:s"),
            {"pc": q["product_code"], "s": q["supplier_id"]}).first()
        conn.execute(text(
            "INSERT INTO product_supplier_prices (product_code, supplier_id, cost_price, supply_state)"
            " VALUES (:pc, :s, :c, '가능')"
            " ON CONFLICT (product_code, supplier_id)"
            " DO UPDATE SET cost_price=:c, supply_state='가능', updated_at=now()"),
            {"pc": q["product_code"], "s": q["supplier_id"], "c": q["price"]})
        rp = _reprice(conn, q["product_code"], fee, margin, "sourcing", q["quote_id"])
        conn.execute(text(
            "UPDATE product_sourcing_quotes SET status='확정' WHERE quote_id=:i"), {"i": quote_id})
        conn.execute(text(
            "UPDATE product_sourcing_quotes SET status='취소'"
            " WHERE batch_id=:b AND quote_id<>:i AND status IN ('요청','회신')"),
            {"b": q["batch_id"], "i": quote_id})
        conn.execute(text(
            "UPDATE sourcing_batches SET status='완료' WHERE batch_id=:b"), {"b": q["batch_id"]})
        log_id = _log(conn, "sourcing_confirm", q["sku"],
                      {"quote_id": quote_id, "product_code": q["product_code"],
                       "supplier_id": q["supplier_id"], "price": q["price"],
                       "before": {"cost_price": before[0] if before else None},
                       "reprice": rp}, kind="sourcing")
        return {"ok": True, "sku": q["sku"], "price": q["price"],
                "purchase_changed": rp["purchase_changed"], "sale_changed": rp["sale_changed"],
                "sale_locked": rp["sale_locked"], "undo_id": log_id}
