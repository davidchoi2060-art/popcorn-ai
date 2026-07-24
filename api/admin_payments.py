"""ADM-PAY-010 결제·정산 — T9 일 정산 마감 성문화 (settlements 첫 쓰기).

T9 정산 규칙:
  대상    : pay_mode='own' ∧ status∈('승인','환불') 화이트리스트(취소·대기 = 돈 미이동 제외),
            date(paid_at) UTC 일자로 묶음. mall은 정산 대상 아님(집계 분리 표시만).
  수수료  : rate = pricing_settings.card_fee_rate 최신 행(Decimal 유지 — price_import의
            _settings는 float 캐스팅이라 원 단위 정산에서 ±1원 왜곡, 재사용 금지).
            fee = |amount|×rate 원 단위 half-up 후 부호 복원(환불 음수 = 수수료 환급).
            개별(settlements.fee_amount) 계산 → batch.fee = Σ개별 — 합계 불변식 보장(안분 금지).
  마감    : settlement_batches('마감'·closed_by·closed_at) 1행 + 결제별 settlements N행,
            settle_mode = 결제 pay_mode 승계("정산은 결제를 따라간다" — ship_mode 전례).
            '대기'는 저장 없는 파생 상태(batch 부재 일자) — batch를 '대기'로 선생성하지 않는다
            (status 어휘 '대기'는 v1 미사용). settle_date UNIQUE + ON CONFLICT 무반환 409로
            이중 마감 경합 원자화.
  유입    : 마감 후 동일 일자에 유입된 정산 대상 결제는 late(건수·금액) 정직 표기만 —
            재정산·보정 배치는 v2 이관.
  undo    : 허용(refund complete류 비가역 아님 — 부수효과가 내부 정산 원장뿐, 재고·주문·고객
            무영향). 생성분 삭제(shipments 전례), 수치는 활동 로그 detail 보존.
            마감 후 유입은 undo 차단 사유 아님(복귀한 대기 행에 자연 합류).
타임존 v1: DB UTC — 그룹·today·라벨 전부 UTC 일자 축(KST 정산일 경계는 이관).
이관 유지: 재정산·보정 배치, KST 경계, PG 실대사, kind 어휘 정리(ADM-LOG).
"""
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from .admin_orders import OPERATOR_ID, _log
from .db import engine

router = APIRouter(prefix="/api/admin")

TARGET = "p.pay_mode='own' AND p.status IN ('승인','환불')"


def _fee_won(amount: int, rate: Decimal) -> int:
    """원 단위 half-up, 절대값 반올림 후 부호 복원. round()는 은행가 반올림이라 금지."""
    sign = -1 if amount < 0 else 1
    return sign * int(Decimal(abs(amount)) * rate + Decimal("0.5"))


def _rate(conn) -> Decimal:
    return conn.execute(text(
        "SELECT card_fee_rate FROM pricing_settings"
        " ORDER BY effective_from DESC LIMIT 1")).scalar_one()


@router.get("/payments")
def list_payments():
    with engine.connect() as conn:
        rate = _rate(conn)
        today = conn.execute(text("SELECT CURRENT_DATE")).scalar_one()
        pays = conn.execute(text(
            "SELECT p.payment_id, o.order_no, p.pay_mode, p.method, p.pg_ref,"
            " p.amount, p.status, p.paid_at"
            " FROM payments p JOIN orders o USING (order_id)"
            " ORDER BY p.paid_at DESC NULLS LAST, p.payment_id DESC")).mappings().all()
        batches = conn.execute(text(
            "SELECT batch_id, settle_date, gross, fee, net, status, closed_at"
            " FROM settlement_batches ORDER BY settle_date DESC")).mappings().all()
        # 정산 대상 결제 일자별 원본(대기 파생 + late 판정 공용) — settlements 소속 여부 포함
        rows = conn.execute(text(
            "SELECT p.payment_id, p.amount, p.status, date(p.paid_at) AS d,"
            " s.settlement_id IS NOT NULL AS settled"
            " FROM payments p LEFT JOIN settlements s USING (payment_id)"
            f" WHERE {TARGET} AND p.paid_at IS NOT NULL")).mappings().all()

    by_day: dict = {}
    for r in rows:
        by_day.setdefault(r["d"], []).append(r)
    closed_days = {b["settle_date"] for b in batches}

    settles = []
    for b in batches:
        late = [r for r in by_day.get(b["settle_date"], []) if not r["settled"]]
        settles.append({
            "date": b["settle_date"].isoformat(), "state": b["status"],
            "gross": b["gross"], "fee": b["fee"], "net": b["net"],
            "n": len(by_day.get(b["settle_date"], [])) - len(late),
            "refund_n": sum(1 for r in by_day.get(b["settle_date"], [])
                            if r["settled"] and r["status"] == "환불"),
            "closed_at": b["closed_at"].isoformat() if b["closed_at"] else None,
            "late": {"n": len(late), "gross": sum(r["amount"] for r in late)} if late else None,
        })
    for d, drows in by_day.items():
        if d in closed_days:
            continue
        fees = [_fee_won(r["amount"], rate) for r in drows]  # 잠정 — 개별→합산(마감과 동일 규칙)
        gross = sum(r["amount"] for r in drows)
        settles.append({
            "date": d.isoformat(), "state": "대기",
            "gross": gross, "fee": sum(fees), "net": gross - sum(fees),
            "n": len(drows), "refund_n": sum(1 for r in drows if r["status"] == "환불"),
            "closed_at": None, "late": None,
        })
    settles.sort(key=lambda s: s["date"], reverse=True)

    return {
        "fee_rate": float(rate), "today": today.isoformat(),
        "payments": [{
            "order_no": p["order_no"], "mode": p["pay_mode"], "method": p["method"],
            "pg_ref": p["pg_ref"], "amount": p["amount"], "status": p["status"],
            "at": p["paid_at"].isoformat() if p["paid_at"] else None,
        } for p in pays],
        "settles": settles,
    }


