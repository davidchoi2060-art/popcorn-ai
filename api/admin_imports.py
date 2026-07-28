"""ADM-SYS-030 일괄 등록 이력 · ADM-PRD-040 상품 원본 자료 (슬라이스 45).

두 화면이 같은 원장을 본다:
  · **일괄 등록 이력**(csv-jobs) = 배치가 언제 무엇을 몇 건 넣었나 — `csv_import_jobs`
  · **상품 원본 자료**(imports) = 그 배치의 **원본 셀 그대로** — `csv_import_errors.raw_row`

**정직 표기(중요)**: 성공 행의 원본(`product_imports`)은 **저장하지 않는다**. 22,808행의
32컬럼 원문을 다시 담으면 수십 MB가 중복되고, 원본 CSV가 이미 정본이기 때문이다. 그래서
이 화면이 보여주는 원본 행은 **적재가 거부한 행뿐**이고, 화면이 그 사실을 밝힌다 —
"원본이 다 보인다"고 착각하게 두지 않는다. 성공 행은 상품 목록에서 조회한다.
"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from .timeutil import iso
from .db import engine

router = APIRouter(prefix="/api/admin")

SOURCE_LABELS = {"catalog_csv": "상품 카탈로그 CSV", "supplier_excel": "공급처 단가표"}
ORIGIN_LABELS = {"real": "실데이터", "demo": "데모"}


@router.get("/import-jobs")
def list_jobs():
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT j.job_id, j.file_name, j.row_total, j.row_ok, j.row_error, j.row_review,"
            " j.status, j.data_origin, j.source, j.created_at, o.name AS operator,"
            " (SELECT COUNT(*) FROM csv_import_errors e WHERE e.job_id = j.job_id) AS err_rows,"
            " (SELECT COUNT(*) FROM product_imports p WHERE p.job_id = j.job_id) AS kept_rows"
            " FROM csv_import_jobs j LEFT JOIN admin_operators o ON o.operator_id = j.created_by"
            " ORDER BY j.job_id DESC LIMIT 50")).mappings().all()

        # 화면 상단 집계 — '무엇이 얼마나 들어왔나'를 배치 합으로 말한다
        agg = conn.execute(text(
            "SELECT COALESCE(SUM(row_total), 0) t, COALESCE(SUM(row_ok), 0) ok,"
            " COALESCE(SUM(row_error), 0) er, COALESCE(SUM(row_review), 0) rv,"
            " COUNT(*) n FROM csv_import_jobs")).mappings().first()
        # 현재 카탈로그 실측 — 배치 합과 다를 수 있다(재실행 upsert·삭제 없음)
        cur = conn.execute(text(
            "SELECT count(*) tot, count(*) FILTER (WHERE data_origin='real') real,"
            " count(*) FILTER (WHERE data_origin='demo') demo FROM products")).mappings().first()

    return {
        "items": [{
            "job_id": r["job_id"], "file": r["file_name"],
            "source": r["source"], "source_label": SOURCE_LABELS.get(r["source"], r["source"] or "—"),
            "origin": r["data_origin"],
            "origin_label": ORIGIN_LABELS.get(r["data_origin"], r["data_origin"]),
            "total": r["row_total"], "ok": r["row_ok"], "error": r["row_error"],
            "review": r["row_review"], "status": r["status"],
            "operator": r["operator"], "at": iso(r["created_at"]),
            "err_rows": r["err_rows"], "kept_rows": r["kept_rows"],
        } for r in rows],
        "summary": {"batches": agg["n"], "total": agg["t"], "ok": agg["ok"],
                    "error": agg["er"], "review": agg["rv"],
                    "catalog": cur["tot"], "real": cur["real"], "demo": cur["demo"]},
        "note": ("배치 합과 현재 카탈로그 수가 다를 수 있습니다 — 적재는 product_code 기준"
                 " upsert이고 삭제가 없어 재실행분이 합에 중복 계상됩니다."
                 " **성공 행의 원본은 저장하지 않습니다**(원본 CSV가 정본 · 용량 중복 회피) —"
                 " 원본 셀은 적재가 거부한 행만 볼 수 있습니다."),
    }


@router.get("/import-jobs/{job_id}/rows")
def job_rows(job_id: int, limit: int = 100):
    limit = max(1, min(limit, 500))
    with engine.connect() as conn:
        job = conn.execute(text(
            "SELECT job_id, file_name, row_total, row_ok, row_error, row_review, source,"
            " data_origin, created_at FROM csv_import_jobs WHERE job_id = :i"),
            {"i": job_id}).mappings().first()
        if job is None:
            raise HTTPException(404, "배치가 없습니다")
        errs = conn.execute(text(
            "SELECT error_id, row_no, raw_row, reason FROM csv_import_errors"
            " WHERE job_id = :i ORDER BY row_no LIMIT :lim"),
            {"i": job_id, "lim": limit}).mappings().all()
        kept = conn.execute(text(
            "SELECT p.import_id, p.product_code, p.raw_row, pr.sku, pr.product_name"
            " FROM product_imports p LEFT JOIN products pr USING (product_code)"
            " WHERE p.job_id = :i ORDER BY p.import_id LIMIT :lim"),
            {"i": job_id, "lim": limit}).mappings().all()

    def cells(raw):
        """원본 셀을 그대로 — 값이 있는 칸만(32컬럼 중 빈 칸을 나열하면 읽을 수 없다)."""
        if not raw:
            return []
        return [{"col": k, "value": str(v)[:120]} for k, v in raw.items()
                if v not in (None, "", [])][:14]

    rows = [{
        "kind": "error", "row_no": e["row_no"], "sku": None,
        "reason": e["reason"], "cells": cells(e["raw_row"]),
    } for e in errs] + [{
        "kind": "kept", "row_no": None, "sku": e["sku"],
        "reason": f"적재됨 — {e['product_name'][:40]}" if e["product_name"] else "적재됨",
        "cells": cells(e["raw_row"]),
    } for e in kept]

    return {
        "job": {"job_id": job["job_id"], "file": job["file_name"],
                "total": job["row_total"], "ok": job["row_ok"],
                "error": job["row_error"], "review": job["row_review"],
                "source": job["source"], "origin": job["data_origin"],
                "at": iso(job["created_at"])},
        "rows": rows,
        "shown": {"error": len(errs), "kept": len(kept)},
        "note": ("원본 셀은 **적재가 거부한 행**만 보관합니다 — 성공 행 원문은 저장하지 않고"
                 " 원본 CSV를 정본으로 둡니다(용량 중복 회피). 성공 행은 상품 목록에서"
                 " SKU로 조회하세요. 값이 있는 칸만 표시합니다(32컬럼 중)."),
    }
