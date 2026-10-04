"""Connection-injected sourcing confirmation; transaction belongs to caller.

Products are acquired as one ascending set before batch and ascending quotes.
Discovered quote/product links are checked again before any business write.
This does not add expected, revision, ABA or receipt guarantees.
Injected confirmed_at_ready is invoked at the legacy
point after repricing/readback; its production adapter may use another connection.
No operational application modules are imported and no transaction is opened.
"""

from fastapi import HTTPException
from sqlalchemy import text

from .pricing_write_guard_core import lock_products, ProductScopeChanged


_QUOTE_SQL = (
    "SELECT quote_id, product_code, supplier_id, price, status, batch_id"
    " FROM product_sourcing_quotes WHERE quote_id=:i"
)
_SCOPE_SQL = (
    "SELECT quote_id, product_code, batch_id FROM product_sourcing_quotes"
    " WHERE quote_id=:i OR batch_id=:b ORDER BY quote_id"
)
_LOCK_QUOTES_SQL = (
    "SELECT quote_id, product_code, supplier_id, price, status, batch_id"
    " FROM product_sourcing_quotes WHERE quote_id = ANY(:ids)"
    " ORDER BY quote_id FOR UPDATE"
)


def _scope_links(rows):
    return {row["quote_id"]: (row["product_code"], row["batch_id"]) for row in rows}


def _scope_changed():
    raise HTTPException(409, "견적의 상품 또는 배치 연결이 변경되었습니다. 다시 확인하세요")


