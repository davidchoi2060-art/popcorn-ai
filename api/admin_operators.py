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
# 빈 값의 이유(로그인 방식·승인)는 **내 정보와 같은 판정을 쓴다**(슬라이스 100 4/4).
# 여기서 다시 구현하면 문구를 고칠 때 한쪽만 고치는 사고가 난다 — 실제로 이 화면은
# 같은 두 필드를 `—`로 보여 주고 있었다.
from .admin_profile import identity_reasons
from .auth import ROLE_RANK, current_operator
from .db import engine

router = APIRouter(prefix="/api/admin")

ROLE_KO = {"viewer": "조회", "operator": "운영자", "owner": "관리자"}


def _pending_note(rows) -> str:
    """승인 대기 안내문 — **승인 판단의 근거이므로 서버가 말한다.**

    화면은 오래 "직원이 회사 계정으로 **본인 확인을 마친** 신청입니다"라고 적어 왔다.
    dev 어댑터에서는 본인 확인이 일어나지 않는다(`"@" in email`만 본다). owner는 그 문장을
    읽고 신원이 확인된 줄 알고 승인한다 — **승인 게이트의 근거가 거짓 전제 위에 있었다.**
    그래서 문구를 실제 신청 상태에서 파생시킨다: 실 OAuth가 붙어 검증이 실제로 일어나면
    문구가 저절로 바뀐다(손으로 고쳐야 하는 문장은 언젠가 사실과 어긋난다).
    """
    pend = [r for r in rows if r["status"] == "대기"]
    if not pend:
        return "대기 중인 신청이 없습니다."
    bad = [r for r in pend if not identity_reasons(r)["provider_verified"]]
    if bad:
        return (f"신청 {len(pend)}건 중 {len(bad)}건은 신원이 검증되지 않은 신청입니다"
                " — 지금은 신청자가 입력한 이메일을 그대로 신원으로 받습니다(dev 어댑터)."
                " 승인 전에 본인에게 직접 확인하십시오."
                " 승인하면 그 순간부터 접근됩니다.")
    return ("회사 계정으로 본인 확인을 마친 신청입니다."
            " 권한을 정해 승인하면 그 순간부터 접근됩니다.")


@router.get("/operators")
def list_operators():
    with engine.connect() as conn:
        # 집계는 상관 서브쿼리로 — 로그·세션을 함께 JOIN하면 두 집합의 곱이 되어
        # 작업 수·세션 수가 동시에 부풀어 오른다(실제로 1,320으로 뻥튄 것을 보고 고쳤다).
        rows = conn.execute(text(
            "SELECT o.operator_id, o.name, o.email, o.role, o.status, o.provider, o.phone,"
            " o.duty, o.created_at, o.approved_at, o.approved_by, o.last_login_at,"
            " a.name AS approver,"
            " (SELECT COUNT(*) FROM admin_operator_activity_logs l"
            "    WHERE l.operator_id = o.operator_id) AS acts,"
            " (SELECT COUNT(*) FROM admin_sessions s"
            "    WHERE s.operator_id = o.operator_id"
            "      AND s.revoked_at IS NULL AND s.expires_at > now()) AS live_sessions,"
            # 비밀번호가 없으면 **로그인 자체가 안 된다**(슬라이스 70). 화면이 그걸 알아야
            # owner가 누구에게 발급해야 하는지 안다.
            " (o.password_hash IS NOT NULL) AS has_password, o.must_change_password,"
            " (o.locked_until IS NOT NULL AND o.locked_until > now()) AS is_locked"
            " FROM admin_operators o"
            " LEFT JOIN admin_operators a ON a.operator_id = o.approved_by"
            " ORDER BY (o.status='대기') DESC, o.operator_id")).mappings().all()
    me = current_operator() or {}
    return {"items": [{
        "id": r["operator_id"], "name": r["name"], "email": r["email"],
        "role": r["role"], "role_label": ROLE_KO.get(r["role"], r["role"]),
        # 표시용 '—'를 데이터에 담지 않는다 — 값이 없다는 사실은 null이 말하고,
        # 왜 없는지는 identity_reasons가 문장으로 말한다(슬라이스 100 4/4와 같은 원천).
        "status": r["status"], "provider": r["provider"],
        "phone": r["phone"], "duty": r["duty"],
        "joined": iso(r["created_at"]),
        "approved_at": iso(r["approved_at"]) if r["approved_at"] else None,
        "approver": r["approver"], "acts": r["acts"], "live_sessions": r["live_sessions"],
        "last_login": iso(r["last_login_at"]) if r["last_login_at"] else None,
        "is_me": r["operator_id"] == me.get("operator_id"),
        "has_password": bool(r["has_password"]),
        "must_change_password": bool(r["must_change_password"]),
        "is_locked": bool(r["is_locked"]),
        **identity_reasons(r),
    } for r in rows], "me": me,
        "pending_note": _pending_note(rows),
        "note": ("승인 전 계정은 어떤 데이터도 볼 수 없습니다 · 정지 시 진행 중 세션이 즉시 끊깁니다"
                 " · 자기 계정의 강등·정지는 막혀 있습니다(스스로 잠기는 것 방지)"
                 " · 비밀번호는 해시로만 보관합니다(원문은 저장하지 않습니다)"
                 " · 비밀번호가 없는 계정은 로그인할 수 없습니다 — owner가 발급해야 합니다")}


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


