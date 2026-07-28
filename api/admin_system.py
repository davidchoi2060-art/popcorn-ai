"""시스템 3화면(운영자·권한 / AI 사용량·비용 / 일괄 등록 이력) — 읽기 전용.

원천 실태(슬라이스 31 조사): admin_operators 1행(시드 관리자) / api_cost_logs·cost_thresholds
0행(LLM 연동 보류 — 결정 2026-07-21) / csv_import_jobs·csv_import_errors 0행(T0 CSV 파이프라인
미구현). 실집계가 가능한 것만 실값으로 주고, 나머지는 **값 대신 상태(empty)와 사유**를 준다 —
화면이 "0"을 성과처럼 보여주지 않게 하기 위함(0건과 원천 부재는 다르다).

운영자 화면은 실데이터가 있으므로 실집계한다: 계정 목록 + **활동 로그 기반 실작업량**
(전체·최근 7일·마지막 활동). 권한 3단계(조회/운영자/관리자)는 확정된 정책이나 실제 권한 검사는
미구현(mock 인증) — 화면에 정직 표기.
"""
from fastapi import APIRouter
from sqlalchemy import text

from .timeutil import iso
from .db import engine

router = APIRouter(prefix="/api/admin")

ROLE_KO = {"owner": "관리자", "operator": "운영자", "viewer": "조회"}
ROLE_NOTE = ("권한 3단계(조회/운영자/관리자)는 확정된 정책이지만 실제 권한 검사는 아직 없습니다"
             " — 현재 모든 쓰기는 시드 운영자(operator_id=1)로 기록됩니다(실 인증 이관).")


@router.get("/system")
def system():
    with engine.connect() as conn:
        ops = conn.execute(text(
            "SELECT o.operator_id, o.name, o.email, o.role, o.status, o.created_at,"
            " COUNT(l.log_id) AS acts,"
            " COUNT(l.log_id) FILTER (WHERE l.created_at >= now() - interval '7 days') AS acts7,"
            " MAX(l.created_at) AS last_at"
            " FROM admin_operators o"
            " LEFT JOIN admin_operator_activity_logs l USING (operator_id)"
            " GROUP BY o.operator_id, o.name, o.email, o.role, o.status, o.created_at"
            " ORDER BY o.operator_id")).mappings().all()
        ai_rows = conn.execute(text("SELECT COUNT(*) FROM api_cost_logs")).scalar_one()
        thresholds = conn.execute(text("SELECT COUNT(*) FROM cost_thresholds")).scalar_one()
        jobs = conn.execute(text("SELECT COUNT(*) FROM csv_import_jobs")).scalar_one()
        job_rows = conn.execute(text(
            "SELECT job_id, file_name, row_total, row_ok, row_error, status, created_at"
            " FROM csv_import_jobs ORDER BY job_id DESC LIMIT 20")).mappings().all()
        imports = conn.execute(text("SELECT COUNT(*) FROM product_imports")).scalar_one()

    return {
        "operators": {
            "rows": [{
                "id": o["operator_id"], "name": o["name"], "email": o["email"],
                "role": o["role"], "role_label": ROLE_KO.get(o["role"], o["role"]),
                "status": o["status"], "joined": iso(o["created_at"]),
                "acts": o["acts"], "acts7": o["acts7"],
                "last_at": iso(o["last_at"]) if o["last_at"] else None,
            } for o in ops],
            "note": ROLE_NOTE,
        },
        "ai_cost": {
            "empty": ai_rows == 0, "log_rows": ai_rows, "threshold_rows": thresholds,
            "reason": ("실제 LLM 연동이 보류 상태(2026-07-21 결정)라 사용량·비용 기록이 없습니다."
                       " 착수 시 팝콘톡 한정으로 공개하고, 일 캡·초과 시 동작(배치 연기)을"
                       " cost_thresholds에 등록하면 이 화면이 실값으로 채워집니다."),
        },
        "imports": {
            "empty": jobs == 0, "jobs": jobs, "raw_rows": imports,
            "rows": [{
                "job_id": j["job_id"], "file": j["file_name"], "total": j["row_total"],
                "ok": j["row_ok"], "error": j["row_error"], "status": j["status"],
                "at": iso(j["created_at"]),
            } for j in job_rows],
            "reason": ("CSV 일괄 적재(T0) 파이프라인이 아직 없습니다 — 현재 상품은 시드와"
                       " 단가표 편입(ADM-SRC-020 경로)으로 들어옵니다."
                       " 적재를 붙이면 이 화면이 배치 이력으로 채워집니다."),
        },
    }
