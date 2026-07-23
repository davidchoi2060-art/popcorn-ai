"""ADM-PRD-020 검수 큐 — 읽기 + 첫 쓰기 이음새 (처리/되돌리기/일괄 확정).

승인 전이(ERD §8 T2): specs 값 반영 → (잔여 0건이면) verified → locked_fields 등록
→ review_required 재산정(필수 충족 ∧ 잔여 0) → true→false 전이 시에만 ai_candidate 승격.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from .admin_products import PART_TYPE_LABELS, REQUIRED_SPEC_FIELDS
from .db import engine

router = APIRouter(prefix="/api/admin")

OPERATOR_ID = 1  # 인증 슬라이스 전까지 시드 운영자 고정

# ERD §7.3 호환성 치명 필드 (목업 CRIT_CONFLICT와 다름 — ERD 우선 채택, 의도된 차이)
CRITICAL_FIELDS = {"length_mm", "gpu_max_mm", "rated_watt", "socket"}

# 검수 처리 가능한 specs 컬럼 화이트리스트 + SQL 캐스트 타입.
# 컬럼명은 이 딕셔너리를 통해서만 SQL에 삽입된다(ports JSONB는 제외 — 구조 편집은 별도 화면).
FIELD_CAST = {
    **{f: "INTEGER" for f in (
        "length_mm", "rated_watt", "refresh_hz", "capacity_gb", "clock_mhz",
        "tdp_watt", "required_power_watt", "gpu_max_mm", "cooler_height_mm", "cooler_tdp")},
    "size_inch": "NUMERIC(4,1)",
    **{f: "VARCHAR" for f in (
        "socket", "chipset", "mem_type", "form_factor", "interface", "pcie_gen",
        "resolution", "panel", "switch_type", "key_layout", "connection")},
}


def _risk(review_type: str, field: str | None) -> str:
    if review_type == "spec_conflict" and field in CRITICAL_FIELDS:
        return "치명"
    if review_type in ("spec_conflict", "spec_missing"):
        return "주의"
    return "경미"


def _crit(part_type: str, target_field: str | None, review_type: str, specs: dict | None):
    out = []
    for f in REQUIRED_SPEC_FIELDS.get(part_type, []):
        if f == target_field:
            out.append({"field": f, "value": "불일치" if review_type == "spec_conflict" else "미확인", "ok": False})
        else:
            v = specs.get(f) if specs else None
            out.append({"field": f, "value": "미확인" if v is None else str(v), "ok": True if v is not None else None})
    return out


@router.get("/reviews")
def list_reviews():
    q = text("""
        SELECT r.review_id, r.product_code, r.review_type, r.field_name, r.detail,
               r.origin_value, r.suggested_value, r.confidence, r.created_at,
               p.sku, p.product_name, p.part_type, to_jsonb(ps) AS specs
        FROM product_reviews r
        JOIN products p USING (product_code)          -- product_code NULL(csv_error류)은 자연 제외
        LEFT JOIN product_specs ps USING (product_code)
        WHERE r.review_status = '대기'
        ORDER BY r.created_at
    """)
    with engine.connect() as conn:
        rows = conn.execute(q).mappings().all()
    items = [{
        "review_id": r["review_id"],
        "sku": r["sku"],
        "name": r["product_name"],
        "cat": PART_TYPE_LABELS.get(r["part_type"], r["part_type"]),
        "part_type": r["part_type"],
        "type": r["review_type"],
        "field": r["field_name"],
        "detail": r["detail"],
        "origin_value": r["origin_value"],
        "suggested_value": r["suggested_value"],
        "confidence": float(r["confidence"]) if r["confidence"] is not None else None,
        "created_at": r["created_at"].isoformat(),
        "risk": _risk(r["review_type"], r["field_name"]),
        "crit": _crit(r["part_type"], r["field_name"], r["review_type"], r["specs"]),
    } for r in rows]
    return {"items": items}


class ProcessBody(BaseModel):
    action: str  # origin | suggested | manual | reject
    value: str | None = None


def _approve(conn, review, value, new_status: str) -> tuple[dict, int]:
    """승인 전이 공용 헬퍼(단건·일괄 공유). before 스냅샷과 pool_added를 반환."""
    field = review["field_name"]
    if field not in FIELD_CAST:
        raise HTTPException(400, f"처리할 수 없는 필드: {field}")
    pc = review["product_code"]

    prod = conn.execute(text(
        "SELECT part_type, review_required_yn, ai_candidate_yn, locked_fields"
        " FROM products WHERE product_code=:pc FOR UPDATE"), {"pc": pc}).mappings().one()
    spec = conn.execute(text(
        "SELECT to_jsonb(ps) AS specs FROM product_specs ps WHERE product_code=:pc FOR UPDATE"),
        {"pc": pc}).mappings().first()
    specs_before = spec["specs"] if spec else None

    before = {
        "spec_value": (specs_before or {}).get(field),
        "verified_yn": (specs_before or {}).get("verified_yn", False),
        "review_required_yn": prod["review_required_yn"],
        "ai_candidate_yn": prod["ai_candidate_yn"],
        "locked_fields": prod["locked_fields"],
        "review_status": review["review_status"],
    }

    try:
        conn.execute(text(f"""
            INSERT INTO product_specs (product_code, part_type, {field})
            VALUES (:pc, :pt, CAST(:v AS {FIELD_CAST[field]}))
            ON CONFLICT (product_code)
            DO UPDATE SET {field} = EXCLUDED.{field}, updated_at = now()
        """), {"pc": pc, "pt": prod["part_type"], "v": value})
    except DBAPIError:
        raise HTTPException(400, f"값 형식 오류: {value!r} → {field}")

    remaining = conn.execute(text(
        "SELECT COUNT(*) FROM product_reviews WHERE product_code=:pc"
        " AND review_status IN ('대기','검수중') AND review_id<>:rid"),
        {"pc": pc, "rid": review["review_id"]}).scalar()
    if remaining == 0:
        conn.execute(text(
            "UPDATE product_specs SET verified_yn=true, updated_at=now() WHERE product_code=:pc"),
            {"pc": pc})

    specs_now = conn.execute(text(
        "SELECT to_jsonb(ps) AS s FROM product_specs ps WHERE product_code=:pc"),
        {"pc": pc}).scalar()
    required = REQUIRED_SPEC_FIELDS.get(prod["part_type"], [])
    all_filled = all((specs_now or {}).get(f) is not None for f in required)
    new_review_required = not (all_filled and remaining == 0)

    pool_added = 0
    if prod["review_required_yn"] and not new_review_required:
        # 게이트 해제 전이 — 이 순간에만 ai_candidate 승격 (ERD §8 T2)
        conn.execute(text(
            "UPDATE products SET review_required_yn=false, ai_candidate_yn=true,"
            " locked_fields = CASE WHEN locked_fields ? :lf THEN locked_fields"
            " ELSE locked_fields || jsonb_build_array(:lf) END, updated_at=now()"
            " WHERE product_code=:pc"), {"pc": pc, "lf": f"specs.{field}"})
        pool_added = 1
    else:
        conn.execute(text(
            "UPDATE products SET"
            " locked_fields = CASE WHEN locked_fields ? :lf THEN locked_fields"
            " ELSE locked_fields || jsonb_build_array(:lf) END, updated_at=now()"
            " WHERE product_code=:pc"), {"pc": pc, "lf": f"specs.{field}"})

    conn.execute(text(
        "UPDATE product_reviews SET review_status=:st, reviewed_by=:op, reviewed_at=now()"
        " WHERE review_id=:rid"),
        {"st": new_status, "op": OPERATOR_ID, "rid": review["review_id"]})
    return before, pool_added


def _log(conn, action: str, target_id: str, detail: dict) -> int:
    import json
    return conn.execute(text(
        "INSERT INTO admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)"
        " VALUES (:op, :a, 'product_review', :t, CAST(:d AS JSONB)) RETURNING log_id"),
        {"op": OPERATOR_ID, "a": action, "t": target_id, "d": json.dumps(detail)}).scalar()


def _lock_waiting_review(conn, review_id: int):
    r = conn.execute(text(
        "SELECT * FROM product_reviews WHERE review_id=:rid FOR UPDATE"),
        {"rid": review_id}).mappings().first()
    if r is None:
        raise HTTPException(404, "검수 항목이 없습니다")
    if r["review_status"] != "대기":
        raise HTTPException(409, "이미 처리된 항목입니다")
    return r


@router.post("/reviews/{review_id}/process")
def process_review(review_id: int, body: ProcessBody):
    if body.action not in ("origin", "suggested", "manual", "reject"):
        raise HTTPException(400, f"알 수 없는 액션: {body.action}")
    with engine.begin() as conn:
        review = _lock_waiting_review(conn, review_id)

        if body.action == "reject":
            conn.execute(text(
                "UPDATE product_reviews SET review_status='보류', reviewed_by=:op, reviewed_at=now()"
                " WHERE review_id=:rid"), {"op": OPERATOR_ID, "rid": review_id})
            log_id = _log(conn, "review_process", str(review_id),
                          {"mode": "reject", "review_id": review_id,
                           "before": {"review_status": "대기"}})
            return {"ok": True, "undo_id": log_id, "pool_added": 0}

        value = {"origin": review["origin_value"], "suggested": review["suggested_value"],
                 "manual": body.value}[body.action]
        if value is None:
            raise HTTPException(400, "확정할 값이 없습니다")
        new_status = "수정" if body.action == "manual" else "승인"
        before, pool_added = _approve(conn, review, value, new_status)
        log_id = _log(conn, "review_process", str(review_id),
                      {"mode": "approve", "review_id": review_id,
                       "field": review["field_name"], "value": str(value), "before": before})
        return {"ok": True, "undo_id": log_id, "pool_added": pool_added}


@router.post("/reviews/bulk-confirm")
def bulk_confirm():
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT * FROM product_reviews WHERE review_type='low_confidence'"
            " AND review_status='대기' ORDER BY review_id FOR UPDATE")).mappings().all()
        entries, skipped, pool_total = [], 0, 0
        for r in rows:
            if r["origin_value"] is None:
                skipped += 1
                continue
            before, pool_added = _approve(conn, r, r["origin_value"], "승인")
            pool_total += pool_added
            entries.append({"mode": "approve", "review_id": r["review_id"],
                            "field": r["field_name"], "value": r["origin_value"], "before": before})
        if not entries:
            raise HTTPException(400, "일괄 확정 대상이 없습니다")
        log_id = _log(conn, "review_bulk_confirm", f"{len(entries)}건", {"items": entries})
        return {"count": len(entries), "skipped": skipped, "undo_id": log_id, "pool_added": pool_total}


def _revert_one(conn, entry: dict):
    rid = entry["review_id"]
    r = conn.execute(text(
        "SELECT * FROM product_reviews WHERE review_id=:rid FOR UPDATE"),
        {"rid": rid}).mappings().first()
    if r is None:
        raise HTTPException(404, f"검수 항목이 없습니다: {rid}")
    if r["review_status"] == "대기":
        raise HTTPException(409, "이미 대기 상태입니다")  # 이중 undo·경합 방어의 전부
    before = entry["before"]
    if entry["mode"] == "approve":
        field, pc = entry["field"], r["product_code"]
        import json
        conn.execute(text(f"""
            UPDATE product_specs SET {field} = CAST(:v AS {FIELD_CAST[field]}),
                   verified_yn = :vy, updated_at = now() WHERE product_code = :pc
        """), {"v": before["spec_value"], "vy": before["verified_yn"], "pc": pc})
        conn.execute(text(
            "UPDATE products SET review_required_yn=:rr, ai_candidate_yn=:ac,"
            " locked_fields=CAST(:lf AS JSONB), updated_at=now() WHERE product_code=:pc"),
            {"rr": before["review_required_yn"], "ac": before["ai_candidate_yn"],
             "lf": json.dumps(before["locked_fields"]), "pc": pc})
    conn.execute(text(
        "UPDATE product_reviews SET review_status='대기', reviewed_by=NULL, reviewed_at=NULL"
        " WHERE review_id=:rid"), {"rid": rid})


@router.post("/reviews/undo/{log_id}")
def undo(log_id: int):
    with engine.begin() as conn:
        log = conn.execute(text(
            "SELECT action, detail FROM admin_operator_activity_logs WHERE log_id=:id"),
            {"id": log_id}).mappings().first()
        if log is None or log["action"] not in ("review_process", "review_bulk_confirm"):
            raise HTTPException(404, "되돌릴 작업 기록이 없습니다")
        detail = log["detail"]
        entries = detail["items"] if log["action"] == "review_bulk_confirm" else [detail]
        for e in entries:
            _revert_one(conn, e)
        _log(conn, "review_undo", str(log_id), {"ref_log_id": log_id, "count": len(entries)})
        return {"ok": True, "restored": len(entries)}