# ---- 슬라이스 73: 운영자 이메일 정정 ----
# 신청 화면에서 오타가 난 계정이 실제로 있었다(lsa@proteam13@@ — @가 두 번).
# 이메일은 **로그인 신원**이라 형식이 깨지면 그 사람은 영영 못 들어온다.
# 계정을 지우고 다시 신청하게 할 수도 있지만, 승인 이력과 권한이 함께 사라진다.
#
# 신원을 바꾸는 일이므로 owner만, 그리고 **비밀번호는 함께 지운다** —
# 바뀐 주소의 주인이 정말 그 사람인지 다시 확인받아야 한다.


class FixEmailBody(BaseModel):
    email: str


@router.post("/operators/{operator_id}/email")
def fix_email(operator_id: int, body: FixEmailBody):
    from .admin_orders import _log

    me = current_operator() or {}
    if me.get("role") != "owner":
        raise HTTPException(403, "관리자(owner)만 정정할 수 있습니다")
    new = (body.email or "").strip().lower()
    # 형식 검사 — 느슨하게 보되 '@가 하나' 같은 최소 조건은 지킨다
    if new.count("@") != 1 or new.startswith("@") or new.endswith("@"):
        raise HTTPException(400, "이메일 형식이 올바르지 않습니다")
    local, _, domain = new.partition("@")
    if not local or "." not in domain or domain.endswith("."):
        raise HTTPException(400, "이메일 형식이 올바르지 않습니다")

    with engine.begin() as conn:
        cur = conn.execute(text(
            "SELECT email, name, status FROM admin_operators WHERE operator_id=:i"
            " FOR UPDATE"), {"i": operator_id}).mappings().first()
        if cur is None:
            raise HTTPException(404, "운영자가 없습니다")
        if cur["email"] and cur["email"].lower() == new:
            raise HTTPException(400, "같은 이메일입니다")
        dup = conn.execute(text(
            "SELECT operator_id FROM admin_operators WHERE lower(email)=:e"
            "   AND operator_id <> :i"), {"e": new, "i": operator_id}).scalar()
        if dup:
            raise HTTPException(409, "이미 쓰는 이메일입니다")

        conn.execute(text(
            "UPDATE admin_operators SET email=:e, provider_uid=:e,"
            # 신원이 바뀌었으니 비밀번호는 무효로 둔다 — 새 주소의 주인이 맞는지
            # owner가 다시 발급하며 확인한다
            " password_hash=NULL, password_set_at=NULL, must_change_password=false,"
            " login_fail_count=0, locked_until=NULL"
            " WHERE operator_id=:i"), {"e": new, "i": operator_id})
        # 쓰던 세션도 끊는다(옛 신원으로 열린 세션이다)
        killed = conn.execute(text(
            "UPDATE admin_sessions SET revoked_at=now()"
            " WHERE operator_id=:i AND revoked_at IS NULL"),
            {"i": operator_id}).rowcount
        _log(conn, "operator_email_fix", cur["name"],
             {"operator_id": operator_id, "from": cur["email"], "to": new,
              "sessions_killed": killed}, kind="operator")
    return {"ok": True, "email": new, "sessions_killed": killed,
            "note": (cur["name"] + " 님의 이메일을 정정했습니다."
                     " 비밀번호가 초기화됐으니 다시 발급해 주세요.")}
