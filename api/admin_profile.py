"""ADM-SYS-022 내 정보 — 운영자 자기 계정 조회·수정 (슬라이스 92).

**이 화면은 새로 생긴 약속이 아니다.** 상단바 프로필 드롭다운의 `내 정보`가 30개 화면에
이미 있었는데 전부 `href="#!"`인 죽은 링크였다. 이 모듈이 그 약속을 지킨다.

■ 자기 것만, 그것도 일부만 고친다
운영자·권한(ADM-SYS-020)은 **owner가 남을** 관리하는 화면이고, 여기는 **본인이 자기를** 보는
화면이다. 그래서 고칠 수 있는 필드를 셋으로 못박는다 — `name` · `phone` · `duty`.

  role/status  자기 권한 상승·정지 해제를 막는다. 승인 게이트의 의미가 사라진다.
  email        **로그인 신원 그 자체다**(dev 어댑터든 OAuth든 이메일로 계정을 찾는다).
               본인이 바꾸면 계정이 통째로 다른 사람에게 옮겨간다. 정정은 owner 경로
               (`/operators/{id}/email`, 슬라이스 73)로만 한다.

■ 모르는 필드는 조용히 무시하지 않고 거절한다(`extra="forbid"`)
`{"name":"x","role":"owner"}`를 보냈을 때 role만 버리고 200을 주면 **보낸 쪽은 성공했다고
믿는다.** 화면이 죽은 줄 모르고 다른 것을 파는 것과 같은 부류다(슬라이스 58 전례).
422로 거절해서 "그 필드는 여기서 못 고친다"를 분명히 한다.

■ 등급이 아니라 필드가 방벽이다
`required_role`에서 이 경로를 **viewer**로 열어 뒀다. 조회 등급 직원도 자기 이름·연락처는
고칠 수 있어야 하기 때문이다. 권한 상승은 등급이 아니라 위 화이트리스트가 막는다.
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from .admin_orders import _log
from .auth import COOKIE, DEVICE_COOKIE, _schema_ready, current_operator
from .db import engine
from .timeutil import iso

router = APIRouter(prefix="/api/admin")

ROLE_KO = {"viewer": "조회", "operator": "운영자", "owner": "관리자"}

# 본인이 고칠 수 있는 필드 — 이 셋이 전부다. 늘릴 때는 위 주석의 판단을 다시 한다.
EDITABLE = ("name", "phone", "duty")


class ProfileBody(BaseModel):
    # extra="forbid" — 모르는 필드는 거절한다(위 주석 참조). 조용한 무시가 더 위험하다.
    model_config = ConfigDict(extra="forbid")
    name: str
    phone: str | None = None
    duty: str | None = None


# ─────────────── 빈 값에 이유를 적는다 (슬라이스 100 · 4/4) ───────────────
# `—` 하나로 덮으면 **서로 다른 세 사실이 같아 보인다.** 실제로 이 DB에 셋이 다 있었다:
#   #1  시드가 직접 만든 계정      provider NULL · approved_at NULL (신청·승인을 안 거쳤다)
#   #4  부트스트랩 자동 승인       approved_at 있음 · approved_by NULL (사람이 승인 안 했다)
#   #17 아직 승인 대기             approved_at NULL (승인될 차례를 기다린다)
# 판정은 **서버가** 한다 — 화면이 빈 값을 보고 이유를 추측하면 그게 지어낸 근거가 된다.
#
# **`provider`는 요청 본문에서 그대로 들어온다**(`auth.py` 신청 INSERT). 검증이 없다.
# 그래서 'google'을 "Google 계정"이라 적으면 **하지 않은 검증을 주장**하는 것이다.
# 실 OAuth를 붙이는 날 여기의 `verified`와 문구를 함께 고친다 — 이 자리가 그 신호다.
PROVIDER_NONE = ("기록 없음", False,
                 "신청 절차를 거치지 않고 만들어진 계정입니다(시드·부트스트랩)."
                 " 로그인은 이메일과 비밀번호로 합니다.")
PROVIDER_KO = {
    "dev": ("개발용 임시 인증", False,
            "dev 어댑터입니다 — 이메일 입력만으로 통과하며 신원을 검증하지 않습니다."
            " 실 OAuth 전환 전까지 내부 전용입니다."),
    "google": ("Google(신고된 값)", False,
               "클라이언트가 보낸 제공자 이름을 그대로 기록한 값입니다."
               " id_token 검증은 아직 하지 않습니다."),
}


def identity_reasons(r) -> dict:
    """`로그인 방식`·`승인`이 비어 있는 이유를 문장으로 만든다.

    **이 판정의 단일 원천이다.** 운영자·권한(ADM-SYS-020)도 같은 두 필드를 보여 주므로
    그 화면을 고칠 때는 이 함수를 가져다 쓴다 — 같은 판정을 두 번 구현하면 한쪽만
    고치는 사고가 난다(상품 보기·고치기를 한 화면에 둔 것과 같은 이유).
    """
    p = r["provider"]
    if not p:
        label, verified, note = PROVIDER_NONE
    elif p in PROVIDER_KO:
        label, verified, note = PROVIDER_KO[p]
    else:
        # 모르는 값에 PROVIDER_NONE 문구를 붙이면 거짓말이 된다(신청은 거쳤으므로).
        label, verified, note = (
            f"{p}(신고된 값)", False,
            "우리가 아는 제공자 목록에 없는 값입니다 — 검증하지 않았습니다.")

    if r["approved_at"]:
        none_reason = None
        if r["approver"]:
            approved_note = f"승인자: {r['approver']}"
            approved_short = r["approver"]
        elif r["approved_by"]:
            # 승인은 사람이 했는데 그 계정이 지워졌다(슬라이스 78에서 실제로 지웠다).
            approved_note = (f"승인자 계정(#{r['approved_by']})이 남아 있지 않아"
                             " 이름을 찾을 수 없습니다")
            approved_short = "계정 삭제됨"
        else:
            approved_note = ("부트스트랩 자동 승인 — 사람이 승인한 것이 아닙니다"
                             " (ADMIN_BOOTSTRAP_EMAILS의 첫 관리자)")
            approved_short = "부트스트랩(자동)"
    else:
        approved_note = None
        # 표 칸에 문장을 담을 수 없다. 짧은 라벨도 **서버가** 준다 — 화면이 문장을 잘라
        # 만들면 그건 화면이 지어내는 것이고, 문구를 고칠 때 두 곳이 어긋난다(ADM-SYS-020).
        approved_short = "승인 안 됨"
        if r["status"] == "대기":
            none_reason = "승인 대기 중입니다 — 승인되면 그때 시각이 기록됩니다"
        elif r["status"] == "활성":
            # 승인 경로는 항상 approved_at을 넣는다(admin_operators.py). 활성인데 비었다면
            # 신청·승인을 거치지 않고 만들어진 계정이라는 뜻이다.
            none_reason = ("승인 기록 없이 활성입니다"
                           " — 신청·승인을 거치지 않고 만들어진 계정입니다(시드)")
        elif r["status"] == "정지":
            # 승인되기 전에 정지된 계정 — 반려된 신청이 이 모양으로 남는다.
            none_reason = "승인된 적이 없습니다 — 승인 전에 정지된 계정입니다"
        else:
            none_reason = "승인 기록이 없습니다"

    return {"provider_label": label, "provider_verified": verified,
            "provider_note": note, "approved_note": approved_note,
            "approved_none_reason": none_reason, "approved_short": approved_short}


def _row(conn, op_id: int):
    return conn.execute(text(
        "SELECT o.operator_id, o.name, o.email, o.role, o.status, o.provider, o.phone,"
        " o.duty, o.created_at, o.approved_at, o.approved_by, o.last_login_at,"
        " o.password_set_at,"
        " o.must_change_password, o.login_fail_count, a.name AS approver,"
        " (o.password_hash IS NOT NULL) AS has_password,"
        " (o.locked_until IS NOT NULL AND o.locked_until > now()) AS is_locked,"
        " (SELECT COUNT(*) FROM admin_operator_activity_logs l"
        "    WHERE l.operator_id = o.operator_id) AS acts,"
        " (SELECT COUNT(*) FROM admin_sessions s"
        "    WHERE s.operator_id = o.operator_id"
        "      AND s.revoked_at IS NULL AND s.expires_at > now()) AS live_sessions"
        " FROM admin_operators o"
        " LEFT JOIN admin_operators a ON a.operator_id = o.approved_by"
        " WHERE o.operator_id = :id"), {"id": op_id}).mappings().first()


def _shape(r) -> dict:
    return {
        "id": r["operator_id"], "name": r["name"], "email": r["email"],
        "role": r["role"], "role_label": ROLE_KO.get(r["role"], r["role"]),
        # 데이터 필드에 표시용 '—'를 넣지 않는다 — 값이 없다는 사실은 null이 말하고,
        # 왜 없는지는 identity_reasons가 문장으로 말한다.
        "status": r["status"], "provider": r["provider"],
        "phone": r["phone"], "duty": r["duty"],
        "joined": iso(r["created_at"]),
        "approved_at": iso(r["approved_at"]) if r["approved_at"] else None,
        "approver": r["approver"],
        "last_login": iso(r["last_login_at"]) if r["last_login_at"] else None,
        "password_set_at": iso(r["password_set_at"]) if r["password_set_at"] else None,
        "has_password": bool(r["has_password"]),
        "must_change_password": bool(r["must_change_password"]),
        "is_locked": bool(r["is_locked"]),
        "login_fail_count": r["login_fail_count"],
        "acts": r["acts"], "live_sessions": r["live_sessions"],
        # 화면이 무엇을 잠글지 서버가 알려준다 — 화면이 스스로 정하면 서버와 어긋난다.
        "editable": list(EDITABLE),
        # 빈 값의 이유도 같은 원칙이다 — 화면이 추측하지 않고 받아 적는다.
        **identity_reasons(r),
    }


@router.get("/my-profile")
def get_my_profile():
    me = current_operator()
    if not me:
        raise HTTPException(401, "로그인이 필요합니다")
    with engine.connect() as conn:
        r = _row(conn, me["operator_id"])
    if r is None:                     # 세션은 살아 있는데 계정 행이 없다(삭제된 경우)
        raise HTTPException(404, "계정을 찾을 수 없습니다")
    d = _shape(r)
    d["note"] = ("이름·연락처·직무만 본인이 고칠 수 있습니다"
                 " · 이메일은 로그인 신원이라 관리자만 정정합니다"
                 " · 권한 등급은 여기서 바꿀 수 없습니다"
                 " · 비밀번호는 해시로만 보관합니다(원문은 저장하지 않습니다)")
    return d


@router.patch("/my-profile")
def update_my_profile(body: ProfileBody):
    me = current_operator()
    if not me:
        raise HTTPException(401, "로그인이 필요합니다")

    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "이름을 입력하세요")
    if len(name) > 100:
        raise HTTPException(400, "이름은 100자 이하로 입력하세요")
    phone = (body.phone or "").strip() or None
    if phone and len(phone) > 30:
        raise HTTPException(400, "연락처는 30자 이하로 입력하세요")
    duty = (body.duty or "").strip() or None
    if duty and len(duty) > 100:
        raise HTTPException(400, "직무는 100자 이하로 입력하세요")

    with engine.begin() as conn:
        before = _row(conn, me["operator_id"])
        if before is None:
            raise HTTPException(404, "계정을 찾을 수 없습니다")

        changed = {}
        for key, new in (("name", name), ("phone", phone), ("duty", duty)):
            if (before[key] or None) != new:
                changed[key] = {"before": before[key], "after": new}
        if not changed:
            # 바뀐 게 없으면 원장에 남기지 않는다 — '고쳤다'는 기록이 거짓이 된다.
            out = _shape(before)
            out["note"] = "바뀐 값이 없습니다"
            out["changed"] = {}
            return out

        conn.execute(text(
            "UPDATE admin_operators SET name=:n, phone=:p, duty=:d WHERE operator_id=:id"),
            {"n": name, "p": phone, "d": duty, "id": me["operator_id"]})

        # 원문 값을 그대로 남긴다 — 민감정보가 아니고, 무엇이 어떻게 바뀌었는지
        # 나중에 되짚을 수 있어야 한다(비밀번호와는 다르다).
        _log(conn, "operator_self_update", before["email"] or str(me["operator_id"]),
             {"changed": changed}, kind="operator")

        after = _row(conn, me["operator_id"])

    out = _shape(after)
    out["changed"] = changed
    # 이름을 바꾸면 **과거 작업 기록의 표시 이름도 함께 바뀐다**(로그는 operator_id를
    # 참조하고 이름은 조인으로 나온다). 같은 사람이므로 의도된 동작이지만, 화면이
    # 그 사실을 미리 말해야 "예전 기록이 왜 바뀌었지"를 묻지 않는다.
    out["note"] = ("저장했습니다 — " + " · ".join(
        {"name": "이름", "phone": "연락처", "duty": "직무"}[k] for k in changed)
        + (" (이름은 지난 작업 기록의 표시에도 함께 반영됩니다)" if "name" in changed else ""))
    return out


# ---- 슬라이스 100: 다른 기기에서 로그아웃 ----
# 화면이 "열려 있는 세션 21개"라고 정직하게 말하면서 **끊을 수단을 주지 않았다.**
# 공용 PC에서 로그인한 것을 알아차려도 할 수 있는 게 없었다.
#
# ■ 현재 세션은 남긴다 (사용자 결정 2026-07-30)
# "내가 지금 쓰는 것 말고 정리"가 대부분의 의도다. 전부 끊으면 실수로 눌렀을 때
# 대가가 크고, 비밀번호 유출을 의심하는 상황에는 **비밀번호 변경이 더 확실한 조치**이며
# 그건 이미 있다(변경 시 다른 세션이 어떻게 되는지는 슬라이스 70 소관).
#
# ■ 삭제가 아니라 철회다
# `revoked_at`을 남긴다 — 로그아웃(`/auth/logout`)과 같은 방식이다. 행을 지우면
# "언제 어디서 열려 있었나"를 잃는다. `resolve_session`이 revoked를 즉시 무효로 본다.
#
# ■ 되돌리기는 만들지 않는다
# 끊은 세션을 되살리는 것은 보안상 위험하다. 대신 누르기 전에 몇 개가 끊기는지 말한다.


@router.get("/my-profile/sessions")
def my_sessions(request: Request):
    """내 세션 목록 — 누르기 전에 무엇이 끊기는지 보여주기 위한 것."""
    me = current_operator()
    if not me:
        raise HTTPException(401, "로그인이 필요합니다")
    cur = request.cookies.get(COOKIE, "")
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT session_id, created_at, last_seen_at, expires_at, user_agent, login_ip"
            " FROM admin_sessions"
            " WHERE operator_id = :op AND revoked_at IS NULL AND expires_at > now()"
            " ORDER BY last_seen_at DESC"), {"op": me["operator_id"]}).mappings().all()
    items = [{
        # **세션 식별자를 그대로 내보내지 않는다** — 그 값이 곧 로그인 자격이다.
        # 지금 기기인지 구분할 수 있을 만큼만 알려준다.
        "current": r["session_id"] == cur,
        "created": iso(r["created_at"]),
        "last_seen": iso(r["last_seen_at"]),
        "expires": iso(r["expires_at"]),
        "agent": (r["user_agent"] or "")[:120] or None,
        # 접속 IP — 기록만 한다(차단 아님, 2026-08-15 사장님 확정 · api/auth.py
        # _client_ip 참조). 이 컬럼이 생기기 전 로그인이거나 IP를 못 알아낸
        # 경우는 NULL이다 — 화면이 그 이유를 지어내지 않고 null 그대로 받는다.
        "ip": str(r["login_ip"]) if r["login_ip"] is not None else None,
    } for r in rows]
    others = [i for i in items if not i["current"]]
    return {"items": items, "total": len(items), "others": len(others),
            "note": (f"지금 기기를 포함해 {len(items)}개가 열려 있습니다."
                     + (f" [다른 기기에서 로그아웃]을 누르면 {len(others)}개가 끊기고"
                        " 지금 기기는 유지됩니다." if others else " 다른 기기는 없습니다."))}


@router.post("/my-profile/sessions/revoke-others")
def revoke_other_sessions(request: Request):
    me = current_operator()
    if not me:
        raise HTTPException(401, "로그인이 필요합니다")
    cur = request.cookies.get(COOKIE, "")
    with engine.begin() as conn:
        # 현재 세션을 뺀 나머지만. `cur`가 빈 값이면 전부가 대상이 되므로 막는다 —
        # 쿠키 없이 이 경로에 닿는 일은 없어야 하지만, 있으면 자기 세션까지 끊긴다.
        if not cur:
            raise HTTPException(400, "현재 세션을 확인할 수 없습니다")
        n = conn.execute(text(
            "UPDATE admin_sessions SET revoked_at = now()"
            " WHERE operator_id = :op AND session_id <> :cur"
            "   AND revoked_at IS NULL AND expires_at > now()"),
            {"op": me["operator_id"], "cur": cur}).rowcount
        if n:
            _log(conn, "session_revoke_others", me.get("email") or str(me["operator_id"]),
                 {"revoked": n}, kind="operator")
        left = conn.execute(text(
            "SELECT count(*) FROM admin_sessions"
            " WHERE operator_id = :op AND revoked_at IS NULL AND expires_at > now()"),
            {"op": me["operator_id"]}).scalar_one()
    return {"ok": True, "revoked": n, "remaining": left,
            "note": (f"{n}개를 끊었습니다 — 지금 기기는 그대로 쓸 수 있습니다."
                     if n else "끊을 다른 세션이 없습니다.")}


# ---- 2026-08-15: 기기 기억(비밀번호 생략) 목록·철회 ----
# admin_sessions("다른 기기에서 로그아웃", 위)와 같은 결을 따르되 다른 점 하나:
# 세션은 "다른 것 전부"를 한 번에 끊지만, 기기는 **하나씩** 잊는다(사장님 지시
# 원문 "그 기기 잊어버려" — 단수). 그래서 revoke가 device_id 하나를 받는다.


@router.get("/my-profile/devices")
def my_devices(request: Request):
    """기억된 기기 목록 — 시크릿(secret)은 서버도 갖고 있지 않다(해시만 저장,
    api/auth.py `_remember_device` 참조). 여기서 내보내는 `device_id`는 조회용
    식별자일 뿐 그것만으로는 로그인할 수 없다 — 세션 식별자(session_id)와
    달리 노출해도 안전하다.
    """
    me = current_operator()
    if not me:
        raise HTTPException(401, "로그인이 필요합니다")
    if not _schema_ready():
        # 마이그레이션 0051 미적용 — api/auth.py _schema_ready 참조. 화면은
        # "아직 없다"고 정직하게 말한다(0건을 지어내는 것과는 다르다 — 이유가
        # 있는 빈 상태다).
        return {"items": [], "total": 0, "ready": False,
                "note": "기기 기억 기능이 아직 이 서버에 적용되지 않았습니다."}
    cur_device_id = request.cookies.get(DEVICE_COOKIE, "").partition(":")[0]
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT device_id, created_at, last_used_at, expires_at, user_agent"
            " FROM admin_operator_devices"
            " WHERE operator_id = :op AND revoked_at IS NULL AND expires_at > now()"
            " ORDER BY last_used_at DESC"), {"op": me["operator_id"]}).mappings().all()
    items = [{
        "device_id": r["device_id"],
        "current": bool(cur_device_id) and r["device_id"] == cur_device_id,
        "created": iso(r["created_at"]),
        "last_used": iso(r["last_used_at"]),
        "expires": iso(r["expires_at"]),
        "agent": (r["user_agent"] or "")[:120] or None,
    } for r in rows]
    return {"items": items, "total": len(items), "ready": True,
            "note": (f"비밀번호 없이 로그인할 수 있는 기기 {len(items)}개가 등록돼 있습니다."
                     if items else "등록된 기기가 없습니다.")}


@router.post("/my-profile/devices/{device_id}/revoke")
def revoke_device(device_id: str, request: Request):
    """기기 하나를 잊는다 — 삭제가 아니라 철회(`revoked_at`, 되돌림은 삭제가
    아니라 역방향 전이). 지금 열려 있는 세션은 끊지 않는다 — 그 기기로 다음에
    다시 들어올 때부터 비밀번호를 묻는다는 뜻이다(세션 자체를 끊고 싶으면
    위 `/sessions/revoke-others`를 따로 쓴다 — 이 둘은 서로 다른 일이다).
    """
    me = current_operator()
    if not me:
        raise HTTPException(401, "로그인이 필요합니다")
    if not _schema_ready():
        raise HTTPException(404, "기기 기억 기능이 아직 이 서버에 적용되지 않았습니다")
    with engine.begin() as conn:
        n = conn.execute(text(
            "UPDATE admin_operator_devices SET revoked_at = now()"
            " WHERE device_id = :d AND operator_id = :op AND revoked_at IS NULL"),
            {"d": device_id, "op": me["operator_id"]}).rowcount
        if n:
            _log(conn, "device_forget", me.get("email") or str(me["operator_id"]),
                 {"device_id": device_id}, kind="operator")
    if not n:
        raise HTTPException(404, "기기를 찾을 수 없습니다")
    return {"ok": True, "note": "이 기기는 다음부터 로그인할 때 비밀번호를 다시 물어봅니다."}
