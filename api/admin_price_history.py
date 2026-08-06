"""ADM-PRC-030 가격 이력 — 판매가·매입가 변동 원장 조회 (읽기 전용).

원장 원칙: 가격 변경은 삭제하지 않는다 — 되돌림도 역방향 이력 행으로 남는다(슬라이스 3부터).
reason 어휘(ERD §3.4·§6.3): csv / sourcing / margin_policy / manual / price_import(+_undo).
정직 표기 2건:
  ① **공급처별 매입가 분리 불가** — product_price_history에 supplier 구분 컬럼이 없다.
     purchase 이력은 공급처 간 재판정 결과(최저가)이므로 차트는 판매가·매입가 2선만 그린다
     (목업의 공급처별 2선은 연출 — 컬럼화 이관).
  ② **6주 고정 축 아님** — 실데이터 구간이 짧아 이력 전체를 시간축에 그린다(구간 필터 이관).
ref_id는 사유별 의미가 다르다(price_import=file_id, margin_policy·manual=활동로그 log_id,
sourcing=sourcing_id) — 화면 링크도 사유별로 분기한다.
"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from .timeutil import iso, kst_day_range, range_sql
from .db import engine

router = APIRouter(prefix="/api/admin")

REASON_KO = {
    "price_import": ("단가표 반영", "price-import.html"),
    "price_import_undo": ("단가표 반영 되돌림", "price-import.html"),
    "margin_policy": ("가격 검토 승인", "price-review.html"),
    "manual": ("운영자 직접 수정", "activity-logs.html"),
    "sourcing": ("매입 확정", "sourcing.html"),
    "csv": ("일괄 등록", "csv-jobs.html"),
}
FIELD_KO = {"sale": "판매가", "purchase": "매입가"}


@router.get("/price-history")
def price_history(product_code: int | None = None,
                  date_from: str | None = None, date_to: str | None = None):
    # 기간은 **서울 날짜**로 받는다 — 변환은 `timeutil` 하나가 한다(9시간 함정).
    try:
        _lo, _hi = kst_day_range(date_from, date_to)
    except ValueError as e:
        raise HTTPException(400, str(e) or "기간 형식은 YYYY-MM-DD 입니다")
    _p = {}
    if _lo is not None:
        _p["_dt_lo"] = _lo
    if _hi is not None:
        _p["_dt_hi"] = _hi
    _RANGE = range_sql("h.changed_at", _lo, _hi)
    with engine.connect() as conn:
        prods = conn.execute(text(
            "SELECT h.product_code, p.sku, p.product_name, COUNT(*) AS cnt,"
            " MAX(h.changed_at) AS last_at"
            " FROM product_price_history h JOIN products p USING (product_code)"
            " WHERE TRUE" + _RANGE +
            # 좌측 상품 목록도 같은 기간을 본다 — 안 그러면 "이 기간에 이력이 있는 상품"이
            # 아니라 전체가 뜨고, 골라 들어가면 오른쪽이 비어 있다.
            " GROUP BY h.product_code, p.sku, p.product_name"
            " ORDER BY cnt DESC, last_at DESC"), _p).mappings().all()
        if not prods:
            return {"products": [], "items": [], "series": {"sale": [], "purchase": []},
                    "product": None, "note": "가격 이력이 아직 없습니다."}
        pc = product_code or prods[0]["product_code"]
        if not any(p["product_code"] == pc for p in prods):
            raise HTTPException(404, "해당 상품의 가격 이력이 없습니다")
        rows = conn.execute(text(
            "SELECT h.history_id, h.field, h.old_price, h.new_price, h.reason, h.ref_id,"
            " h.changed_at, h.supplier_id, s.name AS supplier"
            " FROM product_price_history h LEFT JOIN suppliers s USING (supplier_id)"
            " WHERE h.product_code=:pc" + _RANGE +
            " ORDER BY h.changed_at, h.history_id"),
            {"pc": pc, **_p}).mappings().all()
        cur = conn.execute(text(
            "SELECT sku, product_name, purchase_price, sale_price FROM products"
            " WHERE product_code=:pc"), {"pc": pc}).mappings().one()

    # 판매가 1선 + 매입가는 **공급처별 분리**(0004에서 supplier_id 추가 — 출처 미기록분은 '기록 없음')
    series = {"sale": [], "purchase": []}
    by_supplier: dict = {}
    for r in rows:
        if r["field"] not in series or r["new_price"] is None:
            continue
        pt = {"at": iso(r["changed_at"]), "price": r["new_price"]}
        series[r["field"]].append(pt)
        if r["field"] == "purchase":
            key = r["supplier"] or "출처 미기록"
            by_supplier.setdefault(key, []).append(pt)
    items = [{
        "id": r["history_id"], "at": iso(r["changed_at"]),
        "field": r["field"], "field_label": FIELD_KO.get(r["field"], r["field"]),
        "old": r["old_price"], "new": r["new_price"],
        "delta": (r["new_price"] - r["old_price"]) if (r["old_price"] is not None and r["new_price"] is not None) else None,
        "reason": r["reason"],
        "reason_label": REASON_KO.get(r["reason"], (r["reason"], "activity-logs.html"))[0],
        "reason_link": REASON_KO.get(r["reason"], (r["reason"], "activity-logs.html"))[1],
        "ref_id": r["ref_id"], "supplier": r["supplier"],
    } for r in reversed(rows)]   # 최신 우선
    return {
        "products": [{"product_code": p["product_code"], "sku": p["sku"],
                      "name": p["product_name"], "count": p["cnt"]} for p in prods],
        "product": {"product_code": pc, "sku": cur["sku"], "name": cur["product_name"],
                    "purchase": cur["purchase_price"], "sale": cur["sale_price"]},
        "items": items, "series": series,
        "by_supplier": [{"supplier": k, "points": v} for k, v in by_supplier.items()],
        "note": ("매입가는 공급처별로 나눠 그립니다(마이그레이션 0004에서 이력에 공급처를 남김)."
                 " '출처 미기록'은 공급처 구분이 없던 시점의 이력입니다 —"
                 " 복수 공급처 상품은 추정하지 않고 그대로 둡니다 ·"
                 " 구간 필터는 준비 중이며 현재는 이력 전체를 시간축에 그립니다 ·"
                 " 되돌림도 역방향 행으로 남습니다."),
    }