def confirm_quote_tx(conn, quote_id: int, *, settings, reprice, log, confirmed_at_ready):
    """Execute the legacy body on conn without begin/commit/rollback/connection creation."""
    discovered = conn.execute(text(_QUOTE_SQL), {"i": quote_id}).mappings().first()
    if discovered is None:
        raise HTTPException(404, "견적이 없습니다")
    if discovered["status"] != "회신" or discovered["price"] is None:
        raise HTTPException(409, "회신이 기록된 견적만 확정할 수 있습니다")
    scope_params = {"i": quote_id, "b": discovered["batch_id"]}
    candidates = conn.execute(text(_SCOPE_SQL), scope_params).mappings().all()
    expected = _scope_links(candidates)
    if (len(expected) != len(candidates)
            or expected.get(quote_id) != (discovered["product_code"], discovered["batch_id"])):
        _scope_changed()
    try:
        lock_products(conn, [row["product_code"] for row in candidates])
    except ProductScopeChanged:
        _scope_changed()
    # A nullable legacy batch still yields its original None before value.
    batch_before = conn.execute(text(
        "SELECT status FROM sourcing_batches WHERE batch_id=:b FOR UPDATE"),
        {"b": discovered["batch_id"]}).scalar()
    locked = conn.execute(text(_LOCK_QUOTES_SQL), {"ids": sorted(expected)}).mappings().all()
    current = conn.execute(text(_SCOPE_SQL), scope_params).mappings().all()
    if (len(locked) != len(expected) or _scope_links(locked) != expected
            or len(current) != len(expected) or _scope_links(current) != expected
            or [row["quote_id"] for row in locked] != sorted(expected)):
        _scope_changed()
    q = dict(next(row for row in locked if row["quote_id"] == quote_id))
    if q["status"] != "회신" or q["price"] is None:
        raise HTTPException(409, "회신이 기록된 견적만 확정할 수 있습니다")
    q["sku"] = conn.execute(text("SELECT sku FROM products WHERE product_code=:pc"),
                            {"pc": q["product_code"]}).scalar_one()
    # Only active siblings enter the legacy undo detail; terminal rows are also
    # locked so their product links cannot silently expand the acquired set.
    siblings_before = [row for row in locked if row["quote_id"] != quote_id
                       and row["status"] in ("요청", "회신")]
    fee, margin = settings(conn)
    before = conn.execute(text(
        "SELECT cost_price, supply_state FROM product_supplier_prices"
        " WHERE product_code=:pc AND supplier_id=:s"),
        {"pc": q["product_code"], "s": q["supplier_id"]}).first()
    # 확정 결과 패널(ADM-SRC-010 계약 ㉰)은 "148,000 → 142,000" 같은 **실제 전·후 값**을
    # 요구하는데 _reprice()는 불리언만 돌려준다(admin_price_import.py:161 — 카탈로그
    # 재적재·가격 검토도 같이 쓰는 함수라 반환 계약을 넓히지 않는다). 그래서 여기서
    # 같은 트랜잭션 안에서 전·후를 한 번씩 더 읽는다(추가 쓰기 없음, 읽기 2회뿐).
    prod_before = conn.execute(text(
        "SELECT purchase_price, sale_price FROM products WHERE product_code=:pc"),
        {"pc": q["product_code"]}).mappings().one()
    # Sibling statuses and the actual batch status were captured under the
    # earlier locks; preserve them for undo before the cancellation/completion.
    conn.execute(text(
        "INSERT INTO product_supplier_prices (product_code, supplier_id, cost_price, supply_state)"
        " VALUES (:pc, :s, :c, '가능')"
        " ON CONFLICT (product_code, supplier_id)"
        " DO UPDATE SET cost_price=:c, supply_state='가능', updated_at=now()"),
        {"pc": q["product_code"], "s": q["supplier_id"], "c": q["price"]})
    rp = reprice(conn, q["product_code"], fee, margin, "sourcing", q["quote_id"])
    prod_after = conn.execute(text(
        "SELECT purchase_price, sale_price FROM products WHERE product_code=:pc"),
        {"pc": q["product_code"]}).mappings().one()
    # 결함 수정(2026-08-15): status만 바꾸고 시각을 안 남기면 "오늘 확정 {n}건"을 셀
    # 방법이 없다(_confirmed_at_ready() 참조). 컬럼이 아직 없으면(마이그레이션 0053
    # 미적용) 이 UPDATE는 지금까지처럼 status만 바꾼다 — 적용 후 재배포되면 그 뒤로
    # 확정되는 건부터 confirmed_at이 찍힌다(그 이전 확정 건은 언제인지 모르므로
    # 지어내지 않고 NULL로 남는다).
    if confirmed_at_ready():
        conn.execute(text(
            "UPDATE product_sourcing_quotes SET status='확정', confirmed_at=now()"
            " WHERE quote_id=:i"), {"i": quote_id})
    else:
        conn.execute(text(
            "UPDATE product_sourcing_quotes SET status='확정' WHERE quote_id=:i"), {"i": quote_id})
    conn.execute(text(
        "UPDATE product_sourcing_quotes SET status='취소'"
        " WHERE batch_id=:b AND quote_id<>:i AND status IN ('요청','회신')"),
        {"b": q["batch_id"], "i": quote_id})
    conn.execute(text(
        "UPDATE sourcing_batches SET status='완료' WHERE batch_id=:b"), {"b": q["batch_id"]})
    log_id = log(conn, "sourcing_confirm", q["sku"],
                  {"quote_id": quote_id, "product_code": q["product_code"],
                   "supplier_id": q["supplier_id"], "price": q["price"],
                   # 되돌리기 재료(2026-08-28, req-activity-undo.md §④와 맞물린다) —
                   # 이 확정이 건드리는 세 갈래(이 견적 자신 · 공급처 매입가 ·
                   # 상품 가격)의 이전 값. cost_price 는 기존 필드 그대로(소비자
                   # admin_activity_logs.py:171 요약 문구가 이 키를 읽는다 — 이름을
                   # 바꾸지 않았다), supply_state·quote_status·purchase_price·
                   # sale_price 는 이번에 추가했다. purchase_price·sale_price 는
                   # 이미 읽어 둔 prod_before(위 ㉰ 결과 패널용)를 그대로 쓴다 —
                   # 두 번 계산하지 않는다.
                   "before": {"quote_status": q["status"],
                              "batch_status": batch_before,
                              "cost_price": before[0] if before else None,
                              "supply_state": before[1] if before else None,
                              "purchase_price": prod_before["purchase_price"],
                              "sale_price": prod_before["sale_price"]},
                   # 자동 취소된 형제 견적 — 각자 이전 상태를 담아야 개별 복원이
                   # 된다(전부 '취소'로 뭉뚱그리면 원래 '요청'이었는지 '회신'이었는지
                   # 사라진다).
                   "cancelled_siblings": [{"quote_id": s["quote_id"], "status": s["status"]}
                                          for s in siblings_before],
                   "reprice": rp}, kind="sourcing")
    return {"ok": True, "sku": q["sku"], "price": q["price"],
            "purchase_changed": rp["purchase_changed"], "sale_changed": rp["sale_changed"],
            "sale_locked": rp["sale_locked"],
            "purchase_before": prod_before["purchase_price"],
            "purchase_after": prod_after["purchase_price"],
            "sale_before": prod_before["sale_price"], "sale_after": prod_after["sale_price"],
            "undo_id": log_id}
