"""ADM-ORD-020 관리자 주문 관리 — 목록 파생 조립 + 상태 전이(성문화 v1) + undo.

전이 규칙 v1 (이 슬라이스에서 성문화 — 이전엔 미문서화):
  (T7 기구현) NULL→접수→결제완료(고객/PG)
  assemble : 결제완료 → 조립중                                  (운영자)
  ship     : 조립중  → 배송중 + shipments 생성                  (운영자)
             ship_mode = 주문 ops_snapshot.ship (own 고정 아님 — 감사 정합)
  done     : 배송중  → 완료  + shipments 완료·delivered_at      (운영자)
  가드: 기대 상태 불일치 409 · 활성 환불(접수/검토/수거·처리) 존재 시 전 액션 409.
  ERD '출고' 상태는 목업이 건너뛰어 v1 미사용 — ADM-SHIP-010 슬라이스에서 세분화 여지.
  이 전이 API는 단일 공용 — SHIP 화면도 추후 재사용(원장 단일, 화면은 뷰).

undo = 직전 1단계 역행. order_events는 불변 원장 — 삭제 없이 역방향 이벤트 추가
(actor '운영자(되돌림)'). shipments는 운영 상태 테이블 — ship undo는 생성분 삭제
(송장은 활동 로그 detail에 보존), done undo는 배송중·delivered_at NULL 복원.

표시 파생(전용): refund 라벨 "RF-{1023+refund_id}"는 표시 전용 규칙(refund_no 컬럼
성문화 여부는 ADM-CLM-010 슬라이스에서 재결정).
"""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from .admin_products import PART_TYPE_LABELS
from .db import engine

router = APIRouter(prefix="/api/admin")

OPERATOR_ID = 1
LABELS = {**PART_TYPE_LABELS, "COOLER": "CPU쿨러"}
STEP = {"접수": 1, "결제완료": 1, "조립중": 2, "출고": 3, "배송중": 3, "완료": 4, "취소": 0}
ACTIVE_REFUND = ("접수", "검토", "수거·처리")
MODE_KO = {"own": "자체", "mall": "쇼핑몰"}
TRANSITIONS = {"assemble": ("결제완료", "조립중"), "ship": ("조립중", "배송중"), "done": ("배송중", "완료")}


def _ops_text(ops: dict) -> str:
    keys = ["pay", "settle", "ship", "refund"]
    if all(ops.get(k) == "mall" for k in keys):
        return "전 항목 쇼핑몰 인계"
    ko = lambda k: MODE_KO.get(ops.get(k), ops.get(k, "?"))
    return (f"결제 {ko('pay')} · 정산 {ko('settle')} · 배송 {ko('ship')}"
            f" · 환불 {ko('refund')} (주문 시점 스냅샷)")


def _item_label(kind: str, spec) -> str:
    if kind == "assembly_service":
        return "조립·검수"
    pt = (spec or {}).get("part_type")
    if kind == "peripheral":
        return (LABELS.get(pt, pt) if pt else "주변기기") + "(함께 구성)"
    return LABELS.get(pt, pt) if pt else "구성"


def _log(conn, action: str, target_id: str, detail: dict) -> int:
    return conn.execute(text(
        "INSERT INTO admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)"
        " VALUES (:op, :a, 'order', :t, CAST(:d AS JSONB)) RETURNING log_id"),
        {"op": OPERATOR_ID, "a": action, "t": target_id, "d": json.dumps(detail)}).scalar()


