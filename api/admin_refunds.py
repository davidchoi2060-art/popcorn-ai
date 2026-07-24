"""ADM-CLM-010 환불·클레임 처리 — T8 환불 전이 성문화 (이 슬라이스에서 첫 성문화).

T8 전이 규칙:
  review   : 접수 → 검토                                   (운영자, undo 가능)
  approve  : 검토 → 수거·처리                              (운영자, undo 가능)
             own = "수거 접수·PG 환불 예약" / mall = "쇼핑몰 인계 처리 기록" — 문구 분기, 전이 동일
  complete : 수거·처리 → 완료                              (운영자, **비가역** — undo_id null)
             부수효과(한 트랜잭션): ① payments 환불 행 추가 — 원 결제 레일 승계
             (pay_mode·method 복사, amount = -refund.amount 음수 표기, pg_ref own={원참조}-R / mall=NULL
              — refund_mode는 클레임 절차 모드지 자금 레일이 아님)
             ② order_items 실물 라인 전부 stock_movements('return', +qty) + stock_qty 복귀
             ③ 주문 결제완료·조립중·배송중 → '취소' + order_events (배송중 유지안은
                환불 완료 후 done advance 루프홀이라 기각) / 완료(반품·교환)만 유지
  reject   : 접수·검토 → 반려                              (운영자, undo 가능 — 단 동일 주문
             타 활성 환불 존재 시 undo 409. 반려·완료는 ACTIVE_REFUND 제외 → 주문 전이 잠금 해제)

kind 파생: 주문 상태 기준 — 결제완료·조립중·'취소'→'주문 취소' / 완료→'반품·교환' / else '환불'
('취소' 분기는 완료 처리 후 라벨 표류 방지 — MY-020 kindOf와 동일 규칙).
이관 유지: refund_no·reason_detail·completed_at 컬럼화, 부분 환불, 접수 철회, settlements 반영.
"""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from .admin_orders import ACTIVE_REFUND, OPERATOR_ID, _log, refund_label
from .db import engine

router = APIRouter(prefix="/api/admin")

STATE_IDX = {"접수": 0, "검토": 1, "수거·처리": 2, "완료": 3, "반려": -1}
TRANSITIONS = {"review": (("접수",), "검토"), "approve": (("검토",), "수거·처리"),
               "complete": (("수거·처리",), "완료"), "reject": (("접수", "검토"), "반려")}
CANCELABLE = ("결제완료", "조립중", "배송중")


def _kind(order_status: str) -> str:
    if order_status in ("결제완료", "조립중", "취소"):
        return "주문 취소"
    if order_status == "완료":
        return "반품·교환"
    return "환불"


@router.get("/refunds")
def list_refunds():
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT r.refund_id, r.refund_mode, r.reason_type, r.amount, r.status, r.created_at,"
            " o.order_no, o.status AS order_status, COALESCE(m.nickname, '비회원') AS cust"
            " FROM refunds r JOIN orders o USING (order_id)"
            " LEFT JOIN members m USING (member_id)")).mappings().all()
    items = [{
        "refund_id": r["refund_id"], "no": refund_label(r["refund_id"]),
        "order": r["order_no"], "cust": r["cust"], "kind": _kind(r["order_status"]),
        "reason": r["reason_type"], "mode": r["refund_mode"],
        "state": STATE_IDX.get(r["status"], 0), "status": r["status"],
        "amount": r["amount"], "at": r["created_at"].isoformat(),
        "note": None,  # reason_detail 저장처 없음(이관) — 화면 '—' 정직
        "order_status": r["order_status"],
    } for r in rows]
    active = {"접수", "검토", "수거·처리"}
    items.sort(key=lambda x: x["at"], reverse=True)          # 최신 우선
    items.sort(key=lambda x: 0 if x["status"] in active else 1)  # 활성 우선(안정 정렬)
    return {"items": items}


class AdvanceBody(BaseModel):
    action: str  # review | approve | complete | reject


