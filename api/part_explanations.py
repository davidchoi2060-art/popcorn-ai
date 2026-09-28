"""Source-bound component copy. Public reads never expose unreviewed drafts."""
import hashlib
import json

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from .db import engine
from .taxonomy import SLOT_LABELS
from .product_name import display_name, remove_discount_label

router = APIRouter()


def fingerprint(name, spec):
    value = json.dumps([name or "", spec or ""], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def is_current(row):
    if row.get("product_code") is None:
        return False
    if row["source_fingerprint"] == fingerprint(row.get("product_name"), row.get("spec_source_text")):
        return True
    # Catalog ingestion trims outer whitespace. Preserve the original evidence hash,
    # but do not mark a trailing space as a changed specification.
    source = row.get("source_snapshot") or {}
    return (bool(source)
            and row["source_fingerprint"] == fingerprint(source.get("name"), source.get("spec"))
            and (row.get("product_name") or "").strip() == (source.get("name") or "").strip()
            and (row.get("spec_source_text") or "").strip() == (source.get("spec") or "").strip())


def can_publish(row):
    return (row.get("status") == "approved" and row.get("approved_by") is not None
            and row.get("approved_at") is not None and row.get("sale_status") == "판매중"
            and is_current(row) and not row["content"].get("review_issues"))


SELECT = """
 SELECT e.*, p.product_name, p.spec_source_text, p.status AS sale_status, p.sale_price
 FROM product_explanations e LEFT JOIN products p ON p.product_code=e.product_code
"""


def present(row, admin=False):
    result = dict(row["content"])
    result["name"] = remove_discount_label(result.get("name", ""))
    result["slot_label"] = SLOT_LABELS.get(result.get("slot"), result.get("slot", ""))
    if result.get("image_asset"):
        result["merchant_image_url"] = result.get("image_url")
        result["image_url"] = f"/api/product-images/{row['source_product_code']}/detail"
    result.update(product_code=row["source_product_code"], price=row["sale_price"],
                  price_basis="현재 부품 판매가", status=row["status"],
                  source_current=is_current(row), product_linked=row["product_code"] is not None)
    if admin:
        result["updated_at"] = row["updated_at"]
    else:
        result["name"] = display_name(result.get("name", ""))
        result.pop("image_asset", None)
        result.pop("review_issues", None)
    return result


@router.get("/api/admin/part-explanations")
def list_explanations(q: str = Query("", max_length=100), slot: str = Query("", max_length=20),
                      offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=50)):
    where = " WHERE (:q='' OR e.content->>'name' ILIKE :pattern OR e.source_product_code::text=:q) AND (:slot='' OR e.content->>'slot'=:slot)"
    args = dict(q=q, pattern="%"+q+"%", slot=slot, offset=offset, limit=limit)
    with engine.connect() as conn:
        total = conn.execute(text("SELECT count(*) FROM product_explanations e"+where), args).scalar_one()
        rows = conn.execute(text(SELECT+where+" ORDER BY e.source_product_code LIMIT :limit OFFSET :offset"), args).mappings().all()
    return dict(total=total, offset=offset, limit=limit, items=[present(r, True) for r in rows])


@router.get("/api/admin/part-explanations/{code}")
def admin_explanation(code: int):
    return get_explanation(code, admin=True)


def get_explanation(code, admin=False):
    with engine.connect() as conn:
        row = conn.execute(text(SELECT+" WHERE e.source_product_code=:code"), {"code":code}).mappings().first()
    if row is None or (not admin and not can_publish(row)):
        raise HTTPException(404, "공개 검수가 완료된 부품 설명이 없습니다.")
    return present(row, admin)


@router.get("/api/part-explanations/{code}")
def public_explanation(code: int):
    return get_explanation(code)