@router.get("/orders")
def list_orders():
    with engine.connect() as conn:
        orders = conn.execute(text(
            "SELECT o.order_id, o.order_no, o.channel, o.status, o.total_amount,"
            " o.ops_snapshot, o.created_at, COALESCE(m.nickname, '비회원') AS cust"
            " FROM orders o LEFT JOIN members m USING (member_id)"
            " ORDER BY o.created_at DESC, o.order_id DESC")).mappings().all()
        items_by = {}
        for r in conn.execute(text(
                "SELECT order_id, item_kind, name_snap, price_snap, qty, spec_snap"
                " FROM order_items ORDER BY item_id")).mappings():
            items_by.setdefault(r["order_id"], []).append(
                [_item_label(r["item_kind"], r["spec_snap"]), r["name_snap"],
                 r["price_snap"] * r["qty"]])
        pays = {r["order_id"]: r for r in conn.execute(text(
            "SELECT DISTINCT ON (order_id) order_id, pay_mode, method, pg_ref FROM payments"
            " ORDER BY order_id, payment_id DESC")).mappings()}
        ships = {r["order_id"]: r for r in conn.execute(text(
            "SELECT DISTINCT ON (order_id) order_id, carrier, tracking_no, status FROM shipments"
            " ORDER BY order_id, shipment_id DESC")).mappings()}
        holds = {r["order_id"]: r["n"] for r in conn.execute(text(
            "SELECT order_id, COUNT(*) AS n FROM stock_reservations"
            " WHERE status='converted' GROUP BY order_id")).mappings()}
        refunds = {r["order_id"]: r for r in conn.execute(text(
            "SELECT DISTINCT ON (order_id) order_id, refund_id, reason_type, status FROM refunds"
            " WHERE status = ANY(:st) ORDER BY order_id, refund_id DESC"),
            {"st": list(ACTIVE_REFUND)}).mappings()}

    out = []
    for o in orders:
        oid, ops = o["order_id"], o["ops_snapshot"]
        own = o["channel"] == "own"
        p = pays.get(oid)
        pay = ("결제 대기" if p is None
               else f"{p['method']} · PG 승인 {p['pg_ref']}" if p["pay_mode"] == "own"
               else "쇼핑몰 결제 (인계)")
        s = ships.get(oid)
        if s:
            ship = f"{s['carrier']} {s['tracking_no']}" + (" · 배송 완료" if s["status"] == "완료" else "")
        elif o["status"] == "완료":
            ship = "배송 완료"
        else:
            ship = None
        n = holds.get(oid, 0)
        hold = (f"재고 예약(hold) {n}건 → 결제 승인 시 확정 배정 전환 완료" if own and n
                else "확정 배정 완료" if own
                else "—(인계 주문 · 재고 수량은 API 유입으로 정합)")
        rf = refunds.get(oid)
        out.append({
            "order_id": oid, "no": o["order_no"], "created_at": o["created_at"].isoformat(),
            "cust": o["cust"], "ch": o["channel"], "status": o["status"],
            "step": STEP.get(o["status"], 1), "total": o["total_amount"],
            "ops": _ops_text(ops), "pay": pay, "ship": ship, "hold": hold,
            "items": items_by.get(oid, []),
            "refund": f"RF-{1023 + rf['refund_id']} 환불 {rf['status']} ({rf['reason_type']})" if rf else None,
        })
    return {"items": out}


class AdvanceBody(BaseModel):
    action: str  # assemble | ship | done


def _guard_refund(conn, order_id: int):
    if conn.execute(text(
            "SELECT 1 FROM refunds WHERE order_id=:o AND status = ANY(:st) LIMIT 1"),
            {"o": order_id, "st": list(ACTIVE_REFUND)}).first():
        raise HTTPException(409, {"error": "refund_active",
                                  "detail": "환불·클레임 진행 중 — 환불·클레임 화면에서 처리하세요"})


