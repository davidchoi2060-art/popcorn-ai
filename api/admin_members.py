"""ADM-CUS-010 회원 관리 — 자체 회원 원장 읽기 + 쇼핑몰 계정 매핑 요청(쓰기 1종).

매핑 상태 3종(스키마가 요구하는 정직 확장 — 목업은 2상태였음):
  mapped    = mall_member_id 존재(매핑 완료)
  requested = mall_map_requested_at만 존재(동의 대기 — ADM-CUS-010 발송, 고객 수용 경로는 미구현)
  none      = 미연결
**실제 매핑 완료(mall_member_id 쓰기)는 범위 밖** — 동의 수용 경로(MY-010) 부재 상태에서
관리자가 임의 기입하면 가짜 원장(슬라이스 19 "S2 소비 범위 밖"과 동형).
매핑 요청은 운영 모드(member)와 무관하게 발송 기록 허용(사용자 확정) — own 모드에서는
"연동 모드 전환 시 고객에게 표시"를 정직 표기(응답 member_mode로 화면 분기).
이메일 원문 노출(사용자 확정 — 기존 관리자 화면 정합, 마스킹은 실 인증·권한 체계 시 재결정).
consults 집계는 실질 공허: recommend가 member_id NULL 고정(S1 = 로그인 전) — 시드 귀속분만.
note는 서버 파생 문장(손글 서술 저장처 없음). 이관: 회원 딥링크·status UI·검색/페이지네이션.
"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from .timeutil import iso
from .admin_orders import _log
from .auth import current_operator_id
from .db import engine

router = APIRouter(prefix="/api/admin")

VIA_KO = {"email": "이메일", "kakao": "카카오", "naver": "네이버"}


def _note(r) -> str:
    parts = []
    if r["mall_member_id"]:
        parts.append(f"쇼핑몰 계정 매핑 완료 — {r['mall_member_id']}")
    elif r["requested_at"]:
        parts.append("매핑 요청 발송 — 고객 동의 대기")
    else:
        parts.append("쇼핑몰 계정 미연결 — 매핑 요청 미발송")
    if r["alerts"]:
        parts.append(f"가격 알림 {r['alerts']}건 활성")
    if r["orders"]:
        parts.append(f"주문 {r['orders']}건")
    return " · ".join(parts)


@router.get("/members")
def list_members():
    q = text("""
        SELECT m.member_id, m.nickname, m.email, m.joined_via, m.created_at,
               m.mall_member_id, m.mall_map_requested_at AS requested_at,
               COALESCE(o.cnt,0) AS orders, o.last_at AS o_last,
               COALESCE(c.cnt,0) AS consults, c.last_at AS c_last,
               COALESCE(r.cnt,0) AS reviews, r.last_at AS r_last,
               COALESCE(f.cnt,0) AS favs, COALESCE(f.alerts,0) AS alerts, f.last_at AS f_last
        FROM members m
        LEFT JOIN (SELECT member_id, COUNT(*) cnt, MAX(created_at) last_at
                   FROM orders GROUP BY member_id) o USING (member_id)
        LEFT JOIN (SELECT member_id, COUNT(*) cnt, MAX(created_at) last_at
                   FROM consult_sessions WHERE member_id IS NOT NULL GROUP BY member_id) c USING (member_id)
        LEFT JOIN (SELECT member_id, COUNT(*) cnt, MAX(created_at) last_at
                   FROM member_reviews GROUP BY member_id) r USING (member_id)
        LEFT JOIN (SELECT member_id, COUNT(*) cnt,
                          COUNT(*) FILTER (WHERE price_alert) alerts, MAX(created_at) last_at
                   FROM member_favorites GROUP BY member_id) f USING (member_id)
        ORDER BY m.member_id
    """)
    with engine.connect() as conn:
        rows = conn.execute(q).mappings().all()
        mode = dict(conn.execute(text("SELECT key, mode FROM ops_settings")).all()).get("member", "own")
    items = []
    for r in rows:
        last = max((t for t in (r["o_last"], r["c_last"], r["r_last"], r["f_last"]) if t), default=None)
        state = "mapped" if r["mall_member_id"] else ("requested" if r["requested_at"] else "none")
        items.append({
            "id": r["member_id"], "name": r["nickname"], "email": r["email"],
            "via": VIA_KO.get(r["joined_via"], r["joined_via"]), "joined": iso(r["created_at"]),
            "map_state": state, "mall_id": r["mall_member_id"],
            "requested_at": iso(r["requested_at"]) if r["requested_at"] else None,
            "orders": r["orders"], "consults": r["consults"], "reviews": r["reviews"],
            "favs": r["favs"], "alerts": r["alerts"],
            "last": iso(last) if last else None,
            "note": _note(r),
        })
    return {"items": items, "member_mode": mode}


@router.post("/members/{member_id}/map-request")
def map_request(member_id: int):
    with engine.begin() as conn:
        m = conn.execute(text(
            "SELECT member_id, nickname, mall_member_id, mall_map_requested_at FROM members"
            " WHERE member_id=:i FOR UPDATE"), {"i": member_id}).mappings().first()
        if m is None:
            raise HTTPException(404, "회원이 없습니다")
        if m["mall_member_id"]:
            raise HTTPException(409, "이미 쇼핑몰 계정이 매핑된 회원입니다")
        if m["mall_map_requested_at"]:
            raise HTTPException(409, "이미 매핑 요청이 발송된 회원입니다(동의 대기)")
        conn.execute(text(
            "UPDATE members SET mall_map_requested_at=now() WHERE member_id=:i"), {"i": member_id})
        mode = dict(conn.execute(text("SELECT key, mode FROM ops_settings")).all()).get("member", "own")
        log_id = _log(conn, "member_map_request", str(member_id),
                      {"member_id": member_id, "nickname": m["nickname"],
                       "before": {"mall_map_requested_at": None}}, kind="member")
        return {"ok": True, "undo_id": log_id, "member_mode": mode}


@router.post("/members/map-request/undo/{log_id}")
def undo_map_request(log_id: int):
    with engine.begin() as conn:
        log = conn.execute(text(
            "SELECT action, detail FROM admin_operator_activity_logs WHERE log_id=:i"),
            {"i": log_id}).mappings().first()
        if log is None or log["action"] != "member_map_request":
            raise HTTPException(404, "되돌릴 발송 기록이 없습니다")
        if conn.execute(text(
                "SELECT 1 FROM admin_operator_activity_logs"
                " WHERE action='member_map_request_undo' AND (detail->>'ref_log_id')::int=:i LIMIT 1"),
                {"i": log_id}).first():
            raise HTTPException(409, "이미 되돌린 발송입니다")
        d = log["detail"]
        m = conn.execute(text(
            "SELECT mall_member_id, mall_map_requested_at FROM members WHERE member_id=:i FOR UPDATE"),
            {"i": d["member_id"]}).mappings().first()
        if m is None or m["mall_member_id"] or m["mall_map_requested_at"] is None:
            raise HTTPException(409, "발송 이후 상태가 변경되어 되돌릴 수 없습니다")
        conn.execute(text(
            "UPDATE members SET mall_map_requested_at=NULL WHERE member_id=:i"), {"i": d["member_id"]})
        _log(conn, "member_map_request_undo", str(log_id),
             {"ref_log_id": log_id, "member_id": d["member_id"]}, kind="member")
        return {"ok": True}
