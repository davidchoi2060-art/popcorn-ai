"""ADM-CUS-020 후기 관리 — 노출·신고 처리 + S2 근거 인용 선별.

원칙: 후기 = 구매 인증만(member_reviews.order_item_id NOT NULL이 DB 강제 — 가짜 후기
원천 차단 A-10). 검수 큐(/api/admin/reviews·product_reviews)와는 별개 도메인 —
라우트 /member-reviews·action 어휘 member_review_*로 이름 공간 분리.

전이 가드: hide ← 게시·신고됨 / keep ← 신고됨 / restore ← 숨김 / cite_on·cite_off ← 게시만
(숨김·신고 후기는 인용 불가). **hide 시 cite_s2=false 동반**(숨긴 후기가 S2 근거로 남는
모순 차단 — undo 시 before 스냅샷으로 자동 원복).
cite_s2는 U-02(S2 커뮤니티 근거 소스 — 미정)의 후보 소스 — S2 화면 소비는 미정 해소 전 금지,
여기서는 운영자 선별·집계까지만.
moderation_note는 v1에서 신고 접수 메모 겸 처리 사유(신고 수신함 컬럼화는 ERD 개정 이관).
KPI는 클라 계산(응답 rows 단일 원천). 이관: 신고 접수 파이프라인·페이지네이션.
"""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from .admin_orders import OPERATOR_ID, _log
from .db import engine

router = APIRouter(prefix="/api/admin")

# action → (허용 현재 상태들, 적용 함수 서술)
TRANSITIONS = {
    "hide": ("게시", "신고됨"),
    "keep": ("신고됨",),
    "restore": ("숨김",),
    "cite_on": ("게시",),
    "cite_off": ("게시",),
}
ACTION_KO = {"hide": "숨김 처리", "keep": "게시 유지", "restore": "게시 복원",
             "cite_on": "S2 근거 인용", "cite_off": "S2 근거 인용 해제"}


@router.get("/member-reviews")
def list_member_reviews():
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT r.review_id, r.rating, r.body, r.status, r.cite_s2, r.moderation_note,"
            " r.created_at, m.nickname, o.order_no, oi.name_snap"
            " FROM member_reviews r"
            " JOIN members m USING (member_id)"
            " JOIN order_items oi ON oi.item_id = r.order_item_id"
            " JOIN orders o ON o.order_id = oi.order_id"
            " ORDER BY r.created_at DESC, r.review_id DESC")).mappings().all()
    return {"items": [{
        "id": r["review_id"], "cust": r["nickname"], "order": r["order_no"],
        "item": r["name_snap"], "rating": r["rating"], "at": r["created_at"].isoformat(),
        "state": r["status"], "cite": r["cite_s2"], "body": r["body"],
        "note": r["moderation_note"],
    } for r in rows]}


class ModerateBody(BaseModel):
    action: str  # hide | keep | restore | cite_on | cite_off
    note: str | None = None  # 처리 사유(hide·keep 시 moderation_note 갱신)


@router.post("/member-reviews/{review_id}/moderate")
def moderate(review_id: int, body: ModerateBody):
    if body.action not in TRANSITIONS:
        raise HTTPException(400, f"알 수 없는 액션: {body.action}")
    with engine.begin() as conn:
        r = conn.execute(text(
            "SELECT review_id, status, cite_s2, moderation_note FROM member_reviews"
            " WHERE review_id=:i FOR UPDATE"), {"i": review_id}).mappings().first()
        if r is None:
            raise HTTPException(404, "후기가 없습니다")
        if r["status"] not in TRANSITIONS[body.action]:
            raise HTTPException(409, {"error": "invalid_state",
                                      "detail": f"현재 상태 '{r['status']}' — {ACTION_KO[body.action]}는"
                                                f" {'/'.join(TRANSITIONS[body.action])} 상태에서만 가능합니다"})
        before = {"status": r["status"], "cite_s2": r["cite_s2"],
                  "moderation_note": r["moderation_note"]}
        new_status, new_cite, new_note = r["status"], r["cite_s2"], r["moderation_note"]
        if body.action == "hide":
            new_status, new_cite = "숨김", False  # 숨긴 후기는 S2 근거에서 동반 해제
            new_note = body.note or new_note
        elif body.action in ("keep", "restore"):
            new_status = "게시"
            if body.note:
                new_note = body.note
        elif body.action == "cite_on":
            new_cite = True
        elif body.action == "cite_off":
            new_cite = False
        conn.execute(text(
            "UPDATE member_reviews SET status=:s, cite_s2=:c, moderation_note=:n"
            " WHERE review_id=:i"),
            {"s": new_status, "c": new_cite, "n": new_note, "i": review_id})
        log_id = _log(conn, "member_review_moderate", str(review_id),
                      {"review_id": review_id, "action": body.action,
                       "before": before, "after": {"status": new_status, "cite_s2": new_cite}},
                      kind="member_review")
        return {"ok": True, "undo_id": log_id, "state": new_status, "cite": new_cite}


@router.post("/member-reviews/undo/{log_id}")
def undo_moderate(log_id: int):
    with engine.begin() as conn:
        log = conn.execute(text(
            "SELECT action, detail FROM admin_operator_activity_logs WHERE log_id=:i"),
            {"i": log_id}).mappings().first()
        if log is None or log["action"] != "member_review_moderate":
            raise HTTPException(404, "되돌릴 처리 기록이 없습니다")
        if conn.execute(text(
                "SELECT 1 FROM admin_operator_activity_logs"
                " WHERE action='member_review_undo' AND (detail->>'ref_log_id')::int=:i LIMIT 1"),
                {"i": log_id}).first():
            raise HTTPException(409, "이미 되돌린 처리입니다")
        d = log["detail"]
        r = conn.execute(text(
            "SELECT status, cite_s2 FROM member_reviews WHERE review_id=:i FOR UPDATE"),
            {"i": d["review_id"]}).mappings().first()
        if r is None or r["status"] != d["after"]["status"] or r["cite_s2"] != d["after"]["cite_s2"]:
            raise HTTPException(409, "처리 이후 상태가 변경되어 되돌릴 수 없습니다")
        b = d["before"]
        conn.execute(text(
            "UPDATE member_reviews SET status=:s, cite_s2=:c, moderation_note=:n"
            " WHERE review_id=:i"),
            {"s": b["status"], "c": b["cite_s2"], "n": b["moderation_note"], "i": d["review_id"]})
        _log(conn, "member_review_undo", str(log_id),
             {"ref_log_id": log_id, "review_id": d["review_id"]}, kind="member_review")
        return {"ok": True, "state": b["status"], "cite": b["cite_s2"]}