@router.post("/settlements/{settle_date}/close")
def close_settlement(settle_date: str):
    with engine.begin() as conn:
        rate = _rate(conn)
        targets = conn.execute(text(
            "SELECT p.payment_id, p.pay_mode, p.amount FROM payments p"
            f" WHERE {TARGET} AND date(p.paid_at)=:d"
            " ORDER BY p.payment_id FOR UPDATE"), {"d": settle_date}).mappings().all()
        if not targets:
            raise HTTPException(400, "해당 일자에 정산 대상 결제가 없습니다")
        items = [{"payment_id": t["payment_id"], "mode": t["pay_mode"],
                  "amount": t["amount"], "fee": _fee_won(t["amount"], rate)}
                 for t in targets]
        gross = sum(i["amount"] for i in items)
        fee = sum(i["fee"] for i in items)  # batch = Σ개별(불변식)
        b = conn.execute(text(
            "INSERT INTO settlement_batches (settle_date, gross, fee, net, status, closed_by, closed_at)"
            " VALUES (:d, :g, :f, :n, '마감', :op, now())"
            " ON CONFLICT (settle_date) DO NOTHING RETURNING batch_id, closed_at"),
            {"d": settle_date, "g": gross, "f": fee, "n": gross - fee,
             "op": OPERATOR_ID}).mappings().first()
        if b is None:
            raise HTTPException(409, {"error": "already_closed",
                                      "detail": f"{settle_date}은 이미 마감된 일자입니다"})
        for i in items:
            conn.execute(text(
                "INSERT INTO settlements (payment_id, batch_id, settle_mode, fee_amount, net_amount, settled_at)"
                " VALUES (:p, :b, :m, :f, :n, now())"),
                {"p": i["payment_id"], "b": b["batch_id"], "m": i["mode"],
                 "f": i["fee"], "n": i["amount"] - i["fee"]})
        log_id = _log(conn, "settlement_close", settle_date,
                      {"batch_id": b["batch_id"], "settle_date": settle_date,
                       "gross": gross, "fee": fee, "net": gross - fee,
                       "fee_rate": float(rate),
                       "payment_ids": [i["payment_id"] for i in items]},
                      kind="settlement")
        return {"ok": True, "undo_id": log_id,
                "batch": {"date": settle_date, "gross": gross, "fee": fee,
                          "net": gross - fee, "n": len(items),
                          "closed_at": b["closed_at"].isoformat()}}


@router.post("/settlements/undo/{log_id}")
def undo_settlement(log_id: int):
    with engine.begin() as conn:
        log = conn.execute(text(
            "SELECT action, detail FROM admin_operator_activity_logs WHERE log_id=:i"),
            {"i": log_id}).mappings().first()
        if log is None or log["action"] != "settlement_close":
            raise HTTPException(404, "되돌릴 정산 마감 기록이 없습니다")
        if conn.execute(text(
                "SELECT 1 FROM admin_operator_activity_logs"
                " WHERE action='settlement_close_undo' AND (detail->>'ref_log_id')::int=:i"
                " LIMIT 1"), {"i": log_id}).first():
            raise HTTPException(409, "이미 되돌린 마감입니다")
        d = log["detail"]
        b = conn.execute(text(
            "SELECT batch_id, gross, fee, net, status FROM settlement_batches"
            " WHERE batch_id=:b FOR UPDATE"), {"b": d["batch_id"]}).mappings().first()
        if b is None or b["status"] != "마감" or b["gross"] != d["gross"] \
                or b["fee"] != d["fee"] or b["net"] != d["net"]:
            raise HTTPException(409, "마감 이후 정산 원장이 변경되어 되돌릴 수 없습니다")
        conn.execute(text("DELETE FROM settlements WHERE batch_id=:b"), {"b": b["batch_id"]})
        conn.execute(text("DELETE FROM settlement_batches WHERE batch_id=:b"), {"b": b["batch_id"]})
        _log(conn, "settlement_close_undo", str(log_id),
             {"ref_log_id": log_id, "settle_date": d["settle_date"]}, kind="settlement")
        return {"ok": True, "date": d["settle_date"]}