@router.post("/refunds/{refund_id}/advance")
def advance(refund_id: int, body: AdvanceBody):
    if body.action not in TRANSITIONS:
        raise HTTPException(400, f"알 수 없는 액션: {body.action}")
    expects, target = TRANSITIONS[body.action]
    with engine.begin() as conn:
        r = conn.execute(text(
            "SELECT r.refund_id, r.order_id, r.refund_mode, r.amount, r.status"
            " FROM refunds r WHERE r.refund_id=:i FOR UPDATE"), {"i": refund_id}).mappings().first()
        if r is None:
            raise HTTPException(404, "환불 건이 없습니다")
        if r["status"] not in expects:
            raise HTTPException(409, {"error": "invalid_transition",
                                      "detail": f"현재 상태 '{r['status']}' — {'/'.join(expects)}에서만 가능한 처리입니다"})
        returned, refund_row = 0, None
        if body.action == "complete":
            o = conn.execute(text(
                "SELECT order_id, order_no, status FROM orders WHERE order_id=:o FOR UPDATE"),
                {"o": r["order_id"]}).mappings().one()
            # ① 환불 행 — 원 결제 레일 승계
            p = conn.execute(text(
                "SELECT pay_mode, method, pg_ref FROM payments WHERE order_id=:o AND status='승인'"
                " ORDER BY payment_id DESC LIMIT 1"), {"o": o["order_id"]}).mappings().first()
            if p:
                pg_ref = f"{p['pg_ref']}-R" if (p["pay_mode"] == "own" and p["pg_ref"]) else None
                conn.execute(text(
                    "INSERT INTO payments (order_id, pay_mode, method, pg_ref, amount, status, paid_at)"
                    " VALUES (:o, :m, :me, :ref, :a, '환불', now())"),
                    {"o": o["order_id"], "m": p["pay_mode"], "me": p["method"],
                     "ref": pg_ref, "a": -r["amount"]})
                refund_row = {"method": p["method"], "pg_ref": pg_ref, "amount": -r["amount"]}
            # ② 재고 복귀 — 실물 라인 전부
            for it in conn.execute(text(
                    "SELECT product_code, qty FROM order_items"
                    " WHERE order_id=:o AND product_code IS NOT NULL"), {"o": o["order_id"]}).all():
                conn.execute(text(
                    "INSERT INTO stock_movements (product_code, movement_type, qty_delta, ref_kind, ref_id)"
                    " VALUES (:pc, 'return', :q, 'refund', :r)"),
                    {"pc": it[0], "q": it[1], "r": refund_id})
                conn.execute(text(
                    "UPDATE products SET stock_qty = stock_qty + :q, updated_at=now()"
                    " WHERE product_code=:pc"), {"q": it[1], "pc": it[0]})
                returned += 1
            # ③ 주문 상태 분기
            if o["status"] in CANCELABLE:
                conn.execute(text("UPDATE orders SET status='취소' WHERE order_id=:o"),
                             {"o": o["order_id"]})
                conn.execute(text(
                    "INSERT INTO order_events (order_id, from_state, to_state, actor)"
                    " VALUES (:o, :f, '취소', '운영자')"), {"o": o["order_id"], "f": o["status"]})
        conn.execute(text("UPDATE refunds SET status=:s WHERE refund_id=:i"),
                     {"s": target, "i": refund_id})
        log_id = _log(conn, "refund_advance", refund_label(refund_id),
                      {"refund_id": refund_id, "action": body.action,
                       "from": r["status"], "to": target}, kind="refund")
        return {"status": target, "state": STATE_IDX[target],
                "undo_id": None if body.action == "complete" else log_id,  # complete = 비가역
                "returned": returned, "refund_row": refund_row}


@router.post("/refunds/undo/{log_id}")
def undo(log_id: int):
    with engine.begin() as conn:
        log = conn.execute(text(
            "SELECT action, detail FROM admin_operator_activity_logs WHERE log_id=:i"),
            {"i": log_id}).mappings().first()
        if log is None or log["action"] != "refund_advance":
            raise HTTPException(404, "되돌릴 처리 기록이 없습니다")
        d = log["detail"]
        if d["action"] == "complete":
            raise HTTPException(409, "완료 처리는 되돌릴 수 없습니다(원장 확산 — 비가역)")
        r = conn.execute(text(
            "SELECT refund_id, order_id, status FROM refunds WHERE refund_id=:i FOR UPDATE"),
            {"i": d["refund_id"]}).mappings().one()
        if r["status"] != d["to"]:
            raise HTTPException(409, "이미 되돌렸거나 이후 상태가 변경됐습니다")
        if d["action"] == "reject":
            # reject-undo = 활성 복원 — 동일 주문에 타 활성 환불이 생겼으면 이중 활성 금지
            if conn.execute(text(
                    "SELECT 1 FROM refunds WHERE order_id=:o AND refund_id<>:i"
                    " AND status = ANY(:st) LIMIT 1"),
                    {"o": r["order_id"], "i": r["refund_id"],
                     "st": list(ACTIVE_REFUND)}).first():
                raise HTTPException(409, {"error": "refund_active",
                                          "detail": "같은 주문에 다른 환불이 진행 중이라 되돌릴 수 없습니다"})
        conn.execute(text("UPDATE refunds SET status=:s WHERE refund_id=:i"),
                     {"s": d["from"], "i": r["refund_id"]})
        _log(conn, "refund_advance_undo", str(log_id),
             {"ref_log_id": log_id, "refund_id": r["refund_id"]}, kind="refund")
        return {"status": d["from"], "state": STATE_IDX[d["from"]]}
