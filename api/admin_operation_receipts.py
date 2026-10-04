"""Fresh owner context and exact terminal reprice receipt lookup."""
from fastapi import APIRouter, HTTPException, Response
from uuid import UUID

from .auth import current_operator
from .db import engine
from .admin_operation_receipt_core import (
    operation_context, lookup_operation, operation_record, ReceiptUnavailable, OperationConflict,
)

router = APIRouter(prefix="/api/admin/reprice/operations")


def _context():
    me = current_operator() or {}
    if me.get("role") != "owner":
        raise HTTPException(403, "관리자(owner)만 판매가를 재산정할 수 있습니다", headers={"Cache-Control": "no-store"})
    try:
        return operation_context(me)
    except ReceiptUnavailable as error:
        raise HTTPException(503, str(error), headers={"Cache-Control": "no-store"}) from None
    except OperationConflict:
        raise HTTPException(403, "재산정 요청의 권한을 확인할 수 없습니다", headers={"Cache-Control": "no-store"}) from None


@router.get("/context")
def context(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return _context()


@router.get("/{operation_id}")
def receipt(operation_id: UUID, response: Response):
    response.headers["Cache-Control"] = "no-store"
    identity = _context() | {"operation_id": str(operation_id)}
    with engine.connect() as conn:
        row = lookup_operation(conn, identity, owned=True)
    if row is None:
        raise HTTPException(404, "재산정 요청 결과를 찾을 수 없습니다", headers={"Cache-Control": "no-store"})
    record = operation_record(row)
    # SQL ownership is checked again before exposing even a corrupted stored row.
    if any(record["receipt"][k] != identity[k] for k in identity):
        raise HTTPException(404, "재산정 요청 결과를 찾을 수 없습니다", headers={"Cache-Control": "no-store"})
    return {"operation_receipt": record["receipt"], "response": record["response_body"],
            "original_http_status": record["http_status"]}
