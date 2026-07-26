"""ADM-SYS-010 운영 전환 설정 — 5종 스위치 (슬라이스 44).

**이 화면은 주문·결제 흐름을 실제로 바꾼다.** `pay='mall'`이면 `/api/orders`가 409로
자체 결제를 거부하고(orders.py), 고객 S4가 쇼핑몰 인계 화면으로 간다. 그래서 정책 발행급
행위로 다루고 **owner 전용**으로 게이트한다(auth.required_role).

**상호 제약을 서버가 최종 방어한다**(목업 `enforce()`와 같은 규칙):
  · `settle`은 `pay`를 따른다 — 결제 주체가 정산 주체다.
  · `refund='own'`은 `pay='own'`일 때만 — 쇼핑몰 결제 건은 PG 취소 권한이 없다.
화면에도 같은 보정이 있지만 그건 UX다. API를 직접 부르면 모순 상태를 만들 수 있으므로
서버가 다시 강제한다(클라이언트를 신뢰하지 않는다).

변경은 **삭제 없는 원장**을 따른다: before 스냅샷을 활동 로그에 남기고 undo는 그 스냅샷으로
되돌린다(가격·재고와 같은 방식).

**되돌림 역참조 키는 `ref_log_id`다**(프로젝트 규약). 활동 로그 화면이 이 키로 '되돌려짐'
배지를 파생하므로 다른 이름을 쓰면 되돌림 행과 원본이 1:1로 맞지 않는다 —
슬라이스 44에서 `undo_of`로 썼다가 회귀 세트가 잡아냈다.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from .admin_orders import _log
from .db import engine

router = APIRouter(prefix="/api/admin")

KEYS = ("member", "pay", "settle", "ship", "refund")
LABELS = {"member": "회원·가입", "pay": "결제", "settle": "정산", "ship": "배송", "refund": "환불"}
MODE_LABELS = {"own": "자체", "mall": "쇼핑몰 인계"}

# 화면 프리셋과 같은 정의(참고용으로 응답에 실어 화면이 서버와 어긋나지 않게 한다)
PRESETS = [
    {"key": "current", "label": "현행(쇼핑몰 중심)",
     "modes": {"member": "own", "pay": "mall", "settle": "mall", "ship": "mall", "refund": "mall"}},
    {"key": "own_pay", "label": "자체 결제 전환",
     "modes": {"member": "own", "pay": "own", "settle": "own", "ship": "mall", "refund": "own"}},
    {"key": "full_own", "label": "전면 자체 운영",
     "modes": {"member": "own", "pay": "own", "settle": "own", "ship": "own", "refund": "own"}},
]


def _read(conn) -> dict:
    return dict(conn.execute(text("SELECT key, mode FROM ops_settings")).all())


def _enforce(modes: dict) -> tuple:
    """상호 제약 적용 — (보정된 modes, 보정 사유 목록)."""
    notes = []
    if modes.get("settle") != modes.get("pay"):
        modes["settle"] = modes["pay"]
        notes.append("정산은 결제 주체를 따릅니다 — 결제와 동일하게 보정했습니다")
    if modes.get("refund") == "own" and modes.get("pay") != "own":
        modes["refund"] = "mall"
        notes.append("쇼핑몰 결제 건은 PG 취소 권한이 없어 환불도 쇼핑몰 창구로 보정했습니다")
    return modes, notes


def _effects(modes: dict) -> list:
    """이 설정이 실제로 무엇을 바꾸는가 — 화면 '예상 영향'과 같은 문장."""
    own_pay = modes.get("pay") == "own"
    return [
        {"where": "S4 결제 화면",
         "effect": "자체 결제창(배송지·결제수단 입력)" if own_pay else "쇼핑몰 인계 화면"},
        {"where": "주문 생성 API",
         "effect": "허용" if own_pay else "409 거부 — 자체 결제 불가(쇼핑몰 인계 모드)"},
        {"where": "재고 예약(hold)",
         "effect": "활성 — 결제 중 임시 점유" if own_pay else "비활성 — 쇼핑몰 재고 로직"},
        {"where": "가입 흐름",
         "effect": "독립 가입" if modes.get("member") == "own" else "쇼핑몰 계정 매핑 생성"},
        {"where": "배송 추적",
         "effect": "마이페이지 + 배송 관리" if modes.get("ship") == "own" else "쇼핑몰 배송 조회 링크"},
        {"where": "환불 접수",
         "effect": "마이페이지 → 환불·클레임" if modes.get("refund") == "own" else "쇼핑몰 CS 창구"},
        {"where": "정산 마감",
         "effect": "결제·정산 화면에서 일 마감" if modes.get("settle") == "own" else "쇼핑몰 정산 합산"},
    ]


@router.get("/ops-settings")
def get_ops():
    with engine.connect() as conn:
        modes = _read(conn)
        rows = conn.execute(text(
            "SELECT key, mode, updated_at FROM ops_settings ORDER BY key")).mappings().all()
        hist = conn.execute(text(
            "SELECT l.log_id, l.action, l.detail, l.created_at, o.name AS operator,"
            " EXISTS (SELECT 1 FROM admin_operator_activity_logs u"
            "         WHERE u.detail->>'ref_log_id' = l.log_id::text) AS undone"
            " FROM admin_operator_activity_logs l"
            " LEFT JOIN admin_operators o USING (operator_id)"
            " WHERE l.target_kind = 'ops' ORDER BY l.log_id DESC LIMIT 20")).mappings().all()
    return {
        "modes": modes,
        "items": [{"key": r["key"], "label": LABELS.get(r["key"], r["key"]),
                   "mode": r["mode"], "mode_label": MODE_LABELS.get(r["mode"], r["mode"]),
                   "updated_at": r["updated_at"].isoformat()} for r in rows],
        "presets": PRESETS,
        "effects": _effects(dict(modes)),
        # 되돌림 행도 '무엇을 되돌렸는지'를 내려준다 — 화면에 '—'만 남으면 이력이 아니다
        "history": [{"log_id": h["log_id"], "action": h["action"],
                     "operator": h["operator"], "at": h["created_at"].isoformat(),
                     "changed": ((h["detail"] or {}).get("changed")
                                 or (h["detail"] or {}).get("restored")),
                     "undo_of": (h["detail"] or {}).get("ref_log_id"),
                     "undone": h["undone"]} for h in hist],
        "note": ("이 설정은 주문·결제 흐름을 실제로 바꿉니다 — 결제를 '쇼핑몰 인계'로 두면"
                 " 자체 주문 생성이 409로 거부됩니다. 정산은 결제 주체를 따르고,"
                 " 환불 '자체'는 결제가 '자체'일 때만 가능합니다(서버가 강제)."),
    }


class OpsBody(BaseModel):
    modes: dict


@router.post("/ops-settings")
def set_ops(body: OpsBody):
    want = {k: str(v).strip() for k, v in (body.modes or {}).items() if k in KEYS}
    if not want:
        raise HTTPException(400, "변경할 항목이 없습니다")
    bad = [f"{k}={v}" for k, v in want.items() if v not in ("own", "mall")]
    if bad:
        raise HTTPException(400, f"알 수 없는 모드: {', '.join(bad)}")

    with engine.begin() as conn:
        before = _read(conn)
        merged = {**before, **want}
        merged, notes = _enforce(merged)
        changed = {k: {"from": before.get(k), "to": merged[k]}
                   for k in KEYS if before.get(k) != merged.get(k)}
        if not changed:
            return {"ok": True, "modes": merged, "changed": {}, "notes": notes,
                    "message": "변경된 항목이 없습니다"}
        for k, v in changed.items():
            conn.execute(text(
                "UPDATE ops_settings SET mode = :m, updated_at = now() WHERE key = :k"),
                {"m": v["to"], "k": k})
        log_id = _log(conn, "ops_change", ",".join(sorted(changed)),
                      {"changed": changed, "before": before, "notes": notes}, kind="ops")
        return {"ok": True, "modes": merged, "changed": changed, "notes": notes,
                "undo_id": log_id, "effects": _effects(merged),
                "message": f"{len(changed)}개 항목 전환 — 즉시 적용됩니다"}


@router.post("/ops-settings/undo/{log_id}")
def undo_ops(log_id: int):
    """before 스냅샷으로 되돌린다(블라인드 복원이 아니라 기록된 값으로)."""
    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT detail FROM admin_operator_activity_logs"
            " WHERE log_id = :i AND action = 'ops_change'"), {"i": log_id}).mappings().first()
        if row is None:
            raise HTTPException(404, "되돌릴 변경 기록이 없습니다")
        if conn.execute(text(
                "SELECT 1 FROM admin_operator_activity_logs"
                " WHERE detail->>'ref_log_id' = :i LIMIT 1"), {"i": str(log_id)}).first():
            raise HTTPException(409, "이미 되돌린 변경입니다")
        before = (row["detail"] or {}).get("before") or {}
        if not before:
            raise HTTPException(409, "이전 값 기록이 없어 되돌릴 수 없습니다")
        now = _read(conn)
        restored = {k: {"from": now.get(k), "to": before[k]}
                    for k in KEYS if k in before and now.get(k) != before[k]}
        for k, v in restored.items():
            conn.execute(text(
                "UPDATE ops_settings SET mode = :m, updated_at = now() WHERE key = :k"),
                {"m": v["to"], "k": k})
        _log(conn, "ops_change_undo", ",".join(sorted(restored)) or "-",
             {"ref_log_id": log_id, "restored": restored}, kind="ops")
        return {"ok": True, "restored": restored, "modes": _read(conn)}
