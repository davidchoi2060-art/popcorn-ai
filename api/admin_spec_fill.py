# -*- coding: utf-8 -*-
"""웹 사양 채움 — 진행 조회 (읽기 전용 · B안 확정 2026-08-13).

■ 이 모듈이 하는 일 — **집계 SELECT 뿐이다**
  `/admin2/spec-fill` 화면의 진행 섹션·결과 미리보기가 쓰는 유일한 신규 API.
  근거: `docs/design/spec-fill-ui-direction-2026-08-13.md`, decision-log P-10.

■ 이 모듈이 하지 않는 일 — 정본을 복제하지 않는다
  · **실행**은 여기 없다. 화면의 [웹 사양 채움 실행] 버튼은 기존 대시보드 큐
    (`POST /api/admin/dash/say`, `api/dash.py`)에 구조화된 메시지를 넣을 뿐이고,
    감시자→하네스→스펙크롤러(`tools/spec_fill_apply.py`)로 이어지는 기존 체인을 그대로 탄다.
  · **승인**도 여기 없다. `product_specs`에 값을 반영하는 것은 검수 화면(ADM-PRD-020,
    `api/admin_reviews._approve`)만 한다(A-18 계약과 동일선상) — 이 모듈은
    `product_reviews`·`product_specs`에 쓰지 않는다.
"""
from fastapi import APIRouter
from sqlalchemy import text

from .db import engine
from .timeutil import iso

router = APIRouter(prefix="/api/admin/spec-fill", tags=["admin-spec-fill"])


def _has_table(conn) -> bool:
    return bool(conn.execute(text(
        "SELECT 1 FROM information_schema.tables"
        " WHERE table_name = 'spec_web_suggestions'")).first())


@router.get("/status")
def status(page: int = 1, size: int = 20):
    """진행 집계 + 최근 배치 목록(서버 페이지네이션 — 전 행 반환 금지 규약).

    - `total` — `spec_web_suggestions` 총 행 수.
    - `latest_fetched_at` — 가장 최근 제안이 채워진 시각.
    - `pending_review` — 이 제안이 올라간 검수 행(`applied_review_id`)이
      **아직 '대기' 상태**인 건수. 승인/기각된 것은 빠진다 — "지금 확인이 필요한 수"다.
    - `items` — 최근 배치 목록(상품명·필드·제안값·출처 URL·confidence·적용 시각·검수 상태).
    """
    size = max(1, min(size, 100))
    page = max(1, page)
    with engine.connect() as conn:
        if not _has_table(conn):
            return {"ok": False,
                    "reason": "spec_web_suggestions 테이블이 없습니다 — 마이그레이션 0045 미적용",
                    "items": [], "total": 0, "page": page, "size": size, "pages": 0,
                    "latest_fetched_at": None, "pending_review": 0}
        total = conn.execute(text("SELECT count(*) FROM spec_web_suggestions")).scalar_one()
        latest = conn.execute(text("SELECT max(fetched_at) FROM spec_web_suggestions")).scalar_one()
        pending = conn.execute(text(
            "SELECT count(*) FROM spec_web_suggestions s"
            " JOIN product_reviews r ON r.review_id = s.applied_review_id"
            " WHERE r.review_status = '대기'")).scalar_one()
        rows = conn.execute(text("""
            SELECT s.id, s.product_code, p.product_name, s.field_name, s.suggested_value,
                   s.source_url, s.source_name, s.confidence, s.fetched_at, r.review_status
            FROM spec_web_suggestions s
            JOIN products p USING (product_code)
            LEFT JOIN product_reviews r ON r.review_id = s.applied_review_id
            ORDER BY s.fetched_at DESC, s.id DESC
            LIMIT :size OFFSET :offset
        """), {"size": size, "offset": (page - 1) * size}).mappings().all()
    items = [{
        "id": r["id"], "product_code": r["product_code"], "name": r["product_name"],
        "field": r["field_name"], "value": r["suggested_value"],
        "source_url": r["source_url"], "source_name": r["source_name"],
        "confidence": float(r["confidence"]) if r["confidence"] is not None else None,
        "fetched_at": iso(r["fetched_at"]),
        # None이면 applied_review_id가 가리키던 검수 행이 다른 경로로 이미 사라진
        # 예외적인 경우다 — 화면이 지어내지 않고 그대로 보인다.
        "review_status": r["review_status"],
    } for r in rows]
    return {"ok": True, "total": total, "page": page, "size": size,
            "pages": (total + size - 1) // size if total else 0,
            "latest_fetched_at": iso(latest) if latest else None,
            "pending_review": pending, "items": items,
            "note": ("spec_web_suggestions 집계입니다. product_specs 반영(승인)은"
                     " 상품 사양 검수(ADM-PRD-020)에서만 합니다 — 이 화면은 쓰지 않습니다.")}