@router.post("/orders/{order_no}/advance")
def advance(order_no: str, body: AdvanceBody):
    if body.action not in TRANSITIONS:
        raise HTTPException(400, f"알 수 없는 액션: {body.action}")
    expect, target = TRANSITIONS[body.action]
    with engine.begin() as conn:
        o = conn.execute(text(
            "SELECT order_id, status, ops_snapshot FROM orders WHERE order_no=:n FOR UPDATE"),
            {"n": order_no}).mappings().first()
        if o is None:
            raise HTTPException(404, "주문이 없습니다")
        _guard_refund(conn, o["order_id"])
        if o["status"] != expect:
            raise HTTPException(409, {"error": "invalid_transition",
                                      "detail": f"현재 상태 '{o['status']}' — '{expect}'에서만 가능한 처리입니다"})
        before = {"status": o["status"]}
        ship_text = None
        if body.action == "ship":
            tracking = f"6483-{o['order_id']:04d}-{(o['order_id'] * 7919) % 10000:04d}"
            sid = conn.execute(text(
                "INSERT INTO shipments (order_id, ship_mode, carrier, tracking_no, status, shipped_at)"
                " VALUES (:o, :m, 'CJ대한통운', :t, '배송중', now()) RETURNING shipment_id"),
                {"o": o["order_id"], "m": (o["ops_snapshot"] or {}).get("ship", "own"),
                 "t": tracking}).scalar()
            before["shipment_id"] = sid
            before["tracking"] = tracking
            ship_text = f"CJ대한통운 {tracking}"
        elif body.action == "done":
            upd = conn.execute(text(
                "UPDATE shipments SET status='완료', delivered_at=now() WHERE order_id=:o"
                " RETURNING shipment_id, carrier, tracking_no"),
                {"o": o["order_id"]}).mappings().first()
            before["shipment_updated"] = bool(upd)
            ship_text = f"{upd['carrier']} {upd['tracking_no']} · 배송 완료" if upd else "배송 완료"
        conn.execute(text("UPDATE orders SET status=:s WHERE order_id=:o"),
                     {"s": target, "o": o["order_id"]})
        conn.execute(text(
            "INSERT INTO order_events (order_id, from_state, to_state, actor)"
            " VALUES (:o, :f, :t, '운영자')"), {"o": o["order_id"], "f": expect, "t": target})
        log_id = _log(conn, "order_advance", order_no,
                      {"order_id": o["order_id"], "action": body.action,
                       "from": expect, "to": target, "before": before})
        return {"ok": True, "undo_id": log_id, "status": target,
                "step": STEP[target], "ship": ship_text}


@router.post("/orders/undo/{log_id}")
def undo(log_id: int):
    with engine.begin() as conn:
        log = conn.execute(text(
            "SELECT action, detail FROM admin_operator_activity_logs WHERE log_id=:i"),
            {"i": log_id}).mappings().first()
        if log is None or log["action"] != "order_advance":
            raise HTTPException(404, "되돌릴 처리 기록이 없습니다")
        d = log["detail"]
        o = conn.execute(text(
            "SELECT order_id, status FROM orders WHERE order_id=:o FOR UPDATE"),
            {"o": d["order_id"]}).mappings().one()
        if o["status"] != d["to"]:
            raise HTTPException(409, "이미 되돌렸거나 이후 상태가 변경됐습니다")
        _guard_refund(conn, o["order_id"])
        ship_text = None
        if d["action"] == "ship":
            conn.execute(text("DELETE FROM shipments WHERE shipment_id=:s"),
                         {"s": d["before"]["shipment_id"]})  # 송장은 이 로그 detail에 보존
        elif d["action"] == "done" and d["before"].get("shipment_updated"):
            s = conn.execute(text(
                "UPDATE shipments SET status='배송중', delivered_at=NULL WHERE order_id=:o"
                " RETURNING carrier, tracking_no"), {"o": o["order_id"]}).mappings().first()
            if s:
                ship_text = f"{s['carrier']} {s['tracking_no']}"
        conn.execute(text("UPDATE orders SET status=:s WHERE order_id=:o"),
                     {"s": d["from"], "o": o["order_id"]})
        # order_events = 불변 원장 — 삭제 대신 역방향 이벤트
        conn.execute(text(
            "INSERT INTO order_events (order_id, from_state, to_state, actor)"
            " VALUES (:o, :f, :t, '운영자(되돌림)')"),
            {"o": o["order_id"], "f": d["to"], "t": d["from"]})
        _log(conn, "order_advance_undo", str(log_id),
             {"ref_log_id": log_id, "order_id": o["order_id"]})
        return {"ok": True, "status": d["from"], "step": STEP[d["from"]], "ship": ship_text}
