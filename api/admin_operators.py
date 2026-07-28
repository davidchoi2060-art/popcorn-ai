"""ADM-SYS-020 운영자·권한 — 승인 게이트 관리 (owner 전용, 슬라이스 37).

권한 3단계(2026-07-14 확정): viewer(조회) / operator(운영자) / owner(관리자 — 정책·규칙 발행).
이 라우터는 미들웨어에서 **owner 전용**으로 게이트된다(auth.required_role).

행위 3종: 승인(대기→활성 + 권한 부여) / 권한 변경 / 정지(활성→정지 + **세션 즉시 무효**).
자기 계정 강등·정지는 막는다(관리자가 스스로를 잠가 시스템에서 잠기는 것을 방지).
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from .timeutil import iso
from .admin_orders import _log
from .auth import ROLE_RANK, current_operator
from .db import engine

router = APIRouter(prefix="/api/admin")

ROLE_KO = {"viewer": "조회", "operator": "운영자", "owner": "관리자"}


@router.get("/operators")
def list_operators():
    with engine.connect() as conn:
        # 집계는 상관 서브쿼리로 — 로그·세션을 함께 JOIN하면 두 집합의 곱이 되어
        # 작업 수·세션 수가 동시에 부풀어 오른다(실제로 1,320으로 뻥튄 것을 보고 고쳤다).
        rows = conn.execute(text(
            "SELECT o.operator_id, o.name, o.email, o.role, o.status, o.provider, o.phone,"
            " o.duty, o.created_at, o.approved_at, o.last_login_at, a.name AS approver,"
            " (SELECT COUNT(*) FROM admin_operator_activity_logs l"
            "    WHERE l.operator_id = o.operator_id) AS acts,"
            " (SELECT COUNT(*) FROM admin_sessions s"
            "    WHERE s.operator_id = o.operator_id"
            "      AND s.revoked_at IS NULL AND s.expires_at > now()) AS live_sessions"
            " FROM admin_operators o"
            " LEFT JOIN admin_operators a ON a.operator_id = o.approved_by"
            " ORDER BY (o.status='대기') DESC, o.operator_id")).mappings().all()
    me = current_operator() or {}
    return {"items": [{
        "id": r["operator_id"], "name": r["name"], "email": r["email"],
        "role": r["role"], "role_label": ROLE_KO.get(r["role"], r["role"]),
        "status": r["status"], "provider": r["provider"] or "—",
        "phone": r["phone"], "duty": r["duty"],
        "joined": iso(r["created_at"]),
        "approved_at": iso(r["approved_at"]) if r["approved_at"] else None,
        "approver": r["approver"], "acts": r["acts"], "live_sessions": r["live_sessions"],
        "last_login": iso(r["last_login_at"]) if r["last_login_at"] else None,
        "is_me": r["operator_id"] == me.get("operator_id"),
    } for r in rows], "me": me,
        "note": ("승인 전 계정은 어떤 데이터도 볼 수 없습니다 · 정지 시 진행 중 세션이 즉시 끊깁니다"
                 " · 자기 계정의 강등·정지는 막혀 있습니다(스스로 잠기는 것 방지)"
                 " · 비밀번호는 저장하지 않습니다(신원은 소셜 제공자가 확인)")}


class ApproveBody(BaseModel):
    role: str = "operator"


@router.post("/operators/{operator_id}/approve")
def approve(operator_id: int, body: ApproveBody):
    if body.role not in ROLE_RANK:
        raise HTTPException(400, f"알 수 없는 권한: {body.role}")
    me = current_operator() or {}
    with engine.begin() as conn:
        o = conn.execute(text(
            "SELECT operator_id, name, email, status, role FROM admin_operators"
            " WHERE operator_id=:i FOR UPDATE"), {"i": operator_id}).mappings().first()
        if o is None:
            raise HTTPException(404, "운영자가 없습니다")
        if o["status"] == "활성":
            raise HTTPException(409, "이미 활성 계정입니다 — 권한 변경을 사용하세요")
        conn.execute(text(
            "UPDATE admin_operators SET status='활성', role=:r, approved_by=:by,"
            " approved_at=now() WHERE operator_id=:i"),
            {"r": body.role, "by": me.get("operator_id"), "i": operator_id})
        _log(conn, "operator_approve", o["email"],
             {"operator_id": operator_id, "email": o["email"], "role": body.role,
              "before": {"status": o["status"], "role": o["role"]}}, kind="operator")
        return {"ok": True, "status": "활성", "role": body.role}


class RoleBody(BaseModel):
    role: str


@router.post("/operators/{operator_id}/role")
def change_role(operator_id: int, body: RoleBody):
    if body.role not in ROLE_RANK:
        raise HTTPException(400, f"알 수 없는 권한: {body.role}")
    me = current_operator() or {}
    if operator_id == me.get("operator_id") and ROLE_RANK[body.role] < ROLE_RANK["owner"]:
        raise HTTPException(409, "자기 계정을 강등할 수 없습니다(스스로 잠기는 것 방지)")
    with engine.begin() as conn:
        o = conn.execute(text(
            "SELECT operator_id, email, role, status FROM admin_operators"
            " WHERE operator_id=:i FOR UPDATE"), {"i": operator_id}).mappings().first()
        if o is None:
            raise HTTPException(404, "운영자가 없습니다")
        if o["status"] != "활성":
            raise HTTPException(409, f"'{o['status']}' 계정의 권한은 변경할 수 없습니다")
        conn.execute(text("UPDATE admin_operators SET role=:r WHERE operator_id=:i"),
                     {"r": body.role, "i": operator_id})
        _log(conn, "operator_role", o["email"],
             {"operator_id": operator_id, "email": o["email"], "role": body.role,
              "before": {"role": o["role"]}}, kind="operator")
        return {"ok": True, "role": body.role}


@router.post("/operators/{operator_id}/suspend")
def suspend(operator_id: int):
    """정지 — 진행 중 세션을 즉시 무효화한다(퇴사·사고 시 접근이 그 순간 끊긴다)."""
    me = current_operator() or {}
    if operator_id == me.get("operator_id"):
        raise HTTPException(409, "자기 계정을 정지할 수 없습니다")
    with engine.begin() as conn:
        o = conn.execute(text(
            "SELECT operator_id, email, status, role FROM admin_operators"
            " WHERE operator_id=:i FOR UPDATE"), {"i": operator_id}).mappings().first()
        if o is None:
            raise HTTPException(404, "운영자가 없습니다")
        if o["status"] == "정지":
            raise HTTPException(409, "이미 정지된 계정입니다")
        owners = conn.execute(text(
            "SELECT COUNT(*) FROM admin_operators WHERE role='owner' AND status='활성'")).scalar_one()
        if o["role"] == "owner" and owners <= 1:
            raise HTTPException(409, "마지막 관리자는 정지할 수 없습니다")
        conn.execute(text("UPDATE admin_operators SET status='정지' WHERE operator_id=:i"),
                     {"i": operator_id})
        killed = conn.execute(text(
            "UPDATE admin_sessions SET revoked_at=now()"
            " WHERE operator_id=:i AND revoked_at IS NULL"), {"i": operator_id}).rowcount
        _log(conn, "operator_suspend", o["email"],
             {"operator_id": operator_id, "email": o["email"], "sessions_killed": killed,
              "before": {"status": o["status"], "role": o["role"]}}, kind="operator")
        return {"ok": True, "status": "정지", "sessions_killed": killed}
