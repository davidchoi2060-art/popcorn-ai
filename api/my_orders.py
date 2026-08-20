"""MY-020 고객 주문 내역·환불 접수 — 고객 축의 원장 열람 + 환불 원장 첫 기록.

인증: email 쿼리 파라미터 = mock 인증(localStorage popcorn-member 기반, 로컬 데모 한정 수용).
실 인증(세션·토큰)은 별도 슬라이스. 미가입 이메일은 items:[] 정직 빈 목록.

환불 접수(POST /refunds): 접수만 기록(refunds 행 = 원장) — 주문 상태는 불변.
고객 접수 즉시 관리자 주문·배송 화면의 상태 전이가 잠긴다(admin_orders._guard_refund 409).
접수 가능 상태: 결제완료(주문 취소)·조립중(주문 취소)·배송중(환불)·완료(반품·교환, 활성 환불 없을 때).
이관(ADM-CLM-010): reason_detail 저장 컬럼·부분 환불·접수 철회(현재 불가 — 접수 주문은 활성 잠금).

고객 쓰기 잠금(2026-08-20, 지인·테스터 오픈 준비): 환불 접수는 `customer_write_lock`
스위치가 켜져 있으면 403으로 거부된다 — 근거·켜는 법은 그 모듈 docstring 참조.
기본은 꺼짐(지금 동작 그대로). ⚠ `ops_snapshot`의 `refund`(own/mall)와는 다른 축이다 —
그건 접수된 건을 누가 처리하는지를 정할 뿐 접수 자체를 막지 않는다(아래 create_refund
실측 그대로).
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from .timeutil import iso
from .admin_orders import STEP, _item_label, refund_label
from .customer_auth import require_member
from .customer_write_lock import write_locked, REASON as WRITE_LOCK_REASON
from .db import engine

router = APIRouter(prefix="/api/my")

REASONS = ("단순 변심", "초기 불량", "오배송·구성 오류", "기타")
ACTIVE_REFUND = ("접수", "검토", "수거·처리")


@router.get("/orders")
def my_orders():
    # 회원 경계는 **세션**이 정한다(슬라이스 38). 요청이 주장하는 이메일은 더 이상 믿지 않는다.
    member_id = require_member()["member_id"]
    with engine.connect() as conn:
        orders = conn.execute(text(
            "SELECT order_id, order_no, channel, status, total_amount, ops_snapshot, created_at"
            " FROM orders WHERE member_id=:m ORDER BY created_at DESC, order_id DESC"),
            {"m": member_id}).mappings().all()
        ids = [o["order_id"] for o in orders]
        items_by, pays, ships, refunds = {}, {}, {}, {}
        if ids:
            for r in conn.execute(text(
                    "SELECT order_id, item_kind, name_snap, price_snap, qty, spec_snap"
                    " FROM order_items WHERE order_id = ANY(:ids) ORDER BY item_id"), {"ids": ids}).mappings():
                items_by.setdefault(r["order_id"], []).append(
                    [_item_label(r["item_kind"], r["spec_snap"]), r["name_snap"],
                     r["price_snap"] * r["qty"]])
            pays = {r["order_id"]: r for r in conn.execute(text(
                "SELECT DISTINCT ON (order_id) order_id, pay_mode, method, status, paid_at"
                " FROM payments WHERE order_id = ANY(:ids) ORDER BY order_id, payment_id DESC"),
                {"ids": ids}).mappings()}
            ships = {r["order_id"]: r for r in conn.execute(text(
                "SELECT DISTINCT ON (order_id) order_id, carrier, tracking_no FROM shipments"
                " WHERE order_id = ANY(:ids) ORDER BY order_id, shipment_id DESC"),
                {"ids": ids}).mappings()}
            refunds = {r["order_id"]: r for r in conn.execute(text(
                "SELECT DISTINCT ON (order_id) order_id, refund_id, refund_mode, reason_type, status"
                " FROM refunds WHERE order_id = ANY(:ids) ORDER BY order_id, refund_id DESC"),
                {"ids": ids}).mappings()}

    out = []
    for o in orders:
        oid = o["order_id"]
        p, s, rf = pays.get(oid), ships.get(oid), refunds.get(oid)
        pay = None
        if p:
            suffix = " (자체 결제)" if p["pay_mode"] == "own" else " (인계)"
            pay = {"method": p["method"] + suffix, "state": p["status"],
                   "at": iso(p["paid_at"]) if p["paid_at"] else None}
        out.append({
            "no": o["order_no"], "created_at": iso(o["created_at"]),
            "channel": o["channel"], "status": o["status"],
            "step": STEP.get(o["status"], 1), "total": o["total_amount"],
            "items": items_by.get(oid, []),
            "pay": pay,
            "ship": {"carrier": s["carrier"], "no": s["tracking_no"]} if s else None,
            "refund_mode": (o["ops_snapshot"] or {}).get("refund", "mall"),  # 접수 전 안내문(주문 시점 스냅샷)
            "refund": {"no": refund_label(rf["refund_id"]), "reason": rf["reason_type"],
                       "status": rf["status"], "mode": rf["refund_mode"]} if rf else None,
        })
    return {"items": out}


class RefundBody(BaseModel):
    order_no: str
    reason_type: str


@router.post("/refunds")
def create_refund(body: RefundBody):
    me = require_member()
    if write_locked():
        # my-orders.html 은 res.j.detail 을 객체로 보고 .detail/.error 를 꺼낸다
        # (409 invalid_state·refund_active 와 같은 모양) — 문자열만 주면
        # "잠시 후 다시 시도해 주세요"로 뭉개져 사유가 안 보인다.
        raise HTTPException(403, {"error": "write_locked", "detail": WRITE_LOCK_REASON})
    if body.reason_type not in REASONS:
        raise HTTPException(400, f"알 수 없는 사유: {body.reason_type}")
    with engine.begin() as conn:
        o = conn.execute(text(
            "SELECT o.order_id, o.status, o.total_amount, o.ops_snapshot, o.member_id"
            " FROM orders o WHERE o.order_no=:n FOR UPDATE OF o"),
            {"n": body.order_no}).mappings().first()
        if o is None:
            raise HTTPException(404, "주문이 없습니다")
        if o["member_id"] != me["member_id"]:
            raise HTTPException(403, "본인 주문만 접수할 수 있습니다")
        if o["status"] in ("접수", "취소"):
            raise HTTPException(409, {"error": "invalid_state",
                                      "detail": f"'{o['status']}' 상태의 주문은 접수할 수 없습니다"})
        if conn.execute(text(
                "SELECT 1 FROM refunds WHERE order_id=:o AND status = ANY(:st) LIMIT 1"),
                {"o": o["order_id"], "st": list(ACTIVE_REFUND)}).first():
            raise HTTPException(409, {"error": "refund_active",
                                      "detail": "이미 접수된 건이 진행 중입니다"})
        mode = (o["ops_snapshot"] or {}).get("refund", "mall")
        rid = conn.execute(text(
            "INSERT INTO refunds (order_id, refund_mode, reason_type, amount, status)"
            " VALUES (:o, :m, :r, :a, '접수') RETURNING refund_id"),
            {"o": o["order_id"], "m": mode, "r": body.reason_type,
             "a": o["total_amount"]}).scalar()
    return {"refund_no": refund_label(rid), "status": "접수", "mode": mode}
