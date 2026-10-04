"""Connection-injected repricing core; transaction ownership stays with caller.

This extraction preserves existing SQL, locking, price decisions and history.
It does not add expected/revision checks or a new global writer lock order.
"""
from typing import Callable

from sqlalchemy import text

from .pricing import sale_from_purchase


def reprice(conn, pc: int, fee: float, margin: float, reason: str, ref_id: int,
             restore: dict | None = None, *, operator_id: Callable[[], int]) -> dict:
    """공급처 간 재판정(ERD §11): purchase = '가능' 상태 최저 cost, 없으면 전체 최저.
    변경분만 UPDATE + product_price_history 기록. undo도 이 헬퍼를 재실행한다(블라인드 복원 금지).

    restore(undo 전용) = 반영 시점의 {purchase, sale} 스냅샷. 재판정 결과 purchase가 반영 전
    값으로 완전히 복귀했다면 sale도 기록된 원본으로 복원한다(공식 재도출이 아니라 — 시드처럼
    공식과 무관한 판매가를 보존). 교차 반영으로 purchase가 다른 값이면 공식 도출 유지.

    2026-08-15 결함 수정(확인자 실측 123327·123326 — 원장 정합성): product_supplier_prices가
    0행이면(그 반영이 이 상품의 처음이자 유일한 공급처 가격이었을 때, undo()가 psp_before=None
    분기에서 그 행을 DELETE한 직후가 정확히 이 상태다) 예전엔 restore가 있어도 곧바로 return해
    products.purchase_price·sale_price가 반영 당시 값에 «영구 고정»되고 product_price_history에
    되돌림 행도 안 남았다 — API는 {"ok":true,"restored":1}을 주는데 실제로는 아무것도 안
    되돌아가는 결함. 0행이어도 restore가 있으면 그 스냅샷 값을 그대로 써서 복원한다(공급처가
    하나도 없으니 "재판정"이 아니라 "복원"이다). restore가 없는 기존 호출부(admin_price_review.
    approve의 margin_policy · admin_sourcing.confirm_quote의 sourcing — 둘 다 restore 인자를
    안 준다)는 그대로 조기 return한다 — 동작 불변(git grep "_reprice(" 전수 확인)."""
    prod = conn.execute(text(
        "SELECT purchase_price, sale_price, locked_fields FROM products"
        " WHERE product_code=:pc FOR UPDATE"), {"pc": pc}).mappings().one()
    rows = conn.execute(text(
        "SELECT cost_price, supply_state, supplier_id FROM product_supplier_prices"
        " WHERE product_code=:pc"), {"pc": pc}).all()
    out = {"purchase_changed": False, "sale_changed": False, "sale_locked": False}
    src_supplier = None
    if rows:
        avail = [(c, sid) for c, s, sid in rows if s == "가능"]
        pool = avail if avail else [(c, sid) for c, _s, sid in rows]
        new_purchase, src_supplier = min(pool)   # 최저가 + 그 값을 만든 공급처(이력에 남긴다 — 0004)
    elif restore is not None:
        new_purchase = restore["purchase"]   # 공급처 가격 0행 — 재판정 불가, 스냅샷으로 복원
    else:
        return out   # 공급처 가격도 없고 복원할 스냅샷도 없다 — 기존 동작 그대로(no-op)
    if new_purchase != prod["purchase_price"]:
        conn.execute(text(
            "UPDATE products SET purchase_price=:v, updated_at=now() WHERE product_code=:pc"),
            {"v": new_purchase, "pc": pc})
        conn.execute(text(
            "INSERT INTO product_price_history"
            " (product_code, field, old_price, new_price, reason, ref_id, changed_by, supplier_id)"
            " VALUES (:pc, 'purchase', :o, :n, :r, :ref, :op, :sid)"),
            {"pc": pc, "o": prod["purchase_price"], "n": new_purchase,
             "r": reason, "ref": ref_id, "op": operator_id(), "sid": src_supplier})
        out["purchase_changed"] = True
    if restore is not None and new_purchase == restore["purchase"]:
        new_sale = restore["sale"]
    else:
        new_sale = sale_from_purchase(new_purchase, fee, margin)
    if "sale_price" in (prod["locked_fields"] or []):
        out["sale_locked"] = new_sale != prod["sale_price"]
    elif new_sale != prod["sale_price"]:
        conn.execute(text(
            "UPDATE products SET sale_price=:v, updated_at=now() WHERE product_code=:pc"),
            {"v": new_sale, "pc": pc})
        conn.execute(text(
            "INSERT INTO product_price_history (product_code, field, old_price, new_price, reason, ref_id, changed_by)"
            " VALUES (:pc, 'sale', :o, :n, :r, :ref, :op)"),
            {"pc": pc, "o": prod["sale_price"], "n": new_sale,
             "r": reason, "ref": ref_id, "op": operator_id()})
        out["sale_changed"] = True
    return out
